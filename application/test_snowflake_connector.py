"""
Test YOUR Snowflake connector (application/src/connectors/snowflake.py).

Run from repo root:
  python application/test_snowflake_connector.py

Requires .env in repo root:
  SNOWFLAKE_PASSWORD=...
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")


def load_snowflake_module():
    """Load application connector by file path (avoid clash with packages/connectors)."""
    path = ROOT / "application" / "src" / "connectors" / "snowflake.py"
    if not path.is_file():
        raise FileNotFoundError(f"Connector not found: {path}")
    spec = importlib.util.spec_from_file_location("app_snowflake_connector", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load module from {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main() -> None:
    mod = load_snowflake_module()
    SnowflakeConnector = mod.SnowflakeConnector

    sf = SnowflakeConnector(
        tenant_id="demo",
        connector_instance_id="app-snowflake-test-1",
        account_id="jd97000.ap-southeast-7.aws",
        user_id="Sasi9392",
        warehouse_id="COMPUTE_WH",
        database_id="ANALYTICS_DB",
        role="ACCOUNTADMIN",
        # schema="",  # empty = all schemas in database
    )

    print("=== 1) test_connection ===")
    result = sf.test_connection()
    print(result)

    if not result.get("ok"):
        print("Test failed. Check .env SNOWFLAKE_PASSWORD and account details.")
        sys.exit(1)

    print("\n=== 2) get_databases ===")
    dbs = sf.get_databases()
    print("ok:", dbs.get("ok"), "message:", dbs.get("message"))
    details = dbs.get("details") or {}
    databases = details.get("databases") or []
    print("database count:", len(databases))
    for row in databases[:10]:
        name = row[1] if isinstance(row, (list, tuple)) and len(row) > 1 else row
        print(" -", name)

    print("\n=== 3) _fetch_tables (table metadata) ===")
    tables = sf._fetch_tables()
    print("table count:", len(tables))
    for t in tables[:10]:
        print(
            f" - {t['dataset_id']}  rows={t.get('row_count')}  "
            f"last_altered={t.get('last_altered')}"
        )
    if len(tables) > 10:
        print(f" ... and {len(tables) - 10} more")

    print("\n=== 4) pull_state (Sync envelopes) ===")
    envelopes = sf.pull_state()
    print("envelope count:", len(envelopes))
    for env in envelopes[:5]:
        raw = env.get("raw") or {}
        print(
            f" - source_system={env.get('source_system')}  "
            f"dataset_id={raw.get('dataset_id')}  "
            f"event_type={raw.get('event_type')}"
        )
    if len(envelopes) > 5:
        print(f" ... and {len(envelopes) - 5} more")

    print("\nDone. Snowflake connector Sync path works. Next: store envelopes in Metadata DB.")


if __name__ == "__main__":
    main()
