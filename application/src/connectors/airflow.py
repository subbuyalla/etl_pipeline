"""Apache Airflow orchestrator connector (ETL / orchestrator tool)."""

from __future__ import annotations

import os
from typing import Any

import requests


class AirflowConnector:
    tool_id = "airflow"
    kind = "orchestrator"

    def __init__(
        self,
        *,
        tenant_id: str,
        connector_instance_id: str,
        base_url: str,
        username: str | None = None,
        password: str | None = None,
        token: str | None = None,
        dag_id: str = "",
        **_: Any,
    ):
        self.tenant_id = tenant_id
        self.connector_instance_id = connector_instance_id
        self.base_url = (base_url or "").rstrip("/")
        self.username = username or os.getenv("AIRFLOW_USERNAME") or ""
        self.password = password or os.getenv("AIRFLOW_PASSWORD") or ""
        self.token = token or os.getenv("AIRFLOW_TOKEN") or ""
        self.dag_id = (dag_id or "").strip()

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def _auth(self) -> tuple[str, str] | None:
        if self.token:
            return None
        if self.username:
            return (self.username, self.password)
        return None

    def _get(self, path: str, params: dict | None = None) -> dict:
        url = f"{self.base_url}{path}"
        resp = requests.get(
            url, headers=self._headers(), auth=self._auth(), params=params, timeout=60
        )
        resp.raise_for_status()
        data = resp.json()
        return data if isinstance(data, dict) else {"data": data}

    def test_connection(self) -> dict[str, Any]:
        try:
            if not self.base_url:
                return {"ok": False, "message": "base_url is required"}
            # Airflow 2+ health
            try:
                data = self._get("/api/v1/health")
            except Exception:
                data = self._get("/health")
            return {"ok": True, "message": "Airflow connection OK", "details": data}
        except Exception as e:
            return {"ok": False, "message": str(e)}

    def pull_state(self) -> list[dict]:
        """Recent DAG runs as ETL-style envelopes (compatible with map_run)."""
        if not self.base_url:
            return []
        params: dict[str, Any] = {"limit": 25, "order_by": "-execution_date"}
        if self.dag_id:
            path = f"/api/v1/dags/{self.dag_id}/dagRuns"
        else:
            path = "/api/v1/dags/~/dagRuns"
        data = self._get(path, params=params)
        runs = data.get("dag_runs") or data.get("dagRuns") or []
        envelopes = []
        for run in runs:
            if not isinstance(run, dict):
                continue
            state = str(run.get("state") or "").lower()
            status = {
                "success": "succeeded",
                "failed": "failed",
                "running": "running",
                "queued": "queued",
            }.get(state, state or "unknown")
            run_id = run.get("dag_run_id") or run.get("run_id") or run.get("execution_date")
            envelopes.append(
                {
                    "source_system": "airflow",
                    "tenant_id": self.tenant_id,
                    "connector_instance_id": self.connector_instance_id,
                    "raw": {
                        "run_id": str(run_id),
                        "status": status,
                        "started_at": run.get("start_date") or run.get("execution_date"),
                        "finished_at": run.get("end_date"),
                        "error_message": run.get("note") if status == "failed" else None,
                        "dag_id": run.get("dag_id") or self.dag_id,
                        "relations": [],
                        "rows_read": None,
                        "rows_written": None,
                    },
                }
            )
        return envelopes
