# One assistant (not three)

## Decision

Use **one reliability assistant** instead of separate Observability, RCA, and DQ assistants for MVP.

Your teammate's external assistant platform is fine **if it reads Metadata DB via tools**.

## Recommended tools (5–6)

| Tool | Returns |
|------|---------|
| `list_pipelines(tenant_id)` | All pipelines |
| `get_pipeline(pipeline_id)` | Source, ETL, target from `pipeline_io` + last execution |
| `list_executions(pipeline_id, limit)` | Recent runs + errors |
| `get_execution(execution_id)` | Full error log |
| `list_datasets(tenant_id)` | All tables |
| `get_lineage(dataset_id)` | Upstream/downstream (when populated) |

## Example questions → tools

| User asks | Tools used |
|-----------|------------|
| "What failed recently?" | `list_executions` |
| "Why did stock ETL fail?" | `get_pipeline` + `get_execution` |
| "What's downstream of RAW.STOCK_DATA_RAW?" | `get_lineage` |
| "Which tables have no monitors?" | `list_datasets` + `list_monitors` (later) |

## Integration options

### A — Use existing Assistants package

- `packages/assistants/` already has LangGraph + Metadata tools
- Consolidate to one chat endpoint + one prompt

### B — Use your external platform

- Expose Metadata API on `:8000`
- Register HTTP tools in your platform pointing to:
  - `GET /v1/pipelines`
  - `GET /v1/executions`
  - `GET /v1/datasets`
  - `GET /v1/lineage`

### C — Direct SQL (simplest for hackathon)

- Read-only MySQL user on `metadata` database
- Assistant runs parameterized queries

## What to defer

- A2A JSON-RPC orchestrator
- Multiple skill cards
- LangGraph notebook demos (keep for learning only)
