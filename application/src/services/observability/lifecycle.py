"""
Monitor → check → alert → incident lifecycle (Phase 5).

Evaluates default monitors from obs_* snapshots and SQL validation monitors.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any

from application.src.services.observability.filters import (
    fetchall,
    fetchone,
    num,
    utc_now,
    volume_drop_crit_pct,
    volume_drop_warn_pct,
)
from application.src.services.observability.freshness import freshness_sla_hours, load_pipeline_freshness
from application.src.services.observability.incidents import list_derived_incidents
from application.src.services.observability.quality import infer_dimension

_SQL_KINDS = {"null_check", "null_pct", "unique_check", "unique_violation", "duplicate_check", "duplicate_count", "custom_sql"}


def _write_check_result(
    cur,
    *,
    monitor_id: str,
    pipeline_id: str,
    status: str,
    severity: str,
    message: str,
    observed: dict[str, Any],
    now: datetime,
) -> None:
    """Keep one latest result per monitor (avoids poller duplicate rows in quality aggregates)."""
    cur.execute(
        "DELETE FROM obs_check_results WHERE monitor_id = %s AND pipeline_id = %s",
        (monitor_id, pipeline_id),
    )
    cid = str(uuid.uuid4())
    cur.execute(
        """
        INSERT INTO obs_check_results (
          check_id, monitor_id, pipeline_id, status, severity, message, observed_json, checked_at
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
        """,
        (cid, monitor_id, pipeline_id, status, severity, message, json.dumps(observed), now),
    )


def _latest_successful_target_rows(conn, pipeline_id: str) -> list[dict]:
    """Two most recent successful runs with summed TARGET row counts (NULL = unknown)."""
    return fetchall(
        conn,
        """
        SELECT r.id AS run_id,
               SUM(a.row_count) AS target_rows,
               SUM(CASE WHEN a.row_count IS NOT NULL THEN 1 ELSE 0 END) AS rows_known,
               COALESCE(r.end_time, r.start_time, r.created_at) AS run_at
        FROM obs_pipeline_runs r
        LEFT JOIN obs_run_assets a
          ON a.run_id = CAST(r.id AS CHAR) AND UPPER(COALESCE(a.asset_role, '')) = 'TARGET'
        WHERE r.pipeline_id = %s
          AND LOWER(COALESCE(r.status, '')) IN ('success', 'succeeded')
        GROUP BY r.id, r.end_time, r.start_time, r.created_at
        ORDER BY run_at DESC
        LIMIT 2
        """,
        (pipeline_id,),
    )


def _dbt_test_failures(conn, pipeline_id: str) -> list[dict]:
    latest = fetchone(
        conn,
        """
        SELECT id FROM obs_pipeline_runs
        WHERE pipeline_id = %s
        ORDER BY COALESCE(end_time, start_time, created_at) DESC
        LIMIT 1
        """,
        (pipeline_id,),
    )
    rid = str((latest or {}).get("id") or "")
    if not rid:
        return []
    return fetchall(
        conn,
        """
        SELECT check_id, status, message, observed_json
        FROM obs_check_results
        WHERE pipeline_id = %s
          AND monitor_id = %s
          AND LOWER(COALESCE(status, '')) NOT IN ('pass', 'passed', 'success', 'ok', 'warn', 'warning')
        """,
        (pipeline_id, f"dbt-run:{rid}"),
    )


def _build_db_connector(tool: dict, secret: str):
    """Instantiate a warehouse connector that supports run_column_validation."""
    from application.src.connectors.registry import get_connector
    from application.src.sync_once import connector_kwargs_from_tool

    ctype = str(tool.get("connector_type") or "").lower()
    if ctype not in {"snowflake", "snowflake_lab", "postgres", "postgresql", "bigquery", "bq"}:
        return None
    kwargs = connector_kwargs_from_tool(tool, tenant_id=str(tool.get("tenant_id") or "default"))
    if secret:
        kwargs["password"] = secret
    return get_connector(ctype, **kwargs), ctype


def _target_db_connector(conn, pipeline_id: str, *, dataset_id: str | None = None):
    """Best-effort TARGET database connector (Snowflake, Postgres, BigQuery)."""
    from application.src.store.meta_mysql import get_decrypted_tool_secret, get_tool, list_pipeline_bindings

    bindings = [
        b for b in list_pipeline_bindings(conn, pipeline_id)
        if str(b.get("role") or "").upper() == "TARGET"
    ]
    if not bindings:
        pipe = fetchone(conn, "SELECT target_instance_id FROM obs_pipelines WHERE pipeline_id=%s", (pipeline_id,))
        iid = (pipe or {}).get("target_instance_id")
        if iid:
            bindings = [{"instance_id": iid}]
    ds_norm = (dataset_id or "").strip().upper()
    ordered = bindings
    if ds_norm and len(bindings) > 1:
        matched = []
        rest = []
        for b in bindings:
            iid = str(b.get("instance_id") or "")
            tool = get_tool(iid) if iid else None
            cfg = (tool or {}).get("config") or {}
            if isinstance(cfg, str):
                try:
                    cfg = json.loads(cfg)
                except json.JSONDecodeError:
                    cfg = {}
            prefix = ".".join(
                str(x or "").upper()
                for x in (
                    cfg.get("database_id") or cfg.get("project_id") or cfg.get("database"),
                    cfg.get("schema") or cfg.get("dataset"),
                )
                if x
            )
            if prefix and ds_norm.startswith(prefix):
                matched.append(b)
            else:
                rest.append(b)
        ordered = matched + rest if matched else bindings
    for binding in ordered:
        iid = str(binding.get("instance_id") or "")
        if not iid:
            continue
        tool = get_tool(iid)
        if not tool or (tool.get("kind") or "database") != "database":
            continue
        secret = get_decrypted_tool_secret(iid)
        if not secret and str(tool.get("connector_type") or "").lower() not in {"bigquery", "bq"}:
            continue
        connector, _ctype = _build_db_connector(tool, secret or "")
        if connector is not None and hasattr(connector, "run_column_validation"):
            return connector
    return None


def _evaluate_sql_monitor(conn, monitor: dict, cfg: dict) -> tuple[str, str, str, dict[str, Any]]:
    kind = str(monitor.get("monitor_kind") or "")
    dataset_id = str(monitor.get("dataset_id") or cfg.get("dataset_id") or "")
    column_name = str(monitor.get("column_name") or cfg.get("column_name") or "")
    expected_max = int(cfg.get("expected_max") or 0)
    pid = str(monitor.get("pipeline_id") or "")

    if not dataset_id or (kind != "custom_sql" and not column_name):
        return "pass", "low", "sql monitor config incomplete", {"skipped": True}

    sf = _target_db_connector(conn, pid, dataset_id=dataset_id)
    if sf is None:
        return "pass", "low", "warehouse credentials unavailable — sql monitor skipped", {"skipped": True}

    try:
        observed = sf.run_column_validation(
            dataset_id=dataset_id,
            column_name=column_name,
            check_type=kind,
            custom_sql=cfg.get("sql"),
            expected_max=expected_max,
        )
    except Exception as exc:
        return "fail", "high", f"SQL validation error: {exc}", {"error": str(exc)}

    observed["monitor_kind"] = kind
    observed["dimension"] = monitor.get("dimension") or infer_dimension(monitor_kind=kind)
    failure = int(observed.get("failure_count") or 0)
    if failure > expected_max:
        return (
            "fail",
            "high",
            f"{observed.get('check_type')} failed: {failure} violations (max {expected_max})",
            observed,
        )
    return "pass", "low", "sql validation ok", observed


def ensure_default_monitors(conn) -> int:
    """Seed one freshness + volume + failure monitor per pipeline if missing."""
    pipes = fetchall(conn, "SELECT pipeline_id, pipeline_name FROM obs_pipelines")
    created = 0
    with conn.cursor() as cur:
        for p in pipes:
            pid = p["pipeline_id"]
            for kind, name, cfg, mon_type, dimension in (
                ("freshness", "Freshness SLA", {"sla_hours": freshness_sla_hours()}, "freshness", "timeliness"),
                ("volume_drop", "Volume drop", {"crit_pct": volume_drop_crit_pct()}, "volume", "completeness"),
                ("pipeline_failure", "Latest run failed", {}, "operational", None),
                ("dbt_test_failure", "dbt test failures", {}, "validation", "validity"),
            ):
                cur.execute(
                    """
                    SELECT monitor_id FROM obs_monitors
                    WHERE pipeline_id=%s AND monitor_kind=%s LIMIT 1
                    """,
                    (pid, kind),
                )
                if cur.fetchone():
                    continue
                mid = str(uuid.uuid4())
                cur.execute(
                    """
                    INSERT INTO obs_monitors (
                      monitor_id, pipeline_id, name, monitor_kind, config_json,
                      is_enabled, monitor_type, dimension
                    ) VALUES (%s,%s,%s,%s,%s,1,%s,%s)
                    """,
                    (mid, pid, name, kind, json.dumps(cfg), mon_type, dimension),
                )
                created += 1
    conn.commit()
    return created


def _default_unique_rule_target(conn, pipeline_id: str) -> tuple[str, str, str] | None:
    """Best-effort dataset + id-like column for seed UNIQUE rule."""
    from application.src.store.meta_mysql import get_tool, list_pipeline_bindings

    bindings = [
        b for b in list_pipeline_bindings(conn, pipeline_id)
        if str(b.get("role") or "").upper() == "TARGET"
    ]
    tool = None
    if bindings:
        tool = get_tool(str(bindings[0].get("instance_id") or ""))
    if tool is None:
        pipe = fetchone(
            conn,
            "SELECT target_instance_id FROM obs_pipelines WHERE pipeline_id=%s",
            (pipeline_id,),
        )
        iid = (pipe or {}).get("target_instance_id")
        if iid:
            tool = get_tool(str(iid))

    db = schema = table = ""
    if tool:
        cfg = tool.get("config") or {}
        if isinstance(cfg, str):
            try:
                cfg = json.loads(cfg)
            except json.JSONDecodeError:
                cfg = {}
        db = str(cfg.get("database_id") or cfg.get("database") or cfg.get("project_id") or "")
        schema = str(cfg.get("schema") or cfg.get("dataset") or "")
        tables = cfg.get("tables") or []
        if tables:
            table = str(tables[0])

    if not table:
        asset = fetchone(
            conn,
            """
            SELECT a.database_name, a.schema_name, a.object_name
            FROM obs_run_assets a
            JOIN obs_pipeline_runs r ON r.id = a.run_id
            WHERE r.pipeline_id = %s AND UPPER(COALESCE(a.asset_role, '')) = 'TARGET'
            ORDER BY a.created_at DESC
            LIMIT 1
            """,
            (pipeline_id,),
        )
        if asset:
            db = db or str(asset.get("database_name") or "")
            schema = schema or str(asset.get("schema_name") or "")
            table = str(asset.get("object_name") or "")

    if not db or not schema or not table:
        return None

    dataset_id = f"{db}.{schema}.{table}".upper()
    cols = fetchall(
        conn,
        """
        SELECT c.column_name, c.ordinal_position
        FROM obs_run_columns c
        JOIN obs_pipeline_runs r ON r.id = c.run_id
        WHERE r.pipeline_id = %s
          AND UPPER(COALESCE(c.asset_role, '')) = 'TARGET'
          AND UPPER(c.object_name) = UPPER(%s)
        ORDER BY c.ordinal_position, c.column_name
        """,
        (pipeline_id, table),
    )
    column_name = ""
    for c in cols:
        name = str(c.get("column_name") or "")
        upper = name.upper()
        if upper.endswith("_ID") or upper == "ID":
            column_name = name
            break
    if not column_name and cols:
        column_name = str(cols[0].get("column_name") or "")
    if not column_name:
        return None
    return dataset_id, column_name, table


def ensure_default_dq_rules(conn, *, pipeline_id: str | None = None) -> int:
    """Seed a UNIQUE rule per pipeline when TARGET metadata is available."""
    from application.src.store.meta_mysql import upsert_dq_rule

    sql = "SELECT pipeline_id FROM obs_pipelines"
    params: tuple[Any, ...] = ()
    if pipeline_id:
        sql += " WHERE pipeline_id = %s"
        params = (pipeline_id,)
    pipes = fetchall(conn, sql, params)
    created = 0
    for p in pipes:
        pid = str(p.get("pipeline_id") or "")
        existing = fetchone(
            conn,
            """
            SELECT rule_id FROM obs_dq_rules
            WHERE pipeline_id = %s AND rule_type = 'UNIQUE' LIMIT 1
            """,
            (pid,),
        )
        if existing:
            continue
        target = _default_unique_rule_target(conn, pid)
        if not target:
            continue
        dataset_id, column_name, table_name = target
        upsert_dq_rule(
            conn,
            {
                "rule_id": f"seed:unique:{pid}"[:64],
                "pipeline_id": pid,
                "rule_name": f"Unique {column_name} on {table_name}",
                "rule_type": "UNIQUE",
                "dataset_id": dataset_id,
                "column_name": column_name,
                "dimension": "uniqueness",
                "severity": "high",
                "evaluation_trigger": "poller",
            },
        )
        created += 1
    return created


def evaluate_monitors(conn) -> dict[str, Any]:
    """Run enabled monitors; write check_results, upsert alerts, sync incidents from failures."""
    ensure_default_monitors(conn)
    ensure_default_dq_rules(conn)
    monitors = fetchall(conn, "SELECT * FROM obs_monitors WHERE is_enabled=1")
    fresh = {r["pipeline_id"]: r for r in load_pipeline_freshness(conn)}
    open_fail = {
        i["pipeline_id"]
        for i in list_derived_incidents(conn, include_resolved=False)
        if i.get("status") == "open"
    }
    checks = 0
    alerts_open = 0
    now = utc_now()

    with conn.cursor() as cur:
        for m in monitors:
            pid = m["pipeline_id"]
            kind = m["monitor_kind"]
            cfg = {}
            try:
                cfg = json.loads(m["config_json"] or "{}")
            except json.JSONDecodeError:
                pass
            status = "pass"
            severity = "low"
            message = "ok"
            observed: dict[str, Any] = {}

            if kind in _SQL_KINDS:
                status, severity, message, observed = _evaluate_sql_monitor(conn, m, cfg)
            elif kind == "freshness":
                fr = fresh.get(pid) or {}
                lag = fr.get("lag_hours")
                sla = float(cfg.get("sla_hours") or freshness_sla_hours())
                observed = {"lag_hours": lag, "sla_hours": sla, "freshness": fr.get("status")}
                if lag is None:
                    status, severity, message = (
                        "warn",
                        "low",
                        "freshness pending (no TARGET timestamp)",
                    )
                elif float(lag) > sla * 2:
                    status, severity, message = "fail", "critical", f"Stale: lag={lag}h sla={sla}h"
                elif float(lag) > sla:
                    status, severity, message = "fail", "high", f"Delayed: lag={lag}h sla={sla}h"
            elif kind == "pipeline_failure":
                observed = {"open_failure": pid in open_fail}
                if pid in open_fail:
                    status, severity, message = "fail", "critical", "Latest pipeline run failed"
            elif kind == "volume_drop":
                samples = _latest_successful_target_rows(conn, pid)
                cur_sample = samples[0] if samples else {}
                prev_sample = samples[1] if len(samples) > 1 else {}
                cur_rows_raw = cur_sample.get("target_rows")
                prev_rows_raw = prev_sample.get("target_rows")
                cur_known = int(num(cur_sample.get("rows_known")))
                prev_known = int(num(prev_sample.get("rows_known")))
                cur_rows = num(cur_rows_raw) if cur_rows_raw is not None else None
                prev_rows = num(prev_rows_raw) if prev_rows_raw is not None else None
                observed = {
                    "latest_target_rows": cur_rows,
                    "previous_target_rows": prev_rows,
                    "latest_rows_known": cur_known,
                    "previous_rows_known": prev_known,
                }
                if len(samples) < 2:
                    status, message = "pass", "volume baseline pending (need 2 successful runs)"
                elif cur_known == 0 or prev_known == 0:
                    status, message = "pass", "volume count unknown (TARGET row_count unavailable)"
                elif prev_rows is None or prev_rows <= 0:
                    status, message = "pass", "volume baseline pending (prior run had no rows)"
                else:
                    assert cur_rows is not None
                    drop_pct = 100.0 * (prev_rows - cur_rows) / prev_rows
                    observed["drop_pct"] = round(drop_pct, 2)
                    crit = float(cfg.get("crit_pct") or volume_drop_crit_pct())
                    warn = volume_drop_warn_pct()
                    if drop_pct >= crit:
                        status, severity, message = (
                            "fail",
                            "critical",
                            f"Volume dropped {drop_pct:.1f}% (threshold {crit}%)",
                        )
                    elif drop_pct >= warn:
                        status, severity, message = (
                            "fail",
                            "high",
                            f"Volume dropped {drop_pct:.1f}% (warning {warn}%)",
                        )
                    else:
                        status, message = "pass", "volume within baseline"
            elif kind == "dbt_test_failure":
                failures = _dbt_test_failures(conn, pid)
                observed = {"failed_tests": len(failures)}
                if failures:
                    status, severity, message = (
                        "fail",
                        "high",
                        f"{len(failures)} dbt test(s) failed on latest run",
                    )
                else:
                    status, message = "pass", "no dbt test failures on latest run"

            _write_check_result(
                cur,
                monitor_id=m["monitor_id"],
                pipeline_id=pid,
                status=status,
                severity=severity,
                message=message,
                observed=observed,
                now=now,
            )
            checks += 1

            if status == "fail":
                alerts_open += 1
                cur.execute(
                    """
                    INSERT INTO obs_alerts (
                      alert_id, monitor_id, pipeline_id, status, severity, title, message, opened_at
                    ) VALUES (%s,%s,%s,'open',%s,%s,%s,%s)
                    ON DUPLICATE KEY UPDATE
                      severity=VALUES(severity),
                      message=VALUES(message),
                      status='open',
                      resolved_at=NULL
                    """,
                    (
                        f"alert:{m['monitor_id']}",
                        m["monitor_id"],
                        pid,
                        severity,
                        m.get("name") or kind,
                        message,
                        now,
                    ),
                )
            else:
                cur.execute(
                    """
                    UPDATE obs_alerts
                    SET status='resolved', resolved_at=%s
                    WHERE monitor_id=%s AND status='open'
                    """,
                    (now, m["monitor_id"]),
                )

        for pid in open_fail:
            inc = next(
                (
                    i
                    for i in list_derived_incidents(conn, include_resolved=False)
                    if i.get("pipeline_id") == pid and i.get("status") == "open"
                ),
                None,
            )
            if not inc:
                continue
            cur.execute(
                """
                INSERT INTO obs_incidents (
                  incident_id, pipeline_id, pipeline_name, status, severity, title, description,
                  run_id, opened_at
                ) VALUES (%s,%s,%s,'open',%s,%s,%s,%s,%s)
                ON DUPLICATE KEY UPDATE
                  status='open', severity=VALUES(severity), title=VALUES(title),
                  description=VALUES(description), run_id=VALUES(run_id), resolved_at=NULL
                """,
                (
                    f"inc:{pid}:open",
                    pid,
                    inc.get("pipeline_name"),
                    inc.get("severity") or "high",
                    inc.get("title"),
                    inc.get("description") or inc.get("error_message"),
                    inc.get("run_id"),
                    _parse_dt(inc.get("opened_at")) or now,
                ),
            )
        cur.execute("SELECT incident_id, pipeline_id FROM obs_incidents WHERE status='open'")
        for row in cur.fetchall() or []:
            if row["pipeline_id"] not in open_fail:
                cur.execute(
                    "UPDATE obs_incidents SET status='resolved', resolved_at=%s WHERE incident_id=%s",
                    (now, row["incident_id"]),
                )

    conn.commit()
    return {"ok": True, "checks": checks, "alerts_touched": alerts_open, "evaluated_at": now.isoformat()}


def _parse_dt(value: Any) -> datetime | None:
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


def list_alerts(conn, *, status: str | None = None) -> list[dict]:
    sql = "SELECT * FROM obs_alerts"
    params: list[Any] = []
    if status:
        sql += " WHERE status=%s"
        params.append(status)
    sql += " ORDER BY opened_at DESC LIMIT 200"
    return fetchall(conn, sql, params)


def list_stored_incidents(conn, *, status: str | None = None) -> list[dict]:
    sql = "SELECT * FROM obs_incidents"
    params: list[Any] = []
    if status:
        sql += " WHERE status=%s"
        params.append(status)
    sql += " ORDER BY opened_at DESC LIMIT 200"
    return fetchall(conn, sql, params)
