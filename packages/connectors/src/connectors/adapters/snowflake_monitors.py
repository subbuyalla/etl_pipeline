from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def _parse_ts(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value).strip()
    if not text:
        return None
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        dt = datetime.fromisoformat(text)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def build_table_monitor_events(
    row: dict[str, Any],
    *,
    now: datetime | None = None,
    freshness_sla_minutes: int = 60,
    volume_min_rows: int | None = 1,
) -> list[dict[str, Any]]:
    """
    From a catalog row (database/schema/table/row_count/last_altered), emit
    discovered plus optional freshness/volume breach payloads for WarehouseMapper.
    """
    database = row.get("database")
    schema = row.get("schema")
    table = row.get("table")
    dataset_id = row.get("dataset_id") or f"{database}.{schema}.{table}"
    last_altered = row.get("last_altered") or row.get("last_updated_at")
    row_count = row.get("row_count")

    events: list[dict[str, Any]] = [
        {
            "event_type": "discovered",
            "database": database,
            "schema": schema,
            "table": table,
            "dataset_id": dataset_id,
            "row_count": row_count,
            "last_altered": last_altered,
        }
    ]

    ts = _parse_ts(last_altered)
    clock = now or datetime.now(timezone.utc)
    if ts is not None and freshness_sla_minutes > 0:
        lag_minutes = max(0, int((clock - ts).total_seconds() // 60))
        if lag_minutes > freshness_sla_minutes:
            events.append(
                {
                    "event_type": "freshness",
                    "database": database,
                    "schema": schema,
                    "table": table,
                    "dataset_id": dataset_id,
                    "last_altered": last_altered,
                    "last_updated_at": last_altered,
                    "sla_minutes": freshness_sla_minutes,
                    "lag_minutes": lag_minutes,
                    "severity": "high" if lag_minutes > freshness_sla_minutes * 2 else "medium",
                }
            )

    if volume_min_rows is not None and row_count is not None:
        try:
            count_i = int(row_count)
        except (TypeError, ValueError):
            count_i = None
        if count_i is not None and count_i < int(volume_min_rows):
            events.append(
                {
                    "event_type": "volume",
                    "database": database,
                    "schema": schema,
                    "table": table,
                    "dataset_id": dataset_id,
                    "row_count": count_i,
                    "expected_min": int(volume_min_rows),
                    "severity": "high" if count_i == 0 else "medium",
                }
            )

    return events
