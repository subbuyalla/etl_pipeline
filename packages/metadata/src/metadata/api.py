from __future__ import annotations

from typing import Any, Optional

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from metadata.db import get_session, init_db
from metadata.ingest import ingest_canonical_event, ingest_canonical_events
from metadata.links import execution_to_dict
from metadata.repository import MetadataRepository

app = FastAPI(
    title="Metadata API",
    version="0.1.0",
    description="Canonical metadata store for ETL/ELT observability (Monte Carlo parity + beyond)",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class CanonicalEventIn(BaseModel):
    event_id: str
    event_type: str
    occurred_at: str
    tenant_id: str
    source_system: str
    source_tool: str
    connector_instance_id: Optional[str] = None
    payload: dict[str, Any] = Field(default_factory=dict)


class CanonicalBatchIn(BaseModel):
    events: list[CanonicalEventIn]


class NormalizeAndIngestIn(BaseModel):
    """Accept raw tool payload: normalize then store."""

    source_system: str
    tenant_id: str
    raw: dict[str, Any]
    connector_instance_id: Optional[str] = None


def session_dep():
    session = get_session()
    try:
        yield session
    finally:
        session.close()


@app.on_event("startup")
def on_startup() -> None:
    init_db()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "layer": "metadata"}


@app.post("/v1/events")
def post_event(body: CanonicalEventIn, session: Session = Depends(session_dep)) -> dict[str, Any]:
    return ingest_canonical_event(session, body.model_dump())


@app.post("/v1/events/batch")
def post_events(body: CanonicalBatchIn, session: Session = Depends(session_dep)) -> dict[str, Any]:
    results = ingest_canonical_events(session, [e.model_dump() for e in body.events])
    return {"results": results, "count": len(results)}


@app.post("/v1/ingest/raw")
def ingest_raw(body: NormalizeAndIngestIn, session: Session = Depends(session_dep)) -> dict[str, Any]:
    try:
        from normalization import normalize_production
    except ImportError as exc:
        raise HTTPException(status_code=500, detail="normalization not installed") from exc

    result = normalize_production(
        source_system=body.source_system,
        tenant_id=body.tenant_id,
        raw=body.raw,
        connector_instance_id=body.connector_instance_id,
    )
    ingested = []
    for event in result.events:
        ingested.append(ingest_canonical_event(session, event))
    return {
        "normalized_events": len(result.events),
        "dead_letters": [d.to_dict() for d in result.dead_letters],
        "ingest": ingested,
    }


@app.get("/v1/pipelines")
def get_pipelines(
    tenant_id: str = Query(...),
    limit: int = Query(100, le=1000),
    session: Session = Depends(session_dep),
) -> dict[str, Any]:
    repo = MetadataRepository(session)
    rows = repo.list_pipelines(tenant_id, limit=limit)
    return {
        "items": [
            {
                "pipeline_id": r.pipeline_id,
                "name": r.name,
                "source_tool": r.source_tool,
                "status": r.status,
            }
            for r in rows
        ]
    }


@app.get("/v1/pipelines/{pipeline_id}")
def get_pipeline(
    pipeline_id: str,
    tenant_id: str = Query(...),
    session: Session = Depends(session_dep),
) -> dict[str, Any]:
    repo = MetadataRepository(session)
    pipeline = repo.get_pipeline(tenant_id, pipeline_id)
    if not pipeline:
        raise HTTPException(status_code=404, detail=f"Pipeline '{pipeline_id}' not found")
    io_rows = repo.list_pipeline_io(tenant_id, pipeline_id=pipeline_id, limit=500)
    related_datasets: set[str] = set()
    pipeline_io = []
    for io in io_rows:
        related_datasets.add(io.upstream_dataset_id)
        related_datasets.add(io.downstream_dataset_id)
        pipeline_io.append(
            {
                "upstream_dataset_id": io.upstream_dataset_id,
                "downstream_dataset_id": io.downstream_dataset_id,
                "source_tool": io.source_tool,
            }
        )
    if not related_datasets:
        for edge in repo.list_lineage(tenant_id, limit=500):
            if (edge.transform or "") == pipeline_id or pipeline_id in (edge.transform or ""):
                related_datasets.add(edge.upstream_dataset_id)
                related_datasets.add(edge.downstream_dataset_id)
    return {
        "pipeline_id": pipeline.pipeline_id,
        "name": pipeline.name,
        "source_tool": pipeline.source_tool,
        "status": pipeline.status,
        "tags": pipeline.tags or [],
        "related_datasets": sorted(related_datasets),
        "pipeline_io": pipeline_io,
    }


@app.get("/v1/pipelines/{pipeline_id}/dashboard")
def get_pipeline_dashboard(
    pipeline_id: str,
    tenant_id: str = Query(...),
    session: Session = Depends(session_dep),
) -> dict[str, Any]:
    repo = MetadataRepository(session)
    dash = repo.pipeline_dashboard(tenant_id, pipeline_id)
    if not dash:
        raise HTTPException(status_code=404, detail=f"Pipeline '{pipeline_id}' not found")
    return dash


def _iso(dt: Any) -> str | None:
    if dt is None:
        return None
    return dt.isoformat() if hasattr(dt, "isoformat") else str(dt)


def _monitor_type_from_incident_key(incident_key: str) -> str | None:
    parts = (incident_key or "").split(":")
    return parts[-1] if len(parts) >= 2 else None


def _dataset_payload(r: Any) -> dict[str, Any]:
    return {
        "dataset_id": r.dataset_id,
        "name": r.name,
        "database": r.database_name,
        "schema": r.schema_name,
        "platform": r.platform,
        "row_count": r.row_count,
        "last_updated_at": _iso(r.last_updated_at),
    }


def _incident_payload(r: Any) -> dict[str, Any]:
    return {
        "incident_key": r.incident_key,
        "title": r.title,
        "status": r.status,
        "severity": r.severity,
        "root_asset_type": r.root_asset_type,
        "root_asset_id": r.root_asset_id,
        "monitor_type": _monitor_type_from_incident_key(r.incident_key),
        "blast_radius_count": r.blast_radius_count,
        "summary": r.summary,
        "error_message": r.summary,
        "opened_at": _iso(r.opened_at),
        "resolved_at": _iso(r.resolved_at),
    }


def _latest_failed_execution(
    repo: MetadataRepository,
    tenant_id: str,
    *,
    root_asset_type: str | None,
    root_asset_id: str | None,
) -> dict[str, Any] | None:
    if not root_asset_id:
        return None
    asset_type = (root_asset_type or "").lower()
    pipeline_id: str | None = None
    task_id: str | None = None
    if asset_type == "pipeline":
        pipeline_id = root_asset_id
    elif asset_type == "task" and "." in root_asset_id:
        pipeline_id, task_id = root_asset_id.split(".", 1)
    else:
        return None

    rows = repo.list_executions(tenant_id, pipeline_id=pipeline_id, limit=100)
    for row in rows:
        if task_id and row.task_id != task_id:
            continue
        if (row.status or "").lower() in {"failed", "error", "cancelled"}:
            return execution_to_dict(row)
    return None


def _incident_detail_payload(repo: MetadataRepository, tenant_id: str, row: Any) -> dict[str, Any]:
    payload = _incident_payload(row)
    asset_id = row.root_asset_id
    alerts = repo.list_alerts(tenant_id, asset_id=asset_id, limit=10) if asset_id else []
    payload["alerts"] = [_alert_payload(a) for a in alerts]
    latest_failure = _latest_failed_execution(
        repo,
        tenant_id,
        root_asset_type=row.root_asset_type,
        root_asset_id=asset_id,
    )
    payload["latest_failure"] = latest_failure
    if latest_failure and latest_failure.get("error_message"):
        payload["error_message"] = latest_failure["error_message"]
    elif alerts:
        for alert in alerts:
            if alert.message:
                payload["error_message"] = alert.message
                break
    return payload


def _alert_payload(r: Any) -> dict[str, Any]:
    return {
        "alert_key": r.alert_key,
        "title": r.title,
        "severity": r.severity,
        "status": r.status,
        "asset_type": r.asset_type,
        "asset_id": r.asset_id,
        "monitor_type": r.monitor_type,
        "message": r.message,
        "raised_at": _iso(r.raised_at),
        "resolved_at": _iso(r.resolved_at),
    }


def _check_result_payload(r: Any) -> dict[str, Any]:
    return {
        "id": r.id,
        "monitor_id": r.monitor_id,
        "monitor_type": r.monitor_type,
        "asset_type": r.asset_type,
        "asset_id": r.asset_id,
        "status": r.status,
        "metric_value": r.metric_value,
        "baseline_value": r.baseline_value,
        "severity": r.severity,
        "details": r.details or {},
        "checked_at": _iso(r.checked_at),
    }


@app.get("/v1/datasets")
def get_datasets(
    tenant_id: str = Query(...),
    limit: int = Query(100, le=1000),
    session: Session = Depends(session_dep),
) -> dict[str, Any]:
    repo = MetadataRepository(session)
    rows = repo.list_datasets(tenant_id, limit=limit)
    items = [_dataset_payload(r) for r in rows]
    return {"items": items, "returned": len(items)}


@app.get("/v1/datasets/{dataset_id:path}")
def get_dataset(
    dataset_id: str,
    tenant_id: str = Query(...),
    include: Optional[str] = Query(
        None,
        description="Comma-separated: monitors, checks, lineage, blast",
    ),
    session: Session = Depends(session_dep),
) -> dict[str, Any]:
    repo = MetadataRepository(session)
    row = repo.get_dataset(tenant_id, dataset_id)
    if not row:
        raise HTTPException(status_code=404, detail=f"Dataset '{dataset_id}' not found")
    payload: dict[str, Any] = _dataset_payload(row)
    if include:
        parts = {p.strip().lower() for p in include.split(",") if p.strip()}
        if "monitors" in parts:
            monitors = [m for m in repo.list_monitors(tenant_id, limit=500) if m.asset_id == dataset_id]
            payload["monitors"] = [
                {
                    "monitor_key": m.monitor_key,
                    "monitor_type": m.monitor_type,
                    "enabled": m.enabled,
                    "name": m.name,
                    "config": m.config or {},
                }
                for m in monitors
            ]
        if "checks" in parts:
            payload["recent_checks"] = [
                _check_result_payload(c)
                for c in repo.list_check_results(tenant_id, asset_id=dataset_id, limit=20)
            ]
        if "lineage" in parts:
            edges = repo.list_lineage(tenant_id, dataset_id=dataset_id, limit=100)
            payload["lineage"] = {
                "upstream": sorted({e.upstream_dataset_id for e in edges if e.downstream_dataset_id == dataset_id}),
                "downstream": sorted({e.downstream_dataset_id for e in edges if e.upstream_dataset_id == dataset_id}),
                "edges": [
                    {
                        "upstream_dataset_id": e.upstream_dataset_id,
                        "downstream_dataset_id": e.downstream_dataset_id,
                        "confidence": e.confidence,
                        "transform": e.transform,
                    }
                    for e in edges
                ],
            }
        if "blast" in parts:
            downstream = repo.blast_radius(tenant_id, dataset_id)
            payload["blast_radius"] = {
                "dataset_id": dataset_id,
                "downstream": downstream,
                "count": len(downstream),
            }
    return payload


@app.get("/v1/executions")
def get_executions(
    tenant_id: str = Query(...),
    pipeline_id: Optional[str] = None,
    limit: int = Query(100, le=1000),
    session: Session = Depends(session_dep),
) -> dict[str, Any]:
    repo = MetadataRepository(session)
    rows = repo.list_executions(tenant_id, pipeline_id=pipeline_id, limit=limit)
    return {"items": [execution_to_dict(r) for r in rows]}


@app.get("/v1/metrics")
def get_metrics(
    tenant_id: str = Query(...),
    asset_id: Optional[str] = None,
    name: Optional[str] = None,
    limit: int = Query(100, le=1000),
    session: Session = Depends(session_dep),
) -> dict[str, Any]:
    repo = MetadataRepository(session)
    rows = repo.list_metrics(tenant_id, asset_id=asset_id, name=name, limit=limit)
    items = [
        {
            "name": r.name,
            "asset_type": r.asset_type,
            "asset_id": r.asset_id,
            "value": r.value,
            "unit": r.unit,
            "recorded_at": _iso(r.recorded_at),
            "labels": r.labels or {},
        }
        for r in rows
    ]
    return {"items": items, "returned": len(items)}


@app.get("/v1/incidents")
def get_incidents(
    tenant_id: str = Query(...),
    status: Optional[str] = None,
    asset_id: Optional[str] = None,
    limit: int = Query(100, le=1000),
    session: Session = Depends(session_dep),
) -> dict[str, Any]:
    repo = MetadataRepository(session)
    rows = repo.list_incidents(tenant_id, status=status, asset_id=asset_id, limit=limit)
    items = [_incident_payload(r) for r in rows]
    return {"items": items, "returned": len(items)}


@app.get("/v1/incidents/{incident_key:path}")
def get_incident(
    incident_key: str,
    tenant_id: str = Query(...),
    session: Session = Depends(session_dep),
) -> dict[str, Any]:
    repo = MetadataRepository(session)
    row = repo.get_incident(tenant_id, incident_key)
    if not row:
        raise HTTPException(status_code=404, detail=f"Incident '{incident_key}' not found")
    return _incident_detail_payload(repo, tenant_id, row)


@app.get("/v1/alerts")
def get_alerts(
    tenant_id: str = Query(...),
    asset_id: Optional[str] = None,
    monitor_type: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = Query(100, le=1000),
    session: Session = Depends(session_dep),
) -> dict[str, Any]:
    repo = MetadataRepository(session)
    rows = repo.list_alerts(
        tenant_id,
        asset_id=asset_id,
        monitor_type=monitor_type,
        status=status,
        limit=limit,
    )
    items = [_alert_payload(r) for r in rows]
    return {"items": items, "returned": len(items)}


@app.get("/v1/monitors")
def get_monitors(
    tenant_id: str = Query(...),
    asset_id: Optional[str] = None,
    monitor_type: Optional[str] = None,
    limit: int = Query(100, le=1000),
    session: Session = Depends(session_dep),
) -> dict[str, Any]:
    repo = MetadataRepository(session)
    rows = repo.list_monitors(
        tenant_id,
        asset_id=asset_id,
        monitor_type=monitor_type,
        limit=limit,
    )
    items = [
        {
            "monitor_key": r.monitor_key,
            "monitor_type": r.monitor_type,
            "asset_type": r.asset_type,
            "asset_id": r.asset_id,
            "enabled": r.enabled,
            "name": r.name,
            "config": r.config or {},
        }
        for r in rows
    ]
    return {"items": items, "returned": len(items)}


@app.get("/v1/check-results")
def get_check_results(
    tenant_id: str = Query(...),
    asset_id: Optional[str] = None,
    monitor_type: Optional[str] = None,
    limit: int = Query(100, le=1000),
    session: Session = Depends(session_dep),
) -> dict[str, Any]:
    """Recent monitor outcomes (freshness / volume / schema / distribution)."""
    repo = MetadataRepository(session)
    rows = repo.list_check_results(
        tenant_id,
        asset_id=asset_id,
        monitor_type=monitor_type,
        limit=limit,
    )
    items = [_check_result_payload(r) for r in rows]
    return {"items": items, "returned": len(items)}


@app.get("/v1/lineage")
def get_lineage(
    tenant_id: str = Query(...),
    dataset_id: Optional[str] = None,
    limit: int = Query(200, le=2000),
    session: Session = Depends(session_dep),
) -> dict[str, Any]:
    repo = MetadataRepository(session)
    rows = repo.list_lineage(tenant_id, dataset_id=dataset_id, limit=limit)
    return {
        "items": [
            {
                "upstream_dataset_id": r.upstream_dataset_id,
                "downstream_dataset_id": r.downstream_dataset_id,
                "confidence": r.confidence,
                "transform": r.transform,
                "platform": r.platform,
            }
            for r in rows
        ]
    }


@app.get("/v1/lineage/blast-radius")
def get_blast_radius(
    tenant_id: str = Query(...),
    dataset_id: str = Query(...),
    session: Session = Depends(session_dep),
) -> dict[str, Any]:
    repo = MetadataRepository(session)
    downstream = repo.blast_radius(tenant_id, dataset_id)
    return {"dataset_id": dataset_id, "downstream": downstream, "count": len(downstream)}


@app.get("/v1/connectors")
def list_connectors_legacy() -> dict[str, Any]:
    """Backward-compatible short list; prefer /v1/connectors/catalog."""
    try:
        from connectors.runtime import catalog as conn_catalog
    except ImportError:
        return {"items": []}
    items = []
    for spec in conn_catalog():
        items.append(
            {
                "tool": spec["tool_id"],
                "input": ",".join(spec.get("input_modes") or []),
                "description": spec.get("description"),
                "sample_columns": list((spec.get("config_schema") or {}).get("properties") or {}.keys()),
            }
        )
    return {"items": items}


@app.get("/v1/connectors/catalog")
def connectors_catalog() -> dict[str, Any]:
    """Monte Carlo–style connector catalog with JSON Schema forms."""
    try:
        from connectors.runtime import catalog as conn_catalog
    except ImportError as exc:
        raise HTTPException(
            status_code=500,
            detail="connectors package not installed (pip install -e packages/connectors)",
        ) from exc
    return {"items": conn_catalog()}


def _instance_payload(row: Any) -> dict[str, Any]:
    return {
        "instance_id": row.instance_id,
        "tool_id": row.tool_id,
        "name": row.name,
        "config": row.config or {},
        "secrets_ref": row.secrets_ref or {},
        "status": row.status,
        "last_sync_at": row.last_sync_at.isoformat() if row.last_sync_at else None,
        "last_error": row.last_error,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


class ConnectorInstanceIn(BaseModel):
    tenant_id: str
    tool_id: str
    name: str
    config: dict[str, Any] = Field(default_factory=dict)
    secrets_ref: dict[str, Any] = Field(
        default_factory=dict,
        description="Env var names for secrets, e.g. {\"password_env\": \"SNOWFLAKE_PASSWORD\"}",
    )
    instance_id: Optional[str] = None


class ConnectorInstanceUpdateIn(BaseModel):
    tenant_id: str
    name: Optional[str] = None
    config: Optional[dict[str, Any]] = None
    secrets_ref: Optional[dict[str, Any]] = None


@app.get("/v1/connectors/instances")
def list_connector_instances(
    tenant_id: str = Query(...),
    limit: int = Query(100, le=500),
    session: Session = Depends(session_dep),
) -> dict[str, Any]:
    repo = MetadataRepository(session)
    rows = repo.list_connector_instances(tenant_id, limit=limit)
    return {"items": [_instance_payload(r) for r in rows]}


@app.post("/v1/connectors/instances")
def create_connector_instance(
    body: ConnectorInstanceIn,
    session: Session = Depends(session_dep),
) -> dict[str, Any]:
    try:
        from connectors.runtime import validate_tool
    except ImportError as exc:
        raise HTTPException(status_code=500, detail="connectors package not installed") from exc

    try:
        validate_tool(body.tool_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    import uuid

    instance_id = body.instance_id or f"{body.tool_id}-{uuid.uuid4().hex[:10]}"
    # Merge secrets_ref into config for env key names (password_env etc.) — no secret values
    config = dict(body.config or {})
    for k, v in (body.secrets_ref or {}).items():
        if v is not None and k not in config:
            config[k] = v

    repo = MetadataRepository(session)
    existing = repo.get_connector_instance(body.tenant_id, instance_id)
    if existing:
        raise HTTPException(status_code=409, detail=f"instance_id '{instance_id}' already exists")

    row = repo.create_connector_instance(
        tenant_id=body.tenant_id,
        instance_id=instance_id,
        tool_id=body.tool_id,
        name=body.name,
        config=config,
        secrets_ref=body.secrets_ref or {},
    )
    return _instance_payload(row)


@app.get("/v1/connectors/instances/{instance_id}")
def get_connector_instance(
    instance_id: str,
    tenant_id: str = Query(...),
    session: Session = Depends(session_dep),
) -> dict[str, Any]:
    repo = MetadataRepository(session)
    row = repo.get_connector_instance(tenant_id, instance_id)
    if not row:
        raise HTTPException(status_code=404, detail="Connector instance not found")
    return _instance_payload(row)


@app.put("/v1/connectors/instances/{instance_id}")
def update_connector_instance_api(
    instance_id: str,
    body: ConnectorInstanceUpdateIn,
    session: Session = Depends(session_dep),
) -> dict[str, Any]:
    repo = MetadataRepository(session)
    row = repo.get_connector_instance(body.tenant_id, instance_id)
    if not row:
        raise HTTPException(status_code=404, detail="Connector instance not found")

    config = dict(body.config) if body.config is not None else None
    secrets_ref = dict(body.secrets_ref) if body.secrets_ref is not None else None
    if config is not None and secrets_ref:
        for k, v in secrets_ref.items():
            if v is not None:
                config[k] = v

    row = repo.update_connector_instance(
        row,
        name=body.name,
        config=config,
        secrets_ref=secrets_ref,
        status="updated",
        last_error="",
    )
    return _instance_payload(row)


@app.delete("/v1/connectors/instances/{instance_id}")
def delete_connector_instance_api(
    instance_id: str,
    tenant_id: str = Query(...),
    session: Session = Depends(session_dep),
) -> dict[str, Any]:
    repo = MetadataRepository(session)
    row = repo.get_connector_instance(tenant_id, instance_id)
    if not row:
        raise HTTPException(status_code=404, detail="Connector instance not found")
    repo.delete_connector_instance(row)
    return {"deleted": True, "instance_id": instance_id}


@app.post("/v1/connectors/instances/{instance_id}/test")
def test_connector_instance(
    instance_id: str,
    tenant_id: str = Query(...),
    session: Session = Depends(session_dep),
) -> dict[str, Any]:
    try:
        from connectors.registry import build_context
        from connectors.runtime import test_instance
    except ImportError as exc:
        raise HTTPException(status_code=500, detail="connectors package not installed") from exc

    repo = MetadataRepository(session)
    row = repo.get_connector_instance(tenant_id, instance_id)
    if not row:
        raise HTTPException(status_code=404, detail="Connector instance not found")

    ctx = build_context(
        tenant_id=tenant_id,
        connector_instance_id=instance_id,
        tool_id=row.tool_id,
        config=dict(row.config or {}),
    )
    result = test_instance(ctx)
    repo.update_connector_instance(
        row,
        status="ready" if result.get("ok") else "error",
        last_error=None if result.get("ok") else str(result.get("message") or "test failed"),
    )
    return {"instance_id": instance_id, "result": result}


@app.post("/v1/connectors/instances/{instance_id}/sync")
def sync_connector_instance(
    instance_id: str,
    tenant_id: str = Query(...),
    session: Session = Depends(session_dep),
) -> dict[str, Any]:
    try:
        from connectors.runtime import run_sync_from_config
    except ImportError as exc:
        raise HTTPException(status_code=500, detail="connectors package not installed") from exc

    import uuid

    repo = MetadataRepository(session)
    row = repo.get_connector_instance(tenant_id, instance_id)
    if not row:
        raise HTTPException(status_code=404, detail="Connector instance not found")

    run_id = f"sync-{uuid.uuid4().hex[:12]}"
    sync_row = repo.start_sync_run(
        tenant_id=tenant_id,
        run_id=run_id,
        instance_id=instance_id,
        tool_id=row.tool_id,
    )
    try:
        stats = run_sync_from_config(
            tenant_id=tenant_id,
            connector_instance_id=instance_id,
            tool_id=row.tool_id,
            config=dict(row.config or {}),
        )
        repo.finish_sync_run(
            sync_row,
            status="succeeded",
            envelopes=int(stats.get("envelopes") or 0),
            ingested=int(stats.get("ingested") or 0),
            duplicates=int(stats.get("duplicates") or 0),
            dead_letters=int(stats.get("dead_letters") or 0),
            details={"discover": stats.get("discover")},
        )
        from datetime import datetime

        repo.update_connector_instance(
            row,
            status="synced",
            last_error="",
            last_sync_at=datetime.utcnow(),
        )
        return {"run_id": run_id, "instance_id": instance_id, **stats}
    except Exception as exc:
        repo.finish_sync_run(
            sync_row,
            status="failed",
            error_message=str(exc)[:500],
        )
        repo.update_connector_instance(row, status="error", last_error=str(exc)[:500])
        raise HTTPException(status_code=500, detail=str(exc)[:400]) from exc


@app.post("/v1/connectors/ingest-csv")
async def ingest_connector_csv(
    tool: str = Form(..., description="snowflake or dbt"),
    tenant_id: str = Form("demo"),
    file: UploadFile = File(...),
) -> dict[str, Any]:
    """
    Advanced fallback: Upload a CSV → connector (raw) → normalize → metadata.
    Prefer /v1/connectors/instances for Monte Carlo–style live connections.
    """
    tool_key = tool.strip().lower()
    if tool_key not in {"snowflake", "dbt"}:
        raise HTTPException(status_code=400, detail="tool must be 'snowflake' or 'dbt'")

    try:
        from connectors.runner import ingest_csv
    except ImportError as exc:
        raise HTTPException(
            status_code=500,
            detail="connectors package not installed (pip install -e packages/connectors)",
        ) from exc

    raw_bytes = await file.read()
    try:
        text = raw_bytes.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=400, detail="CSV must be UTF-8") from exc

    if not text.strip():
        raise HTTPException(status_code=400, detail="Empty CSV")

    try:
        stats = ingest_csv(tool_key, text, tenant_id=tenant_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)[:400]) from exc

    stats["filename"] = file.filename
    return stats


@app.get("/v1/catalog")
def catalog() -> dict[str, Any]:
    """Machine-readable list of metadata entities stored in this layer."""
    return {
        "entities": [
            "Tool",
            "Domain",
            "Owner",
            "DataProduct",
            "Pipeline",
            "Task",
            "Execution",
            "Dataset",
            "DatasetColumn",
            "Resource",
            "SLA",
            "Monitor",
            "CheckResult",
            "Metric",
            "LineageEdge",
            "PipelineIO",
            "Alert",
            "Incident",
            "EventLog",
            "ChangeEvent",
            "CostRecord",
            "AssetHealthScore",
            "ConnectorInstance",
            "ConnectorSyncRun",
        ]
    }


def create_app() -> FastAPI:
    return app


if __name__ == "__main__":
    import uvicorn

    init_db()
    uvicorn.run("metadata.api:app", host="0.0.0.0", port=8000, reload=False)
