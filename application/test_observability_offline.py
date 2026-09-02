"""
Offline observability unit tests (no dbt/Snowflake network).

Run from repo root:
  python application/test_observability_offline.py
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from application.src.connectors.dbt import DbtConnector  # noqa: E402
from application.src.connectors.snowflake import SnowflakeConnector  # noqa: E402
from application.src.connectors.openlineage import parse_openlineage_event  # noqa: E402
from application.src.connectors.validation import parse_dataset_fqn, quote_ident_pg  # noqa: E402
from application.src.connectors.errors import (  # noqa: E402
    classify_dbt_http_error,
    classify_snowflake_error,
    parse_dbt_runtime_error,
)
from application.src.services.observability.quality import (  # noqa: E402
    dataset_dq_map,
    dataset_status_key,
    dimension_pillar_summary,
    infer_dimension,
    quality_summary,
    quality_summary_by_dataset,
)
from application.src.services.observability.rca_context import build_rca_context  # noqa: E402
from application.src.services.observability.rca_deltas import (  # noqa: E402
    compute_schema_diffs,
    compute_volume_deltas,
)
from application.src.services.observability.lineage import build_lineage_detail  # noqa: E402
from application.src.services.observability.volume import _is_pipeline_volume_healthy  # noqa: E402
from application.src.store.meta_mysql import (  # noqa: E402
    delete_dq_rule,
    delete_monitor,
    ensure_tables,
    get_connection,
    get_dq_rule,
    get_monitor,
    list_dq_rules,
    list_monitors,
    resolve_pipeline_tool_groups,
    store_openlineage_event,
    upsert_dq_rule,
    upsert_monitor,
)
from application.src.sync_once import _merge_run_table_filters  # noqa: E402


class TestOfflineHelpers(unittest.TestCase):
    def test_merge_run_table_filters(self):
        out = _merge_run_table_filters(["ORDERS"], ["analytics.raw.stg_orders", "ORDERS"])
        self.assertEqual(out, ["ORDERS", "ANALYTICS.RAW.STG_ORDERS"])

    def test_volume_deltas(self):
        prev = [
            {"asset_role": "TARGET", "dataset_id": "ANALYTICS.MART.FCT_ORDERS", "row_count": 480000},
        ]
        cur = [
            {"asset_role": "TARGET", "dataset_id": "ANALYTICS.MART.FCT_ORDERS", "row_count": 495000},
        ]
        deltas = compute_volume_deltas(cur, prev)
        self.assertEqual(len(deltas), 1)
        self.assertEqual(deltas[0]["row_delta"], 15000)
        self.assertEqual(deltas[0]["status"], "changed")

    def test_schema_diffs(self):
        prev = [
            {
                "database_name": "ANALYTICS",
                "schema_name": "MART",
                "object_name": "FCT_ORDERS",
                "column_name": "ORDER_ID",
                "data_type": "NUMBER",
                "asset_role": "TARGET",
            }
        ]
        cur = list(prev) + [
            {
                "database_name": "ANALYTICS",
                "schema_name": "MART",
                "object_name": "FCT_ORDERS",
                "column_name": "STATUS",
                "data_type": "VARCHAR",
                "asset_role": "TARGET",
            }
        ]
        diffs = compute_schema_diffs(cur, prev)
        self.assertEqual(len(diffs), 1)
        self.assertEqual(diffs[0]["change_type"], "column_added")
        self.assertEqual(diffs[0]["column_name"], "STATUS")

    def test_snowflake_view_row_count_fallback(self):
        class FakeCursor:
            def __init__(self):
                self.last_sql = ""

            def execute(self, sql, params=None):
                self.last_sql = sql

            def fetchone(self):
                return (208,)

        conn = SnowflakeConnector.__new__(SnowflakeConnector)
        conn.database_id = "INVENTORY_DB"
        conn.cursor = FakeCursor()
        rows = [
            {
                "database": "INVENTORY_DB",
                "schema": "MART",
                "table": "DIM_INVENTORY",
                "table_type": "VIEW",
                "row_count": None,
            },
            {
                "database": "INVENTORY_DB",
                "schema": "MART",
                "table": "RAW_TABLE",
                "table_type": "BASE TABLE",
                "row_count": 100,
            },
        ]
        conn._fill_view_row_counts(rows)
        self.assertEqual(rows[0]["row_count"], 208)
        self.assertEqual(rows[1]["row_count"], 100)
        self.assertIn("COUNT(*)", conn.cursor.last_sql)

    def test_pipeline_volume_baseline_healthy(self):
        cases = [
            (5.0, 100, True, True, "normal stable"),
            (-50.0, 50, True, False, "real drop"),
            (None, 65, True, True, "baseline first run"),
            (None, 0, True, False, "baseline zero rows"),
            (None, 0, False, False, "missing current run"),
        ]
        for change, cur_records, had_current_run, expected, label in cases:
            with self.subTest(label=label):
                self.assertEqual(
                    _is_pipeline_volume_healthy(
                        change,
                        cur_records=cur_records,
                        had_current_run=had_current_run,
                    ),
                    expected,
                )

    def test_manifest_to_edges(self):
        manifest = {
            "nodes": {
                "model.demo.fct": {
                    "depends_on": ["model.demo.stg"],
                    "relation_name": "DB.SCHEMA.FCT",
                },
                "model.demo.stg": {"depends_on": [], "relation_name": "DB.SCHEMA.STG"},
            },
            "sources": {},
        }
        edges = DbtConnector.manifest_to_edges(manifest)
        self.assertEqual(len(edges), 1)
        self.assertEqual(edges[0]["from_dataset"], "DB.SCHEMA.STG")
        self.assertEqual(edges[0]["to_dataset"], "DB.SCHEMA.FCT")

    def test_classify_dbt_errors(self):
        err = classify_dbt_http_error("account locked", status_code=401)
        self.assertEqual(err["error_code"], "dbt_unauthorized")
        err2 = parse_dbt_runtime_error("dbt Cloud API 403: forbidden")
        self.assertEqual(err2["error_code"], "dbt_forbidden")

    def test_classify_snowflake_errors(self):
        err = classify_snowflake_error("390913: authentication failed")
        self.assertEqual(err["error_code"], "snowflake_auth_failed")

    def test_parse_dataset_fqn(self):
        db, schema, table = parse_dataset_fqn("analytics.mart.fct_orders")
        self.assertEqual((db, schema, table), ("analytics", "mart", "fct_orders"))
        self.assertIn('"ORDER_ID"', quote_ident_pg("ORDER_ID"))

    def test_openlineage_parser(self):
        payload = {
            "eventType": "COMPLETE",
            "run": {"runId": "ol-1"},
            "job": {"namespace": "demo", "name": "job"},
            "inputs": [{"namespace": "snowflake://x", "name": "DB.RAW.STG"}],
            "outputs": [{"namespace": "snowflake://x", "name": "DB.MART.FCT"}],
        }
        parsed = parse_openlineage_event(payload)
        self.assertEqual(parsed["event_type"], "COMPLETE")
        self.assertEqual(len(parsed["edges"]), 1)
        self.assertEqual(parsed["edges"][0]["edge_kind"], "openlineage")


class TestSeededMetadata(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from scripts.seed_demo_metadata import seed

        seed()

    def test_quality_summary(self):
        conn = get_connection()
        try:
            ensure_tables(conn)
            summary = quality_summary(conn, pipeline_id="demo-pipeline-001", source="dbt")
            self.assertTrue(summary.get("available"))
            self.assertEqual(summary.get("checks_run"), 4)
            self.assertEqual(summary.get("failed"), 1)

            last_run = quality_summary(
                conn,
                pipeline_id="demo-pipeline-001",
                score_mode="last_run",
                source="dbt",
            )
            self.assertEqual(last_run.get("checks_run"), 4)
            self.assertEqual(last_run.get("dbt_checks"), 4)
            self.assertEqual(last_run.get("monitor_checks"), 0)

            ds = quality_summary_by_dataset(
                conn,
                pipeline_id="demo-pipeline-001",
                dataset_id="ANALYTICS.MART.FCT_ORDERS",
            )
            self.assertTrue(ds.get("available"))
            self.assertEqual(ds.get("checks_run"), 4)
            self.assertEqual(ds.get("status_key"), "bad")
            self.assertEqual(len(ds.get("alerting_checks") or []), 2)
        finally:
            conn.close()

    def test_infer_dimension(self):
        self.assertEqual(infer_dimension(message="not_null on order_id"), "completeness")
        self.assertEqual(infer_dimension(message="unique on order_id"), "uniqueness")
        self.assertEqual(dataset_status_key(passed=2, warn=1, failed=0), "degraded")
        self.assertEqual(dataset_status_key(passed=2, warn=0, failed=1), "bad")

    def test_dimension_pillars_and_dataset_map(self):
        conn = get_connection()
        try:
            ensure_tables(conn)
            uniq = dimension_pillar_summary(
                conn,
                pipeline_id="demo-pipeline-001",
                dimensions=["uniqueness"],
                score_mode="last_run",
            )
            self.assertTrue(uniq.get("available"))
            self.assertEqual(uniq.get("checks_run"), 1)
            self.assertEqual(uniq.get("passed"), 1)

            dq_map = dataset_dq_map(conn, pipeline_id="demo-pipeline-001")
            fct = dq_map.get("ANALYTICS.MART.FCT_ORDERS") or {}
            self.assertEqual(fct.get("status_key"), "bad")
            self.assertEqual(fct.get("data_quality_display"), "1 failed test(s)")
        finally:
            conn.close()

    def test_monitor_crud(self):
        conn = get_connection()
        try:
            ensure_tables(conn)
            mid = upsert_monitor(
                conn,
                {
                    "pipeline_id": "demo-pipeline-001",
                    "monitor_kind": "null_check",
                    "name": "Demo null check",
                    "dataset_id": "ANALYTICS.MART.FCT_ORDERS",
                    "column_name": "ORDER_ID",
                    "config": {"expected_max": 0},
                    "tags": ["team:demo"],
                },
            )
            item = get_monitor(conn, mid)
            self.assertIsNotNone(item)
            self.assertEqual(item.get("monitor_kind"), "null_check")
            items = list_monitors(conn, pipeline_id="demo-pipeline-001")
            self.assertTrue(any(i.get("monitor_id") == mid for i in items))
            self.assertTrue(delete_monitor(conn, mid))
            disabled = get_monitor(conn, mid)
            self.assertFalse(disabled.get("is_enabled"))
        finally:
            conn.close()

    def test_dq_rule_crud(self):
        conn = get_connection()
        try:
            ensure_tables(conn)
            rid = upsert_dq_rule(
                conn,
                {
                    "pipeline_id": "demo-pipeline-001",
                    "rule_type": "NOT_NULL",
                    "rule_name": "Demo not null",
                    "dataset_id": "ANALYTICS.MART.FCT_ORDERS",
                    "column_name": "ORDER_ID",
                    "config": {"expected_max": 0},
                    "tags": ["team:demo"],
                },
            )
            item = get_dq_rule(conn, rid)
            self.assertIsNotNone(item)
            self.assertEqual(item.get("rule_type"), "NOT_NULL")
            items = list_dq_rules(conn, pipeline_id="demo-pipeline-001")
            self.assertTrue(any(i.get("rule_id") == rid for i in items))
            self.assertTrue(delete_dq_rule(conn, rid))
        finally:
            conn.close()

    def test_openlineage_store(self):
        conn = get_connection()
        try:
            ensure_tables(conn)
            payload = {
                "eventType": "COMPLETE",
                "run": {"runId": "ol-demo-001"},
                "job": {"namespace": "demo", "name": "load"},
                "inputs": [{"name": "ANALYTICS.RAW.STG_ORDERS"}],
                "outputs": [{"name": "ANALYTICS.MART.FCT_ORDERS"}],
            }
            result = store_openlineage_event(
                conn, payload=payload, pipeline_id="demo-pipeline-001"
            )
            self.assertTrue(result.get("ok"))
            self.assertGreaterEqual(result.get("edges_stored") or 0, 1)
        finally:
            conn.close()

    def test_resolve_pipeline_tool_groups(self):
        groups = resolve_pipeline_tool_groups("demo-pipeline-001")
        if groups:
            self.assertGreaterEqual(len(groups.get("SOURCE") or []), 1)
            self.assertGreaterEqual(len(groups.get("TARGET") or []), 1)

    def test_lineage_dataset_quality(self):
        conn = get_connection()
        try:
            ensure_tables(conn)
            detail = build_lineage_detail(conn, "demo-pipeline-001")
            dq_rows = (detail.get("meta") or {}).get("dataset_quality") or []
            self.assertGreaterEqual(len(dq_rows), 1)
            self.assertEqual(dq_rows[0].get("status_key"), "bad")
        finally:
            conn.close()

    def test_rca_context(self):
        conn = get_connection()
        try:
            ensure_tables(conn)
            ctx = build_rca_context(conn, "demo-run-001")
            self.assertTrue(ctx.get("ok"))
            self.assertIn("run", ctx)
            self.assertGreaterEqual(len(ctx.get("dbt_tests") or []), 1)
            self.assertIn("dq_checks", ctx)
            self.assertGreaterEqual(len(ctx.get("dq_checks") or []), 1)
            self.assertIn("lineage_upstream", ctx)
            self.assertIn("lineage_downstream", ctx)
            self.assertIn("change_since_last_success", ctx)
            change = ctx.get("change_since_last_success") or {}
            if change.get("available"):
                self.assertGreaterEqual(change.get("volume_changes", 0), 1)
            summary = ctx.get("summary") or {}
            self.assertIn("dq_check_count", summary)
            self.assertIn("compiled_sql_nodes", summary)
        finally:
            conn.close()


def main() -> int:
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
