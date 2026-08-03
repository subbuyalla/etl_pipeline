from __future__ import annotations

from assistants.agentic.tools import select_tools_for_question
from assistants.observability.chat import continue_observability_chat, start_observability_chat
from assistants.observability.prompt import format_overview_fallback
from test_conversations_eval import FakeLLM, FakeMeta


def test_select_tools_observability_overview():
    calls = select_tools_for_question(
        "Give me a reliability overview",
        kind="observability",
        bound={},
    )
    names = [n for n, _ in calls]
    assert "get_reliability_overview" in names
    assert "list_incidents" in names


def test_observability_fallback_format():
    evidence = {
        "reliability_overview": {
            "pipeline_count": 5,
            "dataset_count": 9,
            "open_incident_count": 11,
            "alert_count": 12,
            "failed_pipeline_count": 1,
            "failing_check_count": 3,
            "top_open_incidents": [
                {
                    "title": "Pipeline failed: finance_etl",
                    "severity": "high",
                    "root_asset_id": "finance_etl",
                }
            ],
        }
    }
    text = format_overview_fallback(evidence)
    assert "11" in text or "open incidents" in text.lower()
    assert "finance_etl" in text
    assert "Monitors:" not in text
    assert "Failing checks" in text


def test_observability_conversation():
    meta = FakeMeta()
    llm = FakeLLM(
        [
            "You have 1 failed pipeline (finance_etl) and open volume issues on FCT_ORDERS. Start with the pipeline failure.",
            "Prioritize the extract_orders timeout, then re-check mart volume.",
        ]
    )
    session = start_observability_chat(
        "demo",
        client=meta,  # type: ignore[arg-type]
        llm=llm,  # type: ignore[arg-type]
    )
    assert session["kind"] == "observability"
    opening = session["messages"][-1]["content"]
    assert opening
    assert "alert:" not in opening

    turn = continue_observability_chat(
        session["session_id"],
        "What should I look at first?",
        llm=llm,  # type: ignore[arg-type]
        client=meta,  # type: ignore[arg-type]
    )
    assert turn["reply"]
    assert turn.get("agentic") is True
