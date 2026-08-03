from __future__ import annotations

import pytest
from normalization import normalize

from metadata.db import init_db, reset_db_state, get_session
from metadata.ingest import ingest_canonical_event
from metadata.repository import MetadataRepository
from metadata.messages import distribution_message, distribution_title, volume_message


def test_distribution_title_without_column():
    assert distribution_title("ANALYTICS.MART.FCT_ORDERS", None) == (
        "Distribution anomaly: ANALYTICS.MART.FCT_ORDERS"
    )
    assert distribution_title("T", "None") == "Distribution anomaly: T"


def test_distribution_message_human():
    msg = distribution_message("null_rate", 0.42, 0.1, None)
    assert "0.42" in msg
    assert "0.10" in msg or "0.1" in msg
    assert "None" not in msg


def test_volume_message_human():
    assert "50" in volume_message(50)
    assert "lag_minutes" not in volume_message(50).lower()


@pytest.fixture()
def session():
    reset_db_state()
    init_db("sqlite:///:memory:")
    s = get_session()
    yield s
    s.close()
    reset_db_state()


def test_csv_null_rate_maps_to_distribution_value(session):
    events = normalize(
        {
            "source_system": "snowflake",
            "tenant_id": "demo",
            "raw": {
                "event_type": "distribution",
                "database": "ANALYTICS",
                "schema": "MART",
                "table": "FCT_ORDERS",
                "null_rate": 0.42,
                "severity": "medium",
            },
        }
    )
    assert events[0]["event_type"] == "dataset.distribution.anomaly.v1"
    assert events[0]["payload"]["value"] == 0.42

    ingest_canonical_event(session, events[0])
    repo = MetadataRepository(session)
    alerts = repo.list_alerts("demo")
    assert len(alerts) == 1
    assert alerts[0].title == "Distribution anomaly: ANALYTICS.MART.FCT_ORDERS"
    assert "0.42" in (alerts[0].message or "")
    assert "null_rate=None" not in (alerts[0].message or "")
