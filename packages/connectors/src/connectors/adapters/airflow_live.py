from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any, Iterator
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from connector_sdk import ConnectionResult, Connector, ConnectorContext, RawEnvelope

from connectors.csv_util import read_csv_rows
from connectors.specs import AIRFLOW_SPEC


class AirflowCsvConnector(Connector):
    """Offline Airflow DAG/task runs from CSV."""

    tool_id = "airflow"
    spec = AIRFLOW_SPEC

    def __init__(
        self,
        csv_source: str | Path,
        *,
        tenant_id: str = "demo",
        connector_instance_id: str | None = None,
    ) -> None:
        self.csv_source = csv_source
        self.tenant_id = tenant_id
        self.connector_instance_id = connector_instance_id or "airflow-csv-1"
        self._rows = read_csv_rows(csv_source)

    def test_connection(self) -> ConnectionResult:
        return ConnectionResult(ok=True, message=f"CSV readable ({len(self._rows)} rows)")

    def discover(self) -> list[dict[str, Any]]:
        dags = sorted({str(r.get("dag_id") or r.get("pipeline_id")) for r in self._rows if r.get("dag_id") or r.get("pipeline_id")})
        return [{"asset_type": "pipeline", "pipeline_id": d, "platform": "airflow"} for d in dags]

    def pull_state(self) -> list[RawEnvelope]:
        out: list[RawEnvelope] = []
        for row in self._rows:
            raw = dict(row)
            if "dag_id" not in raw and raw.get("pipeline_id"):
                raw["dag_id"] = raw["pipeline_id"]
            if "dag_run_id" not in raw and raw.get("run_id"):
                raw["dag_run_id"] = raw["run_id"]
            if "state" not in raw and raw.get("status"):
                raw["state"] = raw["status"]
            out.append(
                RawEnvelope(
                    source_system=self.tool_id,
                    tenant_id=self.tenant_id,
                    raw=raw,
                    connector_instance_id=self.connector_instance_id,
                    meta={"input": "csv"},
                )
            )
        return out

    def stream_events(self, *, ticks: int | None = None) -> Iterator[RawEnvelope]:
        count = 0
        for env in self.pull_state():
            yield env
            count += 1
            if ticks is not None and count >= ticks:
                return


class AirflowLiveConnector(Connector):
    """
    Apache Airflow REST API (2.x).
    Auth: basic (AIRFLOW_USERNAME/AIRFLOW_PASSWORD) or bearer token (AIRFLOW_TOKEN).
    """

    tool_id = "airflow"
    spec = AIRFLOW_SPEC

    def __init__(self, ctx: ConnectorContext) -> None:
        self.ctx = ctx
        self.tenant_id = ctx.tenant_id
        self.connector_instance_id = ctx.connector_instance_id
        self.config = ctx.config
        self.secrets = ctx.secrets
        self.base_url = str(ctx.config.get("base_url") or "").rstrip("/")
        if not self.base_url:
            raise ValueError("base_url is required for Airflow live mode")

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        token = self.secrets.get("api_token") or ""
        user = self.secrets.get("username") or self.config.get("username") or ""
        password = self.secrets.get("password") or ""
        if token:
            headers["Authorization"] = f"Bearer {token}"
        elif user and password:
            blob = base64.b64encode(f"{user}:{password}".encode()).decode()
            headers["Authorization"] = f"Basic {blob}"
        else:
            raise RuntimeError(
                "Missing Airflow credentials. Set AIRFLOW_TOKEN or "
                "AIRFLOW_USERNAME + AIRFLOW_PASSWORD (env names from connector form)."
            )
        return headers

    def _get(self, path: str) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        req = Request(url, headers=self._headers(), method="GET")
        try:
            with urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")[:300]
            raise RuntimeError(f"Airflow API {exc.code}: {body}") from exc
        except URLError as exc:
            raise RuntimeError(f"Airflow unreachable: {exc}") from exc

    def test_connection(self) -> ConnectionResult:
        try:
            data = self._get("/api/v1/health")
            return ConnectionResult(
                ok=True,
                message="Airflow connection OK",
                details={"metadatabase": (data.get("metadatabase") or {}).get("status")},
            )
        except Exception as exc:
            return ConnectionResult(ok=False, message=str(exc), details={"error_type": type(exc).__name__})

    def discover(self) -> list[dict[str, Any]]:
        dag_filter = (self.config.get("dag_id") or "").strip()
        if dag_filter:
            return [{"asset_type": "pipeline", "pipeline_id": dag_filter, "platform": "airflow"}]
        data = self._get("/api/v1/dags?limit=100")
        dags = data.get("dags") or []
        return [
            {"asset_type": "pipeline", "pipeline_id": d.get("dag_id"), "platform": "airflow"}
            for d in dags
            if d.get("dag_id")
        ]

    def pull_state(self) -> list[RawEnvelope]:
        dag_filter = (self.config.get("dag_id") or "").strip()
        limit = int(self.config.get("run_limit") or 20)
        envelopes: list[RawEnvelope] = []

        if dag_filter:
            dag_ids = [dag_filter]
        else:
            dag_ids = [a["pipeline_id"] for a in self.discover()[:20]]

        for dag_id in dag_ids:
            runs = self._get(f"/api/v1/dags/{dag_id}/dagRuns?order_by=-start_date&limit={limit}")
            for run in runs.get("dag_runs") or []:
                raw = {
                    "dag_id": dag_id,
                    "dag_run_id": run.get("dag_run_id"),
                    "state": run.get("state"),
                    "execution_date": run.get("execution_date") or run.get("logical_date"),
                    "start_date": run.get("start_date"),
                    "end_date": run.get("end_date"),
                    "external_trigger": run.get("external_trigger"),
                    "error": run.get("note") if run.get("state") == "failed" else None,
                }
                envelopes.append(
                    RawEnvelope(
                        source_system=self.tool_id,
                        tenant_id=self.tenant_id,
                        raw=raw,
                        connector_instance_id=self.connector_instance_id,
                        meta={"input": "live", "kind": "dag_run"},
                    )
                )
                run_id = run.get("dag_run_id")
                if not run_id:
                    continue
                try:
                    tasks = self._get(
                        f"/api/v1/dags/{dag_id}/dagRuns/{run_id}/taskInstances?limit=50"
                    )
                except Exception:
                    continue
                for ti in tasks.get("task_instances") or []:
                    state = ti.get("state")
                    err = None
                    if state in {"failed", "up_for_retry"}:
                        err = ti.get("note") or f"Task {ti.get('task_id')} {state}"
                    envelopes.append(
                        RawEnvelope(
                            source_system=self.tool_id,
                            tenant_id=self.tenant_id,
                            raw={
                                "dag_id": dag_id,
                                "task_id": ti.get("task_id"),
                                "dag_run_id": run_id,
                                "state": state,
                                "try_number": ti.get("try_number"),
                                "execution_date": ti.get("execution_date") or ti.get("start_date"),
                                "start_date": ti.get("start_date"),
                                "end_date": ti.get("end_date"),
                                "error": err,
                            },
                            connector_instance_id=self.connector_instance_id,
                            meta={"input": "live", "kind": "task_instance"},
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


def create_airflow_connector(ctx: ConnectorContext) -> Connector:
    mode = (ctx.input_mode or ctx.config.get("input_mode") or "live").lower()
    if mode == "csv":
        path = ctx.config.get("csv_path")
        if not path:
            raise ValueError("csv_path is required when input_mode=csv")
        return AirflowCsvConnector(
            path,
            tenant_id=ctx.tenant_id,
            connector_instance_id=ctx.connector_instance_id,
        )
    return AirflowLiveConnector(ctx)
