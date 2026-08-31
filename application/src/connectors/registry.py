"""Factory for connector plugins by tool_id / connector_type."""

from __future__ import annotations

from typing import Any


def list_connector_types() -> list[dict[str, str]]:
    return [
        {"id": "snowflake", "kind": "database", "label": "Snowflake"},
        {"id": "mysql", "kind": "database", "label": "MySQL"},
        {"id": "postgres", "kind": "database", "label": "PostgreSQL"},
        {"id": "redshift", "kind": "database", "label": "Amazon Redshift"},
        {"id": "bigquery", "kind": "database", "label": "Google BigQuery"},
        {"id": "dbt", "kind": "etl", "label": "dbt Cloud"},
        {"id": "dbt_cloud", "kind": "etl", "label": "dbt Cloud"},
        {"id": "airbyte", "kind": "etl", "label": "Airbyte"},
        {"id": "airflow", "kind": "orchestrator", "label": "Apache Airflow"},
    ]


def get_connector(connector_type: str, **kwargs: Any) -> Any:
    """
    Instantiate a connector by type.
    kwargs are tool-specific (tenant_id, credentials, schema filters, …).
    """
    key = (connector_type or "").strip().lower()
    if key in {"snowflake", "snowflake_lab"}:
        from application.src.connectors.snowflake import SnowflakeConnector

        return SnowflakeConnector(**kwargs)
    if key in {"mysql", "mysql_lab"}:
        from application.src.connectors.mysql import MysqlConnector

        return MysqlConnector(**kwargs)
    if key in {"postgres", "postgresql"}:
        from application.src.connectors.postgres import PostgresConnector

        return PostgresConnector(**kwargs)
    if key in {"redshift"}:
        from application.src.connectors.redshift import RedshiftConnector

        return RedshiftConnector(**kwargs)
    if key in {"bigquery", "bq"}:
        from application.src.connectors.bigquery import BigQueryConnector

        return BigQueryConnector(**kwargs)
    if key in {"dbt", "dbt_cloud"}:
        from application.src.connectors.dbt import DbtConnector

        return DbtConnector(**kwargs)
    if key in {"airbyte"}:
        from application.src.connectors.airbyte import AirbyteConnector

        return AirbyteConnector(**kwargs)
    if key in {"airflow"}:
        from application.src.connectors.airflow import AirflowConnector

        return AirflowConnector(**kwargs)
    raise ValueError(f"Unknown connector_type={connector_type!r}")
