"""
Informatica IICS / IDMC Cloud Data Integration Connector.
Connects to Informatica Intelligent Cloud Services via REST API (v2 and v3)
to pull job execution status, transformation metrics, row counts, and data quality check results.
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from typing import Any
import requests


# Map Informatica executionState values to standard DataPulse statuses
# IICS states: 1 = Success, 2 = Warning, 3 = Failed, etc. or strings "SUCCESS", "FAILED", "RUNNING"
INFORMATICA_STATUS_MAP: dict[str, str] = {
    "1": "succeeded",
    "2": "warning",
    "3": "failed",
    "success": "succeeded",
    "succeeded": "succeeded",
    "failed": "failed",
    "failure": "failed",
    "error": "failed",
    "running": "running",
    "in_progress": "running",
    "queued": "queued",
    "pending": "queued",
    "warning": "succeeded",  # Warning usually completes with non-fatal rows
    "stopped": "failed",
    "aborted": "failed",
}


def normalize_pod_url(pod_or_url: str) -> str:
    """
    Normalizes POD identifier or full URL to standard IICS base URL.
    Examples:
      'dm-us' -> 'https://dm-us.informaticacloud.com'
      'dm-em' -> 'https://dm-em.informaticacloud.com'
      'dm-ap' -> 'https://dm-ap.informaticacloud.com'
      'https://na1.dm-us.informaticacloud.com/' -> 'https://na1.dm-us.informaticacloud.com'
    """
    raw = (pod_or_url or "").strip().rstrip("/")
    if not raw:
        return "https://dm-us.informaticacloud.com"

    shortcuts = {
        "dm-us": "https://dm-us.informaticacloud.com",
        "us": "https://dm-us.informaticacloud.com",
        "na": "https://dm-us.informaticacloud.com",
        "dm-em": "https://dm-em.informaticacloud.com",
        "em": "https://dm-em.informaticacloud.com",
        "eu": "https://dm-em.informaticacloud.com",
        "dm-ap": "https://dm-ap.informaticacloud.com",
        "ap": "https://dm-ap.informaticacloud.com",
        "dmp-us": "https://dmp-us.informaticacloud.com",
    }
    key = raw.lower()
    if key in shortcuts:
        return shortcuts[key]

    if not raw.startswith("http://") and not raw.startswith("https://"):
        raw = f"https://{raw}"

    return raw.rstrip("/")


def parse_infa_timestamp(ts: Any) -> str | None:
    """Converts Informatica timestamps (ISO string, epoch ms, or epoch s) to UTC ISO string."""
    if not ts:
        return None
    try:
        if isinstance(ts, (int, float)):
            # Epoch milliseconds or seconds
            secs = ts / 1000.0 if ts > 1e11 else float(ts)
            return datetime.fromtimestamp(secs, tz=timezone.utc).isoformat()
        if isinstance(ts, str):
            s = ts.strip()
            if s.isdigit():
                val = int(s)
                secs = val / 1000.0 if val > 1e11 else float(val)
                return datetime.fromtimestamp(secs, tz=timezone.utc).isoformat()
            # Try ISO parse
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
            return dt.astimezone(timezone.utc).isoformat()
    except Exception:
        pass
    return str(ts)


class InformaticaConnector:
    """
    Informatica Intelligent Cloud Services (IICS) / IDMC Connector.
    Extracts pipeline runs, row volumes, table relations, and data quality check results.
    """

    tool_id = "informatica"
    kind = "etl"

    def __init__(
        self,
        *,
        tenant_id: str,
        connector_instance_id: str,
        pod_url: str | None = None,
        username: str | None = None,
        password: str | None = None,
        org_id: str | None = None,
        task_type: str | None = None,
        task_filter: str | None = None,
        timeout: int = 60,
        **_: Any,
    ):
        self.tenant_id = tenant_id
        self.connector_instance_id = connector_instance_id
        self.pod_url = normalize_pod_url(pod_url or os.getenv("INFORMATICA_POD_URL") or "dm-us")
        self.username = username or os.getenv("INFORMATICA_USERNAME") or ""
        self.password = password or os.getenv("INFORMATICA_PASSWORD") or ""
        self.org_id = (org_id or os.getenv("INFORMATICA_ORG_ID") or "").strip()
        self.task_type = (task_type or "MTT").strip().upper()  # Default to Mapping Tasks (MTT)
        self.task_filter = (task_filter or "").strip()
        self.timeout = timeout

        # Session state
        self._session_id: str | None = None
        self._server_url: str | None = None
        self._org_name: str | None = None
        self._org_id_retrieved: str | None = None

    def _auth_headers(self) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if self._session_id:
            # IICS accepts both INFA-SESSION-ID and icSessionId headers
            headers["INFA-SESSION-ID"] = self._session_id
            headers["icSessionId"] = self._session_id
        return headers

    def _login(self, force: bool = False) -> None:
        """
        Authenticates against IICS to acquire a session token and POD server URL.
        Uses REST API v3 login with fallback to v2.
        """
        if self._session_id and not force:
            return

        if not self.username or not self.password:
            raise ValueError("Informatica username and password are required")

        # 1. Attempt REST API v3 login (Recommended for IDMC / IICS)
        v3_url = f"{self.pod_url}/saas/public/core/v3/login"
        payload = {
            "username": self.username,
            "password": self.password,
        }

        resp = None
        try:
            resp = requests.post(v3_url, json=payload, headers={"Content-Type": "application/json", "Accept": "application/json"}, timeout=self.timeout)
        except Exception as e:
            # Check if domain resolution failed or network error
            raise RuntimeError(f"Unable to reach Informatica POD at {self.pod_url}: {e}") from e

        if resp.status_code == 200:
            data = resp.json() if resp.content else {}
            # v3 response structure
            user_info = data.get("userInfo") or {}
            self._session_id = data.get("sessionId") or user_info.get("sessionId")

            # Extract Address 2 (serverUrl) where IICS data and logs live
            server_url = (
                data.get("serverUrl")
                or data.get("baseApiUrl")
                or user_info.get("serverUrl")
                or user_info.get("baseApiUrl")
            )
            if not server_url and isinstance(data.get("products"), list):
                for prod in data["products"]:
                    if isinstance(prod, dict):
                        found_url = prod.get("baseApiUrl") or prod.get("serviceUrl") or prod.get("serverUrl")
                        if found_url:
                            server_url = found_url
                            break
            if not server_url and isinstance(user_info.get("products"), list):
                for prod in user_info["products"]:
                    if isinstance(prod, dict):
                        found_url = prod.get("baseApiUrl") or prod.get("serviceUrl") or prod.get("serverUrl")
                        if found_url:
                            server_url = found_url
                            break

            # Retain serverUrl for all subsequent calls (e.g. https://apse1.dm-ap.informaticacloud.com/saas)
            self._server_url = str(server_url).rstrip("/") if server_url else self.pod_url
            self._org_name = user_info.get("orgName") or data.get("orgName")
            self._org_id_retrieved = user_info.get("orgId") or self.org_id
            return

        # 2. Fallback to REST API v2 login if v3 returned 404 or method not allowed
        if resp.status_code in (404, 405):
            v2_url = f"{self.pod_url}/ma/api/v2/user/login"
            v2_payload = {
                "@type": "login",
                "username": self.username,
                "password": self.password,
            }
            v2_resp = requests.post(v2_url, json=v2_payload, headers={"Content-Type": "application/json", "Accept": "application/json"}, timeout=self.timeout)
            if v2_resp.status_code == 200:
                v2_data = v2_resp.json() if v2_resp.content else {}
                self._session_id = v2_data.get("icSessionId") or v2_data.get("sessionId")
                server_url = v2_data.get("serverUrl") or v2_data.get("baseApiUrl")
                self._server_url = str(server_url).rstrip("/") if server_url else self.pod_url
                self._org_name = v2_data.get("orgName")
                self._org_id_retrieved = v2_data.get("orgId") or self.org_id
                return
            err_msg = v2_resp.text
            raise RuntimeError(f"Informatica v2 login failed ({v2_resp.status_code}): {err_msg}")

        # V3 error handling
        err_text = resp.text
        try:
            err_json = resp.json()
            err_text = err_json.get("error", {}).get("message") or err_json.get("description") or err_text
        except Exception:
            pass

        if resp.status_code == 401 or "Unauthorized" in err_text:
            raise RuntimeError(f"Informatica authentication failed: Invalid username or password ({err_text})")
        raise RuntimeError(f"Informatica login error ({resp.status_code}): {err_text}")

    def _resolve_url(self, path: str) -> str:
        """Resolves endpoint path against serverUrl (Address 2) with proper /saas prefixing."""
        if path.startswith("http://") or path.startswith("https://"):
            return path
        base = (self._server_url or self.pod_url).rstrip("/")
        clean_path = "/" + path.lstrip("/")
        # If base ends with /saas and path starts with /saas, avoid duplication
        if base.endswith("/saas") and clean_path.startswith("/saas/"):
            clean_path = clean_path[5:]
        # If base does NOT end with /saas and path starts with /api/v2, append /saas
        elif not base.endswith("/saas") and clean_path.startswith("/api/v2/"):
            clean_path = f"/saas{clean_path}"
        return f"{base}{clean_path}"

    def _request(self, method: str, path: str, *, params: dict | None = None, json_body: dict | None = None) -> Any:
        """
        Executes an authenticated request against Informatica serverUrl (Address 2).
        Automatically re-authenticates and retries on HTTP 401 session expiry.
        """
        self._login()
        url = self._resolve_url(path)

        resp = requests.request(
            method,
            url,
            headers=self._auth_headers(),
            params=params,
            json=json_body,
            timeout=self.timeout,
        )

        # Handle session expiration (IICS tokens expire after 30 mins)
        if resp.status_code in (401, 403):
            self._login(force=True)
            url = self._resolve_url(path)
            resp = requests.request(
                method,
                url,
                headers=self._auth_headers(),
                params=params,
                json=json_body,
                timeout=self.timeout,
            )

        resp.raise_for_status()
        return resp.json() if resp.content else {}

    def test_connection(self) -> dict[str, Any]:
        """
        Validates connectivity, authentication, and permissions against Informatica IICS.
        """
        try:
            self._login(force=True)

            # Test querying activityLog with limit 1 to verify user role permissions against serverUrl
            test_resp = self._request("GET", "/api/v2/activity/activityLog", params={"rowLimit": 1})
            entries_count = len(test_resp) if isinstance(test_resp, list) else 0

            return {
                "ok": True,
                "message": "Informatica IICS connection and permissions verified",
                "details": {
                    "pod_url": self.pod_url,
                    "server_url": self._server_url,
                    "org_id": self._org_id_retrieved or self.org_id or "default",
                    "org_name": self._org_name or "Informatica Org",
                    "tasks_accessible": entries_count >= 0,
                    "permissions": {
                        "authentication": True,
                        "session_active": True,
                        "activity_log_read": True,
                    },
                },
            }
        except Exception as e:
            return {
                "ok": False,
                "message": f"Informatica connection failed: {str(e)}",
                "details": {
                    "pod_url": self.pod_url,
                    "server_url": self._server_url,
                    "permissions": {
                        "authentication": bool(self._session_id),
                        "activity_log_read": False,
                    },
                },
            }

    def pull_state(self, limit: int = 50) -> list[dict[str, Any]]:
        """
        Pulls recent job execution attempts from IICS Activity Log (/api/v2/activity/activityLog).
        Maps each task run into a standard DataPulse ETL envelope.
        """
        params: dict[str, Any] = {"rowLimit": limit}
        if self.task_type and self.task_type != "ALL":
            params["taskType"] = self.task_type

        try:
            data = self._request("GET", "/api/v2/activity/activityLog", params=params)
        except Exception as e:
            print(f"WARN [Informatica] pull_state failed: {e}")
            return []

        entries = data if isinstance(data, list) else (data.get("entries") or data.get("activityLog") or [])
        envelopes = []

        for item in entries:
            if not isinstance(item, dict):
                continue

            task_name = item.get("objectName") or item.get("taskName") or item.get("name") or "Informatica_Task"
            if self.task_filter and self.task_filter.lower() not in task_name.lower():
                continue

            raw_state = str(item.get("executionState") or item.get("state") or "").strip().lower()
            status = INFORMATICA_STATUS_MAP.get(raw_state, "failed" if "fail" in raw_state else ("running" if "run" in raw_state else "succeeded"))

            run_id = item.get("id") or item.get("runId")
            started_at = parse_infa_timestamp(item.get("startTime") or item.get("start_time"))
            finished_at = parse_infa_timestamp(item.get("endTime") or item.get("end_time"))

            # Calculate duration seconds if timestamps exist
            duration = None
            if started_at and finished_at:
                try:
                    dt_start = datetime.fromisoformat(started_at)
                    dt_end = datetime.fromisoformat(finished_at)
                    duration = max(0.0, (dt_end - dt_start).total_seconds())
                except Exception:
                    pass

            rows_read = item.get("rowsRead") or item.get("sourceSuccessRows") or item.get("successRows") or 0
            rows_written = item.get("successRows") or item.get("targetSuccessRows") or item.get("rowsWritten") or 0
            failed_rows = item.get("failedRows") or item.get("errorRows") or 0
            error_msg = item.get("errorMsg") or item.get("errorMessage")

            if status == "failed" and not error_msg:
                error_msg = f"Informatica task {task_name} terminated with failure (state={raw_state})"

            # Extract relations touched by this task
            relations = []
            if item.get("sourceName"):
                relations.append(str(item.get("sourceName")))
            if item.get("targetName"):
                relations.append(str(item.get("targetName")))

            failed_nodes = []
            if status == "failed":
                failed_nodes.append({
                    "node_id": str(run_id),
                    "name": task_name,
                    "error": error_msg,
                    "type": item.get("taskType") or "MTT",
                })

            envelopes.append({
                "source_system": "informatica",
                "tenant_id": self.tenant_id,
                "connector_instance_id": self.connector_instance_id,
                "raw": {
                    "id": str(run_id),
                    "run_id": str(run_id),
                    "external_run_id": str(item.get("runId") or run_id),
                    "pipeline_name": task_name,
                    "task_name": task_name,
                    "task_type": item.get("taskType") or self.task_type,
                    "status": status,
                    "started_at": started_at,
                    "finished_at": finished_at,
                    "duration": duration,
                    "error_message": error_msg,
                    "rows_read": int(rows_read) if rows_read is not None else None,
                    "rows_written": int(rows_written) if rows_written is not None else None,
                    "failed_rows": int(failed_rows) if failed_rows is not None else 0,
                    "relations": relations,
                    "failed_nodes": failed_nodes,
                },
            })

        return envelopes

    def fetch_run_assets(self, run_id: str) -> list[dict[str, Any]]:
        """
        Fetches detailed source/target dataset transformations from /api/v2/activity/activityLog/{id}.
        Returns asset rows for obs_run_assets with roles 'SOURCE' and 'TARGET'.
        """
        try:
            detail = self._request("GET", f"/api/v2/activity/activityLog/{run_id}")
        except Exception as e:
            print(f"WARN [Informatica] fetch_run_assets({run_id}) failed: {e}")
            return []

        entries = detail.get("transformationEntries") or []
        assets = []

        for tx in entries:
            if not isinstance(tx, dict):
                continue

            tx_name = tx.get("txName") or tx.get("transformationName") or tx.get("name") or "dataset"
            tx_type = str(tx.get("txType") or "").lower()

            # Determine whether this is a SOURCE or TARGET transformation
            if "target" in tx_type:
                role = "TARGET"
                row_count = tx.get("successRows") or tx.get("targetSuccessRows") or 0
            elif "source" in tx_type:
                role = "SOURCE"
                row_count = tx.get("successRows") or tx.get("sourceSuccessRows") or 0
            else:
                continue

            assets.append({
                "dataset_id": tx_name.upper(),
                "asset_role": role,
                "row_count": int(row_count) if row_count is not None else None,
                "error_rows": int(tx.get("failedRows") or 0),
                "tx_type": tx.get("txType"),
            })

        return assets

    def fetch_test_results(self, run_id: str) -> list[dict[str, Any]]:
        """
        Extracts Data Quality assertion results from failed/rejected rows in the task run.
        Populates obs_check_results with automated gating telemetry.
        """
        try:
            detail = self._request("GET", f"/api/v2/activity/activityLog/{run_id}")
        except Exception:
            return []

        tests: list[dict[str, Any]] = []
        entries = detail.get("transformationEntries") or []

        # If transformationEntries exists, create check per transformation target
        for tx in entries:
            if not isinstance(tx, dict):
                continue
            tx_name = tx.get("txName") or "Transformation"
            failed_rows = int(tx.get("failedRows") or 0)
            success_rows = int(tx.get("successRows") or 0)

            if failed_rows > 0:
                tests.append({
                    "check_name": f"{tx_name}_error_rows_check",
                    "column_name": "N/A",
                    "dataset_id": tx_name.upper(),
                    "status": "fail",
                    "failure_count": failed_rows,
                    "total_rows": success_rows + failed_rows,
                    "check_type": "infa_rejected_rows",
                    "source": "informatica_cdi",
                })
            elif success_rows > 0:
                tests.append({
                    "check_name": f"{tx_name}_integrity_check",
                    "column_name": "N/A",
                    "dataset_id": tx_name.upper(),
                    "status": "pass",
                    "failure_count": 0,
                    "total_rows": success_rows,
                    "check_type": "infa_transformation_integrity",
                    "source": "informatica_cdi",
                })

        # If no granular transformations, check top-level failedRows on activity entry
        if not tests:
            failed_rows = int(detail.get("failedRows") or 0)
            success_rows = int(detail.get("successRows") or 0)
            task_name = detail.get("objectName") or "Informatica_Task"

            if failed_rows > 0:
                tests.append({
                    "check_name": f"{task_name}_row_error_gate",
                    "column_name": "N/A",
                    "dataset_id": task_name.upper(),
                    "status": "fail",
                    "failure_count": failed_rows,
                    "total_rows": success_rows + failed_rows,
                    "check_type": "infa_error_rows",
                    "source": "informatica_cdi",
                })
            elif success_rows > 0:
                tests.append({
                    "check_name": f"{task_name}_execution_gate",
                    "column_name": "N/A",
                    "dataset_id": task_name.upper(),
                    "status": "pass",
                    "failure_count": 0,
                    "total_rows": success_rows,
                    "check_type": "infa_pipeline_pass",
                    "source": "informatica_cdi",
                })

        return tests

    def fetch_session_log(self, run_id: str) -> str | None:
        """
        Retrieves the raw session execution log for Root Cause Analysis (RCA).
        Endpoint: /api/v2/activity/activityLog/{run_id}/sessionLog
        """
        try:
            self._login()
            base = (self._server_url or self.pod_url).rstrip("/")
            url = f"{base}/api/v2/activity/activityLog/{run_id}/sessionLog"
            resp = requests.get(url, headers=self._auth_headers(), timeout=self.timeout)
            if resp.ok:
                return resp.text
        except Exception as e:
            print(f"WARN [Informatica] fetch_session_log({run_id}) failed: {e}")
        return None
