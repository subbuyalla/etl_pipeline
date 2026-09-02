"""Volume: TARGET row/byte totals with period-over-period change (safe aggregates)."""

from __future__ import annotations

from typing import Any, Optional

from application.src.api.schemas import make_kpi
from application.src.services.observability.filters import (
    age_label,
    apply_delta,
    build_run_where,
    chart_bucket_grain,
    delta_pct,
    envelope,
    fetchall,
    fetchone,
    json_val,
    num,
    parse_range,
    pct,
    sql_time_bucket_expr,
    volume_drop_crit_pct,
    volume_drop_warn_pct,
    zero_fill_series,
)


def _target_assets_subquery() -> str:
    """Per-run TARGET aggregates; NULL row_count excluded from SUM (unknown, not zero)."""
    return """
          SELECT
            a.run_id,
            SUM(a.row_count) AS target_rows,
            SUM(COALESCE(a.size_bytes, 0)) AS target_bytes,
            SUM(CASE WHEN a.row_count IS NOT NULL THEN 1 ELSE 0 END) AS rows_known
          FROM obs_run_assets a
          WHERE UPPER(COALESCE(a.asset_role, '')) = 'TARGET'
          GROUP BY a.run_id
    """


def _run_volume_totals(conn, from_str: str, to_str: str, *, pipeline_name=None, pipeline_id=None, tool=None) -> dict:
    where, params = build_run_where(
        alias="r",
        pipeline_name=pipeline_name,
        pipeline_id=pipeline_id,
        tool=tool,
        from_str=from_str,
        to_str=to_str,
    )
    # Aggregate TARGET assets per run first, then sum — avoids cartesian blow-up
    sql = f"""
        SELECT
          COALESCE(SUM(t.target_rows), 0) AS total_rows,
          COALESCE(SUM(t.target_bytes), 0) AS total_bytes,
          COUNT(DISTINCT r.pipeline_id) AS pipelines_with_runs,
          COUNT(DISTINCT r.id) AS run_count
        FROM obs_pipeline_runs r
        LEFT JOIN (
          {_target_assets_subquery()}
        ) t ON t.run_id = CAST(r.id AS CHAR)
        {where}
    """
    return fetchone(conn, sql, params)


def _latest_target_counts_available(conn, *, pipeline_name=None, pipeline_id=None, tool=None) -> bool:
    """True when the latest run in scope has at least one TARGET asset with row_count."""
    where, params = build_run_where(
        alias="r",
        pipeline_name=pipeline_name,
        pipeline_id=pipeline_id,
        tool=tool,
    )
    row = fetchone(
        conn,
        f"""
        SELECT COALESCE(SUM(CASE WHEN a.row_count IS NOT NULL THEN 1 ELSE 0 END), 0) AS known
        FROM obs_run_assets a
        INNER JOIN (
          SELECT r.id AS run_id
          FROM obs_pipeline_runs r
          {where}
          ORDER BY COALESCE(r.end_time, r.start_time, r.created_at) DESC
          LIMIT 1
        ) latest ON latest.run_id = CAST(a.run_id AS CHAR)
        WHERE UPPER(COALESCE(a.asset_role, '')) = 'TARGET'
        """,
        params,
    )
    return int(num((row or {}).get("known"))) > 0


def _per_pipeline_volume(
    conn, from_str: str, to_str: str, *, pipeline_name=None, pipeline_id=None, tool=None
) -> list[dict]:
    where, params = build_run_where(
        alias="r",
        pipeline_name=pipeline_name,
        pipeline_id=pipeline_id,
        tool=tool,
        from_str=from_str,
        to_str=to_str,
    )
    sql = f"""
        SELECT
          r.pipeline_id,
          r.pipeline_name,
          COALESCE(SUM(t.target_rows), 0) AS records,
          COALESCE(SUM(t.target_bytes), 0) AS bytes,
          MAX(COALESCE(r.end_time, r.start_time, r.created_at)) AS last_run_at,
          COUNT(DISTINCT r.id) AS runs
        FROM obs_pipeline_runs r
        LEFT JOIN (
          {_target_assets_subquery()}
        ) t ON t.run_id = CAST(r.id AS CHAR)
        {where}
        GROUP BY r.pipeline_id, r.pipeline_name
        ORDER BY records DESC
    """
    return fetchall(conn, sql, params)


def _series_volume(
    conn, from_str: str, to_str: str, *, pipeline_name=None, pipeline_id=None, tool=None, grain="hour"
) -> list[dict]:
    where, params = build_run_where(
        alias="r",
        pipeline_name=pipeline_name,
        pipeline_id=pipeline_id,
        tool=tool,
        from_str=from_str,
        to_str=to_str,
    )
    bucket_expr = sql_time_bucket_expr("r", grain)
    sql = f"""
        SELECT
          {bucket_expr} AS bucket,
          COALESCE(SUM(t.target_rows), 0) AS records,
          COALESCE(SUM(t.target_bytes), 0) AS bytes
        FROM obs_pipeline_runs r
        LEFT JOIN (
          {_target_assets_subquery()}
        ) t ON t.run_id = CAST(r.id AS CHAR)
        {where}
        GROUP BY bucket
        ORDER BY bucket ASC
    """
    return fetchall(conn, sql, params)


def _volume_status(change_pct: float | None) -> str:
    if change_pct is None:
        return "unknown"
    drop = -change_pct if change_pct < 0 else 0
    if drop >= volume_drop_crit_pct():
        return "failed"
    if drop >= volume_drop_warn_pct():
        return "degraded"
    return "healthy"


def _is_pipeline_volume_healthy(
    change: float | None,
    *,
    cur_records: float | None,
    had_current_run: bool,
) -> bool:
    if _volume_status(change) == "healthy":
        return True
    if change is None and had_current_run and num(cur_records) > 0:
        return True
    return False


def _fmt_bytes(n: float) -> str:
    if n >= 1024**4:
        return f"{n / (1024**4):.2f} TB"
    if n >= 1024**3:
        return f"{n / (1024**3):.2f} GB"
    if n >= 1024**2:
        return f"{n / (1024**2):.2f} MB"
    if n >= 1024:
        return f"{n / 1024:.1f} KB"
    return f"{int(n)} B"


def _fmt_rows(n: float) -> str:
    if n >= 1_000_000_000:
        return f"{n / 1_000_000_000:.2f}B"
    if n >= 1_000_000:
        return f"{n / 1_000_000:.2f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(int(n))


def build_volume_page(
    conn,
    *,
    preset: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    pipeline_name: Optional[str] = None,
    pipeline_id: Optional[str] = None,
    tool: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    rng = parse_range(preset, start_date, end_date, start_time, end_time)
    cur = _run_volume_totals(
        conn, rng["from_str"], rng["to_str"],
        pipeline_name=pipeline_name, pipeline_id=pipeline_id, tool=tool,
    )
    prev = _run_volume_totals(
        conn, rng["prev_from_str"], rng["prev_to_str"],
        pipeline_name=pipeline_name, pipeline_id=pipeline_id, tool=tool,
    )
    cur_rows = num(cur.get("total_rows"))
    prev_rows = num(prev.get("total_rows"))
    cur_bytes = num(cur.get("total_bytes"))
    prev_bytes = num(prev.get("total_bytes"))
    rows_delta = apply_delta(delta_pct(cur_rows, prev_rows), rng)
    bytes_delta = apply_delta(delta_pct(cur_bytes, prev_bytes), rng)

    pipe_count = fetchone(conn, "SELECT COUNT(*) AS n FROM obs_pipelines")
    total_pipelines = int(num(pipe_count.get("n")))
    active = int(num(cur.get("pipelines_with_runs")))

    per = _per_pipeline_volume(
        conn, rng["from_str"], rng["to_str"],
        pipeline_name=pipeline_name, pipeline_id=pipeline_id, tool=tool,
    )
    prev_per = {
        r["pipeline_id"]: r
        for r in _per_pipeline_volume(
            conn, rng["prev_from_str"], rng["prev_to_str"],
            pipeline_name=pipeline_name, pipeline_id=pipeline_id, tool=tool,
        )
    }

    items = []
    for r in per:
        pid = r.get("pipeline_id")
        prev_r = prev_per.get(pid) or {}
        change = apply_delta(delta_pct(num(r.get("records")), num(prev_r.get("records"))), rng)
        status_key = (
            "healthy"
            if _is_pipeline_volume_healthy(
                change, cur_records=num(r.get("records")), had_current_run=True
            )
            else _volume_status(change)
        )
        items.append(
            {
                "pipeline_id": pid,
                "pipeline_name": r.get("pipeline_name"),
                "records": int(num(r.get("records"))),
                "records_display": _fmt_rows(num(r.get("records"))),
                "bytes": int(num(r.get("bytes"))),
                "bytes_display": _fmt_bytes(num(r.get("bytes"))),
                "pct_change": change,
                "status": status_key.title(),
                "status_key": status_key,
                "runs": int(num(r.get("runs"))),
                "last_updated_at": json_val(r.get("last_run_at")),
                "last_updated_age": age_label(r.get("last_run_at")),
            }
        )

    grain = chart_bucket_grain(rng)
    series_rows = _series_volume(
        conn, rng["from_str"], rng["to_str"],
        pipeline_name=pipeline_name, pipeline_id=pipeline_id, tool=tool, grain=grain,
    )
    raw_labels = [json_val(s.get("bucket")) for s in series_rows]
    filled_labels, filled = zero_fill_series(
        raw_labels,
        {
            "records": [int(num(s.get("records"))) for s in series_rows],
            "bytes": [int(num(s.get("bytes"))) for s in series_rows],
        },
        rng,
        grain=grain,
    )
    series = {
        "volume_over_time": [
            {
                "timestamp": lab,
                "records": rec,
                "bytes": byt,
                "volume_gb": round(byt / (1024**3), 4),
            }
            for lab, rec, byt in zip(filled_labels, filled["records"], filled["bytes"])
        ]
    }
    charts = {
        "by_pipeline": [
            {
                "pipeline_name": i["pipeline_name"],
                "records": i["records"],
                "bytes": i["bytes"],
                "share_pct": pct(i["records"], cur_rows) or 0,
            }
            for i in items[:10]
        ]
    }

    kpis = [
        make_kpi(
            id="data_received",
            title="Data Received",
            value=cur_bytes,
            display=_fmt_bytes(cur_bytes),
            delta=bytes_delta,
            delta_label="vs previous period",
            tone="ok",
        ),
        make_kpi(
            id="records_received",
            title="Records Received",
            value=cur_rows,
            display=_fmt_rows(cur_rows),
            delta=rows_delta,
            delta_label="vs previous period",
            tone="ok",
        ),
        make_kpi(
            id="pipelines_active",
            title="Pipelines Active",
            value=active,
            display=f"{active} / {total_pipelines}",
            tone="ok" if total_pipelines and active >= total_pipelines * 0.8 else "warn",
        ),
        make_kpi(
            id="runs",
            title="Runs",
            value=int(num(cur.get("run_count"))),
            display=str(int(num(cur.get("run_count")))),
        ),
    ]

    page = max(1, int(page or 1))
    page_size = max(1, min(int(page_size or 20), 100))
    start = (page - 1) * page_size

    return envelope(
        rng=rng,
        filters_applied={
            "pipeline_name": pipeline_name,
            "pipeline_id": pipeline_id,
            "tool": tool,
            "preset": rng.get("preset"),
        },
        kpis=kpis,
        series=series,
        charts=charts,
        items=items[start : start + page_size],
        page=page,
        page_size=page_size,
        total=len(items),
        summary={
            "total_rows": cur_rows,
            "total_bytes": cur_bytes,
            "prev_rows": prev_rows,
            "prev_bytes": prev_bytes,
        },
        meta={
            "formula": "SUM(TARGET row_count/size_bytes) per run in range; NULL row_count treated as unknown.",
            "byte_note": "1 TB = 1024 GB",
            "records_available": _latest_target_counts_available(
                conn,
                pipeline_name=pipeline_name,
                pipeline_id=pipeline_id,
                tool=tool,
            ),
        },
    )


def volume_health_score(conn, from_str: str, to_str: str, prev_from: str, prev_to: str) -> dict[str, Any]:
    """Overview pillar: % of pipelines without critical volume drop (cur ∪ prev)."""
    cur_list = _per_pipeline_volume(conn, from_str, to_str)
    prev_list = _per_pipeline_volume(conn, prev_from, prev_to)
    cur_map = {r["pipeline_id"]: r for r in cur_list}
    prev_map = {r["pipeline_id"]: r for r in prev_list}
    all_pids = set(cur_map) | set(prev_map)
    if not all_pids:
        return {"score": None, "available": False, "healthy": 0, "total": 0}
    healthy = 0
    for pid in all_pids:
        cur_r = cur_map.get(pid)
        prev_r = prev_map.get(pid) or {}
        if cur_r is None:
            # Had volume previously but missing in current window → severe drop
            change = -100.0 if num(prev_r.get("records")) > 0 else None
        else:
            change = delta_pct(num(cur_r.get("records")), num(prev_r.get("records")))
        cur_records = num(cur_r.get("records")) if cur_r else None
        if _is_pipeline_volume_healthy(
            change, cur_records=cur_records, had_current_run=cur_r is not None
        ):
            healthy += 1
    score = pct(healthy, len(all_pids))
    return {"score": score, "available": True, "healthy": healthy, "total": len(all_pids)}
