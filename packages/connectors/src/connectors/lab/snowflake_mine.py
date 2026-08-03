"""
YOUR Snowflake connector (lab).

Build order inside this file:
  Step A — class + __init__
  Step B — _connect
  Step C — test_connection
  Step D — _fetch_tables
  Step E — discover / pull_state / stream_events
  Step F — create_snowflake_lab_connector factory
"""

from __future__ import annotations

from typing import Any, Iterator

from connector_sdk import ConnectionResult, Connector, ConnectorContext, ConnectorSpec, RawEnvelope

# ---------------------------------------------------------------------------
# Step: Spec (drives the UI form for tool_id = snowflake_lab)
# ---------------------------------------------------------------------------

SNOWFLAKE_LAB_SPEC = ConnectorSpec(
    tool_id="snowflake_lab",
    display_name="Snowflake (My Lab)",
    description="Learning connector — you built this class step by step.",
    auth_kinds=["password"],
    capabilities=["catalog"],
    input_modes=["live"],
    secret_fields=["password"],
    config_schema={
        "type": "object",
        "required": ["account", "user", "warehouse", "database", "role"],
        "properties": {
            "input_mode": {
                "type": "string",
                "title": "Input mode",
                "enum": ["live"],
                "default": "live",
            },
            "account": {"type": "string", "title": "Account identifier"},
            "user": {"type": "string", "title": "User"},
            "warehouse": {"type": "string", "title": "Warehouse"},
            "database": {"type": "string", "title": "Database"},
            "schema": {"type": "string", "title": "Schema filter", "default": ""},
            "role": {"type": "string", "title": "Role"},
            "password_env": {
                "type": "string",
                "title": "Password env var",
                "default": "SNOWFLAKE_PASSWORD",
            },
        },
    },
)


# ---------------------------------------------------------------------------
# Step A — Your connector class
# ---------------------------------------------------------------------------

class SnowflakeMineConnector(Connector):
    """
    One class = one tool (Snowflake).

    Job: connect → list tables → wrap as RawEnvelope for Normalization.
    """

    tool_id = "snowflake_lab"
    spec = SNOWFLAKE_LAB_SPEC

    def __init__(self, ctx: ConnectorContext) -> None:
        self.ctx = ctx
        self.tenant_id = ctx.tenant_id
        self.connector_instance_id = ctx.connector_instance_id
        self.config = ctx.config
        self.secrets = ctx.secrets  # {"password": "..."} from .env

    # ------------------------------------------------------------------
    # Step B — Open a Snowflake connection
    # ------------------------------------------------------------------

    def _connect(self):
        try:
            import snowflake.connector  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "Install driver: pip install snowflake-connector-python"
            ) from exc

        password = self.secrets.get("password")
        if not password:
            raise RuntimeError(
                "Missing password. Set SNOWFLAKE_PASSWORD in project .env "
                "(never store the real password in MySQL)."
            )

        return snowflake.connector.connect(
            account=self.config.get("account"),
            user=self.config.get("user"),
            password=password,
            warehouse=self.config.get("warehouse"),
            database=self.config.get("database"),
            role=self.config.get("role"),
        )

    # ------------------------------------------------------------------
    # Step C — Test (does login work?)
    # ------------------------------------------------------------------

    def test_connection(self) -> ConnectionResult:
        try:
            conn = self._connect()
            try:
                cur = conn.cursor()
                cur.execute("SELECT CURRENT_VERSION()")
                version = cur.fetchone()
                return ConnectionResult(
                    ok=True,
                    message="Snowflake Lab connection OK",
                    details={"version": version[0] if version else None},
                )
            finally:
                conn.close()
        except Exception as exc:
            return ConnectionResult(
                ok=False,
                message=str(exc),
                details={"error_type": type(exc).__name__},
            )

    # ------------------------------------------------------------------
    # Step D — Read table metadata from Snowflake
    # ------------------------------------------------------------------

    def _fetch_tables(self) -> list[dict[str, Any]]:
        """
        This is the metadata we store (not the business row data).

        Returns rows like:
          {
            "database": "ANALYTICS_DB",
            "schema": "RAW",
            "table": "STOCK_DATA_RAW",
            "dataset_id": "ANALYTICS_DB.RAW.STOCK_DATA_RAW",
            "row_count": 123,
            "last_altered": "2026-07-29T..."
          }
        """
        database = self.config.get("database")
        schema_filter = (self.config.get("schema") or "").strip()

        conn = self._connect()
        try:
            cur = conn.cursor()
            if database:
                cur.execute(f"USE DATABASE {database}")

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

            cur.execute(sql, params or None)

            rows: list[dict[str, Any]] = []
            for catalog, schema, table, row_count, last_altered in cur.fetchall():
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
            conn.close()

    # ------------------------------------------------------------------
    # Step E — Required Connector API
    # ------------------------------------------------------------------

    def discover(self) -> list[dict[str, Any]]:
        """Short list of assets (for UI / debugging)."""
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
        """
        Sync uses this.

        Important: source_system="snowflake" so Normalization's warehouse
        mapper still works (same as production Snowflake connector).
        """
        envelopes: list[RawEnvelope] = []
        for row in self._fetch_tables():
            raw = {
                "event_type": "discovered",
                "database": row["database"],
                "schema": row["schema"],
                "table": row["table"],
                "dataset_id": row["dataset_id"],
                "row_count": row.get("row_count"),
                "last_altered": row.get("last_altered"),
            }
            envelopes.append(
                RawEnvelope(
                    source_system="snowflake",  # for normalization
                    tenant_id=self.tenant_id,
                    raw=raw,
                    connector_instance_id=self.connector_instance_id,
                    meta={"input": "live", "lab": True},
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


# ---------------------------------------------------------------------------
# Step F — Factory (registry calls this)
# ---------------------------------------------------------------------------

def create_snowflake_lab_connector(ctx: ConnectorContext) -> Connector:
    return SnowflakeMineConnector(ctx)
