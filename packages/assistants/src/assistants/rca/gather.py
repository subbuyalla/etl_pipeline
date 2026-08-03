from __future__ import annotations

from typing import Any

from assistants.metadata_client import MetadataClient
from assistants import tools


def _add_id(bucket: set[str], value: Any) -> None:
    if value is None:
        return
    text = str(value).strip()
    if text:
        bucket.add(text)


def gather_evidence(
    client: MetadataClient, tenant_id: str, incident_key: str
) -> dict[str, Any]:
    """Deterministic gather node: build evidence pack + allowed citation IDs."""
    incident = tools.get_incident(client, tenant_id, incident_key)
    asset_type = (incident.get("root_asset_type") or "").lower()
    asset_id = incident.get("root_asset_id")

    alerts = tools.list_alerts_for_asset(client, tenant_id, asset_id)
    monitors = tools.list_monitors_for_asset(client, tenant_id, asset_id)
    check_results: list[dict[str, Any]] = []
    if asset_type == "dataset" and asset_id:
        check_results = tools.list_check_results_for_asset(client, tenant_id, asset_id)

    executions: list[dict[str, Any]] = []
    dashboard: dict[str, Any] | None = None
    blast: dict[str, Any] | None = None
    lineage: list[dict[str, Any]] = []
    pipeline_io: list[dict[str, Any]] = []

    if asset_type == "pipeline" and asset_id:
        executions = tools.list_executions(client, tenant_id, asset_id)
        dashboard = tools.get_pipeline_dashboard(client, tenant_id, asset_id)
        pipeline_io = list((dashboard or {}).get("pipeline_io") or [])
        # Pull DQ checks for related datasets
        for ds in (dashboard or {}).get("related_datasets") or []:
            check_results.extend(tools.list_check_results_for_asset(client, tenant_id, ds)[:10])
    elif asset_type == "dataset" and asset_id:
        blast = tools.get_blast_radius(client, tenant_id, asset_id)
        lineage = tools.list_lineage(client, tenant_id, asset_id)
        transforms = {e.get("transform") for e in lineage if e.get("transform")}
        for pid in sorted(x for x in transforms if x):
            executions.extend(tools.list_executions(client, tenant_id, pid)[:10])
            dash = tools.get_pipeline_dashboard(client, tenant_id, pid)
            if dash:
                pipeline_io.extend(dash.get("pipeline_io") or [])
    elif asset_id:
        executions = tools.list_executions(client, tenant_id, asset_id)
        dashboard = tools.get_pipeline_dashboard(client, tenant_id, asset_id)
        pipeline_io = list((dashboard or {}).get("pipeline_io") or [])
        try:
            blast = tools.get_blast_radius(client, tenant_id, asset_id)
            lineage = tools.list_lineage(client, tenant_id, asset_id)
            check_results = tools.list_check_results_for_asset(client, tenant_id, asset_id)
        except Exception:
            pass

    allowed: set[str] = set()
    _add_id(allowed, incident.get("incident_key"))
    _add_id(allowed, asset_id)
    for a in alerts:
        _add_id(allowed, a.get("alert_key"))
        _add_id(allowed, a.get("asset_id"))
    for e in executions:
        _add_id(allowed, e.get("execution_id"))
        _add_id(allowed, e.get("pipeline_id"))
        _add_id(allowed, e.get("task_id"))
    for m in monitors:
        _add_id(allowed, m.get("monitor_key"))
        _add_id(allowed, m.get("asset_id"))
    for cr in check_results:
        if cr.get("id") is not None:
            _add_id(allowed, f"check:{cr.get('id')}")
        _add_id(allowed, cr.get("monitor_type"))
        _add_id(allowed, cr.get("asset_id"))
    if dashboard:
        pipe = dashboard.get("pipeline") or {}
        _add_id(allowed, pipe.get("pipeline_id"))
        for t in dashboard.get("tasks") or []:
            _add_id(allowed, t.get("task_id"))
        for d in dashboard.get("related_datasets") or []:
            _add_id(allowed, d)
    for io in pipeline_io:
        _add_id(allowed, io.get("upstream_dataset_id"))
        _add_id(allowed, io.get("downstream_dataset_id"))
        _add_id(allowed, io.get("pipeline_id"))
    if blast:
        _add_id(allowed, blast.get("dataset_id"))
        for d in blast.get("downstream") or []:
            _add_id(allowed, d)
    for edge in lineage:
        _add_id(allowed, edge.get("upstream_dataset_id"))
        _add_id(allowed, edge.get("downstream_dataset_id"))
        _add_id(allowed, edge.get("transform"))

    evidence = {
        "incident": incident,
        "alerts": alerts[:20],
        "monitors": monitors[:20],
        "check_results": check_results[:40],
        "executions": executions[:40],
        "pipeline_io": pipeline_io[:40],
        "pipeline_dashboard": {
            "pipeline": (dashboard or {}).get("pipeline"),
            "metrics": (dashboard or {}).get("metrics"),
            "task_stats": (dashboard or {}).get("task_stats"),
            "related_datasets": (dashboard or {}).get("related_datasets"),
            "pipeline_io": (dashboard or {}).get("pipeline_io"),
        }
        if dashboard
        else None,
        "blast_radius": blast,
        "lineage_edges": lineage[:40],
        "allowed_citation_ids": sorted(allowed),
    }
    return evidence
