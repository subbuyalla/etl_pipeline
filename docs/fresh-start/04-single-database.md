# Single database — how everything is stored

## One MySQL database (`metadata`)

All observability data lives in one place. Assistants and reports read **only this DB**.

## Core tables for MVP

| Table | What it stores | Filled by |
|-------|----------------|-----------|
| `etl_tools` | Registered systems (snowflake, dbt) | Ingest |
| `etl_pipelines` | Pipeline definitions | dbt sync, twin |
| `etl_executions` | Run history + **error logs** | dbt sync |
| `etl_datasets` | Tables (Snowflake FQN) | Snowflake sync |
| `etl_monitors` | DQ rules (freshness, volume, …) | Snowflake sync, twin |
| `etl_check_results` | Monitor outcomes | Sync / twin |
| `etl_pipeline_io` | Source ↔ target per pipeline | **Manual or manifest (MVP gap)** |
| `etl_lineage_edges` | Upstream → downstream | Manifest / manual |
| `etl_incidents` | Grouped open problems | Ingest on failure |
| `etl_alerts` | Fired signals | Ingest |
| `etl_connector_instances` | Connection configs (no secrets) | UI/API |

Full catalog: [../METADATA_LAYER.md](../METADATA_LAYER.md)

## Per-pipeline view (logical)

```text
etl_pipelines
  pipeline_id = stock_etl

etl_pipeline_io
  stock_etl | RAW.STOCK_DATA_RAW → STG_STOCK_DATA

etl_executions (filter by pipeline_id from dbt)
  run_id, status, error_message, started_at, finished_at

etl_datasets
  RAW.STOCK_DATA_RAW, STG_STOCK_DATA (from Snowflake)
```

## What "logs" mean in each table

| Log type | Table | Example field |
|----------|-------|---------------|
| dbt job failure | `etl_executions` | `error_message` |
| Table freshness | `etl_check_results` | `status=breach` |
| Open problem | `etl_incidents` | `title`, `severity` |

## Tenant isolation

- All rows have `tenant_id` (default: `demo`)
- Multiple Snowflake accounts = multiple connector instances, same tenant unless you split tenants

## External assistant platform

**Yes, this works:**

```text
Your assistant platform
  → tools call Metadata REST API (:8000)
  OR
  → tools run SQL against MySQL (read-only user)
```

Do not point the assistant at Snowflake/dbt directly for production answers.

## Optional: BIRT reports

Eclipse BIRT (open source) can generate PDF/HTML reports **from the same MySQL DB**:

- Pipeline success rate
- Open incidents
- Last sync per connector

BIRT does **not** replace connectors — it only visualizes stored data.
