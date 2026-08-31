"""Airbyte ETL connector (ETL tool)."""

from __future__ import annotations

import os
from typing import Any

import requests


class AirbyteConnector:
    tool_id = "airbyte"
    kind = "etl"

    def __init__(
        self,
        *,
        tenant_id: str,
        connector_instance_id: str,
        base_url: str,
        username: str | None = None,
        password: str | None = None,
        client_id: str | None = None,
        client_secret: str | None = None,
        connection_id: str = "",
        workspace_id: str = "",
        **_: Any,
    ):
        self.tenant_id = tenant_id
        self.connector_instance_id = connector_instance_id
        self.base_url = (base_url or "").rstrip("/")
        self.username = username or os.getenv("AIRBYTE_USERNAME") or ""
        self.password = password or os.getenv("AIRBYTE_PASSWORD") or ""
        self.client_id = client_id or os.getenv("AIRBYTE_CLIENT_ID") or ""
        self.client_secret = client_secret or os.getenv("AIRBYTE_CLIENT_SECRET") or ""
        self.connection_id = (connection_id or "").strip()
        self.workspace_id = (workspace_id or "").strip()
        self._token: str | None = None

    def _auth_headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return headers

    def _ensure_token(self) -> None:
        if self._token or not (self.client_id and self.client_secret):
            return
        # Airbyte Cloud / some OSS builds use application access tokens
        url = f"{self.base_url}/api/v1/applications/token"
        resp = requests.post(
            url,
            json={
                "client_id": self.client_id,
                "client_secret": self.client_secret,
            },
            timeout=60,
        )
        if resp.ok:
            data = resp.json() if resp.content else {}
            self._token = data.get("access_token") or data.get("token")

    def _post(self, path: str, body: dict | None = None) -> dict:
        self._ensure_token()
        url = f"{self.base_url}{path}"
        auth = None
        if not self._token and self.username:
            auth = (self.username, self.password)
        resp = requests.post(
            url,
            headers=self._auth_headers(),
            json=body or {},
            auth=auth,
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json() if resp.content else {}
        return data if isinstance(data, dict) else {"data": data}

    def test_connection(self) -> dict[str, Any]:
        try:
            if not self.base_url:
                return {"ok": False, "message": "base_url is required"}
            # Prefer health; fall back to list workspaces
            try:
                resp = requests.get(f"{self.base_url}/api/v1/health", timeout=30)
                if resp.ok:
                    return {
                        "ok": True,
                        "message": "Airbyte connection OK",
                        "details": resp.json() if resp.content else {},
                    }
            except Exception:
                pass
            data = self._post("/api/v1/workspaces/list", {})
            return {
                "ok": True,
                "message": "Airbyte connection OK",
                "details": {"workspaces": len(data.get("workspaces") or [])},
            }
        except Exception as e:
            return {"ok": False, "message": str(e)}

    def pull_state(self) -> list[dict]:
        """Recent job attempts as ETL-style envelopes."""
        if not self.base_url:
            return []
        body: dict[str, Any] = {"configTypes": ["sync"], "pagination": {"pageSize": 25}}
        if self.workspace_id:
            body["workspaceId"] = self.workspace_id
        if self.connection_id:
            body["configId"] = self.connection_id
        try:
            data = self._post("/api/v1/jobs/list", body)
        except Exception:
            # Older Airbyte: list jobs without filters
            data = self._post("/api/v1/jobs/list", {"configTypes": ["sync"]})

        jobs = data.get("jobs") or []
        envelopes = []
        for item in jobs:
            job = item.get("job") if isinstance(item, dict) and "job" in item else item
            if not isinstance(job, dict):
                continue
            if self.connection_id and str(job.get("configId") or "") not in {
                self.connection_id,
                "",
            }:
                # Keep unmatched when API ignored filter
                if job.get("configId") and str(job.get("configId")) != self.connection_id:
                    continue
            status_raw = str(job.get("status") or "").lower()
            status = {
                "succeeded": "succeeded",
                "failed": "failed",
                "cancelled": "failed",
                "running": "running",
                "pending": "queued",
                "incomplete": "failed",
            }.get(status_raw, status_raw or "unknown")
            run_id = job.get("id") or job.get("jobId")
            envelopes.append(
                {
                    "source_system": "airbyte",
                    "tenant_id": self.tenant_id,
                    "connector_instance_id": self.connector_instance_id,
                    "raw": {
                        "run_id": str(run_id),
                        "status": status,
                        "started_at": job.get("createdAt") or job.get("startTime"),
                        "finished_at": job.get("updatedAt") or job.get("endTime"),
                        "error_message": None if status != "failed" else "airbyte job failed",
                        "relations": [],
                        "rows_read": job.get("rowsSynced") or job.get("recordsSynced"),
                        "rows_written": job.get("rowsSynced") or job.get("recordsSynced"),
                    },
                }
            )
        return envelopes
