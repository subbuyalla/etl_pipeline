from __future__ import annotations

import json

from typing import Any

from assistants.rca.format import build_evidence_reference
from assistants.shared.chat import GROUNDING_RULES, WRITING_RULES


SYSTEM_PROMPT = """You are an Incident RCA (Root Cause Analysis) assistant for an ETL/ELT observability platform.

Rules:
1. Use ONLY the evidence JSON provided. Never invent pipelines, datasets, executions, alerts, or IDs.
2. Every factual claim must cite an ID that appears in evidence.allowed_citation_ids.
3. If evidence is insufficient, say so clearly in likely_cause and keep citations limited to what exists.
4. Prefer concrete failures (failed executions, monitor breaches, blast radius) over vague speculation.
5. Return ONLY valid JSON matching the schema — no markdown fences, no prose outside JSON.

Output schema:
{
  "summary": "1-2 sentence root cause",
  "likely_cause": "detailed cause grounded in evidence",
  "timeline": [{"at": "iso-or-unknown", "event": "what happened", "citation": "id-from-allowed"}],
  "blast_radius": ["dataset_or_asset_ids"],
  "recommended_actions": ["action1", "action2"],
  "citations": ["id1", "id2"]
}
"""


CHAT_SYSTEM = f"""You are a friendly, knowledgeable Incident RCA (Root Cause Analysis) assistant for an ETL observability platform.

Your audience: a data engineer or on-call responder who wants clear, practical help — NOT raw logs or internal IDs.

Context:
- You already have metadata evidence for ONE incident bound to this chat session.
- tenant_id and incident_key are set by the product — the user should NEVER need to provide them.

CONVERSATIONAL FREEDOM:
- Answer naturally like a helpful on-call colleague.
- You may explain tradeoffs, suggest investigation paths, and answer follow-ups in your own words.
- Adapt tone and depth to what the user asks — brief for simple questions, more detail when they want it.
- You are NOT locked into a rigid template; organize your reply however best helps the user.
- For opening messages, cover what happened, likely cause, blast radius, and sensible next steps — but in your own voice.

{GROUNDING_RULES}

{WRITING_RULES}
5. Name pipelines and datasets clearly once, then you may say "this pipeline" or "the root asset".
6. Prefer concrete failures (failed executions, open alerts, monitor breaches) over vague speculation.
7. For blast radius: say what downstream assets could be affected; if empty, say metadata shows no downstream impact flagged.
8. When evidence includes error_message on failed executions or alert messages, quote that error text clearly — that is the primary symptom the user needs.
9. If deep_link is present on a failed execution, tell the user they can open the native tool for full logs (mention the tool name, not raw URLs unless helpful).

Good example: "The orders pipeline failed twice this morning. Metadata points to a volume drop in the upstream raw table, and two downstream marts may be stale until the load recovers."

Bad example: "Execution exec:abc123 failed on pipeline:demo:orders. Citations: inc:demo:..."
"""


def _compact_evidence(evidence: dict[str, Any]) -> dict[str, Any]:
    return {
        "incident": evidence.get("incident"),
        "alerts": evidence.get("alerts"),
        "monitors": evidence.get("monitors"),
        "executions": evidence.get("executions"),
        "pipeline_dashboard": evidence.get("pipeline_dashboard"),
        "blast_radius": evidence.get("blast_radius"),
        "lineage_edges": evidence.get("lineage_edges"),
        "allowed_citation_ids": evidence.get("allowed_citation_ids"),
    }


def build_user_prompt(evidence: dict[str, Any]) -> str:
    compact = _compact_evidence(evidence)
    return (
        "Analyze this incident and produce grounded RCA JSON.\n\n"
        f"EVIDENCE:\n{json.dumps(compact, default=str, indent=2)}"
    )


def build_chat_system_prompt(
    evidence: dict[str, Any],
    tenant_id: str,
    incident_key: str,
    *,
    title: str | None = None,
    instruction: str | None = None,
) -> str:
    """System prompt for conversational RCA chat — evidence + reference + grounding rules."""
    compact = _compact_evidence(evidence)
    evidence_blob = json.dumps(compact, default=str)
    if len(evidence_blob) > 12000:
        evidence_blob = evidence_blob[:12000] + "\n...[truncated]"

    reference = build_evidence_reference(evidence, incident_key)
    allowed = evidence.get("allowed_citation_ids") or []
    allowed_blob = json.dumps(allowed, default=str)
    if len(allowed_blob) > 4000:
        allowed_blob = allowed_blob[:4000] + "...[truncated]"

    parts = [
        CHAT_SYSTEM,
        f"\n\nBound incident_key: {incident_key}",
        f"Bound tenant_id: {tenant_id}",
    ]
    if title:
        parts.append(f"Incident title: {title}")
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
