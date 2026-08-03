from __future__ import annotations

import json
from typing import Any

from openai import OpenAI

from assistants.config import OPENROUTER_API_KEY, OPENROUTER_BASE_URL, OPENROUTER_MODEL


class OpenRouterLLM:
    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
    ) -> None:
        self.api_key = (api_key if api_key is not None else OPENROUTER_API_KEY).strip()
        self.model = model or OPENROUTER_MODEL
        self.base_url = (base_url or OPENROUTER_BASE_URL).rstrip("/")

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def chat(self, system: str, user: str) -> str:
        return self.chat_messages(system, [{"role": "user", "content": user}])

    def chat_messages(self, system: str, messages: list[dict[str, Any]]) -> str:
        if not self.api_key:
            raise RuntimeError("OPENROUTER_API_KEY is not set")
        client = OpenAI(api_key=self.api_key, base_url=self.base_url)
        payload = [{"role": "system", "content": system}, *messages]
        resp = client.chat.completions.create(
            model=self.model,
            messages=payload,
            temperature=0.2,
        )
        content = resp.choices[0].message.content
        return content or ""

    def chat_tools(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        *,
        tool_choice: str | dict[str, Any] = "auto",
        temperature: float = 0.2,
    ) -> dict[str, Any]:
        """
        Native OpenAI-compatible tool/function calling via OpenRouter.
        Returns {content, tool_calls, message} where message is appendable to the chat.
        """
        if not self.api_key:
            raise RuntimeError("OPENROUTER_API_KEY is not set")
        client = OpenAI(api_key=self.api_key, base_url=self.base_url)
        resp = client.chat.completions.create(
            model=self.model,
            messages=messages,
            tools=tools or None,
            tool_choice=tool_choice if tools else None,
            temperature=temperature,
        )
        msg = resp.choices[0].message
        tool_calls: list[dict[str, Any]] = []
        raw_tcs = getattr(msg, "tool_calls", None) or []
        for tc in raw_tcs:
            fn = getattr(tc, "function", None)
            tool_calls.append(
                {
                    "id": getattr(tc, "id", None) or f"call_{len(tool_calls)}",
                    "type": "function",
                    "function": {
                        "name": getattr(fn, "name", None) or "",
                        "arguments": getattr(fn, "arguments", None) or "{}",
                    },
                }
            )
        assistant_message: dict[str, Any] = {
            "role": "assistant",
            "content": msg.content,
        }
        if tool_calls:
            assistant_message["tool_calls"] = tool_calls
        return {
            "content": (msg.content or "").strip(),
            "tool_calls": tool_calls,
            "message": assistant_message,
        }


def parse_tool_arguments(raw: str | dict[str, Any] | None) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}
