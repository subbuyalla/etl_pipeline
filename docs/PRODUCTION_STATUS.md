# Production status (no-credential work)

Matrix of production-grade observability items. Update as phases complete.

| Area | Item | Status | Notes |
|------|------|--------|-------|
| Sync | Relations merge (config + dbt) | Done | `_merge_run_table_filters` |
| Sync | dbt tests + manifest storage | Done | `obs_check_results`, `obs_lineage_edges` |
| API | RCA context bundle | Done | `GET /api/v1/runs/{id}/rca-context` — includes `change_since_last_success`, `dq_checks`, `compiled_sql`, lineage slices |
| API | Promoted `relations_json` / `failed_nodes_json` | Done | On `obs_pipeline_runs` |
| API | Quality page from stored checks | Done | `/api/v1/observability/quality` |
| API | Lineage from manifest edges | Done | Merged in lineage page + detail |
| API | Overview DQ pillar | Done | Uses `quality_summary` |
| API | Collector health | Done | `/api/v1/health` + `degraded` flag |
| Ops | Classified Sync/webhook errors | Done | dbt + Snowflake error codes |
| Ops | Webhook async (202) | Done | Background Sync |
| Monitors | dbt test failure | Done | `dbt_test_failure` in lifecycle |
| Monitors | Volume drop baseline | Done | Compares last 2 successful TARGET totals |
| Monitors | Monitor CRUD API | Done | `GET/POST/PUT/DELETE /v1/monitors` |
| API | Consistency / Uniqueness pillars | Done | Dimension aggregates in overview health |
| API | Lineage per-dataset DQ | Done | `target_datasets[]`, `meta.dataset_quality[]` |
| API | SQL validation monitors | Done | Snowflake, Postgres, BigQuery TARGET via `validation.py` |
| DQ | Declarative rules (`obs_dq_rules`) | Done | `GET/POST/PUT/DELETE /v1/dq-rules`; poller + `/ops/evaluate-dq-rules` |
| Sync | N-source / N-target fan-in | Done | `resolve_pipeline_tool_groups`; `source_tool_ids[]` / `target_tool_ids[]` compose |
| Lineage | OpenLineage ingest | Done | `POST /webhooks/openlineage`; `obs_lineage_events` + edge merge |
| Testing | Demo seeder | Done | `scripts/seed_demo_metadata.py` |
| Testing | Unit tests + smoke `--offline` | Done | See `application/test_observability_offline.py` |
| Docs | Go-live checklist + audit script | Done | This doc + `GO_LIVE_CHECKLIST.md` |
| **Blocked** | Live Sync E2E | Needs creds | dbt Cloud token + Snowflake |
| **Blocked** | Tool test 33/33 smoke | Needs creds | Account locked / auth errors |
| **Blocked** | Real manifest ingest | Needs creds | dbt Cloud API |
| **Blocked** | AI assistant re-integration | Needs creds | Depends on live Sync samples |

## Success criteria (no credentials)

- [x] `python scripts/seed_demo_metadata.py` → Quality, Lineage, Overview show KPIs
- [x] `GET /api/v1/runs/demo-run-001/rca-context` works on seeded data
- [x] `python scripts/smoke_api.py --offline` passes
- [x] `/api/v1/health` reports collector heartbeat status
- [x] Sync/webhook return classified errors when vendor fails (unit-tested)

## Next when credentials arrive

1. Fix dbt Cloud API token (401 / account locked)
2. Store secrets on template ETL tools (`has_secret=true`)
3. Run `python scripts/smoke_api.py --live` until 33/33 pass
4. Enable poller in production compose
