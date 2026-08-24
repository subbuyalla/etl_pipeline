"""Freshness: lag vs SLA → Fresh / Delayed / Stale."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from application.src.api.schemas import make_kpi
from application.src.services.observability.filters import (
    age_label,
    envelope,
    fetchall,
    freshness_sla_hours,
    json_val,
    num,
    parse_range,
    pct,
    utc_now,
)


def _parse_ts(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None) if value.tzinfo else value
    text = str(value).replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text.replace(" ", "T"))
        return dt.replace(tzinfo=None) if dt.tzinfo else dt
    except ValueError:
        return None


def classify_lag(lag_hours: float | None, sla_hours: float) -> str:
    if lag_hours is None:
        return "stale"
    if lag_hours <= sla_hours:
        return "fresh"
    if lag_hours <= 2 * sla_hours:
        return "delayed"
    return "stale"


def load_pipeline_freshness(conn, *, pipeline_name: Optional[str] = None, pipeline_id: Optional[str] = None) -> list[dict]:
    """
    One row per pipeline:
    last_success_at = max TARGET last_updated_at on latest successful run,
    else last successful run end_time/start_time.
    """
    # Latest successful run per pipeline
    sql = f"""
        SELECT
          p.pipeline_id,
          p.pipeline_name,
          p.source_tool,
          p.etl_tool,
          p.target_tool,
          lr.id AS run_id,
          lr.status AS latest_success_status,
          lr.end_time AS run_end_time,
          lr.start_time AS run_start_time,
          (
            SELECT MAX(a.last_updated_at)
            FROM obs_run_assets a
            WHERE a.run_id = CAST(lr.id AS CHAR)
              AND UPPER(COALESCE(a.asset_role, '')) = 'TARGET'
          ) AS target_last_updated_at
        FROM obs_pipelines p
        LEFT JOIN obs_pipeline_runs lr
          ON lr.id = (
            SELECT r.id
            FROM obs_pipeline_runs r
            WHERE r.pipeline_id = p.pipeline_id
              AND LOWER(COALESCE(r.status, '')) IN ('success', 'succeeded')
            ORDER BY COALESCE(r.end_time, r.start_time, r.created_at) DESC
            LIMIT 1
          )
    """
    # Optional filter on pipeline list
    extra_clauses = []
    extra_params: list[Any] = []
    if pipeline_name:
        names = [n.strip() for n in pipeline_name.split(",") if n.strip()]
        if names:
            ph = ",".join(["%s"] * len(names))
            extra_clauses.append(f"p.pipeline_name IN ({ph})")
            extra_params.extend(names)
    if pipeline_id:
        ids = [i.strip() for i in pipeline_id.split(",") if i.strip()]
        if ids:
            ph = ",".join(["%s"] * len(ids))
            extra_clauses.append(f"p.pipeline_id IN ({ph})")
            extra_params.extend(ids)
    if extra_clauses:
        sql += " WHERE " + " AND ".join(extra_clauses)

    sql += " ORDER BY p.pipeline_name"
    rows = fetchall(conn, sql, extra_params)

    sla = freshness_sla_hours()
    now = utc_now()
    out = []
    for r in rows:
        last_success = _parse_ts(r.get("target_last_updated_at")) or _parse_ts(
            r.get("run_end_time")
        ) or _parse_ts(r.get("run_start_time"))
        lag_hours = None
        if last_success:
            lag_hours = max(0.0, (now - last_success).total_seconds() / 3600.0)
        status = classify_lag(lag_hours, sla)
        out.append(
            {
                "pipeline_id": r.get("pipeline_id"),
                "pipeline_name": r.get("pipeline_name"),
                "source_tool": r.get("source_tool"),
                "etl_tool": r.get("etl_tool"),
                "target_tool": r.get("target_tool"),
                "run_id": r.get("run_id"),
                "last_updated_at": json_val(last_success),
                "last_updated_age": age_label(last_success, now),
                "sla_hours": sla,
                "current_lag_hours": round(lag_hours, 2) if lag_hours is not None else None,
                "current_lag_display": (
                    f"{int(lag_hours)}h" if lag_hours is not None and lag_hours >= 1
                    else (f"{int((lag_hours or 0) * 60)}m" if lag_hours is not None else "N/A")
                ),
                "status": status.title(),
                "status_key": status,
            }
        )
    return out


def freshness_summary(rows: list[dict]) -> dict[str, Any]:
    total = len(rows)
    fresh = sum(1 for r in rows if r.get("status_key") == "fresh")
    delayed = sum(1 for r in rows if r.get("status_key") == "delayed")
    stale = sum(1 for r in rows if r.get("status_key") == "stale")
    lags = [num(r.get("current_lag_hours")) for r in rows if r.get("current_lag_hours") is not None]
    avg_lag = round(sum(lags) / len(lags), 2) if lags else None
    return {
        "monitored": total,
        "fresh": fresh,
        "delayed": delayed,
        "stale": stale,
        "fresh_pct": pct(fresh, total),
        "avg_lag_hours": avg_lag,
    }


def build_freshness_page(
    conn,
    *,
    preset: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    pipeline_name: Optional[str] = None,
    pipeline_id: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    rng = parse_range(preset, start_date, end_date, start_time, end_time)
    rows = load_pipeline_freshness(conn, pipeline_name=pipeline_name, pipeline_id=pipeline_id)
    summary = freshness_summary(rows)
    total = len(rows)
    page = max(1, int(page or 1))
    page_size = max(1, min(int(page_size or 20), 100))
    start = (page - 1) * page_size
    page_items = rows[start : start + page_size]

    kpis = [
        make_kpi(
            id="fresh",
            title="Fresh",
            value=summary["fresh"],
            display=f"{summary['fresh']} ({summary['fresh_pct'] or 0}%)",
            tone="ok",
        ),
        make_kpi(
            id="delayed",
            title="Delayed",
            value=summary["delayed"],
            display=f"{summary['delayed']} ({pct(summary['delayed'], summary['monitored']) or 0}%)",
            tone="warn" if summary["delayed"] else "ok",
        ),
        make_kpi(
            id="stale",
            title="Stale",
            value=summary["stale"],
            display=f"{summary['stale']} ({pct(summary['stale'], summary['monitored']) or 0}%)",
            tone="bad" if summary["stale"] else "ok",
        ),
        make_kpi(
            id="avg_lag",
            title="Average Lag",
            value=summary["avg_lag_hours"],
            display=(
                f"{summary['avg_lag_hours']}h"
                if summary["avg_lag_hours"] is not None
                else "N/A"
            ),
            available=summary["avg_lag_hours"] is not None,
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
        items=page_items,
        page=page,
        page_size=page_size,
        total=total,
        summary=summary,
        meta={
            "formula": (
                "lag = now - last_success_at; last_success_at = TARGET.last_updated_at "
                "or last success end_time. Fresh<=SLA, Delayed<=2*SLA, else Stale."
            ),
            "sla_hours": freshness_sla_hours(),
        },
    )
