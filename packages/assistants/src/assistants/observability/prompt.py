from __future__ import annotations

import json
from typing import Any

from assistants.shared.chat import GROUNDING_RULES, WRITING_RULES


CHAT_SYSTEM = f"""You are the Observability assistant for an ETL reliability platform (Monte Carlo–style).

Your audience: data engineers and on-call responders looking at the Reliability overview.

Context:
- You are bound to one tenant (tenant_id is set by the product).
- You can see estate-wide Metadata: pipelines, datasets, open incidents, monitors, alerts, check results, metrics.
- Prefer a clear reliability summary: what is broken, how bad, what to look at first.

CONVERSATIONAL FREEDOM:
- Answer like a helpful SRE colleague.
- Lead with counts and the worst open issues, then suggest next actions (open Incidents chat / Explain DQ).
- You may drill into a named pipeline or dataset if the user asks.

{GROUNDING_RULES}

{WRITING_RULES}
5. Never invent pipeline or dataset names — only use what tools returned.
6. Distinguish open incidents vs alerts vs monitors clearly when the user asks.
7. If metrics time series are empty, say so (counts can still be high without chart points).
"""


def build_chat_system_prompt(
    evidence: dict[str, Any],
    tenant_id: str,
    *,
    instruction: str | None = None,
) -> str:
    overview = evidence.get("reliability_overview") or {}
    compact = {
        "reliability_overview": overview,
        "pipelines": (evidence.get("pipelines") or [])[:20],
        "datasets": (evidence.get("datasets") or [])[:20],
        "incidents": (evidence.get("incidents") or [])[:15],
        "alerts": (evidence.get("alerts") or [])[:15],
        "monitors": (evidence.get("monitors") or [])[:20],
        "check_results": (evidence.get("check_results") or [])[:15],
        "metrics": (evidence.get("metrics") or [])[:20],
        "allowed_citation_ids": evidence.get("allowed_citation_ids"),
    }
    parts = [
        CHAT_SYSTEM,
        f"\nBound tenant_id: {tenant_id}",
        "\nEVIDENCE JSON:\n" + json.dumps(compact, default=str)[:12000],
    ]
    if instruction:
        parts.append("\nINSTRUCTION:\n" + instruction)
    return "\n".join(parts)


def format_overview_fallback(evidence: dict[str, Any]) -> str:
    """Deterministic opening when the LLM is unavailable."""
    ov = evidence.get("reliability_overview") or {}
    pipelines = ov.get("pipeline_count", len(evidence.get("pipelines") or []))
    datasets = ov.get("dataset_count", len(evidence.get("datasets") or []))
    open_inc = ov.get("open_incident_count")
    if open_inc is None:
        open_inc = sum(1 for i in (evidence.get("incidents") or []) if (i.get("status") or "") == "open")
    alerts = ov.get("alert_count", len(evidence.get("alerts") or []))
    failed = ov.get("failed_pipeline_count", 0)
    failing_checks = ov.get("failing_check_count")
    if failing_checks is None:
        failing_checks = sum(
            1
            for c in (evidence.get("check_results") or [])
            if (c.get("status") or "").lower() in {"anomalous", "failed", "breach", "error"}
        )

    lines = [
        "Here's a quick reliability snapshot from metadata:",
        f"- Pipelines: {pipelines} (failed status: {failed})",
        f"- Datasets: {datasets}",
        f"- Open incidents: {open_inc}",
        f"- Alerts: {alerts}",
        f"- Failing checks: {failing_checks}",
        "",
    ]
    tops = ov.get("top_open_incidents") or [
        i for i in (evidence.get("incidents") or []) if (i.get("status") or "") == "open"
    ][:5]
    if tops:
        lines.append("Top open incidents:")
        for i in tops[:5]:
            title = i.get("title") or i.get("incident_key") or "incident"
            sev = i.get("severity") or "unknown"
            asset = i.get("root_asset_id") or "—"
            lines.append(f"- [{sev}] {title} (asset: {asset})")
    else:
        lines.append("No open incidents in the current evidence.")
    lines.append("")
    lines.append(
        "Ask me what to fix first, which pipelines are failing, or which monitors are noisy."
    )
    return "\n".join(lines)
