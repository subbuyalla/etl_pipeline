from __future__ import annotations

from typing import Any, Optional

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from assistants.a2a import cards as a2a_cards
from assistants.a2a.server import handle_jsonrpc
from assistants.config import ASSISTANTS_HOST, ASSISTANTS_PORT, OPENROUTER_API_KEY, OPENROUTER_MODEL
from assistants.dq.chat import continue_dq_chat, start_dq_chat_session
from assistants.dq.graph import run_dq_lineage
from assistants.llm import OpenRouterLLM
from assistants.metadata_client import MetadataClient
from assistants.observability.chat import continue_observability_chat, start_observability_chat
from assistants.rca.chat import continue_chat, get_session, start_chat_session
from assistants.rca.graph import run_incident_rca
from assistants.sessions import STORE

app = FastAPI(
    title="Assistants API",
    version="0.5.0",
    description=(
        "Agentic conversational assistants grounded in Metadata tool calls (LangGraph). "
        "Incident RCA: /v1/chat/sessions. "
        "Data Quality + Lineage: /v1/dq/chat/sessions. "
        "Observability: /v1/observability/chat/sessions. "
        "A2A: /.well-known/agent.json + POST /a2a/jsonrpc."
    ),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class RcaIncidentIn(BaseModel):
    tenant_id: str = Field(..., min_length=1)
    incident_key: str = Field(..., min_length=1)


class ChatSessionIn(BaseModel):
    tenant_id: str = Field(..., min_length=1, description="Taken from the UI tenant selector")
    incident_key: str = Field(..., min_length=1, description="Taken from the selected incident row")
    opening_question: Optional[str] = Field(
        default=None,
        description="Optional first user question; defaults to a root-cause request",
    )


class DqChatSessionIn(BaseModel):
    tenant_id: str = Field(..., min_length=1, description="Taken from the UI tenant selector")
    dataset_id: str = Field(..., min_length=1, description="Taken from monitors / lineage / datasets")
    opening_question: Optional[str] = Field(
        default=None,
        description="Optional first user question; defaults to a quality + lineage request",
    )


class DqDatasetIn(BaseModel):
    tenant_id: str = Field(..., min_length=1)
    dataset_id: str = Field(..., min_length=1)


class ObservabilityChatSessionIn(BaseModel):
    tenant_id: str = Field(..., min_length=1, description="Taken from the UI tenant selector")
    opening_question: Optional[str] = Field(
        default=None,
        description="Optional first user question; defaults to a reliability overview request",
    )


class ChatMessageIn(BaseModel):
    message: str = Field(..., min_length=1, description="Natural language follow-up; no IDs needed")


def _require_openrouter() -> None:
    if not OPENROUTER_API_KEY:
        raise HTTPException(
            status_code=503,
            detail="OPENROUTER_API_KEY is not set. Add it to the repo .env and restart assistants.",
        )


def _map_meta_errors(exc: Exception, client: MetadataClient) -> None:
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        detail = exc.response.text[:300]
        if status == 404:
            raise HTTPException(status_code=404, detail=detail or "Not found") from exc
        raise HTTPException(status_code=502, detail=f"Metadata API error {status}: {detail}") from exc
    if isinstance(exc, httpx.RequestError):
        raise HTTPException(
            status_code=502,
            detail=f"Cannot reach Metadata API at {client.base_url}: {exc}",
        ) from exc


def _a2a_base_url() -> str:
    return f"http://{ASSISTANTS_HOST}:{ASSISTANTS_PORT}".replace("0.0.0.0", "127.0.0.1")


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "layer": "assistants",
        "openrouter_configured": bool(OPENROUTER_API_KEY),
        "model": OPENROUTER_MODEL,
        "active_sessions": STORE.count(),
        "assistants": ["incident_rca", "dq_lineage", "observability", "orchestrator"],
        "mode": "langgraph",
        "framework": "langgraph",
        "a2a": {
            "protocol": a2a_cards.PROTOCOL_VERSION,
            "agent_card": "/.well-known/agent.json",
            "jsonrpc": "/a2a/jsonrpc",
            "agents": ["incident_rca", "dq_lineage", "observability", "orchestrator"],
        },
    }


@app.get("/.well-known/agent.json", tags=["a2a"])
def agent_card_catalog() -> dict[str, Any]:
    """A2A Agent Card catalog (RCA, DQ, Orchestrator)."""
    return a2a_cards.catalog(base_url=_a2a_base_url())


@app.get("/.well-known/agent/{skill}.json", tags=["a2a"])
def agent_card(skill: str) -> dict[str, Any]:
    base = _a2a_base_url()
    key = (skill or "").lower()
    if key in {"incident_rca", "rca"}:
        return a2a_cards.incident_rca_card(base_url=base)
    if key in {"dq_lineage", "dq"}:
        return a2a_cards.dq_lineage_card(base_url=base)
    if key in {"observability", "overview", "reliability"}:
        return a2a_cards.observability_card(base_url=base)
    if key in {"orchestrator", "orchestrate"}:
        return a2a_cards.orchestrator_card(base_url=base)
    raise HTTPException(status_code=404, detail=f"Unknown agent skill: {skill}")


@app.post("/a2a/jsonrpc", tags=["a2a"])
def a2a_jsonrpc(body: dict[str, Any]) -> dict[str, Any]:
    """
    A2A JSON-RPC endpoint.
    Methods: message/send, agents/list, agent/getCard.
    Pass metadata.skill = incident_rca | dq_lineage | orchestrate plus incident_key / dataset_id.
    """
    _require_openrouter()
    client = MetadataClient()
    llm = OpenRouterLLM()
    return handle_jsonrpc(body, client=client, llm=llm, base_url=_a2a_base_url())


@app.post("/v1/chat/sessions", tags=["chat"])
def create_chat_session(body: ChatSessionIn) -> dict[str, Any]:
    """Start a conversation bound to one incident. Returns opening RCA + session_id."""
    _require_openrouter()
    client = MetadataClient()
    llm = OpenRouterLLM()
    try:
        return start_chat_session(
            body.tenant_id,
            body.incident_key,
            client=client,
            llm=llm,
            opening_question=body.opening_question,
        )
    except Exception as exc:
        _map_meta_errors(exc, client)
        if isinstance(exc, ValueError):
            raise HTTPException(status_code=502, detail=str(exc)[:400]) from exc
        raise HTTPException(status_code=500, detail=str(exc)[:400]) from exc


@app.get("/v1/chat/sessions/{session_id}", tags=["chat"])
def read_chat_session(session_id: str) -> dict[str, Any]:
    session = get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found (short-term memory may have restarted)")
    return session.as_dict()


@app.post("/v1/chat/sessions/{session_id}/messages", tags=["chat"])
def post_chat_message(session_id: str, body: ChatMessageIn) -> dict[str, Any]:
    """Send a follow-up. Only `message` is required — incident/tenant already in session memory."""
    _require_openrouter()
    llm = OpenRouterLLM()
    try:
        return continue_chat(session_id, body.message, llm=llm)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)[:400]) from exc


@app.post("/v1/dq/chat/sessions", tags=["dq-lineage"])
def create_dq_chat_session(body: DqChatSessionIn) -> dict[str, Any]:
    """Start DQ + Lineage chat bound to one dataset."""
    _require_openrouter()
    client = MetadataClient()
    llm = OpenRouterLLM()
    try:
        return start_dq_chat_session(
            body.tenant_id,
            body.dataset_id,
            client=client,
            llm=llm,
            opening_question=body.opening_question,
        )
    except Exception as exc:
        _map_meta_errors(exc, client)
        if isinstance(exc, ValueError):
            raise HTTPException(status_code=400, detail=str(exc)[:400]) from exc
        raise HTTPException(status_code=500, detail=str(exc)[:400]) from exc


@app.get("/v1/dq/chat/sessions/{session_id}", tags=["dq-lineage"])
def read_dq_chat_session(session_id: str) -> dict[str, Any]:
    session = get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found (short-term memory may have restarted)")
    return session.as_dict()


@app.post("/v1/dq/chat/sessions/{session_id}/messages", tags=["dq-lineage"])
def post_dq_chat_message(session_id: str, body: ChatMessageIn) -> dict[str, Any]:
    """Send a DQ/lineage follow-up. Only `message` is required."""
    _require_openrouter()
    llm = OpenRouterLLM()
    try:
        return continue_dq_chat(session_id, body.message, llm=llm)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)[:400]) from exc


@app.post("/v1/observability/chat/sessions", tags=["observability"])
def create_observability_chat_session(body: ObservabilityChatSessionIn) -> dict[str, Any]:
    """Start tenant-wide Observability chat (Reliability overview)."""
    _require_openrouter()
    client = MetadataClient()
    llm = OpenRouterLLM()
    try:
        return start_observability_chat(
            body.tenant_id,
            client=client,
            llm=llm,
            opening_question=body.opening_question,
        )
    except Exception as exc:
        _map_meta_errors(exc, client)
        if isinstance(exc, ValueError):
            raise HTTPException(status_code=400, detail=str(exc)[:400]) from exc
        raise HTTPException(status_code=500, detail=str(exc)[:400]) from exc


@app.get("/v1/observability/chat/sessions/{session_id}", tags=["observability"])
def read_observability_chat_session(session_id: str) -> dict[str, Any]:
    session = get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found (short-term memory may have restarted)")
    return session.as_dict()


@app.post("/v1/observability/chat/sessions/{session_id}/messages", tags=["observability"])
def post_observability_chat_message(session_id: str, body: ChatMessageIn) -> dict[str, Any]:
    """Send an Observability follow-up. Only `message` is required."""
    _require_openrouter()
    llm = OpenRouterLLM()
    try:
        return continue_observability_chat(session_id, body.message, llm=llm)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)[:400]) from exc


@app.post("/v1/dq/dataset", tags=["dq-lineage", "one-shot"])
def dq_dataset(body: DqDatasetIn) -> dict[str, Any]:
    """One-shot DQ + Lineage analysis (no memory). Prefer /v1/dq/chat/sessions."""
    _require_openrouter()
    client = MetadataClient()
    llm = OpenRouterLLM()
    try:
        return run_dq_lineage(body.tenant_id, body.dataset_id, client=client, llm=llm)
    except Exception as exc:
        _map_meta_errors(exc, client)
        if isinstance(exc, ValueError):
            raise HTTPException(status_code=502, detail=f"LLM response parse error: {exc}") from exc
        raise HTTPException(status_code=500, detail=str(exc)[:400]) from exc


@app.post("/v1/rca/incident", tags=["one-shot"], deprecated=True)
def rca_incident(body: RcaIncidentIn) -> dict[str, Any]:
    """One-shot RCA (no memory). Prefer conversational /v1/chat/sessions."""
    _require_openrouter()
    client = MetadataClient()
    llm = OpenRouterLLM()
    try:
        return run_incident_rca(body.tenant_id, body.incident_key, client=client, llm=llm)
    except Exception as exc:
        _map_meta_errors(exc, client)
        if isinstance(exc, ValueError):
            raise HTTPException(status_code=502, detail=f"LLM response parse error: {exc}") from exc
        raise HTTPException(status_code=500, detail=str(exc)[:400]) from exc


def main() -> None:
    import uvicorn

    uvicorn.run("assistants.api:app", host=ASSISTANTS_HOST, port=ASSISTANTS_PORT, reload=True)


if __name__ == "__main__":
    main()

