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


def gather_dq_evidence(
    client: MetadataClient, tenant_id: str, dataset_id: str
) -> dict[str, Any]:
    """Deterministic gather: quality checks + lineage/blast for one dataset."""
    dataset = tools.get_dataset(client, tenant_id, dataset_id)
    if dataset is None:
        # Soft fallback so chat can still open with lineage/alerts even if catalog miss
        dataset = {"dataset_id": dataset_id, "name": dataset_id, "missing_from_catalog": True}

    monitors = tools.list_monitors_for_asset(client, tenant_id, dataset_id)
    check_results = tools.list_check_results_for_asset(client, tenant_id, dataset_id, limit=40)
    alerts = tools.list_alerts_for_asset(client, tenant_id, dataset_id)
    incidents = tools.list_incidents_for_asset(client, tenant_id, dataset_id)
    lineage = tools.list_lineage(client, tenant_id, dataset_id)
    blast = tools.get_blast_radius(client, tenant_id, dataset_id)

    executions: list[dict[str, Any]] = []
    transforms = {e.get("transform") for e in lineage if e.get("transform")}
    for pid in sorted(x for x in transforms if x):
        executions.extend(tools.list_executions(client, tenant_id, pid)[:10])

    # Summarize breach types from recent check results
    breach_types: dict[str, int] = {}
    for cr in check_results:
        status = (cr.get("status") or "").lower()
        if status in {"failed", "anomalous"}:
            mt = str(cr.get("monitor_type") or "custom")
            breach_types[mt] = breach_types.get(mt, 0) + 1

    allowed: set[str] = set()
    _add_id(allowed, dataset_id)
    _add_id(allowed, dataset.get("dataset_id"))
    for m in monitors:
        _add_id(allowed, m.get("monitor_key"))
        _add_id(allowed, m.get("asset_id"))
    for cr in check_results:
        _add_id(allowed, cr.get("asset_id"))
        _add_id(allowed, cr.get("monitor_type"))
        if cr.get("id") is not None:
            _add_id(allowed, f"check:{cr.get('id')}")
    for a in alerts:
        _add_id(allowed, a.get("alert_key"))
        _add_id(allowed, a.get("asset_id"))
    for i in incidents:
        _add_id(allowed, i.get("incident_key"))
        _add_id(allowed, i.get("root_asset_id"))
    for e in executions:
        _add_id(allowed, e.get("execution_id"))
        _add_id(allowed, e.get("pipeline_id"))
        _add_id(allowed, e.get("task_id"))
    if blast:
        _add_id(allowed, blast.get("dataset_id"))
        for d in blast.get("downstream") or []:
            _add_id(allowed, d)
    for edge in lineage:
        _add_id(allowed, edge.get("upstream_dataset_id"))
        _add_id(allowed, edge.get("downstream_dataset_id"))
        _add_id(allowed, edge.get("transform"))

    return {
        "dataset": dataset,
        "monitors": monitors[:20],
        "check_results": check_results[:40],
        "breach_summary": breach_types,
        "alerts": alerts[:20],
        "incidents": incidents[:20],
        "executions": executions[:30],
        "blast_radius": blast,
        "lineage_edges": lineage[:40],
        "allowed_citation_ids": sorted(allowed),
    }

