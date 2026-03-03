from __future__ import annotations

"""PostgreSQL connection utilities based on environment variables."""

import os

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine


def _require_env(name: str) -> str:
    """Read one required environment variable and fail fast when missing."""
    value = str(os.getenv(name, "")).strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def _build_db_url() -> str:
    """Build PostgreSQL SQLAlchemy URL from ``POSTGRES_*`` env variables."""
    host = _require_env("POSTGRES_HOST")
    port = _require_env("POSTGRES_PORT")
    dbname = _require_env("POSTGRES_DB")
    user = _require_env("POSTGRES_USER")
    password = _require_env("POSTGRES_PASSWORD")
    return f"postgresql://{user}:{password}@{host}:{port}/{dbname}"


def get_db_engine() -> Engine:
    """Create a SQLAlchemy engine for PostgreSQL.

    Returns
    -------
    sqlalchemy.engine.Engine
        Database engine configured from ``POSTGRES_*`` environment variables.

    Raises
    ------
    RuntimeError
        If engine initialization fails.
    """
    try:
        return create_engine(_build_db_url())
    except Exception as e:
        raise RuntimeError(
            "PostgreSQL engine initialization failed. Check Docker/Postgres is running and "
            "POSTGRES_HOST/PORT/DB/USER/PASSWORD environment variables are correct."
        ) from e


def get_db_connection():
    """Backward-compatible raw DB-API connection for existing callers."""
    engine = get_db_engine()
    return engine.raw_connection()
