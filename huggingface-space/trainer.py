from __future__ import annotations

import json
import os
import shutil
import tempfile
import uuid
from datetime import datetime, timezone
from typing import Any

from arabic_evaluation import held_out_prompt_keys, normalize_text

BASE_MODEL_ID = os.getenv("BASE_MODEL_ID", "Qwen/Qwen3-8B")
MAX_SEQUENCE_LENGTH = 768
MIN_EXAMPLES = 8


def _read_jsonl(path: str) -> list[dict[str, str]]:
    examples: list[dict[str, str]] = []
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            prompt = row.get("prompt")
            response = row.get("response")
            if isinstance(prompt, str) and prompt.strip() and isinstance(response, str) and response.strip():
                examples.append({"prompt": prompt.strip()[:4000], "response": response.strip()[:4000]})
    return examples


def _load_saved_feedback(token: str) -> list[dict[str, str]]:
    repo_id = os.getenv("FEEDBACK_DATASET_ID", "").strip()
    if not repo_id:
        return []

    from huggingface_hub import HfApi, hf_hub_download

    api = HfApi(token=token)
    paths = api.list_repo_files(repo_id=repo_id, repo_type="dataset", token=token)
    feedback_paths = [path for path in paths if path.startswith("feedback/") and path.endswith(".jsonl")]
    examples: list[dict[str, str]] = []
    for path in feedback_paths[-500:]:
        local_path = hf_hub_download(
            repo_id=repo_id,
            repo_type="dataset",
            filename=path,
            token=token,
        )
        examples.extend(_read_jsonl(local_path))
    return examples


class _ResponseOnlyDataset:
    def __init__(self, rows: list[dict[str, Any]]):
        self.rows = rows

    def __len__(self) -> int:
        return len(self.rows)

    def __getitem__(self, index: int) -> dict[str, list[int]]:
        return self.rows[index]


class _ResponseOnlyCollator:
    def __init__(self, pad_token_id: int):
        self.pad_token_id = pad_token_id

    def __call__(self, features: list[dict[str, list[int]]]) -> dict[str, Any]:
        import torch

        max_length = max(len(item["input_ids"]) for item in features)
        batch_size = len(features)
        input_ids = torch.full((batch_size, max_length), self.pad_token_id, dtype=torch.long)
        attention_mask = torch.zeros((batch_size, max_length), dtype=torch.long)
        labels = torch.full((batch_size, max_length), -100, dtype=torch.long)
        for row, item in enumerate(features):
            length = len(item["input_ids"])
            input_ids[row, :length] = torch.tensor(item["input_ids"], dtype=torch.long)
            attention_mask[row, :length] = 1
            labels[row, :length] = torch.tensor(item["labels"], dtype=torch.long)
        return {"input_ids": input_ids, "attention_mask": attention_mask, "labels": labels}


def _tokenized_examples(tokenizer: Any, examples: list[dict[str, str]]) -> list[dict[str, list[int]]]:
    prepared: list[dict[str, list[int]]] = []
    for example in examples:
        user_message = [{"role": "user", "content": example["prompt"]}]
        full_messages = user_message + [{"role": "assistant", "content": example["response"]}]
        try:
            prefix_ids = tokenizer.apply_chat_template(
                user_message,
                tokenize=True,
                add_generation_prompt=True,
                enable_thinking=False,
            )
            full_ids = tokenizer.apply_chat_template(
                full_messages,
                tokenize=True,
                add_generation_prompt=False,
                enable_thinking=False,
            )
        except TypeError:
            prefix_ids = tokenizer.apply_chat_template(
                user_message,
                tokenize=True,
                add_generation_prompt=True,
            )
            full_ids = tokenizer.apply_chat_template(
                full_messages,
                tokenize=True,
                add_generation_prompt=False,
            )
        if not isinstance(prefix_ids, list) or not isinstance(full_ids, list):
            continue
        full_ids = full_ids[:MAX_SEQUENCE_LENGTH]
        response_start = min(len(prefix_ids), len(full_ids))
        if response_start >= len(full_ids):
            continue
        labels = [-100] * response_start + full_ids[response_start:]
        prepared.append({"input_ids": full_ids, "labels": labels})
    return prepared


def train_candidate(uploaded_jsonl: str | None = None) -> str:
    """Train a short LoRA candidate from explicitly curated corrections."""
    write_token = os.getenv("HF_WRITE_TOKEN") or os.getenv("HF_TOKEN")
    candidate_prefix = os.getenv("CANDIDATE_MODEL_REPO_PREFIX", "").strip().rstrip("/")
    if not write_token or not candidate_prefix or "/" not in candidate_prefix:
        raise RuntimeError(
            "أضف HF_WRITE_TOKEN ورابط CANDIDATE_MODEL_REPO_PREFIX بصيغة owner/repo إلى أسرار الـSpace."
        )

    examples = _read_jsonl(uploaded_jsonl) if uploaded_jsonl else _load_saved_feedback(write_token)
    if len(examples) < MIN_EXAMPLES:
        raise RuntimeError(
            f"يلزم {MIN_EXAMPLES} أمثلة عربية مصححة على الأقل؛ المتاح الآن {len(examples)}."
        )
    held_out = held_out_prompt_keys()
    overlap_ids = [
        index
        for index, example in enumerate(examples, start=1)
        if normalize_text(example["prompt"]) in held_out
    ]
    if overlap_ids:
        raise RuntimeError(
            "تتضمن بيانات التدريب أسئلة من مجموعة التقييم المحجوزة؛ احذفها قبل التدريب "
            f"(عدد الصفوف المتداخلة: {len(overlap_ids)})."
        )

    import torch
    from huggingface_hub import HfApi
    from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
    from transformers import (
        AutoModelForCausalLM,
        AutoTokenizer,
        BitsAndBytesConfig,
        Trainer,
        TrainingArguments,
    )

    read_token = os.getenv("HF_READ_TOKEN") or os.getenv("HF_TOKEN")
    tokenizer = AutoTokenizer.from_pretrained(
        BASE_MODEL_ID,
        token=read_token,
        trust_remote_code=False,
    )
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    quantization = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_use_double_quant=True,
        bnb_4bit_compute_dtype=torch.bfloat16,
    )
    model = AutoModelForCausalLM.from_pretrained(
        BASE_MODEL_ID,
        quantization_config=quantization,
        device_map={"": "cuda:0"},
        token=read_token,
        trust_remote_code=False,
    )
    model.config.use_cache = False
    model = prepare_model_for_kbit_training(model, use_gradient_checkpointing=True)
    model = get_peft_model(
        model,
        LoraConfig(
            task_type="CAUSAL_LM",
            r=8,
            lora_alpha=16,
            lora_dropout=0.05,
            target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
            bias="none",
        ),
    )

    dataset_rows = _tokenized_examples(tokenizer, examples)
    if len(dataset_rows) < MIN_EXAMPLES:
        raise RuntimeError("لم يبق عدد كافٍ من الأمثلة بعد ترميزها بقالب النموذج.")

    training_directory = tempfile.mkdtemp(prefix="uti-candidate-")
    candidate_repo = (
        f"{candidate_prefix}-candidate-{datetime.now(timezone.utc):%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:6]}"
    )
    try:
        training_args = TrainingArguments(
            output_dir=training_directory,
            per_device_train_batch_size=1,
            gradient_accumulation_steps=2,
            max_steps=min(12, max(4, len(dataset_rows))),
            learning_rate=5e-5,
            logging_steps=1,
            save_strategy="no",
            report_to="none",
            bf16=True,
            fp16=False,
            gradient_checkpointing=True,
            optim="paged_adamw_8bit",
            remove_unused_columns=False,
            dataloader_pin_memory=False,
        )
        trainer = Trainer(
            model=model,
            args=training_args,
            train_dataset=_ResponseOnlyDataset(dataset_rows),
            data_collator=_ResponseOnlyCollator(tokenizer.pad_token_id),
        )
        trainer.train()
        model.save_pretrained(training_directory)
        tokenizer.save_pretrained(training_directory)

        api = HfApi(token=write_token)
        api.create_repo(
            repo_id=candidate_repo,
            repo_type="model",
            private=True,
            exist_ok=True,
            token=write_token,
        )
        api.upload_folder(
            repo_id=candidate_repo,
            repo_type="model",
            folder_path=training_directory,
            token=write_token,
            commit_message="Upload a short LoRA training candidate",
        )
    finally:
        shutil.rmtree(training_directory, ignore_errors=True)

    return (
        f"تم حفظ مرشح LoRA خاص: {candidate_repo}. "
        "لم يُعتمد تلقائياً؛ اختبره على مجموعة تقييم مستقلة ثم غيّر PROJECT_MODEL_ID يدوياً."
    )
