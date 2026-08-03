from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Iterator


@dataclass
class RawEnvelope:
    """Raw tool payload ready for the Normalization layer."""

    source_system: str
    tenant_id: str
    raw: dict[str, Any]
    connector_instance_id: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_system": self.source_system,
            "tenant_id": self.tenant_id,
            "raw": self.raw,
            "connector_instance_id": self.connector_instance_id,
        }


@dataclass
class ConnectionResult:
    """Outcome of Connector.test_connection()."""

    ok: bool
    message: str
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "message": self.message, "details": self.details}


@dataclass
class ConnectorSpec:
    """
    Catalog entry that drives Monte Carlo–style UI forms.
    config_schema is JSON Schema for non-secret fields.
    secret_fields lists keys resolved from env / secrets_ref (never stored in DB).
    """

    tool_id: str
    display_name: str
    description: str = ""
    auth_kinds: list[str] = field(default_factory=lambda: ["password"])
    capabilities: list[str] = field(default_factory=list)
    config_schema: dict[str, Any] = field(default_factory=dict)
    secret_fields: list[str] = field(default_factory=list)
    input_modes: list[str] = field(default_factory=lambda: ["live", "csv"])

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool_id": self.tool_id,
            "display_name": self.display_name,
            "description": self.description,
            "auth_kinds": self.auth_kinds,
            "capabilities": self.capabilities,
            "config_schema": self.config_schema,
            "secret_fields": self.secret_fields,
            "input_modes": self.input_modes,
        }


@dataclass
class ConnectorContext:
    """Resolved runtime context for a connector instance (secrets never logged)."""

    tenant_id: str
    connector_instance_id: str
    tool_id: str
    config: dict[str, Any] = field(default_factory=dict)
    secrets: dict[str, str] = field(default_factory=dict)
    input_mode: str = "live"

    def public_config(self) -> dict[str, Any]:
        """Config safe to return in APIs (no secret values)."""
        return dict(self.config)


class Connector(ABC):
    """
    Every real connector and the Digital Twin implement this interface.
    Output is always raw vendor-shaped JSON — never canonical events.
    """

    tool_id: str
    spec: ConnectorSpec | None = None

    @abstractmethod
    def discover(self) -> list[dict[str, Any]]:
        """List known assets (pipelines, datasets, …) in vendor-ish shape."""

    @abstractmethod
    def pull_state(self) -> list[RawEnvelope]:
        """One-shot snapshot of current state as raw envelopes."""

    @abstractmethod
    def stream_events(self, *, ticks: int | None = None) -> Iterator[RawEnvelope]:
        """
        Continuous (or bounded) stream of raw events.
        ticks=None → infinite; ticks=N → stop after N envelopes.
        """

    def test_connection(self) -> ConnectionResult:
        """
        Verify credentials / reachability.
        Default: succeed if discover() does not raise.
        """
        try:
            assets = self.discover()
            return ConnectionResult(
                ok=True,
                message="Connection OK",
                details={"asset_count": len(assets)},
            )
        except Exception as exc:
            return ConnectionResult(ok=False, message=str(exc), details={"error_type": type(exc).__name__})
