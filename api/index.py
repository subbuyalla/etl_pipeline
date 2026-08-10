"""
Vercel ASGI entry for the ETL Observability App API.

Vercel routes requests to this module; we re-export the FastAPI `app`
from application.src.app.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Repo root must be on sys.path so `application.*` imports resolve.
_ROOT = Path(__file__).resolve().parents[1]
_root_str = str(_ROOT)
if _root_str not in sys.path:
    sys.path.insert(0, _root_str)

from application.src.app import app  # noqa: E402

__all__ = ["app"]
