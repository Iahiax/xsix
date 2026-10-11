"""Small, privacy-safe in-memory monitor for HTTP 5xx responses."""

from __future__ import annotations

from collections import deque
from datetime import datetime, timedelta, timezone
from threading import Lock
from typing import Any

_MAX_EVENTS = 100
_WINDOW = timedelta(hours=24)
_events: deque[dict[str, Any]] = deque(maxlen=_MAX_EVENTS)
_lock = Lock()


def _safe_path(path: str) -> str:
    segments = []
    for segment in path.split("?", 1)[0].split("/"):
        if not segment:
            continue
        if len(segment) >= 32 or segment.isdigit():
            segments.append(":segment")
        else:
            segments.append(segment[:80])
    return ("/" + "/".join(segments))[:180]


def record_error(status_code: int, method: str, path: str) -> None:
    if status_code < 500:
        return
    now = datetime.now(timezone.utc)
    item = {
        "occurredAt": now.isoformat(),
        "statusCode": min(599, max(500, int(status_code))),
        "method": method.upper()[:10],
        "path": _safe_path(path),
    }
    with _lock:
        _prune(now)
        _events.append(item)


def _prune(now: datetime) -> None:
    cutoff = now - _WINDOW
    while _events and datetime.fromisoformat(_events[0]["occurredAt"]) < cutoff:
        _events.popleft()


def get_error_snapshot() -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    with _lock:
        _prune(now)
        recent = list(reversed(_events))
    return {
        "state": "attention" if recent else "healthy",
        "errorCount": len(recent),
        "recentErrors": recent[:20],
        "checkedAt": now.isoformat(),
        "retentionNote": (
            "أخطاء HTTP من فئة 5xx فقط؛ تُحفظ في ذاكرة Space الحالية حتى 24 ساعة "
            "وبحد أقصى 100 حدث، من دون نصوص الطلبات أو تفاصيل الاستثناء."
        ),
    }
