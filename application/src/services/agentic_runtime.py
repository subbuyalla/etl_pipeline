"""Autonomous ReAct Multi-Agent Runtime.

Executes iterative multi-step reasoning (Thought -> Action -> Observation -> Reflection)
with automatic error self-correction, specialized sub-agent delegation,
session checkpointing, and Human-in-the-Loop (HITL) gatekeeping.
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

from application.src.services.agent_session_store import (
    create_or_get_session,
    record_pending_action,
    record_step,
)
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

MUTATING_TOOLS = {"create_incident_action", "acknowledge_alert_action", "trigger_sync_action"}

SYSTEM_PROMPT = """You are DataPulse Copilot, a friendly, intelligent, and conversational Enterprise DataOps & Observability assistant.
You operate on an autonomous ReAct reasoning loop with direct access to database telemetry tools.

CONVERSATIONAL GUIDELINES:
1. Speak naturally, warmly, and clearly like a trusted Staff Data Engineer colleague.
2. If the user greets you (e.g. "hi", "hello", "how are you") or asks about your capabilities, converse naturally, introduce yourself, and offer helpful next steps without abruptly dumping metrics.
3. When the user asks about data pipelines, incidents, run failures, or data quality, formulate your investigative plan, call the appropriate tools autonomously, and synthesize the results in clean markdown with tables and key insights.
4. If a tool call errors or returns empty results, reflect on the error, adjust your query parameters, and self-correct.
5. If the user requests an operational mutation (such as creating an incident or triggering a sync), clearly specify the parameters for human approval.
"""


def execute_tool_safely(tool_name: str, args: dict[str, Any], context: dict[str, Any] | None = None) -> dict[str, Any]:
    """Execute a platform tool and safely handle exceptions."""
    ctx = context or {}
    try:
        if tool_name == "list_pipelines":
            return list_registered_pipelines(
                status_filter=args.get("status_filter"),
                tool_filter=args.get("tool_filter") or ctx.get("active_tool"),
            )
        elif tool_name == "diagnose_pipeline_failure":
            return diagnose_root_cause(
                run_id=args.get("run_id") or ctx.get("active_run_id"),
                pipeline_id=args.get("pipeline_id") or ctx.get("active_pipeline_id"),
            )
        elif tool_name == "inspect_data_quality":
            return explain_data_quality(
                pipeline_id=args.get("pipeline_id") or ctx.get("active_pipeline_id"),
                days=int(args.get("days") or 7),
            )
        elif tool_name == "get_observability_health":
            return get_observability_analytics(
                tool_filter=args.get("tool_filter") or ctx.get("active_tool"),
                days=int(args.get("days") or 7),
            )
        elif tool_name == "list_incidents":
            return list_active_incidents(
                status=args.get("status") or "open",
                severity=args.get("severity"),
            )
        elif tool_name == "query_metadata_sql":
            return safe_query_metadata_sql(sql=args.get("sql") or "")
        elif tool_name == "create_incident_action":
            return execute_ops_action(action_type="create_incident", payload=args)
        else:
            return {"ok": False, "error": f"Unknown tool: '{tool_name}'"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


class AgenticRuntime:
    """Multi-Agent ReAct Execution Controller."""

    def __init__(self, session_id: str | None = None, max_hops: int = 5):
        self.session_id = session_id or create_or_get_session()
        self.max_hops = max_hops
        self.step_trace: list[dict[str, Any]] = []

    def run_deterministic_react_chain(self, query: str, context: dict[str, Any]) -> dict[str, Any]:
        """Autonomous multi-hop deterministic agent loop for local/zero-API execution."""
        q = (query or "").lower().strip()
        pid = context.get("active_pipeline_id")
        tool = context.get("active_tool")

        # 0. Conversational Greetings & Capabilities
        greeting_match = re.search(r"^(hi|hello|hey|hola|greetings|good\s+(morning|afternoon|evening)|howdy)\b", q)
        capabilities_match = re.search(r"(who\s+are\s+you|what\s+can\s+you\s+do|help|capabilities|how\s+to\s+use)", q)
        if greeting_match or capabilities_match:
            thought = "User initiated conversational dialogue. Formulating natural introduction and offering relevant Observability workflows."
            self.step_trace.append({
                "step": 1,
                "agent": "Supervisor",
                "thought": thought,
                "tool": "conversational_handler",
                "observation": "Greeting acknowledged.",
            })
            record_step(self.session_id, 1, "Supervisor", thought, "conversational_handler", {}, {"status": "greeted"}, "Warm conversational response prepared.")

            resp = (
                "Hello! 👋 I'm **DataPulse Copilot**, your enterprise DataOps & Observability assistant.\n\n"
                "I'm here to help you monitor pipelines, troubleshoot failures, and track data reliability in real time. Here's what we can do:\n\n"
                "- 🔍 **Pipelines Catalog:** Ask me *\"Give me the list of pipelines\"* to see all active sources, ETL tools, and destinations.\n"
                "- 🛠️ **Root Cause Analysis (RCA):** Ask me *\"Diagnose failure for healthcare_pipeline\"* to inspect stacktraces, failed dbt/Informatica steps, and query history.\n"
                "- 📊 **Data Quality & Anomalies:** Ask me *\"Explain data quality status\"* to view test assertions, pass rates, and null violations.\n"
                "- 🚨 **Incident Management:** Ask me *\"Show active incidents\"* to triage open alerts or propose remediation tickets.\n\n"
                "What would you like to check today?"
            )
            return {
                "ok": True,
                "session_id": self.session_id,
                "response": resp,
                "thought_trace": self.step_trace,
                "actions": [
                    {"label": "List Registered Pipelines", "query": "give me the list of pipelines"},
                    {"label": "Diagnose healthcare_pipeline", "query": "Diagnose failure for healthcare_pipeline"},
                    {"label": "Check Data Quality", "query": "Explain data quality status"},
                    {"label": "Show Active Incidents", "query": "Show active open incidents"},
                ],
            }

        # 0b. Conversational Thanks / Courtesies
        if re.search(r"^(thanks|thank\s+you|awesome|great|cool|perfect|good\s+job)\b", q):
            thought = "User expressed gratitude. Acknowledging conversationally."
            self.step_trace.append({
                "step": 1,
                "agent": "Supervisor",
                "thought": thought,
                "tool": "conversational_handler",
                "observation": "Polite acknowledgment.",
            })
            record_step(self.session_id, 1, "Supervisor", thought, "conversational_handler", {}, {"status": "acknowledged"}, "Acknowledged.")
            return {
                "ok": True,
                "session_id": self.session_id,
                "response": "You're very welcome! 😊 Let me know whenever you'd like to inspect run logs, check data quality scores, or troubleshoot failures.",
                "thought_trace": self.step_trace,
                "actions": [
                    {"label": "List Pipelines", "query": "give me the list of pipelines"},
                    {"label": "Check Data Quality", "query": "Explain data quality status"},
                ],
            }

        # 0c. Incident / Alerts Listing Intent
        if any(k in q for k in ["incident", "incidents", "alert", "alerts", "open issue"]):
            thought = "User requested active incidents triage. Invoking list_active_incidents tool."
            res = execute_tool_safely("list_active_incidents", {"pipeline_id": pid}, context)
            record_step(self.session_id, 1, "Supervisor", thought, "list_active_incidents", {"pipeline_id": pid}, res, "Incidents retrieved.")
            self.step_trace.append({"step": 1, "agent": "Supervisor", "thought": thought, "tool": "list_active_incidents", "observation": f"Found {res.get('total_incidents', 0)} open incidents."})

            incs = res.get("incidents", [])
            lines = [
                f"### Active Open Incidents ({len(incs)} total)",
                "| Severity | Title | Pipeline | Opened At |",
                "| :--- | :--- | :--- | :--- |",
            ]
            for inc in incs:
                sev_badge = "🔴 critical" if inc.get("severity") == "critical" else ("🟡 high" if inc.get("severity") == "high" else f"`{inc.get('severity')}`")
                lines.append(f"| {sev_badge} | **{inc.get('title')}** | `{inc.get('pipeline_name') or inc.get('pipeline_id')}` | {inc.get('created_at')} |")
            lines.append("\n> 💡 **Tip:** Ask *\"Diagnose failure for {pipeline}\"* to investigate the root cause.")

            return {
                "ok": True,
                "session_id": self.session_id,
                "response": "\n".join(lines),
                "thought_trace": self.step_trace,
                "actions": [
                    {"label": f"Diagnose {incs[0].get('pipeline_name') or 'Top Incident'}", "query": f"Diagnose failure for {incs[0].get('pipeline_id')}"} if incs else {},
                    {"label": "Check Data Quality", "query": "Explain data quality status"},
                ],
            }

        # 1. Pipeline Listing Intent (Strict catalog query only)
        catalog_patterns = [
            r"\b(list\s+(of\s+)?pipelines?|all\s+pipelines?|registered\s+pipelines?|show\s+(all\s+)?pipelines?|pipeline\s+catalog|what\s+pipelines?\s+(do\s+we\s+have|are\s+there|exist))\b",
            r"^pipelines?$",
            r"^(give|show)\s+(me\s+)?(all\s+)?(the\s+)?pipelines?$",
        ]
        is_catalog_query = any(re.search(pat, q) for pat in catalog_patterns) and not any(k in q for k in ["null", "fail", "error", "broken", "run", "log", "metric", "dq", "quality", "target", "value", "table", "order", "health", "data"])

        if is_catalog_query:
            # Hop 1: List pipelines
            thought = "User requested a catalog of pipelines. Invoking list_pipelines tool."
            res = execute_tool_safely("list_pipelines", {"tool_filter": tool}, context)
            record_step(self.session_id, 1, "Supervisor", thought, "list_pipelines", {"tool_filter": tool}, res, "Catalog retrieved.")
            self.step_trace.append({"step": 1, "agent": "Supervisor", "thought": thought, "tool": "list_pipelines", "observation": f"Found {res.get('total_pipelines', 0)} pipelines."})

            pipelines = res.get("pipelines", [])
            lines = [
                f"### Registered Data Pipelines ({len(pipelines)} total)",
                "| Pipeline Name | Source | ETL Engine | Target | Status |",
                "| :--- | :--- | :--- | :--- | :--- |",
            ]
            for p in pipelines:
                st = "🟢 Active" if p.get("is_active") else "⚪ Inactive"
                lines.append(f"| **{p.get('name')}** (`{p.get('pipeline_id')[:8]}…`) | `{p.get('source_tool')}` | `{p.get('etl_tool')}` | `{p.get('target_tool')}` | {st} |")
            lines.append("\n> 💡 **Tip:** Click any pipeline name or ask *\"Diagnose failure for {name}\"* to inspect runs and root causes.")

            return {
                "ok": True,
                "session_id": self.session_id,
                "response": "\n".join(lines),
                "thought_trace": self.step_trace,
                "actions": [
                    {"label": f"Diagnose {pipelines[0].get('name')}", "query": f"Diagnose failure for {pipelines[0].get('pipeline_id')}"} if pipelines else {},
                    {"label": "Check Data Quality", "query": "Explain data quality status"},
                ],
            }

        # 2. Multi-Hop Failure Investigation (RCA Specialist Loop)
        if any(k in q for k in ["fail", "error", "broken", "rca", "diagnose", "why did", "crash", "investigate"]):
            # Hop 1: Supervisor identifies target pipeline
            target_pid = pid
            if not target_pid:
                pipe_res = execute_tool_safely("list_pipelines", {}, context)
                pipes = pipe_res.get("pipelines", [])
                for p in pipes:
                    if p.get("name") in q or p.get("pipeline_id") in q:
                        target_pid = p.get("pipeline_id")
                        break
                if not target_pid and pipes:
                    target_pid = pipes[0].get("pipeline_id")

            thought1 = f"Identified investigation target pipeline: {target_pid}. Delegating to RCA Specialist."
            self.step_trace.append({"step": 1, "agent": "Supervisor", "thought": thought1, "tool": "list_pipelines", "observation": f"Target: {target_pid}"})
            record_step(self.session_id, 1, "Supervisor", thought1, "list_pipelines", {}, {"target_pipeline": target_pid}, "Target established.")

            # Hop 2: RCA Specialist diagnoses run and failure stage
            thought2 = f"RCA Specialist analyzing latest run failure, stacktrace, and failed nodes for {target_pid}."
            rca_res = execute_tool_safely("diagnose_pipeline_failure", {"pipeline_id": target_pid}, context)
            self.step_trace.append({"step": 2, "agent": "RCASpecialist", "thought": thought2, "tool": "diagnose_pipeline_failure", "observation": f"Status: {rca_res.get('status')}, Failed node: {rca_res.get('failed_node')}"})
            record_step(self.session_id, 2, "RCASpecialist", thought2, "diagnose_pipeline_failure", {"pipeline_id": target_pid}, rca_res, "Failure profile extracted.")

            # Hop 3: RCA Specialist inspects database query history for failed SQL
            run_id = rca_res.get("run_id")
            thought3 = f"Inspecting target database query history for run {run_id} to identify execution errors."
            sql_query = f"SELECT query_id, execution_status, error_code, error_message, query_text FROM obs_run_query_history WHERE run_id = '{run_id}' LIMIT 5"
            qh_res = execute_tool_safely("query_metadata_sql", {"sql": sql_query}, context)
            failed_queries = [r for r in qh_res.get("rows", []) if str(r.get("execution_status")).upper() == "FAILED" or r.get("error_code")]
            self.step_trace.append({"step": 3, "agent": "RCASpecialist", "thought": thought3, "tool": "query_metadata_sql", "observation": f"Found {len(failed_queries)} failed target database queries."})
            record_step(self.session_id, 3, "RCASpecialist", thought3, "query_metadata_sql", {"sql": sql_query}, qh_res, f"{len(failed_queries)} query failures.")

            # Hop 4: Final Synthesis & Action Proposal
            pname = rca_res.get("pipeline_name") or target_pid
            lines = [
                f"### Multi-Hop Root Cause Analysis: **{pname}**",
                f"- **Target Run:** `{run_id}`",
                f"- **Execution Status:** 🔴 `{rca_res.get('status')}`",
                f"- **Failure Stage:** `{rca_res.get('failure_stage') or 'Execution'}`",
                f"- **Connector / Tool:** `{rca_res.get('tool') or 'Unknown'}`",
                "",
                "#### 🔍 Correlated Evidence",
            ]
            if rca_res.get("failed_node"):
                lines.append(f"- **Failed Task Node:** `{rca_res.get('failed_node')}`")
            if rca_res.get("failed_message"):
                lines.append(f"- **Engine Error Message:**\n  ```text\n  {rca_res.get('failed_message')}\n  ```")

            if failed_queries:
                fq = failed_queries[0]
                lines.extend([
                    "- **Correlated DB Query Error:**",
                    f"  - Error Code: `{fq.get('error_code')}`",
                    f"  - Error: `{fq.get('error_message')}`",
                    f"  - SQL: `{str(fq.get('query_text') or '')[:140]}…`",
                ])

            causes = rca_res.get("probable_causes") or []
            if causes:
                lines.append("\n#### ⚠️ Fault Tree Findings")
                for c in causes:
                    lines.append(f"- {c}")

            remediations = rca_res.get("remediation_steps") or []
            if remediations:
                lines.append("\n#### 🛠️ Recommended Remediation")
                for idx, r in enumerate(remediations, 1):
                    lines.append(f"{idx}. {r}")

            # Proposal for Human-in-the-Loop Action
            action_id = record_pending_action(
                self.session_id,
                "create_incident",
                {
                    "pipeline_id": target_pid,
                    "run_id": run_id,
                    "severity": "high",
                    "title": f"Investigated Failure on {pname} (Run #{run_id})",
                    "description": rca_res.get("failed_message") or "Diagnosed via DataPulse Autonomous Agent.",
                },
                proposed_by="OpsAgent",
            )

            return {
                "ok": True,
                "session_id": self.session_id,
                "response": "\n".join(lines),
                "thought_trace": self.step_trace,
                "pending_approval": {
                    "action_id": action_id,
                    "action_type": "create_incident",
                    "title": f"Create High-Severity Incident for {pname}?",
                    "summary": f"Incident ticket for failed run {run_id}",
                    "payload": {"pipeline_id": target_pid, "run_id": run_id, "severity": "high"},
                },
                "actions": [
                    {"label": f"Approve Incident Creation", "action_id": action_id},
                    {"label": "Check Data Quality", "query": f"Explain data quality for {target_pid}"},
                ],
            }

        # 3. Data Quality & Null Values Investigation (DQ Specialist Loop)
        if any(k in q for k in ["quality", "dq", "checks", "test", "completeness", "accuracy", "validity", "null", "nulls", "missing", "nan", "blank", "uniqueness"]):
            # Extract target pipeline if specified in query text
            target_pid = pid
            target_pname = None
            pipe_res = execute_tool_safely("list_pipelines", {}, context)
            pipes = pipe_res.get("pipelines", [])
            for p in pipes:
                pn = str(p.get("name", "")).lower()
                pid_candidate = str(p.get("pipeline_id", "")).lower()
                if pn in q or pn.replace("_", " ") in q or pid_candidate in q or ("order" in q and "order" in pn) or ("health" in q and "health" in pn):
                    target_pid = p.get("pipeline_id")
                    target_pname = p.get("name")
                    break

            is_null_query = any(k in q for k in ["null", "nulls", "missing", "nan", "blank", "completeness"])
            thought1 = f"User requested {'null value and completeness analysis' if is_null_query else 'Data Quality diagnosis'} for {target_pname or target_pid or 'all pipelines'}. Invoking inspect_data_quality tool."
            dq_res = execute_tool_safely("inspect_data_quality", {"pipeline_id": target_pid, "days": 7}, context)
            self.step_trace.append({"step": 1, "agent": "DQSpecialist", "thought": thought1, "tool": "inspect_data_quality", "observation": f"Overall score: {dq_res.get('overall_score_pct')}%"})
            record_step(self.session_id, 1, "DQSpecialist", thought1, "inspect_data_quality", {"pipeline_id": target_pid}, dq_res, "Quality summary compiled.")

            # Hop 2: For null queries, inspect specific null/completeness rules and check results
            null_rules = []
            if target_pid:
                rule_sql = f"SELECT rule_name, dataset_id, column_name, rule_type, dimension, severity FROM obs_dq_rules WHERE pipeline_id = '{target_pid}' AND (rule_type LIKE '%null%' OR dimension = 'completeness')"
                rule_res = execute_tool_safely("query_metadata_sql", {"sql": rule_sql}, context)
                null_rules = rule_res.get("rows", [])
                thought2 = f"Queried configured null/completeness assertions for {target_pname}. Found {len(null_rules)} rule(s)."
                self.step_trace.append({"step": 2, "agent": "DQSpecialist", "thought": thought2, "tool": "query_metadata_sql", "observation": f"{len(null_rules)} rules found."})
                record_step(self.session_id, 2, "DQSpecialist", thought2, "query_metadata_sql", {"sql": rule_sql}, rule_res, "Rule assertions analyzed.")

            summ = dq_res.get("summary", {})
            score = dq_res.get("overall_score_pct", 100.0)
            badge = "🟢 Healthy" if score >= 90 else ("🟡 Warning" if score >= 75 else "🔴 Degraded")
            title_name = f"for **{target_pname or target_pid}**" if (target_pname or target_pid) else ""

            if is_null_query:
                lines = [
                    f"### Null Value & Completeness Audit {title_name}",
                    f"- **Target Pipeline:** `{target_pname or target_pid or 'Global'}`",
                    f"- **Data Completeness & Quality Score:** **{score}%** ({badge})",
                    f"- **Total Check Evaluations (7d):** `{summ.get('total_evaluations', 0)}` (`{summ.get('passed', 0)} passed`, `{summ.get('failed', 0)} failed`)",
                    "",
                ]
                if null_rules:
                    lines.extend([
                        "#### 📋 Monitored Not-Null & Completeness Rules",
                        "| Rule Name | Target Dataset | Column | Rule Type | Severity |",
                        "| :--- | :--- | :--- | :--- | :--- |",
                    ])
                    for r in null_rules:
                        lines.append(f"| `{r.get('rule_name')}` | `{r.get('dataset_id')}` | `{r.get('column_name') or 'table-level'}` | `{r.get('rule_type')}` | `{r.get('severity')}` |")
                    lines.append("")
                else:
                    lines.append("ℹ️ **Configured Rules:** No dedicated custom not-null assertions defined yet for this pipeline. Standard schema completeness checks are evaluated on each run.\n")

                failures = dq_res.get("recent_failures", [])
                null_failures = [f for f in failures if any(k in str(f.get("message", "")).lower() for k in ["null", "empty", "blank"])]
                if null_failures:
                    lines.extend([
                        "#### 🚨 Detected Null Violations",
                        "| Severity | Check / Monitor | Message | Checked At |",
                        "| :--- | :--- | :--- | :--- |",
                    ])
                    for f in null_failures[:5]:
                        lines.append(f"| `{f.get('severity')}` | `{f.get('monitor_id')}` | {f.get('message')} | {f.get('checked_at')} |")
                elif failures:
                    lines.extend([
                        "#### ⚠️ Other Recent Quality Issues",
                        "| Severity | Check / Monitor | Message | Checked At |",
                        "| :--- | :--- | :--- | :--- |",
                    ])
                    for f in failures[:3]:
                        lines.append(f"| `{f.get('severity')}` | `{f.get('monitor_id')}` | {f.get('message')} | {f.get('checked_at')} |")
                else:
                    lines.append("✅ **Zero null value violations detected** across target database tables in the past 7 days.")
            else:
                lines = [
                    f"### Data Quality Analysis {title_name}",
                    f"- **Overall Quality Score:** **{score}%** ({badge})",
                    f"- **Evaluated Checks (7d):** `{summ.get('total_evaluations', 0)}`",
                    f"- **Passed:** `{summ.get('passed', 0)}` | **Warned:** `{summ.get('warned', 0)}` | **Failed:** `{summ.get('failed', 0)}`",
                    "",
                ]
                failures = dq_res.get("recent_failures", [])
                if failures:
                    lines.extend([
                        "#### 🚨 Recent Violations",
                        "| Severity | Check / Monitor | Message | Checked At |",
                        "| :--- | :--- | :--- | :--- |",
                    ])
                    for f in failures[:5]:
                        lines.append(f"| `{f.get('severity')}` | `{f.get('monitor_id')}` | {f.get('message') or 'Threshold breach'} | {f.get('checked_at')} |")
                else:
                    lines.append("✅ **No critical data quality violations found** in active 7-day window.")

            return {
                "ok": True,
                "session_id": self.session_id,
                "response": "\n".join(lines),
                "thought_trace": self.step_trace,
                "actions": [
                    {"label": f"Diagnose {target_pname or 'Pipeline'}", "query": f"Diagnose failure for {target_pid}"} if target_pid else {},
                    {"label": "Show Daily Quality Trends", "query": "Show daily quality trends"},
                    {"label": "List Registered Pipelines", "query": "give me the list of pipelines"},
                ],
            }

        # 4. Observability Health & SLA Summary (Supervisor + Metrics)
        thought1 = "Retrieving 7-day observability health, failure rates, and open incidents."
        health_res = execute_tool_safely("get_observability_health", {"tool_filter": tool, "days": 7}, context)
        self.step_trace.append({"step": 1, "agent": "Supervisor", "thought": thought1, "tool": "get_observability_health", "observation": f"Success rate: {health_res.get('success_rate_pct')}%"})
        record_step(self.session_id, 1, "Supervisor", thought1, "get_observability_health", {"tool_filter": tool}, health_res, "Health rollups compiled.")

        lines = [
            f"### Observability Health & SLA Summary",
            f"- **Timeframe:** Past 7 Days",
            f"- **Total Executions:** `{health_res.get('total_runs', 0)}`",
            f"- **Success Rate:** **{health_res.get('success_rate_pct')}%** (`{health_res.get('success_runs')} passed`, `{health_res.get('failed_runs')} failed`)",
            f"- **Average Duration:** `{health_res.get('avg_duration_sec')}s`",
            f"- **Rows Processed:** `{health_res.get('total_rows_processed'):,}` rows",
            "",
        ]
        failing = health_res.get("top_failing_pipelines", [])
        if failing:
            lines.extend([
                "#### ⚠️ Pipelines Needing Attention",
                "| Pipeline | Tool | Failures (7d) | Last Failure |",
                "| :--- | :--- | :--- | :--- |",
            ])
            for f in failing:
                lines.append(f"| **{f.get('name')}** | `{f.get('tool')}` | `{f.get('failures')}` | {f.get('last_failed')} |")

        return {
            "ok": True,
            "session_id": self.session_id,
            "response": "\n".join(lines),
            "thought_trace": self.step_trace,
            "actions": [
                {"label": "List Registered Pipelines", "query": "give me the list of pipelines"},
                {"label": "Check Data Quality", "query": "Explain data quality status"},
            ],
        }

    def run_llm_react_loop(self, query: str, context: dict[str, Any], history: list[dict[str, str]] | None = None) -> dict[str, Any]:
        """Execute a full iterative ReAct tool-use loop with self-correction using an LLM (No rule-based fallback)."""
        gemini_key = os.getenv("GEMINI_API_KEY")
        groq_key = os.getenv("GROQ_API_KEY")
        openrouter_key = os.getenv("OPENROUTER_API_KEY")
        openai_key = os.getenv("OPENAI_API_KEY")
        copilot_key = os.getenv("COPILOT_API_KEY")

        if gemini_key:
            api_key = gemini_key
            api_base = os.getenv("GEMINI_API_BASE") or "https://generativelanguage.googleapis.com/v1beta/openai"
            model = os.getenv("GEMINI_MODEL") or "gemini-2.0-flash"
        elif groq_key:
            api_key = groq_key
            api_base = os.getenv("GROQ_API_BASE") or "https://api.groq.com/openai/v1"
            model = os.getenv("GROQ_MODEL") or "llama-3.3-70b-versatile"
        elif openrouter_key:
            api_key = openrouter_key
            api_base = os.getenv("OPENAI_API_BASE") or os.getenv("COPILOT_API_BASE") or "https://openrouter.ai/api/v1"
            model = os.getenv("OPENROUTER_MODEL") or "meta-llama/llama-3.3-70b-instruct:free"
        elif openai_key or copilot_key:
            api_key = openai_key or copilot_key
            api_base = os.getenv("OPENAI_API_BASE") or os.getenv("COPILOT_API_BASE") or "https://api.openai.com/v1"
            model = os.getenv("COPILOT_MODEL") or "gpt-4o-mini"
        else:
            api_key = None
            api_base = None
            model = None

        if not api_key:
            return {
                "ok": False,
                "session_id": self.session_id,
                "response": (
                    "⚠️ **LLM API Key Required (Fallback Removed):**\n\n"
                    "The rule-based fallback has been completely disabled as requested. "
                    "The Copilot is now in 100% LLM mode.\n\n"
                    "Please provide an active API key in root `.env`:\n"
                    "- `OPENROUTER_API_KEY=sk-or-v1-...`\n"
                    "- `GEMINI_API_KEY=AIzaSy...`\n"
                    "- `GROQ_API_KEY=gsk_...`\n"
                    "- `OPENAI_API_KEY=sk-...`"
                ),
                "thought_trace": [],
                "actions": [],
            }

        try:
            import requests

            messages = [{"role": "system", "content": SYSTEM_PROMPT}]
            if history:
                for h in history[-4:]:
                    messages.append({"role": h.get("role", "user"), "content": h.get("content", "")})

            ambient = f"[Page: {context.get('route', 'overview')}"
            if context.get("active_pipeline_id"):
                ambient += f" | Active Pipeline: {context.get('active_pipeline_id')}"
            ambient += "]"
            messages.append({"role": "user", "content": f"{ambient}\n{query}"})

            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
                "HTTP-Referer": "http://localhost:5173",
                "X-Title": "DataPulse Copilot",
            }

            # Multi-hop loop (up to max_hops iterations)
            for hop in range(1, self.max_hops + 1):
                payload = {
                    "model": model,
                    "messages": messages,
                    "tools": COPILOT_TOOLS_SCHEMA,
                    "tool_choice": "auto",
                    "temperature": 0.1,
                    "max_tokens": 800,
                }
                res = requests.post(f"{api_base.rstrip('/')}/chat/completions", headers=headers, json=payload, timeout=15)
                if res.status_code != 200:
                    err_msg = res.text[:300]
                    logger.warning("LLM API call (%s) failed with status %s: %s", model, res.status_code, err_msg)
                    return {
                        "ok": False,
                        "session_id": self.session_id,
                        "response": (
                            f"⚠️ **LLM API Error (HTTP {res.status_code}):**\n"
                            f"The model `{model}` failed with the following response from `{api_base}`:\n"
                            f"```text\n{err_msg}\n```\n"
                            "Please check your API key and permissions in `.env`."
                        ),
                        "thought_trace": self.step_trace,
                        "actions": [],
                    }

                data = res.json()
                assistant_msg = data.get("choices", [{}])[0].get("message", {})
                tool_calls = assistant_msg.get("tool_calls") or []

                if not tool_calls:
                    # Model provided final synthesis
                    final_content = assistant_msg.get("content") or ""
                    return {
                        "ok": True,
                        "session_id": self.session_id,
                        "response": final_content,
                        "thought_trace": self.step_trace,
                        "actions": [],
                    }

                # Model decided to invoke a tool
                first_tool = tool_calls[0]
                tool_name = first_tool.get("function", {}).get("name")
                raw_args = first_tool.get("function", {}).get("arguments") or "{}"
                args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args

                # Check if mutating action requires Human-In-The-Loop approval
                if tool_name in MUTATING_TOOLS:
                    action_id = record_pending_action(self.session_id, tool_name, args, proposed_by="OpsAgent")
                    thought = f"OpsAgent prepared {tool_name} action. Pausing for human approval."
                    self.step_trace.append({"step": hop, "agent": "OpsAgent", "thought": thought, "tool": tool_name, "observation": "Awaiting user approval card."})
                    record_step(self.session_id, hop, "OpsAgent", thought, tool_name, args, {"status": "awaiting_approval"}, "Paused for user approval.")

                    return {
                        "ok": True,
                        "session_id": self.session_id,
                        "response": f"⚠️ **Approval Required:** The agent has prepared the `{tool_name}` action. Please confirm below to proceed.",
                        "thought_trace": self.step_trace,
                        "pending_approval": {
                            "action_id": action_id,
                            "action_type": tool_name,
                            "title": f"Confirm {tool_name}?",
                            "payload": args,
                        },
                        "actions": [{"label": "Approve Action", "action_id": action_id}],
                    }

                # Safe execution
                thought = f"Agent hop {hop}: Invoking tool {tool_name} with parameters {args}."
                observation = execute_tool_safely(tool_name, args, context)

                # Self-correction check: If observation produced an error, feed error back to LLM to self-correct
                reflection = "Observation gathered successfully."
                if not observation.get("ok"):
                    reflection = f"Tool reported error: {observation.get('error')}. Reflection: self-correcting query parameters."

                self.step_trace.append({
                    "step": hop,
                    "agent": "ReActAgent",
                    "thought": thought,
                    "tool": tool_name,
                    "observation": str(observation)[:300],
                    "reflection": reflection,
                })
                record_step(self.session_id, hop, "ReActAgent", thought, tool_name, args, observation, reflection)

                messages.append(assistant_msg)
                messages.append({
                    "role": "tool",
                    "tool_call_id": first_tool.get("id", f"call_{hop}"),
                    "name": tool_name,
                    "content": json.dumps(observation, default=str),
                })

        except Exception as exc:
            logger.warning("ReAct LLM loop error: %s", exc)

        return None
