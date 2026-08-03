from __future__ import annotations

import os
from typing import Any
from urllib.parse import quote


def deep_link_label(source_tool: str | None) -> str | None:
    tool = (source_tool or "").lower()
    labels = {
        "airflow": "Open in Airflow",
        "dbt": "Open in dbt Cloud",
        "glue": "Open in AWS Glue",
        "adf": "Open in Azure Data Factory",
    }
    return labels.get(tool)


def build_deep_link(
    *,
    source_tool: str | None,
    pipeline_id: str | None,
    execution_id: str | None,
    task_id: str | None = None,
) -> str | None:
    """Build an optional deep link into the native ETL tool UI (env-configured)."""
    tool = (source_tool or "").lower()
    if not pipeline_id:
        return None

    if tool == "airflow":
        base = os.environ.get("AIRFLOW_BASE_URL", "").strip().rstrip("/")
        if not base or not execution_id:
            return None
        url = (
            f"{base}/dags/{quote(pipeline_id, safe='')}/grid"
            f"?dag_run_id={quote(str(execution_id), safe='')}"
        )
        if task_id:
            url += f"&task_id={quote(str(task_id), safe='')}"
        return url

    if tool == "dbt":
        base = os.environ.get("DBT_CLOUD_BASE_URL", "").strip().rstrip("/")
        if not base:
            return None
        if execution_id:
            return f"{base}/runs/{quote(str(execution_id), safe='')}"
        return f"{base}/runs"

    if tool == "glue":
        region = (
            os.environ.get("GLUE_CONSOLE_REGION")
            or os.environ.get("AWS_REGION")
            or os.environ.get("AWS_DEFAULT_REGION")
            or ""
        ).strip()
        if not region or not execution_id:
            return None
        job = quote(str(pipeline_id), safe="")
        run = quote(str(execution_id), safe="")
        return (
            f"https://{region}.console.aws.amazon.com/gluestudio/home"
            f"?region={quote(region, safe='')}#/job/{job}/run/{run}"
        )

    if tool == "adf":
        base = os.environ.get("ADF_PORTAL_BASE_URL", "").strip().rstrip("/")
        if not base or not execution_id:
            return None
        return f"{base}/en/authoring/pipeline/{quote(str(pipeline_id), safe='')}/run/{quote(str(execution_id), safe='')}"

    return None


def execution_to_dict(e: Any) -> dict[str, Any]:
    """Serialize an Execution ORM row for API responses."""
    started = e.started_at.isoformat() if getattr(e.started_at, "isoformat", None) else e.started_at
    finished = e.finished_at.isoformat() if getattr(e.finished_at, "isoformat", None) else e.finished_at
    deep_link = build_deep_link(
        source_tool=e.source_tool,
        pipeline_id=e.pipeline_id,
        execution_id=e.execution_id,
        task_id=e.task_id,
    )
    return {
        "execution_id": e.execution_id,
        "pipeline_id": e.pipeline_id,
        "task_id": e.task_id,
        "status": e.status,
        "attempt": e.attempt,
        "error_message": e.error_message,
        "source_tool": e.source_tool,
        "started_at": started,
        "finished_at": finished,
        "duration_ms": e.duration_ms,
        "triggered_by": e.triggered_by,
        "deep_link": deep_link,
        "deep_link_label": deep_link_label(e.source_tool) if deep_link else None,
    }
