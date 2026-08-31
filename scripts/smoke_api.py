"""Full API smoke test against a running uvicorn instance."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

BASE = os.getenv("SMOKE_BASE", "http://127.0.0.1:8010")
results: list[tuple[str, int | None, bool, str]] = []


def call(method: str, path: str, body=None, timeout: int = 120):
    data = None
    headers = {}
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode()
            try:
                payload = json.loads(raw) if raw else {}
            except Exception:
                payload = {"_raw": raw[:200]}
            return r.status, payload, None
    except urllib.error.HTTPError as e:
        err = e.read().decode()
        try:
            payload = json.loads(err)
        except Exception:
            payload = {"_raw": err[:400]}
        return e.code, payload, str(e)
    except Exception as e:
        return None, {}, str(e)


def record(name: str, status, ok_pred, detail: str = ""):
    passed = bool(ok_pred)
    results.append((name, status, passed, detail))
    mark = "PASS" if passed else "FAIL"
    line = f"{mark:4} {name}  status={status}  {detail}"
    print(line[:220])


def tool_id_from(p: dict) -> str | None:
    if not isinstance(p, dict):
        return None
    t = p.get("tool") if isinstance(p.get("tool"), dict) else p
    return (t or {}).get("tool_id") or p.get("tool_id")


def run_dashboard_gets(*, include_quality: bool = False) -> None:
    dash_paths = [
        "/api/v1/health",
        "/api/v1/filters",
        "/api/v1/overview",
        "/api/v1/overview/kpis",
        "/api/v1/pipelines",
        "/api/v1/pipelines/catalog",
        "/api/v1/connectors/types",
        "/api/v1/tools",
        "/api/v1/observability/freshness",
        "/api/v1/observability/volume",
        "/api/v1/incidents",
        "/api/v1/metrics",
        "/api/v1/logs",
        "/api/v1/alerts",
        "/api/v1/lineage",
        "/v1/dashboard/overview",
    ]
    if include_quality:
        dash_paths.insert(8, "/api/v1/observability/quality")
    for path in dash_paths:
        st, p, err = call("GET", path, timeout=90)
        record(f"GET {path}", st, st == 200, err or "")


def run_offline() -> None:
    subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "seed_demo_metadata.py")],
        check=True,
    )

    st, p, err = call("GET", "/")
    record("GET /", st, st == 200 and bool(p.get("service")), err or "")

    st, p, err = call("GET", "/health")
    record("GET /health", st, st == 200 and p.get("ok") is True, err or "")

    st, p, err = call("GET", "/api/v1/health")
    has_collectors = isinstance(p.get("collectors"), list)
    record(
        "GET /api/v1/health (collectors)",
        st,
        st == 200 and has_collectors,
        f"collectors={len(p.get('collectors') or [])} degraded={p.get('degraded')}",
    )

    run_dashboard_gets(include_quality=True)

    st, p, err = call("GET", "/api/v1/observability/quality")
    summary = p.get("summary") or {}
    record(
        "GET quality KPIs (seeded)",
        st,
        st == 200 and summary.get("available") is True and (summary.get("checks_run") or 0) >= 1,
        f"checks={summary.get('checks_run')} failed={summary.get('failed')}",
    )

    st, p, err = call("GET", "/api/v1/overview/health")
    pillars = {x.get("id"): x for x in (p.get("pillars") or p.get("health") or [])}
    dq = pillars.get("data_quality") or {}
    record(
        "GET overview DQ pillar (seeded)",
        st,
        st == 200 and dq.get("available") is True,
        f"score={dq.get('score')}",
    )
    uniq = pillars.get("uniqueness") or {}
    record(
        "GET overview uniqueness pillar (seeded)",
        st,
        st == 200 and uniq.get("available") is True,
        f"score={uniq.get('score')}",
    )

    st, p, err = call("GET", "/v1/monitors?pipeline_id=demo-pipeline-001")
    record(
        "GET /v1/monitors (seeded pipeline)",
        st,
        st == 200 and isinstance(p.get("items"), list),
        f"n={len(p.get('items') or [])}",
    )

    st, p, err = call("GET", "/api/v1/pipelines/demo-pipeline-001/monitors")
    record(
        "GET pipeline monitors (dashboard)",
        st,
        st == 200 and isinstance(p.get("items"), list),
        f"n={len(p.get('items') or [])}",
    )

    st, p, err = call("GET", "/v1/dq-rules?pipeline_id=demo-pipeline-001")
    record(
        "GET /v1/dq-rules (seeded pipeline)",
        st,
        st == 200 and isinstance(p.get("items"), list),
        f"n={len(p.get('items') or [])}",
    )

    st, p, err = call("GET", "/api/v1/lineage/demo-pipeline-001")
    ds_q = ((p.get("meta") or {}).get("dataset_quality") or [])
    record(
        "GET lineage detail dataset_quality",
        st,
        st == 200 and len(ds_q) >= 1,
        f"datasets={len(ds_q)}",
    )

    st, p, err = call("GET", "/api/v1/runs/demo-run-001/rca-context")
    record(
        "GET rca-context (seeded run)",
        st,
        st == 200 and bool((p.get("run") or p.get("meta", {}).get("run")) or p.get("ok")),
        err or str(list(p.keys())[:6]),
    )

    ol_fixture = ROOT / "scripts" / "fixtures" / "openlineage_complete.json"
    ol_payload = json.loads(ol_fixture.read_text(encoding="utf-8")) if ol_fixture.exists() else {
        "eventType": "COMPLETE",
        "run": {"runId": "smoke-ol-offline"},
        "job": {"namespace": "demo", "name": "load"},
        "inputs": [{"name": "DB.RAW.STG"}],
        "outputs": [{"name": "DB.MART.FCT"}],
    }
    st, p, err = call(
        "POST",
        "/webhooks/openlineage/demo_ecommerce_etl",
        ol_payload,
        timeout=60,
    )
    record(
        "POST /webhooks/openlineage (async 202)",
        st,
        st == 202 and p.get("accepted") is True,
        f"{str(p)[:100]}",
    )

    st, p, err = call(
        "POST",
        "/webhooks/dbt",
        {"eventType": "run.completed", "data": {"runId": "smoke-offline-0"}},
        timeout=10,
    )
    record(
        "POST /webhooks/dbt (async 202)",
        st,
        st == 202 and p.get("accepted") is True,
        f"{str(p)[:100]}",
    )


def run_live() -> None:
    st, p, err = call("GET", "/")
    record("GET /", st, st == 200 and bool(p.get("service")), err or "")

    st, p, err = call("GET", "/health")
    record("GET /health", st, st == 200 and p.get("ok") is True, err or "")

    st, p, err = call("GET", "/v1/tools/types")
    types = [i.get("id") for i in (p.get("items") or [])]
    record(
        "GET /v1/tools/types",
        st,
        st == 200 and "snowflake" in types and "dbt" in types,
        f"n={len(types)}",
    )

    st, p, err = call("GET", "/v1/tools")
    record("GET /v1/tools", st, st == 200 and "items" in p, err or "")

    sf_secret = os.getenv("SNOWFLAKE_PASSWORD") or "smoke-test-secret"
    dbt_secret = (
        os.getenv("ECOM_DBT_CLOUD_API_TOKEN")
        or os.getenv("DBT_CLOUD_API_TOKEN")
        or "smoke-dbt-token"
    )

    src_body = {
        "name": "smoke-sf-source",
        "connector_type": "snowflake",
        "kind": "database",
        "secret": sf_secret,
        "config": {
            "account_id": os.getenv("ECOM_SNOWFLAKE_ACCOUNT") or "dummy",
            "user_id": os.getenv("ECOM_SNOWFLAKE_USER") or "dummy",
            "warehouse_id": os.getenv("ECOM_SNOWFLAKE_WAREHOUSE") or "WH",
            "database_id": os.getenv("ECOM_SNOWFLAKE_DATABASE") or "DB",
            "schema": os.getenv("ECOM_SF_SOURCE_SCHEMA") or "SRC",
            "tables": [
                t.strip()
                for t in (os.getenv("ECOM_SF_SOURCE_TABLES") or "T1").split(",")
                if t.strip()
            ],
            "sf_role": os.getenv("ECOM_SNOWFLAKE_ROLE") or "ACCOUNTADMIN",
        },
    }
    st, p, err = call("POST", "/v1/tools", src_body)
    src_id = tool_id_from(p)
    has_secret = (p.get("tool") or p).get("has_secret") if isinstance(p, dict) else None
    record(
        "POST /v1/tools (snowflake source+secret)",
        st,
        st == 200 and bool(src_id),
        f"tool_id={src_id} has_secret={has_secret}",
    )

    tgt_body = {
        **src_body,
        "name": "smoke-sf-target",
        "config": {
            **src_body["config"],
            "schema": os.getenv("ECOM_SF_TARGET_SCHEMA") or "CLEAN",
            "tables": [
                t.strip()
                for t in (os.getenv("ECOM_SF_TARGET_TABLES") or "T2").split(",")
                if t.strip()
            ],
        },
    }
    st, p, err = call("POST", "/v1/tools", tgt_body)
    tgt_id = tool_id_from(p)
    record(
        "POST /v1/tools (snowflake target+secret)",
        st,
        st == 200 and bool(tgt_id),
        f"tool_id={tgt_id}",
    )

    etl_body = {
        "name": "smoke-dbt",
        "connector_type": "dbt",
        "kind": "etl",
        "secret": dbt_secret,
        "config": {
            "account_id": os.getenv("ECOM_DBT_ACCOUNT_ID") or "1",
            "project_id": os.getenv("ECOM_DBT_PROJECT_ID") or "1",
            "job_id": os.getenv("ECOM_DBT_JOB_ID") or "1",
            "project_name": os.getenv("ECOM_DBT_PROJECT_NAME") or "ecommerce",
            "api_base": os.getenv("ECOM_DBT_API_BASE") or "https://cloud.getdbt.com/api/v2",
        },
    }
    st, p, err = call("POST", "/v1/tools", etl_body)
    etl_id = tool_id_from(p)
    record(
        "POST /v1/tools (dbt+secret)",
        st,
        st == 200 and bool(etl_id),
        f"tool_id={etl_id}",
    )

    pipe_id = None
    pipe_name = "smoke_from_tools"

    if src_id:
        st, p, err = call("GET", f"/v1/tools/{src_id}")
        tool = p.get("tool") or {}
        cfg = tool.get("config") or {}
        no_pw = "password" not in cfg and "api_token" not in cfg
        record(
            "GET /v1/tools/{id} (no plaintext secret)",
            st,
            st == 200 and tool.get("has_secret") is True and no_pw,
            f"has_secret={tool.get('has_secret')}",
        )

        st, p, err = call("PUT", f"/v1/tools/{src_id}/secret", {"secret": sf_secret})
        record("PUT /v1/tools/{id}/secret", st, st == 200, str(p)[:100])

        st, p, err = call("POST", f"/v1/tools/{src_id}/test", timeout=90)
        result = p.get("result") if isinstance(p.get("result"), dict) else p
        live_ok = st == 200 and bool((result or {}).get("ok"))
        record(
            "POST /v1/tools/{id}/test (live snowflake)",
            st,
            live_ok,
            "connected" if live_ok else str(p)[:140],
        )

    if src_id and etl_id and tgt_id:
        st, p, err = call(
            "POST",
            "/v1/pipelines/from-tools",
            {
                "pipeline_name": pipe_name,
                "source_tool_id": src_id,
                "etl_tool_id": etl_id,
                "target_tool_id": tgt_id,
                "make_active": True,
                "description": "smoke test",
            },
        )
        pipe_id = (p.get("pipeline") or p).get("pipeline_id") if isinstance(p, dict) else None
        if not pipe_id:
            pipe_id = p.get("pipeline_id")
        record(
            "POST /v1/pipelines/from-tools",
            st,
            st == 200 and bool(pipe_id),
            f"pipeline_id={pipe_id} {str(p)[:100]}",
        )
    else:
        record("POST /v1/pipelines/from-tools", None, False, "skipped — missing tool ids")

    st, p, err = call("GET", "/v1/pipelines")
    record(
        "GET /v1/pipelines",
        st,
        st == 200 and isinstance(p.get("pipelines"), list),
        f"n={len(p.get('pipelines') or [])}",
    )

    st, p, err = call("GET", "/v1/pipelines/templates")
    record("GET /v1/pipelines/templates", st, st == 200, str(p)[:80])

    st, p, err = call("GET", "/v1/pipelines/current")
    record(
        "GET /v1/pipelines/current",
        st,
        st == 200 and bool(p.get("pipeline_id") or p.get("pipeline_name")),
        err or str(p)[:80],
    )

    st, p, err = call(
        "POST", "/v1/pipelines", {"pipeline_name": "ecommerce_etl", "make_active": False}
    )
    record(
        "POST /v1/pipelines (legacy template)",
        st,
        st in (200, 403),
        f"{str(p)[:100]}",
    )

    sync_body = {"pipeline_name": pipe_name, "refresh_db": False}
    if pipe_id:
        sync_body = {"pipeline_id": pipe_id, "refresh_db": False}
    st, p, err = call("POST", "/v1/sync", sync_body, timeout=180)
    sync_ok = st == 200 and (
        p.get("ok") is True
        or p.get("run_id")
        or p.get("obs_run_id")
        or "pipeline_id" in p
    )
    record(
        "POST /v1/sync (live)",
        st,
        sync_ok,
        str(p)[:140] if not sync_ok else f"keys={list(p)[:8]}",
    )

    run_dashboard_gets(include_quality=True)

    st, p, err = call(
        "POST",
        "/webhooks/dbt",
        {"eventType": "run.completed", "data": {"runId": "smoke-0"}},
        timeout=10,
    )
    record("POST /webhooks/dbt", st, st in (200, 202, 404, 422), f"{str(p)[:100]}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke test ETL observability API")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--offline", action="store_true", help="Seed demo data; skip live Sync/tool test")
    mode.add_argument("--live", action="store_true", help="Full live smoke (requires vendor creds)")
    args = parser.parse_args()

    print(f"BASE={BASE} mode={'offline' if args.offline else 'live'}\n")

    if args.offline:
        run_offline()
    else:
        run_live()

    passed = sum(1 for r in results if r[2])
    failed = [r for r in results if not r[2]]
    print()
    print(f"SUMMARY {passed}/{len(results)} passed")
    if failed:
        print("FAILED:")
        for name, status, _, detail in failed:
            print(f"  - {name} status={status} {detail}"[:220])
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
