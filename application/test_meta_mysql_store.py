"""
Test Metadata MySQL store (application/src/store/meta_mysql.py).

Run from repo root:
  python application/test_meta_mysql_store.py
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")


def _load(name: str, relative: str):
    path = ROOT / relative
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main() -> None:
    store = _load("app_meta_mysql", "application/src/store/meta_mysql.py")
    map_run = _load("app_map_run", "application/src/transform/map_run.py")
    map_ds = _load("app_map_dataset", "application/src/transform/map_dataset.py")

    pipeline_id = map_run.new_pipeline_id()
    dbt_envelope = {
        "source_system": "dbt",
        "tenant_id": "demo",
        "connector_instance_id": "store-test-dbt",
        "raw": {
            "event_type": "run",
            "project_name": "analytics",
            "run_id": "store-test-run-001",
            "job_id": "job-1",
            "status": "succeeded",
            "started_at": "2026-07-22T08:00:00Z",
            "finished_at": "2026-07-22T08:05:00Z",
            "error_message": "",
        },
    }
    source_envelope = {
        "source_system": "mysql",
        "tenant_id": "demo",
        "connector_instance_id": "store-test-mysql",
        "raw": {
            "event_type": "discovered",
            "database": "ecommerce",
            "schema": "ecommerce",
            "table": "orders",
            "dataset_id": "ecommerce.orders",
            "row_count": 100,
            "last_altered": "2026-07-22T08:00:00Z",
        },
    }
    target_envelope = {
        "source_system": "snowflake",
        "tenant_id": "demo",
        "connector_instance_id": "store-test-sf",
        "raw": {
            "event_type": "discovered",
            "database": "ANALYTICS_DB",
            "schema": "RAW",
            "table": "STOCK_DATA_RAW",
            "dataset_id": "ANALYTICS_DB.RAW.STOCK_DATA_RAW",
            "row_count": 165,
            "last_altered": "2026-07-23T22:37:19",
        },
    }

    run_log = map_run.map_run(
        dbt_envelope,
        pipeline_id=pipeline_id,
        pipeline_name="stock_etl",
    )
    run_id = run_log["id"]
    sources = [map_ds.map_dataset(source_envelope, run_id=run_id, asset_role="SOURCE")]
    targets = [map_ds.map_dataset(target_envelope, run_id=run_id, asset_role="TARGET")]

    print("Writing to Metadata MySQL...")
    result = store.store_to_meta_mysql(run_log, sources, targets)
    print(result)

    # read back
    conn = store.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id, pipeline_id, status FROM obs_pipeline_runs WHERE id=%s", (run_id,))
            print("run row:", cur.fetchone())
            cur.execute(
                "SELECT asset_role, dataset_id, system_name FROM obs_run_assets WHERE run_id=%s",
                (run_id,),
            )
            print("asset rows:", cur.fetchall())
    finally:
        conn.close()

    print("Done. Data is in metadata.obs_pipeline_runs / metadata.obs_run_assets")


if __name__ == "__main__":
    main()
