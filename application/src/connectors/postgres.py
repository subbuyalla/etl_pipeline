"""Postgres database connector (SOURCE / TARGET tool)."""

from __future__ import annotations

import os
from typing import Any


class PostgresConnector:
    tool_id = "postgres"
    kind = "database"

    def __init__(
        self,
        *,
        tenant_id: str,
        connector_instance_id: str,
        host: str,
        user: str,
        database: str,
        port: int = 5432,
        password: str | None = None,
        schema: str = "public",
        tables: list[str] | None = None,
    ):
        self.tenant_id = tenant_id
        self.connector_instance_id = connector_instance_id
        self.host = host
        self.port = int(port)
        self.user = user
        self.database = database
        self.schema = (schema or "public").strip()
        self.tables = [str(t).strip().upper() for t in (tables or []) if str(t).strip()]
        self.password = password or os.getenv("POSTGRES_PASSWORD") or os.getenv("PGPASSWORD") or ""

    def _connect(self):
        try:
            import psycopg2
        except ImportError as exc:
            raise RuntimeError(
                "psycopg2-binary is required for Postgres. "
                "pip install psycopg2-binary"
            ) from exc
        if not self.password:
            raise RuntimeError("Missing POSTGRES_PASSWORD / PGPASSWORD")
        self.connection = psycopg2.connect(
            host=self.host,
            port=self.port,
            user=self.user,
            password=self.password,
            dbname=self.database,
        )
        self.cursor = self.connection.cursor()

    def test_connection(self) -> dict[str, Any]:
        """test the connection to PostgreSQL and verify schema/database permissions"""
        try:
            self._connect()
            self.cursor.execute("SELECT version(), current_user, current_database()")
            row = self.cursor.fetchone()
            version = row[0] if row else None
            user = row[1] if row and len(row) > 1 else None
            db = row[2] if row and len(row) > 2 else None

            permissions = {
                "connection": True,
                "database_access": True,
                "schema_access": True,
            }

            if self.schema:
                try:
                    self.cursor.execute(
                        "SELECT has_schema_privilege(current_user, %s, 'usage')",
                        (self.schema,),
                    )
                    res = self.cursor.fetchone()
                    if res and not res[0]:
                        permissions["schema_access"] = False
                        raise PermissionError(
                            f"PostgreSQL user '{user}' lacks USAGE privilege on schema '{self.schema}'"
                        )
                except Exception as perm_err:
                    permissions["schema_access"] = False
                    raise PermissionError(
                        f"PostgreSQL permission check failed for schema '{self.schema}': {perm_err}"
                    )

            self.cursor.close()
            self.connection.close()
            return {
                "ok": True,
                "message": "Postgres connection and permissions verified",
                "details": {
                    "version": version,
                    "user": user,
                    "database": db,
                    "permissions": permissions,
                },
            }
        except Exception as e:
            return {"ok": False, "message": str(e), "details": {"permissions": {"connection": False}}}

    def _fetch_tables(self) -> list[dict]:
        self._connect()
        try:
            sql = """
                SELECT n.nspname, c.relname,
                       COALESCE(s.n_live_tup, 0),
                       GREATEST(s.last_vacuum, s.last_autovacuum, s.last_analyze, s.last_autoanalyze),
                       COALESCE(pg_total_relation_size(c.oid), 0) AS size_bytes
                FROM pg_class c
                JOIN pg_namespace n ON n.oid = c.relnamespace
                LEFT JOIN pg_stat_all_tables s ON s.relid = c.oid
                WHERE c.relkind = 'r' AND n.nspname = %s
            """
            params: list[Any] = [self.schema]
            if self.tables:
                sql += " AND UPPER(c.relname) = ANY(%s)"
                params.append(self.tables)
            sql += " ORDER BY c.relname"
            self.cursor.execute(sql, params)
            rows = []
            for schema_name, table, row_count, last_altered, size_bytes in self.cursor.fetchall():
                rows.append(
                    {
                        "database": self.database,
                        "schema": schema_name,
                        "table": table,
                        "dataset_id": f"{self.database}.{schema_name}.{table}",
                        "row_count": int(row_count or 0),
                        "size_bytes": int(size_bytes or 0),
                        "last_altered": (
                            last_altered.isoformat()
                            if hasattr(last_altered, "isoformat")
                            else last_altered
                        ),
                    }
                )
            return rows
        finally:
            self.cursor.close()
            self.connection.close()

    def fetch_columns(self, tables: list[str] | None = None) -> list[dict]:
        """
        Pull column metadata for tables in this database/schema.
        Returns rows: database, schema, table, column_name, data_type, ordinal_position.
        """
        names = [
            str(t).strip().upper()
            for t in (tables if tables is not None else self.tables)
            if str(t).strip()
        ]
        self._connect()
        try:
            sql = """
                SELECT table_catalog, table_schema, table_name,
                       column_name, data_type, ordinal_position
                FROM information_schema.columns
                WHERE table_schema = %s
            """
            params: list[Any] = [self.schema]
            if names:
                sql += " AND UPPER(table_name) = ANY(%s)"
                params.append(names)
            sql += " ORDER BY table_schema, table_name, ordinal_position"

            self.cursor.execute(sql, params)
            rows: list[dict] = []
            for db, schema_name, table, col, dtype, ordinal in self.cursor.fetchall():
                rows.append(
                    {
                        "database": db or self.database,
                        "schema": schema_name,
                        "table": table,
                        "column_name": col,
                        "data_type": dtype,
                        "ordinal_position": int(ordinal) if ordinal is not None else None,
                        "dataset_id": f"{db or self.database}.{schema_name}.{table}",
                    }
                )
            return rows
        finally:
            self.cursor.close()
            self.connection.close()

    def pull_state(self) -> list[dict]:
        envelopes = []
        for row in self._fetch_tables():
            envelopes.append(
                {
                    "source_system": "postgres",
                    "tenant_id": self.tenant_id,
                    "connector_instance_id": self.connector_instance_id,
                    "raw": {
                        "event_type": "discovered",
                        "database": row["database"],
                        "schema": row["schema"],
                        "table": row["table"],
                        "dataset_id": row["dataset_id"],
                        "row_count": row.get("row_count"),
                        "size_bytes": row.get("size_bytes"),
                        "last_altered": row.get("last_altered"),
                    },
                }
            )
        return envelopes

    def run_column_validation(
        self,
        *,
        dataset_id: str,
        column_name: str,
        check_type: str,
        custom_sql: str | None = None,
        expected_max: int = 0,
    ) -> dict[str, Any]:
        from application.src.connectors.validation import (
            build_observed_result,
            parse_dataset_fqn,
            quote_ident_pg,
        )

        db, schema, table = parse_dataset_fqn(dataset_id)
        parts = [db, schema, table]
        col = str(column_name or "").strip()
        if not col:
            raise ValueError("column_name is required")
        fqn = f"{quote_ident_pg(schema)}.{quote_ident_pg(table)}"
        col_q = quote_ident_pg(col)
        kind = (check_type or "").lower()

        self._connect()
        try:
            if kind == "custom_sql" and custom_sql:
                self.cursor.execute(custom_sql)
                row = self.cursor.fetchone()
                actual = int(row[0]) if row else 0
                return build_observed_result(
                    check_type="CUSTOM_SQL",
                    parts=parts,
                    column_name=col,
                    actual_value=actual,
                    expected_max=expected_max,
                )

            # Unified column profiling metrics query
            self.cursor.execute(
                f"""
                SELECT COUNT(*) AS total_rows,
                       COUNT({col_q}) AS non_null_rows,
                       COUNT(DISTINCT {col_q}) AS distinct_count,
                       COALESCE(SUM(CASE WHEN TRIM(CAST({col_q} AS VARCHAR)) = '' THEN 1 ELSE 0 END), 0) AS blank_count
                FROM {fqn}
                """
            )
            row = self.cursor.fetchone() or (0, 0, 0, 0)
            total = int(row[0] or 0)
            non_null = int(row[1] or 0)
            distinct = int(row[2] or 0)
            blank = int(row[3] or 0)

            null_count = max(0, total - non_null)
            dup_count = max(0, total - distinct)
            null_rate = round(100.0 * null_count / total, 2) if total > 0 else 0.0
            non_null_rate = round(100.0 * non_null / total, 2) if total > 0 else 0.0
            unique_rate = round(100.0 * distinct / total, 2) if total > 0 else 0.0

            if kind in {"null_rate", "null_pct"}:
                actual_val = null_rate
                ctype = "NULL_RATE"
            elif kind == "non_null_rate":
                actual_val = non_null_rate
                ctype = "NON_NULL_RATE"
            elif kind == "null_check":
                actual_val = null_count
                ctype = "NOT_NULL"
            elif kind in {"unique_rate"}:
                actual_val = unique_rate
                ctype = "UNIQUE_RATE"
            elif kind in {"distinct_count"}:
                actual_val = distinct
                ctype = "DISTINCT_COUNT"
            elif kind in {"blank_count", "empty_string_count"}:
                actual_val = blank
                ctype = "BLANK_COUNT"
            elif kind in {"unique_check", "unique_violation", "duplicate_check", "duplicate_count"}:
                actual_val = dup_count
                ctype = "UNIQUE" if "unique" in kind else "DUPLICATE"
            else:
                raise ValueError(f"Unsupported check_type: {check_type}")

            return build_observed_result(
                check_type=ctype,
                parts=parts,
                column_name=col,
                actual_value=actual_val,
                expected_max=expected_max,
                total_rows=total,
                null_count=null_count,
                null_rate=null_rate,
                distinct_count=distinct,
                unique_rate=unique_rate,
                blank_count=blank,
                non_null_rate=non_null_rate,
            )
        finally:
            try:
                self.cursor.close()
                self.connection.close()
            except Exception:
                pass
