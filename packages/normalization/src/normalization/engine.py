from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from normalization.errors import (
    CanonicalValidationError,
    InvalidRawPayloadError,
    NormalizationError,
    UnknownToolError,
)
from normalization.registry import get_mapper, list_tools
from normalization.result import DeadLetter, NormalizeResult

_CONTRACTS_DIR = Path(__file__).resolve().parents[3] / "contracts" / "schemas"
_EVENT_SCHEMA_PATH = _CONTRACTS_DIR / "canonical_event.schema.json"
_PACKAGED_SCHEMA = Path(__file__).resolve().parent / "schemas" / "canonical_event.schema.json"

_validator: Draft202012Validator | None = None


def _get_validator() -> Draft202012Validator:
    global _validator
    if _validator is None:
        schema_path = _EVENT_SCHEMA_PATH if _EVENT_SCHEMA_PATH.exists() else _PACKAGED_SCHEMA
        if schema_path.exists():
            schema = json.loads(schema_path.read_text(encoding="utf-8"))
        else:
            schema = {
                "type": "object",
                "required": [
                    "event_id",
                    "event_type",
                    "occurred_at",
                    "tenant_id",
                    "source_system",
                    "source_tool",
                    "payload",
                ],
                "properties": {
                    "event_id": {"type": "string", "minLength": 1},
                    "event_type": {"type": "string", "minLength": 1},
                    "occurred_at": {"type": "string"},
                    "tenant_id": {"type": "string", "minLength": 1},
                    "source_system": {"type": "string", "minLength": 1},
                    "source_tool": {"type": "string", "minLength": 1},
                    "connector_instance_id": {"type": ["string", "null"]},
                    "payload": {"type": "object"},
                },
            }
        _validator = Draft202012Validator(schema)
    return _validator


def validate_canonical(event: dict[str, Any]) -> None:
    errors = sorted(_get_validator().iter_errors(event), key=lambda e: e.path)
    if errors:
        msgs = "; ".join(f"{'/'.join(map(str, e.path)) or '<root>'}: {e.message}" for e in errors)
        raise CanonicalValidationError(msgs)


def _resolve_args(
    envelope: dict[str, Any] | None,
    source_system: str | None,
    raw: dict[str, Any] | list[Any] | None,
    tenant_id: str | None,
    connector_instance_id: str | None,
) -> tuple[str, dict[str, Any] | list[Any], str, str | None]:
    if envelope is not None:
        source_system = source_system or envelope.get("source_system") or envelope.get("source_tool")
        if raw is None:
            raw = envelope.get("raw")
            if raw is None:
                raw = envelope.get("payload")
        tenant_id = tenant_id or envelope.get("tenant_id")
        if connector_instance_id is None:
            connector_instance_id = envelope.get("connector_instance_id")

    if not source_system:
        raise InvalidRawPayloadError("unknown", "source_system is required")
    if raw is None or not isinstance(raw, (dict, list)):
        raise InvalidRawPayloadError(str(source_system), "raw must be a JSON object or array")
    if not tenant_id:
        raise InvalidRawPayloadError(str(source_system), "tenant_id is required")
    return str(source_system), raw, str(tenant_id), connector_instance_id


def normalize(
    envelope: dict[str, Any] | None = None,
    *,
    source_system: str | None = None,
    raw: dict[str, Any] | list[Any] | None = None,
    tenant_id: str | None = None,
    connector_instance_id: str | None = None,
    validate: bool = True,
) -> list[dict[str, Any]]:
    """
    Normalize one raw tool payload into canonical event(s).
    Raises on failure (strict). Prefer normalize_production() for dead-letter handling.
    """
    source_system, raw, tenant_id, connector_instance_id = _resolve_args(
        envelope, source_system, raw, tenant_id, connector_instance_id
    )

    mapper = get_mapper(source_system)
    if mapper is None:
        raise UnknownToolError(source_system)

    # Mappers expect dict; wrap bare lists
    payload: dict[str, Any]
    if isinstance(raw, list):
        payload = {"items": raw}
    else:
        payload = raw

    events = mapper.map(payload, tenant_id=tenant_id, connector_instance_id=connector_instance_id)
    if validate:
        for event in events:
            validate_canonical(event)
    return events


def normalize_batch(envelopes: list[dict[str, Any]], *, validate: bool = True) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in envelopes:
        out.extend(normalize(item, validate=validate))
    return out


def normalize_production(
    envelope: dict[str, Any] | None = None,
    *,
    source_system: str | None = None,
    raw: dict[str, Any] | list[Any] | None = None,
    tenant_id: str | None = None,
    connector_instance_id: str | None = None,
    validate: bool = True,
) -> NormalizeResult:
    """
    Production entrypoint: never raises for bad payloads — returns events + dead_letters.
    Unknown tools and invalid envelopes become dead letters.
    """
    result = NormalizeResult()
    try:
        source_system, raw, tenant_id, connector_instance_id = _resolve_args(
            envelope, source_system, raw, tenant_id, connector_instance_id
        )
    except NormalizationError as exc:
        result.dead_letters.append(
            DeadLetter(
                source_system=getattr(exc, "tool", "unknown"),
                tenant_id=tenant_id,
                error_type=type(exc).__name__,
                error_message=str(exc),
                raw=raw if raw is not None else envelope,
                connector_instance_id=connector_instance_id,
            )
        )
        return result

    mapper = get_mapper(source_system)
    if mapper is None:
        result.dead_letters.append(
            DeadLetter(
                source_system=source_system,
                tenant_id=tenant_id,
                error_type="UnknownToolError",
                error_message=f"No mapper registered for '{source_system}'",
                raw=raw,
                connector_instance_id=connector_instance_id,
            )
        )
        return result

    payload: dict[str, Any] = {"items": raw} if isinstance(raw, list) else raw

    try:
        events = mapper.map(payload, tenant_id=tenant_id, connector_instance_id=connector_instance_id)
        if validate:
            for event in events:
                validate_canonical(event)
        result.events.extend(events)
    except NormalizationError as exc:
        result.dead_letters.append(
            DeadLetter(
                source_system=source_system,
                tenant_id=tenant_id,
                error_type=type(exc).__name__,
                error_message=str(exc),
                raw=raw,
                connector_instance_id=connector_instance_id,
            )
        )
    except Exception as exc:  # noqa: BLE001 — production must not crash the ingest worker
        result.dead_letters.append(
            DeadLetter(
                source_system=source_system,
                tenant_id=tenant_id,
                error_type=type(exc).__name__,
                error_message=str(exc),
                raw=raw,
                connector_instance_id=connector_instance_id,
            )
        )
    return result


def normalize_batch_production(
    envelopes: list[dict[str, Any]],
    *,
    validate: bool = True,
) -> NormalizeResult:
    """Batch production normalize — aggregates events and dead letters."""
    merged = NormalizeResult()
    for idx, item in enumerate(envelopes):
        part = normalize_production(item, validate=validate)
        merged.events.extend(part.events)
        for dl in part.dead_letters:
            dl.index = idx
            merged.dead_letters.append(dl)
    return merged


def supported_tools() -> list[str]:
    return list_tools()
