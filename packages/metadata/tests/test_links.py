from __future__ import annotations

import os

from metadata.links import build_deep_link, deep_link_label, execution_to_dict


def test_airflow_deep_link(monkeypatch):
    monkeypatch.setenv("AIRFLOW_BASE_URL", "https://airflow.example.com")
    url = build_deep_link(
        source_tool="airflow",
        pipeline_id="finance_etl",
        execution_id="manual__2026-07-22T10:00:00+00:00",
        task_id="extract_orders",
    )
    assert url is not None
    assert "https://airflow.example.com/dags/finance_etl/grid" in url
    assert "dag_run_id=" in url
    assert "task_id=extract_orders" in url
    assert deep_link_label("airflow") == "Open in Airflow"


def test_deep_link_missing_config():
    old = os.environ.pop("AIRFLOW_BASE_URL", None)
    try:
        assert build_deep_link(
            source_tool="airflow",
            pipeline_id="finance_etl",
            execution_id="run-1",
        ) is None
    finally:
        if old is not None:
            os.environ["AIRFLOW_BASE_URL"] = old


def test_execution_to_dict_includes_deep_link(monkeypatch):
    monkeypatch.setenv("AIRFLOW_BASE_URL", "https://airflow.example.com")

    class Row:
        execution_id = "run-1"
        pipeline_id = "finance_etl"
        task_id = None
        status = "failed"
        attempt = 1
        error_message = "Task failed"
        source_tool = "airflow"
        started_at = None
        finished_at = None
        duration_ms = 100
        triggered_by = None

    payload = execution_to_dict(Row())
    assert payload["error_message"] == "Task failed"
    assert payload["deep_link"].startswith("https://airflow.example.com/dags/finance_etl/grid")
    assert payload["deep_link_label"] == "Open in Airflow"
