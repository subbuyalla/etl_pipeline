from __future__ import annotations

from pathlib import Path
from typing import Any, Iterator

from connector_sdk import Connector, RawEnvelope

from connectors.csv_util import read_csv_rows


class DbtCsvConnector(Connector):
    """
    dbt connector fed by CSV (no dbt Cloud / CLI credentials).

    Rows look like run_results entries (unique_id + status) or flat pipeline runs.
    """

    tool_id = "dbt"

    def __init__(
        self,
        csv_source: str | Path,
        *,
        tenant_id: str = "demo",
        connector_instance_id: str | None = None,
    ) -> None:
        self.csv_source = csv_source
        self.tenant_id = tenant_id
        self.connector_instance_id = connector_instance_id or "dbt-csv-1"
        self._rows = read_csv_rows(csv_source)

    def discover(self) -> list[dict[str, Any]]:
        projects: set[str] = set()
        models: list[dict[str, Any]] = []
        for row in self._rows:
            project = str(
                row.get("project_name")
                or row.get("project")
                or row.get("pipeline_id")
                or "dbt"
            )
            projects.add(project)
            uid = row.get("unique_id") or row.get("task_id") or row.get("node_name")
            if uid:
                models.append(
                    {
                        "asset_type": "task",
                        "pipeline_id": project,
                        "task_id": str(uid),
                        "platform": "dbt",
                    }
                )
        assets: list[dict[str, Any]] = [
            {"asset_type": "pipeline", "pipeline_id": p, "platform": "dbt"} for p in sorted(projects)
        ]
        assets.extend(models)
        return assets

    def pull_state(self) -> list[RawEnvelope]:
        return list(self._iter_envelopes())

    def stream_events(self, *, ticks: int | None = None) -> Iterator[RawEnvelope]:
        count = 0
        for env in self._iter_envelopes():
            yield env
            count += 1
            if ticks is not None and count >= ticks:
                return

    def _iter_envelopes(self) -> Iterator[RawEnvelope]:
        for row in self._rows:
            raw = dict(row)
            # Ensure project_name for dbt mapper
            if "project_name" not in raw:
                if "project" in raw:
                    raw["project_name"] = raw["project"]
                elif "pipeline_id" in raw:
                    raw["project_name"] = raw["pipeline_id"]
            if "invocation_id" not in raw and "run_id" in raw:
                raw["invocation_id"] = raw["run_id"]
            if "unique_id" not in raw and "task_id" in raw:
                # Flat task row — still usable via OrchestrationMapper fallback
                pass
            yield RawEnvelope(
                source_system=self.tool_id,
                tenant_id=self.tenant_id,
                raw=raw,
                connector_instance_id=self.connector_instance_id,
                meta={"input": "csv"},
            )
