"""
Shared range/filter helpers and JSON-safe DB utilities for observability APIs.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Optional

from application.src.store.meta_mysql import get_connection, persist_operational_flags

PRESETS: dict[str, Optional[int]] = {
    "15m": 0,  # minutes handled specially
    "24h": 24,
    "7d": 168,
    "30d": 720,
    "all": None,
}


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def json_val(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return value.isoformat(sep=" ", timespec="seconds")
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    if isinstance(value, timedelta):
        return int(value.total_seconds())
    return value


def json_row(row: dict | None) -> dict:
    if not row:
        return {}
    return {k: json_val(v) for k, v in row.items()}


def json_rows(rows: list | None) -> list[dict]:
    return [json_row(r) for r in (rows or [])]


def num(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def pct(numerator: float, denominator: float) -> float | None:
    if not denominator:
        return None
    return round(100.0 * numerator / denominator, 1)


def activity_lookback_hours() -> float:
    """How recent a run must be for the pipeline to count as operating (Active)."""
    try:
        return float(os.getenv("ACTIVITY_LOOKBACK_HOURS") or "168")
    except ValueError:
        return 168.0


def freshness_sla_hours() -> float:
    try:
        return float(os.getenv("DEFAULT_FRESHNESS_SLA_HOURS") or "24")
    except ValueError:
        return 24.0


def volume_drop_warn_pct() -> float:
    try:
        return float(os.getenv("VOLUME_DROP_WARN_PCT") or "30")
    except ValueError:
        return 30.0


def volume_drop_crit_pct() -> float:
    try:
        return float(os.getenv("VOLUME_DROP_CRIT_PCT") or "60")
    except ValueError:
        return 60.0


def parse_range(
    preset: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
) -> dict[str, Any]:
    """
    Resolve query window to absolute from/to datetimes (naive UTC, MySQL style).
    Returns previous window of equal length for delta comparisons.
    """
    now = utc_now()
    preset_key = (preset or "").strip().lower() or None

    if start_date and str(start_date).strip():
        st = (start_time or "").strip() or "00:00:00"
        et = (end_time or "").strip() or "23:59:59"
        from_dt = datetime.fromisoformat(f"{start_date.strip()} {st}")
        if end_date and str(end_date).strip():
            to_dt = datetime.fromisoformat(f"{end_date.strip()} {et}")
        else:
            to_dt = now
        duration = max(to_dt - from_dt, timedelta(seconds=1))
        prev_to = from_dt
        prev_from = from_dt - duration
        return {
            "preset": preset_key or "custom",
            "from": from_dt,
            "to": to_dt,
            "prev_from": prev_from,
            "prev_to": prev_to,
            "from_str": from_dt.strftime("%Y-%m-%d %H:%M:%S"),
            "to_str": to_dt.strftime("%Y-%m-%d %H:%M:%S"),
            "prev_from_str": prev_from.strftime("%Y-%m-%d %H:%M:%S"),
            "prev_to_str": prev_to.strftime("%Y-%m-%d %H:%M:%S"),
        }

    if preset_key == "15m":
        from_dt = now - timedelta(minutes=15)
        prev_to = from_dt
        prev_from = from_dt - timedelta(minutes=15)
    elif preset_key == "all" or preset_key is None and not start_date:
        # Default dashboard window = 24h when nothing specified
        if preset_key == "all":
            from_dt = datetime(1970, 1, 1)
            prev_from = from_dt
            prev_to = from_dt
        else:
            preset_key = "24h"
            from_dt = now - timedelta(hours=24)
            prev_to = from_dt
            prev_from = from_dt - timedelta(hours=24)
    else:
        hours = PRESETS.get(preset_key, 24)
        if hours is None:
            from_dt = datetime(1970, 1, 1)
            prev_from = from_dt
            prev_to = from_dt
            preset_key = "all"
        else:
            from_dt = now - timedelta(hours=int(hours))
            prev_to = from_dt
            prev_from = from_dt - timedelta(hours=int(hours))

    to_dt = now
    return {
        "preset": preset_key or "24h",
        "from": from_dt,
        "to": to_dt,
        "prev_from": prev_from,
        "prev_to": prev_to,
        "from_str": from_dt.strftime("%Y-%m-%d %H:%M:%S"),
        "to_str": to_dt.strftime("%Y-%m-%d %H:%M:%S"),
        "prev_from_str": prev_from.strftime("%Y-%m-%d %H:%M:%S"),
        "prev_to_str": prev_to.strftime("%Y-%m-%d %H:%M:%S"),
    }


def range_meta(rng: dict[str, Any]) -> dict[str, Any]:
    return {
        "from": rng.get("from_str"),
        "to": rng.get("to_str"),
        "preset": rng.get("preset"),
    }


def split_csv(value: Optional[str]) -> list[str]:
    if not value or not str(value).strip():
        return []
    return [p.strip() for p in str(value).split(",") if p.strip()]


def build_run_where(
    *,
    alias: str = "r",
    pipeline_name: Optional[str] = None,
    pipeline_id: Optional[str] = None,
    status: Optional[str] = None,
    tool: Optional[str] = None,
    from_str: Optional[str] = None,
    to_str: Optional[str] = None,
    time_column: str = "COALESCE({a}.end_time, {a}.start_time, {a}.created_at)",
) -> tuple[str, list[Any]]:
    """Parameterized WHERE for obs_pipeline_runs. Returns (sql_fragment, params)."""
    a = alias
    tc = time_column.format(a=a)
    clauses: list[str] = []
    params: list[Any] = []

    names = split_csv(pipeline_name)
    if names:
        ph = ",".join(["%s"] * len(names))
        clauses.append(f"{a}.pipeline_name IN ({ph})")
        params.extend(names)

    ids = split_csv(pipeline_id)
    if ids:
        ph = ",".join(["%s"] * len(ids))
        clauses.append(f"{a}.pipeline_id IN ({ph})")
        params.extend(ids)

    statuses = [s.lower() for s in split_csv(status)]
    if statuses:
        ph = ",".join(["%s"] * len(statuses))
        clauses.append(f"LOWER(COALESCE({a}.status, '')) IN ({ph})")
        params.extend(statuses)

    tools = [t.lower() for t in split_csv(tool)]
    if tools:
        ph = ",".join(["%s"] * len(tools))
        clauses.append(f"LOWER(COALESCE({a}.tool_name, '')) IN ({ph})")
        params.extend(tools)

    if from_str:
        clauses.append(f"{tc} >= %s")
        params.append(from_str)
    if to_str:
        clauses.append(f"{tc} <= %s")
        params.append(to_str)

    if not clauses:
        return "", []
    return "WHERE " + " AND ".join(clauses), params


def fetchall(conn, sql: str, params: tuple | list | None = None) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(sql, tuple(params or ()))
        return list(cur.fetchall() or [])


def fetchone(conn, sql: str, params: tuple | list | None = None) -> dict:
    rows = fetchall(conn, sql, params)
    return rows[0] if rows else {}


def with_connection(fn):
    """Decorator-style helper: open connection, run, close."""

    def wrapper(*args, **kwargs):
        conn = get_connection()
        try:
            return fn(conn, *args, **kwargs)
        finally:
            try:
                conn.close()
            except Exception:
                pass

    return wrapper


def format_duration(seconds: Any) -> str | None:
    if seconds is None or seconds == "":
        return None
    try:
        s = int(round(float(seconds)))
    except (TypeError, ValueError):
        return None
    if s < 0:
        return None
    if s < 60:
        return f"{s}s"
    m, rem = divmod(s, 60)
    if m < 60:
        return f"{m}m {rem}s" if rem else f"{m}m"
    h, rem_m = divmod(m, 60)
    return f"{h}h {rem_m}m"


def age_label(ts: Any, now: datetime | None = None) -> str | None:
    if not ts:
        return None
    if isinstance(ts, str):
        try:
            ts = datetime.fromisoformat(ts.replace("Z", "+00:00").replace(" ", "T"))
        except ValueError:
            return None
    if getattr(ts, "tzinfo", None) is not None:
        ts = ts.replace(tzinfo=None)
    now = now or utc_now()
    seconds = int((now - ts).total_seconds())
    if seconds < 0:
        seconds = 0
    if seconds < 60:
        return f"{seconds}s ago"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m ago"
    hours = minutes // 60
    if hours < 48:
        return f"{hours}h ago"
    days = hours // 24
    return f"{days}d ago"


KNOWN_RUN_STATUSES = ["success", "failed", "running", "error", "cancelled"]
KNOWN_PRESETS = [
    {"id": "15m", "label": "Last 15 minutes"},
    {"id": "24h", "label": "Last 24 hours"},
    {"id": "7d", "label": "Last 7 days"},
    {"id": "30d", "label": "Last 30 days"},
    {"id": "all", "label": "All time"},
]


def _as_naive_dt(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None) if value.tzinfo else value
    text = str(value).replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed.replace(tzinfo=None) if parsed.tzinfo else parsed


def is_pipeline_operational(
    last_run_at: Any,
    last_run_status: Any = None,
    sla_hours: float | None = None,
) -> bool:
    """
    Real-world Active vs Inactive:
    - Active: currently running, or last run (success or fail) within SLA window
    - Inactive: never ran, or last activity older than SLA
    A recent failed run is still Active (unhealthy, but the pipeline is operating).
    """
    status = str(last_run_status or "").strip().lower()
    if status == "running":
        return True
    ts = _as_naive_dt(last_run_at)
    if ts is None:
        return False
    hours = sla_hours if sla_hours is not None else activity_lookback_hours()
    lag_hours = (utc_now() - ts).total_seconds() / 3600.0
    return lag_hours <= max(hours, 0)


def load_pipeline_activity(conn, *, persist: bool = True) -> list[dict[str, Any]]:
    sla = activity_lookback_hours()
    rows = fetchall(
        conn,
        """
        SELECT
          p.pipeline_id,
          p.pipeline_name,
          p.etl_tool,
          p.is_active AS is_sync_default,
          lr.last_run_at,
          lr.last_run_status
        FROM obs_pipelines p
        LEFT JOIN (
          SELECT r.pipeline_id, r.status AS last_run_status,
                 COALESCE(r.end_time, r.start_time, r.created_at) AS last_run_at
          FROM obs_pipeline_runs r
          INNER JOIN (
            SELECT pipeline_id, MAX(COALESCE(end_time, start_time, created_at)) AS max_ts
            FROM obs_pipeline_runs
            GROUP BY pipeline_id
          ) m
            ON m.pipeline_id = r.pipeline_id
           AND COALESCE(r.end_time, r.start_time, r.created_at) = m.max_ts
        ) lr ON lr.pipeline_id = p.pipeline_id
        ORDER BY p.pipeline_name ASC, p.pipeline_id ASC
        """,
    )
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for r in rows:
        pid = str(r.get("pipeline_id") or "")
        if not pid or pid in seen:
            continue
        seen.add(pid)
        operational = is_pipeline_operational(r.get("last_run_at"), r.get("last_run_status"), sla)
        out.append(
            {
                "pipeline_id": pid,
                "pipeline_name": str(r.get("pipeline_name") or pid),
                "is_active": operational,
                "activity": "Active" if operational else "Inactive",
                "is_sync_default": bool(r.get("is_sync_default")),
                "tool": r.get("etl_tool") or None,
                "last_run_at": json_val(r.get("last_run_at")),
                "last_run_status": (str(r.get("last_run_status")).lower() if r.get("last_run_status") else None),
                "sla_hours": sla,
            }
        )
    if persist and out:
        persist_operational_flags(conn, out)
    return out


def list_filter_pipelines(conn, q: Optional[str] = None) -> list[dict[str, Any]]:
    """Pipeline dropdown: id, name, and real-world Active/Inactive from last run."""
    items = load_pipeline_activity(conn, persist=True)
    if q and q.strip():
        needle = q.strip().lower()
        items = [
            i
            for i in items
            if needle in i["pipeline_id"].lower() or needle in i["pipeline_name"].lower()
        ]
    return items


def _distinct_strings(conn, sql: str, params: list | tuple | None = None) -> list[str]:
    seen: list[str] = []
    for row in fetchall(conn, sql, params):
        val = row.get("v")
        if val is None:
            continue
        s = str(val).strip()
        if s and s.lower() not in {x.lower() for x in seen}:
            seen.append(s)
    return seen


def build_filter_catalog(conn, q: Optional[str] = None) -> dict[str, Any]:
    """All filter options the UI needs to populate dropdowns before clicking."""
    rng = parse_range("all", None, None, None, None)
    pipelines = list_filter_pipelines(conn, q=q)
    db_statuses = _distinct_strings(
        conn,
        """
        SELECT DISTINCT LOWER(TRIM(status)) AS v
        FROM obs_pipeline_runs
        WHERE status IS NOT NULL AND TRIM(status) <> ''
        ORDER BY v
        """,
    )
    statuses = []
    for s in KNOWN_RUN_STATUSES + db_statuses:
        if s.lower() not in {x.lower() for x in statuses}:
            statuses.append(s.lower())
    tools = _distinct_strings(
        conn,
        """
        SELECT v FROM (
          SELECT DISTINCT etl_tool AS v FROM obs_pipelines WHERE etl_tool IS NOT NULL AND TRIM(etl_tool) <> ''
          UNION
          SELECT DISTINCT source_tool AS v FROM obs_pipelines WHERE source_tool IS NOT NULL AND TRIM(source_tool) <> ''
          UNION
          SELECT DISTINCT target_tool AS v FROM obs_pipelines WHERE target_tool IS NOT NULL AND TRIM(target_tool) <> ''
          UNION
          SELECT DISTINCT tool_name AS v FROM obs_pipeline_runs WHERE tool_name IS NOT NULL AND TRIM(tool_name) <> ''
        ) t
        ORDER BY v
        """,
    )
    return envelope(
        rng=rng,
        filters_applied={"q": q},
        items=pipelines,
        pipelines=pipelines,
        total=len(pipelines),
        page=1,
        page_size=len(pipelines) or 1,
        presets=KNOWN_PRESETS,
        statuses=[{"id": s, "label": s.capitalize()} for s in statuses],
        tools=[{"id": t, "label": t} for t in tools],
        freshness_statuses=[
            {"id": "fresh", "label": "Fresh"},
            {"id": "delayed", "label": "Delayed"},
            {"id": "stale", "label": "Stale"},
        ],
        incident_statuses=[
            {"id": "open", "label": "Open"},
            {"id": "resolved", "label": "Resolved"},
        ],
        activity_statuses=[
            {"id": "active", "label": "Active"},
            {"id": "inactive", "label": "Inactive"},
        ],
        query_params={
            "pipeline_id": "Comma-separated pipeline_id values from items[].pipeline_id",
            "pipeline_name": "Comma-separated pipeline_name values from items[].pipeline_name",
            "status": "Comma-separated run statuses from statuses[].id",
            "tool": "Comma-separated tool ids from tools[].id",
            "preset": "One of presets[].id",
        },
    )


def delta_pct(current: float | None, previous: float | None) -> float | None:
    if current is None or previous is None:
        return None
    if previous == 0:
        return None if current == 0 else 100.0
    return round(100.0 * (current - previous) / abs(previous), 1)


def envelope(
    *,
    rng: dict[str, Any],
    filters_applied: dict[str, Any] | None = None,
    kpis: list | None = None,
    series: dict | None = None,
    charts: dict | None = None,
    items: list | None = None,
    page: int = 1,
    page_size: int = 20,
    total: int | None = None,
    **extra: Any,
) -> dict[str, Any]:
    items = items if items is not None else []
    out = {
        "ok": True,
        "generated_at": utc_now().isoformat(timespec="seconds") + "Z",
        "range": range_meta(rng),
        "filters_applied": filters_applied or {},
        "kpis": kpis or [],
        "series": series or {},
        "charts": charts or {},
        "items": items,
        "pagination": {
            "page": page,
            "page_size": page_size,
            "total": total if total is not None else len(items),
        },
        "pillars": [],
        "incidents": [],
        "pipelines": [],
        "health": [],
        "summary": {},
        "meta": {},
    }
    out.update(extra)
    return out
