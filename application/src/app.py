"""
Application API — Observability & Dashboard REST APIs.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")

from application.src.api.observability_router import (  # noqa: E402
    router as observability_api_router,
)
from application.src.store.meta_mysql import (  # noqa: E402
    get_active_pipeline,
    list_pipelines,
)

app = FastAPI(
    title="ETL Observability App API",
    description="ETL Observability & Reliability Dashboard REST APIs under /api/v1/*.",
    version="0.6.0",
)

# Mount the Observability Router under /api/v1
app.include_router(observability_api_router, prefix="/api/v1")

# Enable CORS for frontend clients
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def root() -> dict[str, Any]:
    """Root probe."""
    return {
        "service": "etl-observability-api",
        "status": "online",
        "docs": "/docs",
        "health": "/health",
        "api_v1": "/api/v1/overview",
    }


@app.get("/health")
def health() -> dict:
    """Service health status."""
    active = get_active_pipeline()
    return {
        "ok": True,
        "active_pipeline": (active or {}).get("pipeline_name"),
    }


@app.get("/v1/pipelines")
def pipelines_list() -> dict:
    """List pipelines in metadata store."""
    return {"ok": True, "pipelines": list_pipelines()}
