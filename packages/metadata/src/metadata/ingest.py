from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from metadata.repository import MetadataRepository
from metadata.messages import (
    distribution_message,
    distribution_title,
    freshness_message,
    volume_message,
)


def _pipeline_id_from_payload(payload: dict[str, Any]) -> str | None:
    transform = payload.get("transform") or payload.get("pipeline_id")
    return str(transform) if transform else None


def _link_pipeline_io(
    repo: MetadataRepository,
    *,
    tenant_id: str,
    pipeline_id: str,
    upstream: str,
    downstream: str,
    source_tool: str,
) -> None:
    repo.upsert_pipeline(tenant_id, pipeline_id, source_tool)
    repo.upsert_pipeline_io(
        tenant_id=tenant_id,
        pipeline_id=pipeline_id,
        upstream_dataset_id=upstream,
        downstream_dataset_id=downstream,
        source_tool=source_tool,
    )


def ingest_canonical_event(session: Session, event: dict[str, Any]) -> dict[str, Any]:
    """
    Apply one canonical event into the metadata store.
    Idempotent on event_id (event_log unique constraint).
    """
    repo = MetadataRepository(session)
    tenant_id = event["tenant_id"]
    source_tool = event.get("source_tool") or event.get("source_system")
    event_type = event["event_type"]
    payload = event.get("payload") or {}

    logged = repo.record_event_log(event)
    if logged is None:
        return {"status": "duplicate", "event_id": event["event_id"]}

    repo.ensure_tool(tenant_id, source_tool, event.get("connector_instance_id"))

    if event_type.startswith("pipeline.execution."):
        pipeline_id = str(payload["pipeline_id"])
        repo.upsert_pipeline(tenant_id, pipeline_id, source_tool)
        status = str(payload.get("status") or "unknown")
        repo.upsert_execution(
            tenant_id=tenant_id,
            execution_id=str(payload.get("execution_id")),
            pipeline_id=pipeline_id,
            source_tool=source_tool,
            status=status,
            started_at=payload.get("started_at"),
            finished_at=payload.get("finished_at"),
            duration_ms=payload.get("duration_ms"),
            error_message=payload.get("error_message"),
            triggered_by=payload.get("triggered_by"),
        )
        pipe = repo.upsert_pipeline(tenant_id, pipeline_id, source_tool)
        pipe.status = status
        upstream = payload.get("upstream_dataset_id") or payload.get("upstream")
        downstream = payload.get("downstream_dataset_id") or payload.get("downstream")
        if upstream and downstream:
            _link_pipeline_io(
                repo,
                tenant_id=tenant_id,
                pipeline_id=pipeline_id,
                upstream=str(upstream),
                downstream=str(downstream),
                source_tool=source_tool,
            )
        if status == "failed":
            repo.raise_alert_and_incident(
                tenant_id=tenant_id,
                title=f"Pipeline failed: {pipeline_id}",
                asset_type="pipeline",
                asset_id=pipeline_id,
                monitor_type="pipeline_failure",
                severity="high",
                message=payload.get("error_message"),
                event_id=event["event_id"],
            )

    elif event_type.startswith("task.execution."):
        pipeline_id = str(payload["pipeline_id"])
        task_id = str(payload["task_id"])
        repo.upsert_pipeline(tenant_id, pipeline_id, source_tool)
        repo.upsert_task(tenant_id, pipeline_id, task_id, source_tool)
        status = str(payload.get("status") or "unknown")
        repo.upsert_execution(
            tenant_id=tenant_id,
            execution_id=str(payload.get("execution_id")),
            pipeline_id=pipeline_id,
            task_id=task_id,
            source_tool=source_tool,
            status=status,
            attempt=int(payload.get("attempt") or 1),
            started_at=payload.get("started_at"),
            finished_at=payload.get("finished_at"),
            duration_ms=payload.get("duration_ms"),
            error_message=payload.get("error_message"),
        )
        if status == "failed":
            repo.raise_alert_and_incident(
                tenant_id=tenant_id,
                title=f"Task failed: {pipeline_id}.{task_id}",
                asset_type="task",
                asset_id=f"{pipeline_id}.{task_id}",
                monitor_type="task_failure",
                severity="high",
                message=payload.get("error_message"),
                event_id=event["event_id"],
            )

    elif event_type == "dataset.discovered.v1":
        repo.upsert_dataset(tenant_id, payload, platform=str(payload.get("platform") or source_tool))
        if payload.get("row_count") is not None:
            try:
                repo.add_metric(
                    tenant_id,
                    "row_count",
                    float(payload["row_count"]),
                    asset_type="dataset",
                    asset_id=str(payload.get("dataset_id")),
                    unit="rows",
                    recorded_at=event.get("occurred_at"),
                )
            except (TypeError, ValueError):
                pass

    elif event_type == "dataset.freshness.breached.v1":
        ds = repo.upsert_dataset(tenant_id, payload, platform=str(payload.get("platform") or source_tool))
        monitor = repo.ensure_monitor(tenant_id, "freshness", ds.dataset_id, config={"sla_minutes": payload.get("sla_minutes")})
        lag = payload.get("lag_minutes")
        repo.add_check_result(
            tenant_id=tenant_id,
            monitor=monitor,
            status="failed",
            metric_value=float(lag) if lag is not None else None,
            baseline_value=float(payload["sla_minutes"]) if payload.get("sla_minutes") is not None else None,
            severity=str(payload.get("severity") or "high"),
            details=payload,
            checked_at=event.get("occurred_at"),
        )
        repo.raise_alert_and_incident(
            tenant_id=tenant_id,
            title=f"Freshness breach: {ds.dataset_id}",
            asset_type="dataset",
            asset_id=ds.dataset_id,
            monitor_type="freshness",
            severity=str(payload.get("severity") or "high"),
            message=freshness_message(lag, payload.get("sla_minutes")),
            event_id=event["event_id"],
        )

    elif event_type == "dataset.volume.anomaly.v1":
        ds = repo.upsert_dataset(tenant_id, payload, platform=str(payload.get("platform") or source_tool))
        monitor = repo.ensure_monitor(tenant_id, "volume", ds.dataset_id)
        row_count = payload.get("row_count")
        repo.add_check_result(
            tenant_id=tenant_id,
            monitor=monitor,
            status="anomalous",
            metric_value=float(row_count) if row_count is not None else None,
            baseline_value=float(payload["expected_min"]) if payload.get("expected_min") is not None else None,
            severity=str(payload.get("severity") or "medium"),
            details=payload,
            checked_at=event.get("occurred_at"),
        )
        repo.raise_alert_and_incident(
            tenant_id=tenant_id,
            title=f"Volume anomaly: {ds.dataset_id}",
            asset_type="dataset",
            asset_id=ds.dataset_id,
            monitor_type="volume",
            severity=str(payload.get("severity") or "medium"),
            message=volume_message(row_count, payload.get("expected_min"), payload.get("expected_max")),
            event_id=event["event_id"],
        )

    elif event_type == "dataset.schema.changed.v1":
        ds = repo.upsert_dataset(tenant_id, payload, platform=str(payload.get("platform") or source_tool))
        monitor = repo.ensure_monitor(tenant_id, "schema", ds.dataset_id)
        breaking = bool(payload.get("breaking"))
        repo.add_check_result(
            tenant_id=tenant_id,
            monitor=monitor,
            status="failed" if breaking else "anomalous",
            severity="high" if breaking else "medium",
            details=payload,
            checked_at=event.get("occurred_at"),
        )
        repo.add_change_event(
            tenant_id,
            change_type="schema",
            asset_id=ds.dataset_id,
            breaking=breaking,
            details=payload,
            source_tool=source_tool,
            occurred_at=event.get("occurred_at"),
        )
        repo.raise_alert_and_incident(
            tenant_id=tenant_id,
            title=f"Schema change: {ds.dataset_id}",
            asset_type="dataset",
            asset_id=ds.dataset_id,
            monitor_type="schema",
            severity="high" if breaking else "medium",
            message=str(payload.get("change_type")),
            event_id=event["event_id"],
        )

    elif event_type == "dataset.distribution.anomaly.v1":
        ds = repo.upsert_dataset(tenant_id, payload, platform=str(payload.get("platform") or source_tool))
        monitor = repo.ensure_monitor(tenant_id, "distribution", ds.dataset_id)
        value = payload.get("value")
        repo.add_check_result(
            tenant_id=tenant_id,
            monitor=monitor,
            status="anomalous",
            metric_value=float(value) if value is not None else None,
            baseline_value=float(payload["baseline"]) if payload.get("baseline") is not None else None,
            severity=str(payload.get("severity") or "medium"),
            details=payload,
            checked_at=event.get("occurred_at"),
        )
        repo.raise_alert_and_incident(
            tenant_id=tenant_id,
            title=distribution_title(ds.dataset_id, payload.get("column")),
            asset_type="dataset",
            asset_id=ds.dataset_id,
            monitor_type="distribution",
            severity=str(payload.get("severity") or "medium"),
            message=distribution_message(
                payload.get("metric"),
                value,
                payload.get("baseline"),
                payload.get("column"),
            ),
            event_id=event["event_id"],
        )

    elif event_type == "lineage.edge.upserted.v1":
        upstream = str(payload["upstream_dataset_id"])
        downstream = str(payload["downstream_dataset_id"])
        transform = _pipeline_id_from_payload(payload)
        repo.upsert_lineage(
            tenant_id,
            upstream=upstream,
            downstream=downstream,
            confidence=str(payload.get("confidence") or "observed"),
            transform=transform,
            platform=payload.get("platform") or source_tool,
        )
        if transform:
            _link_pipeline_io(
                repo,
                tenant_id=tenant_id,
                pipeline_id=transform,
                upstream=upstream,
                downstream=downstream,
                source_tool=source_tool,
            )

    elif event_type == "alert.raised.v1":
        repo.raise_alert_and_incident(
            tenant_id=tenant_id,
            title=str(payload.get("title") or "Alert"),
            asset_type=str(payload.get("asset_type") or "dataset"),
            asset_id=str(payload.get("asset_id") or "unknown"),
            monitor_type=str(payload.get("monitor_type") or "custom"),
            severity=str(payload.get("severity") or "medium"),
            message=payload.get("message"),
            event_id=event["event_id"],
        )

    elif event_type == "monitor.check.completed.v1":
        asset_id = str(payload.get("asset_id") or payload.get("dataset_id") or "unknown")
        monitor_type = str(payload.get("monitor_type") or "custom")
        monitor = repo.ensure_monitor(tenant_id, monitor_type, asset_id)
        repo.add_check_result(
            tenant_id=tenant_id,
            monitor=monitor,
            status=str(payload.get("status") or "passed"),
            metric_value=float(payload["metric_value"]) if payload.get("metric_value") is not None else None,
            details=payload,
            checked_at=event.get("occurred_at"),
        )

    session.commit()
    return {"status": "ingested", "event_id": event["event_id"], "event_type": event_type}


def ingest_canonical_events(session: Session, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    results = []
    for event in events:
        results.append(ingest_canonical_event(session, event))
    return results
