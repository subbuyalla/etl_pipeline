# Connector lab — build YOUR Snowflake connector step by step

This lab is **separate** from the production connector (`snowflake`).
Your new tool id: **`snowflake_lab`** (shows in Connectors catalog as "Snowflake (My Lab)").

Production code stays untouched. You learn by owning this class.

## Steps

| Step | What you do | File |
|------|-------------|------|
| 1 | Read the SDK contract | `packages/connector-sdk/.../base.py` |
| 2 | Open your class | `packages/connectors/src/connectors/lab/snowflake_mine.py` |
| 3 | Understand `_connect` | same file |
| 4 | Understand `test_connection` | same file |
| 5 | Understand `_fetch_tables` + `pull_state` | same file |
| 6 | Spec + register | already wired; see below |
| 7 | Put password in `.env` | `SNOWFLAKE_PASSWORD=...` |
| 8 | Run the try script | `python docs/fresh-start/connector-lab/try_snowflake_lab.py` |
| 9 | Or UI: Connectors → **Snowflake (My Lab)** → Test → Sync |

## Rule

- Connector emits **raw** JSON in `RawEnvelope`
- Use `source_system="snowflake"` inside envelopes so **existing normalization** still maps to `etl_datasets`
- Password only from env — never hardcode

## After Snowflake lab

Copy the same pattern for dbt: new class `DbtMineConnector` in `lab/`.
