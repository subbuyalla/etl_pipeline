from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid5, NAMESPACE_URL

from dateutil import parser as date_parser


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_time(value: Any, default: str | None = None) -> str:
    if value is None or value == "":
        return default or utc_now_iso()
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    dt = date_parser.isoparse(str(value))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def stable_event_id(*parts: str) -> str:
    """Deterministic id for idempotent upserts."""
    key = "|".join(p for p in parts if p is not None)
    return str(uuid5(NAMESPACE_URL, key))


def normalize_status(raw: Any) -> str:
    if raw is None:
        return "unknown"
    s = str(raw).strip().lower().replace(" ", "_")
    mapping = {
        "success": "succeeded",
        "succeeded": "succeeded",
        "successful": "succeeded",
        "ok": "succeeded",
        "completed": "succeeded",
        "complete": "succeeded",
        "done": "succeeded",
        "failed": "failed",
        "failure": "failed",
        "error": "failed",
        "errored": "failed",
        "fail": "failed",
        "running": "running",
        "in_progress": "running",
        "inprogress": "running",
        "active": "running",
        "queued": "queued",
        "pending": "queued",
        "scheduled": "queued",
        "waiting": "queued",
        "skipped": "skipped",
        "up_for_retry": "retrying",
        "retry": "retrying",
        "retrying": "retrying",
        "cancelled": "cancelled",
        "canceled": "cancelled",
        "timeout": "failed",
        "timed_out": "failed",
    }
    return mapping.get(s, s)


def pipeline_event_type(status: str) -> str:
    status = normalize_status(status)
    if status == "succeeded":
        return "pipeline.execution.succeeded.v1"
    if status in {"failed", "cancelled"}:
        return "pipeline.execution.failed.v1"
    return "pipeline.execution.started.v1"


def task_event_type(status: str) -> str:
    status = normalize_status(status)
    if status == "succeeded":
        return "task.execution.succeeded.v1"
    if status == "retrying":
        return "task.execution.retried.v1"
    if status in {"failed", "cancelled"}:
        return "task.execution.failed.v1"
    return "task.execution.started.v1"


def require(raw: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in raw and raw[key] is not None and raw[key] != "":
            return raw[key]
    raise KeyError(f"Missing required field; tried {keys}")


def first(raw: dict[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        if key in raw and raw[key] is not None and raw[key] != "":
            return raw[key]
    return default
