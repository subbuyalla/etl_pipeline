"""Evaluate obs_dq_rules and write results to obs_check_results."""

from __future__ import annotations

import json
import uuid
from typing import Any

from application.src.services.observability.filters import utc_now
from application.src.services.observability.lifecycle import _target_db_connector
from application.src.services.observability.quality import infer_dimension, normalize_dataset_id
from application.src.store.meta_mysql import _RULE_TYPE_TO_CHECK_KIND, list_dq_rules


def _evaluate_one_rule(conn, rule: dict) -> tuple[str, str, str, dict[str, Any]]:
    pid = str(rule.get("pipeline_id") or "")
    rtype = str(rule.get("rule_type") or "").upper()
    cfg = rule.get("config") or {}
    dataset_id = normalize_dataset_id(rule.get("dataset_id") or cfg.get("dataset_id"))
    column_name = str(rule.get("column_name") or cfg.get("column_name") or "")
    expected_max = int(cfg.get("expected_max") or 0)
    check_kind = _RULE_TYPE_TO_CHECK_KIND.get(rtype, "custom_sql")

    if rtype in {"NOT_NULL", "UNIQUE", "DUPLICATE"}:
        if not dataset_id or not column_name:
            return "pass", "low", "rule config incomplete", {"skipped": True}
        connector = _target_db_connector(conn, pid, dataset_id=dataset_id)
        if connector is None:
            return "pass", "low", "warehouse credentials unavailable — rule skipped", {"skipped": True}
        try:
            observed = connector.run_column_validation(
                dataset_id=dataset_id,
                column_name=column_name,
                check_type=check_kind,
                custom_sql=cfg.get("sql"),
                expected_max=expected_max,
            )
        except Exception as exc:
            return "fail", str(rule.get("severity") or "high"), f"Rule evaluation error: {exc}", {"error": str(exc)}
    elif rtype == "CUSTOM_SQL":
        sql = cfg.get("sql")
        if not sql:
            return "pass", "low", "custom_sql rule missing sql", {"skipped": True}
        connector = _target_db_connector(conn, pid, dataset_id=dataset_id or None)
        if connector is None:
            return "pass", "low", "warehouse credentials unavailable — rule skipped", {"skipped": True}
        try:
            observed = connector.run_column_validation(
                dataset_id=dataset_id or "DB.SCHEMA.TABLE",
                column_name=column_name or "col",
                check_type="custom_sql",
                custom_sql=sql,
                expected_max=expected_max,
            )
        except Exception as exc:
            return "fail", str(rule.get("severity") or "high"), f"Rule SQL error: {exc}", {"error": str(exc)}
    elif rtype == "ACCEPTED_VALUES":
        allowed = cfg.get("allowed_values") or cfg.get("values") or []
        col = column_name
        if not dataset_id or not col or not allowed:
            return "pass", "low", "accepted_values rule incomplete", {"skipped": True}
        vals = ", ".join(f"'{str(v).replace(chr(39), chr(39)+chr(39))}'" for v in allowed)
        sql = cfg.get("sql") or (
            f"SELECT COUNT(*) FROM {dataset_id.split('.')[-1]} "
            f"WHERE {col} IS NOT NULL AND {col} NOT IN ({vals})"
        )
        connector = _target_db_connector(conn, pid, dataset_id=dataset_id)
        if connector is None:
            return "pass", "low", "warehouse credentials unavailable — rule skipped", {"skipped": True}
        try:
            observed = connector.run_column_validation(
                dataset_id=dataset_id,
                column_name=col,
                check_type="custom_sql",
                custom_sql=sql,
                expected_max=expected_max,
            )
            observed["check_type"] = "ACCEPTED_VALUES"
        except Exception as exc:
            return "fail", str(rule.get("severity") or "high"), f"Rule error: {exc}", {"error": str(exc)}
    elif rtype == "RANGE":
        if not dataset_id or not column_name:
            return "pass", "low", "range rule incomplete", {"skipped": True}
        min_v = cfg.get("min")
        max_v = cfg.get("max")
        sql = cfg.get("sql")
        if not sql and (min_v is not None or max_v is not None):
            parts = []
            if min_v is not None:
                parts.append(f"{column_name} < {min_v}")
            if max_v is not None:
                parts.append(f"{column_name} > {max_v}")
            sql = f"SELECT COUNT(*) FROM {dataset_id} WHERE {' OR '.join(parts)}"
        if not sql:
            return "pass", "low", "range rule missing bounds/sql", {"skipped": True}
        connector = _target_db_connector(conn, pid, dataset_id=dataset_id)
        if connector is None:
            return "pass", "low", "warehouse credentials unavailable — rule skipped", {"skipped": True}
        try:
            observed = connector.run_column_validation(
                dataset_id=dataset_id,
                column_name=column_name,
                check_type="custom_sql",
                custom_sql=sql,
                expected_max=expected_max,
            )
            observed["check_type"] = "RANGE"
        except Exception as exc:
            return "fail", str(rule.get("severity") or "high"), f"Rule error: {exc}", {"error": str(exc)}
    else:
        return "pass", "low", f"unsupported rule_type {rtype}", {"skipped": True}

    observed["rule_id"] = rule.get("rule_id")
    observed["rule_type"] = rtype
    observed["dimension"] = rule.get("dimension") or infer_dimension(monitor_kind=check_kind)
    observed["tags"] = rule.get("tags") or []
    failure = int(observed.get("failure_count") or 0)
    if failure > expected_max:
        return (
            "fail",
            str(rule.get("severity") or "high"),
            f"{rtype} failed: {failure} violations (max {expected_max})",
            observed,
        )
    return "pass", "low", "rule ok", observed


def evaluate_dq_rules(conn, *, pipeline_id: str | None = None) -> dict[str, Any]:
    """Run enabled poller-triggered DQ rules; write obs_check_results."""
    rules = list_dq_rules(conn, pipeline_id=pipeline_id, include_disabled=False)
    rules = [r for r in rules if str(r.get("evaluation_trigger") or "poller") in {"poller", "both"}]
    now = utc_now()
    checks = 0
    failed = 0

    with conn.cursor() as cur:
        for rule in rules:
            rid = str(rule.get("rule_id") or "")
            pid = str(rule.get("pipeline_id") or "")
            status, severity, message, observed = _evaluate_one_rule(conn, rule)
            cid = str(uuid.uuid4())
            cur.execute(
                """
                INSERT INTO obs_check_results (
                  check_id, monitor_id, pipeline_id, status, severity, message, observed_json, checked_at
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                """,
                (
                    cid,
                    f"rule:{rid}"[:64],
                    pid,
                    status,
                    severity,
                    message,
                    json.dumps(observed, default=str),
                    now,
                ),
            )
            checks += 1
            if status == "fail":
                failed += 1

    conn.commit()
    return {"ok": True, "checks": checks, "failed": failed, "evaluated_at": now.isoformat()}
