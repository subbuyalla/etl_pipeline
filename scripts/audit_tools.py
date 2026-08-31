#!/usr/bin/env python3
"""List tools missing encrypted secrets (read-only credential cutover helper)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from application.src.store.meta_mysql import ensure_tables, get_connection, list_tools  # noqa: E402


def audit() -> dict:
    conn = get_connection()
    try:
        ensure_tables(conn)
    finally:
        conn.close()
    tools = list_tools()
        flagged = []
        for t in tools or []:
            cfg = t.get("config") or {}
            if isinstance(cfg, str):
                try:
                    cfg = json.loads(cfg)
                except json.JSONDecodeError:
                    cfg = {}
            has_secret = bool(t.get("has_secret"))
            token_env = cfg.get("api_token_env") or cfg.get("password_env")
            if not has_secret and token_env:
                flagged.append(
                    {
                        "tool_id": t.get("tool_id"),
                        "name": t.get("name"),
                        "connector_type": t.get("connector_type"),
                        "kind": t.get("kind"),
                        "api_token_env": token_env,
                        "has_secret": has_secret,
                    }
                )
        return {"ok": True, "total_tools": len(tools or []), "missing_secret": flagged}


def main() -> int:
    result = audit()
    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
