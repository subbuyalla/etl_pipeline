"""Shared column validation helpers for warehouse connectors."""

from __future__ import annotations

from typing import Any


def parse_dataset_fqn(dataset_id: str) -> tuple[str, str, str]:
    """Parse DB.SCHEMA.TABLE (3-part) or DB.TABLE (2-part) dataset id."""
    parts = [p.strip() for p in str(dataset_id or "").split(".") if p.strip()]
    if len(parts) == 2:
        return parts[0], "", parts[1]
    if len(parts) != 3:
        raise ValueError(f"dataset_id must be DB.SCHEMA.TABLE or DB.TABLE, got {dataset_id!r}")
    return parts[0], parts[1], parts[2]


def quote_ident_double(name: str) -> str:
    return '"' + str(name or "").replace('"', '""') + '"'


def quote_ident_pg(name: str) -> str:
    return '"' + str(name or "").replace('"', '""') + '"'


def quote_ident_bq(name: str) -> str:
    return "`" + str(name or "").replace("`", "\\`") + "`"


def quote_ident_mysql(name: str) -> str:
    return "`" + str(name or "").replace("`", "``") + "`"


def build_observed_result(
    *,
    check_type: str,
    parts: list[str],
    column_name: str,
    actual_value: int | float,
    expected_max: int | float = 0,
    source: str = "platform_sql",
    total_rows: int | None = None,
    null_count: int | None = None,
    null_rate: float | None = None,
    distinct_count: int | None = None,
    unique_rate: float | None = None,
    blank_count: int | None = None,
    non_null_rate: float | None = None,
    rate_pct: float | None = None,
) -> dict[str, Any]:
    ds = ".".join(p.upper() for p in parts if p)
    col = str(column_name or "").strip().upper()
    diff = float(actual_value) - float(expected_max)
    failure = max(0, int(round(diff))) if diff > 0 else 0
    res: dict[str, Any] = {
        "check_type": check_type,
        "dataset_id": ds,
        "column_name": col,
        "expected_value": expected_max,
        "actual_value": actual_value,
        "failure_count": failure,
        "source": source,
    }
    if total_rows is not None:
        res["total_rows"] = int(total_rows)
    if null_count is not None:
        res["null_count"] = int(null_count)
    if null_rate is not None:
        res["null_rate"] = round(float(null_rate), 2)
    if distinct_count is not None:
        res["distinct_count"] = int(distinct_count)
    if unique_rate is not None:
        res["unique_rate"] = round(float(unique_rate), 2)
    if blank_count is not None:
        res["blank_count"] = int(blank_count)
    if non_null_rate is not None:
        res["non_null_rate"] = round(float(non_null_rate), 2)
    if rate_pct is not None:
        res["rate_pct"] = round(float(rate_pct), 2)
    return res


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
