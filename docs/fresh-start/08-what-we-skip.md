# What we skip for MVP (fresh start)

Cut scope so connectors + one DB + one assistant ship first.

## Skip for v1

| Feature | Why skip |
|---------|----------|
| 3 separate assistants (Observability, RCA, DQ) | One assistant with tools is enough |
| A2A orchestrator | No multi-agent routing needed yet |
| Auto monitor on 47 tables (Monte Carlo style) | Manual monitors / Snowflake sync only |
| ML anomaly detection / Tune model | Static thresholds or twin only |
| Scheduled connector sync | Manual Sync button first |
| Full 28-tool connector catalog | Snowflake + dbt only |
| Custom web UI for everything | Connectors page + your assistant platform |
| Domains, owners, FinOps, health scores | Schema exists; wave 2 |
| Digital twin as primary data | Use live connectors for demo |

## Keep from existing repo

| Keep | Reason |
|------|--------|
| Connector SDK + Snowflake + dbt adapters | Already working |
| Metadata API + MySQL | System of record |
| Normalization for snowflake/dbt | Required for ingest |
| Connectors UI page | Test/Sync UX |
| `pipeline_io` + lineage tables | Needed for source/ETL/target |

## Monte Carlo parity (later)

- Bulk data product monitor deploy
- Gap detection / coverage map
- NL → create monitor (Oria-style)
- Event-driven "on table update" triggers

## Success criteria for fresh start

1. Snowflake + dbt sync reliably
2. One pipeline (`stock_etl`) has source/ETL/target in DB
3. One assistant answers from Metadata only
4. Demo: failed dbt run → stored error → assistant explains it
