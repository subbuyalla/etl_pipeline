"""Connector SDK — discover / pull_state / stream_events + production specs."""

from connector_sdk.base import (
    ConnectionResult,
    Connector,
    ConnectorContext,
    ConnectorSpec,
    RawEnvelope,
)

__all__ = [
    "ConnectionResult",
    "Connector",
    "ConnectorContext",
    "ConnectorSpec",
    "RawEnvelope",
]
__version__ = "0.2.0"
