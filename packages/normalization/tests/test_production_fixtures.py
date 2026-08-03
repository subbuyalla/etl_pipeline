from __future__ import annotations

import json
from pathlib import Path

import pytest

from normalization import (
    list_tools,
    normalize,
    normalize_batch_production,
    normalize_production,
)
from normalization.errors import UnknownToolError

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_airflow_dag_runs_list_envelope():
    events = normalize({"source_system": "airflow", "tenant_id": "demo", "raw": _load("airflow_dag_runs.json")})
    assert len(events) == 2
    assert events[0]["event_type"] == "pipeline.execution.failed.v1"
    assert events[1]["event_type"] == "pipeline.execution.succeeded.v1"
    assert events[0]["payload"]["pipeline_id"] == "finance_etl"


def test_airflow_task_instances():
    events = normalize(
        {"source_system": "airflow", "tenant_id": "demo", "raw": _load("airflow_task_instances.json")}
    )
    assert len(events) == 1
    assert events[0]["event_type"] == "task.execution.retried.v1"
    assert events[0]["payload"]["attempt"] == 2


def test_glue_job_runs():
    events = normalize({"source_system": "glue", "tenant_id": "demo", "raw": _load("glue_job_runs.json")})
    assert events[0]["event_type"] == "pipeline.execution.failed.v1"
    assert events[0]["payload"]["pipeline_id"] == "dim_customer_load"
    assert "parquet" in (events[0]["payload"]["error_message"] or "")


def test_dbt_run_results():
    events = normalize({"source_system": "dbt", "tenant_id": "demo", "raw": _load("dbt_run_results.json")})
    assert len(events) == 2
    assert events[0]["event_type"] == "task.execution.succeeded.v1"
    assert events[1]["event_type"] == "task.execution.failed.v1"
    assert events[0]["payload"]["pipeline_id"] == "analytics"
    assert events[0]["payload"]["execution_id"] == "inv-9f3a"


def test_snowflake_information_schema_mix():
    events = normalize(
        {"source_system": "snowflake", "tenant_id": "demo", "raw": _load("snowflake_information_schema.json")}
    )
    assert len(events) == 2
    assert events[0]["event_type"] == "dataset.discovered.v1"
    assert events[1]["event_type"] == "dataset.freshness.breached.v1"
    assert "FCT_ORDERS" in events[0]["payload"]["dataset_id"]


def test_bigquery_table_reference():
    events = normalize({"source_system": "bigquery", "tenant_id": "demo", "raw": _load("bigquery_tables.json")})
    assert events[0]["event_type"] == "dataset.discovered.v1"
    assert events[0]["payload"]["database"] == "acme-prod"
    assert events[0]["payload"]["name"] == "orders"


def test_adf_value_envelope():
    events = normalize({"source_system": "adf", "tenant_id": "demo", "raw": _load("adf_pipeline_runs.json")})
    assert events[0]["event_type"] == "pipeline.execution.failed.v1"
    assert events[0]["payload"]["pipeline_id"] == "pl_ingest_sales"


def test_tableau_workbook_discover():
    events = normalize({"source_system": "tableau", "tenant_id": "demo", "raw": _load("tableau_workbooks.json")})
    assert events[0]["event_type"] == "dataset.discovered.v1"
    assert events[0]["source_tool"] == "tableau"


def test_powerbi_refresh():
    events = normalize({"source_system": "powerbi", "tenant_id": "demo", "raw": _load("powerbi_refresh.json")})
    assert events[0]["event_type"] == "pipeline.execution.failed.v1"
    assert events[0]["payload"]["status"] == "failed"


def test_production_dead_letter_unknown_tool():
    result = normalize_production(
        {"source_system": "not_real", "tenant_id": "demo", "raw": {"x": 1}}
    )
    assert result.ok is False
    assert result.event_count == 0
    assert result.error_count == 1
    assert result.dead_letters[0].error_type == "UnknownToolError"


def test_production_dead_letter_bad_payload():
    result = normalize_production(
        {"source_system": "airflow", "tenant_id": "demo", "raw": {"no_dag": True}}
    )
    assert result.ok is False
    assert result.error_count == 1


def test_production_batch_partial_success():
    result = normalize_batch_production(
        [
            {"source_system": "airflow", "tenant_id": "demo", "raw": _load("airflow_dag_runs.json")},
            {"source_system": "missing_tool", "tenant_id": "demo", "raw": {"a": 1}},
        ]
    )
    assert result.event_count == 2
    assert result.error_count == 1
    assert result.ok is False


def test_bi_tools_registered():
    tools = set(list_tools())
    assert {"tableau", "looker", "powerbi"}.issubset(tools)


def test_strict_still_raises():
    with pytest.raises(UnknownToolError):
        normalize({"source_system": "nope", "tenant_id": "demo", "raw": {}})
