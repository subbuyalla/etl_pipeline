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
) -> dict:
    """Persist transformed payloads into Metadata MySQL."""
    store_mod = _load_module("app_meta_mysql", "application/src/store/meta_mysql.py")
    result = store_mod.store_to_meta_mysql(
        run_log, source_rows, target_rows, pipeline=pipeline
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
    map_ds_mod = _load_module("app_map_dataset", "application/src/transform/map_dataset.py")
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
    sf_source = sf_mod.SnowflakeConnector(
        tenant_id=pipeline.get("tenant_id") or "demo",
        connector_instance_id=source_cfg["connector_instance_id"],
        account_id=source_cfg["account_id"],
        user_id=source_cfg["user_id"],
        warehouse_id=source_cfg["warehouse_id"],
        database_id=source_cfg["database_id"],
        role=source_cfg.get("sf_role") or "ACCOUNTADMIN",
        schema=source_cfg.get("schema") or "RAW",
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
    )

    dbt_envs = dbt.pull_state()
    source_envs = sf_source.pull_state()
    target_envs = sf_target.pull_state()

    if not dbt_envs:
        return {"ok": False, "message": "No dbt runs found", "stored": False}

    chosen = dbt_envs[0]
    if dbt_run_id:
        for env in dbt_envs:
            if str((env.get("raw") or {}).get("run_id")) == str(dbt_run_id):
                chosen = env
                break

    run_log = map_run_mod.map_run(
        chosen,
        pipeline_id=pipeline["pipeline_id"],
        pipeline_name=pipeline.get("pipeline_name") or "stock_etl",
    )
    run_id = run_log["id"]
    source_rows = [
        map_ds_mod.map_dataset(env, run_id=run_id, asset_role="SOURCE")
        for env in source_envs
    ]
    target_rows = [
        map_ds_mod.map_dataset(env, run_id=run_id, asset_role="TARGET")
        for env in target_envs
    ]

    # dbt artifacts often report rows_affected=0 for CTAS/views.
    # Fall back to Snowflake INFORMATION_SCHEMA row_count from this Sync.
    src_total = sum(int(r.get("row_count") or 0) for r in source_rows)
    tgt_total = sum(int(r.get("row_count") or 0) for r in target_rows)
    if run_log.get("rows_read") in (None, 0) and src_total:
        run_log["rows_read"] = src_total
    if run_log.get("rows_written") in (None, 0) and tgt_total:
        run_log["rows_written"] = tgt_total

    store_result = store_payload(run_log, source_rows, target_rows, pipeline=pipeline)

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
        "run_id": run_id,
        "status": run_log.get("status"),
        "source_count": len(source_rows),
        "target_count": len(target_rows),
        "stored": True,
        "store": store_result,
    }
