from __future__ import annotations

from typing import Any

from assistants.dq.chat import continue_dq_chat, start_dq_chat_session
from assistants.dq.format import format_dq_opening
from assistants.rca.chat import continue_chat, start_chat_session
from assistants.rca.format import format_executions_answer, format_rca_opening
from assistants.shared.chat import clean_reply, fact_check_reply


class FakeLLM:
    """Deterministic LLM for conversation path tests (no network)."""

    model = "fake-eval"

    def __init__(self, replies: list[str] | None = None) -> None:
        self.replies = list(replies or [])
        self.calls = 0

    def chat(self, system: str, user: str) -> str:
        return self.chat_messages(system, [{"role": "user", "content": user}])

    def chat_messages(self, system: str, messages: list[dict[str, Any]]) -> str:
        self.calls += 1
        if self.replies:
            return self.replies.pop(0)
        return (
            "The finance_etl pipeline failed. Metadata shows Connection timeout to Snowflake "
            "on extract_orders. Downstream ANALYTICS.MART.FCT_ORDERS may be stale."
        )


class FakeMeta:
    """In-memory MetadataClient stand-in for assistant conversation tests."""

    def get_incident(self, tenant_id: str, incident_key: str) -> dict[str, Any]:
        return {
            "incident_key": incident_key,
            "title": "Pipeline failed: finance_etl",
            "status": "open",
            "severity": "high",
            "root_asset_type": "pipeline",
            "root_asset_id": "finance_etl",
            "summary": "Connection timeout to Snowflake",
            "error_message": "Connection timeout to Snowflake",
        }

    def list_alerts(self, tenant_id: str, *, asset_id: str | None = None, limit: int = 200):
        return [
            {
                "alert_key": "alert:run-1",
                "title": "Pipeline failed: finance_etl",
                "status": "open",
                "severity": "high",
                "asset_id": "finance_etl",
                "message": "Connection timeout to Snowflake",
                "monitor_type": "pipeline_failure",
            }
        ]

    def list_incidents(self, tenant_id: str, *, asset_id: str | None = None, limit: int = 200):
        return [self.get_incident(tenant_id, "inc:demo:pipeline:finance_etl:pipeline_failure")]

    def list_executions(self, tenant_id: str, pipeline_id: str | None = None, limit: int = 100):
        return [
            {
                "execution_id": "manual__2026-07-28",
                "pipeline_id": "finance_etl",
                "task_id": "extract_orders",
                "status": "failed",
                "error_message": "Connection timeout to Snowflake",
                "source_tool": "airflow",
                "started_at": "2026-07-28T10:00:00Z",
                "deep_link": "https://airflow.example.com/dags/finance_etl/grid?dag_run_id=manual__2026-07-28",
                "deep_link_label": "Open in Airflow",
            }
        ]

    def get_pipeline_dashboard(self, tenant_id: str, pipeline_id: str):
        return {
            "pipeline": {"pipeline_id": pipeline_id, "source_tool": "airflow", "status": "failed"},
            "metrics": {"failed": 1, "succeeded": 0, "total_runs": 1},
            "task_stats": [{"task_id": "extract_orders", "failed": 1, "total": 1}],
            "related_datasets": ["ANALYTICS.RAW.ORDERS", "ANALYTICS.MART.FCT_ORDERS"],
            "pipeline_io": [
                {
                    "upstream_dataset_id": "ANALYTICS.RAW.ORDERS",
                    "downstream_dataset_id": "ANALYTICS.MART.FCT_ORDERS",
                    "source_tool": "airflow",
                }
            ],
            "executions": self.list_executions(tenant_id, pipeline_id),
            "tasks": [{"task_id": "extract_orders", "name": "extract_orders", "source_tool": "airflow"}],
        }

    def get_dataset(self, tenant_id: str, dataset_id: str):
        return {
            "dataset_id": dataset_id,
            "name": dataset_id.split(".")[-1],
            "platform": "snowflake",
            "row_count": 50,
        }

    def get_blast_radius(self, tenant_id: str, dataset_id: str):
        return {"dataset_id": dataset_id, "downstream": [], "count": 0}

    def list_lineage(self, tenant_id: str, dataset_id: str | None = None, limit: int = 200):
        return [
            {
                "upstream_dataset_id": "ANALYTICS.RAW.ORDERS",
                "downstream_dataset_id": "ANALYTICS.MART.FCT_ORDERS",
                "transform": "finance_etl",
            }
        ]

    def list_monitors(self, tenant_id: str, limit: int = 200):
        return [
            {
                "monitor_key": "mon:demo:volume:ANALYTICS.MART.FCT_ORDERS",
                "monitor_type": "volume",
                "asset_id": "ANALYTICS.MART.FCT_ORDERS",
                "enabled": True,
            }
        ]

    def list_check_results(self, tenant_id: str, *, asset_id=None, monitor_type=None, limit=100):
        if asset_id and "FCT_ORDERS" not in asset_id and "ORDERS" not in asset_id:
            return []
        return [
            {
                "id": 1,
                "monitor_type": "volume",
                "asset_id": asset_id or "ANALYTICS.MART.FCT_ORDERS",
                "status": "anomalous",
                "metric_value": 50,
                "details": {"row_count": 50, "expected_min": 10000},
                "severity": "medium",
            }
        ]

    def list_datasets(self, tenant_id: str, limit: int = 200):
        return [self.get_dataset(tenant_id, "ANALYTICS.MART.FCT_ORDERS")]

    def list_pipelines(self, tenant_id: str, limit: int = 200):
        return [
            {
                "pipeline_id": "finance_etl",
                "name": "finance_etl",
                "source_tool": "airflow",
                "status": "failed",
            }
        ]

    def list_metrics(self, tenant_id: str, *, asset_id=None, name=None, limit=100):
        rows = [
            {
                "name": "row_count",
                "asset_id": "ANALYTICS.MART.FCT_ORDERS",
                "value": 50,
                "unit": "rows",
                "recorded_at": "2026-07-28T10:00:00Z",
            },
            {
                "name": "freshness_lag_hours",
                "asset_id": "ANALYTICS.MART.FCT_ORDERS",
                "value": 6,
                "unit": "hours",
                "recorded_at": "2026-07-28T10:00:00Z",
            },
        ]
        if asset_id:
            rows = [r for r in rows if r["asset_id"] == asset_id]
        if name:
            rows = [r for r in rows if r["name"] == name]
        return rows[:limit]


def test_fact_check_flags_invented_fqn():
    evidence = {
        "allowed_citation_ids": ["finance_etl", "ANALYTICS.RAW.ORDERS"],
        "executions": [{"pipeline_id": "finance_etl", "status": "failed"}],
    }
    reply, grounded, invented = fact_check_reply(
        "The issue is in FAKE.SCHEMA.INVENTED_TABLE which never appears in metadata.",
        evidence,
    )
    assert grounded is False
    assert any("INVENTED" in t for t in invented)
    assert "doesn't confirm" in reply.lower() or "unverified" in reply.lower()


def test_fact_check_allows_known_assets():
    evidence = {
        "allowed_citation_ids": ["finance_etl", "ANALYTICS.MART.FCT_ORDERS", "extract_orders"],
        "executions": [
            {
                "pipeline_id": "finance_etl",
                "task_id": "extract_orders",
                "error_message": "Connection timeout to Snowflake",
            }
        ],
    }
    reply, grounded, invented = fact_check_reply(
        "finance_etl failed on extract_orders. ANALYTICS.MART.FCT_ORDERS may be stale.",
        evidence,
    )
    assert grounded is True
    assert invented == []
    assert "finance_etl" in reply


def test_rca_conversation_opening_and_followups():
    meta = FakeMeta()
    llm = FakeLLM(
        [
            "finance_etl failed due to Connection timeout to Snowflake on extract_orders.",
            "Open Airflow for the full task log. Metadata shows the same timeout error.",
            "Blast radius: related datasets include ANALYTICS.MART.FCT_ORDERS.",
        ]
    )
    session = start_chat_session(
        "demo",
        "inc:demo:pipeline:finance_etl:pipeline_failure",
        client=meta,  # type: ignore[arg-type]
        llm=llm,  # type: ignore[arg-type]
    )
    assert session["messages"]
    assert session["messages"][-1]["role"] == "assistant"
    opening = session["messages"][-1]["content"]
    assert "finance_etl" in opening.lower() or "timeout" in opening.lower()
    assert "alert:" not in opening

    sid = session["session_id"]
    turn = continue_chat(sid, "What failed and why?", llm=llm, client=meta)  # type: ignore[arg-type]
    assert turn["reply"]
    assert turn.get("grounded") is True
    assert turn.get("agentic") is True
    assert "alert:" not in turn["reply"]

    turn2 = continue_chat(sid, "What is the blast radius?", llm=llm, client=meta)  # type: ignore[arg-type]
    assert "FCT_ORDERS" in turn2["reply"] or "blast" in turn2["reply"].lower() or "metadata" in turn2["reply"].lower()


def test_rca_fallback_without_llm():
    meta = FakeMeta()

    class BoomLLM(FakeLLM):
        def chat_messages(self, system, messages):
            raise RuntimeError("no network")

    session = start_chat_session(
        "demo",
        "inc:demo:pipeline:finance_etl:pipeline_failure",
        client=meta,  # type: ignore[arg-type]
        llm=BoomLLM(),  # type: ignore[arg-type]
    )
    content = session["messages"][-1]["content"]
    assert content
    assert "alert:" not in content
    # Fallback should still surface error context
    assert "timeout" in content.lower() or "finance_etl" in content.lower() or "failed" in content.lower()


def test_dq_conversation_paths():
    meta = FakeMeta()
    llm = FakeLLM(
        [
            "Volume looks low on ANALYTICS.MART.FCT_ORDERS (about 50 rows). It is built from ANALYTICS.RAW.ORDERS.",
            "No downstream blast radius is flagged in metadata.",
            "Suggested next step: re-run finance_etl after fixing the extract.",
        ]
    )
    session = start_dq_chat_session(
        "demo",
        "ANALYTICS.MART.FCT_ORDERS",
        client=meta,  # type: ignore[arg-type]
        llm=llm,  # type: ignore[arg-type]
    )
    opening = session["messages"][-1]["content"]
    assert "FCT_ORDERS" in opening or "volume" in opening.lower() or "50" in opening
    assert "alert:" not in opening

    sid = session["session_id"]
    t1 = continue_dq_chat(sid, "What checks failed?", llm=llm, client=meta)  # type: ignore[arg-type]
    assert t1["reply"]
    assert t1.get("agentic") is True
    t2 = continue_dq_chat(sid, "What about lineage?", llm=llm, client=meta)  # type: ignore[arg-type]
    assert t2["reply"]


def test_dq_fallback_format():
    meta = FakeMeta()

    class BoomLLM(FakeLLM):
        def chat_messages(self, system, messages):
            raise RuntimeError("down")

    session = start_dq_chat_session(
        "demo",
        "ANALYTICS.MART.FCT_ORDERS",
        client=meta,  # type: ignore[arg-type]
        llm=BoomLLM(),  # type: ignore[arg-type]
    )
    content = session["messages"][-1]["content"]
    assert "alert:" not in content
    assert "FCT_ORDERS" in content or "volume" in content.lower()


def test_format_helpers_error_and_dq():
    evidence = {
        "incident": {"summary": "Pipeline failed", "title": "Pipeline failed: finance_etl"},
        "alerts": [],
        "executions": [
            {
                "pipeline_id": "finance_etl",
                "status": "failed",
                "error_message": "Connection timeout to Snowflake",
                "deep_link": "https://airflow.example.com/x",
                "deep_link_label": "Open in Airflow",
            }
        ],
        "dataset": {"dataset_id": "ANALYTICS.MART.FCT_ORDERS"},
        "check_results": [
            {
                "monitor_type": "volume",
                "status": "anomalous",
                "metric_value": 50,
                "details": {"row_count": 50},
            }
        ],
        "lineage_edges": [
            {
                "upstream_dataset_id": "ANALYTICS.RAW.ORDERS",
                "downstream_dataset_id": "ANALYTICS.MART.FCT_ORDERS",
            }
        ],
        "blast_radius": {"downstream": []},
        "alerts": [],
        "incidents": [],
    }
    exec_ans = format_executions_answer(evidence)
    assert "Connection timeout" in exec_ans
    assert "Open in Airflow" in exec_ans
    rca = format_rca_opening(
        {"summary": "Failed", "likely_cause": "Timeout", "timeline": [], "blast_radius": [], "recommended_actions": []},
        "Pipeline failed: finance_etl",
        evidence=evidence,
    )
    assert "Error detail" in rca
    dq = format_dq_opening(evidence, "ANALYTICS.MART.FCT_ORDERS")
    assert "alert:" not in dq
    assert "alert:" not in clean_reply("See alert:abc-123")
    assert "See" in clean_reply("See alert:abc-123")


# Golden eval scoring helpers used by scripts/eval_assistants.py
GOLDEN_RCA = {
    "must_mention_any": ["finance_etl", "timeout", "extract_orders"],
    "must_not_contain": ["alert:", "inc:", "Citations:"],
}

GOLDEN_DQ = {
    "must_mention_any": ["volume", "50", "FCT_ORDERS", "ORDERS"],
    "must_not_contain": ["alert:", "inc:", "Citations:"],
}


def score_reply(reply: str, golden: dict[str, list[str]]) -> dict[str, Any]:
    text = reply or ""
    lower = text.lower()
    hits = [t for t in golden["must_mention_any"] if t.lower() in lower]
    leaks = [t for t in golden["must_not_contain"] if t.lower() in lower]
    return {
        "pass": bool(hits) and not leaks,
        "hits": hits,
        "leaks": leaks,
    }


def test_golden_scores_on_fallback_outputs():
    meta = FakeMeta()
    evidence_rca = {
        "incident": meta.get_incident("demo", "x"),
        "alerts": meta.list_alerts("demo"),
        "executions": meta.list_executions("demo", "finance_etl"),
    }
    rca_text = format_rca_opening(
        {
            "summary": "finance_etl failed with timeout",
            "likely_cause": "extract_orders Connection timeout to Snowflake",
            "timeline": [],
            "blast_radius": [],
            "recommended_actions": ["Open Airflow"],
        },
        "Pipeline failed: finance_etl",
        evidence=evidence_rca,
    )
    assert score_reply(rca_text, GOLDEN_RCA)["pass"] is True

    dq_ev = {
        "dataset": meta.get_dataset("demo", "ANALYTICS.MART.FCT_ORDERS"),
        "check_results": meta.list_check_results("demo", asset_id="ANALYTICS.MART.FCT_ORDERS"),
        "lineage_edges": meta.list_lineage("demo"),
        "blast_radius": meta.get_blast_radius("demo", "ANALYTICS.MART.FCT_ORDERS"),
        "alerts": [],
        "incidents": [],
    }
    dq_text = format_dq_opening(dq_ev, "ANALYTICS.MART.FCT_ORDERS")
    assert score_reply(dq_text, GOLDEN_DQ)["pass"] is True
