# Metadata Layer — what we store & how it compares

This document explains the **Metadata Layer** (Plan 3): what entities are stored, how they map to Monte Carlo–style observability, and what we store **beyond** common tools (Monte Carlo, Bigeye, Acceldata, Soda, Metaplane).

## Role in the platform

```text
Connector / Twin  →  Normalization  →  Metadata (this layer)  →  UI / AI Assistants
                         canonical events           durable store
```

- **Normalization** translates vendor JSON into canonical events.
- **Metadata** is the **system of record**: assets, monitors, lineage, incidents, costs, health scores.
- UI and AI must read **only** this layer (never raw connector payloads).

Default DB: SQLite (`./metadata.db`) unless you configure MySQL via `.env`.

**Important:** Platform tables use the **`etl_` prefix** (`etl_incidents`, `etl_pipelines`, …). They live in the MySQL database/schema **`metadata`** (not `monitoring`).

### MySQL setup

1. Copy [`.env.example`](../.env.example) → `.env` in the project root.
2. Fill in your MySQL user/password/host/database (credentials are **yours** — not stored in the repo).
3. Create an empty database, e.g. `CREATE DATABASE metadata;`
4. Reinstall metadata deps (`pymysql`) and run:

```bash
pip install -e "packages/metadata[dev]"
python -m simulator db-url          # password masked
python -m simulator run --ticks 20  # creates tables + loads twin data
```

Example `.env`:

```env
DB_DRIVER=mysql+pymysql
DB_HOST=127.0.0.1
DB_PORT=3306
DB_USER=root
DB_PASSWORD=your_password
DB_NAME=metadata
```

Or one URL:

```env
DATABASE_URL=mysql+pymysql://root:your_password@127.0.0.1:3306/metadata
```

---

## Entity catalog (what we store)

| Entity | Purpose | Monte Carlo–like? |
|--------|---------|-------------------|
| **Tool** | Registered source systems (airflow, snowflake, …) | Partial (integrations) |
| **Pipeline** | DAG / job / flow definition | Yes (pipeline assets) |
| **Task** | Step inside a pipeline | Yes (ops detail) |
| **Execution** | Run history (pipeline + task), retries, errors | Yes |
| **Dataset** | Table / topic / object / BI asset | Yes (core) |
| **DatasetColumn** | Column types for schema drift | Yes |
| **Resource** | Warehouse, cluster, bucket | Acceldata-like |
| **Monitor** | Freshness / volume / schema / distribution / custom | Yes (core) |
| **CheckResult** | Individual monitor outcomes over time | Yes |
| **Metric** | Time-series signals (row_count, lag, …) | Yes |
| **LineageEdge** | Upstream → downstream (observed \| declared) | Yes |
| **PipelineIO** | Explicit pipeline ↔ source ↔ target links | Internal (reliability) |
| **Alert** | Fired signal | Yes |
| **Incident** | Grouped issue + blast radius | Yes |
| **EventLog** | Idempotent canonical event audit/replay | Internal (needed) |
| **Domain** | Business domain (Finance, …) | Beyond MC |
| **Owner** | People / teams accountable | Catalog-like / beyond |
| **DataProduct** | Productized data set grouping | Beyond MC |
| **SLA** | Freshness / success targets | Partial elsewhere |
| **ChangeEvent** | Schema / deploy / config changes (CI/CD) | **Beyond Monte Carlo** |
| **CostRecord** | Per-asset FinOps attribution | **Acceldata / beyond MC** |
| **AssetHealthScore** | Maturity / health dimensions for reports | **health-check** |

### Monitor types (Monte Carlo four pillars + ops)

| Monitor type | Meaning |
|--------------|---------|
| `freshness` | Data older than SLA |
| `volume` | Row count / throughput anomaly |
| `schema` | Column add/remove/type change |
| `distribution` | Null rate / stats shift |
| `pipeline_failure` / `task_failure` | Orchestration failures |
| `custom` | Extensible checks |

---

## Database tables & columns (21 tables)

Every table includes `tenant_id` (multi-tenant isolation) unless noted. Source of truth: `packages/metadata/src/metadata/models.py`.

### 1. `tools`

| Column | Type | Notes |
|--------|------|-------|
| `id` | Integer PK | |
| `tenant_id` | String(128) | indexed |
| `tool_id` | String(64) | e.g. `airflow`, `snowflake`; unique with tenant |
| `family` | String(64) | nullable — etl / warehouse / bi |
| `display_name` | String(256) | nullable |
| `connector_instance_id` | String(128) | nullable |
| `created_at` | DateTime | |

### 2. `domains`

| Column | Type | Notes |
|--------|------|-------|
| `id` | Integer PK | |
| `tenant_id` | String(128) | indexed |
| `name` | String(128) | unique with tenant |
| `description` | Text | nullable |
| `created_at` | DateTime | |

### 3. `owners`

| Column | Type | Notes |
|--------|------|-------|
| `id` | Integer PK | |
| `tenant_id` | String(128) | indexed |
| `email` | String(256) | unique with tenant |
| `name` | String(256) | nullable |
| `team` | String(128) | nullable |
| `created_at` | DateTime | |

### 4. `data_products`

| Column | Type | Notes |
|--------|------|-------|
| `id` | Integer PK | |
| `tenant_id` | String(128) | indexed |
| `name` | String(256) | unique with tenant |
| `domain_id` | Integer FK → `domains.id` | nullable |
| `owner_id` | Integer FK → `owners.id` | nullable |
| `description` | Text | nullable |
| `created_at` | DateTime | |

### 5. `pipelines`

| Column | Type | Notes |
|--------|------|-------|
| `id` | Integer PK | |
| `tenant_id` | String(128) | indexed |
| `pipeline_id` | String(512) | unique with tenant |
| `name` | String(512) | |
| `source_tool` | String(64) | indexed |
| `domain_id` | Integer FK → `domains.id` | nullable |
| `owner_id` | Integer FK → `owners.id` | nullable |
| `status` | String(64) | nullable — last known status |
| `tags` | JSON | default `[]` |
| `created_at` | DateTime | |
| `updated_at` | DateTime | |

### 6. `tasks`

| Column | Type | Notes |
|--------|------|-------|
| `id` | Integer PK | |
| `tenant_id` | String(128) | indexed |
| `pipeline_id` | String(512) | indexed |
| `task_id` | String(512) | unique with tenant + pipeline |
| `name` | String(512) | |
| `source_tool` | String(64) | |
| `created_at` | DateTime | |

### 7. `executions`

| Column | Type | Notes |
|--------|------|-------|
| `id` | Integer PK | |
| `tenant_id` | String(128) | indexed |
| `execution_id` | String(512) | unique with tenant + task_id |
| `pipeline_id` | String(512) | indexed |
| `task_id` | String(512) | nullable — null = pipeline-level run |
| `source_tool` | String(64) | |
| `status` | String(64) | indexed — succeeded / failed / running / … |
| `attempt` | Integer | default 1 |
| `started_at` | DateTime | nullable |
| `finished_at` | DateTime | nullable |
| `duration_ms` | Integer | nullable |
| `error_message` | Text | nullable |
| `triggered_by` | String(128) | nullable |
| `created_at` | DateTime | |

### 8. `datasets`

| Column | Type | Notes |
|--------|------|-------|
| `id` | Integer PK | |
| `tenant_id` | String(128) | indexed |
| `dataset_id` | String(1024) | unique with tenant — e.g. `DB.SCHEMA.TABLE` |
| `name` | String(512) | |
| `database_name` | String(256) | nullable |
| `schema_name` | String(256) | nullable |
| `platform` | String(64) | indexed — snowflake / kafka / … |
| `row_count` | Integer | nullable |
| `last_updated_at` | DateTime | nullable |
| `owner_id` | Integer FK → `owners.id` | nullable |
| `domain_id` | Integer FK → `domains.id` | nullable |
| `data_product_id` | Integer FK → `data_products.id` | nullable |
| `tags` | JSON | default `[]` |
| `schema_fingerprint` | String(128) | nullable |
| `created_at` | DateTime | |
| `updated_at` | DateTime | |

### 9. `dataset_columns`

| Column | Type | Notes |
|--------|------|-------|
| `id` | Integer PK | |
| `tenant_id` | String(128) | indexed |
| `dataset_id` | String(1024) | indexed |
| `column_name` | String(256) | unique with tenant + dataset |
| `data_type` | String(128) | nullable |
| `is_nullable` | Boolean | nullable |
| `ordinal` | Integer | nullable — column position |
| `updated_at` | DateTime | |

### 10. `resources`

| Column | Type | Notes |
|--------|------|-------|
| `id` | Integer PK | |
| `tenant_id` | String(128) | indexed |
| `resource_id` | String(512) | unique with tenant |
| `resource_type` | String(64) | cluster / warehouse / bucket |
| `name` | String(512) | |
| `platform` | String(64) | nullable |
| `meta` | JSON | default `{}` |
| `created_at` | DateTime | |

### 11. `slas`

| Column | Type | Notes |
|--------|------|-------|
| `id` | Integer PK | |
| `tenant_id` | String(128) | indexed |
| `name` | String(256) | unique with tenant + asset_id |
| `asset_type` | String(64) | `dataset` \| `pipeline` |
| `asset_id` | String(1024) | |
| `freshness_minutes` | Integer | nullable |
| `success_rate_pct` | Float | nullable |
| `created_at` | DateTime | |

### 12. `monitors`

| Column | Type | Notes |
|--------|------|-------|
| `id` | Integer PK | |
| `tenant_id` | String(128) | indexed |
| `monitor_key` | String(512) | unique with tenant |
| `monitor_type` | String(64) | indexed — freshness / volume / schema / distribution |
| `asset_type` | String(64) | |
| `asset_id` | String(1024) | indexed |
| `name` | String(512) | |
| `config` | JSON | default `{}` — thresholds, SLA, etc. |
| `enabled` | Boolean | default true |
| `created_at` | DateTime | |

### 13. `check_results`

| Column | Type | Notes |
|--------|------|-------|
| `id` | Integer PK | |
| `tenant_id` | String(128) | indexed |
| `monitor_id` | Integer FK → `monitors.id` | nullable |
| `monitor_type` | String(64) | |
| `asset_type` | String(64) | |
| `asset_id` | String(1024) | |
| `status` | String(64) | `passed` \| `failed` \| `anomalous` |
| `metric_value` | Float | nullable |
| `baseline_value` | Float | nullable |
| `severity` | String(32) | nullable |
| `details` | JSON | default `{}` |
| `checked_at` | DateTime | indexed |

### 14. `metrics`

| Column | Type | Notes |
|--------|------|-------|
| `id` | Integer PK | |
| `tenant_id` | String(128) | indexed |
| `name` | String(256) | e.g. `row_count`, `lag_minutes` |
| `asset_type` | String(64) | nullable |
| `asset_id` | String(1024) | nullable |
| `value` | Float | |
| `unit` | String(64) | nullable |
| `recorded_at` | DateTime | |
| `labels` | JSON | default `{}` |

### 15. `lineage_edges`

| Column | Type | Notes |
|--------|------|-------|
| `id` | Integer PK | |
| `tenant_id` | String(128) | indexed |
| `upstream_dataset_id` | String(1024) | indexed |
| `downstream_dataset_id` | String(1024) | indexed; unique pair with tenant + upstream |
| `confidence` | String(32) | `observed` \| `declared` |
| `transform` | String(512) | nullable — **pipeline_id** that produced the downstream dataset |
| `platform` | String(64) | nullable |
| `updated_at` | DateTime | |

When lineage events include `transform` (or `pipeline_id` in the raw payload), ingest also upserts **`pipeline_io`** for reliable pipeline ↔ dataset linking.

### 15b. `pipeline_io`

| Column | Type | Notes |
|--------|------|-------|
| `id` | Integer PK | |
| `tenant_id` | String(128) | indexed |
| `pipeline_id` | String(255) | indexed — ETL pipeline / DAG / job |
| `upstream_dataset_id` | String(255) | indexed — source dataset |
| `downstream_dataset_id` | String(255) | indexed — target dataset |
| `source_tool` | String(64) | nullable — orchestration tool (airflow, glue, …) |
| `updated_at` | DateTime | |

Unique on `(tenant_id, pipeline_id, upstream_dataset_id, downstream_dataset_id)`.

Populated when:
- A `lineage.edge.upserted.v1` event carries `transform` / `pipeline_id`
- A `pipeline.execution.*` event payload includes `upstream` / `downstream` dataset ids

Pipeline dashboard and `GET /v1/pipelines/{id}` prefer `pipeline_io` for `related_datasets`.

### 16. `incidents`

| Column | Type | Notes |
|--------|------|-------|
| `id` | Integer PK | |
| `tenant_id` | String(128) | indexed |
| `incident_key` | String(512) | unique |
| `title` | String(512) | |
| `status` | String(32) | `open` \| `triage` \| `resolved` |
| `severity` | String(32) | default `medium` |
| `root_asset_type` | String(64) | nullable |
| `root_asset_id` | String(1024) | nullable |
| `blast_radius_count` | Integer | default 0 |
| `summary` | Text | nullable |
| `opened_at` | DateTime | |
| `resolved_at` | DateTime | nullable |

### 17. `alerts`

| Column | Type | Notes |
|--------|------|-------|
| `id` | Integer PK | |
| `tenant_id` | String(128) | indexed |
| `alert_key` | String(512) | unique |
| `title` | String(512) | |
| `severity` | String(32) | default `medium` |
| `status` | String(32) | `open` \| `acked` \| `resolved` |
| `asset_type` | String(64) | nullable |
| `asset_id` | String(1024) | nullable |
| `monitor_type` | String(64) | nullable |
| `message` | Text | nullable |
| `raised_at` | DateTime | |
| `resolved_at` | DateTime | nullable |
| `incident_id` | Integer FK → `incidents.id` | nullable |

### 18. `event_log`

| Column | Type | Notes |
|--------|------|-------|
| `id` | Integer PK | |
| `tenant_id` | String(128) | indexed |
| `event_id` | String(128) | unique with tenant — idempotent ingest |
| `event_type` | String(128) | e.g. `pipeline.execution.failed.v1` |
| `source_tool` | String(64) | |
| `occurred_at` | DateTime | |
| `connector_instance_id` | String(128) | nullable |
| `payload` | JSON | canonical event payload |
| `ingested_at` | DateTime | |

### 19. `change_events`

| Column | Type | Notes |
|--------|------|-------|
| `id` | Integer PK | |
| `tenant_id` | String(128) | indexed |
| `change_type` | String(64) | `schema` \| `deploy` \| `config` |
| `asset_type` | String(64) | nullable |
| `asset_id` | String(1024) | nullable |
| `breaking` | Boolean | default false |
| `details` | JSON | default `{}` |
| `occurred_at` | DateTime | |
| `source_tool` | String(64) | nullable |

### 20. `cost_records`

| Column | Type | Notes |
|--------|------|-------|
| `id` | Integer PK | |
| `tenant_id` | String(128) | indexed |
| `asset_type` | String(64) | |
| `asset_id` | String(1024) | |
| `amount` | Float | |
| `currency` | String(8) | default `USD` |
| `cost_category` | String(64) | nullable — compute / storage / egress |
| `platform` | String(64) | nullable |
| `recorded_at` | DateTime | |
| `labels` | JSON | default `{}` |

### 21. `asset_health_scores`

| Column | Type | Notes |
|--------|------|-------|
| `id` | Integer PK | |
| `tenant_id` | String(128) | indexed |
| `asset_type` | String(64) | |
| `asset_id` | String(1024) | unique with tenant + dimension |
| `dimension` | String(64) | health-check pillar name |
| `score` | Float | |
| `max_score` | Float | default 100 |
| `details` | JSON | default `{}` |
| `scored_at` | DateTime | |

### Column count summary

| Table | Columns (incl. `id` / `tenant_id`) |
|-------|-------------------------------------|
| `tools` | 7 |
| `domains` | 5 |
| `owners` | 6 |
| `data_products` | 7 |
| `pipelines` | 11 |
| `tasks` | 7 |
| `executions` | 14 |
| `datasets` | 16 |
| `dataset_columns` | 8 |
| `resources` | 8 |
| `slas` | 8 |
| `monitors` | 10 |
| `check_results` | 12 |
| `metrics` | 9 |
| `lineage_edges` | 8 |
| `incidents` | 12 |
| `alerts` | 13 |
| `event_log` | 9 |
| `change_events` | 9 |
| `cost_records` | 10 |
| `asset_health_scores` | 9 |
| **Total tables** | **21** |

---

## Comparison vs other tools

Legend: **Y** = first-class, **P** = partial / weak, **N** = not a product focus.

| Metadata / capability | Monte Carlo | Bigeye | Acceldata | Soda | Metaplane | **Metadata** |
|----------------------|:-----------:|:------:|:---------:|:----:|:---------:|:------------------:|
| Dataset / table catalog | Y | Y | Y | P | Y | **Y** |
| Column schema metadata | Y | Y | Y | P | Y | **Y** (`DatasetColumn`) |
| Freshness monitors | Y | Y | Y | Y | Y | **Y** |
| Volume monitors | Y | Y | Y | Y | Y | **Y** |
| Schema change monitors | Y | Y | Y | P | Y | **Y** + `ChangeEvent` |
| Distribution / nulls | Y | Y | Y | Y | Y | **Y** |
| Table lineage + blast radius | Y | P | Y | N | P | **Y** |
| Incident workflow | Y | P | Y | N | P | **Y** |
| Pipeline / task executions (Airflow, Glue, …) | P | P | Y | N | N | **Y** (first-class) |
| Cross-tool ETL ops (Informatica, SSIS, ADF, …) | P | P | P | N | N | **Y** (via normalizer) |
| BI asset refresh (Tableau / Looker / PBI) | P | N | P | N | N | **Y** |
| Rule / check-as-code style | P | P | Y | Y | P | **P** (custom monitors; Soda-style later) |
| Infrastructure / cluster health | N | N | Y | N | N | **P** (`Resource` ready) |
| **FinOps / cost per pipeline** | N | N | Y | N | N | **Y** (`CostRecord`) |
| **CI/CD deploy ↔ break correlation** | N | N | P | N | N | **Y** (`ChangeEvent`) |
| **Business domain / data product / owner** | P | P | P | N | P | **Y** |
| **Health / maturity scores (8 dimensions)** | N | N | N | N | N | **Y** (`AssetHealthScore`) |
| Vendor-neutral tool labels | N (own product) | N | N | N | N | **Y** (`Tool` + normalizer) |
| Idempotent event log for replay | Internal | Internal | Internal | N | Internal | **Y** (`EventLog`) |

### What we add more than Monte Carlo

1. **Cross-stack ETL/ELT execution metadata** (not warehouse-only).
2. **FinOps** — `CostRecord` for pipeline/dataset spend.
3. **CI/CD change intelligence** — `ChangeEvent` linked to schema/deploy.
4. **Business context** — `Domain`, `Owner`, `DataProduct`, `SLA`.
5. **Health-check scores** — `AssetHealthScore` for the 4-week / continuous report.
6. **BI refresh observability** as first-class pipelines/datasets.
7. **Tool-agnostic contract** — same store whether data comes from twin or any connector.

### What we intentionally match (do not miss)

To stay at least at Monte Carlo / Bigeye parity on DQ observability, this layer **always** stores:

- Datasets + columns  
- Monitors + check results for freshness, volume, schema, distribution  
- Lineage edges + blast-radius computation  
- Alerts grouped into incidents  
- Metrics time series  
- Execution history for jobs that produce data  

If a competitor field exists for those, we have a home for it in the catalog above.

---

## Ingest path

1. Canonical event (from Normalization) `POST /v1/events`
2. Or raw tool JSON `POST /v1/ingest/raw` (normalize → ingest)
3. Handlers upsert entities, open incidents on failures/breaches, update lineage

Idempotency: duplicate `event_id` → skipped (`EventLog` unique key).

---

## Query APIs (AI / UI)

| Endpoint | Returns |
|----------|---------|
| `GET /v1/pipelines` | Pipelines |
| `GET /v1/datasets` | Datasets |
| `GET /v1/executions` | Runs |
| `GET /v1/monitors` | Monitors |
| `GET /v1/check-results` | Monitor outcomes (`asset_id`, `monitor_type` filters) |
| `GET /v1/datasets/{dataset_id}` | Single dataset |
| `GET /v1/alerts` | Alerts |
| `GET /v1/incidents` | Incidents |
| `GET /v1/lineage` | Edges |
| `GET /v1/lineage/blast-radius` | Downstream impact |
| `GET /v1/catalog` | Entity list |

---

## Run locally

```bash
cd packages/metadata
pip install -e ".[dev]"
pip install -e ../normalization
python -m pytest -q
python -m metadata.api
# API on http://127.0.0.1:8000/docs
```
