"""Copilot Tools & Skill Handlers for DataPulse.

Provides safe, parameterized access to:
- Metadata Store (safe read-only SQL)
- Root Cause Analysis (RCA) correlation
- Data Quality check diagnostics
- Observability rollups & analytics
- Operational actions (Incident creation, alert acknowledgement)
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta
from typing import Any

from application.src.store.meta_mysql import get_connection
from application.src.services.observability.filters import fetchall, fetchone, json_val
from application.src.services.observability.rca_context import build_rca_context

logger = logging.getLogger(__name__)

# Allowed tables for safe read-only metadata queries
ALLOWED_TABLES = {
    "obs_pipelines",
    "obs_pipeline_runs",
    "obs_run_assets",
    "obs_run_columns",
    "obs_run_query_history",
    "obs_connections",
    "obs_connector_instances",
    "obs_pipeline_bindings",
    "obs_tool_snapshots",
    "obs_monitors",
    "obs_dq_rules",
    "obs_dq_daily_rollups",
    "obs_check_results",
    "obs_alerts",
    "obs_incidents",
    "obs_lineage_edges",
    "obs_assets",
    "obs_metric_rollups_daily",
    "obs_metric_observations",
    "obs_collector_heartbeats",
}

FORBIDDEN_KEYWORDS = {
    "insert", "update", "delete", "drop", "alter", "truncate",
    "grant", "revoke", "create", "replace", "execute", "call",
    "information_schema", "mysql.", "performance_schema", "sys.",
    "obs_secrets"
}


def safe_query_metadata_sql(sql: str, tenant_id: str = "default", max_rows: int = 50) -> dict[str, Any]:
    """Execute a safe, validated read-only SQL query against obs_* tables."""
    clean_sql = (sql or "").strip().rstrip(";").strip()
    if not clean_sql:
        return {"ok": False, "error": "Empty SQL query"}

    lower_sql = clean_sql.lower()
    if not lower_sql.startswith("select"):
        return {"ok": False, "error": "Only SELECT queries are permitted"}

    for kw in FORBIDDEN_KEYWORDS:
        if re.search(r"\b" + re.escape(kw) + r"\b", lower_sql):
            return {"ok": False, "error": f"Security violation: query contains forbidden keyword '{kw}'"}

    # Extract table names mentioned
    tables_found = set(re.findall(r"\b(obs_[a-z0-9_]+)\b", lower_sql))
    if not tables_found:
        return {"ok": False, "error": "Query must reference at least one valid obs_* table"}

    disallowed = tables_found - ALLOWED_TABLES
    if disallowed:
        return {"ok": False, "error": f"Access denied to tables: {', '.join(disallowed)}"}

    if "limit" not in lower_sql:
        clean_sql += f" LIMIT {max_rows}"

    with get_connection() as conn:
        try:
            rows = fetchall(conn, clean_sql)
            sanitized_rows = []
            for row in rows:
                sanitized_rows.append({
                    k: json_val(v) for k, v in row.items()
                    if "secret" not in k.lower() and "token" not in k.lower() and "password" not in k.lower()
                })
            return {
                "ok": True,
                "row_count": len(sanitized_rows),
                "rows": sanitized_rows[:max_rows],
                "sql": clean_sql
            }
        except Exception as exc:
            return {"ok": False, "error": str(exc), "sql": clean_sql}


def diagnose_root_cause(run_id: str | None = None, pipeline_id: str | None = None) -> dict[str, Any]:
    """Perform multi-hop root cause analysis using the existing RCA bundle."""
    with get_connection() as conn:
        if not run_id and pipeline_id:
            latest_failed = fetchone(
                conn,
                """
                SELECT id FROM obs_pipeline_runs
                WHERE pipeline_id = %s AND LOWER(status) IN ('failed', 'error', 'failure')
                ORDER BY COALESCE(end_time, start_time, created_at) DESC
                LIMIT 1
                """,
                (pipeline_id,)
            )
            if latest_failed:
                run_id = str(latest_failed.get("id"))
            else:
                latest_any = fetchone(
                    conn,
                    "SELECT id FROM obs_pipeline_runs WHERE pipeline_id = %s ORDER BY COALESCE(end_time, start_time, created_at) DESC LIMIT 1",
                    (pipeline_id,)
                )
                if latest_any:
                    run_id = str(latest_any.get("id"))

        if not run_id:
            return {"ok": False, "error": "No run_id provided or found for diagnosis"}

        try:
            bundle = build_rca_context(conn, run_id=run_id)
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
        if not bundle.get("ok"):
            return bundle

        failure = bundle.get("failure") or {}
        run = bundle.get("run") or {}
        queries = bundle.get("query_history") or []
        failed_queries = [q for q in queries if str(q.get("execution_status")).upper() == "FAILED" or q.get("error_code")]
        lineage_up = bundle.get("lineage_upstream") or []
        failed_dq = [c for c in (bundle.get("dq_checks") or []) if str(c.get("status")).lower() in {"fail", "failed", "error", "warn"}]
        change_since = bundle.get("change_since_last_success") or {}

        probable_causes = []
        if failure.get("failed_message"):
            probable_causes.append(f"Execution Error: {failure.get('failed_message')}")
        if failure.get("failed_node"):
            probable_causes.append(f"Failed Node: {failure.get('failed_node')} at stage '{failure.get('stage') or 'unknown'}'")
        if failed_queries:
            fq = failed_queries[0]
            probable_causes.append(f"Target DB Query Failure [{fq.get('error_code')}]: {fq.get('error_message') or fq.get('query_text')[:120]}")
        if change_since.get("schema_change_count", 0) > 0:
            probable_causes.append(f"Schema Drift: {change_since.get('schema_change_count')} schema changes detected since last successful run")
        if failed_dq:
            probable_causes.append(f"Data Quality Violations: {len(failed_dq)} failed DQ check(s) in pipeline window")

        remediation_steps = []
        if failure.get("error_class") == "SyntaxError" or "syntax" in str(failure.get("failed_message") or "").lower():
            remediation_steps.append("Inspect SQL query syntax in the failed transformation model.")
        elif "timeout" in str(failure.get("failed_message") or "").lower():
            remediation_steps.append("Increase warehouse compute size or tune table partitioning/clustering keys.")
        elif change_since.get("schema_change_count", 0) > 0:
            remediation_steps.append("Reconcile schema mismatch between source extraction and target table definition.")
        else:
            remediation_steps.append("Verify source connection availability and review failed step parameters.")

        return {
            "ok": True,
            "run_id": run_id,
            "pipeline_id": bundle.get("pipeline_id"),
            "pipeline_name": bundle.get("pipeline_name"),
            "status": bundle.get("status"),
            "tool": run.get("tool_name"),
            "failure_stage": failure.get("stage"),
            "failed_node": failure.get("failed_node"),
            "error_class": failure.get("error_class"),
            "failed_message": failure.get("failed_message") or failure.get("error_message"),
            "probable_causes": probable_causes,
            "remediation_steps": remediation_steps,
            "failed_queries_count": len(failed_queries),
            "upstream_dependencies_count": len(lineage_up),
            "failed_dq_checks_count": len(failed_dq),
            "schema_changes_since_last_success": change_since.get("schema_change_count", 0),
            "raw_log_sample": (bundle.get("run", {}).get("raw_log") or "")[:500] if bundle.get("run") else "",
        }


def explain_data_quality(pipeline_id: str | None = None, dataset_id: str | None = None, days: int = 7) -> dict[str, Any]:
    """Retrieve and explain data quality rules, failures, and rollups."""
    with get_connection() as conn:
        where_clauses = ["checked_at >= DATE_SUB(NOW(), INTERVAL %s DAY)"]
        params: list[Any] = [days]

        if pipeline_id:
            where_clauses.append("pipeline_id = %s")
            params.append(pipeline_id)

        sql = f"""
            SELECT check_id, monitor_id, pipeline_id, status, severity, message, observed_json, checked_at
            FROM obs_check_results
            WHERE {' AND '.join(where_clauses)}
            ORDER BY checked_at DESC
            LIMIT 100
        """
        checks = fetchall(conn, sql, tuple(params))

        rules_sql = "SELECT rule_id, pipeline_id, rule_name, rule_type, dataset_id, column_name, dimension, severity, is_enabled FROM obs_dq_rules"
        if pipeline_id:
            rules_sql += " WHERE pipeline_id = %s"
            rules = fetchall(conn, rules_sql, (pipeline_id,))
        else:
            rules = fetchall(conn, rules_sql + " LIMIT 50")

        rollup_sql = "SELECT bucket_date, pipeline_id, source_type, passed, warn, failed, total, score_pct FROM obs_dq_daily_rollups WHERE bucket_date >= DATE_SUB(CURDATE(), INTERVAL %s DAY)"
        rollup_params: list[Any] = [days]
        if pipeline_id:
            rollup_sql += " AND pipeline_id = %s"
            rollup_params.append(pipeline_id)
        rollup_sql += " ORDER BY bucket_date DESC LIMIT 30"
        rollups = fetchall(conn, rollup_sql, tuple(rollup_params))

        total_checks = len(checks)
        failed_checks = [c for c in checks if str(c.get("status")).lower() in {"fail", "failed", "error"}]
        warn_checks = [c for c in checks if str(c.get("status")).lower() in {"warn", "warning"}]
        pass_checks = [c for c in checks if str(c.get("status")).lower() in {"pass", "passed", "success"}]

        overall_score = round((len(pass_checks) / total_checks * 100), 1) if total_checks > 0 else 100.0

        return {
            "ok": True,
            "pipeline_id": pipeline_id,
            "time_window_days": days,
            "overall_score_pct": overall_score,
            "summary": {
                "total_evaluations": total_checks,
                "passed": len(pass_checks),
                "warned": len(warn_checks),
                "failed": len(failed_checks),
                "rules_configured": len(rules),
            },
            "recent_failures": [
                {
                    "check_id": c.get("check_id"),
                    "pipeline_id": c.get("pipeline_id"),
                    "monitor_id": c.get("monitor_id"),
                    "severity": c.get("severity") or "high",
                    "message": c.get("message"),
                    "checked_at": str(c.get("checked_at")),
                }
                for c in failed_checks[:10]
            ],
            "configured_rules": [
                {
                    "name": r.get("rule_name"),
                    "type": r.get("rule_type"),
                    "dimension": r.get("dimension"),
                    "column": r.get("column_name"),
                    "severity": r.get("severity"),
                }
                for r in rules[:10]
            ],
            "daily_trends": [
                {
                    "date": str(ro.get("bucket_date")),
                    "score_pct": ro.get("score_pct"),
                    "passed": ro.get("passed"),
                    "failed": ro.get("failed"),
                }
                for ro in rollups[:7]
            ]
        }


def get_observability_analytics(tool_filter: str | None = None, days: int = 7) -> dict[str, Any]:
    """Compute aggregated metrics: run success rates, duration, top failing pipelines, and open incidents."""
    with get_connection() as conn:
        tool_clause = ""
        params: list[Any] = [days]
        if tool_filter and tool_filter != "all":
            tool_clause = "AND LOWER(tool_name) = LOWER(%s)"
            params.append(tool_filter)

        run_stats = fetchone(
            conn,
            f"""
            SELECT
              COUNT(*) AS total_runs,
              SUM(CASE WHEN LOWER(status) IN ('success', 'completed') THEN 1 ELSE 0 END) AS success_runs,
              SUM(CASE WHEN LOWER(status) IN ('failed', 'error', 'failure') THEN 1 ELSE 0 END) AS failed_runs,
              AVG(duration) AS avg_duration_sec,
              SUM(COALESCE(rows_written, 0)) AS total_rows_written
            FROM obs_pipeline_runs
            WHERE start_time >= DATE_SUB(NOW(), INTERVAL %s DAY)
            {tool_clause}
            """,
            tuple(params)
        ) or {}

        top_failing_sql = f"""
            SELECT pipeline_id, pipeline_name, tool_name,
                   COUNT(*) AS fail_count,
                   MAX(start_time) AS last_failed_at
            FROM obs_pipeline_runs
            WHERE start_time >= DATE_SUB(NOW(), INTERVAL %s DAY)
              AND LOWER(status) IN ('failed', 'error', 'failure')
              {tool_clause}
            GROUP BY pipeline_id, pipeline_name, tool_name
            ORDER BY fail_count DESC
            LIMIT 5
        """
        top_failing = fetchall(conn, top_failing_sql, tuple(params))

        open_incidents = fetchall(
            conn,
            """
            SELECT incident_id, pipeline_id, pipeline_name, severity, title, status, opened_at
            FROM obs_incidents
            WHERE LOWER(status) IN ('open', 'investigating')
            ORDER BY opened_at DESC
            LIMIT 5
            """
        )

        total = run_stats.get("total_runs") or 0
        success = run_stats.get("success_runs") or 0
        success_rate = round((success / total * 100), 1) if total > 0 else 0.0

        return {
            "ok": True,
            "time_window_days": days,
            "tool_filter": tool_filter or "all",
            "total_runs": total,
            "success_runs": success,
            "failed_runs": run_stats.get("failed_runs") or 0,
            "success_rate_pct": success_rate,
            "avg_duration_sec": round(run_stats.get("avg_duration_sec") or 0, 1),
            "total_rows_processed": run_stats.get("total_rows_written") or 0,
            "top_failing_pipelines": [
                {
                    "pipeline_id": f.get("pipeline_id"),
                    "name": f.get("pipeline_name") or f.get("pipeline_id"),
                    "tool": f.get("tool_name"),
                    "failures": f.get("fail_count"),
                    "last_failed": str(f.get("last_failed_at")),
                }
                for f in top_failing
            ],
            "active_incidents": [
                {
                    "id": i.get("incident_id"),
                    "title": i.get("title"),
                    "severity": i.get("severity"),
                    "pipeline": i.get("pipeline_name") or i.get("pipeline_id"),
                    "opened_at": str(i.get("opened_at")),
                }
                for i in open_incidents
            ]
        }


def execute_ops_action(action_type: str, payload: dict[str, Any], tenant_id: str = "default") -> dict[str, Any]:
    """Execute operational actions like creating an incident ticket or acknowledging alerts."""
    with get_connection() as conn:
        if action_type == "create_incident":
            pipeline_id = payload.get("pipeline_id")
            if not pipeline_id:
                return {"ok": False, "error": "pipeline_id is required"}

            pipe = fetchone(conn, "SELECT pipeline_name FROM obs_pipelines WHERE pipeline_id = %s", (pipeline_id,))
            pname = pipe.get("pipeline_name") if pipe else pipeline_id

            incident_id = f"inc_{int(datetime.utcnow().timestamp())}"
            severity = payload.get("severity") or "high"
            title = payload.get("title") or f"Copilot Triage: Incident on {pname}"
            desc = payload.get("description") or "Automated incident created via DataPulse Copilot."
            run_id = payload.get("run_id")

            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO obs_incidents (incident_id, pipeline_id, pipeline_name, status, severity, title, description, run_id, opened_at)
                    VALUES (%s, %s, %s, 'open', %s, %s, %s, %s, NOW())
                    """,
                    (incident_id, pipeline_id, pname, severity, title, desc, run_id)
                )
            conn.commit()
            return {
                "ok": True,
                "action": "create_incident",
                "incident_id": incident_id,
                "message": f"Incident '{title}' ({severity.upper()}) created successfully.",
            }

        elif action_type == "acknowledge_alert":
            alert_id = payload.get("alert_id")
            if not alert_id:
                return {"ok": False, "error": "alert_id is required"}

            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE obs_alerts SET status = 'acknowledged' WHERE alert_id = %s",
                    (alert_id,)
                )
            conn.commit()
            return {
                "ok": True,
                "action": "acknowledge_alert",
                "alert_id": alert_id,
                "message": f"Alert {alert_id} acknowledged.",
            }

        return {"ok": False, "error": f"Unknown action_type '{action_type}'"}
