"""
Vercel FastAPI entrypoint (supported root name: app.py).

Re-exports the Metadata API FastAPI instance as `app`.
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
_root_str = str(_ROOT)
if _root_str not in sys.path:
    sys.path.insert(0, _root_str)

from application.src.app import app  # noqa: E402

__all__ = ["app"]
