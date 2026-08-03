from __future__ import annotations

from pathlib import Path
from typing import Any, Iterator

from connector_sdk import Connector, RawEnvelope

from connectors.csv_util import read_csv_rows


class SnowflakeCsvConnector(Connector):
    """
    Snowflake connector fed by CSV (no live account).

    Each row becomes one vendor-shaped raw record for the snowflake mapper
    (discovered / freshness / volume / schema / distribution).
    """

    tool_id = "snowflake"

    def __init__(
        self,
        csv_source: str | Path,
        *,
        tenant_id: str = "demo",
        connector_instance_id: str | None = None,
    ) -> None:
        self.csv_source = csv_source
        self.tenant_id = tenant_id
        self.connector_instance_id = connector_instance_id or "snowflake-csv-1"
        self._rows = read_csv_rows(csv_source)

    def discover(self) -> list[dict[str, Any]]:
        assets: list[dict[str, Any]] = []
        seen: set[str] = set()
        for row in self._rows:
            database = row.get("database") or row.get("DATABASE_NAME") or "UNKNOWN"
            schema = row.get("schema") or row.get("SCHEMA_NAME") or "PUBLIC"
            table = row.get("table") or row.get("TABLE_NAME") or row.get("name")
            if not table:
                continue
            dataset_id = str(row.get("dataset_id") or f"{database}.{schema}.{table}")
            if dataset_id in seen:
                continue
            seen.add(dataset_id)
            assets.append(
                {
                    "asset_type": "dataset",
                    "dataset_id": dataset_id,
                    "database": database,
                    "schema": schema,
                    "table": table,
                    "platform": "snowflake",
                }
            )
        return assets

    def pull_state(self) -> list[RawEnvelope]:
        return list(self._iter_envelopes())

    def stream_events(self, *, ticks: int | None = None) -> Iterator[RawEnvelope]:
        count = 0
        for env in self._iter_envelopes():
            yield env
            count += 1
            if ticks is not None and count >= ticks:
                return

    def _iter_envelopes(self) -> Iterator[RawEnvelope]:
        for row in self._rows:
            raw = dict(row)
            # Normalize common aliases so WarehouseMapper always finds fields
            if "TABLE_NAME" in raw and "table" not in raw:
                raw["table"] = raw["TABLE_NAME"]
            if "TABLE_SCHEMA" in raw and "schema" not in raw:
                raw["schema"] = raw["TABLE_SCHEMA"]
            if "TABLE_CATALOG" in raw and "database" not in raw:
                raw["database"] = raw["TABLE_CATALOG"]
            if "event_type" not in raw and "monitor_type" not in raw:
                raw["event_type"] = "discovered"
            yield RawEnvelope(
                source_system=self.tool_id,
                tenant_id=self.tenant_id,
                raw=raw,
                connector_instance_id=self.connector_instance_id,
                meta={"input": "csv"},
            )
