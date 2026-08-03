# ETL Digital Twin (mock data)

Simulates a multi-domain, multi-tool estate **without credentials**.
Emits vendor-shaped raw JSON through the Connector SDK → Normalization → Metadata.

## Estate

- Domains: Finance, Marketing, Ops
- Tools: Airflow, Glue, dbt, ADF, Snowflake
- Scenarios: pipeline success/fail, task retry, freshness, volume, schema, distribution, lineage, dbt run_results

## Install

```bash
cd packages/connector-sdk && pip install -e .
cd ../normalization && pip install -e .
cd ../metadata && pip install -e .
cd ../simulator && pip install -e ".[dev]"
```

## Commands

```bash
# Estate overview
python -m simulator summary

# Print raw envelopes only
python -m simulator dry-run --ticks 5

# Bootstrap + stream into Metadata DB
python -m simulator run --ticks 40

# Named Monte Carlo scenarios
python -m simulator scenario freshness_breach schema_break pipeline_failure
```

DB URL: `DATABASE_URL` or `--db sqlite:///./metadata.db`
