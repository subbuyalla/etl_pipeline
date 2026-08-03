from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class TwinDataset:
    database: str
    schema: str
    table: str
    platform: str = "snowflake"
    domain: str = "finance"

    @property
    def dataset_id(self) -> str:
        return f"{self.database}.{self.schema}.{self.table}"


@dataclass
class TwinPipeline:
    pipeline_id: str
    tool: str
    domain: str
    produces: list[str] = field(default_factory=list)  # dataset_ids


@dataclass
class TwinEstate:
    tenant_id: str
    datasets: list[TwinDataset]
    pipelines: list[TwinPipeline]
    lineage: list[tuple[str, str, str]]  # upstream, downstream, pipeline_id


def default_estate(tenant_id: str = "demo") -> TwinEstate:
    """Multi-domain mock estate: Finance, Marketing, Ops."""
    datasets = [
        TwinDataset("ANALYTICS", "RAW", "ORDERS", domain="finance"),
        TwinDataset("ANALYTICS", "RAW", "CUSTOMERS", domain="finance"),
        TwinDataset("ANALYTICS", "MART", "FCT_ORDERS", domain="finance"),
        TwinDataset("ANALYTICS", "MART", "DIM_CUSTOMER", domain="finance"),
        TwinDataset("MARKETING", "RAW", "CAMPAIGNS", domain="marketing"),
        TwinDataset("MARKETING", "MART", "FCT_CAMPAIGN", domain="marketing"),
        TwinDataset("OPS", "RAW", "TICKETS", domain="ops"),
        TwinDataset("OPS", "MART", "FCT_SLA", domain="ops"),
    ]
    pipelines = [
        TwinPipeline("finance_etl", "airflow", "finance", ["ANALYTICS.RAW.ORDERS", "ANALYTICS.MART.FCT_ORDERS"]),
        TwinPipeline("dim_customer_load", "glue", "finance", ["ANALYTICS.MART.DIM_CUSTOMER"]),
        TwinPipeline("analytics", "dbt", "finance", ["ANALYTICS.MART.FCT_ORDERS"]),
        TwinPipeline("marketing_sync", "airflow", "marketing", ["MARKETING.RAW.CAMPAIGNS"]),
        TwinPipeline("ops_tickets_ingest", "adf", "ops", ["OPS.RAW.TICKETS"]),
    ]
    lineage = [
        ("ANALYTICS.RAW.ORDERS", "ANALYTICS.MART.FCT_ORDERS", "finance_etl"),
        ("ANALYTICS.RAW.CUSTOMERS", "ANALYTICS.MART.DIM_CUSTOMER", "dim_customer_load"),
        ("MARKETING.RAW.CAMPAIGNS", "MARKETING.MART.FCT_CAMPAIGN", "marketing_sync"),
        ("OPS.RAW.TICKETS", "OPS.MART.FCT_SLA", "ops_tickets_ingest"),
    ]
    return TwinEstate(tenant_id=tenant_id, datasets=datasets, pipelines=pipelines, lineage=lineage)


def estate_summary(estate: TwinEstate) -> dict[str, Any]:
    return {
        "tenant_id": estate.tenant_id,
        "domains": sorted({d.domain for d in estate.datasets}),
        "dataset_count": len(estate.datasets),
        "pipeline_count": len(estate.pipelines),
        "lineage_edges": len(estate.lineage),
        "tools": sorted({p.tool for p in estate.pipelines}),
    }
