import os
import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class DbtConnector:
    """one class= one tool(dbt)"""

    tool_id="dbt_lab"
    def __init__(
    self,
    *,
    tenant_id: str,
    connector_instance_id: str,
    account_id: str,  # dbt Cloud account id
    project_id: str = "",
    job_id: str = "",  # optional: filter one job
    project_name: str = "analytics",
    api_base: str = "https://cloud.getdbt.com/api/v2",
    api_token: str | None = None,
):
        self.tenant_id = tenant_id
        self.connector_instance_id = connector_instance_id
        self.account_id = account_id
        self.project_id = project_id
        self.job_id = job_id
        self.project_name = project_name
        self.api_base = api_base.rstrip("/")
        self.api_token = api_token or os.getenv("DBT_CLOUD_API_TOKEN", "")
        self.api_headers = {
            "Authorization": f"Token {self.api_token}",
            "Content-Type": "application/json",
        }
    def _get(self, path: str) -> dict:
        """HTTP GET to dbt Cloud API (like Snowflake _connect + execute)."""
        if not self.api_token:
            raise RuntimeError("Missing DBT_CLOUD_API_TOKEN")

        url = f"{self.api_base}{path}"
        req = Request(url, headers=self.api_headers, method="GET")
        try:
            with urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")[:300]
            raise RuntimeError(f"dbt Cloud API {e.code}: {body}") from e
        except URLError as e:
            raise RuntimeError(f"dbt Cloud unreachable: {e}") from e

    def test_connection(self) -> dict:
        """Test: can we reach this dbt Cloud account?"""
        try:
            if not self.account_id:
                return {"ok": False, "message": "account_id is required"}
            data = self._get(f"/accounts/{self.account_id}/")
            name = (data.get("data") or {}).get("name")
            return {
                "ok": True,
                "message": "dbt Cloud connection OK",
                "details": {"account": name},
            }
        except Exception as e:
            return {"ok": False, "message": str(e)}

    def _fetch_runs(self, *, limit: int = 10) -> list[dict]:
        """
        Pull recent dbt Cloud job runs (metadata/logs, not business data).
        Like Snowflake _fetch_tables.
        """
        if not self.account_id:
            raise ValueError("account_id is required")

        if self.job_id:
            path = (
                f"/accounts/{self.account_id}/runs/"
                f"?job_definition_id={self.job_id}&order_by=-id&limit={limit}"
            )
        else:
            path = f"/accounts/{self.account_id}/runs/?order_by=-id&limit={limit}"

        data = self._get(path)
        runs = data.get("data") or []
        rows: list[dict] = []
        for run in runs:
            status_code = run.get("status")
            if status_code == 10:
                status = "succeeded"
            elif status_code in {20, 30}:
                status = "failed"
            else:
                status = "running"

            rows.append(
                {
                    "run_id": str(run.get("id")),
                    "job_id": str(run.get("job_definition_id") or self.job_id or ""),
                    "project_name": self.project_name,
                    "status": status,
                    "status_code": status_code,
                    "started_at": run.get("started_at"),
                    "finished_at": run.get("finished_at"),
                    "error_message": run.get("status_message"),
                }
            )
        return rows

    def pull_state(self) -> list[dict]:
        """
        Sync payload: wrap each run as an envelope for Metadata later.
        """
        envelopes: list[dict] = []
        for row in self._fetch_runs():
            envelopes.append(
                {
                    "source_system": "dbt",
                    "tenant_id": self.tenant_id,
                    "connector_instance_id": self.connector_instance_id,
                    "raw": {
                        "event_type": "run",
                        "project_name": row["project_name"],
                        "run_id": row["run_id"],
                        "job_id": row.get("job_id"),
                        "status": row.get("status"),
                        "started_at": row.get("started_at"),
                        "finished_at": row.get("finished_at"),
                        "error_message": row.get("error_message"),
                    },
                }
            )
        return envelopes

