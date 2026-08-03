from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable

from connector_sdk import Connector, ConnectorContext, ConnectorSpec

from connectors.specs import SPECS

Factory = Callable[[ConnectorContext], Connector]

_FACTORIES: dict[str, Factory] = {}
_DOTENV_LOADED = False


def _ensure_dotenv() -> None:
    """Load repo-root .env so SNOWFLAKE_PASSWORD / DBT_CLOUD_API_TOKEN etc. are visible.

    Always re-reads .env with override=False so newly added keys are picked up
    without requiring a process restart (existing process env values win).
    """
    global _DOTENV_LOADED
    try:
        from dotenv import load_dotenv
    except ImportError:
        _DOTENV_LOADED = True
        return
    here = Path(__file__).resolve()
    candidates = [
        Path.cwd() / ".env",
        here.parents[4] / ".env" if len(here.parents) > 4 else None,
        here.parents[3] / ".env" if len(here.parents) > 3 else None,
    ]
    for path in candidates:
        if path and path.is_file():
            load_dotenv(path, override=False)
            _DOTENV_LOADED = True
            return
    load_dotenv(override=False)
    _DOTENV_LOADED = True


def register(tool_id: str, factory: Factory) -> None:
    _FACTORIES[tool_id] = factory


def get_spec(tool_id: str) -> ConnectorSpec | None:
    return SPECS.get(tool_id)


def list_specs() -> list[ConnectorSpec]:
    return [SPECS[k] for k in sorted(SPECS)]


def create_connector(ctx: ConnectorContext) -> Connector:
    factory = _FACTORIES.get(ctx.tool_id)
    if not factory:
        raise ValueError(
            f"No connector registered for tool '{ctx.tool_id}'. "
            f"Registered: {', '.join(sorted(_FACTORIES)) or '(none)'}"
        )
    return factory(ctx)


def _apply_secret_env_defaults(tool_id: str, config: dict[str, Any]) -> dict[str, Any]:
    """Fill password_env / api_token_env from ConnectorSpec defaults when blank."""
    out = dict(config)
    spec = get_spec(tool_id)
    if not spec:
        return out
    props = (spec.config_schema or {}).get("properties") or {}
    for field in spec.secret_fields:
        key = f"{field}_env"
        current = out.get(key)
        if isinstance(current, str) and current.strip():
            continue
        default = (props.get(key) or {}).get("default")
        if default:
            out[key] = str(default)
        else:
            out[key] = f"{tool_id.upper()}_{field.upper()}"
    return out


def resolve_secrets(
    config: dict[str, Any],
    secret_fields: list[str],
    *,
    tool_id: str | None = None,
) -> dict[str, str]:
    """
    Resolve secrets from env using *_{env} config keys.
    Never logs secret values.
    """
    _ensure_dotenv()
    out: dict[str, str] = {}
    for field in secret_fields:
        env_key_name = config.get(f"{field}_env")
        candidates: list[str] = []
        if isinstance(env_key_name, str) and env_key_name.strip():
            candidates.append(env_key_name.strip())
        if tool_id:
            candidates.append(f"{tool_id.upper()}_{field.upper()}")
        candidates.append(field.upper())
        for name in candidates:
            val = os.getenv(name, "")
            if val:
                out[field] = val
                break
    return out


def build_context(
    *,
    tenant_id: str,
    connector_instance_id: str,
    tool_id: str,
    config: dict[str, Any],
) -> ConnectorContext:
    _ensure_dotenv()
    config = _apply_secret_env_defaults(tool_id, config)
    spec = get_spec(tool_id)
    secret_fields = list(spec.secret_fields) if spec else []
    secrets = resolve_secrets(config, secret_fields, tool_id=tool_id)
    input_mode = str(config.get("input_mode") or "live")
    public = {k: v for k, v in config.items() if not k.endswith("_secret") and k not in secret_fields}
    return ConnectorContext(
        tenant_id=tenant_id,
        connector_instance_id=connector_instance_id,
        tool_id=tool_id,
        config=public,
        secrets=secrets,
        input_mode=input_mode,
    )


def _register_builtins() -> None:
    from connectors.adapters.airflow_live import create_airflow_connector
    from connectors.adapters.dbt_live import create_dbt_connector
    from connectors.adapters.snowflake_live import create_snowflake_connector
    from connectors.lab.snowflake_mine import create_snowflake_lab_connector

    register("snowflake", create_snowflake_connector)
    register("dbt", create_dbt_connector)
    register("airflow", create_airflow_connector)
    register("snowflake_lab", create_snowflake_lab_connector)


_register_builtins()
