from __future__ import annotations

from normalization.mappers.base import BaseMapper
from normalization.mappers.tools import (
    AdfMapper,
    AdlsMapper,
    AirflowMapper,
    BigQueryMapper,
    DagsterMapper,
    DatabricksMapper,
    DbtMapper,
    GcsMapper,
    GenericApiMapper,
    GlueMapper,
    InformaticaMapper,
    KafkaMapper,
    LookerMapper,
    MysqlMapper,
    NifiMapper,
    OracleMapper,
    PostgresMapper,
    PowerBiMapper,
    PrefectMapper,
    RedshiftMapper,
    S3Mapper,
    SalesforceMapper,
    SapMapper,
    SnowflakeMapper,
    SqlServerMapper,
    SsisMapper,
    TableauMapper,
    TalendMapper,
)

TOOL_FAMILIES: dict[str, list[str]] = {
    "etl_orchestration": [
        "airflow",
        "glue",
        "informatica",
        "adf",
        "talend",
        "ssis",
        "nifi",
        "prefect",
        "dagster",
    ],
    "elt_transform": ["dbt"],
    "warehouse_database": [
        "snowflake",
        "bigquery",
        "databricks",
        "redshift",
        "oracle",
        "postgres",
        "mysql",
        "sqlserver",
    ],
    "streaming_storage": ["kafka", "s3", "gcs", "adls"],
    "saas_source": ["salesforce", "sap", "generic_api"],
    "bi_analytics": ["tableau", "looker", "powerbi"],
}

_MAPPER_CLASSES: list[type[BaseMapper]] = [
    AirflowMapper,
    GlueMapper,
    InformaticaMapper,
    AdfMapper,
    TalendMapper,
    SsisMapper,
    NifiMapper,
    PrefectMapper,
    DagsterMapper,
    DbtMapper,
    SnowflakeMapper,
    BigQueryMapper,
    DatabricksMapper,
    RedshiftMapper,
    OracleMapper,
    PostgresMapper,
    MysqlMapper,
    SqlServerMapper,
    KafkaMapper,
    S3Mapper,
    GcsMapper,
    AdlsMapper,
    SalesforceMapper,
    SapMapper,
    GenericApiMapper,
    TableauMapper,
    LookerMapper,
    PowerBiMapper,
]

_REGISTRY: dict[str, BaseMapper] = {cls.tool_id: cls() for cls in _MAPPER_CLASSES}


def get_mapper(tool: str) -> BaseMapper | None:
    return _REGISTRY.get(tool.lower().strip())


def list_tools() -> list[str]:
    return sorted(_REGISTRY.keys())


def register_mapper(mapper: BaseMapper) -> None:
    """Allow plugins / twin adapters to register additional tools at runtime."""
    _REGISTRY[mapper.tool_id] = mapper
    family = getattr(mapper, "family", "custom")
    TOOL_FAMILIES.setdefault(family, [])
    if mapper.tool_id not in TOOL_FAMILIES[family]:
        TOOL_FAMILIES[family].append(mapper.tool_id)
