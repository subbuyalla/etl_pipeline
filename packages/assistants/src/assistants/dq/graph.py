from __future__ import annotations

from typing import Any, TypedDict

from assistants.llm import OpenRouterLLM
from assistants.metadata_client import MetadataClient
from assistants.dq.gather import gather_dq_evidence
from assistants.dq.prompt import SYSTEM_PROMPT, build_user_prompt
from assistants.dq.validate import validate_dq_response
from assistants.rca.validate import parse_llm_json


class DqState(TypedDict, total=False):
    tenant_id: str
    dataset_id: str
    evidence: dict[str, Any] | None
    draft: dict[str, Any] | None
    result: dict[str, Any] | None


def run_dq_lineage(
    tenant_id: str,
    dataset_id: str,
    *,
    client: MetadataClient | None = None,
    llm: OpenRouterLLM | None = None,
) -> dict[str, Any]:
    """dq_lineage_graph: gather → generate → validate_citations."""
    meta = client or MetadataClient()
    model = llm or OpenRouterLLM()

    evidence = gather_dq_evidence(meta, tenant_id, dataset_id)
    raw = model.chat(SYSTEM_PROMPT, build_user_prompt(evidence))
    draft = parse_llm_json(raw)
    return validate_dq_response(draft, evidence, model.model)

