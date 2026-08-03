from __future__ import annotations

from typing import Any, TypedDict

from assistants.llm import OpenRouterLLM
from assistants.metadata_client import MetadataClient
from assistants.rca.gather import gather_evidence
from assistants.rca.prompt import SYSTEM_PROMPT, build_user_prompt
from assistants.rca.validate import parse_llm_json, validate_citations


class RcaState(TypedDict, total=False):
    tenant_id: str
    incident_key: str
    evidence: dict[str, Any] | None
    draft: dict[str, Any] | None
    result: dict[str, Any] | None
    errors: list[str]


def run_incident_rca(
    tenant_id: str,
    incident_key: str,
    *,
    client: MetadataClient | None = None,
    llm: OpenRouterLLM | None = None,
) -> dict[str, Any]:
    """incident_rca_graph: gather → generate → validate_citations."""
    state: RcaState = {
        "tenant_id": tenant_id,
        "incident_key": incident_key,
        "evidence": None,
        "draft": None,
        "result": None,
        "errors": [],
    }
    meta = client or MetadataClient()
    model = llm or OpenRouterLLM()

    # Node 1: gather
    evidence = gather_evidence(meta, tenant_id, incident_key)
    state["evidence"] = evidence

    # Node 2: generate
    raw = model.chat(SYSTEM_PROMPT, build_user_prompt(evidence))
    draft = parse_llm_json(raw)
    state["draft"] = draft

    # Node 3: validate
    result = validate_citations(draft, evidence, model.model)
    state["result"] = result
    return result
