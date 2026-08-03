from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from dateutil import parser as date_parser
from sqlalchemy import select
from sqlalchemy.orm import Session

from metadata.links import execution_to_dict
from metadata.models import (
    Alert,
    ChangeEvent,
    CheckResult,
    ConnectorInstance,
    ConnectorSyncRun,
    Dataset,
    EventLog,
    Execution,
    Incident,
    LineageEdge,
    Metric,
    Monitor,
    Pipeline,
    PipelineIO,
    Task,
    Tool,
)


def _parse_dt(value: Any) -> Optional[datetime]:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    try:
        return date_parser.isoparse(str(value)).replace(tzinfo=None)
    except (ValueError, TypeError):
        return None


class MetadataRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def ensure_tool(self, tenant_id: str, tool_id: str, connector_instance_id: str | None = None) -> Tool:
        row = self.session.scalar(
            select(Tool).where(Tool.tenant_id == tenant_id, Tool.tool_id == tool_id)
        )
        if row:
            return row
        row = Tool(
            tenant_id=tenant_id,
            tool_id=tool_id,
            display_name=tool_id,
            connector_instance_id=connector_instance_id,
        )
        self.session.add(row)
        self.session.flush()
        return row

    def upsert_pipeline(self, tenant_id: str, pipeline_id: str, source_tool: str) -> Pipeline:
        row = self.session.scalar(
            select(Pipeline).where(Pipeline.tenant_id == tenant_id, Pipeline.pipeline_id == pipeline_id)
        )
        if row:
            row.source_tool = source_tool
            row.updated_at = datetime.utcnow()
            return row
        row = Pipeline(
            tenant_id=tenant_id,
            pipeline_id=pipeline_id,
            name=pipeline_id,
            source_tool=source_tool,
        )
        self.session.add(row)
        self.session.flush()
        return row

    def upsert_task(self, tenant_id: str, pipeline_id: str, task_id: str, source_tool: str) -> Task:
        row = self.session.scalar(
            select(Task).where(
                Task.tenant_id == tenant_id,
                Task.pipeline_id == pipeline_id,
                Task.task_id == task_id,
            )
        )
        if row:
            return row
        row = Task(
            tenant_id=tenant_id,
            pipeline_id=pipeline_id,
            task_id=task_id,
            name=task_id,
            source_tool=source_tool,
        )
        self.session.add(row)
        self.session.flush()
        return row

    def upsert_execution(
        self,
        *,
        tenant_id: str,
        execution_id: str,
        pipeline_id: str,
        source_tool: str,
        status: str,
        task_id: str | None = None,
        attempt: int = 1,
        started_at: Any = None,
        finished_at: Any = None,
        duration_ms: Any = None,
        error_message: str | None = None,
        triggered_by: str | None = None,
    ) -> Execution:
        row = self.session.scalar(
            select(Execution).where(
                Execution.tenant_id == tenant_id,
                Execution.execution_id == execution_id,
                Execution.task_id == task_id,
            )
        )
        if row is None:
            row = Execution(
                tenant_id=tenant_id,
                execution_id=execution_id,
                pipeline_id=pipeline_id,
                task_id=task_id,
                source_tool=source_tool,
                status=status,
            )
            self.session.add(row)
        row.status = status
        row.attempt = attempt
        row.started_at = _parse_dt(started_at) or row.started_at
        row.finished_at = _parse_dt(finished_at) or row.finished_at
        if duration_ms is not None:
            try:
                row.duration_ms = int(duration_ms)
            except (TypeError, ValueError):
                pass
        row.error_message = error_message
        row.triggered_by = triggered_by
        self.session.flush()
        return row

    def upsert_dataset(self, tenant_id: str, payload: dict[str, Any], platform: str) -> Dataset:
        dataset_id = str(payload.get("dataset_id") or payload.get("name"))
        row = self.session.scalar(
            select(Dataset).where(Dataset.tenant_id == tenant_id, Dataset.dataset_id == dataset_id)
        )
        if row is None:
            row = Dataset(
                tenant_id=tenant_id,
                dataset_id=dataset_id,
                name=str(payload.get("name") or dataset_id),
                platform=platform,
            )
            self.session.add(row)
        row.database_name = payload.get("database") or row.database_name
        row.schema_name = payload.get("schema") or row.schema_name
        row.name = str(payload.get("name") or row.name)
        row.platform = platform
        if payload.get("row_count") is not None:
            try:
                row.row_count = int(payload["row_count"])
            except (TypeError, ValueError):
                pass
        row.last_updated_at = _parse_dt(payload.get("last_updated_at")) or row.last_updated_at
        if payload.get("tags") is not None:
            row.tags = payload.get("tags")
        row.updated_at = datetime.utcnow()
        self.session.flush()
        return row

    def upsert_lineage(
        self,
        tenant_id: str,
        upstream: str,
        downstream: str,
        confidence: str = "observed",
        transform: str | None = None,
        platform: str | None = None,
    ) -> LineageEdge:
        row = self.session.scalar(
            select(LineageEdge).where(
                LineageEdge.tenant_id == tenant_id,
                LineageEdge.upstream_dataset_id == upstream,
                LineageEdge.downstream_dataset_id == downstream,
            )
        )
        if row is None:
            row = LineageEdge(
                tenant_id=tenant_id,
                upstream_dataset_id=upstream,
                downstream_dataset_id=downstream,
            )
            self.session.add(row)
        row.confidence = confidence
        row.transform = transform
        row.platform = platform
        row.updated_at = datetime.utcnow()
        self.session.flush()
        return row

    def upsert_pipeline_io(
        self,
        *,
        tenant_id: str,
        pipeline_id: str,
        upstream_dataset_id: str,
        downstream_dataset_id: str,
        source_tool: str | None = None,
    ) -> PipelineIO:
        row = self.session.scalar(
            select(PipelineIO).where(
                PipelineIO.tenant_id == tenant_id,
                PipelineIO.pipeline_id == pipeline_id,
                PipelineIO.upstream_dataset_id == upstream_dataset_id,
                PipelineIO.downstream_dataset_id == downstream_dataset_id,
            )
        )
        if row is None:
            row = PipelineIO(
                tenant_id=tenant_id,
                pipeline_id=pipeline_id,
                upstream_dataset_id=upstream_dataset_id,
                downstream_dataset_id=downstream_dataset_id,
            )
            self.session.add(row)
        if source_tool:
            row.source_tool = source_tool
        row.updated_at = datetime.utcnow()
        self.session.flush()
        return row

    def list_pipeline_io(
        self,
        tenant_id: str,
        *,
        pipeline_id: str | None = None,
        limit: int = 200,
    ) -> list[PipelineIO]:
        stmt = select(PipelineIO).where(PipelineIO.tenant_id == tenant_id)
        if pipeline_id:
            stmt = stmt.where(PipelineIO.pipeline_id == pipeline_id)
        return list(self.session.scalars(stmt.limit(limit)))

    def ensure_monitor(
        self,
        tenant_id: str,
        monitor_type: str,
        asset_id: str,
        asset_type: str = "dataset",
        config: dict | None = None,
    ) -> Monitor:
        key = f"{monitor_type}:{asset_type}:{asset_id}"
        row = self.session.scalar(
            select(Monitor).where(Monitor.tenant_id == tenant_id, Monitor.monitor_key == key)
        )
        if row:
            return row
        row = Monitor(
            tenant_id=tenant_id,
            monitor_key=key,
            monitor_type=monitor_type,
            asset_type=asset_type,
            asset_id=asset_id,
            name=f"{monitor_type} on {asset_id}",
            config=config or {},
        )
        self.session.add(row)
        self.session.flush()
        return row

    def add_check_result(
        self,
        *,
        tenant_id: str,
        monitor: Monitor,
        status: str,
        metric_value: float | None = None,
        baseline_value: float | None = None,
        severity: str | None = None,
        details: dict | None = None,
        checked_at: Any = None,
    ) -> CheckResult:
        row = CheckResult(
            tenant_id=tenant_id,
            monitor_id=monitor.id,
            monitor_type=monitor.monitor_type,
            asset_type=monitor.asset_type,
            asset_id=monitor.asset_id,
            status=status,
            metric_value=metric_value,
            baseline_value=baseline_value,
            severity=severity,
            details=details or {},
            checked_at=_parse_dt(checked_at) or datetime.utcnow(),
        )
        self.session.add(row)
        self.session.flush()
        return row

    def raise_alert_and_incident(
        self,
        *,
        tenant_id: str,
        title: str,
        asset_type: str,
        asset_id: str,
        monitor_type: str,
        severity: str = "high",
        message: str | None = None,
        event_id: str,
    ) -> tuple[Alert, Incident]:
        incident_key = f"inc:{tenant_id}:{asset_type}:{asset_id}:{monitor_type}"
        incident = self.session.scalar(
            select(Incident).where(Incident.incident_key == incident_key)
        )
        blast = self._blast_radius(tenant_id, asset_id) if asset_type == "dataset" else 0
        if incident is None:
            incident = Incident(
                tenant_id=tenant_id,
                incident_key=incident_key,
                title=title,
                severity=severity,
                root_asset_type=asset_type,
                root_asset_id=asset_id,
                blast_radius_count=blast,
                summary=message,
            )
            self.session.add(incident)
            self.session.flush()
        else:
            incident.status = "open"
            incident.blast_radius_count = max(incident.blast_radius_count, blast)
            incident.summary = message or incident.summary

        alert_key = f"alert:{event_id}"
        alert = self.session.scalar(select(Alert).where(Alert.alert_key == alert_key))
        if alert is None:
            alert = Alert(
                tenant_id=tenant_id,
                alert_key=alert_key,
                title=title,
                severity=severity,
                asset_type=asset_type,
                asset_id=asset_id,
                monitor_type=monitor_type,
                message=message,
                incident_id=incident.id,
            )
            self.session.add(alert)
        else:
            alert.status = "open"
            alert.incident_id = incident.id
        self.session.flush()
        return alert, incident

    def _blast_radius(self, tenant_id: str, dataset_id: str) -> int:
        edges = self.session.scalars(
            select(LineageEdge).where(
                LineageEdge.tenant_id == tenant_id,
                LineageEdge.upstream_dataset_id == dataset_id,
            )
        ).all()
        return len(edges)

    def record_event_log(self, event: dict[str, Any]) -> EventLog | None:
        existing = self.session.scalar(
            select(EventLog).where(
                EventLog.tenant_id == event["tenant_id"],
                EventLog.event_id == event["event_id"],
            )
        )
        if existing:
            return None  # idempotent skip
        row = EventLog(
            tenant_id=event["tenant_id"],
            event_id=event["event_id"],
            event_type=event["event_type"],
            source_tool=event["source_tool"],
            occurred_at=_parse_dt(event.get("occurred_at")) or datetime.utcnow(),
            connector_instance_id=event.get("connector_instance_id"),
            payload=event.get("payload") or {},
        )
        self.session.add(row)
        self.session.flush()
        return row

    def add_change_event(
        self,
        tenant_id: str,
        change_type: str,
        asset_id: str,
        asset_type: str = "dataset",
        breaking: bool = False,
        details: dict | None = None,
        source_tool: str | None = None,
        occurred_at: Any = None,
    ) -> ChangeEvent:
        row = ChangeEvent(
            tenant_id=tenant_id,
            change_type=change_type,
            asset_type=asset_type,
            asset_id=asset_id,
            breaking=breaking,
            details=details or {},
            source_tool=source_tool,
            occurred_at=_parse_dt(occurred_at) or datetime.utcnow(),
        )
        self.session.add(row)
        self.session.flush()
        return row

    def add_metric(
        self,
        tenant_id: str,
        name: str,
        value: float,
        asset_type: str | None = None,
        asset_id: str | None = None,
        unit: str | None = None,
        recorded_at: Any = None,
    ) -> Metric:
        row = Metric(
            tenant_id=tenant_id,
            name=name,
            value=value,
            asset_type=asset_type,
            asset_id=asset_id,
            unit=unit,
            recorded_at=_parse_dt(recorded_at) or datetime.utcnow(),
        )
        self.session.add(row)
        self.session.flush()
        return row

    # --- queries ---

    def list_pipelines(self, tenant_id: str, limit: int = 100) -> list[Pipeline]:
        return list(
            self.session.scalars(
                select(Pipeline).where(Pipeline.tenant_id == tenant_id).limit(limit)
            )
        )

    def list_datasets(self, tenant_id: str, limit: int = 100) -> list[Dataset]:
        return list(
            self.session.scalars(
                select(Dataset).where(Dataset.tenant_id == tenant_id).limit(limit)
            )
        )

    def get_dataset(self, tenant_id: str, dataset_id: str) -> Dataset | None:
        return self.session.scalar(
            select(Dataset).where(
                Dataset.tenant_id == tenant_id,
                Dataset.dataset_id == dataset_id,
            )
        )

    def list_check_results(
        self,
        tenant_id: str,
        *,
        asset_id: str | None = None,
        monitor_type: str | None = None,
        limit: int = 100,
    ) -> list[CheckResult]:
        stmt = select(CheckResult).where(CheckResult.tenant_id == tenant_id)
        if asset_id:
            stmt = stmt.where(CheckResult.asset_id == asset_id)
        if monitor_type:
            stmt = stmt.where(CheckResult.monitor_type == monitor_type)
        return list(
            self.session.scalars(stmt.order_by(CheckResult.checked_at.desc()).limit(limit))
        )

    def list_executions(self, tenant_id: str, pipeline_id: str | None = None, limit: int = 100) -> list[Execution]:
        stmt = select(Execution).where(Execution.tenant_id == tenant_id)
        if pipeline_id:
            stmt = stmt.where(Execution.pipeline_id == pipeline_id)
        return list(self.session.scalars(stmt.order_by(Execution.id.desc()).limit(limit)))

    def list_incidents(
        self,
        tenant_id: str,
        status: str | None = None,
        asset_id: str | None = None,
        limit: int = 100,
    ) -> list[Incident]:
        stmt = select(Incident).where(Incident.tenant_id == tenant_id)
        if status:
            stmt = stmt.where(Incident.status == status)
        if asset_id:
            stmt = stmt.where(Incident.root_asset_id == asset_id)
        return list(self.session.scalars(stmt.order_by(Incident.opened_at.desc()).limit(limit)))

    def get_incident(self, tenant_id: str, incident_key: str) -> Incident | None:
        return self.session.scalar(
            select(Incident).where(
                Incident.tenant_id == tenant_id,
                Incident.incident_key == incident_key,
            )
        )

    def list_alerts(
        self,
        tenant_id: str,
        *,
        asset_id: str | None = None,
        monitor_type: str | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> list[Alert]:
        stmt = select(Alert).where(Alert.tenant_id == tenant_id)
        if asset_id:
            stmt = stmt.where(Alert.asset_id == asset_id)
        if monitor_type:
            stmt = stmt.where(Alert.monitor_type == monitor_type)
        if status:
            stmt = stmt.where(Alert.status == status)
        return list(
            self.session.scalars(stmt.order_by(Alert.raised_at.desc()).limit(limit))
        )

    def list_monitors(
        self,
        tenant_id: str,
        *,
        asset_id: str | None = None,
        monitor_type: str | None = None,
        limit: int = 100,
    ) -> list[Monitor]:
        stmt = select(Monitor).where(Monitor.tenant_id == tenant_id)
        if asset_id:
            stmt = stmt.where(Monitor.asset_id == asset_id)
        if monitor_type:
            stmt = stmt.where(Monitor.monitor_type == monitor_type)
        return list(self.session.scalars(stmt.limit(limit)))

    def list_lineage(self, tenant_id: str, dataset_id: str | None = None, limit: int = 200) -> list[LineageEdge]:
        stmt = select(LineageEdge).where(LineageEdge.tenant_id == tenant_id)
        if dataset_id:
            stmt = stmt.where(
                (LineageEdge.upstream_dataset_id == dataset_id)
                | (LineageEdge.downstream_dataset_id == dataset_id)
            )
        return list(self.session.scalars(stmt.limit(limit)))

    def get_pipeline(self, tenant_id: str, pipeline_id: str) -> Pipeline | None:
        return self.session.scalar(
            select(Pipeline).where(Pipeline.tenant_id == tenant_id, Pipeline.pipeline_id == pipeline_id)
        )

    def list_tasks(self, tenant_id: str, pipeline_id: str, limit: int = 200) -> list[Task]:
        return list(
            self.session.scalars(
                select(Task)
                .where(Task.tenant_id == tenant_id, Task.pipeline_id == pipeline_id)
                .limit(limit)
            )
        )

    def list_metrics_for_asset(
        self, tenant_id: str, asset_id: str, limit: int = 100
    ) -> list[Metric]:
        return list(
            self.session.scalars(
                select(Metric)
                .where(Metric.tenant_id == tenant_id, Metric.asset_id == asset_id)
                .order_by(Metric.recorded_at.desc())
                .limit(limit)
            )
        )

    def list_metrics(
        self,
        tenant_id: str,
        *,
        asset_id: str | None = None,
        name: str | None = None,
        limit: int = 100,
    ) -> list[Metric]:
        stmt = select(Metric).where(Metric.tenant_id == tenant_id)
        if asset_id:
            stmt = stmt.where(Metric.asset_id == asset_id)
        if name:
            stmt = stmt.where(Metric.name == name)
        return list(self.session.scalars(stmt.order_by(Metric.recorded_at.desc()).limit(limit)))

    def pipeline_dashboard(self, tenant_id: str, pipeline_id: str) -> dict[str, Any] | None:
        pipeline = self.get_pipeline(tenant_id, pipeline_id)
        if not pipeline:
            return None

        executions = self.list_executions(tenant_id, pipeline_id=pipeline_id, limit=200)
        tasks = self.list_tasks(tenant_id, pipeline_id)

        # Pipeline-level runs (no task_id) for success rate; fall back to all if none
        pipeline_runs = [e for e in executions if not e.task_id]
        rate_basis = pipeline_runs or executions
        total = len(rate_basis)
        succeeded = sum(1 for e in rate_basis if (e.status or "").lower() in {"succeeded", "success"})
        failed = sum(1 for e in rate_basis if "fail" in (e.status or "").lower())
        running = sum(1 for e in rate_basis if (e.status or "").lower() in {"running", "queued", "retrying"})
        durations = [e.duration_ms for e in rate_basis if e.duration_ms is not None]
        avg_duration = int(sum(durations) / len(durations)) if durations else None
        max_duration = max(durations) if durations else None
        retries = sum(1 for e in executions if (e.attempt or 1) > 1)

        # Related incidents / alerts by pipeline id in asset fields or title
        all_incidents = self.list_incidents(tenant_id, limit=200)
        incidents = [
            i
            for i in all_incidents
            if (i.root_asset_id == pipeline_id)
            or (i.root_asset_type == "pipeline" and i.root_asset_id == pipeline_id)
            or (pipeline_id in (i.title or ""))
            or (pipeline_id in (i.root_asset_id or ""))
        ]
        all_alerts = self.list_alerts(tenant_id, limit=200)
        alerts = [
            a
            for a in all_alerts
            if a.asset_id == pipeline_id
            or (a.asset_id or "").startswith(f"{pipeline_id}.")
            or pipeline_id in (a.title or "")
        ]

        # Explicit pipeline I/O (preferred) or lineage transform match
        io_rows = self.list_pipeline_io(tenant_id, pipeline_id=pipeline_id, limit=500)
        dataset_ids: set[str] = set()
        pipeline_io_items: list[dict[str, Any]] = []
        related_edges: list[LineageEdge | PipelineIO] = []

        if io_rows:
            related_edges = io_rows
            for io in io_rows:
                dataset_ids.add(io.upstream_dataset_id)
                dataset_ids.add(io.downstream_dataset_id)
                pipeline_io_items.append(
                    {
                        "upstream_dataset_id": io.upstream_dataset_id,
                        "downstream_dataset_id": io.downstream_dataset_id,
                        "source_tool": io.source_tool,
                    }
                )
        else:
            lineage = self.list_lineage(tenant_id, limit=500)
            related_edges = [
                e
                for e in lineage
                if (e.transform or "") == pipeline_id or pipeline_id in (e.transform or "")
            ]
            for e in related_edges:
                dataset_ids.add(e.upstream_dataset_id)
                dataset_ids.add(e.downstream_dataset_id)

        # Task failure breakdown
        task_stats: dict[str, dict[str, int]] = {}
        for e in executions:
            if not e.task_id:
                continue
            bucket = task_stats.setdefault(e.task_id, {"total": 0, "failed": 0, "succeeded": 0})
            bucket["total"] += 1
            if "fail" in (e.status or "").lower():
                bucket["failed"] += 1
            elif (e.status or "").lower() in {"succeeded", "success"}:
                bucket["succeeded"] += 1

        metrics = self.list_metrics_for_asset(tenant_id, pipeline_id, limit=50)

        def _iso(dt: datetime | None) -> str | None:
            return dt.isoformat() if dt else None

        return {
            "pipeline": {
                "pipeline_id": pipeline.pipeline_id,
                "name": pipeline.name,
                "source_tool": pipeline.source_tool,
                "status": pipeline.status,
                "tags": pipeline.tags or [],
                "updated_at": _iso(pipeline.updated_at),
                "created_at": _iso(pipeline.created_at),
            },
            "metrics": {
                "total_runs": total,
                "succeeded": succeeded,
                "failed": failed,
                "running": running,
                "success_rate_pct": round((succeeded / total) * 100, 1) if total else None,
                "failure_rate_pct": round((failed / total) * 100, 1) if total else None,
                "avg_duration_ms": avg_duration,
                "max_duration_ms": max_duration,
                "retry_count": retries,
                "task_count": len(tasks),
                "open_incident_count": sum(1 for i in incidents if i.status == "open"),
                "alert_count": len(alerts),
            },
            "tasks": [
                {"task_id": t.task_id, "name": t.name, "source_tool": t.source_tool} for t in tasks
            ],
            "task_stats": [
                {"task_id": k, **v} for k, v in sorted(task_stats.items(), key=lambda x: -x[1]["failed"])
            ],
            "executions": [execution_to_dict(e) for e in executions[:50]],
            "incidents": [
                {
                    "incident_key": i.incident_key,
                    "title": i.title,
                    "status": i.status,
                    "severity": i.severity,
                    "root_asset_id": i.root_asset_id,
                    "blast_radius_count": i.blast_radius_count,
                    "summary": i.summary,
                }
                for i in incidents[:20]
            ],
            "alerts": [
                {
                    "alert_key": a.alert_key,
                    "title": a.title,
                    "severity": a.severity,
                    "status": a.status,
                    "monitor_type": a.monitor_type,
                    "asset_id": a.asset_id,
                }
                for a in alerts[:20]
            ],
            "related_datasets": sorted(dataset_ids),
            "pipeline_io": pipeline_io_items[:50],
            "lineage_edges": [
                {
                    "upstream_dataset_id": e.upstream_dataset_id,
                    "downstream_dataset_id": e.downstream_dataset_id,
                    "confidence": getattr(e, "confidence", None),
                    "transform": getattr(e, "transform", None) or pipeline_id,
                }
                for e in related_edges[:50]
            ],
            "metric_points": [
                {
                    "name": m.name,
                    "value": m.value,
                    "unit": m.unit,
                    "recorded_at": _iso(m.recorded_at),
                }
                for m in metrics
            ],
        }

    def blast_radius(self, tenant_id: str, dataset_id: str) -> list[str]:
        downstream = set()
        frontier = [dataset_id]
        while frontier:
            current = frontier.pop()
            for edge in self.session.scalars(
                select(LineageEdge).where(
                    LineageEdge.tenant_id == tenant_id,
                    LineageEdge.upstream_dataset_id == current,
                )
            ):
                if edge.downstream_dataset_id not in downstream:
                    downstream.add(edge.downstream_dataset_id)
                    frontier.append(edge.downstream_dataset_id)
        return sorted(downstream)

    # --- Connector instances (Monte Carlo–style) ---

    def create_connector_instance(
        self,
        *,
        tenant_id: str,
        instance_id: str,
        tool_id: str,
        name: str,
        config: dict[str, Any] | None = None,
        secrets_ref: dict[str, Any] | None = None,
    ) -> ConnectorInstance:
        row = ConnectorInstance(
            tenant_id=tenant_id,
            instance_id=instance_id,
            tool_id=tool_id,
            name=name,
            config=config or {},
            secrets_ref=secrets_ref or {},
            status="created",
        )
        self.session.add(row)
        self.session.commit()
        self.session.refresh(row)
        return row

    def list_connector_instances(self, tenant_id: str, limit: int = 100) -> list[ConnectorInstance]:
        return list(
            self.session.scalars(
                select(ConnectorInstance)
                .where(ConnectorInstance.tenant_id == tenant_id)
                .order_by(ConnectorInstance.updated_at.desc())
                .limit(limit)
            )
        )

    def get_connector_instance(self, tenant_id: str, instance_id: str) -> ConnectorInstance | None:
        return self.session.scalar(
            select(ConnectorInstance).where(
                ConnectorInstance.tenant_id == tenant_id,
                ConnectorInstance.instance_id == instance_id,
            )
        )

    def update_connector_instance(
        self,
        row: ConnectorInstance,
        *,
        status: str | None = None,
        last_error: str | None = None,
        last_sync_at: datetime | None = None,
        config: dict[str, Any] | None = None,
        name: str | None = None,
        secrets_ref: dict[str, Any] | None = None,
    ) -> ConnectorInstance:
        if status is not None:
            row.status = status
        if last_error is not None:
            row.last_error = last_error
        if last_sync_at is not None:
            row.last_sync_at = last_sync_at
        if config is not None:
            row.config = config
        if name is not None:
            row.name = name
        if secrets_ref is not None:
            row.secrets_ref = secrets_ref
        row.updated_at = datetime.utcnow()
        self.session.commit()
        self.session.refresh(row)
        return row

    def delete_connector_instance(self, row: ConnectorInstance) -> None:
        self.session.delete(row)
        self.session.commit()

    def start_sync_run(
        self,
        *,
        tenant_id: str,
        run_id: str,
        instance_id: str,
        tool_id: str,
    ) -> ConnectorSyncRun:
        row = ConnectorSyncRun(
            tenant_id=tenant_id,
            run_id=run_id,
            instance_id=instance_id,
            tool_id=tool_id,
            status="running",
        )
        self.session.add(row)
        self.session.commit()
        self.session.refresh(row)
        return row

    def finish_sync_run(
        self,
        row: ConnectorSyncRun,
        *,
        status: str,
        envelopes: int = 0,
        ingested: int = 0,
        duplicates: int = 0,
        dead_letters: int = 0,
        error_message: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> ConnectorSyncRun:
        row.status = status
        row.envelopes = envelopes
        row.ingested = ingested
        row.duplicates = duplicates
        row.dead_letters = dead_letters
        row.error_message = error_message
        row.details = details or {}
        row.finished_at = datetime.utcnow()
        self.session.commit()
        self.session.refresh(row)
        return row
