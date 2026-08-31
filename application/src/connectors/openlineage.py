"""Parse OpenLineage RUN/COMPLETE events into lineage edges."""

from __future__ import annotations

from datetime import datetime
from typing import Any


def _dataset_fqn(ds: dict) -> str:
    """Normalize OpenLineage Dataset to DB.SCHEMA.TABLE style label."""
    namespace = str(ds.get("namespace") or "").strip()
    name = str(ds.get("name") or "").strip()
    if not name:
        return ""
    # snowflake://ACCOUNT/db/schema/table or postgres://host:5432/db.schema.table
    if "://" in name:
        return name.split("://", 1)[-1].upper()
    if namespace and "://" in namespace:
        ns_tail = namespace.split("://", 1)[-1]
        combined = f"{ns_tail}.{name}" if ns_tail else name
        return combined.replace("/", ".").upper()
    if namespace:
        return f"{namespace}.{name}".replace("/", ".").upper()
    return name.replace("/", ".").upper()


def parse_openlineage_event(payload: dict) -> dict[str, Any]:
    """
    Parse OpenLineage JSON (v1 COMPLETE/RUN) into edges + metadata.

    Returns:
      event_type, run_id, job_name, producer, event_time, edges[], raw_event
    """
    if not isinstance(payload, dict):
        raise ValueError("OpenLineage payload must be a JSON object")

    event_type = str(payload.get("eventType") or "").upper()
    run = payload.get("run") or {}
    job = payload.get("job") or {}
    run_id = str(run.get("runId") or run.get("id") or "")
    job_ns = str(job.get("namespace") or "")
    job_name = str(job.get("name") or "")
    producer = str(payload.get("producer") or "")
    event_time = payload.get("eventTime")

    inputs = [d for d in (payload.get("inputs") or []) if isinstance(d, dict)]
    outputs = [d for d in (payload.get("outputs") or []) if isinstance(d, dict)]

    input_fqns = [_dataset_fqn(d) for d in inputs]
    output_fqns = [_dataset_fqn(d) for d in outputs]
    input_fqns = [x for x in input_fqns if x]
    output_fqns = [x for x in output_fqns if x]

    edges: list[dict] = []
    if input_fqns and output_fqns:
        for inp in input_fqns:
            for out in output_fqns:
                if inp != out:
                    edges.append(
                        {
                            "from_dataset": inp,
                            "to_dataset": out,
                            "edge_kind": "openlineage",
                            "confidence": 0.9,
                            "job": f"{job_ns}.{job_name}".strip("."),
                        }
                    )
    elif len(output_fqns) >= 2:
        for i in range(len(output_fqns) - 1):
            edges.append(
                {
                    "from_dataset": output_fqns[i],
                    "to_dataset": output_fqns[i + 1],
                    "edge_kind": "openlineage",
                    "confidence": 0.7,
                }
            )

    # Dedupe by from/to
    seen: set[tuple[str, str]] = set()
    deduped: list[dict] = []
    for e in edges:
        key = (e["from_dataset"], e["to_dataset"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(e)

    return {
        "event_type": event_type,
        "run_id": run_id,
        "job_name": job_name,
        "job_namespace": job_ns,
        "producer": producer,
        "event_time": event_time,
        "edges": deduped,
        "input_count": len(input_fqns),
        "output_count": len(output_fqns),
    }


def should_ingest_event(parsed: dict) -> bool:
    """v1: ingest COMPLETE (and RUN with edges) only."""
    et = str(parsed.get("event_type") or "").upper()
    if et == "COMPLETE":
        return True
    if et == "RUN" and parsed.get("edges"):
        return True
    return False
