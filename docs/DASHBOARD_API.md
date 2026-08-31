# Dashboard API (`/api/v1`)

Stable, versioned REST APIs for the VITHI observability UI. Backed by MySQL `obs_*` tables.

Base URL (local): `http://127.0.0.1:8002`  
OpenAPI: `/docs`

## Envelope (every list/KPI route)

```json
{
  "ok": true,
  "generated_at": "2026-08-21T12:00:00Z",
  "range": { "from": "...", "to": "...", "preset": "24h" },
  "filters_applied": {},
  "kpis": [
    {
      "id": "success_rate",
      "title": "Successful Runs",
      "value": 91.3,
      "display": "91.3%",
      "delta": 2.1,
      "delta_label": "vs previous period",
      "tone": "ok",
      "available": true
    }
  ],
  "series": {},
  "charts": {},
  "items": [],
  "pagination": { "page": 1, "page_size": 20, "total": 0 },
  "pillars": [],
  "incidents": [],
  "pipelines": [],
  "health": [],
  "summary": {},
  "meta": {}
}
```

Rules for frontend:

- Keys are always present. Missing data → `null`, `[]`, or `"N/A"`.
- If `available: false`, show N/A (Quality / Consistency / Uniqueness / Alerts until monitors exist).
- Prefer `/api/v1/overview` for the Overview page (one call).
- `delta` is `null` when undefined (previous period = 0, or `preset=all`).

## Shared query params

| Param | Description |
|-------|-------------|
| `preset` | `15m` \| `24h` \| `7d` \| `30d` \| `all` |
| `start_date` / `end_date` | `YYYY-MM-DD` (optional; overrides preset) |
| `start_time` / `end_time` | `HH:MM:SS` |
| `pipeline_name` / `pipeline_id` | Comma-separated |
| `status` / `tool` | Comma-separated |
| `page` / `page_size` | Pagination |

Previous-period deltas use a window of equal length immediately before the current range.
When `preset=all`, all KPI deltas are suppressed (`null`).

## Pipeline catalog + detail (call these for list → click)

**`GET /api/v1/pipelines/catalog`** — lean list for the UI to click:

```json
{
  "ok": true,
  "items": [
    {
      "pipeline_id": "ae28a22e-...",
      "pipeline_name": "hr_etl",
      "is_active": true,
      "activity": "Active",
      "tool": "dbt"
    }
  ]
}
```

Optional: `?q=hr`

**`GET /api/v1/pipelines/{pipeline_id}`** — full details after click (source / etl / target + last run).

`GET /api/v1/filters` still returns presets/statuses/tools (and pipelines) for other dropdowns.

`is_active` is **operational**, not the Sync default:

- **Active** (`is_active: true`): currently `running`, or last run (success or fail) within `ACTIVITY_LOOKBACK_HOURS` (default **168** = 7 days)
- **Inactive**: never ran, or last activity older than that window
- A recent **failed** run is still Active (the job is operating; health is a separate field)
- Freshness SLA stays `DEFAULT_FRESHNESS_SLA_HOURS` (24h) — that is data delay, not Active/Inactive
- `is_sync_default` is the attach pointer (which pipeline Sync uses if none is named)
- Calling the catalog API also writes `obs_pipelines.is_operational` so metadata matches the dashboard
- Overview/pipelines table uses **global** last activity for Active/Inactive (not range-scoped)

## Routes

| Method | Path | Screen |
|--------|------|--------|
| GET | `/api/v1/health` | Health |
| GET | `/api/v1/filters` | Filter dropdown catalog |
| GET | `/api/v1/pipelines/catalog` | Pipeline id + name list |
| GET | `/api/v1/pipelines/{pipeline_id}` | Pipeline full detail |
| GET | `/api/v1/overview` | Overview (full) |
| GET | `/api/v1/overview/kpis` | Overview KPIs |
| GET | `/api/v1/overview/charts` | Overview charts |
| GET | `/api/v1/overview/health` | Health pillars |
| GET | `/api/v1/overview/recent-incidents` | Recent incidents |
| GET | `/api/v1/overview/pipelines` | Overview table |
| GET | `/api/v1/pipelines` | Pipelines list |
| GET | `/api/v1/pipelines/{pipeline_id}` | Pipeline full detail |
| GET | `/api/v1/pipelines/{pipeline_id}/runs` | Pipeline runs |
| GET | `/api/v1/observability/freshness` | Freshness |
| GET | `/api/v1/observability/volume` | Volume |
| GET | `/api/v1/observability/quality` | Data Quality (dbt tests + monitors) |
| GET | `/api/v1/observability/schema` | Schema |
| GET | `/api/v1/lineage` | Lineage |
| GET | `/api/v1/lineage/{pipeline_id}` | Lineage detail |
| GET | `/api/v1/incidents` | Incidents |
| GET | `/api/v1/incidents/{incident_id}` | Incident detail |
| GET | `/api/v1/metrics` | Metrics |
| GET | `/api/v1/logs` | Logs |
| GET | `/api/v1/runs/{run_id}` | Run detail |
| GET | `/api/v1/runs/{run_id}/rca-context` | RCA bundle (run, lineage, DQ, deltas, compiled SQL) |
| GET | `/api/v1/alerts` | Alerts (empty / N/A) |

Legacy (unchanged): `GET /v1/dashboard/overview`.

## Calculation formulas

### Freshness

- `last_success_at` = TARGET `last_updated_at` on latest successful run **on/before range end**, else that run’s `end_time`/`start_time`
- `lag_hours` = **as_of** − last_success_at (as_of = range `to`; `preset=all` uses now)
- SLA default = `DEFAULT_FRESHNESS_SLA_HOURS` (env, default **24**)
- **Fresh** ≤ SLA; **Delayed** ≤ 2×SLA; else **Stale**

### Volume

- Sum TARGET `row_count` / `size_bytes` per run (aggregated by `run_id` first — no SOURCE×TARGET cartesian join)
- Period totals + % change vs previous equal-length window
- Drop thresholds: `VOLUME_DROP_WARN_PCT` (30), `VOLUME_DROP_CRIT_PCT` (60)
- `tool` filter applies to totals, per-pipeline, and series
- Volume health pillar: pipelines in **current ∪ previous**; missing current with prior volume = critical drop

### Incidents

- **Open** = pipeline whose **latest** run is failed/error (one incident per `pipeline_id`)
- **Resolved** = failure in range, then a later successful latest run
- Severity: compilation → critical; runtime/timeout → high; else medium
- Blast radius = count of TARGET assets on the failed run
- Chart series `critical` / `high` / `medium` = **failed runs by severity** (not remapped)
- Chart series `failed_runs` / `success_runs` = run-status counts (honest labels). Legacy keys `open` / `resolved` are aliases of those counts — **not** true open/resolved incident timelines

### Data Quality

- Source: `obs_check_results` (dbt tests + lifecycle / SQL monitors)
- Score: `100 * passed / (passed + warn + failed)` over time window or `score_mode=last_run`
- Query params on `GET /api/v1/observability/quality`:
  - `score_mode=time_window|last_run`
  - `source=all|dbt|monitor`
  - `dataset_id=DB.SCHEMA.TABLE` — per-dataset score + `status_key` (`good|degraded|bad`)
  - `dimension=completeness|uniqueness|accuracy|validity|timeliness`
  - `tag=` — filter by tag
- Trend: `series.quality_score_over_time` (from `obs_dq_daily_rollups`; fallback aggregates raw checks)
- Overview pillars: `data_quality`, `consistency` (accuracy dimension), `uniqueness` (uniqueness dimension)
- Lineage: `target_datasets[]` per pipeline; lineage detail `meta.dataset_quality[]`

### Monitors (write path)

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/v1/monitors` | List monitors (`?pipeline_id=` `?monitor_kind=`) |
| GET | `/v1/monitors/{id}` | Monitor detail |
| POST | `/v1/monitors` | Create monitor (SQL validation, custom rules) |
| PUT | `/v1/monitors/{id}` | Update monitor |
| DELETE | `/v1/monitors/{id}` | Soft-disable (`?hard=true` to delete) |
| GET | `/api/v1/pipelines/{id}/monitors` | Read-only list for dashboard |

Evaluated by poller or `POST /api/v1/ops/evaluate-monitors`.

### Alerts

- Read `obs_alerts` after monitor evaluation

### Schema

- Diff TARGET columns between the latest two **successful** runs per pipeline
- Add column = non-breaking; drop / type change = breaking

### Success rate

- `100 * success_runs / terminal_runs`
- Terminal = status ∈ {success, succeeded, failed, error, cancelled} — **excludes `running`**

### Chart bucketing

- Range ≤ 24h → hourly buckets; longer → daily
- Zero-filled across the selected window (except `preset=all`, which keeps observed buckets only)

### Deltas

- `delta_pct = 100 * (current − previous) / |previous|`
- If `previous == 0` → `null` (undefined; not 100%)
- If `preset=all` → all deltas `null`

### Health pillars

- Stable string ids: `freshness`, `volume`, `data_quality`, `schema`, `consistency`, `uniqueness`

### Active incidents KPI

- Counts open incidents whose `opened_at` falls in the selected window (same definition for value and previous-period delta)
- `preset=all` uses live open count; deltas suppressed

### Total pipelines KPI

- Respects `pipeline_id` / `pipeline_name` / `tool` filters when set

## Known limitations

1. **Incidents** can be derived *and* stored in `obs_incidents` after `POST /api/v1/ops/evaluate-monitors` (poller also runs this).
2. **Alerts** read `obs_alerts` (evaluator-backed). Consistency/Uniqueness pillars aggregate checks by dimension when dbt tests exist.
3. **Incident chart open/resolved** remain run-status proxies for series; prefer `failed_runs` / `success_runs` keys.
4. **Volume bytes** depend on Snowflake `size_bytes` at sync time.
5. **Junk pipelines**: `POST /v1/pipelines` rejects placeholders like `pipeline_id="string"`.
6. **Webhook / Sync** with a specific `dbt_run_id` fails loud (404) if missing — no silent latest fallback.
7. **`obs_run_id`** dual-written on new syncs; run detail accepts vendor `id` or `obs_run_id`.
8. **Rollups / purge / poller**: see `docs/MATURITY_STATUS.md`. Charts still primarily scan raw runs for short presets.
9. **Bindings** support multiple SOURCE/TARGET tools; Sync fan-in collects from each binding (`resolve_pipeline_tool_groups`).
10. **Freemium**: `FREEMIUM_MAX_PIPELINES` (default 50) blocks new pipeline creates when at cap.

## Ops endpoints

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/v1/ops/evaluate-monitors` | Seed/evaluate monitors → alerts/incidents |
| POST | `/api/v1/ops/rollup-daily` | Upsert `obs_metric_rollups_daily` + `obs_dq_daily_rollups` |
| POST | `/api/v1/ops/purge-raw` | Delete raw rows older than `RAW_RETENTION_DAYS` |
| POST | `/api/v1/ops/migrate-bindings` | Backfill SOURCE/ETL/TARGET bindings |
| GET | `/api/v1/pipelines/{id}/bindings` | Declared bindings |
| GET | `/api/v1/pipelines/{id}/monitors` | Pipeline monitors |
| GET | `/api/v1/connectors/types` | Plugin catalog |

Poller: `python application/poller.py` (default every 300s). Compose: `docker-compose.yml`.

## Env vars

| Var | Default | Purpose |
|-----|---------|---------|
| `DB_HOST` / `DB_USER` / `DB_PASSWORD` / `DB_NAME` / `DB_PORT` | — | Metadata MySQL |
| `DEFAULT_FRESHNESS_SLA_HOURS` | `24` | Freshness SLA |
| `ACTIVITY_LOOKBACK_HOURS` | `168` | Pipeline Active if last run within this many hours |
| `VOLUME_DROP_WARN_PCT` | `30` | Volume degraded |
| `VOLUME_DROP_CRIT_PCT` | `60` | Volume failed |
| `SYNC_INTERVAL_SECONDS` | `300` | Poller interval |
| `RAW_RETENTION_DAYS` | `30` | Raw purge window |
| `FREEMIUM_MAX_PIPELINES` | `50` | Max pipelines (new creates) |

## Source layout

- Router: `application/src/api/observability_router.py`
- Schemas: `application/src/api/schemas.py`
- SQL/metrics: `application/src/services/observability/`
- Poller: `application/poller.py`
- Status: `docs/MATURITY_STATUS.md`