"""Diagnose remaining smoke failures + dbt credential wiring (no secrets printed)."""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")


def http_status(token: str, api_base: str, account_id: str):
    url = f"{api_base.rstrip('/')}/accounts/{account_id}/"
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Token {token}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            return r.status, "ok"
    except urllib.error.HTTPError as e:
        msg = e.read().decode("utf-8", "replace").lower()
        if "cancelled or locked" in msg:
            brief = "account_cancelled_or_locked"
        elif e.code == 401:
            brief = "unauthorized"
        else:
            brief = "http_error"
        return e.code, brief
    except Exception as e:
        return None, type(e).__name__


def main() -> None:
    acc = os.getenv("ECOM_DBT_ACCOUNT_ID") or ""
    base = os.getenv("ECOM_DBT_API_BASE") or ""
    cloud = "https://cloud.getdbt.com/api/v2"
    print("=== dbt Cloud token probe (status only) ===")
    print("account_id_set=", bool(acc), "configured_api_base=", base)
    for name, env_key, b in [
        ("primary", "DBT_CLOUD_API_TOKEN", base),
        ("ecom", "ECOM_DBT_CLOUD_API_TOKEN", base),
        ("hr", "HR_DBT_CLOUD_API_TOKEN", base),
        ("primary", "DBT_CLOUD_API_TOKEN", cloud),
        ("ecom", "ECOM_DBT_CLOUD_API_TOKEN", cloud),
    ]:
        tok = os.getenv(env_key) or ""
        host = b.split("//")[-1] if b else "?"
        if not tok:
            print(f"  {name}@{host}: MISSING_ENV")
            continue
        code, brief = http_status(tok, b, acc)
        print(f"  {name}@{host}: http={code} reason={brief}")

    print("\n=== dbt tool auth_ref wiring ===")
    from application.src.store.meta_mysql import (
        get_connection,
        get_decrypted_tool_secret,
        get_tool,
    )

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT instance_id, name, connector_type, auth_ref, connection_id
                FROM obs_connector_instances
                WHERE connector_type IN ('dbt', 'dbt_cloud')
                ORDER BY updated_at DESC
                LIMIT 10
                """
            )
            rows = list(cur.fetchall() or [])
    finally:
        conn.close()

    for r in rows:
        iid = r["instance_id"]
        gt = get_tool(iid) or {}
        decryptable = False
        decrypt_err = None
        try:
            decryptable = bool(get_decrypted_tool_secret(iid))
        except Exception as e:
            decrypt_err = type(e).__name__
        print(
            {
                "name": r["name"],
                "db_instance_auth_ref": r.get("auth_ref"),
                "api_returned_auth_ref": gt.get("auth_ref"),
                "has_secret_flag": gt.get("has_secret"),
                "decryptable_secret": decryptable,
                "decrypt_err": decrypt_err,
                "config_api_token_env": (gt.get("config") or {}).get("api_token_env"),
                "config_api_base": (gt.get("config") or {}).get("api_base"),
            }
        )

    print("\n=== legacy dashboard overview ===")
    try:
        with urllib.request.urlopen(
            "http://127.0.0.1:8010/v1/dashboard/overview", timeout=90
        ) as resp:
            print("http=", resp.status)
    except urllib.error.HTTPError as e:
        print("http=", e.code, e.read().decode()[:400])
    except Exception as e:
        print("err=", type(e).__name__, e)

    print("\n=== snowflake error class (no password printed) ===")
    try:
        import snowflake.connector

        snowflake.connector.connect(
            account=os.getenv("ECOM_SNOWFLAKE_ACCOUNT"),
            user=os.getenv("ECOM_SNOWFLAKE_USER"),
            password=os.getenv("SNOWFLAKE_PASSWORD"),
            warehouse=os.getenv("ECOM_SNOWFLAKE_WAREHOUSE"),
            database=os.getenv("ECOM_SNOWFLAKE_DATABASE"),
            role=os.getenv("ECOM_SNOWFLAKE_ROLE"),
            login_timeout=35,
        ).close()
        print("snowflake_connect=OK")
    except Exception as e:
        msg = str(e)
        code = msg.split(":")[0].strip() if ":" in msg else type(e).__name__
        print("snowflake_connect=FAIL", "code=", code, "hint=", msg[:180])


if __name__ == "__main__":
    main()
