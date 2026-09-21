# VITHI / Orbit — Data Observability Dashboard

React + Vite frontend for the **ETL Observability API** (FastAPI).

## Setup

```bash
npm install
cp .env.example .env   # set API_BACKEND_URL locally (gitignored)
npm run dev
npm run build
```

| Variable | Where | Purpose |
|----------|--------|---------|
| `API_BACKEND_URL` | Local `.env` + Vercel env (secret) | Backend host for Vite proxy / Vercel `api/bridge` |

Do **not** commit real hosts or secrets. On Vercel leave `VITE_API_BASE_URL` empty; use `API_BACKEND_URL` only.

Primary dashboard reads: `GET /api/v1/*`  
Config / sync writes: `POST/GET /v1/*`

---

# API issues log (observations)

Issues found while wiring Orbit to the live Observability API.  
Format for each: **Issue → Why it happens → Resolution → Why this resolution**.

---

## 1. Health pillars ignore Run status / Tool filters

### What is the issue?
On Overview, user selects **Run status = Failed** (0 matching runs). KPIs/charts go empty, but **Freshness / Volume / Data Quality / Schema / Uniqueness** still show scores.

### Why this issue comes
- Run KPIs come from `GET /api/v1/overview` (supports `status`, `pipeline_name`, `tool`, date).
- Health comes from `GET /api/v1/overview/health`, whose OpenAPI params are **only date-related** (`preset`, `start_date`, `end_date`, …).
- Health measures **dataset / monitor state**, not “runs with this status”.

### What is the resolution?
- **Do not block or hide** health when run filters are empty — keep showing what the health API returns.
- UI copy clarifies run filters vs health (tip when 0 runs for a status).
- Frontend only sends date params to `/overview/health`.

### Why we solve this way
Matching the API contract avoids fake empty health. Hiding pillars would invent UX the backend does not support and confuse “no failed runs” with “no freshness data”.

---

## 2. Main Overview payload vs Health endpoint

### What is the issue?
`GET /api/v1/overview` sometimes has empty or incomplete `pillars` / `health`, so the UI looked like health was missing even when data existed.

### Why this issue comes
Dashboard health is exposed as a **dedicated** resource: `/api/v1/overview/health` (`items[]` with scores). The aggregated overview document is not always the single source of truth for pillars.

### What is the resolution?
Overview page loads in parallel:
- `/api/v1/overview`
- `/api/v1/overview/health`
- `/api/v1/overview/recent-incidents`
- `/api/v1/logs`
- `/api/v1/filters`

Prefer health `items` for the pillar cards.

### Why we solve this way
Uses the endpoint designed for that UI section instead of guessing from a partial aggregate.

---

## 3. KPI id naming mismatch (`active_incidents` vs `open_incidents`)

### What is the issue?
UI looked for `open_incidents` while API returns `active_incidents` → wrong/empty incident KPI.

### Why this issue comes
Frontend assumed one naming scheme; API uses another.

### What is the resolution?
Read both: `kpiMap.active_incidents || kpiMap.open_incidents`. Prefer API `title` / `display` fields.

### Why we solve this way
Tolerant mapping without hardcoding fake KPI numbers.

---

## 4. Engine / Tool filter on Overview is misleading

### What is the issue?
Selecting **Tool = snowflake** made run KPIs go to **0**, even though the pipeline uses Snowflake as source/target.

### Why this issue comes
`tool` on overview filters **run `tool_name`** (executions are tagged `dbt`), not “any connector in the topology”.

### What is the resolution?
Removed **Engine / Tool** from the Overview filter bar. Keep Pipeline + Run status + Search + date. Tool filtering belongs on Logs / Pipelines where run tool is the right dimension.

### Why we solve this way
Avoids a filter that is “working” per API but wrong for user mental model on Overview.

---

## 5. Status filter returns pipeline rows with `status: N/A`

### What is the issue?
`status=failed` → `total_runs=0`, but `items` can still contain a pipeline with `status: "N/A"`.

### Why this issue comes
API still returns the pipeline entity in the catalog/list while run aggregates for that status are empty.

### What is the resolution?
- Trust KPI/charts from API for the status filter.
- Client hides table rows where status is missing/`N/A` when a run status is selected.
- Show a tip when selected status has 0 runs.

### Why we solve this way
Does not invent run data; only avoids showing a contradictory pipeline row next to “0 runs”.

---

## 6. `preset=all` date range starts at `1970-01-01`

### What is the issue?
UI showed `API window: 1970-01-01 00:00:00 → … (all)` which looks like a bug.

### Why this issue comes
Backend uses Unix-epoch as the open-ended “from” for **all time**.

### What is the resolution?
Display friendly label: **All recorded history** when `from` is epoch; still send `preset=all` to the API.

### Why we solve this way
Presentation fix only — do not change query semantics or invent a different range.

---

## 7. Custom `start_date` / `end_date` still reports `preset: "24h"` in `range`

### What is the issue?
Custom date query returns data for the requested days, but `range.preset` may still say `24h`.

### Why this issue comes
Response metadata `preset` is not always overwritten when absolute dates are used.

### What is the resolution?
UI labels custom ranges from **local filter state** (`custom`), not only `range.preset`.

### Why we solve this way
User-visible label stays honest; we still call the API with `start_date` / `end_date` as documented.

---

## 8. Overview has no `q` (search) query param

### What is the issue?
Sending `q` on overview either does nothing or causes unnecessary refetches.

### Why this issue comes
OpenAPI for `/api/v1/overview` lists `pipeline_name`, `status`, `tool`, dates — **not** `q`.

### What is the resolution?
Search is **client-side only** on the pipeline table. API filters: date, pipeline, run status.

### Why we solve this way
Matches documented API; avoids racey refetches on every keystroke.

---

## 9. Short date presets look “empty” (24h / 7d)

### What is the issue?
Defaulting or selecting last 24h/7d shows N/A / 0 runs even though a pipeline exists.

### Why this issue comes
Last successful run can be **older than the window** (e.g. run on Sep 2, today Sep 10). API correctly returns zero runs in-window.

### What is the resolution?
- Prefer documenting **All time** when exploring sparse history.
- Empty states + tip: try All Time or Success status.
- Do not inject demo/hardcoded runs.

### Why we solve this way
Empty is truthful. Hardcoded demo data would violate “API-only” UI.

---

## 10. Hardcoded / demo UI data vs live API

### What is the issue?
Pages previously seeded `inventory_etl`, fake alerts, fake charts, etc., so UI lied when API failed or was empty.

### Why this issue comes
Early UI built against a single demo pipeline before filters/API contracts were stable.

### What is the resolution?
Overview (and ongoing cleanup): no seeded entities; missing values show `—`. Filters/status/presets from `/api/v1/filters` when available.

### Why we solve this way
UI reflects real backend state for debugging and production trust.

---

## 11. HTTPS frontend + HTTP API (mixed content)

### What is the issue?
Browser blocks `https://…vercel.app` calling `http://HOST:8002` directly.

### Why this issue comes
Browsers forbid mixed active content.

### What is the resolution?
- Relative `/api/v1/…` from the SPA.
- Local: Vite proxy via `API_BACKEND_URL`.
- Vercel: `api/bridge` serverless proxy + `API_BACKEND_URL` env (not in git).

### Why we solve this way
Keeps backend URL out of the client bundle and satisfies HTTPS.

---

## 12. `VITE_API_BASE_URL` vs `API_BACKEND_URL`

### What is the issue?
Putting the HTTP API URL in `VITE_*` exposes it at build time and does not fix mixed content on Vercel.

### Why this issue comes
Vite inlines `VITE_*` into the browser bundle.

### What is the resolution?
Use server-side **`API_BACKEND_URL`** only. Leave Vercel `VITE_API_BASE_URL` empty.

### Why we solve this way
One secret/server env; SPA always uses same-origin paths.

---

## Quick reference — Overview filters vs API

| UI control | Sent to API? | Endpoint behavior |
|------------|--------------|-------------------|
| Date preset / custom | Yes | overview + health + logs + incidents |
| Pipeline | Yes (`pipeline_name`) | overview, logs, incidents |
| Run status | Yes (`status`) | overview run KPIs/charts; **not** health |
| Search | No | Client filter on table only |
| Engine/Tool | Removed from Overview | Was misleading (`tool` = run tool name) |

---

# Data Observability — what we need from the API

Frontend screens (`/observability`, Freshness, Volume, Quality, Schema) already consume live endpoints. Below is what is **missing, thin, or unclear** on the backend so those screens can become truly enterprise-grade. UI currently shows `—` / empty states instead of inventing data.

**Endpoints in use today**

| Screen | Primary API |
|--------|-------------|
| Hub | `GET /api/v1/overview/health` + pillar endpoints |
| Freshness | `GET /api/v1/observability/freshness` (+ `POST .../ops/evaluate-monitors`) |
| Volume | `GET /api/v1/observability/volume` (+ `/v1/monitors`) |
| Data Quality | `GET /api/v1/observability/quality` (+ `/v1/dq-rules`, evaluate DQ) |
| Schema | `GET /api/v1/observability/schema` |

---

## A. Freshness — gaps

| Need | Why |
|------|-----|
| **Stable pipeline identity in UI** | Two items both named `inventory_etl` with different `pipeline_id`s (one has lag, one `lag=N/A` / no `run_id`). Prefer unique `display_name` or `pipeline_key`, or mark inactive/never-synced explicitly (`status_reason`). |
| **`series` / lag history** | Freshness returns empty `series` and `charts`. Need lag-over-time (and/or SLA breach history) for trends. |
| **KPI `delta` / `delta_label`** | All freshness KPI deltas are `null` — no “vs previous window” comparison. |
| **Reliable `as_of` / `last_updated_at`** | Often `null` on stale rows; hard to explain “when checked”. |
| **Explicit inactive vs stale** | `N/A` lag + Stale is confusing. Prefer `status_key=never_synced` / `inactive` vs `stale`. |
| **Filter params parity** | Confirm `pipeline_name`, `status` (fresh/delayed/stale) are supported server-side (UI also filters client-side). |

**Useful extras:** SLA breach count in range; last breach timestamp; link `run_id` when present.

---

## B. Volume — gaps

| Need | Why |
|------|-----|
| **Richer `volume_over_time`** | Often **1 point** (e.g. one day). Need daily/hourly points across the selected preset for a real trend chart. |
| **More pipelines / datasets in `items`** | Frequently **1 item**. Volume UI looks empty without more entities. |
| **`pct_change` populated** | Item field exists but is often `null`. Needed for spike/drop signal. |
| **Anomaly / volume-drop events** | Monitors have `volume` + `crit_pct`, but no list of fired anomalies on the volume page payload. Need `anomalies[]` or alerts tied to volume monitors. |
| **KPI deltas** | All volume KPI deltas `null`. |
| **Dataset / table grain** | Items are pipeline-level. Table-level row counts (SOURCE vs TARGET) would match Monte Carlo-style volume. |

**Useful extras:** expected baseline + threshold from monitor config on each item; bytes + records in series consistently.

---

## C. Data Quality — gaps (best pillar today)

| Need | Why |
|------|-----|
| **Populate relation / column on dbt checks** | Many items have `relation_name`, `column_name`, `dataset_id` = `null` — table is harder to triage. |
| **Longer `quality_score_over_time`** | Series exists but is short (few dates). Need full preset coverage. |
| **KPI deltas** | All quality KPI deltas `null`. |
| **Join DQ rules ↔ check results** | `/v1/dq-rules` exists (e.g. UNIQUE on PRODUCT_ID) but check rows don’t clearly reference `rule_id`. |
| **Clear severity on monitor warns** | Timeliness warns from freshness monitors show `severity=low`; document semantics. |

**Useful extras:** fail/warn counts by pipeline; last failure age; deep link fields for RCA.

---

## D. Schema — gaps (thinnest pillar)

| Need | Why |
|------|-----|
| **Real drift `items[]`** | Currently **0 events** even with 2 schemas monitored. Until runs produce diffs, Schema UI stays empty-state. |
| **`charts.by_type` filled** | Array is empty; impact chart is all zeros. |
| **`series` for drift over time** | Empty — need change count over time. |
| **Monitored schema inventory** | KPI `schemas_monitored=2` but no `schemas[]` / `monitored[]` list (name, database, table, last fingerprint). |
| **Event payload shape** | When items appear, please include: `pipeline_id`, `table_name`, `column_name`, `change_type` (add/drop/type), `from_type`, `to_type`, `impact` (breaking/non_breaking), `detected_at`, `run_id`. |

**Useful extras:** fingerprint / contract version; who owns the schema.

---

## E. Hub / health — gaps

| Need | Why |
|------|-----|
| **`consistency` pillar** | Returned as `available=false` / N/A. Either implement or omit from `pillars` so UI doesn’t show a dead tile. |
| **Pillar `change` / trend** | `change` is always `null` on health pillars. |
| **Health + pipeline filter** | Health only accepts date params (documented). If product wants filtered health, API must add `pipeline_name` (etc.). |
| **Incidents tied to pillars** | Recent incidents often empty; linking `pillar` / `monitor_type` / `pipeline_id` would power hub triage. |

---

## F. Cross-cutting API asks

1. **KPI deltas** — populate `delta` + `delta_label` on all observability KPIs (vs previous period).  
2. **History density** — series length should match preset (`24h`, `7d`, `30d`, `all`), not a single point.  
3. **No demo fallbacks** — keep returning honest empties; frontend already uses `—`.  
4. **Document status enums** — freshness: `fresh|delayed|stale|…`; volume: `healthy|…`; quality: `pass|warn|fail`.  
5. **Monitor evaluation responses** — `evaluate-monitors` / `evaluate-dq-rules` should return a small result summary the UI can flash after “Re-check”.  
6. **Pagination** — quality already has many items (29+); server `pagination` + `limit`/`offset` (or cursor) for large estates.  
7. **Anomalies endpoint (optional)** — e.g. `GET /api/v1/observability/anomalies` for volume/freshness breaches (none exists today).

---

## G. Priority for backend (suggested)

| Priority | Ask | Unlocks |
|----------|-----|---------|
| P0 | Schema drift `items` + monitored schema list | Schema page becomes real |
| P0 | Freshness: inactive vs stale + status reason | Less confusion on duplicate/N/A rows |
| P1 | Volume series denser + `pct_change` / anomalies | Volume looks “alive” |
| P1 | Quality: column/relation on checks + rule_id link | Faster triage |
| P2 | KPI deltas everywhere | Period comparison |
| P2 | Consistency pillar implement or remove | Cleaner hub |
| P2 | Evaluate endpoints return summary payload | Better Re-check UX |

---

## How to add a new observation

Copy this block into this file when you find another API quirk:

```md
## N. Short title

### What is the issue?
…

### Why this issue comes
…

### What is the resolution?
…

### Why we solve this way
…
```
