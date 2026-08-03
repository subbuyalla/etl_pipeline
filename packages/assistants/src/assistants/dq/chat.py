from __future__ import annotations

from typing import Any

from assistants.agentic.runtime import run_agentic_turn
from assistants.dq.format import (
    describe_lineage,
    format_checks_answer,
    format_dq_opening,
)
from assistants.dq.prompt import build_chat_system_prompt
from assistants.llm import OpenRouterLLM
from assistants.metadata_client import MetadataClient
from assistants.sessions import KIND_DQ_LINEAGE, STORE, ChatMessage

OPENING_INSTRUCTION = (
    "This is the START of the conversation. Give a helpful opening analysis of "
    "data quality issues and lineage impact in plain language. Be conversational "
    "and practical — not a rigid template."
)


def _fallback_reply(message: str, evidence: dict[str, Any], dataset_id: str) -> str:
    q = (message or "").strip().lower()
    if any(p in q for p in ("which check", "what check", "checks failed", "what failed")):
        return format_checks_answer(evidence) or format_dq_opening(evidence, dataset_id)
    if any(p in q for p in ("blast radius", "downstream", "upstream", "lineage")):
        return describe_lineage(evidence, dataset_id)
    return format_dq_opening(evidence, dataset_id)


def start_dq_chat_session(
    tenant_id: str,
    dataset_id: str,
    *,
    client: MetadataClient | None = None,
    llm: OpenRouterLLM | None = None,
    opening_question: str | None = None,
) -> dict[str, Any]:
    meta = client or MetadataClient()
    model = llm or OpenRouterLLM()
    ds = (dataset_id or "").strip()
    if not ds:
        raise ValueError("dataset_id is required")

    user_text = opening_question or (
        "Explain the data quality issues for this dataset and the lineage blast radius."
    )
    bound = {"dataset_id": ds}
    opening_meta: dict[str, Any] = {"agentic": True}

    try:
        result = run_agentic_turn(
            client=meta,
            llm=model,
            tenant_id=tenant_id,
            question=user_text,
            kind="dq_lineage",
            bound=bound,
            build_system=lambda ev: build_chat_system_prompt(
                ev,
                tenant_id,
                ds,
                title=(ev.get("dataset") or {}).get("name") or ds,
                instruction=OPENING_INSTRUCTION,
            ),
            history=[],
            prior_evidence={},
        )
        opening = result["reply"]
        evidence = result.get("evidence") or {}
        title = (evidence.get("dataset") or {}).get("name") or ds
        opening_meta.update(
            {
                "source": "llm",
                "grounded": result.get("grounded"),
                "agent_mode": result.get("agent_mode"),
                "tool_trace": result.get("tool_trace"),
                "used_tools": result.get("used_tools"),
                "breach_summary": evidence.get("breach_summary"),
            }
        )
    except Exception:
        evidence = {}
        title = ds
        opening = format_dq_opening(evidence, ds)
        opening_meta.update({"source": "fallback_format", "grounded": True})

    session = STORE.create(
        tenant_id=tenant_id,
        kind=KIND_DQ_LINEAGE,
        dataset_id=ds,
        incident_title=title,
        evidence=evidence,
    )
    session.messages.append(ChatMessage(role="user", content=user_text))
    session.messages.append(ChatMessage(role="assistant", content=opening, meta=opening_meta))
    STORE.save(session)
    return session.as_dict()


def continue_dq_chat(
    session_id: str,
    message: str,
    *,
    llm: OpenRouterLLM | None = None,
    client: MetadataClient | None = None,
) -> dict[str, Any]:
    session = STORE.get(session_id)
    if not session:
        raise KeyError(f"Unknown session_id: {session_id}")
    if session.kind != KIND_DQ_LINEAGE:
        raise ValueError("Session is not a DQ+Lineage chat")

    text = (message or "").strip()
    if not text:
        raise ValueError("message is required")

    session.messages.append(ChatMessage(role="user", content=text))
    prior = session.evidence or {}
    model = llm or OpenRouterLLM()
    meta = client or MetadataClient()
    title = session.incident_title
    ds = session.dataset_id or ""
    bound = {"dataset_id": ds}

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
            kind="dq_lineage",
            bound=bound,
            build_system=lambda ev: build_chat_system_prompt(
                ev, session.tenant_id, ds, title=title
            ),
            history=history,
            prior_evidence=prior,
        )
        reply = result["reply"]
        grounded = bool(result.get("grounded"))
        tool_trace = list(result.get("tool_trace") or [])
        agent_mode = result.get("agent_mode")
        session.evidence = result.get("evidence") or prior
    except Exception:
        reply = _fallback_reply(text, prior, ds)
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
        "dataset_id": session.dataset_id,
        "tenant_id": session.tenant_id,
        "kind": session.kind,
        "grounded": grounded,
        "agentic": source == "llm",
        "agent_mode": agent_mode,
        "tool_trace": tool_trace,
        "messages": [m.as_dict() for m in session.messages],
        "model": model.model if source == "llm" else "fallback_format",
    }
