from __future__ import annotations

from typing import Any

from normalization.mappers.base import BaseMapper
from normalization.utils import first, normalize_status, pipeline_event_type


class BiMapper(BaseMapper):
    """
    BI tools (Tableau / Looker / Power BI) — treat extracts/refreshes as pipeline
    executions and published datasets as discovered assets.
    """

    family = "bi_analytics"

    asset_keys = (
        "dataset_id",
        "dataset",
        "datasource_id",
        "workbook_id",
        "dashboard_id",
        "view_id",
        "model_id",
        "name",
        "id",
    )
    status_keys = ("status", "state", "refresh_status", "lastRefreshStatus", "statusDescription")
    time_keys = ("occurred_at", "completed_at", "endTime", "lastRefresh", "timestamp", "updated_at")

    def map(
        self,
        raw: dict[str, Any],
        *,
        tenant_id: str,
        connector_instance_id: str | None = None,
    ) -> list[dict[str, Any]]:
        kind = str(first(raw, "kind", "event_type", "resource_type", default="")).lower()
        name = str(first(raw, *self.asset_keys, default="unknown_asset"))
        status_raw = first(raw, *self.status_keys)
        status = normalize_status(status_raw or "succeeded")
        occurred = first(raw, *self.time_keys)

        is_refresh = (
            status_raw is not None
            or "refresh" in kind
            or "extract" in kind
            or kind in {"pipeline", "refresh", "extract"}
        )
        if is_refresh:
            event_type = pipeline_event_type(status)
            pipeline_id = str(first(raw, "pipeline_id", "workbook", "dashboard", "dataset", default=name))
            run_id = str(first(raw, "refresh_id", "run_id", "request_id", "id", default=f"{pipeline_id}-refresh"))
            return [
                self.event(
                    event_type=event_type,
                    tenant_id=tenant_id,
                    occurred_at=occurred,
                    connector_instance_id=connector_instance_id,
                    payload={
                        "pipeline_id": pipeline_id,
                        "execution_id": run_id,
                        "status": status,
                        "asset_type": first(raw, "resource_type", "kind", default="bi_asset"),
                        "error_message": first(raw, "error", "error_message", "message"),
                        "started_at": first(raw, "startTime", "started_at", "start_time"),
                        "finished_at": first(raw, "endTime", "completed_at", "end_time"),
                    },
                    id_parts=[tenant_id, self.tool_id, event_type, pipeline_id, run_id, status],
                )
            ]

        dataset_id = f"{self.tool_id}.{name}"
        return [
            self.event(
                event_type="dataset.discovered.v1",
                tenant_id=tenant_id,
                occurred_at=occurred,
                connector_instance_id=connector_instance_id,
                payload={
                    "dataset_id": dataset_id,
                    "database": self.tool_id,
                    "schema": first(raw, "project", "site", "workspace", default="default"),
                    "name": name,
                    "platform": self.tool_id,
                    "owner": first(raw, "owner", "owner_id"),
                    "tags": first(raw, "tags", default=[]),
                },
                id_parts=[tenant_id, self.tool_id, "discovered", dataset_id],
            )
        ]
