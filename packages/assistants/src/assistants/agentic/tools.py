from __future__ import annotations

from typing import Any, Callable

from assistants.metadata_client import MetadataClient

ToolFn = Callable[[MetadataClient, str, dict[str, Any]], Any]


def _tool_get_incident(client: MetadataClient, tenant_id: str, args: dict[str, Any]) -> Any:
    return client.get_incident(tenant_id, str(args["incident_key"]))


def _tool_list_executions(client: MetadataClient, tenant_id: str, args: dict[str, Any]) -> Any:
    return client.list_executions(tenant_id, pipeline_id=args.get("pipeline_id"), limit=int(args.get("limit") or 40))


def _tool_pipeline_dashboard(client: MetadataClient, tenant_id: str, args: dict[str, Any]) -> Any:
    return client.get_pipeline_dashboard(tenant_id, str(args["pipeline_id"]))


def _tool_list_check_results(client: MetadataClient, tenant_id: str, args: dict[str, Any]) -> Any:
    return client.list_check_results(
        tenant_id,
        asset_id=args.get("asset_id"),
        monitor_type=args.get("monitor_type"),
        limit=int(args.get("limit") or 40),
    )


def _tool_list_monitors(client: MetadataClient, tenant_id: str, args: dict[str, Any]) -> Any:
    rows = client.list_monitors(tenant_id)
    asset_id = args.get("asset_id")
    if asset_id:
        rows = [m for m in rows if m.get("asset_id") == asset_id]
    return rows[: int(args.get("limit") or 40)]


def _tool_list_alerts(client: MetadataClient, tenant_id: str, args: dict[str, Any]) -> Any:
    return client.list_alerts(tenant_id, asset_id=args.get("asset_id"), limit=int(args.get("limit") or 40))


def _tool_blast_radius(client: MetadataClient, tenant_id: str, args: dict[str, Any]) -> Any:
    return client.get_blast_radius(tenant_id, str(args["dataset_id"]))


def _tool_list_lineage(client: MetadataClient, tenant_id: str, args: dict[str, Any]) -> Any:
    return client.list_lineage(tenant_id, dataset_id=args.get("dataset_id"), limit=int(args.get("limit") or 40))


def _tool_get_dataset(client: MetadataClient, tenant_id: str, args: dict[str, Any]) -> Any:
    return client.get_dataset(tenant_id, str(args["dataset_id"]))


def _tool_list_metrics(client: MetadataClient, tenant_id: str, args: dict[str, Any]) -> Any:
    # Client may not have list_metrics yet — call via _get if needed
    if hasattr(client, "list_metrics"):
        return client.list_metrics(  # type: ignore[attr-defined]
            tenant_id, asset_id=args.get("asset_id"), name=args.get("name"), limit=int(args.get("limit") or 100)
        )
    data = client._get(  # noqa: SLF001
        "/v1/metrics",
        {"tenant_id": tenant_id, "asset_id": args.get("asset_id"), "name": args.get("name"), "limit": args.get("limit") or 100},
    )
    return list(data.get("items") or [])


def _tool_list_incidents(client: MetadataClient, tenant_id: str, args: dict[str, Any]) -> Any:
    rows = client.list_incidents(tenant_id, asset_id=args.get("asset_id"), limit=int(args.get("limit") or 50))
    status = args.get("status")
    if status:
        rows = [r for r in rows if (r.get("status") or "").lower() == str(status).lower()]
    return rows


def _tool_list_pipelines(client: MetadataClient, tenant_id: str, args: dict[str, Any]) -> Any:
    if hasattr(client, "list_pipelines"):
        return client.list_pipelines(tenant_id, limit=int(args.get("limit") or 100))  # type: ignore[attr-defined]
    data = client._get("/v1/pipelines", {"tenant_id": tenant_id, "limit": args.get("limit") or 100})  # noqa: SLF001
    return list(data.get("items") or [])


def _tool_list_datasets(client: MetadataClient, tenant_id: str, args: dict[str, Any]) -> Any:
    return client.list_datasets(tenant_id, limit=int(args.get("limit") or 100))


def _tool_reliability_overview(client: MetadataClient, tenant_id: str, args: dict[str, Any]) -> Any:
    """Composite snapshot matching the Reliability overview UI cards."""
    pipelines = _tool_list_pipelines(client, tenant_id, {"limit": 200})
    datasets = _tool_list_datasets(client, tenant_id, {"limit": 200})
    incidents = _tool_list_incidents(client, tenant_id, {"limit": 100})
    alerts = _tool_list_alerts(client, tenant_id, {"limit": 100})
    open_inc = [i for i in incidents if (i.get("status") or "").lower() == "open"]
    failed = [p for p in pipelines if "fail" in (p.get("status") or "").lower()]
    checks = _tool_list_check_results(client, tenant_id, {"limit": 100})
    failing_checks = [
        c
        for c in checks
        if (c.get("status") or "").lower() in {"anomalous", "failed", "breach", "error"}
    ]
    return {
        "pipeline_count": len(pipelines),
        "dataset_count": len(datasets),
        "open_incident_count": len(open_inc),
        "alert_count": len(alerts),
        "failed_pipeline_count": len(failed),
        "failing_check_count": len(failing_checks),
        "top_open_incidents": [
            {
                "title": i.get("title"),
                "severity": i.get("severity"),
                "status": i.get("status"),
                "root_asset_id": i.get("root_asset_id"),
                "blast_radius_count": i.get("blast_radius_count"),
            }
            for i in open_inc[:8]
        ],
        "failed_pipelines": [
            {"pipeline_id": p.get("pipeline_id"), "status": p.get("status"), "source_tool": p.get("source_tool")}
            for p in failed[:8]
        ],
    }


TOOLS: dict[str, dict[str, Any]] = {
    "get_incident": {
        "description": "Fetch one incident by key",
        "fn": _tool_get_incident,
        "required": ["incident_key"],
        "properties": {
            "incident_key": {"type": "string", "description": "Incident key from the bound context"},
        },
    },
    "list_executions": {
        "description": "List pipeline/task run history",
        "fn": _tool_list_executions,
        "required": [],
        "properties": {
            "pipeline_id": {"type": "string", "description": "Pipeline / DAG id"},
            "limit": {"type": "integer", "description": "Max rows (default 40)"},
        },
    },
    "get_pipeline_dashboard": {
        "description": "Pipeline metrics, IO, related datasets, recent runs",
        "fn": _tool_pipeline_dashboard,
        "required": ["pipeline_id"],
        "properties": {
            "pipeline_id": {"type": "string", "description": "Pipeline / DAG id"},
        },
    },
    "list_check_results": {
        "description": "Data quality check results for an asset",
        "fn": _tool_list_check_results,
        "required": [],
        "properties": {
            "asset_id": {"type": "string", "description": "Dataset or pipeline asset id"},
            "monitor_type": {"type": "string", "description": "Optional: freshness|volume|schema|distribution"},
            "limit": {"type": "integer", "description": "Max rows (default 40)"},
        },
    },
    "list_monitors": {
        "description": "Monitors configured for an asset",
        "fn": _tool_list_monitors,
        "required": [],
        "properties": {
            "asset_id": {"type": "string", "description": "Filter by asset id"},
            "limit": {"type": "integer", "description": "Max rows (default 40)"},
        },
    },
    "list_alerts": {
        "description": "Alerts for an asset",
        "fn": _tool_list_alerts,
        "required": [],
        "properties": {
            "asset_id": {"type": "string", "description": "Filter by asset id"},
            "limit": {"type": "integer", "description": "Max rows (default 40)"},
        },
    },
    "get_blast_radius": {
        "description": "Downstream datasets affected by a dataset issue",
        "fn": _tool_blast_radius,
        "required": ["dataset_id"],
        "properties": {
            "dataset_id": {"type": "string", "description": "Dataset FQN"},
        },
    },
    "list_lineage": {
        "description": "Upstream/downstream lineage edges",
        "fn": _tool_list_lineage,
        "required": [],
        "properties": {
            "dataset_id": {"type": "string", "description": "Dataset FQN"},
            "limit": {"type": "integer", "description": "Max edges (default 40)"},
        },
    },
    "get_dataset": {
        "description": "Dataset catalog details",
        "fn": _tool_get_dataset,
        "required": ["dataset_id"],
        "properties": {
            "dataset_id": {"type": "string", "description": "Dataset FQN"},
        },
    },
    "list_metrics": {
        "description": "Time-series metrics for charts (row_count, lag, etc.)",
        "fn": _tool_list_metrics,
        "required": [],
        "properties": {
            "asset_id": {"type": "string", "description": "Asset id"},
            "name": {"type": "string", "description": "Metric name e.g. row_count"},
            "limit": {"type": "integer", "description": "Max points (default 100)"},
        },
    },
    "list_incidents": {
        "description": "List incidents for the tenant (optionally filter by status/asset)",
        "fn": _tool_list_incidents,
        "required": [],
        "properties": {
            "asset_id": {"type": "string", "description": "Filter by root asset id"},
            "status": {"type": "string", "description": "e.g. open"},
            "limit": {"type": "integer", "description": "Max rows (default 50)"},
        },
    },
    "list_pipelines": {
        "description": "List pipelines / DAGs for the tenant",
        "fn": _tool_list_pipelines,
        "required": [],
        "properties": {
            "limit": {"type": "integer", "description": "Max rows (default 100)"},
        },
    },
    "list_datasets": {
        "description": "List datasets / tables for the tenant",
        "fn": _tool_list_datasets,
        "required": [],
        "properties": {
            "limit": {"type": "integer", "description": "Max rows (default 100)"},
        },
    },
    "get_reliability_overview": {
        "description": "Estate snapshot: counts of pipelines, datasets, open incidents, monitors, alerts, plus top open issues",
        "fn": _tool_reliability_overview,
        "required": [],
        "properties": {},
    },
}


def openai_tool_schemas(*, kind: str | None = None) -> list[dict[str, Any]]:
    """OpenAI/OpenRouter function-calling tool definitions."""
    # All tools available; kind only affects agent prompt hints
    _ = kind
    schemas: list[dict[str, Any]] = []
    for name, spec in TOOLS.items():
        schemas.append(
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": spec["description"],
                    "parameters": {
                        "type": "object",
                        "properties": spec.get("properties") or {},
                        "required": list(spec.get("required") or []),
                    },
                },
            }
        )
    return schemas


def select_tools_for_question(
    question: str,
    *,
    kind: str,
    bound: dict[str, Any],
) -> list[tuple[str, dict[str, Any]]]:
    """
    Agentic planner (deterministic): map user question → Metadata tool calls.
    kind: incident_rca | dq_lineage | orchestrator
    """
    q = (question or "").lower()
    calls: list[tuple[str, dict[str, Any]]] = []

    incident_key = bound.get("incident_key")
    dataset_id = bound.get("dataset_id")
    pipeline_id = bound.get("pipeline_id")
    asset_id = bound.get("asset_id") or dataset_id or pipeline_id

    # Always anchor on bound context
    if kind == "incident_rca" and incident_key:
        calls.append(("get_incident", {"incident_key": incident_key}))
        if pipeline_id or asset_id:
            pid = pipeline_id or asset_id
            calls.append(("list_executions", {"pipeline_id": pid, "limit": 40}))
            calls.append(("get_pipeline_dashboard", {"pipeline_id": pid}))
            calls.append(("list_alerts", {"asset_id": pid}))
        if any(w in q for w in ("blast", "downstream", "lineage", "impact", "affect")):
            # Prefer related datasets from later merge; still try dataset-shaped assets
            if dataset_id:
                calls.append(("get_blast_radius", {"dataset_id": dataset_id}))
                calls.append(("list_lineage", {"dataset_id": dataset_id}))
        if any(w in q for w in ("check", "fresh", "volume", "schema", "quality", "dq", "null")):
            if dataset_id:
                calls.append(("list_check_results", {"asset_id": dataset_id}))
                calls.append(("list_monitors", {"asset_id": dataset_id}))
            elif pipeline_id or asset_id:
                # checks on related datasets fetched after dashboard
                pass
        if any(w in q for w in ("metric", "trend", "chart", "history", "row_count", "lag")):
            if asset_id:
                calls.append(("list_metrics", {"asset_id": asset_id}))

    elif kind == "dq_lineage" and dataset_id:
        calls.append(("get_dataset", {"dataset_id": dataset_id}))
        calls.append(("list_check_results", {"asset_id": dataset_id}))
        calls.append(("list_monitors", {"asset_id": dataset_id}))
        calls.append(("list_alerts", {"asset_id": dataset_id}))
        if any(w in q for w in ("blast", "downstream", "upstream", "lineage", "impact", "built from", "feeds")):
            calls.append(("get_blast_radius", {"dataset_id": dataset_id}))
            calls.append(("list_lineage", {"dataset_id": dataset_id}))
        if any(w in q for w in ("pipeline", "run", "execution", "failed", "airflow", "dbt")):
            calls.append(("list_lineage", {"dataset_id": dataset_id}))
        if any(w in q for w in ("metric", "trend", "chart", "history", "row_count", "lag")):
            calls.append(("list_metrics", {"asset_id": dataset_id}))
        # Default: always include lineage for DQ openings
        if not any(c[0] == "list_lineage" for c in calls):
            calls.append(("list_lineage", {"dataset_id": dataset_id}))
            calls.append(("get_blast_radius", {"dataset_id": dataset_id}))

    elif kind == "observability":
        calls.append(("get_reliability_overview", {}))
        if any(w in q for w in ("incident", "open", "severity", "blast", "what failed", "worst")):
            calls.append(("list_incidents", {"status": "open", "limit": 40}))
        if any(w in q for w in ("pipeline", "dag", "failed pipeline", "airflow", "dbt")):
            calls.append(("list_pipelines", {"limit": 50}))
        if any(w in q for w in ("dataset", "table", "mart", "warehouse")):
            calls.append(("list_datasets", {"limit": 50}))
        if any(w in q for w in ("monitor", "check", "fresh", "volume", "schema", "quality")):
            calls.append(("list_monitors", {"limit": 40}))
            calls.append(("list_check_results", {"limit": 40}))
        if any(w in q for w in ("alert", "alerted", "noisy")):
            calls.append(("list_alerts", {"limit": 40}))
        if any(w in q for w in ("metric", "trend", "chart", "row_count", "lag", "freshness")):
            calls.append(("list_metrics", {"limit": 100}))
        # Opening / generic: also pull open incidents + monitors
        if not any(c[0] == "list_incidents" for c in calls):
            calls.append(("list_incidents", {"status": "open", "limit": 30}))
        if not any(c[0] == "list_monitors" for c in calls):
            calls.append(("list_monitors", {"limit": 30}))
        if not any(c[0] == "list_alerts" for c in calls):
            calls.append(("list_alerts", {"limit": 30}))

    else:
        # orchestrator / generic
        if incident_key:
            calls.append(("get_incident", {"incident_key": incident_key}))
        if dataset_id:
            calls.append(("get_dataset", {"dataset_id": dataset_id}))
            calls.append(("list_check_results", {"asset_id": dataset_id}))
        if pipeline_id:
            calls.append(("list_executions", {"pipeline_id": pipeline_id}))

    # Deduplicate by tool name (keep first)
    seen: set[str] = set()
    uniq: list[tuple[str, dict[str, Any]]] = []
    for name, args in calls:
        if name in seen:
            continue
        seen.add(name)
        uniq.append((name, args))
    return uniq


def run_tool_calls(
    client: MetadataClient,
    tenant_id: str,
    calls: list[tuple[str, dict[str, Any]]],
) -> dict[str, Any]:
    """Execute tool calls; return evidence fragments + trace for debugging."""
    evidence: dict[str, Any] = {"tool_trace": []}
    for name, args in calls:
        spec = TOOLS.get(name)
        if not spec:
            evidence["tool_trace"].append({"tool": name, "ok": False, "error": "unknown tool"})
            continue
        missing = [r for r in spec["required"] if not args.get(r)]
        if missing:
            evidence["tool_trace"].append({"tool": name, "ok": False, "error": f"missing {missing}"})
            continue
        try:
            result = spec["fn"](client, tenant_id, args)
            evidence["tool_trace"].append({"tool": name, "ok": True, "args": args})
            _merge_tool_result(evidence, name, result)
        except Exception as exc:
            evidence["tool_trace"].append({"tool": name, "ok": False, "error": str(exc)[:200]})
    return evidence


def _merge_tool_result(evidence: dict[str, Any], name: str, result: Any) -> None:
    if name == "get_incident":
        evidence["incident"] = result
    elif name == "list_executions":
        evidence["executions"] = result if isinstance(result, list) else []
    elif name == "get_pipeline_dashboard":
        evidence["pipeline_dashboard"] = result
        if isinstance(result, dict):
            evidence.setdefault("pipeline_io", result.get("pipeline_io") or [])
            if not evidence.get("executions"):
                evidence["executions"] = result.get("executions") or []
    elif name == "list_check_results":
        evidence["check_results"] = result if isinstance(result, list) else []
    elif name == "list_monitors":
        evidence["monitors"] = result if isinstance(result, list) else []
    elif name == "list_alerts":
        evidence["alerts"] = result if isinstance(result, list) else []
    elif name == "get_blast_radius":
        evidence["blast_radius"] = result
    elif name == "list_lineage":
        evidence["lineage_edges"] = result if isinstance(result, list) else []
    elif name == "get_dataset":
        evidence["dataset"] = result
    elif name == "list_metrics":
        evidence["metrics"] = result if isinstance(result, list) else []
    elif name == "list_incidents":
        evidence["incidents"] = result if isinstance(result, list) else []
    elif name == "list_pipelines":
        evidence["pipelines"] = result if isinstance(result, list) else []
    elif name == "list_datasets":
        evidence["datasets"] = result if isinstance(result, list) else []
    elif name == "get_reliability_overview":
        evidence["reliability_overview"] = result
        if isinstance(result, dict):
            # Also seed list-shaped keys for citation building when present in overview only
            pass


def build_allowed_ids(evidence: dict[str, Any]) -> list[str]:
    allowed: set[str] = set()

    def add(v: Any) -> None:
        if v is None:
            return
        t = str(v).strip()
        if t:
            allowed.add(t)

    inc = evidence.get("incident") or {}
    add(inc.get("incident_key"))
    add(inc.get("root_asset_id"))
    ds = evidence.get("dataset") or {}
    add(ds.get("dataset_id"))
    for e in evidence.get("executions") or []:
        add(e.get("pipeline_id"))
        add(e.get("task_id"))
        add(e.get("execution_id"))
    for a in evidence.get("alerts") or []:
        add(a.get("alert_key"))
        add(a.get("asset_id"))
    for m in evidence.get("monitors") or []:
        add(m.get("monitor_key"))
        add(m.get("asset_id"))
    for cr in evidence.get("check_results") or []:
        add(cr.get("asset_id"))
        if cr.get("id") is not None:
            add(f"check:{cr.get('id')}")
    for edge in evidence.get("lineage_edges") or []:
        add(edge.get("upstream_dataset_id"))
        add(edge.get("downstream_dataset_id"))
        add(edge.get("transform"))
    blast = evidence.get("blast_radius") or {}
    add(blast.get("dataset_id"))
    for d in blast.get("downstream") or []:
        add(d)
    dash = evidence.get("pipeline_dashboard") or {}
    for d in dash.get("related_datasets") or []:
        add(d)
    for i in evidence.get("incidents") or []:
        add(i.get("incident_key"))
        add(i.get("root_asset_id"))
        add(i.get("title"))
    for p in evidence.get("pipelines") or []:
        add(p.get("pipeline_id"))
        add(p.get("name"))
    for d in evidence.get("datasets") or []:
        add(d.get("dataset_id"))
        add(d.get("name"))
    ov = evidence.get("reliability_overview") or {}
    for i in ov.get("top_open_incidents") or []:
        add(i.get("root_asset_id"))
        add(i.get("title"))
    for p in ov.get("failed_pipelines") or []:
        add(p.get("pipeline_id"))
    return sorted(allowed)


def agentic_gather(
    client: MetadataClient,
    tenant_id: str,
    question: str,
    *,
    kind: str,
    bound: dict[str, Any],
) -> dict[str, Any]:
    """Question-driven Metadata gather (agentic tool use)."""
    # Enrich bound from incident if needed
    bound = dict(bound)
    if kind == "incident_rca" and bound.get("incident_key") and not bound.get("pipeline_id"):
        try:
            inc = client.get_incident(tenant_id, str(bound["incident_key"]))
            bound["asset_id"] = inc.get("root_asset_id")
            if (inc.get("root_asset_type") or "").lower() == "pipeline":
                bound["pipeline_id"] = inc.get("root_asset_id")
            if (inc.get("root_asset_type") or "").lower() == "dataset":
                bound["dataset_id"] = inc.get("root_asset_id")
        except Exception:
            pass

    calls = select_tools_for_question(question, kind=kind, bound=bound)
    evidence = run_tool_calls(client, tenant_id, calls)

    # Follow-on: if dashboard has related datasets and user asked about quality, fetch checks
    q = (question or "").lower()
    dash = evidence.get("pipeline_dashboard") or {}
    if any(w in q for w in ("check", "fresh", "volume", "quality", "dq")) or kind == "incident_rca":
        for ds in (dash.get("related_datasets") or [])[:5]:
            extra = run_tool_calls(
                client,
                tenant_id,
                [("list_check_results", {"asset_id": ds, "limit": 10})],
            )
            prev = evidence.get("check_results") or []
            evidence["check_results"] = list(prev) + list(extra.get("check_results") or [])
            evidence["tool_trace"] = list(evidence.get("tool_trace") or []) + list(extra.get("tool_trace") or [])

    # Transforms → executions
    for edge in evidence.get("lineage_edges") or []:
        transform = edge.get("transform")
        if transform and not evidence.get("executions"):
            extra = run_tool_calls(
                client,
                tenant_id,
                [("list_executions", {"pipeline_id": transform, "limit": 20})],
            )
            evidence["executions"] = extra.get("executions") or []
            evidence["tool_trace"] = list(evidence.get("tool_trace") or []) + list(extra.get("tool_trace") or [])
            break

    evidence["allowed_citation_ids"] = build_allowed_ids(evidence)
    evidence["agentic"] = True
    evidence["bound"] = bound
    return evidence
