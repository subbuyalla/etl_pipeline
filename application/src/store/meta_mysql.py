"""
Store transformed payloads into Metadata MySQL (database from DB_* / .env).

Tables (created if missing):
  - obs_pipelines       ← pipeline attach (source / etl / target)
  - obs_pipeline_runs   ← colleague pipeline-run log
  - obs_run_assets      ← colleague source/target metadata
"""

from __future__ import annotations

import json
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
            CREATE TABLE IF NOT EXISTS obs_pipelines (
              pipeline_id VARCHAR(64) NOT NULL,
              pipeline_name VARCHAR(255) NOT NULL,
              tenant_id VARCHAR(128) NULL,
              description TEXT NULL,
              source_tool VARCHAR(64) NULL,
              source_instance_id VARCHAR(128) NULL,
              source_schema VARCHAR(255) NULL,
              etl_tool VARCHAR(64) NULL,
              etl_instance_id VARCHAR(128) NULL,
              target_tool VARCHAR(64) NULL,
              target_instance_id VARCHAR(128) NULL,
              target_schema VARCHAR(255) NULL,
              config_json LONGTEXT NULL,
              is_active TINYINT(1) NOT NULL DEFAULT 0,
              created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
              updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                ON UPDATE CURRENT_TIMESTAMP,
              PRIMARY KEY (pipeline_id),
              KEY ix_obs_pipelines_name (pipeline_name),
              KEY ix_obs_pipelines_active (is_active)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )
        # Older DBs created before is_active existed
        try:
            cur.execute(
                "ALTER TABLE obs_pipelines ADD COLUMN is_active TINYINT(1) NOT NULL DEFAULT 0"
            )
        except Exception:
            pass
        try:
            cur.execute(
                "ALTER TABLE obs_pipeline_runs ADD COLUMN rows_added BIGINT NULL"
            )
        except Exception:
            pass
        try:
            cur.execute(
                "ALTER TABLE obs_pipeline_runs ADD COLUMN failure_stage VARCHAR(32) NULL"
            )
        except Exception:
            pass
        try:
            cur.execute(
                "ALTER TABLE obs_pipeline_runs ADD COLUMN failed_node VARCHAR(512) NULL"
            )
        except Exception:
            pass
        try:
            cur.execute(
                "ALTER TABLE obs_pipeline_runs ADD COLUMN failed_message TEXT NULL"
            )
        except Exception:
            pass
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
              rows_added BIGINT NULL,
              failure_stage VARCHAR(32) NULL,
              failed_node VARCHAR(512) NULL,
              failed_message TEXT NULL,
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
        backfill_rows_added(conn)
    conn.commit()


def store_pipeline(conn, pipeline: dict, *, make_active: bool = True) -> None:
    source = pipeline.get("source") or {}
    etl = pipeline.get("etl") or {}
    target = pipeline.get("target") or {}
    with conn.cursor() as cur:
        if make_active:
            cur.execute("UPDATE obs_pipelines SET is_active = 0 WHERE is_active = 1")
        cur.execute(
            """
            INSERT INTO obs_pipelines (
              pipeline_id, pipeline_name, tenant_id, description,
              source_tool, source_instance_id, source_schema,
              etl_tool, etl_instance_id,
              target_tool, target_instance_id, target_schema,
              config_json, is_active
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON DUPLICATE KEY UPDATE
              pipeline_name=VALUES(pipeline_name),
              description=VALUES(description),
              source_tool=VALUES(source_tool),
              source_instance_id=VALUES(source_instance_id),
              source_schema=VALUES(source_schema),
              etl_tool=VALUES(etl_tool),
              etl_instance_id=VALUES(etl_instance_id),
              target_tool=VALUES(target_tool),
              target_instance_id=VALUES(target_instance_id),
              target_schema=VALUES(target_schema),
              config_json=VALUES(config_json),
              is_active=VALUES(is_active)
            """,
            (
                pipeline.get("pipeline_id"),
                pipeline.get("pipeline_name"),
                pipeline.get("tenant_id"),
                pipeline.get("description"),
                source.get("tool"),
                source.get("connector_instance_id"),
                source.get("schema"),
                etl.get("tool"),
                etl.get("connector_instance_id"),
                target.get("tool"),
                target.get("connector_instance_id"),
                target.get("schema"),
                json.dumps(pipeline, default=str),
                1 if make_active else 0,
            ),
        )


def _row_to_pipeline(row: dict) -> dict | None:
    if not row:
        return None
    raw = row.get("config_json")
    if raw:
        try:
            data = json.loads(raw) if isinstance(raw, str) else raw
            if isinstance(data, dict) and data.get("pipeline_id"):
                data["is_active"] = bool(row.get("is_active"))
                return data
        except json.JSONDecodeError:
            pass
    # Fallback if config_json missing
    return {
        "pipeline_id": row.get("pipeline_id"),
        "pipeline_name": row.get("pipeline_name"),
        "tenant_id": row.get("tenant_id") or "demo",
        "description": row.get("description"),
        "is_active": bool(row.get("is_active")),
        "source": {
            "tool": row.get("source_tool"),
            "connector_instance_id": row.get("source_instance_id"),
            "schema": row.get("source_schema"),
        },
        "etl": {
            "tool": row.get("etl_tool"),
            "connector_instance_id": row.get("etl_instance_id"),
        },
        "target": {
            "tool": row.get("target_tool"),
            "connector_instance_id": row.get("target_instance_id"),
            "schema": row.get("target_schema"),
        },
    }


def get_pipeline_by_id(pipeline_id: str) -> dict | None:
    conn = get_connection()
    try:
        ensure_tables(conn)
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM obs_pipelines WHERE pipeline_id = %s",
                (pipeline_id,),
            )
            return _row_to_pipeline(cur.fetchone() or {})
    finally:
        conn.close()


def get_pipeline_by_name(pipeline_name: str) -> dict | None:
    """Lookup pipeline attach config by name (case-insensitive)."""
    name = (pipeline_name or "").strip()
    if not name:
        return None
    conn = get_connection()
    try:
        ensure_tables(conn)
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT * FROM obs_pipelines
                WHERE LOWER(pipeline_name) = LOWER(%s)
                ORDER BY is_active DESC, updated_at DESC
                LIMIT 1
                """,
                (name,),
            )
            return _row_to_pipeline(cur.fetchone() or {})
    finally:
        conn.close()


def get_active_pipeline() -> dict | None:
    """Load the active pipeline from DB (no env PIPELINE_ID needed)."""
    conn = get_connection()
    try:
        ensure_tables(conn)
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM obs_pipelines WHERE is_active = 1 ORDER BY updated_at DESC LIMIT 1"
            )
            row = cur.fetchone()
            if row:
                return _row_to_pipeline(row)
            # Fallback: latest pipeline if none marked active
            cur.execute(
                "SELECT * FROM obs_pipelines ORDER BY updated_at DESC LIMIT 1"
            )
            return _row_to_pipeline(cur.fetchone() or {})
    finally:
        conn.close()


def list_pipelines() -> list[dict]:
    conn = get_connection()
    try:
        ensure_tables(conn)
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT pipeline_id, pipeline_name, source_tool, source_schema,
                       etl_tool, target_tool, target_schema, is_active, updated_at
                FROM obs_pipelines
                ORDER BY is_active DESC, updated_at DESC
                """
            )
            return list(cur.fetchall() or [])
    finally:
        conn.close()


def upsert_pipeline(pipeline: dict, *, make_active: bool = True) -> dict[str, Any]:
    conn = get_connection()
    try:
        ensure_tables(conn)
        store_pipeline(conn, pipeline, make_active=make_active)
        conn.commit()
        return {
            "ok": True,
            "pipeline_id": pipeline.get("pipeline_id"),
            "pipeline_name": pipeline.get("pipeline_name"),
            "is_active": make_active,
            "source": f"snowflake/{(pipeline.get('source') or {}).get('schema')}",
            "etl": "dbt",
            "target": f"snowflake/{(pipeline.get('target') or {}).get('schema')}",
            "table": "obs_pipelines",
            "message": "Pipeline saved in DB. Sync/webhook will load it from MySQL (no PIPELINE_ID env needed).",
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _target_row_total(rows: list[dict]) -> int:
    return sum(int(r.get("row_count") or 0) for r in rows)


def get_previous_target_row_count(
    conn, pipeline_id: str, current_run_id: str
) -> int | None:
    """Sum TARGET row_count from the prior run for this pipeline (by start_time)."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id FROM obs_pipeline_runs
            WHERE pipeline_id = %s AND id != %s
            ORDER BY start_time DESC, id DESC
            LIMIT 1
            """,
            (pipeline_id, current_run_id),
        )
        prev = cur.fetchone()
        if not prev:
            return None
        cur.execute(
            """
            SELECT COALESCE(SUM(row_count), 0) AS total
            FROM obs_run_assets
            WHERE run_id = %s AND asset_role = 'TARGET'
            """,
            (prev["id"],),
        )
        row = cur.fetchone()
        if not row:
            return None
        return int(row["total"])


def compute_rows_added(
    *,
    target_row_total: int | None,
    rows_written: int | None,
    previous_target_row_total: int | None,
) -> int | None:
    """
    Net new rows in the target table vs the previous run.
    First run: rows_added = current target size.
    Full refresh (same size): rows_added = 0.
    """
    current = target_row_total
    if current is None and rows_written is not None:
        current = int(rows_written)
    if current is None:
        return None
    if previous_target_row_total is None:
        return int(current)
    return int(current) - int(previous_target_row_total)


def apply_rows_added(conn, run_log: dict, target_rows: list[dict]) -> None:
    """Set run_log['rows_added'] from target snapshots vs previous run."""
    pipeline_id = str(run_log.get("pipeline_id") or "")
    run_id = str(run_log.get("id") or "")
    if not pipeline_id or not run_id:
        return
    tgt_total = _target_row_total(target_rows)
    prev_total = get_previous_target_row_count(conn, pipeline_id, run_id)
    run_log["rows_added"] = compute_rows_added(
        target_row_total=tgt_total if tgt_total else None,
        rows_written=run_log.get("rows_written"),
        previous_target_row_total=prev_total,
    )


def backfill_rows_added(conn) -> int:
    """Backfill rows_added for runs that predate the column (ordered per pipeline)."""
    updated = 0
    with conn.cursor() as cur:
        cur.execute("SELECT DISTINCT pipeline_id FROM obs_pipeline_runs")
        pipeline_ids = [r["pipeline_id"] for r in (cur.fetchall() or [])]
        for pipeline_id in pipeline_ids:
            cur.execute(
                """
                SELECT id, rows_written, rows_added
                FROM obs_pipeline_runs
                WHERE pipeline_id = %s
                ORDER BY start_time ASC, id ASC
                """,
                (pipeline_id,),
            )
            runs = cur.fetchall() or []
            prev_tgt: int | None = None
            for run in runs:
                if run.get("rows_added") is not None:
                    cur.execute(
                        """
                        SELECT COALESCE(SUM(row_count), 0) AS total
                        FROM obs_run_assets
                        WHERE run_id = %s AND asset_role = 'TARGET'
                        """,
                        (run["id"],),
                    )
                    snap = cur.fetchone()
                    tgt = int(snap["total"]) if snap else 0
                    if not tgt and run.get("rows_written"):
                        tgt = int(run["rows_written"])
                    prev_tgt = tgt
                    continue
                cur.execute(
                    """
                    SELECT COALESCE(SUM(row_count), 0) AS total
                    FROM obs_run_assets
                    WHERE run_id = %s AND asset_role = 'TARGET'
                    """,
                    (run["id"],),
                )
                snap = cur.fetchone()
                tgt = int(snap["total"]) if snap else 0
                if not tgt and run.get("rows_written"):
                    tgt = int(run["rows_written"])
                added = compute_rows_added(
                    target_row_total=tgt if tgt else None,
                    rows_written=run.get("rows_written"),
                    previous_target_row_total=prev_tgt,
                )
                cur.execute(
                    "UPDATE obs_pipeline_runs SET rows_added = %s WHERE id = %s",
                    (added, run["id"]),
                )
                updated += cur.rowcount
                prev_tgt = tgt if tgt else prev_tgt
    return updated


def store_run(conn, run_log: dict) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO obs_pipeline_runs (
              id, pipeline_id, pipeline_name, status, start_time, end_time, duration,
              tool_name, rows_read, rows_written, rows_added,
              failure_stage, failed_node, failed_message,
              error_message, raw_log,
              execution_mode, triggered_by, orchestrator_tool,
              orchestrator_dag_id, orchestrator_task_id, orchestrator_run_id,
              tenant_id, connector_instance_id
            ) VALUES (
              %s,%s,%s,%s,%s,%s,%s,
              %s,%s,%s,%s,
              %s,%s,%s,
              %s,%s,
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
              rows_written=VALUES(rows_written),
              rows_added=VALUES(rows_added),
              failure_stage=VALUES(failure_stage),
              failed_node=VALUES(failed_node),
              failed_message=VALUES(failed_message)
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
                run_log.get("rows_added"),
                run_log.get("failure_stage"),
                run_log.get("failed_node"),
                run_log.get("failed_message"),
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
    pipeline: dict | None = None,
) -> dict[str, Any]:
    """Write run + source/target assets into Metadata MySQL."""
    conn = get_connection()
    try:
        ensure_tables(conn)
        if pipeline:
            store_pipeline(conn, pipeline)
        apply_rows_added(conn, run_log, target_rows)
        store_run(conn, run_log)
        for row in source_rows:
            store_asset(conn, row)
        for row in target_rows:
            store_asset(conn, row)
        conn.commit()
        tables = ["obs_pipeline_runs", "obs_run_assets"]
        if pipeline:
            tables.insert(0, "obs_pipelines")
        return {
            "ok": True,
            "database": os.getenv("DB_NAME") or "metadata",
            "run_id": run_log.get("id"),
            "pipeline_id": run_log.get("pipeline_id"),
            "sources_stored": len(source_rows),
            "targets_stored": len(target_rows),
            "tables": tables,
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
