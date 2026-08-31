"""RCA context bundle — single payload for human triage and AI assistants."""

from __future__ import annotations

import json
from typing import Any

from application.src.services.observability.filters import (
    fetchall,
    fetchone,
    format_duration,
    json_val,
)
from application.src.services.observability.freshness import load_pipeline_freshness
from application.src.services.observability.rca_deltas import build_change_since_last_success


def _parse_json_field(value: Any) -> Any:
    if value is None or value == "":
        return None
    if isinstance(value, (list, dict)):
        return value
    try:
        return json.loads(value) if isinstance(value, str) else value
    except (json.JSONDecodeError, TypeError):
        return None


def _lineage_slice(
    edges: list[dict],
    *,
    failed_node: str | None,
    relations: list[str],
    direction: str = "upstream",
) -> list[dict]:
    """Upstream or downstream slice from manifest/openlineage edges."""
    if not edges:
        return []
    target_keys = set()
    fn = (failed_node or "").lower()
    for rel in relations or []:
        target_keys.add(str(rel).lower())
        parts = str(rel).replace('"', "").replace("`", "").split(".")
        if parts:
            target_keys.add(parts[-1].lower())
    if fn:
        target_keys.add(fn)
        if "." in fn:
            target_keys.add(fn.split(".")[-1])

    if not target_keys:
        return edges[:50]

    if direction == "downstream":
        adj: dict[str, list[str]] = {}
        for e in edges:
            from_d = str(e.get("from_dataset") or "").lower()
            to_d = str(e.get("to_dataset") or "")
            adj.setdefault(from_d, []).append(to_d)
            parts = from_d.split(".")
            if parts:
                adj.setdefault(parts[-1], []).append(to_d)

        seeds = list(target_keys)
        visited: set[str] = set()
        frontier = list(seeds)
        related: set[str] = set(seeds)
        while frontier:
            key = frontier.pop()
            if key in visited:
                continue
            visited.add(key)
            for child in adj.get(key, []):
                ck = child.lower()
                related.add(ck)
                if ck not in visited:
                    frontier.append(ck)

        out = []
        for e in edges:
            from_l = str(e.get("from_dataset") or "").lower()
            to_l = str(e.get("to_dataset") or "").lower()
            from_short = from_l.split(".")[-1] if from_l else ""
            if (
                from_l in related
                or to_l in related
                or from_short in related
                or any(k in from_l or k in to_l for k in target_keys)
            ):
                out.append(e)
        return out[:100] if out else edges[:50]

    # upstream (default)
    rev: dict[str, list[str]] = {}
    for e in edges:
        to_d = str(e.get("to_dataset") or "").lower()
        from_d = str(e.get("from_dataset") or "")
        rev.setdefault(to_d, []).append(from_d)
        parts = to_d.split(".")
        if parts:
            rev.setdefault(parts[-1], []).append(from_d)

    seeds = list(target_keys)
    visited: set[str] = set()
    frontier = list(seeds)
    related_to: set[str] = set(seeds)
    while frontier:
        key = frontier.pop()
        if key in visited:
            continue
        visited.add(key)
        for parent in rev.get(key, []):
            pk = parent.lower()
            related_to.add(pk)
            if pk not in visited:
                frontier.append(pk)

    out = []
    for e in edges:
        to_l = str(e.get("to_dataset") or "").lower()
        from_l = str(e.get("from_dataset") or "").lower()
        to_short = to_l.split(".")[-1] if to_l else ""
        if (
            to_l in related_to
            or from_l in related_to
            or to_short in related_to
            or any(k in to_l or k in from_l for k in target_keys)
        ):
            out.append(e)
    return out[:100] if out else edges[:50]


def _upstream_edges(
    edges: list[dict],
    *,
    failed_node: str | None,
    relations: list[str],
    pipe_node: str | None = None,
) -> list[dict]:
    """Backward-compatible alias for lineage detail upstream slice."""
    return _lineage_slice(
        edges,
        failed_node=failed_node,
        relations=relations,
        direction="upstream",
    )


def _extract_compiled_sql(failed_nodes: list, raw_log: Any) -> dict[str, str]:
    out: dict[str, str] = {}
    for node in failed_nodes or []:
        if isinstance(node, dict) and node.get("compiled_sql"):
            uid = str(node.get("unique_id") or node.get("node") or "")
            if uid:
                out[uid] = str(node["compiled_sql"])
    raw = _parse_json_field(raw_log)
    if isinstance(raw, dict) and isinstance(raw.get("compiled_sql"), dict):
        for k, v in raw["compiled_sql"].items():
            out.setdefault(str(k), str(v))
    return out


def build_rca_context(conn, run_id: str) -> dict[str, Any]:
    """
    Assemble grounded RCA context for a pipeline run.
    Resolves vendor run id or obs_run_id.
    """
    run = fetchone(
        conn,
        """
        SELECT r.*, p.source_tool, p.source_schema, p.etl_tool, p.target_tool, p.target_schema
        FROM obs_pipeline_runs r
        LEFT JOIN obs_pipelines p ON p.pipeline_id = r.pipeline_id
        WHERE r.id = %s OR r.obs_run_id = %s
        LIMIT 1
        """,
        (run_id, run_id),
    )
    if not run:
        raise LookupError(f"Run not found: {run_id}")

    rid = str(run.get("id") or run_id)
    pid = str(run.get("pipeline_id") or "")

    relations = _parse_json_field(run.get("relations_json")) or []
    failed_nodes = _parse_json_field(run.get("failed_nodes_json")) or []

    assets = fetchall(
        conn,
        "SELECT * FROM obs_run_assets WHERE run_id = %s ORDER BY asset_role, object_name",
        (rid,),
    )
    columns = fetchall(
        conn,
        "SELECT * FROM obs_run_columns WHERE run_id = %s ORDER BY asset_role, object_name, ordinal_position",
        (rid,),
    )
    queries = fetchall(
        conn,
        "SELECT * FROM obs_run_query_history WHERE run_id = %s ORDER BY start_time DESC LIMIT 25",
        (rid,),
    )
    edges = fetchall(
        conn,
        """
        SELECT * FROM obs_lineage_edges
        WHERE run_id = %s OR (pipeline_id = %s AND run_id IS NULL)
        ORDER BY from_dataset, to_dataset
        LIMIT 500
        """,
        (rid, pid),
    )
    dbt_tests = fetchall(
        conn,
        """
        SELECT * FROM obs_check_results
        WHERE monitor_id = %s
        ORDER BY checked_at DESC
        """,
        (f"dbt-run:{rid}",),
    )
    dq_checks = fetchall(
        conn,
        """
        SELECT * FROM obs_check_results
        WHERE pipeline_id = %s
          AND checked_at >= DATE_SUB(NOW(), INTERVAL 7 DAY)
        ORDER BY checked_at DESC
        LIMIT 100
        """,
        (pid,),
    ) if pid else []

    incidents = fetchall(
        conn,
        """
        SELECT incident_id, pipeline_id, status, severity, title, description,
               opened_at, resolved_at, created_at
        FROM obs_incidents
        WHERE pipeline_id = %s
          AND LOWER(COALESCE(status, '')) IN ('open', 'investigating')
        ORDER BY COALESCE(opened_at, created_at) DESC
        LIMIT 10
        """,
        (pid,),
    ) if pid else []

    fresh_rows = load_pipeline_freshness(conn, pipeline_id=pid) if pid else []
    freshness = fresh_rows[0] if fresh_rows else {}

    edge_dicts = [{k: json_val(v) for k, v in e.items()} for e in edges]
    upstream = _lineage_slice(
        edge_dicts,
        failed_node=run.get("failed_node"),
        relations=relations if isinstance(relations, list) else [],
        direction="upstream",
    )
    downstream = _lineage_slice(
        edge_dicts,
        failed_node=run.get("failed_node"),
        relations=relations if isinstance(relations, list) else [],
        direction="downstream",
    )

    run_at = run.get("end_time") or run.get("start_time") or run.get("created_at")
    change_since = build_change_since_last_success(
        conn,
        pipeline_id=pid,
        run_id=rid,
        run_at=run_at,
        current_assets=assets,
        current_columns=columns,
    )

    compiled_sql = _extract_compiled_sql(
        failed_nodes if isinstance(failed_nodes, list) else [],
        run.get("raw_log"),
    )

    run_out = {k: json_val(v) for k, v in run.items() if k not in {"raw_log"}}
    run_out["duration_display"] = format_duration(run.get("duration"))
    run_out["relations"] = relations
    run_out["failed_nodes"] = failed_nodes

    failed_dq = [
        c for c in dq_checks
        if str(c.get("status") or "").lower() in {"fail", "failed", "error", "warn", "warning"}
    ]

    return {
        "ok": True,
        "run_id": rid,
        "obs_run_id": run.get("obs_run_id"),
        "pipeline_id": pid,
        "pipeline_name": run.get("pipeline_name"),
        "status": run.get("status"),
        "failure": {
            "stage": run.get("failure_stage"),
            "failed_node": run.get("failed_node"),
            "failed_message": run.get("failed_message"),
            "error_class": run.get("error_class"),
            "error_message": run.get("error_message"),
            "failed_nodes": failed_nodes,
        },
        "run": run_out,
        "pipeline": {
            "source_tool": run.get("source_tool"),
            "source_schema": run.get("source_schema"),
            "etl_tool": run.get("etl_tool"),
            "target_tool": run.get("target_tool"),
            "target_schema": run.get("target_schema"),
        },
        "relations": relations,
        "freshness": freshness,
        "assets": [{k: json_val(v) for k, v in a.items()} for a in assets],
        "columns": [{k: json_val(v) for k, v in c.items()} for c in columns],
        "query_history": [{k: json_val(v) for k, v in q.items()} for q in queries],
        "lineage_edges": edge_dicts,
        "lineage_upstream": upstream,
        "lineage_downstream": downstream,
        "dbt_tests": [{k: json_val(v) for k, v in t.items()} for t in dbt_tests],
        "dq_checks": [{k: json_val(v) for k, v in c.items()} for c in dq_checks],
        "open_incidents": [{k: json_val(v) for k, v in i.items()} for i in incidents],
        "change_since_last_success": change_since,
        "compiled_sql": compiled_sql,
        "summary": {
            "asset_count": len(assets),
            "column_count": len(columns),
            "query_count": len(queries),
            "lineage_edge_count": len(edges),
            "dbt_test_count": len(dbt_tests),
            "dq_check_count": len(dq_checks),
            "failed_dq_check_count": len(failed_dq),
            "failed_test_count": sum(
                1
                for t in dbt_tests
                if str(t.get("status") or "").lower() in {"fail", "failed", "error"}
            ),
            "volume_changes": change_since.get("volume_changes") if change_since.get("available") else 0,
            "schema_change_count": change_since.get("schema_change_count") if change_since.get("available") else 0,
            "compiled_sql_nodes": len(compiled_sql),
        },
    }
