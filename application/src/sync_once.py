"""
Shared Sync-once path used by webhook API and manual trigger.
"""

from __future__ import annotations

import importlib.util
import os
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


def store_payload(run_log: dict, source_rows: list[dict], target_rows: list[dict]) -> dict:
    """Persist transformed payloads into Metadata MySQL."""
    store_mod = _load_module("app_meta_mysql", "application/src/store/meta_mysql.py")
    result = store_mod.store_to_meta_mysql(run_log, source_rows, target_rows)
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
    pipeline_id: str,
    pipeline_name: str = "stock_etl",
    dbt_run_id: str | None = None,
) -> dict[str, Any]:
    """
    Pull connectors → transform → store once.
    If dbt_run_id is set (from webhook), prefer that run envelope.
    """
    map_run_mod = _load_module("app_map_run", "application/src/transform/map_run.py")
    map_ds_mod = _load_module("app_map_dataset", "application/src/transform/map_dataset.py")
    dbt_mod = _load_module("app_dbt", "application/src/connectors/dbt.py")
    mysql_mod = _load_module("app_mysql", "application/src/connectors/mysql.py")
    sf_mod = _load_module("app_snowflake", "application/src/connectors/snowflake.py")

    dbt = dbt_mod.DbtConnector(
        tenant_id="demo",
        connector_instance_id="api-dbt-1",
        account_id="70506183151322",
        project_id="70506183153936",
        job_id="",
        project_name="analytics",
        api_base="https://li589.us1.dbt.com/api/v2",
    )
    mysql = mysql_mod.MysqlConnector(
        tenant_id="demo",
        connector_instance_id="api-mysql-source-1",
        host="database-1.cbsuuwi6y4bg.eu-north-1.rds.amazonaws.com",
        user="admin",
        database=os.getenv("DB_NAME", "metadata"),
        port=3306,
    )
    snowflake = sf_mod.SnowflakeConnector(
        tenant_id="demo",
        connector_instance_id="api-snowflake-target-1",
        account_id="jd97000.ap-southeast-7.aws",
        user_id="Sasi9392",
        warehouse_id="COMPUTE_WH",
        database_id="ANALYTICS_DB",
        role="ACCOUNTADMIN",
    )

    dbt_envs = dbt.pull_state()
    mysql_envs = mysql.pull_state()
    sf_envs = snowflake.pull_state()

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
        pipeline_id=pipeline_id,
        pipeline_name=pipeline_name,
    )
    run_id = run_log["id"]
    source_rows = [
        map_ds_mod.map_dataset(env, run_id=run_id, asset_role="SOURCE")
        for env in mysql_envs
    ]
    target_rows = [
        map_ds_mod.map_dataset(env, run_id=run_id, asset_role="TARGET")
        for env in sf_envs
    ]

    store_result = store_payload(run_log, source_rows, target_rows)

    return {
        "ok": True,
        "message": "Sync completed and stored in Metadata MySQL",
        "pipeline_id": pipeline_id,
        "run_id": run_id,
        "status": run_log.get("status"),
        "source_count": len(source_rows),
        "target_count": len(target_rows),
        "stored": True,
        "store": store_result,
    }
