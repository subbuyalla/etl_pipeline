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
