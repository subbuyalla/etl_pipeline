from __future__ import annotations

from typing import Any, Optional


def _fmt_num(value: Any) -> str | None:
    if value is None or value == "":
        return None
    try:
        f = float(value)
        if f == int(f):
            return f"{int(f):,}"
        return f"{f:,.2f}"
    except (TypeError, ValueError):
        return str(value)


def distribution_title(dataset_id: str, column: Optional[str]) -> str:
    col = (column or "").strip()
    if col and col.lower() not in {"none", "null", "nan"}:
        return f"Distribution anomaly: {dataset_id}.{col}"
    return f"Distribution anomaly: {dataset_id}"


def freshness_message(lag_minutes: Any, sla_minutes: Any = None) -> str:
    lag = _fmt_num(lag_minutes)
    sla = _fmt_num(sla_minutes)
    if lag and sla:
        return f"Data is {lag} minutes late (SLA: {sla} minutes)."
    if lag:
        return f"Data is {lag} minutes late."
    return "Data did not refresh within the expected time window."


def volume_message(row_count: Any, expected_min: Any = None, expected_max: Any = None) -> str:
    rows = _fmt_num(row_count)
    lo = _fmt_num(expected_min)
    hi = _fmt_num(expected_max)
    if rows and lo:
        return f"Row count is {rows}, below expected minimum of {lo}."
    if rows and hi:
        return f"Row count is {rows}, above expected maximum of {hi}."
    if rows:
        return f"Row count ({rows} rows) looks unusual."
    return "Row count looks unusual compared to recent history."


def distribution_message(
    metric: Optional[str],
    value: Any,
    baseline: Any = None,
    column: Optional[str] = None,
) -> str:
    label = (metric or "null_rate").replace("_", " ")
    val = _fmt_num(value)
    base = _fmt_num(baseline)
    col = (column or "").strip()
    col_part = f" on column {col}" if col and col.lower() not in {"none", "null", "nan"} else ""
    if val and base:
        return f"{label.title()}{col_part} is {val} (baseline ~{base})."
    if val:
        return f"{label.title()}{col_part} is {val}, which looks abnormal."
    return f"{label.title()}{col_part} looks abnormal compared to baseline."
