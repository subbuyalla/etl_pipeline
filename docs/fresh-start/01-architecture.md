# Architecture (simplified)

## Four layers

```text
External tools (Snowflake, dbt, Airflow, …)
        │
        ▼
┌───────────────┐
│  Connectors   │  Pull raw logs / catalog (no business logic)
└───────┬───────┘
        │ RawEnvelope (vendor JSON)
        ▼
┌───────────────┐
│ Normalization │  Map to canonical events
└───────┬───────┘
        │ canonical events
        ▼
┌───────────────┐
│ Metadata DB   │  System of record (MySQL)
└───────┬───────┘
        │
        ▼
┌───────────────┐
│ One assistant │  Tools read Metadata API or SQL
└───────────────┘
```

## What each layer does

| Layer | Job | Does NOT |
|-------|-----|----------|
| Connector | Test connection, Sync, emit raw JSON | Store secrets, write entities directly |
| Normalization | Translate tool JSON → standard events | Call external APIs |
| Metadata | Persist pipelines, datasets, runs, lineage | Run ETL jobs |
| Assistant | Answer questions from stored data | Query Snowflake at chat time |

## Pipelines run outside our app

```text
Your dbt job runs in dbt Cloud (or CI)
        │
        ▼
Connector Sync (we observe, we don't execute)
        │
        ▼
Metadata DB stores execution + error_message
        │
        ▼
Assistant: "Why did this fail?"
```

## Multi-connector example (your stock pipeline)

```text
Snowflake connector  →  datasets: RAW.STOCK_DATA_RAW, STG_STOCK_DATA
dbt connector        →  pipeline + executions (run logs, errors)

Join (pipeline_io):  stock_etl
  source  = ANALYTICS_DB.RAW.STOCK_DATA_RAW
  etl     = dbt-70506183153936
  target  = ANALYTICS_DB.STAGING_STAGING.STG_STOCK_DATA
```

Connectors collect **independently**. **pipeline_io** defines they belong to the same pipeline.
