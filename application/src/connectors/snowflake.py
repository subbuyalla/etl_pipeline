# this is the class for snowflake connector
from typing import Any, Iterator, Optional
import os


class SnowflakeConnector:
    """one class= one tool(snowflake)"""

    tool_id = "snowflake_lab"

    def __init__(
        self,
        *,
        tenant_id: str,
        connector_instance_id: str,
        account_id: str,
        user_id: str,
        warehouse_id: str,
        database_id: str,  # one DB for now
        role: str,
        password: str | None = None,
        schema: str = "",
        tables: list[str] | None = None,
    ):
        self.tenant_id = tenant_id
        self.connector_instance_id = connector_instance_id
        self.account_id = account_id
        self.user_id = user_id
        self.warehouse_id = warehouse_id
        self.database_id = database_id
        self.role = role
        self.schema = (schema or "").strip()
        self.tables = [
            str(t).strip().upper() for t in (tables or []) if str(t).strip()
        ]
        self.password = password or os.getenv("SNOWFLAKE_PASSWORD", "")

    def _connect(self):
        """connect to snowflake"""
        import snowflake.connector

        if not self.password:
            raise RuntimeError("Missing SNOWFLAKE_PASSWORD")

        self.connection = snowflake.connector.connect(
            user=self.user_id,
            password=self.password,
            account=self.account_id,
            warehouse=self.warehouse_id,
            database=self.database_id,
            role=self.role,
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
            return {
                "ok": True,
                "message": "Snowflake connection OK",
                "details": {"version": version},
            }
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
            return {
                "ok": True,
                "message": "Snowflake databases OK",
                "details": {"databases": result},
            }
        except Exception as e:
            return {"ok": False, "message": str(e)}

    def _fetch_tables(self) -> list[dict]:
        """
        Pull table metadata from the connected database.
        This is what we store (not business row data).
        Optional tables filter limits to named objects (pipeline grain).
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
            if self.tables:
                placeholders = ", ".join(["%s"] * len(self.tables))
                sql += f" AND TABLE_NAME IN ({placeholders})"
                params.extend(self.tables)
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
            if self.database_id:
                self.cursor.execute(f"USE DATABASE {self.database_id}")

            sql = """
                SELECT TABLE_CATALOG, TABLE_SCHEMA, TABLE_NAME,
                       COLUMN_NAME, DATA_TYPE, ORDINAL_POSITION
                FROM INFORMATION_SCHEMA.COLUMNS
                WHERE 1=1
            """
            params: list = []
            if self.schema:
                sql += " AND TABLE_SCHEMA = %s"
                params.append(self.schema.upper())
            if names:
                placeholders = ", ".join(["%s"] * len(names))
                sql += f" AND TABLE_NAME IN ({placeholders})"
                params.extend(names)
            sql += " ORDER BY TABLE_SCHEMA, TABLE_NAME, ORDINAL_POSITION"

            self.cursor.execute(sql, params or None)
            rows: list[dict] = []
            for catalog, schema, table, col, dtype, ordinal in self.cursor.fetchall():
                rows.append(
                    {
                        "database": catalog,
                        "schema": schema,
                        "table": table,
                        "column_name": col,
                        "data_type": dtype,
                        "ordinal_position": int(ordinal) if ordinal is not None else None,
                        "dataset_id": f"{catalog}.{schema}.{table}",
                    }
                )
            return rows
        finally:
            self.cursor.close()
            self.connection.close()

    def fetch_query_history(
        self,
        *,
        hours_back: int = 24,
        limit: int = 25,
        errors_only: bool = True,
    ) -> list[dict]:
        """
        Recent warehouse query history (for RCA). Uses INFORMATION_SCHEMA.QUERY_HISTORY,
        falls back to ACCOUNT_USAGE. Best-effort: returns [] on errors.
        """
        hours = max(1, min(int(hours_back or 24), 168))
        lim = max(1, min(int(limit or 25), 100))
        self._connect()
        try:
            if self.database_id:
                self.cursor.execute(f"USE DATABASE {self.database_id}")
            if self.warehouse_id:
                self.cursor.execute(f"USE WAREHOUSE {self.warehouse_id}")

            status_clause = (
                "AND EXECUTION_STATUS ILIKE 'FAIL%'" if errors_only else ""
            )
            sql_info = f"""
                SELECT QUERY_ID, START_TIME, END_TIME, EXECUTION_STATUS,
                       ERROR_CODE, ERROR_MESSAGE, QUERY_TEXT,
                       WAREHOUSE_NAME, USER_NAME, DATABASE_NAME, SCHEMA_NAME
                FROM TABLE(INFORMATION_SCHEMA.QUERY_HISTORY(
                    END_TIME_RANGE_START => DATEADD('hour', -{hours}, CURRENT_TIMESTAMP()),
                    END_TIME_RANGE_END => CURRENT_TIMESTAMP()
                ))
                WHERE 1=1
                {status_clause}
                ORDER BY START_TIME DESC
                LIMIT {lim}
            """
            sql_account = f"""
                SELECT QUERY_ID, START_TIME, END_TIME, EXECUTION_STATUS,
                       ERROR_CODE, ERROR_MESSAGE, QUERY_TEXT,
                       WAREHOUSE_NAME, USER_NAME, DATABASE_NAME, SCHEMA_NAME
                FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
                WHERE START_TIME >= DATEADD('hour', -{hours}, CURRENT_TIMESTAMP())
                {status_clause}
                ORDER BY START_TIME DESC
                LIMIT {lim}
            """
            try:
                self.cursor.execute(sql_info)
            except Exception:
                self.cursor.execute(sql_account)

            rows: list[dict] = []
            for (
                qid,
                start,
                end,
                status,
                err_code,
                err_msg,
                qtext,
                wh,
                user,
                db,
                sch,
            ) in self.cursor.fetchall():
                text = qtext if qtext is None else str(qtext)
                if text and len(text) > 2000:
                    text = text[:2000]
                err = err_msg if err_msg is None else str(err_msg)
                if err and len(err) > 2000:
                    err = err[:2000]
                rows.append(
                    {
                        "query_id": str(qid) if qid is not None else None,
                        "start_time": (
                            start.isoformat() if hasattr(start, "isoformat") else start
                        ),
                        "end_time": (
                            end.isoformat() if hasattr(end, "isoformat") else end
                        ),
                        "execution_status": status,
                        "error_code": str(err_code) if err_code is not None else None,
                        "error_message": err,
                        "query_text": text,
                        "warehouse_name": wh,
                        "user_name": user,
                        "database_name": db,
                        "schema_name": sch,
                    }
                )
            return rows
        except Exception:
            return []
        finally:
            try:
                self.cursor.close()
                self.connection.close()
            except Exception:
                pass

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
