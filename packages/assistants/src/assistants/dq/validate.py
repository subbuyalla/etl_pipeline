from __future__ import annotations

from typing import Any

from assistants.dq.format import describe_check_issue
from assistants.rca.validate import parse_llm_json


def _human_check_detail(cr: dict[str, Any]) -> str:
    return describe_check_issue(cr).get("explanation", "")


def validate_dq_response(draft: dict[str, Any], evidence: dict[str, Any], model: str) -> dict[str, Any]:
    allowed = set(evidence.get("allowed_citation_ids") or [])
    dataset = evidence.get("dataset") or {}
    dataset_id = dataset.get("dataset_id")

    raw_citations = draft.get("citations") or []
    if not isinstance(raw_citations, list):
        raw_citations = []
    citations = [str(c) for c in raw_citations if str(c) in allowed]
    invented = [str(c) for c in raw_citations if str(c) not in allowed]

    issues_in = draft.get("quality_issues") or []
    quality_issues: list[dict[str, Any]] = []
    if isinstance(issues_in, list):
        for item in issues_in:
            if not isinstance(item, dict):
                continue
            cite = str(item.get("citation") or "")
            if cite and cite not in allowed:
                invented.append(cite)
                cite = ""
            elif cite:
                citations.append(cite)
            quality_issues.append(
                {
                    "monitor_type": str(item.get("monitor_type") or "custom"),
                    "status": str(item.get("status") or "unknown"),
                    "detail": str(item.get("detail") or ""),
                    "citation": cite or None,
                }
            )

    if not quality_issues:
        for cr in (evidence.get("check_results") or [])[:8]:
            status = (cr.get("status") or "").lower()
            if status not in {"failed", "anomalous"}:
                continue
            cite = f"check:{cr.get('id')}" if cr.get("id") is not None else str(cr.get("monitor_type") or "")
            if cite in allowed:
                citations.append(cite)
            quality_issues.append(
                {
                    "monitor_type": str(cr.get("monitor_type") or "custom"),
                    "status": str(cr.get("status") or "unknown"),
                    "detail": _human_check_detail(cr),
                    "citation": cite if cite in allowed else None,
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
    if not blast and evidence.get("blast_radius"):
        blast = list((evidence["blast_radius"].get("downstream") or [])[:20])
        for b in blast:
            citations.append(b)

    actions = draft.get("recommended_actions") or []
    if not isinstance(actions, list):
        actions = []
    actions = [str(a) for a in actions][:8]

    if dataset_id and dataset_id not in citations:
        citations.insert(0, str(dataset_id))

    seen: set[str] = set()
    uniq_citations: list[str] = []
    for c in citations:
        if c not in seen:
            seen.add(c)
            uniq_citations.append(c)

    summary = str(
        draft.get("summary")
        or (
            f"Quality review for {dataset_id}: "
            + (", ".join(f"{k}×{v}" for k, v in (evidence.get("breach_summary") or {}).items()) or "no recent breaches")
        )
    )
    lineage_impact = str(
        draft.get("lineage_impact")
        or (
            f"{len(blast)} downstream dataset(s) in blast radius"
            if blast
            else "No downstream lineage impact found in metadata."
        )
    )

    grounded = len(invented) == 0 and bool(uniq_citations)

    return {
        "dataset_id": dataset_id,
        "summary": summary,
        "quality_issues": quality_issues,
        "lineage_impact": lineage_impact,
        "blast_radius": blast[:50],
        "recommended_actions": actions,
        "citations": uniq_citations,
        "model": model,
        "grounded": grounded,
        "invented_ids_dropped": sorted(set(invented)),
    }


__all__ = ["validate_dq_response", "parse_llm_json"]
