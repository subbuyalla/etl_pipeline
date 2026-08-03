"""
Test YOUR dbt Cloud connector (application/src/connectors/dbt.py).

Run from repo root:
  python application/test_dbt_connector.py

Requires .env in repo root:
  DBT_CLOUD_API_TOKEN=...
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")


def load_dbt_module():
    """Load application connector by file path (avoid clash with packages/connectors)."""
    path = ROOT / "application" / "src" / "connectors" / "dbt.py"
    if not path.is_file():
        raise FileNotFoundError(f"Connector not found: {path}")
    spec = importlib.util.spec_from_file_location("app_dbt_connector", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load module from {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main() -> None:
    mod = load_dbt_module()
    DbtConnector = mod.DbtConnector

    dbt = DbtConnector(
        tenant_id="demo",
        connector_instance_id="app-dbt-test-1",
        account_id="70506183151322",
        project_id="70506183153936",
        job_id="",  # blank = all jobs
        project_name="analytics",
        api_base="https://li589.us1.dbt.com/api/v2",
        # token from .env: DBT_CLOUD_API_TOKEN
    )

    print("=== 1) test_connection ===")
    result = dbt.test_connection()
    print(result)

    if not result.get("ok"):
        print("Test failed. Check .env DBT_CLOUD_API_TOKEN, api_base, and account_id.")
        sys.exit(1)

    print("\n=== 2) _fetch_runs (job run metadata) ===")
    runs = dbt._fetch_runs()
    print("run count:", len(runs))
    for r in runs[:5]:
        print(
            f" - run_id={r['run_id']}  status={r.get('status')}  "
            f"job_id={r.get('job_id')}  error={r.get('error_message')!r}"
        )
    if len(runs) > 5:
        print(f" ... and {len(runs) - 5} more")

    print("\n=== 3) pull_state (Sync envelopes) ===")
    envelopes = dbt.pull_state()
    print("envelope count:", len(envelopes))
    for env in envelopes[:5]:
        raw = env.get("raw") or {}
        print(
            f" - source_system={env.get('source_system')}  "
            f"run_id={raw.get('run_id')}  status={raw.get('status')}  "
            f"event_type={raw.get('event_type')}"
        )
    if len(envelopes) > 5:
        print(f" ... and {len(envelopes) - 5} more")

    print("\nDone. dbt connector Sync path works. Next: store envelopes in Metadata DB.")


if __name__ == "__main__":
    main()
