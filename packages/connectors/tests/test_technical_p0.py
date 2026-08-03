from __future__ import annotations

from datetime import datetime, timezone, timedelta

from connectors.adapters.airflow_live import AirflowCsvConnector
from connectors.adapters.snowflake_monitors import build_table_monitor_events
from connectors.registry import list_specs
from pathlib import Path

SAMPLES = Path(__file__).resolve().parents[1] / "samples"


def test_airflow_registered():
    ids = {s.tool_id for s in list_specs()}
    assert "airflow" in ids
    assert "snowflake" in ids
    assert "dbt" in ids


def test_snowflake_monitor_events_freshness_and_volume():
    now = datetime(2026, 7, 28, 12, 0, tzinfo=timezone.utc)
    stale = (now - timedelta(hours=3)).isoformat()
    events = build_table_monitor_events(
        {
            "database": "ANALYTICS",
            "schema": "RAW",
            "table": "ORDERS",
            "row_count": 0,
            "last_altered": stale,
        },
        now=now,
        freshness_sla_minutes=60,
        volume_min_rows=1,
    )
    types = [e["event_type"] for e in events]
    assert "discovered" in types
    assert "freshness" in types
    assert "volume" in types
    fresh = next(e for e in events if e["event_type"] == "freshness")
    assert fresh["lag_minutes"] >= 180


def test_snowflake_monitor_healthy_table_only_discovered():
    now = datetime(2026, 7, 28, 12, 0, tzinfo=timezone.utc)
    events = build_table_monitor_events(
        {
            "database": "ANALYTICS",
            "schema": "MART",
            "table": "FCT_ORDERS",
            "row_count": 10000,
            "last_altered": (now - timedelta(minutes=10)).isoformat(),
        },
        now=now,
        freshness_sla_minutes=60,
        volume_min_rows=1,
    )
    assert [e["event_type"] for e in events] == ["discovered"]


def test_airflow_csv_connector():
    c = AirflowCsvConnector(SAMPLES / "airflow_runs.csv", tenant_id="demo")
    assets = c.discover()
    assert any(a["pipeline_id"] == "finance_etl" for a in assets)
    envs = c.pull_state()
    assert len(envs) >= 2
    failed = [e for e in envs if str(e.raw.get("state") or "").lower() == "failed"]
    assert failed
    assert any("timeout" in str(e.raw.get("error") or "").lower() for e in failed)
