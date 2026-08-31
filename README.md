# ETL Observability API

Backend for pipeline observability: **connectors**, **FastAPI**, and **MySQL metadata**.

Live code lives in [`application/`](application/). Connectors: [`application/src/connectors/`](application/src/connectors/).

## Local metadata DB

Set `DB_HOST=127.0.0.1` in `.env` (required — no cloud default). Create DB `metadata` on local MySQL. Switch to production host later when cutting over.

## Tools → pipelines

1. `POST /v1/tools` — configure DB / ETL tools once
2. `POST /v1/pipelines/from-tools` — pick source + etl + target tool IDs
3. `POST /v1/sync` — ETL logs per pipeline; DB snapshots reused across pipelines

See [`docs/CONNECTORS.md`](docs/CONNECTORS.md).

## Metadata contract

What each tool registers vs what Sync collects into `obs_*` tables:

- [`docs/METADATA_MODEL.md`](docs/METADATA_MODEL.md) — architecture and decisions  
- [`docs/METADATA_FIELDS.md`](docs/METADATA_FIELDS.md) — **field-by-field list** (database vs ETL, why, where used)

## Run locally

```bash
.\.venv\Scripts\Activate.ps1
pip install -r application/requirements.txt
python -m uvicorn application.src.app:app --host 127.0.0.1 --port 8002
```

Docs: [`docs/DASHBOARD_API.md`](docs/DASHBOARD_API.md) · [`docs/CONNECTORS.md`](docs/CONNECTORS.md) · [`docs/MATURITY_STATUS.md`](docs/MATURITY_STATUS.md)
