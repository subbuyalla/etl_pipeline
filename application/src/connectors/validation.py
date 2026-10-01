"""Shared column validation helpers for warehouse connectors."""

from __future__ import annotations

from typing import Any


def parse_dataset_fqn(dataset_id: str) -> tuple[str, str, str]:
    """Parse DB.SCHEMA.TABLE (3-part) or DB.TABLE (2-part) dataset id."""
    parts = [p.strip() for p in str(dataset_id or "").split(".") if p.strip()]
    if len(parts) == 2:
        return parts[0], "", parts[1]
    if len(parts) != 3:
        raise ValueError(f"dataset_id must be DB.SCHEMA.TABLE or DB.TABLE, got {dataset_id!r}")
    return parts[0], parts[1], parts[2]


def quote_ident_double(name: str) -> str:
    return '"' + str(name or "").replace('"', '""') + '"'


def quote_ident_pg(name: str) -> str:
    return '"' + str(name or "").replace('"', '""') + '"'


def quote_ident_bq(name: str) -> str:
    return "`" + str(name or "").replace("`", "\\`") + "`"


def quote_ident_mysql(name: str) -> str:
    return "`" + str(name or "").replace("`", "``") + "`"


def build_observed_result(
    *,
    check_type: str,
    parts: list[str],
    column_name: str,
    actual_value: int | float,
    expected_max: int | float = 0,
    source: str = "platform_sql",
    total_rows: int | None = None,
    null_count: int | None = None,
    null_rate: float | None = None,
    distinct_count: int | None = None,
    unique_rate: float | None = None,
    blank_count: int | None = None,
    non_null_rate: float | None = None,
    rate_pct: float | None = None,
) -> dict[str, Any]:
    ds = ".".join(p.upper() for p in parts if p)
    col = str(column_name or "").strip().upper()
    diff = float(actual_value) - float(expected_max)
    failure = max(0, int(round(diff))) if diff > 0 else 0
    res: dict[str, Any] = {
        "check_type": check_type,
        "dataset_id": ds,
        "column_name": col,
        "expected_value": expected_max,
        "actual_value": actual_value,
        "failure_count": failure,
        "source": source,
    }
    if total_rows is not None:
        res["total_rows"] = int(total_rows)
    if null_count is not None:
        res["null_count"] = int(null_count)
    if null_rate is not None:
        res["null_rate"] = round(float(null_rate), 2)
    if distinct_count is not None:
        res["distinct_count"] = int(distinct_count)
    if unique_rate is not None:
        res["unique_rate"] = round(float(unique_rate), 2)
    if blank_count is not None:
        res["blank_count"] = int(blank_count)
    if non_null_rate is not None:
        res["non_null_rate"] = round(float(non_null_rate), 2)
    if rate_pct is not None:
        res["rate_pct"] = round(float(rate_pct), 2)
    return res


def run_column_validation_on_connector(
    connector: Any,
    *,
    dataset_id: str,
    column_name: str,
    check_type: str,
    custom_sql: str | None = None,
    expected_max: int = 0,
) -> dict[str, Any]:
    """Dispatch to connector.run_column_validation if present."""
    fn = getattr(connector, "run_column_validation", None)
    if not callable(fn):
        raise ValueError(f"Connector {type(connector).__name__} does not support column validation")
    return fn(
        dataset_id=dataset_id,
        column_name=column_name,
        check_type=check_type,
        custom_sql=custom_sql,
        expected_max=expected_max,
    )


def validate_tool_credentials_and_permissions(
    *,
    connector_type: str,
    config: dict[str, Any] | None = None,
    secret: str | None = None,
    auth_ref: str | None = None,
    tenant_id: str = "demo",
) -> dict[str, Any]:
    """
    Validates connector credentials and verifies required permissions
    before tool creation, without persisting anything to the database.
    """
    from application.src.connectors.registry import get_connector
    from application.src.sync_once import connector_kwargs_from_tool

    cfg = dict(config or {})
    # Extract secret if nested in config
    nested_secret = None
    for k in ("password", "api_token", "token", "secret", "client_secret"):
        if cfg.get(k) and not secret:
            nested_secret = str(cfg[k])
    effective_secret = secret if secret is not None else nested_secret

    ctype = (connector_type or "").strip().lower()
    synthetic_tool = {
        "connector_type": ctype,
        "config": cfg,
        "auth_ref": auth_ref,
    }

    try:
        kwargs = connector_kwargs_from_tool(synthetic_tool, tenant_id=tenant_id)
    except Exception as exc:
        return {
            "ok": False,
            "authenticated": False,
            "permissions_verified": False,
            "message": f"Invalid connector configuration: {exc}",
            "details": {
                "config": {
                    k: v
                    for k, v in cfg.items()
                    if k not in ("password", "api_token", "token", "secret", "client_secret")
                }
            },
        }

    # Inject secret into kwargs
    if effective_secret:
        if ctype in {
            "snowflake",
            "snowflake_lab",
            "mysql",
            "mysql_lab",
            "postgres",
            "postgresql",
            "redshift",
        }:
            kwargs["password"] = effective_secret
        elif ctype in {"dbt", "dbt_cloud"}:
            kwargs["api_token"] = effective_secret
        elif ctype == "airflow":
            kwargs["password"] = effective_secret
            kwargs["token"] = effective_secret
        elif ctype == "airbyte":
            kwargs["client_secret"] = effective_secret
            kwargs["password"] = effective_secret
        elif ctype in {"informatica", "iics", "idmc"}:
            kwargs["password"] = effective_secret

    try:
        connector = get_connector(ctype, **kwargs)
        result = connector.test_connection()
    except Exception as exc:
        return {
            "ok": False,
            "authenticated": False,
            "permissions_verified": False,
            "message": f"Connection test failed: {exc}",
            "details": {"error": str(exc)},
        }

    if not isinstance(result, dict):
        return {
            "ok": False,
            "authenticated": False,
            "permissions_verified": False,
            "message": "Connector returned invalid test response",
            "details": {},
        }

    if not result.get("ok"):
        details = result.get("details") or {}
        perms = details.get("permissions") or {}
        return {
            "ok": False,
            "authenticated": False,
            "permissions_verified": False,
            "message": result.get("message") or "Authentication failed",
            "details": details,
            "error_code": result.get("error_code"),
            "error_hint": result.get("error_hint"),
            "permissions": perms,
        }

    # If test passed, check permissions breakdown
    details = result.get("details") or {}
    perms = details.get("permissions") or {
        "authentication": True,
        "read_access": True,
    }

    missing = [k for k, v in perms.items() if not v]
    if missing:
        return {
            "ok": False,
            "authenticated": True,
            "permissions_verified": False,
            "message": f"Authenticated successfully, but missing required permissions: {', '.join(missing)}",
            "details": details,
            "permissions": perms,
        }

    return {
        "ok": True,
        "authenticated": True,
        "permissions_verified": True,
        "message": result.get("message") or "Credentials and permissions verified successfully",
        "details": details,
        "permissions": perms,
    }

