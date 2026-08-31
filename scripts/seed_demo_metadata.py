#!/usr/bin/env python3
"""Idempotent demo metadata for offline API testing (no dbt/Snowflake credentials)."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

load_dotenv(ROOT / ".env")

from application.src.store.meta_mysql import ensure_tables, get_connection, record_heartbeat  # noqa: E402

DEMO_PIPELINE_ID = "demo-pipeline-001"
DEMO_PIPELINE_NAME = "demo_ecommerce_etl"
DEMO_RUN_ID = "demo-run-001"
DEMO_OBS_RUN_ID = "demo-run-001"
DEMO_PRIOR_RUN_ID = "demo-run-000"


def seed() -> dict:
    conn = get_connection()
    try:
        ensure_tables(conn)
        now = datetime.utcnow()
        run_start = now - timedelta(hours=2)
        run_end = now - timedelta(hours=1, minutes=55)

        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO obs_pipelines (
                  pipeline_id, pipeline_name, source_tool, source_schema,
                  etl_tool, target_tool, target_schema, is_active, description
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,1,%s)
                ON DUPLICATE KEY UPDATE
                  pipeline_name=VALUES(pipeline_name),
                  source_tool=VALUES(source_tool),
                  source_schema=VALUES(source_schema),
                  etl_tool=VALUES(etl_tool),
                  target_tool=VALUES(target_tool),
                  target_schema=VALUES(target_schema),
                  description=VALUES(description)
                """,
                (
                    DEMO_PIPELINE_ID,
                    DEMO_PIPELINE_NAME,
                    "snowflake",
                    "RAW",
                    "dbt",
                    "snowflake",
                    "ANALYTICS",
                    "Demo pipeline for offline observability testing",
                ),
            )

            relations = [
                "ANALYTICS.RAW.STG_ORDERS",
                "ANALYTICS.RAW.STG_CUSTOMERS",
                "ANALYTICS.MART.FCT_ORDERS",
            ]
            failed_nodes = ["model.demo.stg_orders"]
            prior_start = run_start - timedelta(hours=26)
            prior_end = run_start - timedelta(hours=25, minutes=55)

            cur.execute(
                """
                INSERT INTO obs_pipeline_runs (
                  id, obs_run_id, pipeline_id, pipeline_name, tool_name, status,
                  start_time, end_time, duration, rows_read, rows_written,
                  failed_node, error_message, relations_json, failed_nodes_json
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON DUPLICATE KEY UPDATE
                  status=VALUES(status),
                  start_time=VALUES(start_time),
                  end_time=VALUES(end_time),
                  duration=VALUES(duration),
                  relations_json=VALUES(relations_json),
                  failed_nodes_json=VALUES(failed_nodes_json)
                """,
                (
                    DEMO_PRIOR_RUN_ID,
                    DEMO_PRIOR_RUN_ID,
                    DEMO_PIPELINE_ID,
                    DEMO_PIPELINE_NAME,
                    "dbt",
                    "success",
                    prior_start,
                    prior_end,
                    280,
                    480000,
                    480000,
                    None,
                    None,
                    json.dumps(relations),
                    json.dumps([]),
                ),
            )

            for role, ds, rows in (
                ("SOURCE", "RAW.STG_ORDERS", 480000),
                ("TARGET", "ANALYTICS.MART.FCT_ORDERS", 480000),
            ):
                cur.execute(
                    """
                    INSERT INTO obs_run_assets (
                      run_id, asset_role, system_name, system_type,
                      database_name, schema_name, object_name, object_type,
                      row_count, last_updated_at, dataset_id
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON DUPLICATE KEY UPDATE
                      row_count=VALUES(row_count),
                      last_updated_at=VALUES(last_updated_at)
                    """,
                    (
                        DEMO_PRIOR_RUN_ID,
                        role,
                        "snowflake",
                        "warehouse",
                        ds.split(".")[0] if "." in ds else "DB",
                        ds.split(".")[0] if "." in ds else "SCHEMA",
                        ds.split(".")[-1],
                        "TABLE",
                        rows,
                        prior_end,
                        ds,
                    ),
                )

            cur.execute("DELETE FROM obs_run_columns WHERE run_id = %s", (DEMO_PRIOR_RUN_ID,))
            cur.execute(
                """
                INSERT INTO obs_run_columns (
                  run_id, asset_role, database_name, schema_name,
                  object_name, column_name, data_type, ordinal_position, dataset_id
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """,
                (
                    DEMO_PRIOR_RUN_ID,
                    "TARGET",
                    "ANALYTICS",
                    "MART",
                    "FCT_ORDERS",
                    "ORDER_ID",
                    "NUMBER",
                    1,
                    "ANALYTICS.MART.FCT_ORDERS",
                ),
            )

            cur.execute(
                """
                INSERT INTO obs_pipeline_runs (
                  id, obs_run_id, pipeline_id, pipeline_name, tool_name, status,
                  start_time, end_time, duration, rows_read, rows_written,
                  failed_node, error_message, relations_json, failed_nodes_json
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON DUPLICATE KEY UPDATE
                  status=VALUES(status),
                  start_time=VALUES(start_time),
                  end_time=VALUES(end_time),
                  duration=VALUES(duration),
                  relations_json=VALUES(relations_json),
                  failed_nodes_json=VALUES(failed_nodes_json)
                """,
                (
                    DEMO_RUN_ID,
                    DEMO_OBS_RUN_ID,
                    DEMO_PIPELINE_ID,
                    DEMO_PIPELINE_NAME,
                    "dbt",
                    "success",
                    run_start,
                    run_end,
                    300,
                    500000,
                    495000,
                    None,
                    None,
                    json.dumps(relations),
                    json.dumps(failed_nodes),
                ),
            )

            for role, ds, rows in (
                ("SOURCE", "RAW.STG_ORDERS", 500000),
                ("TARGET", "ANALYTICS.MART.FCT_ORDERS", 495000),
            ):
                cur.execute(
                    """
                    INSERT INTO obs_run_assets (
                      run_id, asset_role, system_name, system_type,
                      database_name, schema_name, object_name, object_type,
                      row_count, last_updated_at, dataset_id
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON DUPLICATE KEY UPDATE
                      row_count=VALUES(row_count),
                      last_updated_at=VALUES(last_updated_at)
                    """,
                    (
                        DEMO_RUN_ID,
                        role,
                        "snowflake",
                        "warehouse",
                        ds.split(".")[0] if "." in ds else "DB",
                        ds.split(".")[0] if "." in ds else "SCHEMA",
                        ds.split(".")[-1],
                        "TABLE",
                        rows,
                        run_end,
                        ds,
                    ),
                )

            cur.execute("DELETE FROM obs_run_columns WHERE run_id = %s", (DEMO_RUN_ID,))
            cur.execute(
                """
                INSERT INTO obs_run_columns (
                  run_id, asset_role, database_name, schema_name,
                  object_name, column_name, data_type, ordinal_position, dataset_id
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """,
                (
                    DEMO_RUN_ID,
                    "TARGET",
                    "ANALYTICS",
                    "MART",
                    "FCT_ORDERS",
                    "ORDER_ID",
                    "NUMBER",
                    1,
                    "ANALYTICS.MART.FCT_ORDERS",
                ),
            )

            monitor_id = f"dbt-run:{DEMO_RUN_ID}"
            cur.execute("DELETE FROM obs_check_results WHERE monitor_id = %s", (monitor_id,))
            checks = [
                ("demo:check:1", "pass", "low", "not_null on order_id", "ANALYTICS.MART.FCT_ORDERS"),
                ("demo:check:2", "pass", "low", "unique on order_id", "ANALYTICS.MART.FCT_ORDERS"),
                ("demo:check:3", "warn", "medium", "accepted_values on status", "ANALYTICS.MART.FCT_ORDERS"),
                ("demo:check:4", "fail", "high", "relationships to customers", "ANALYTICS.MART.FCT_ORDERS"),
            ]
            for cid, status, sev, msg, rel in checks:
                cur.execute(
                    """
                    INSERT INTO obs_check_results (
                      check_id, monitor_id, pipeline_id, status, severity,
                      message, observed_json, checked_at
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                    """,
                    (
                        cid,
                        monitor_id,
                        DEMO_PIPELINE_ID,
                        status,
                        sev,
                        msg,
                        json.dumps(
                            {
                                "run_id": DEMO_RUN_ID,
                                "test_id": f"test.demo.{cid}",
                                "relation_name": rel,
                                "dataset_id": rel,
                                "dimension": (
                                    "completeness"
                                    if "not_null" in msg
                                    else "uniqueness"
                                    if "unique" in msg
                                    else "validity"
                                    if "accepted_values" in msg
                                    else "accuracy"
                                    if "relationships" in msg
                                    else None
                                ),
                                "tags": [f"dataset:{rel}"],
                                "source": "dbt_run_results",
                            }
                        ),
                        run_end,
                    ),
                )

            cur.execute("DELETE FROM obs_lineage_edges WHERE run_id = %s", (DEMO_RUN_ID,))
            edges = [
                ("demo-edge-1", "RAW.STG_ORDERS", "ANALYTICS.MART.FCT_ORDERS"),
                ("demo-edge-2", "RAW.STG_CUSTOMERS", "ANALYTICS.MART.FCT_ORDERS"),
            ]
            for eid, src, tgt in edges:
                cur.execute(
                    """
                    INSERT INTO obs_lineage_edges (
                      edge_id, pipeline_id, run_id, from_dataset, to_dataset,
                      edge_kind, confidence, observed_at
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                    """,
                    (
                        eid,
                        DEMO_PIPELINE_ID,
                        DEMO_RUN_ID,
                        src,
                        tgt,
                        "dbt_manifest",
                        1.0,
                        run_end,
                    ),
                )

        record_heartbeat(conn, DEMO_PIPELINE_ID, "poller", ok=True, meta={"source": "seed_demo_metadata"})
        conn.commit()
        return {
            "ok": True,
            "pipeline_id": DEMO_PIPELINE_ID,
            "pipeline_name": DEMO_PIPELINE_NAME,
            "run_id": DEMO_RUN_ID,
            "checks": 4,
            "lineage_edges": 2,
        }
    finally:
        conn.close()


def main() -> int:
    result = seed()
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
