# Pipeline mapping — source, ETL, target

## The problem

Snowflake and dbt are **two separate connectors**. Each sync writes its own records. They do **not** automatically know they are the same pipeline.

## The solution

Use **pipeline_io** (and optionally lineage) in Metadata to declare:

```text
pipeline_id: stock_etl

  SOURCE  → ANALYTICS_DB.RAW.STOCK_DATA_RAW
  ETL     → dbt-70506183153936  (or dbt job name)
  TARGET  → ANALYTICS_DB.STAGING_STAGING.STG_STOCK_DATA
```

## Table: `etl_pipeline_io`

| Column | Example |
|--------|---------|
| `tenant_id` | `demo` |
| `pipeline_id` | `stock_etl` |
| `upstream_dataset_id` | `ANALYTICS_DB.RAW.STOCK_DATA_RAW` |
| `downstream_dataset_id` | `ANALYTICS_DB.STAGING_STAGING.STG_STOCK_DATA` |
| `role` | `source` / `transform` / `target` (conceptual) |

## How to fill it (MVP options)

### Option A — Manual (fastest)

Insert rows after first Snowflake + dbt sync when you know the table names.

### Option B — dbt manifest (next)

On dbt sync, also fetch `manifest.json`:

- Model `unique_id` → `relation_name` (Snowflake FQN)
- `depends_on` → lineage edges RAW → STG

### Option C — Name matching

If dbt model builds `STG_STOCK_DATA` and Snowflake has same FQN, auto-link by string match.

## Query pattern for one assistant

```text
get_pipeline("stock_etl") returns:
  - source datasets (from pipeline_io)
  - etl pipeline id + last executions (from dbt)
  - target datasets (from pipeline_io)
  - last error_message if failed
```

## Your stock pipeline (example)

```text
SOURCE:  ANALYTICS_DB.RAW.STOCK_DATA_RAW
ETL:     dbt Cloud project 70506183153936
TARGET:  ANALYTICS_DB.STAGING_STAGING.STG_STOCK_DATA
         (also: ANALYTICS_DB.DBT_SM_STAGING.STG_STOCK_DATA)
```

## Lineage vs pipeline_io

| Concept | Use for |
|---------|---------|
| `pipeline_io` | "This pipeline reads X and writes Y" |
| `lineage_edges` | "X flows to Y" for blast radius |

For MVP, **pipeline_io is enough** for source/ETL/target.
