from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone
from typing import Any, Iterator
from uuid import uuid4

from connector_sdk import Connector, RawEnvelope
from simulator.estate import TwinEstate, TwinPipeline, default_estate


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _iso(dt: datetime) -> str:
    return dt.isoformat().replace("+00:00", "Z")


SCENARIOS = (
    "pipeline_success",
    "pipeline_failure",
    "task_retry",
    "freshness_breach",
    "volume_anomaly",
    "schema_break",
    "distribution_anomaly",
    "lineage_upsert",
    "dataset_discovered",
    "dbt_run_results",
)


class DigitalTwinConnector(Connector):
    """
    Mock connector that speaks Airflow / Glue / dbt / Snowflake / ADF shapes.
    Same interface as future real connectors.
    """

    tool_id = "digital_twin"

    def __init__(
        self,
        estate: TwinEstate | None = None,
        *,
        tenant_id: str = "demo",
        seed: int | None = 42,
        connector_instance_id: str = "twin-local-1",
    ) -> None:
        self.estate = estate or default_estate(tenant_id)
        self.tenant_id = self.estate.tenant_id
        self.connector_instance_id = connector_instance_id
        self._rng = random.Random(seed)
        self._tick = 0

    def discover(self) -> list[dict[str, Any]]:
        assets: list[dict[str, Any]] = []
        for p in self.estate.pipelines:
            assets.append(
                {
                    "asset_type": "pipeline",
                    "pipeline_id": p.pipeline_id,
                    "tool": p.tool,
                    "domain": p.domain,
                }
            )
        for d in self.estate.datasets:
            assets.append(
                {
                    "asset_type": "dataset",
                    "dataset_id": d.dataset_id,
                    "platform": d.platform,
                    "domain": d.domain,
                }
            )
        return assets

    def pull_state(self) -> list[RawEnvelope]:
        """Bootstrap: discover datasets + lineage + a healthy run per pipeline."""
        out: list[RawEnvelope] = []
        for d in self.estate.datasets:
            out.append(self._envelope("snowflake", self._dataset_discovered(d)))
        for up, down, pipeline_id in self.estate.lineage:
            parts = down.split(".")
            out.append(
                self._envelope(
                    "snowflake",
                    {
                        "database": parts[0],
                        "schema": parts[1],
                        "table": parts[2],
                        "event_type": "lineage",
                        "upstream": up,
                        "downstream": down,
                        "transform": pipeline_id,
                    },
                )
            )
        for p in self.estate.pipelines:
            out.append(self._pipeline_event(p, success=True))
        return out

    def stream_events(self, *, ticks: int | None = None) -> Iterator[RawEnvelope]:
        emitted = 0
        while ticks is None or emitted < ticks:
            scenario = self._rng.choice(SCENARIOS)
            for env in self._generate_scenario(scenario):
                yield env
                emitted += 1
                self._tick += 1
                if ticks is not None and emitted >= ticks:
                    return

    def run_scenario(self, name: str) -> list[RawEnvelope]:
        if name not in SCENARIOS:
            raise ValueError(f"Unknown scenario '{name}'. Choose from: {SCENARIOS}")
        return list(self._generate_scenario(name))

    def _envelope(self, source_system: str, raw: dict[str, Any], **meta: Any) -> RawEnvelope:
        return RawEnvelope(
            source_system=source_system,
            tenant_id=self.tenant_id,
            raw=raw,
            connector_instance_id=self.connector_instance_id,
            meta={"scenario": meta.get("scenario"), "tick": self._tick},
        )

    def _pick_pipeline(self) -> TwinPipeline:
        return self._rng.choice(self.estate.pipelines)

    def _pick_dataset(self):
        return self._rng.choice(self.estate.datasets)

    def _generate_scenario(self, name: str) -> Iterator[RawEnvelope]:
        if name == "pipeline_success":
            yield self._pipeline_event(self._pick_pipeline(), success=True, scenario=name)
        elif name == "pipeline_failure":
            yield self._pipeline_event(self._pick_pipeline(), success=False, scenario=name)
        elif name == "task_retry":
            p = self._pick_pipeline()
            if p.tool == "airflow":
                yield self._envelope(
                    "airflow",
                    {
                        "dag_id": p.pipeline_id,
                        "task_id": "extract_orders",
                        "dag_run_id": f"twin_{uuid4().hex[:8]}",
                        "state": "up_for_retry",
                        "try_number": self._rng.randint(2, 4),
                        "execution_date": _iso(_utc_now()),
                        "start_date": _iso(_utc_now() - timedelta(minutes=5)),
                    },
                    scenario=name,
                )
            else:
                yield self._pipeline_event(p, success=False, scenario=name)
        elif name == "freshness_breach":
            d = self._pick_dataset()
            yield self._envelope(
                d.platform,
                {
                    "database": d.database,
                    "schema": d.schema,
                    "table": d.table,
                    "event_type": "freshness",
                    "last_updated_at": _iso(_utc_now() - timedelta(hours=6)),
                    "sla_minutes": 60,
                    "lag_minutes": self._rng.randint(120, 400),
                    "severity": "high",
                },
                scenario=name,
            )
        elif name == "volume_anomaly":
            d = self._pick_dataset()
            yield self._envelope(
                d.platform,
                {
                    "database": d.database,
                    "schema": d.schema,
                    "table": d.table,
                    "event_type": "volume",
                    "row_count": self._rng.randint(0, 50),
                    "expected_min": 10000,
                    "severity": "medium",
                },
                scenario=name,
            )
        elif name == "schema_break":
            d = self._pick_dataset()
            yield self._envelope(
                d.platform,
                {
                    "database": d.database,
                    "schema": d.schema,
                    "table": d.table,
                    "kind": "schema",
                    "change_type": "column_removed",
                    "columns_removed": ["legacy_id"],
                    "breaking": True,
                },
                scenario=name,
            )
        elif name == "distribution_anomaly":
            d = self._pick_dataset()
            yield self._envelope(
                d.platform,
                {
                    "database": d.database,
                    "schema": d.schema,
                    "table": d.table,
                    "event_type": "distribution",
                    "column": "email",
                    "metric": "null_rate",
                    "value": 0.42,
                    "baseline": 0.02,
                    "severity": "medium",
                },
                scenario=name,
            )
        elif name == "lineage_upsert":
            up, down, pipeline_id = self._rng.choice(self.estate.lineage)
            parts = down.split(".")
            yield self._envelope(
                "snowflake",
                {
                    "database": parts[0],
                    "schema": parts[1],
                    "table": parts[2],
                    "event_type": "lineage",
                    "upstream": up,
                    "downstream": down,
                    "transform": pipeline_id,
                },
                scenario=name,
            )
        elif name == "dataset_discovered":
            d = self._pick_dataset()
            yield self._envelope(d.platform, self._dataset_discovered(d), scenario=name)
        elif name == "dbt_run_results":
            yield self._envelope("dbt", self._dbt_run_results(), scenario=name)
        else:
            yield self._pipeline_event(self._pick_pipeline(), success=True, scenario=name)

    def _dataset_discovered(self, d) -> dict[str, Any]:
        return {
            "database": d.database,
            "schema": d.schema,
            "table": d.table,
            "row_count": self._rng.randint(1_000, 2_000_000),
            "last_updated_at": _iso(_utc_now() - timedelta(minutes=self._rng.randint(5, 90))),
            "tags": [d.domain],
        }

    def _pipeline_event(self, p: TwinPipeline, *, success: bool, scenario: str | None = None) -> RawEnvelope:
        now = _utc_now()
        start = now - timedelta(minutes=self._rng.randint(2, 30))
        run_id = f"twin_{uuid4().hex[:10]}"
        if p.tool == "airflow":
            raw = {
                "dag_id": p.pipeline_id,
                "dag_run_id": run_id,
                "state": "success" if success else "failed",
                "execution_date": _iso(start),
                "start_date": _iso(start),
                "end_date": _iso(now),
                "error": None if success else f"Twin simulated failure in {p.pipeline_id}",
            }
        elif p.tool == "glue":
            raw = {
                "JobName": p.pipeline_id,
                "Id": run_id,
                "JobRunState": "SUCCEEDED" if success else "FAILED",
                "StartedOn": _iso(start),
                "CompletedOn": _iso(now),
                "ErrorMessage": None if success else "Twin Glue job failed",
            }
        elif p.tool == "adf":
            raw = {
                "pipelineName": p.pipeline_id,
                "runId": run_id,
                "status": "Succeeded" if success else "Failed",
                "runStart": _iso(start),
                "runEnd": _iso(now),
                "message": None if success else "Twin ADF activity failed",
            }
        elif p.tool == "dbt":
            raw = self._dbt_run_results(success=success)
        else:
            raw = {
                "pipeline_id": p.pipeline_id,
                "run_id": run_id,
                "status": "succeeded" if success else "failed",
                "start_time": _iso(start),
                "end_time": _iso(now),
            }
        return self._envelope(p.tool, raw, scenario=scenario)

    def _dbt_run_results(self, success: bool = True) -> dict[str, Any]:
        inv = f"inv-{uuid4().hex[:8]}"
        return {
            "metadata": {
                "generated_at": _iso(_utc_now()),
                "invocation_id": inv,
                "project_name": "analytics",
            },
            "results": [
                {
                    "status": "success",
                    "execution_time": 1.1,
                    "unique_id": "model.analytics.fct_orders",
                    "message": None,
                },
                {
                    "status": "success" if success else "error",
                    "execution_time": 0.5,
                    "unique_id": "test.analytics.not_null_fct_orders_id",
                    "message": None if success else "Got 12 results, configured to fail if != 0",
                },
            ],
        }
