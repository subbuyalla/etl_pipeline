from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterator
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from connector_sdk import ConnectionResult, Connector, ConnectorContext, RawEnvelope

from connectors.dbt import DbtCsvConnector
from connectors.specs import DBT_SPEC


class DbtPathConnector(Connector):
    """Local dbt artifacts (run_results.json / optional manifest)."""

    tool_id = "dbt"
    spec = DBT_SPEC

    def __init__(self, ctx: ConnectorContext) -> None:
        self.ctx = ctx
        self.tenant_id = ctx.tenant_id
        self.connector_instance_id = ctx.connector_instance_id
        path = ctx.config.get("run_results_path")
        if not path:
            raise ValueError("run_results_path is required when input_mode=path")
        self.run_results_path = Path(path)
        self.project_name = str(ctx.config.get("project_name") or "analytics")

    def test_connection(self) -> ConnectionResult:
        if not self.run_results_path.is_file():
            return ConnectionResult(ok=False, message=f"File not found: {self.run_results_path}")
        try:
            data = json.loads(self.run_results_path.read_text(encoding="utf-8"))
            results = data.get("results") if isinstance(data, dict) else None
            return ConnectionResult(
                ok=True,
                message="dbt artifact readable",
                details={"results": len(results or [])},
            )
        except Exception as exc:
            return ConnectionResult(ok=False, message=str(exc))

    def discover(self) -> list[dict[str, Any]]:
        assets = [{"asset_type": "pipeline", "pipeline_id": self.project_name, "platform": "dbt"}]
        for env in self.pull_state():
            uid = env.raw.get("unique_id")
            if uid:
                assets.append(
                    {
                        "asset_type": "task",
                        "pipeline_id": self.project_name,
                        "task_id": uid,
                        "platform": "dbt",
                    }
                )
        return assets

    def pull_state(self) -> list[RawEnvelope]:
        data = json.loads(self.run_results_path.read_text(encoding="utf-8"))
        meta = data.get("metadata") if isinstance(data, dict) else {}
        results = data.get("results") if isinstance(data, dict) else []
        project = str((meta or {}).get("project_name") or self.project_name)
        invocation = str((meta or {}).get("invocation_id") or "local")
        generated = (meta or {}).get("generated_at")
        envelopes: list[RawEnvelope] = []
        for row in results or []:
            raw = dict(row)
            raw["project_name"] = project
            raw["invocation_id"] = invocation
            if generated and "generated_at" not in raw:
                raw["generated_at"] = generated
            raw["_parent_metadata"] = meta or {}
            envelopes.append(
                RawEnvelope(
                    source_system=self.tool_id,
                    tenant_id=self.tenant_id,
                    raw=raw,
                    connector_instance_id=self.connector_instance_id,
                    meta={"input": "path"},
                )
            )
        return envelopes

    def stream_events(self, *, ticks: int | None = None) -> Iterator[RawEnvelope]:
        count = 0
        for env in self.pull_state():
            yield env
            count += 1
            if ticks is not None and count >= ticks:
                return


class DbtCloudConnector(Connector):
    """dbt Cloud API (jobs / runs) — token from env via secrets_ref."""

    tool_id = "dbt"
    spec = DBT_SPEC

    def __init__(self, ctx: ConnectorContext) -> None:
        self.ctx = ctx
        self.tenant_id = ctx.tenant_id
        self.connector_instance_id = ctx.connector_instance_id
        self.config = ctx.config
        self.token = ctx.secrets.get("api_token") or ""
        self.api_base = str(ctx.config.get("api_base") or "https://cloud.getdbt.com/api/v2").rstrip("/")

    def _headers(self) -> dict[str, str]:
        if not self.token:
            raise RuntimeError(
                f"Missing dbt Cloud token. Set env var "
                f"{self.config.get('api_token_env') or 'DBT_CLOUD_API_TOKEN'}."
            )
        return {"Authorization": f"Token {self.token}", "Content-Type": "application/json"}

    def _get(self, path: str) -> dict[str, Any]:
        url = f"{self.api_base}{path}"
        req = Request(url, headers=self._headers(), method="GET")
        try:
            with urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")[:300]
            raise RuntimeError(f"dbt Cloud API {exc.code}: {body}") from exc
        except URLError as exc:
            raise RuntimeError(f"dbt Cloud unreachable: {exc}") from exc

    def test_connection(self) -> ConnectionResult:
        account_id = self.config.get("account_id")
        if not account_id:
            return ConnectionResult(ok=False, message="account_id is required for dbt Cloud live mode")
        try:
            data = self._get(f"/accounts/{account_id}/")
            name = (data.get("data") or {}).get("name")
            return ConnectionResult(ok=True, message="dbt Cloud connection OK", details={"account": name})
        except Exception as exc:
            return ConnectionResult(ok=False, message=str(exc), details={"error_type": type(exc).__name__})

    def discover(self) -> list[dict[str, Any]]:
        project = str(self.config.get("project_id") or "dbt")
        return [{"asset_type": "pipeline", "pipeline_id": f"dbt-cloud-{project}", "platform": "dbt"}]

    def pull_state(self) -> list[RawEnvelope]:
        account_id = self.config.get("account_id")
        job_id = self.config.get("job_id")
        if not account_id:
            raise ValueError("account_id is required")
        if job_id:
            path = f"/accounts/{account_id}/runs/?job_definition_id={job_id}&order_by=-id&limit=10"
        else:
            path = f"/accounts/{account_id}/runs/?order_by=-id&limit=10"
        data = self._get(path)
        runs = data.get("data") or []
        project_name = str(self.config.get("project_name") or f"dbt-{self.config.get('project_id') or 'cloud'}")
        envelopes: list[RawEnvelope] = []
        for run in runs:
            status_code = run.get("status")
            status = "succeeded" if status_code == 10 else "failed" if status_code in {20, 30} else "running"
            run_id = str(run.get("id"))
            # Prefer per-node run_results artifact when available
            artifact_envs = self._try_run_results_artifact(account_id, run_id, project_name)
            if artifact_envs:
                envelopes.extend(artifact_envs)
                continue
            raw = {
                "project_name": project_name,
                "pipeline_id": project_name,
                "run_id": run_id,
                "invocation_id": run_id,
                "status": status,
                "started_at": run.get("started_at"),
                "finished_at": run.get("finished_at"),
                "error_message": run.get("status_message"),
            }
            envelopes.append(
                RawEnvelope(
                    source_system=self.tool_id,
                    tenant_id=self.tenant_id,
                    raw=raw,
                    connector_instance_id=self.connector_instance_id,
                    meta={"input": "live", "dbt_cloud": True},
                )
            )
        return envelopes

    def _try_run_results_artifact(
        self, account_id: Any, run_id: str, project_name: str
    ) -> list[RawEnvelope]:
        """Fetch run_results.json from dbt Cloud artifacts when the API allows it."""
        try:
            data = self._get(f"/accounts/{account_id}/runs/{run_id}/artifacts/run_results.json")
        except Exception:
            return []
        if not isinstance(data, dict):
            return []
        meta = data.get("metadata") or {}
        results = data.get("results") or []
        project = str(meta.get("project_name") or project_name)
        invocation = str(meta.get("invocation_id") or run_id)
        generated = meta.get("generated_at")
        envelopes: list[RawEnvelope] = []
        for row in results:
            raw = dict(row)
            raw["project_name"] = project
            raw["invocation_id"] = invocation
            if generated and "generated_at" not in raw:
                raw["generated_at"] = generated
            raw["_parent_metadata"] = meta
            envelopes.append(
                RawEnvelope(
                    source_system=self.tool_id,
                    tenant_id=self.tenant_id,
                    raw=raw,
                    connector_instance_id=self.connector_instance_id,
                    meta={"input": "live", "dbt_cloud_artifact": True},
                )
            )
        return envelopes

    def stream_events(self, *, ticks: int | None = None) -> Iterator[RawEnvelope]:
        count = 0
        for env in self.pull_state():
            yield env
            count += 1
            if ticks is not None and count >= ticks:
                return


def create_dbt_connector(ctx: ConnectorContext) -> Connector:
    mode = (ctx.input_mode or ctx.config.get("input_mode") or "live").lower()
    if mode == "csv":
        path = ctx.config.get("csv_path")
        if not path:
            raise ValueError("csv_path is required when input_mode=csv")
        return DbtCsvConnector(
            path,
            tenant_id=ctx.tenant_id,
            connector_instance_id=ctx.connector_instance_id,
        )
    if mode == "path":
        return DbtPathConnector(ctx)
    return DbtCloudConnector(ctx)
