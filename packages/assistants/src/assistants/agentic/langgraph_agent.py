from __future__ import annotations

"""LangGraph ReAct agent over Metadata tools."""

import json
from typing import Any, Optional

from langchain.agents import create_agent
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import StructuredTool
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field, create_model

from assistants.agentic.tools import TOOLS, build_allowed_ids, run_tool_calls
from assistants.config import OPENROUTER_API_KEY, OPENROUTER_BASE_URL, OPENROUTER_MODEL
from assistants.metadata_client import MetadataClient
from assistants.shared.chat import fact_check_reply

MAX_TOOL_RESULT_CHARS = 6000

AGENT_SYSTEM = """You are an ETL observability agent with Metadata tools (LangGraph / LangChain create_agent).

Rules:
1. Call tools to gather facts before answering. Prefer several targeted tool calls over guessing.
2. Use ONLY tool results for factual claims. If tools lack data, say metadata doesn't show that yet.
3. Bound context IDs are given below — use them as tool arguments (do not invent other IDs).
4. Never expose internal keys like alert:, inc:, check:, monitor: or UUIDs to the user.
5. When you have enough evidence, stop calling tools and answer in plain English.
6. Be concise and practical.

Bound context (JSON):
{bound_json}
"""


def build_chat_model(
    *,
    api_key: str | None = None,
    model: str | None = None,
    base_url: str | None = None,
    temperature: float = 0.2,
) -> ChatOpenAI:
    key = (api_key if api_key is not None else OPENROUTER_API_KEY).strip()
    if not key:
        raise RuntimeError("OPENROUTER_API_KEY is not set")
    return ChatOpenAI(
        model=model or OPENROUTER_MODEL,
        api_key=key,
        base_url=(base_url or OPENROUTER_BASE_URL).rstrip("/"),
        temperature=temperature,
    )


def _arg_model(name: str, spec: dict[str, Any]) -> type[BaseModel]:
    """Build a pydantic model for a tool's arguments."""
    fields: dict[str, Any] = {}
    props = spec.get("properties") or {}
    required = set(spec.get("required") or [])
    for pname, pspec in props.items():
        base = int if (pspec or {}).get("type") == "integer" else str
        desc = (pspec or {}).get("description") or pname
        if pname in required:
            fields[pname] = (base, Field(description=desc))
        else:
            fields[pname] = (Optional[base], Field(default=None, description=desc))
    if not fields:
        return create_model(f"{name}_Args")
    return create_model(f"{name}_Args", **fields)


def build_metadata_tools(
    client: MetadataClient,
    tenant_id: str,
    bound: dict[str, Any],
    evidence: dict[str, Any],
) -> list[StructuredTool]:
    """LangChain tools that execute Metadata calls and accumulate evidence."""

    def make_tool(tool_name: str, spec: dict[str, Any]) -> StructuredTool:
        ArgsModel = _arg_model(tool_name, spec)

        def _run(**kwargs: Any) -> str:
            args = _fill_args_from_bound(tool_name, dict(kwargs), bound)
            frag = run_tool_calls(client, tenant_id, [(tool_name, args)])
            _accumulate_evidence(evidence, frag)
            return _tool_result_payload(tool_name, frag)

        return StructuredTool.from_function(
            func=_run,
            name=tool_name,
            description=str(spec.get("description") or tool_name),
            args_schema=ArgsModel,
        )

    return [make_tool(name, spec) for name, spec in TOOLS.items()]


def run_langgraph_turn(
    *,
    client: MetadataClient,
    tenant_id: str,
    question: str,
    kind: str,
    bound: dict[str, Any],
    history: list[dict[str, str]] | None = None,
    prior_evidence: dict[str, Any] | None = None,
    chat_model: Any | None = None,
    api_key: str | None = None,
    model_name: str | None = None,
    recursion_limit: int = 12,
) -> dict[str, Any]:
    """
    Run a LangGraph create_react_agent turn against Metadata tools.
    Returns reply, evidence, tool_trace, grounded flag.
    """
    _ = kind  # reserved for future skill-specific graphs
    evidence: dict[str, Any] = {
        "tool_trace": [],
        "agentic": True,
        "agent_mode": "langgraph",
        "bound": bound,
    }
    tools = build_metadata_tools(client, tenant_id, bound, evidence)
    llm = chat_model or build_chat_model(api_key=api_key, model=model_name)
    agent = create_agent(
        llm,
        tools,
        system_prompt=AGENT_SYSTEM.format(bound_json=json.dumps(bound, default=str)),
    )

    messages: list[Any] = []
    for h in (history or [])[-8:]:
        role = h.get("role")
        content = h.get("content") or ""
        if role == "user":
            messages.append(HumanMessage(content=content))
        elif role == "assistant":
            messages.append(AIMessage(content=content))
    messages.append(HumanMessage(content=question))

    result = agent.invoke(
        {"messages": messages},
        config={"recursion_limit": recursion_limit},
    )
    out_messages = result.get("messages") or []
    final_text = _last_ai_text(out_messages)

    merged = dict(prior_evidence or {})
    _accumulate_evidence(merged, evidence)
    merged["allowed_citation_ids"] = build_allowed_ids(merged)
    merged["agent_mode"] = "langgraph"
    merged["agentic"] = True
    merged["bound"] = bound

    reply, grounded, _ = fact_check_reply(final_text or "Metadata didn't return enough to answer.", merged)
    used_tools = any(t.get("ok") for t in (merged.get("tool_trace") or []))

    return {
        "reply": reply,
        "grounded": grounded,
        "evidence": merged,
        "tool_trace": merged.get("tool_trace") or [],
        "agentic": True,
        "agent_mode": "langgraph",
        "used_tools": used_tools,
    }


def _last_ai_text(messages: list[Any]) -> str:
    for msg in reversed(messages):
        if isinstance(msg, AIMessage):
            # Prefer final answer without pending tool_calls
            if getattr(msg, "tool_calls", None):
                continue
            content = msg.content
            if isinstance(content, list):
                parts = []
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        parts.append(str(block.get("text") or ""))
                    else:
                        parts.append(str(block))
                text = "".join(parts).strip()
            else:
                text = str(content or "").strip()
            if text:
                return text
        if isinstance(msg, ToolMessage):
            continue
    # Fallback: any AIMessage content
    for msg in reversed(messages):
        if isinstance(msg, AIMessage) and msg.content:
            return str(msg.content).strip()
    return ""


def _fill_args_from_bound(name: str, args: dict[str, Any], bound: dict[str, Any]) -> dict[str, Any]:
    out = {k: v for k, v in args.items() if v is not None}
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


def _accumulate_evidence(target: dict[str, Any], frag: dict[str, Any]) -> None:
    for key, value in frag.items():
        if key == "tool_trace":
            target["tool_trace"] = list(target.get("tool_trace") or []) + list(value or [])
            continue
        if value is None:
            continue
        if isinstance(value, list) and not value:
            continue
        if isinstance(value, dict) and not value:
            continue
        if key in {"agentic", "agent_mode", "bound"}:
            continue
        target[key] = value


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
