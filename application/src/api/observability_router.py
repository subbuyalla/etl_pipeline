"""
/api/v1 Observability dashboard routes — stable contracts for the VITHI UI.
"""

from __future__ import annotations

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
from application.src.services.observability.freshness import build_freshness_page
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
from application.src.store.meta_mysql import get_connection as db_connect

router = APIRouter(tags=["Dashboard API v1"])


def _conn():
    return db_connect()


def _common_filters(
    preset: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    pipeline_name: Optional[str] = None,
    pipeline_id: Optional[str] = None,
    status: Optional[str] = None,
    tool: Optional[str] = None,
    range: Optional[str] = None,
) -> dict[str, Any]:
    resolved_preset = preset if (preset and preset != "24h") else (range or preset or "24h")
    return dict(
        preset=resolved_preset,
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

@router.get("/health", summary="API & DB health")
def api_v1_health() -> dict[str, Any]:
    conn = _conn()
    try:
        fetchone(conn, "SELECT 1 AS ok")
        return {"ok": True, "status": "ok", "database": "connected"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database unavailable: {e}") from e
    finally:
        conn.close()


# =============================================================================
# Filter lookups (status/tool/presets; pipelines live under /pipelines/catalog)
# =============================================================================

@router.get("/filters", summary="All filter options (pipelines, status, tool, presets)")
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

@router.get("/overview", summary="Full Overview dashboard payload")
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


@router.get("/overview/kpis", summary="Overview KPI cards")
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


@router.get("/overview/charts", summary="Overview time-series charts")
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


@router.get("/overview/health", summary="Observability health pillars")
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


@router.get("/overview/recent-incidents", summary="Recent open incidents")
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


@router.get("/overview/pipelines", summary="Overview pipeline monitoring table")
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

@router.get("/pipelines/catalog", summary="Pipeline id + name list (for dropdown / click)")
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


@router.get("/pipelines", summary="Pipelines list + KPI strip")
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


@router.get("/pipelines/{pipeline_id}", summary="Full pipeline details by id")
def pipeline_detail(pipeline_id: str) -> dict[str, Any]:
    conn = _conn()
    try:
        data = build_pipeline_detail(conn, pipeline_id)
        if not data.get("ok", True) and data.get("error") == "pipeline_not_found":
            raise HTTPException(status_code=404, detail=f"Pipeline '{pipeline_id}' not found")
        return data
    finally:
        conn.close()


@router.get("/pipelines/{pipeline_id}/runs", summary="Pipeline runs")
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

@router.get("/observability/freshness", summary="Freshness page")
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


@router.get("/observability/volume", summary="Volume page")
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


@router.get("/observability/quality", summary="Data Quality page (N/A until checks exist)")
def quality_page(
    preset: Optional[str] = Query("24h", description=_PRE),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    start_time: Optional[str] = Query(None),
    end_time: Optional[str] = Query(None),
    pipeline_name: Optional[str] = Query(None),
    pipeline_id: Optional[str] = Query(None),
) -> dict[str, Any]:
    rng = parse_range(preset, start_date, end_date, start_time, end_time)
    kpis = [
        make_kpi(id="quality_status", title="Quality Status", available=False),
        make_kpi(id="checks_run", title="Checks Run", available=False),
        make_kpi(id="passed", title="Passed", available=False),
        make_kpi(id="warning", title="Warning", available=False),
        make_kpi(id="failed", title="Failed", available=False),
    ]
    return envelope(
        rng=rng,
        filters_applied={
            "pipeline_name": pipeline_name,
            "pipeline_id": pipeline_id,
            "preset": rng.get("preset"),
        },
        kpis=kpis,
        series={"quality_score_over_time": []},
        charts={"checks_by_status": {"passed": 0, "warning": 0, "failed": 0, "total": 0}},
        items=[],
        meta={
            "available": False,
            "reason": "No DQ check_results in obs_*. Contract reserved for frontend.",
        },
        summary={"available": False},
    )


@router.get("/observability/schema", summary="Schema drift page")
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

@router.get("/lineage", summary="Lineage graph + pipeline hops")
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


@router.get("/lineage/{pipeline_id}", summary="Lineage detail for one pipeline")
def lineage_detail(pipeline_id: str) -> dict[str, Any]:
    conn = _conn()
    try:
        data = build_lineage_detail(conn, pipeline_id)
        if data.get("error") == "pipeline_not_found":
            raise HTTPException(status_code=404, detail=f"Pipeline '{pipeline_id}' not found")
        return data
    finally:
        conn.close()


@router.get("/incidents", summary="Incidents page")
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


@router.get("/incidents/{incident_id}", summary="Single incident detail")
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


@router.get("/metrics", summary="Metrics page")
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


@router.get("/logs", summary="Execution logs (from pipeline runs)")
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
            if level and lvl.upper() != level.strip().upper():
                continue
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


@router.get("/runs/{run_id}", summary="Single run detail")
def run_detail(run_id: str) -> dict[str, Any]:
    conn = _conn()
    try:
        runs = fetchall(conn, "SELECT * FROM obs_pipeline_runs WHERE id = %s", (run_id,))
        if not runs:
            raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")
        run = runs[0]
        assets = fetchall(conn, "SELECT * FROM obs_run_assets WHERE run_id = %s", (run_id,))
        columns = fetchall(conn, "SELECT * FROM obs_run_columns WHERE run_id = %s", (run_id,))
        queries = fetchall(
            conn, "SELECT * FROM obs_run_query_history WHERE run_id = %s", (run_id,)
        )
        raw_log = run.get("raw_log")
        run_out = {k: json_val(v) for k, v in run.items() if k != "raw_log"}
        run_out["raw_log"] = raw_log
        run_out["duration_display"] = format_duration(run.get("duration"))
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


@router.get("/alerts", summary="Alerts page (empty until alert store exists)")
def alerts_page(
    preset: Optional[str] = Query("24h", description=_PRE),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
) -> dict[str, Any]:
    rng = parse_range(preset, start_date, end_date, None, None)
    kpis = [
        make_kpi(id="open_alerts", title="Open Alerts", value=0, display="0"),
        make_kpi(id="critical_alerts", title="Critical", value=0, display="0"),
        make_kpi(id="acked_alerts", title="Acknowledged", value=0, display="0"),
        make_kpi(id="resolved_alerts", title="Resolved", value=0, display="0"),
    ]
    return envelope(
        rng=rng,
        filters_applied={"preset": rng.get("preset")},
        kpis=kpis,
        items=[],
        meta={
            "available": False,
            "reason": "No etl_alerts / alert store wired to obs_* yet. Stable empty contract for FE.",
        },
        summary={"available": False, "open": 0},
    )
