from __future__ import annotations

from assistants.a2a.cards import catalog, incident_rca_card
from assistants.a2a.server import handle_jsonrpc
from assistants.agentic.tools import select_tools_for_question

from test_conversations_eval import FakeLLM, FakeMeta


def test_select_tools_rca_blast_radius():
    calls = select_tools_for_question(
        "What is the blast radius?",
        kind="incident_rca",
        bound={"incident_key": "inc:1", "pipeline_id": "finance_etl", "dataset_id": "ANALYTICS.MART.FCT_ORDERS"},
    )
    names = [n for n, _ in calls]
    assert "get_incident" in names
    assert "get_blast_radius" in names
    assert "list_lineage" in names


def test_select_tools_dq_metrics():
    calls = select_tools_for_question(
        "Show the row_count trend chart history",
        kind="dq_lineage",
        bound={"dataset_id": "ANALYTICS.MART.FCT_ORDERS"},
    )
    names = [n for n, _ in calls]
    assert "list_metrics" in names
    assert "list_check_results" in names


def test_a2a_agents_list():
    body = {"jsonrpc": "2.0", "id": 1, "method": "agents/list", "params": {}}
    out = handle_jsonrpc(body, client=FakeMeta(), llm=FakeLLM(), base_url="http://test")  # type: ignore[arg-type]
    assert out["id"] == 1
    assert "result" in out
    assert len(out["result"]["agents"]) == 4


def test_a2a_message_send_rca():
    llm = FakeLLM(
        [
            "finance_etl failed due to Connection timeout to Snowflake on extract_orders.",
        ]
    )
    body = {
        "jsonrpc": "2.0",
        "id": "t1",
        "method": "message/send",
        "params": {
            "message": {
                "parts": [{"kind": "text", "text": "What failed and why?"}],
                "metadata": {
                    "tenant_id": "demo",
                    "skill": "incident_rca",
                    "incident_key": "inc:demo:pipeline:finance_etl:pipeline_failure",
                },
            }
        },
    }
    out = handle_jsonrpc(body, client=FakeMeta(), llm=llm)  # type: ignore[arg-type]
    assert "result" in out
    assert out["result"]["status"]["state"] == "completed"
    text = out["result"]["artifacts"][0]["parts"][0]["text"]
    assert "finance_etl" in text.lower() or "timeout" in text.lower()


def test_a2a_orchestrator_delegates():
    llm = FakeLLM(
        [
            "RCA: finance_etl failed with Connection timeout to Snowflake.",
            "DQ: volume is low on ANALYTICS.MART.FCT_ORDERS (50 rows).",
        ]
    )
    body = {
        "jsonrpc": "2.0",
        "id": "orch-1",
        "method": "message/send",
        "params": {
            "message": {
                "parts": [
                    {
                        "kind": "text",
                        "text": "Pipeline failed and the mart table volume looks wrong — explain both.",
                    }
                ],
                "metadata": {
                    "tenant_id": "demo",
                    "skill": "orchestrate",
                    "incident_key": "inc:demo:pipeline:finance_etl:pipeline_failure",
                    "dataset_id": "ANALYTICS.MART.FCT_ORDERS",
                },
            }
        },
    }
    out = handle_jsonrpc(body, client=FakeMeta(), llm=llm)  # type: ignore[arg-type]
    assert "result" in out
    text = out["result"]["artifacts"][0]["parts"][0]["text"]
    assert "RCA agent" in text or "Quality" in text
    data_parts = [p for p in out["result"]["artifacts"][0]["parts"] if p.get("kind") == "data"]
    assert data_parts
    assert data_parts[0]["data"].get("a2a_delegations")


def test_agent_cards_shape():
    card = incident_rca_card(base_url="http://127.0.0.1:8001")
    assert card["protocolVersion"]
    assert card["skills"][0]["id"] == "incident_rca"
    cat = catalog(base_url="http://127.0.0.1:8001")
    assert len(cat["agents"]) == 4
