from __future__ import annotations

from assistants.rca.format import describe_failure_errors, format_executions_answer, format_rca_opening


def test_describe_failure_errors_from_executions():
    evidence = {
        "incident": {"summary": "Pipeline failed: finance_etl"},
        "alerts": [],
        "executions": [
            {
                "pipeline_id": "finance_etl",
                "task_id": "extract_orders",
                "status": "failed",
                "error_message": "Connection timeout to Snowflake",
                "deep_link": "https://airflow.example.com/dags/finance_etl/grid?dag_run_id=run-1",
                "deep_link_label": "Open in Airflow",
            }
        ],
    }
    text = describe_failure_errors(evidence)
    assert "Connection timeout to Snowflake" in text
    assert "finance_etl.extract_orders" in text


def test_format_rca_opening_includes_error_block():
    evidence = {
        "incident": {"summary": "Task failed"},
        "alerts": [],
        "executions": [
            {
                "pipeline_id": "finance_etl",
                "status": "failed",
                "error_message": "Simulated twin failure",
            }
        ],
    }
    rca = {
        "summary": "Pipeline finance_etl failed.",
        "likely_cause": "Extract step error.",
        "timeline": [],
        "blast_radius": [],
        "recommended_actions": ["Check Airflow task logs"],
    }
    text = format_rca_opening(rca, "Pipeline failed: finance_etl", evidence=evidence)
    assert "**Error detail:**" in text
    assert "Simulated twin failure" in text
    assert "Extract step error" in text


def test_format_executions_answer_shows_error_and_link():
    evidence = {
        "executions": [
            {
                "pipeline_id": "finance_etl",
                "status": "failed",
                "started_at": "2026-07-22T10:00:00Z",
                "error_message": "Task extract_orders failed",
                "deep_link": "https://airflow.example.com/dags/finance_etl/grid?dag_run_id=run-1",
                "deep_link_label": "Open in Airflow",
            }
        ]
    }
    text = format_executions_answer(evidence)
    assert "Task extract_orders failed" in text
    assert "Open in Airflow" in text
