"""
Step-by-step try of YOUR Snowflake lab connector.

Usage (from repo root):
  python docs/fresh-start/connector-lab/try_snowflake_lab.py

Requires .env:
  SNOWFLAKE_PASSWORD=...
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "packages" / "connectors" / "src"))
sys.path.insert(0, str(ROOT / "packages" / "connector-sdk" / "src"))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env", override=True)

from connector_sdk import ConnectorContext
from connectors.lab.snowflake_mine import create_snowflake_lab_connector
from connectors.registry import resolve_secrets


def main() -> None:
    print("=== Step 1: load password from .env ===")
    if not os.getenv("SNOWFLAKE_PASSWORD"):
        print("ERROR: set SNOWFLAKE_PASSWORD in .env")
        sys.exit(1)
    print("password loaded: yes")

    print("\n=== Step 2: build context (same as Metadata API) ===")
    config = {
        "account": os.getenv("SNOWFLAKE_ACCOUNT", "jd97000.ap-southeast-7.aws"),
        "user": os.getenv("SNOWFLAKE_USER", "Sasi9392"),
        "warehouse": os.getenv("SNOWFLAKE_WAREHOUSE", "COMPUTE_WH"),
        "database": os.getenv("SNOWFLAKE_DATABASE", "ANALYTICS_DB"),
        "role": os.getenv("SNOWFLAKE_ROLE", "ACCOUNTADMIN"),
        "password_env": "SNOWFLAKE_PASSWORD",
        "input_mode": "live",
    }
    secrets = resolve_secrets(config, ["password"], tool_id="snowflake_lab")
    ctx = ConnectorContext(
        tenant_id="demo",
        connector_instance_id="snowflake-lab-try-1",
        tool_id="snowflake_lab",
        config=config,
        secrets=secrets,
        input_mode="live",
    )

    print("\n=== Step 3: create YOUR class ===")
    connector = create_snowflake_lab_connector(ctx)
    print("class:", type(connector).__name__)

    print("\n=== Step 4: test_connection ===")
    result = connector.test_connection()
    print(result)

    if not result.ok:
        sys.exit(1)

    print("\n=== Step 5: pull_state (metadata envelopes) ===")
    envelopes = connector.pull_state()
    print("envelopes:", len(envelopes))
    for env in envelopes[:5]:
        print(" -", env.raw.get("dataset_id"), "rows=", env.raw.get("row_count"))
    if len(envelopes) > 5:
        print(f" ... and {len(envelopes) - 5} more")

    print("\nDone. Next: Create connection in UI with tool Snowflake (My Lab), then Sync.")


if __name__ == "__main__":
    main()
