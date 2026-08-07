"""
Pipeline definitions: attach source + ETL + target connector roles.
"""

from __future__ import annotations

import os
import uuid
from typing import Any, Callable


def new_pipeline_id() -> str:
    return str(uuid.uuid4())


# Demo pipeline: Snowflake (RAW) -> dbt -> Snowflake (staging)
STOCK_ETL: dict[str, Any] = {
    "pipeline_name": "stock_etl",
    "tenant_id": "demo",
    "description": "Snowflake RAW source -> dbt Cloud -> Snowflake staging target",
    "source": {
        "tool": "snowflake",
        "connector_instance_id": "sf-source-raw",
        "role": "SOURCE",
        "account_id": os.getenv("SNOWFLAKE_ACCOUNT", "jd97000.ap-southeast-7.aws"),
        "user_id": os.getenv("SNOWFLAKE_USER", "Sasi9392"),
        "warehouse_id": os.getenv("SNOWFLAKE_WAREHOUSE", "COMPUTE_WH"),
        "database_id": os.getenv("SNOWFLAKE_DATABASE", "ANALYTICS_DB"),
        "schema": os.getenv("SF_SOURCE_SCHEMA", "RAW"),
        "sf_role": os.getenv("SNOWFLAKE_ROLE", "ACCOUNTADMIN"),
    },
    "etl": {
        "tool": "dbt",
        "connector_instance_id": "dbt-stock-job",
        "account_id": os.getenv("DBT_ACCOUNT_ID", "70506183151322"),
        "project_id": os.getenv("DBT_PROJECT_ID", "70506183153936"),
        "job_id": os.getenv("DBT_JOB_ID", ""),
        "project_name": os.getenv("DBT_PROJECT_NAME", "analytics"),
        "api_base": os.getenv("DBT_API_BASE", "https://li589.us1.dbt.com/api/v2"),
        # Token read at Sync time from env unless overridden in config_json
        "api_token_env": "DBT_CLOUD_API_TOKEN",
    },
    "target": {
        "tool": "snowflake",
        "connector_instance_id": "sf-target-staging",
        "role": "TARGET",
        "account_id": os.getenv("SNOWFLAKE_ACCOUNT", "jd97000.ap-southeast-7.aws"),
        "user_id": os.getenv("SNOWFLAKE_USER", "Sasi9392"),
        "warehouse_id": os.getenv("SNOWFLAKE_WAREHOUSE", "COMPUTE_WH"),
        "database_id": os.getenv("SNOWFLAKE_DATABASE", "ANALYTICS_DB"),
        "schema": os.getenv("SF_TARGET_SCHEMA", "STAGING_STAGING"),
        "sf_role": os.getenv("SNOWFLAKE_ROLE", "ACCOUNTADMIN"),
    },
}


# Ecommerce: Snowflake SRC_DATA -> dbt (eg250) -> Snowflake CLEAN_DATA
ECOMMERCE_ETL: dict[str, Any] = {
    "pipeline_name": "ecommerce_etl",
    "tenant_id": "demo",
    "description": "Snowflake ECOMMERCE.SRC_DATA -> dbt Cloud -> ECOMMERCE.CLEAN_DATA",
    "source": {
        "tool": "snowflake",
        "connector_instance_id": "sf-ecom-source",
        "role": "SOURCE",
        "account_id": os.getenv(
            "ECOM_SNOWFLAKE_ACCOUNT",
            os.getenv("SNOWFLAKE_ACCOUNT", "jd97000.ap-southeast-7.aws"),
        ),
        "user_id": os.getenv(
            "ECOM_SNOWFLAKE_USER", os.getenv("SNOWFLAKE_USER", "Sasi9392")
        ),
        "warehouse_id": os.getenv("ECOM_SNOWFLAKE_WAREHOUSE", "ECOMMERCE_WH"),
        "database_id": os.getenv("ECOM_SNOWFLAKE_DATABASE", "ECOMMERCE"),
        "schema": os.getenv("ECOM_SF_SOURCE_SCHEMA", "SRC_DATA"),
        "sf_role": os.getenv(
            "ECOM_SNOWFLAKE_ROLE", os.getenv("SNOWFLAKE_ROLE", "ACCOUNTADMIN")
        ),
    },
    "etl": {
        "tool": "dbt",
        "connector_instance_id": "dbt-ecom-job",
        "account_id": os.getenv("ECOM_DBT_ACCOUNT_ID", "70506183153835"),
        # "Pipeline ID" from UI mapped to project_id (set ECOM_DBT_JOB_ID to filter one job)
        "project_id": os.getenv("ECOM_DBT_PROJECT_ID", "70506183136444"),
        "job_id": os.getenv("ECOM_DBT_JOB_ID", ""),
        "project_name": os.getenv("ECOM_DBT_PROJECT_NAME", "ecommerce"),
        "api_base": os.getenv(
            "ECOM_DBT_API_BASE", "https://eg250.us1.dbt.com/api/v2"
        ),
        "api_token_env": "ECOM_DBT_CLOUD_API_TOKEN",
    },
    "target": {
        "tool": "snowflake",
        "connector_instance_id": "sf-ecom-target",
        "role": "TARGET",
        "account_id": os.getenv(
            "ECOM_SNOWFLAKE_ACCOUNT",
            os.getenv("SNOWFLAKE_ACCOUNT", "jd97000.ap-southeast-7.aws"),
        ),
        "user_id": os.getenv(
            "ECOM_SNOWFLAKE_USER", os.getenv("SNOWFLAKE_USER", "Sasi9392")
        ),
        "warehouse_id": os.getenv("ECOM_SNOWFLAKE_WAREHOUSE", "ECOMMERCE_WH"),
        "database_id": os.getenv("ECOM_SNOWFLAKE_DATABASE", "ECOMMERCE"),
        "schema": os.getenv("ECOM_SF_TARGET_SCHEMA", "CLEAN_DATA"),
        "sf_role": os.getenv(
            "ECOM_SNOWFLAKE_ROLE", os.getenv("SNOWFLAKE_ROLE", "ACCOUNTADMIN")
        ),
    },
}


def resolve_pipeline_id() -> str:
    return (os.getenv("PIPELINE_ID") or "").strip() or new_pipeline_id()


def get_stock_etl_pipeline(*, pipeline_id: str | None = None) -> dict[str, Any]:
    """Return the stock_etl pipeline with a stable UUID."""
    pid = (pipeline_id or "").strip() or resolve_pipeline_id()
    return {
        "pipeline_id": pid,
        **STOCK_ETL,
        "pipeline_name": os.getenv("PIPELINE_NAME", STOCK_ETL["pipeline_name"]),
    }


def get_ecommerce_etl_pipeline(*, pipeline_id: str | None = None) -> dict[str, Any]:
    """Return the ecommerce_etl pipeline (SRC_DATA -> dbt -> CLEAN_DATA)."""
    pid = (pipeline_id or "").strip() or new_pipeline_id()
    return {
        "pipeline_id": pid,
        **ECOMMERCE_ETL,
        "pipeline_name": os.getenv(
            "ECOM_PIPELINE_NAME", ECOMMERCE_ETL["pipeline_name"]
        ),
    }


# HR Analytics: Snowflake RAW_DATA -> dbt (eg250) -> Snowflake FINAL_DATA
HR_ETL: dict[str, Any] = {
    "pipeline_name": "hr_etl",
    "tenant_id": "demo",
    "description": (
        "Snowflake HR_ANALYTICS.RAW_DATA.RAW_EMPLOYEES -> dbt Cloud -> "
        "HR_ANALYTICS.FINAL_DATA.DIM_EMPLOYEES"
    ),
    "source": {
        "tool": "snowflake",
        "connector_instance_id": "sf-hr-source",
        "role": "SOURCE",
        "account_id": os.getenv(
            "HR_SNOWFLAKE_ACCOUNT",
            os.getenv("SNOWFLAKE_ACCOUNT", "jd97000.ap-southeast-7.aws"),
        ),
        "user_id": os.getenv(
            "HR_SNOWFLAKE_USER", os.getenv("SNOWFLAKE_USER", "Sasi9392")
        ),
        "warehouse_id": os.getenv("HR_SNOWFLAKE_WAREHOUSE", "HR_ANALYTICS_WH"),
        "database_id": os.getenv("HR_SNOWFLAKE_DATABASE", "HR_ANALYTICS"),
        "schema": os.getenv("HR_SF_SOURCE_SCHEMA", "RAW_DATA"),
        "sf_role": os.getenv(
            "HR_SNOWFLAKE_ROLE", os.getenv("SNOWFLAKE_ROLE", "ACCOUNTADMIN")
        ),
    },
    "etl": {
        "tool": "dbt",
        "connector_instance_id": "dbt-hr-job",
        "account_id": os.getenv("HR_DBT_ACCOUNT_ID", "70506183153835"),
        # "Pipeline ID" from UI mapped to project_id
        "project_id": os.getenv("HR_DBT_PROJECT_ID", "70506183136587"),
        "job_id": os.getenv("HR_DBT_JOB_ID", ""),
        "project_name": os.getenv("HR_DBT_PROJECT_NAME", "hr_analytics"),
        "api_base": os.getenv(
            "HR_DBT_API_BASE", "https://eg250.us1.dbt.com/api/v2"
        ),
        "api_token_env": "HR_DBT_CLOUD_API_TOKEN",
    },
    "target": {
        "tool": "snowflake",
        "connector_instance_id": "sf-hr-target",
        "role": "TARGET",
        "account_id": os.getenv(
            "HR_SNOWFLAKE_ACCOUNT",
            os.getenv("SNOWFLAKE_ACCOUNT", "jd97000.ap-southeast-7.aws"),
        ),
        "user_id": os.getenv(
            "HR_SNOWFLAKE_USER", os.getenv("SNOWFLAKE_USER", "Sasi9392")
        ),
        "warehouse_id": os.getenv("HR_SNOWFLAKE_WAREHOUSE", "HR_ANALYTICS_WH"),
        "database_id": os.getenv("HR_SNOWFLAKE_DATABASE", "HR_ANALYTICS"),
        "schema": os.getenv("HR_SF_TARGET_SCHEMA", "FINAL_DATA"),
        "sf_role": os.getenv(
            "HR_SNOWFLAKE_ROLE", os.getenv("SNOWFLAKE_ROLE", "ACCOUNTADMIN")
        ),
    },
}


def get_hr_etl_pipeline(*, pipeline_id: str | None = None) -> dict[str, Any]:
    """Return the hr_etl pipeline (RAW_DATA -> dbt -> FINAL_DATA)."""
    pid = (pipeline_id or "").strip() or new_pipeline_id()
    return {
        "pipeline_id": pid,
        **HR_ETL,
        "pipeline_name": os.getenv("HR_PIPELINE_NAME", HR_ETL["pipeline_name"]),
    }


_TEMPLATE_BUILDERS: dict[str, Callable[..., dict[str, Any]]] = {
    "stock_etl": get_stock_etl_pipeline,
    "ecommerce_etl": get_ecommerce_etl_pipeline,
    "hr_etl": get_hr_etl_pipeline,
}


def list_pipeline_templates() -> list[str]:
    return sorted(_TEMPLATE_BUILDERS.keys())


def get_pipeline_template(
    pipeline_name: str | None = None,
    *,
    pipeline_id: str | None = None,
) -> dict[str, Any]:
    """
    Build a pipeline dict from a known template name.
    Unknown names fall back to stock_etl.
    """
    key = (pipeline_name or "stock_etl").strip().lower()
    builder = _TEMPLATE_BUILDERS.get(key) or get_stock_etl_pipeline
    pipe = builder(pipeline_id=pipeline_id)
    if pipeline_name and key not in _TEMPLATE_BUILDERS:
        pipe["pipeline_name"] = pipeline_name
    return pipe
