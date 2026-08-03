from __future__ import annotations

import json
from typing import Any

from assistants.agentic.runtime import run_agentic_turn
from assistants.agentic.tools import openai_tool_schemas
from assistants.llm import parse_tool_arguments
from test_conversations_eval import FakeMeta


class ScriptedToolLLM:
    """Simulates OpenRouter tool calling: tool round(s) then final answer."""

    model = "fake-tools"

    def __init__(self, script: list[dict[str, Any]]) -> None:
        self.script = list(script)
        self.calls = 0

    def chat_messages(self, system: str, messages: list[dict[str, Any]]) -> str:
        self.calls += 1
        return "fallback chat_messages should not be primary path"

    def chat_tools(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        *,
        tool_choice: str | dict[str, Any] = "auto",
        temperature: float = 0.2,
    ) -> dict[str, Any]:
        self.calls += 1
        if not self.script:
            return {"content": "No more scripted steps.", "tool_calls": [], "message": {"role": "assistant", "content": "No more scripted steps."}}
        step = self.script.pop(0)
        tool_calls = step.get("tool_calls") or []
        content = step.get("content") or ""
        msg: dict[str, Any] = {"role": "assistant", "content": content or None}
        if tool_calls:
            msg["tool_calls"] = tool_calls
        return {"content": content, "tool_calls": tool_calls, "message": msg}


def test_parse_tool_arguments():
    assert parse_tool_arguments('{"pipeline_id":"finance_etl"}')["pipeline_id"] == "finance_etl"
    assert parse_tool_arguments({"a": 1})["a"] == 1
    assert parse_tool_arguments("not-json") == {}


def test_openai_tool_schemas_cover_registry():
    schemas = openai_tool_schemas()
    names = {s["function"]["name"] for s in schemas}
    assert "get_incident" in names
    assert "list_check_results" in names
    assert "list_metrics" in names


def test_llm_tool_loop_multi_step():
    llm = ScriptedToolLLM(
        [
            {
                "tool_calls": [
                    {
                        "id": "1",
                        "type": "function",
                        "function": {
                            "name": "get_incident",
                            "arguments": json.dumps(
                                {"incident_key": "inc:demo:pipeline:finance_etl:pipeline_failure"}
                            ),
                        },
                    },
                    {
                        "id": "2",
                        "type": "function",
                        "function": {
                            "name": "list_executions",
                            "arguments": json.dumps({"pipeline_id": "finance_etl"}),
                        },
                    },
                ]
            },
            {
                "content": (
                    "finance_etl failed on extract_orders due to Connection timeout to Snowflake."
                ),
                "tool_calls": [],
            },
        ]
    )
    result = run_agentic_turn(
        client=FakeMeta(),  # type: ignore[arg-type]
        llm=llm,  # type: ignore[arg-type]
        tenant_id="demo",
        question="What failed and why?",
        kind="incident_rca",
        bound={"incident_key": "inc:demo:pipeline:finance_etl:pipeline_failure"},
        build_system=lambda ev: "system",
    )
    assert result["agent_mode"] == "llm_tools"
    assert result["used_tools"] is True
    assert result["grounded"] is True
    assert "finance_etl" in result["reply"].lower() or "timeout" in result["reply"].lower()
    tools_used = [t.get("tool") for t in result["tool_trace"] if t.get("ok")]
    assert "get_incident" in tools_used
    assert "list_executions" in tools_used


def test_llm_tool_loop_fills_bound_args():
    """Model omits incident_key; runtime fills from bound context."""
    llm = ScriptedToolLLM(
        [
            {
                "tool_calls": [
                    {
                        "id": "1",
                        "type": "function",
                        "function": {"name": "get_incident", "arguments": "{}"},
                    }
                ]
            },
            {
                "content": "Pipeline finance_etl timed out connecting to Snowflake.",
                "tool_calls": [],
            },
        ]
    )
    result = run_agentic_turn(
        client=FakeMeta(),  # type: ignore[arg-type]
        llm=llm,  # type: ignore[arg-type]
        tenant_id="demo",
        question="Explain the incident",
        kind="incident_rca",
        bound={"incident_key": "inc:demo:pipeline:finance_etl:pipeline_failure"},
        build_system=lambda ev: "system",
    )
    assert result["used_tools"] is True
    assert any(t.get("tool") == "get_incident" and t.get("ok") for t in result["tool_trace"])
