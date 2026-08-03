from __future__ import annotations

from assistants.agentic.runtime import run_agentic_turn
from assistants.agentic.tools import TOOLS, agentic_gather, openai_tool_schemas, select_tools_for_question

__all__ = [
    "TOOLS",
    "agentic_gather",
    "openai_tool_schemas",
    "select_tools_for_question",
    "run_agentic_turn",
    "run_langgraph_turn",
]


def __getattr__(name: str):
    if name == "run_langgraph_turn":
        from assistants.agentic.langgraph_agent import run_langgraph_turn

        return run_langgraph_turn
    raise AttributeError(name)
