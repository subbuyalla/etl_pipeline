"""
Store transformed payloads into Metadata MySQL (database from DB_* / .env).

Tables (created if missing):
  - obs_pipeline_runs   ← colleague pipeline-run log
  - obs_run_assets      ← colleague source/target metadata
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any

import pymysql


def _parse_dt(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def get_connection():
    """Connect to Metadata MySQL using the same env as the platform."""
    host = os.getenv("DB_HOST") or "database-1.cbsuuwi6y4bg.eu-north-1.rds.amazonaws.com"
    # Guard against old dead hostname left in .env
    if "c9yg0giiwoxf" in host:
        host = "database-1.cbsuuwi6y4bg.eu-north-1.rds.amazonaws.com"
    user = os.getenv("DB_USER") or "admin"
    password = os.getenv("MYSQL_PASSWORD") or os.getenv("DB_PASSWORD") or ""
    database = os.getenv("DB_NAME") or "metadata"
    port = int(os.getenv("DB_PORT") or "3306")
    if not password:
        raise RuntimeError("Missing DB_PASSWORD / MYSQL_PASSWORD for Metadata MySQL")
    return pymysql.connect(
        host=host,
        port=port,
        user=user,
        password=password,
        database=database,
        charset="utf8mb4",
        autocommit=False,
        cursorclass=pymysql.cursors.DictCursor,
    )


def ensure_tables(conn) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS obs_pipeline_runs (
              id VARCHAR(64) NOT NULL,
              pipeline_id VARCHAR(64) NOT NULL,
              pipeline_name VARCHAR(255) NULL,
              status VARCHAR(64) NULL,
              start_time DATETIME NULL,
              end_time DATETIME NULL,
              duration INT NULL,
              tool_name VARCHAR(64) NULL,
              rows_read BIGINT NULL,
              rows_written BIGINT NULL,
              error_message TEXT NULL,
              raw_log LONGTEXT NULL,
              execution_mode VARCHAR(64) NULL,
              triggered_by VARCHAR(128) NULL,
              orchestrator_tool VARCHAR(64) NULL,
              orchestrator_dag_id VARCHAR(255) NULL,
              orchestrator_task_id VARCHAR(255) NULL,
              orchestrator_run_id VARCHAR(255) NULL,
              tenant_id VARCHAR(128) NULL,
              connector_instance_id VARCHAR(128) NULL,
              created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
              PRIMARY KEY (id),
              KEY ix_obs_runs_pipeline (pipeline_id),
              KEY ix_obs_runs_status (status)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS obs_run_assets (
              id BIGINT NOT NULL AUTO_INCREMENT,
              run_id VARCHAR(64) NOT NULL,
              asset_role VARCHAR(16) NOT NULL,
              system_name VARCHAR(128) NULL,
              system_type VARCHAR(64) NULL,
              database_name VARCHAR(255) NULL,
              schema_name VARCHAR(255) NULL,
              object_name VARCHAR(255) NULL,
              object_type VARCHAR(64) NULL,
              row_count BIGINT NULL,
              column_count INT NULL,
              size_bytes BIGINT NULL,
              last_updated_at DATETIME NULL,
              observed_at DATETIME NULL,
              tenant_id VARCHAR(128) NULL,
              connector_instance_id VARCHAR(128) NULL,
              dataset_id VARCHAR(512) NULL,
              created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
              PRIMARY KEY (id),
              UNIQUE KEY uq_obs_asset (run_id, asset_role, dataset_id(255)),
              KEY ix_obs_assets_run (run_id),
              KEY ix_obs_assets_role (asset_role)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )
    conn.commit()


def store_run(conn, run_log: dict) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO obs_pipeline_runs (
              id, pipeline_id, pipeline_name, status, start_time, end_time, duration,
              tool_name, rows_read, rows_written, error_message, raw_log,
              execution_mode, triggered_by, orchestrator_tool,
              orchestrator_dag_id, orchestrator_task_id, orchestrator_run_id,
              tenant_id, connector_instance_id
            ) VALUES (
              %s,%s,%s,%s,%s,%s,%s,
              %s,%s,%s,%s,%s,
              %s,%s,%s,
              %s,%s,%s,
              %s,%s
            )
            ON DUPLICATE KEY UPDATE
              status=VALUES(status),
              start_time=VALUES(start_time),
              end_time=VALUES(end_time),
              duration=VALUES(duration),
              error_message=VALUES(error_message),
              raw_log=VALUES(raw_log),
              rows_read=VALUES(rows_read),
              rows_written=VALUES(rows_written)
            """,
            (
                str(run_log.get("id") or ""),
                str(run_log.get("pipeline_id") or ""),
                run_log.get("pipeline_name"),
                run_log.get("status"),
                _parse_dt(run_log.get("start_time")),
                _parse_dt(run_log.get("end_time")),
                run_log.get("duration"),
                run_log.get("tool_name"),
                run_log.get("rows_read"),
                run_log.get("rows_written"),
                run_log.get("error_message"),
                run_log.get("raw_log"),
                run_log.get("execution_mode"),
                run_log.get("triggered_by"),
                run_log.get("orchestrator_tool"),
                run_log.get("orchestrator_dag_id"),
                run_log.get("orchestrator_task_id"),
                run_log.get("orchestrator_run_id"),
                run_log.get("tenant_id"),
                run_log.get("connector_instance_id"),
            ),
        )


def store_asset(conn, row: dict) -> None:
    dataset_id = row.get("dataset_id") or (
        f"{row.get('database_name')}.{row.get('schema_name')}.{row.get('object_name')}"
    )
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO obs_run_assets (
              run_id, asset_role, system_name, system_type,
              database_name, schema_name, object_name, object_type,
              row_count, column_count, size_bytes,
              last_updated_at, observed_at,
              tenant_id, connector_instance_id, dataset_id
            ) VALUES (
              %s,%s,%s,%s,
              %s,%s,%s,%s,
              %s,%s,%s,
              %s,%s,
              %s,%s,%s
            )
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
                str(row.get("run_id") or ""),
                row.get("asset_role"),
                row.get("system_name"),
                row.get("system_type"),
                row.get("database_name"),
                row.get("schema_name"),
                row.get("object_name"),
                row.get("object_type"),
                row.get("row_count"),
                row.get("column_count"),
                row.get("size_bytes"),
                _parse_dt(row.get("last_updated_at")),
                _parse_dt(row.get("observed_at")),
                row.get("tenant_id"),
                row.get("connector_instance_id"),
                dataset_id,
            ),
        )


def store_to_meta_mysql(
    run_log: dict,
    source_rows: list[dict],
    target_rows: list[dict],
) -> dict[str, Any]:
    """Write run + source/target assets into Metadata MySQL."""
    conn = get_connection()
    try:
        ensure_tables(conn)
        store_run(conn, run_log)
        for row in source_rows:
            store_asset(conn, row)
        for row in target_rows:
            store_asset(conn, row)
        conn.commit()
        return {
            "ok": True,
            "database": os.getenv("DB_NAME") or "metadata",
            "run_id": run_log.get("id"),
            "pipeline_id": run_log.get("pipeline_id"),
            "sources_stored": len(source_rows),
            "targets_stored": len(target_rows),
            "tables": ["obs_pipeline_runs", "obs_run_assets"],
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
