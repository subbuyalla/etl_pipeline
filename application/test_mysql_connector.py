"""
Test YOUR MySQL connector (application/src/connectors/mysql.py).

Run from repo root:
  python application/test_mysql_connector.py

Requires .env in repo root:
  DB_HOST, DB_PORT, DB_USER, DB_PASSWORD (or MYSQL_PASSWORD), DB_NAME
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")


def load_mysql_module():
    """Load application connector by file path."""
    path = ROOT / "application" / "src" / "connectors" / "mysql.py"
    if not path.is_file():
        raise FileNotFoundError(f"Connector not found: {path}")
    spec = importlib.util.spec_from_file_location("app_mysql_connector", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load module from {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main() -> None:
    mod = load_mysql_module()
    MysqlConnector = mod.MysqlConnector

    # Hardcode Workbench host (same idea as Snowflake test).
    # Password still from .env: DB_PASSWORD or MYSQL_PASSWORD
    host = "database-1.cbsuuwi6y4bg.eu-north-1.rds.amazonaws.com"
    user = "admin"
    database = os.getenv("DB_NAME", "metadata")
    port = 3306

    print(f"Connecting to host={host!r} user={user!r} database={database!r} port={port}")

    mysql = MysqlConnector(
        tenant_id="demo",
        connector_instance_id="app-mysql-test-1",
        host=host,
        port=port,
        user=user,
        database=database,
    )

    print("\n=== 1) test_connection ===")
    result = mysql.test_connection()
    print(result)

    if not result.get("ok"):
        print("Test failed. Check .env DB_HOST / DB_USER / DB_PASSWORD / DB_NAME.")
        sys.exit(1)

    print("\n=== 2) get_databases ===")
    dbs = mysql.get_databases()
    print("ok:", dbs.get("ok"), "message:", dbs.get("message"))
    databases = (dbs.get("details") or {}).get("databases") or []
    print("database count:", len(databases))
    for name in databases[:10]:
        print(" -", name)

    print("\n=== 3) _fetch_tables (table metadata) ===")
    tables = mysql._fetch_tables()
    print("table count:", len(tables))
    for t in tables[:10]:
        print(
            f" - {t['dataset_id']}  rows={t.get('row_count')}  "
            f"last_altered={t.get('last_altered')}"
        )
    if len(tables) > 10:
        print(f" ... and {len(tables) - 10} more")

    print("\n=== 4) pull_state (Sync envelopes) ===")
    envelopes = mysql.pull_state()
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

    print("\nDone. MySQL connector Sync path works.")


if __name__ == "__main__":
    main()
