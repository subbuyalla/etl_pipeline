"""
Vercel FastAPI entrypoint.

Must expose a top-level `app` (Vercel static entrypoint detection).
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
_root_str = str(_ROOT)
if _root_str not in sys.path:
    sys.path.insert(0, _root_str)

from application.src.app import app

__all__ = ["app"]
