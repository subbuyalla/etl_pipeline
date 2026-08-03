# Assistants layer (Plan 4)

AI skills that talk **only** to Metadata HTTP APIs, powered by **LangGraph / LangChain `create_agent`**. LLM via OpenRouter. Metadata remains the source of truth; the model explains and is citation-validated.

## Assistants

| Assistant | Bind | API |
|-----------|------|-----|
| Incident RCA | `incident_key` | `POST /v1/chat/sessions` |
| Data Quality + Lineage | `dataset_id` | `POST /v1/dq/chat/sessions` |
| Observability | tenant only | `POST /v1/observability/chat/sessions` |
| A2A Orchestrator | both / overview | `POST /a2a/jsonrpc` |

## Agentic behavior (LangGraph)

Each chat turn runs a **LangGraph-backed** LangChain `create_agent` ReAct loop:

1. Metadata APIs are exposed as LangChain `StructuredTool`s.
2. The LLM (OpenRouter via `ChatOpenAI`) chooses tools and may loop for several steps.
3. Tool results accumulate into evidence; the final answer is **fact-checked**.
4. If LangGraph/OpenRouter is unavailable, a deterministic question→tool planner is used.

**Hands-on lab:** open [`notebooks/langgraph_assistant_walkthrough.ipynb`](notebooks/langgraph_assistant_walkthrough.ipynb) to test each layer offline (FakeMeta + scripted model), then optionally live Metadata/OpenRouter.

A2A orchestrator delegates to RCA/DQ agents; each agent runs the same LangGraph loop.

## A2A (Agent-to-Agent)

Compatible with the A2A JSON-RPC style:

| Endpoint | Purpose |
|----------|---------|
| `GET /.well-known/agent.json` | Catalog of agent cards |
| `GET /.well-known/agent/{skill}.json` | Single card (`rca`, `dq`, `orchestrator`) |
| `POST /a2a/jsonrpc` | `message/send`, `agents/list`, `agent/getCard` |

Example:

```bash
curl -X POST http://127.0.0.1:8001/a2a/jsonrpc \
  -H "Content-Type: application/json" \
  -d "{
    \"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"message/send\",
    \"params\":{
      \"message\":{
        \"parts\":[{\"kind\":\"text\",\"text\":\"Explain the failure and DQ impact\"}],
        \"metadata\":{
          \"tenant_id\":\"demo\",
          \"skill\":\"orchestrate\",
          \"incident_key\":\"YOUR_KEY\",
          \"dataset_id\":\"ANALYTICS.MART.FCT_ORDERS\"
        }
      }
    }
  }"
```

The orchestrator delegates to the RCA and/or DQ agents and returns a merged reply.

## Unified grounding rules

1. **Metadata = truth**
2. **LLM explains** (conversational analyst tone)
3. **No hallucination** — replies stay within evidence
4. **No internal IDs in chat** — strips `alert:` / `inc:` / `check:` / `monitor:` keys
5. **Graceful fallback** — format helpers when the LLM is down
6. **One-shot JSON graphs** — `run_incident_rca` / `run_dq_lineage` still available

## Run

```bash
cd packages/assistants
pip install -e .
python -m assistants.api
```

API: http://127.0.0.1:8001 · Docs: http://127.0.0.1:8001/docs

## Env

| Variable | Default | Purpose |
|----------|---------|---------|
| `OPENROUTER_API_KEY` | — | Required for generate |
| `OPENROUTER_MODEL` | `openrouter/free` | Free model router |
| `METADATA_API_BASE` | `http://127.0.0.1:8000` | Metadata layer |
