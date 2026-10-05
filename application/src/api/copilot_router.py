"""Copilot REST & Streaming API Router for DataPulse."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Body, HTTPException, Request

from application.src.services.copilot_service import (
    get_contextual_suggestions,
    process_copilot_turn,
)
from application.src.services.copilot_tools import execute_ops_action

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/copilot", tags=["copilot"])


@router.post("/chat")
async def copilot_chat(
    payload: dict[str, Any] = Body(...),
):
    """Process a conversational turn with DataPulse Copilot."""
    try:
        message = str(payload.get("message") or "")
        context = payload.get("context") or {}
        history = payload.get("history") or []

        if not message.strip():
            raise HTTPException(status_code=400, detail="Message cannot be empty")

        result = process_copilot_turn(message=message, context=context, history=history)
        return result
    except Exception as exc:
        logger.exception("Error in copilot_chat: %s", exc)
        return {
            "ok": False,
            "response": f"⚠️ An error occurred while processing your request: {exc}",
            "intent": "ERROR",
            "actions": []
        }


@router.post("/action")
async def copilot_action(
    payload: dict[str, Any] = Body(...),
):
    """Execute a Jira-style operational action directly from Copilot."""
    try:
        action_type = payload.get("action_type") or payload.get("action")
        action_payload = payload.get("payload") or {}
        if not action_type:
            raise HTTPException(status_code=400, detail="action_type is required")

        result = execute_ops_action(action_type=action_type, payload=action_payload)
        return result
    except Exception as exc:
        logger.exception("Error in copilot_action: %s", exc)
        return {"ok": False, "error": str(exc)}


@router.post("/suggestions")
async def copilot_suggestions(
    payload: dict[str, Any] = Body(...),
):
    """Return contextual prompt suggestions based on current frontend route and active entity."""
    context = payload.get("context") or {}
    suggestions = get_contextual_suggestions(context)
    return {"ok": True, "suggestions": suggestions}
