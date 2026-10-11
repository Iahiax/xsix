from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone


def save_correction(prompt: str, correction: str) -> str:
    token = os.getenv("HF_WRITE_TOKEN") or os.getenv("HF_TOKEN")
    repo_id = os.getenv("FEEDBACK_DATASET_ID", "").strip()
    if not token or not repo_id:
        raise RuntimeError(
            "أضف HF_WRITE_TOKEN وFEEDBACK_DATASET_ID إلى أسرار الـSpace لحفظ أمثلة التدريب."
        )

    from huggingface_hub import HfApi

    api = HfApi(token=token)
    api.create_repo(repo_id=repo_id, repo_type="dataset", private=True, exist_ok=True)
    record = {
        "prompt": prompt.strip()[:4000],
        "response": correction.strip()[:4000],
        "kind": "user_approved_correction",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    path = f"feedback/{datetime.now(timezone.utc):%Y%m%d}/{uuid.uuid4().hex}.jsonl"
    api.upload_file(
        path_or_fileobj=(json.dumps(record, ensure_ascii=False) + "\n").encode("utf-8"),
        path_in_repo=path,
        repo_id=repo_id,
        repo_type="dataset",
        token=token,
        commit_message="Add a user-approved training correction",
    )
    return path
