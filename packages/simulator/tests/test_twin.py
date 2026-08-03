from __future__ import annotations

from simulator.estate import default_estate, estate_summary
from simulator.runner import bootstrap_and_stream, run_named_scenarios
from simulator.twin import SCENARIOS, DigitalTwinConnector
from metadata.db import get_session, reset_db_state
from metadata.repository import MetadataRepository


def test_estate_summary():
    s = estate_summary(default_estate("demo"))
    assert s["dataset_count"] >= 8
    assert s["pipeline_count"] >= 5
    assert "finance" in s["domains"]


def test_discover_and_pull_state():
    twin = DigitalTwinConnector(tenant_id="demo", seed=1)
    assets = twin.discover()
    assert any(a["asset_type"] == "pipeline" for a in assets)
    state = twin.pull_state()
    assert len(state) > 10
    assert all(e.source_system and e.raw for e in state)


def test_all_scenarios_produce_envelopes():
    twin = DigitalTwinConnector(tenant_id="demo", seed=2)
    for name in SCENARIOS:
        envs = twin.run_scenario(name)
        assert len(envs) >= 1, name


def test_pull_state_lineage_includes_transform():
    twin = DigitalTwinConnector(tenant_id="demo", seed=1)
    state = twin.pull_state()
    lineage_envs = [
        e for e in state if isinstance(e.raw, dict) and e.raw.get("event_type") == "lineage"
    ]
    assert len(lineage_envs) >= 4
    assert all(e.raw.get("transform") for e in lineage_envs)


def test_bootstrap_ingests_pipeline_io_links():
    reset_db_state()
    stats = bootstrap_and_stream(
        tenant_id="demo",
        ticks=15,
        seed=3,
        database_url="sqlite:///:memory:",
        bootstrap=True,
    )
    assert stats["envelopes"] > 15
    assert stats["ingested"] > 0
    assert stats["dead_letters"] == 0

    session = get_session()
    try:
        repo = MetadataRepository(session)
        assert len(repo.list_pipelines("demo")) >= 1
        assert len(repo.list_datasets("demo")) >= 1
        io_rows = repo.list_pipeline_io("demo")
        assert len(io_rows) >= 4
        lineage = repo.list_lineage("demo")
        assert any(e.transform for e in lineage)
    finally:
        session.close()
        reset_db_state()


def test_named_scenario_freshness_creates_incident():
    reset_db_state()
    stats = run_named_scenarios(
        ["lineage_upsert", "freshness_breach", "pipeline_failure"],
        tenant_id="demo",
        database_url="sqlite:///:memory:",
    )
    assert stats["dead_letters"] == 0
    assert stats["ingested"] >= 3

    session = get_session()
    try:
        repo = MetadataRepository(session)
        assert len(repo.list_incidents("demo")) >= 1
        assert len(repo.list_monitors("demo")) >= 1
        assert len(repo.list_lineage("demo")) >= 1
    finally:
        session.close()
        reset_db_state()
