"""Agent session checkpoint & memory store in MySQL."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any
import uuid

from application.src.store.meta_mysql import get_connection
from application.src.services.observability.filters import fetchall, fetchone, json_val

logger = logging.getLogger(__name__)


def create_or_get_session(
    session_id: str | None = None,
    tenant_id: str = "default",
    ambient_context: dict[str, Any] | None = None,
    title: str | None = None,
) -> str:
    """Create or return an active agent session ID."""
    sid = session_id or f"sess_{uuid.uuid4().hex[:12]}"
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO obs_agent_sessions (session_id, tenant_id, title, status, ambient_context_json)
                VALUES (%s, %s, %s, 'active', %s)
                ON DUPLICATE KEY UPDATE
                  ambient_context_json = VALUES(ambient_context_json),
                  updated_at = NOW()
                """,
                (
                    sid,
                    tenant_id,
                    title or "Observability Investigation",
                    json.dumps(ambient_context or {}, default=str),
                ),
            )
        conn.commit()
    return sid


def record_step(
    session_id: str,
    step_number: int,
    agent_role: str,
    thought: str | None,
    action_tool: str | None,
    action_input: dict[str, Any] | None,
    observation: Any | None,
    reflection: str | None = None,
) -> int:
    """Record an autonomous reasoning step (Thought -> Action -> Observation -> Reflection)."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO obs_agent_steps
                  (session_id, step_number, agent_role, thought, action_tool, action_input_json, observation_json, reflection)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    session_id,
                    step_number,
                    agent_role,
                    thought,
                    action_tool,
                    json.dumps(action_input or {}, default=str),
                    json.dumps(observation or {}, default=str)[:8000],  # protect max text size
                    reflection,
                ),
            )
            step_id = cur.lastrowid
        conn.commit()
    return step_id


def record_pending_action(
    session_id: str,
    action_type: str,
    payload: dict[str, Any],
    proposed_by: str = "OpsAgent",
) -> str:
    """Create a pending Human-in-the-Loop action requiring user approval."""
    action_id = f"act_{uuid.uuid4().hex[:10]}"
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO obs_agent_pending_actions
                  (action_id, session_id, action_type, action_payload_json, status, proposed_by)
                VALUES (%s, %s, %s, %s, 'pending', %s)
                """,
                (action_id, session_id, action_type, json.dumps(payload, default=str), proposed_by),
            )
            # update session status to awaiting_approval
            cur.execute("UPDATE obs_agent_sessions SET status = 'awaiting_approval' WHERE session_id = %s", (session_id,))
        conn.commit()
    return action_id


def resolve_pending_action(action_id: str, approved: bool) -> dict[str, Any]:
    """Approve or reject a pending Human-in-the-Loop action."""
    status = "approved" if approved else "rejected"
    with get_connection() as conn:
        act = fetchone(conn, "SELECT * FROM obs_agent_pending_actions WHERE action_id = %s", (action_id,))
        if not act:
            return {"ok": False, "error": f"Pending action '{action_id}' not found"}

        with conn.cursor() as cur:
            cur.execute(
                "UPDATE obs_agent_pending_actions SET status = %s, decided_at = NOW() WHERE action_id = %s",
                (status, action_id),
            )
            cur.execute(
                "UPDATE obs_agent_sessions SET status = 'active' WHERE session_id = %s",
                (act.get("session_id"),),
            )
        conn.commit()

        payload = {}
        try:
            payload = json.loads(act.get("action_payload_json") or "{}")
        except Exception:
            pass

        return {
            "ok": True,
            "action_id": action_id,
            "status": status,
            "action_type": act.get("action_type"),
            "payload": payload,
        }


def get_session_steps(session_id: str) -> list[dict[str, Any]]:
    """Retrieve full chronological thought trace of an agent investigation."""
    with get_connection() as conn:
        rows = fetchall(
            conn,
            """
            SELECT step_id, session_id, step_number, agent_role, thought, action_tool,
                   action_input_json, observation_json, reflection, created_at
            FROM obs_agent_steps
            WHERE session_id = %s
            ORDER BY step_number ASC, step_id ASC
            """,
            (session_id,),
        )
        out = []
        for r in rows:
            out.append({
                "step_id": r.get("step_id"),
                "step_number": r.get("step_number"),
                "agent_role": r.get("agent_role"),
                "thought": r.get("thought"),
                "action_tool": r.get("action_tool"),
                "action_input": json_val(r.get("action_input_json")),
                "observation": json_val(r.get("observation_json")),
                "reflection": r.get("reflection"),
                "created_at": str(r.get("created_at")),
            })
        return out
