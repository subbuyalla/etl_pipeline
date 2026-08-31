# Go-live checklist

Use this before pointing production traffic at the observability API.

## 1. Environment

- [ ] `DATABASE_URL` or `DB_*` points at metadata MySQL (RDS in prod)
- [ ] `SECRETS_MASTER_KEY` set (32+ bytes) for encrypted tool secrets
- [ ] `SYNC_INTERVAL_SECONDS` set for poller (default `300`)
- [ ] Optional: `VOLUME_DROP_WARN_PCT`, `VOLUME_DROP_CRIT_PCT`, `DEFAULT_FRESHNESS_SLA_HOURS`

## 2. Tools (credentials)

- [ ] Create **source** database tool (`POST /v1/tools`) with encrypted secret
- [ ] Create **target** database tool with encrypted secret
- [ ] Create **ETL** tool (dbt Cloud) with API token via secret
- [ ] Run `python scripts/audit_tools.py` — no tools should rely on legacy `api_token_env` without `has_secret`

## 3. Pipeline

- [ ] `POST /v1/pipelines/from-tools` with source + etl + target tool IDs
- [ ] Confirm pipeline in `GET /v1/pipelines` and `/api/v1/pipelines/catalog`

## 4. Collect metadata

- [ ] `POST /v1/sync` succeeds (or poller running: `python application/poller.py`)
- [ ] `GET /api/v1/health` shows collector heartbeats (not stale)
- [ ] Optional: configure dbt webhook → returns **202** and Sync runs in background

## 5. Validate dashboards (offline first)

```bash
python scripts/seed_demo_metadata.py
python scripts/smoke_api.py --offline
```

- [ ] Quality, Lineage, Overview show real KPIs (not permanent N/A)
- [ ] `GET /api/v1/runs/demo-run-001/rca-context` returns full bundle

## 6. Live validation (when creds available)

```bash
python scripts/smoke_api.py --live
```

- [ ] Tool test, Sync, webhook paths green

## Metadata contract

Field-level reference: [METADATA_FIELDS.md](METADATA_FIELDS.md)

Architecture and AI context: [METADATA_MODEL.md](METADATA_MODEL.md)
