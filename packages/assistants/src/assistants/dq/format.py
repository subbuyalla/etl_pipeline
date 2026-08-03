from __future__ import annotations

from typing import Any

CHECK_TITLES = {
    "freshness": "Freshness",
    "volume": "Volume",
    "schema": "Schema",
    "distribution": "Distribution",
    "custom": "Custom check",
}


def _short_table(name: str) -> str:
    """ANALYTICS.MART.FCT_ORDERS -> FCT_ORDERS for readability after first mention."""
    if not name:
        return "this table"
    parts = name.split(".")
    return parts[-1] if len(parts) > 1 else name


def _fmt_num(value: Any) -> str | None:
    if value is None:
        return None
    try:
        f = float(value)
        if f == int(f):
            return f"{int(f):,}"
        return f"{f:,.2f}"
    except (TypeError, ValueError):
        return str(value)


def describe_check_issue(cr: dict[str, Any]) -> dict[str, str]:
    """Turn one check result into a human-readable issue."""
    monitor_type = str(cr.get("monitor_type") or "custom").lower()
    title = CHECK_TITLES.get(monitor_type, CHECK_TITLES["custom"])
    details = cr.get("details") or {}
    metric = cr.get("metric_value")
    baseline = cr.get("baseline_value")
    severity = (cr.get("severity") or details.get("severity") or "").lower()

    explanation = ""
    if monitor_type == "freshness":
        lag = metric if metric is not None else details.get("lag_minutes")
        sla = baseline if baseline is not None else details.get("sla_minutes")
        lag_s = _fmt_num(lag)
        sla_s = _fmt_num(sla)
        if lag_s and sla_s:
            explanation = f"Data is about {lag_s} minutes late; the SLA allows {sla_s} minutes."
        elif lag_s:
            explanation = f"Data is about {lag_s} minutes late."
        else:
            explanation = "The table did not refresh within the expected time window."
    elif monitor_type == "volume":
        rows = metric if metric is not None else details.get("row_count")
        expected_min = baseline if baseline is not None else details.get("expected_min")
        expected_max = details.get("expected_max")
        rows_s = _fmt_num(rows)
        if rows_s and expected_min is not None:
            explanation = f"Row count is {rows_s}, which is below the expected minimum of {_fmt_num(expected_min)}."
        elif rows_s and expected_max is not None:
            explanation = f"Row count is {rows_s}, which is above the expected maximum of {_fmt_num(expected_max)}."
        elif rows_s:
            explanation = f"Row count ({rows_s} rows) looks unusual compared to recent history."
        else:
            explanation = "The number of rows in this table looks unusual."
    elif monitor_type == "schema":
        change = details.get("change_type") or "change"
        breaking = details.get("breaking")
        if breaking:
            explanation = f"A breaking schema {change} was detected — downstream jobs may fail."
        else:
            explanation = f"A schema {change} was detected (columns added, removed, or changed)."
    elif monitor_type == "distribution":
        column = details.get("column") or "a column"
        metric_name = details.get("metric") or "null_rate"
        value = metric if metric is not None else details.get("value")
        base = baseline if baseline is not None else details.get("baseline")
        value_s = _fmt_num(value)
        base_s = _fmt_num(base)
        label = metric_name.replace("_", " ")
        if value_s and base_s:
            explanation = f"{label} on {column} is {value_s} (baseline ~{base_s})."
        elif value_s:
            explanation = f"{label} on {column} is {value_s}, which looks off."
        else:
            explanation = f"Values in {column} ({label}) don't match the normal pattern."
    else:
        explanation = str(cr.get("status") or "Check did not pass.")

    if severity in {"high", "critical"}:
        explanation += " Severity: high."

    return {"title": title, "explanation": explanation, "monitor_type": monitor_type}


def _open_incidents(evidence: dict[str, Any]) -> list[dict[str, Any]]:
    return [i for i in (evidence.get("incidents") or []) if (i.get("status") or "").lower() != "resolved"]


def _failed_checks(evidence: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen_types: set[str] = set()
    for cr in evidence.get("check_results") or []:
        status = (cr.get("status") or "").lower()
        if status not in {"failed", "anomalous"}:
            continue
        mt = str(cr.get("monitor_type") or "")
        if mt in seen_types:
            continue
        seen_types.add(mt)
        out.append(cr)
    # If no check results, infer from open incidents
    if not out:
        for inc in _open_incidents(evidence):
            mt = str(inc.get("title") or "").lower()
            for key in CHECK_TITLES:
                if key in mt or key in (inc.get("summary") or "").lower():
                    out.append({"monitor_type": key, "status": "failed", "details": {}, "severity": inc.get("severity")})
                    break
    return out


def describe_lineage(evidence: dict[str, Any], dataset_id: str) -> str:
    edges = evidence.get("lineage_edges") or []
    upstream = sorted({e.get("upstream_dataset_id") for e in edges if e.get("upstream_dataset_id")})
    downstream = sorted({e.get("downstream_dataset_id") for e in edges if e.get("downstream_dataset_id") and e.get("downstream_dataset_id") != dataset_id})
    blast = evidence.get("blast_radius") or {}
    blast_list = blast.get("downstream") or []

    parts: list[str] = []
    if upstream:
        if len(upstream) == 1:
            parts.append(f"This table is built from **{upstream[0]}**.")
        else:
            parts.append(f"This table is built from: {', '.join(upstream)}.")
    else:
        parts.append("We don't see any upstream source tables in lineage metadata.")

    if blast_list:
        if len(blast_list) == 1:
            parts.append(f"If this table has a problem, **1 downstream table** could be affected: {blast_list[0]}.")
        else:
            names = ", ".join(blast_list[:5])
            extra = f" (and {len(blast_list) - 5} more)" if len(blast_list) > 5 else ""
            parts.append(f"If this table has a problem, **{len(blast_list)} downstream tables** could be affected: {names}{extra}.")
    elif downstream:
        parts.append(f"It feeds into {len(downstream)} downstream table(s), but none are in the blast-radius list right now.")
    else:
        parts.append("Nothing downstream depends on this table in metadata — impact is limited to this table itself.")

    return " ".join(parts)


def format_dq_opening(evidence: dict[str, Any], dataset_id: str) -> str:
    """Deterministic, human-readable opening message — no alert IDs or jargon."""
    table = dataset_id or "this dataset"
    short = _short_table(table)
    failed = _failed_checks(evidence)
    open_alerts = [a for a in (evidence.get("alerts") or []) if (a.get("status") or "").lower() == "open"]

    lines: list[str] = []
    lines.append(f"Here’s what we know about **{table}**:")
    lines.append("")

    # What's wrong
    if failed:
        lines.append("**What’s wrong**")
        if len(failed) == 1:
            issue = describe_check_issue(failed[0])
            lines.append(f"- **{issue['title']}**: {issue['explanation']}")
        else:
            lines.append(f"This table has **{len(failed)} open data-quality problems**:")
            for cr in failed[:6]:
                issue = describe_check_issue(cr)
                lines.append(f"- **{issue['title']}**: {issue['explanation']}")
        if open_alerts:
            lines.append(f"\nThere are also **{len(open_alerts)} open alert(s)** tied to this table.")
    else:
        lines.append("**What’s wrong**")
        lines.append("No failed freshness, volume, schema, or distribution checks show up in metadata right now.")

    lines.append("")
    lines.append("**Where it sits in the pipeline**")
    lines.append(describe_lineage(evidence, dataset_id))

    # Optional catalog note — softer wording
    dataset = evidence.get("dataset") or {}
    if dataset.get("missing_from_catalog"):
        lines.append("")
        lines.append(
            "_Note: this table isn’t fully registered in the dataset catalog yet, "
            "but monitors and lineage still recorded the issues above._"
        )

    # Next steps
    lines.append("")
    lines.append("**What you can do next**")
    actions = _suggest_actions(failed, evidence, dataset_id)
    for a in actions[:4]:
        lines.append(f"- {a}")

    lines.append("")
    lines.append("Ask me anything — for example: *Which checks failed?* or *Is anything downstream affected?*")
    return "\n".join(lines)


def _suggest_actions(failed: list[dict[str, Any]], evidence: dict[str, Any], dataset_id: str) -> list[str]:
    actions: list[str] = []
    types = {str(cr.get("monitor_type") or "").lower() for cr in failed}
    edges = evidence.get("lineage_edges") or []
    upstream = next((e.get("upstream_dataset_id") for e in edges if e.get("upstream_dataset_id")), None)

    if "volume" in types:
        actions.append("Compare today’s row count with the last few successful loads — a sudden drop or spike often means a partial or duplicate load.")
    if "distribution" in types:
        actions.append("Inspect the flagged column(s) for unexpected nulls or value shifts — often caused by a source change or bad join.")
    if "freshness" in types:
        actions.append("Check whether the pipeline that refreshes this table ran on schedule and finished successfully.")
    if "schema" in types:
        actions.append("Review recent schema changes and confirm downstream models still match the new columns.")
    if upstream:
        actions.append(f"Look upstream at **{upstream}** — issues there often show up in this table first.")
    if not actions:
        actions.append("Review recent pipeline runs and confirm source data arrived as expected.")
    return actions


def format_checks_answer(evidence: dict[str, Any]) -> str | None:
    """Short deterministic answer for 'which checks failed?' — LLM fallback only."""
    failed = _failed_checks(evidence)
    if not failed:
        return "According to metadata, no freshness, volume, schema, or distribution checks are currently failing for this table."
    lines = ["These checks are **not passing** right now:", ""]
    for cr in failed:
        issue = describe_check_issue(cr)
        lines.append(f"- **{issue['monitor_type'].title()}**: {issue['explanation']}")
    return "\n".join(lines)


def build_evidence_reference(evidence: dict[str, Any], dataset_id: str) -> str:
    """Compact factual digest for LLM grounding — internal reference, not user-facing."""
    table = dataset_id or "this dataset"
    failed = _failed_checks(evidence)
    open_alerts = [a for a in (evidence.get("alerts") or []) if (a.get("status") or "").lower() == "open"]
    lines: list[str] = [f"Dataset: {table}"]

    breach = evidence.get("breach_summary") or {}
    if breach:
        parts = [f"{k}×{v}" for k, v in breach.items()]
        lines.append(f"Breach counts: {', '.join(parts)}")

    if failed:
        lines.append("Failed checks (ground truth):")
        for cr in failed[:8]:
            issue = describe_check_issue(cr)
            lines.append(f"- {issue['title']}: {issue['explanation']}")
    else:
        lines.append("Failed checks: none in metadata right now.")

    if open_alerts:
        lines.append(f"Open alerts on this table: {len(open_alerts)}")

    lines.append("")
    lines.append("Lineage / blast radius:")
    lines.append(describe_lineage(evidence, dataset_id))

    dataset = evidence.get("dataset") or {}
    if dataset.get("missing_from_catalog"):
        lines.append("Note: table is not fully registered in the dataset catalog.")

    actions = _suggest_actions(failed, evidence, dataset_id)
    if actions:
        lines.append("")
        lines.append("Suggested investigation paths (from metadata):")
        for action in actions[:4]:
            lines.append(f"- {action}")

    return "\n".join(lines)
