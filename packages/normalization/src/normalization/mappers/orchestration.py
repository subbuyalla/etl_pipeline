from __future__ import annotations

from typing import Any

from normalization.expand import as_records, flatten_dotted
from normalization.mappers.base import BaseMapper
from normalization.utils import (
    first,
    normalize_status,
    pipeline_event_type,
    require,
    task_event_type,
)


class OrchestrationMapper(BaseMapper):
    """
    Shared mapper for ETL orchestrators.

    Production behavior:
    - Unwraps list envelopes (dag_runs, JobRuns, value, results, ...)
    - Flattens nested state/conf objects
    - Emits one canonical event per record
    """

    family = "etl_orchestration"

    pipeline_keys = ("pipeline_id", "dag_id", "job_name", "jobName", "JobName", "pipeline_name", "name", "flow_name")
    run_keys = ("run_id", "execution_id", "job_run_id", "JobRunId", "dag_run_id", "instance_id", "Id", "id")
    status_keys = ("status", "state", "jobRunState", "JobRunState", "run_status", "Result", "state_name")
    task_keys = ("task_id", "task_name", "activity_name", "activityName", "step_name", "op_name", "step_key")
    start_keys = ("start_time", "start_date", "started_at", "StartTime", "StartedOn", "runStart")
    end_keys = ("end_time", "end_date", "finished_at", "EndTime", "CompletedOn", "runEnd")
    time_keys = ("occurred_at", "execution_date", "logical_date", "event_time", "timestamp", "data_interval_start")
    error_keys = ("error", "error_message", "ErrorMessage", "message", "exception", "note")

    def map(
        self,
        raw: dict[str, Any],
        *,
        tenant_id: str,
        connector_instance_id: str | None = None,
    ) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        for record in as_records(raw):
            events.extend(
                self.map_record(
                    flatten_dotted(record),
                    tenant_id=tenant_id,
                    connector_instance_id=connector_instance_id,
                )
            )
        if not events:
            self.fail("no mappable records found in payload")
        return events

    def map_record(
        self,
        raw: dict[str, Any],
        *,
        tenant_id: str,
        connector_instance_id: str | None = None,
    ) -> list[dict[str, Any]]:
        try:
            pipeline_id = str(require(raw, *self.pipeline_keys))
        except KeyError as exc:
            self.fail(str(exc))

        run_id = str(first(raw, *self.run_keys, default=f"{pipeline_id}-unknown"))
        status = normalize_status(first(raw, *self.status_keys, default="running"))
        occurred = first(raw, *self.time_keys, *self.end_keys, *self.start_keys)
        task_id = first(raw, *self.task_keys)
        kind = str(first(raw, "kind", "event_kind", default="")).lower()

        if task_id or kind == "task":
            task_id = str(task_id or "unknown_task")
            event_type = task_event_type(status)
            attempt = first(raw, "attempt", "try_number", "retry_count", default=1)
            try:
                attempt_i = int(attempt or 1)
            except (TypeError, ValueError):
                attempt_i = 1
            payload = {
                "pipeline_id": pipeline_id,
                "task_id": task_id,
                "execution_id": run_id,
                "status": status,
                "attempt": attempt_i,
                "started_at": first(raw, *self.start_keys),
                "finished_at": first(raw, *self.end_keys),
                "error_message": first(raw, *self.error_keys),
                "duration_ms": first(raw, "duration_ms", "duration", "execution_time"),
            }
            return [
                self.event(
                    event_type=event_type,
                    tenant_id=tenant_id,
                    payload=payload,
                    occurred_at=occurred,
                    connector_instance_id=connector_instance_id,
                    id_parts=[
                        tenant_id,
                        self.tool_id,
                        event_type,
                        pipeline_id,
                        task_id,
                        run_id,
                        status,
                        str(attempt_i),
                    ],
                )
            ]

        event_type = pipeline_event_type(status)
        payload = {
            "pipeline_id": pipeline_id,
            "execution_id": run_id,
            "status": status,
            "started_at": first(raw, *self.start_keys),
            "finished_at": first(raw, *self.end_keys),
            "error_message": first(raw, *self.error_keys),
            "duration_ms": first(raw, "duration_ms", "duration", "execution_time"),
            "triggered_by": first(raw, "triggered_by", "external_trigger", "run_type"),
        }
        upstream = first(raw, "upstream_dataset_id", "upstream")
        downstream = first(raw, "downstream_dataset_id", "downstream")
        if upstream:
            payload["upstream_dataset_id"] = upstream
        if downstream:
            payload["downstream_dataset_id"] = downstream
        return [
            self.event(
                event_type=event_type,
                tenant_id=tenant_id,
                payload=payload,
                occurred_at=occurred,
                connector_instance_id=connector_instance_id,
                id_parts=[tenant_id, self.tool_id, event_type, pipeline_id, run_id, status],
            )
        ]
