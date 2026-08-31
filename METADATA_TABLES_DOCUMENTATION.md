# Metadata Tables — Required Fields and Recommendations

This document describes the **MySQL metadata tables** used by the observability platform: what each table stores, why the information is required, and recommended future additions.

> **Canonical references**
> - Architecture and three-layer model: [`docs/METADATA_MODEL.md`](docs/METADATA_MODEL.md)
> - Field-by-field (DB vs ETL tools): [`docs/METADATA_FIELDS.md`](docs/METADATA_FIELDS.md)
> - Production implementation status: [`docs/PRODUCTION_STATUS.md`](docs/PRODUCTION_STATUS.md)
> - DQA detail: [`Part 2E — Data Quality Assurance (DQA) metadata.md`](Part%202E%20%E2%80%94%20Data%20Quality%20Assurance%20(DQA)%20metadata.md)

**Status terminology**

| Label | Meaning |
|-------|---------|
| **Current** | Defined in schema (`meta_mysql.ensure_tables`) and used in Sync/APIs |
| **Recommended** | Useful enhancement; not required for current operation |
| **Future** | Planned capability; not implemented yet |

---

## Table inventory

### Registration (Layer 1)

| Table | Purpose |
|-------|---------|
| `obs_connections` | Shared connection/auth references |
| `obs_connector_instances` | Tool registration and `config_json` |
| `obs_secrets` | Encrypted credentials (Fernet) |
| `obs_pipelines` | Pipeline registry |
| `obs_pipeline_bindings` | SOURCE / ETL / TARGET tool links |

### Collection (Layer 2) — core seven

| Table | Purpose |
|-------|---------|
| `obs_pipeline_runs` | One observed pipeline execution (spine table) |
| `obs_run_assets` | Table-level metadata per run |
| `obs_run_columns` | Column-level metadata per run |
| `obs_tool_snapshots` | Cached DB metadata per tool (~300s TTL) |
| `obs_run_query_history` | Snowflake query context for RCA |

### Derived & operational (Layer 3)

| Table | Purpose |
|-------|---------|
| `obs_check_results` | Monitor + dbt test check outcomes |
| `obs_monitors` | Monitor definitions (freshness, volume, failures, dbt tests) |
| `obs_alerts` | Open/resolved alert state |
| `obs_incidents` | Persisted incident records |
| `obs_lineage_edges` | Model-level lineage from dbt manifest |
| `obs_collector_heartbeats` | Poller/Sync heartbeat per pipeline |
| `obs_metric_rollups_daily` | Daily run/volume rollups |
| `obs_asset_fingerprints` | Write-on-change fingerprint cache |
| `obs_usage_counters` | Freemium/usage counters |

This document details the **core collection tables** first, then summarizes registration and derived tables.

---

# 1. `obs_connector_instances`

## Purpose

Stores **registration and configuration** for every connected database, ETL, or orchestrator tool.

> **What tool is connected, where is it located, and what scope should we monitor?**

Secrets live in `obs_secrets`, not in `config_json`.

## Current schema

| Column | Why we need it |
|--------|----------------|
| `instance_id` | Primary key (public `tool_id` in APIs) |
| `connection_id` | Optional link to `obs_connections` |
| `tenant_id` | Multi-tenant isolation |
| `name` | Human-readable name in UI |
| `connector_type` | e.g. `snowflake`, `dbt`, `mysql` |
| `kind` | `database`, `etl`, or `orchestrator` |
| `scope_json` | Optional scope metadata |
| `config_json` | Non-secret tool config (host, schema, tables, dbt account, etc.) |
| `status` | e.g. `active` |
| `created_at` | Audit |
| `updated_at` | Last config change |

Config fields inside `config_json` (by tool type) are documented in [`docs/METADATA_FIELDS.md`](docs/METADATA_FIELDS.md).

## Recommendation

No mandatory schema changes. Optional: explicit `last_test_at` / `last_error` on the instance row for connector health UI.

---

# 2. `obs_secrets`

## Purpose

Stores **encrypted credentials** separately from connector configuration.

> **How are tools authenticated without plaintext in config?**

## Current schema

| Column | Why we need it |
|--------|----------------|
| `secret_id` | Unique secret row id |
| `owner_type` | e.g. `tool` |
| `owner_id` | Links to `obs_connector_instances.instance_id` |
| `secret_name` | Slot name (default `default`) |
| `ciphertext` | Fernet-encrypted secret bytes (base64) |
| `key_version` | Key rotation label (default `v1`) |
| `created_at` | Audit |
| `updated_at` | Rotation tracking |

## Relationship

```text
obs_connector_instances (instance_id)
        |
        | owner_type='tool', owner_id=instance_id
        v
   obs_secrets
```

**Environment:** `SECRETS_MASTER_KEY` in `.env` — never stored in MySQL.

---

# 3. `obs_pipelines` and `obs_pipeline_bindings`

## Purpose

**Pipeline registry** — which named pipeline exists and which three tools compose it.

| Table | Answers |
|-------|---------|
| `obs_pipelines` | What is the pipeline? (`pipeline_id`, names, denormalized source/etl/target, `is_active`) |
| `obs_pipeline_bindings` | Which tool instance fills SOURCE / ETL / TARGET? |

See [`docs/METADATA_MODEL.md`](docs/METADATA_MODEL.md) for compose flow (`POST /v1/pipelines/from-tools`).

---

# 4. `obs_pipeline_runs`

## Purpose

Stores **one observed execution** of a pipeline — the **central spine** of observability.

> **What happened when a pipeline ran?**

Used by: Overview, runs, incidents, logs, metrics, RCA, `GET /api/v1/runs/{id}/rca-context`.

## Current fields

| Field | Why we need it |
|-------|----------------|
| `id` | Vendor run id (e.g. dbt `run_id`) — primary key |
| `obs_run_id` | Internal platform correlation UUID |
| `pipeline_id` | Pipeline reference |
| `pipeline_name` | Human-readable name |
| `status` | success / failed / running |
| `start_time`, `end_time`, `duration` | Timing and performance |
| `tool_name` | ETL tool (e.g. `dbt`) |
| `rows_read`, `rows_written`, `rows_added` | Throughput and net volume delta |
| `failure_stage` | Where failure occurred |
| `failed_node` | First failed dbt model/test |
| `failed_message` | Message for failed node |
| `failed_nodes_json` | All failed nodes + messages (RCA) |
| `relations_json` | dbt `relations[]` for run — table scope + lineage (promoted from `raw_log`) |
| `error_class` | compilation / runtime / permission / timeout |
| `error_message` | Overall run error |
| `raw_log` | Full vendor JSON for audit/debug |
| `execution_mode`, `triggered_by` | How run was triggered |
| `orchestrator_*` | Parent Airflow/orchestrator context when present |
| `tenant_id`, `connector_instance_id` | Isolation and ETL tool link |
| `created_at` | Record creation audit |

## Recommended additions

| Field | Why we need it |
|-------|----------------|
| `environment` | DEV / STAGING / PROD separation |
| `updated_at` | If run records are amended after ingest |

## Design point

Keep both `id` (vendor) and `obs_run_id` (platform). Foreign keys from assets/columns/queries use vendor `id` as `run_id` today.

---

# 5. `obs_run_assets`

## Purpose

**Table-level metadata** observed during a pipeline run.

> **Which tables were involved, and what was their state when we observed them?**

## Current fields

| Field | Why we need it |
|-------|----------------|
| `run_id` | Links to `obs_pipeline_runs.id` |
| `asset_role` | `SOURCE` or `TARGET` |
| `system_name`, `system_type` | Platform label and category |
| `database_name`, `schema_name`, `object_name`, `object_type` | Qualified object identity |
| `row_count` | Volume observability |
| `size_bytes` | Storage signal |
| `column_count` | Schema size hint |
| `last_updated_at` | Freshness (from catalog `LAST_ALTERED`) |
| `observed_at` | When platform pulled metadata |
| `dataset_id` | **Canonical identity** — e.g. `ANALYTICS.MART.FCT_ORDERS` |
| `tenant_id`, `connector_instance_id` | Isolation and source tool |
| `created_at` | Audit |

## Design point

Always use `dataset_id` as the stable key — not `object_name` alone (multiple schemas can have the same table name).

---

# 6. `obs_run_columns`

## Purpose

**Column-level metadata** for tables observed on a run — powers schema drift detection.

## Current fields

| Field | Why we need it |
|-------|----------------|
| `run_id`, `asset_role` | Run and SOURCE/TARGET context |
| `database_name`, `schema_name`, `object_name` | Table identity |
| `column_name`, `data_type`, `ordinal_position` | Schema snapshot |
| `dataset_id` | Link to asset |
| `created_at` | Audit |

## Future enhancements

| Field | Why we may need it |
|-------|-------------------|
| `is_nullable` | Nullability drift |
| `default_value` | Default drift |
| `comment` | Documentation in UI |

Defer until native DQA checks need them (see Part 2E).

---

# 7. `obs_tool_snapshots`

## Purpose

**Cached database metadata** per tool — avoids re-querying the warehouse on every Sync when TTL is valid (default **300 seconds**).

> **What metadata did we recently retrieve from this connector?**

## Current fields

| Field | Why we need it |
|-------|----------------|
| `snapshot_id` | Row id |
| `instance_id` | Database connector |
| `dataset_id` | Table key |
| `asset_role` | SOURCE vs TARGET cache partition |
| `fingerprint` | Change detection |
| `payload_json` | Serialized asset metadata |
| `columns_json` | Serialized columns |
| `pulled_at` | Cache timestamp |

## Cache vs history

```text
obs_run_assets     → historical observation tied to a specific run
obs_tool_snapshots → recent reusable cache for Sync performance
```

## Recommended addition

| Field | Why |
|-------|-----|
| `expires_at` | Explicit TTL check (`now < expires_at`) instead of computing from `pulled_at` each time |

---

# 8. `obs_run_query_history`

## Purpose

**Query execution context** for pipeline runs — primarily Snowflake failures.

> **What SQL ran, and what database error explains the failure?**

## Current fields

| Field | Why we need it |
|-------|----------------|
| `run_id` | Pipeline run link |
| `query_id` | Warehouse query id |
| `start_time`, `end_time` | Timing |
| `execution_status` | Success/failure |
| `error_code`, `error_message` | Database error (e.g. Snowflake `390913`) |
| `query_text` | SQL context (truncated ~2K) |
| `warehouse_name`, `user_name` | Execution context |
| `database_name`, `schema_name` | Object context |
| `created_at` | Audit |

## Recommended additions

| Field | Why |
|-------|-----|
| `connector_instance_id` | Which DB tool produced the query |
| `observed_at` | When platform collected the row |

## Scope

RCA slice only — not a full warehouse query-log warehouse.

---

# 9. Derived tables (summary)

## `obs_check_results`

Outcomes of **monitors** and **dbt tests**. See Part 2E for DQA detail.

| Column | Purpose |
|--------|---------|
| `check_id` | Unique result id |
| `monitor_id` | Monitor id, or `dbt-run:{run_id}` for dbt tests |
| `pipeline_id` | Pipeline scope |
| `status` | pass / warn / fail |
| `severity` | low / medium / high / critical |
| `message` | Human-readable outcome |
| `observed_json` | Tool-specific payload (test_id, relation_name, drop_pct, etc.) |
| `checked_at` | Evaluation time |

## `obs_monitors`

Default monitors per pipeline: `freshness`, `volume_drop`, `pipeline_failure`, `dbt_test_failure`.

## `obs_lineage_edges`

dbt manifest edges: `from_dataset` → `to_dataset`, scoped by `pipeline_id` and `run_id`.

## `obs_collector_heartbeats`

Poller/Sync success: `last_success_at`, `last_error` — exposed on `GET /api/v1/health`.

## `obs_alerts` / `obs_incidents`

Alert and incident lifecycle driven by `evaluate_monitors()` and failed runs.

---

# Architecture (full)

```text
obs_connections
       |
       v
obs_connector_instances ────── obs_secrets
       |                              |
       |                              |
       v                              v
obs_pipeline_bindings ──► obs_pipelines
       |
       v
obs_pipeline_runs ◄──── Sync / poller / webhook (202 + background)
       |
       +──── obs_run_assets ──► obs_run_columns
       |
       +──── obs_run_query_history
       |
       +──── obs_lineage_edges (from dbt manifest)

obs_connector_instances
       |
       v
obs_tool_snapshots (cache)

obs_monitors ──► obs_check_results ──► obs_alerts ──► obs_incidents

obs_collector_heartbeats (operational)
obs_metric_rollups_daily (rollups)
```

## Design principles

```text
obs_connector_instances  = What tools are connected?
obs_secrets              = How are they authenticated?
obs_pipelines            = What pipelines exist?
obs_pipeline_runs        = What happened during execution?
obs_run_assets           = Which tables were involved?
obs_run_columns          = What was the schema?
obs_tool_snapshots       = What metadata is cached?
obs_run_query_history    = What query/error explains a failure?
obs_check_results        = Did checks/tests pass?
obs_lineage_edges        = How do models depend on each other?
```

---

# Implementation status

| Area | Status |
|------|--------|
| Connector + pipeline registration | **Current** |
| Secret storage (Fernet) | **Current** — schema above |
| Pipeline run metadata + `relations_json` | **Current** |
| Table/column metadata | **Current** |
| Metadata caching | **Current** |
| Query history / RCA context | **Current** |
| dbt tests → `obs_check_results` | **Current** |
| Manifest → `obs_lineage_edges` | **Current** |
| DQA / Quality API + Overview pillar | **Current** |
| Collector heartbeats in health API | **Current** |
| Native DQA rules (`obs_dq_rules`) | **Current** — CRUD + poller evaluation |
| OpenLineage archive (`obs_lineage_events`) | **Current** |
| N-source / N-target pipeline bindings | **Current** — fan-in Sync collect |
| SQL validation (Snowflake / Postgres / BigQuery) | **Current** |
| Rich check columns (`expected_value`, etc.) | **Future** — use `observed_json` today |
| Connector `environment` on runs | **Recommended** |
| Snapshot `expires_at` | **Recommended** |
| Extended column metadata for DQA | **Future** |

---

# Related documentation

| Document | Use when |
|----------|----------|
| [`docs/METADATA_MODEL.md`](docs/METADATA_MODEL.md) | Architecture, Sync behavior, AI RCA bundle |
| [`docs/METADATA_FIELDS.md`](docs/METADATA_FIELDS.md) | Per-field mapping from Snowflake/dbt to tables |
| [`Part 2E — Data Quality Assurance (DQA) metadata.md`](Part%202E%20%E2%80%94%20Data%20Quality%20Assurance%20(DQA)%20metadata.md) | DQA checks, dbt tests, future rule engine |
| [`docs/PRODUCTION_STATUS.md`](docs/PRODUCTION_STATUS.md) | Done vs blocked-on-credentials matrix |
