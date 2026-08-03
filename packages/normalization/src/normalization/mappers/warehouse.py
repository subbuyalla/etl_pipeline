from __future__ import annotations

from typing import Any

from normalization.expand import as_records, flatten_dotted
from normalization.mappers.base import BaseMapper
from normalization.utils import first, require


class WarehouseMapper(BaseMapper):
    """
    Shared mapper for warehouses / databases / lakehouses.

    Unwraps list envelopes (tables, rows, Records, value) for production catalog pulls.
    """

    family = "warehouse_database"

    dataset_keys = (
        "dataset_id",
        "table",
        "table_name",
        "TABLE_NAME",
        "tableName",
        "table_id",
        "full_name",
        "relation",
        "object_name",
        "name",
    )
    schema_keys = ("schema", "schema_name", "SCHEMA_NAME", "table_schema", "dataset", "TABLE_SCHEMA", "owner")
    database_keys = (
        "database",
        "database_name",
        "DATABASE_NAME",
        "TABLE_CATALOG",
        "project",
        "project_id",
        "catalog",
        "catalog_name",
        "db",
    )

    def map(
        self,
        raw: dict[str, Any],
        *,
        tenant_id: str,
        connector_instance_id: str | None = None,
    ) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        for record in as_records(raw):
            events.extend(
                self.map_record(
                    flatten_dotted(record),
                    tenant_id=tenant_id,
                    connector_instance_id=connector_instance_id,
                )
            )
        if not events:
            self.fail("no mappable records found in payload")
        return events

    def map_record(
        self,
        raw: dict[str, Any],
        *,
        tenant_id: str,
        connector_instance_id: str | None = None,
    ) -> list[dict[str, Any]]:
        event_hint = str(first(raw, "event_type", "monitor_type", "check_type", "kind", default="discovered")).lower()

        try:
            dataset_name = str(require(raw, *self.dataset_keys))
        except KeyError as exc:
            self.fail(str(exc))

        schema = first(raw, *self.schema_keys, default="public")
        database = first(raw, *self.database_keys, default="default")
        dataset_id = first(raw, "dataset_id") or f"{database}.{schema}.{dataset_name}"

        base_payload = {
            "dataset_id": dataset_id,
            "database": database,
            "schema": schema,
            "name": dataset_name,
            "platform": self.tool_id,
        }

        if "fresh" in event_hint or event_hint in {"freshness", "staleness", "dataset.freshness.breached.v1"}:
            return [
                self.event(
                    event_type="dataset.freshness.breached.v1",
                    tenant_id=tenant_id,
                    occurred_at=first(raw, "occurred_at", "detected_at", "timestamp", "LAST_ALTERED"),
                    connector_instance_id=connector_instance_id,
                    payload={
                        **base_payload,
                        "last_updated_at": first(
                            raw, "last_updated_at", "max_loaded_at", "last_altered", "LAST_ALTERED"
                        ),
                        "sla_minutes": first(raw, "sla_minutes", "freshness_sla_minutes"),
                        "lag_minutes": first(raw, "lag_minutes", "delay_minutes"),
                        "severity": first(raw, "severity", default="high"),
                    },
                    id_parts=[
                        tenant_id,
                        self.tool_id,
                        "freshness",
                        dataset_id,
                        str(first(raw, "last_updated_at", "LAST_ALTERED", "window_id", default="")),
                    ],
                )
            ]

        if "volume" in event_hint or event_hint in {"row_count", "dataset.volume.anomaly.v1"}:
            return [
                self.event(
                    event_type="dataset.volume.anomaly.v1",
                    tenant_id=tenant_id,
                    occurred_at=first(raw, "occurred_at", "detected_at", "timestamp"),
                    connector_instance_id=connector_instance_id,
                    payload={
                        **base_payload,
                        "row_count": first(raw, "row_count", "rows", "ROW_COUNT", "metric_value"),
                        "expected_min": first(raw, "expected_min", "baseline_min"),
                        "expected_max": first(raw, "expected_max", "baseline_max"),
                        "severity": first(raw, "severity", default="medium"),
                    },
                    id_parts=[
                        tenant_id,
                        self.tool_id,
                        "volume",
                        dataset_id,
                        str(first(raw, "row_count", "ROW_COUNT", "window_id", default="")),
                    ],
                )
            ]

        if "schema" in event_hint or event_hint in {"schema_change", "dataset.schema.changed.v1"}:
            return [
                self.event(
                    event_type="dataset.schema.changed.v1",
                    tenant_id=tenant_id,
                    occurred_at=first(raw, "occurred_at", "detected_at", "timestamp"),
                    connector_instance_id=connector_instance_id,
                    payload={
                        **base_payload,
                        "change_type": first(raw, "change_type", default="unknown"),
                        "columns_added": first(raw, "columns_added", default=[]),
                        "columns_removed": first(raw, "columns_removed", default=[]),
                        "columns_changed": first(raw, "columns_changed", default=[]),
                        "breaking": bool(first(raw, "breaking", default=False)),
                    },
                    id_parts=[
                        tenant_id,
                        self.tool_id,
                        "schema",
                        dataset_id,
                        str(first(raw, "schema_version", "fingerprint", default="")),
                    ],
                )
            ]

        if "distrib" in event_hint or "null" in event_hint or event_hint in {"dataset.distribution.anomaly.v1"}:
            return [
                self.event(
                    event_type="dataset.distribution.anomaly.v1",
                    tenant_id=tenant_id,
                    occurred_at=first(raw, "occurred_at", "detected_at", "timestamp"),
                    connector_instance_id=connector_instance_id,
                    payload={
                        **base_payload,
                        "column": first(raw, "column", "column_name"),
                        "metric": first(raw, "metric", default="null_rate"),
                        "value": first(raw, "value", "metric_value", "null_rate"),
                        "baseline": first(raw, "baseline", "expected", "expected_baseline"),
                        "severity": first(raw, "severity", default="medium"),
                    },
                    id_parts=[
                        tenant_id,
                        self.tool_id,
                        "distribution",
                        dataset_id,
                        str(first(raw, "column", default="")),
                        str(first(raw, "window_id", default="")),
                    ],
                )
            ]

        if "lineage" in event_hint or event_hint in {"lineage.edge.upserted.v1"}:
            upstream = first(raw, "upstream", "source", "input", "upstream_dataset_id")
            downstream = first(raw, "downstream", "target", "output", "downstream_dataset_id", default=dataset_id)
            if not upstream:
                self.fail("lineage events require upstream/source")
            return [
                self.event(
                    event_type="lineage.edge.upserted.v1",
                    tenant_id=tenant_id,
                    occurred_at=first(raw, "occurred_at", "timestamp"),
                    connector_instance_id=connector_instance_id,
                    payload={
                        "upstream_dataset_id": upstream,
                        "downstream_dataset_id": downstream,
                        "confidence": first(raw, "confidence", default="observed"),
                        "transform": first(raw, "transform", "job", "pipeline_id"),
                        "platform": self.tool_id,
                    },
                    id_parts=[tenant_id, self.tool_id, "lineage", str(upstream), str(downstream)],
                )
            ]

        return [
            self.event(
                event_type="dataset.discovered.v1",
                tenant_id=tenant_id,
                occurred_at=first(raw, "occurred_at", "timestamp", "last_altered", "LAST_ALTERED"),
                connector_instance_id=connector_instance_id,
                payload={
                    **base_payload,
                    "row_count": first(raw, "row_count", "rows", "ROW_COUNT"),
                    "last_updated_at": first(raw, "last_updated_at", "last_altered", "LAST_ALTERED", "max_loaded_at"),
                    "owner": first(raw, "owner"),
                    "tags": first(raw, "tags", default=[]),
                },
                id_parts=[tenant_id, self.tool_id, "discovered", dataset_id],
            )
        ]
