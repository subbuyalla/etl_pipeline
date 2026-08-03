from __future__ import annotations

from connector_sdk import ConnectorContext
from connectors.registry import build_context, create_connector, list_specs
from connectors.runtime import catalog


def test_catalog_has_snowflake_and_dbt():
    specs = {s.tool_id for s in list_specs()}
    assert "snowflake" in specs
    assert "dbt" in specs
    items = catalog()
    assert any(i["tool_id"] == "snowflake" for i in items)
    assert "config_schema" in items[0]


def test_snowflake_csv_mode_via_registry(tmp_path):
    from pathlib import Path

    sample = Path(__file__).resolve().parents[1] / "samples" / "snowflake_checks.csv"
    ctx = build_context(
        tenant_id="demo",
        connector_instance_id="sf-csv-test",
        tool_id="snowflake",
        config={"input_mode": "csv", "csv_path": str(sample)},
    )
    conn = create_connector(ctx)
    assets = conn.discover()
    assert assets
    envs = conn.pull_state()
    assert envs
    assert all(e.source_system == "snowflake" for e in envs)
    result = conn.test_connection()
    assert result.ok


def test_dbt_csv_mode_via_registry():
    from pathlib import Path

    sample = Path(__file__).resolve().parents[1] / "samples" / "dbt_runs.csv"
    ctx = build_context(
        tenant_id="demo",
        connector_instance_id="dbt-csv-test",
        tool_id="dbt",
        config={"input_mode": "csv", "csv_path": str(sample)},
    )
    conn = create_connector(ctx)
    assert conn.pull_state()
    assert conn.test_connection().ok
