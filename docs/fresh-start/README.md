# Fresh start — ETL Observability MVP

This folder is the **single source of truth** for restarting the project with a simpler scope.

## What we are building

One platform that answers:

> For each pipeline: **what is the source, what is the ETL tool, what is the target, did it fail, and why?**

```text
SOURCE (Snowflake table)  →  ETL (dbt job)  →  TARGET (Snowflake table)
         │                          │                      │
         └──────────────── One Metadata DB ───────────────┘
                                    │
                          One assistant (your platform)
```

## Read in this order

| # | Doc | Purpose |
|---|-----|---------|
| 1 | [01-architecture.md](./01-architecture.md) | Simple 4-layer architecture |
| 2 | [02-connectors.md](./02-connectors.md) | How to build and use connectors |
| 3 | [03-pipeline-mapping.md](./03-pipeline-mapping.md) | Source / ETL / target linking |
| 4 | [04-single-database.md](./04-single-database.md) | One DB schema for everything |
| 5 | [05-one-assistant.md](./05-one-assistant.md) | Single assistant + tools (external platform OK) |
| 6 | [06-implementation-plan.md](./06-implementation-plan.md) | 4-week MVP plan |
| 7 | [07-credentials-checklist.md](./07-credentials-checklist.md) | Snowflake + dbt setup (no secrets in repo) |
| 8 | [08-what-we-skip.md](./08-what-we-skip.md) | Scope cuts for v1 |
| **9** | **[09-e2e-architecture.md](./09-e2e-architecture.md)** | **Main shareable guide: architecture, tables, pipeline_id, what we can do** |
| **PDF** | **[09-e2e-architecture.pdf](./09-e2e-architecture.pdf)** | **Same guide as PDF with flowchart images** |
| **Lab** | **[connector-lab/](./connector-lab/)** | **Build YOUR Snowflake connector step by step** |

## Services (when running locally)

| Service | Port | Command |
|---------|------|---------|
| Metadata API | `8000` | `cd packages/metadata && python -m metadata.api` |
| Assistants API | `8001` | `cd packages/assistants && python -m assistants.api` |
| Web UI | `5173` | `cd web && npm run dev` |

## Hard rules

1. **Connectors** emit raw vendor JSON only.
2. **Normalization** converts raw → canonical events.
3. **Metadata DB** is the only system of record.
4. **Assistants** read Metadata only — never call Snowflake/dbt directly.
5. **Secrets** live in `.env` — never in the database or git.

## Code locations (existing repo)

| Area | Path |
|------|------|
| Connector SDK | `packages/connector-sdk/` |
| Connectors | `packages/connectors/` |
| Normalization | `packages/normalization/` |
| Metadata API + DB | `packages/metadata/` |
| Assistants (optional for MVP) | `packages/assistants/` |
| UI | `web/` |

## Status (as of fresh start)

| Item | Status |
|------|--------|
| Snowflake live connector | Working (Test + Sync) |
| dbt Cloud live connector | Working (Test + Sync; token in `.env`) |
| Pipeline source/ETL/target auto-link | **Not built — manual `pipeline_io` for MVP** |
| Multiple assistants | **Defer — use one assistant** |
| Scheduled sync | **Not built — manual Sync for now** |
