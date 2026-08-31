"""
/api/v1 Observability dashboard routes — stable contracts for the VITHI UI.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query

from application.src.api.schemas import make_kpi
from application.src.services.observability.filters import (
    build_filter_catalog,
    build_run_where,
    envelope,
    fetchall,
    fetchone,
    format_duration,
    json_val,
    list_filter_pipelines,
    num,
    parse_range,
)
from application.src.services.observability.freshness import (
    build_freshness_page,
    load_pipeline_freshness,
)
from application.src.services.observability.incidents import (
    build_incidents_page,
    get_incident,
    list_derived_incidents,
)
from application.src.services.observability.lineage import (
    build_lineage_detail,
    build_lineage_page,
)
from application.src.services.observability.metrics import build_metrics_page
from application.src.services.observability.quality import build_quality_page
from application.src.services.observability.rca_context import build_rca_context
from application.src.services.observability.overview import (
    build_overview,
    build_overview_charts,
    build_overview_health,
    build_overview_kpis,
    build_pipeline_detail,
    build_pipeline_monitoring,
    build_pipeline_runs,
    build_pipelines_list,
)
from application.src.services.observability.schema_diff import build_schema_page
from application.src.services.observability.volume import build_volume_page
from application.src.store.meta_mysql import get_connection as db_connect, list_collector_heartbeats

router = APIRouter()


def _conn():
    return db_connect()


def _common_filters(
    preset: Optional[str],
    start_date: Optional[str],
    end_date: Optional[str],
    start_time: Optional[str],
    end_time: Optional[str],
    pipeline_name: Optional[str],
    pipeline_id: Optional[str],
    status: Optional[str],
    tool: Optional[str],
) -> dict[str, Any]:
    return dict(
        preset=preset,
        start_date=start_date,
        end_date=end_date,
        start_time=start_time,
        end_time=end_time,
        pipeline_name=pipeline_name,
        pipeline_id=pipeline_id,
        status=status,
        tool=tool,
    )


# Shared Query descriptions
_P = "Comma-separated pipeline name(s)"
_PID = "Comma-separated pipeline id(s)"
_ST = "Comma-separated status filter"
_TOOL = "Comma-separated tool_name filter"
_PRE = "Range preset: 15m | 24h | 7d | 30d | all (default 24h)"
_SD = "Start date YYYY-MM-DD"
_ED = "End date YYYY-MM-DD"


# =============================================================================
# Health
# =============================================================================

@router.get("/health", tags=["Dashboard / Health & filters"], summary="API & DB health", description="Checks API process and metadata MySQL connectivity.")
def api_v1_health() -> dict[str, Any]:
    conn = _conn()
    try:
        fetchone(conn, "SELECT 1 AS ok")
        collectors_raw = list_collector_heartbeats(conn)
        try:
            interval = int(os.getenv("SYNC_INTERVAL_SECONDS") or "300")
        except ValueError:
            interval = 300
        stale_seconds = 2 * interval
        now = datetime.utcnow()
        degraded = False
        collectors: list[dict[str, Any]] = []
        for row in collectors_raw:
            last = row.get("last_success_at")
            stale = False
            age_seconds: float | None = None
            if isinstance(last, datetime):
                age_seconds = (now - last).total_seconds()
                stale = age_seconds > stale_seconds
            elif last is None:
                stale = True
            if stale:
                degraded = True
            collectors.append(
                {
                    "pipeline_id": row.get("pipeline_id"),
                    "pipeline_name": row.get("pipeline_name"),
                    "collector": row.get("collector"),
                    "last_success_at": json_val(last),
                    "last_error": row.get("last_error"),
                    "stale": stale,
                    "age_seconds": round(age_seconds, 1) if age_seconds is not None else None,
                }
            )
        return {
            "ok": True,
            "status": "degraded" if degraded else "ok",
            "degraded": degraded,
            "database": "connected",
            "collectors": collectors,
            "collector_stale_after_seconds": stale_seconds,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database unavailable: {e}") from e
    finally:
        conn.close()


# =============================================================================
# Filter lookups (status/tool/presets; pipelines live under /pipelines/catalog)
# =============================================================================

@router.get("/filters", tags=["Dashboard / Health & filters"], summary="Filter catalog", description="Pipelines, statuses, tools, and time presets for UI dropdowns.")
def filter_catalog(
    q: Optional[str] = Query(None, description="Optional search on pipeline id or name"),
) -> dict[str, Any]:
    conn = _conn()
    try:
        return build_filter_catalog(conn, q=q)
    finally:
        conn.close()


# =============================================================================
# Overview
# =============================================================================

@router.get("/overview", tags=["Dashboard / Overview"], summary="Full Overview payload", description="Combined Overview page: KPIs, charts, health, incidents, pipelines.")
def overview(
    preset: Optional[str] = Query("24h", description=_PRE),
    start_date: Optional[str] = Query(None, description=_SD),
    end_date: Optional[str] = Query(None, description=_ED),
    start_time: Optional[str] = Query(None),
    end_time: Optional[str] = Query(None),
    pipeline_name: Optional[str] = Query(None, description=_P),
    pipeline_id: Optional[str] = Query(None, description=_PID),
    status: Optional[str] = Query(None, description=_ST),
    tool: Optional[str] = Query(None, description=_TOOL),
    incident_limit: int = Query(10, ge=1, le=50),
) -> dict[str, Any]:
    conn = _conn()
    try:
        return build_overview(
            conn,
            **_common_filters(
                preset, start_date, end_date, start_time, end_time,
                pipeline_name, pipeline_id, status, tool,
            ),
            incident_limit=incident_limit,
        )
    finally:
        conn.close()


@router.get("/overview/kpis", tags=["Dashboard / Overview"], summary="Overview KPI cards")
def overview_kpis(
    preset: Optional[str] = Query("24h", description=_PRE),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    start_time: Optional[str] = Query(None),
    end_time: Optional[str] = Query(None),
    pipeline_name: Optional[str] = Query(None),
    pipeline_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    tool: Optional[str] = Query(None),
) -> dict[str, Any]:
    conn = _conn()
    try:
        rng = parse_range(preset, start_date, end_date, start_time, end_time)
        filters = dict(
            pipeline_name=pipeline_name, pipeline_id=pipeline_id, status=status, tool=tool
        )
        return envelope(
            rng=rng,
            filters_applied={**filters, "preset": rng.get("preset")},
            kpis=build_overview_kpis(conn, rng, **filters),
        )
    finally:
        conn.close()


@router.get("/overview/charts", tags=["Dashboard / Overview"], summary="Overview time-series charts")
def overview_charts(
    preset: Optional[str] = Query("24h", description=_PRE),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    start_time: Optional[str] = Query(None),
    end_time: Optional[str] = Query(None),
    pipeline_name: Optional[str] = Query(None),
    pipeline_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    tool: Optional[str] = Query(None),
) -> dict[str, Any]:
    conn = _conn()
    try:
        rng = parse_range(preset, start_date, end_date, start_time, end_time)
        filters = dict(
            pipeline_name=pipeline_name, pipeline_id=pipeline_id, status=status, tool=tool
        )
        charts = build_overview_charts(conn, rng, **filters)
        return envelope(
            rng=rng,
            filters_applied={**filters, "preset": rng.get("preset")},
            series={
                "runs_over_time": charts["runs_over_time"],
                "success_rate_over_time": charts["success_rate_over_time"],
                "incidents_over_time": charts["incidents_over_time"],
            },
            charts=charts,
        )
    finally:
        conn.close()


@router.get("/overview/health", tags=["Dashboard / Overview"], summary="Observability health pillars")
def overview_health(
    preset: Optional[str] = Query("24h", description=_PRE),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    start_time: Optional[str] = Query(None),
    end_time: Optional[str] = Query(None),
) -> dict[str, Any]:
    conn = _conn()
    try:
        rng = parse_range(preset, start_date, end_date, start_time, end_time)
        health = build_overview_health(conn, rng)
        return envelope(
            rng=rng,
            filters_applied={"preset": rng.get("preset")},
            pillars=health["pillars"],
            health=health["pillars"],
            items=health["pillars"],
        )
    finally:
        conn.close()


@router.get("/overview/recent-incidents", tags=["Dashboard / Overview"], summary="Recent open incidents")
def overview_recent_incidents(
    preset: Optional[str] = Query("24h", description=_PRE),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    start_time: Optional[str] = Query(None),
    end_time: Optional[str] = Query(None),
    pipeline_name: Optional[str] = Query(None),
    pipeline_id: Optional[str] = Query(None),
    limit: int = Query(10, ge=1, le=50),
) -> dict[str, Any]:
    conn = _conn()
    try:
        rng = parse_range(preset, start_date, end_date, start_time, end_time)
        items = [
            i
            for i in list_derived_incidents(
                conn,
                from_str=rng["from_str"],
                to_str=rng["to_str"],
                pipeline_name=pipeline_name,
                pipeline_id=pipeline_id,
                include_resolved=False,
            )
            if i.get("status") == "open"
        ][:limit]
        return envelope(
            rng=rng,
            filters_applied={
                "pipeline_name": pipeline_name,
                "pipeline_id": pipeline_id,
                "preset": rng.get("preset"),
            },
            items=items,
            incidents=items,
            total=len(items),
        )
    finally:
        conn.close()


@router.get("/overview/pipelines", tags=["Dashboard / Overview"], summary="Overview pipeline table")
def overview_pipelines(
    preset: Optional[str] = Query("24h", description=_PRE),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    start_time: Optional[str] = Query(None),
    end_time: Optional[str] = Query(None),
    pipeline_name: Optional[str] = Query(None),
    pipeline_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    tool: Optional[str] = Query(None),
) -> dict[str, Any]:
    conn = _conn()
    try:
        rng = parse_range(preset, start_date, end_date, start_time, end_time)
        filters = dict(
            pipeline_name=pipeline_name, pipeline_id=pipeline_id, status=status, tool=tool
        )
        items = build_pipeline_monitoring(conn, rng, **filters)
        return envelope(
            rng=rng,
            filters_applied={**filters, "preset": rng.get("preset")},
            items=items,
            pipelines=items,
            total=len(items),
        )
    finally:
        conn.close()


# =============================================================================
# Pipelines
# =============================================================================

@router.get("/pipelines/catalog", tags=["Dashboard / Pipelines"], summary="Pipeline catalog", description="Lean id+name list for dropdowns; also refreshes is_operational.")
def pipelines_catalog(
    q: Optional[str] = Query(None, description="Optional search on pipeline id or name"),
) -> dict[str, Any]:
    conn = _conn()
    try:
        rng = parse_range("all", None, None, None, None)
        items = list_filter_pipelines(conn, q=q)
        return envelope(
            rng=rng,
            filters_applied={"q": q},
            items=items,
            pipelines=items,
            total=len(items),
            page=1,
            page_size=len(items) or 1,
        )
    finally:
        conn.close()


@router.get("/pipelines", tags=["Dashboard / Pipelines"], summary="Pipelines list + KPIs")
def pipelines_list(
    preset: Optional[str] = Query("24h", description=_PRE),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    start_time: Optional[str] = Query(None),
    end_time: Optional[str] = Query(None),
    pipeline_name: Optional[str] = Query(None),
    pipeline_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    tool: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> dict[str, Any]:
    conn = _conn()
    try:
        return build_pipelines_list(
            conn,
            **_common_filters(
                preset, start_date, end_date, start_time, end_time,
                pipeline_name, pipeline_id, status, tool,
            ),
            page=page,
            page_size=page_size,
        )
    finally:
        conn.close()


@router.get("/pipelines/{pipeline_id}", tags=["Dashboard / Pipelines"], summary="Pipeline detail", description="Source / ETL / target + last run for one pipeline.")
def pipeline_detail(pipeline_id: str) -> dict[str, Any]:
    conn = _conn()
    try:
        data = build_pipeline_detail(conn, pipeline_id)
        if not data.get("ok", True) and data.get("error") == "pipeline_not_found":
            raise HTTPException(status_code=404, detail=f"Pipeline '{pipeline_id}' not found")
        return data
    finally:
        conn.close()


@router.get("/pipelines/{pipeline_id}/runs", tags=["Dashboard / Pipelines"], summary="Pipeline runs")
def pipeline_runs(
    pipeline_id: str,
    preset: Optional[str] = Query("all", description=_PRE),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    start_time: Optional[str] = Query(None),
    end_time: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    tool: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
) -> dict[str, Any]:
    conn = _conn()
    try:
        return build_pipeline_runs(
            conn,
            pipeline_id,
            preset=preset,
            start_date=start_date,
            end_date=end_date,
            start_time=start_time,
            end_time=end_time,
            status=status,
            tool=tool,
            page=page,
            page_size=page_size,
        )
    finally:
        conn.close()


# =============================================================================
# Observability pages
# =============================================================================

@router.get("/observability/freshness", tags=["Dashboard / Observability"], summary="Freshness page")
def freshness_page(
    preset: Optional[str] = Query("24h", description=_PRE),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    start_time: Optional[str] = Query(None),
    end_time: Optional[str] = Query(None),
    pipeline_name: Optional[str] = Query(None),
    pipeline_id: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> dict[str, Any]:
    conn = _conn()
    try:
        return build_freshness_page(
            conn,
            preset=preset,
            start_date=start_date,
            end_date=end_date,
            start_time=start_time,
            end_time=end_time,
            pipeline_name=pipeline_name,
            pipeline_id=pipeline_id,
            page=page,
            page_size=page_size,
        )
    finally:
        conn.close()


@router.get("/observability/volume", tags=["Dashboard / Observability"], summary="Volume page")
def volume_page(
    preset: Optional[str] = Query("24h", description=_PRE),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    start_time: Optional[str] = Query(None),
    end_time: Optional[str] = Query(None),
    pipeline_name: Optional[str] = Query(None),
    pipeline_id: Optional[str] = Query(None),
    tool: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> dict[str, Any]:
    conn = _conn()
    try:
        return build_volume_page(
            conn,
            preset=preset,
            start_date=start_date,
            end_date=end_date,
            start_time=start_time,
            end_time=end_time,
            pipeline_name=pipeline_name,
            pipeline_id=pipeline_id,
            tool=tool,
            page=page,
            page_size=page_size,
        )
    finally:
        conn.close()


@router.get("/observability/quality", tags=["Dashboard / Observability"], summary="Data Quality page", description="Check results from monitors and dbt tests.")
def quality_page(
    preset: Optional[str] = Query("24h", description=_PRE),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    start_time: Optional[str] = Query(None),
    end_time: Optional[str] = Query(None),
    pipeline_name: Optional[str] = Query(None),
    pipeline_id: Optional[str] = Query(None),
    score_mode: Optional[str] = Query(
        "time_window",
        description="time_window | last_run — MC-style last-run score uses last_run",
    ),
    source: Optional[str] = Query(
        "all",
        description="all | dbt | monitor — split validation vs operational checks",
    ),
    dataset_id: Optional[str] = Query(
        None,
        description="Filter to one dataset (e.g. ANALYTICS.MART.FCT_ORDERS)",
    ),
    tag: Optional[str] = Query(None, description="Filter by tag (e.g. team:finance)"),
    dimension: Optional[str] = Query(
        None,
        description="Filter by DQ dimension: completeness, uniqueness, accuracy, validity, timeliness",
    ),
) -> dict[str, Any]:
    conn = _conn()
    try:
        return build_quality_page(
            conn,
            preset=preset,
            start_date=start_date,
            end_date=end_date,
            start_time=start_time,
            end_time=end_time,
            pipeline_name=pipeline_name,
            pipeline_id=pipeline_id,
            score_mode=score_mode or "time_window",
            source=source or "all",
            dataset_id=dataset_id,
            tag=tag,
            dimension=dimension,
        )
    finally:
        conn.close()


@router.get("/observability/schema", tags=["Dashboard / Observability"], summary="Schema drift page")
def schema_page(
    preset: Optional[str] = Query("24h", description=_PRE),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    start_time: Optional[str] = Query(None),
    end_time: Optional[str] = Query(None),
    pipeline_name: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> dict[str, Any]:
    conn = _conn()
    try:
        return build_schema_page(
            conn,
            preset=preset,
            start_date=start_date,
            end_date=end_date,
            start_time=start_time,
            end_time=end_time,
            pipeline_name=pipeline_name,
            page=page,
            page_size=page_size,
        )
    finally:
        conn.close()


# =============================================================================
# Lineage / Incidents / Metrics / Logs / Alerts / Runs
# =============================================================================

@router.get("/lineage", tags=["Dashboard / Lineage"], summary="Lineage graph")
def lineage_page(
    preset: Optional[str] = Query("24h", description=_PRE),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    start_time: Optional[str] = Query(None),
    end_time: Optional[str] = Query(None),
    pipeline_name: Optional[str] = Query(None),
    pipeline_id: Optional[str] = Query(None),
) -> dict[str, Any]:
    conn = _conn()
    try:
        return build_lineage_page(
            conn,
            preset=preset,
            start_date=start_date,
            end_date=end_date,
            start_time=start_time,
            end_time=end_time,
            pipeline_name=pipeline_name,
            pipeline_id=pipeline_id,
        )
    finally:
        conn.close()


@router.get("/lineage/{pipeline_id}", tags=["Dashboard / Lineage"], summary="Lineage detail")
def lineage_detail(pipeline_id: str) -> dict[str, Any]:
    conn = _conn()
    try:
        data = build_lineage_detail(conn, pipeline_id)
        if data.get("error") == "pipeline_not_found":
            raise HTTPException(status_code=404, detail=f"Pipeline '{pipeline_id}' not found")
        return data
    finally:
        conn.close()


@router.get("/incidents", tags=["Dashboard / Incidents & alerts"], summary="Incidents list")
def incidents_page(
    preset: Optional[str] = Query("7d", description=_PRE),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    start_time: Optional[str] = Query(None),
    end_time: Optional[str] = Query(None),
    pipeline_name: Optional[str] = Query(None),
    pipeline_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None, description="open,resolved"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> dict[str, Any]:
    conn = _conn()
    try:
        return build_incidents_page(
            conn,
            preset=preset,
            start_date=start_date,
            end_date=end_date,
            start_time=start_time,
            end_time=end_time,
            pipeline_name=pipeline_name,
            pipeline_id=pipeline_id,
            status=status,
            page=page,
            page_size=page_size,
        )
    finally:
        conn.close()


@router.get("/incidents/{incident_id}", tags=["Dashboard / Incidents & alerts"], summary="Incident detail")
def incident_detail(incident_id: str) -> dict[str, Any]:
    conn = _conn()
    try:
        item = get_incident(conn, incident_id)
        if not item:
            raise HTTPException(status_code=404, detail=f"Incident '{incident_id}' not found")
        rng = parse_range("7d")
        return envelope(
            rng=rng,
            filters_applied={"incident_id": incident_id},
            items=[item],
            incidents=[item],
            meta={"incident": item},
            total=1,
        )
    finally:
        conn.close()


@router.get("/metrics", tags=["Dashboard / Metrics & logs"], summary="Metrics page")
def metrics_page(
    preset: Optional[str] = Query("15m", description=_PRE),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    start_time: Optional[str] = Query(None),
    end_time: Optional[str] = Query(None),
    pipeline_name: Optional[str] = Query(None),
    pipeline_id: Optional[str] = Query(None),
    tool: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> dict[str, Any]:
    conn = _conn()
    try:
        return build_metrics_page(
            conn,
            preset=preset,
            start_date=start_date,
            end_date=end_date,
            start_time=start_time,
            end_time=end_time,
            pipeline_name=pipeline_name,
            pipeline_id=pipeline_id,
            tool=tool,
            page=page,
            page_size=page_size,
        )
    finally:
        conn.close()


@router.get("/logs", tags=["Dashboard / Metrics & logs"], summary="Execution logs")
def logs_page(
    preset: Optional[str] = Query("24h", description=_PRE),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    start_time: Optional[str] = Query(None),
    end_time: Optional[str] = Query(None),
    pipeline_name: Optional[str] = Query(None),
    pipeline_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    tool: Optional[str] = Query(None),
    level: Optional[str] = Query(None, description="ERROR|WARN|INFO mapped from status"),
    search: Optional[str] = Query(None, description="Search message/pipeline"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
) -> dict[str, Any]:
    conn = _conn()
    try:
        rng = parse_range(preset, start_date, end_date, start_time, end_time)
        where, params = build_run_where(
            alias="r",
            pipeline_name=pipeline_name,
            pipeline_id=pipeline_id,
            status=status,
            tool=tool,
            from_str=None if rng.get("preset") == "all" else rng["from_str"],
            to_str=None if rng.get("preset") == "all" else rng["to_str"],
        )
        extra = []
        if search and search.strip():
            extra.append(
                "(r.pipeline_name LIKE %s OR COALESCE(r.error_message,'') LIKE %s OR COALESCE(r.failed_node,'') LIKE %s)"
            )
            q = f"%{search.strip()}%"
            params = list(params) + [q, q, q]
        # Level filter in SQL before pagination (ERROR/WARN/INFO mapped from status)
        if level and level.strip():
            lvl = level.strip().upper()
            if lvl == "ERROR":
                extra.append("LOWER(COALESCE(r.status,'')) IN ('failed','error')")
            elif lvl == "WARN":
                extra.append("LOWER(COALESCE(r.status,'')) IN ('running','cancelled')")
            elif lvl == "INFO":
                extra.append(
                    "LOWER(COALESCE(r.status,'')) NOT IN ('failed','error','running','cancelled')"
                )
        if extra:
            where = (where + " AND " if where else "WHERE ") + " AND ".join(extra)

        count = fetchone(conn, f"SELECT COUNT(*) AS n FROM obs_pipeline_runs r {where}", params)
        total = int(num(count.get("n")))
        page_size = max(1, min(int(page_size), 200))
        page = max(1, int(page))
        offset = (page - 1) * page_size
        rows = fetchall(
            conn,
            f"""
            SELECT
              id AS run_id, pipeline_id, pipeline_name, status, tool_name,
              start_time, end_time, duration, rows_read, rows_written,
              failure_stage, failed_node, error_class, error_message, created_at
            FROM obs_pipeline_runs r
            {where}
            ORDER BY COALESCE(end_time, start_time, created_at) DESC
            LIMIT %s OFFSET %s
            """,
            list(params) + [page_size, offset],
        )

        def level_for(st: str) -> str:
            s = (st or "").lower()
            if s in {"failed", "error"}:
                return "ERROR"
            if s in {"running", "cancelled"}:
                return "WARN"
            return "INFO"

        items = []
        for r in rows:
            lvl = level_for(str(r.get("status") or ""))
            msg = r.get("error_message") or (
                f"Run {r.get('status')} — {r.get('rows_written') or 0} rows written"
            )
            items.append(
                {
                    "timestamp": json_val(r.get("end_time") or r.get("start_time") or r.get("created_at")),
                    "pipeline_name": r.get("pipeline_name"),
                    "pipeline_id": r.get("pipeline_id"),
                    "run_id": r.get("run_id"),
                    "level": lvl,
                    "tool": r.get("tool_name"),
                    "message": str(msg)[:500],
                    "duration": format_duration(r.get("duration")),
                    "duration_seconds": num(r.get("duration")) if r.get("duration") is not None else None,
                    "status": r.get("status"),
                }
            )

        # KPIs from unfiltered status counts in range
        stats = fetchone(
            conn,
            f"""
            SELECT
              COUNT(*) AS total_logs,
              SUM(CASE WHEN LOWER(COALESCE(status,'')) IN ('failed','error') THEN 1 ELSE 0 END) AS failed_logs,
              SUM(CASE WHEN LOWER(COALESCE(status,'')) IN ('success','succeeded') THEN 1 ELSE 0 END) AS success_logs,
              AVG(duration) AS avg_duration
            FROM obs_pipeline_runs r
            {where}
            """,
            params,
        )
        kpis = [
            make_kpi(
                id="total_logs",
                title="Total Logs",
                value=int(num(stats.get("total_logs"))),
                display=str(int(num(stats.get("total_logs")))),
            ),
            make_kpi(
                id="failed_logs",
                title="Failed Logs",
                value=int(num(stats.get("failed_logs"))),
                display=str(int(num(stats.get("failed_logs")))),
                tone="bad" if num(stats.get("failed_logs")) else "ok",
            ),
            make_kpi(
                id="success_logs",
                title="Success Logs",
                value=int(num(stats.get("success_logs"))),
                display=str(int(num(stats.get("success_logs")))),
                tone="ok",
            ),
            make_kpi(
                id="avg_duration",
                title="Log Duration (Avg)",
                value=num(stats.get("avg_duration")) if stats.get("avg_duration") is not None else None,
                display=format_duration(stats.get("avg_duration")) or "N/A",
                available=stats.get("avg_duration") is not None,
            ),
        ]

        return envelope(
            rng=rng,
            filters_applied={
                "pipeline_name": pipeline_name,
                "pipeline_id": pipeline_id,
                "status": status,
                "tool": tool,
                "level": level,
                "search": search,
                "preset": rng.get("preset"),
            },
            kpis=kpis,
            items=items,
            page=page,
            page_size=page_size,
            total=total,
        )
    finally:
        conn.close()


@router.get("/runs/{run_id}", tags=["Dashboard / Metrics & logs"], summary="Run detail", description="Resolve by run id or obs_run_id.")
def run_detail(run_id: str) -> dict[str, Any]:
    conn = _conn()
    try:
        runs = fetchall(
            conn,
            "SELECT * FROM obs_pipeline_runs WHERE id = %s OR obs_run_id = %s LIMIT 1",
            (run_id, run_id),
        )
        if not runs:
            raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")
        run = runs[0]
        rid = str(run.get("id") or run_id)
        assets = fetchall(conn, "SELECT * FROM obs_run_assets WHERE run_id = %s", (rid,))
        columns = fetchall(conn, "SELECT * FROM obs_run_columns WHERE run_id = %s", (rid,))
        queries = fetchall(
            conn, "SELECT * FROM obs_run_query_history WHERE run_id = %s", (rid,)
        )
        raw_log = run.get("raw_log")
        run_out = {k: json_val(v) for k, v in run.items() if k not in {"raw_log", "relations_json", "failed_nodes_json"}}
        run_out["raw_log"] = raw_log
        run_out["duration_display"] = format_duration(run.get("duration"))
        try:
            rel = run.get("relations_json")
            run_out["relations"] = json.loads(rel) if isinstance(rel, str) and rel else (rel or [])
        except json.JSONDecodeError:
            run_out["relations"] = []
        try:
            fn = run.get("failed_nodes_json")
            run_out["failed_nodes"] = json.loads(fn) if isinstance(fn, str) and fn else (fn or [])
        except json.JSONDecodeError:
            run_out["failed_nodes"] = []
        rng = parse_range("all")
        return envelope(
            rng=rng,
            filters_applied={"run_id": run_id},
            items=[],
            meta={
                "run": run_out,
                "assets": [{k: json_val(v) for k, v in a.items()} for a in assets],
                "columns": [{k: json_val(v) for k, v in c.items()} for c in columns],
                "query_history": [{k: json_val(v) for k, v in q.items()} for q in queries],
            },
        )
    finally:
        conn.close()


@router.get(
    "/runs/{run_id}/rca-context",
    tags=["Dashboard / Metrics & logs"],
    summary="RCA context bundle",
    description=(
        "Grounded failure context for triage and AI: run, failed nodes, relations, "
        "assets, columns, query history, lineage upstream slice, dbt tests."
    ),
)
def run_rca_context(run_id: str) -> dict[str, Any]:
    conn = _conn()
    try:
        ctx = build_rca_context(conn, run_id)
        rng = parse_range("all")
        return envelope(
            rng=rng,
            filters_applied={"run_id": run_id},
            items=[],
            meta=ctx,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    finally:
        conn.close()


@router.get("/alerts", tags=["Dashboard / Incidents & alerts"], summary="Alerts list")
def alerts_page(
    preset: Optional[str] = Query("24h", description=_PRE),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    status: Optional[str] = Query("open"),
) -> dict[str, Any]:
    from application.src.services.observability.lifecycle import list_alerts

    rng = parse_range(preset, start_date, end_date, None, None)
    conn = _conn()
    try:
        items = list_alerts(conn, status=status)
        open_n = sum(1 for a in items if a.get("status") == "open")
        crit_n = sum(
            1
            for a in items
            if a.get("status") == "open" and str(a.get("severity") or "").lower() == "critical"
        )
        acked_n = sum(1 for a in items if a.get("status") == "acked")
        resolved_n = sum(1 for a in items if a.get("status") == "resolved")
        available = True
        kpis = [
            make_kpi(id="open_alerts", title="Open Alerts", value=open_n, display=str(open_n), tone="bad" if open_n else "ok"),
            make_kpi(id="critical_alerts", title="Critical", value=crit_n, display=str(crit_n), tone="bad" if crit_n else "ok"),
            make_kpi(id="acked_alerts", title="Acknowledged", value=acked_n, display=str(acked_n)),
            make_kpi(id="resolved_alerts", title="Resolved", value=resolved_n, display=str(resolved_n)),
        ]
        return envelope(
            rng=rng,
            filters_applied={"preset": rng.get("preset"), "status": status},
            kpis=kpis,
            items=[{k: json_val(v) for k, v in a.items()} for a in items],
            meta={"available": available, "reason": None},
            summary={"available": available, "open": open_n},
        )
    finally:
        conn.close()


@router.post("/ops/evaluate-monitors", tags=["Dashboard / Ops"], summary="Evaluate monitors", description="Run monitor evaluation → alerts/incidents.")
def ops_evaluate_monitors() -> dict[str, Any]:
    from application.src.services.observability.lifecycle import evaluate_monitors

    conn = _conn()
    try:
        return evaluate_monitors(conn)
    finally:
        conn.close()


@router.post(
    "/ops/evaluate-dq-rules",
    tags=["Dashboard / Ops"],
    summary="Evaluate DQ rules",
    description="Run obs_dq_rules evaluation → obs_check_results.",
)
def ops_evaluate_dq_rules(
    pipeline_id: Optional[str] = Query(None, description="Limit to one pipeline"),
) -> dict[str, Any]:
    from application.src.services.observability.dq_rules import evaluate_dq_rules

    conn = _conn()
    try:
        return evaluate_dq_rules(conn, pipeline_id=pipeline_id)
    finally:
        conn.close()


@router.post("/ops/rollup-daily", tags=["Dashboard / Ops"], summary="Daily metric rollups")
def ops_rollup_daily(day: Optional[str] = Query(None, description="YYYY-MM-DD")) -> dict[str, Any]:
    from application.src.store.meta_mysql import rollup_daily_metrics, rollup_dq_daily_metrics

    conn = _conn()
    try:
        n = rollup_daily_metrics(conn, day=day)
        dq_n = rollup_dq_daily_metrics(conn, day=day)
        return {"ok": True, "upserted": n, "dq_upserted": dq_n, "day": day}
    finally:
        conn.close()


@router.post("/ops/purge-raw", tags=["Dashboard / Ops"], summary="Purge raw observations")
def ops_purge_raw() -> dict[str, Any]:
    from application.src.store.meta_mysql import purge_raw_observations

    conn = _conn()
    try:
        return {"ok": True, "deleted": purge_raw_observations(conn)}
    finally:
        conn.close()


@router.post("/ops/migrate-bindings", tags=["Dashboard / Ops"], summary="Migrate pipeline bindings")
def ops_migrate_bindings() -> dict[str, Any]:
    from application.src.store.meta_mysql import migrate_pipeline_bindings

    conn = _conn()
    try:
        n = migrate_pipeline_bindings(conn)
        return {"ok": True, "pipelines": n}
    finally:
        conn.close()


@router.get("/pipelines/{pipeline_id}/bindings", tags=["Dashboard / Pipelines"], summary="Pipeline bindings", description="Declared SOURCE / ETL / TARGET tool bindings.")
def pipeline_bindings(pipeline_id: str) -> dict[str, Any]:
    from application.src.store.meta_mysql import list_pipeline_bindings

    conn = _conn()
    try:
        items = list_pipeline_bindings(conn, pipeline_id)
        rng = parse_range("all")
        return envelope(
            rng=rng,
            filters_applied={"pipeline_id": pipeline_id},
            items=[{k: json_val(v) for k, v in i.items()} for i in items],
            total=len(items),
        )
    finally:
        conn.close()


@router.get(
    "/pipelines/{pipeline_id}/monitors",
    tags=["Dashboard / Pipelines"],
    summary="Pipeline monitors",
    description="Read-only list of DQ / operational monitors for one pipeline.",
)
def pipeline_monitors(pipeline_id: str) -> dict[str, Any]:
    from application.src.store.meta_mysql import list_monitors

    conn = _conn()
    try:
        items = list_monitors(conn, pipeline_id=pipeline_id)
        rng = parse_range("all")
        return envelope(
            rng=rng,
            filters_applied={"pipeline_id": pipeline_id},
            items=items,
            monitors=items,
            total=len(items),
        )
    finally:
        conn.close()


@router.get("/connectors/types", tags=["Dashboard / Tools catalog"], summary="Connector types")
def connector_types() -> dict[str, Any]:
    from application.src.connectors.registry import list_connector_types

    return {"ok": True, "items": list_connector_types()}


@router.get("/tools", tags=["Dashboard / Tools catalog"], summary="List tools (read-only)", description="UI catalog. Create/update tools via POST /v1/tools.")
def api_list_tools(
    kind: str | None = Query(default=None),
    connector_type: str | None = Query(default=None),
) -> dict[str, Any]:
    from application.src.store.meta_mysql import list_tools

    return {"ok": True, "items": list_tools(kind=kind, connector_type=connector_type)}

