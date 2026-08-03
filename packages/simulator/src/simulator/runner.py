from __future__ import annotations

from typing import Any, Iterable

from connector_sdk import RawEnvelope
from metadata.db import get_session, init_db
from metadata.ingest import ingest_canonical_event
from normalization import normalize_production
from simulator.twin import DigitalTwinConnector


def envelopes_to_metadata(
    envelopes: Iterable[RawEnvelope],
    *,
    database_url: str | None = None,
) -> dict[str, Any]:
    """Normalize each twin envelope and ingest into Metadata."""
    if database_url:
        init_db(database_url)
    else:
        init_db()

    session = get_session()
    stats = {
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


def bootstrap_and_stream(
    *,
    tenant_id: str = "demo",
    ticks: int = 50,
    seed: int = 42,
    database_url: str | None = None,
    bootstrap: bool = True,
) -> dict[str, Any]:
    twin = DigitalTwinConnector(tenant_id=tenant_id, seed=seed)
    envelopes: list[RawEnvelope] = []
    if bootstrap:
        envelopes.extend(twin.pull_state())
    envelopes.extend(list(twin.stream_events(ticks=ticks)))
    stats = envelopes_to_metadata(envelopes, database_url=database_url)
    stats["discover"] = twin.discover()
    stats["scenarios_available"] = list(__import__("simulator.twin", fromlist=["SCENARIOS"]).SCENARIOS)
    return stats


def run_named_scenarios(
    names: list[str],
    *,
    tenant_id: str = "demo",
    database_url: str | None = None,
) -> dict[str, Any]:
    twin = DigitalTwinConnector(tenant_id=tenant_id, seed=7)
    envelopes: list[RawEnvelope] = []
    for name in names:
        envelopes.extend(twin.run_scenario(name))
    return envelopes_to_metadata(envelopes, database_url=database_url)
