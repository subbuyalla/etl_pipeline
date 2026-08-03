"""
Automatic Sync loop (replaces manual Sync clicks/scripts).

Flow every N seconds:
  1) dbt / mysql / snowflake pull_state()
  2) transform → run log + source/target metadata
  3) store hook (print for now — wire Metadata DB next)

Run from repo root:
  python application/auto_sync.py

Env (optional):
  SYNC_INTERVAL_SECONDS=300
  PIPELINE_ID=   (reuse a UUID; if empty, creates one and prints it)
  PIPELINE_NAME=stock_etl
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "application" / "src"))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")


def _load_module(module_name: str, relative: str):
    path = ROOT / relative
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def store_payload(run_log: dict, source_rows: list[dict], target_rows: list[dict]) -> None:
    """
    Automatic store step.
    MVP: print. Next: INSERT into Metadata MySQL.
    """
    print("--- STORE (auto) ---")
    print("run:", run_log.get("id"), "status=", run_log.get("status"), "pipeline_id=", run_log.get("pipeline_id"))
    print("source tables:", len(source_rows), "target tables:", len(target_rows))
    # Keep one sample line so you can see it working
    if source_rows:
        print("  source sample:", source_rows[0].get("dataset_id") or source_rows[0].get("object_name"))
    if target_rows:
        print("  target sample:", target_rows[0].get("dataset_id") or target_rows[0].get("object_name"))


def run_once(
    *,
    dbt,
    mysql,
    snowflake,
    map_run,
    map_dataset,
    pipeline_id: str,
    pipeline_name: str,
) -> None:
    print("\n=== AUTO SYNC tick ===", time.strftime("%Y-%m-%d %H:%M:%S"))

    dbt_envs = dbt.pull_state()
    mysql_envs = mysql.pull_state()
    sf_envs = snowflake.pull_state()

    print(f"pulled: dbt_runs={len(dbt_envs)} mysql_tables={len(mysql_envs)} snowflake_tables={len(sf_envs)}")

    if not dbt_envs:
        print("No dbt runs yet — skip transform/store this tick.")
        return

    # Newest run first (dbt connector already orders by -id)
    run_log = map_run(
        dbt_envs[0],
        pipeline_id=pipeline_id,
        pipeline_name=pipeline_name,
    )
    run_id = run_log["id"]

    source_rows = [
        map_dataset(env, run_id=run_id, asset_role="SOURCE") for env in mysql_envs
    ]
    target_rows = [
        map_dataset(env, run_id=run_id, asset_role="TARGET") for env in sf_envs
    ]

    store_payload(run_log, source_rows, target_rows)


def main() -> None:
    interval = int(os.getenv("SYNC_INTERVAL_SECONDS", "300"))
    pipeline_name = os.getenv("PIPELINE_NAME", "stock_etl")

    map_run_mod = _load_module("app_map_run", "application/src/transform/map_run.py")
    map_ds_mod = _load_module("app_map_dataset", "application/src/transform/map_dataset.py")
    dbt_mod = _load_module("app_dbt", "application/src/connectors/dbt.py")
    mysql_mod = _load_module("app_mysql", "application/src/connectors/mysql.py")
    sf_mod = _load_module("app_snowflake", "application/src/connectors/snowflake.py")

    pipeline_id = (os.getenv("PIPELINE_ID") or "").strip() or map_run_mod.new_pipeline_id()
    print("Automatic Sync started.")
    print(f"  interval={interval}s")
    print(f"  pipeline_id={pipeline_id}")
    print(f"  pipeline_name={pipeline_name}")
    print("  Tip: set PIPELINE_ID in .env to reuse the same UUID.")
    print("  Ctrl+C to stop.\n")

    dbt = dbt_mod.DbtConnector(
        tenant_id="demo",
        connector_instance_id="auto-dbt-1",
        account_id="70506183151322",
        project_id="70506183153936",
        job_id="",
        project_name="analytics",
        api_base="https://li589.us1.dbt.com/api/v2",
    )
    mysql = mysql_mod.MysqlConnector(
        tenant_id="demo",
        connector_instance_id="auto-mysql-source-1",
        host="database-1.cbsuuwi6y4bg.eu-north-1.rds.amazonaws.com",
        user="admin",
        database=os.getenv("DB_NAME", "metadata"),
        port=3306,
    )
    snowflake = sf_mod.SnowflakeConnector(
        tenant_id="demo",
        connector_instance_id="auto-snowflake-target-1",
        account_id="jd97000.ap-southeast-7.aws",
        user_id="Sasi9392",
        warehouse_id="COMPUTE_WH",
        database_id="ANALYTICS_DB",
        role="ACCOUNTADMIN",
    )

    while True:
        try:
            run_once(
                dbt=dbt,
                mysql=mysql,
                snowflake=snowflake,
                map_run=map_run_mod.map_run,
                map_dataset=map_ds_mod.map_dataset,
                pipeline_id=pipeline_id,
                pipeline_name=pipeline_name,
            )
        except Exception as exc:
            print("AUTO SYNC error:", exc)
        time.sleep(interval)


if __name__ == "__main__":
    main()
