"""
Shared Sync-once path used by webhook API and manual trigger.

Prefers tools/bindings when present:
  - ETL: always pull per pipeline run
  - DB: reuse tool-wise snapshots within TTL, else pull + upsert snapshots
Falls back to classic config_json Snowflake+dbt path.
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]


def _load_module(module_name: str, relative: str):
    path = ROOT / relative
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _normalize_tables(raw: Any) -> list[str]:
    if not raw:
        return []
    if isinstance(raw, str):
        return [p.strip().upper() for p in raw.split(",") if p.strip()]
    if isinstance(raw, (list, tuple)):
        return [str(p).strip().upper() for p in raw if str(p).strip()]
    return []


def _resolve_table_filter(
    configured: list[str],
    dbt_relation_names: list[str],
) -> list[str]:
    """Legacy: prefer configured tables; fall back to dbt relation short names."""
    if configured:
        return configured
    return list(dbt_relation_names or [])


def _merge_run_table_filters(
    configured: list[str],
    dbt_relation_names: list[str],
) -> list[str]:
    """Union pipeline-config tables with all dbt relations from the run (production RCA scope)."""
    merged: list[str] = []
    seen: set[str] = set()
    for name in list(configured or []) + list(dbt_relation_names or []):
        key = str(name).strip().upper()
        if key and key not in seen:
            seen.add(key)
            merged.append(key)
    return merged


def _dbt_run_extras(
    dbt: Any, run_id: str, *, failed_nodes: list | None = None
) -> tuple[list[dict], list[dict], dict[str, str]]:
    """Pull dbt test results, manifest lineage edges, compiled SQL for failed nodes."""
    tests: list[dict] = []
    edges: list[dict] = []
    compiled: dict[str, str] = {}
    try:
        if hasattr(dbt, "fetch_test_results"):
            tests = dbt.fetch_test_results(run_id) or []
    except Exception as exc:
        print("WARN dbt test results:", exc)
    try:
        if hasattr(dbt, "fetch_manifest_edges"):
            edges = dbt.fetch_manifest_edges(run_id) or []
    except Exception as exc:
        print("WARN dbt manifest edges:", exc)
    try:
        node_ids: list[str] = []
        for node in failed_nodes or []:
            if isinstance(node, dict):
                uid = node.get("unique_id") or node.get("node")
                if uid:
                    node_ids.append(str(uid))
            elif node:
                node_ids.append(str(node))
        if node_ids and hasattr(dbt, "fetch_compiled_sql_for_nodes"):
            compiled = dbt.fetch_compiled_sql_for_nodes(run_id, node_ids) or {}
    except Exception as exc:
        print("WARN dbt compiled sql:", exc)
    return tests, edges, compiled


def _enrich_failed_nodes_with_compiled(
    failed_nodes: list | dict | None, compiled: dict[str, str]
) -> list[dict]:
    if not compiled:
        return list(failed_nodes or []) if isinstance(failed_nodes, list) else []
    nodes = list(failed_nodes or []) if isinstance(failed_nodes, list) else []
    out: list[dict] = []
    for node in nodes:
        if not isinstance(node, dict):
            out.append(node)
            continue
        enriched = dict(node)
        uid = str(enriched.get("unique_id") or enriched.get("node") or "")
        if uid and uid in compiled:
            enriched["compiled_sql"] = compiled[uid]
        out.append(enriched)
    return out


def _run_hours_back(run_log: dict, *, default: int = 48, max_hours: int = 168) -> int:
    from datetime import datetime

    start = run_log.get("start_time") or run_log.get("end_time")
    end = run_log.get("end_time") or run_log.get("start_time")
    if not start:
        return default
    try:
        if isinstance(start, str):
            start_dt = datetime.fromisoformat(str(start).replace("Z", "+00:00"))
        else:
            start_dt = start
        if isinstance(end, str):
            end_dt = datetime.fromisoformat(str(end).replace("Z", "+00:00"))
        else:
            end_dt = end or start_dt
        if end_dt.tzinfo:
            end_dt = end_dt.replace(tzinfo=None)
        if start_dt.tzinfo:
            start_dt = start_dt.replace(tzinfo=None)
        span = max(1, int((end_dt - start_dt).total_seconds() // 3600) + 2)
        return min(max_hours, max(default, span))
    except Exception:
        return default


def _should_fetch_query_history(run_log: dict, dbt_tests: list[dict]) -> bool:
    st = str(run_log.get("status") or "").lower()
    if st in {"failed", "error"}:
        return True
    if st in {"success", "succeeded"}:
        for t in dbt_tests or []:
            if str(t.get("status") or "").lower() in {"fail", "failed", "error"}:
                return True
    return False


def _collect_query_history(
    target_tools: list[dict],
    *,
    tenant_id: str,
    run_log: dict,
    dbt_tests: list[dict],
) -> list[dict]:
    if not _should_fetch_query_history(run_log, dbt_tests):
        return []
    from application.src.connectors.registry import get_connector

    hours = _run_hours_back(run_log)
    errors_only = str(run_log.get("status") or "").lower() in {"failed", "error"}
    query_history: list[dict] = []
    for target_tool in target_tools:
        try:
            tgt_kwargs = connector_kwargs_from_tool(target_tool, tenant_id=tenant_id)
            tgt_conn = get_connector(
                target_tool.get("connector_type") or "snowflake", **tgt_kwargs
            )
            if hasattr(tgt_conn, "fetch_query_history"):
                qh = (
                    tgt_conn.fetch_query_history(
                        hours_back=hours, limit=25, errors_only=errors_only
                    )
                    or []
                )
                query_history.extend(qh)
        except Exception as exc:
            print("WARN query history:", exc)
    return query_history


def _pipeline_has_source(pipe: dict | None) -> bool:
    if not pipe:
        return False
    source = pipe.get("source") or {}
    return bool(
        source.get("account_id")
        or source.get("host")
        or source.get("connector_instance_id")
        or source.get("database_id")
    )


def _resolve_pipeline(
    *,
    pipeline_id: str | None = None,
    pipeline_name: str | None = None,
) -> dict[str, Any]:
    """Prefer DB row; create template only if DB has no matching pipeline yet."""
    store_mod = _load_module("app_meta_mysql", "application/src/store/meta_mysql.py")
    pipe_mod = _load_module("app_pipelines", "application/src/pipelines.py")

    if pipeline_id:
        found = store_mod.get_pipeline_by_id(pipeline_id)
        if found and _pipeline_has_source(found):
            return found
        template = pipe_mod.get_pipeline_template(
            pipeline_name, pipeline_id=pipeline_id
        )
        if pipeline_name:
            template["pipeline_name"] = pipeline_name
        return template

    if pipeline_name:
        found = store_mod.get_pipeline_by_name(pipeline_name)
        if found and _pipeline_has_source(found):
            return found
        template = pipe_mod.get_pipeline_template(pipeline_name)
        store_mod.upsert_pipeline(template, make_active=False)
        return template

    active = store_mod.get_active_pipeline()
    if active and _pipeline_has_source(active):
        return active

    template = pipe_mod.get_stock_etl_pipeline()
    store_mod.upsert_pipeline(template, make_active=True)
    return template


def _resolve_dbt_token(etl_cfg: dict) -> str | None:
    if etl_cfg.get("api_token"):
        return str(etl_cfg["api_token"])
    env_name = (etl_cfg.get("api_token_env") or "DBT_CLOUD_API_TOKEN").strip()
    return os.getenv(env_name) or os.getenv("DBT_CLOUD_API_TOKEN") or None


def _resolve_db_password(cfg: dict) -> str | None:
    if cfg.get("password"):
        return str(cfg["password"])
    env_name = (cfg.get("password_env") or "").strip()
    if env_name:
        return os.getenv(env_name) or None
    return os.getenv("SNOWFLAKE_PASSWORD") or os.getenv("MYSQL_PASSWORD") or None


def _resolve_tool_secret(tool: dict) -> str | None:
    """Prefer encrypted DB secret; fall back to auth_ref / env (legacy)."""
    from application.src.store.meta_mysql import get_decrypted_tool_secret

    iid = str(tool.get("tool_id") or tool.get("instance_id") or "")
    if iid:
        try:
            secret = get_decrypted_tool_secret(iid)
            if secret:
                return secret
        except Exception as exc:
            print("WARN decrypt tool secret:", exc)
    # Legacy env pointer
    auth_ref = (tool.get("auth_ref") or "").strip()
    if auth_ref:
        return os.getenv(auth_ref) or None
    return None


def store_payload(
    run_log: dict,
    source_rows: list[dict],
    target_rows: list[dict],
    pipeline: dict | None = None,
    columns: list[dict] | None = None,
    query_history: list[dict] | None = None,
    dbt_test_results: list[dict] | None = None,
    lineage_edges: list[dict] | None = None,
) -> dict:
    """Persist transformed payloads into Metadata MySQL."""
    store_mod = _load_module("app_meta_mysql", "application/src/store/meta_mysql.py")
    result = store_mod.store_to_meta_mysql(
        run_log,
        source_rows,
        target_rows,
        pipeline=pipeline,
        columns=columns,
        query_history=query_history,
        dbt_test_results=dbt_test_results,
        lineage_edges=lineage_edges,
    )
    print(
        "STORE MySQL ok=",
        result.get("ok"),
        "run=",
        result.get("run_id"),
        "sources=",
        result.get("sources_stored"),
        "targets=",
        result.get("targets_stored"),
        "columns=",
        result.get("columns_stored"),
        "qh=",
        result.get("query_history_stored"),
        "tables=",
        result.get("tables"),
    )
    return result


def connector_kwargs_from_tool(tool: dict, *, tenant_id: str) -> dict[str, Any]:
    cfg = dict(tool.get("config") or {})
    ctype = (tool.get("connector_type") or "").strip().lower()
    iid = tool.get("tool_id") or tool.get("instance_id") or "tool"
    base: dict[str, Any] = {
        "tenant_id": tenant_id,
        "connector_instance_id": str(iid),
    }
    db_secret = _resolve_tool_secret(tool)
    if ctype in {"snowflake", "snowflake_lab"}:
        return {
            **base,
            "account_id": cfg.get("account_id") or "",
            "user_id": cfg.get("user_id") or "",
            "warehouse_id": cfg.get("warehouse_id") or "",
            "database_id": cfg.get("database_id") or "",
            "role": cfg.get("sf_role") or cfg.get("role") or "ACCOUNTADMIN",
            "schema": cfg.get("schema") or "",
            "tables": _normalize_tables(cfg.get("tables")) or None,
            "password": db_secret
            or _resolve_db_password({**cfg, "password_env": tool.get("auth_ref")}),
        }
    if ctype in {"mysql", "mysql_lab"}:
        return {
            **base,
            "host": cfg.get("host") or "127.0.0.1",
            "port": int(cfg.get("port") or 3306),
            "user": cfg.get("user") or cfg.get("user_id") or "root",
            "database": cfg.get("database") or cfg.get("database_id") or "",
            "schema": cfg.get("schema") or "",
            "password": db_secret
            or _resolve_db_password(
                {**cfg, "password_env": tool.get("auth_ref") or "MYSQL_PASSWORD"}
            ),
        }
    if ctype in {"postgres", "postgresql"}:
        return {
            **base,
            "host": cfg.get("host") or "127.0.0.1",
            "port": int(cfg.get("port") or 5432),
            "user": cfg.get("user") or cfg.get("user_id") or "postgres",
            "database": cfg.get("database") or cfg.get("database_id") or "",
            "schema": cfg.get("schema") or "public",
            "tables": _normalize_tables(cfg.get("tables")) or None,
            "password": db_secret
            or _resolve_db_password(
                {**cfg, "password_env": tool.get("auth_ref") or "POSTGRES_PASSWORD"}
            ),
        }
    if ctype in {"redshift"}:
        return {
            **base,
            "host": cfg.get("host") or "",
            "port": int(cfg.get("port") or 5439),
            "user": cfg.get("user") or cfg.get("user_id") or "",
            "database": cfg.get("database") or cfg.get("database_id") or "",
            "schema": cfg.get("schema") or "public",
            "tables": _normalize_tables(cfg.get("tables")) or None,
            "password": db_secret
            or _resolve_db_password(
                {**cfg, "password_env": tool.get("auth_ref") or "REDSHIFT_PASSWORD"}
            ),
        }
    if ctype in {"bigquery", "bq"}:
        return {
            **base,
            "project_id": cfg.get("project_id") or cfg.get("database_id") or "",
            "dataset": cfg.get("dataset") or cfg.get("schema") or "",
            "location": cfg.get("location") or "US",
            "credentials_path": cfg.get("credentials_path")
            or os.getenv("GOOGLE_APPLICATION_CREDENTIALS"),
            "tables": _normalize_tables(cfg.get("tables")) or None,
            # For BQ, secret may be JSON key material written to a temp path later;
            # credentials_path in config remains supported.
        }
    if ctype in {"dbt", "dbt_cloud"}:
        return {
            **base,
            "account_id": str(cfg.get("account_id") or ""),
            "project_id": str(cfg.get("project_id") or ""),
            "job_id": str(cfg.get("job_id") or ""),
            "project_name": cfg.get("project_name") or "analytics",
            "api_base": cfg.get("api_base") or "https://cloud.getdbt.com/api/v2",
            "api_token": db_secret
            or _resolve_dbt_token(
                {**cfg, "api_token_env": tool.get("auth_ref") or cfg.get("api_token_env")}
            ),
        }
    if ctype in {"airflow"}:
        return {
            **base,
            "base_url": cfg.get("base_url") or cfg.get("api_base") or "",
            "username": cfg.get("username") or os.getenv("AIRFLOW_USERNAME"),
            "password": db_secret
            or _resolve_db_password(
                {**cfg, "password_env": tool.get("auth_ref") or "AIRFLOW_PASSWORD"}
            ),
            "token": db_secret
            if tool.get("auth_ref") in {None, "", "AIRFLOW_TOKEN"}
            and db_secret
            else (
                os.getenv(tool.get("auth_ref") or "AIRFLOW_TOKEN")
                if tool.get("auth_ref")
                else os.getenv("AIRFLOW_TOKEN")
            ),
            "dag_id": cfg.get("dag_id") or "",
        }
    if ctype in {"airbyte"}:
        return {
            **base,
            "base_url": cfg.get("base_url") or cfg.get("api_base") or "",
            "username": cfg.get("username") or os.getenv("AIRBYTE_USERNAME"),
            "password": db_secret
            or _resolve_db_password(
                {**cfg, "password_env": tool.get("auth_ref") or "AIRBYTE_PASSWORD"}
            ),
            "client_id": cfg.get("client_id") or os.getenv("AIRBYTE_CLIENT_ID"),
            "client_secret": db_secret
            or os.getenv(tool.get("auth_ref") or "AIRBYTE_CLIENT_SECRET")
            or os.getenv("AIRBYTE_CLIENT_SECRET"),
            "connection_id": cfg.get("connection_id") or "",
            "workspace_id": cfg.get("workspace_id") or "",
        }
    raise ValueError(f"Unsupported connector_type={ctype!r}")


# Back-compat alias
_connector_kwargs_from_tool = connector_kwargs_from_tool


def _col_counts(cols: list[dict]) -> dict[str, int]:
    out: dict[str, int] = {}
    for c in cols:
        key = (c.get("dataset_id") or "").upper()
        if not key:
            key = (f"{c.get('database')}.{c.get('schema')}.{c.get('table')}").upper()
        out[key] = out.get(key, 0) + 1
    return out


def _collect_db_side(
    *,
    tool: dict,
    asset_role: str,
    table_filter: list[str],
    tenant_id: str,
    map_ds_mod: Any,
    run_id: str,
    force_refresh: bool = False,
) -> tuple[list[dict], list[dict], dict[str, Any]]:
    """
    Collect SOURCE/TARGET assets for a DB tool.
    Reuses tool-wise snapshots when fresh; otherwise pulls and upserts snapshots.
    """
    from application.src.connectors.registry import get_connector
    from application.src.store import meta_mysql as store_mod

    iid = str(tool.get("tool_id") or tool.get("instance_id"))
    meta: dict[str, Any] = {"instance_id": iid, "reused": False}

    if not force_refresh:
        snaps = store_mod.get_fresh_tool_snapshots(iid, asset_role=asset_role)
        if snaps:
            rows: list[dict] = []
            cols: list[dict] = []
            for snap in snaps:
                payload = dict(snap.get("payload") or {})
                # Ensure mapped shape for store
                if not payload.get("dataset_id") and snap.get("dataset_id"):
                    payload["dataset_id"] = snap["dataset_id"]
                payload["run_id"] = run_id
                payload["asset_role"] = asset_role
                rows.append(payload)
                for c in snap.get("columns") or []:
                    cols.append({**c, "asset_role": asset_role})
            meta["reused"] = True
            meta["snapshot_count"] = len(snaps)
            return rows, cols, meta

    ctype = (tool.get("connector_type") or "snowflake").strip().lower()
    kwargs = connector_kwargs_from_tool(tool, tenant_id=tenant_id)
    if table_filter:
        kwargs["tables"] = table_filter
    connector = get_connector(ctype, **kwargs)
    envs = connector.pull_state() or []
    cols_raw: list[dict] = []
    try:
        if hasattr(connector, "fetch_columns"):
            cols_raw = connector.fetch_columns(table_filter or None) or []
    except Exception as exc:
        print(f"WARN {asset_role} columns:", exc)

    counts = _col_counts(cols_raw)
    rows = []
    assets_for_snap: list[dict] = []
    cols_by_ds: dict[str, list[dict]] = {}
    for env in envs:
        ds = map_ds_mod.map_dataset(env, run_id=run_id, asset_role=asset_role)
        did = (ds.get("dataset_id") or "").upper()
        if did in counts:
            ds["column_count"] = counts[did]
        rows.append(ds)
        assets_for_snap.append(ds)
        cols_by_ds[did] = [
            c
            for c in cols_raw
            if (c.get("dataset_id") or "").upper() == did
            or (
                f"{c.get('database')}.{c.get('schema')}.{c.get('table')}"
            ).upper()
            == did
        ]

    try:
        store_mod.upsert_tool_snapshots(
            iid,
            asset_role=asset_role,
            assets=assets_for_snap,
            columns_by_dataset=cols_by_ds,
        )
    except Exception as exc:
        print("WARN upsert_tool_snapshots:", exc)

    columns_rows = [{**c, "asset_role": asset_role} for c in cols_raw]
    meta["reused"] = False
    meta["pulled"] = len(rows)
    return rows, columns_rows, meta


def run_sync_once(
    *,
    pipeline_id: str | None = None,
    pipeline_name: str | None = None,
    dbt_run_id: str | None = None,
    refresh_db: bool = False,
) -> dict[str, Any]:
    """
    Load pipeline → prefer bindings/tools → ETL always fresh → DB snapshot reuse → store.
    """
    map_run_mod = _load_module("app_map_run", "application/src/transform/map_run.py")
    map_ds_mod = _load_module(
        "app_map_dataset", "application/src/transform/map_dataset.py"
    )
    dbt_mod = _load_module("app_dbt", "application/src/connectors/dbt.py")
    store_mod = _load_module("app_meta_mysql", "application/src/store/meta_mysql.py")

    pipeline = _resolve_pipeline(pipeline_id=pipeline_id, pipeline_name=pipeline_name)
    pid = str(pipeline.get("pipeline_id") or "")
    tenant_id = pipeline.get("tenant_id") or "demo"

    tools = None
    tool_groups = None
    try:
        tool_groups = store_mod.resolve_pipeline_tool_groups(pid) if pid else None
        tools = store_mod.resolve_pipeline_tools(pid) if pid else None
    except Exception as exc:
        print("WARN resolve_pipeline_tools:", exc)

    db_reuse_meta: dict[str, Any] = {}

    if tool_groups:
        from application.src.connectors.registry import get_connector

        etl_tool = tool_groups["ETL"][0]
        source_tools = tool_groups["SOURCE"]
        target_tools = tool_groups["TARGET"]

        etl_kwargs = connector_kwargs_from_tool(etl_tool, tenant_id=tenant_id)
        dbt = get_connector(etl_tool.get("connector_type") or "dbt", **etl_kwargs)

        etl_envs = dbt.pull_state()
        if not etl_envs:
            return {
                "ok": False,
                "message": f"No runs found for ETL tool ({etl_tool.get('connector_type')})",
                "stored": False,
            }

        chosen = etl_envs[0]
        if dbt_run_id:
            matched = None
            for env in etl_envs:
                raw = env.get("raw") or {}
                rid = raw.get("run_id") or raw.get("id")
                if str(rid) == str(dbt_run_id):
                    matched = env
                    break
            if matched is None:
                raise ValueError(
                    f"run_id={dbt_run_id} not found in recent job runs. "
                    "Refusing to fall back to latest run."
                )
            chosen = matched

        chosen_raw = chosen.get("raw") or {}
        dbt_table_names = dbt_mod.relation_short_names(chosen_raw.get("relations") or [])

        run_log = map_run_mod.map_run(
            chosen,
            pipeline_id=pid,
            pipeline_name=pipeline.get("pipeline_name") or "composed",
        )
        run_id = run_log["id"]
        failed_nodes_raw = run_log.get("failed_nodes") or []
        dbt_tests, lineage_edges, compiled_sql = _dbt_run_extras(
            dbt, str(run_id), failed_nodes=failed_nodes_raw
        )
        enriched_nodes = _enrich_failed_nodes_with_compiled(failed_nodes_raw, compiled_sql)
        run_log["failed_nodes"] = enriched_nodes
        run_log["failed_nodes_json"] = __import__("json").dumps(enriched_nodes, default=str)
        if compiled_sql:
            run_log["compiled_sql"] = compiled_sql

        source_rows: list[dict] = []
        source_cols: list[dict] = []
        target_rows: list[dict] = []
        target_cols: list[dict] = []
        src_metas: list[dict] = []
        tgt_metas: list[dict] = []

        for source_tool in source_tools:
            binding = source_tool.get("_binding") or {}
            selector = binding.get("asset_selector_json") or {}
            if isinstance(selector, str):
                try:
                    import json as _json
                    selector = _json.loads(selector)
                except Exception:
                    selector = {}
            cfg_tables = _normalize_tables((source_tool.get("config") or {}).get("tables"))
            sel_tables = _normalize_tables(selector.get("tables"))
            source_tables = _merge_run_table_filters(sel_tables or cfg_tables, dbt_table_names)
            rows, cols, meta = _collect_db_side(
                tool=source_tool,
                asset_role="SOURCE",
                table_filter=source_tables,
                tenant_id=tenant_id,
                map_ds_mod=map_ds_mod,
                run_id=run_id,
                force_refresh=refresh_db,
            )
            source_rows.extend(rows)
            source_cols.extend(cols)
            src_metas.append({"tool": source_tool.get("name"), **meta})

        for target_tool in target_tools:
            binding = target_tool.get("_binding") or {}
            selector = binding.get("asset_selector_json") or {}
            if isinstance(selector, str):
                try:
                    import json as _json
                    selector = _json.loads(selector)
                except Exception:
                    selector = {}
            cfg_tables = _normalize_tables((target_tool.get("config") or {}).get("tables"))
            sel_tables = _normalize_tables(selector.get("tables"))
            target_tables = _merge_run_table_filters(sel_tables or cfg_tables, dbt_table_names)
            rows, cols, meta = _collect_db_side(
                tool=target_tool,
                asset_role="TARGET",
                table_filter=target_tables,
                tenant_id=tenant_id,
                map_ds_mod=map_ds_mod,
                run_id=run_id,
                force_refresh=refresh_db,
            )
            target_rows.extend(rows)
            target_cols.extend(cols)
            tgt_metas.append({"tool": target_tool.get("name"), **meta})

        db_reuse_meta = {"sources": src_metas, "targets": tgt_metas}

        columns_rows = list(source_cols) + list(target_cols)
        src_total = sum(int(r.get("row_count") or 0) for r in source_rows)
        tgt_total = sum(int(r.get("row_count") or 0) for r in target_rows)
        if source_rows:
            run_log["rows_read"] = src_total
        if target_rows:
            run_log["rows_written"] = tgt_total

        query_history = _collect_query_history(
            target_tools,
            tenant_id=tenant_id,
            run_log=run_log,
            dbt_tests=dbt_tests,
        )

        store_result = store_payload(
            run_log,
            source_rows,
            target_rows,
            pipeline=pipeline,
            columns=columns_rows,
            query_history=query_history,
            dbt_test_results=dbt_tests,
            lineage_edges=lineage_edges,
        )

        return {
            "ok": True,
            "message": "Sync completed (tools/bindings)",
            "pipeline_id": pid,
            "pipeline_name": pipeline.get("pipeline_name"),
            "pipeline_from": "obs_pipeline_bindings",
            "db_snapshots": db_reuse_meta,
            "attachments": {
                "sources": [t.get("name") for t in source_tools],
                "etl": etl_tool.get("name"),
                "targets": [t.get("name") for t in target_tools],
            },
            "source_count": len(source_rows),
            "target_count": len(target_rows),
            "dbt_relations": dbt_table_names,
            "dbt_tests_stored": len(dbt_tests),
            "lineage_edges_stored": len(lineage_edges),
            "run_id": run_id,
            "status": run_log.get("status"),
            "rows_read": run_log.get("rows_read"),
            "rows_written": run_log.get("rows_written"),
            "stored": True,
            "store": store_result,
        }

    # ----- Classic config_json path (Snowflake + dbt) -----
    sf_mod = _load_module("app_snowflake", "application/src/connectors/snowflake.py")
    source_cfg = pipeline["source"]
    etl_cfg = pipeline["etl"]
    target_cfg = pipeline["target"]

    dbt = dbt_mod.DbtConnector(
        tenant_id=tenant_id,
        connector_instance_id=etl_cfg["connector_instance_id"],
        account_id=etl_cfg["account_id"],
        project_id=etl_cfg.get("project_id") or "",
        job_id=etl_cfg.get("job_id") or "",
        project_name=etl_cfg.get("project_name") or "analytics",
        api_base=etl_cfg.get("api_base") or "https://li589.us1.dbt.com/api/v2",
        api_token=_resolve_dbt_token(etl_cfg),
    )

    dbt_envs = dbt.pull_state()
    if not dbt_envs:
        return {"ok": False, "message": "No dbt runs found", "stored": False}

    chosen = dbt_envs[0]
    if dbt_run_id:
        matched = None
        for env in dbt_envs:
            raw = env.get("raw") or {}
            rid = raw.get("run_id") or raw.get("id")
            if str(rid) == str(dbt_run_id):
                matched = env
                break
        if matched is None:
            raise ValueError(
                f"dbt run_id={dbt_run_id} not found in recent job runs. "
                "Refusing to fall back to latest run."
            )
        chosen = matched

    chosen_raw = chosen.get("raw") or {}
    dbt_table_names = dbt_mod.relation_short_names(chosen_raw.get("relations") or [])
    source_tables = _merge_run_table_filters(
        _normalize_tables(source_cfg.get("tables")),
        dbt_table_names,
    )
    target_tables = _merge_run_table_filters(
        _normalize_tables(target_cfg.get("tables")),
        dbt_table_names,
    )

    dbt_tests, lineage_edges, compiled_sql = _dbt_run_extras(
        dbt,
        str(chosen_raw.get("run_id") or ""),
        failed_nodes=chosen_raw.get("failed_nodes") or [],
    )

    sf_source = sf_mod.SnowflakeConnector(
        tenant_id=tenant_id,
        connector_instance_id=source_cfg["connector_instance_id"],
        account_id=source_cfg["account_id"],
        user_id=source_cfg["user_id"],
        warehouse_id=source_cfg["warehouse_id"],
        database_id=source_cfg["database_id"],
        role=source_cfg.get("sf_role") or "ACCOUNTADMIN",
        schema=source_cfg.get("schema") or "RAW",
        tables=source_tables or None,
    )
    sf_target = sf_mod.SnowflakeConnector(
        tenant_id=tenant_id,
        connector_instance_id=target_cfg["connector_instance_id"],
        account_id=target_cfg["account_id"],
        user_id=target_cfg["user_id"],
        warehouse_id=target_cfg["warehouse_id"],
        database_id=target_cfg["database_id"],
        role=target_cfg.get("sf_role") or "ACCOUNTADMIN",
        schema=target_cfg.get("schema") or "STAGING_STAGING",
        tables=target_tables or None,
    )

    source_envs = sf_source.pull_state()
    target_envs = sf_target.pull_state()

    source_cols_raw: list[dict] = []
    target_cols_raw: list[dict] = []
    try:
        source_cols_raw = sf_source.fetch_columns(source_tables or None) or []
    except Exception as exc:
        print("WARN source columns:", exc)
    try:
        target_cols_raw = sf_target.fetch_columns(target_tables or None) or []
    except Exception as exc:
        print("WARN target columns:", exc)

    run_log = map_run_mod.map_run(
        chosen,
        pipeline_id=pipeline["pipeline_id"],
        pipeline_name=pipeline.get("pipeline_name") or "stock_etl",
    )
    run_id = run_log["id"]
    enriched_nodes = _enrich_failed_nodes_with_compiled(
        run_log.get("failed_nodes") or chosen_raw.get("failed_nodes"),
        compiled_sql,
    )
    run_log["failed_nodes"] = enriched_nodes
    run_log["failed_nodes_json"] = __import__("json").dumps(enriched_nodes, default=str)
    if compiled_sql:
        run_log["compiled_sql"] = compiled_sql

    src_counts = _col_counts(source_cols_raw)
    tgt_counts = _col_counts(target_cols_raw)

    source_rows = []
    for env in source_envs:
        ds = map_ds_mod.map_dataset(env, run_id=run_id, asset_role="SOURCE")
        did = (ds.get("dataset_id") or "").upper()
        if did in src_counts:
            ds["column_count"] = src_counts[did]
        source_rows.append(ds)
    target_rows = []
    for env in target_envs:
        ds = map_ds_mod.map_dataset(env, run_id=run_id, asset_role="TARGET")
        did = (ds.get("dataset_id") or "").upper()
        if did in tgt_counts:
            ds["column_count"] = tgt_counts[did]
        target_rows.append(ds)

    columns_rows: list[dict] = []
    for c in source_cols_raw:
        columns_rows.append({**c, "asset_role": "SOURCE"})
    for c in target_cols_raw:
        columns_rows.append({**c, "asset_role": "TARGET"})

    src_total = sum(int(r.get("row_count") or 0) for r in source_rows)
    tgt_total = sum(int(r.get("row_count") or 0) for r in target_rows)
    if source_rows:
        run_log["rows_read"] = src_total
    elif run_log.get("rows_read") in (None, 0) and src_total:
        run_log["rows_read"] = src_total
    if target_rows:
        run_log["rows_written"] = tgt_total
    elif run_log.get("rows_written") in (None, 0) and tgt_total:
        run_log["rows_written"] = tgt_total

    query_history: list[dict] = []
    if _should_fetch_query_history(run_log, dbt_tests):
        try:
            hours = _run_hours_back(run_log)
            errors_only = str(run_log.get("status") or "").lower() in {"failed", "error"}
            query_history = (
                sf_target.fetch_query_history(
                    hours_back=hours, limit=25, errors_only=errors_only
                )
                or []
            )
        except Exception as exc:
            print("WARN query history:", exc)

    # Also seed tool snapshots from classic path when instance ids present
    try:
        src_iid = source_cfg.get("connector_instance_id")
        tgt_iid = target_cfg.get("connector_instance_id")
        if src_iid:
            store_mod.upsert_tool_snapshots(
                str(src_iid), asset_role="SOURCE", assets=source_rows
            )
        if tgt_iid:
            store_mod.upsert_tool_snapshots(
                str(tgt_iid), asset_role="TARGET", assets=target_rows
            )
    except Exception as exc:
        print("WARN classic snapshot seed:", exc)

    store_result = store_payload(
        run_log,
        source_rows,
        target_rows,
        pipeline=pipeline,
        columns=columns_rows,
        query_history=query_history,
        dbt_test_results=dbt_tests,
        lineage_edges=lineage_edges,
    )

    return {
        "ok": True,
        "message": "Sync completed (pipeline loaded from DB)",
        "pipeline_id": pipeline["pipeline_id"],
        "pipeline_name": pipeline.get("pipeline_name"),
        "pipeline_from": "metadata.obs_pipelines",
        "attachments": {
            "source": f"snowflake/{source_cfg.get('schema')}",
            "etl": "dbt",
            "target": f"snowflake/{target_cfg.get('schema')}",
        },
        "table_filters": {
            "source": source_tables,
            "target": target_tables,
        },
        "dbt_relations": dbt_table_names,
        "dbt_tests_stored": len(dbt_tests),
        "lineage_edges_stored": len(lineage_edges),
        "run_id": run_id,
        "status": run_log.get("status"),
        "source_count": len(source_rows),
        "target_count": len(target_rows),
        "rows_read": run_log.get("rows_read"),
        "rows_written": run_log.get("rows_written"),
        "stored": True,
        "store": store_result,
    }
