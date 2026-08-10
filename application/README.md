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

The repo root is the Vercel project. Entrypoint: [`app.py`](../app.py)
(config in [`vercel.json`](../vercel.json) + [`pyproject.toml`](../pyproject.toml)).

```bash
cd "d:\etl pipeline"
npx vercel          # preview
npx vercel --prod   # production
```

After deploy, open:

- `https://<deployment>/` — service probe
- `https://<deployment>/health`
- `https://<deployment>/docs`

### Fix Vercel 404 / wrong framework

If the site shows a Next.js page or `404: NOT_FOUND`:

1. Vercel Project → **Settings → General → Framework Preset** = **Other** (not Next.js/Vite)
2. **Root Directory** = empty (repo root)
3. Redeploy **Production** from latest `main`
4. Disable **Deployment Protection** on Production if `/docs` asks you to log in to Vercel

`vercel.json` forces `@vercel/python` with a catch-all route to `app.py`.

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
| `PUBLIC_BASE_URL` | optional override; default `https://etl-pipeline-lemon.vercel.app` |

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

## dbt Cloud webhook URLs (production)

Base: `https://etl-pipeline-lemon.vercel.app`

| Pipeline | Webhook URL (POST) |
|----------|--------------------|
| Active pipeline | `https://etl-pipeline-lemon.vercel.app/webhooks/dbt` |
| stock_etl | `https://etl-pipeline-lemon.vercel.app/webhooks/dbt/stock_etl` |
| ecommerce_etl | `https://etl-pipeline-lemon.vercel.app/webhooks/dbt/ecommerce_etl` |
| hr_etl | `https://etl-pipeline-lemon.vercel.app/webhooks/dbt/hr_etl` |

Also listed on `GET /health` as `webhook_urls`.

## Main endpoints

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/health` | Liveness + webhook URLs |
| GET/POST | `/v1/pipelines` | List / create pipelines |
| POST | `/v1/sync` | Manual Sync |
| POST | `/grafana/dashboard` | Upsert Grafana dashboard |
| POST | `/webhooks/dbt` | dbt Cloud webhook |
| POST | `/webhooks/dbt/{pipeline_name}` | Named-pipeline webhook |
