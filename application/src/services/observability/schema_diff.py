"""Schema drift: compare TARGET columns between latest two successful runs."""

from __future__ import annotations

from typing import Any, Optional

from application.src.api.schemas import make_kpi
from application.src.services.observability.filters import (
    age_label,
    envelope,
    fetchall,
    json_val,
    num,
    parse_range,
    pct,
    utc_now,
)


def _success_runs_by_pipeline(conn) -> dict[str, list[dict]]:
    rows = fetchall(
        conn,
        """
        SELECT id, pipeline_id, pipeline_name,
               COALESCE(end_time, start_time, created_at) AS ts
        FROM obs_pipeline_runs
        WHERE LOWER(COALESCE(status, '')) IN ('success', 'succeeded')
        ORDER BY pipeline_id, COALESCE(end_time, start_time, created_at) DESC
        """,
    )
    by: dict[str, list[dict]] = {}
    for r in rows:
        pid = str(r.get("pipeline_id") or "")
        by.setdefault(pid, []).append(r)
    return by


def _columns_for_run(conn, run_id: str) -> list[dict]:
    return fetchall(
        conn,
        """
        SELECT database_name, schema_name, object_name, column_name, data_type, ordinal_position
        FROM obs_run_columns
        WHERE run_id = %s AND UPPER(COALESCE(asset_role, '')) = 'TARGET'
        ORDER BY object_name, ordinal_position, column_name
        """,
        (str(run_id),),
    )


def _col_key(c: dict) -> tuple:
    return (
        str(c.get("database_name") or ""),
        str(c.get("schema_name") or ""),
        str(c.get("object_name") or ""),
        str(c.get("column_name") or ""),
    )


def compute_schema_changes(conn) -> list[dict]:
    by_pipe = _success_runs_by_pipeline(conn)
    events: list[dict] = []
    now = utc_now()

    for pid, runs in by_pipe.items():
        if len(runs) < 2:
            continue
        newer, older = runs[0], runs[1]
        new_cols = _columns_for_run(conn, newer["id"])
        old_cols = _columns_for_run(conn, older["id"])
        if not new_cols and not old_cols:
            continue

        new_map = {_col_key(c): c for c in new_cols}
        old_map = {_col_key(c): c for c in old_cols}

        for key, c in new_map.items():
            if key not in old_map:
                events.append(
                    {
                        "time": json_val(newer.get("ts")),
                        "age": age_label(newer.get("ts"), now),
                        "pipeline_id": pid,
                        "pipeline_name": newer.get("pipeline_name"),
                        "object_name": c.get("object_name"),
                        "dataset": f"{c.get('database_name')}.{c.get('schema_name')}.{c.get('object_name')}",
                        "change_type": "add_column",
                        "impact": "non_breaking",
                        "summary": f"Added column {c.get('column_name')} ({c.get('data_type')})",
                        "from_run_id": older.get("id"),
                        "to_run_id": newer.get("id"),
                    }
                )
            else:
                old_t = str(old_map[key].get("data_type") or "")
                new_t = str(c.get("data_type") or "")
                if old_t and new_t and old_t.lower() != new_t.lower():
                    events.append(
                        {
                            "time": json_val(newer.get("ts")),
                            "age": age_label(newer.get("ts"), now),
                            "pipeline_id": pid,
                            "pipeline_name": newer.get("pipeline_name"),
                            "object_name": c.get("object_name"),
                            "dataset": f"{c.get('database_name')}.{c.get('schema_name')}.{c.get('object_name')}",
                            "change_type": "modify_column",
                            "impact": "breaking",
                            "summary": f"Modified {c.get('column_name')}: {old_t} → {new_t}",
                            "from_run_id": older.get("id"),
                            "to_run_id": newer.get("id"),
                        }
                    )

        for key, c in old_map.items():
            if key not in new_map:
                events.append(
                    {
                        "time": json_val(newer.get("ts")),
                        "age": age_label(newer.get("ts"), now),
                        "pipeline_id": pid,
                        "pipeline_name": newer.get("pipeline_name"),
                        "object_name": c.get("object_name"),
                        "dataset": f"{c.get('database_name')}.{c.get('schema_name')}.{c.get('object_name')}",
                        "change_type": "drop_column",
                        "impact": "breaking",
                        "summary": f"Dropped column {c.get('column_name')} ({c.get('data_type')})",
                        "from_run_id": older.get("id"),
                        "to_run_id": newer.get("id"),
                    }
                )

    events.sort(key=lambda e: e.get("time") or "", reverse=True)
    return events


def schema_health_score(conn) -> dict[str, Any]:
    events = compute_schema_changes(conn)
    if not events:
        # No diffs available — still "available" with 100 if we have column snapshots
        has_cols = fetchall(conn, "SELECT 1 AS x FROM obs_run_columns LIMIT 1")
        if not has_cols:
            return {"score": None, "available": False, "changes": 0, "breaking": 0}
        return {"score": 100.0, "available": True, "changes": 0, "breaking": 0}
    breaking = sum(1 for e in events if e.get("impact") == "breaking")
    total = len(events)
    non_breaking = total - breaking
    score = pct(non_breaking, total)
    return {"score": score, "available": True, "changes": total, "breaking": breaking}


def build_schema_page(
    conn,
    *,
    preset: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    pipeline_name: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    rng = parse_range(preset, start_date, end_date, start_time, end_time)
    events = compute_schema_changes(conn)
    if pipeline_name:
        names = {n.strip() for n in pipeline_name.split(",") if n.strip()}
        events = [e for e in events if e.get("pipeline_name") in names]

    # Optional filter by range on event time
    if rng.get("preset") != "all":
        from_s = rng.get("from_str") or ""
        to_s = rng.get("to_str") or ""
        filtered = []
        for e in events:
            t = e.get("time") or ""
            if from_s and t < from_s:
                continue
            if to_s and t > to_s:
                continue
            filtered.append(e)
        events = filtered

    breaking = sum(1 for e in events if e.get("impact") == "breaking")
    total = len(events)
    compatibility = pct(total - breaking, total) if total else 100.0

    type_counts: dict[str, int] = {}
    for e in events:
        ct = e.get("change_type") or "unknown"
        type_counts[ct] = type_counts.get(ct, 0) + 1

    monitored = fetchall(
        conn,
        "SELECT COUNT(DISTINCT CONCAT(database_name,'.',schema_name,'.',object_name)) AS n FROM obs_run_columns",
    )
    schemas_monitored = int(num((monitored[0] if monitored else {}).get("n")))

    page = max(1, int(page or 1))
    page_size = max(1, min(int(page_size or 20), 100))
    start = (page - 1) * page_size

    kpis = [
        make_kpi(id="schema_changes", title="Schema Changes", value=total, display=str(total)),
        make_kpi(
            id="breaking_changes",
            title="Breaking Changes",
            value=breaking,
            display=str(breaking),
            tone="bad" if breaking else "ok",
        ),
        make_kpi(
            id="compatibility",
            title="Compatibility",
            value=compatibility,
            display=f"{compatibility}%" if compatibility is not None else "N/A",
            available=compatibility is not None,
            tone="ok" if (compatibility or 0) >= 90 else "warn",
        ),
        make_kpi(
            id="schemas_monitored",
            title="Schemas Monitored",
            value=schemas_monitored,
            display=str(schemas_monitored),
        ),
    ]

    return envelope(
        rng=rng,
        filters_applied={"pipeline_name": pipeline_name, "preset": rng.get("preset")},
        kpis=kpis,
        series={},
        charts={
            "by_type": [{"change_type": k, "count": v} for k, v in type_counts.items()],
            "by_impact": [
                {"impact": "non_breaking", "count": total - breaking},
                {"impact": "breaking", "count": breaking},
            ],
        },
        items=events[start : start + page_size],
        page=page,
        page_size=page_size,
        total=total,
        summary={"changes": total, "breaking": breaking, "compatibility_pct": compatibility},
        meta={
            "formula": (
                "Compare TARGET columns between latest two successful runs per pipeline. "
                "Add=non_breaking; drop/type-change=breaking."
            ),
            "available": True,
        },
    )
