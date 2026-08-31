# Metadata model — what we store from tools

This is the **contract** for observability metadata: what is registered on a tool, what is collected on Sync, and what lands in MySQL.  
We **observe only** — no pipeline execution, no business row data, no plaintext secrets.

---

## Principles

| Rule | Detail |
|------|--------|
| **No secrets in metadata tables** | Passwords/tokens → `obs_secrets` (Fernet). `config_json` is non-secret only. |
| **No business data** | Table **metadata** (counts, sizes, column names/types) — never row contents. |
| **ETL per pipeline run** | Each Sync attaches one ETL/orchestrator run to one pipeline. |
| **DB per tool snapshot** | Warehouse metadata is cached per **tool** (`obs_tool_snapshots`), reused across pipelines within TTL (default 300s). |
| **Vendor id + platform id** | ETL run PK = vendor `run_id` (e.g. dbt). Platform correlation = `obs_run_id` (UUID). |

---

## Three layers

```
┌─────────────────────────────────────────────────────────────────┐
│ 1. REGISTRATION (static) — obs_connections, obs_connector_     │
│    instances, obs_pipeline_bindings, obs_pipelines              │
│    "How to connect" + which tools belong to which pipeline      │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼ Sync / poller
┌─────────────────────────────────────────────────────────────────┐
│ 2. COLLECTION (pulled) — obs_pipeline_runs, obs_run_assets,     │
│    obs_run_columns, obs_run_query_history, obs_tool_snapshots   │
│    "What happened" + table snapshots at observe time            │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼ evaluate_monitors / APIs
┌─────────────────────────────────────────────────────────────────┐
│ 3. DERIVED — obs_check_results, obs_alerts, obs_incidents,      │
│    obs_metric_rollups_daily, Grafana views                      │
│    Freshness, volume, failures, SLA breaches                    │
└─────────────────────────────────────────────────────────────────┘
```

---

## Layer 1 — Tool registration (`POST /v1/tools`)

Stored in **`obs_connector_instances.config_json`** (+ optional **`obs_connections`** for shared auth).

### Database tools (`kind: database`)

| Field | Snowflake | MySQL / Postgres / Redshift | BigQuery |
|-------|-----------|------------------------------|----------|
| `account_id` / `host` | account locator | host | — |
| `user_id` / `user` | user | user | — |
| `warehouse_id` | warehouse | — | — |
| `database_id` / `database` | database | database | `project_id` |
| `schema` | schema | schema (optional) | `dataset` |
| `tables` | list of table names (pipeline grain) | same | same |
| `sf_role` / `role` | Snowflake role | — | — |
| `port` | — | port | — |
| `location` | — | — | BQ location |
| `credentials_path` | — | — | GCP JSON path (path only, not file contents) |

**Secret slot:** `password` (or warehouse password) → `obs_secrets`, never in `config_json`.

### ETL tools (`kind: etl`)

| Field | dbt / dbt_cloud | Airbyte |
|-------|-----------------|---------|
| `account_id` | dbt Cloud account id | — |
| `project_id` | dbt project id | — |
| `job_id` | dbt job definition id | — |
| `project_name` | display label | — |
| `api_base` | e.g. `https://eg250.us1.dbt.com/api/v2` | `base_url` |
| `connection_id` | — | Airbyte connection id |
| `workspace_id` | — | workspace id |

**Secret slot:** `api_token` (dbt) or client secret / password → `obs_secrets`.

### Orchestrator tools (`kind: orchestrator`)

| Field | Airflow |
|-------|---------|
| `base_url` | Airflow REST URL |
| `dag_id` | optional filter |
| `username` | optional |

**Secret slot:** `token` or `password` → `obs_secrets`.

### Pipeline compose (`POST /v1/pipelines/from-tools`)

| Table | What is stored |
|-------|----------------|
| `obs_pipelines` | `pipeline_id`, `pipeline_name`, denormalized `source_*` / `etl_*` / `target_*`, `config_json` (derived source/etl/target dicts) |
| `obs_pipeline_bindings` | `(pipeline_id, role, instance_id)` for SOURCE / ETL / TARGET |

---

## Layer 2 — Collection on Sync

### ETL / orchestrator → `obs_pipeline_runs`

**Source:** connector `pull_state()` → `map_run()` → `store_run()`.

| Column | dbt Cloud (today) | Airflow (planned same path) |
|--------|-------------------|----------------------------|
| `id` | dbt `run_id` | DAG run id |
| `obs_run_id` | new UUID per sync | same |
| `pipeline_id`, `pipeline_name` | from pipeline | same |
| `status` | success / failed / running | mapped |
| `start_time`, `end_time`, `duration` | from API | same |
| `tool_name` | `dbt` | `airflow` |
| `rows_read`, `rows_written` | from `run_results.json` artifact | if available |
| `rows_added` | computed vs previous TARGET total | computed |
| `failure_stage`, `failed_node`, `failed_message` | dbt artifact + inference | TBD |
| `failed_nodes_json` | list of failed nodes | TBD |
| `error_class` | compilation / runtime / permission / timeout | classified |
| `error_message` | dbt status message | same |
| `raw_log` | **full dbt run JSON** (for RCA) | full vendor payload |
| `execution_mode`, `triggered_by` | e.g. orchestrated, dbt-cloud | configurable |
| `orchestrator_*` | null until Airflow linked | dag/task/run ids |
| `tenant_id`, `connector_instance_id` | tool ids | same |

**dbt envelope fields collected (in `raw` before map):**  
`run_id`, `job_id`, `project_name`, `status`, `started_at`, `finished_at`, `error_message`, `rows_read`, `rows_written`, `node_count`, `relations[]`, `failed_node`, `failed_message`, `failure_stage`, `failed_nodes[]`, `error_class`.

**Not stored from dbt today:** individual test results, full compile log text (only summary in `error_message` / `raw_log`).

---

### Database tools → `obs_run_assets` + `obs_run_columns` + `obs_tool_snapshots`

**Source:** connector `pull_state()` + `fetch_columns()` → `map_dataset()` → `store_asset()` / `store_columns()`.

Per **table** (SOURCE or TARGET role):

| Field | Source |
|-------|--------|
| `run_id` | links snapshot to current ETL run |
| `asset_role` | `SOURCE` or `TARGET` |
| `system_name` / `system_type` | Snowflake, MySQL, etc. |
| `database_name`, `schema_name`, `object_name` | catalog |
| `object_type` | `TABLE` |
| `row_count` | `INFORMATION_SCHEMA` / vendor catalog |
| `size_bytes` | catalog (Snowflake `BYTES`) |
| `column_count` | count of columns fetched |
| `last_updated_at` | `LAST_ALTERED` / equivalent |
| `observed_at` | UTC time we pulled |
| `dataset_id` | `DB.SCHEMA.TABLE` |
| `connector_instance_id` | tool id |

**Columns** (`obs_run_columns`): `column_name`, `data_type`, `ordinal_position` per table per run.

**Tool snapshot** (`obs_tool_snapshots`): same asset payload + `columns_json` + `fingerprint` + `pulled_at` — **shared** across pipelines using that DB tool until TTL expires.

**Query history** (Snowflake TARGET only, best-effort): `obs_run_query_history` — `query_id`, times, status, error, truncated `query_text` (2k chars), warehouse, user, db, schema.

---

## Layer 3 — Derived (not from tools directly)

| Output | Inputs |
|--------|--------|
| Freshness | Latest success run + TARGET `last_updated_at` vs SLA |
| Volume | TARGET `row_count` / `size_bytes` deltas across runs |
| Schema drift | Diff `obs_run_columns` between last two successful runs |
| Monitors / alerts / incidents | `evaluate_monitors()` on freshness, volume drop, run failure |
| Daily rollups | `obs_metric_rollups_daily` from runs + assets |

**Not yet from tools:** custom DQ checks, dbt test results → `obs_check_results` (table exists, writers partial).

---

## What we explicitly do NOT store

- Plaintext passwords, API tokens, private keys  
- Table row data / query result sets  
- Full query text beyond 2k truncation (Snowflake RCA slice)  
- PII from warehouse (we only read catalog + query metadata)

---

## Sync behavior summary

| Data | Behavior |
|------|----------|
| ETL run | **Always fresh** on every Sync |
| DB metadata | Reuse `obs_tool_snapshots` if age &lt; `DB_TOOL_SNAPSHOT_TTL_SECONDS` (default 300); else re-pull |
| `refresh_db=true` on Sync | Force DB re-pull |
| Multiple pipelines, same DB tool | Share one snapshot cache |

---

---

## Full schema vs pipeline scope (for Lineage, RCA, DQA, AI)

**You do not need the full warehouse schema** (every table in the account) for AI-assisted RCA on a pipeline failure.

What AI needs is a **failure context bundle** around the blast radius of one run — not Monte Carlo–style estate-wide inventory.

### What each capability needs

| Capability | Need full account schema? | What metadata is enough |
|------------|---------------------------|-------------------------|
| **Lineage (UI)** | No | Pipeline bindings (source → dbt → target) + tables touched in **this run** |
| **Lineage (deep / AI)** | No | **dbt manifest** model `depends_on` graph + `relations[]` from `run_results.json` |
| **RCA (AI)** | No | Failed run + `failed_nodes[]` + error class/message + Snowflake **query_history** + column schema for **involved tables only** |
| **DQA** | No | **dbt test results** + column metadata on **monitored models** (not every table in the DB) |

### Recommended collection scope (finalize on this)

```
Pipeline registration (static)
  └── config.tables = "anchor" tables (entry/exit of pipeline)

On each Sync (dynamic, per run)
  └── dbt run_results → relations[] + failed_nodes[]
  └── Collect DB metadata + columns for:
        • config.tables (SOURCE anchors)
        • ALL dbt relations from that run (TARGET + intermediate models)  ← expand here
  └── On failure: query_history (warehouse)
  └── Next: manifest.json → obs_lineage_edges (model-level graph)
  └── Next: dbt tests → obs_check_results (DQA)
```

**Why not full schema?**

- Cost: polling entire `INFORMATION_SCHEMA` every 5 min is slow and expensive.
- Noise: AI gets worse with irrelevant tables; RCA is about the failed node and its upstream/downstream.
- Lineage from dbt **manifest** is more accurate than inferring from warehouse catalog alone.

### AI RCA context bundle

`GET /api/v1/runs/{run_id}/rca-context` assembles a single grounded payload for triage and LLM assistants:

| Section | Source | Purpose |
|---------|--------|---------|
| `run`, `failure` | `obs_pipeline_runs` | Status, failed node, error class/message |
| `relations`, `assets`, `columns` | run-scoped metadata | Schema + volume for involved tables |
| `lineage_upstream` / `lineage_downstream` | `obs_lineage_edges` | Up/downstream slice around failed node |
| `query_history` | `obs_run_query_history` | Warehouse SQL near run window |
| `dbt_tests` | `obs_check_results` (`dbt-run:{id}`) | Tests from this run |
| `dq_checks` | `obs_check_results` (pipeline, 7d) | Monitors + rules across pipeline |
| `change_since_last_success` | delta vs prior success run | Volume + schema diffs |
| `compiled_sql` | `failed_nodes_json` / `raw_log` | dbt compiled SQL for failed nodes |
| `open_incidents` | `obs_incidents` | Active incidents on pipeline |
| `summary` | computed | Counts for quick UI / prompt sizing |

No row data. No full-database dump.

### Gap vs today (what to build after credentials)

| Item | Status | Priority for AI RCA |
|------|--------|---------------------|
| Run + failed_nodes in `obs_pipeline_runs` | Done | P0 |
| `relations[]` promoted to queryable fields | Done | P0 |
| Schema for **all dbt relations** on run | Done (SOURCE+TARGET merge) | P0 |
| `change_since_last_success` (volume + schema) | Done | P0 |
| Pipeline-scoped `dq_checks` in RCA bundle | Done | P0 |
| dbt compiled SQL on failed nodes | Done | P0 |
| Query history: run-window + success+failed tests | Done | P0 |
| `manifest.json` → lineage edges | Done | P1 |
| dbt test results → DQA | Done | P1 |
| AI assistant / structured RCA output | Not built | P2 (wire LLM on `rca-context`) |
| Full warehouse schema scan | Not planned | Skip |

---

## Decisions to lock (finalize checklist)

Use this before credentials / full testing:

- [ ] **Table grain:** anchor tables in tool config + **expand to all dbt `relations` per run** (not full account schema) → **Recommended**
- [ ] **dbt scope:** one `job_id` per ETL tool? → **Current: yes, recommended**
- [ ] **dbt `api_base`:** per-tool in config (supports multi-host) → **Current: yes**
- [ ] **Snapshot TTL:** 300s aligned with poller? → **Current: yes** (`DB_TOOL_SNAPSHOT_TTL_SECONDS`)
- [ ] **Query history:** Snowflake only, errors-only, 24h window? → **Current: yes**
- [ ] **dbt lineage:** ingest `manifest.json` into `obs_lineage_edges`? → **Recommended for AI RCA (P1)**
- [ ] **dbt `relations[]` / `failed_nodes[]`:** promote out of `raw_log` to indexed fields? → **Recommended (P1)**
- [ ] **dbt test results:** ingest into `obs_check_results`? → **Yes for DQA + AI (P1)**
- [ ] **Full warehouse schema:** skip unless estate-wide discovery needed → **Recommended: skip**
- [ ] **Airbyte as ETL:** same run mapping as dbt? → **Connector exists; map_run path needs validation**
- [ ] **Legacy `config_json` pipelines:** migrate all to tools + bindings? → **Recommended before prod**

---

## Table index

| Table | Purpose |
|-------|---------|
| `obs_connections` | Shared connection / `auth_ref` |
| `obs_connector_instances` | Tool definition + `config_json` |
| `obs_secrets` | Encrypted credentials |
| `obs_pipeline_bindings` | SOURCE / ETL / TARGET tool ids |
| `obs_pipelines` | Pipeline registry + denormalized labels |
| `obs_pipeline_runs` | ETL/orchestrator run log |
| `obs_run_assets` | SOURCE/TARGET table metadata per run |
| `obs_run_columns` | Column schema per run |
| `obs_run_query_history` | Warehouse queries for RCA |
| `obs_tool_snapshots` | Cached DB metadata per tool |
| `obs_check_results` | Monitor / DQ check outcomes |
| `obs_alerts` / `obs_incidents` | Operational signals |
| `obs_metric_rollups_daily` | Aggregated metrics |
| `obs_lineage_edges` | Declared lineage (pipeline-level) |

---

## Related docs

- `docs/CONNECTORS.md` — connector IDs and secrets  
- `docs/METADATA_FIELDS.md` — **field list by tool type (why + where used)**  
- `docs/MONTE_CARLO_DATA_COLLECTION.md` — industry comparison  
- `docs/DASHBOARD_API.md` — how stored metadata surfaces in APIs
