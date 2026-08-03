from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker


class Base(DeclarativeBase):
    pass


def _now() -> datetime:
    return datetime.utcnow()


class TenantMixin:
    tenant_id: Mapped[str] = mapped_column(String(128), index=True, nullable=False)


class Tool(Base, TenantMixin):
    """Registered source tool / platform (airflow, snowflake, …)."""

    __tablename__ = "etl_tools"
    __table_args__ = (UniqueConstraint("tenant_id", "tool_id", name="uq_tool"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tool_id: Mapped[str] = mapped_column(String(64), nullable=False)
    family: Mapped[Optional[str]] = mapped_column(String(64))
    display_name: Mapped[Optional[str]] = mapped_column(String(256))
    connector_instance_id: Mapped[Optional[str]] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class Domain(Base, TenantMixin):
    """Business domain (Finance, Marketing) — beyond typical DQ-only tools."""

    __tablename__ = "etl_domains"
    __table_args__ = (UniqueConstraint("tenant_id", "name", name="uq_domain"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class Owner(Base, TenantMixin):
    __tablename__ = "etl_owners"
    __table_args__ = (UniqueConstraint("tenant_id", "email", name="uq_owner"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(256), nullable=False)
    name: Mapped[Optional[str]] = mapped_column(String(256))
    team: Mapped[Optional[str]] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class DataProduct(Base, TenantMixin):
    __tablename__ = "etl_data_products"
    __table_args__ = (UniqueConstraint("tenant_id", "name", name="uq_data_product"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    domain_id: Mapped[Optional[int]] = mapped_column(ForeignKey("etl_domains.id"))
    owner_id: Mapped[Optional[int]] = mapped_column(ForeignKey("etl_owners.id"))
    description: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class Pipeline(Base, TenantMixin):
    __tablename__ = "etl_pipelines"
    __table_args__ = (UniqueConstraint("tenant_id", "pipeline_id", name="uq_pipeline"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    pipeline_id: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    source_tool: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    domain_id: Mapped[Optional[int]] = mapped_column(ForeignKey("etl_domains.id"))
    owner_id: Mapped[Optional[int]] = mapped_column(ForeignKey("etl_owners.id"))
    status: Mapped[Optional[str]] = mapped_column(String(64))
    tags: Mapped[Optional[Any]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)


class Task(Base, TenantMixin):
    __tablename__ = "etl_tasks"
    __table_args__ = (UniqueConstraint("tenant_id", "pipeline_id", "task_id", name="uq_task"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    pipeline_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    task_id: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    source_tool: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class Execution(Base, TenantMixin):
    """Pipeline or task run history."""

    __tablename__ = "etl_executions"
    __table_args__ = (
        UniqueConstraint("tenant_id", "execution_id", "task_id", name="uq_execution"),
        Index("ix_exec_pipeline_time", "tenant_id", "pipeline_id", "started_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    execution_id: Mapped[str] = mapped_column(String(255), nullable=False)
    pipeline_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    task_id: Mapped[Optional[str]] = mapped_column(String(255))
    source_tool: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer)
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    triggered_by: Mapped[Optional[str]] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class Dataset(Base, TenantMixin):
    __tablename__ = "etl_datasets"
    __table_args__ = (UniqueConstraint("tenant_id", "dataset_id", name="uq_dataset"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    dataset_id: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    database_name: Mapped[Optional[str]] = mapped_column(String(256))
    schema_name: Mapped[Optional[str]] = mapped_column(String(256))
    platform: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    row_count: Mapped[Optional[int]] = mapped_column(Integer)
    last_updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    owner_id: Mapped[Optional[int]] = mapped_column(ForeignKey("etl_owners.id"))
    domain_id: Mapped[Optional[int]] = mapped_column(ForeignKey("etl_domains.id"))
    data_product_id: Mapped[Optional[int]] = mapped_column(ForeignKey("etl_data_products.id"))
    tags: Mapped[Optional[Any]] = mapped_column(JSON, default=list)
    schema_fingerprint: Mapped[Optional[str]] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)


class DatasetColumn(Base, TenantMixin):
    """Column-level metadata (schema drift support)."""

    __tablename__ = "etl_dataset_columns"
    __table_args__ = (
        UniqueConstraint("tenant_id", "dataset_id", "column_name", name="uq_column"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    dataset_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    column_name: Mapped[str] = mapped_column(String(256), nullable=False)
    data_type: Mapped[Optional[str]] = mapped_column(String(128))
    is_nullable: Mapped[Optional[bool]] = mapped_column(Boolean)
    ordinal: Mapped[Optional[int]] = mapped_column(Integer)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)


class Resource(Base, TenantMixin):
    """Compute/storage resource (cluster, warehouse, bucket)."""

    __tablename__ = "etl_resources"
    __table_args__ = (UniqueConstraint("tenant_id", "resource_id", name="uq_resource"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    resource_id: Mapped[str] = mapped_column(String(255), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    platform: Mapped[Optional[str]] = mapped_column(String(64))
    meta: Mapped[Optional[Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class SLA(Base, TenantMixin):
    __tablename__ = "etl_slas"
    __table_args__ = (UniqueConstraint("tenant_id", "name", "asset_id", name="uq_sla"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    asset_type: Mapped[str] = mapped_column(String(64), nullable=False)  # dataset|pipeline
    asset_id: Mapped[str] = mapped_column(String(255), nullable=False)
    freshness_minutes: Mapped[Optional[int]] = mapped_column(Integer)
    success_rate_pct: Mapped[Optional[float]] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class Monitor(Base, TenantMixin):
    """Monte Carlo–style monitors: freshness, volume, schema, distribution, custom."""

    __tablename__ = "etl_monitors"
    __table_args__ = (
        UniqueConstraint("tenant_id", "monitor_key", name="uq_monitor"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    monitor_key: Mapped[str] = mapped_column(String(255), nullable=False)
    monitor_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    asset_type: Mapped[str] = mapped_column(String(64), nullable=False)
    asset_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    config: Mapped[Optional[Any]] = mapped_column(JSON, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class CheckResult(Base, TenantMixin):
    __tablename__ = "etl_check_results"
    __table_args__ = (Index("ix_check_asset_time", "tenant_id", "asset_id", "checked_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    monitor_id: Mapped[Optional[int]] = mapped_column(ForeignKey("etl_monitors.id"))
    monitor_type: Mapped[str] = mapped_column(String(64), nullable=False)
    asset_type: Mapped[str] = mapped_column(String(64), nullable=False)
    asset_id: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(64), nullable=False)  # passed|failed|anomalous
    metric_value: Mapped[Optional[float]] = mapped_column(Float)
    baseline_value: Mapped[Optional[float]] = mapped_column(Float)
    severity: Mapped[Optional[str]] = mapped_column(String(32))
    details: Mapped[Optional[Any]] = mapped_column(JSON, default=dict)
    checked_at: Mapped[datetime] = mapped_column(DateTime, default=_now, index=True)


class Metric(Base, TenantMixin):
    __tablename__ = "etl_metrics"
    __table_args__ = (Index("ix_metric_time", "tenant_id", "name", "recorded_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    asset_type: Mapped[Optional[str]] = mapped_column(String(64))
    asset_id: Mapped[Optional[str]] = mapped_column(String(255))
    value: Mapped[float] = mapped_column(Float, nullable=False)
    unit: Mapped[Optional[str]] = mapped_column(String(64))
    recorded_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    labels: Mapped[Optional[Any]] = mapped_column(JSON, default=dict)


class LineageEdge(Base, TenantMixin):
    __tablename__ = "etl_lineage_edges"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "upstream_dataset_id", "downstream_dataset_id", name="uq_lineage"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    upstream_dataset_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    downstream_dataset_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    confidence: Mapped[str] = mapped_column(String(32), default="observed")  # observed|declared
    transform: Mapped[Optional[str]] = mapped_column(String(255))
    platform: Mapped[Optional[str]] = mapped_column(String(64))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)


class PipelineIO(Base, TenantMixin):
    """Explicit pipeline ↔ source ↔ target dataset links."""

    __tablename__ = "etl_pipeline_io"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "pipeline_id",
            "upstream_dataset_id",
            "downstream_dataset_id",
            name="uq_pipeline_io",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    pipeline_id: Mapped[str] = mapped_column(String(191), nullable=False, index=True)
    upstream_dataset_id: Mapped[str] = mapped_column(String(191), nullable=False, index=True)
    downstream_dataset_id: Mapped[str] = mapped_column(String(191), nullable=False, index=True)
    source_tool: Mapped[Optional[str]] = mapped_column(String(64))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)


class Incident(Base, TenantMixin):
    __tablename__ = "etl_incidents"
    __table_args__ = (Index("ix_incident_status", "tenant_id", "status", "opened_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    incident_key: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="open")  # open|triage|resolved
    severity: Mapped[str] = mapped_column(String(32), default="medium")
    root_asset_type: Mapped[Optional[str]] = mapped_column(String(64))
    root_asset_id: Mapped[Optional[str]] = mapped_column(String(255))
    blast_radius_count: Mapped[int] = mapped_column(Integer, default=0)
    summary: Mapped[Optional[str]] = mapped_column(Text)
    opened_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime)


class Alert(Base, TenantMixin):
    __tablename__ = "etl_alerts"
    __table_args__ = (Index("ix_alert_status", "tenant_id", "status", "raised_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    alert_key: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    severity: Mapped[str] = mapped_column(String(32), default="medium")
    status: Mapped[str] = mapped_column(String(32), default="open")  # open|acked|resolved
    asset_type: Mapped[Optional[str]] = mapped_column(String(64))
    asset_id: Mapped[Optional[str]] = mapped_column(String(255))
    monitor_type: Mapped[Optional[str]] = mapped_column(String(64))
    message: Mapped[Optional[str]] = mapped_column(Text)
    raised_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    incident_id: Mapped[Optional[int]] = mapped_column(ForeignKey("etl_incidents.id"))


class EventLog(Base, TenantMixin):
    """Immutable-ish log of canonical events (audit + replay)."""

    __tablename__ = "etl_event_log"
    __table_args__ = (
        UniqueConstraint("tenant_id", "event_id", name="uq_event"),
        Index("ix_event_type_time", "tenant_id", "event_type", "occurred_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_id: Mapped[str] = mapped_column(String(128), nullable=False)
    event_type: Mapped[str] = mapped_column(String(128), nullable=False)
    source_tool: Mapped[str] = mapped_column(String(64), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    connector_instance_id: Mapped[Optional[str]] = mapped_column(String(128))
    payload: Mapped[Any] = mapped_column(JSON, nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class ChangeEvent(Base, TenantMixin):
    """CI/CD / schema / config changes — beyond Monte Carlo core."""

    __tablename__ = "etl_change_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    change_type: Mapped[str] = mapped_column(String(64), nullable=False)  # schema|deploy|config
    asset_type: Mapped[Optional[str]] = mapped_column(String(64))
    asset_id: Mapped[Optional[str]] = mapped_column(String(255))
    breaking: Mapped[bool] = mapped_column(Boolean, default=False)
    details: Mapped[Optional[Any]] = mapped_column(JSON, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    source_tool: Mapped[Optional[str]] = mapped_column(String(64))


class CostRecord(Base, TenantMixin):
    """FinOps — per pipeline/dataset cost attribution (beyond Monte Carlo)."""

    __tablename__ = "etl_cost_records"
    __table_args__ = (Index("ix_cost_time", "tenant_id", "asset_id", "recorded_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    asset_type: Mapped[str] = mapped_column(String(64), nullable=False)
    asset_id: Mapped[str] = mapped_column(String(255), nullable=False)
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    currency: Mapped[str] = mapped_column(String(8), default="USD")
    cost_category: Mapped[Optional[str]] = mapped_column(String(64))  # compute|storage|egress
    platform: Mapped[Optional[str]] = mapped_column(String(64))
    recorded_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    labels: Mapped[Optional[Any]] = mapped_column(JSON, default=dict)


class AssetHealthScore(Base, TenantMixin):
    """Health / maturity scores for health-check report."""

    __tablename__ = "etl_asset_health_scores"
    __table_args__ = (
        UniqueConstraint("tenant_id", "asset_type", "asset_id", "dimension", name="uq_health"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    asset_type: Mapped[str] = mapped_column(String(64), nullable=False)
    asset_id: Mapped[str] = mapped_column(String(255), nullable=False)
    dimension: Mapped[str] = mapped_column(String(64), nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    max_score: Mapped[float] = mapped_column(Float, default=100.0)
    details: Mapped[Optional[Any]] = mapped_column(JSON, default=dict)
    scored_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class ConnectorInstance(Base, TenantMixin):
    """Monte Carlo–style connector connection (non-secret config only)."""

    __tablename__ = "etl_connector_instances"
    __table_args__ = (
        UniqueConstraint("tenant_id", "instance_id", name="uq_connector_instance"),
        Index("ix_connector_tool", "tenant_id", "tool_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    instance_id: Mapped[str] = mapped_column(String(128), nullable=False)
    tool_id: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    config: Mapped[Optional[Any]] = mapped_column(JSON, default=dict)
    secrets_ref: Mapped[Optional[Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(32), default="created")
    last_sync_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    last_error: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)


class ConnectorSyncRun(Base, TenantMixin):
    """One sync execution for a connector instance."""

    __tablename__ = "etl_connector_sync_runs"
    __table_args__ = (Index("ix_sync_instance", "tenant_id", "instance_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    instance_id: Mapped[str] = mapped_column(String(128), nullable=False)
    tool_id: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="running")
    envelopes: Mapped[int] = mapped_column(Integer, default=0)
    ingested: Mapped[int] = mapped_column(Integer, default=0)
    duplicates: Mapped[int] = mapped_column(Integer, default=0)
    dead_letters: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    details: Mapped[Optional[Any]] = mapped_column(JSON, default=dict)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime)


def create_session_factory(database_url: str = "sqlite:///:memory:"):
    engine = create_engine(database_url, future=True)
    return engine, sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
