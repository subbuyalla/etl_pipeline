"""Shared column validation helpers for warehouse connectors."""

from __future__ import annotations

from typing import Any


def parse_dataset_fqn(dataset_id: str) -> tuple[str, str, str]:
    """Parse DB.SCHEMA.TABLE (3-part) dataset id."""
    parts = [p.strip() for p in str(dataset_id or "").split(".") if p.strip()]
    if len(parts) != 3:
        raise ValueError(f"dataset_id must be DB.SCHEMA.TABLE, got {dataset_id!r}")
    return parts[0], parts[1], parts[2]


def quote_ident_double(name: str) -> str:
    return '"' + str(name or "").replace('"', '""') + '"'


def quote_ident_pg(name: str) -> str:
    return '"' + str(name or "").replace('"', '""') + '"'


def quote_ident_bq(name: str) -> str:
    return "`" + str(name or "").replace("`", "\\`") + "`"


def build_observed_result(
    *,
    check_type: str,
    parts: list[str],
    column_name: str,
    actual_value: int,
    expected_max: int = 0,
    source: str = "platform_sql",
) -> dict[str, Any]:
    ds = ".".join(p.upper() for p in parts)
    col = str(column_name or "").strip().upper()
    failure = max(0, int(actual_value) - int(expected_max))
    return {
        "check_type": check_type,
        "dataset_id": ds,
        "column_name": col,
        "expected_value": expected_max,
        "actual_value": int(actual_value),
        "failure_count": failure,
        "source": source,
    }


def run_column_validation_on_connector(
    connector: Any,
    *,
    dataset_id: str,
    column_name: str,
    check_type: str,
    custom_sql: str | None = None,
    expected_max: int = 0,
) -> dict[str, Any]:
    """Dispatch to connector.run_column_validation if present."""
    fn = getattr(connector, "run_column_validation", None)
    if not callable(fn):
        raise ValueError(f"Connector {type(connector).__name__} does not support column validation")
    return fn(
        dataset_id=dataset_id,
        column_name=column_name,
        check_type=check_type,
        custom_sql=custom_sql,
        expected_max=expected_max,
    )
