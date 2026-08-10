# ETL Observability App API

FastAPI service for pipeline attach, Sync (Snowflake → dbt → Snowflake),
Grafana dashboard upsert, and dbt webhooks. Metadata lives in MySQL (`obs_*`).

## Run locally

From repo root (with `.env` loaded):

```bash
pip install -r application/requirements.txt
uvicorn application.src.app:app --host 0.0.0.0 --port 8002 --reload
```

Or Docker (from repo root):

```bash
docker build -t etl-obs-api -f Dockerfile .
docker run --rm -p 8002:8002 --env-file .env etl-obs-api
```

## Deploy to Vercel

The repo root is the Vercel project. Entry point: [`api/index.py`](../api/index.py)
(rewrites in [`vercel.json`](../vercel.json)).

```bash
cd "d:\etl pipeline"
npx vercel          # preview
npx vercel --prod   # production
```

### Environment variables (Vercel project settings)

Do **not** commit secrets. Set at least:

| Variable | Purpose |
|----------|---------|
| `DB_HOST` / `DB_PORT` / `DB_USER` / `DB_PASSWORD` / `DB_NAME` | Metadata MySQL |
| `SNOWFLAKE_*` / `DBT_*` (and ecom/hr overrides) | Sync connectors |
| `GRAFANA_URL` | e.g. `http://16.113.97.80:3000` |
| `GRAFANA_TOKEN` | Grafana service-account token |
| `GRAFANA_DATASOURCE_UID` | optional pin |
| `GRAFANA_DASHBOARD_UID` | default `etl-obs` |

RDS must allow connections from Vercel egress (or be publicly reachable with auth).

### After deploy — smoke checks

- `GET https://<deployment>/health`
- `GET https://<deployment>/docs`
- `POST https://<deployment>/grafana/dashboard`

### Sync / timeout note

`/v1/sync` and dbt webhooks call Snowflake/dbt and can exceed Hobby timeouts.
This project sets `maxDuration: 60` (Pro). If Sync still times out or the
Snowflake wheel is too large for serverless, run Sync on Docker/EC2 and keep
Vercel for lighter read/control endpoints.

## Main endpoints

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/health` | Liveness |
| GET/POST | `/v1/pipelines` | List / create pipelines |
| POST | `/v1/sync` | Manual Sync |
| POST | `/grafana/dashboard` | Upsert Grafana dashboard |
| POST | `/webhooks/dbt` | dbt Cloud webhook |
| POST | `/webhooks/dbt/{pipeline_name}` | Named-pipeline webhook |
