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

## Routes

| Method | Path | Screen |
|--------|------|--------|
| GET | `/api/v1/health` | Health |
| GET | `/api/v1/overview` | Overview (full) |
| GET | `/api/v1/overview/kpis` | Overview KPIs |
| GET | `/api/v1/overview/charts` | Overview charts |
| GET | `/api/v1/overview/health` | Health pillars |
| GET | `/api/v1/overview/recent-incidents` | Recent incidents |
| GET | `/api/v1/overview/pipelines` | Overview table |
| GET | `/api/v1/pipelines` | Pipelines list |
| GET | `/api/v1/pipelines/{pipeline_id}` | Pipeline detail |
| GET | `/api/v1/pipelines/{pipeline_id}/runs` | Pipeline runs |
| GET | `/api/v1/observability/freshness` | Freshness |
| GET | `/api/v1/observability/volume` | Volume |
| GET | `/api/v1/observability/quality` | Data Quality (N/A) |
| GET | `/api/v1/observability/schema` | Schema |
| GET | `/api/v1/lineage` | Lineage |
| GET | `/api/v1/lineage/{pipeline_id}` | Lineage detail |
| GET | `/api/v1/incidents` | Incidents |
| GET | `/api/v1/incidents/{incident_id}` | Incident detail |
| GET | `/api/v1/metrics` | Metrics |
| GET | `/api/v1/logs` | Logs |
| GET | `/api/v1/runs/{run_id}` | Run detail |
| GET | `/api/v1/alerts` | Alerts (empty) |

Legacy (unchanged): `GET /v1/dashboard/overview`.

## Calculation formulas

### Freshness

- `last_success_at` = TARGET `last_updated_at` on latest successful run, else that run’s `end_time`/`start_time`
- `lag_hours` = now − last_success_at
- SLA default = `DEFAULT_FRESHNESS_SLA_HOURS` (env, default **24**)
- **Fresh** ≤ SLA; **Delayed** ≤ 2×SLA; else **Stale**

### Volume

- Sum TARGET `row_count` / `size_bytes` per run (aggregated by `run_id` first — no SOURCE×TARGET cartesian join)
- Period totals + % change vs previous equal-length window
- Drop thresholds: `VOLUME_DROP_WARN_PCT` (30), `VOLUME_DROP_CRIT_PCT` (60)

### Incidents

- **Open** = pipeline whose **latest** run is failed/error (one incident per `pipeline_id`)
- **Resolved** = failure in range, then a later successful latest run
- Severity: compilation → critical; runtime/timeout → high; else medium
- Blast radius = count of TARGET assets on the failed run

### Data Quality / Alerts / Consistency / Uniqueness

- Stable empty / `available: false` until check/alert tables are wired

### Schema

- Diff TARGET columns between the latest two **successful** runs per pipeline
- Add column = non-breaking; drop / type change = breaking

### Success rate

- `100 * success_runs / total_runs` where status ∈ {success, succeeded}

## Env vars

| Var | Default | Purpose |
|-----|---------|---------|
| `DB_HOST` / `DB_USER` / `DB_PASSWORD` / `DB_NAME` / `DB_PORT` | — | Metadata MySQL |
| `DEFAULT_FRESHNESS_SLA_HOURS` | `24` | Freshness SLA |
| `VOLUME_DROP_WARN_PCT` | `30` | Volume degraded |
| `VOLUME_DROP_CRIT_PCT` | `60` | Volume failed |

## Source layout

- Router: `application/src/api/observability_router.py`
- Schemas: `application/src/api/schemas.py`
- SQL/metrics: `application/src/services/observability/`
