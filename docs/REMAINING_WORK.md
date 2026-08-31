# Remaining work (backend / ops)

Short checklist after Monte Carlo-style DQ and backend gap closure.

## Blocked on credentials (ops, not code)

- Fix dbt Cloud API token (401 / account locked)
- Store encrypted secrets on source, target, and ETL tools
- Run `python scripts/smoke_api.py --live` until green
- Enable poller in production (`docker-compose` api + poller + mysql)
- Schedule `POST /api/v1/ops/rollup-daily` for trend charts

## Deferred architecture

~~All four items below are implemented.~~ See `docs/PRODUCTION_STATUS.md` for details.

- ~~N-source / N-target Sync fan-in~~ — **Done**
- ~~OpenLineage event ingest~~ — **Done**
- ~~`obs_dq_rules` declarative rule engine~~ — **Done**
- ~~Non-Snowflake SQL validation (Postgres, BigQuery)~~ — **Done**

## Still optional / future

- AI assistant re-integration (packages removed)
- Charts sourced only from rollups for long ranges

## Optional product polish

- Frontend binding for new quality query params and lineage `target_datasets`
- Auto-seed default monitors on pipeline create (today: poller / evaluate-monitors)
- Tag management UI for CDE / team / data-contract filters
