"""Connector plugin contract for DB / ETL / orchestrator tools."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class ConnectorPlugin(Protocol):
    tool_id: str
    kind: str  # database | etl | orchestrator | dlt

    def test_connection(self) -> dict[str, Any]:
        ...

    def pull_state(self) -> list[dict[str, Any]]:
        ...


def correlation_stamp(
    *,
    obs_run_id: str,
    pipeline_id: str,
    pipeline_name: str | None = None,
) -> str:
    """Query-tag / session stamp used to correlate warehouse work to a platform run."""
    parts = [
        f"obs_run_id={obs_run_id}",
        f"obs_pipeline_id={pipeline_id}",
    ]
    if pipeline_name:
        parts.append(f"obs_pipeline={pipeline_name}")
    return ";".join(parts)
