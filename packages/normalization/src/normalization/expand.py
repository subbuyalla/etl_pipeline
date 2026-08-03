from __future__ import annotations

from typing import Any


LIST_WRAPPER_KEYS = (
    "dag_runs",
    "task_instances",
    "JobRuns",
    "jobRuns",
    "value",
    "data",
    "items",
    "results",
    "Records",
    "rows",
    "runs",
    "executions",
    "activities",
    "tables",
    "Nodes",
    "entries",
    "workbooks",
    "views",
    "dashboards",
    "datasets",
)


def as_records(raw: dict[str, Any] | list[Any]) -> list[dict[str, Any]]:
    """
    Unwrap common vendor list envelopes into a list of record dicts.

    Supports:
      { "dag_runs": [ {...}, ... ] }
      { "JobRuns": [ {...} ] }
      { "results": [ {...} ] }          # dbt
      { "data": [ {...} ] } / { "value": [ {...} ] }
      single object { ... }
      already a list
    """
    if isinstance(raw, list):
        return [r for r in raw if isinstance(r, dict)]

    if not isinstance(raw, dict):
        return []

    for key in LIST_WRAPPER_KEYS:
        if key in raw and isinstance(raw[key], list):
            records = [r for r in raw[key] if isinstance(r, dict)]
            if records:
                # Attach parent metadata useful for dbt / airflow
                meta = {k: v for k, v in raw.items() if k != key and not isinstance(v, (list, dict))}
                nested_meta = raw.get("metadata") if isinstance(raw.get("metadata"), dict) else {}
                enriched = []
                for rec in records:
                    merged = {**meta, **nested_meta, **rec}
                    # Keep nested metadata accessible
                    if nested_meta and "metadata" not in rec:
                        merged["_parent_metadata"] = nested_meta
                    enriched.append(merged)
                return enriched

    # Airflow nested: { "dag_run": { ... } }
    for key in ("dag_run", "task_instance", "JobRun", "run", "execution", "table", "record"):
        if key in raw and isinstance(raw[key], dict):
            return [{**{k: v for k, v in raw.items() if k != key}, **raw[key]}]

    return [raw]


def flatten_dotted(raw: dict[str, Any]) -> dict[str, Any]:
    """Copy top-level keys; also expose nested conf/state objects as flat aliases."""
    out = dict(raw)
    for nest_key in ("conf", "state", "status", "attributes", "properties"):
        nested = raw.get(nest_key)
        if isinstance(nested, dict):
            for k, v in nested.items():
                out.setdefault(k, v)
                out.setdefault(f"{nest_key}.{k}", v)
        elif nested is not None and nest_key == "state" and "state" not in out:
            out["state"] = nested
    # Prefect: state: { type: COMPLETED, name: Completed }
    state_obj = raw.get("state")
    if isinstance(state_obj, dict):
        out.setdefault("state_name", state_obj.get("name") or state_obj.get("type"))
        out.setdefault("status", state_obj.get("name") or state_obj.get("type"))
    return out
