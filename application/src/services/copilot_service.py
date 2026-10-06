"""DataPulse Copilot Multi-Agent Orchestrator Service.

Provides conversational intelligence, root cause diagnosis, data quality insights,
and operational actions across the entire DataPulse observability estate.
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, AsyncGenerator, Generator

from application.src.services.copilot_tools import (
    diagnose_root_cause,
    execute_ops_action,
    explain_data_quality,
    get_observability_analytics,
    safe_query_metadata_sql,
)

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are DataPulse Copilot, the AI observability and DataOps assistant built into the DataPulse platform.
You assist data engineers, analytics engineers, and DataOps leads with:
1. Answering questions about pipelines, runs, schemas, assets, and connector configurations (Informatica, Snowflake, dbt, etc.).
2. Explaining root causes for pipeline failures by correlating failed nodes, SQL errors, schema drift, and upstream lineage.
3. Diagnosing data quality violations across dimensions (completeness, accuracy, freshness, validity, uniqueness).
4. Generating executive analytics, SLA adherence metrics, and incident summaries.
5. Performing operational actions (such as creating incident tickets or acknowledging alerts).

Always be concise, precise, and actionable. Format responses using GitHub-flavored Markdown with bold text, bullet points, and code blocks where helpful.
When diagnosing an issue, clearly state:
- **What happened** (the immediate failure or symptom)
- **Root cause** (the underlying reason, failed query, schema drift, or upstream block)
- **Remediation steps** (concrete instructions to fix or mitigate)
"""


def _detect_intent(query: str, context: dict[str, Any]) -> str:
    """Classify user prompt into one of the core Copilot intents."""
    q = (query or "").lower().strip()
    if any(k in q for k in ["fail", "error", "broken", "rca", "root cause", "diagnose", "why did", "crash"]):
        return "RCA"
    if any(k in q for k in ["data quality", "dq", "checks", "test", "completeness", "accuracy", "validity", "drift", "schema"]):
        return "DATA_QUALITY"
    if any(k in q for k in ["summary", "overview", "analytics", "sla", "freshness", "health", "metrics", "rate", "mttr"]):
        return "ANALYTICS"
    if any(k in q for k in ["create incident", "file ticket", "ack alert", "acknowledge", "incident"]):
        return "ACTION"
    if any(k in q for k in ["select", "show tables", "count", "list pipelines", "show runs", "how many"]):
        return "SQL_QUERY"
    # Fallback to context
    route = context.get("route", "")
    if "quality" in route:
        return "DATA_QUALITY"
    if "incident" in route:
        return "RCA"
    return "ANALYTICS"


def call_external_llm(
    user_query: str,
    grounded_data: dict[str, Any] | list[Any],
    history: list[dict[str, str]] | None = None,
) -> str | None:
    """Call external OpenAI-compatible or custom LLM if configured via environment variables."""
    openrouter_key = os.getenv("OPENROUTER_API_KEY")
    api_key = openrouter_key or os.getenv("OPENAI_API_KEY") or os.getenv("COPILOT_API_KEY")

    if openrouter_key and not os.getenv("OPENAI_API_BASE") and not os.getenv("COPILOT_API_BASE"):
        api_base = "https://openrouter.ai/api/v1"
        model = os.getenv("OPENROUTER_MODEL") or os.getenv("COPILOT_MODEL") or "meta-llama/llama-3.3-70b-instruct:free"
    else:
        api_base = os.getenv("OPENAI_API_BASE") or os.getenv("COPILOT_API_BASE") or "https://api.openai.com/v1"
        model = os.getenv("COPILOT_MODEL", "gpt-4o-mini")

    is_local_endpoint = "localhost" in api_base or "127.0.0.1" in api_base
    if not api_key and not is_local_endpoint:
        return None

    try:
        import requests

        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        if history:
            for h in history[-4:]:
                messages.append({"role": h.get("role", "user"), "content": h.get("content", "")})

        prompt_with_data = (
            f"User Question: {user_query}\n\n"
            f"Platform Grounded Context Data:\n"
            f"```json\n{json.dumps(grounded_data, default=str)[:3500]}\n```\n\n"
            f"Answer the user's question clearly, concisely, and actionably using the grounded data above."
        )
        messages.append({"role": "user", "content": prompt_with_data})

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key or 'ollama'}",
            "HTTP-Referer": "http://localhost:5173",
            "X-Title": "DataPulse Copilot",
        }
        res = requests.post(
            f"{api_base.rstrip('/')}/chat/completions",
            headers=headers,
            json={"model": model, "messages": messages, "temperature": 0.2, "max_tokens": 800},
            timeout=12,
        )
        if res.status_code == 200:
            data = res.json()
            choices = data.get("choices") or []
            if choices:
                content = choices[0].get("message", {}).get("content")
                if content and content.strip():
                    return content.strip()
    except Exception as exc:
        logger.debug("External LLM not reachable, using native engine: %s", exc)

    return None


def process_copilot_turn(
    message: str,
    context: dict[str, Any] | None = None,
    history: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Process a single copilot turn using the multi-agent orchestrator.

    If an external LLM key is configured (OPENAI_API_KEY, etc.), it can connect to the model.
    Otherwise, it utilizes the native deterministic DataPulse Copilot Engine.
    """
    ctx = context or {}
    user_query = (message or "").strip()
    intent = _detect_intent(user_query, ctx)

    active_pipeline_id = ctx.get("active_pipeline_id")
    active_run_id = ctx.get("active_run_id")
    active_tool = ctx.get("active_tool")

    # Extract pipeline_id or run_id if mentioned directly in user message
    pipe_match = re.search(r"\b(pip_[a-zA-Z0-9_]+)\b", user_query)
    if pipe_match:
        active_pipeline_id = pipe_match.group(1)

    run_match = re.search(r"\b(run_[a-zA-Z0-9_]+)\b", user_query)
    if run_match:
        active_run_id = run_match.group(1)

    # 1. ROOT CAUSE ANALYSIS INTENT
    if intent == "RCA":
        diag = diagnose_root_cause(run_id=active_run_id, pipeline_id=active_pipeline_id)
        if not diag.get("ok"):
            # Provide general failure overview
            analytics = get_observability_analytics(tool_filter=active_tool, days=7)
            top_failing = analytics.get("top_failing_pipelines", [])
            lines = [
                f"### Pipeline Health & Failure Overview",
                f"No specific run was targeted. Here are the top failing pipelines across your estate over the past 7 days:",
                "",
                "| Pipeline | Tool | Failures | Last Failed At |",
                "| :--- | :--- | :--- | :--- |",
            ]
            for tf in top_failing:
                lines.append(f"| **{tf.get('name')}** (`{tf.get('pipeline_id')}`) | `{tf.get('tool')}` | `{tf.get('failures')}` | {tf.get('last_failed')} |")
            lines.extend([
                "",
                "> 💡 **Tip:** Click on any specific failed run in the **Pipelines** or **Incidents** view and ask *\"Why did this run fail?\"* for an instant multi-hop root cause diagnosis.",
            ])
            return {
                "ok": True,
                "intent": "RCA",
                "response": "\n".join(lines),
                "actions": [
                    {"label": "Diagnose Top Failing Pipeline", "query": f"Diagnose failure for {top_failing[0].get('pipeline_id')}" if top_failing else "Show overview metrics"}
                ]
            }

        # Format complete RCA diagnosis
        pname = diag.get("pipeline_name") or diag.get("pipeline_id")
        rid = diag.get("run_id")
        lines = [
            f"### Root Cause Diagnosis for **{pname}**",
            f"- **Target Run:** `{rid}`",
            f"- **Status:** 🔴 `{diag.get('status')}`",
            f"- **Connector / Tool:** `{diag.get('tool') or 'Unknown'}`",
            f"- **Failure Stage:** `{diag.get('failure_stage') or 'Execution'}`",
            "",
            "#### 🔍 Primary Failure Findings",
        ]

        if diag.get("failed_node"):
            lines.append(f"- **Failed Node / Task:** `{diag.get('failed_node')}`")
        if diag.get("failed_message"):
            lines.append(f"- **Error Message:**\n  ```text\n  {diag.get('failed_message')}\n  ```")

        causes = diag.get("probable_causes") or []
        if causes:
            lines.append("\n#### ⚠️ Correlated Causes Detected")
            for c in causes:
                lines.append(f"- {c}")

        remediations = diag.get("remediation_steps") or []
        if remediations:
            lines.append("\n#### 🛠️ Recommended Remediation Steps")
            for idx, r in enumerate(remediations, 1):
                lines.append(f"{idx}. {r}")

        actions = [
            {
                "type": "create_incident",
                "label": f"Create Incident for {pname}",
                "payload": {
                    "pipeline_id": diag.get("pipeline_id"),
                    "run_id": rid,
                    "severity": "high",
                    "title": f"Failure on {pname} (Run #{rid})",
                    "description": diag.get("failed_message") or "Diagnosed via DataPulse Copilot."
                }
            }
        ]

        return {
            "ok": True,
            "intent": "RCA",
            "response": "\n".join(lines),
            "data": diag,
            "actions": actions
        }

    # 2. DATA QUALITY INTENT
    if intent == "DATA_QUALITY":
        dq_info = explain_data_quality(pipeline_id=active_pipeline_id, days=7)
        summ = dq_info.get("summary", {})
        score = dq_info.get("overall_score_pct", 100.0)

        badge = "🟢 Healthy" if score >= 90 else ("🟡 Warning" if score >= 75 else "🔴 Degraded")
        lines = [
            f"### Data Quality Analysis {f'for **{active_pipeline_id}**' if active_pipeline_id else ''}",
            f"- **Overall Quality Score:** **{score}%** ({badge})",
            f"- **Checks Evaluated (7d):** `{summ.get('total_evaluations', 0)}`",
            f"- **Passed:** `{summ.get('passed', 0)}` | **Warned:** `{summ.get('warned', 0)}` | **Failed:** `{summ.get('failed', 0)}`",
            "",
        ]

        failures = dq_info.get("recent_failures", [])
        if failures:
            lines.extend([
                "#### 🚨 Recent Data Quality Violations",
                "| Severity | Check / Monitor | Message | Checked At |",
                "| :--- | :--- | :--- | :--- |",
            ])
            for f in failures[:5]:
                sev_icon = "🔴" if str(f.get("severity")).lower() == "critical" else "🟠"
                lines.append(f"| {sev_icon} `{f.get('severity')}` | `{f.get('monitor_id')}` | {f.get('message') or 'Check threshold breached'} | {f.get('checked_at')} |")
        else:
            lines.append("✅ **No critical data quality violations found** in the active 7-day window.")

        rules = dq_info.get("configured_rules", [])
        if rules:
            lines.extend([
                "",
                "#### 📋 Configured Quality Rules",
            ])
            for r in rules[:4]:
                lines.append(f"- **{r.get('name')}** (`{r.get('dimension') or 'General'}`): checks column `{r.get('column') or 'all'}` ({r.get('type')})")

        return {
            "ok": True,
            "intent": "DATA_QUALITY",
            "response": "\n".join(lines),
            "data": dq_info,
            "actions": [
                {"label": "Show Quality Trends", "query": "Show daily quality trends"},
                {"label": "List Failing Monitors", "query": "Which monitors failed most?"}
            ]
        }

    # 3. EXECUTIVE ANALYTICS / HEALTH SUMMARY
    if intent == "ANALYTICS":
        stats = get_observability_analytics(tool_filter=active_tool, days=7)
        tool_label = f" (Tool: `{active_tool}`)" if active_tool and active_tool != "all" else ""
        lines = [
            f"### Observability Health & SLA Summary{tool_label}",
            f"- **Timeframe:** Past 7 Days",
            f"- **Total Pipeline Executions:** `{stats.get('total_runs', 0)}`",
            f"- **Success Rate:** **{stats.get('success_rate_pct')}%** (`{stats.get('success_runs')} passed`, `{stats.get('failed_runs')} failed`)",
            f"- **Average Duration:** `{stats.get('avg_duration_sec')}s`",
            f"- **Rows Ingested/Processed:** `{stats.get('total_rows_processed'):,}` rows",
            "",
        ]

        failing = stats.get("top_failing_pipelines", [])
        if failing:
            lines.extend([
                "#### ⚠️ Pipelines Needing Attention",
                "| Pipeline | Tool | Failures (7d) | Last Failure |",
                "| :--- | :--- | :--- | :--- |",
            ])
            for f in failing:
                lines.append(f"| **{f.get('name')}** | `{f.get('tool')}` | `{f.get('failures')}` | {f.get('last_failed')} |")

        incidents = stats.get("active_incidents", [])
        if incidents:
            lines.extend([
                "",
                "#### 🚨 Active Open Incidents",
                "| Severity | Title | Pipeline | Opened At |",
                "| :--- | :--- | :--- | :--- |",
            ])
            for inc in incidents:
                lines.append(f"| `{inc.get('severity')}` | **{inc.get('title')}** | `{inc.get('pipeline')}` | {inc.get('opened_at')} |")

        return {
            "ok": True,
            "intent": "ANALYTICS",
            "response": "\n".join(lines),
            "data": stats,
            "actions": [
                {"label": "Diagnose Top Incident", "query": "Diagnose the most recent incident"},
                {"label": "Check Data Quality", "query": "Show data quality status"}
            ]
        }

    # 4. ACTION INTENT (Jira-style direct execution)
    if intent == "ACTION":
        # Check if user wants to create an incident
        if "incident" in user_query.lower() and active_pipeline_id:
            res = execute_ops_action(
                action_type="create_incident",
                payload={
                    "pipeline_id": active_pipeline_id,
                    "severity": "high",
                    "title": f"Incident created for {active_pipeline_id}",
                    "description": f"Triggered from DataPulse Copilot for user request: {user_query}",
                    "run_id": active_run_id
                }
            )
            return {
                "ok": True,
                "intent": "ACTION",
                "response": f"✅ **Incident Created Successfully**\n- **Incident ID:** `{res.get('incident_id')}`\n- **Pipeline:** `{active_pipeline_id}`\n- **Status:** `OPEN`\n- **Severity:** `HIGH`\n\nYou can now view and assign this incident on the **Incidents** triage page.",
                "data": res
            }

        return {
            "ok": True,
            "intent": "ACTION",
            "response": "To execute an operational action, specify the target pipeline or choose an action chip below:",
            "actions": [
                {
                    "type": "create_incident",
                    "label": f"Create Incident for {active_pipeline_id or 'Active Pipeline'}",
                    "payload": {"pipeline_id": active_pipeline_id or "default_pipe", "severity": "high"}
                }
            ]
        }

    # 5. METADATA SQL QUERY INTENT
    if intent == "SQL_QUERY":
        # Auto-synthesize common queries
        clean_q = user_query.strip()
        if clean_q.lower().startswith("select"):
            res = safe_query_metadata_sql(clean_q)
            if not res.get("ok"):
                return {"ok": False, "response": f"⚠️ **SQL Execution Error:** {res.get('error')}"}
            rows = res.get("rows", [])
            if not rows:
                return {"ok": True, "response": "Query returned 0 matching records."}
            headers = list(rows[0].keys())
            table_lines = [
                f"### Query Results ({len(rows)} rows)",
                "| " + " | ".join(headers) + " |",
                "| " + " | ".join(["---"] * len(headers)) + " |",
            ]
            for r in rows[:15]:
                table_lines.append("| " + " | ".join(str(r.get(h, "")) for h in headers) + " |")
            return {"ok": True, "response": "\n".join(table_lines), "data": rows}

        # Otherwise answer pipeline list query
        res = safe_query_metadata_sql("SELECT pipeline_id, pipeline_name, source_tool, etl_tool, target_tool, is_active FROM obs_pipelines LIMIT 20")
        rows = res.get("rows", [])
        lines = [
            "### Registered Data Pipelines",
            "| Pipeline ID | Name | Source | ETL | Target | Active |",
            "| :--- | :--- | :--- | :--- | :--- | :--- |",
        ]
        for r in rows:
            lines.append(f"| `{r.get('pipeline_id')}` | **{r.get('pipeline_name')}** | `{r.get('source_tool') or '-'}` | `{r.get('etl_tool') or '-'}` | `{r.get('target_tool') or '-'}` | {'🟢' if r.get('is_active') else '⚪'} |")
        return {"ok": True, "response": "\n".join(lines), "data": rows}

    # For general questions, ground with current platform overview and invoke LLM if configured
    overview_analytics = get_observability_analytics(tool_filter=active_tool, days=7)
    llm_resp = call_external_llm(user_query, overview_analytics, history)
    if llm_resp:
        return {
            "ok": True,
            "intent": "GENERAL_LLM",
            "response": llm_resp,
            "actions": [
                {"label": "Show Pipeline Health", "query": "What is our overall pipeline health?"},
                {"label": "Explain Data Quality", "query": "Explain data quality status"},
            ]
        }

    return {
        "ok": True,
        "response": f"I analyzed your request. You can ask me to **diagnose failures**, **inspect data quality**, **summarize SLAs**, or **create incidents**.",
        "actions": [
            {"label": "Show Pipeline Health", "query": "What is our overall pipeline health?"},
            {"label": "Explain Data Quality", "query": "Explain data quality status"},
        ]
    }


def get_contextual_suggestions(context: dict[str, Any]) -> list[str]:
    """Generate dynamic prompt suggestions based on current frontend route and active entity."""
    route = (context.get("route") or "").lower()
    pid = context.get("active_pipeline_id")
    tool = context.get("active_tool")

    if "quality" in route:
        return [
            f"Why did the latest DQ check fail for {pid}?" if pid else "Which tables have the lowest data quality score?",
            "Explain completeness vs accuracy test coverage",
            "What data quality checks failed in the last 24 hours?",
            "Recommend new data quality rules for staging tables",
        ]
    elif "incident" in route:
        return [
            "What is the root cause of the latest critical incident?",
            "Show MTTR and incident trends by connector tool",
            "Which pipelines have recurring unresolved incidents?",
            "Create an incident postmortem summary",
        ]
    elif "freshness" in route or "sla" in route:
        return [
            f"Are any SLA thresholds breached for {tool or 'Snowflake'}?",
            "Which pipeline has the longest lag today?",
            "Show average duration spikes over the past 7 days",
        ]
    elif "volume" in route:
        return [
            "Did any pipeline ingest 0 rows today?",
            "Detect volume anomalies in our target tables",
            "Show top 5 largest datasets by row count",
        ]
    else:
        return [
            "Give me a weekly summary of pipeline health",
            "Why did the most recent failed pipeline crash?",
            "Show all active connections and their status",
            "Which connector tool has the highest failure rate?",
        ]
