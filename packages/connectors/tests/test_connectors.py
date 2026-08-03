from __future__ import annotations

from pathlib import Path

from connectors.csv_util import read_csv_rows
from connectors.dbt import DbtCsvConnector
from connectors.snowflake import SnowflakeCsvConnector

SAMPLES = Path(__file__).resolve().parents[1] / "samples"


def test_read_snowflake_csv():
    rows = read_csv_rows(SAMPLES / "snowflake_checks.csv")
    assert len(rows) >= 5
    assert rows[0]["event_type"] == "discovered"


def test_snowflake_discover_and_envelopes():
    c = SnowflakeCsvConnector(SAMPLES / "snowflake_checks.csv", tenant_id="demo")
    assets = c.discover()
    assert any(a["dataset_id"].endswith("ORDERS") for a in assets)
    envs = c.pull_state()
    assert envs
    assert all(e.source_system == "snowflake" for e in envs)


def test_dbt_discover_and_envelopes():
    c = DbtCsvConnector(SAMPLES / "dbt_runs.csv", tenant_id="demo")
    assets = c.discover()
    assert any(a.get("pipeline_id") == "analytics" for a in assets)
    envs = c.pull_state()
    assert len(envs) == 4
    assert envs[0].raw["unique_id"].startswith("model.")
