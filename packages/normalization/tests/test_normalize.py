from __future__ import annotations

import pytest

from normalization import list_tools, normalize, normalize_batch, TOOL_FAMILIES
from normalization.errors import InvalidRawPayloadError, UnknownToolError
from normalization.registry import get_mapper


EXPECTED_TOOLS = {
    "airflow",
    "glue",
    "informatica",
    "adf",
    "talend",
    "ssis",
    "nifi",
    "prefect",
    "dagster",
    "dbt",
    "snowflake",
    "bigquery",
    "databricks",
    "redshift",
    "oracle",
    "postgres",
    "mysql",
    "sqlserver",
    "kafka",
    "s3",
    "gcs",
    "adls",
    "salesforce",
    "sap",
    "generic_api",
    "tableau",
    "looker",
    "powerbi",
}


def test_all_tools_registered():
    tools = set(list_tools())
    assert EXPECTED_TOOLS.issubset(tools)
    assert sum(len(v) for v in TOOL_FAMILIES.values()) >= len(EXPECTED_TOOLS)


@pytest.mark.parametrize("tool", sorted(EXPECTED_TOOLS))
def test_mapper_exists(tool: str):
    assert get_mapper(tool) is not None


def test_airflow_pipeline_failed():
    events = normalize(
        {
            "source_system": "airflow",
            "tenant_id": "demo",
            "raw": {
                "dag_id": "finance_etl",
                "dag_run_id": "manual__2026-07-22",
                "state": "failed",
                "execution_date": "2026-07-22T10:00:00Z",
                "start_date": "2026-07-22T10:00:00Z",
                "end_date": "2026-07-22T10:05:00Z",
                "error": "Task extract_orders failed",
            },
        }
    )
    assert len(events) == 1
    ev = events[0]
    assert ev["event_type"] == "pipeline.execution.failed.v1"
    assert ev["source_tool"] == "airflow"
    assert ev["payload"]["pipeline_id"] == "finance_etl"
    assert ev["payload"]["status"] == "failed"


def test_airflow_task_retry():
    events = normalize(
        source_system="airflow",
        tenant_id="demo",
        raw={
            "dag_id": "finance_etl",
            "task_id": "extract_orders",
            "run_id": "manual__1",
            "state": "up_for_retry",
            "try_number": 2,
            "execution_date": "2026-07-22T10:00:00Z",
        },
    )
    assert events[0]["event_type"] == "task.execution.retried.v1"
    assert events[0]["payload"]["attempt"] == 2


def test_glue_success():
    events = normalize(
        {
            "source_system": "glue",
            "tenant_id": "demo",
            "raw": {
                "jobName": "dim_customer",
                "Id": "jr_123",
                "JobRunState": "SUCCEEDED",
                "StartedOn": "2026-07-22T09:00:00Z",
                "CompletedOn": "2026-07-22T09:10:00Z",
            },
        }
    )
    assert events[0]["event_type"] == "pipeline.execution.succeeded.v1"
    assert events[0]["payload"]["pipeline_id"] == "dim_customer"


def test_dbt_model_task():
    events = normalize(
        {
            "source_system": "dbt",
            "tenant_id": "demo",
            "raw": {
                "project_name": "analytics",
                "unique_id": "model.analytics.fct_orders",
                "node_name": "fct_orders",
                "invocation_id": "inv-1",
                "status": "success",
                "kind": "task",
            },
        }
    )
    assert events[0]["event_type"] == "task.execution.succeeded.v1"


def test_snowflake_freshness():
    events = normalize(
        {
            "source_system": "snowflake",
            "tenant_id": "demo",
            "raw": {
                "database": "ANALYTICS",
                "schema": "MART",
                "table": "FCT_ORDERS",
                "event_type": "freshness",
                "last_updated_at": "2026-07-21T00:00:00Z",
                "sla_minutes": 60,
                "lag_minutes": 180,
            },
        }
    )
    assert events[0]["event_type"] == "dataset.freshness.breached.v1"
    assert "ANALYTICS.MART.FCT_ORDERS" in events[0]["payload"]["dataset_id"]


def test_bigquery_schema_change():
    events = normalize(
        {
            "source_system": "bigquery",
            "tenant_id": "demo",
            "raw": {
                "project": "acme",
                "dataset": "mart",
                "table": "orders",
                "kind": "schema",
                "change_type": "column_removed",
                "columns_removed": ["legacy_id"],
                "breaking": True,
            },
        }
    )
    assert events[0]["event_type"] == "dataset.schema.changed.v1"
    assert events[0]["payload"]["breaking"] is True


def test_kafka_volume():
    events = normalize(
        {
            "source_system": "kafka",
            "tenant_id": "demo",
            "raw": {
                "cluster": "prod",
                "topic": "orders.events",
                "event_type": "volume",
                "row_count": 10,
                "expected_min": 1000,
            },
        }
    )
    assert events[0]["event_type"] == "dataset.volume.anomaly.v1"


@pytest.mark.parametrize(
    "tool,raw",
    [
        ("informatica", {"workflow_name": "wf_load", "run_id": "1", "status": "Succeeded"}),
        ("adf", {"pipeline_name": "pl_ingest", "runId": "r1", "status": "Succeeded"}),
        ("talend", {"job_name": "job_x", "execution_id": "e1", "status": "ok"}),
        ("ssis", {"package_name": "pkg", "execution_id": "9", "status": "failed"}),
        ("nifi", {"process_group": "pg1", "run_id": "b1", "status": "running"}),
        ("prefect", {"flow_name": "daily", "flow_run_id": "fr1", "state_name": "Completed"}),
        ("dagster", {"job_name": "assets", "run_id": "dr1", "status": "SUCCESS"}),
        ("oracle", {"owner": "APP", "table_name": "CUSTOMERS"}),
        ("postgres", {"database": "dw", "schema": "public", "table": "users"}),
        ("mysql", {"database": "app", "table": "orders"}),
        ("sqlserver", {"database": "dw", "schema": "dbo", "table": "fact"}),
        ("redshift", {"database": "dw", "schema": "public", "table": "events"}),
        ("databricks", {"catalog": "main", "schema": "gold", "table": "orders"}),
        ("s3", {"bucket": "lake", "key": "raw/orders/dt=2026-07-22/part.parquet"}),
        ("gcs", {"bucket": "lake", "object": "raw/x.json"}),
        ("adls", {"account": "datalake", "filesystem": "raw", "path": "orders/1.csv"}),
        ("salesforce", {"object": "Account", "org": "prod"}),
        ("sap", {"table": "VBAK", "system": "ERP"}),
        ("generic_api", {"service": "billing", "resource": "/v1/invoices"}),
        ("tableau", {"id": "wb1", "name": "Board Pack", "kind": "workbook"}),
        ("looker", {"id": "d1", "name": "Orders Explore", "kind": "dashboard"}),
        ("powerbi", {"dataset": "Sales", "status": "Completed", "kind": "refresh"}),
    ],
)
def test_every_tool_normalizes(tool: str, raw: dict):
    events = normalize({"source_system": tool, "tenant_id": "demo", "raw": raw})
    assert len(events) >= 1
    assert events[0]["source_tool"] == tool
    assert events[0]["event_id"]
    assert events[0]["payload"]


def test_idempotent_event_ids():
    payload = {
        "source_system": "airflow",
        "tenant_id": "demo",
        "raw": {"dag_id": "a", "run_id": "r1", "state": "failed", "execution_date": "2026-07-22T10:00:00Z"},
    }
    a = normalize(payload)[0]["event_id"]
    b = normalize(payload)[0]["event_id"]
    assert a == b


def test_batch():
    out = normalize_batch(
        [
            {"source_system": "airflow", "tenant_id": "demo", "raw": {"dag_id": "a", "run_id": "1", "state": "success"}},
            {
                "source_system": "snowflake",
                "tenant_id": "demo",
                "raw": {"database": "D", "schema": "S", "table": "T", "event_type": "freshness", "lag_minutes": 90},
            },
        ]
    )
    assert len(out) == 2


def test_unknown_tool():
    with pytest.raises(UnknownToolError):
        normalize({"source_system": "not_a_tool", "tenant_id": "demo", "raw": {"x": 1}})


def test_missing_tenant():
    with pytest.raises(InvalidRawPayloadError):
        normalize({"source_system": "airflow", "raw": {"dag_id": "a", "state": "failed"}})
