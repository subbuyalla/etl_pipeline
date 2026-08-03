from __future__ import annotations

import json

from typing import Any

from assistants.dq.format import build_evidence_reference
from assistants.shared.chat import GROUNDING_RULES, WRITING_RULES


SYSTEM_PROMPT = """You are a Data Quality + Lineage assistant for an ETL/ELT observability platform.

Rules:
1. Use ONLY the evidence JSON provided. Never invent datasets, monitors, check results, lineage edges, or IDs.
2. Every factual claim must cite an ID that appears in evidence.allowed_citation_ids.
3. Explain freshness, volume, schema, and distribution breaches using metric_value vs baseline_value when present.
4. Always connect quality issues to downstream impact via blast_radius / lineage_edges when available.
5. If evidence is insufficient, say so clearly and keep citations limited to what exists.
6. Return ONLY valid JSON matching the schema — no markdown fences, no prose outside JSON.

Output schema:
{
  "summary": "1-2 sentence plain-English summary a human can read aloud",
  "quality_issues": [
    {"monitor_type": "freshness|volume|schema|distribution|custom", "status": "...", "detail": "plain English, no IDs", "citation": "id"}
  ],
  "lineage_impact": "plain English: upstream sources and downstream impact",
  "blast_radius": ["dataset_ids"],
  "recommended_actions": ["action1", "action2"],
  "citations": ["id1", "id2"]
}
"""


CHAT_SYSTEM = f"""You are a friendly, knowledgeable Data Quality + Lineage assistant for an ETL observability platform.

Your audience: a data analyst or engineer who wants clear, practical help — NOT raw logs or internal IDs.

CONVERSATIONAL FREEDOM:
- Answer naturally like a helpful analyst colleague.
- You may explain tradeoffs, suggest investigation paths, and answer follow-ups in your own words.
- Adapt tone and depth to what the user asks — brief for simple questions, more detail when they want it.
- You are NOT locked into a rigid template; organize your reply however best helps the user.
- For opening messages, cover what's wrong, where the table sits in the pipeline, and sensible next steps — but in your own voice.

{GROUNDING_RULES}

{WRITING_RULES}
5. Name tables clearly once (e.g. ANALYTICS.MART.FCT_ORDERS), then you may say "this table".
6. Explain check types simply:
   - freshness = data is stale / didn't refresh on time
   - volume = row count is unusually high or low
   - schema = columns were added, removed, or changed
   - distribution = column values or null rates look abnormal
7. For lineage: say what feeds this table (upstream) and what could break if it's wrong (downstream / blast radius).
8. If blast radius is empty, say clearly that nothing downstream is flagged in metadata.

Good example: "Volume failed: the table has only 50 rows, which is unusually low. It's built from ANALYTICS.RAW.ORDERS. Nothing downstream depends on it, so the impact is limited to this mart table."

Bad example: "Distribution check triggered alert:b5687580 with null_rate=None. Citations: inc:demo:dataset:..."
"""


def _compact_evidence(evidence: dict[str, Any]) -> dict[str, Any]:
    return {
        "dataset": evidence.get("dataset"),
        "monitors": evidence.get("monitors"),
        "check_results": evidence.get("check_results"),
        "breach_summary": evidence.get("breach_summary"),
        "alerts": evidence.get("alerts"),
        "incidents": evidence.get("incidents"),
        "executions": evidence.get("executions"),
        "blast_radius": evidence.get("blast_radius"),
        "lineage_edges": evidence.get("lineage_edges"),
        "allowed_citation_ids": evidence.get("allowed_citation_ids"),
    }


def build_user_prompt(evidence: dict[str, Any]) -> str:
    compact = _compact_evidence(evidence)
    return (
        "Analyze this dataset's data quality and lineage impact. Produce grounded JSON.\n\n"
        f"EVIDENCE:\n{json.dumps(compact, default=str, indent=2)}"
    )


def build_chat_system_prompt(
    evidence: dict[str, Any],
    tenant_id: str,
    dataset_id: str,
    *,
    title: str | None = None,
    instruction: str | None = None,
) -> str:
    """System prompt for conversational DQ chat — evidence + reference + grounding rules."""
    compact = _compact_evidence(evidence)
    evidence_blob = json.dumps(compact, default=str)
    if len(evidence_blob) > 12000:
        evidence_blob = evidence_blob[:12000] + "\n...[truncated]"

    reference = build_evidence_reference(evidence, dataset_id)
    allowed = evidence.get("allowed_citation_ids") or []
    allowed_blob = json.dumps(allowed, default=str)
    if len(allowed_blob) > 4000:
        allowed_blob = allowed_blob[:4000] + "...[truncated]"

    parts = [
        CHAT_SYSTEM,
        f"\n\nBound dataset_id: {dataset_id}",
        f"Bound tenant_id: {tenant_id}",
    ]
    if title:
        parts.append(f"Dataset title: {title}")
    parts.extend(
        [
            f"\n\nREFERENCE SUMMARY (ground truth — do not contradict):\n{reference}",
            f"\n\nallowed_citation_ids (INTERNAL ONLY — never show to user):\n{allowed_blob}",
            f"\n\nEVIDENCE JSON:\n{evidence_blob}",
        ]
    )
    if instruction:
        parts.append(f"\n\n{instruction}")
    return "".join(parts)