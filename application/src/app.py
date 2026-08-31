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
from fastapi import BackgroundTasks, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
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
    create_or_update_tool,
    create_pipeline_from_tools,
    delete_monitor,
    delete_dq_rule,
    ensure_tables,
    FreemiumLimitError,
    get_active_pipeline,
    get_connection,
    get_dq_rule,
    get_monitor,
    get_pipeline_by_name,
    get_tool,
    list_dq_rules,
    list_monitors,
    list_pipelines,
    list_tools,
    upsert_monitor,
    upsert_dq_rule,
    upsert_pipeline,
    upsert_tool_secret,
)
from application.src.connectors.registry import (  # noqa: E402
    get_connector,
    list_connector_types,
)
from application.src.connectors.errors import (  # noqa: E402
    classify_snowflake_error,
    parse_dbt_runtime_error,
    vendor_http_exception,
)
from application.src.sync_once import (  # noqa: E402
    connector_kwargs_from_tool,
    run_sync_once,
)
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
    title="ETL Observability API",
    description="""
## How to use (tools-first)

1. **Tools** — configure DB (Snowflake/MySQL/Postgres/Redshift/BigQuery) and ETL/orchestrator (dbt/Airbyte/Airflow) once via `/v1/tools`
2. **Pipelines** — compose with `/v1/pipelines/from-tools` (pick source + etl + target tool IDs)
3. **Sync** — `/v1/sync` collects ETL per pipeline; DB snapshots are reused across pipelines

Legacy: `/v1/pipelines` still creates from named templates (`stock_etl`, `ecommerce_etl`, `hr_etl`).

**Metadata DB** must be local in dev (`DB_HOST=127.0.0.1`).
Tool secrets are stored **encrypted in MySQL** (`obs_secrets`); only `SECRETS_MASTER_KEY` stays in env.

Dashboard read APIs live under `/api/v1/*`.
""".strip(),
    version="0.6.1",
    openapi_tags=[
        {
            "name": "System",
            "description": "Health and service probes",
        },
        {
            "name": "1. Tools",
            "description": (
                "Reusable connectors (database + ETL). "
                "Create once, reuse across many pipelines."
            ),
        },
        {
            "name": "2. Pipelines",
            "description": (
                "Compose pipelines from tools, or create from legacy templates. "
                "List and inspect registered pipelines."
            ),
        },
        {
            "name": "3. Sync",
            "description": "Manual collect: ETL per pipeline; DB tool snapshots shared by TTL",
        },
        {
            "name": "4. Webhooks",
            "description": "dbt Cloud webhooks that trigger Sync",
        },
        {
            "name": "5. Integrations",
            "description": "Grafana dashboard upsert and legacy overview helpers",
        },
        {
            "name": "Dashboard / Health & filters",
            "description": "`/api/v1` health + shared filter catalog for UI dropdowns",
        },
        {
            "name": "Dashboard / Overview",
            "description": "Overview page: full payload, KPIs, charts, health pillars, recent incidents",
        },
        {
            "name": "Dashboard / Pipelines",
            "description": "Pipeline catalog, list, detail, runs, and bindings",
        },
        {
            "name": "Dashboard / Observability",
            "description": "Freshness, volume, quality, schema drift pages",
        },
        {
            "name": "Dashboard / Lineage",
            "description": "Lineage graph and per-pipeline hops",
        },
        {
            "name": "Dashboard / Incidents & alerts",
            "description": "Incidents and alerts for the UI",
        },
        {
            "name": "Dashboard / Metrics & logs",
            "description": "Metrics page, execution logs, and single-run detail",
        },
        {
            "name": "Dashboard / Ops",
            "description": "Ops actions: evaluate monitors, rollups, purge, migrate bindings",
        },
        {
            "name": "Dashboard / Tools catalog",
            "description": "Read-only tool/connector catalog for the UI (create tools via `/v1/tools`)",
        },
    ],
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


@app.get(
    "/",
    tags=["System"],
    summary="Root",
    description="Service probe with docs/health/webhook URL hints.",
)
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


class CreatePipelineRequest(BaseModel):
    pipeline_id: str | None = Field(
        default=None,
        description="Omit to create a new UUID (stored in DB)",
        examples=[None],
    )
    pipeline_name: str | None = Field(
        default="stock_etl",
        description="Template name: stock_etl | ecommerce_etl | hr_etl",
        examples=["stock_etl"],
    )
    make_active: bool = Field(
        default=True,
        description="If true, this pipeline becomes the Sync default",
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "pipeline_name": "hr_etl",
                    "make_active": True,
                }
            ]
        }
    }


class CreateToolRequest(BaseModel):
    name: str = Field(..., description="Display name for the tool", examples=["sf-raw-source"])
    connector_type: str = Field(
        ...,
        description=(
            "snowflake | mysql | postgres | redshift | bigquery | "
            "dbt | dbt_cloud | airbyte | airflow"
        ),
        examples=["snowflake"],
    )
    kind: str | None = Field(
        default=None,
        description="database | etl | orchestrator (inferred from connector_type if omitted)",
        examples=["database"],
    )
    secret: str | None = Field(
        default=None,
        description=(
            "Plaintext password/token. Encrypted with SECRETS_MASTER_KEY and stored in "
            "obs_secrets. Never returned by GET APIs."
        ),
    )
    secret_name: str = Field(
        default="default",
        description="Logical secret slot name (default | password | api_token)",
    )
    auth_ref: str | None = Field(
        default=None,
        description="Optional legacy env var name fallback if no DB secret",
        examples=[None],
    )
    config: dict[str, Any] = Field(
        default_factory=dict,
        description="Non-secret connector config (account, schema, job_id, …)",
    )
    tool_id: str | None = Field(
        default=None, description="Omit to mint a new tool id"
    )
    connection_id: str | None = Field(
        default=None, description="Optional parent connection id"
    )
    tenant_id: str | None = Field(default="demo")

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "name": "sf-analytics-raw",
                    "connector_type": "snowflake",
                    "kind": "database",
                    "secret": "my-snowflake-password",
                    "config": {
                        "account_id": "xy12345.us-east-1",
                        "user_id": "OBS_USER",
                        "warehouse_id": "COMPUTE_WH",
                        "database_id": "ANALYTICS_DB",
                        "schema": "RAW",
                        "tables": ["RAW_ORDERS"],
                        "sf_role": "ACCOUNTADMIN",
                    },
                },
                {
                    "name": "dbt-orders-job",
                    "connector_type": "dbt",
                    "kind": "etl",
                    "secret": "dbt-cloud-api-token-value",
                    "config": {
                        "account_id": "12345",
                        "project_id": "67890",
                        "job_id": "111",
                        "project_name": "analytics",
                        "api_base": "https://cloud.getdbt.com/api/v2",
                    },
                },
            ]
        }
    }


class UpsertToolSecretRequest(BaseModel):
    secret: str = Field(..., description="Plaintext to encrypt and store")
    secret_name: str = Field(default="default")


class ComposePipelineRequest(BaseModel):
    pipeline_name: str = Field(..., examples=["orders_etl"])
    source_tool_id: str | None = Field(default=None, description="Database tool id (SOURCE) — legacy single")
    etl_tool_id: str = Field(..., description="ETL tool id (dbt)")
    target_tool_id: str | None = Field(default=None, description="Database tool id (TARGET) — legacy single")
    source_tool_ids: list[str] | None = Field(default=None, description="Multiple SOURCE database tools")
    target_tool_ids: list[str] | None = Field(default=None, description="Multiple TARGET database tools")
    pipeline_id: str | None = Field(
        default=None, description="Omit to mint a UUID"
    )
    make_active: bool = True
    description: str | None = None
    tenant_id: str | None = "demo"

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "pipeline_name": "orders_etl",
                    "source_tool_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
                    "etl_tool_id": "ffffffff-1111-2222-3333-444444444444",
                    "target_tool_id": "55555555-6666-7777-8888-999999999999",
                    "make_active": True,
                }
            ]
        }
    }


class CreateMonitorRequest(BaseModel):
    pipeline_id: str = Field(..., description="Pipeline this monitor belongs to")
    name: str | None = Field(default=None, description="Display name")
    monitor_kind: str = Field(
        ...,
        description=(
            "freshness | volume_drop | pipeline_failure | dbt_test_failure | "
            "null_check | unique_check | duplicate_check | custom_sql"
        ),
    )
    config: dict[str, Any] = Field(default_factory=dict, description="Monitor config JSON")
    tags: list[str] | None = Field(default=None, description="Optional tags")
    dimension: str | None = Field(default=None, description="DQ dimension override")
    monitor_type: str | None = Field(default=None, description="validation | freshness | volume | custom_sql")
    dataset_id: str | None = Field(default=None, description="DB.SCHEMA.TABLE for SQL monitors")
    column_name: str | None = Field(default=None, description="Column for null/unique checks")
    is_enabled: bool = True
    monitor_id: str | None = Field(default=None, description="Omit to mint UUID")


class UpdateMonitorRequest(BaseModel):
    name: str | None = None
    monitor_kind: str | None = None
    config: dict[str, Any] | None = None
    tags: list[str] | None = None
    dimension: str | None = None
    monitor_type: str | None = None
    dataset_id: str | None = None
    column_name: str | None = None
    is_enabled: bool | None = None


class CreateDqRuleRequest(BaseModel):
    pipeline_id: str
    rule_name: str | None = None
    rule_type: str = Field(..., description="NOT_NULL | UNIQUE | DUPLICATE | ACCEPTED_VALUES | RANGE | CUSTOM_SQL")
    dataset_id: str | None = None
    column_name: str | None = None
    dimension: str | None = None
    severity: str | None = "high"
    config: dict[str, Any] = Field(default_factory=dict)
    tags: list[str] | None = None
    is_enabled: bool = True
    evaluation_trigger: str = Field(default="poller", description="poller | sync | both")
    rule_id: str | None = None


class UpdateDqRuleRequest(BaseModel):
    rule_name: str | None = None
    rule_type: str | None = None
    dataset_id: str | None = None
    column_name: str | None = None
    dimension: str | None = None
    severity: str | None = None
    config: dict[str, Any] | None = None
    tags: list[str] | None = None
    is_enabled: bool | None = None
    evaluation_trigger: str | None = None


class SyncRequest(BaseModel):
    pipeline_id: str | None = Field(default=None, description="Preferred: sync this pipeline id")
    pipeline_name: str | None = Field(default=None, description="Or sync by name")
    dbt_run_id: str | None = Field(
        default=None, description="Optional exact dbt run id (no silent latest fallback)"
    )
    refresh_db: bool = Field(
        default=False,
        description="If true, force DB tool re-pull (ignore snapshot TTL)",
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {"pipeline_name": "orders_etl"},
                {"pipeline_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee", "refresh_db": False},
            ]
        }
    }


_INVALID_PIPELINE_ID_PLACEHOLDERS = {
    "",
    "string",
    "null",
    "none",
    "undefined",
    "nan",
    "uuid",
    "id",
    "pipeline_id",
    "example",
    "test",
}


def _validate_pipeline_id_or_mint(raw: str | None) -> str:
    """Reject OpenAPI/Swagger placeholders; mint UUID when omitted. Keep real UUIDs."""
    import re
    import uuid as _uuid

    text = (raw or "").strip()
    if not text:
        return new_pipeline_id()
    if text.lower() in _INVALID_PIPELINE_ID_PLACEHOLDERS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Invalid pipeline_id={text!r}. Omit pipeline_id to auto-mint a UUID, "
                "or pass a real UUID (not a placeholder like 'string')."
            ),
        )
    # Accept existing UUID pipelines; also allow already-stored non-UUID ids that look intentional
    try:
        return str(_uuid.UUID(text))
    except ValueError:
        # Non-UUID but not a known placeholder — allow if alphanumeric/dash/underscore (legacy)
        if re.fullmatch(r"[A-Za-z0-9_.:-]{8,64}", text):
            return text
        raise HTTPException(
            status_code=400,
            detail=(
                f"Invalid pipeline_id={text!r}. Expected a UUID or omit for auto-mint."
            ),
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


def _raise_vendor_sync_error(exc: Exception) -> None:
    msg = str(exc).lower()
    vendor = "snowflake" if "snowflake" in msg or "390913" in msg else "dbt"
    status, body = vendor_http_exception(exc, vendor=vendor)
    raise HTTPException(status_code=status, detail=body) from exc


def _run_sync_background(*, pipeline_name: str | None, dbt_run_id: str | None) -> None:
    try:
        run_sync_once(pipeline_name=pipeline_name, dbt_run_id=dbt_run_id)
    except Exception as exc:
        print("WEBHOOK background sync failed:", exc)


def _handle_dbt_webhook(
    payload: dict,
    *,
    pipeline_name: str | None = None,
    background_tasks: BackgroundTasks | None = None,
):
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

    if background_tasks is not None:
        background_tasks.add_task(
            _run_sync_background,
            pipeline_name=name,
            dbt_run_id=run_id,
        )
        return JSONResponse(
            status_code=202,
            content={
                "accepted": True,
                "pipeline_name": name,
                "run_id": run_id,
                "status": "accepted",
            },
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
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        _raise_vendor_sync_error(exc)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get(
    "/health",
    tags=["System"],
    summary="Health",
    description="Liveness plus active pipeline and webhook URLs.",
)
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


@app.get(
    "/v1/pipelines/templates",
    tags=["2. Pipelines"],
    summary="List pipeline templates",
    description="Built-in template names for legacy `POST /v1/pipelines`.",
)
def pipelines_templates() -> dict:
    return {"ok": True, "templates": list_pipeline_templates()}


@app.get(
    "/v1/tools/types",
    tags=["1. Tools"],
    summary="List connector types",
    description="Supported plugin types: snowflake, mysql, dbt.",
)
def tools_types() -> dict:
    return {"ok": True, "items": list_connector_types()}


@app.get(
    "/v1/tools",
    tags=["1. Tools"],
    summary="List tools",
    description="Reusable tools. Filter with `?kind=database|etl` or `?connector_type=`.",
)
def tools_list(
    kind: str | None = Query(default=None, description="database | etl"),
    connector_type: str | None = Query(default=None),
) -> dict:
    try:
        return {
            "ok": True,
            "items": list_tools(kind=kind, connector_type=connector_type),
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get(
    "/v1/tools/{tool_id}",
    tags=["1. Tools"],
    summary="Get tool",
    description="Tool detail (config without secrets).",
)
def tools_get(tool_id: str) -> dict:
    tool = get_tool(tool_id)
    if not tool:
        raise HTTPException(status_code=404, detail=f"Tool not found: {tool_id}")
    return {"ok": True, "tool": tool}


@app.post(
    "/v1/tools",
    tags=["1. Tools"],
    summary="Create or update tool",
    description=(
        "Register a reusable database or ETL tool. "
        "Pass `secret` (password/token); it is Fernet-encrypted into `obs_secrets`. "
        "Plaintext is never stored in config_json or returned by GET."
    ),
)
def tools_create(body: CreateToolRequest) -> dict:
    try:
        return create_or_update_tool(
            name=body.name,
            connector_type=body.connector_type,
            config=body.config,
            kind=body.kind,
            auth_ref=body.auth_ref,
            secret=body.secret,
            secret_name=body.secret_name,
            tool_id=body.tool_id,
            connection_id=body.connection_id,
            tenant_id=body.tenant_id,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.put(
    "/v1/tools/{tool_id}/secret",
    tags=["1. Tools"],
    summary="Rotate / set tool secret",
    description="Encrypt and upsert secret for an existing tool (does not return plaintext).",
)
def tools_set_secret(tool_id: str, body: UpsertToolSecretRequest) -> dict:
    tool = get_tool(tool_id)
    if not tool:
        raise HTTPException(status_code=404, detail=f"Tool not found: {tool_id}")
    try:
        return upsert_tool_secret(
            tool_id, body.secret, secret_name=body.secret_name or "default"
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post(
    "/v1/tools/{tool_id}/test",
    tags=["1. Tools"],
    summary="Test tool connection",
    description="Runs `test_connection()` for the stored tool config + env secret.",
)
def tools_test(tool_id: str) -> dict:
    tool = get_tool(tool_id)
    if not tool:
        raise HTTPException(status_code=404, detail=f"Tool not found: {tool_id}")
    try:
        kwargs = connector_kwargs_from_tool(
            tool, tenant_id=str(tool.get("config", {}).get("tenant_id") or "demo")
        )
        connector = get_connector(tool.get("connector_type") or "", **kwargs)
        result = connector.test_connection()
        if not result.get("ok"):
            msg = str(result.get("message") or "")
            ctype = str(tool.get("connector_type") or "").lower()
            if ctype == "snowflake":
                err = classify_snowflake_error(msg)
            elif ctype == "dbt":
                err = parse_dbt_runtime_error(msg)
            else:
                err = {"error_code": "connection_failed", "error_hint": msg, "detail": msg}
            return {
                "ok": False,
                "tool_id": tool_id,
                "result": result,
                **err,
            }
        return {"ok": True, "tool_id": tool_id, "result": result}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get(
    "/v1/monitors",
    tags=["2. Pipelines"],
    summary="List monitors",
    description="DQ / operational monitors for pipelines. Filter by pipeline_id or monitor_kind.",
)
def monitors_list(
    pipeline_id: str | None = Query(default=None),
    monitor_kind: str | None = Query(default=None),
    include_disabled: bool = Query(default=True),
) -> dict:
    conn = get_connection()
    try:
        ensure_tables(conn)
        items = list_monitors(
            conn,
            pipeline_id=pipeline_id,
            monitor_kind=monitor_kind,
            include_disabled=include_disabled,
        )
        return {"ok": True, "items": items, "total": len(items)}
    finally:
        conn.close()


@app.get(
    "/v1/monitors/{monitor_id}",
    tags=["2. Pipelines"],
    summary="Get monitor",
)
def monitors_get(monitor_id: str) -> dict:
    conn = get_connection()
    try:
        ensure_tables(conn)
        item = get_monitor(conn, monitor_id)
        if not item:
            raise HTTPException(status_code=404, detail=f"Monitor not found: {monitor_id}")
        return {"ok": True, "monitor": item}
    finally:
        conn.close()


@app.post(
    "/v1/monitors",
    tags=["2. Pipelines"],
    summary="Create monitor",
    description="Create a DQ or operational monitor. Evaluated on poller tick or POST /api/v1/ops/evaluate-monitors.",
)
def monitors_create(body: CreateMonitorRequest) -> dict:
    conn = get_connection()
    try:
        ensure_tables(conn)
        mid = upsert_monitor(
            conn,
            {
                "monitor_id": body.monitor_id,
                "pipeline_id": body.pipeline_id,
                "name": body.name,
                "monitor_kind": body.monitor_kind,
                "config": body.config,
                "tags": body.tags,
                "dimension": body.dimension,
                "monitor_type": body.monitor_type,
                "dataset_id": body.dataset_id,
                "column_name": body.column_name,
                "is_enabled": body.is_enabled,
            },
        )
        item = get_monitor(conn, mid)
        return {"ok": True, "monitor_id": mid, "monitor": item}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        conn.close()


@app.put(
    "/v1/monitors/{monitor_id}",
    tags=["2. Pipelines"],
    summary="Update monitor",
)
def monitors_update(monitor_id: str, body: UpdateMonitorRequest) -> dict:
    conn = get_connection()
    try:
        ensure_tables(conn)
        existing = get_monitor(conn, monitor_id)
        if not existing:
            raise HTTPException(status_code=404, detail=f"Monitor not found: {monitor_id}")
        payload = {
            "monitor_id": monitor_id,
            "pipeline_id": existing["pipeline_id"],
            "name": body.name if body.name is not None else existing.get("name"),
            "monitor_kind": body.monitor_kind or existing.get("monitor_kind"),
            "config": body.config if body.config is not None else existing.get("config"),
            "tags": body.tags if body.tags is not None else existing.get("tags"),
            "dimension": body.dimension if body.dimension is not None else existing.get("dimension"),
            "monitor_type": body.monitor_type if body.monitor_type is not None else existing.get("monitor_type"),
            "dataset_id": body.dataset_id if body.dataset_id is not None else existing.get("dataset_id"),
            "column_name": body.column_name if body.column_name is not None else existing.get("column_name"),
            "is_enabled": body.is_enabled if body.is_enabled is not None else existing.get("is_enabled"),
        }
        upsert_monitor(conn, payload)
        item = get_monitor(conn, monitor_id)
        return {"ok": True, "monitor_id": monitor_id, "monitor": item}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        conn.close()


@app.delete(
    "/v1/monitors/{monitor_id}",
    tags=["2. Pipelines"],
    summary="Disable monitor",
    description="Soft-disables monitor (is_enabled=0). Pass ?hard=true to delete row.",
)
def monitors_delete(
    monitor_id: str,
    hard: bool = Query(default=False),
) -> dict:
    conn = get_connection()
    try:
        ensure_tables(conn)
        if not get_monitor(conn, monitor_id):
            raise HTTPException(status_code=404, detail=f"Monitor not found: {monitor_id}")
        ok = delete_monitor(conn, monitor_id, hard=hard)
        return {"ok": ok, "monitor_id": monitor_id, "deleted": hard, "disabled": not hard}
    finally:
        conn.close()


@app.get(
    "/v1/dq-rules",
    tags=["2. Pipelines"],
    summary="List DQ rules",
    description="Declarative DQ rules evaluated on poller (obs_dq_rules).",
)
def dq_rules_list(
    pipeline_id: str | None = Query(default=None),
    include_disabled: bool = Query(default=True),
) -> dict:
    conn = get_connection()
    try:
        ensure_tables(conn)
        items = list_dq_rules(conn, pipeline_id=pipeline_id, include_disabled=include_disabled)
        return {"ok": True, "items": items, "total": len(items)}
    finally:
        conn.close()


@app.get(
    "/v1/dq-rules/{rule_id}",
    tags=["2. Pipelines"],
    summary="Get DQ rule",
)
def dq_rules_get(rule_id: str) -> dict:
    conn = get_connection()
    try:
        ensure_tables(conn)
        item = get_dq_rule(conn, rule_id)
        if not item:
            raise HTTPException(status_code=404, detail=f"DQ rule not found: {rule_id}")
        return {"ok": True, "rule": item}
    finally:
        conn.close()


@app.post(
    "/v1/dq-rules",
    tags=["2. Pipelines"],
    summary="Create DQ rule",
)
def dq_rules_create(body: CreateDqRuleRequest) -> dict:
    conn = get_connection()
    try:
        ensure_tables(conn)
        rid = upsert_dq_rule(
            conn,
            {
                "rule_id": body.rule_id,
                "pipeline_id": body.pipeline_id,
                "rule_name": body.rule_name,
                "rule_type": body.rule_type,
                "dataset_id": body.dataset_id,
                "column_name": body.column_name,
                "dimension": body.dimension,
                "severity": body.severity,
                "config": body.config,
                "tags": body.tags,
                "is_enabled": body.is_enabled,
                "evaluation_trigger": body.evaluation_trigger,
            },
        )
        item = get_dq_rule(conn, rid)
        return {"ok": True, "rule_id": rid, "rule": item}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        conn.close()


@app.put(
    "/v1/dq-rules/{rule_id}",
    tags=["2. Pipelines"],
    summary="Update DQ rule",
)
def dq_rules_update(rule_id: str, body: UpdateDqRuleRequest) -> dict:
    conn = get_connection()
    try:
        ensure_tables(conn)
        existing = get_dq_rule(conn, rule_id)
        if not existing:
            raise HTTPException(status_code=404, detail=f"DQ rule not found: {rule_id}")
        payload = {
            "rule_id": rule_id,
            "pipeline_id": existing["pipeline_id"],
            "rule_name": body.rule_name if body.rule_name is not None else existing.get("rule_name"),
            "rule_type": body.rule_type or existing.get("rule_type"),
            "dataset_id": body.dataset_id if body.dataset_id is not None else existing.get("dataset_id"),
            "column_name": body.column_name if body.column_name is not None else existing.get("column_name"),
            "dimension": body.dimension if body.dimension is not None else existing.get("dimension"),
            "severity": body.severity if body.severity is not None else existing.get("severity"),
            "config": body.config if body.config is not None else existing.get("config"),
            "tags": body.tags if body.tags is not None else existing.get("tags"),
            "is_enabled": body.is_enabled if body.is_enabled is not None else existing.get("is_enabled"),
            "evaluation_trigger": body.evaluation_trigger if body.evaluation_trigger is not None else existing.get("evaluation_trigger"),
        }
        upsert_dq_rule(conn, payload)
        item = get_dq_rule(conn, rule_id)
        return {"ok": True, "rule_id": rule_id, "rule": item}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        conn.close()


@app.delete(
    "/v1/dq-rules/{rule_id}",
    tags=["2. Pipelines"],
    summary="Disable DQ rule",
)
def dq_rules_delete(rule_id: str, hard: bool = Query(default=False)) -> dict:
    conn = get_connection()
    try:
        ensure_tables(conn)
        if not get_dq_rule(conn, rule_id):
            raise HTTPException(status_code=404, detail=f"DQ rule not found: {rule_id}")
        ok = delete_dq_rule(conn, rule_id, hard=hard)
        return {"ok": ok, "rule_id": rule_id, "deleted": hard, "disabled": not hard}
    finally:
        conn.close()


@app.post(
    "/v1/pipelines/from-tools",
    tags=["2. Pipelines"],
    summary="Compose pipeline from tools",
    description=(
        "Preferred create path: pick `source_tool_id` + `etl_tool_id` + `target_tool_id`. "
        "Writes bindings and derived config_json."
    ),
)
def pipelines_from_tools(body: ComposePipelineRequest) -> dict:
    try:
        pipeline_id = _validate_pipeline_id_or_mint(body.pipeline_id)
        source_ids = list(body.source_tool_ids or [])
        target_ids = list(body.target_tool_ids or [])
        if body.source_tool_id:
            source_ids = [body.source_tool_id] + [x for x in source_ids if x != body.source_tool_id]
        if body.target_tool_id:
            target_ids = [body.target_tool_id] + [x for x in target_ids if x != body.target_tool_id]
        if not source_ids or not target_ids:
            raise ValueError("Provide source_tool_id/source_tool_ids and target_tool_id/target_tool_ids")
        return create_pipeline_from_tools(
            pipeline_name=body.pipeline_name,
            source_tool_ids=source_ids,
            etl_tool_id=body.etl_tool_id,
            target_tool_ids=target_ids,
            pipeline_id=pipeline_id,
            make_active=body.make_active,
            description=body.description,
            tenant_id=body.tenant_id,
        )
    except FreemiumLimitError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get(
    "/v1/pipelines",
    tags=["2. Pipelines"],
    summary="List pipelines",
)
def pipelines_list() -> dict:
    return {"ok": True, "pipelines": list_pipelines()}


@app.get(
    "/v1/pipelines/current",
    tags=["2. Pipelines"],
    summary="Get Sync-default pipeline",
    description="Pipeline marked `is_active` (Sync default when no id/name given).",
)
def get_current_pipeline() -> dict:
    active = get_active_pipeline()
    if not active:
        raise HTTPException(status_code=404, detail="No pipeline in DB. POST /v1/pipelines first.")
    return active


@app.post(
    "/v1/pipelines",
    tags=["2. Pipelines"],
    summary="Create pipeline from template (legacy)",
    description=(
        "Legacy create from named template (`stock_etl` | `ecommerce_etl` | `hr_etl`). "
        "Prefer `POST /v1/pipelines/from-tools` for tools-first compose."
    ),
)
def create_pipeline(body: CreatePipelineRequest | None = None) -> dict:
    """
    Create/update a pipeline in DB from a known template.

    Templates:
      stock_etl      — ANALYTICS_DB.RAW -> dbt -> STAGING_STAGING
      ecommerce_etl  — ECOMMERCE.SRC_DATA -> dbt (eg250) -> CLEAN_DATA
      hr_etl         — HR_ANALYTICS.RAW_DATA -> dbt (eg250) -> FINAL_DATA
    """
    body = body or CreatePipelineRequest()
    pipeline_id = _validate_pipeline_id_or_mint(body.pipeline_id)
    pipeline_name = (body.pipeline_name or "stock_etl").strip()
    pipeline = get_pipeline_template(pipeline_name, pipeline_id=pipeline_id)
    pipeline["pipeline_name"] = pipeline_name
    from application.src.store.meta_mysql import (
        FreemiumLimitError,
        freemium_max_pipelines,
        get_connection,
        get_pipeline_by_id,
    )

    try:
        existing = get_pipeline_by_id(pipeline_id)
        if not existing:
            conn = get_connection()
            try:
                with conn.cursor() as cur:
                    cur.execute("SELECT COUNT(*) AS n FROM obs_pipelines")
                    n = int((cur.fetchone() or {}).get("n") or 0)
                if n >= freemium_max_pipelines():
                    raise FreemiumLimitError(
                        f"Pipeline limit reached ({freemium_max_pipelines()}). "
                        "Raise FREEMIUM_MAX_PIPELINES or remove unused pipelines."
                    )
            finally:
                conn.close()
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
    except FreemiumLimitError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post(
    "/v1/sync",
    tags=["3. Sync"],
    summary="Sync pipeline once",
    description=(
        "Collect ETL run (always) + DB assets (reuse tool snapshots within TTL unless "
        "`refresh_db=true`). Pass `pipeline_id` or `pipeline_name`, or omit for Sync-default."
    ),
)
def sync_manual(body: SyncRequest | None = None) -> dict:
    """Manual Sync — loads active pipeline from DB (or pipeline_id / pipeline_name)."""
    body = body or SyncRequest()
    try:
        return run_sync_once(
            pipeline_id=body.pipeline_id,
            pipeline_name=body.pipeline_name,
            dbt_run_id=body.dbt_run_id,
            refresh_db=bool(body.refresh_db),
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        _raise_vendor_sync_error(exc)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get(
    "/v1/dashboard/overview",
    tags=["5. Integrations"],
    summary="Legacy dashboard overview",
    description="Prefer `/api/v1/overview` for the versioned dashboard contract.",
)
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


@app.post(
    "/grafana/dashboard",
    tags=["5. Integrations"],
    summary="Upsert Grafana dashboard",
    description="Requires GRAFANA_URL + GRAFANA_TOKEN in .env.",
)
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


@app.post(
    "/webhooks/dbt",
    tags=["4. Webhooks"],
    summary="dbt webhook (active or ?pipeline_name=)",
    response_model=None,
)
def dbt_webhook(
    payload: dict,
    background_tasks: BackgroundTasks,
    pipeline_name: str | None = Query(
        default=None,
        description="Optional pipeline name; omit to Sync the active pipeline",
    ),
):
    """dbt Cloud webhook → Sync active pipeline (or ?pipeline_name=...)."""
    return _handle_dbt_webhook(
        payload, pipeline_name=pipeline_name, background_tasks=background_tasks
    )


@app.post(
    "/webhooks/dbt/{pipeline_name}",
    tags=["4. Webhooks"],
    summary="dbt webhook for named pipeline",
    response_model=None,
)
def dbt_webhook_for_pipeline(
    pipeline_name: str,
    payload: dict,
    background_tasks: BackgroundTasks,
):
    """
    dbt Cloud webhook for one named pipeline.

    Examples (production):
      https://etl-pipeline-lemon.vercel.app/webhooks/dbt/stock_etl
      https://etl-pipeline-lemon.vercel.app/webhooks/dbt/ecommerce_etl
      https://etl-pipeline-lemon.vercel.app/webhooks/dbt/hr_etl
    """
    return _handle_dbt_webhook(
        payload, pipeline_name=pipeline_name, background_tasks=background_tasks
    )


def _resolve_pipeline_for_openlineage(pipeline_name: str | None) -> tuple[str | None, str | None]:
    """Return (pipeline_id, pipeline_name) for OpenLineage ingest."""
    name = (pipeline_name or "").strip() or None
    if name:
        known = get_pipeline_by_name(name)
        if known:
            return str(known.get("pipeline_id") or ""), name
        templates = set(list_pipeline_templates())
        if name.lower() not in templates:
            raise HTTPException(
                status_code=404,
                detail=f"Unknown pipeline_name={name}. Register pipeline first.",
            )
        return None, name
    active = get_active_pipeline()
    if active:
        return str(active.get("pipeline_id") or ""), str(active.get("pipeline_name") or "")
    return None, None


def _ingest_openlineage_background(payload: dict, *, pipeline_id: str | None) -> None:
    from application.src.store.meta_mysql import ensure_tables, get_connection, store_openlineage_event

    conn = get_connection()
    try:
        ensure_tables(conn)
        result = store_openlineage_event(conn, payload=payload, pipeline_id=pipeline_id)
        print("OpenLineage ingest:", result)
    except Exception as exc:
        print("OpenLineage ingest error:", exc)
    finally:
        conn.close()


def _handle_openlineage_webhook(
    payload: dict,
    *,
    pipeline_name: str | None = None,
    background_tasks: BackgroundTasks | None = None,
):
    pid, pname = _resolve_pipeline_for_openlineage(pipeline_name)
    print("WEBHOOK openlineage pipeline=", pname or pid or "(none)")

    if background_tasks is not None:
        background_tasks.add_task(
            _ingest_openlineage_background,
            payload or {},
            pipeline_id=pid,
        )
        return JSONResponse(
            status_code=202,
            content={
                "accepted": True,
                "pipeline_id": pid,
                "pipeline_name": pname,
                "status": "accepted",
            },
        )

    from application.src.store.meta_mysql import ensure_tables, get_connection, store_openlineage_event

    conn = get_connection()
    try:
        ensure_tables(conn)
        return store_openlineage_event(conn, payload=payload or {}, pipeline_id=pid)
    finally:
        conn.close()


@app.post(
    "/webhooks/openlineage",
    tags=["4. Webhooks"],
    summary="OpenLineage webhook (active or ?pipeline_name=)",
    response_model=None,
)
def openlineage_webhook(
    payload: dict,
    background_tasks: BackgroundTasks,
    pipeline_name: str | None = Query(default=None),
):
    """OpenLineage RUN/COMPLETE → obs_lineage_edges (+ optional event archive)."""
    return _handle_openlineage_webhook(
        payload, pipeline_name=pipeline_name, background_tasks=background_tasks
    )


@app.post(
    "/webhooks/openlineage/{pipeline_name}",
    tags=["4. Webhooks"],
    summary="OpenLineage webhook for named pipeline",
    response_model=None,
)
def openlineage_webhook_for_pipeline(
    pipeline_name: str,
    payload: dict,
    background_tasks: BackgroundTasks,
):
    return _handle_openlineage_webhook(
        payload, pipeline_name=pipeline_name, background_tasks=background_tasks
    )
