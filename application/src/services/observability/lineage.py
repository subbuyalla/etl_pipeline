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
from application.src.services.observability.quality import (
    dataset_dq_map,
    failed_test_count_by_pipeline,
    normalize_dataset_id,
)
from application.src.services.observability.rca_context import _upstream_edges
from application.src.services.observability.schema_diff import schema_health_score


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


def _lineage_edges_for_run(conn, run_id: Any) -> list[dict]:
    if not run_id:
        return []
    rows = fetchall(
        conn,
        """
        SELECT edge_id, pipeline_id, run_id, from_dataset, to_dataset,
               edge_kind, confidence, observed_at
        FROM obs_lineage_edges
        WHERE run_id = %s
        ORDER BY from_dataset, to_dataset
        """,
        (str(run_id),),
    )
    seen: set[tuple[str, str]] = set()
    deduped: list[dict] = []
    for e in rows:
        key = (
            str(e.get("from_dataset") or "").upper(),
            str(e.get("to_dataset") or "").upper(),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(e)
    return deduped


def _merge_manifest_edges(
    edges: list[dict],
    nodes: list[dict],
    seen_nodes: set[str],
    manifest_edges: list[dict],
    *,
    pipe_node: str,
) -> None:
    """Add model-level nodes/links from obs_lineage_edges."""
    for e in manifest_edges or []:
        from_ds = str(e.get("from_dataset") or "")
        to_ds = str(e.get("to_dataset") or "")
        if not from_ds or not to_ds:
            continue
        from_id = f"model:{from_ds}"
        to_id = f"model:{to_ds}"
        if from_id not in seen_nodes:
            seen_nodes.add(from_id)
            nodes.append(
                {
                    "id": from_id,
                    "type": "model",
                    "label": from_ds,
                    "metadata": {"edge_kind": e.get("edge_kind")},
                }
            )
        if to_id not in seen_nodes:
            seen_nodes.add(to_id)
            nodes.append(
                {
                    "id": to_id,
                    "type": "model",
                    "label": to_ds,
                    "metadata": {"edge_kind": e.get("edge_kind")},
                }
            )
        edges.append(
            {
                "from": from_id,
                "to": to_id,
                "label": e.get("edge_kind") or "depends_on",
            }
        )
        edges.append({"from": from_id, "to": pipe_node, "label": "feeds_pipeline"})
        edges.append({"from": pipe_node, "to": to_id, "label": "produces"})


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
    pipe_ids = [str(p.get("pipeline_id")) for p in pipes]
    dq_fail_map = failed_test_count_by_pipeline(conn, pipe_ids)

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
        run_id = latest.get("id")
        assets = _assets_for_run(conn, run_id)
        manifest_edges = _lineage_edges_for_run(conn, run_id)
        _merge_manifest_edges(edges, nodes, seen_nodes, manifest_edges, pipe_node=pipe_node)
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
            ds_norm = normalize_dataset_id(ds)
            dq_meta = dataset_dq_map(conn, pipeline_id=pid, dataset_ids=[ds_norm]).get(ds_norm) or {}
            add_node(
                tid,
                "target",
                str(ds),
                {
                    "system": a.get("system_name"),
                    "rows": a.get("row_count"),
                    "dq_status_key": dq_meta.get("status_key"),
                    "quality_score": dq_meta.get("quality_score"),
                },
            )
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
        dq_failed = dq_fail_map.get(pid, 0)
        dq_display = f"{dq_failed} failed test(s)" if dq_failed else "OK"
        target_ds_ids = [
            normalize_dataset_id(
                a.get("dataset_id")
                or f"{a.get('database_name')}.{a.get('schema_name')}.{a.get('object_name')}"
            )
            for a in tgt_assets
        ]
        target_ds_ids = [d for d in target_ds_ids if d]
        ds_dq = dataset_dq_map(conn, pipeline_id=pid, dataset_ids=target_ds_ids or None)
        target_datasets = [
            {
                "dataset_id": ds,
                "quality_score": info.get("quality_score"),
                "status_key": info.get("status_key"),
                "data_quality_display": info.get("data_quality_display"),
                "failed": info.get("failed"),
                "warn": info.get("warn"),
            }
            for ds, info in sorted(ds_dq.items())
        ]
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
                "data_quality": dq_failed,
                "data_quality_display": dq_display,
                "target_datasets": target_datasets,
                "manifest_edges": len(manifest_edges),
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
    rid = latest.get("id")
    assets = _assets_for_run(conn, rid)
    manifest_edges = _lineage_edges_for_run(conn, rid)
    fr = load_pipeline_freshness(conn, pipeline_id=pipeline_id)
    fr0 = fr[0] if fr else {}
    dq_map = failed_test_count_by_pipeline(conn, [pipeline_id])
    dq_failed = dq_map.get(pipeline_id, 0)
    sch = schema_health_score(conn)
    target_ds_ids = [
        normalize_dataset_id(
            a.get("dataset_id")
            or f"{a.get('database_name')}.{a.get('schema_name')}.{a.get('object_name')}"
        )
        for a in assets
        if str(a.get("asset_role") or "").upper() == "TARGET"
    ]
    target_ds_ids = [d for d in target_ds_ids if d]
    ds_dq = dataset_dq_map(conn, pipeline_id=pipeline_id, dataset_ids=target_ds_ids or None)
    dataset_quality = [
        {
            "dataset_id": ds,
            "quality_score": info.get("quality_score"),
            "status_key": info.get("status_key"),
            "data_quality_display": info.get("data_quality_display"),
            "failed": info.get("failed"),
            "warn": info.get("warn"),
            "passed": info.get("passed"),
        }
        for ds, info in sorted(ds_dq.items())
    ]
    relations: list[str] = []
    try:
        import json as _json

        rel_raw = latest.get("relations_json")
        if rel_raw:
            relations = _json.loads(rel_raw) if isinstance(rel_raw, str) else list(rel_raw or [])
    except (TypeError, ValueError, _json.JSONDecodeError):
        relations = []
    failed_node = latest.get("failed_node")
    upstream = _upstream_edges(
        manifest_edges,
        failed_node=str(failed_node) if failed_node else None,
        relations=relations,
    )

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
            "data_quality": {
                "available": True,
                "display": f"{dq_failed} failed test(s)" if dq_failed else "OK",
                "failed_tests": dq_failed,
            },
            "dataset_quality": dataset_quality,
            "schema": {
                "status": "good" if (sch.get("score") or 0) >= 90 else "warning",
                "display": f"{sch.get('score')}%" if sch.get("available") else "N/A",
                "available": bool(sch.get("available")),
                "breaking_changes": sch.get("breaking"),
            },
            "manifest_edges": manifest_edges,
            "upstream_slice": upstream,
        },
    }
