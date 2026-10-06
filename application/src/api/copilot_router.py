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


@router.post("/approve")
async def copilot_approve(
    payload: dict[str, Any] = Body(...),
):
    """Human-in-the-Loop decision gateway: approve or reject a proposed action."""
    from application.src.services.agent_session_store import resolve_pending_action

    action_id = str(payload.get("action_id") or "")
    approved = bool(payload.get("approved", True))

    if not action_id:
        raise HTTPException(status_code=400, detail="action_id is required")

    resolved = resolve_pending_action(action_id=action_id, approved=approved)
    if not resolved.get("ok"):
        return resolved

    if approved:
        # Execute the approved mutation
        action_type = resolved.get("action_type")
        act_payload = resolved.get("payload") or {}
        exec_res = execute_ops_action(action_type=action_type, payload=act_payload)
        return {
            "ok": True,
            "decision": "approved",
            "action_id": action_id,
            "execution": exec_res,
            "message": f"Action approved and executed: {exec_res.get('message', 'Success')}",
        }
    else:
        return {
            "ok": True,
            "decision": "rejected",
            "action_id": action_id,
            "message": "Action was cancelled by user.",
        }


@router.get("/sessions/{session_id}/steps")
async def copilot_session_steps(session_id: str):
    """Retrieve full chronological thought trace of an agent investigation."""
    from application.src.services.agent_session_store import get_session_steps

    steps = get_session_steps(session_id)
    return {"ok": True, "session_id": session_id, "steps": steps}
