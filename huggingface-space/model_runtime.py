from __future__ import annotations

import json
import os
import re
import threading
from typing import Any

from spaces import GPU

from arabic_evaluation import (
    EVALUATION_CASES,
    model_artifact_fingerprint,
    promotion_report_is_valid,
)

BASE_MODEL_ID = os.getenv("BASE_MODEL_ID", "Qwen/Qwen3-8B")
PROJECT_MODEL_ID = os.getenv("PROJECT_MODEL_ID", "").strip()
_read_token = os.getenv("HF_READ_TOKEN") or os.getenv("HF_TOKEN")
SAFETY_SYSTEM_PROMPT = (
    "أنت النموذج الحواري الخاص بمشروع مرصاد. أجب بالعربية الواضحة. "
    "لا تدّع امتلاك بيانات سوق حية أو تنفيذ صفقات. ميّز بوضوح بين البيانات التركيبية والحقيقية، "
    "وصرّح بعدم اليقين. لا تطلب كلمات مرور أو مفاتيح API ولا تكررها."
)

_model: Any = None
_tokenizer: Any = None
_load_error: str | None = None
_promotion_approved = False
PROJECT_MODEL_REVISION = ""
PROJECT_MODEL_ARTIFACT_FINGERPRINT = ""
_model_lock = threading.RLock()


def _has_passing_evaluation(checkpoint_id: str, artifact_fingerprint: str) -> bool:
    try:
        from huggingface_hub import hf_hub_download

        report_path = hf_hub_download(
            repo_id=checkpoint_id,
            repo_type="model",
            filename="evaluation/latest.json",
            token=_read_token,
        )
        with open(report_path, "r", encoding="utf-8") as handle:
            report = json.load(handle)
        return promotion_report_is_valid(report, checkpoint_id, artifact_fingerprint)
    except Exception as error:
        print(f"Promotion evaluation unavailable: {type(error).__name__}")
        return False


def _load_project_checkpoint() -> None:
    """Load only a project checkpoint whose exact files passed promotion review."""
    global _model, _tokenizer, _load_error, _promotion_approved
    global PROJECT_MODEL_REVISION, PROJECT_MODEL_ARTIFACT_FINGERPRINT
    if not PROJECT_MODEL_ID:
        return
    try:
        from huggingface_hub import HfApi

        model_info = HfApi(token=_read_token).model_info(
            repo_id=PROJECT_MODEL_ID,
            files_metadata=True,
        )
        PROJECT_MODEL_REVISION = model_info.sha or ""
        PROJECT_MODEL_ARTIFACT_FINGERPRINT = model_artifact_fingerprint(model_info)
    except Exception as error:
        _load_error = type(error).__name__
        print(f"Project checkpoint metadata could not be read: {_load_error}")
        return

    _promotion_approved = bool(PROJECT_MODEL_ARTIFACT_FINGERPRINT) and _has_passing_evaluation(
        PROJECT_MODEL_ID,
        PROJECT_MODEL_ARTIFACT_FINGERPRINT,
    )
    if not _promotion_approved:
        _load_error = "promotion_evaluation_missing_or_failed"
        print("Project checkpoint is evaluation-blocked; weights will not be loaded.")
        return

    try:
        import torch
        from peft import PeftModel
        from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

        quantization = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_use_double_quant=True,
            bnb_4bit_compute_dtype=torch.bfloat16,
        )
        _tokenizer = AutoTokenizer.from_pretrained(
            BASE_MODEL_ID,
            token=_read_token,
            trust_remote_code=False,
        )
        if _tokenizer.pad_token is None:
            _tokenizer.pad_token = _tokenizer.eos_token
        base = AutoModelForCausalLM.from_pretrained(
            BASE_MODEL_ID,
            quantization_config=quantization,
            device_map={"": "cuda:0"},
            token=_read_token,
            trust_remote_code=False,
        )
        _model = PeftModel.from_pretrained(
            base,
            PROJECT_MODEL_ID,
            token=_read_token,
            revision=PROJECT_MODEL_REVISION,
        )
        _model.eval()
        _load_error = None
    except Exception as error:  # Keep the Space alive so it can report setup errors.
        _model = None
        _tokenizer = None
        _load_error = type(error).__name__
        print(f"Project checkpoint could not be loaded: {_load_error}")


_load_project_checkpoint()


def model_status() -> dict[str, Any]:
    if not PROJECT_MODEL_ID:
        return {"ready": False, "state": "trained_checkpoint_missing"}
    if not _promotion_approved:
        return {
            "ready": False,
            "state": "promotion_blocked",
            "reason": "passing_candidate_evaluation_required",
        }
    if _model is None:
        return {"ready": False, "state": "checkpoint_load_failed", "error": _load_error}
    return {"ready": True, "state": "project_checkpoint_loaded"}


def _chat_prompt(
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None,
) -> str:
    options: dict[str, Any] = {
        "tokenize": False,
        "add_generation_prompt": True,
    }
    if tools:
        options["tools"] = tools
    try:
        return _tokenizer.apply_chat_template(
            messages,
            enable_thinking=False,
            **options,
        )
    except TypeError:
        return _tokenizer.apply_chat_template(messages, **options)


def _parse_tool_calls(text: str) -> tuple[str, list[dict[str, Any]]]:
    calls: list[dict[str, Any]] = []
    pattern = re.compile(r"<tool_call>\s*([\s\S]*?)\s*</tool_call>")
    for match in list(pattern.finditer(text))[:4]:
        try:
            payload = json.loads(match.group(1))
            name = payload.get("name")
            if not isinstance(name, str) or not name:
                continue
            arguments = payload.get("arguments", {})
            if not isinstance(arguments, (dict, list)):
                arguments = {}
            calls.append(
                {
                    "id": f"call_{len(calls) + 1}",
                    "type": "function",
                    "function": {
                        "name": name,
                        "arguments": json.dumps(arguments, ensure_ascii=False),
                    },
                }
            )
        except (TypeError, ValueError):
            continue

    content = pattern.sub("", text)
    content = re.sub(r"<\|(?:im_end|endoftext|fim_suffix)\|>", "", content)
    content = re.sub(r"<think>[\s\S]*?</think>", "", content).strip()
    return content, calls


def _generate_loaded_model(
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
    max_new_tokens: int = 512,
    temperature: float = 0.2,
) -> dict[str, Any]:
    import torch

    prompt = _chat_prompt(messages, tools)
    encoded = _tokenizer(prompt, return_tensors="pt")
    device = next(_model.parameters()).device
    encoded = {key: value.to(device) for key, value in encoded.items()}
    limit = max(32, min(int(max_new_tokens), 768))
    temperature = max(0.0, min(float(temperature), 1.0))
    generation_options: dict[str, Any] = {
        **encoded,
        "max_new_tokens": limit,
        "pad_token_id": _tokenizer.pad_token_id,
        "eos_token_id": _tokenizer.eos_token_id,
        "do_sample": temperature > 0,
    }
    if temperature > 0:
        generation_options["temperature"] = temperature
        generation_options["top_p"] = 0.9

    with torch.inference_mode():
        output = _model.generate(**generation_options)
    prompt_length = encoded["input_ids"].shape[1]
    text = _tokenizer.decode(
        output[0][prompt_length:],
        skip_special_tokens=False,
    )
    content, tool_calls = _parse_tool_calls(text)
    return {"content": content, "tool_calls": tool_calls}


@GPU(duration=120)
def generate(
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
    max_new_tokens: int = 512,
    temperature: float = 0.2,
) -> dict[str, Any]:
    if not _promotion_approved:
        raise RuntimeError("لا يسمح بتشغيل نموذج لم يجتز بوابة التقييم.")
    if _model is None or _tokenizer is None:
        raise RuntimeError("لا توجد نسخة مدرّبة ومحمّلة من نموذج المشروع.")
    if not messages:
        raise ValueError("يجب إرسال رسائل المحادثة.")

    with _model_lock:
        return _generate_loaded_model(
            messages,
            tools=tools,
            max_new_tokens=max_new_tokens,
            temperature=temperature,
        )


@GPU(duration=240)
def evaluate_candidate_responses(
    candidate_model_id: str,
    candidate_revision: str,
) -> dict[str, dict[str, str]]:
    """Compare deterministic held-out responses without loading a second base model."""
    if _model is None or _tokenizer is None:
        raise RuntimeError("لا يمكن تقييم المرشح قبل تحميل النموذج الحالي.")
    if not candidate_model_id.strip() or candidate_model_id == PROJECT_MODEL_ID:
        raise ValueError("يجب إدخال معرف مرشح مختلف عن النموذج الحالي.")

    with _model_lock:
        previous_adapter = _model.active_adapter
        if isinstance(previous_adapter, (list, tuple)):
            previous_adapter = previous_adapter[0]
        candidate_adapter = "evaluation_candidate"
        try:
            _model.load_adapter(
                candidate_model_id,
                adapter_name=candidate_adapter,
                token=_read_token,
                revision=candidate_revision,
            )
            responses: dict[str, dict[str, str]] = {"baseline": {}, "candidate": {}}
            for adapter_name, response_key in (
                (previous_adapter, "baseline"),
                (candidate_adapter, "candidate"),
            ):
                _model.set_adapter(adapter_name)
                for case in EVALUATION_CASES:
                    prompts = [
                        (case["id"], case["prompt"]),
                        *[
                            (
                                f"{case['id']}::{variant['id']}",
                                variant["prompt"],
                            )
                            for variant in case.get("prompt_variants", [])
                        ],
                    ]
                    for response_id, prompt in prompts:
                        result = _generate_loaded_model(
                            [
                                {"role": "system", "content": SAFETY_SYSTEM_PROMPT},
                                {"role": "user", "content": prompt},
                            ],
                            max_new_tokens=128,
                            temperature=0,
                        )
                        responses[response_key][response_id] = result["content"]
            return responses
        finally:
            _model.set_adapter(previous_adapter)
