from __future__ import annotations

import re
from typing import Any

from assistants.llm import OpenRouterLLM

# Patterns to strip if the model leaks internal IDs or citation footers
_ID_LEAK_RE = re.compile(
    r"\b(?:alert|inc|check|monitor):[A-Za-z0-9_:\-\.]+|"
    r"_?Citations:.*$|"
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b",
    re.IGNORECASE | re.MULTILINE,
)

# Likely asset / pipeline identifiers that must appear in evidence if claimed
_ASSET_LIKE_RE = re.compile(
    r"\b([A-Z][A-Z0-9_]+\.[A-Z][A-Z0-9_]+\.[A-Z][A-Z0-9_]+|"
    r"[a-z][a-z0-9_]*(?:_etl|_sync|_load|_ingest)?)\b"
)

GROUNDING_RULES = """STRICT GROUNDING (never break these):
1. Use ONLY facts from the EVIDENCE JSON and REFERENCE SUMMARY below.
2. Never invent datasets, pipelines, monitors, check results, lineage edges, incidents, executions, or metrics not in evidence.
3. If something isn't in evidence, say clearly: "metadata doesn't show that yet."
4. Internally, every factual claim should map to an ID in allowed_citation_ids — but NEVER expose those IDs to the user."""

WRITING_RULES = """WRITING RULES:
1. Plain English. Short paragraphs and simple bullet points when helpful.
2. NEVER show internal IDs: no alert:, inc:, check:, monitor keys, UUIDs, or "Citations:" footers.
3. NEVER say things like "null_rate=None" or "metric=50 baseline=None" — translate to human language.
4. Do NOT use JSON in replies unless the user explicitly asks for JSON."""


def clean_reply(text: str) -> str:
    """Remove leaked internal IDs and citation footers from model output."""
    cleaned = _ID_LEAK_RE.sub("", text)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def _collect_allowed_names(evidence: dict[str, Any] | None) -> set[str]:
    """Build a set of known asset/pipeline names from evidence for soft fact-check."""
    if not evidence:
        return set()
    names: set[str] = set()
    allowed = evidence.get("allowed_citation_ids") or []
    for item in allowed:
        text = str(item).strip()
        if text:
            names.add(text)
            # Also allow short table names from FQN
            if "." in text and not text.startswith(("alert:", "inc:", "check:", "monitor:")):
                names.add(text.split(".")[-1])

    for key in ("incident", "dataset"):
        obj = evidence.get(key) or {}
        for field in ("root_asset_id", "dataset_id", "title", "pipeline_id"):
            val = obj.get(field)
            if val:
                names.add(str(val))
                if "." in str(val):
                    names.add(str(val).split(".")[-1])

    for exe in evidence.get("executions") or []:
        for field in ("pipeline_id", "task_id", "execution_id", "error_message"):
            val = exe.get(field)
            if val:
                names.add(str(val))

    for edge in evidence.get("lineage_edges") or []:
        for field in ("upstream_dataset_id", "downstream_dataset_id", "transform"):
            val = edge.get(field)
            if val:
                names.add(str(val))
                if "." in str(val):
                    names.add(str(val).split(".")[-1])

    dash = evidence.get("pipeline_dashboard") or {}
    for d in dash.get("related_datasets") or []:
        names.add(str(d))
        if "." in str(d):
            names.add(str(d).split(".")[-1])
    for io in dash.get("pipeline_io") or evidence.get("pipeline_io") or []:
        for field in ("upstream_dataset_id", "downstream_dataset_id", "pipeline_id"):
            val = io.get(field) if isinstance(io, dict) else None
            if val:
                names.add(str(val))

    blast = evidence.get("blast_radius") or {}
    for d in blast.get("downstream") or []:
        names.add(str(d))

    # Common words that look like assets but aren't
    stop = {
        "metadata", "pipeline", "pipelines", "dataset", "datasets", "table", "tables",
        "incident", "alert", "volume", "freshness", "schema", "distribution", "error",
        "failed", "success", "running", "unknown", "assistant", "summary", "timeline",
    }
    return {n for n in names if n and n.lower() not in stop}


def fact_check_reply(text: str, evidence: dict[str, Any] | None) -> tuple[str, bool, list[str]]:
    """
    Soft fact-check: flag invented FQNs / pipeline-like tokens not present in evidence.
    Returns (possibly annotated reply, grounded, invented_tokens).
    """
    cleaned = clean_reply(text)
    allowed = _collect_allowed_names(evidence)
    if not allowed:
        # No evidence names — treat as grounded only if reply admits missing metadata
        thin = "metadata doesn't show" in cleaned.lower() or "doesn't show that" in cleaned.lower()
        return cleaned, thin or True, []

    invented: list[str] = []
    for match in _ASSET_LIKE_RE.finditer(cleaned):
        token = match.group(1)
        # Skip lowercase common verbs/nouns already filtered; require either FQN or known-looking id
        if "." not in token and "_" not in token:
            continue
        if token in allowed:
            continue
        # Case-insensitive match against allowed
        if any(token.lower() == a.lower() for a in allowed):
            continue
        # Allow short tokens that are substrings of allowed FQNs
        if any(token.lower() in a.lower() for a in allowed):
            continue
        invented.append(token)

    # Deduplicate preserving order
    seen: set[str] = set()
    uniq = []
    for t in invented:
        if t not in seen:
            seen.add(t)
            uniq.append(t)

    grounded = len(uniq) == 0
    if not grounded:
        note = (
            "\n\n_Note: metadata doesn't confirm these names from evidence: "
            + ", ".join(uniq[:5])
            + ". Treat them as unverified._"
        )
        cleaned = cleaned + note
    return cleaned, grounded, uniq


def generate_grounded_reply(
    *,
    model: OpenRouterLLM,
    system: str,
    history: list[dict[str, str]],
    user_text: str,
    evidence: dict[str, Any] | None = None,
) -> tuple[str, bool]:
    """Call the LLM and return (user-safe reply, grounded flag)."""
    raw = model.chat_messages(system, history + [{"role": "user", "content": user_text}])
    reply, grounded, _invented = fact_check_reply(raw, evidence)
    return reply, grounded
