"""Structured vendor error classification for Sync and tool test responses."""

from __future__ import annotations

import re
from typing import Any


def classify_dbt_http_error(message: str | None, *, status_code: int | None = None) -> dict[str, Any]:
    text = (message or "").lower()
    code = "dbt_error"
    hint = "Check dbt Cloud API token, account id, and network access."

    if status_code == 401 or "401" in text or "unauthorized" in text:
        code = "dbt_unauthorized"
        hint = "Invalid or expired dbt Cloud API token."
    elif status_code == 403 or "403" in text or "forbidden" in text:
        code = "dbt_forbidden"
        hint = "Token lacks permission for this dbt Cloud account or resource."
    elif "locked" in text or "cancelled" in text or "canceled" in text:
        code = "dbt_account_locked"
        hint = "dbt Cloud account may be locked or the token was revoked."
    elif status_code in {502, 503, 504} or "unreachable" in text or "timed out" in text:
        code = "dbt_unreachable"
        hint = "dbt Cloud API is unreachable or timed out."
    elif "missing dbt" in text or "missing api" in text:
        code = "dbt_missing_credentials"
        hint = "Set DBT_CLOUD_API_TOKEN or store an encrypted secret on the ETL tool."

    return {"error_code": code, "error_hint": hint, "detail": (message or "")[:500]}


def classify_snowflake_error(message: str | None) -> dict[str, Any]:
    text = message or ""
    lower = text.lower()
    code = "snowflake_error"
    hint = "Check Snowflake account, user, role, warehouse, and password."

    if "390913" in text or "authentication" in lower or "incorrect username or password" in lower:
        code = "snowflake_auth_failed"
        hint = "Snowflake authentication failed — verify user, password, and account identifier."
    elif "390100" in text or "390102" in text:
        code = "snowflake_auth_failed"
        hint = "Snowflake login rejected — check credentials and network policy."
    elif "missing snowflake" in lower or "missing password" in lower:
        code = "snowflake_missing_credentials"
        hint = "Set SNOWFLAKE_PASSWORD or store an encrypted secret on the database tool."
    elif "network" in lower or "connection" in lower and "refused" in lower:
        code = "snowflake_unreachable"
        hint = "Cannot reach Snowflake — check network, account URL, and firewall."

    return {"error_code": code, "error_hint": hint, "detail": text[:500]}


def parse_dbt_runtime_error(message: str | None) -> dict[str, Any]:
    """Extract HTTP status from RuntimeError messages like 'dbt Cloud API 401: ...'."""
    text = message or ""
    m = re.search(r"dbt Cloud API (\d{3}):", text)
    status = int(m.group(1)) if m else None
    return classify_dbt_http_error(text, status_code=status)


def vendor_http_exception(exc: Exception, *, vendor: str = "dbt") -> tuple[int, dict[str, Any]]:
    msg = str(exc)
    if vendor == "snowflake":
        body = classify_snowflake_error(msg)
        status = 502
    else:
        body = parse_dbt_runtime_error(msg)
        status = 503 if body["error_code"] == "dbt_unreachable" else 502
    return status, {"ok": False, **body}
