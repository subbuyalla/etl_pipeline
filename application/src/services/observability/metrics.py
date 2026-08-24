"""Metrics page aggregates from obs_pipeline_runs + freshness."""

from __future__ import annotations

from typing import Any, Optional

from application.src.api.schemas import make_kpi
from application.src.services.observability.filters import (
    age_label,
    build_run_where,
    delta_pct,
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


def _run_stats(conn, from_str, to_str, **filters) -> dict:
    where, params = build_run_where(
        alias="r",
        from_str=from_str,
        to_str=to_str,
        pipeline_name=filters.get("pipeline_name"),
        pipeline_id=filters.get("pipeline_id"),
        status=filters.get("status"),
        tool=filters.get("tool"),
    )
    return fetchone(
        conn,
        f"""
        SELECT
          COUNT(*) AS total_runs,
          SUM(CASE WHEN LOWER(COALESCE(status,'')) IN ('success','succeeded') THEN 1 ELSE 0 END) AS success_runs,
          SUM(CASE WHEN LOWER(COALESCE(status,'')) IN ('failed','error') THEN 1 ELSE 0 END) AS failed_runs,
          SUM(CASE WHEN LOWER(COALESCE(status,'')) = 'running' THEN 1 ELSE 0 END) AS running_runs,
          AVG(duration) AS avg_duration
        FROM obs_pipeline_runs r
        {where}
        """,
        params,
    )


def build_metrics_page(
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
    rng = parse_range(preset or "15m", start_date, end_date, start_time, end_time)
    filt = dict(pipeline_name=pipeline_name, pipeline_id=pipeline_id, tool=tool)
    cur = _run_stats(conn, rng["from_str"], rng["to_str"], **filt)
    prev = _run_stats(conn, rng["prev_from_str"], rng["prev_to_str"], **filt)

    total = num(cur.get("total_runs"))
    success = num(cur.get("success_runs"))
    failed = num(cur.get("failed_runs"))
    avg_dur = num(cur.get("avg_duration")) if cur.get("avg_duration") is not None else None
    success_rate = pct(success, total)

    prev_total = num(prev.get("total_runs"))
    prev_success = num(prev.get("success_runs"))
    prev_failed = num(prev.get("failed_runs"))
    prev_avg = num(prev.get("avg_duration")) if prev.get("avg_duration") is not None else None
    prev_rate = pct(prev_success, prev_total)

    fresh_rows = load_pipeline_freshness(conn, pipeline_name=pipeline_name, pipeline_id=pipeline_id)
    lags = [num(r.get("current_lag_hours")) for r in fresh_rows if r.get("current_lag_hours") is not None]
    avg_fresh = round(sum(lags) / len(lags), 2) if lags else None

    # Frequency: runs / hours in window
    window_hours = max(
        (rng["to"] - rng["from"]).total_seconds() / 3600.0,
        1 / 60.0,
    )
    freq = round(total / window_hours, 2) if window_hours else None

    where, params = build_run_where(
        alias="r",
        from_str=rng["from_str"],
        to_str=rng["to_str"],
        **filt,
    )
    duration_series = fetchall(
        conn,
        f"""
        SELECT
          DATE_FORMAT(COALESCE(r.end_time, r.start_time), '%%Y-%%m-%%d %%H:%%i') AS ts,
          r.pipeline_name,
          r.duration
        FROM obs_pipeline_runs r
        {where}
        AND r.duration IS NOT NULL
        ORDER BY COALESCE(r.end_time, r.start_time) ASC
        LIMIT 500
        """,
        params,
    )
    success_series = fetchall(
        conn,
        f"""
        SELECT
          DATE_FORMAT(COALESCE(r.end_time, r.start_time), '%%Y-%%m-%%d %%H:00') AS bucket,
          SUM(CASE WHEN LOWER(COALESCE(status,'')) IN ('success','succeeded') THEN 1 ELSE 0 END) AS success_cnt,
          COUNT(*) AS total_cnt
        FROM obs_pipeline_runs r
        {where}
        GROUP BY bucket
        ORDER BY bucket ASC
        """,
        params,
    )

    # Per-pipeline live table
    per = fetchall(
        conn,
        f"""
        SELECT
          r.pipeline_id,
          r.pipeline_name,
          MAX(r.tool_name) AS tool_name,
          COUNT(*) AS runs,
          SUM(CASE WHEN LOWER(COALESCE(status,'')) IN ('success','succeeded') THEN 1 ELSE 0 END) AS success_runs,
          AVG(duration) AS avg_duration,
          MAX(COALESCE(end_time, start_time, created_at)) AS last_run_at,
          SUBSTRING_INDEX(
            GROUP_CONCAT(status ORDER BY COALESCE(end_time, start_time, created_at) DESC),
            ',', 1
          ) AS latest_status
        FROM obs_pipeline_runs r
        {where}
        GROUP BY r.pipeline_id, r.pipeline_name
        ORDER BY last_run_at DESC
        """,
        params,
    )
    open_inc = {
        i["pipeline_id"]
        for i in list_derived_incidents(conn, include_resolved=False)
        if i.get("status") == "open"
    }
    fresh_map = {r["pipeline_id"]: r for r in fresh_rows}

    items = []
    for r in per:
        pid = r.get("pipeline_id")
        runs = num(r.get("runs"))
        sr = pct(num(r.get("success_runs")), runs)
        fr = fresh_map.get(pid) or {}
        st = str(r.get("latest_status") or "").lower()
        if pid in open_inc or st in {"failed", "error"}:
            health = "failed"
        elif fr.get("status_key") in {"delayed", "stale"}:
            health = "degraded"
        else:
            health = "healthy"
        items.append(
            {
                "pipeline_id": pid,
                "pipeline_name": r.get("pipeline_name"),
                "tool": r.get("tool_name"),
                "status": health.title(),
                "status_key": health,
                "last_run_at": json_val(r.get("last_run_at")),
                "last_run_age": age_label(r.get("last_run_at")),
                "duration": format_duration(r.get("avg_duration")),
                "avg_duration_seconds": num(r.get("avg_duration")) if r.get("avg_duration") is not None else None,
                "success_rate_pct": sr,
                "avg_freshness_hours": fr.get("current_lag_hours"),
                "avg_freshness_display": fr.get("current_lag_display") or "N/A",
                "runs": int(runs),
            }
        )

    top_duration = sorted(
        items,
        key=lambda x: x.get("avg_duration_seconds") or 0,
        reverse=True,
    )[:5]

    kpis = [
        make_kpi(
            id="avg_duration",
            title="Average Duration",
            value=avg_dur,
            display=format_duration(avg_dur) or "N/A",
            delta=delta_pct(avg_dur, prev_avg) if avg_dur is not None else None,
            delta_label="vs previous period",
            available=avg_dur is not None,
        ),
        make_kpi(
            id="runs",
            title="Runs",
            value=int(total),
            display=str(int(total)),
            delta=delta_pct(total, prev_total),
            delta_label="vs previous period",
        ),
        make_kpi(
            id="failed_runs",
            title="Failed Runs",
            value=int(failed),
            display=str(int(failed)),
            delta=delta_pct(failed, prev_failed),
            delta_label="vs previous period",
            tone="bad" if failed else "ok",
        ),
        make_kpi(
            id="success_rate",
            title="Success Rate",
            value=success_rate,
            display=f"{success_rate}%" if success_rate is not None else "N/A",
            delta=(
                round(success_rate - prev_rate, 1)
                if success_rate is not None and prev_rate is not None
                else None
            ),
            delta_label="vs previous period",
            available=success_rate is not None,
            tone="ok" if (success_rate or 0) >= 90 else "warn",
        ),
        make_kpi(
            id="avg_freshness",
            title="Avg Freshness",
            value=avg_fresh,
            display=f"{avg_fresh}h" if avg_fresh is not None else "N/A",
            available=avg_fresh is not None,
        ),
        make_kpi(
            id="run_frequency",
            title="Avg Run Frequency",
            value=freq,
            display=f"{freq} runs/hr" if freq is not None else "N/A",
            available=freq is not None,
        ),
    ]

    page = max(1, int(page or 1))
    page_size = max(1, min(int(page_size or 20), 100))
    start = (page - 1) * page_size

    return envelope(
        rng=rng,
        filters_applied={**filt, "preset": rng.get("preset")},
        kpis=kpis,
        series={
            "duration": [
                {
                    "timestamp": json_val(d.get("ts")),
                    "pipeline_name": d.get("pipeline_name"),
                    "duration_seconds": num(d.get("duration")),
                }
                for d in duration_series
            ],
            "success_rate_over_time": [
                {
                    "timestamp": json_val(s.get("bucket")),
                    "success_rate_pct": pct(num(s.get("success_cnt")), num(s.get("total_cnt"))),
                }
                for s in success_series
            ],
        },
        charts={
            "runs_by_status": {
                "success": int(success),
                "failed": int(failed),
                "running": int(num(cur.get("running_runs"))),
                "cancelled": int(max(0, total - success - failed - num(cur.get("running_runs")))),
            },
            "top_by_duration": top_duration,
        },
        items=items[start : start + page_size],
        page=page,
        page_size=page_size,
        total=len(items),
        summary={
            "total_runs": int(total),
            "success_runs": int(success),
            "failed_runs": int(failed),
            "success_rate_pct": success_rate,
        },
    )
