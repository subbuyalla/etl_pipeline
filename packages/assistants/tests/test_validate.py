from __future__ import annotations

from assistants.rca.validate import parse_llm_json, validate_citations


def test_parse_llm_json_fenced():
    raw = '```json\n{"summary": "x", "citations": ["a"]}\n```'
    data = parse_llm_json(raw)
    assert data["summary"] == "x"


def test_validate_drops_invented_ids():
    evidence = {
        "incident": {"incident_key": "inc:demo:pipeline:marketing_sync:freshness", "summary": "stale"},
        "allowed_citation_ids": [
            "inc:demo:pipeline:marketing_sync:freshness",
            "marketing_sync",
            "exec-1",
        ],
        "blast_radius": None,
    }
    draft = {
        "summary": "Pipeline failed",
        "likely_cause": "Task failed",
        "timeline": [{"at": "t", "event": "fail", "citation": "exec-1"}],
        "blast_radius": ["fake_dataset"],
        "recommended_actions": ["Retry"],
        "citations": ["exec-1", "invented_id"],
    }
    result = validate_citations(draft, evidence, "openrouter/free")
    assert "exec-1" in result["citations"]
    assert "invented_id" not in result["citations"]
    assert "fake_dataset" not in result["blast_radius"]
    assert result["grounded"] is False
    assert "invented_id" in result["invented_ids_dropped"]
