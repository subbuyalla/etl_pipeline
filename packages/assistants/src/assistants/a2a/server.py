from __future__ import annotations

import uuid
from typing import Any

from assistants.a2a import cards
from assistants.agentic.runtime import run_agentic_turn
from assistants.dq.prompt import build_chat_system_prompt as build_dq_system
from assistants.llm import OpenRouterLLM
from assistants.metadata_client import MetadataClient
from assistants.observability.prompt import build_chat_system_prompt as build_obs_system
from assistants.rca.prompt import build_chat_system_prompt as build_rca_system


def _text_from_message(message: dict[str, Any]) -> str:
    parts = message.get("parts") or []
    texts: list[str] = []
    for p in parts:
        if isinstance(p, dict):
            if p.get("kind") == "text" or p.get("type") == "text" or "text" in p:
                texts.append(str(p.get("text") or ""))
    if texts:
        return "\n".join(t for t in texts if t).strip()
    return str(message.get("content") or message.get("text") or "").strip()


def _meta_from_message(message: dict[str, Any]) -> dict[str, Any]:
    meta = dict(message.get("metadata") or {}) if isinstance(message.get("metadata"), dict) else {}
    for key in ("tenant_id", "incident_key", "dataset_id", "pipeline_id", "skill", "agent"):
        if key in message and key not in meta:
            meta[key] = message[key]
    return meta


def handle_jsonrpc(
    body: dict[str, Any],
    *,
    client: MetadataClient | None = None,
    llm: OpenRouterLLM | None = None,
    base_url: str = "http://127.0.0.1:8001",
) -> dict[str, Any]:
    req_id = body.get("id")
    method = body.get("method") or ""
    params = body.get("params") or {}
    try:
        if method in {"message/send", "tasks/send", "SendMessage"}:
            result = _message_send(params, client=client, llm=llm)
            return {"jsonrpc": "2.0", "id": req_id, "result": result}
        if method in {"agents/list", "agent/list"}:
            return {"jsonrpc": "2.0", "id": req_id, "result": cards.catalog(base_url=base_url)}
        if method in {"agent/getCard", "agents/getCard"}:
            skill = (params.get("skill") or params.get("agent") or "orchestrate").lower()
            return {"jsonrpc": "2.0", "id": req_id, "result": _card_for_skill(skill, base_url=base_url)}
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": -32601, "message": f"Method not found: {method}"},
        }
    except Exception as exc:
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": -32000, "message": str(exc)[:400]},
        }


def _card_for_skill(skill: str, *, base_url: str) -> dict[str, Any]:
    if skill in {"incident_rca", "rca"}:
        return cards.incident_rca_card(base_url=base_url)
    if skill in {"dq_lineage", "dq"}:
        return cards.dq_lineage_card(base_url=base_url)
    if skill in {"observability", "overview", "reliability"}:
        return cards.observability_card(base_url=base_url)
    return cards.orchestrator_card(base_url=base_url)


def _message_send(
    params: dict[str, Any],
    *,
    client: MetadataClient | None,
    llm: OpenRouterLLM | None,
) -> dict[str, Any]:
    meta_client = client or MetadataClient()
    model = llm or OpenRouterLLM()
    message = params.get("message") or params
    if not isinstance(message, dict):
        message = {"parts": [{"kind": "text", "text": str(message)}]}
    text = _text_from_message(message)
    meta = _meta_from_message(message)
    for key in ("tenant_id", "incident_key", "dataset_id", "pipeline_id", "skill"):
        if key in params and key not in meta:
            meta[key] = params[key]

    tenant_id = str(meta.get("tenant_id") or "demo")
    skill = str(meta.get("skill") or meta.get("agent") or _route_skill(text, meta)).lower()
    task_id = str(params.get("id") or uuid.uuid4())

    if skill in {"orchestrate", "orchestrator"}:
        return _orchestrate(meta_client, model, tenant_id, text, meta, task_id)
    if skill in {"incident_rca", "rca"}:
        return _run_rca(meta_client, model, tenant_id, text, meta, task_id)
    if skill in {"dq_lineage", "dq"}:
        return _run_dq(meta_client, model, tenant_id, text, meta, task_id)
    if skill in {"observability", "overview", "reliability"}:
        return _run_observability(meta_client, model, tenant_id, text, meta, task_id)
    return _orchestrate(meta_client, model, tenant_id, text, meta, task_id)


def _route_skill(text: str, meta: dict[str, Any]) -> str:
    if meta.get("incident_key") and meta.get("dataset_id"):
        return "orchestrate"
    if meta.get("incident_key"):
        return "incident_rca"
    if meta.get("dataset_id"):
        return "dq_lineage"
    q = (text or "").lower()
    if any(
        w in q
        for w in (
            "overview",
            "reliability",
            "estate",
            "how healthy",
            "what should i look",
            "open incidents",
            "how many",
        )
    ):
        return "observability"
    if any(w in q for w in ("incident", "pipeline failed", "root cause", "execution")):
        return "incident_rca"
    if any(w in q for w in ("fresh", "volume", "schema", "lineage", "quality", "dataset")):
        return "dq_lineage"
    return "observability"


def _task_result(task_id: str, text: str, *, data: dict[str, Any] | None = None) -> dict[str, Any]:
    parts: list[dict[str, Any]] = [{"kind": "text", "text": text}]
    if data:
        parts.append({"kind": "data", "data": data})
    return {
        "id": task_id,
        "contextId": task_id,
        "status": {"state": "completed"},
        "artifacts": [{"artifactId": f"art-{task_id[:8]}", "parts": parts}],
        "history": [],
        "metadata": {},
    }


def _run_rca(
    client: MetadataClient,
    llm: OpenRouterLLM,
    tenant_id: str,
    text: str,
    meta: dict[str, Any],
    task_id: str,
) -> dict[str, Any]:
    incident_key = str(meta.get("incident_key") or "")
    if not incident_key:
        raise ValueError("incident_key is required for incident_rca skill")
    question = text or "Explain the root cause of this incident."
    bound = {
        "incident_key": incident_key,
        "pipeline_id": meta.get("pipeline_id"),
        "dataset_id": meta.get("dataset_id"),
    }
    result = run_agentic_turn(
        client=client,
        llm=llm,
        tenant_id=tenant_id,
        question=question,
        kind="incident_rca",
        bound=bound,
        build_system=lambda ev: build_rca_system(
            ev,
            tenant_id,
            incident_key,
            title=(ev.get("incident") or {}).get("title"),
        ),
        history=[],
        prior_evidence={},
    )
    return _task_result(
        task_id,
        result["reply"],
        data={
            "grounded": result.get("grounded"),
            "tool_trace": result.get("tool_trace"),
            "agent_mode": result.get("agent_mode"),
            "skill": "incident_rca",
            "a2a": True,
        },
    )


def _run_dq(
    client: MetadataClient,
    llm: OpenRouterLLM,
    tenant_id: str,
    text: str,
    meta: dict[str, Any],
    task_id: str,
) -> dict[str, Any]:
    dataset_id = str(meta.get("dataset_id") or "")
    if not dataset_id:
        raise ValueError("dataset_id is required for dq_lineage skill")
    question = text or "Explain data quality and lineage for this dataset."
    bound = {"dataset_id": dataset_id}
    result = run_agentic_turn(
        client=client,
        llm=llm,
        tenant_id=tenant_id,
        question=question,
        kind="dq_lineage",
        bound=bound,
        build_system=lambda ev: build_dq_system(
            ev, tenant_id, dataset_id, title=dataset_id
        ),
        history=[],
        prior_evidence={},
    )
    return _task_result(
        task_id,
        result["reply"],
        data={
            "grounded": result.get("grounded"),
            "tool_trace": result.get("tool_trace"),
            "agent_mode": result.get("agent_mode"),
            "skill": "dq_lineage",
            "a2a": True,
        },
    )


def _run_observability(
    client: MetadataClient,
    llm: OpenRouterLLM,
    tenant_id: str,
    text: str,
    meta: dict[str, Any],
    task_id: str,
) -> dict[str, Any]:
    question = text or (
        "Give me a reliability overview: pipelines, datasets, open incidents, monitors, and alerts."
    )
    result = run_agentic_turn(
        client=client,
        llm=llm,
        tenant_id=tenant_id,
        question=question,
        kind="observability",
        bound={},
        build_system=lambda ev: build_obs_system(ev, tenant_id),
        history=[],
        prior_evidence={},
    )
    return _task_result(
        task_id,
        result["reply"],
        data={
            "grounded": result.get("grounded"),
            "tool_trace": result.get("tool_trace"),
            "agent_mode": result.get("agent_mode"),
            "skill": "observability",
            "a2a": True,
        },
    )


def _orchestrate(
    client: MetadataClient,
    llm: OpenRouterLLM,
    tenant_id: str,
    text: str,
    meta: dict[str, Any],
    task_id: str,
) -> dict[str, Any]:
    """A2A: delegate to RCA and/or DQ agents (each runs LLM tool loop)."""
    parts: list[str] = []
    traces: list[dict[str, Any]] = []
    q = (text or "").lower()
    want_rca = bool(meta.get("incident_key")) or any(
        w in q for w in ("incident", "pipeline", "failed", "root cause", "execution")
    )
    want_dq = bool(meta.get("dataset_id")) or any(
        w in q for w in ("fresh", "volume", "schema", "lineage", "quality", "null", "dataset", "table")
    )
    if meta.get("incident_key") and not want_dq and not want_rca:
        want_rca = True
    if meta.get("dataset_id") and not want_rca and not want_dq:
        want_dq = True

    if want_rca and meta.get("incident_key"):
        rca = _run_rca(client, llm, tenant_id, text, meta, f"{task_id}-rca")
        parts.append("**Incident RCA agent:**\n" + _artifact_text(rca))
        traces.append({"agent": "incident_rca", "via": "a2a", "task": rca.get("id")})
    if want_dq and meta.get("dataset_id"):
        dq = _run_dq(client, llm, tenant_id, text, meta, f"{task_id}-dq")
        parts.append("**Data Quality + Lineage agent:**\n" + _artifact_text(dq))
        traces.append({"agent": "dq_lineage", "via": "a2a", "task": dq.get("id")})

    if not parts:
        return _task_result(
            task_id,
            "Orchestrator needs incident_key and/or dataset_id in message metadata to delegate via A2A.",
            data={"skill": "orchestrate", "a2a_delegations": []},
        )
    return _task_result(
        task_id,
        "\n\n".join(parts),
        data={"skill": "orchestrate", "a2a_delegations": traces},
    )


def _artifact_text(task: dict[str, Any]) -> str:
    for art in task.get("artifacts") or []:
        for part in art.get("parts") or []:
            if part.get("kind") == "text" or "text" in part:
                return str(part.get("text") or "")
    return ""
