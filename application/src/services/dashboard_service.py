"""
Executive Overview dashboard payload from Metadata MySQL (obs_* / views).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from application.src.store.meta_mysql import ensure_grafana_views, get_connection

KPI_DEFS: list[dict[str, str]] = [
    {
        "id": "pipelines",
        "title": "Pipelines",
        "meaning": "How many ETL pipelines are registered in metadata.",
        "formula": "COUNT(*) FROM obs_pipelines",
        "tables": "obs_pipelines",
    },
    {
        "id": "success_rate",
        "title": "Success Rate",
        "meaning": "Share of pipeline runs that finished successfully in the selected range.",
        "formula": "100 * success_runs / total_runs from obs_pipeline_runs (status = success)",
        "tables": "obs_pipeline_runs, vw_kpi_totals",
    },
    {
        "id": "failed_pipelines",
        "title": "Failed Pipelines",
        "meaning": "Pipelines whose latest run failed (unhealthy).",
        "formula": "COUNT of vw_pipeline_health WHERE health_status = 'unhealthy'",
        "tables": "vw_pipeline_health, obs_pipeline_runs",
    },
    {
        "id": "incidents",
        "title": "Incidents",
        "meaning": "Failed runs treated as open incidents (no separate incidents table yet).",
        "formula": "COUNT(*) FROM vw_failed_runs in the selected range",
        "tables": "vw_failed_runs, obs_pipeline_runs",
    },
    {
        "id": "datasets",
        "title": "Datasets",
        "meaning": "Distinct target tables observed from the target database.",
        "formula": "COUNT DISTINCT (database_name, schema_name, object_name) WHERE asset_role = TARGET",
        "tables": "obs_run_assets",
    },
    {
        "id": "freshness",
        "title": "Data Freshness",
        "meaning": "Percent of latest target tables updated within 24 hours.",
        "formula": "100 * fresh_target_tables / latest_target_tables (last_updated_at or latest run end_time)",
        "tables": "obs_run_assets, obs_pipeline_runs",
    },
    {
        "id": "obs_freshness",
        "title": "Freshness",
        "meaning": "Same as Data Freshness: are target tables recent enough?",
        "formula": "100 * fresh_target_tables / latest_target_tables",
        "tables": "obs_run_assets, obs_pipeline_runs",
    },
    {
        "id": "obs_volume",
        "title": "Volume",
        "meaning": "Percent of latest target tables that have row_count > 0.",
        "formula": "100 * tables_with_rows / latest_target_tables",
        "tables": "obs_run_assets",
    },
    {
        "id": "obs_schema",
        "title": "Schema",
        "meaning": "Percent of pipelines that have a target schema on the latest TARGET run.",
        "formula": "100 * pipelines_with_target_schema / registered_pipelines",
        "tables": "obs_pipelines, obs_run_assets, obs_pipeline_runs",
    },
    {
        "id": "obs_quality",
        "title": "Data Quality",
        "meaning": "Column-level quality scores are not stored in obs_* yet.",
        "formula": "N/A — not in metadata",
        "tables": "—",
    },
    {
        "id": "obs_consistency",
        "title": "Consistency",
        "meaning": "Cross-system consistency checks are not stored in obs_* yet.",
        "formula": "N/A — not in metadata",
        "tables": "—",
    },
    {
        "id": "obs_uniqueness",
        "title": "Uniqueness",
        "meaning": "Uniqueness / duplicate checks are not stored in obs_* yet.",
        "formula": "N/A — not in metadata",
        "tables": "—",
    },
]

RANGE_HOURS = {"24h": 24, "7d": 168, "30d": 720, "all": None}


def _json_val(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return value.isoformat(sep=" ", timespec="seconds")
    if isinstance(value, timedelta):
        return int(value.total_seconds())
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return value


def _json_row(row: dict | None) -> dict:
    if not row:
        return {}
    return {k: _json_val(v) for k, v in row.items()}


def _json_rows(rows: list | None) -> list[dict]:
    return [_json_row(r) for r in (rows or [])]


def _num(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _pct(num: float, den: float) -> float | None:
    if not den:
        return None
    return round(100.0 * num / den, 1)


def _parse_range(range_key: str) -> tuple[str, int | None]:
    key = (range_key or "24h").strip().lower()
    if key not in RANGE_HOURS:
        key = "24h"
    return key, RANGE_HOURS[key]


def _since_sql(hours: int | None) -> str:
    if hours is None:
        return "1=1"
    return f"COALESCE(end_time, start_time) >= DATE_SUB(UTC_TIMESTAMP(), INTERVAL {int(hours)} HOUR)"


def _fetchall(cur, sql: str, args: tuple | None = None) -> list[dict]:
    cur.execute(sql, args or ())
    rows = cur.fetchall() or []
    return list(rows)


def _fetchone(cur, sql: str, args: tuple | None = None) -> dict:
    cur.execute(sql, args or ())
    row = cur.fetchone()
    return row or {}


def _age_label(ts: Any) -> str | None:
    if not ts:
        return None
    if isinstance(ts, str):
        try:
            ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except ValueError:
            return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
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


def _format_duration(seconds: Any) -> str | None:
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


LATEST_TARGET_SQL = """
SELECT
  r.pipeline_name,
  r.pipeline_id,
  r.id AS run_id,
  r.end_time AS run_end_time,
  r.start_time AS run_start_time,
  a.database_name,
  a.schema_name,
  a.object_name,
  a.row_count,
  a.last_updated_at,
  a.asset_role
FROM obs_run_assets a
JOIN obs_pipeline_runs r ON CAST(r.id AS CHAR) = a.run_id
JOIN (
  SELECT r2.pipeline_name, MAX(r2.start_time) AS max_start
  FROM obs_pipeline_runs r2
  JOIN obs_run_assets a2 ON CAST(r2.id AS CHAR) = a2.run_id
  WHERE UPPER(a2.asset_role) = 'TARGET'
  GROUP BY r2.pipeline_name
) latest
  ON latest.pipeline_name = r.pipeline_name
 AND latest.max_start = r.start_time
WHERE UPPER(a.asset_role) = 'TARGET'
"""


def build_overview(range_key: str = "24h") -> dict[str, Any]:
    key, hours = _parse_range(range_key)
    since = _since_sql(hours)
    conn = get_connection()
    try:
        ensure_grafana_views(conn)
        with conn.cursor() as cur:
            pipelines = _fetchall(
                cur,
                """
                SELECT pipeline_id, pipeline_name, is_active,
                       source_tool, source_schema, etl_tool,
                       target_tool, target_schema, description
                FROM obs_pipelines
                ORDER BY pipeline_name
                """,
            )
            pipeline_count = len(pipelines)

            kpi_range = _fetchone(
                cur,
                f"""
                SELECT
                  COUNT(*) AS total_runs,
                  SUM(CASE WHEN LOWER(COALESCE(status,'')) = 'success' THEN 1 ELSE 0 END) AS success_runs,
                  SUM(CASE WHEN LOWER(COALESCE(status,'')) = 'failed' THEN 1 ELSE 0 END) AS failed_runs
                FROM obs_pipeline_runs
                WHERE {since}
                """,
            )
            totals = _fetchone(cur, "SELECT * FROM vw_kpi_totals")
            health = _fetchall(cur, "SELECT * FROM vw_pipeline_health ORDER BY pipeline_name")
            failed_runs = _fetchall(
                cur,
                f"""
                SELECT run_id, pipeline_id, pipeline_name, status, start_time, end_time,
                       duration, failure_stage, failed_node, error_class, error_message
                FROM vw_failed_runs
                WHERE {_since_sql(hours)}
                ORDER BY COALESCE(end_time, start_time) DESC
                LIMIT 20
                """,
            )
            daily = _fetchall(
                cur,
                """
                SELECT metric_date, total_runs, success_runs, failed_runs
                FROM vw_daily_metrics
                ORDER BY metric_date
                """,
            )
            duration_series = _fetchall(
                cur,
                f"""
                SELECT DATE(COALESCE(end_time, start_time)) AS metric_date,
                       ROUND(AVG(duration), 1) AS avg_duration_seconds
                FROM obs_pipeline_runs
                WHERE {_since_sql(hours)}
                  AND duration IS NOT NULL
                GROUP BY DATE(COALESCE(end_time, start_time))
                ORDER BY metric_date
                """,
            )
            throughput_series = _fetchall(
                cur,
                f"""
                SELECT DATE(COALESCE(end_time, start_time)) AS metric_date,
                       ROUND(
                         SUM(COALESCE(rows_read, 0)) / NULLIF(SUM(COALESCE(duration, 0)), 0),
                         2
                       ) AS rows_per_sec
                FROM obs_pipeline_runs
                WHERE {_since_sql(hours)}
                GROUP BY DATE(COALESCE(end_time, start_time))
                ORDER BY metric_date
                """,
            )
            status_kinds = _fetchall(
                cur,
                f"""
                SELECT LOWER(COALESCE(status, 'unknown')) AS status, COUNT(*) AS n
                FROM obs_pipeline_runs
                WHERE {_since_sql(hours)}
                GROUP BY LOWER(COALESCE(status, 'unknown'))
                """,
            )
            recent_runs = _fetchall(
                cur,
                f"""
                SELECT
                  r.run_id, r.pipeline_id, r.pipeline_name, r.status,
                  r.start_time, r.end_time, r.duration,
                  r.rows_read, r.rows_written, r.rows_added,
                  r.failure_stage, r.failed_node, r.error_class,
                  p.source_tool, p.source_schema, p.target_tool, p.target_schema
                FROM vw_recent_runs r
                LEFT JOIN obs_pipelines p ON p.pipeline_id = r.pipeline_id
                WHERE {"1=1" if hours is None else "COALESCE(r.end_time, r.start_time) >= DATE_SUB(UTC_TIMESTAMP(), INTERVAL %d HOUR)" % int(hours)}
                ORDER BY COALESCE(r.end_time, r.start_time) DESC
                LIMIT 25
                """,
            )
            latest_targets = _fetchall(cur, LATEST_TARGET_SQL)
            yesterday = _fetchone(
                cur,
                """
                SELECT
                  COUNT(*) AS total_runs,
                  SUM(CASE WHEN LOWER(COALESCE(status,'')) = 'success' THEN 1 ELSE 0 END) AS success_runs,
                  SUM(CASE WHEN LOWER(COALESCE(status,'')) = 'failed' THEN 1 ELSE 0 END) AS failed_runs
                FROM obs_pipeline_runs
                WHERE DATE(COALESCE(end_time, start_time)) = DATE(DATE_SUB(UTC_TIMESTAMP(), INTERVAL 1 DAY))
                """,
            )
            today = _fetchone(
                cur,
                """
                SELECT
                  COUNT(*) AS total_runs,
                  SUM(CASE WHEN LOWER(COALESCE(status,'')) = 'success' THEN 1 ELSE 0 END) AS success_runs,
                  SUM(CASE WHEN LOWER(COALESCE(status,'')) = 'failed' THEN 1 ELSE 0 END) AS failed_runs
                FROM obs_pipeline_runs
                WHERE DATE(COALESCE(end_time, start_time)) = DATE(UTC_TIMESTAMP())
                """,
            )

        total_runs = _num(kpi_range.get("total_runs") or totals.get("total_runs"))
        success_runs = _num(kpi_range.get("success_runs") or totals.get("success_runs"))
        failed_run_count = _num(kpi_range.get("failed_runs") or totals.get("failed_runs"))
        success_rate = _pct(success_runs, total_runs)

        unhealthy = [h for h in health if str(h.get("health_status") or "").lower() == "unhealthy"]
        failed_pipeline_count = len(unhealthy)

        target_keys = {
            (
                str(t.get("database_name") or ""),
                str(t.get("schema_name") or ""),
                str(t.get("object_name") or ""),
            )
            for t in latest_targets
            if t.get("object_name")
        }
        dataset_count = len(target_keys) or len(
            {
                (str(t.get("schema_name") or ""), str(t.get("object_name") or ""))
                for t in latest_targets
                if t.get("object_name")
            }
        )

        now = datetime.now(timezone.utc)
        fresh_cutoff = now - timedelta(hours=24)
        fresh_n = 0
        volume_n = 0
        for t in latest_targets:
            ts = t.get("last_updated_at") or t.get("run_end_time") or t.get("run_start_time")
            if isinstance(ts, datetime):
                cmp = ts.replace(tzinfo=timezone.utc) if ts.tzinfo is None else ts
                if cmp >= fresh_cutoff:
                    fresh_n += 1
            if _num(t.get("row_count")) > 0:
                volume_n += 1
        target_n = len(latest_targets)
        freshness_pct = _pct(fresh_n, target_n)
        volume_pct = _pct(volume_n, target_n)

        pipelines_with_schema = {
            str(t.get("pipeline_name"))
            for t in latest_targets
            if t.get("schema_name")
        }
        schema_pct = _pct(len(pipelines_with_schema), pipeline_count) if pipeline_count else None

        y_total = _num(yesterday.get("total_runs"))
        y_success = _num(yesterday.get("success_runs"))
        y_failed = _num(yesterday.get("failed_runs"))
        t_total = _num(today.get("total_runs"))
        t_success = _num(today.get("success_runs"))
        t_failed = _num(today.get("failed_runs"))
        y_rate = _pct(y_success, y_total)
        t_rate = _pct(t_success, t_total)

        def delta(current: float | None, previous: float | None) -> float | None:
            if current is None or previous is None:
                return None
            if y_total <= 0 and t_total <= 0:
                return None
            return round(current - previous, 1)

        spark_success = [_num(d.get("success_runs")) for d in daily][-14:]
        spark_failed = [_num(d.get("failed_runs")) for d in daily][-14:]

        kpis = [
            {
                "id": "pipelines",
                "title": "Pipelines",
                "value": pipeline_count,
                "display": str(pipeline_count),
                "delta": None,
                "delta_label": None,
                "sparkline": spark_success,
                "tone": "neutral",
            },
            {
                "id": "success_rate",
                "title": "Success Rate",
                "value": success_rate,
                "display": f"{success_rate}%" if success_rate is not None else "—",
                "delta": delta(t_rate, y_rate),
                "delta_label": "vs yesterday" if y_total else None,
                "sparkline": spark_success,
                "tone": "ok" if (success_rate or 0) >= 80 else "warn",
            },
            {
                "id": "failed_pipelines",
                "title": "Failed Pipelines",
                "value": failed_pipeline_count,
                "display": str(failed_pipeline_count),
                "delta": None,
                "delta_label": None,
                "sparkline": spark_failed,
                "tone": "bad" if failed_pipeline_count else "ok",
            },
            {
                "id": "incidents",
                "title": "Incidents",
                "value": len(failed_runs),
                "display": str(len(failed_runs)),
                "delta": delta(t_failed, y_failed) if y_total else None,
                "delta_label": "vs yesterday" if y_total else None,
                "sparkline": spark_failed,
                "tone": "warn" if failed_runs else "ok",
            },
            {
                "id": "datasets",
                "title": "Datasets",
                "value": dataset_count,
                "display": str(dataset_count),
                "delta": None,
                "delta_label": None,
                "sparkline": [],
                "tone": "neutral",
            },
            {
                "id": "freshness",
                "title": "Data Freshness",
                "value": freshness_pct,
                "display": f"{freshness_pct}%" if freshness_pct is not None else "—",
                "delta": None,
                "delta_label": None,
                "sparkline": [],
                "tone": "ok" if (freshness_pct or 0) >= 80 else "warn",
            },
        ]

        observability = [
            {
                "id": "obs_freshness",
                "title": "Freshness",
                "value": freshness_pct,
                "display": f"{freshness_pct}%" if freshness_pct is not None else "—",
                "available": freshness_pct is not None,
            },
            {
                "id": "obs_volume",
                "title": "Volume",
                "value": volume_pct,
                "display": f"{volume_pct}%" if volume_pct is not None else "—",
                "available": volume_pct is not None,
            },
            {
                "id": "obs_schema",
                "title": "Schema",
                "value": schema_pct,
                "display": f"{schema_pct}%" if schema_pct is not None else "—",
                "available": schema_pct is not None,
            },
            {
                "id": "obs_quality",
                "title": "Data Quality",
                "value": None,
                "display": "N/A",
                "available": False,
            },
            {
                "id": "obs_consistency",
                "title": "Consistency",
                "value": None,
                "display": "N/A",
                "available": False,
            },
            {
                "id": "obs_uniqueness",
                "title": "Uniqueness",
                "value": None,
                "display": "N/A",
                "available": False,
            },
        ]

        status_set = {str(s.get("status") or "") for s in status_kinds}
        runs_over_time = []
        for d in daily:
            point = {
                "date": _json_val(d.get("metric_date")),
                "success": _num(d.get("success_runs")),
                "failed": _num(d.get("failed_runs")),
                "total": _num(d.get("total_runs")),
            }
            if "running" in status_set:
                point["running"] = 0
            if "cancelled" in status_set:
                point["cancelled"] = 0
            runs_over_time.append(point)

        volume_by_pipeline: dict[str, float] = {}
        for t in latest_targets:
            name = str(t.get("pipeline_name") or "unknown")
            volume_by_pipeline[name] = volume_by_pipeline.get(name, 0) + _num(t.get("row_count"))
        top_volume = sorted(
            [{"pipeline_name": k, "target_row_count": round(v, 0)} for k, v in volume_by_pipeline.items()],
            key=lambda x: x["target_row_count"],
            reverse=True,
        )

        failure_rate = []
        for h in health:
            total = _num(h.get("total_runs"))
            failed = _num(h.get("failed_count"))
            failure_rate.append(
                {
                    "pipeline_name": h.get("pipeline_name"),
                    "failure_rate_pct": _pct(failed, total) or 0,
                    "failed_count": int(failed),
                    "total_runs": int(total),
                    "health_status": h.get("health_status"),
                }
            )
        failure_rate.sort(key=lambda x: x["failure_rate_pct"], reverse=True)

        unhealthy_names = {str(h.get("pipeline_name")) for h in unhealthy}
        impact = []
        for t in latest_targets:
            if str(t.get("pipeline_name")) in unhealthy_names:
                impact.append(
                    {
                        "pipeline_name": t.get("pipeline_name"),
                        "object_name": t.get("object_name"),
                        "schema_name": t.get("schema_name"),
                        "database_name": t.get("database_name"),
                        "impact": "High",
                    }
                )

        lineage = []
        for p in pipelines:
            lineage.append(
                {
                    "pipeline_name": p.get("pipeline_name"),
                    "source": f"{p.get('source_tool') or 'source'}/{p.get('source_schema') or '—'}",
                    "etl": p.get("etl_tool") or "etl",
                    "target": f"{p.get('target_tool') or 'target'}/{p.get('target_schema') or '—'}",
                    "source_tool": p.get("source_tool"),
                    "source_schema": p.get("source_schema"),
                    "etl_tool": p.get("etl_tool"),
                    "target_tool": p.get("target_tool"),
                    "target_schema": p.get("target_schema"),
                }
            )

        incidents = []
        for fr in failed_runs[:8]:
            end = fr.get("end_time") or fr.get("start_time")
            msg = str(fr.get("error_message") or fr.get("error_class") or "Failed run")
            incidents.append(
                {
                    "pipeline_name": fr.get("pipeline_name"),
                    "title": f"{fr.get('pipeline_name')} failed",
                    "detail": msg[:180],
                    "severity": "P1" if str(fr.get("error_class") or "").lower() in {"compilation", "runtime"} else "P2",
                    "age": _age_label(end),
                    "status": "open",
                    "run_id": fr.get("run_id"),
                }
            )

        freshness_datasets = []
        for t in latest_targets:
            ts = t.get("last_updated_at") or t.get("run_end_time")
            freshness_datasets.append(
                {
                    "pipeline_name": t.get("pipeline_name"),
                    "object_name": t.get("object_name"),
                    "schema_name": t.get("schema_name"),
                    "last_updated_at": _json_val(ts),
                    "age": _age_label(ts),
                    "row_count": _json_val(t.get("row_count")),
                }
            )

        system_health = []
        for h in health:
            status = str(h.get("health_status") or "unknown")
            system_health.append(
                {
                    "name": h.get("pipeline_name"),
                    "status": status,
                    "label": status.replace("_", " ").title(),
                    "success_rate_pct": _json_val(h.get("success_rate_pct")),
                    "latest_status": h.get("latest_status"),
                }
            )

        runs = []
        for r in recent_runs:
            src = f"{r.get('source_tool') or '—'} → {r.get('target_tool') or '—'}"
            if r.get("source_schema") or r.get("target_schema"):
                src = f"{r.get('source_schema') or r.get('source_tool') or '—'} → {r.get('target_schema') or r.get('target_tool') or '—'}"
            runs.append(
                {
                    "run_id": r.get("run_id"),
                    "pipeline_name": r.get("pipeline_name"),
                    "source_target": src,
                    "status": r.get("status"),
                    "duration": _format_duration(r.get("duration")),
                    "duration_seconds": _json_val(r.get("duration")),
                    "rows_read": _json_val(r.get("rows_read")),
                    "rows_written": _json_val(r.get("rows_written")),
                    "start_time": _json_val(r.get("start_time")),
                    "end_time": _json_val(r.get("end_time")),
                    "last_run": _age_label(r.get("end_time") or r.get("start_time")),
                    "error_class": r.get("error_class"),
                }
            )

        return {
            "ok": True,
            "range": key,
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "kpi_defs": KPI_DEFS,
            "kpis": kpis,
            "observability": observability,
            "series": {
                "runs_over_time": runs_over_time,
                "duration": [
                    {
                        "date": _json_val(d.get("metric_date")),
                        "avg_duration_seconds": _num(d.get("avg_duration_seconds")),
                        "avg_duration_minutes": round(_num(d.get("avg_duration_seconds")) / 60.0, 2),
                    }
                    for d in duration_series
                ],
                "throughput": [
                    {
                        "date": _json_val(d.get("metric_date")),
                        "rows_per_sec": _num(d.get("rows_per_sec")),
                    }
                    for d in throughput_series
                ],
            },
            "charts": {
                "top_volume": top_volume,
                "failure_rate": failure_rate,
            },
            "incidents": incidents,
            "lineage": lineage,
            "impact": impact,
            "system_health": system_health,
            "freshness_datasets": freshness_datasets,
            "runs": runs,
            "health": _json_rows(health),
            "totals": {
                "total_runs": int(total_runs),
                "success_runs": int(success_runs),
                "failed_runs": int(failed_run_count),
                "success_rate_pct": success_rate,
            },
        }
    finally:
        conn.close()
