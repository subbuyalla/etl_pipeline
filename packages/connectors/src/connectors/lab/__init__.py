"""Learning connectors (separate from production adapters)."""

from connectors.lab.snowflake_mine import SNOWFLAKE_LAB_SPEC, create_snowflake_lab_connector

__all__ = ["SNOWFLAKE_LAB_SPEC", "create_snowflake_lab_connector"]
