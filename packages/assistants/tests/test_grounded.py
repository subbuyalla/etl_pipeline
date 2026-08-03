from __future__ import annotations

from assistants.dq.format import build_evidence_reference, format_dq_opening
from assistants.shared.chat import clean_reply


def test_clean_reply_strips_alert_ids():
    raw = (
        "Volume failed on the table. "
        "See alert:b5687580-4240-5622-a392-6505555cebeb for details.\n\n"
        "_Citations:_ inc:demo:dataset:FOO:volume, alert:abc"
    )
    cleaned = clean_reply(raw)
    assert "alert:" not in cleaned
    assert "inc:" not in cleaned
    assert "Citations" not in cleaned
    assert "Volume failed" in cleaned


def test_format_dq_opening_no_internal_ids():
    evidence = {
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
    text = format_dq_opening(evidence, "ANALYTICS.MART.FCT_ORDERS")
    assert "alert:" not in text
    assert "inc:" not in text
    assert "50" in text
    assert "ANALYTICS.RAW.ORDERS" in text


def test_build_evidence_reference_grounded_facts():
    evidence = {
        "dataset": {"dataset_id": "T"},
        "check_results": [
            {"monitor_type": "freshness", "status": "failed", "metric_value": 90, "details": {"sla_minutes": 60}}
        ],
        "lineage_edges": [],
        "blast_radius": {"downstream": ["D2"]},
        "alerts": [],
        "incidents": [],
    }
    ref = build_evidence_reference(evidence, "T")
    assert "Freshness" in ref or "freshness" in ref.lower()
    assert "D2" in ref
