"""CSV-backed and production connectors for Snowflake and dbt."""

from connectors.dbt import DbtCsvConnector
from connectors.registry import create_connector, list_specs, register
from connectors.runner import build_connector, ingest_csv
from connectors.runtime import catalog, run_sync_from_config, test_instance
from connectors.snowflake import SnowflakeCsvConnector
from connectors.specs import DBT_SPEC, SNOWFLAKE_SPEC

__all__ = [
    "SnowflakeCsvConnector",
    "DbtCsvConnector",
    "SNOWFLAKE_SPEC",
    "DBT_SPEC",
    "register",
    "create_connector",
    "list_specs",
    "catalog",
    "build_connector",
    "ingest_csv",
    "run_sync_from_config",
    "test_instance",
]
__version__ = "0.2.0"
