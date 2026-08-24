"""
Stable response contracts for /api/v1 dashboard APIs.

Field names and envelope keys are fixed for the frontend. Values may be null,
empty lists, or "N/A" when data is unavailable — keys are never omitted.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class RangeMeta(BaseModel):
    from_: Optional[str] = Field(None, alias="from")
    to: Optional[str] = None
    preset: Optional[str] = None

    model_config = {"populate_by_name": True}


class PaginationMeta(BaseModel):
    page: int = 1
    page_size: int = 20
    total: int = 0


class KpiItem(BaseModel):
    id: str
    title: str
    value: Any = None
    display: str = "N/A"
    delta: Optional[float] = None
    delta_label: Optional[str] = None
    tone: str = "neutral"  # neutral | ok | warn | bad
    available: bool = True


class ApiEnvelope(BaseModel):
    """Canonical list/KPI response shape for dashboard pages."""

    ok: bool = True
    generated_at: str
    range: RangeMeta = Field(default_factory=RangeMeta)
    filters_applied: dict[str, Any] = Field(default_factory=dict)
    kpis: list[KpiItem] = Field(default_factory=list)
    series: dict[str, Any] = Field(default_factory=dict)
    charts: dict[str, Any] = Field(default_factory=dict)
    items: list[Any] = Field(default_factory=list)
    pagination: PaginationMeta = Field(default_factory=PaginationMeta)
    # Extra page-specific blocks (always present when used by a route)
    pillars: list[Any] = Field(default_factory=list)
    incidents: list[Any] = Field(default_factory=list)
    pipelines: list[Any] = Field(default_factory=list)
    health: list[Any] = Field(default_factory=list)
    summary: dict[str, Any] = Field(default_factory=dict)
    meta: dict[str, Any] = Field(default_factory=dict)


def make_kpi(
    *,
    id: str,
    title: str,
    value: Any = None,
    display: str | None = None,
    delta: float | None = None,
    delta_label: str | None = None,
    tone: str = "neutral",
    available: bool = True,
) -> dict[str, Any]:
    if not available:
        return {
            "id": id,
            "title": title,
            "value": None,
            "display": "N/A",
            "delta": None,
            "delta_label": None,
            "tone": "neutral",
            "available": False,
        }
    if display is None:
        if value is None:
            display = "N/A"
        else:
            display = str(value)
    return {
        "id": id,
        "title": title,
        "value": value,
        "display": display,
        "delta": delta,
        "delta_label": delta_label,
        "tone": tone,
        "available": True,
    }
