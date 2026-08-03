# AI ETL Observability Platform

Four-layer architecture: **Connector → Normalization → Metadata → AI Assistants**.

```text
Live form / CSV / Twin  →  Connectors  →  Normalization  →  Metadata (:8000)
                                                              ↘  Assistants (:8001)
                                                              ↘  UI (:5173)
```

## Packages

| Package | Role |
|---------|------|
| [packages/connector-sdk](packages/connector-sdk) | Production connector contract (`ConnectorSpec`, `test_connection`, raw envelopes) |
| [packages/connectors](packages/connectors) | Registry + Snowflake/dbt adapters (live / path / csv) |
| [packages/normalization](packages/normalization) | Raw → canonical events (28 tools) |
| [packages/metadata](packages/metadata) | Canonical store + REST API (`:8000`) |
| [packages/simulator](packages/simulator) | Digital Twin mock estate |
| [packages/assistants](packages/assistants) | Agentic Incident RCA + DQ chat + A2A (`:8001`) |
| [web](web) | Reliability UI (`:5173`) |
| [docs/CONNECTORS.md](docs/CONNECTORS.md) | How to add a connector (Monte Carlo–style) |
| [docs/METADATA_LAYER.md](docs/METADATA_LAYER.md) | Metadata entities (incl. `pipeline_io`, lineage `transform`) |
| **[docs/fresh-start/](docs/fresh-start/)** | **Fresh-start MVP plan (start here)** |

## Services (long-running)

| Service | Port | Docs / UI |
|---------|------|-----------|
| Metadata API | `8000` | http://127.0.0.1:8000/docs |
| Assistants API | `8001` | http://127.0.0.1:8001/docs |
| Web UI | `5173` | http://127.0.0.1:5173 |

---

## One-time setup

```powershell
cd "D:\etl pipeline"

pip install -e packages/connector-sdk
pip install -e packages/normalization
pip install -e packages/metadata
pip install -e packages/simulator
pip install -e packages/connectors
pip install -e packages/assistants
# Optional for live Snowflake:
# pip install snowflake-connector-python

cd web
npm install
cd ..
```

### Environment (`.env`)

```env
DATABASE_URL=mysql+pymysql://USER:PASS@HOST:3306/metadata
TENANT_ID=demo

OPENROUTER_API_KEY=sk-or-...
OPENROUTER_MODEL=openrouter/free
METADATA_API_BASE=http://127.0.0.1:8000

# Live connector secrets (names only referenced in UI — values stay in env)
SNOWFLAKE_PASSWORD=
DBT_CLOUD_API_TOKEN=
```

---

## Start every server (3 terminals)

```powershell
cd "D:\etl pipeline\packages\metadata"
python -m metadata.api
```

```powershell
cd "D:\etl pipeline\packages\assistants"
python -m assistants.api
```

```powershell
cd "D:\etl pipeline\web"
npm run dev
```


---

## Connectors (Monte Carlo–style)

In the UI open **Connectors**:

1. Choose **Snowflake**, **dbt**, or **Airflow**
2. Fill connection fields
3. Put passwords/tokens in env vars (e.g. `SNOWFLAKE_PASSWORD`, `AIRFLOW_TOKEN`)
4. **Create connection** → **Test** → **Sync**

CSV upload is available under **advanced / offline**.

Snowflake **live** sync now emits freshness/volume breaches from `LAST_ALTERED` / `ROW_COUNT` (SLA configurable). Airflow syncs DAG runs + task instances (live REST or CSV).

See [docs/CONNECTORS.md](docs/CONNECTORS.md) to add Glue, etc. without changing Assistants.

### Optional: twin / CSV CLI

```powershell
python -m simulator run --ticks 40
python -m connectors ingest --tool snowflake --csv packages/connectors/samples/snowflake_checks.csv --tenant-id demo
python -m connectors ingest --tool dbt --csv packages/connectors/samples/dbt_runs.csv --tenant-id demo
python -m connectors ingest --tool airflow --csv packages/connectors/samples/airflow_runs.csv --tenant-id demo
```

---

## Assistants

UI: **Assistants** → Incident RCA, DQ + Lineage, or A2A orchestrator info.

- **Agentic mode**: **LangGraph** ReAct agents — the model chooses Metadata tools per turn, then answers with grounding. Deterministic planner is fallback only.
- Incident RCA: **Incidents** → **Chat RCA**
- DQ + Lineage: **Monitors** / **Lineage** / **Datasets** → **Explain DQ**
- **A2A (Agent-to-Agent)**:
  - `GET /.well-known/agent.json` — agent cards (RCA, DQ, Orchestrator)
  - `POST /a2a/jsonrpc` — `message/send` with `metadata.skill` = `incident_rca` | `dq_lineage` | `orchestrate`

Both assistants use: **Metadata = truth**, **LLM explains**, **no hallucination** (grounded), **no internal IDs in chat**. See [packages/assistants/README.md](packages/assistants/README.md).

Swagger: http://127.0.0.1:8001/docs

- `POST /v1/chat/sessions` — Incident RCA
- `POST /v1/dq/chat/sessions` — Data Quality + Lineage (bind `dataset_id`)
- `POST /a2a/jsonrpc` — A2A JSON-RPC

---

## Port already in use

```powershell
netstat -ano | findstr ":8000"
netstat -ano | findstr ":8001"
taskkill /PID <pid> /F
```
