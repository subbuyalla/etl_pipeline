"""Amazon Redshift database connector (SOURCE / TARGET tool)."""

from __future__ import annotations

import os
from typing import Any


class RedshiftConnector:
    """Uses the Postgres wire protocol (psycopg2) against Redshift."""

    tool_id = "redshift"
    kind = "database"

    def __init__(
        self,
        *,
        tenant_id: str,
        connector_instance_id: str,
        host: str,
        user: str,
        database: str,
        port: int = 5439,
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
        self.password = (
            password
            or os.getenv("REDSHIFT_PASSWORD")
            or os.getenv("POSTGRES_PASSWORD")
            or ""
        )

    def _connect(self):
        try:
            import psycopg2
        except ImportError as exc:
            raise RuntimeError(
                "psycopg2-binary is required for Redshift. pip install psycopg2-binary"
            ) from exc
        if not self.password:
            raise RuntimeError("Missing REDSHIFT_PASSWORD")
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
            self.cursor.execute("SELECT 1")
            self.cursor.fetchone()
            self.cursor.close()
            self.connection.close()
            return {"ok": True, "message": "Redshift connection OK", "details": {}}
        except Exception as e:
            return {"ok": False, "message": str(e)}

    def _fetch_tables(self) -> list[dict]:
        self._connect()
        try:
            sql = """
                SELECT table_schema, table_name
                FROM information_schema.tables
                WHERE table_type = 'BASE TABLE' AND table_schema = %s
            """
            params: list[Any] = [self.schema]
            if self.tables:
                placeholders = ",".join(["%s"] * len(self.tables))
                sql += f" AND UPPER(table_name) IN ({placeholders})"
                params.extend(self.tables)
            sql += " ORDER BY table_name"
            self.cursor.execute(sql, params)
            rows = []
            for schema_name, table in self.cursor.fetchall():
                rows.append(
                    {
                        "database": self.database,
                        "schema": schema_name,
                        "table": table,
                        "dataset_id": f"{self.database}.{schema_name}.{table}",
                        "row_count": None,
                        "last_altered": None,
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
                    "source_system": "redshift",
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
        schema_part = schema or self.schema or "public"
        parts = [db, schema_part, table]
        col = str(column_name or "").strip()
        if not col:
            raise ValueError("column_name is required")
        fqn = f"{quote_ident_pg(schema_part)}.{quote_ident_pg(table)}"
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
