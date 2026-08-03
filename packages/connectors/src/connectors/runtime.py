from __future__ import annotations

import time
from typing import Any, Callable, TypeVar

from connector_sdk import Connector, ConnectorContext, RawEnvelope

from connectors.registry import build_context, create_connector, get_spec

T = TypeVar("T")


def with_retries(fn: Callable[[], T], *, attempts: int = 3, base_delay: float = 0.4) -> T:
    last: Exception | None = None
    for i in range(attempts):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 — retry boundary
            last = exc
            if i == attempts - 1:
                break
            time.sleep(base_delay * (2**i))
    assert last is not None
    raise last


def instantiate(ctx: ConnectorContext) -> Connector:
    return create_connector(ctx)


def test_instance(ctx: ConnectorContext) -> dict[str, Any]:
    connector = instantiate(ctx)
    result = with_retries(connector.test_connection, attempts=2)
    return result.to_dict()


def sync_instance(ctx: ConnectorContext) -> tuple[list[RawEnvelope], list[dict[str, Any]]]:
    """Pull state with retries; returns envelopes + discover assets."""
    connector = instantiate(ctx)

    def _pull() -> list[RawEnvelope]:
        return list(connector.pull_state())

    envelopes = with_retries(_pull, attempts=3)
    assets = connector.discover()
    return envelopes, assets


def envelopes_to_metadata(envelopes: list[RawEnvelope]) -> dict[str, Any]:
    from metadata.db import get_session, init_db
    from metadata.ingest import ingest_canonical_event
    from normalization import normalize_production

    init_db()
    session = get_session()
    stats: dict[str, Any] = {
        "envelopes": 0,
        "canonical_events": 0,
        "ingested": 0,
        "duplicates": 0,
        "dead_letters": 0,
        "errors": [],
    }
    try:
        for env in envelopes:
            stats["envelopes"] += 1
            result = normalize_production(
                source_system=env.source_system,
                tenant_id=env.tenant_id,
                raw=env.raw,
                connector_instance_id=env.connector_instance_id,
            )
            stats["dead_letters"] += len(result.dead_letters)
            for dl in result.dead_letters:
                stats["errors"].append(dl.to_dict())
            for event in result.events:
                stats["canonical_events"] += 1
                out = ingest_canonical_event(session, event)
                if out.get("status") == "ingested":
                    stats["ingested"] += 1
                else:
                    stats["duplicates"] += 1
    finally:
        session.close()
    return stats


def run_sync_from_config(
    *,
    tenant_id: str,
    connector_instance_id: str,
    tool_id: str,
    config: dict[str, Any],
) -> dict[str, Any]:
    ctx = build_context(
        tenant_id=tenant_id,
        connector_instance_id=connector_instance_id,
        tool_id=tool_id,
        config=config,
    )
    envelopes, assets = sync_instance(ctx)
    stats = envelopes_to_metadata(envelopes)
    stats["tool"] = tool_id
    stats["discover"] = assets
    stats["connector_instance_id"] = connector_instance_id
    return stats


def catalog() -> list[dict[str, Any]]:
    from connectors.registry import list_specs

    return [s.to_dict() for s in list_specs()]


def validate_tool(tool_id: str) -> None:
    if not get_spec(tool_id):
        raise ValueError(f"Unknown connector tool '{tool_id}'")
