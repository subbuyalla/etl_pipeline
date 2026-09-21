# Volume Observability — Full Analysis

**Separate from** the root `README.md` (do not treat this as a replacement).  
**Purpose:** Clear list of issues, root causes, near-term resolution, why that path works, and everything we still need to upgrade for Volume (including gaps vs [Monte Carlo Volume](https://docs.getmontecarlo.com/docs/volume)).

| | |
|--|--|
| **API** | `GET /api/v1/observability/volume` |
| **Related** | `GET /v1/monitors` (volume / `volume_drop`), pipeline runs + run `assets[]` |
| **UI** | Data Observability → **Volume** (`src/pages/DataObservability/Volume.jsx`) |
| **Backend docs** | OpenAPI / Swagger on the live host (e.g. `:8002/docs`) |

---

## 1. What is Volume? (understand first)

### 1.1 One-sentence definitions

| System | Volume means |
|--------|----------------|
| **Ours (today)** | Totals of **TARGET** row counts and byte sizes from **pipeline runs that finished inside the selected date range**. |
| **Monte Carlo** | Whether a **warehouse table’s size** (rows/bytes) is **anomalous** vs history or rules (growth, drop, unchanged). |

They both use “rows” and “bytes”, but they answer **different questions**.

### 1.2 Our calculation (API contract)

Documented in response `meta.formula`:

```text
SUM(TARGET row_count / size_bytes) per run in range
NULL row_count → unknown (excluded / not treated as zero)
Byte scale note: 1 TB = 1024 GB
```

**Step by step:**

1. Resolve time window from `preset` or custom dates (`15m` \| `24h` \| `7d` \| `30d` \| `all`, default often `24h` if omitted).
2. Find **runs** with `end_time` in that window (optionally filtered by `pipeline_id` / `pipeline_name` / `tool`).
3. For each run, take assets where `asset_role = TARGET` → `row_count`, `size_bytes`.
4. **Sum** into KPIs / `summary` / per-pipeline `items` / daily `series.volume_over_time`.
5. UI **pulls** this on load / date change / refresh — **no WebSocket / push**.

**Example from a real success run:**

| Role | Dataset | row_count | size_bytes |
|------|---------|-----------|------------|
| SOURCE | `…RAW_DATA.RAW_INVENTORY` | 208 | 11264 |
| **TARGET** | `…FINAL_DATA.DIM_INVENTORY` | **65** | **4096** |

Volume KPIs show **65 records / 4.0 KB** — SOURCE is **intentionally excluded**.

Run-level fields like `rows_read` (208) / `rows_written` (65) are related but Volume page totals follow **TARGET assets**, not “read” metrics.

### 1.3 What Volume is *not* (common confusion)

| Not this | Why people mix it up |
|----------|----------------------|
| Freshness / “is data late?” | Freshness = lag vs SLA; Volume = size in window |
| Live warehouse COUNT(*) every second | We only update when a **run** is stored |
| SOURCE + TARGET combined | Formula is TARGET only |
| Monte Carlo–style ML band on a table chart | We do pipeline-run sums + simple drop monitors |

### 1.4 Monte Carlo display model (for comparison)

From [Monte Carlo Volume docs](https://docs.getmontecarlo.com/docs/volume) and related volume rules:

- Managed on **Assets** (table), not primarily on “pipeline catalog”.
- Widgets: size over time, **Edit threshold** (automatic ML Low/Med/High, explicit, or disable).
- Alert families: **size increase**, **size decrease**, **unchanged size**.
- Needs **repeated size measurements**; rules often need **≥2 points** before they evaluate.

---

## 2. What the API returns today (so nothing is “hidden”)

### 2.1 Query parameters

| Param | Role |
|-------|------|
| `preset` | `15m` \| `24h` \| `7d` \| `30d` \| `all` (missing → short default; UI should always send preset) |
| `start_date` / `end_date` / `start_time` / `end_time` | Custom window |
| `pipeline_name` / `pipeline_id` / `tool` | Filters |
| `page` / `page_size` | Pagination for `items` |

### 2.2 Response blocks

| Block | Present? | Notes |
|-------|----------|--------|
| `ok`, `generated_at`, `range`, `filters_applied` | Yes | Range is authoritative for “why zero?” |
| `meta.formula`, `meta.byte_note`, `meta.records_available` | Yes | Trust formula here |
| `summary` | Yes | `total_rows`, `total_bytes`, `prev_rows`, `prev_bytes` |
| `kpis[]` | Yes | `data_received`, `records_received`, `pipelines_active`, `runs` — **`delta` often null** |
| `series.volume_over_time[]` | Yes | `timestamp`, `records`, `bytes`, `volume_gb` |
| `charts.by_pipeline[]` | Yes | `records`, `bytes`, `share_pct` |
| `items[]` | Yes | Pipeline rows: status, runs, last_updated_*, **`pct_change` often null** |
| `pagination` | Yes | |
| `pillars`, `incidents`, `pipelines`, `health` | Usually **empty arrays** | Reserved / unused on this payload — UI must not depend on them for Volume |

### 2.3 Monitors (separate endpoint)

- `GET /v1/monitors` — `monitor_type: volume`, `monitor_kind: volume_drop`, `config.crit_pct` (e.g. 60).
- Volume page may show crit % in copy; **fired anomaly list is not on the volume payload**.
- Evaluate path exists as ops (`/api/v1/ops/evaluate-monitors`); Volume does not auto-push alerts into the page body.

### 2.4 UI behavior that is *not* the API

- Default date preset on Volume UI is often **`30d`** (so users see history while API default alone is shorter).
- Frontend **pads** sparse `volume_over_time` into a multi-day chart (zeros between points) — chart length ≠ “API invented daily warehouse scans”.
- Filters (search / status / activity) are partly **client-side** on `items`.

---

## 3. What is the issue? (clear list)

Split into **not a bug**, **real product/ops issues**, and **missing vs Monte Carlo**.

### 3.1 Not a calculation bug

| Observation | Verdict |
|-------------|---------|
| TARGET sum = 65 / 4 KB for the Sep-success run | **Correct** |
| SOURCE 208 not in Volume totals | **By design** |
| Freshness stale + Volume healthy (on 30d) | **Two different metrics** |
| `volume_gb = 0.0` for 4096 bytes | **Rounding**, not missing data |

### 3.2 Issues users hit today

| # | Issue | Symptom | Severity |
|---|--------|---------|----------|
| I1 | **Window empty** | `15m`/`24h`/`7d` = 0 when last run is older | High (looks broken) |
| I2 | **Confusion with Freshness** | Fresh = 0%, lag ~317h; Volume shows 65 on 30d | High (trust) |
| I3 | **Not streaming real-time** | Numbers only change after run + refresh | Medium |
| I4 | **Sparse trend** | One non-zero day; flat GB line | Medium |
| I5 | **Duplicate pipeline names** | Several `inventory_etl` IDs; sync-default may have 0 runs | High (ops) |
| I6 | **Drop monitors idle** | Need ≥2 comparable runs / baseline | Medium |
| I7 | **Null deltas / pct_change** | No “vs previous period” story | Medium |
| I8 | **Pipeline-only grain** | No table Asset Volume page | High vs MC |
| I9 | **Empty satellite arrays** | `incidents` / `pillars` unused on volume response | Low |
| I10 | **Never-synced still “monitored” elsewhere** | Sister pipelines with no run confuse “active” KPIs | Medium |
| I11 | **NULL row_count semantics** | Unknown vs zero hard to see in UI | Medium (when it happens) |
| I12 | **Preset mismatch risk** | API default short window if UI forgets `preset` | Medium |

### 3.3 Live snapshot pattern (example environment)

| Preset | total_rows | Notes |
|--------|------------|-------|
| 15m / 24h / 7d | **0** | Last success outside window |
| 30d / all | **65** | Run included |
| Pipelines | 3 named `inventory_etl` | Only **1** has a success run |
| Volume monitors | 3 × `volume_drop` @ 60% | Cannot learn from one point |

---

## 4. Why does the issue come? (root causes)

| Root cause | Leads to |
|------------|----------|
| **R1. Windowed SUM of runs** | Short presets correctly return 0 |
| **R2. Event-based collection** | No run → no new series points (unlike MC metadata poll) |
| **R3. Different pillar formulas** | Freshness lag ≠ Volume sum |
| **R4. Sparse demo/ops history** | One run → empty charts & dead monitors |
| **R5. Multiple pipeline IDs, one name** | Sync goes to wrong ID → “Volume empty forever” |
| **R6. Monitor model is drop-% only** | No increase / unchanged / ML band |
| **R7. API leaves deltas null** | UI cannot show period comparison |
| **R8. Display unit choice** | GB series understates tiny tables |
| **R9. Product naming** | Calling it “Volume” like Monte Carlo without table grain sets wrong expectations |

---

## 5. What is the resolution? (near term — no fake data)

### 5.1 Operational / process

| ID | Resolution | Owner |
|----|------------|-------|
| N1 | Run **`POST /v1/sync`** (or dbt) regularly on the **sync-default / current** pipeline | Ops |
| N2 | Investigate with **30d** or **all** (or custom dates covering the run) | User / UI default |
| N3 | **Refresh** Volume after sync | User |
| N4 | **One active pipeline** per logical ETL; retire or don’t sync orphans | Ops / Backend |
| N5 | Confirm run `assets[]` always include TARGET `row_count` / `size_bytes` | Backend |

### 5.2 Product / UX (still near term)

| ID | Resolution |
|----|------------|
| N6 | Insight copy: “TARGET rows/bytes from runs **in this range**” |
| N7 | Empty state: “No runs in this window — try 30d / All time” when short preset is empty |
| N8 | Prefer KB/MB labels when `volume_gb ≈ 0` |
| N9 | Show “baseline pending” when &lt; 2 runs for volume_drop |

### 5.3 Why we can solve *this way* (near term)

1. **`meta.formula` already matches the data** for the success run — changing the SUM to invent SOURCE rows or “live COUNT(*)” would lie.
2. Empty short windows are **expected** until there are recent runs — fixing “zeros” by ignoring the date filter would break trust.
3. Freshness and Volume will **both** improve after new syncs (lag drops; volume points appear in short presets).
4. Monte Carlo parity **cannot** be faked in the frontend; it needs **snapshots + thresholds** on the API.
5. Clearing duplicate pipeline IDs removes the most common ops trap (“I synced but Volume still 0”).

**Do not “fix” by:** fabricating series points, counting SOURCE as Volume totals, or marking Freshness fresh without a new TARGET success.

---

## 6. Why upgrade further? (longer term direction)

Keep **two layers** named clearly:

| Layer | Question | Status |
|-------|----------|--------|
| **A. Pipeline Volume (keep)** | Did this pipeline’s TARGET produce rows/bytes in the window? | Exists today |
| **B. Table / Asset Volume (add)** | Is this table’s size normal vs history / rules? | Missing — MC-like |

Why this split:

- Layer A is correct for **ETL observability**.
- Layer B is what users expect when they read Monte Carlo “Volume”.
- Mixing them under one unlabeled chart causes the confusion listed above.

---

## 7. What needs to upgrade — full checklist

### 7.1 Backend / API

- [ ] **U1** Table/asset grain in volume (or sibling endpoint): `dataset_id`, table name, role SOURCE|TARGET
- [ ] **U2** Periodic **size snapshots** (metadata or COUNT) between runs
- [ ] **U3** Change metrics: Δ rows, Δ bytes, DoD / WoW
- [ ] **U4** Populate `kpi.delta`, `item.pct_change`, use `summary.prev_*` consistently
- [ ] **U5** Denser `volume_over_time` for `all` and long presets (daily/hourly)
- [ ] **U6** Anomalies on payload: `anomalies[]` or link to alerts (increase / decrease / unchanged)
- [ ] **U7** Richer monitors beyond `volume_drop` + `crit_pct` (absolute size, growth rate, unchanged duration; optional sensitivity)
- [ ] **U8** Attach monitor baseline + threshold on each `item`
- [ ] **U9** Status enums documented: when `healthy` / `warning` / `critical`; distinguish `never_synced` vs empty window
- [ ] **U10** NULL vs 0: explicit `records_available` / unknown flags per item
- [ ] **U11** Stable pipeline display identity when names collide
- [ ] **U12** Optional: volume evaluate / last evaluation timestamp on page

### 7.2 Frontend / UX

- [ ] **U13** Copy that matches Layer A until Layer B exists
- [ ] **U14** Smart empty state (short window empty + hint longer range)
- [ ] **U15** Adaptive units (B/KB/MB/GB) — don’t lead with dead GB series
- [ ] **U16** Baseline-pending banner for volume monitors
- [ ] **U17** Surface `pct_change` / deltas when API fills them
- [ ] **U18** Table Volume section when U1/U2 ship
- [ ] **U19** Show anomaly list when U6 ships
- [ ] **U20** Always send `preset` (already preferred in `buildDateParams`)

### 7.3 Operations

- [ ] **U21** Scheduled or frequent sync on sync-default
- [ ] **U22** Deduplicate / archive unused `pipeline_id`s
- [ ] **U23** Validate every success run writes TARGET (and optionally SOURCE) assets with counts
- [ ] **U24** Alert routing for volume anomalies (audience / channel) once U6 exists

### 7.4 Docs / QA acceptance

- [ ] **U25** Keep this file updated when API `meta.formula` changes
- [ ] **U26** Fixture: one run outside 24h → Volume 24h=0, 30d&gt;0 (regression for “false bug”)
- [ ] **U27** Fixture: Freshness stale + Volume non-zero same run (document expected)

---

## 8. Debug decision tree

```text
Volume shows 0?
├─ Check response.range / preset
│  └─ Run end_time outside range? → Widen preset (N2) — not an API bug
├─ Check pipelines: which pipeline_id was synced?
│  └─ Sync-default has 0 runs, another ID has data? → Align IDs (N4)
├─ Check last run assets[]
│  └─ No TARGET row_count? → Backend write path (N5 / U10)
├─ Freshness also bad?
│  └─ Expected until new success; Volume can still show old window totals on 30d
└─ Numbers stale after sync?
   └─ Refresh UI (N3); confirm new run appears under that pipeline_id
```

---

## 9. Side-by-side: ours vs Monte Carlo (display)

| Display / capability | Ours now | Monte Carlo |
|----------------------|----------|-------------|
| Object | Pipeline | Table / asset |
| Primary number | Sum of TARGET rows in range | Current / historical table size |
| Chart | Run-derived daily buckets (often sparse) | Size over time + threshold band |
| Threshold UI | Monitor `crit_pct` (drop) | Edit threshold: auto / explicit / off |
| Alert types | Drop (limited) | Increase, decrease, unchanged |
| Collection | On run success | Scheduled metadata (+ optional COUNT) |
| “Real-time” | Pull after run | Continuous monitoring cadence |

**Gap to close for MC-like Volume:** U1–U7 primarily.

---

## 10. Priority order (suggested)

| Priority | Items | Outcome |
|----------|--------|---------|
| **P0** | N1–N5, N6–N7, U20–U23 | Stop false “Volume broken” reports |
| **P1** | U4, U5, U9–U11, U15–U17 | Trustworthy pipeline Volume UX |
| **P2** | U1–U3, U6–U8, U18–U19, U24 | Monte Carlo–class table Volume |
| **P3** | U12, U25–U27 | Hardening / docs / QA |

---

## 11. Summary table

| Question | Answer |
|----------|--------|
| **What is Volume?** | Ours = TARGET run totals in a time window. MC = table size anomaly monitoring. |
| **What is the issue?** | Empty short windows, Freshness confusion, no stream, sparse charts, duplicate pipelines, weak monitors/deltas, no table grain. |
| **Is SUM wrong?** | No — for the known success run, TARGET 65 / 4 KB is correct. |
| **What is the resolution (now)?** | Sync the right pipeline often, use wide presets, refresh, clarify copy; do not invent data. |
| **Why solve that way?** | Formula is honest; zeros are window/ops; MC features need new APIs. |
| **Why does it happen?** | Windowed event SUM + sparse history + naming/expectation mismatch. |
| **What to upgrade?** | Snapshots, table grain, change metrics, anomalies, deltas, denser series, richer monitors, UX units/empty states, ops hygiene. |

---

## 12. Related links

- Monte Carlo Volume: https://docs.getmontecarlo.com/docs/volume  
- Monte Carlo Volume Rules (thresholds / growth): https://docs.getmontecarlo.com/docs/setting-up-volume-rules  
- Project root README Volume API gaps (section B): `README.md` — left unchanged; this file is the deep dive.

---

*Last expanded for completeness (API shape, UI padding, monitors, debug tree, MC gap, priorities). Does not modify root `README.md`.*
