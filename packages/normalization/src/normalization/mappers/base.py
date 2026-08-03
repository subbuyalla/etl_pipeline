from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from normalization.errors import InvalidRawPayloadError
from normalization.utils import parse_time, stable_event_id, utc_now_iso


class BaseMapper(ABC):
    """Maps one tool's raw payload into one or more canonical events."""

    tool_id: str
    family: str

    @abstractmethod
    def map(
        self,
        raw: dict[str, Any],
        *,
        tenant_id: str,
        connector_instance_id: str | None = None,
    ) -> list[dict[str, Any]]:
        raise NotImplementedError

    def event(
        self,
        *,
        event_type: str,
        tenant_id: str,
        payload: dict[str, Any],
        occurred_at: Any = None,
        event_id: str | None = None,
        connector_instance_id: str | None = None,
        id_parts: list[str] | None = None,
    ) -> dict[str, Any]:
        if not event_id:
            parts = id_parts or [tenant_id, self.tool_id, event_type, str(payload)]
            event_id = stable_event_id(*parts)
        return {
            "event_id": event_id,
            "event_type": event_type,
            "occurred_at": parse_time(occurred_at, default=utc_now_iso()),
            "tenant_id": tenant_id,
            "source_system": self.tool_id,
            "source_tool": self.tool_id,
            "connector_instance_id": connector_instance_id,
            "payload": payload,
        }

    def fail(self, detail: str) -> None:
        raise InvalidRawPayloadError(self.tool_id, detail)
