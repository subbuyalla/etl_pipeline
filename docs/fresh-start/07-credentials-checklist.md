# Credentials checklist (no secrets in git)

Copy `.env.example` → `.env` and fill locally. **Never commit `.env`.**

## Required for Metadata

```env
DATABASE_URL=mysql+pymysql://USER:PASS@HOST:3306/metadata
TENANT_ID=demo
```

## Snowflake connector

**Form fields:**

| Field | Example |
|-------|---------|
| Display name | `Snowflake ANALYTICS_DB` |
| Input mode | `live` |
| Account | `jd97000.ap-southeast-7.aws` |
| User | `Sasi9392` |
| Warehouse | `COMPUTE_WH` |
| Database | `ANALYTICS_DB` |
| Role | `ACCOUNTADMIN` |
| Password env var | `SNOWFLAKE_PASSWORD` |

**In `.env`:**

```env
SNOWFLAKE_PASSWORD=<your password>
```

## dbt Cloud connector

**Form fields:**

| Field | Example |
|-------|---------|
| Display name | `dbt Cloud - Prod` |
| Input mode | `live` |
| Account id | `70506183151322` |
| Project id | `70506183153936` |
| Job id | *(blank = all jobs)* |
| API base URL | `https://li589.us1.dbt.com/api/v2` |
| API token env var | `DBT_CLOUD_API_TOKEN` |

**In `.env`:**

```env
DBT_CLOUD_API_TOKEN=<your dbt cloud token>
```

## After changing `.env`

Restart Metadata API:

```powershell
cd "D:\etl pipeline\packages\metadata"
python -m metadata.api
```

## Your tables (reference)

| Role | Schema.Table |
|------|----------------|
| Source | `ANALYTICS_DB.RAW.STOCK_DATA_RAW` |
| Target | `ANALYTICS_DB.STAGING_STAGING.STG_STOCK_DATA` |
| Target (dbt) | `ANALYTICS_DB.DBT_SM_STAGING.STG_STOCK_DATA` |

## Second Snowflake account

- Create **new** connector instance (does not replace first)
- Use different `password_env` if password differs, e.g. `SNOWFLAKE_PASSWORD_ACCT2`
- Same tenant unless you want isolation → use different `tenant_id`
