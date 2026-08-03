# this is the class for snowflake connector
from typing import Any,Iterator,Optional
import os
import snowflake
import snowflake.connector

class SnowflakeConnector:
    """one class= one tool(snowflake)"""

    tool_id="snowflake_lab"

    def __init__(
    self,
    *,
    tenant_id: str,
    connector_instance_id: str,
    account_id: str,
    user_id: str,
    warehouse_id: str,
    database_id: str,          # one DB for now
    role: str,
    password: str | None = None,
    schema: str = "",
):
        self.tenant_id = tenant_id
        self.connector_instance_id = connector_instance_id
        self.account_id = account_id
        self.user_id = user_id
        self.warehouse_id = warehouse_id
        self.database_id = database_id
        self.role = role
        self.schema = (schema or "").strip()
        self.password = password or os.getenv("SNOWFLAKE_PASSWORD", "")

    def _connect(self):
        """connect to snowflake"""
        if not self.password:
            raise RuntimeError("Missing SNOWFLAKE_PASSWORD")    

        self.connection = snowflake.connector.connect(
            user=self.user_id,
            password=self.password,
            account=self.account_id,
            warehouse=self.warehouse_id,
            database=self.database_id,
            role=self.role
        )

        self.cursor = self.connection.cursor()

    def test_connection(self) -> dict:
        """test the connection to snowflake"""
        try:
            self._connect()
            self.cursor.execute("SELECT CURRENT_VERSION()")  # or SELECT 1
            version = self.cursor.fetchone()
            self.cursor.close()
            self.connection.close()
            return {"ok": True, "message": "Snowflake connection OK", "details": {"version": version}}
        except Exception as e:
            return {"ok": False, "message": str(e)}

    def get_databases(self):
        """get the databases from snowflake"""
        try:
            self._connect()
            self.cursor.execute("SHOW DATABASES")
            result = self.cursor.fetchall()
            self.cursor.close()
            self.connection.close()
            return {"ok": True, "message": "Snowflake databases OK", "details": {"databases": result}}
        except Exception as e:
            return {"ok": False, "message": str(e)}

    def _fetch_tables(self) -> list[dict]:
        """
        Pull table metadata from the connected database.
        This is what we store (not business row data).
        """
        self._connect()
        try:
            if self.database_id:
                self.cursor.execute(f"USE DATABASE {self.database_id}")

            sql = """
                SELECT TABLE_CATALOG, TABLE_SCHEMA, TABLE_NAME, ROW_COUNT, LAST_ALTERED
                FROM INFORMATION_SCHEMA.TABLES
                WHERE TABLE_TYPE = 'BASE TABLE'
            """
            params: list = []
            if self.schema:
                sql += " AND TABLE_SCHEMA = %s"
                params.append(self.schema.upper())
            sql += " ORDER BY TABLE_SCHEMA, TABLE_NAME"

            self.cursor.execute(sql, params or None)

            rows: list[dict] = []
            for catalog, schema, table, row_count, last_altered in self.cursor.fetchall():
                rows.append(
                    {
                        "database": catalog,
                        "schema": schema,
                        "table": table,
                        "dataset_id": f"{catalog}.{schema}.{table}",
                        "row_count": row_count,
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
        """
        Sync payload: wrap each table as an envelope for Metadata later.
        """
        envelopes: list[dict] = []
        for row in self._fetch_tables():
            envelopes.append(
                {
                    "source_system": "snowflake",
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