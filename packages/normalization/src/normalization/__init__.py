"""Normalization Layer — raw tool payloads → canonical events."""

from normalization.engine import (
    normalize,
    normalize_batch,
    normalize_batch_production,
    normalize_production,
    supported_tools,
)
from normalization.registry import TOOL_FAMILIES, list_tools, register_mapper
from normalization.result import DeadLetter, NormalizeResult

__all__ = [
    "normalize",
    "normalize_batch",
    "normalize_production",
    "normalize_batch_production",
    "supported_tools",
    "list_tools",
    "register_mapper",
    "TOOL_FAMILIES",
    "DeadLetter",
    "NormalizeResult",
]
__version__ = "0.2.0"
