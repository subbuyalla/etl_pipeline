"""
Pipeline definitions: attach source + ETL + target connector roles.
"""

from __future__ import annotations

import os
import uuid
from typing import Any


def new_pipeline_id() -> str:
    return str(uuid.uuid4())


# Fixed demo pipeline: Snowflake (RAW) -> dbt -> Snowflake (staging)
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
