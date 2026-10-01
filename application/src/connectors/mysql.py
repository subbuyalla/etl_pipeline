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
        """test the connection to MySQL and verify database permissions"""
        try:
            self._connect()
            self.cursor.execute("SELECT VERSION(), CURRENT_USER(), DATABASE()")
            row = self.cursor.fetchone()
            version = row[0] if row else None
            user = row[1] if row and len(row) > 1 else None
            active_db = row[2] if row and len(row) > 2 else None

            permissions = {
                "connection": True,
                "database_access": True,
            }

            if self.database:
                try:
                    self.cursor.execute(f"SHOW TABLES IN `{self.database}`")
                    self.cursor.fetchall()
                    permissions["database_access"] = True
                except Exception as perm_err:
                    permissions["database_access"] = False
                    raise PermissionError(f"MySQL permission denied for database '{self.database}': {perm_err}")

            self.cursor.close()
            self.connection.close()
            return {
                "ok": True,
                "message": "MySQL connection and permissions verified",
                "details": {
                    "version": version,
                    "user": user,
                    "database": active_db or self.database,
                    "permissions": permissions,
                },
            }
        except Exception as e:
            return {"ok": False, "message": str(e), "details": {"permissions": {"connection": False}}}

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

    def run_column_validation(
        self,
        *,
        dataset_id: str,
        column_name: str,
        check_type: str,
        custom_sql: str | None = None,
        expected_max: int = 0,
    ) -> dict:
        from application.src.connectors.validation import (
            build_observed_result,
            parse_dataset_fqn,
            quote_ident_mysql,
        )

        db, schema, table = parse_dataset_fqn(dataset_id)
        db_name = db or self.database
        parts = [db_name, table] if not schema else [db_name, schema, table]
        col = str(column_name or "").strip()
        if not col:
            raise ValueError("column_name is required")
        fqn = f"{quote_ident_mysql(db_name)}.{quote_ident_mysql(table)}"
        col_q = quote_ident_mysql(col)
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
                       COALESCE(SUM(CASE WHEN TRIM(CAST({col_q} AS CHAR)) = '' THEN 1 ELSE 0 END), 0) AS blank_count
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
