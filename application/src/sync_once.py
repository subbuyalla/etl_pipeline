"""
Shared Sync-once path used by webhook API and manual trigger.

Pipeline: Snowflake (RAW) -> dbt Cloud -> Snowflake (staging)
pipeline_id / attach config are loaded from Metadata MySQL (obs_pipelines).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]


def _load_module(module_name: str, relative: str):
    path = ROOT / relative
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _normalize_tables(raw: Any) -> list[str]:
    if not raw:
        return []
    if isinstance(raw, str):
        return [p.strip().upper() for p in raw.split(",") if p.strip()]
    if isinstance(raw, (list, tuple)):
        return [str(p).strip().upper() for p in raw if str(p).strip()]
    return []


def _resolve_table_filter(
    configured: list[str],
    dbt_relation_names: list[str],
) -> list[str]:
    """
    Prefer explicit pipeline config tables; else dbt relation short names;
    else empty (full schema).
    """
    if configured:
        return configured
    return list(dbt_relation_names or [])


def _resolve_pipeline(
    *,
    pipeline_id: str | None = None,
    pipeline_name: str | None = None,
) -> dict[str, Any]:
    """Prefer DB row; create template only if DB has no matching pipeline yet."""
    store_mod = _load_module("app_meta_mysql", "application/src/store/meta_mysql.py")
    pipe_mod = _load_module("app_pipelines", "application/src/pipelines.py")

    if pipeline_id:
        found = store_mod.get_pipeline_by_id(pipeline_id)
        if found and found.get("source") and found["source"].get("account_id"):
            return found
        template = pipe_mod.get_pipeline_template(
            pipeline_name, pipeline_id=pipeline_id
        )
        if pipeline_name:
            template["pipeline_name"] = pipeline_name
        return template

    if pipeline_name:
        found = store_mod.get_pipeline_by_name(pipeline_name)
        if found and found.get("source") and found["source"].get("account_id"):
            return found
        template = pipe_mod.get_pipeline_template(pipeline_name)
        store_mod.upsert_pipeline(template, make_active=False)
        return template

    active = store_mod.get_active_pipeline()
    if active and active.get("source") and active["source"].get("account_id"):
        return active

    # First-time: build stock template, save as active in DB
    template = pipe_mod.get_stock_etl_pipeline()
    store_mod.upsert_pipeline(template, make_active=True)
    return template


def _resolve_dbt_token(etl_cfg: dict) -> str | None:
    """Per-pipeline dbt token: explicit api_token, else api_token_env, else default env."""
    import os

    if etl_cfg.get("api_token"):
        return str(etl_cfg["api_token"])
    env_name = (etl_cfg.get("api_token_env") or "DBT_CLOUD_API_TOKEN").strip()
    return os.getenv(env_name) or os.getenv("DBT_CLOUD_API_TOKEN") or None


def store_payload(
    run_log: dict,
    source_rows: list[dict],
    target_rows: list[dict],
    pipeline: dict | None = None,
    columns: list[dict] | None = None,
    query_history: list[dict] | None = None,
) -> dict:
    """Persist transformed payloads into Metadata MySQL."""
    store_mod = _load_module("app_meta_mysql", "application/src/store/meta_mysql.py")
    result = store_mod.store_to_meta_mysql(
        run_log,
        source_rows,
        target_rows,
        pipeline=pipeline,
        columns=columns,
        query_history=query_history,
    )
    print(
        "STORE MySQL ok=",
        result.get("ok"),
        "run=",
        result.get("run_id"),
        "sources=",
        result.get("sources_stored"),
        "targets=",
        result.get("targets_stored"),
        "columns=",
        result.get("columns_stored"),
        "qh=",
        result.get("query_history_stored"),
        "tables=",
        result.get("tables"),
    )
    return result


def run_sync_once(
    *,
    pipeline_id: str | None = None,
    pipeline_name: str | None = None,
    dbt_run_id: str | None = None,
) -> dict[str, Any]:
    """
    Load active pipeline from DB → pull connectors → transform → store.
    """
    map_run_mod = _load_module("app_map_run", "application/src/transform/map_run.py")
    map_ds_mod = _load_module(
        "app_map_dataset", "application/src/transform/map_dataset.py"
    )
    dbt_mod = _load_module("app_dbt", "application/src/connectors/dbt.py")
    sf_mod = _load_module("app_snowflake", "application/src/connectors/snowflake.py")

    pipeline = _resolve_pipeline(pipeline_id=pipeline_id, pipeline_name=pipeline_name)
    source_cfg = pipeline["source"]
    etl_cfg = pipeline["etl"]
    target_cfg = pipeline["target"]

    dbt = dbt_mod.DbtConnector(
        tenant_id=pipeline.get("tenant_id") or "demo",
        connector_instance_id=etl_cfg["connector_instance_id"],
        account_id=etl_cfg["account_id"],
        project_id=etl_cfg.get("project_id") or "",
        job_id=etl_cfg.get("job_id") or "",
        project_name=etl_cfg.get("project_name") or "analytics",
        api_base=etl_cfg.get("api_base") or "https://li589.us1.dbt.com/api/v2",
        api_token=_resolve_dbt_token(etl_cfg),
    )

    dbt_envs = dbt.pull_state()
    if not dbt_envs:
        return {"ok": False, "message": "No dbt runs found", "stored": False}

    chosen = dbt_envs[0]
    if dbt_run_id:
        for env in dbt_envs:
            if str((env.get("raw") or {}).get("run_id")) == str(dbt_run_id):
                chosen = env
                break

    chosen_raw = chosen.get("raw") or {}
    dbt_table_names = dbt_mod.relation_short_names(chosen_raw.get("relations") or [])

    # SOURCE: only explicit config (dbt relations are usually models/targets, not RAW tables).
    source_tables = _normalize_tables(source_cfg.get("tables"))
    # TARGET: config first, else dbt relation short names, else full schema.
    target_tables = _resolve_table_filter(
        _normalize_tables(target_cfg.get("tables")),
        dbt_table_names,
    )

    sf_source = sf_mod.SnowflakeConnector(
        tenant_id=pipeline.get("tenant_id") or "demo",
        connector_instance_id=source_cfg["connector_instance_id"],
        account_id=source_cfg["account_id"],
        user_id=source_cfg["user_id"],
        warehouse_id=source_cfg["warehouse_id"],
        database_id=source_cfg["database_id"],
        role=source_cfg.get("sf_role") or "ACCOUNTADMIN",
        schema=source_cfg.get("schema") or "RAW",
        tables=source_tables or None,
    )
    sf_target = sf_mod.SnowflakeConnector(
        tenant_id=pipeline.get("tenant_id") or "demo",
        connector_instance_id=target_cfg["connector_instance_id"],
        account_id=target_cfg["account_id"],
        user_id=target_cfg["user_id"],
        warehouse_id=target_cfg["warehouse_id"],
        database_id=target_cfg["database_id"],
        role=target_cfg.get("sf_role") or "ACCOUNTADMIN",
        schema=target_cfg.get("schema") or "STAGING_STAGING",
        tables=target_tables or None,
    )

    source_envs = sf_source.pull_state()
    target_envs = sf_target.pull_state()

    # Column catalogs for schema-diff RCA (best-effort).
    source_cols_raw = []
    target_cols_raw = []
    try:
        source_cols_raw = sf_source.fetch_columns(source_tables or None) or []
    except Exception as exc:
        print("WARN source columns:", exc)
    try:
        target_cols_raw = sf_target.fetch_columns(target_tables or None) or []
    except Exception as exc:
        print("WARN target columns:", exc)

    run_log = map_run_mod.map_run(
        chosen,
        pipeline_id=pipeline["pipeline_id"],
        pipeline_name=pipeline.get("pipeline_name") or "stock_etl",
    )
    run_id = run_log["id"]

    # column_count per table from catalogs
    def _col_counts(cols: list[dict]) -> dict[str, int]:
        out: dict[str, int] = {}
        for c in cols:
            key = (c.get("dataset_id") or "").upper()
            if not key:
                key = (
                    f"{c.get('database')}.{c.get('schema')}.{c.get('table')}"
                ).upper()
            out[key] = out.get(key, 0) + 1
        return out

    src_counts = _col_counts(source_cols_raw)
    tgt_counts = _col_counts(target_cols_raw)

    source_rows = []
    for env in source_envs:
        ds = map_ds_mod.map_dataset(env, run_id=run_id, asset_role="SOURCE")
        did = (ds.get("dataset_id") or "").upper()
        if did in src_counts:
            ds["column_count"] = src_counts[did]
        source_rows.append(ds)
    target_rows = []
    for env in target_envs:
        ds = map_ds_mod.map_dataset(env, run_id=run_id, asset_role="TARGET")
        did = (ds.get("dataset_id") or "").upper()
        if did in tgt_counts:
            ds["column_count"] = tgt_counts[did]
        target_rows.append(ds)

    columns_rows: list[dict] = []
    for c in source_cols_raw:
        columns_rows.append({**c, "asset_role": "SOURCE"})
    for c in target_cols_raw:
        columns_rows.append({**c, "asset_role": "TARGET"})

    # Prefer filtered Snowflake table sizes for read/write (correct grain).
    # Keep dbt artifact totals only when Snowflake returned nothing.
    src_total = sum(int(r.get("row_count") or 0) for r in source_rows)
    tgt_total = sum(int(r.get("row_count") or 0) for r in target_rows)
    if source_rows:
        run_log["rows_read"] = src_total
    elif run_log.get("rows_read") in (None, 0) and src_total:
        run_log["rows_read"] = src_total
    if target_rows:
        run_log["rows_written"] = tgt_total
    elif run_log.get("rows_written") in (None, 0) and tgt_total:
        run_log["rows_written"] = tgt_total

    # Query history for failed runs (warehouse SQL errors beyond dbt message).
    query_history: list[dict] = []
    if str(run_log.get("status") or "").lower() == "failed":
        try:
            query_history = (
                sf_target.fetch_query_history(
                    hours_back=48, limit=25, errors_only=True
                )
                or []
            )
        except Exception as exc:
            print("WARN query history:", exc)

    store_result = store_payload(
        run_log,
        source_rows,
        target_rows,
        pipeline=pipeline,
        columns=columns_rows,
        query_history=query_history,
    )

    return {
        "ok": True,
        "message": "Sync completed (pipeline loaded from DB)",
        "pipeline_id": pipeline["pipeline_id"],
        "pipeline_name": pipeline.get("pipeline_name"),
        "pipeline_from": "metadata.obs_pipelines",
        "attachments": {
            "source": f"snowflake/{source_cfg.get('schema')}",
            "etl": "dbt",
            "target": f"snowflake/{target_cfg.get('schema')}",
        },
        "table_filters": {
            "source": source_tables,
            "target": target_tables,
        },
        "run_id": run_id,
        "status": run_log.get("status"),
        "source_count": len(source_rows),
        "target_count": len(target_rows),
        "rows_read": run_log.get("rows_read"),
        "rows_written": run_log.get("rows_written"),
        "stored": True,
        "store": store_result,
    }
