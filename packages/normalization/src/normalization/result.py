from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass
class DeadLetter:
    """Payload that failed normalization — keep for replay / ops."""

    source_system: str
    tenant_id: str | None
    error_type: str
    error_message: str
    raw: Any
    connector_instance_id: str | None = None
    index: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class NormalizeResult:
    """Production normalize outcome: successes + dead letters (never silent drop)."""

    events: list[dict[str, Any]] = field(default_factory=list)
    dead_letters: list[DeadLetter] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return len(self.dead_letters) == 0

    @property
    def event_count(self) -> int:
        return len(self.events)

    @property
    def error_count(self) -> int:
        return len(self.dead_letters)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "event_count": self.event_count,
            "error_count": self.error_count,
            "events": self.events,
            "dead_letters": [d.to_dict() for d in self.dead_letters],
        }
