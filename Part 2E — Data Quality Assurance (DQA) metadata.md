# Part 2E — Data Quality Assurance (DQA) metadata

Data Quality Assurance identifies whether observed data meets expectations: completeness, validity, freshness, volume stability, and dbt test outcomes.

**Implementation status (2026-08)**

| Capability | Status |
|------------|--------|
| Context metadata (runs, assets, columns) | **Done** |
| dbt test ingest → `obs_check_results` | **Done** (on Sync) |
| Quality page API | **Done** — `GET /api/v1/observability/quality` |
| Overview DQ health pillar | **Done** |
| `dbt_test_failure` monitor | **Done** |
| Freshness / volume monitors (derived checks) | **Done** |
| RCA includes dbt tests | **Done** — `GET /api/v1/runs/{id}/rca-context` |
| Native rule engine (`obs_dq_rules`) | **Done** — `/v1/dq-rules`, poller, `/ops/evaluate-dq-rules` |
| Platform-native NOT_NULL / UNIQUE (SQL) | **Done** — monitors + rules; Snowflake / Postgres / BigQuery TARGET |
| Full relational check schema (see §2E.2 target) | **Partial** — use `observed_json` today |

Related: [`METADATA_TABLES_DOCUMENTATION.md`](METADATA_TABLES_DOCUMENTATION.md) · [`docs/METADATA_FIELDS.md`](docs/METADATA_FIELDS.md)

---

## 2E.1 DQA metadata currently available

Metadata already collected and used for DQA context:

| Metadata | Source table | DQA use |
|----------|--------------|---------|
| `dataset_id` | `obs_run_assets` / `obs_run_columns` | Identify the table being checked |
| `run_id` | `obs_pipeline_runs` (+ link via `monitor_id`) | Associate results with a pipeline run |
| `asset_role` | `obs_run_assets` / `obs_run_columns` | SOURCE vs TARGET |
| `column_name`, `data_type` | `obs_run_columns` | Column identity and type expectations |
| `row_count` | `obs_run_assets` | Volume / row-count validation |
| `last_updated_at` | `obs_run_assets` | Freshness validation |
| `relations_json` | `obs_pipeline_runs` | dbt models/tables in run scope |

**Why:** DQA needs stable asset and column identity plus run context. Existing run/asset/column metadata provides that without storing business row data.

---

## 2E.2 Check results — `obs_check_results`

### Current schema (implemented)

Each row is one **monitor evaluation** or one **dbt test outcome**.

| Field | Why we store it | Where it is used |
|-------|-----------------|------------------|
| `check_id` | Unique result id | Dedup, detail views |
| `monitor_id` | Monitor id, or `dbt-run:{run_id}` for dbt tests | Join to run; filter dbt vs platform checks |
| `pipeline_id` | Pipeline scope | DQA page, filters, incidents |
| `status` | pass / warn / fail | DQA KPIs, alerts |
| `severity` | Impact level | Alerts, incident severity |
| `message` | Human-readable outcome | UI, RCA |
| `observed_json` | Tool-specific payload (see below) | Detail, future AI RCA |
| `checked_at` | When evaluated | History, time filters |

### `observed_json` for dbt tests (current)

```json
{
  "run_id": "70506183553987",
  "test_id": "test.analytics.not_null_orders_order_id",
  "relation_name": "ANALYTICS.MART.FCT_ORDERS",
  "dataset_id": "ANALYTICS.MART.FCT_ORDERS",
  "dimension": "completeness",
  "tags": ["dimension:completeness", "dataset:ANALYTICS.MART.FCT_ORDERS"],
  "execution_time": 1.2,
  "source": "dbt_run_results"
}
```

### Target schema (future — optional migration)

If platform-native DQA grows, these columns may be promoted out of `observed_json`:

| Field | Why we would store it |
|-------|----------------------|
| `run_id` | Direct FK to run (today via `monitor_id`) |
| `dataset_id` | Affected table |
| `column_name` | Column-level checks |
| `check_type` | NOT_NULL, UNIQUE, DBT_TEST, etc. |
| `check_name` | Human label |
| `expected_value` / `actual_value` | Threshold comparisons |
| `failure_count` / `failure_percentage` | Severity and trends |
| `details_json` | Extended vendor payload |
| `tenant_id` | Multi-tenant filtering |

**Today:** ingest path is `store_dbt_test_results()` in `meta_mysql.py`; read path is `quality.py` + `lifecycle.py`.

---

## 2E.3 Supported check types

### Implemented today

| Source | Check types | How stored |
|--------|-------------|------------|
| **dbt** | dbt tests (not_null, unique, relationships, etc.) | `obs_check_results` with `monitor_id = dbt-run:{run_id}` |
| **Monitors** | Freshness SLA, volume drop, latest run failed, dbt test failure | `obs_check_results` via `evaluate_monitors()` |

### Planned (platform-native)

| Check type | Example | Primary level |
|------------|---------|---------------|
| `NOT_NULL` | `email` must not be NULL | Column |
| `UNIQUE` | `order_id` unique | Column |
| `ACCEPTED_VALUES` | `status` in allowed set | Column |
| `RANGE` | `amount >= 0` | Column |
| `ROW_COUNT` | Table within threshold | Table |
| `REFERENTIAL_INTEGRITY` | FK exists in parent | Cross-table |
| `FRESHNESS` | Updated within SLA | Table (also monitor) |
| `VOLUME_ANOMALY` | Row count delta | Table (also monitor) |
| `DBT_TEST` | Explicit type label for dbt rows | Model / column |

Native types require **`obs_dq_rules`** (or equivalent) — not implemented yet.

---

## 2E.4 Data Quality rules and configuration

Monitors in `obs_monitors` cover freshness, volume, run failure, dbt test failure, and optional SQL validation (`null_check`, `unique_check`, `duplicate_check`, `custom_sql`).

**Monitor CRUD (implemented):**

| Method | Path |
|--------|------|
| GET/POST | `/v1/monitors` |
| GET/PUT/DELETE | `/v1/monitors/{monitor_id}` |
| GET | `/api/v1/pipelines/{pipeline_id}/monitors` |

Fields: `monitor_kind`, `config_json`, `dataset_id`, `column_name`, `dimension`, `tags_json`, `monitor_type`.

**DQ rules CRUD (implemented):**

| Method | Path |
|--------|------|
| GET/POST | `/v1/dq-rules` |
| GET/PUT/DELETE | `/v1/dq-rules/{rule_id}` |
| POST | `/api/v1/ops/evaluate-dq-rules` |

Rule types: `NOT_NULL`, `UNIQUE`, `DUPLICATE`, `ACCEPTED_VALUES`, `RANGE`, `CUSTOM_SQL`. Results write to `obs_check_results` with `monitor_id=rule:{rule_id}`.

**Monitors vs rules:** Monitors remain for operational checks (freshness, volume). Rules are the declarative DQ layer for platform-native SQL checks.

---

## 2E.5 dbt test results (implemented)

```text
Pipeline Sync
    ↓
dbt connector: fetch_test_results(run_id)
    ↓
store_dbt_test_results() → obs_check_results
    ↓
Quality API / Overview / RCA / dbt_test_failure monitor
```

Example stored result (logical view):

```text
monitor_id: dbt-run:70506183553987
pipeline_id: demo-pipeline-001
status: fail
message: relationships to customers
observed_json.relation_name: ANALYTICS.MART.FCT_ORDERS
observed_json.test_id: test.demo.relationships_fct_orders
checked_at: 2026-08-28T10:00:00Z
```

---

## 2E.6 How DQA fits the metadata model

```text
ETL run
    ↓
obs_pipeline_runs
    │
    ├── status, failed_nodes_json, relations_json
    │
    ▼
Database metadata
    ├── obs_run_assets (row_count, last_updated_at)
    └── obs_run_columns (column_name, data_type)
                │
                ▼
        Checks & monitors
                │
                ▼
        obs_check_results
                │
          ┌─────┴─────┐
          ▼           ▼
      obs_alerts   obs_incidents
                │
                ▼
    Quality page / Overview / RCA context API
```

---

## 2E.7 Where DQA metadata is used (product)

| Surface | Status | Source |
|---------|--------|--------|
| **DQA page** | Done | `build_quality_page()` |
| **Overview DQ pillar** | Done | `quality_summary()` |
| **Pipeline run / RCA** | Done | `build_rca_context()` → `dbt_tests` |
| **Lineage detail** | Done | Failed test count per pipeline |
| **Alerts / incidents** | Partial | Monitors → alerts; dbt failures via `dbt_test_failure` |
| **Dataset / column detail pages** | Future | Needs per-asset drill-down UI |
| **AI RCA assistant** | Future | Context API ready; assistant not wired |

---

## 2E.8 Quick lookup by capability

| Feature | Context metadata | ETL metadata | Result storage |
|---------|------------------|--------------|----------------|
| Not-null (dbt) | Column + asset | Run + relation | `obs_check_results` |
| Uniqueness (dbt) | Column identity | dbt test | `obs_check_results` |
| Accepted values (dbt) | Column identity | dbt test | `obs_check_results` |
| Referential integrity (dbt) | Dataset/column | dbt test | `obs_check_results` |
| Freshness | `last_updated_at` | Last successful run | Monitor → `obs_check_results` |
| Volume anomaly | `row_count` | Run throughput | Monitor → `obs_check_results` |
| dbt test failure | Model/column in `observed_json` | dbt artifact | `obs_check_results` |
| Native NOT_NULL / UNIQUE | Column identity | Run context | **Done** — `/v1/monitors` + `/v1/dq-rules` on warehouse TARGET |
| AI RCA | Asset + column + tests | Failed nodes/errors | `rca-context` bundle |

---

## Testing without live credentials

```bash
python scripts/seed_demo_metadata.py   # 4 sample checks + lineage
python application/test_observability_offline.py
python scripts/smoke_api.py --offline
```

Demo run id: `demo-run-001` · pipeline: `demo-pipeline-001`
