#!/usr/bin/env python3
"""
Idempotent demo metadata for offline API / UI testing (no live dbt/Snowflake).

Seeds:
  - Always: demo_ecommerce_etl (demo-pipeline-001) — used by offline unit tests
  - Always: informatica_orders_etl — MySQL → Informatica → MySQL with failed latest run
  - Any pipelines already in obs_pipelines
  - If catalog is empty (besides demo): ecommerce_etl, hr_etl, stock_etl

Populates runs, SOURCE/TARGET assets, columns, DQ checks, and lineage edges
so Overview / Freshness / Volume / Quality / Lineage / Schema pages have data.

Usage:
  python scripts/seed_demo_metadata.py
  docker compose -f docker-compose.prod.yml exec api python scripts/seed_demo_metadata.py
"""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

load_dotenv(ROOT / ".env")

from application.src.store.meta_mysql import ensure_tables, get_connection, record_heartbeat  # noqa: E402

DEMO_PIPELINE_ID = "demo-pipeline-001"
DEMO_PIPELINE_NAME = "demo_ecommerce_etl"

# Rich column sets so Lineage "Column" view has shared names + fan-in/out wires
COLS_ORDERS = [
    "ORDER_ID", "CUSTOMER_ID", "ORDER_DATE", "STATUS", "AMOUNT", "CURRENCY",
    "DISCOUNT_PCT", "TAX_AMOUNT", "SHIPPING_COST", "PAYMENT_METHOD",
    "PRODUCT_SKU", "QUANTITY", "WAREHOUSE_ID", "CHANNEL", "UPDATED_AT",
    "CREATED_AT", "IS_RETURNED", "REGION",
]
COLS_CUSTOMERS = [
    "CUSTOMER_ID", "EMAIL", "FIRST_NAME", "LAST_NAME", "PHONE",
    "CITY", "STATE", "COUNTRY", "ZIP_CODE", "SEGMENT",
    "LIFETIME_VALUE", "CREATED_AT", "UPDATED_AT", "IS_ACTIVE",
]
COLS_ORDERS_MART = [
    "ORDER_ID", "CUSTOMER_ID", "ORDER_DATE", "STATUS", "AMOUNT", "CURRENCY",
    "DISCOUNT_PCT", "TAX_AMOUNT", "SHIPPING_COST", "PAYMENT_METHOD",
    "PRODUCT_SKU", "QUANTITY", "WAREHOUSE_ID", "CHANNEL", "UPDATED_AT",
    "CREATED_AT", "IS_RETURNED", "REGION", "NET_AMOUNT", "CUSTOMER_EMAIL",
]
COLS_EMPLOYEES = [
    "EMPLOYEE_ID", "EMPLOYEE_SALARY", "DEPT", "FIRST_NAME", "LAST_NAME",
    "EMAIL", "HIRE_DATE", "MANAGER_ID", "JOB_TITLE", "LOCATION",
    "EMPLOYMENT_STATUS", "UPDATED_AT", "CREATED_AT", "COST_CENTER",
]
COLS_STOCK = [
    "ORDER_ID", "SKU", "QTY", "WAREHOUSE_ID", "UNIT_COST", "UNIT_PRICE",
    "SUPPLIER_ID", "RECEIVED_AT", "STATUS", "LOT_NUMBER",
    "EXPIRY_DATE", "UPDATED_AT", "CREATED_AT", "IS_DAMAGED",
]

# Catalog pipelines when DB has no real pipelines yet (match product templates)
CATALOG_PIPELINES: list[dict[str, Any]] = [
    {
        "pipeline_id": "seed-ecommerce-etl",
        "pipeline_name": "ecommerce_etl",
        "source_tool": "snowflake",
        "source_schema": "SRC_DATA",
        "etl_tool": "dbt",
        "target_tool": "snowflake",
        "target_schema": "CLEAN_DATA",
        "description": "Seeded ecommerce pipeline (SRC_DATA → dbt → CLEAN_DATA)",
        "sources": [
            ("ECOMMERCE", "SRC_DATA", "RAW_CUSTOMERS", COLS_CUSTOMERS),
            ("ECOMMERCE", "SRC_DATA", "RAW_ORDERS", COLS_ORDERS),
        ],
        "targets": [
            ("ECOMMERCE", "CLEAN_DATA", "MY_FIRST_DBT_MODEL", COLS_ORDERS_MART),
        ],
        "edges": [
            ("ECOMMERCE.SRC_DATA.RAW_ORDERS", "ECOMMERCE.CLEAN_DATA.MY_FIRST_DBT_MODEL"),
            ("ECOMMERCE.SRC_DATA.RAW_CUSTOMERS", "ECOMMERCE.CLEAN_DATA.MY_FIRST_DBT_MODEL"),
        ],
    },
    {
        "pipeline_id": "seed-hr-etl",
        "pipeline_name": "hr_etl",
        "source_tool": "snowflake",
        "source_schema": "RAW_DATA",
        "etl_tool": "dbt",
        "target_tool": "snowflake",
        "target_schema": "FINAL_DATA",
        "description": "Seeded HR pipeline (RAW_DATA → dbt → FINAL_DATA)",
        "sources": [
            ("HR_ANALYTICS", "RAW_DATA", "RAW_EMPLOYEES", COLS_EMPLOYEES),
        ],
        "targets": [
            ("HR_ANALYTICS", "FINAL_DATA", "DIM_EMPLOYEES", COLS_EMPLOYEES + ["SALARY_BAND", "TENURE_YEARS"]),
        ],
        "edges": [
            ("HR_ANALYTICS.RAW_DATA.RAW_EMPLOYEES", "HR_ANALYTICS.FINAL_DATA.DIM_EMPLOYEES"),
        ],
    },
    {
        "pipeline_id": "seed-stock-etl",
        "pipeline_name": "stock_etl",
        "source_tool": "snowflake",
        "source_schema": "RAW",
        "etl_tool": "dbt",
        "target_tool": "snowflake",
        "target_schema": "STAGING",
        "description": "Seeded stock pipeline (RAW → dbt → STAGING)",
        "sources": [
            ("ANALYTICS_DB", "RAW", "RAW_ORDERS", COLS_STOCK),
        ],
        "targets": [
            ("ANALYTICS_DB", "STAGING", "STG_ORDERS", COLS_STOCK + ["EXTENDED_COST", "MARGIN_PCT"]),
        ],
        "edges": [
            ("ANALYTICS_DB.RAW.RAW_ORDERS", "ANALYTICS_DB.STAGING.STG_ORDERS"),
        ],
    },
]

DEMO_SPEC: dict[str, Any] = {
    "pipeline_id": DEMO_PIPELINE_ID,
    "pipeline_name": DEMO_PIPELINE_NAME,
    "source_tool": "snowflake",
    "source_schema": "RAW",
    "etl_tool": "dbt",
    "target_tool": "snowflake",
    "target_schema": "ANALYTICS",
    "description": "Demo pipeline for offline observability testing",
    "latest_status": "success",
    "sources": [
        ("ANALYTICS", "RAW", "STG_ORDERS", COLS_ORDERS),
        ("ANALYTICS", "RAW", "STG_CUSTOMERS", COLS_CUSTOMERS),
    ],
    "targets": [
        ("ANALYTICS", "MART", "FCT_ORDERS", COLS_ORDERS_MART),
    ],
    "edges": [
        ("ANALYTICS.RAW.STG_ORDERS", "ANALYTICS.MART.FCT_ORDERS"),
        ("ANALYTICS.RAW.STG_CUSTOMERS", "ANALYTICS.MART.FCT_ORDERS"),
    ],
}

# Always seeded: Informatica ETL with a failed latest run (for Incidents / RCA UI)
INFORMATICA_FAIL_SPEC: dict[str, Any] = {
    "pipeline_id": "seed-informatica-orders-fail",
    "pipeline_name": "informatica_orders_etl",
    "source_tool": "mysql",
    "source_schema": "src_orders",
    "etl_tool": "informatica",
    "target_tool": "mysql",
    "target_schema": "stg_orders",
    "description": "Seeded Informatica (IICS) pipeline — latest run failed on mapping",
    "system_name": "MySQL",
    "system_type": "DATABASE",
    "latest_status": "failed",
    "error_message": (
        "Informatica task 'm_orders_load' failed: "
        "[ERROR] Connection to target MySQL timed out while writing STG_ORDERS "
        "(IICS activity log id=987654). Check network / JDBC credentials."
    ),
    "failed_nodes": ["mapping.m_orders_load", "task.s_orders_daily"],
    "sources": [
        ("orders_db", "src_orders", "RAW_ORDERS", COLS_ORDERS),
        ("orders_db", "src_orders", "RAW_CUSTOMERS", COLS_CUSTOMERS),
    ],
    "targets": [
        ("orders_db", "stg_orders", "STG_ORDERS", COLS_ORDERS_MART),
    ],
    "edges": [
        ("orders_db.src_orders.RAW_ORDERS", "orders_db.stg_orders.STG_ORDERS"),
        ("orders_db.src_orders.RAW_CUSTOMERS", "orders_db.stg_orders.STG_ORDERS"),
    ],
}


def _short_id(prefix: str, *parts: str) -> str:
    h = hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:12]
    return f"{prefix}-{h}"[:64]


def _upsert_pipeline(cur, spec: dict[str, Any]) -> None:
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
          description=VALUES(description),
          is_active=1
        """,
        (
            spec["pipeline_id"],
            spec["pipeline_name"],
            spec.get("source_tool") or "snowflake",
            spec.get("source_schema") or "RAW",
            spec.get("etl_tool") or "dbt",
            spec.get("target_tool") or "snowflake",
            spec.get("target_schema") or "ANALYTICS",
            spec.get("description") or "Seeded observability pipeline",
        ),
    )


def _insert_run(
    cur,
    *,
    run_id: str,
    pipeline_id: str,
    pipeline_name: str,
    status: str,
    start: datetime,
    end: datetime,
    duration: int,
    rows_read: int,
    rows_written: int,
    relations: list[str],
    tool_name: str = "dbt",
    failed_nodes: list[str] | None = None,
    error_message: str | None = None,
) -> None:
    cur.execute(
        """
        INSERT INTO obs_pipeline_runs (
          id, obs_run_id, pipeline_id, pipeline_name, tool_name, status,
          start_time, end_time, duration, rows_read, rows_written,
          failed_node, error_message, relations_json, failed_nodes_json
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON DUPLICATE KEY UPDATE
          tool_name=VALUES(tool_name),
          status=VALUES(status),
          start_time=VALUES(start_time),
          end_time=VALUES(end_time),
          duration=VALUES(duration),
          rows_read=VALUES(rows_read),
          rows_written=VALUES(rows_written),
          failed_node=VALUES(failed_node),
          error_message=VALUES(error_message),
          relations_json=VALUES(relations_json),
          failed_nodes_json=VALUES(failed_nodes_json)
        """,
        (
            run_id,
            run_id,
            pipeline_id,
            pipeline_name,
            tool_name,
            status,
            start,
            end,
            duration,
            rows_read,
            rows_written,
            (failed_nodes or [None])[0] if failed_nodes else None,
            error_message,
            json.dumps(relations),
            json.dumps(failed_nodes or []),
        ),
    )


def _upsert_asset(
    cur,
    *,
    run_id: str,
    role: str,
    database: str,
    schema: str,
    table: str,
    rows: int,
    observed_at: datetime,
    column_count: int,
    system_name: str = "Snowflake",
    system_type: str = "DATA_WAREHOUSE",
) -> str:
    dataset_id = f"{database}.{schema}.{table}"
    cur.execute(
        """
        INSERT INTO obs_run_assets (
          run_id, asset_role, system_name, system_type,
          database_name, schema_name, object_name, object_type,
          row_count, column_count, size_bytes, last_updated_at, observed_at, dataset_id
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON DUPLICATE KEY UPDATE
          row_count=VALUES(row_count),
          column_count=VALUES(column_count),
          size_bytes=VALUES(size_bytes),
          last_updated_at=VALUES(last_updated_at),
          observed_at=VALUES(observed_at),
          system_name=VALUES(system_name),
          system_type=VALUES(system_type)
        """,
        (
            run_id,
            role,
            system_name,
            system_type,
            database,
            schema,
            table,
            "TABLE",
            rows,
            column_count,
            max(rows, 0) * 120,
            observed_at,
            observed_at,
            dataset_id,
        ),
    )
    return dataset_id


def _replace_columns(
    cur,
    *,
    run_id: str,
    role: str,
    database: str,
    schema: str,
    table: str,
    columns: list[str],
) -> None:
    dataset_id = f"{database}.{schema}.{table}"
    cur.execute(
        """
        DELETE FROM obs_run_columns
        WHERE run_id=%s AND asset_role=%s AND dataset_id=%s
        """,
        (run_id, role, dataset_id),
    )
    for i, col in enumerate(columns, start=1):
        dtype = "NUMBER" if col.endswith("_ID") or col in {"AMOUNT", "QTY", "EMPLOYEE_SALARY"} else "VARCHAR"
        cur.execute(
            """
            INSERT INTO obs_run_columns (
              run_id, asset_role, database_name, schema_name,
              object_name, column_name, data_type, ordinal_position, dataset_id
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """,
            (run_id, role, database, schema, table, col, dtype, i, dataset_id),
        )


def _seed_checks(cur, *, pipeline_id: str, run_id: str, dataset_id: str, checked_at: datetime) -> int:
    monitor_id = f"dbt-run:{run_id}"
    cur.execute("DELETE FROM obs_check_results WHERE monitor_id = %s", (monitor_id,))
    checks = [
        ("pass", "low", "not_null on primary key", "completeness"),
        ("pass", "low", "unique on primary key", "uniqueness"),
        ("warn", "medium", "accepted_values on status", "validity"),
        ("fail", "high", "relationships to parent", "accuracy"),
    ]
    for i, (status, sev, msg, dim) in enumerate(checks, start=1):
        cid = _short_id("chk", pipeline_id, run_id, str(i))
        cur.execute(
            """
            INSERT INTO obs_check_results (
              check_id, monitor_id, pipeline_id, status, severity,
              message, observed_json, checked_at
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
            ON DUPLICATE KEY UPDATE
              status=VALUES(status),
              severity=VALUES(severity),
              message=VALUES(message),
              observed_json=VALUES(observed_json),
              checked_at=VALUES(checked_at)
            """,
            (
                cid,
                monitor_id,
                pipeline_id,
                status,
                sev,
                msg,
                json.dumps(
                    {
                        "run_id": run_id,
                        "test_id": f"test.seed.{i}",
                        "relation_name": dataset_id,
                        "dataset_id": dataset_id,
                        "dimension": dim,
                        "tags": [f"dataset:{dataset_id}"],
                        "source": "dbt_run_results",
                    }
                ),
                checked_at,
            ),
        )
    return len(checks)


def _seed_edges(
    cur,
    *,
    pipeline_id: str,
    run_id: str,
    edges: list[tuple[str, str]],
    observed_at: datetime,
) -> int:
    cur.execute("DELETE FROM obs_lineage_edges WHERE run_id = %s", (run_id,))
    for i, (src, tgt) in enumerate(edges, start=1):
        eid = _short_id("edge", pipeline_id, run_id, str(i))
        cur.execute(
            """
            INSERT INTO obs_lineage_edges (
              edge_id, pipeline_id, run_id, from_dataset, to_dataset,
              edge_kind, confidence, observed_at
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
            """,
            (eid, pipeline_id, run_id, src, tgt, "dbt_manifest", 1.0, observed_at),
        )
    return len(edges)


def _default_spec_from_row(row: dict) -> dict[str, Any]:
    """Build a reasonable seed shape from an existing obs_pipelines row."""
    pid = str(row.get("pipeline_id"))
    pname = str(row.get("pipeline_name") or pid)
    src_schema = str(row.get("source_schema") or "RAW")
    tgt_schema = str(row.get("target_schema") or "ANALYTICS")
    db = "ANALYTICS_DB"
    # Prefer catalog template if name matches
    for spec in CATALOG_PIPELINES:
        if spec["pipeline_name"] == pname:
            out = dict(spec)
            out["pipeline_id"] = pid
            return out
    if pname == DEMO_PIPELINE_NAME or pid == DEMO_PIPELINE_ID:
        out = dict(DEMO_SPEC)
        out["pipeline_id"] = pid
        return out
    return {
        "pipeline_id": pid,
        "pipeline_name": pname,
        "source_tool": row.get("source_tool") or "snowflake",
        "source_schema": src_schema,
        "etl_tool": row.get("etl_tool") or "dbt",
        "target_tool": row.get("target_tool") or "snowflake",
        "target_schema": tgt_schema,
        "description": row.get("description") or f"Seeded data for {pname}",
        "sources": [
            (db, src_schema, "RAW_ORDERS", COLS_ORDERS),
            (db, src_schema, "RAW_CUSTOMERS", COLS_CUSTOMERS),
        ],
        "targets": [(db, tgt_schema, "STG_ORDERS", COLS_ORDERS_MART)],
        "edges": [
            (f"{db}.{src_schema}.RAW_ORDERS", f"{db}.{tgt_schema}.STG_ORDERS"),
            (f"{db}.{src_schema}.RAW_CUSTOMERS", f"{db}.{tgt_schema}.STG_ORDERS"),
        ],
    }


def _seed_pipeline(cur, conn, spec: dict[str, Any], *, now: datetime) -> dict[str, Any]:
    _upsert_pipeline(cur, spec)
    pid = spec["pipeline_id"]
    pname = spec["pipeline_name"]
    sources = spec.get("sources") or []
    targets = spec.get("targets") or []
    edges = spec.get("edges") or []
    tool_name = str(spec.get("etl_tool") or "dbt")
    latest_status = str(spec.get("latest_status") or "success").lower()
    error_message = spec.get("error_message")
    failed_nodes = list(spec.get("failed_nodes") or [])
    if pid == DEMO_PIPELINE_ID and not failed_nodes:
        failed_nodes = [f"model.seed.{pname}.stg_orders"]
    sys_name = str(spec.get("system_name") or "Snowflake")
    sys_type = str(spec.get("system_type") or "DATA_WAREHOUSE")

    relations = [f"{db}.{sch}.{tbl}" for db, sch, tbl, _ in sources + targets]

    # Prior successful run (~26h ago) for volume/freshness baselines
    prior_id = _short_id("run", pid, "prior")
    prior_start = now - timedelta(hours=26)
    prior_end = now - timedelta(hours=25, minutes=50)
    _insert_run(
        cur,
        run_id=prior_id,
        pipeline_id=pid,
        pipeline_name=pname,
        status="success",
        start=prior_start,
        end=prior_end,
        duration=280,
        rows_read=480000,
        rows_written=475000,
        relations=relations,
        tool_name=tool_name,
    )
    for db, sch, tbl, cols in sources:
        _upsert_asset(
            cur,
            run_id=prior_id,
            role="SOURCE",
            database=db,
            schema=sch,
            table=tbl,
            rows=480000,
            observed_at=prior_end,
            column_count=len(cols),
            system_name=sys_name,
            system_type=sys_type,
        )
        _replace_columns(
            cur, run_id=prior_id, role="SOURCE", database=db, schema=sch, table=tbl, columns=cols
        )
    for db, sch, tbl, cols in targets:
        _upsert_asset(
            cur,
            run_id=prior_id,
            role="TARGET",
            database=db,
            schema=sch,
            table=tbl,
            rows=475000,
            observed_at=prior_end,
            column_count=len(cols),
            system_name=sys_name,
            system_type=sys_type,
        )
        _replace_columns(
            cur, run_id=prior_id, role="TARGET", database=db, schema=sch, table=tbl, columns=cols
        )

    # Latest run (~2h ago)
    run_id = _short_id("run", pid, "latest")
    # Keep stable id for classic demo tests
    if pid == DEMO_PIPELINE_ID:
        prior_id_demo = "demo-run-000"
        run_id = "demo-run-001"
        # Re-write prior with classic ids for offline tests
        _insert_run(
            cur,
            run_id=prior_id_demo,
            pipeline_id=pid,
            pipeline_name=pname,
            status="success",
            start=prior_start,
            end=prior_end,
            duration=280,
            rows_read=480000,
            rows_written=480000,
            relations=relations,
            tool_name=tool_name,
        )
        for db, sch, tbl, cols in sources:
            _upsert_asset(
                cur,
                run_id=prior_id_demo,
                role="SOURCE",
                database=db,
                schema=sch,
                table=tbl,
                rows=480000,
                observed_at=prior_end,
                column_count=len(cols),
                system_name=sys_name,
                system_type=sys_type,
            )
            _replace_columns(
                cur,
                run_id=prior_id_demo,
                role="SOURCE",
                database=db,
                schema=sch,
                table=tbl,
                columns=cols,
            )
        for db, sch, tbl, cols in targets:
            _upsert_asset(
                cur,
                run_id=prior_id_demo,
                role="TARGET",
                database=db,
                schema=sch,
                table=tbl,
                rows=480000,
                observed_at=prior_end,
                column_count=len(cols),
                system_name=sys_name,
                system_type=sys_type,
            )
            _replace_columns(
                cur,
                run_id=prior_id_demo,
                role="TARGET",
                database=db,
                schema=sch,
                table=tbl,
                columns=cols,
            )

    run_start = now - timedelta(hours=2)
    run_end = now - timedelta(hours=1, minutes=55)
    is_failed = latest_status in {"failed", "error", "fail"}
    latest_rows_read = 500000 if not is_failed else 120000
    latest_rows_written = 495000 if not is_failed else 0
    latest_target_rows = 495000 if not is_failed else 0
    _insert_run(
        cur,
        run_id=run_id,
        pipeline_id=pid,
        pipeline_name=pname,
        status="failed" if is_failed else "success",
        start=run_start,
        end=run_end,
        duration=95 if is_failed else 300,
        rows_read=latest_rows_read,
        rows_written=latest_rows_written,
        relations=relations,
        tool_name=tool_name,
        failed_nodes=failed_nodes if is_failed or pid == DEMO_PIPELINE_ID else [],
        error_message=error_message if is_failed else None,
    )

    for db, sch, tbl, cols in sources:
        _upsert_asset(
            cur,
            run_id=run_id,
            role="SOURCE",
            database=db,
            schema=sch,
            table=tbl,
            rows=latest_rows_read,
            observed_at=run_end,
            column_count=len(cols),
            system_name=sys_name,
            system_type=sys_type,
        )
        _replace_columns(
            cur, run_id=run_id, role="SOURCE", database=db, schema=sch, table=tbl, columns=cols
        )
    target_ds = None
    for db, sch, tbl, cols in targets:
        target_ds = _upsert_asset(
            cur,
            run_id=run_id,
            role="TARGET",
            database=db,
            schema=sch,
            table=tbl,
            rows=latest_target_rows,
            observed_at=run_end,
            column_count=len(cols),
            system_name=sys_name,
            system_type=sys_type,
        )
        _replace_columns(
            cur, run_id=run_id, role="TARGET", database=db, schema=sch, table=tbl, columns=cols
        )

    checks = _seed_checks(
        cur,
        pipeline_id=pid,
        run_id=run_id,
        dataset_id=target_ds or relations[-1],
        checked_at=run_end,
    )
    edge_n = _seed_edges(
        cur, pipeline_id=pid, run_id=run_id, edges=edges, observed_at=run_end
    )
    record_heartbeat(conn, pid, "poller", ok=True, meta={"source": "seed_demo_metadata"})

    return {
        "pipeline_id": pid,
        "pipeline_name": pname,
        "run_id": run_id,
        "etl_tool": tool_name,
        "latest_status": "failed" if is_failed else "success",
        "checks": checks,
        "lineage_edges": edge_n,
        "source_tables": len(sources),
        "target_tables": len(targets),
    }


def seed() -> dict:
    conn = get_connection()
    try:
        ensure_tables(conn)
        now = datetime.utcnow()
        seeded: list[dict] = []

        with conn.cursor() as cur:
            # Always seed classic demo pipeline (offline tests)
            seeded.append(_seed_pipeline(cur, conn, DEMO_SPEC, now=now))
            # Always seed Informatica failure pipeline for Incidents / failed-run UI
            seeded.append(_seed_pipeline(cur, conn, INFORMATICA_FAIL_SPEC, now=now))

            cur.execute(
                """
                SELECT pipeline_id, pipeline_name, source_tool, source_schema,
                       etl_tool, target_tool, target_schema, description
                FROM obs_pipelines
                ORDER BY pipeline_name
                """
            )
            existing = list(cur.fetchall() or [])
            existing_ids = {str(r.get("pipeline_id")) for r in existing}
            existing_names = {str(r.get("pipeline_name") or "") for r in existing}

            always_ids = {DEMO_PIPELINE_ID, INFORMATICA_FAIL_SPEC["pipeline_id"]}

            # Seed every existing non-demo pipeline
            for row in existing:
                pid = str(row.get("pipeline_id"))
                if pid in always_ids:
                    continue
                spec = _default_spec_from_row(row)
                seeded.append(_seed_pipeline(cur, conn, spec, now=now))

            # If only always-seeded pipelines exist, also add catalog templates
            non_demo = [
                r
                for r in existing
                if str(r.get("pipeline_id")) not in always_ids
            ]
            if not non_demo:
                for spec in CATALOG_PIPELINES:
                    if spec["pipeline_name"] in existing_names:
                        continue
                    if spec["pipeline_id"] in existing_ids:
                        continue
                    seeded.append(_seed_pipeline(cur, conn, spec, now=now))

        conn.commit()
        return {
            "ok": True,
            "pipelines_seeded": len(seeded),
            "items": seeded,
            "message": (
                "Dummy runs/assets/columns/checks/lineage edges written. "
                "Refresh Overview and Lineage in the UI."
            ),
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def main() -> int:
    result = seed()
    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
