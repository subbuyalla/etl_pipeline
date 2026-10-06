"""DataPulse Copilot Agentic AI Orchestrator Service.

Implements an enterprise ReAct (Reasoning + Acting) tool-use architecture,
mirroring Atlassian Intelligence (Jira Copilot / Rovo) and Claude tool use.
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

from application.src.services.copilot_tools import (
    COPILOT_TOOLS_SCHEMA,
    diagnose_root_cause,
    execute_ops_action,
    explain_data_quality,
    get_observability_analytics,
    list_active_incidents,
    list_registered_pipelines,
    safe_query_metadata_sql,
)

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are DataPulse Copilot, an enterprise DataOps & Observability AI Agent built into the DataPulse platform.
You operate identically to Jira's Atlassian Intelligence / Rovo: you have direct access to platform tools (Skills) to inspect pipelines, diagnose failures, verify data quality, and query metadata.

CRITICAL INSTRUCTIONS:
1. Always invoke the relevant tool to retrieve ground-truth data from the platform. Do NOT guess pipeline names, IDs, or metrics.
2. If the user asks for pipelines (e.g. "give me the list of pipelines"), ALWAYS call the `list_pipelines` tool.
3. If the user asks about an error or failure, ALWAYS call the `diagnose_pipeline_failure` tool.
4. If the user asks about data quality, rules, or test checks, ALWAYS call the `inspect_data_quality` tool.
5. If the user asks for SLA or health metrics, ALWAYS call the `get_observability_health` tool.
6. Format your final response with GitHub-flavored Markdown using clean tables, bold key metrics, and actionable bullet points.
"""


def execute_tool(tool_name: str, args: dict[str, Any], context: dict[str, Any] | None = None) -> dict[str, Any]:
    """Execute a declared platform tool / skill against MySQL metadata."""
    ctx = context or {}
    logger.info("Executing Copilot tool: %s with args: %s", tool_name, args)

    try:
        if tool_name == "list_pipelines":
            status_filter = args.get("status_filter")
            tool_filter = args.get("tool_filter") or ctx.get("active_tool")
            return list_registered_pipelines(status_filter=status_filter, tool_filter=tool_filter)

        elif tool_name == "diagnose_pipeline_failure":
            pipeline_id = args.get("pipeline_id") or ctx.get("active_pipeline_id")
            run_id = args.get("run_id") or ctx.get("active_run_id")
            return diagnose_root_cause(run_id=run_id, pipeline_id=pipeline_id)

        elif tool_name == "inspect_data_quality":
            pipeline_id = args.get("pipeline_id") or ctx.get("active_pipeline_id")
            days = int(args.get("days") or 7)
            return explain_data_quality(pipeline_id=pipeline_id, days=days)

        elif tool_name == "get_observability_health":
            tool_filter = args.get("tool_filter") or ctx.get("active_tool")
            days = int(args.get("days") or 7)
            return get_observability_analytics(tool_filter=tool_filter, days=days)

        elif tool_name == "list_incidents":
            status = args.get("status") or "open"
            severity = args.get("severity")
            return list_active_incidents(status=status, severity=severity)

        elif tool_name == "query_metadata_sql":
            sql = args.get("sql") or ""
            return safe_query_metadata_sql(sql=sql)

        elif tool_name == "create_incident_action":
            return execute_ops_action(action_type="create_incident", payload=args)

        else:
            return {"ok": False, "error": f"Unknown tool: '{tool_name}'"}
    except Exception as exc:
        logger.exception("Error executing tool %s: %s", tool_name, exc)
        return {"ok": False, "error": str(exc)}


def format_tool_observation_markdown(tool_name: str, result: dict[str, Any], user_query: str = "") -> dict[str, Any]:
    """Format structured tool output into rich, professional Markdown with action chips."""
    if not result.get("ok"):
        return {
            "response": f"⚠️ **Tool Execution Error ({tool_name}):** {result.get('error') or 'Operation failed.'}",
            "actions": [{"label": "Show Pipeline Health", "query": "What is our overall pipeline health?"}]
        }

    # 1. LIST PIPELINES OBSERVATION
    if tool_name == "list_pipelines":
        pipelines = result.get("pipelines", [])
        total = result.get("total_pipelines", len(pipelines))
        if not pipelines:
            return {
                "response": "No pipelines registered yet in the metadata store.",
                "actions": [{"label": "View Integrations", "query": "Show active connections"}]
            }

        lines = [
            f"### Registered Data Pipelines ({total} total)",
            "| Pipeline Name | Source | ETL Engine | Target | Status |",
            "| :--- | :--- | :--- | :--- | :--- |",
        ]
        for p in pipelines:
            st_badge = "🟢 Active" if p.get("is_active") else "⚪ Inactive"
            lines.append(
                f"| **{p.get('name')}** (`{p.get('pipeline_id')[:8]}…`) "
                f"| `{p.get('source_tool')}` (`{p.get('source_schema')}`) "
                f"| `{p.get('etl_tool')}` "
                f"| `{p.get('target_tool')}` (`{p.get('target_schema')}`) "
                f"| {st_badge} |"
            )

        lines.extend([
            "",
            "> 💡 **Tip:** Click any pipeline name or ask *\"Diagnose failure for {name}\"* to inspect runs and root causes.",
        ])

        actions = [
            {"label": f"Diagnose {pipelines[0].get('name')}", "query": f"Diagnose latest run for {pipelines[0].get('pipeline_id')}"},
            {"label": "Check Data Quality", "query": "Explain data quality status"},
        ]
        return {"response": "\n".join(lines), "actions": actions}

    # 2. DIAGNOSE PIPELINE FAILURE OBSERVATION (RCA)
    if tool_name == "diagnose_pipeline_failure":
        pname = result.get("pipeline_name") or result.get("pipeline_id")
        rid = result.get("run_id")
        lines = [
            f"### Root Cause Diagnosis for **{pname}**",
            f"- **Target Run:** `{rid}`",
            f"- **Execution Status:** 🔴 `{result.get('status')}`",
            f"- **Connector / Tool:** `{result.get('tool') or 'Unknown'}`",
            f"- **Failure Stage:** `{result.get('failure_stage') or 'Execution'}`",
            "",
            "#### 🔍 Primary Failure Findings",
        ]
        if result.get("failed_node"):
            lines.append(f"- **Failed Node / Task:** `{result.get('failed_node')}`")
        if result.get("failed_message"):
            lines.append(f"- **Error Message:**\n  ```text\n  {result.get('failed_message')}\n  ```")

        causes = result.get("probable_causes") or []
        if causes:
            lines.append("\n#### ⚠️ Correlated Causes Detected")
            for c in causes:
                lines.append(f"- {c}")

        remediations = result.get("remediation_steps") or []
        if remediations:
            lines.append("\n#### 🛠️ Recommended Remediation Steps")
            for idx, r in enumerate(remediations, 1):
                lines.append(f"{idx}. {r}")

        actions = [
            {
                "type": "create_incident",
                "label": f"Create Incident for {pname}",
                "payload": {
                    "pipeline_id": result.get("pipeline_id"),
                    "run_id": rid,
                    "severity": "high",
                    "title": f"Failure on {pname} (Run #{rid})",
                    "description": result.get("failed_message") or "Diagnosed via DataPulse Copilot."
                }
            }
        ]
        return {"response": "\n".join(lines), "actions": actions}

    # 3. DATA QUALITY OBSERVATION
    if tool_name == "inspect_data_quality":
        summ = result.get("summary", {})
        score = result.get("overall_score_pct", 100.0)
        badge = "🟢 Healthy" if score >= 90 else ("🟡 Warning" if score >= 75 else "🔴 Degraded")
        target_pid = result.get('pipeline_id')
        pid_suffix = f" for **{target_pid}**" if target_pid else ""
        lines = [
            f"### Data Quality Analysis{pid_suffix}",
            f"- **Overall Quality Score:** **{score}%** ({badge})",
            f"- **Checks Evaluated (7d):** `{summ.get('total_evaluations', 0)}`",
            f"- **Passed:** `{summ.get('passed', 0)}` | **Warned:** `{summ.get('warned', 0)}` | **Failed:** `{summ.get('failed', 0)}`",
            "",
        ]
        failures = result.get("recent_failures", [])
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

        return {
            "response": "\n".join(lines),
            "actions": [
                {"label": "Show Quality Trends", "query": "Show daily quality trends"},
                {"label": "List Registered Pipelines", "query": "give me the list of pipelines"}
            ]
        }

    # 4. OBSERVABILITY HEALTH OBSERVATION
    if tool_name == "get_observability_health":
        lines = [
            f"### Observability Health & SLA Summary",
            f"- **Timeframe:** Past 7 Days",
            f"- **Total Pipeline Executions:** `{result.get('total_runs', 0)}`",
            f"- **Success Rate:** **{result.get('success_rate_pct')}%** (`{result.get('success_runs')} passed`, `{result.get('failed_runs')} failed`)",
            f"- **Average Duration:** `{result.get('avg_duration_sec')}s`",
            f"- **Rows Ingested/Processed:** `{result.get('total_rows_processed'):,}` rows",
            "",
        ]
        failing = result.get("top_failing_pipelines", [])
        if failing:
            lines.extend([
                "#### ⚠️ Pipelines Needing Attention",
                "| Pipeline | Tool | Failures (7d) | Last Failure |",
                "| :--- | :--- | :--- | :--- |",
            ])
            for f in failing:
                lines.append(f"| **{f.get('name')}** | `{f.get('tool')}` | `{f.get('failures')}` | {f.get('last_failed')} |")

        incidents = result.get("active_incidents", [])
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
            "response": "\n".join(lines),
            "actions": [
                {"label": "List Registered Pipelines", "query": "give me the list of pipelines"},
                {"label": "Check Data Quality", "query": "Explain data quality status"}
            ]
        }

    # 5. LIST INCIDENTS OBSERVATION
    if tool_name == "list_incidents":
        incs = result.get("incidents", [])
        if not incs:
            return {
                "response": "✅ **No active open incidents** found across pipelines.",
                "actions": [{"label": "View Pipeline Health", "query": "What is our overall pipeline health?"}]
            }
        lines = [
            f"### Active Incidents ({len(incs)} total)",
            "| Severity | Title | Pipeline | Opened At |",
            "| :--- | :--- | :--- | :--- |",
        ]
        for inc in incs:
            sev_icon = "🔴" if inc.get("severity") == "critical" else "🟠"
            lines.append(f"| {sev_icon} `{inc.get('severity')}` | **{inc.get('title')}** | `{inc.get('pipeline_name')}` | {inc.get('opened_at')} |")

        return {
            "response": "\n".join(lines),
            "actions": [
                {"label": "Diagnose Top Incident", "query": f"Diagnose failure for {incs[0].get('pipeline_id')}"},
                {"label": "List Registered Pipelines", "query": "give me the list of pipelines"}
            ]
        }

    # 6. SQL QUERY OBSERVATION
    if tool_name == "query_metadata_sql":
        rows = result.get("rows", [])
        if not rows:
            return {"response": "Query returned 0 matching records.", "actions": []}
        headers = list(rows[0].keys())
        lines = [
            f"### Query Results ({len(rows)} rows)",
            "| " + " | ".join(headers) + " |",
            "| " + " | ".join(["---"] * len(headers)) + " |",
        ]
        for r in rows[:15]:
            lines.append("| " + " | ".join(str(r.get(h, "")) for h in headers) + " |")
        return {"response": "\n".join(lines), "actions": []}

    return {"response": json.dumps(result, indent=2), "actions": []}


def _select_tool_semantically(query: str, context: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Deterministic agent semantic router for zero-API / local execution.

    Directly matches the user's intent to the appropriate skill/tool.
    """
    q = (query or "").lower().strip()
    pid = context.get("active_pipeline_id")
    run_id = context.get("active_run_id")
    tool = context.get("active_tool")

    # Match pipelines inquiry
    if any(k in q for k in ["pipeline", "pipelines"]):
        if any(k in q for k in ["list", "show", "give", "what", "all", "registered", "available", "names", "catalog"]):
            return "list_pipelines", {"tool_filter": tool}
        if any(k in q for k in ["fail", "error", "broken", "rca", "diagnose", "crash", "why"]):
            return "diagnose_pipeline_failure", {"pipeline_id": pid, "run_id": run_id}

    # Match failure / RCA
    if any(k in q for k in ["fail", "failed", "error", "broken", "rca", "diagnose", "why did", "crash", "root cause"]):
        return "diagnose_pipeline_failure", {"pipeline_id": pid, "run_id": run_id}

    # Match incidents
    if any(k in q for k in ["incident", "incidents", "triage", "ticket"]):
        if "create" in q or "open incident" in q:
            return "create_incident_action", {"pipeline_id": pid or "default_pipe", "title": query, "severity": "high"}
        return "list_incidents", {"status": "open"}

    # Match Data Quality
    if any(k in q for k in ["quality", "dq", "checks", "test", "completeness", "accuracy", "validity", "drift", "schema"]):
        return "inspect_data_quality", {"pipeline_id": pid, "days": 7}

    # Match SQL
    if q.startswith("select ") or q.startswith("show "):
        return "query_metadata_sql", {"sql": query}

    # Match Health / SLA / Overview
    if any(k in q for k in ["summary", "overview", "analytics", "sla", "health", "metrics", "rate", "status"]):
        return "get_observability_health", {"tool_filter": tool, "days": 7}

    # Fallback to route context
    route = context.get("route", "")
    if "pipeline" in route:
        return "list_pipelines", {"tool_filter": tool}
    if "quality" in route:
        return "inspect_data_quality", {"pipeline_id": pid, "days": 7}
    if "incident" in route:
        return "list_incidents", {"status": "open"}

    return "list_pipelines", {"tool_filter": tool}


def call_llm_with_tools(
    user_query: str,
    context: dict[str, Any],
    history: list[dict[str, str]] | None = None,
) -> dict[str, Any] | None:
    """Execute a true multi-step ReAct Tool-Calling loop if an external LLM is configured."""
    openrouter_key = os.getenv("OPENROUTER_API_KEY")
    api_key = openrouter_key or os.getenv("OPENAI_API_KEY") or os.getenv("COPILOT_API_KEY")

    if openrouter_key and not os.getenv("OPENAI_API_BASE") and not os.getenv("COPILOT_API_BASE"):
        api_base = "https://openrouter.ai/api/v1"
        model = os.getenv("OPENROUTER_MODEL") or "meta-llama/llama-3.3-70b-instruct:free"
    else:
        api_base = os.getenv("OPENAI_API_BASE") or os.getenv("COPILOT_API_BASE") or "https://api.openai.com/v1"
        model = os.getenv("COPILOT_MODEL", "gpt-4o-mini")

    is_local = "localhost" in api_base or "127.0.0.1" in api_base
    if not api_key and not is_local:
        return None

    try:
        import requests

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
        ]
        if history:
            for h in history[-4:]:
                messages.append({"role": h.get("role", "user"), "content": h.get("content", "")})

        # Append current user prompt with ambient context
        ambient = f"[Page: {context.get('route', 'overview')}"
        if context.get("active_pipeline_id"):
            ambient += f" | Active Pipeline: {context.get('active_pipeline_id')}"
        if context.get("active_tool"):
            ambient += f" | Active Tool: {context.get('active_tool')}"
        ambient += "]"

        messages.append({"role": "user", "content": f"{ambient}\n{user_query}"})

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key or 'ollama'}",
            "HTTP-Referer": "http://localhost:5173",
            "X-Title": "DataPulse Copilot",
        }

        # Step 1: LLM Reasoning & Tool Selection
        payload = {
            "model": model,
            "messages": messages,
            "tools": COPILOT_TOOLS_SCHEMA,
            "tool_choice": "auto",
            "temperature": 0.1,
            "max_tokens": 800,
        }

        res = requests.post(f"{api_base.rstrip('/')}/chat/completions", headers=headers, json=payload, timeout=12)
        if res.status_code != 200:
            logger.warning("LLM request failed (status %s): %s", res.status_code, res.text[:200])
            return None

        data = res.json()
        choice = data.get("choices", [{}])[0]
        assistant_msg = choice.get("message", {})
        tool_calls = assistant_msg.get("tool_calls") or []

        # Step 2: If model decided to call tools, execute them and feed observations back
        if tool_calls:
            first_tool = tool_calls[0]
            func_name = first_tool.get("function", {}).get("name")
            raw_args = first_tool.get("function", {}).get("arguments") or "{}"
            try:
                args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
            except Exception:
                args = {}

            # Execute tool
            observation = execute_tool(func_name, args, context)

            # Step 3: Second LLM turn to synthesize final answer from tool output
            messages.append(assistant_msg)
            messages.append({
                "role": "tool",
                "tool_call_id": first_tool.get("id", "call_1"),
                "name": func_name,
                "content": json.dumps(observation, default=str),
            })

            synthesis_res = requests.post(
                f"{api_base.rstrip('/')}/chat/completions",
                headers=headers,
                json={"model": model, "messages": messages, "temperature": 0.2, "max_tokens": 800},
                timeout=12,
            )
            if synthesis_res.status_code == 200:
                synth_data = synthesis_res.json()
                final_content = synth_data.get("choices", [{}])[0].get("message", {}).get("content")
                if final_content:
                    return {
                        "ok": True,
                        "intent": func_name,
                        "response": final_content,
                        "data": observation,
                        "actions": format_tool_observation_markdown(func_name, observation).get("actions", [])
                    }

            # If 2nd turn timed out, fallback to structured tool observation
            formatted = format_tool_observation_markdown(func_name, observation, user_query)
            return {
                "ok": True,
                "intent": func_name,
                "response": formatted["response"],
                "data": observation,
                "actions": formatted["actions"]
            }

        # If model answered directly without tools
        content = assistant_msg.get("content")
        if content:
            return {"ok": True, "intent": "CHAT", "response": content, "actions": []}

    except Exception as exc:
        logger.warning("Agentic LLM tool-calling loop error: %s", exc)

    return None


def process_copilot_turn(
    message: str,
    context: dict[str, Any] | None = None,
    history: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Process a single copilot turn using the Autonomous ReAct Agentic Runtime."""
    from application.src.services.agentic_runtime import AgenticRuntime

    ctx = context or {}
    user_query = (message or "").strip()
    runtime = AgenticRuntime(session_id=ctx.get("session_id"))

    # 1. Attempt Multi-Step ReAct Tool-Calling loop if external LLM is configured
    llm_result = runtime.run_llm_react_loop(query=user_query, context=ctx, history=history)
    if llm_result and llm_result.get("response"):
        return llm_result

    # 2. Autonomous Multi-Hop ReAct Chain with self-correction & HITL approval proposals
    return runtime.run_deterministic_react_chain(query=user_query, context=ctx)


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
            "give me the list of pipelines",
            "Why did the most recent failed pipeline crash?",
            "Show active incidents",
            "Explain data quality status",
        ]
