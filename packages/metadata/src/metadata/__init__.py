"""Metadata Layer — canonical observability store."""

from metadata.db import get_engine, get_session, init_db
from metadata.ingest import ingest_canonical_event, ingest_canonical_events
from metadata.repository import MetadataRepository

__all__ = [
    "get_engine",
    "get_session",
    "init_db",
    "ingest_canonical_event",
    "ingest_canonical_events",
    "MetadataRepository",
]
__version__ = "0.1.0"
