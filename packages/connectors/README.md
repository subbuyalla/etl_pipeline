# Connectors

Production connector package: **registry**, **runtime** (retries), Snowflake + dbt adapters.

Modes per tool:

| Tool | Modes |
|------|--------|
| Snowflake | `live` (account + env password), `csv` |
| dbt | `live` (dbt Cloud token), `path` (run_results.json), `csv` |

```bash
pip install -e .
python -m pytest -q
python -m connectors ingest --tool snowflake --csv samples/snowflake_checks.csv
```

Monte Carlo–style UI uses Metadata APIs (`/v1/connectors/catalog`, `/instances`, `/test`, `/sync`).

Add a tool: see [templates/new_connector](templates/new_connector) and [docs/CONNECTORS.md](../../docs/CONNECTORS.md).
