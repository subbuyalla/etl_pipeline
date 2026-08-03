from __future__ import annotations

from connector_sdk import ConnectorSpec

SNOWFLAKE_SPEC = ConnectorSpec(
    tool_id="snowflake",
    display_name="Snowflake",
    description="Connect a Snowflake account (INFORMATION_SCHEMA catalog sync). Monte Carlo–style form.",
    auth_kinds=["password", "keypair"],
    capabilities=["catalog", "freshness", "volume"],
    input_modes=["live", "csv"],
    secret_fields=["password", "private_key"],
    config_schema={
        "type": "object",
        "required": ["account", "user", "warehouse", "database", "role"],
        "properties": {
            "input_mode": {
                "type": "string",
                "title": "Input mode",
                "enum": ["live", "csv"],
                "default": "live",
            },
            "account": {"type": "string", "title": "Account identifier", "description": "e.g. xy12345.us-east-1"},
            "user": {"type": "string", "title": "User"},
            "warehouse": {"type": "string", "title": "Warehouse"},
            "database": {"type": "string", "title": "Database"},
            "schema": {"type": "string", "title": "Schema filter", "default": ""},
            "role": {"type": "string", "title": "Role"},
            "auth_kind": {
                "type": "string",
                "title": "Auth",
                "enum": ["password", "keypair"],
                "default": "password",
            },
            "password_env": {
                "type": "string",
                "title": "Password env var",
                "description": "Name of env var holding the password (never stored in DB)",
                "default": "SNOWFLAKE_PASSWORD",
            },
            "private_key_env": {
                "type": "string",
                "title": "Private key env var",
                "default": "SNOWFLAKE_PRIVATE_KEY",
            },
            "csv_path": {
                "type": "string",
                "title": "CSV path (csv mode)",
                "description": "Local path when input_mode=csv",
            },
            "freshness_sla_minutes": {
                "type": "integer",
                "title": "Freshness SLA (minutes)",
                "description": "Emit freshness breach when LAST_ALTERED is older than this",
                "default": 60,
            },
            "volume_min_rows": {
                "type": "integer",
                "title": "Minimum expected rows",
                "description": "Emit volume anomaly when ROW_COUNT is below this",
                "default": 1,
            },
        },
    },
)

DBT_SPEC = ConnectorSpec(
    tool_id="dbt",
    display_name="dbt",
    description="Connect dbt Cloud (API) or local run_results/manifest path. Monte Carlo–style form.",
    auth_kinds=["token"],
    capabilities=["runs", "catalog"],
    input_modes=["live", "path", "csv"],
    secret_fields=["api_token"],
    config_schema={
        "type": "object",
        "required": ["input_mode"],
        "properties": {
            "input_mode": {
                "type": "string",
                "title": "Input mode",
                "enum": ["live", "path", "csv"],
                "default": "live",
            },
            "account_id": {"type": "string", "title": "dbt Cloud account id"},
            "project_id": {"type": "string", "title": "dbt Cloud project id"},
            "job_id": {"type": "string", "title": "dbt Cloud job id (optional)"},
            "api_base": {
                "type": "string",
                "title": "API base URL",
                "default": "https://cloud.getdbt.com/api/v2",
            },
            "api_token_env": {
                "type": "string",
                "title": "API token env var",
                "default": "DBT_CLOUD_API_TOKEN",
            },
            "project_name": {
                "type": "string",
                "title": "Project name (path mode)",
                "default": "analytics",
            },
            "run_results_path": {
                "type": "string",
                "title": "run_results.json path",
                "description": "Local artifact when input_mode=path",
            },
            "manifest_path": {
                "type": "string",
                "title": "manifest.json path (optional)",
            },
            "csv_path": {
                "type": "string",
                "title": "CSV path (csv mode)",
            },
        },
    },
)

AIRFLOW_SPEC = ConnectorSpec(
    tool_id="airflow",
    display_name="Apache Airflow",
    description="Sync DAG runs and task instances via Airflow REST API (or CSV offline).",
    auth_kinds=["basic", "token"],
    capabilities=["runs", "tasks", "failures"],
    input_modes=["live", "csv"],
    secret_fields=["username", "password", "api_token"],
    config_schema={
        "type": "object",
        "required": ["input_mode"],
        "properties": {
            "input_mode": {
                "type": "string",
                "title": "Input mode",
                "enum": ["live", "csv"],
                "default": "live",
            },
            "base_url": {
                "type": "string",
                "title": "Airflow base URL",
                "description": "e.g. https://airflow.example.com (no trailing slash)",
            },
            "dag_id": {
                "type": "string",
                "title": "DAG id filter (optional)",
                "description": "Limit sync to one DAG",
            },
            "run_limit": {
                "type": "integer",
                "title": "Max DAG runs per DAG",
                "default": 20,
            },
            "username_env": {
                "type": "string",
                "title": "Username env var",
                "default": "AIRFLOW_USERNAME",
            },
            "password_env": {
                "type": "string",
                "title": "Password env var",
                "default": "AIRFLOW_PASSWORD",
            },
            "api_token_env": {
                "type": "string",
                "title": "Bearer token env var",
                "default": "AIRFLOW_TOKEN",
            },
            "csv_path": {
                "type": "string",
                "title": "CSV path (csv mode)",
            },
        },
    },
)

SPECS: dict[str, ConnectorSpec] = {
    SNOWFLAKE_SPEC.tool_id: SNOWFLAKE_SPEC,
    DBT_SPEC.tool_id: DBT_SPEC,
    AIRFLOW_SPEC.tool_id: AIRFLOW_SPEC,
}

# Lab connector (learning) — registered in registry; spec imported there too
try:
    from connectors.lab.snowflake_mine import SNOWFLAKE_LAB_SPEC

    SPECS[SNOWFLAKE_LAB_SPEC.tool_id] = SNOWFLAKE_LAB_SPEC
except ImportError:
    pass

