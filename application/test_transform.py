"""
Test transform layer (application/src/transform/).

Maps YOUR connector envelopes → colleague JSON shapes:
  - pipeline run log
  - source metadata
  - target metadata

Run from repo root:
  python application/test_transform.py
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TRANSFORM_DIR = ROOT / "application" / "src" / "transform"
sys.path.insert(0, str(TRANSFORM_DIR.parent))  # so `import transform` works


def _load(name: str, file: str):
    path = TRANSFORM_DIR / file
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main() -> None:
    map_run_mod = _load("app_map_run", "map_run.py")
    map_ds_mod = _load("app_map_dataset", "map_dataset.py")
    map_run = map_run_mod.map_run
    map_dataset = map_ds_mod.map_dataset

    # --- sample envelopes (same shape your connectors already return) ---
    dbt_envelope = {
        "source_system": "dbt",
        "tenant_id": "demo",
        "connector_instance_id": "app-dbt-test-1",
        "raw": {
            "event_type": "run",
            "project_name": "analytics",
            "run_id": "70506183553987",
            "job_id": "70506183135814",
            "status": "succeeded",
            "started_at": "2026-07-22T08:00:00Z",
            "finished_at": "2026-07-22T08:05:00Z",
            "error_message": "",
        },
    }

    source_envelope = {
        "source_system": "mysql",
        "tenant_id": "demo",
        "connector_instance_id": "app-mysql-source-1",
        "raw": {
            "event_type": "discovered",
            "database": "ecommerce",
            "schema": "ecommerce",
            "table": "orders",
            "dataset_id": "ecommerce.orders",
            "row_count": 500000,
            "last_altered": "2026-07-22T08:00:00Z",
        },
    }

    target_envelope = {
        "source_system": "snowflake",
        "tenant_id": "demo",
        "connector_instance_id": "app-snowflake-target-1",
        "raw": {
            "event_type": "discovered",
            "database": "ANALYTICS_DB",
            "schema": "RAW",
            "table": "STOCK_DATA_RAW",
            "dataset_id": "ANALYTICS_DB.RAW.STOCK_DATA_RAW",
            "row_count": 165,
            "last_altered": "2026-07-23T22:37:19.747000-07:00",
        },
    }

    # Create pipeline_id once (UUID), then reuse for every run of that pipeline.
    pipeline_id = map_run_mod.new_pipeline_id()

    run_log = map_run(
        dbt_envelope,
        pipeline_id=pipeline_id,
        pipeline_name="stock_etl",
    )
    run_id = run_log["id"]

    source_meta = map_dataset(
        source_envelope,
        run_id=run_id,
        asset_role="SOURCE",
    )
    target_meta = map_dataset(
        target_envelope,
        run_id=run_id,
        asset_role="TARGET",
    )

    print("=== 1) Pipeline run log (from dbt) ===")
    print(json.dumps(run_log, indent=2, default=str))

    print("\n=== 2) Source metadata (from MySQL) ===")
    print(json.dumps(source_meta, indent=2, default=str))

    print("\n=== 3) Target metadata (from Snowflake) ===")
    print(json.dumps(target_meta, indent=2, default=str))

    print("\nDone. Transform maps connector envelopes -> colleague shapes.")
    print("Next: store these dicts in Metadata DB.")


if __name__ == "__main__":
    main()
