"""Describe RDS tool-related schema and smoke tool secret flags."""
from __future__ import annotations

from dotenv import load_dotenv

load_dotenv(".env")

from application.src.store.meta_mysql import get_connection, get_tool  # noqa: E402


def main() -> None:
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("DESCRIBE obs_connector_instances")
            print("instances:", [r["Field"] for r in cur.fetchall()])
            cur.execute("DESCRIBE obs_connections")
            print("connections:", [r["Field"] for r in cur.fetchall()])
            cur.execute("DESCRIBE obs_secrets")
            print("secrets:", [r["Field"] for r in cur.fetchall()])
            cur.execute(
                """
                SELECT instance_id, name, connector_type, connection_id
                FROM obs_connector_instances
                WHERE name LIKE %s OR connector_type IN ('dbt','dbt_cloud')
                ORDER BY updated_at DESC
                LIMIT 12
                """,
                ("smoke%",),
            )
            rows = list(cur.fetchall() or [])
    finally:
        conn.close()

    print("--- tools ---")
    for r in rows:
        t = get_tool(r["instance_id"]) or {}
        print(
            {
                "name": r["name"],
                "type": r["connector_type"],
                "connection_id": r.get("connection_id"),
                "has_secret": t.get("has_secret"),
                "auth_ref": t.get("auth_ref"),
                "api_token_env": (t.get("config") or {}).get("api_token_env"),
                "api_base": (t.get("config") or {}).get("api_base"),
            }
        )


if __name__ == "__main__":
    main()
