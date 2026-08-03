from __future__ import annotations



from typing import Any, Optional

from urllib.parse import quote



import httpx



from assistants.config import METADATA_API_BASE





class MetadataClient:

    """HTTP client for Metadata layer only — never opens a DB connection."""



    def __init__(self, base_url: str | None = None, timeout: float = 30.0) -> None:

        self.base_url = (base_url or METADATA_API_BASE).rstrip("/")

        self.timeout = timeout



    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:

        url = f"{self.base_url}{path}"

        with httpx.Client(timeout=self.timeout) as client:

            res = client.get(url, params={k: v for k, v in (params or {}).items() if v is not None})

            res.raise_for_status()

            return res.json()



    def get_incident(self, tenant_id: str, incident_key: str) -> dict[str, Any]:

        encoded = quote(incident_key, safe="")

        return self._get(

            f"/v1/incidents/{encoded}",

            {"tenant_id": tenant_id},

        )



    def list_incidents(
        self, tenant_id: str, *, asset_id: str | None = None, limit: int = 200
    ) -> list[dict[str, Any]]:
        data = self._get(
            "/v1/incidents",
            {"tenant_id": tenant_id, "asset_id": asset_id, "limit": limit},
        )
        return list(data.get("items") or [])

    def list_alerts(
        self, tenant_id: str, *, asset_id: str | None = None, limit: int = 200
    ) -> list[dict[str, Any]]:
        data = self._get(
            "/v1/alerts",
            {"tenant_id": tenant_id, "asset_id": asset_id, "limit": limit},
        )
        return list(data.get("items") or [])



    def list_executions(

        self, tenant_id: str, pipeline_id: Optional[str] = None, limit: int = 100

    ) -> list[dict[str, Any]]:

        data = self._get(

            "/v1/executions",

            {"tenant_id": tenant_id, "pipeline_id": pipeline_id, "limit": limit},

        )

        return list(data.get("items") or [])



    def get_pipeline_dashboard(self, tenant_id: str, pipeline_id: str) -> dict[str, Any]:

        return self._get(

            f"/v1/pipelines/{pipeline_id}/dashboard",

            {"tenant_id": tenant_id},

        )



    def get_dataset(self, tenant_id: str, dataset_id: str) -> dict[str, Any]:

        encoded = quote(dataset_id, safe="")

        return self._get(

            f"/v1/datasets/{encoded}",

            {"tenant_id": tenant_id},

        )



    def list_datasets(self, tenant_id: str, limit: int = 200) -> list[dict[str, Any]]:

        data = self._get("/v1/datasets", {"tenant_id": tenant_id, "limit": limit})

        return list(data.get("items") or [])

    def list_pipelines(self, tenant_id: str, limit: int = 200) -> list[dict[str, Any]]:
        data = self._get("/v1/pipelines", {"tenant_id": tenant_id, "limit": limit})
        return list(data.get("items") or [])



    def get_blast_radius(self, tenant_id: str, dataset_id: str) -> dict[str, Any]:

        return self._get(

            "/v1/lineage/blast-radius",

            {"tenant_id": tenant_id, "dataset_id": dataset_id},

        )



    def list_lineage(

        self, tenant_id: str, dataset_id: Optional[str] = None, limit: int = 200

    ) -> list[dict[str, Any]]:

        data = self._get(

            "/v1/lineage",

            {"tenant_id": tenant_id, "dataset_id": dataset_id, "limit": limit},

        )

        return list(data.get("items") or [])



    def list_monitors(self, tenant_id: str, limit: int = 200) -> list[dict[str, Any]]:

        data = self._get("/v1/monitors", {"tenant_id": tenant_id, "limit": limit})

        return list(data.get("items") or [])



    def list_check_results(

        self,

        tenant_id: str,

        *,

        asset_id: Optional[str] = None,

        monitor_type: Optional[str] = None,

        limit: int = 100,

    ) -> list[dict[str, Any]]:

        data = self._get(

            "/v1/check-results",

            {

                "tenant_id": tenant_id,

                "asset_id": asset_id,

                "monitor_type": monitor_type,

                "limit": limit,

            },

        )

        return list(data.get("items") or [])

    def list_metrics(
        self,
        tenant_id: str,
        *,
        asset_id: Optional[str] = None,
        name: Optional[str] = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        data = self._get(
            "/v1/metrics",
            {
                "tenant_id": tenant_id,
                "asset_id": asset_id,
                "name": name,
                "limit": limit,
            },
        )
        return list(data.get("items") or [])

