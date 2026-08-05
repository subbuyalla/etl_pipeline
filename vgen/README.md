# VGen ETL Observability Assistant

Chat assistant that answers pipeline health / freshness / volume / lineage / metrics / RCA
using **Metadata MySQL only** (tables filled by the Sync app). No live Snowflake at chat time.

```text
User → Assistant → Observability Agent / RCA Agent → 5 FAAS tools → Metadata MySQL (obs_*)
```

Based on [docs/vgen-use-cases.md](docs/vgen-use-cases.md) and [docs/FAAS-Development-GUIDE.md](docs/FAAS-Development-GUIDE.md).

---

## Folder structure (read this first)

```text
vgen/
├── README.md                          ← you are here
├── scripts/
│   └── wire-ids.js                    ← after push: fill tool/agent ids
├── tools/
│   ├── obs-list-pipelines/            ← discovery / which pipeline?
│   ├── obs-get-pipeline/              ← attach + coarse lineage
│   ├── obs-list-runs/                 ← history / failures (+ time_window)
│   ├── obs-get-run-detail/            ← RCA: error + SOURCE/TARGET assets
│   └── obs-get-health/                ← freshness, volume, metrics
├── agents/
│   ├── observability-agent.yaml
│   └── rca-agent.yaml
└── assistants/
    ├── etl-observability-assistant.yaml
    └── etl-observability-assistant/prompt.json
```

**Important:** VGen FAAS runs **one handler file only**. Do not split into `db.js` / local imports.
All MySQL + time-window logic lives inside each `handler.js`.

Each FAAS tool folder contains:

| File | Purpose |
|------|---------|
| `tool.yaml` | Platform metadata + arguments (leave `id` empty until first push) |
| `handler.js` | **Single file** — `async function handler(event)` + `export default` |
| `package.json` | `"type": "module"` + `mysql2` (npm dep only; no local modules) |
| `payload.json` | Input for `vgen tool test` |

---

## Credentials (user-friendly — no secrets SDK)

Set these on **each** FAAS function environment in the VGen UI (same Metadata DB as Sync):

| Variable | Required | Example |
|----------|----------|---------|
| `DB_HOST` | yes | your RDS host |
| `DB_USER` | yes | admin |
| `DB_PASSWORD` | yes | *** |
| `DB_NAME` | yes | metadata database name |
| `DB_PORT` | no | `3306` |
| `DB_SSL` | no | `true` if needed |

Do **not** use `smriti.secrets` for this MVP.

CLI auth for push/test still uses `vgen/.env` with `vgen_API_KEY` (and related vars) — that is for the CLI only, not for MySQL inside tools.

---

## Push order (required by VGen)

From the `vgen/` directory (with CLI configured):

```bash
# 1) Push tools (CLI writes id into each tool.yaml)
vgen tool push obs-list-pipelines
vgen tool push obs-get-pipeline
vgen tool push obs-list-runs
vgen tool push obs-get-run-detail
vgen tool push obs-get-health

# 2) Wire tool ids into agent skills + agent ids into assistant
node scripts/wire-ids.js

# 3) Push agents, then assistant
vgen agent push observability-agent
vgen agent push rca-agent
node scripts/wire-ids.js
vgen assistant push etl-observability-assistant
```

IDs are **platform UUIDs**, not folder names. Always wire by `id` fields.

Assistant YAML must use API enums: `status: DRAFT` (or `PUBLISHED`, …), `visibility: PRIVATE`, plus `owner`, `type`, `welcomeMessage`, `welcomeDescription`.

---

## Test

```bash
# Edit tools/<name>/payload.json with a real pipeline_id / run_id first
vgen tool test obs-list-pipelines
vgen tool test obs-get-health

vgen assistant test etl-observability-assistant --new-session
```

Starter prompt asks for onboarding guidance (help + suggestions).

---

## What users can ask (assistant will guide)

1. What pipelines do we have?  
2. Is stock_etl healthy?  
3. Today's failures / success rate  
4. Lineage for a pipeline  
5. Why did it fail?  

If the user does not name a pipeline, the assistant **lists options and asks which one**.

---

## Agents vs tools

| Agent | Uses tools |
|-------|------------|
| Observability | all 5 |
| RCA | list-pipelines, list-runs, get-run-detail, get-health |
