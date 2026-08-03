from __future__ import annotations

from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import Field

from assistants.agentic.langgraph_agent import build_metadata_tools, run_langgraph_turn
from assistants.agentic.runtime import run_agentic_turn
from test_conversations_eval import FakeLLM, FakeMeta


class SequencedChatModel(BaseChatModel):
    """Minimal chat model that returns scripted AIMessages (supports bind_tools)."""

    responses: list[AIMessage] = Field(default_factory=list)
    call_i: int = 0

    @property
    def _llm_type(self) -> str:
        return "sequenced-fake"

    def bind_tools(self, tools: Any, **kwargs: Any) -> SequencedChatModel:
        return self

    def _generate(
        self,
        messages: list[Any],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        idx = min(self.call_i, len(self.responses) - 1)
        self.call_i += 1
        msg = self.responses[idx]
        return ChatResult(generations=[ChatGeneration(message=msg)])


def test_build_metadata_tools():
    evidence: dict[str, Any] = {"tool_trace": []}
    tools = build_metadata_tools(
        FakeMeta(),  # type: ignore[arg-type]
        "demo",
        {"incident_key": "inc:demo:pipeline:finance_etl:pipeline_failure", "pipeline_id": "finance_etl"},
        evidence,
    )
    names = {t.name for t in tools}
    assert "get_incident" in names
    assert "list_executions" in names
    out = tools[0].invoke({"incident_key": "inc:demo:pipeline:finance_etl:pipeline_failure"})
    assert "finance_etl" in out or "timeout" in out.lower()
    assert evidence.get("incident") or evidence.get("tool_trace")


def test_langgraph_turn_with_fake_model():
    model = SequencedChatModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "get_incident",
                        "args": {
                            "incident_key": "inc:demo:pipeline:finance_etl:pipeline_failure"
                        },
                        "id": "call_1",
                        "type": "tool_call",
                    },
                    {
                        "name": "list_executions",
                        "args": {"pipeline_id": "finance_etl"},
                        "id": "call_2",
                        "type": "tool_call",
                    },
                ],
            ),
            AIMessage(
                content=(
                    "finance_etl failed on extract_orders due to Connection timeout to Snowflake."
                )
            ),
        ]
    )
    result = run_langgraph_turn(
        client=FakeMeta(),  # type: ignore[arg-type]
        tenant_id="demo",
        question="What failed and why?",
        kind="incident_rca",
        bound={"incident_key": "inc:demo:pipeline:finance_etl:pipeline_failure"},
        chat_model=model,
    )
    assert result["agent_mode"] == "langgraph"
    assert result["used_tools"] is True
    assert "finance_etl" in result["reply"].lower() or "timeout" in result["reply"].lower()
    tools_ok = [t.get("tool") for t in result["tool_trace"] if t.get("ok")]
    assert "get_incident" in tools_ok
    assert "list_executions" in tools_ok


def test_runtime_uses_langgraph_when_chat_model_passed():
    model = SequencedChatModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "get_dataset",
                        "args": {"dataset_id": "ANALYTICS.MART.FCT_ORDERS"},
                        "id": "c1",
                        "type": "tool_call",
                    }
                ],
            ),
            AIMessage(content="Volume looks low on ANALYTICS.MART.FCT_ORDERS (about 50 rows)."),
        ]
    )
    result = run_agentic_turn(
        client=FakeMeta(),  # type: ignore[arg-type]
        llm=FakeLLM(),  # type: ignore[arg-type]
        tenant_id="demo",
        question="How is volume?",
        kind="dq_lineage",
        bound={"dataset_id": "ANALYTICS.MART.FCT_ORDERS"},
        build_system=lambda ev: "sys",
        chat_model=model,
    )
    assert result["agent_mode"] == "langgraph"
    assert "FCT_ORDERS" in result["reply"] or "50" in result["reply"]
