# this is the class for mysql connector
import os

import pymysql


class MysqlConnector:
    """one class = one tool (MySQL)"""

    tool_id = "mysql_lab"

    def __init__(
        self,
        *,
        tenant_id: str,
        connector_instance_id: str,
        host: str,
        user: str,
        database: str,  # one DB for now
        port: int = 3306,
        password: str | None = None,
        schema: str = "",  # optional filter; in MySQL schema ≈ database
    ):
        self.tenant_id = tenant_id
        self.connector_instance_id = connector_instance_id
        self.host = host
        self.port = int(port)
        self.user = user
        self.database = database
        self.schema = (schema or "").strip()
        self.password = password or os.getenv("MYSQL_PASSWORD") or os.getenv("DB_PASSWORD", "")

    def _connect(self):
        """connect to MySQL"""
        if not self.password:
            raise RuntimeError("Missing MYSQL_PASSWORD or DB_PASSWORD")

        self.connection = pymysql.connect(
            host=self.host,
            port=self.port,
            user=self.user,
            password=self.password,
            database=self.database,
            cursorclass=pymysql.cursors.Cursor,
        )
        self.cursor = self.connection.cursor()

    def test_connection(self) -> dict:
        """test the connection to MySQL"""
        try:
            self._connect()
            self.cursor.execute("SELECT VERSION()")
            version = self.cursor.fetchone()
            self.cursor.close()
            self.connection.close()
            return {
                "ok": True,
                "message": "MySQL connection OK",
                "details": {"version": version[0] if version else None},
            }
        except Exception as e:
            return {"ok": False, "message": str(e)}

    def get_databases(self) -> dict:
        """get the databases from MySQL"""
        try:
            self._connect()
            self.cursor.execute("SHOW DATABASES")
            result = self.cursor.fetchall()
            self.cursor.close()
            self.connection.close()
            return {
                "ok": True,
                "message": "MySQL databases OK",
                "details": {"databases": [row[0] for row in result]},
            }
        except Exception as e:
            return {"ok": False, "message": str(e)}

    def _fetch_tables(self) -> list[dict]:
        """
        Pull table metadata from the connected database.
        This is what we store (not business row data).
        """
        self._connect()
        try:
            sql = """
                SELECT TABLE_SCHEMA, TABLE_NAME, TABLE_ROWS, UPDATE_TIME
                FROM INFORMATION_SCHEMA.TABLES
                WHERE TABLE_TYPE = 'BASE TABLE'
            """
            params: list = []
            # In MySQL, TABLE_SCHEMA is the database name
            target_schema = self.schema or self.database
            if target_schema:
                sql += " AND TABLE_SCHEMA = %s"
                params.append(target_schema)
            sql += " ORDER BY TABLE_SCHEMA, TABLE_NAME"

            self.cursor.execute(sql, params)

            rows: list[dict] = []
            for schema_name, table, row_count, update_time in self.cursor.fetchall():
                rows.append(
                    {
                        "database": schema_name,
                        "schema": schema_name,
                        "table": table,
                        "dataset_id": f"{schema_name}.{table}",
                        "row_count": row_count,
                        "last_altered": (
                            update_time.isoformat()
                            if hasattr(update_time, "isoformat")
                            else update_time
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
                    "source_system": "mysql",
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
