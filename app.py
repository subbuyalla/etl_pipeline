"""
Vercel FastAPI entrypoint.

Uses an explicit import with a fallback health app so deploy failures are visible
instead of a blank platform 404.
"""

from __future__ import annotations

import sys
import traceback
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
_root_str = str(_ROOT)
if _root_str not in sys.path:
    sys.path.insert(0, _root_str)

try:
    from application.src.app import app  # noqa: E402
except Exception as exc:  # pragma: no cover - deploy diagnostics only
    from fastapi import FastAPI

    app = FastAPI(title="ETL Observability App API (import error)")
    _err = f"{type(exc).__name__}: {exc}"
    _tb = traceback.format_exc()

    @app.get("/")
    @app.get("/health")
    def _boot_error() -> dict:
        return {
            "ok": False,
            "error": "failed_to_import_application",
            "detail": _err,
            "traceback": _tb[:4000],
        }

__all__ = ["app"]
