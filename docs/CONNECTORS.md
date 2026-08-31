# Application connectors

Connectors live in `application/src/connectors/`. Create reusable **tools**, then compose pipelines.

## Registered types

| ID | Kind | Module |
|----|------|--------|
| `snowflake` | database | `snowflake.py` |
| `mysql` | database | `mysql.py` |
| `postgres` | database | `postgres.py` |
| `redshift` | database | `redshift.py` |
| `bigquery` | database | `bigquery.py` |
| `dbt` / `dbt_cloud` | etl | `dbt.py` |
| `airbyte` | etl | `airbyte.py` |
| `airflow` | orchestrator | `airflow.py` |

**8 connector families** (dbt counted once). Catalog: `GET /v1/tools/types`.

## Tools-first flow

1. `POST /v1/tools` — configure once  
2. `POST /v1/pipelines/from-tools` — source (DB) + etl/orchestrator + target (DB)  
3. `POST /v1/sync` — ETL/orchestrator per pipeline; DB snapshots reused  

## Optional deps

```bash
pip install -r application/requirements.txt
# postgres/redshift → psycopg2-binary
# bigquery → google-cloud-bigquery
```

## Secrets (encrypted in DB)

Tool passwords/tokens are **not** stored in `.env`.

1. Set **one** master key in env: `SECRETS_MASTER_KEY` (Fernet).
2. On `POST /v1/tools`, send `"secret": "<password-or-token>"`.
3. App encrypts with Fernet → stores ciphertext in `obs_secrets`.
4. Sync / test decrypts in memory only; GET APIs never return plaintext (`has_secret: true|false`).

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Rotate a secret later: `PUT /v1/tools/{tool_id}/secret`.

Legacy: `auth_ref` env-var names still work as fallback if no DB secret exists.

## SQL column validation (DQ monitors + rules)

When the pipeline **TARGET** is Snowflake, Postgres, or BigQuery, platform SQL checks run via:

- `POST /v1/monitors` — `null_check`, `unique_check`, `duplicate_check`, `custom_sql`
- `POST /v1/dq-rules` — declarative `NOT_NULL`, `UNIQUE`, `DUPLICATE`, `RANGE`, `ACCEPTED_VALUES`, `CUSTOM_SQL`

Shared helpers: `application/src/connectors/validation.py`. Results land in `obs_check_results`.

Evaluated on poller tick or manually:

- `POST /api/v1/ops/evaluate-monitors`
- `POST /api/v1/ops/evaluate-dq-rules`

## Multi-source / multi-target compose

`POST /v1/pipelines/from-tools` accepts optional arrays:

- `source_tool_ids[]` — multiple SOURCE database tools
- `target_tool_ids[]` — multiple TARGET database tools

Legacy single `source_tool_id` / `target_tool_id` still supported. Sync collects from each binding (fan-in).

## OpenLineage

Ingest RUN/COMPLETE events:

- `POST /webhooks/openlineage`
- `POST /webhooks/openlineage/{pipeline_name}`

Edges merge with dbt manifest lineage in the lineage API (deduped by from/to dataset).

`DB_HOST=127.0.0.1` required. See `.env.example`.
