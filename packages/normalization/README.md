# Normalization Layer (Plan 2) — production

Transforms **every supported ETL / ELT / DB / storage / SaaS / BI** raw payload into
versioned **canonical events** for the Metadata layer.

## Production features

- Unwraps real API envelopes (`dag_runs`, `JobRuns`, `results`, `value`, `tables`, …)
- Flattens nested `state` / `conf` / `tableReference` objects
- `normalize_production()` returns **events + dead_letters** (ingest workers never crash)
- Fixture-tested against Airflow / Glue / dbt / Snowflake / BigQuery / ADF / Tableau / Power BI shapes

## Supported tools (28)

| Family | Tools |
|--------|-------|
| ETL orchestration | airflow, glue, informatica, adf, talend, ssis, nifi, prefect, dagster |
| ELT | dbt (`run_results.json` supported) |
| Warehouse / DB | snowflake, bigquery, databricks, redshift, oracle, postgres, mysql, sqlserver |
| Streaming / storage | kafka, s3, gcs, adls |
| SaaS / API | salesforce, sap, generic_api |
| BI | tableau, looker, powerbi |

## Usage

```python
from normalization import normalize, normalize_production

# Strict (raises)
events = normalize({"source_system": "airflow", "tenant_id": "demo", "raw": {...}})

# Production ingest (dead letters)
result = normalize_production({"source_system": "airflow", "tenant_id": "demo", "raw": {...}})
print(result.events, result.dead_letters)
```

## Install

```bash
pip install -e ".[dev]"
python -m pytest -q
```
