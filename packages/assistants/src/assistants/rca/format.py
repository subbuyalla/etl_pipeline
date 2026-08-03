from __future__ import annotations

from typing import Any


def _failed_executions(evidence: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        e
        for e in (evidence.get("executions") or [])
        if (e.get("status") or "").lower() in {"failed", "error", "cancelled"}
    ]


def _open_alerts(evidence: dict[str, Any]) -> list[dict[str, Any]]:
    return [a for a in (evidence.get("alerts") or []) if (a.get("status") or "").lower() == "open"]


def describe_blast_radius(evidence: dict[str, Any]) -> str:
    blast = evidence.get("blast_radius") or {}
    downstream = blast.get("downstream") or []
    if not downstream:
        return "Metadata does not flag any downstream assets in the blast radius."
    if len(downstream) == 1:
        return f"If this incident is not resolved, **1 downstream asset** could be affected: {downstream[0]}."
    names = ", ".join(downstream[:5])
    extra = f" (and {len(downstream) - 5} more)" if len(downstream) > 5 else ""
    return (
        f"If this incident is not resolved, **{len(downstream)} downstream assets** "
        f"could be affected: {names}{extra}."
    )


def describe_failure_errors(evidence: dict[str, Any]) -> str:
    """Human-readable error lines from incident summary, alerts, and failed executions."""
    lines: list[str] = []
    incident = evidence.get("incident") or {}
    summary = incident.get("summary") or incident.get("error_message")
    if summary:
        lines.append(str(summary))

    for alert in _open_alerts(evidence):
        message = alert.get("message")
        if message and message not in lines:
            lines.append(str(message))

    for exe in _failed_executions(evidence)[:3]:
        message = exe.get("error_message")
        if not message:
            continue
        pipeline = exe.get("pipeline_id") or "pipeline"
        task = exe.get("task_id")
        label = f"{pipeline}.{task}" if task else pipeline
        line = f"{label}: {message}"
        if line not in lines:
            lines.append(line)

    return "\n".join(lines)


def describe_timeline(evidence: dict[str, Any]) -> str:
    incident = evidence.get("incident") or {}
    parts: list[str] = []
    if incident.get("created_at"):
        parts.append(f"Incident opened at {incident['created_at']}.")
    if incident.get("updated_at"):
        parts.append(f"Last updated at {incident['updated_at']}.")
    failed = _failed_executions(evidence)
    if failed:
        parts.append(f"{len(failed)} failed pipeline execution(s) appear in metadata.")
        first_err = failed[0].get("error_message")
        if first_err:
            parts.append(f"Latest error: {first_err}")
    open_alerts = _open_alerts(evidence)
    if open_alerts:
        parts.append(f"{len(open_alerts)} open alert(s) are tied to the root asset.")
    return " ".join(parts) if parts else "Timeline details are limited in current metadata."


def format_rca_opening(
    rca: dict[str, Any],
    incident_title: str | None,
    evidence: dict[str, Any] | None = None,
) -> str:
    """Deterministic, human-readable opening — no internal IDs or citation footers."""
    title = incident_title or "this incident"
    lines = [
        f"Here's what metadata shows for **{title}**:",
        "",
    ]

    errors = describe_failure_errors(evidence) if evidence else ""
    if errors:
        lines.append("**Error detail:**")
        lines.append(errors)
        lines.append("")

    lines.extend([
        f"**Summary:** {rca.get('summary') or 'No summary available yet.'}",
        "",
        f"**Likely cause:** {rca.get('likely_cause') or 'Root cause is unclear from available metadata.'}",
    ])

    timeline = rca.get("timeline") or []
    if timeline:
        lines.append("")
        lines.append("**Timeline:**")
        for item in timeline[:5]:
            event = item.get("event") or "Event recorded"
            at = item.get("at") or "unknown time"
            lines.append(f"- {at}: {event}")

    blast = rca.get("blast_radius") or []
    if blast:
        lines.append("")
        if len(blast) == 1:
            lines.append(f"**Blast radius:** 1 downstream asset may be affected ({blast[0]}).")
        else:
            names = ", ".join(blast[:5])
            extra = f" (and {len(blast) - 5} more)" if len(blast) > 5 else ""
            lines.append(f"**Blast radius:** {len(blast)} downstream assets may be affected: {names}{extra}.")

    actions = rca.get("recommended_actions") or []
    if actions:
        lines.append("")
        lines.append("**Suggested next steps:**")
        for action in actions[:5]:
            lines.append(f"- {action}")

    lines.append("")
    lines.append("Ask a follow-up — e.g. what failed, blast radius, or what to fix first.")
    return "\n".join(lines)


def format_blast_radius_answer(evidence: dict[str, Any]) -> str:
    return describe_blast_radius(evidence)


def format_executions_answer(evidence: dict[str, Any]) -> str:
    failed = _failed_executions(evidence)
    if not failed:
        return "According to metadata, no failed pipeline executions are recorded for this incident's root asset."
    lines = ["These pipeline runs **failed** in metadata:", ""]
    for exe in failed[:8]:
        pipeline = exe.get("pipeline_id") or "unknown pipeline"
        status = exe.get("status") or "failed"
        started = exe.get("started_at") or "unknown time"
        err = exe.get("error_message")
        line = f"- **{pipeline}** — {status} (started {started})"
        if err:
            line += f"\n  Error: {err}"
        label = exe.get("deep_link_label")
        link = exe.get("deep_link")
        if link and label:
            line += f"\n  {label}: {link}"
        lines.append(line)
    return "\n".join(lines)


def build_evidence_reference(evidence: dict[str, Any], incident_key: str) -> str:
    """Compact factual digest for LLM grounding — internal reference, not user-facing."""
    incident = evidence.get("incident") or {}
    title = incident.get("title") or incident_key or "this incident"
    lines: list[str] = [f"Incident: {title}"]

    if incident.get("status"):
        lines.append(f"Status: {incident['status']}")
    if incident.get("severity"):
        lines.append(f"Severity: {incident['severity']}")
    if incident.get("summary"):
        lines.append(f"Incident summary: {incident['summary']}")

    asset_type = incident.get("root_asset_type") or "unknown"
    asset_id = incident.get("root_asset_id") or "unknown"
    lines.append(f"Root asset: {asset_type} — {asset_id}")

    open_alerts = _open_alerts(evidence)
    if open_alerts:
        lines.append(f"Open alerts: {len(open_alerts)}")
        for alert in open_alerts[:5]:
            lines.append(f"- {alert.get('title') or alert.get('alert_type') or 'Alert'}: {alert.get('summary') or alert.get('status')}")

    failed = _failed_executions(evidence)
    if failed:
        lines.append(f"Failed executions: {len(failed)}")
        for exe in failed[:6]:
            pipeline = exe.get("pipeline_id") or "pipeline"
            err = exe.get("error_message")
            detail = f" — error: {err}" if err else ""
            lines.append(
                f"- {pipeline}: {exe.get('status')} at {exe.get('started_at') or 'unknown'}{detail}"
            )
            if exe.get("deep_link"):
                lines.append(f"  deep_link: {exe.get('deep_link')}")

    dashboard = evidence.get("pipeline_dashboard") or {}
    metrics = dashboard.get("metrics") or {}
    if metrics:
        parts = [f"{k}={v}" for k, v in list(metrics.items())[:6]]
        lines.append(f"Pipeline metrics: {', '.join(parts)}")

    lines.append("")
    lines.append("Blast radius:")
    lines.append(describe_blast_radius(evidence))

    lines.append("")
    lines.append("Timeline:")
    lines.append(describe_timeline(evidence))

    return "\n".join(lines)
