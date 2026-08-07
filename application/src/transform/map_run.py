"""
Transform: dbt (ETL) envelope → colleague pipeline-run log shape.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any


def new_pipeline_id() -> str:
    """Create a new pipeline_id (UUID). Store and reuse for that pipeline."""
    return str(uuid.uuid4())


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _duration_seconds(start: Any, end: Any) -> int | None:
    start_dt = _parse_time(start)
    end_dt = _parse_time(end)
    if not start_dt or not end_dt:
        return None
    return int((end_dt - start_dt).total_seconds())


def _map_status(status: str | None) -> str:
    """Our connector statuses → colleague status words."""
    s = (status or "").lower()
    if s in {"succeeded", "success", "ok"}:
        return "success"
    if s in {"failed", "error", "cancelled", "canceled"}:
        return "failed"
    if s in {"running", "queued", "starting"}:
        return "running"
    return s or "unknown"


def map_run(
    envelope: dict,
    *,
    pipeline_id: str | None = None,
    pipeline_name: str = "",
    triggered_by: str | None = "dbt-cloud",
    execution_mode: str | None = "orchestrated",
    orchestrator_tool: str | None = None,
    orchestrator_dag_id: str | None = None,
    orchestrator_task_id: str | None = None,
    orchestrator_run_id: str | None = None,
) -> dict:
    """
    Map one dbt Sync envelope to the pipeline-run log structure.

    pipeline_id: pass an existing UUID for that pipeline, or omit to create one
    with new_pipeline_id() / uuid4. Reuse the same id for every run of that pipeline.
    Orchestrator fields stay null until an Airflow connector exists.
    """
    raw = envelope.get("raw") or {}
    run_id = str(raw.get("run_id") or "")
    start_time = raw.get("started_at")
    end_time = raw.get("finished_at")
    err = raw.get("error_message")
    if err == "":
        err = None

    # Prefer caller-provided UUID; otherwise create one.
    resolved_pipeline_id = (pipeline_id or "").strip() or new_pipeline_id()

    return {
        "id": run_id,
        "pipeline_id": resolved_pipeline_id,
        "pipeline_name": pipeline_name or str(raw.get("project_name") or ""),
        "status": _map_status(raw.get("status")),
        "start_time": start_time,
        "end_time": end_time,
        "duration": _duration_seconds(start_time, end_time),
        "tool_name": envelope.get("source_system") or "dbt",
        "rows_read": raw.get("rows_read"),
        "rows_written": raw.get("rows_written"),
        "rows_added": None,
        "error_message": err,
        "failure_stage": raw.get("failure_stage"),
        "failed_node": raw.get("failed_node"),
        "failed_message": raw.get("failed_message"),
        "raw_log": json.dumps(raw, default=str),
        "execution_mode": execution_mode,
        "triggered_by": triggered_by,
        "orchestrator_tool": orchestrator_tool,
        "orchestrator_dag_id": orchestrator_dag_id,
        "orchestrator_task_id": orchestrator_task_id,
        "orchestrator_run_id": orchestrator_run_id,
        # platform labels (useful for store; not in colleague sample but harmless)
        "tenant_id": envelope.get("tenant_id"),
        "connector_instance_id": envelope.get("connector_instance_id"),
    }


def map_runs(envelopes: list[dict], **kwargs) -> list[dict]:
    return [map_run(env, **kwargs) for env in envelopes]
