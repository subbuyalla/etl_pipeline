from __future__ import annotations

from pathlib import Path
from typing import Any

from connector_sdk import Connector, RawEnvelope

from connectors.adapters.airflow_live import AirflowCsvConnector
from connectors.dbt import DbtCsvConnector
from connectors.snowflake import SnowflakeCsvConnector

# Back-compat helpers used by CLI / CSV ingest API

TOOLS = {
    "snowflake": SnowflakeCsvConnector,
    "dbt": DbtCsvConnector,
    "airflow": AirflowCsvConnector,
}


def build_connector(
    tool: str,
    csv_source: str | Path,
    *,
    tenant_id: str = "demo",
    connector_instance_id: str | None = None,
) -> Connector:
    key = tool.strip().lower()
    cls = TOOLS.get(key)
    if not cls:
        raise ValueError(f"Unknown connector tool '{tool}'. Choose: {', '.join(sorted(TOOLS))}")
    return cls(csv_source, tenant_id=tenant_id, connector_instance_id=connector_instance_id)


def envelopes_to_metadata(envelopes: list[RawEnvelope]) -> dict[str, Any]:
    from connectors.runtime import envelopes_to_metadata as _ingest

    return _ingest(envelopes)


def ingest_csv(
    tool: str,
    csv_source: str | Path,
    *,
    tenant_id: str = "demo",
    connector_instance_id: str | None = None,
) -> dict[str, Any]:
    connector = build_connector(
        tool,
        csv_source,
        tenant_id=tenant_id,
        connector_instance_id=connector_instance_id,
    )
    envelopes = connector.pull_state()
    stats = envelopes_to_metadata(envelopes)
    stats["tool"] = connector.tool_id
    stats["discover"] = connector.discover()
    return stats
