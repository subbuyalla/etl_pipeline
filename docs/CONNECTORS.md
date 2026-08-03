# Production connectors (Monte Carlo–style)

Connectors are how **anyone** plugs a tool into the platform without changing Metadata, Normalization mappers (beyond registering a tool), UI entity pages, or Assistants.

## User flow (like Monte Carlo)

1. Open **Connectors** in the UI  
2. Pick **Snowflake** or **dbt**  
3. Fill the form (account, warehouse, …)  
4. Put secrets in **environment variables** (e.g. `SNOWFLAKE_PASSWORD`) — only the env *name* is stored  
5. **Create connection** → **Test** → **Sync**  
6. Raw payloads flow: Connector → Normalization → Metadata  

CSV upload remains an **advanced / offline** fallback.

## Architecture

```text
UI form  →  Metadata API (/v1/connectors/*)
                →  Connector registry + runtime
                →  Adapter (live | path | csv)
                →  RawEnvelope
                →  normalize_production
                →  Metadata tables
```

Hard rules:

- Connectors emit **raw vendor JSON only** (`RawEnvelope`)
- Secrets never written to the database (env / secrets_ref only)
- Assistants never call connectors

## SDK contract

See [`packages/connector-sdk`](../packages/connector-sdk):

- `ConnectorSpec` — drives the UI form (`config_schema` JSON Schema)
- `ConnectorContext` — tenant, instance id, config, resolved secrets
- `Connector.discover` / `pull_state` / `stream_events` / `test_connection`
- `RawEnvelope` — hand-off to Normalization

## Add a new connector (for any engineer)

1. Copy [`packages/connectors/templates/new_connector/`](../packages/connectors/templates/new_connector/)
2. Implement `create_<tool>_connector(ctx) -> Connector`
3. Define a `ConnectorSpec` in `packages/connectors/src/connectors/specs.py`
4. `register("<tool_id>", factory)` in `registry.py` `_register_builtins`
5. Ensure Normalization has a mapper for `source_system="<tool_id>"` (existing registry)
6. No Metadata entity or Assistant code changes required

## APIs

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/v1/connectors/catalog` | Specs + form schemas |
| POST | `/v1/connectors/instances` | Create connection |
| GET | `/v1/connectors/instances` | List |
| POST | `/v1/connectors/instances/{id}/test` | Test connection |
| POST | `/v1/connectors/instances/{id}/sync` | Pull → normalize → ingest |
| POST | `/v1/connectors/ingest-csv` | Offline CSV fallback |

## Live credentials

```env
# Snowflake
SNOWFLAKE_PASSWORD=...
# optional keypair
SNOWFLAKE_PRIVATE_KEY=...

# dbt Cloud
DBT_CLOUD_API_TOKEN=...
```

Or set `input_mode=csv` / `path` (dbt `run_results.json`) with no cloud credentials.
