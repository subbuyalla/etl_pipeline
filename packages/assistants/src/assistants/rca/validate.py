from __future__ import annotations

import json
import re
from typing import Any


def _extract_json(text: str) -> dict[str, Any]:
    text = (text or "").strip()
    if not text:
        raise ValueError("Empty LLM response")
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{[\s\S]*\}", text)
    if not match:
        raise ValueError("No JSON object in LLM response")
    data = json.loads(match.group(0))
    if not isinstance(data, dict):
        raise ValueError("LLM JSON was not an object")
    return data


def validate_citations(draft: dict[str, Any], evidence: dict[str, Any], model: str) -> dict[str, Any]:
    allowed = set(evidence.get("allowed_citation_ids") or [])
    incident = evidence.get("incident") or {}
    incident_key = incident.get("incident_key")

    raw_citations = draft.get("citations") or []
    if not isinstance(raw_citations, list):
        raw_citations = []
    citations = [str(c) for c in raw_citations if str(c) in allowed]
    invented = [str(c) for c in raw_citations if str(c) not in allowed]

    timeline_in = draft.get("timeline") or []
    timeline: list[dict[str, Any]] = []
    if isinstance(timeline_in, list):
        for item in timeline_in:
            if not isinstance(item, dict):
                continue
            cite = str(item.get("citation") or "")
            if cite and cite not in allowed:
                invented.append(cite)
                cite = ""
            elif cite:
                citations.append(cite)
            timeline.append(
                {
                    "at": item.get("at") or "unknown",
                    "event": item.get("event") or "",
                    "citation": cite or None,
                }
            )

    blast_in = draft.get("blast_radius") or []
    blast: list[str] = []
    if isinstance(blast_in, list):
        for b in blast_in:
            s = str(b)
            if s in allowed:
                blast.append(s)
            else:
                invented.append(s)
    # Fall back to metadata blast if LLM missed it
    if not blast and evidence.get("blast_radius"):
        blast = list((evidence["blast_radius"].get("downstream") or [])[:20])
        for b in blast:
            citations.append(b)

    actions = draft.get("recommended_actions") or []
    if not isinstance(actions, list):
        actions = []
    actions = [str(a) for a in actions][:8]

    if incident_key and incident_key not in citations:
        citations.insert(0, str(incident_key))

    # Deduplicate citations preserving order
    seen: set[str] = set()
    uniq_citations: list[str] = []
    for c in citations:
        if c not in seen:
            seen.add(c)
            uniq_citations.append(c)

    grounded = len(invented) == 0 and bool(uniq_citations)

    return {
        "incident_key": incident_key,
        "summary": str(draft.get("summary") or incident.get("summary") or "Insufficient evidence"),
        "likely_cause": str(draft.get("likely_cause") or "Could not determine root cause from available metadata."),
        "timeline": timeline[:20],
        "blast_radius": blast[:50],
        "recommended_actions": actions,
        "citations": uniq_citations,
        "model": model,
        "grounded": grounded,
        "invented_ids_dropped": sorted(set(invented)),
    }


def parse_llm_json(text: str) -> dict[str, Any]:
    return _extract_json(text)
