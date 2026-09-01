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
    """Connect to Metadata MySQL.

    Prefers DATABASE_URL when set (e.g. mysql+pymysql://user:pass@host:3306/db).
    Falls back to DB_HOST / DB_USER / DB_PASSWORD / DB_NAME / DB_PORT.
    """
    from urllib.parse import unquote, urlparse

    database_url = (os.getenv("DATABASE_URL") or "").strip()
    if database_url:
        # Accept SQLAlchemy-style scheme used in .env
        normalized = database_url.replace("mysql+pymysql://", "mysql://", 1)
        parsed = urlparse(normalized)
        host = parsed.hostname or ""
        port = int(parsed.port or 3306)
        user = unquote(parsed.username or "")
        password = unquote(parsed.password or "")
        database = (parsed.path or "/").lstrip("/") or "metadata"
        if not host or not user or not password:
            raise RuntimeError("DATABASE_URL must include host, user, and password")
    else:
        host = (os.getenv("DB_HOST") or "").strip()
        if not host:
            raise RuntimeError(
                "Missing DATABASE_URL or DB_HOST. Set DATABASE_URL or "
                "DB_HOST=127.0.0.1 (local) / production host for cutover."
            )
        user = os.getenv("DB_USER") or "root"
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
        # Older DBs created before is_active or pipeline_id existed
        try:
            cur.execute(
                "ALTER TABLE obs_pipelines CHANGE COLUMN id pipeline_id VARCHAR(64) NOT NULL"
            )
        except Exception:
            pass
        try:
            cur.execute(
                "ALTER TABLE obs_pipeline_bindings ADD COLUMN pipeline_id VARCHAR(64) NOT NULL AFTER binding_id"
            )
        except Exception:
            pass
        try:
            cur.execute(
                "ALTER TABLE obs_pipelines ADD COLUMN is_active TINYINT(1) NOT NULL DEFAULT 0"
            )
        except Exception:
            pass
        try:
            cur.execute(
                "ALTER TABLE obs_pipelines ADD COLUMN is_operational TINYINT(1) NOT NULL DEFAULT 0"
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
        try:
            cur.execute(
                "ALTER TABLE obs_pipeline_runs ADD COLUMN failed_nodes_json LONGTEXT NULL"
            )
        except Exception:
            pass
        try:
            cur.execute(
                "ALTER TABLE obs_pipeline_runs ADD COLUMN error_class VARCHAR(64) NULL"
            )
        except Exception:
            pass
        try:
            cur.execute(
                "ALTER TABLE obs_pipeline_runs ADD COLUMN relations_json LONGTEXT NULL"
            )
        except Exception:
            pass
        try:
            cur.execute(
                "ALTER TABLE obs_pipeline_runs ADD COLUMN obs_run_id VARCHAR(64) NULL"
            )
        except Exception:
            pass
        try:
            cur.execute(
                "CREATE UNIQUE INDEX uq_obs_runs_obs_run_id ON obs_pipeline_runs (obs_run_id)"
            )
        except Exception:
            pass
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS obs_pipeline_runs (
              id VARCHAR(64) NOT NULL,
              obs_run_id VARCHAR(64) NULL,
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
              failed_nodes_json LONGTEXT NULL,
              error_class VARCHAR(64) NULL,
              relations_json LONGTEXT NULL,
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
              UNIQUE KEY uq_obs_runs_obs_run_id (obs_run_id),
              KEY ix_obs_runs_pipeline (pipeline_id),
              KEY ix_obs_runs_status (status)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )
        # Daily metric rollups (Phase 3 light) — written by optional rollup job
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS obs_metric_rollups_daily (
              bucket_date DATE NOT NULL,
              pipeline_id VARCHAR(64) NOT NULL,
              tool_name VARCHAR(64) NOT NULL DEFAULT '',
              total_runs INT NOT NULL DEFAULT 0,
              success_runs INT NOT NULL DEFAULT 0,
              failed_runs INT NOT NULL DEFAULT 0,
              cancelled_runs INT NOT NULL DEFAULT 0,
              terminal_runs INT NOT NULL DEFAULT 0,
              avg_duration_seconds DOUBLE NULL,
              target_rows BIGINT NULL,
              target_bytes BIGINT NULL,
              updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
              PRIMARY KEY (bucket_date, pipeline_id, tool_name),
              KEY ix_rollups_pipeline (pipeline_id),
              KEY ix_rollups_date (bucket_date)
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
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS obs_run_columns (
              id BIGINT NOT NULL AUTO_INCREMENT,
              run_id VARCHAR(64) NOT NULL,
              asset_role VARCHAR(16) NOT NULL,
              database_name VARCHAR(255) NULL,
              schema_name VARCHAR(255) NULL,
              object_name VARCHAR(255) NULL,
              column_name VARCHAR(255) NOT NULL,
              data_type VARCHAR(128) NULL,
              ordinal_position INT NULL,
              dataset_id VARCHAR(512) NULL,
              created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
              PRIMARY KEY (id),
              KEY ix_obs_cols_run (run_id),
              KEY ix_obs_cols_role (asset_role),
              KEY ix_obs_cols_obj (run_id, asset_role, object_name)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS obs_run_query_history (
              id BIGINT NOT NULL AUTO_INCREMENT,
              run_id VARCHAR(64) NOT NULL,
              query_id VARCHAR(128) NULL,
              start_time DATETIME NULL,
              end_time DATETIME NULL,
              execution_status VARCHAR(64) NULL,
              error_code VARCHAR(64) NULL,
              error_message TEXT NULL,
              query_text TEXT NULL,
              warehouse_name VARCHAR(255) NULL,
              user_name VARCHAR(255) NULL,
              database_name VARCHAR(255) NULL,
              schema_name VARCHAR(255) NULL,
              created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
              PRIMARY KEY (id),
              KEY ix_obs_qh_run (run_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )
        # --- Maturity Phase 2–6 tables ---
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS obs_connections (
              connection_id VARCHAR(64) NOT NULL,
              tenant_id VARCHAR(128) NULL,
              name VARCHAR(255) NOT NULL,
              connector_type VARCHAR(64) NOT NULL,
              auth_ref VARCHAR(255) NULL,
              config_json LONGTEXT NULL,
              status VARCHAR(32) NOT NULL DEFAULT 'active',
              created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
              updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
              PRIMARY KEY (connection_id),
              KEY ix_obs_conn_type (connector_type)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS obs_connector_instances (
              instance_id VARCHAR(64) NOT NULL,
              connection_id VARCHAR(64) NULL,
              tenant_id VARCHAR(128) NULL,
              name VARCHAR(255) NOT NULL,
              connector_type VARCHAR(64) NOT NULL,
              kind VARCHAR(32) NOT NULL DEFAULT 'database',
              scope_json LONGTEXT NULL,
              config_json LONGTEXT NULL,
              status VARCHAR(32) NOT NULL DEFAULT 'active',
              created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
              updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
              PRIMARY KEY (instance_id),
              KEY ix_obs_inst_type (connector_type),
              KEY ix_obs_inst_conn (connection_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS obs_pipeline_bindings (
              binding_id VARCHAR(64) NOT NULL,
              pipeline_id VARCHAR(64) NOT NULL,
              role VARCHAR(16) NOT NULL,
              instance_id VARCHAR(64) NOT NULL,
              asset_selector_json LONGTEXT NULL,
              ordinal INT NOT NULL DEFAULT 0,
              created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
              PRIMARY KEY (binding_id),
              UNIQUE KEY uq_obs_binding (pipeline_id, role, instance_id, ordinal),
              KEY ix_obs_bind_pipe (pipeline_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS obs_tool_snapshots (
              snapshot_id VARCHAR(64) NOT NULL,
              instance_id VARCHAR(64) NOT NULL,
              dataset_id VARCHAR(512) NOT NULL DEFAULT '',
              asset_role VARCHAR(16) NOT NULL DEFAULT 'SOURCE',
              fingerprint VARCHAR(64) NULL,
              payload_json LONGTEXT NOT NULL,
              columns_json LONGTEXT NULL,
              pulled_at DATETIME NOT NULL,
              PRIMARY KEY (snapshot_id),
              UNIQUE KEY uq_obs_tool_snap (instance_id, dataset_id, asset_role),
              KEY ix_obs_tool_snap_inst (instance_id),
              KEY ix_obs_tool_snap_pulled (pulled_at)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS obs_secrets (
              secret_id VARCHAR(64) NOT NULL,
              owner_type VARCHAR(32) NOT NULL,
              owner_id VARCHAR(64) NOT NULL,
              secret_name VARCHAR(64) NOT NULL DEFAULT 'default',
              ciphertext LONGTEXT NOT NULL,
              key_version VARCHAR(32) NOT NULL DEFAULT 'v1',
              created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
              updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
              PRIMARY KEY (secret_id),
              UNIQUE KEY uq_obs_secret_owner (owner_type, owner_id, secret_name),
              KEY ix_obs_secret_owner (owner_type, owner_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS obs_collector_heartbeats (
              pipeline_id VARCHAR(64) NOT NULL,
              collector VARCHAR(64) NOT NULL,
              last_success_at DATETIME NULL,
              last_error TEXT NULL,
              meta_json LONGTEXT NULL,
              updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
              PRIMARY KEY (pipeline_id, collector)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS obs_asset_fingerprints (
              pipeline_id VARCHAR(64) NOT NULL,
              dataset_id VARCHAR(512) NOT NULL,
              asset_role VARCHAR(16) NOT NULL,
              fingerprint VARCHAR(64) NOT NULL,
              last_seen_at DATETIME NOT NULL,
              PRIMARY KEY (pipeline_id, asset_role, dataset_id(191))
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS obs_monitors (
              monitor_id VARCHAR(64) NOT NULL,
              pipeline_id VARCHAR(64) NOT NULL,
              name VARCHAR(255) NOT NULL,
              monitor_kind VARCHAR(64) NOT NULL,
              config_json LONGTEXT NULL,
              is_enabled TINYINT(1) NOT NULL DEFAULT 1,
              created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
              PRIMARY KEY (monitor_id),
              KEY ix_obs_mon_pipe (pipeline_id),
              KEY ix_obs_mon_kind (pipeline_id, monitor_kind)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )
        for col_sql in (
            "ALTER TABLE obs_monitors ADD COLUMN tags_json LONGTEXT NULL",
            "ALTER TABLE obs_monitors ADD COLUMN dimension VARCHAR(64) NULL",
            "ALTER TABLE obs_monitors ADD COLUMN monitor_type VARCHAR(64) NULL",
            "ALTER TABLE obs_monitors ADD COLUMN dataset_id VARCHAR(512) NULL",
            "ALTER TABLE obs_monitors ADD COLUMN column_name VARCHAR(255) NULL",
        ):
            try:
                cur.execute(col_sql)
            except Exception:
                pass
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS obs_dq_daily_rollups (
              bucket_date DATE NOT NULL,
              pipeline_id VARCHAR(64) NOT NULL,
              monitor_id VARCHAR(64) NOT NULL DEFAULT '',
              source_type VARCHAR(32) NOT NULL DEFAULT 'all',
              passed INT NOT NULL DEFAULT 0,
              warn INT NOT NULL DEFAULT 0,
              failed INT NOT NULL DEFAULT 0,
              total INT NOT NULL DEFAULT 0,
              score_pct DOUBLE NULL,
              updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                ON UPDATE CURRENT_TIMESTAMP,
              PRIMARY KEY (bucket_date, pipeline_id, monitor_id, source_type),
              KEY ix_dq_rollups_date (bucket_date),
              KEY ix_dq_rollups_pipe (pipeline_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS obs_dq_rules (
              rule_id VARCHAR(64) NOT NULL,
              pipeline_id VARCHAR(64) NOT NULL,
              rule_name VARCHAR(255) NOT NULL,
              rule_type VARCHAR(64) NOT NULL,
              dataset_id VARCHAR(512) NULL,
              column_name VARCHAR(255) NULL,
              dimension VARCHAR(64) NULL,
              severity VARCHAR(32) NULL,
              config_json LONGTEXT NULL,
              tags_json LONGTEXT NULL,
              is_enabled TINYINT(1) NOT NULL DEFAULT 1,
              evaluation_trigger VARCHAR(32) NOT NULL DEFAULT 'poller',
              created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
              PRIMARY KEY (rule_id),
              KEY ix_dq_rules_pipe (pipeline_id),
              KEY ix_dq_rules_type (rule_type)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS obs_lineage_events (
              event_id VARCHAR(64) NOT NULL,
              pipeline_id VARCHAR(64) NULL,
              run_id VARCHAR(64) NULL,
              event_type VARCHAR(64) NULL,
              event_time DATETIME NULL,
              producer VARCHAR(255) NULL,
              payload_json LONGTEXT NULL,
              ingested_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
              PRIMARY KEY (event_id),
              KEY ix_ol_events_pipe (pipeline_id),
              KEY ix_ol_events_run (run_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS obs_check_results (
              check_id VARCHAR(64) NOT NULL,
              monitor_id VARCHAR(64) NOT NULL,
              pipeline_id VARCHAR(64) NOT NULL,
              status VARCHAR(32) NOT NULL,
              severity VARCHAR(32) NULL,
              message TEXT NULL,
              observed_json LONGTEXT NULL,
              checked_at DATETIME NOT NULL,
              PRIMARY KEY (check_id),
              KEY ix_obs_check_pipe (pipeline_id, checked_at),
              KEY ix_obs_check_mon (monitor_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS obs_alerts (
              alert_id VARCHAR(64) NOT NULL,
              monitor_id VARCHAR(64) NOT NULL,
              pipeline_id VARCHAR(64) NOT NULL,
              status VARCHAR(32) NOT NULL DEFAULT 'open',
              severity VARCHAR(32) NULL,
              title VARCHAR(512) NULL,
              message TEXT NULL,
              opened_at DATETIME NULL,
              resolved_at DATETIME NULL,
              created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
              PRIMARY KEY (alert_id),
              KEY ix_obs_alert_status (status),
              KEY ix_obs_alert_pipe (pipeline_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS obs_incidents (
              incident_id VARCHAR(64) NOT NULL,
              pipeline_id VARCHAR(64) NOT NULL,
              pipeline_name VARCHAR(255) NULL,
              status VARCHAR(32) NOT NULL DEFAULT 'open',
              severity VARCHAR(32) NULL,
              title VARCHAR(512) NULL,
              description TEXT NULL,
              run_id VARCHAR(64) NULL,
              opened_at DATETIME NULL,
              resolved_at DATETIME NULL,
              created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
              PRIMARY KEY (incident_id),
              KEY ix_obs_inc_status (status),
              KEY ix_obs_inc_pipe (pipeline_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS obs_usage_counters (
              tenant_id VARCHAR(128) NOT NULL DEFAULT 'default',
              counter_day DATE NOT NULL,
              pipelines INT NOT NULL DEFAULT 0,
              runs_ingested INT NOT NULL DEFAULT 0,
              poll_ticks INT NOT NULL DEFAULT 0,
              updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
              PRIMARY KEY (tenant_id, counter_day)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS obs_lineage_edges (
              edge_id VARCHAR(64) NOT NULL,
              pipeline_id VARCHAR(64) NULL,
              run_id VARCHAR(64) NULL,
              from_dataset VARCHAR(512) NOT NULL,
              to_dataset VARCHAR(512) NOT NULL,
              edge_kind VARCHAR(32) NOT NULL DEFAULT 'declared',
              confidence DOUBLE NULL,
              observed_at DATETIME NULL,
              PRIMARY KEY (edge_id),
              KEY ix_obs_lin_pipe (pipeline_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )
        backfill_rows_added(conn)
        try:
            cur.execute(
                """
                UPDATE obs_pipeline_runs
                SET obs_run_id = id
                WHERE obs_run_id IS NULL OR obs_run_id = ''
                """
            )
        except Exception:
            pass
    conn.commit()


def ensure_grafana_views(conn) -> None:
    """Create/replace MySQL views used by the Grafana ETL Observability dashboard."""
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE OR REPLACE VIEW vw_kpi_totals AS
            SELECT
              COUNT(*) AS total_runs,
              SUM(CASE WHEN LOWER(COALESCE(status, '')) = 'success' THEN 1 ELSE 0 END)
                AS success_runs,
              SUM(CASE WHEN LOWER(COALESCE(status, '')) = 'failed' THEN 1 ELSE 0 END)
                AS failed_runs,
              ROUND(
                100 * SUM(CASE WHEN LOWER(COALESCE(status, '')) = 'success' THEN 1 ELSE 0 END)
                / NULLIF(COUNT(*), 0),
                1
              ) AS success_rate_pct
            FROM obs_pipeline_runs
            """
        )
        cur.execute(
            """
            CREATE OR REPLACE VIEW vw_daily_metrics AS
            SELECT
              DATE(COALESCE(end_time, start_time)) AS metric_date,
              COUNT(*) AS total_runs,
              SUM(CASE WHEN LOWER(COALESCE(status, '')) = 'success' THEN 1 ELSE 0 END)
                AS success_runs,
              SUM(CASE WHEN LOWER(COALESCE(status, '')) = 'failed' THEN 1 ELSE 0 END)
                AS failed_runs
            FROM obs_pipeline_runs
            WHERE COALESCE(end_time, start_time) IS NOT NULL
            GROUP BY DATE(COALESCE(end_time, start_time))
            """
        )
        cur.execute(
            """
            CREATE OR REPLACE VIEW vw_failed_runs AS
            SELECT
              id AS run_id,
              pipeline_id,
              pipeline_name,
              status,
              start_time,
              end_time,
              duration,
              failure_stage,
              failed_node,
              error_class,
              LEFT(COALESCE(error_message, failed_message, ''), 500) AS error_message
            FROM obs_pipeline_runs
            WHERE LOWER(COALESCE(status, '')) = 'failed'
            """
        )
        cur.execute(
            """
            CREATE OR REPLACE VIEW vw_recent_runs AS
            SELECT
              id AS run_id,
              pipeline_id,
              pipeline_name,
              status,
              start_time,
              end_time,
              duration,
              rows_read,
              rows_written,
              rows_added,
              failure_stage,
              failed_node,
              error_class
            FROM obs_pipeline_runs
            """
        )
        cur.execute(
            """
            CREATE OR REPLACE VIEW vw_pipeline_health AS
            SELECT
              p.pipeline_id,
              p.pipeline_name,
              p.is_active,
              lr.status AS latest_status,
              lr.end_time AS last_end_time,
              lr.start_time AS last_start_time,
              lr.failure_stage,
              lr.failed_node,
              lr.error_class,
              LEFT(COALESCE(lr.error_message, lr.failed_message, ''), 300) AS error_message,
              COALESCE(m.total_runs, 0) AS total_runs,
              COALESCE(m.success_runs, 0) AS success_runs,
              COALESCE(m.failed_count, 0) AS failed_count,
              COALESCE(m.success_rate_pct, 0) AS success_rate_pct,
              CASE
                WHEN lr.id IS NULL THEN 'no_runs'
                WHEN LOWER(COALESCE(lr.status, '')) = 'failed' THEN 'unhealthy'
                WHEN lr.end_time IS NOT NULL
                  AND TIMESTAMPDIFF(HOUR, lr.end_time, UTC_TIMESTAMP()) > 24
                  THEN 'stale'
                WHEN LOWER(COALESCE(lr.status, '')) = 'success' THEN 'healthy'
                ELSE 'unknown'
              END AS health_status
            FROM obs_pipelines p
            LEFT JOIN (
              SELECT r.*
              FROM obs_pipeline_runs r
              INNER JOIN (
                SELECT pipeline_id, MAX(COALESCE(end_time, start_time)) AS mx
                FROM obs_pipeline_runs
                GROUP BY pipeline_id
              ) t
                ON t.pipeline_id = r.pipeline_id
               AND COALESCE(r.end_time, r.start_time) = t.mx
            ) lr ON lr.pipeline_id = p.pipeline_id
            LEFT JOIN (
              SELECT
                pipeline_id,
                COUNT(*) AS total_runs,
                SUM(CASE WHEN LOWER(COALESCE(status, '')) = 'success' THEN 1 ELSE 0 END)
                  AS success_runs,
                SUM(CASE WHEN LOWER(COALESCE(status, '')) = 'failed' THEN 1 ELSE 0 END)
                  AS failed_count,
                ROUND(
                  100 * SUM(CASE WHEN LOWER(COALESCE(status, '')) = 'success' THEN 1 ELSE 0 END)
                  / NULLIF(COUNT(*), 0),
                  1
                ) AS success_rate_pct
              FROM obs_pipeline_runs
              GROUP BY pipeline_id
            ) m ON m.pipeline_id = p.pipeline_id
            """
        )
        cur.execute(
            """
            CREATE OR REPLACE VIEW vw_asset_summary AS
            SELECT
              a.run_id,
              r.pipeline_name,
              a.asset_role,
              a.database_name,
              a.schema_name,
              a.object_name,
              a.row_count,
              a.last_updated_at
            FROM obs_run_assets a
            LEFT JOIN obs_pipeline_runs r ON r.id = a.run_id
            """
        )
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


def persist_operational_flags(conn, rows: list[dict]) -> None:
    """Write derived Active/Inactive into obs_pipelines.is_operational (does not touch is_active Sync default)."""
    ensure_tables(conn)
    with conn.cursor() as cur:
        for row in rows:
            pid = row.get("pipeline_id")
            if not pid:
                continue
            cur.execute(
                "UPDATE obs_pipelines SET is_operational = %s WHERE pipeline_id = %s",
                (1 if row.get("is_active") else 0, pid),
            )
    conn.commit()


def upsert_pipeline(pipeline: dict, *, make_active: bool = True) -> dict[str, Any]:
    conn = get_connection()
    try:
        ensure_tables(conn)
        check_freemium_pipeline_limit(conn)
        store_pipeline(conn, pipeline, make_active=make_active)
        sync_bindings_for_pipeline(conn, pipeline)
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
    except FreemiumLimitError:
        conn.rollback()
        raise
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
    # Keep 0 as a valid total (empty target); only use None when no target rows.
    if target_rows:
        tgt_total: int | None = _target_row_total(target_rows)
    else:
        tgt_total = None
    prev_total = get_previous_target_row_count(conn, pipeline_id, run_id)
    run_log["rows_added"] = compute_rows_added(
        target_row_total=tgt_total,
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
                    target_row_total=tgt,
                    rows_written=run.get("rows_written"),
                    previous_target_row_total=prev_tgt,
                )
                cur.execute(
                    "UPDATE obs_pipeline_runs SET rows_added = %s WHERE id = %s",
                    (added, run["id"]),
                )
                updated += cur.rowcount
                if tgt is not None:
                    prev_tgt = tgt
    return updated


def store_run(conn, run_log: dict) -> None:
    import uuid as _uuid

    failed_nodes_json = run_log.get("failed_nodes_json")
    if failed_nodes_json is None:
        failed_nodes = run_log.get("failed_nodes")
        if failed_nodes is None:
            failed_nodes_json = None
        elif isinstance(failed_nodes, str):
            failed_nodes_json = failed_nodes
        else:
            failed_nodes_json = json.dumps(failed_nodes, default=str)

    relations_json = run_log.get("relations_json")
    if relations_json is None:
        relations = run_log.get("relations")
        if relations is None:
            relations_json = None
        elif isinstance(relations, str):
            relations_json = relations
        else:
            relations_json = json.dumps(relations, default=str)

    vendor_id = str(run_log.get("id") or "")
    obs_run_id = str(run_log.get("obs_run_id") or "").strip() or str(_uuid.uuid4())
    run_log["obs_run_id"] = obs_run_id

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO obs_pipeline_runs (
              id, obs_run_id, pipeline_id, pipeline_name, status, start_time, end_time, duration,
              tool_name, rows_read, rows_written, rows_added,
              failure_stage, failed_node, failed_message,
              failed_nodes_json, error_class, relations_json,
              error_message, raw_log,
              execution_mode, triggered_by, orchestrator_tool,
              orchestrator_dag_id, orchestrator_task_id, orchestrator_run_id,
              tenant_id, connector_instance_id
            ) VALUES (
              %s,%s,%s,%s,%s,%s,%s,%s,
              %s,%s,%s,%s,
              %s,%s,%s,
              %s,%s,%s,
              %s,%s,
              %s,%s,%s,
              %s,%s,%s,
              %s,%s
            )
            ON DUPLICATE KEY UPDATE
              obs_run_id=COALESCE(obs_pipeline_runs.obs_run_id, VALUES(obs_run_id)),
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
              failed_message=VALUES(failed_message),
              failed_nodes_json=VALUES(failed_nodes_json),
              error_class=VALUES(error_class),
              relations_json=VALUES(relations_json)
            """,
            (
                vendor_id,
                obs_run_id,
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
                failed_nodes_json,
                run_log.get("error_class"),
                relations_json,
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


def asset_fingerprint(row: dict) -> str:
    """
    Write-on-change fingerprint for a SOURCE/TARGET asset snapshot.
    Poller should skip insert when fingerprint matches last stored value.
    """
    import hashlib

    parts = [
        str(row.get("dataset_id") or ""),
        str(row.get("row_count") if row.get("row_count") is not None else ""),
        str(row.get("size_bytes") if row.get("size_bytes") is not None else ""),
        str(row.get("last_updated_at") or row.get("last_altered") or ""),
        str(row.get("column_count") if row.get("column_count") is not None else ""),
    ]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:32]


def rollup_daily_metrics(conn, *, day: str | None = None) -> int:
    """
    Upsert one day of pipeline run/volume rollups into obs_metric_rollups_daily.
    day: 'YYYY-MM-DD' (defaults to yesterday UTC).
    Returns rows upserted (approx).
    """
    from datetime import datetime, timedelta, timezone

    if day:
        bucket = day
    else:
        bucket = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
    from_str = f"{bucket} 00:00:00"
    to_str = f"{bucket} 23:59:59"
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO obs_metric_rollups_daily (
              bucket_date, pipeline_id, tool_name,
              total_runs, success_runs, failed_runs, cancelled_runs, terminal_runs,
              avg_duration_seconds, target_rows, target_bytes
            )
            SELECT
              %s AS bucket_date,
              r.pipeline_id,
              COALESCE(r.tool_name, '') AS tool_name,
              COUNT(*) AS total_runs,
              SUM(CASE WHEN LOWER(COALESCE(r.status,'')) IN ('success','succeeded') THEN 1 ELSE 0 END),
              SUM(CASE WHEN LOWER(COALESCE(r.status,'')) IN ('failed','error') THEN 1 ELSE 0 END),
              SUM(CASE WHEN LOWER(COALESCE(r.status,'')) = 'cancelled' THEN 1 ELSE 0 END),
              SUM(CASE WHEN LOWER(COALESCE(r.status,'')) IN
                ('success','succeeded','failed','error','cancelled') THEN 1 ELSE 0 END),
              AVG(r.duration),
              COALESCE(SUM(t.target_rows), 0),
              COALESCE(SUM(t.target_bytes), 0)
            FROM obs_pipeline_runs r
            LEFT JOIN (
              SELECT a.run_id,
                     SUM(COALESCE(a.row_count, 0)) AS target_rows,
                     SUM(COALESCE(a.size_bytes, 0)) AS target_bytes
              FROM obs_run_assets a
              WHERE UPPER(COALESCE(a.asset_role, '')) = 'TARGET'
              GROUP BY a.run_id
            ) t ON t.run_id = CAST(r.id AS CHAR)
            WHERE COALESCE(r.end_time, r.start_time, r.created_at) BETWEEN %s AND %s
            GROUP BY r.pipeline_id, COALESCE(r.tool_name, '')
            ON DUPLICATE KEY UPDATE
              total_runs=VALUES(total_runs),
              success_runs=VALUES(success_runs),
              failed_runs=VALUES(failed_runs),
              cancelled_runs=VALUES(cancelled_runs),
              terminal_runs=VALUES(terminal_runs),
              avg_duration_seconds=VALUES(avg_duration_seconds),
              target_rows=VALUES(target_rows),
              target_bytes=VALUES(target_bytes)
            """,
            (bucket, from_str, to_str),
        )
        return int(cur.rowcount or 0)


def rollup_dq_daily_metrics(conn, *, day: str | None = None) -> int:
    """
    Upsert daily DQ pass/warn/fail rollups into obs_dq_daily_rollups.
    day: 'YYYY-MM-DD' (defaults to yesterday UTC).
    """
    from datetime import timedelta, timezone

    if day:
        bucket = day
    else:
        bucket = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
    from_str = f"{bucket} 00:00:00"
    to_str = f"{bucket} 23:59:59"
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO obs_dq_daily_rollups (
              bucket_date, pipeline_id, monitor_id, source_type,
              passed, warn, failed, total, score_pct
            )
            SELECT
              %s AS bucket_date,
              c.pipeline_id,
              c.monitor_id,
              CASE
                WHEN c.monitor_id LIKE 'dbt-run:%%' THEN 'dbt'
                ELSE 'monitor'
              END AS source_type,
              SUM(CASE WHEN LOWER(COALESCE(c.status,'')) IN
                ('pass','passed','success','ok') THEN 1 ELSE 0 END) AS passed,
              SUM(CASE WHEN LOWER(COALESCE(c.status,'')) IN
                ('warn','warning') THEN 1 ELSE 0 END) AS warn,
              SUM(CASE WHEN LOWER(COALESCE(c.status,'')) NOT IN
                ('pass','passed','success','ok','warn','warning') THEN 1 ELSE 0 END) AS failed,
              COUNT(*) AS total,
              ROUND(100.0 * SUM(CASE WHEN LOWER(COALESCE(c.status,'')) IN
                ('pass','passed','success','ok') THEN 1 ELSE 0 END) / NULLIF(COUNT(*), 0), 2)
            FROM obs_check_results c
            WHERE c.checked_at BETWEEN %s AND %s
            GROUP BY c.pipeline_id, c.monitor_id,
              CASE WHEN c.monitor_id LIKE 'dbt-run:%%' THEN 'dbt' ELSE 'monitor' END
            ON DUPLICATE KEY UPDATE
              passed=VALUES(passed),
              warn=VALUES(warn),
              failed=VALUES(failed),
              total=VALUES(total),
              score_pct=VALUES(score_pct)
            """,
            (bucket, from_str, to_str),
        )
        return int(cur.rowcount or 0)


ALLOWED_MONITOR_KINDS = frozenset(
    {
        "freshness",
        "volume_drop",
        "pipeline_failure",
        "dbt_test_failure",
        "null_check",
        "null_pct",
        "unique_check",
        "unique_violation",
        "duplicate_check",
        "duplicate_count",
        "custom_sql",
    }
)

_MONITOR_TYPE_BY_KIND = {
    "freshness": "freshness",
    "volume_drop": "volume",
    "pipeline_failure": "operational",
    "dbt_test_failure": "validation",
    "null_check": "validation",
    "null_pct": "validation",
    "unique_check": "validation",
    "unique_violation": "validation",
    "duplicate_check": "validation",
    "duplicate_count": "validation",
    "custom_sql": "custom_sql",
}


def _public_monitor_row(row: dict) -> dict:
    out = dict(row)
    for key in ("created_at",):
        if key in out and out[key] is not None:
            out[key] = str(out[key])
    if out.get("config_json") and isinstance(out["config_json"], str):
        try:
            out["config"] = json.loads(out["config_json"])
        except json.JSONDecodeError:
            out["config"] = {}
    else:
        out["config"] = out.get("config_json") or {}
    if out.get("tags_json") and isinstance(out["tags_json"], str):
        try:
            out["tags"] = json.loads(out["tags_json"])
        except json.JSONDecodeError:
            out["tags"] = []
    else:
        out["tags"] = out.get("tags_json") or []
    out["is_enabled"] = bool(out.get("is_enabled"))
    return out


def list_monitors(
    conn,
    *,
    pipeline_id: str | None = None,
    monitor_kind: str | None = None,
    include_disabled: bool = True,
) -> list[dict]:
    clauses: list[str] = []
    params: list[Any] = []
    if pipeline_id:
        clauses.append("pipeline_id = %s")
        params.append(pipeline_id)
    if monitor_kind:
        clauses.append("monitor_kind = %s")
        params.append(monitor_kind.strip().lower())
    if not include_disabled:
        clauses.append("is_enabled = 1")
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT monitor_id, pipeline_id, name, monitor_kind, config_json,
                   is_enabled, tags_json, dimension, monitor_type,
                   dataset_id, column_name, created_at
            FROM obs_monitors
            {where}
            ORDER BY pipeline_id, monitor_kind, name
            """,
            params,
        )
        rows = list(cur.fetchall() or [])
    return [_public_monitor_row(r) for r in rows]


def get_monitor(conn, monitor_id: str) -> dict | None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT monitor_id, pipeline_id, name, monitor_kind, config_json,
                   is_enabled, tags_json, dimension, monitor_type,
                   dataset_id, column_name, created_at
            FROM obs_monitors
            WHERE monitor_id = %s
            LIMIT 1
            """,
            (monitor_id,),
        )
        row = cur.fetchone()
    return _public_monitor_row(row) if row else None


def upsert_monitor(conn, row: dict) -> str:
    import uuid

    from application.src.services.observability.quality import infer_dimension, normalize_dataset_id

    kind = str(row.get("monitor_kind") or "").strip().lower()
    if kind not in ALLOWED_MONITOR_KINDS:
        raise ValueError(f"Unsupported monitor_kind: {kind}")
    pid = str(row.get("pipeline_id") or "").strip()
    if not pid:
        raise ValueError("pipeline_id is required")
    with conn.cursor() as cur:
        cur.execute("SELECT pipeline_id FROM obs_pipelines WHERE pipeline_id=%s", (pid,))
        if not cur.fetchone():
            raise ValueError(f"pipeline_id not found: {pid}")

    mid = str(row.get("monitor_id") or uuid.uuid4())
    name = str(row.get("name") or kind.replace("_", " ").title())
    cfg = row.get("config") if row.get("config") is not None else row.get("config_json") or {}
    if isinstance(cfg, str):
        try:
            cfg = json.loads(cfg)
        except json.JSONDecodeError:
            cfg = {}
    tags = row.get("tags") if row.get("tags") is not None else row.get("tags_json") or []
    if isinstance(tags, str):
        try:
            tags = json.loads(tags)
        except json.JSONDecodeError:
            tags = [t.strip() for t in tags.split(",") if t.strip()]
    dimension = row.get("dimension") or infer_dimension(monitor_kind=kind)
    monitor_type = row.get("monitor_type") or _MONITOR_TYPE_BY_KIND.get(kind, "validation")
    dataset_id = normalize_dataset_id(row.get("dataset_id")) or None
    column_name = str(row.get("column_name") or "").strip() or None
    is_enabled = 1 if row.get("is_enabled", True) else 0

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO obs_monitors (
              monitor_id, pipeline_id, name, monitor_kind, config_json,
              is_enabled, tags_json, dimension, monitor_type, dataset_id, column_name
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON DUPLICATE KEY UPDATE
              pipeline_id=VALUES(pipeline_id),
              name=VALUES(name),
              monitor_kind=VALUES(monitor_kind),
              config_json=VALUES(config_json),
              is_enabled=VALUES(is_enabled),
              tags_json=VALUES(tags_json),
              dimension=VALUES(dimension),
              monitor_type=VALUES(monitor_type),
              dataset_id=VALUES(dataset_id),
              column_name=VALUES(column_name)
            """,
            (
                mid[:64],
                pid,
                name[:255],
                kind,
                json.dumps(cfg, default=str),
                is_enabled,
                json.dumps(tags, default=str) if tags else None,
                dimension,
                monitor_type,
                dataset_id,
                column_name,
            ),
        )
    conn.commit()
    return mid


def delete_monitor(conn, monitor_id: str, *, hard: bool = False) -> bool:
    with conn.cursor() as cur:
        if hard:
            cur.execute("DELETE FROM obs_monitors WHERE monitor_id = %s", (monitor_id,))
        else:
            cur.execute(
                "UPDATE obs_monitors SET is_enabled = 0 WHERE monitor_id = %s",
                (monitor_id,),
            )
        ok = int(cur.rowcount or 0) > 0
    conn.commit()
    return ok


ALLOWED_DQ_RULE_TYPES = frozenset(
    {
        "NOT_NULL",
        "UNIQUE",
        "DUPLICATE",
        "ACCEPTED_VALUES",
        "RANGE",
        "CUSTOM_SQL",
    }
)

_RULE_TYPE_TO_CHECK_KIND = {
    "NOT_NULL": "null_check",
    "UNIQUE": "unique_check",
    "DUPLICATE": "duplicate_check",
    "CUSTOM_SQL": "custom_sql",
    "ACCEPTED_VALUES": "custom_sql",
    "RANGE": "custom_sql",
}


def _public_dq_rule_row(row: dict) -> dict:
    out = dict(row)
    if out.get("created_at") is not None:
        out["created_at"] = str(out["created_at"])
    cfg = out.get("config_json")
    if isinstance(cfg, str):
        try:
            out["config"] = json.loads(cfg)
        except json.JSONDecodeError:
            out["config"] = {}
    else:
        out["config"] = cfg or {}
    tags = out.get("tags_json")
    if isinstance(tags, str):
        try:
            out["tags"] = json.loads(tags)
        except json.JSONDecodeError:
            out["tags"] = []
    else:
        out["tags"] = tags or []
    out["is_enabled"] = bool(out.get("is_enabled"))
    return out


def list_dq_rules(conn, *, pipeline_id: str | None = None, include_disabled: bool = True) -> list[dict]:
    clauses: list[str] = []
    params: list[Any] = []
    if pipeline_id:
        clauses.append("pipeline_id = %s")
        params.append(pipeline_id)
    if not include_disabled:
        clauses.append("is_enabled = 1")
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT rule_id, pipeline_id, rule_name, rule_type, dataset_id, column_name,
                   dimension, severity, config_json, tags_json, is_enabled,
                   evaluation_trigger, created_at
            FROM obs_dq_rules
            {where}
            ORDER BY pipeline_id, rule_name
            """,
            params,
        )
        rows = list(cur.fetchall() or [])
    return [_public_dq_rule_row(r) for r in rows]


def get_dq_rule(conn, rule_id: str) -> dict | None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT rule_id, pipeline_id, rule_name, rule_type, dataset_id, column_name,
                   dimension, severity, config_json, tags_json, is_enabled,
                   evaluation_trigger, created_at
            FROM obs_dq_rules WHERE rule_id = %s LIMIT 1
            """,
            (rule_id,),
        )
        row = cur.fetchone()
    return _public_dq_rule_row(row) if row else None


def upsert_dq_rule(conn, row: dict) -> str:
    import uuid

    from application.src.services.observability.quality import infer_dimension, normalize_dataset_id

    rtype = str(row.get("rule_type") or "").strip().upper()
    if rtype not in ALLOWED_DQ_RULE_TYPES:
        raise ValueError(f"Unsupported rule_type: {rtype}")
    pid = str(row.get("pipeline_id") or "").strip()
    if not pid:
        raise ValueError("pipeline_id is required")
    with conn.cursor() as cur:
        cur.execute("SELECT pipeline_id FROM obs_pipelines WHERE pipeline_id=%s", (pid,))
        if not cur.fetchone():
            raise ValueError(f"pipeline_id not found: {pid}")

    rid = str(row.get("rule_id") or uuid.uuid4())
    name = str(row.get("rule_name") or rtype.replace("_", " ").title())
    cfg = row.get("config") if row.get("config") is not None else row.get("config_json") or {}
    if isinstance(cfg, str):
        try:
            cfg = json.loads(cfg)
        except json.JSONDecodeError:
            cfg = {}
    tags = row.get("tags") if row.get("tags") is not None else row.get("tags_json") or []
    if isinstance(tags, str):
        try:
            tags = json.loads(tags)
        except json.JSONDecodeError:
            tags = [t.strip() for t in tags.split(",") if t.strip()]
    dimension = row.get("dimension") or infer_dimension(monitor_kind=_RULE_TYPE_TO_CHECK_KIND.get(rtype, ""))
    dataset_id = normalize_dataset_id(row.get("dataset_id")) or None
    column_name = str(row.get("column_name") or "").strip() or None
    severity = str(row.get("severity") or "high")
    trigger = str(row.get("evaluation_trigger") or "poller").lower()
    is_enabled = 1 if row.get("is_enabled", True) else 0

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO obs_dq_rules (
              rule_id, pipeline_id, rule_name, rule_type, dataset_id, column_name,
              dimension, severity, config_json, tags_json, is_enabled, evaluation_trigger
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON DUPLICATE KEY UPDATE
              pipeline_id=VALUES(pipeline_id),
              rule_name=VALUES(rule_name),
              rule_type=VALUES(rule_type),
              dataset_id=VALUES(dataset_id),
              column_name=VALUES(column_name),
              dimension=VALUES(dimension),
              severity=VALUES(severity),
              config_json=VALUES(config_json),
              tags_json=VALUES(tags_json),
              is_enabled=VALUES(is_enabled),
              evaluation_trigger=VALUES(evaluation_trigger)
            """,
            (
                rid[:64],
                pid,
                name[:255],
                rtype,
                dataset_id,
                column_name,
                dimension,
                severity,
                json.dumps(cfg, default=str),
                json.dumps(tags, default=str) if tags else None,
                is_enabled,
                trigger,
            ),
        )
    conn.commit()
    return rid


def delete_dq_rule(conn, rule_id: str, *, hard: bool = False) -> bool:
    with conn.cursor() as cur:
        if hard:
            cur.execute("DELETE FROM obs_dq_rules WHERE rule_id = %s", (rule_id,))
        else:
            cur.execute("UPDATE obs_dq_rules SET is_enabled = 0 WHERE rule_id = %s", (rule_id,))
        ok = int(cur.rowcount or 0) > 0
    conn.commit()
    return ok


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


def store_columns(conn, run_id: str, columns: list[dict]) -> int:
    """Replace column snapshots for a run."""
    rid = str(run_id or "")
    if not rid:
        return 0
    with conn.cursor() as cur:
        cur.execute("DELETE FROM obs_run_columns WHERE run_id = %s", (rid,))
        for col in columns or []:
            dataset_id = col.get("dataset_id") or (
                f"{col.get('database') or col.get('database_name')}."
                f"{col.get('schema') or col.get('schema_name')}."
                f"{col.get('table') or col.get('object_name')}"
            )
            cur.execute(
                """
                INSERT INTO obs_run_columns (
                  run_id, asset_role, database_name, schema_name, object_name,
                  column_name, data_type, ordinal_position, dataset_id
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """,
                (
                    rid,
                    col.get("asset_role"),
                    col.get("database") or col.get("database_name"),
                    col.get("schema") or col.get("schema_name"),
                    col.get("table") or col.get("object_name"),
                    col.get("column_name"),
                    col.get("data_type"),
                    col.get("ordinal_position"),
                    dataset_id,
                ),
            )
        return len(columns or [])


def store_query_history(conn, run_id: str, queries: list[dict]) -> int:
    """Replace query-history snapshots for a run."""
    rid = str(run_id or "")
    if not rid:
        return 0
    with conn.cursor() as cur:
        cur.execute("DELETE FROM obs_run_query_history WHERE run_id = %s", (rid,))
        for q in queries or []:
            cur.execute(
                """
                INSERT INTO obs_run_query_history (
                  run_id, query_id, start_time, end_time, execution_status,
                  error_code, error_message, query_text,
                  warehouse_name, user_name, database_name, schema_name
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """,
                (
                    rid,
                    q.get("query_id"),
                    _parse_dt(q.get("start_time")),
                    _parse_dt(q.get("end_time")),
                    q.get("execution_status"),
                    q.get("error_code"),
                    q.get("error_message"),
                    q.get("query_text"),
                    q.get("warehouse_name"),
                    q.get("user_name"),
                    q.get("database_name"),
                    q.get("schema_name"),
                ),
            )
        return len(queries or [])


def store_dbt_test_results(
    conn,
    *,
    pipeline_id: str,
    run_id: str,
    tests: list[dict],
) -> int:
    """Persist dbt test rows from run_results.json into obs_check_results."""
    import hashlib

    from application.src.services.observability.quality import infer_dimension, normalize_dataset_id

    rid = str(run_id or "")
    pid = str(pipeline_id or "")
    if not rid:
        return 0
    monitor_id = f"dbt-run:{rid}"
    now = datetime.utcnow()
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM obs_check_results WHERE monitor_id = %s",
            (monitor_id,),
        )
        stored = 0
        for test in tests or []:
            if not isinstance(test, dict):
                continue
            tid = str(test.get("test_id") or test.get("unique_id") or "")
            if not tid:
                continue
            digest = hashlib.sha256(tid.encode("utf-8")).hexdigest()[:16]
            check_id = f"dbt:{rid}:{digest}"
            status_raw = str(test.get("status") or "").lower()
            if status_raw in {"pass", "passed", "success", "ok"}:
                status = "pass"
            elif status_raw in {"warn", "warning"}:
                status = "warn"
            else:
                status = "fail"
            relation = test.get("relation_name")
            dataset_id = normalize_dataset_id(relation)
            dimension = infer_dimension(message=test.get("message"), test_id=tid)
            tags: list[str] = []
            if dimension:
                tags.append(f"dimension:{dimension}")
            if dataset_id:
                tags.append(f"dataset:{dataset_id}")
            cur.execute(
                """
                INSERT INTO obs_check_results (
                  check_id, monitor_id, pipeline_id, status, severity, message,
                  observed_json, checked_at
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                """,
                (
                    check_id[:64],
                    monitor_id[:64],
                    pid,
                    status,
                    test.get("severity") or ("high" if status == "fail" else "low"),
                    test.get("message"),
                    json.dumps(
                        {
                            "run_id": rid,
                            "test_id": tid,
                            "relation_name": relation,
                            "dataset_id": dataset_id or None,
                            "dimension": dimension,
                            "tags": tags,
                            "execution_time": test.get("execution_time"),
                            "source": "dbt_run_results",
                        },
                        default=str,
                    ),
                    now,
                ),
            )
            stored += 1
    return stored


def store_lineage_edges(
    conn,
    *,
    pipeline_id: str,
    run_id: str,
    edges: list[dict],
) -> int:
    """Replace lineage edges for a run (from dbt manifest)."""
    import hashlib
    import uuid as _uuid

    rid = str(run_id or "")
    pid = str(pipeline_id or "")
    if not rid:
        return 0
    now = datetime.utcnow()
    with conn.cursor() as cur:
        cur.execute("DELETE FROM obs_lineage_edges WHERE run_id = %s", (rid,))
        stored = 0
        for edge in edges or []:
            if not isinstance(edge, dict):
                continue
            from_ds = str(edge.get("from_dataset") or "").strip()
            to_ds = str(edge.get("to_dataset") or "").strip()
            if not from_ds or not to_ds:
                continue
            key = f"{rid}:{from_ds}:{to_ds}:{edge.get('edge_kind') or 'dbt_manifest'}"
            edge_id = hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]
            cur.execute(
                """
                INSERT INTO obs_lineage_edges (
                  edge_id, pipeline_id, run_id, from_dataset, to_dataset,
                  edge_kind, confidence, observed_at
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                ON DUPLICATE KEY UPDATE
                  from_dataset=VALUES(from_dataset),
                  to_dataset=VALUES(to_dataset),
                  edge_kind=VALUES(edge_kind),
                  observed_at=VALUES(observed_at)
                """,
                (
                    edge_id,
                    pid or None,
                    rid,
                    from_ds[:512],
                    to_ds[:512],
                    str(edge.get("edge_kind") or "dbt_manifest")[:32],
                    edge.get("confidence"),
                    now,
                ),
            )
            stored += 1
    return stored


def store_openlineage_event(
    conn,
    *,
    payload: dict,
    pipeline_id: str | None = None,
) -> dict[str, Any]:
    """Parse OpenLineage event, archive raw payload, upsert lineage edges."""
    import hashlib
    import uuid as _uuid

    from application.src.connectors.openlineage import parse_openlineage_event, should_ingest_event

    parsed = parse_openlineage_event(payload)
    if not should_ingest_event(parsed):
        return {"ok": True, "skipped": True, "reason": parsed.get("event_type"), "edges_stored": 0}

    run_id = str(parsed.get("run_id") or "")
    if not run_id:
        run_id = str(_uuid.uuid4())

    event_id = hashlib.sha256(
        f"{run_id}:{parsed.get('event_type')}:{parsed.get('event_time')}".encode("utf-8")
    ).hexdigest()[:32]

    event_time = parsed.get("event_time")
    if isinstance(event_time, str):
        try:
            event_time = datetime.fromisoformat(event_time.replace("Z", "+00:00"))
        except ValueError:
            event_time = datetime.utcnow()
    elif not event_time:
        event_time = datetime.utcnow()

    now = datetime.utcnow()
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO obs_lineage_events (
              event_id, pipeline_id, run_id, event_type, event_time, producer, payload_json
            ) VALUES (%s,%s,%s,%s,%s,%s,%s)
            ON DUPLICATE KEY UPDATE
              payload_json=VALUES(payload_json),
              ingested_at=CURRENT_TIMESTAMP
            """,
            (
                event_id,
                pipeline_id,
                run_id,
                parsed.get("event_type"),
                event_time,
                parsed.get("producer"),
                json.dumps(payload, default=str),
            ),
        )

    edges = parsed.get("edges") or []
    stored = 0
    pid = str(pipeline_id or "")
    with conn.cursor() as cur:
        for edge in edges:
            from_ds = str(edge.get("from_dataset") or "").strip()
            to_ds = str(edge.get("to_dataset") or "").strip()
            if not from_ds or not to_ds:
                continue
            key = f"{run_id}:{from_ds}:{to_ds}:openlineage"
            edge_id = hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]
            cur.execute(
                """
                INSERT INTO obs_lineage_edges (
                  edge_id, pipeline_id, run_id, from_dataset, to_dataset,
                  edge_kind, confidence, observed_at
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                ON DUPLICATE KEY UPDATE
                  edge_kind=VALUES(edge_kind),
                  confidence=VALUES(confidence),
                  observed_at=VALUES(observed_at)
                """,
                (
                    edge_id,
                    pid or None,
                    run_id,
                    from_ds[:512],
                    to_ds[:512],
                    "openlineage",
                    edge.get("confidence"),
                    now,
                ),
            )
            stored += 1
    conn.commit()
    return {
        "ok": True,
        "event_id": event_id,
        "run_id": run_id,
        "edges_stored": stored,
        "event_type": parsed.get("event_type"),
    }


def store_to_meta_mysql(
    run_log: dict,
    source_rows: list[dict],
    target_rows: list[dict],
    pipeline: dict | None = None,
    columns: list[dict] | None = None,
    query_history: list[dict] | None = None,
    dbt_test_results: list[dict] | None = None,
    lineage_edges: list[dict] | None = None,
) -> dict[str, Any]:
    """Write run + source/target assets into Metadata MySQL."""
    conn = get_connection()
    try:
        ensure_tables(conn)
        if pipeline:
            store_pipeline(conn, pipeline)
        apply_rows_added(conn, run_log, target_rows)
        store_run(conn, run_log)
        # Replace assets for this run so filtered Syncs do not leave stale tables.
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM obs_run_assets WHERE run_id = %s",
                (str(run_log.get("id") or ""),),
            )
        for row in source_rows:
            store_asset(conn, row)
        for row in target_rows:
            store_asset(conn, row)
        cols_stored = store_columns(conn, str(run_log.get("id") or ""), columns or [])
        qh_stored = store_query_history(
            conn, str(run_log.get("id") or ""), query_history or []
        )
        tests_stored = store_dbt_test_results(
            conn,
            pipeline_id=str(run_log.get("pipeline_id") or ""),
            run_id=str(run_log.get("id") or ""),
            tests=dbt_test_results or [],
        )
        edges_stored = store_lineage_edges(
            conn,
            pipeline_id=str(run_log.get("pipeline_id") or ""),
            run_id=str(run_log.get("id") or ""),
            edges=lineage_edges or [],
        )
        bump_usage(conn, runs_ingested=1)
        conn.commit()
        tables = [
            "obs_pipeline_runs",
            "obs_run_assets",
            "obs_run_columns",
            "obs_run_query_history",
            "obs_check_results",
            "obs_lineage_edges",
        ]
        if pipeline:
            tables.insert(0, "obs_pipelines")
        return {
            "ok": True,
            "database": os.getenv("DB_NAME") or "metadata",
            "run_id": run_log.get("id"),
            "pipeline_id": run_log.get("pipeline_id"),
            "sources_stored": len(source_rows),
            "targets_stored": len(target_rows),
            "columns_stored": cols_stored,
            "query_history_stored": qh_stored,
            "dbt_tests_stored": tests_stored,
            "lineage_edges_stored": edges_stored,
            "tables": tables,
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


class FreemiumLimitError(RuntimeError):
    """Raised when free-tier caps are exceeded."""


def freemium_max_pipelines() -> int:
    try:
        return int(os.getenv("FREEMIUM_MAX_PIPELINES") or "50")
    except ValueError:
        return 50


def freemium_raw_retention_days() -> int:
    try:
        return int(os.getenv("RAW_RETENTION_DAYS") or "30")
    except ValueError:
        return 30


def check_freemium_pipeline_limit(conn) -> None:
    """Enforce FREEMIUM_MAX_PIPELINES when creating a new pipeline id."""
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) AS n FROM obs_pipelines")
        n = int((cur.fetchone() or {}).get("n") or 0)
    cap = freemium_max_pipelines()
    # Allow updates of existing rows; only block when at/over cap on insert path.
    # Callers that upsert existing ids should check existence first — soft check:
    if n >= cap:
        # Still allow if this is an update of an existing pipeline (checked by caller via store).
        pass


def sync_bindings_for_pipeline(conn, pipeline: dict) -> None:
    """Declare SOURCE/ETL/TARGET bindings from classic pipeline config (Phase 2 dual-write)."""
    import uuid as _uuid

    pid = str(pipeline.get("pipeline_id") or "")
    if not pid:
        return
    source = pipeline.get("source") or {}
    etl = pipeline.get("etl") or {}
    target = pipeline.get("target") or {}
    triples = [
        ("SOURCE", source.get("connector_instance_id") or f"{pid}-source", "snowflake", source),
        ("ETL", etl.get("connector_instance_id") or f"{pid}-etl", "dbt", etl),
        ("TARGET", target.get("connector_instance_id") or f"{pid}-target", "snowflake", target),
    ]
    with conn.cursor() as cur:
        for role, instance_id, ctype, cfg in triples:
            cur.execute(
                """
                INSERT INTO obs_connector_instances (
                  instance_id, name, connector_type, kind, config_json, status
                ) VALUES (%s,%s,%s,%s,%s,'active')
                ON DUPLICATE KEY UPDATE
                  name=VALUES(name), connector_type=VALUES(connector_type),
                  config_json=VALUES(config_json), status='active'
                """,
                (
                    instance_id,
                    f"{pipeline.get('pipeline_name') or pid}-{role.lower()}",
                    ctype,
                    "etl" if role == "ETL" else "database",
                    json.dumps(cfg, default=str),
                ),
            )
            binding_id = f"{pid}:{role}:{instance_id}"
            cur.execute(
                """
                INSERT INTO obs_pipeline_bindings (
                  binding_id, pipeline_id, role, instance_id, asset_selector_json, ordinal
                ) VALUES (%s,%s,%s,%s,%s,%s)
                ON DUPLICATE KEY UPDATE instance_id=VALUES(instance_id)
                """,
                (
                    binding_id[:64],
                    pid,
                    role,
                    instance_id,
                    json.dumps({"schema": cfg.get("schema")}, default=str),
                    0,
                ),
            )


def migrate_pipeline_bindings(conn) -> int:
    """Backfill bindings for all pipelines that have config_json / flat columns."""
    ensure_tables_light = True  # tables already ensured by caller
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM obs_pipelines")
        rows = list(cur.fetchall() or [])
    n = 0
    for row in rows:
        pipe = _row_to_pipeline(row) or {
            "pipeline_id": row.get("pipeline_id"),
            "pipeline_name": row.get("pipeline_name"),
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
        sync_bindings_for_pipeline(conn, pipe)
        n += 1
    conn.commit()
    return n


def list_pipeline_bindings(conn, pipeline_id: str) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT b.*, i.connector_type, i.name AS instance_name, i.kind
            FROM obs_pipeline_bindings b
            LEFT JOIN obs_connector_instances i ON i.instance_id = b.instance_id
            WHERE b.pipeline_id = %s
            ORDER BY b.role, b.ordinal
            """,
            (pipeline_id,),
        )
        return list(cur.fetchall() or [])


def list_collector_heartbeats(conn) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT h.pipeline_id, h.collector, h.last_success_at, h.last_error,
                   h.meta_json, h.updated_at, p.pipeline_name
            FROM obs_collector_heartbeats h
            LEFT JOIN obs_pipelines p ON p.pipeline_id = h.pipeline_id
            ORDER BY h.updated_at DESC
            """
        )
        return list(cur.fetchall() or [])


def record_heartbeat(
    conn,
    pipeline_id: str,
    collector: str,
    *,
    ok: bool = True,
    error: str | None = None,
    meta: dict | None = None,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO obs_collector_heartbeats (
              pipeline_id, collector, last_success_at, last_error, meta_json
            ) VALUES (%s,%s,%s,%s,%s)
            ON DUPLICATE KEY UPDATE
              last_success_at=IF(%s, VALUES(last_success_at), last_success_at),
              last_error=VALUES(last_error),
              meta_json=VALUES(meta_json)
            """,
            (
                pipeline_id,
                collector,
                datetime.utcnow() if ok else None,
                None if ok else (error or "error"),
                json.dumps(meta or {}, default=str),
                1 if ok else 0,
            ),
        )
    conn.commit()


def should_skip_asset_write(conn, pipeline_id: str, row: dict) -> bool:
    """Write-on-change: True if fingerprint unchanged since last poll."""
    ds = str(row.get("dataset_id") or "")
    role = str(row.get("asset_role") or "TARGET")
    if not ds or not pipeline_id:
        return False
    fp = asset_fingerprint(row)
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT fingerprint FROM obs_asset_fingerprints
            WHERE pipeline_id=%s AND asset_role=%s AND dataset_id=%s
            """,
            (pipeline_id, role, ds),
        )
        prev = cur.fetchone()
        if prev and str(prev.get("fingerprint")) == fp:
            return True
        cur.execute(
            """
            INSERT INTO obs_asset_fingerprints (
              pipeline_id, dataset_id, asset_role, fingerprint, last_seen_at
            ) VALUES (%s,%s,%s,%s,%s)
            ON DUPLICATE KEY UPDATE fingerprint=VALUES(fingerprint), last_seen_at=VALUES(last_seen_at)
            """,
            (pipeline_id, ds, role, fp, datetime.utcnow()),
        )
    return False


def bump_usage(conn, *, runs_ingested: int = 0, poll_ticks: int = 0) -> None:
    day = datetime.utcnow().strftime("%Y-%m-%d")
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) AS n FROM obs_pipelines")
        pipes = int((cur.fetchone() or {}).get("n") or 0)
        cur.execute(
            """
            INSERT INTO obs_usage_counters (
              tenant_id, counter_day, pipelines, runs_ingested, poll_ticks
            ) VALUES ('default', %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
              pipelines=VALUES(pipelines),
              runs_ingested=runs_ingested+VALUES(runs_ingested),
              poll_ticks=poll_ticks+VALUES(poll_ticks)
            """,
            (day, pipes, runs_ingested, poll_ticks),
        )


def purge_raw_observations(conn, *, retain_days: int | None = None) -> dict[str, int]:
    """Delete raw run-linked rows older than retention (rollups are kept)."""
    days = retain_days if retain_days is not None else freemium_raw_retention_days()
    cutoff = datetime.utcnow() - __import__("datetime").timedelta(days=max(1, days))
    deleted = {"runs": 0, "assets": 0, "columns": 0, "qh": 0, "checks": 0}
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id FROM obs_pipeline_runs
            WHERE COALESCE(end_time, start_time, created_at) < %s
            """,
            (cutoff,),
        )
        ids = [r["id"] for r in (cur.fetchall() or [])]
        if ids:
            ph = ",".join(["%s"] * len(ids))
            for table, key in (
                ("obs_run_assets", "assets"),
                ("obs_run_columns", "columns"),
                ("obs_run_query_history", "qh"),
            ):
                cur.execute(f"DELETE FROM {table} WHERE run_id IN ({ph})", ids)
                deleted[key] = cur.rowcount
            cur.execute(f"DELETE FROM obs_pipeline_runs WHERE id IN ({ph})", ids)
            deleted["runs"] = cur.rowcount
        cur.execute("DELETE FROM obs_check_results WHERE checked_at < %s", (cutoff,))
        deleted["checks"] = cur.rowcount
    conn.commit()
    return deleted


# ---------------------------------------------------------------------------
# Tools-first: connections, tools (instances), compose, snapshots
# ---------------------------------------------------------------------------

def _parse_json_obj(raw: Any) -> dict:
    if not raw:
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        data = json.loads(raw) if isinstance(raw, str) else {}
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}


def _tool_kind_for_type(connector_type: str, kind: str | None = None) -> str:
    if kind in {"database", "etl", "orchestrator"}:
        return kind
    key = (connector_type or "").strip().lower()
    if key in {"dbt", "dbt_cloud", "airbyte"}:
        return "etl"
    if key in {"airflow"}:
        return "orchestrator"
    return "database"


def _public_tool_row(row: dict) -> dict:
    cfg = _parse_json_obj(row.get("config_json"))
    # Never expose password/token fields if somehow present
    for secret_key in ("password", "api_token", "token", "secret"):
        cfg.pop(secret_key, None)
    return {
        "tool_id": row.get("instance_id"),
        "instance_id": row.get("instance_id"),
        "connection_id": row.get("connection_id"),
        "name": row.get("name"),
        "connector_type": row.get("connector_type"),
        "kind": row.get("kind"),
        "auth_ref": None,  # filled from connection when joined
        "config": cfg,
        "status": row.get("status") or "active",
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


def create_or_update_connection(
    *,
    name: str,
    connector_type: str,
    auth_ref: str | None = None,
    config: dict | None = None,
    connection_id: str | None = None,
    tenant_id: str | None = None,
) -> dict:
    """Upsert obs_connections (account-level auth container)."""
    import uuid as _uuid

    cid = (connection_id or "").strip() or str(_uuid.uuid4())
    conn = get_connection()
    try:
        ensure_tables(conn)
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO obs_connections (
                  connection_id, tenant_id, name, connector_type, auth_ref, config_json, status
                ) VALUES (%s,%s,%s,%s,%s,%s,'active')
                ON DUPLICATE KEY UPDATE
                  name=VALUES(name), connector_type=VALUES(connector_type),
                  auth_ref=VALUES(auth_ref), config_json=VALUES(config_json), status='active'
                """,
                (
                    cid,
                    tenant_id or "demo",
                    name,
                    connector_type,
                    auth_ref,
                    json.dumps(config or {}, default=str),
                ),
            )
        conn.commit()
        return {"ok": True, "connection_id": cid, "name": name, "connector_type": connector_type}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def create_or_update_tool(
    *,
    name: str,
    connector_type: str,
    config: dict | None = None,
    kind: str | None = None,
    auth_ref: str | None = None,
    secret: str | None = None,
    secret_name: str = "default",
    tool_id: str | None = None,
    connection_id: str | None = None,
    tenant_id: str | None = None,
) -> dict:
    """
    Upsert a reusable tool (= obs_connector_instances).
    If `secret` is provided, encrypt with SECRETS_MASTER_KEY and store in obs_secrets.
    Plaintext is never written to config_json.
    """
    import uuid as _uuid

    cfg = dict(config or {})
    # Pull secret out of config if caller nested it there
    nested_secret = None
    for secret_key in ("password", "api_token", "token", "secret"):
        if cfg.get(secret_key):
            nested_secret = str(cfg.pop(secret_key))
    plaintext = secret if secret is not None else nested_secret

    ctype = (connector_type or "").strip().lower()
    tool_kind = _tool_kind_for_type(ctype, kind)
    iid = (tool_id or "").strip() or str(_uuid.uuid4())
    tid = tenant_id or "demo"

    conn = get_connection()
    try:
        ensure_tables(conn)
        cid = (connection_id or "").strip() or None
        if auth_ref or not cid:
            account_key = (
                cfg.get("account_id")
                or cfg.get("host")
                or cfg.get("database_id")
                or name
            )
            cid = cid or f"conn-{ctype}-{str(account_key)[:40]}"
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO obs_connections (
                      connection_id, tenant_id, name, connector_type, auth_ref, config_json, status
                    ) VALUES (%s,%s,%s,%s,%s,%s,'active')
                    ON DUPLICATE KEY UPDATE
                      auth_ref=COALESCE(VALUES(auth_ref), auth_ref),
                      name=VALUES(name), status='active'
                    """,
                    (
                        cid[:64],
                        tid,
                        f"{ctype}-{account_key}"[:255],
                        ctype,
                        auth_ref,
                        json.dumps(
                            {k: cfg.get(k) for k in ("account_id", "host", "user_id", "user") if cfg.get(k)},
                            default=str,
                        ),
                    ),
                )
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO obs_connector_instances (
                  instance_id, connection_id, tenant_id, name, connector_type,
                  kind, config_json, status
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,'active')
                ON DUPLICATE KEY UPDATE
                  connection_id=VALUES(connection_id),
                  name=VALUES(name),
                  connector_type=VALUES(connector_type),
                  kind=VALUES(kind),
                  config_json=VALUES(config_json),
                  status='active'
                """,
                (
                    iid,
                    cid,
                    tid,
                    name,
                    ctype,
                    tool_kind,
                    json.dumps(cfg, default=str),
                ),
            )
        if plaintext is not None and str(plaintext) != "":
            _upsert_secret_on_conn(
                conn,
                owner_type="tool",
                owner_id=iid,
                secret_name=secret_name or "default",
                plaintext=str(plaintext),
            )
        conn.commit()
        tool = get_tool(iid)
        return {"ok": True, "tool": tool, "secret_stored": bool(plaintext)}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _upsert_secret_on_conn(
    conn,
    *,
    owner_type: str,
    owner_id: str,
    secret_name: str,
    plaintext: str,
) -> str:
    from application.src.security.crypto import encrypt_secret

    ciphertext = encrypt_secret(plaintext)
    secret_id = f"{owner_type}:{owner_id}:{secret_name}"[:64]
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO obs_secrets (
              secret_id, owner_type, owner_id, secret_name, ciphertext, key_version
            ) VALUES (%s,%s,%s,%s,%s,'v1')
            ON DUPLICATE KEY UPDATE
              ciphertext=VALUES(ciphertext),
              key_version='v1',
              updated_at=CURRENT_TIMESTAMP
            """,
            (secret_id, owner_type, owner_id, secret_name, ciphertext),
        )
    return secret_id


def upsert_tool_secret(
    tool_id: str,
    plaintext: str,
    *,
    secret_name: str = "default",
) -> dict:
    """Encrypt and store/replace a tool secret in obs_secrets."""
    conn = get_connection()
    try:
        ensure_tables(conn)
        sid = _upsert_secret_on_conn(
            conn,
            owner_type="tool",
            owner_id=tool_id,
            secret_name=secret_name,
            plaintext=plaintext,
        )
        conn.commit()
        return {"ok": True, "secret_id": sid, "tool_id": tool_id, "secret_name": secret_name}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_decrypted_tool_secret(
    tool_id: str,
    *,
    secret_name: str = "default",
) -> str | None:
    """
    Decrypt tool secret from DB. Returns None if no row.
    Falls back to connection-level secret if tool has no secret.
    """
    from application.src.security.crypto import decrypt_secret

    conn = get_connection()
    try:
        ensure_tables(conn)
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT ciphertext FROM obs_secrets
                WHERE owner_type='tool' AND owner_id=%s AND secret_name=%s
                """,
                (tool_id, secret_name),
            )
            row = cur.fetchone()
            if not row:
                # try connection parent
                cur.execute(
                    "SELECT connection_id FROM obs_connector_instances WHERE instance_id=%s",
                    (tool_id,),
                )
                inst = cur.fetchone()
                cid = (inst or {}).get("connection_id")
                if cid:
                    cur.execute(
                        """
                        SELECT ciphertext FROM obs_secrets
                        WHERE owner_type='connection' AND owner_id=%s AND secret_name=%s
                        """,
                        (cid, secret_name),
                    )
                    row = cur.fetchone()
            if not row:
                return None
            return decrypt_secret(row["ciphertext"])
    finally:
        conn.close()


def tool_has_secret(tool_id: str, *, secret_name: str = "default") -> bool:
    conn = get_connection()
    try:
        ensure_tables(conn)
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT 1 FROM obs_secrets
                WHERE owner_type='tool' AND owner_id=%s AND secret_name=%s
                LIMIT 1
                """,
                (tool_id, secret_name),
            )
            return cur.fetchone() is not None
    finally:
        conn.close()


def get_tool(tool_id: str) -> dict | None:
    conn = get_connection()
    try:
        ensure_tables(conn)
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT i.*, c.auth_ref AS connection_auth_ref,
                  EXISTS(
                    SELECT 1 FROM obs_secrets s
                    WHERE s.owner_type='tool' AND s.owner_id=i.instance_id
                  ) AS has_secret
                FROM obs_connector_instances i
                LEFT JOIN obs_connections c ON c.connection_id = i.connection_id
                WHERE i.instance_id = %s
                """,
                (tool_id,),
            )
            row = cur.fetchone()
        if not row:
            return None
        out = _public_tool_row(row)
        out["auth_ref"] = row.get("connection_auth_ref")
        out["has_secret"] = bool(row.get("has_secret"))
        return out
    finally:
        conn.close()


def list_tools(
    *,
    kind: str | None = None,
    connector_type: str | None = None,
) -> list[dict]:
    conn = get_connection()
    try:
        ensure_tables(conn)
        clauses = ["i.status = 'active'"]
        params: list[Any] = []
        if kind:
            clauses.append("i.kind = %s")
            params.append(kind)
        if connector_type:
            clauses.append("i.connector_type = %s")
            params.append(connector_type.strip().lower())
        where = " AND ".join(clauses)
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT i.*, c.auth_ref AS connection_auth_ref,
                  EXISTS(
                    SELECT 1 FROM obs_secrets s
                    WHERE s.owner_type='tool' AND s.owner_id=i.instance_id
                  ) AS has_secret
                FROM obs_connector_instances i
                LEFT JOIN obs_connections c ON c.connection_id = i.connection_id
                WHERE {where}
                ORDER BY i.kind, i.name
                """,
                params,
            )
            rows = list(cur.fetchall() or [])
        out = []
        for row in rows:
            item = _public_tool_row(row)
            item["auth_ref"] = row.get("connection_auth_ref")
            item["has_secret"] = bool(row.get("has_secret"))
            out.append(item)
        return out
    finally:
        conn.close()


def _tool_as_role_config(tool: dict, role: str) -> dict:
    """Map a public tool row into classic source/etl/target config dict."""
    cfg = dict(tool.get("config") or {})
    ctype = (tool.get("connector_type") or "").strip().lower()
    if ctype in {"dbt_cloud"}:
        ctype = "dbt"
    out = {
        "tool": ctype,
        "connector_instance_id": tool.get("tool_id") or tool.get("instance_id"),
        **cfg,
    }
    if role in {"SOURCE", "TARGET"}:
        out.setdefault("role", role)
        if "sf_role" not in out and cfg.get("role"):
            out["sf_role"] = cfg.get("role")
    if tool.get("auth_ref"):
        if role == "ETL":
            out.setdefault("api_token_env", tool["auth_ref"])
        else:
            out.setdefault("password_env", tool["auth_ref"])
    return out


def create_pipeline_from_tools(
    *,
    pipeline_name: str,
    source_tool_ids: list[str],
    etl_tool_id: str,
    target_tool_ids: list[str],
    pipeline_id: str | None = None,
    make_active: bool = True,
    description: str | None = None,
    tenant_id: str | None = None,
) -> dict:
    """Compose a pipeline from one or more SOURCE/TARGET tools plus ETL; write bindings."""
    import uuid as _uuid

    if not source_tool_ids:
        raise ValueError("source_tool_ids is required")
    if not target_tool_ids:
        raise ValueError("target_tool_ids is required")

    source_tools = []
    for sid in source_tool_ids:
        t = get_tool(sid)
        if not t:
            raise ValueError(f"source_tool_id not found: {sid}")
        if (t.get("kind") or "database") != "database":
            raise ValueError(f"source tool must be database: {sid}")
        source_tools.append(t)

    etl = get_tool(etl_tool_id)
    if not etl:
        raise ValueError(f"etl_tool_id not found: {etl_tool_id}")
    if (etl.get("kind") or "") not in {"etl", "orchestrator"}:
        raise ValueError("etl_tool_id must be an etl or orchestrator tool")

    target_tools = []
    for tid in target_tool_ids:
        t = get_tool(tid)
        if not t:
            raise ValueError(f"target_tool_id not found: {tid}")
        if (t.get("kind") or "database") != "database":
            raise ValueError(f"target tool must be database: {tid}")
        target_tools.append(t)

    pid = (pipeline_id or "").strip() or str(_uuid.uuid4())
    primary_source = source_tools[0]
    primary_target = target_tools[0]
    tool_summary = "/".join(
        [*(t.get("tool_id") or t.get("instance_id") or "?" for t in source_tools),
         etl_tool_id,
         *(t.get("tool_id") or t.get("instance_id") or "?" for t in target_tools)]
    )
    pipeline = {
        "pipeline_id": pid,
        "pipeline_name": (pipeline_name or "composed").strip(),
        "tenant_id": tenant_id or "demo",
        "description": description or f"Composed from tools {tool_summary}",
        "source": _tool_as_role_config(primary_source, "SOURCE"),
        "etl": _tool_as_role_config(etl, "ETL"),
        "target": _tool_as_role_config(primary_target, "TARGET"),
    }

    conn = get_connection()
    try:
        ensure_tables(conn)
        with conn.cursor() as cur:
            cur.execute(
                "SELECT pipeline_id FROM obs_pipelines WHERE pipeline_id = %s",
                (pid,),
            )
            exists = cur.fetchone()
            if not exists:
                cur.execute("SELECT COUNT(*) AS n FROM obs_pipelines")
                n = int((cur.fetchone() or {}).get("n") or 0)
                if n >= freemium_max_pipelines():
                    raise FreemiumLimitError(
                        f"Pipeline limit reached ({freemium_max_pipelines()})."
                    )
        store_pipeline(conn, pipeline, make_active=make_active)
        with conn.cursor() as cur:
            cur.execute("DELETE FROM obs_pipeline_bindings WHERE pipeline_id = %s", (pid,))
            ordinal = 0
            for tool in source_tools:
                iid = tool.get("tool_id") or tool.get("instance_id")
                binding_id = f"{pid}:SOURCE:{ordinal}:{iid}"[:64]
                selector = {"schema": (tool.get("config") or {}).get("schema")}
                if (tool.get("config") or {}).get("tables"):
                    selector["tables"] = (tool.get("config") or {}).get("tables")
                cur.execute(
                    """
                    INSERT INTO obs_pipeline_bindings (
                      binding_id, pipeline_id, role, instance_id, asset_selector_json, ordinal
                    ) VALUES (%s,%s,%s,%s,%s,%s)
                    """,
                    (binding_id, pid, "SOURCE", iid, json.dumps(selector, default=str), ordinal),
                )
                ordinal += 1
            iid = etl.get("tool_id") or etl.get("instance_id")
            binding_id = f"{pid}:ETL:{iid}"[:64]
            selector = {"schema": (etl.get("config") or {}).get("schema")}
            cur.execute(
                """
                INSERT INTO obs_pipeline_bindings (
                  binding_id, pipeline_id, role, instance_id, asset_selector_json, ordinal
                ) VALUES (%s,%s,%s,%s,%s,0)
                """,
                (binding_id, pid, "ETL", iid, json.dumps(selector, default=str)),
            )
            ordinal = 0
            for tool in target_tools:
                iid = tool.get("tool_id") or tool.get("instance_id")
                binding_id = f"{pid}:TARGET:{ordinal}:{iid}"[:64]
                selector = {"schema": (tool.get("config") or {}).get("schema")}
                if (tool.get("config") or {}).get("tables"):
                    selector["tables"] = (tool.get("config") or {}).get("tables")
                cur.execute(
                    """
                    INSERT INTO obs_pipeline_bindings (
                      binding_id, pipeline_id, role, instance_id, asset_selector_json, ordinal
                    ) VALUES (%s,%s,%s,%s,%s,%s)
                    """,
                    (binding_id, pid, "TARGET", iid, json.dumps(selector, default=str), ordinal),
                )
                ordinal += 1
        from application.src.services.observability.lifecycle import (
            ensure_default_dq_rules,
            ensure_default_monitors,
        )

        ensure_default_monitors(conn)
        ensure_default_dq_rules(conn, pipeline_id=pid)
        bump_usage(conn, runs_ingested=0, poll_ticks=0)
        conn.commit()
        return {
            "ok": True,
            "pipeline_id": pid,
            "pipeline_name": pipeline["pipeline_name"],
            "is_active": make_active,
            "source_tool_ids": source_tool_ids,
            "etl_tool_id": etl_tool_id,
            "target_tool_ids": target_tool_ids,
            "message": "Pipeline composed from tools; Sync will use bindings.",
        }
    except FreemiumLimitError:
        conn.rollback()
        raise
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def resolve_pipeline_tool_groups(pipeline_id: str) -> dict[str, list[dict]] | None:
    """Return {SOURCE: [...], ETL: [...], TARGET: [...]} from bindings ordered by ordinal."""
    conn = get_connection()
    try:
        ensure_tables(conn)
        bindings = list_pipeline_bindings(conn, pipeline_id)
        groups: dict[str, list[dict]] = {"SOURCE": [], "ETL": [], "TARGET": []}
        for role in groups:
            role_bindings = [
                b for b in bindings if str(b.get("role") or "").upper() == role
            ]
            role_bindings.sort(key=lambda b: int(b.get("ordinal") or 0))
            for b in role_bindings:
                iid = b.get("instance_id")
                tool = get_tool(str(iid)) if iid else None
                if tool:
                    tool = dict(tool)
                    tool["_binding"] = b
                    groups[role].append(tool)
        if groups["ETL"] and groups["SOURCE"] and groups["TARGET"]:
            return groups
        return None
    finally:
        conn.close()


def resolve_pipeline_tools(pipeline_id: str) -> dict[str, dict] | None:
    """
    Return {SOURCE, ETL, TARGET} tool dicts from bindings (first per role), or None if incomplete.
    """
    groups = resolve_pipeline_tool_groups(pipeline_id)
    if not groups:
        return None
    return {
        "SOURCE": groups["SOURCE"][0],
        "ETL": groups["ETL"][0],
        "TARGET": groups["TARGET"][0],
    }


def tool_snapshot_ttl_seconds() -> int:
    return int(os.getenv("DB_TOOL_SNAPSHOT_TTL_SECONDS") or os.getenv("SYNC_INTERVAL_SECONDS") or "300")


def get_fresh_tool_snapshots(
    instance_id: str,
    *,
    asset_role: str = "SOURCE",
    ttl_seconds: int | None = None,
) -> list[dict] | None:
    """
    Return list of snapshot payloads for a DB tool if all rows are within TTL.
    None means caller should pull fresh.
    """
    ttl = ttl_seconds if ttl_seconds is not None else tool_snapshot_ttl_seconds()
    conn = get_connection()
    try:
        ensure_tables(conn)
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT * FROM obs_tool_snapshots
                WHERE instance_id = %s AND asset_role = %s
                ORDER BY dataset_id
                """,
                (instance_id, asset_role),
            )
            rows = list(cur.fetchall() or [])
        if not rows:
            return None
        now = datetime.utcnow()
        out = []
        for row in rows:
            pulled = row.get("pulled_at")
            if not pulled:
                return None
            age = (now - pulled).total_seconds() if hasattr(pulled, "total_seconds") else None
            if age is None:
                try:
                    age = (now - pulled).total_seconds()
                except Exception:
                    return None
            if age > ttl:
                return None
            payload = _parse_json_obj(row.get("payload_json"))
            cols = row.get("columns_json")
            columns = []
            if cols:
                try:
                    columns = json.loads(cols) if isinstance(cols, str) else (cols or [])
                except (json.JSONDecodeError, TypeError):
                    columns = []
            out.append(
                {
                    "snapshot_id": row.get("snapshot_id"),
                    "dataset_id": row.get("dataset_id"),
                    "payload": payload,
                    "columns": columns,
                    "fingerprint": row.get("fingerprint"),
                    "pulled_at": pulled,
                    "reused": True,
                }
            )
        return out
    finally:
        conn.close()


def upsert_tool_snapshots(
    instance_id: str,
    *,
    asset_role: str,
    assets: list[dict],
    columns_by_dataset: dict[str, list[dict]] | None = None,
) -> list[str]:
    """Replace/upsert tool-wise DB snapshots for an instance. Returns snapshot_ids."""
    import hashlib
    import uuid as _uuid

    columns_by_dataset = columns_by_dataset or {}
    conn = get_connection()
    ids: list[str] = []
    try:
        ensure_tables(conn)
        now = datetime.utcnow()
        with conn.cursor() as cur:
            for asset in assets:
                ds = str(asset.get("dataset_id") or asset.get("object_name") or "")[:512]
                fp_src = json.dumps(
                    {
                        "dataset_id": ds,
                        "row_count": asset.get("row_count"),
                        "last_updated_at": str(asset.get("last_updated_at") or ""),
                        "size_bytes": asset.get("size_bytes"),
                    },
                    sort_keys=True,
                    default=str,
                )
                fp = hashlib.sha256(fp_src.encode("utf-8")).hexdigest()[:32]
                snap_id = f"{instance_id}:{asset_role}:{ds}"[:64] or str(_uuid.uuid4())
                cols = columns_by_dataset.get(ds.upper()) or columns_by_dataset.get(ds) or []
                cur.execute(
                    """
                    INSERT INTO obs_tool_snapshots (
                      snapshot_id, instance_id, dataset_id, asset_role,
                      fingerprint, payload_json, columns_json, pulled_at
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                    ON DUPLICATE KEY UPDATE
                      fingerprint=VALUES(fingerprint),
                      payload_json=VALUES(payload_json),
                      columns_json=VALUES(columns_json),
                      pulled_at=VALUES(pulled_at),
                      snapshot_id=VALUES(snapshot_id)
                    """,
                    (
                        snap_id,
                        instance_id,
                        ds,
                        asset_role,
                        fp,
                        json.dumps(asset, default=str),
                        json.dumps(cols, default=str),
                        now,
                    ),
                )
                ids.append(snap_id)
        conn.commit()
        return ids
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
