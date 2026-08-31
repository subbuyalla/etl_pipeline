"""
Transform: Snowflake / MySQL envelope → colleague source or target metadata.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

AssetRole = Literal["SOURCE", "TARGET"]

_SYSTEM = {
    "snowflake": {"system_name": "Snowflake", "system_type": "DATA_WAREHOUSE"},
    "mysql": {"system_name": "MySQL", "system_type": "DATABASE"},
    "postgres": {"system_name": "PostgreSQL", "system_type": "DATABASE"},
    "postgresql": {"system_name": "PostgreSQL", "system_type": "DATABASE"},
    "redshift": {"system_name": "Redshift", "system_type": "DATA_WAREHOUSE"},
    "bigquery": {"system_name": "BigQuery", "system_type": "DATA_WAREHOUSE"},
}


def map_dataset(
    envelope: dict,
    *,
    run_id: str,
    asset_role: AssetRole,
    column_count: int | None = None,
    size_bytes: int | None = None,
    observed_at: str | None = None,
) -> dict:
    """
    Map one DB Sync envelope to source/target metadata.

    run_id links this table snapshot to a pipeline run log.
    asset_role comes from pipeline attach (SOURCE vs TARGET), not from Snowflake itself.
    """
    raw = envelope.get("raw") or {}
    source_system = (envelope.get("source_system") or "").lower()
    system = _SYSTEM.get(
        source_system,
        {
            "system_name": source_system or "Unknown",
            "system_type": "DATABASE",
        },
    )

    database_name = raw.get("database")
    schema_name = raw.get("schema")
    object_name = raw.get("table")

    return {
        "run_id": run_id,
        "asset_role": asset_role,
        "system_name": system["system_name"],
        "system_type": system["system_type"],
        "database_name": database_name,
        "schema_name": schema_name,
        "object_name": object_name,
        "object_type": raw.get("object_type") or "TABLE",
        "row_count": raw.get("row_count"),
        "column_count": column_count,  # optional; add later from INFORMATION_SCHEMA.COLUMNS
        "size_bytes": size_bytes if size_bytes is not None else raw.get("size_bytes"),
        "last_updated_at": raw.get("last_altered"),
        "observed_at": observed_at
        or datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "tenant_id": envelope.get("tenant_id"),
        "connector_instance_id": envelope.get("connector_instance_id"),
        "dataset_id": raw.get("dataset_id"),
    }


def map_datasets(
    envelopes: list[dict],
    *,
    run_id: str,
    asset_role: AssetRole,
    **kwargs: Any,
) -> list[dict]:
    return [
        map_dataset(env, run_id=run_id, asset_role=asset_role, **kwargs)
        for env in envelopes
    ]
