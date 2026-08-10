import os
import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def relation_short_names(relations: list[str] | None) -> list[str]:
    """Extract bare table names from dbt relation_name values (DB.SCHEMA.TABLE)."""
    out: list[str] = []
    seen: set[str] = set()
    for rel in relations or []:
        text = str(rel or "").strip()
        if not text:
            continue
        # Strip quotes and take last segment
        parts = text.replace('"', "").replace("`", "").split(".")
        name = (parts[-1] if parts else text).strip().upper()
        if name and name not in seen:
            seen.add(name)
            out.append(name)
    return out


def classify_error_class(message: str | None) -> str:
    text = (message or "").lower()
    if not text:
        return "unknown"
    if any(k in text for k in ("compilation error", "compile error", "parsing error")):
        return "compilation"
    if any(
        k in text
        for k in (
            "permission",
            "not authorized",
            "access control",
            "insufficient privileges",
        )
    ):
        return "permission"
    if any(k in text for k in ("timeout", "timed out", "deadline")):
        return "timeout"
    if any(
        k in text
        for k in (
            "runtime error",
            "database error",
            "sql compilation",
            "does not exist",
            "null value",
            "duplicate",
        )
    ):
        return "runtime"
    return "unknown"


class DbtConnector:
    """one class= one tool(dbt)"""

    tool_id = "dbt_lab"

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

    def _get_optional(self, path: str) -> dict | None:
        """GET that returns None on 404/errors (artifacts are often missing)."""
        try:
            return self._get(path)
        except Exception:
            return None

    def _row_counts_from_artifact(self, run_id: str) -> dict:
        """
        From run_results.json artifact, sum adapter rows_affected.
        Collect all failed nodes for RCA and relation names for table filters.
        """
        data = self._get_optional(
            f"/accounts/{self.account_id}/runs/{run_id}/artifacts/run_results.json"
        )
        empty = {
            "rows_read": None,
            "rows_written": None,
            "node_count": None,
            "relations": [],
            "rows_from": None,
            "failed_node": None,
            "failed_message": None,
            "failure_stage": None,
            "failed_nodes": [],
            "error_class": None,
        }
        if not isinstance(data, dict):
            return empty

        total = 0
        found = False
        relations: list[str] = []
        failed_nodes: list[dict] = []
        failed_node = None
        failed_message = None

        for result in data.get("results") or []:
            if not isinstance(result, dict):
                continue
            rel = result.get("relation_name")
            if rel:
                relations.append(str(rel))

            unique_id = result.get("unique_id") or result.get("node")
            status = str(result.get("status") or "").lower()
            msg = result.get("message") or result.get("error") or ""
            if status in {"error", "fail", "failed"}:
                entry = {
                    "unique_id": str(unique_id or rel or "unknown_node"),
                    "status": status,
                    "message": str(msg)[:2000] if msg else None,
                    "relation_name": str(rel) if rel else None,
                }
                failed_nodes.append(entry)
                if failed_node is None:
                    failed_node = entry["unique_id"]
                    failed_message = entry["message"]

            adapter = result.get("adapter_response") or {}
            rows = None
            if isinstance(adapter, dict):
                rows = adapter.get("rows_affected")
                if rows is None:
                    rows = adapter.get("rowcount") or adapter.get("rows")
            if rows is None:
                rows = result.get("rows_affected")
            if isinstance(rows, (int, float)):
                total += int(rows)
                found = True

        failure_stage = "etl" if failed_node else None
        error_class = (
            classify_error_class(failed_message) if failed_node else None
        )

        base = {
            "node_count": len(data.get("results") or []),
            "relations": relations,
            "failed_node": failed_node,
            "failed_message": failed_message,
            "failure_stage": failure_stage,
            "failed_nodes": failed_nodes,
            "error_class": error_class,
        }

        if not found:
            return {
                **base,
                "rows_read": None,
                "rows_written": None,
                "rows_from": None,
            }
        return {
            **base,
            "rows_read": total,
            "rows_written": total,
            "rows_from": "dbt_run_results_artifact",
        }

    @staticmethod
    def _infer_failure_stage(
        *,
        status: str,
        error_message: str | None,
        failed_node: str | None,
        artifact_stage: str | None,
    ) -> str | None:
        """Classify failure location for assistant RCA (best-effort)."""
        if status != "failed":
            return None
        text = (error_message or "").lower()
        node = (failed_node or "").lower()

        # Source / upstream read signals
        if any(
            k in text
            for k in (
                "source(",
                "source not found",
                "upstream",
                "seed not found",
                "depends on",
                "could not find raw",
            )
        ) or node.startswith("source."):
            return "source"

        # Target / warehouse write signals
        if any(
            k in text
            for k in (
                "does not exist or not authorized",
                "insufficient privileges",
                "permission denied",
                "not authorized to",
                "cannot create",
                "object does not exist",
                "warehouse",
            )
        ):
            return "target"

        if artifact_stage:
            return artifact_stage
        if failed_node:
            return "etl"
        if any(
            k in text
            for k in (
                "compilation error",
                "database error in model",
                "runtime error",
                "dbt",
                "model.",
                "snapshot.",
                "test.",
            )
        ):
            return "etl"
        if any(k in text for k in ("connection", "timeout", "network", "unreachable")):
            return "unknown"
        return "etl"

    def _job_ids_for_project(self) -> set[str]:
        """Resolve job definition ids for this connector's project (shared accounts)."""
        if not self.project_id:
            return set()
        try:
            data = self._get(
                f"/accounts/{self.account_id}/jobs/"
                f"?project_id={self.project_id}&limit=100"
            )
        except Exception:
            return set()
        jobs = data.get("data") or []
        out: set[str] = set()
        for job in jobs:
            jid = job.get("id")
            if jid is not None:
                out.add(str(jid))
        return out

    def _fetch_runs(self, *, limit: int = 10) -> list[dict]:
        """
        Pull recent dbt Cloud job runs (metadata/logs, not business data).
        Enriches with rows_read/rows_written and failure node from run_results.json.
        """
        if not self.account_id:
            raise ValueError("account_id is required")

        if self.job_id:
            path = (
                f"/accounts/{self.account_id}/runs/"
                f"?job_definition_id={self.job_id}&order_by=-id&limit={limit}"
            )
        else:
            # Do not pass project_id here — some dbt hosts return 404 for that filter.
            path = (
                f"/accounts/{self.account_id}/runs/"
                f"?order_by=-id&limit={max(limit, 30)}"
            )

        data = self._get(path)
        runs = data.get("data") or []

        if self.job_id:
            pass
        elif self.project_id:
            want_project = str(self.project_id)
            job_ids = self._job_ids_for_project()
            filtered = []
            for r in runs:
                rid_project = str(r.get("project_id") or "")
                rid_job = str(r.get("job_definition_id") or "")
                if rid_project and rid_project == want_project:
                    filtered.append(r)
                elif job_ids and rid_job in job_ids:
                    filtered.append(r)
            runs = filtered[:limit]

        rows: list[dict] = []
        for run in runs:
            status_code = run.get("status")
            if status_code == 10:
                status = "succeeded"
            elif status_code in {20, 30}:
                status = "failed"
            else:
                status = "running"

            run_id = str(run.get("id"))
            counts = self._row_counts_from_artifact(run_id)
            relations = counts.pop("relations", [])
            failed_nodes = counts.pop("failed_nodes", []) or []
            error_message = run.get("status_message")
            failed_node = counts.get("failed_node")
            failed_message = counts.get("failed_message")
            # Prefer node-level message when present
            if failed_message and (
                not error_message or len(str(failed_message)) > len(str(error_message))
            ):
                error_message = failed_message

            failure_stage = self._infer_failure_stage(
                status=status,
                error_message=error_message,
                failed_node=failed_node,
                artifact_stage=counts.get("failure_stage"),
            )
            error_class = counts.get("error_class")
            if status == "failed" and not error_class:
                error_class = classify_error_class(error_message)

            rows.append(
                {
                    "run_id": run_id,
                    "job_id": str(run.get("job_definition_id") or self.job_id or ""),
                    "project_name": self.project_name,
                    "status": status,
                    "status_code": status_code,
                    "started_at": run.get("started_at"),
                    "finished_at": run.get("finished_at"),
                    "error_message": error_message,
                    "rows_read": counts.get("rows_read"),
                    "rows_written": counts.get("rows_written"),
                    "node_count": counts.get("node_count"),
                    "relations": relations,
                    "rows_from": counts.get("rows_from"),
                    "failed_node": failed_node,
                    "failed_message": failed_message,
                    "failure_stage": failure_stage,
                    "failed_nodes": failed_nodes,
                    "error_class": error_class,
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
                        "rows_read": row.get("rows_read"),
                        "rows_written": row.get("rows_written"),
                        "node_count": row.get("node_count"),
                        "relations": row.get("relations") or [],
                        "rows_from": row.get("rows_from"),
                        "failed_node": row.get("failed_node"),
                        "failed_message": row.get("failed_message"),
                        "failure_stage": row.get("failure_stage"),
                        "failed_nodes": row.get("failed_nodes") or [],
                        "error_class": row.get("error_class"),
                    },
                }
            )
        return envelopes
