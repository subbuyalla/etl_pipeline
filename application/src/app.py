"""
Application API — pipelines + webhook + manual Sync.

pipeline_id lives in Metadata MySQL (obs_pipelines.is_active), not in .env.

Endpoints:
  GET  /health
  POST /v1/pipelines
  GET  /v1/pipelines
  GET  /v1/pipelines/current
  POST /v1/sync
  POST /webhooks/dbt
"""

from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")

from application.src.pipelines import get_stock_etl_pipeline, new_pipeline_id  # noqa: E402
from application.src.store.meta_mysql import (  # noqa: E402
    get_active_pipeline,
    list_pipelines,
    upsert_pipeline,
)
from application.src.sync_once import run_sync_once  # noqa: E402

app = FastAPI(
    title="ETL Observability App API",
    description="Pipeline attach stored in MySQL; webhook Sync loads active pipeline from DB",
    version="0.3.0",
)


class SyncRequest(BaseModel):
    pipeline_id: str | None = None
    pipeline_name: str | None = None
    dbt_run_id: str | None = None


class CreatePipelineRequest(BaseModel):
    pipeline_id: str | None = Field(
        default=None,
        description="Omit to create a new UUID (stored in DB as active)",
    )
    pipeline_name: str | None = "stock_etl"


@app.get("/health")
def health() -> dict:
    active = get_active_pipeline()
    return {
        "ok": True,
        "pipeline_from": "metadata.obs_pipelines",
        "active_pipeline": {
            "pipeline_id": (active or {}).get("pipeline_id"),
            "pipeline_name": (active or {}).get("pipeline_name"),
            "source": f"snowflake/{((active or {}).get('source') or {}).get('schema')}",
            "etl": "dbt",
            "target": f"snowflake/{((active or {}).get('target') or {}).get('schema')}",
        }
        if active
        else None,
    }


@app.get("/v1/pipelines")
def pipelines_list() -> dict:
    return {"ok": True, "pipelines": list_pipelines()}


@app.get("/v1/pipelines/current")
def get_current_pipeline() -> dict:
    active = get_active_pipeline()
    if not active:
        raise HTTPException(status_code=404, detail="No pipeline in DB. POST /v1/pipelines first.")
    return active


@app.post("/v1/pipelines")
def create_pipeline(body: CreatePipelineRequest | None = None) -> dict:
    """
    Create pipeline in DB and mark it active:
      SOURCE = Snowflake RAW
      ETL    = dbt
      TARGET = Snowflake STAGING_STAGING
    """
    body = body or CreatePipelineRequest()
    pipeline_id = (body.pipeline_id or "").strip() or new_pipeline_id()
    pipeline_name = body.pipeline_name or "stock_etl"
    pipeline = get_stock_etl_pipeline(pipeline_id=pipeline_id)
    pipeline["pipeline_name"] = pipeline_name
    try:
        result = upsert_pipeline(pipeline, make_active=True)
        result["pipeline"] = pipeline
        return result
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/v1/sync")
def sync_manual(body: SyncRequest | None = None) -> dict:
    """Manual Sync — loads active pipeline from DB (or pipeline_id if provided)."""
    body = body or SyncRequest()
    try:
        return run_sync_once(
            pipeline_id=body.pipeline_id,
            pipeline_name=body.pipeline_name,
            dbt_run_id=body.dbt_run_id,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/webhooks/dbt")
def dbt_webhook(payload: dict) -> dict:
    """dbt Cloud webhook: run completed → Sync active pipeline from DB."""
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    run_id = (
        payload.get("runId")
        or payload.get("run_id")
        or data.get("runId")
        or data.get("run_id")
        or data.get("id")
    )
    status = payload.get("status") or data.get("status") or data.get("run_status")
    print("WEBHOOK dbt received run_id=", run_id, "status=", status)

    try:
        result = run_sync_once(dbt_run_id=str(run_id) if run_id else None)
        result["webhook"] = {"run_id": run_id, "status": status}
        return result
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
