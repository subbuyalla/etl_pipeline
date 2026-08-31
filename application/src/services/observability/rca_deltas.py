"""Change detection for RCA: compare current run vs last successful run."""

from __future__ import annotations

from typing import Any

from application.src.services.observability.filters import fetchall, fetchone, json_val
from application.src.services.observability.quality import normalize_dataset_id


def _last_successful_run(
    conn,
    pipeline_id: str,
    *,
    before_run_id: str,
    before_time: Any = None,
) -> dict | None:
    """Most recent successful run for pipeline before the given run."""
    if before_time is not None:
        row = fetchone(
            conn,
            """
            SELECT id, pipeline_id, pipeline_name, status,
                   start_time, end_time, created_at,
                   COALESCE(end_time, start_time, created_at) AS run_at
            FROM obs_pipeline_runs
            WHERE pipeline_id = %s
              AND id <> %s
              AND LOWER(COALESCE(status, '')) IN ('success', 'succeeded')
              AND COALESCE(end_time, start_time, created_at) <
                  COALESCE(%s, end_time, start_time, created_at)
            ORDER BY COALESCE(end_time, start_time, created_at) DESC
            LIMIT 1
            """,
            (pipeline_id, before_run_id, before_time),
        )
        if row:
            return row
    return fetchone(
        conn,
        """
        SELECT id, pipeline_id, pipeline_name, status,
               start_time, end_time, created_at,
               COALESCE(end_time, start_time, created_at) AS run_at
        FROM obs_pipeline_runs
        WHERE pipeline_id = %s
          AND id <> %s
          AND LOWER(COALESCE(status, '')) IN ('success', 'succeeded')
        ORDER BY COALESCE(end_time, start_time, created_at) DESC
        LIMIT 1
        """,
        (pipeline_id, before_run_id),
    )


def _asset_key(row: dict) -> str:
    ds = normalize_dataset_id(
        row.get("dataset_id")
        or ".".join(
            str(x or "")
            for x in (
                row.get("database_name"),
                row.get("schema_name"),
                row.get("object_name"),
            )
            if x
        )
    )
    role = str(row.get("asset_role") or "").upper()
    return f"{role}:{ds}" if ds else ""


def _column_key(row: dict) -> tuple[str, str, str, str]:
    return (
        str(row.get("database_name") or ""),
        str(row.get("schema_name") or ""),
        str(row.get("object_name") or ""),
        str(row.get("column_name") or ""),
    )


def compute_volume_deltas(
    current_assets: list[dict],
    previous_assets: list[dict],
) -> list[dict]:
    prev_by_key = {_asset_key(a): a for a in previous_assets if _asset_key(a)}
    deltas: list[dict] = []
    seen: set[str] = set()
    for cur in current_assets:
        key = _asset_key(cur)
        if not key or key in seen:
            continue
        seen.add(key)
        prev = prev_by_key.get(key)
        cur_rows = int(cur.get("row_count") or 0)
        prev_rows = int((prev or {}).get("row_count") or 0) if prev else None
        delta = None
        pct_change = None
        if prev_rows is not None:
            delta = cur_rows - prev_rows
            if prev_rows:
                pct_change = round(100.0 * delta / prev_rows, 2)
        ds = key.split(":", 1)[-1]
        deltas.append(
            {
                "dataset_id": ds,
                "asset_role": cur.get("asset_role"),
                "row_count_current": cur_rows,
                "row_count_previous": prev_rows,
                "row_delta": delta,
                "row_delta_pct": pct_change,
                "status": "new" if prev is None else "changed" if delta else "unchanged",
            }
        )
    return deltas


def compute_schema_diffs(
    current_columns: list[dict],
    previous_columns: list[dict],
) -> list[dict]:
    cur_map = {_column_key(c): c for c in current_columns}
    prev_map = {_column_key(c): c for c in previous_columns}
    events: list[dict] = []
    for key, col in cur_map.items():
        if key not in prev_map:
            events.append(
                {
                    "change_type": "column_added",
                    "database_name": col.get("database_name"),
                    "schema_name": col.get("schema_name"),
                    "object_name": col.get("object_name"),
                    "column_name": col.get("column_name"),
                    "data_type": col.get("data_type"),
                    "asset_role": col.get("asset_role"),
                }
            )
        else:
            old = prev_map[key]
            if str(col.get("data_type") or "") != str(old.get("data_type") or ""):
                events.append(
                    {
                        "change_type": "column_type_changed",
                        "database_name": col.get("database_name"),
                        "schema_name": col.get("schema_name"),
                        "object_name": col.get("object_name"),
                        "column_name": col.get("column_name"),
                        "data_type_current": col.get("data_type"),
                        "data_type_previous": old.get("data_type"),
                        "asset_role": col.get("asset_role"),
                    }
                )
    for key, col in prev_map.items():
        if key not in cur_map:
            events.append(
                {
                    "change_type": "column_removed",
                    "database_name": col.get("database_name"),
                    "schema_name": col.get("schema_name"),
                    "object_name": col.get("object_name"),
                    "column_name": col.get("column_name"),
                    "data_type": col.get("data_type"),
                    "asset_role": col.get("asset_role"),
                }
            )
    return events


def build_change_since_last_success(
    conn,
    *,
    pipeline_id: str,
    run_id: str,
    run_at: Any,
    current_assets: list[dict],
    current_columns: list[dict],
) -> dict[str, Any]:
    """Volume + schema deltas vs previous successful run."""
    if not pipeline_id:
        return {"available": False, "reason": "no pipeline_id"}

    prev = _last_successful_run(
        conn, pipeline_id, before_run_id=str(run_id), before_time=run_at
    )
    if not prev:
        return {"available": False, "reason": "no prior successful run"}

    prev_id = str(prev.get("id") or "")
    prev_assets = fetchall(
        conn,
        "SELECT * FROM obs_run_assets WHERE run_id = %s",
        (prev_id,),
    )
    prev_columns = fetchall(
        conn,
        "SELECT * FROM obs_run_columns WHERE run_id = %s",
        (prev_id,),
    )

    volume_deltas = compute_volume_deltas(current_assets, prev_assets)
    schema_diffs = compute_schema_diffs(current_columns, prev_columns)

    return {
        "available": True,
        "previous_run_id": prev_id,
        "previous_run_at": json_val(prev.get("run_at")),
        "previous_status": prev.get("status"),
        "volume_deltas": volume_deltas,
        "schema_diffs": schema_diffs,
        "volume_changes": sum(
            1 for v in volume_deltas if v.get("status") != "unchanged"
        ),
        "schema_change_count": len(schema_diffs),
    }
