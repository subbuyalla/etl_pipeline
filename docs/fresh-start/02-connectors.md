# Connectors — build and use

## Connector contract (SDK)

Every connector implements:

| Method | Purpose |
|--------|---------|
| `test_connection()` | Prove credentials work |
| `discover()` | List assets (tables, jobs, …) |
| `pull_state()` | One sync snapshot → list of `RawEnvelope` |
| `stream_events()` | Optional incremental poll |

Location: `packages/connector-sdk/src/connector_sdk/base.py`

## User flow

```text
1. Open Connectors UI (or POST /v1/connectors/instances)
2. Fill form (non-secret fields only)
3. Put password/token in .env
4. Create → Test → Sync
5. Data flows: Connector → Normalization → Metadata DB
```

## MVP connectors (build in this order)

| # | Tool | Role | Status |
|---|------|------|--------|
| 1 | Snowflake | Source + target tables | Done |
| 2 | dbt Cloud | ETL run logs | Done |
| 3 | MySQL | Optional source DB | Not started |
| 4 | Airflow | Optional orchestrator | Partial |

## Snowflake — what Sync pulls

- `INFORMATION_SCHEMA.TABLES` → datasets
- `ROW_COUNT`, `LAST_ALTERED` → freshness/volume monitor events

Config fields: `account`, `user`, `warehouse`, `database`, `role`, `password_env`

## dbt Cloud — what Sync pulls

- `GET /accounts/{account_id}/runs/` → last 10 job runs
- Optional: `run_results.json` artifact per run → per-model results

Config fields: `account_id`, `project_id`, `job_id` (optional), `api_base`, `api_token_env`

## How to add a new connector

1. Add `ConnectorSpec` in `packages/connectors/src/connectors/specs.py`
2. Implement adapter in `packages/connectors/src/connectors/adapters/`
3. `register("tool_id", factory)` in `registry.py`
4. Add normalization mapper for `source_system="tool_id"`
5. No Metadata entity changes if events match existing types

See also: [../CONNECTORS.md](../CONNECTORS.md)

## Common errors

| Error | Fix |
|-------|-----|
| Missing dbt Cloud token | Add `DBT_CLOUD_API_TOKEN` to `.env`, restart Metadata API on `:8000` |
| Missing Snowflake password | Add `SNOWFLAKE_PASSWORD` to `.env`, restart Metadata API |
| Test OK but no lineage | Expected — connectors don't auto-link; use `pipeline_io` |

## API endpoints

| Method | Path |
|--------|------|
| GET | `/v1/connectors/catalog` |
| POST | `/v1/connectors/instances` |
| POST | `/v1/connectors/instances/{id}/test` |
| POST | `/v1/connectors/instances/{id}/sync` |
