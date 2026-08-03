from __future__ import annotations

from typing import Any

from assistants.agentic.runtime import run_agentic_turn
from assistants.llm import OpenRouterLLM
from assistants.metadata_client import MetadataClient
from assistants.rca.format import (
    build_evidence_reference,
    format_blast_radius_answer,
    format_executions_answer,
    format_rca_opening,
)
from assistants.rca.graph import run_incident_rca
from assistants.rca.prompt import build_chat_system_prompt
from assistants.sessions import KIND_INCIDENT_RCA, STORE, ChatMessage

OPENING_INSTRUCTION = (
    "This is the START of the conversation. Give a helpful opening root-cause analysis "
    "in plain language. Be conversational and practical — not a rigid template."
)


def _fallback_reply(
    message: str,
    evidence: dict[str, Any],
    tenant_id: str,
    incident_key: str,
    title: str | None,
    *,
    client: MetadataClient | None = None,
    llm: OpenRouterLLM | None = None,
) -> str:
    q = (message or "").strip().lower()
    if any(p in q for p in ("blast radius", "downstream", "affected")):
        return format_blast_radius_answer(evidence)
    if any(p in q for p in ("execution", "pipeline run", "what failed", "failed run")):
        answer = format_executions_answer(evidence)
        if answer:
            return answer
    try:
        rca = run_incident_rca(tenant_id, incident_key, client=client, llm=llm)
        return format_rca_opening(rca, title, evidence=evidence)
    except Exception:
        return build_evidence_reference(evidence, incident_key)


def start_chat_session(
    tenant_id: str,
    incident_key: str,
    *,
    client: MetadataClient | None = None,
    llm: OpenRouterLLM | None = None,
    opening_question: str | None = None,
) -> dict[str, Any]:
    """Create a session via LLM-native tool calling (or planner fallback)."""
    meta = client or MetadataClient()
    model = llm or OpenRouterLLM()
    user_text = opening_question or "Explain the root cause of this incident."
    bound = {"incident_key": incident_key}

    opening_meta: dict[str, Any] = {"agentic": True}
    try:
        result = run_agentic_turn(
            client=meta,
            llm=model,
            tenant_id=tenant_id,
            question=user_text,
            kind="incident_rca",
            bound=bound,
            build_system=lambda ev: build_chat_system_prompt(
                ev,
                tenant_id,
                incident_key,
                title=(ev.get("incident") or {}).get("title"),
                instruction=OPENING_INSTRUCTION,
            ),
            history=[],
            prior_evidence={},
        )
        opening = result["reply"]
        evidence = result.get("evidence") or {}
        title = (evidence.get("incident") or {}).get("title")
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
        evidence = {}
        title = None
        try:
            rca = run_incident_rca(tenant_id, incident_key, client=meta, llm=model)
            opening = format_rca_opening(rca, title, evidence=evidence)
            opening_meta.update({"source": "fallback_format", "grounded": rca.get("grounded")})
        except Exception:
            opening = build_evidence_reference(evidence, incident_key)
            opening_meta.update({"source": "fallback_reference", "grounded": True})

    session = STORE.create(
        tenant_id=tenant_id,
        kind=KIND_INCIDENT_RCA,
        incident_key=incident_key,
        incident_title=title,
        evidence=evidence,
    )
    session.messages.append(ChatMessage(role="user", content=user_text))
    session.messages.append(ChatMessage(role="assistant", content=opening, meta=opening_meta))
    STORE.save(session)
    return session.as_dict()


def continue_chat(
    session_id: str,
    message: str,
    *,
    llm: OpenRouterLLM | None = None,
    client: MetadataClient | None = None,
) -> dict[str, Any]:
    session = STORE.get(session_id)
    if not session:
        raise KeyError(f"Unknown session_id: {session_id}")
    if session.kind != KIND_INCIDENT_RCA:
        raise ValueError("Session is not an Incident RCA chat")

    text = (message or "").strip()
    if not text:
        raise ValueError("message is required")

    session.messages.append(ChatMessage(role="user", content=text))
    model = llm or OpenRouterLLM()
    meta = client or MetadataClient()
    title = session.incident_title
    prior = session.evidence or {}
    bound = {
        "incident_key": session.incident_key,
        "pipeline_id": (prior.get("bound") or {}).get("pipeline_id")
        if isinstance(prior.get("bound"), dict)
        else None,
        "dataset_id": (prior.get("bound") or {}).get("dataset_id")
        if isinstance(prior.get("bound"), dict)
        else None,
    }
    inc = prior.get("incident") or {}
    if not bound.get("pipeline_id") and (inc.get("root_asset_type") or "").lower() == "pipeline":
        bound["pipeline_id"] = inc.get("root_asset_id")
    if not bound.get("dataset_id") and (inc.get("root_asset_type") or "").lower() == "dataset":
        bound["dataset_id"] = inc.get("root_asset_id")

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
            kind="incident_rca",
            bound=bound,
            build_system=lambda ev: build_chat_system_prompt(
                ev, session.tenant_id, session.incident_key, title=title
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
        reply = _fallback_reply(
            text,
            prior,
            session.tenant_id,
            session.incident_key,
            title,
            client=meta,
            llm=model,
        )
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
        "incident_key": session.incident_key,
        "tenant_id": session.tenant_id,
        "kind": session.kind,
        "grounded": grounded,
        "agentic": source == "llm",
        "agent_mode": agent_mode,
        "tool_trace": tool_trace,
        "messages": [m.as_dict() for m in session.messages],
        "model": model.model if source == "llm" else "fallback_format",
    }


def get_session(session_id: str):
    return STORE.get(session_id)
