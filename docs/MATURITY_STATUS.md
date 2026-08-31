# Maturity roadmap execution status

Product priority: near-realtime observability app first; open source later.

## Tools-first (current)

- Reusable **tools** in `obs_connector_instances` (+ `obs_connections`).
- Compose pipelines: `POST /v1/pipelines/from-tools`.
- Sync prefers bindings; **DB snapshots** in `obs_tool_snapshots` (shared across pipelines); **ETL runs** per pipeline.
- Metadata DB is **local MySQL** (`DB_HOST` required; no RDS default). Production cutover = change `.env` later.

## Done in this codebase

### Phase 0 — Stabilize
- Calculation / API honesty bugs and docs (`docs/DASHBOARD_API.md`).

### Phase 1 — Run identity
- `obs_pipeline_runs.obs_run_id` dual-write; correlation stamp in `connectors/base.py`.

### Phase 2 — Connections / bindings / plugins
- Tables: `obs_connections`, `obs_connector_instances`, `obs_pipeline_bindings`, `obs_lineage_edges`.
- Tools CRUD + compose-from-tools APIs (see `docs/CONNECTORS.md`).
- `GET /api/v1/pipelines/{id}/bindings`, `GET /api/v1/connectors/types`, `GET /api/v1/tools`.

### Phase 3 — Near-realtime + storage
- Poller, heartbeats, fingerprints, daily rollups, raw purge.
- **DB tool snapshots** (`obs_tool_snapshots`) with TTL reuse on Sync.

### Phase 4–6
- MySQL connector in registry; monitors/alerts/incidents; freemium pipeline cap.

### Phase 7
- `docker-compose.yml` (mysql + api + poller).
- Deferred architecture: SQL DQ (PG/BQ), `obs_dq_rules`, N-source/N-target Sync, OpenLineage ingest.

## How to run locally

```bash
docker compose up -d mysql
# .env: DB_HOST=127.0.0.1 (required — no cloud fallback)

uvicorn application.src.app:app --host 127.0.0.1 --port 8002
python application/poller.py
```

## Still deferred
- Airflow live connector; production DB cutover; AI assistant re-integration.

## Reference: Monte Carlo–style collection
See `docs/MONTE_CARLO_DATA_COLLECTION.md` for how industry data observability (metadata, query logs, freshness, volume) maps to our poller + Sync model.
