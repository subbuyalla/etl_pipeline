from __future__ import annotations

import pytest
from normalization import normalize

from metadata.db import init_db, reset_db_state, get_session
from metadata.ingest import ingest_canonical_event, ingest_canonical_events
from metadata.repository import MetadataRepository


@pytest.fixture()
def session():
    reset_db_state()
    init_db("sqlite:///:memory:")
    s = get_session()
    yield s
    s.close()
    reset_db_state()


def test_ingest_pipeline_failure_creates_incident(session):
    events = normalize(
        {
            "source_system": "airflow",
            "tenant_id": "demo",
            "raw": {
                "dag_id": "finance_etl",
                "run_id": "r1",
                "state": "failed",
                "execution_date": "2026-07-22T10:00:00Z",
                "error": "boom",
            },
        }
    )
    result = ingest_canonical_event(session, events[0])
    assert result["status"] == "ingested"

    repo = MetadataRepository(session)
    pipelines = repo.list_pipelines("demo")
    assert len(pipelines) == 1
    assert pipelines[0].pipeline_id == "finance_etl"

    incidents = repo.list_incidents("demo")
    assert len(incidents) == 1
    assert "finance_etl" in incidents[0].title

    # idempotent
    result2 = ingest_canonical_event(session, events[0])
    assert result2["status"] == "duplicate"
    assert len(repo.list_incidents("demo")) == 1


def test_freshness_and_lineage_blast_radius(session):
    events = []
    events += normalize(
        {
            "source_system": "snowflake",
            "tenant_id": "demo",
            "raw": {
                "database": "ANALYTICS",
                "schema": "RAW",
                "table": "ORDERS",
                "event_type": "lineage",
                "upstream": "ANALYTICS.RAW.ORDERS",
                "downstream": "ANALYTICS.MART.FCT_ORDERS",
            },
        }
    )
    events += normalize(
        {
            "source_system": "snowflake",
            "tenant_id": "demo",
            "raw": {
                "database": "ANALYTICS",
                "schema": "RAW",
                "table": "ORDERS",
                "event_type": "freshness",
                "lag_minutes": 180,
                "sla_minutes": 60,
            },
        }
    )
    ingest_canonical_events(session, events)

    repo = MetadataRepository(session)
    assert len(repo.list_datasets("demo")) >= 1
    assert len(repo.list_monitors("demo")) == 1
    assert repo.list_monitors("demo")[0].monitor_type == "freshness"
    downstream = repo.blast_radius("demo", "ANALYTICS.RAW.ORDERS")
    assert "ANALYTICS.MART.FCT_ORDERS" in downstream
    incidents = repo.list_incidents("demo")
    assert any(i.blast_radius_count >= 1 for i in incidents)


def test_lineage_with_transform_creates_pipeline_io(session):
    events = normalize(
        {
            "source_system": "snowflake",
            "tenant_id": "demo",
            "raw": {
                "database": "ANALYTICS",
                "schema": "MART",
                "table": "FCT_ORDERS",
                "event_type": "lineage",
                "upstream": "ANALYTICS.RAW.ORDERS",
                "downstream": "ANALYTICS.MART.FCT_ORDERS",
                "transform": "finance_etl",
            },
        }
    )
    ingest_canonical_event(session, events[0])

    repo = MetadataRepository(session)
    edges = repo.list_lineage("demo")
    assert len(edges) == 1
    assert edges[0].transform == "finance_etl"

    io_rows = repo.list_pipeline_io("demo", pipeline_id="finance_etl")
    assert len(io_rows) == 1
    assert io_rows[0].upstream_dataset_id == "ANALYTICS.RAW.ORDERS"
    assert io_rows[0].downstream_dataset_id == "ANALYTICS.MART.FCT_ORDERS"
    assert io_rows[0].source_tool == "snowflake"

    dash = repo.pipeline_dashboard("demo", "finance_etl")
    assert dash is not None
    assert "ANALYTICS.RAW.ORDERS" in dash["related_datasets"]
    assert "ANALYTICS.MART.FCT_ORDERS" in dash["related_datasets"]
    assert len(dash["pipeline_io"]) == 1


def test_pipeline_execution_with_io_links_datasets(session):
    events = normalize(
        {
            "source_system": "airflow",
            "tenant_id": "demo",
            "raw": {
                "dag_id": "finance_etl",
                "run_id": "r-io-1",
                "state": "success",
                "execution_date": "2026-07-22T10:00:00Z",
                "upstream_dataset_id": "ANALYTICS.RAW.ORDERS",
                "downstream_dataset_id": "ANALYTICS.MART.FCT_ORDERS",
            },
        }
    )
    ingest_canonical_event(session, events[0])

    repo = MetadataRepository(session)
    io_rows = repo.list_pipeline_io("demo", pipeline_id="finance_etl")
    assert len(io_rows) == 1
    assert io_rows[0].upstream_dataset_id == "ANALYTICS.RAW.ORDERS"


def test_schema_change_creates_change_event(session):
    from metadata.models import ChangeEvent
    from sqlalchemy import select

    events = normalize(
        {
            "source_system": "bigquery",
            "tenant_id": "demo",
            "raw": {
                "project": "acme",
                "dataset": "mart",
                "table": "orders",
                "kind": "schema",
                "breaking": True,
                "columns_removed": ["x"],
            },
        }
    )
    ingest_canonical_event(session, events[0])
    changes = session.scalars(select(ChangeEvent).where(ChangeEvent.tenant_id == "demo")).all()
    assert len(changes) == 1
    assert changes[0].breaking is True


def test_api_health():
    from fastapi.testclient import TestClient
    from metadata.api import app
    from metadata.db import reset_db_state, init_db

    reset_db_state()
    init_db("sqlite:///:memory:")
    client = TestClient(app)
    assert client.get("/health").json()["status"] == "ok"
    cat = client.get("/v1/catalog").json()
    assert "Incident" in cat["entities"]
    assert "CostRecord" in cat["entities"]
