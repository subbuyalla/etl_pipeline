"""
Application API — webhook + manual Sync.

Run from repo root:
  uvicorn application.src.app:app --reload --port 8002

Endpoints:
  GET  /health
  POST /webhooks/dbt     ← dbt Cloud calls this when a run finishes
  POST /v1/sync          ← manual Sync (for testing without webhook)
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")

from application.src.sync_once import run_sync_once  # noqa: E402
from application.src.transform.map_run import new_pipeline_id  # noqa: E402

app = FastAPI(
    title="ETL Observability App API",
    description="Webhook + Sync for connectors → transform → store",
    version="0.1.0",
)

# Reuse one pipeline UUID for the demo app process
_PIPELINE_ID = (os.getenv("PIPELINE_ID") or "").strip() or new_pipeline_id()
_PIPELINE_NAME = os.getenv("PIPELINE_NAME", "stock_etl")


class SyncRequest(BaseModel):
    pipeline_id: str | None = None
    pipeline_name: str | None = None
    dbt_run_id: str | None = None


class DbtWebhookPayload(BaseModel):
    """Loose model — dbt Cloud webhook bodies vary by account/version."""

    event_type: str | None = None
    data: dict = Field(default_factory=dict)

    class Config:
        extra = "allow"


@app.get("/health")
def health() -> dict:
    return {
        "ok": True,
        "pipeline_id": _PIPELINE_ID,
        "pipeline_name": _PIPELINE_NAME,
    }


@app.post("/v1/sync")
def sync_manual(body: SyncRequest | None = None) -> dict:
    """Manual Sync — same path as webhook, for local testing."""
    body = body or SyncRequest()
    try:
        return run_sync_once(
            pipeline_id=body.pipeline_id or _PIPELINE_ID,
            pipeline_name=body.pipeline_name or _PIPELINE_NAME,
            dbt_run_id=body.dbt_run_id,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/webhooks/dbt")
def dbt_webhook(payload: dict) -> dict:
    """
    dbt Cloud webhook target.
    When a run completes, dbt POSTs here → we Sync once.
    """
    # Common shapes: top-level run id, or nested under data
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    run_id = (
        payload.get("runId")
        or payload.get("run_id")
        or data.get("runId")
        or data.get("run_id")
        or data.get("id")
    )
    status = (
        payload.get("status")
        or data.get("status")
        or data.get("run_status")
    )

    # Only Sync on finished-ish events when status is present; otherwise still Sync once
    print("WEBHOOK dbt received run_id=", run_id, "status=", status)

    try:
        result = run_sync_once(
            pipeline_id=_PIPELINE_ID,
            pipeline_name=_PIPELINE_NAME,
            dbt_run_id=str(run_id) if run_id else None,
        )
        result["webhook"] = {"run_id": run_id, "status": status}
        return result
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
