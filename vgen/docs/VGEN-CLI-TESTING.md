# Testing tools and assistants with the VGen CLI

The `vgen` binary in this repo supports **`tool test`** (FAAS) and **`assistant test`**. This is the supported way to exercise deployed functions and the full assistant flow.

## Prerequisites

- `.env` (or environment) with **`vgen_API_KEY`**, **`vgen_BASE_URL`**, and JWT-related vars as required by your org.
- **`vgen config validate`** returns OK.
- Tools must be **pushed** at least once so each `tools/<name>/tool.yaml` contains a valid **`functionId`** (FAAS). If `vgen tool test` says `No functionId found`, run:

  ```bash
  vgen tool push mysql-test-connection
  vgen tool push mysql-introspect-schema
  vgen tool push mysql-execute-sql
  vgen tool push mysql-dml-confirm-hitlconfig
  ```

  If the CLI does not write `functionId` into YAML, use **`vgen tool pull <name>`** after the tool exists on the server, or copy **`functionId`** from the VGen UI / API into `tool.yaml`.

- **FAAS environment** for MySQL tools: set **`DB_HOST`**, **`DB_USER`**, **`DB_PASSWORD`**, **`DB_NAME`**, optional **`DB_SSL`**, etc. on the deployed function (same as local `.env` for parity).
- **HITL card in Smriti:** before **`vgen tool test mysql-dml-confirm-hitlconfig`** (or production use), push the bundled card:

  ```bash
  vgen hitl push mysql-dml-confirm
  ```

  See [HITL-MYSQL-DML.md](HITL-MYSQL-DML.md) for `hitl/mysql-dml-confirm/` layout and slug (`MYSQL_DML_HITL_SLUG` defaults to `mysql-dml-confirm`).

## Tool test (`payload.json`)

Each FAAS tool folder includes **`payload.json`**: JSON sent to the function. Shape matches the FAAS handler:

```json
{
  "context": {
    "input": { }
  }
}
```

`input` must match the tool’s **`arguments`** in `tool.yaml`.

Run from repo root:

```bash
vgen tool test mysql-test-connection
vgen tool test mysql-introspect-schema
vgen tool test mysql-execute-sql
vgen tool test mysql-dml-confirm-hitlconfig
```

Optional override directory:

```bash
vgen tool test mysql-test-connection --tools-dir tools
```

Edit **`tools/<name>/payload.json`** to try different inputs (e.g. change `sql` for `mysql_execute_sql`).

## Assistant test (`prompt.json`)

The assistant **`sql-assistant`** uses YAML at **`assistants/sql-assistant.yaml`**. The CLI expects a prompt file at:

**`assistants/sql-assistant/prompt.json`**

This repo includes a starter **`prompt.json`** with both **`prompt`** and **`question`** fields (same text). Newer API agent-assign requires **`question`**; keep both for CLI compatibility. Write the file as UTF-8 **without BOM** (PowerShell `Set-Content -Encoding utf8` adds a BOM that breaks the CLI).

Run:

```bash
vgen assistant test sql-assistant
```

Start a **new** conversation session:

```bash
vgen assistant test sql-assistant --new-session
```

## Agent wiring

`assistant test` runs the **assistant** end-to-end (it uses the assistant’s configured **agents** → **skills**). Ensure **`agents/sql-assistant.yaml`** lists the correct **tool IDs** in `skills` and **`assistants/sql-assistant.yaml`** lists the correct **agent id** in `agents` (use **`node scripts/sync-vgen-skills.mjs`** after pushes, then re-push agent/assistant if needed).

## Reference

```text
vgen hitl push <NAME>       # hitl/<NAME>/ with meta.yaml + config.json
vgen tool test <NAME>       # uses tools/<NAME>/payload.json
vgen assistant test <NAME>  # uses assistants/<NAME>/prompt.json
```

See also [vgen-use-cases.md](vgen-use-cases.md).
