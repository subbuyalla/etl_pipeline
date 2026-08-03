from __future__ import annotations

from typing import Any

PROTOCOL_VERSION = "0.3.0"
BASE = "http://127.0.0.1:8001"


def incident_rca_card(*, base_url: str = BASE) -> dict[str, Any]:
    return {
        "name": "Incident RCA Agent",
        "description": "Root-cause analysis for ETL pipeline/dataset incidents using Metadata evidence.",
        "url": f"{base_url}/a2a/jsonrpc",
        "provider": {"organization": "ETL Observability Platform"},
        "version": "1.0.0",
        "protocolVersion": PROTOCOL_VERSION,
        "capabilities": {"streaming": False, "pushNotifications": False},
        "defaultInputModes": ["text/plain", "application/json"],
        "defaultOutputModes": ["text/plain", "application/json"],
        "skills": [
            {
                "id": "incident_rca",
                "name": "Incident root cause analysis",
                "description": "Explain why an incident happened, quote errors, blast radius, next steps.",
                "tags": ["rca", "incident", "pipeline", "etl"],
                "examples": ["What failed and why?", "What is the blast radius?"],
                "inputModes": ["text/plain"],
                "outputModes": ["text/plain"],
            }
        ],
        "additionalInterfaces": [
            {"url": f"{base_url}/a2a/jsonrpc", "protocolBinding": "JSONRPC"}
        ],
    }


def dq_lineage_card(*, base_url: str = BASE) -> dict[str, Any]:
    return {
        "name": "Data Quality + Lineage Agent",
        "description": "Explain freshness/volume/schema/distribution issues and lineage impact.",
        "url": f"{base_url}/a2a/jsonrpc",
        "provider": {"organization": "ETL Observability Platform"},
        "version": "1.0.0",
        "protocolVersion": PROTOCOL_VERSION,
        "capabilities": {"streaming": False, "pushNotifications": False},
        "defaultInputModes": ["text/plain", "application/json"],
        "defaultOutputModes": ["text/plain", "application/json"],
        "skills": [
            {
                "id": "dq_lineage",
                "name": "Data quality and lineage",
                "description": "Analyze DQ checks and upstream/downstream impact for a dataset.",
                "tags": ["dq", "lineage", "freshness", "volume"],
                "examples": ["Which checks failed?", "What is upstream of this table?"],
                "inputModes": ["text/plain"],
                "outputModes": ["text/plain"],
            }
        ],
        "additionalInterfaces": [
            {"url": f"{base_url}/a2a/jsonrpc", "protocolBinding": "JSONRPC"}
        ],
    }


def orchestrator_card(*, base_url: str = BASE) -> dict[str, Any]:
    return {
        "name": "ETL Observability Orchestrator",
        "description": (
            "Routes questions to Incident RCA or DQ+Lineage agents via A2A, "
            "then returns a combined grounded answer."
        ),
        "url": f"{base_url}/a2a/jsonrpc",
        "provider": {"organization": "ETL Observability Platform"},
        "version": "1.0.0",
        "protocolVersion": PROTOCOL_VERSION,
        "capabilities": {"streaming": False, "pushNotifications": False},
        "defaultInputModes": ["text/plain", "application/json"],
        "defaultOutputModes": ["text/plain", "application/json"],
        "skills": [
            {
                "id": "orchestrate",
                "name": "Multi-agent orchestration",
                "description": "Delegate to RCA and/or DQ agents depending on the question.",
                "tags": ["a2a", "orchestrator", "routing"],
                "examples": [
                    "Pipeline failed and the mart table looks empty — explain both.",
                ],
                "inputModes": ["text/plain", "application/json"],
                "outputModes": ["text/plain", "application/json"],
            }
        ],
        "additionalInterfaces": [
            {"url": f"{base_url}/a2a/jsonrpc", "protocolBinding": "JSONRPC"}
        ],
    }


def observability_card(*, base_url: str = BASE) -> dict[str, Any]:
    return {
        "name": "Observability Agent",
        "description": (
            "Tenant-wide reliability overview: pipelines, datasets, open incidents, "
            "monitors, alerts, and what to fix first."
        ),
        "url": f"{base_url}/a2a/jsonrpc",
        "provider": {"organization": "ETL Observability Platform"},
        "version": "1.0.0",
        "protocolVersion": PROTOCOL_VERSION,
        "capabilities": {"streaming": False, "pushNotifications": False},
        "defaultInputModes": ["text/plain", "application/json"],
        "defaultOutputModes": ["text/plain", "application/json"],
        "skills": [
            {
                "id": "observability",
                "name": "Reliability observability",
                "description": "Summarize estate health and prioritize open issues from Metadata.",
                "tags": ["observability", "overview", "incidents", "monitors", "alerts"],
                "examples": [
                    "Give me a reliability overview",
                    "What should I look at first?",
                    "Which pipelines are failing?",
                ],
                "inputModes": ["text/plain"],
                "outputModes": ["text/plain"],
            }
        ],
        "additionalInterfaces": [
            {"url": f"{base_url}/a2a/jsonrpc", "protocolBinding": "JSONRPC"}
        ],
    }


def catalog(*, base_url: str = BASE) -> dict[str, Any]:
    return {
        "protocolVersion": PROTOCOL_VERSION,
        "agents": [
            incident_rca_card(base_url=base_url),
            dq_lineage_card(base_url=base_url),
            observability_card(base_url=base_url),
            orchestrator_card(base_url=base_url),
        ],
    }
