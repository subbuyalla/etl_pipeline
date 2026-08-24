"""
Application API — pipelines + webhook + manual Sync.

pipeline_id lives in Metadata MySQL (obs_pipelines.is_active), not in .env.

Endpoints:
  GET  /health
  POST /v1/pipelines
  GET  /v1/pipelines
  GET  /v1/pipelines/templates
  GET  /v1/pipelines/current
  POST /v1/sync
  GET  /v1/dashboard/overview
  GET  /api/v1/*               ← versioned dashboard UI APIs (see /docs)
  POST /grafana/dashboard
  POST /webhooks/dbt
  POST /webhooks/dbt/{pipeline_name}
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")

# Public API base (Vercel production). Override with PUBLIC_BASE_URL if needed.
DEFAULT_PUBLIC_BASE_URL = "https://etl-pipeline-lemon.vercel.app"


def public_base_url() -> str:
    explicit = (os.getenv("PUBLIC_BASE_URL") or "").strip().rstrip("/")
    if explicit:
        return explicit
    vercel = (os.getenv("VERCEL_URL") or "").strip().rstrip("/")
    if vercel:
        if vercel.startswith("http://") or vercel.startswith("https://"):
            return vercel
        return f"https://{vercel}"
    return DEFAULT_PUBLIC_BASE_URL


def webhook_urls(base: str | None = None) -> dict[str, Any]:
    root = (base or public_base_url()).rstrip("/")
    return {
        "base_url": root,
        "active": f"{root}/webhooks/dbt",
        "by_name": f"{root}/webhooks/dbt/{{pipeline_name}}",
        "pipelines": {
            "stock_etl": f"{root}/webhooks/dbt/stock_etl",
            "ecommerce_etl": f"{root}/webhooks/dbt/ecommerce_etl",
            "hr_etl": f"{root}/webhooks/dbt/hr_etl",
        },
    }

from application.src.pipelines import (  # noqa: E402
    get_pipeline_template,
    list_pipeline_templates,
    new_pipeline_id,
)
from application.src.store.meta_mysql import (  # noqa: E402
    get_active_pipeline,
    get_pipeline_by_name,
    list_pipelines,
    upsert_pipeline,
)
from application.src.sync_once import run_sync_once  # noqa: E402
from application.src.services.grafana_service import (  # noqa: E402
    create_or_update_dashboard,
)
from application.src.services.dashboard_service import (  # noqa: E402
    build_overview,
)
from application.src.api.observability_router import (  # noqa: E402
    router as observability_api_router,
)

app = FastAPI(
    title="ETL Observability App API",
    description=(
        "Pipeline attach stored in MySQL; webhook Sync loads active or named pipeline. "
        "Dashboard UI APIs under /api/v1/*."
    ),
    version="0.5.0",
)

app.include_router(observability_api_router, prefix="/api/v1")

# Allow local Vite UI (and similar) to call this API from another origin
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def root() -> dict[str, Any]:
    """Root probe for Vercel / load balancers."""
    base = public_base_url()
    return {
        "service": "etl-observability-api",
        "base_url": base,
        "docs": f"{base}/docs",
        "health": f"{base}/health",
        "webhook_urls": webhook_urls(base),
    }


class SyncRequest(BaseModel):
    pipeline_id: str | None = None
    pipeline_name: str | None = None
    dbt_run_id: str | None = None


class CreatePipelineRequest(BaseModel):
    pipeline_id: str | None = Field(
        default=None,
        description="Omit to create a new UUID (stored in DB)",
    )
    pipeline_name: str | None = Field(
        default="stock_etl",
        description="Template name: stock_etl | ecommerce_etl (or custom label)",
    )
    make_active: bool = Field(
        default=True,
        description="If true, this pipeline becomes the Sync default",
    )


def _extract_dbt_webhook_fields(payload: dict) -> tuple[str | None, Any]:
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    run_id = (
        payload.get("runId")
        or payload.get("run_id")
        or data.get("runId")
        or data.get("run_id")
        or data.get("id")
    )
    status = payload.get("status") or data.get("status") or data.get("run_status")
    return (str(run_id) if run_id is not None else None, status)


def _handle_dbt_webhook(
    payload: dict,
    *,
    pipeline_name: str | None = None,
) -> dict:
    """
    Sync a specific pipeline when pipeline_name is set; otherwise Sync active.
    Example URLs:
      POST /webhooks/dbt/ecommerce_etl
      POST /webhooks/dbt/stock_etl
      POST /webhooks/dbt?pipeline_name=ecommerce_etl
      POST /webhooks/dbt   (active pipeline)
    """
    run_id, status = _extract_dbt_webhook_fields(payload or {})
    name = (pipeline_name or "").strip() or None

    if name:
        known = get_pipeline_by_name(name)
        if not known:
            templates = set(list_pipeline_templates())
            if name.lower() not in templates:
                raise HTTPException(
                    status_code=404,
                    detail=(
                        f"Unknown pipeline_name={name}. "
                        f"Register it first (POST /v1/pipelines) or use a template: "
                        f"{sorted(templates)}"
                    ),
                )

    print(
        "WEBHOOK dbt received run_id=",
        run_id,
        "status=",
        status,
        "pipeline_name=",
        name or "(active)",
    )

    try:
        result = run_sync_once(
            pipeline_name=name,
            dbt_run_id=run_id,
        )
        result["webhook"] = {
            "run_id": run_id,
            "status": status,
            "pipeline_name": name or result.get("pipeline_name"),
            "route": f"/webhooks/dbt/{name}" if name else "/webhooks/dbt",
        }
        return result
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/health")
def health() -> dict:
    active = get_active_pipeline()
    base = public_base_url()
    return {
        "ok": True,
        "base_url": base,
        "pipeline_from": "metadata.obs_pipelines",
        "templates": list_pipeline_templates(),
        "webhook_urls": webhook_urls(base),
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


@app.get("/v1/pipelines/templates")
def pipelines_templates() -> dict:
    return {"ok": True, "templates": list_pipeline_templates()}


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
    Create/update a pipeline in DB from a known template.

    Templates:
      stock_etl      — ANALYTICS_DB.RAW -> dbt -> STAGING_STAGING
      ecommerce_etl  — ECOMMERCE.SRC_DATA -> dbt (eg250) -> CLEAN_DATA
      hr_etl         — HR_ANALYTICS.RAW_DATA -> dbt (eg250) -> FINAL_DATA
    """
    body = body or CreatePipelineRequest()
    pipeline_id = (body.pipeline_id or "").strip() or new_pipeline_id()
    pipeline_name = (body.pipeline_name or "stock_etl").strip()
    pipeline = get_pipeline_template(pipeline_name, pipeline_id=pipeline_id)
    pipeline["pipeline_name"] = pipeline_name
    try:
        result = upsert_pipeline(pipeline, make_active=bool(body.make_active))
        result["pipeline"] = {
            "pipeline_id": pipeline.get("pipeline_id"),
            "pipeline_name": pipeline.get("pipeline_name"),
            "description": pipeline.get("description"),
            "source": f"snowflake/{(pipeline.get('source') or {}).get('schema')}",
            "etl": {
                "tool": "dbt",
                "account_id": (pipeline.get("etl") or {}).get("account_id"),
                "project_id": (pipeline.get("etl") or {}).get("project_id"),
                "api_base": (pipeline.get("etl") or {}).get("api_base"),
            },
            "target": f"snowflake/{(pipeline.get('target') or {}).get('schema')}",
        }
        return result
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/v1/sync")
def sync_manual(body: SyncRequest | None = None) -> dict:
    """Manual Sync — loads active pipeline from DB (or pipeline_id / pipeline_name)."""
    body = body or SyncRequest()
    try:
        return run_sync_once(
            pipeline_id=body.pipeline_id,
            pipeline_name=body.pipeline_name,
            dbt_run_id=body.dbt_run_id,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/v1/dashboard/overview")
def dashboard_overview(
    range: str = Query(
        default="24h",
        description="Time range for run-based widgets: 24h | 7d | 30d | all",
    ),
) -> dict:
    """Executive Overview payload from Metadata MySQL views and TARGET assets."""
    try:
        return build_overview(range)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/grafana/dashboard")
def generate_grafana_dashboard() -> dict:
    """
    Upsert the ETL Observability Grafana dashboard (stable uid).

    Requires GRAFANA_URL + GRAFANA_TOKEN in .env. Creates MySQL views and
    ensures a MySQL datasource exists, then writes starter KPI panels.
    """
    try:
        return create_or_update_dashboard()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/webhooks/dbt")
def dbt_webhook(
    payload: dict,
    pipeline_name: str | None = Query(
        default=None,
        description="Optional pipeline name; omit to Sync the active pipeline",
    ),
) -> dict:
    """dbt Cloud webhook → Sync active pipeline (or ?pipeline_name=...)."""
    return _handle_dbt_webhook(payload, pipeline_name=pipeline_name)


@app.post("/webhooks/dbt/{pipeline_name}")
def dbt_webhook_for_pipeline(pipeline_name: str, payload: dict) -> dict:
    """
    dbt Cloud webhook for one named pipeline.

    Examples (production):
      https://etl-pipeline-lemon.vercel.app/webhooks/dbt/stock_etl
      https://etl-pipeline-lemon.vercel.app/webhooks/dbt/ecommerce_etl
      https://etl-pipeline-lemon.vercel.app/webhooks/dbt/hr_etl
    """
    return _handle_dbt_webhook(payload, pipeline_name=pipeline_name)
