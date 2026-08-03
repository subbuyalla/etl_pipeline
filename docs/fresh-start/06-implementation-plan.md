# 4-week implementation plan

## Week 1 — Connectors stable

- [ ] Document `.env` vars for Snowflake + dbt
- [ ] Metadata API always on port `8000`
- [ ] Snowflake: Test + Sync on demand
- [ ] dbt Cloud: Test + Sync on demand
- [ ] Verify data in DB: `etl_datasets`, `etl_executions`

**Done when:** Both connectors sync without manual scripts.

## Week 2 — Pipeline mapping

- [ ] Define 1 real pipeline: `stock_etl`
- [ ] Insert `etl_pipeline_io` rows (source / etl / target)
- [ ] API or SQL view: `pipeline_summary(pipeline_id)`
- [ ] Optional: dbt manifest sync for auto lineage

**Done when:** You can query one pipeline and see source + ETL + target + last error.

## Week 3 — Single DB access layer

- [ ] REST endpoints or views for assistant tools
- [ ] `GET /v1/pipelines/{id}/summary` (stretch)
- [ ] Remove dependency on digital twin for demos
- [ ] Document which tables assistants may read

**Done when:** External platform can answer "what failed on stock_etl?" from DB only.

## Week 4 — One assistant

- [ ] One chat UI or external platform integration
- [ ] 5–6 tools wired to Metadata
- [ ] Test: failure explanation uses `error_message` from `etl_executions`
- [ ] Optional: BIRT weekly health report from same DB

**Done when:** Demo: Sync dbt → ask assistant → get root cause from stored logs.

## Daily workflow (after setup)

```text
1. dbt job runs (outside platform)
2. Click Sync on dbt connector (or cron later)
3. Click Sync on Snowflake connector (periodic)
4. Ask assistant OR view Pipelines page
```

## Team split (suggested)

| Person | Focus |
|--------|-------|
| You | Metadata schema, `pipeline_io`, connector fixes |
| Teammate | Assistant platform + tools |
| Shared | Define pipeline inventory (source/ETL/target list) |
