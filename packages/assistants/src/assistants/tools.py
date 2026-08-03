from __future__ import annotations



from typing import Any



from assistants.metadata_client import MetadataClient





def get_incident(client: MetadataClient, tenant_id: str, incident_key: str) -> dict[str, Any]:

    return client.get_incident(tenant_id, incident_key)





def list_alerts_for_asset(

    client: MetadataClient, tenant_id: str, asset_id: str | None

) -> list[dict[str, Any]]:

    if not asset_id:

        return []

    alerts = client.list_alerts(tenant_id, asset_id=asset_id)
    if alerts:
        return alerts
    return [
        a
        for a in client.list_alerts(tenant_id)

        if a.get("asset_id") == asset_id

        or (a.get("asset_id") or "").startswith(f"{asset_id}.")

        or asset_id in (a.get("title") or "")

    ]





def list_incidents_for_asset(

    client: MetadataClient, tenant_id: str, asset_id: str | None

) -> list[dict[str, Any]]:

    if not asset_id:

        return []

    incidents = client.list_incidents(tenant_id, asset_id=asset_id)
    if incidents:
        return incidents
    return [i for i in client.list_incidents(tenant_id) if i.get("root_asset_id") == asset_id]





def list_executions(

    client: MetadataClient, tenant_id: str, pipeline_id: str | None

) -> list[dict[str, Any]]:

    if not pipeline_id:

        return []

    return client.list_executions(tenant_id, pipeline_id=pipeline_id, limit=50)





def get_pipeline_dashboard(

    client: MetadataClient, tenant_id: str, pipeline_id: str

) -> dict[str, Any] | None:

    try:

        return client.get_pipeline_dashboard(tenant_id, pipeline_id)

    except Exception:

        return None





def get_dataset(client: MetadataClient, tenant_id: str, dataset_id: str) -> dict[str, Any] | None:

    try:

        return client.get_dataset(tenant_id, dataset_id)

    except Exception:

        return None





def get_blast_radius(

    client: MetadataClient, tenant_id: str, dataset_id: str

) -> dict[str, Any]:

    return client.get_blast_radius(tenant_id, dataset_id)





def list_lineage(

    client: MetadataClient, tenant_id: str, dataset_id: str

) -> list[dict[str, Any]]:

    return client.list_lineage(tenant_id, dataset_id=dataset_id, limit=100)





def list_monitors_for_asset(

    client: MetadataClient, tenant_id: str, asset_id: str | None

) -> list[dict[str, Any]]:

    if not asset_id:

        return []

    monitors = client.list_monitors(tenant_id)

    return [m for m in monitors if m.get("asset_id") == asset_id]





def list_check_results_for_asset(

    client: MetadataClient, tenant_id: str, asset_id: str | None, limit: int = 40

) -> list[dict[str, Any]]:

    if not asset_id:

        return []

    try:

        return client.list_check_results(tenant_id, asset_id=asset_id, limit=limit)

    except Exception:

        return []


