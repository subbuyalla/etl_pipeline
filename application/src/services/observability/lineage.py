"""Lineage graph from obs_pipelines + latest-run assets (no name heuristics)."""

from __future__ import annotations

from typing import Any, Optional

from application.src.api.schemas import make_kpi
from application.src.services.observability.filters import (
    age_label,
    envelope,
    fetchall,
    fetchone,
    format_duration,
    json_val,
    num,
    parse_range,
    pct,
)
from application.src.services.observability.freshness import load_pipeline_freshness
from application.src.services.observability.incidents import list_derived_incidents


def _latest_run(conn, pipeline_id: str) -> dict:
    rows = fetchall(
        conn,
        """
        SELECT * FROM obs_pipeline_runs
        WHERE pipeline_id = %s
        ORDER BY COALESCE(end_time, start_time, created_at) DESC
        LIMIT 1
        """,
        (pipeline_id,),
    )
    return rows[0] if rows else {}


def _assets_for_run(conn, run_id: Any) -> list[dict]:
    if not run_id:
        return []
    return fetchall(
        conn,
        "SELECT * FROM obs_run_assets WHERE run_id = %s ORDER BY asset_role, object_name",
        (str(run_id),),
    )


def _health_status(latest_status: str | None, freshness_key: str | None, has_open_incident: bool) -> str:
    st = str(latest_status or "").lower()
    if has_open_incident or st in {"failed", "error"}:
        return "failed"
    if freshness_key in {"delayed", "stale"}:
        return "degraded"
    if st in {"success", "succeeded"}:
        return "healthy"
    return "unknown"


def build_lineage_page(
    conn,
    *,
    preset: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    pipeline_name: Optional[str] = None,
    pipeline_id: Optional[str] = None,
) -> dict[str, Any]:
    rng = parse_range(preset, start_date, end_date, start_time, end_time)
    pipes = fetchall(
        conn,
        """
        SELECT pipeline_id, pipeline_name, source_tool, source_schema,
               etl_tool, target_tool, target_schema, is_active, description
        FROM obs_pipelines
        ORDER BY pipeline_name
        """,
    )
    if pipeline_name:
        names = {n.strip() for n in pipeline_name.split(",") if n.strip()}
        pipes = [p for p in pipes if p.get("pipeline_name") in names]
    if pipeline_id:
        ids = {i.strip() for i in pipeline_id.split(",") if i.strip()}
        pipes = [p for p in pipes if p.get("pipeline_id") in ids]

    fresh_map = {
        r["pipeline_id"]: r
        for r in load_pipeline_freshness(conn, pipeline_name=pipeline_name, pipeline_id=pipeline_id)
    }
    open_inc = {
        i["pipeline_id"]
        for i in list_derived_incidents(conn, include_resolved=False)
        if i.get("status") == "open"
    }

    nodes: list[dict] = []
    edges: list[dict] = []
    items: list[dict] = []
    seen_nodes: set[str] = set()

    def add_node(nid: str, ntype: str, label: str, metadata: dict | None = None):
        if nid in seen_nodes:
            return
        seen_nodes.add(nid)
        nodes.append({"id": nid, "type": ntype, "label": label, "metadata": metadata or {}})

    sources = set()
    healthy = degraded = failed = 0

    for p in pipes:
        pid = str(p.get("pipeline_id"))
        pname = p.get("pipeline_name")
        pipe_node = f"pipeline:{pid}"
        add_node(
            pipe_node,
            "pipeline",
            str(pname),
            {
                "etl_tool": p.get("etl_tool"),
                "is_active": p.get("is_active"),
                "source_tool": p.get("source_tool"),
                "target_tool": p.get("target_tool"),
            },
        )

        latest = _latest_run(conn, pid)
        assets = _assets_for_run(conn, latest.get("id"))
        src_assets = [a for a in assets if str(a.get("asset_role") or "").upper() == "SOURCE"]
        tgt_assets = [a for a in assets if str(a.get("asset_role") or "").upper() == "TARGET"]

        # Fallback to pipeline config schemas when no assets
        if not src_assets and p.get("source_schema"):
            sid = f"source:{p.get('source_tool')}:{p.get('source_schema')}"
            add_node(sid, "source", f"{p.get('source_tool')}/{p.get('source_schema')}", {"tool": p.get("source_tool")})
            edges.append({"from": sid, "to": pipe_node, "label": "feeds_into"})
            sources.add(sid)
        for a in src_assets:
            ds = a.get("dataset_id") or f"{a.get('database_name')}.{a.get('schema_name')}.{a.get('object_name')}"
            sid = f"source:{ds}"
            add_node(sid, "source", str(ds), {"system": a.get("system_name"), "rows": a.get("row_count")})
            edges.append({"from": sid, "to": pipe_node, "label": "feeds_into"})
            sources.add(sid)

        if not tgt_assets and p.get("target_schema"):
            tid = f"target:{p.get('target_tool')}:{p.get('target_schema')}"
            add_node(tid, "target", f"{p.get('target_tool')}/{p.get('target_schema')}", {"tool": p.get("target_tool")})
            edges.append({"from": pipe_node, "to": tid, "label": "writes_to"})
        for a in tgt_assets:
            ds = a.get("dataset_id") or f"{a.get('database_name')}.{a.get('schema_name')}.{a.get('object_name')}"
            tid = f"target:{ds}"
            add_node(tid, "target", str(ds), {"system": a.get("system_name"), "rows": a.get("row_count")})
            edges.append({"from": pipe_node, "to": tid, "label": "writes_to"})

        fr = fresh_map.get(pid) or {}
        hs = _health_status(latest.get("status"), fr.get("status_key"), pid in open_inc)
        if hs == "healthy":
            healthy += 1
        elif hs == "degraded":
            degraded += 1
        elif hs == "failed":
            failed += 1

        vol_rows = sum(num(a.get("row_count")) for a in tgt_assets)
        items.append(
            {
                "pipeline_id": pid,
                "pipeline_name": pname,
                "source": f"{p.get('source_tool') or '-'}/{p.get('source_schema') or '-'}",
                "etl": p.get("etl_tool") or "-",
                "target": f"{p.get('target_tool') or '-'}/{p.get('target_schema') or '-'}",
                "status": hs.title(),
                "status_key": hs,
                "last_run_at": json_val(latest.get("end_time") or latest.get("start_time")),
                "last_run_age": age_label(latest.get("end_time") or latest.get("start_time")),
                "duration": format_duration(latest.get("duration")),
                "freshness": fr.get("status") or "N/A",
                "freshness_lag_hours": fr.get("current_lag_hours"),
                "target_rows": int(vol_rows),
                "data_quality": None,
                "data_quality_display": "N/A",
            }
        )

    total = len(pipes)
    kpis = [
        make_kpi(id="total_pipelines", title="Total Pipelines", value=total, display=str(total)),
        make_kpi(
            id="healthy",
            title="Healthy",
            value=healthy,
            display=f"{healthy} ({pct(healthy, total) or 0}%)",
            tone="ok",
        ),
        make_kpi(
            id="degraded",
            title="Degraded",
            value=degraded,
            display=f"{degraded} ({pct(degraded, total) or 0}%)",
            tone="warn" if degraded else "ok",
        ),
        make_kpi(
            id="failed",
            title="Failed",
            value=failed,
            display=f"{failed} ({pct(failed, total) or 0}%)",
            tone="bad" if failed else "ok",
        ),
        make_kpi(
            id="data_sources",
            title="Data Sources",
            value=len(sources),
            display=str(len(sources)),
        ),
    ]

    return envelope(
        rng=rng,
        filters_applied={
            "pipeline_name": pipeline_name,
            "pipeline_id": pipeline_id,
            "preset": rng.get("preset"),
        },
        kpis=kpis,
        items=items,
        pipelines=items,
        meta={"nodes": nodes, "edges": edges, "total_nodes": len(nodes), "total_edges": len(edges)},
        summary={"healthy": healthy, "degraded": degraded, "failed": failed, "sources": len(sources)},
    )


def build_lineage_detail(conn, pipeline_id: str) -> dict[str, Any]:
    pipe = fetchone(
        conn,
        """
        SELECT * FROM obs_pipelines WHERE pipeline_id = %s
        """,
        (pipeline_id,),
    )
    if not pipe:
        return {"ok": False, "error": "pipeline_not_found", "pipeline_id": pipeline_id}

    page = build_lineage_page(conn, pipeline_id=pipeline_id)
    item = next((i for i in page.get("items") or [] if i.get("pipeline_id") == pipeline_id), {})
    latest = _latest_run(conn, pipeline_id)
    assets = _assets_for_run(conn, latest.get("id"))
    fr = load_pipeline_freshness(conn, pipeline_id=pipeline_id)
    fr0 = fr[0] if fr else {}

    return {
        "ok": True,
        "generated_at": page["generated_at"],
        "range": page["range"],
        "filters_applied": {"pipeline_id": pipeline_id},
        "kpis": page["kpis"],
        "series": {},
        "charts": {},
        "items": [],
        "pagination": {"page": 1, "page_size": 1, "total": 1},
        "pillars": [],
        "incidents": [],
        "pipelines": [],
        "health": [],
        "summary": {},
        "meta": {
            "pipeline": {k: json_val(v) for k, v in (pipe or {}).items()},
            "lineage_item": item,
            "last_run": {
                k: json_val(v) if k != "raw_log" else None
                for k, v in (latest or {}).items()
            },
            "assets": [
                {k: json_val(v) for k, v in a.items()} for a in assets
            ],
            "freshness": fr0,
            "data_quality": {"available": False, "display": "N/A"},
            "schema": {"status": "unknown", "display": "N/A", "available": False},
        },
    }
