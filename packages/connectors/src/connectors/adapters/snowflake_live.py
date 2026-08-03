from __future__ import annotations

from pathlib import Path
from typing import Any, Iterator

from connector_sdk import ConnectionResult, Connector, ConnectorContext, RawEnvelope

from connectors.adapters.snowflake_monitors import build_table_monitor_events
from connectors.snowflake import SnowflakeCsvConnector
from connectors.specs import SNOWFLAKE_SPEC


class SnowflakeLiveConnector(Connector):
    """Live Snowflake via snowflake-connector-python; falls back messaging if package/creds missing."""

    tool_id = "snowflake"
    spec = SNOWFLAKE_SPEC

    def __init__(self, ctx: ConnectorContext) -> None:
        self.ctx = ctx
        self.tenant_id = ctx.tenant_id
        self.connector_instance_id = ctx.connector_instance_id
        self.config = ctx.config
        self.secrets = ctx.secrets

    def _connect(self):
        try:
            import snowflake.connector  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "snowflake-connector-python is not installed. "
                "pip install snowflake-connector-python  OR use input_mode=csv"
            ) from exc

        password = self.secrets.get("password")
        private_key = self.secrets.get("private_key")
        auth_kind = str(self.config.get("auth_kind") or "password")
        kwargs: dict[str, Any] = {
            "account": self.config.get("account"),
            "user": self.config.get("user"),
            "warehouse": self.config.get("warehouse"),
            "database": self.config.get("database"),
            "role": self.config.get("role"),
        }
        if auth_kind == "keypair" and private_key:
            kwargs["private_key"] = private_key.encode() if isinstance(private_key, str) else private_key
        elif password:
            kwargs["password"] = password
        else:
            raise RuntimeError(
                f"Missing Snowflake credentials. Set env var "
                f"{self.config.get('password_env') or 'SNOWFLAKE_PASSWORD'} "
                f"(never stored in the database)."
            )
        return snowflake.connector.connect(**kwargs)

    def test_connection(self) -> ConnectionResult:
        try:
            conn = self._connect()
            try:
                cur = conn.cursor()
                cur.execute("SELECT CURRENT_VERSION()")
                version = cur.fetchone()
                return ConnectionResult(
                    ok=True,
                    message="Snowflake connection OK",
                    details={"version": version[0] if version else None},
                )
            finally:
                conn.close()
        except Exception as exc:
            return ConnectionResult(ok=False, message=str(exc), details={"error_type": type(exc).__name__})

    def discover(self) -> list[dict[str, Any]]:
        return [
            {
                "asset_type": "dataset",
                "dataset_id": a["dataset_id"],
                "database": a["database"],
                "schema": a["schema"],
                "table": a["table"],
                "platform": "snowflake",
            }
            for a in self._fetch_tables()
        ]

    def pull_state(self) -> list[RawEnvelope]:
        freshness_sla = int(self.config.get("freshness_sla_minutes") or 60)
        volume_min_raw = self.config.get("volume_min_rows")
        volume_min = 1 if volume_min_raw is None or volume_min_raw == "" else int(volume_min_raw)
        envelopes: list[RawEnvelope] = []
        for row in self._fetch_tables():
            for raw in build_table_monitor_events(
                row,
                freshness_sla_minutes=freshness_sla,
                volume_min_rows=volume_min,
            ):
                envelopes.append(
                    RawEnvelope(
                        source_system=self.tool_id,
                        tenant_id=self.tenant_id,
                        raw=raw,
                        connector_instance_id=self.connector_instance_id,
                        meta={"input": "live", "monitors": True},
                    )
                )
        return envelopes

    def stream_events(self, *, ticks: int | None = None) -> Iterator[RawEnvelope]:
        count = 0
        for env in self.pull_state():
            yield env
            count += 1
            if ticks is not None and count >= ticks:
                return

    def _fetch_tables(self) -> list[dict[str, Any]]:
        database = self.config.get("database")
        schema_filter = (self.config.get("schema") or "").strip()
        conn = self._connect()
        try:
            cur = conn.cursor()
            sql = """
                SELECT TABLE_CATALOG, TABLE_SCHEMA, TABLE_NAME, ROW_COUNT, LAST_ALTERED
                FROM INFORMATION_SCHEMA.TABLES
                WHERE TABLE_TYPE = 'BASE TABLE'
            """
            params: list[Any] = []
            if schema_filter:
                sql += " AND TABLE_SCHEMA = %s"
                params.append(schema_filter.upper())
            sql += " ORDER BY TABLE_SCHEMA, TABLE_NAME"
            if database:
                cur.execute(f"USE DATABASE {database}")
            cur.execute(sql, params or None)
            rows = []
            for catalog, schema, table, row_count, last_altered in cur.fetchall():
                rows.append(
                    {
                        "database": catalog,
                        "schema": schema,
                        "table": table,
                        "dataset_id": f"{catalog}.{schema}.{table}",
                        "row_count": row_count,
                        "last_altered": last_altered.isoformat() if hasattr(last_altered, "isoformat") else last_altered,
                    }
                )
            return rows
        finally:
            conn.close()


def create_snowflake_connector(ctx: ConnectorContext) -> Connector:
    mode = (ctx.input_mode or ctx.config.get("input_mode") or "live").lower()
    if mode == "csv":
        path = ctx.config.get("csv_path")
        if not path:
            raise ValueError("csv_path is required when input_mode=csv")
        return SnowflakeCsvConnector(
            path,
            tenant_id=ctx.tenant_id,
            connector_instance_id=ctx.connector_instance_id,
        )
    return SnowflakeLiveConnector(ctx)
