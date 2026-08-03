from __future__ import annotations

from typing import Any

from assistants.agentic.runtime import run_agentic_turn
from assistants.llm import OpenRouterLLM
from assistants.metadata_client import MetadataClient
from assistants.observability.prompt import build_chat_system_prompt, format_overview_fallback
from assistants.sessions import KIND_OBSERVABILITY, STORE, ChatMessage

OPENING_INSTRUCTION = (
    "This is the START of the conversation. Give a helpful reliability overview of the tenant: "
    "counts for pipelines/datasets/open incidents/monitors/alerts, highlight the worst open issues, "
    "and suggest what to look at first. Be conversational — not a rigid template."
)


def start_observability_chat(
    tenant_id: str,
    *,
    client: MetadataClient | None = None,
    llm: OpenRouterLLM | None = None,
    opening_question: str | None = None,
) -> dict[str, Any]:
    """Tenant-wide Observability chat (LangGraph tools over estate Metadata)."""
    meta = client or MetadataClient()
    model = llm or OpenRouterLLM()
    user_text = opening_question or (
        "Give me a reliability overview: pipelines, datasets, open incidents, monitors, and alerts. "
        "What should I look at first?"
    )
    bound: dict[str, Any] = {}
    opening_meta: dict[str, Any] = {"agentic": True}

    try:
        result = run_agentic_turn(
            client=meta,
            llm=model,
            tenant_id=tenant_id,
            question=user_text,
            kind="observability",
            bound=bound,
            build_system=lambda ev: build_chat_system_prompt(
                ev, tenant_id, instruction=OPENING_INSTRUCTION
            ),
            history=[],
            prior_evidence={},
        )
        opening = result["reply"]
        evidence = result.get("evidence") or {}
        opening_meta.update(
            {
                "source": "llm",
                "grounded": result.get("grounded"),
                "agent_mode": result.get("agent_mode"),
                "tool_trace": result.get("tool_trace"),
                "used_tools": result.get("used_tools"),
            }
        )
    except Exception:
        from assistants.agentic.tools import agentic_gather

        evidence = agentic_gather(meta, tenant_id, user_text, kind="observability", bound=bound)
        opening = format_overview_fallback(evidence)
        opening_meta.update({"source": "fallback_format", "grounded": True})

    session = STORE.create(
        tenant_id=tenant_id,
        kind=KIND_OBSERVABILITY,
        incident_title="Reliability overview",
        evidence=evidence,
    )
    session.messages.append(ChatMessage(role="user", content=user_text))
    session.messages.append(ChatMessage(role="assistant", content=opening, meta=opening_meta))
    STORE.save(session)
    return session.as_dict()


def continue_observability_chat(
    session_id: str,
    message: str,
    *,
    llm: OpenRouterLLM | None = None,
    client: MetadataClient | None = None,
) -> dict[str, Any]:
    session = STORE.get(session_id)
    if not session:
        raise KeyError(f"Unknown session_id: {session_id}")
    if session.kind != KIND_OBSERVABILITY:
        raise ValueError("Session is not an Observability chat")

    text = (message or "").strip()
    if not text:
        raise ValueError("message is required")

    session.messages.append(ChatMessage(role="user", content=text))
    prior = session.evidence or {}
    model = llm or OpenRouterLLM()
    meta = client or MetadataClient()

    history = [
        {"role": m.role, "content": m.content}
        for m in session.messages[:-1]
        if m.role in {"user", "assistant"}
    ][-12:]

    source = "llm"
    grounded = True
    tool_trace: list[Any] = []
    agent_mode = None
    try:
        result = run_agentic_turn(
            client=meta,
            llm=model,
            tenant_id=session.tenant_id,
            question=text,
            kind="observability",
            bound={},
            build_system=lambda ev: build_chat_system_prompt(ev, session.tenant_id),
            history=history,
            prior_evidence=prior,
        )
        reply = result["reply"]
        grounded = bool(result.get("grounded"))
        tool_trace = list(result.get("tool_trace") or [])
        agent_mode = result.get("agent_mode")
        session.evidence = result.get("evidence") or prior
    except Exception:
        reply = format_overview_fallback(prior)
        source = "fallback_format"
        grounded = True

    session.messages.append(
        ChatMessage(
            role="assistant",
            content=reply,
            meta={
                "source": source,
                "grounded": grounded,
                "agentic": source == "llm",
                "agent_mode": agent_mode,
                "tool_trace": tool_trace,
            },
        )
    )
    STORE.save(session)

    return {
        "session_id": session.session_id,
        "reply": reply,
        "tenant_id": session.tenant_id,
        "kind": session.kind,
        "grounded": grounded,
        "agentic": source == "llm",
        "agent_mode": agent_mode,
        "tool_trace": tool_trace,
        "messages": [m.as_dict() for m in session.messages],
        "model": model.model if source == "llm" else "fallback_format",
    }
