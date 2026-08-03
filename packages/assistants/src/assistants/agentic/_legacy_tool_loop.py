from __future__ import annotations

"""Manual OpenAI-style tool loop used by ScriptedToolLLM unit tests."""

import json
from typing import Any, Callable

from assistants.agentic.tools import (
    agentic_gather,
    build_allowed_ids,
    openai_tool_schemas,
    run_tool_calls,
)
from assistants.llm import parse_tool_arguments
from assistants.metadata_client import MetadataClient
from assistants.shared.chat import fact_check_reply, generate_grounded_reply

MAX_TOOL_STEPS = 6
MAX_TOOL_RESULT_CHARS = 6000

AGENT_SYSTEM = """You are an ETL observability agent with Metadata tools.

Bound context (JSON):
{bound_json}
"""


def run_scripted_tool_loop(
    *,
    client: MetadataClient,
    llm: Any,
    tenant_id: str,
    question: str,
    kind: str,
    bound: dict[str, Any],
    history: list[dict[str, str]],
    prior_evidence: dict[str, Any],
    build_system: Callable[[dict[str, Any]], str],
) -> dict[str, Any]:
    tools = openai_tool_schemas(kind=kind)
    evidence: dict[str, Any] = {
        "tool_trace": [],
        "agentic": True,
        "agent_mode": "llm_tools",
        "bound": bound,
    }
    messages: list[dict[str, Any]] = [
        {
            "role": "system",
            "content": AGENT_SYSTEM.format(bound_json=json.dumps(bound, default=str)),
        }
    ]
    for h in history[-8:]:
        if h.get("role") in {"user", "assistant"} and h.get("content"):
            messages.append({"role": h["role"], "content": h["content"]})
    messages.append({"role": "user", "content": question})

    final_text = ""
    used_tools = False
    content = ""

    for step in range(MAX_TOOL_STEPS):
        last = step == MAX_TOOL_STEPS - 1
        result = llm.chat_tools(
            messages,
            tools,
            tool_choice="none" if last else "auto",
            temperature=0.2,
        )
        tool_calls = result.get("tool_calls") or []
        content = (result.get("content") or "").strip()
        messages.append(result["message"])

        if not tool_calls:
            final_text = content
            break

        used_tools = True
        for tc in tool_calls:
            fn = tc.get("function") or {}
            name = str(fn.get("name") or "")
            args = parse_tool_arguments(fn.get("arguments"))
            args = _fill_args_from_bound(name, args, bound)
            frag = run_tool_calls(client, tenant_id, [(name, args)])
            evidence = _merge_evidence(evidence, frag)
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.get("id") or f"call_{step}_{name}",
                    "content": _tool_result_payload(name, frag),
                }
            )

    if not final_text.strip():
        evidence["allowed_citation_ids"] = build_allowed_ids(evidence)
        system = build_system(_merge_evidence(prior_evidence, evidence))
        final_text, grounded = generate_grounded_reply(
            model=llm,
            system=system,
            history=history,
            user_text=question,
            evidence=_merge_evidence(prior_evidence, evidence),
        )
        merged = _merge_evidence(prior_evidence, evidence)
        return {
            "reply": final_text,
            "grounded": grounded,
            "evidence": merged,
            "tool_trace": evidence.get("tool_trace") or [],
            "agentic": True,
            "agent_mode": "llm_tools_then_grounded",
            "used_tools": used_tools,
        }

    merged = _merge_evidence(prior_evidence, evidence)
    merged["allowed_citation_ids"] = build_allowed_ids(merged)
    reply, grounded, _ = fact_check_reply(final_text, merged)

    if not used_tools and not (
        merged.get("incident") or merged.get("dataset") or merged.get("check_results")
    ):
        seeded = agentic_gather(client, tenant_id, question, kind=kind, bound=bound)
        merged = _merge_evidence(merged, seeded)
        reply, grounded, _ = fact_check_reply(final_text, merged)

    return {
        "reply": reply,
        "grounded": grounded,
        "evidence": merged,
        "tool_trace": merged.get("tool_trace") or [],
        "agentic": True,
        "agent_mode": "llm_tools",
        "used_tools": used_tools,
    }


def _fill_args_from_bound(name: str, args: dict[str, Any], bound: dict[str, Any]) -> dict[str, Any]:
    out = dict(args)
    if name == "get_incident" and not out.get("incident_key") and bound.get("incident_key"):
        out["incident_key"] = bound["incident_key"]
    if name in {"get_dataset", "get_blast_radius", "list_lineage"} and not out.get("dataset_id"):
        if bound.get("dataset_id"):
            out["dataset_id"] = bound["dataset_id"]
    if name in {"list_executions", "get_pipeline_dashboard"} and not out.get("pipeline_id"):
        if bound.get("pipeline_id"):
            out["pipeline_id"] = bound["pipeline_id"]
        elif bound.get("asset_id"):
            out["pipeline_id"] = bound["asset_id"]
    if name in {"list_check_results", "list_monitors", "list_alerts", "list_metrics"} and not out.get(
        "asset_id"
    ):
        out["asset_id"] = bound.get("dataset_id") or bound.get("pipeline_id") or bound.get("asset_id")
    return out


def _tool_result_payload(name: str, frag: dict[str, Any]) -> str:
    key_map = {
        "get_incident": "incident",
        "list_executions": "executions",
        "get_pipeline_dashboard": "pipeline_dashboard",
        "list_check_results": "check_results",
        "list_monitors": "monitors",
        "list_alerts": "alerts",
        "get_blast_radius": "blast_radius",
        "list_lineage": "lineage_edges",
        "get_dataset": "dataset",
        "list_metrics": "metrics",
        "list_incidents": "incidents",
        "list_pipelines": "pipelines",
        "list_datasets": "datasets",
        "get_reliability_overview": "reliability_overview",
    }
    key = key_map.get(name)
    data: Any = frag.get(key) if key else frag
    if data is None:
        trace = frag.get("tool_trace") or []
        data = {"ok": False, "trace": trace[-1] if trace else {}}
    text = json.dumps(data, default=str)
    if len(text) > MAX_TOOL_RESULT_CHARS:
        text = text[: MAX_TOOL_RESULT_CHARS - 20] + '..."truncated}'
    return text


def _merge_evidence(prior: dict[str, Any], fresh: dict[str, Any]) -> dict[str, Any]:
    out = dict(prior)
    for key, value in fresh.items():
        if key == "tool_trace":
            out["tool_trace"] = list(prior.get("tool_trace") or []) + list(value or [])
            continue
        if key == "allowed_citation_ids":
            merged = set(prior.get("allowed_citation_ids") or []) | set(value or [])
            out["allowed_citation_ids"] = sorted(merged)
            continue
        if value is None:
            continue
        if isinstance(value, list) and not value:
            continue
        if isinstance(value, dict) and not value:
            continue
        out[key] = value
    if "allowed_citation_ids" not in out:
        out["allowed_citation_ids"] = build_allowed_ids(out)
    return out
