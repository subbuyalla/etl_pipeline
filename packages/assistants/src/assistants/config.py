from __future__ import annotations

import os
from pathlib import Path


def _load_dotenv() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    here = Path(__file__).resolve()
    candidates = [
        Path.cwd() / ".env",
        here.parents[4] / ".env" if len(here.parents) > 4 else None,
        here.parents[3] / ".env" if len(here.parents) > 3 else None,
    ]
    for path in candidates:
        if path and path.is_file():
            load_dotenv(path, override=False)
            return
    load_dotenv(override=False)


_load_dotenv()

METADATA_API_BASE = os.getenv("METADATA_API_BASE", "http://127.0.0.1:8000").rstrip("/")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "").strip()
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "openrouter/free").strip() or "openrouter/free"
OPENROUTER_BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1").rstrip("/")
ASSISTANTS_HOST = os.getenv("ASSISTANTS_HOST", "0.0.0.0")
ASSISTANTS_PORT = int(os.getenv("ASSISTANTS_PORT", "8001"))
