from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import quote_plus

from sqlalchemy.orm import Session

from metadata.models import Base, create_session_factory

_ENGINE = None
_SessionLocal = None


def _load_dotenv() -> None:
    """Load project-root .env if python-dotenv is installed."""
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    # Walk up from this file to find repo .env (packages/metadata/src/metadata → root)
    here = Path(__file__).resolve()
    candidates = [
        Path.cwd() / ".env",
        here.parents[4] / ".env" if len(here.parents) > 4 else None,  # .../etl pipeline/.env
        here.parents[3] / ".env" if len(here.parents) > 3 else None,
    ]
    for path in candidates:
        if path and path.is_file():
            load_dotenv(path, override=False)
            return
    load_dotenv(override=False)


def build_database_url_from_parts() -> str | None:
    """
    Build URL from DB_* env vars.
    Example MySQL: mysql+pymysql://user:pass@host:3306/dbname
    """
    user = os.getenv("DB_USER")
    password = os.getenv("DB_PASSWORD")
    host = os.getenv("DB_HOST")
    name = os.getenv("DB_NAME")
    if not all([user, host, name]):
        return None
    driver = os.getenv("DB_DRIVER", "mysql+pymysql")
    port = os.getenv("DB_PORT", "3306")
    # URL-encode password so special chars (@:#/) are safe
    user_q = quote_plus(user)
    pass_q = quote_plus(password or "")
    return f"{driver}://{user_q}:{pass_q}@{host}:{port}/{name}"


def get_database_url() -> str:
    _load_dotenv()
    url = os.getenv("DATABASE_URL", "").strip()
    if url:
        return url
    built = build_database_url_from_parts()
    if built:
        return built
    return "sqlite:///./metadata.db"


def get_engine():
    global _ENGINE, _SessionLocal
    if _ENGINE is None:
        _ENGINE, _SessionLocal = create_session_factory(get_database_url())
    return _ENGINE


def get_session_factory():
    get_engine()
    return _SessionLocal


def get_session() -> Session:
    return get_session_factory()()


def init_db(database_url: str | None = None) -> None:
    global _ENGINE, _SessionLocal
    url = database_url or get_database_url()
    _ENGINE, _SessionLocal = create_session_factory(url)
    Base.metadata.create_all(_ENGINE)


def reset_db_state() -> None:
    """Test helper."""
    global _ENGINE, _SessionLocal
    _ENGINE = None
    _SessionLocal = None
