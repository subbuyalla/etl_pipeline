from __future__ import annotations



import threading

import uuid

from dataclasses import dataclass, field

from datetime import datetime, timezone

from typing import Any



KIND_INCIDENT_RCA = "incident_rca"

KIND_DQ_LINEAGE = "dq_lineage"

KIND_OBSERVABILITY = "observability"





def _utcnow() -> str:

    return datetime.now(timezone.utc).isoformat()





@dataclass

class ChatMessage:

    role: str  # user | assistant | system

    content: str

    created_at: str = field(default_factory=_utcnow)

    meta: dict[str, Any] = field(default_factory=dict)



    def as_dict(self) -> dict[str, Any]:

        return {

            "role": self.role,

            "content": self.content,

            "created_at": self.created_at,

            "meta": self.meta,

        }





@dataclass

class ChatSession:

    session_id: str

    tenant_id: str

    kind: str = KIND_INCIDENT_RCA

    incident_key: str = ""

    dataset_id: str | None = None

    incident_title: str | None = None  # display title for any kind

    evidence: dict[str, Any] | None = None

    messages: list[ChatMessage] = field(default_factory=list)

    created_at: str = field(default_factory=_utcnow)

    updated_at: str = field(default_factory=_utcnow)



    def as_dict(self, *, include_evidence: bool = False) -> dict[str, Any]:

        data = {

            "session_id": self.session_id,

            "tenant_id": self.tenant_id,

            "kind": self.kind,

            "incident_key": self.incident_key,

            "dataset_id": self.dataset_id,

            "incident_title": self.incident_title,

            "created_at": self.created_at,

            "updated_at": self.updated_at,

            "message_count": len(self.messages),

            "messages": [m.as_dict() for m in self.messages],

        }

        if include_evidence:

            data["evidence"] = self.evidence

        return data





class SessionStore:

    """In-process short-term conversation memory (cleared on process restart)."""



    def __init__(self) -> None:

        self._lock = threading.Lock()

        self._sessions: dict[str, ChatSession] = {}



    def create(

        self,

        *,

        tenant_id: str,

        kind: str = KIND_INCIDENT_RCA,

        incident_key: str = "",

        dataset_id: str | None = None,

        incident_title: str | None = None,

        evidence: dict[str, Any] | None = None,

    ) -> ChatSession:

        session = ChatSession(

            session_id=str(uuid.uuid4()),

            tenant_id=tenant_id,

            kind=kind,

            incident_key=incident_key,

            dataset_id=dataset_id,

            incident_title=incident_title,

            evidence=evidence,

        )

        with self._lock:

            self._sessions[session.session_id] = session

        return session



    def get(self, session_id: str) -> ChatSession | None:

        with self._lock:

            return self._sessions.get(session_id)



    def save(self, session: ChatSession) -> None:

        session.updated_at = _utcnow()

        with self._lock:

            self._sessions[session.session_id] = session



    def delete(self, session_id: str) -> bool:

        with self._lock:

            return self._sessions.pop(session_id, None) is not None



    def count(self) -> int:

        with self._lock:

            return len(self._sessions)





STORE = SessionStore()


