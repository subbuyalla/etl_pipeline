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
        try:
            self._connect()
            self.cursor.execute("SELECT version()")
            version = self.cursor.fetchone()
            self.cursor.close()
            self.connection.close()
            return {
                "ok": True,
                "message": "Postgres connection OK",
                "details": {"version": version[0] if version else None},
            }
        except Exception as e:
            return {"ok": False, "message": str(e)}

    def _fetch_tables(self) -> list[dict]:
        self._connect()
        try:
            sql = """
                SELECT n.nspname, c.relname,
                       COALESCE(s.n_live_tup, 0),
                       GREATEST(s.last_vacuum, s.last_autovacuum, s.last_analyze, s.last_autoanalyze)
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
            for schema_name, table, row_count, last_altered in self.cursor.fetchall():
                rows.append(
                    {
                        "database": self.database,
                        "schema": schema_name,
                        "table": table,
                        "dataset_id": f"{self.database}.{schema_name}.{table}",
                        "row_count": int(row_count or 0),
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

            if kind in {"null_check", "null_pct"}:
                self.cursor.execute(
                    f"SELECT COUNT(*) AS total_rows, COUNT({col_q}) AS non_null_rows FROM {fqn}"
                )
                total, non_null = self.cursor.fetchone()
                null_count = int(total or 0) - int(non_null or 0)
                return build_observed_result(
                    check_type="NOT_NULL",
                    parts=parts,
                    column_name=col,
                    actual_value=null_count,
                    expected_max=expected_max,
                )

            if kind in {"unique_check", "unique_violation", "duplicate_check", "duplicate_count"}:
                self.cursor.execute(
                    f"SELECT COUNT(*) - COUNT(DISTINCT {col_q}) AS dup_count FROM {fqn}"
                )
                dup_count = int((self.cursor.fetchone() or [0])[0] or 0)
                ctype = "UNIQUE" if "unique" in kind else "DUPLICATE"
                return build_observed_result(
                    check_type=ctype,
                    parts=parts,
                    column_name=col,
                    actual_value=dup_count,
                    expected_max=expected_max,
                )

            raise ValueError(f"Unsupported check_type: {check_type}")
        finally:
            try:
                self.cursor.close()
                self.connection.close()
            except Exception:
                pass
