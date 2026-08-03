from __future__ import annotations

"""Agentic turn: LangGraph ReAct (primary) + deterministic planner fallback."""

from typing import Any, Callable

from assistants.agentic.tools import agentic_gather, build_allowed_ids
from assistants.llm import OpenRouterLLM
from assistants.metadata_client import MetadataClient
from assistants.shared.chat import generate_grounded_reply


def run_agentic_turn(
    *,
    client: MetadataClient,
    llm: OpenRouterLLM,
    tenant_id: str,
    question: str,
    kind: str,
    bound: dict[str, Any],
    build_system: Callable[[dict[str, Any]], str],
    history: list[dict[str, str]] | None = None,
    prior_evidence: dict[str, Any] | None = None,
    chat_model: Any | None = None,
) -> dict[str, Any]:
    """
    Agentic turn order:
      1) LangGraph create_react_agent (LLM chooses Metadata tools)
      2) Deterministic question→tool planner + grounded LLM answer (tests / fallback)
    """
    bound = _enrich_bound(client, tenant_id, kind, dict(bound))

    use_langgraph = chat_model is not None or (
        getattr(llm, "configured", False) and not getattr(llm, "force_deterministic", False)
    )
    # Unit fakes without OpenRouter key / without LangChain model → planner path
    if hasattr(llm, "chat_tools") and not getattr(llm, "api_key", None) and chat_model is None:
        # ScriptedToolLLM path for non-LangGraph unit tests
        if type(llm).__name__ in {"ScriptedToolLLM"}:
            from assistants.agentic._legacy_tool_loop import run_scripted_tool_loop

            return run_scripted_tool_loop(
                client=client,
                llm=llm,
                tenant_id=tenant_id,
                question=question,
                kind=kind,
                bound=bound,
                history=history or [],
                prior_evidence=prior_evidence or {},
                build_system=build_system,
            )

    if use_langgraph:
        try:
            from assistants.agentic.langgraph_agent import run_langgraph_turn

            return run_langgraph_turn(
                client=client,
                tenant_id=tenant_id,
                question=question,
                kind=kind,
                bound=bound,
                history=history or [],
                prior_evidence=prior_evidence or {},
                chat_model=chat_model,
                api_key=getattr(llm, "api_key", None),
                model_name=getattr(llm, "model", None),
            )
        except Exception:
            pass

    return _deterministic_turn(
        client=client,
        llm=llm,
        tenant_id=tenant_id,
        question=question,
        kind=kind,
        bound=bound,
        history=history or [],
        prior_evidence=prior_evidence or {},
        build_system=build_system,
    )


def _enrich_bound(
    client: MetadataClient, tenant_id: str, kind: str, bound: dict[str, Any]
) -> dict[str, Any]:
    if kind == "incident_rca" and bound.get("incident_key") and not bound.get("pipeline_id"):
        try:
            inc = client.get_incident(tenant_id, str(bound["incident_key"]))
            bound["asset_id"] = inc.get("root_asset_id")
            if (inc.get("root_asset_type") or "").lower() == "pipeline":
                bound["pipeline_id"] = inc.get("root_asset_id")
            if (inc.get("root_asset_type") or "").lower() == "dataset":
                bound["dataset_id"] = inc.get("root_asset_id")
        except Exception:
            pass
    return bound


def _deterministic_turn(
    *,
    client: MetadataClient,
    llm: OpenRouterLLM,
    tenant_id: str,
    question: str,
    kind: str,
    bound: dict[str, Any],
    history: list[dict[str, str]],
    prior_evidence: dict[str, Any],
    build_system: Callable[[dict[str, Any]], str],
) -> dict[str, Any]:
    fresh = agentic_gather(client, tenant_id, question, kind=kind, bound=bound)
    fresh["agent_mode"] = "deterministic_planner"
    evidence = _merge_evidence(prior_evidence, fresh)
    system = build_system(evidence)
    reply, grounded = generate_grounded_reply(
        model=llm,
        system=system,
        history=history,
        user_text=question,
        evidence=evidence,
    )
    return {
        "reply": reply,
        "grounded": grounded,
        "evidence": evidence,
        "tool_trace": fresh.get("tool_trace") or [],
        "agentic": True,
        "agent_mode": "deterministic_planner",
        "used_tools": True,
    }


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
