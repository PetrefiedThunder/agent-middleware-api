"""Normalize database URLs for SQLAlchemy vs raw asyncpg consumers.

Railway and many hosts provide ``postgresql://...``. SQLAlchemy async needs
``postgresql+asyncpg://...``. Raw ``asyncpg.create_pool`` rejects the
``+asyncpg`` driver suffix.
"""

from __future__ import annotations


def as_sqlalchemy_url(url: str) -> str:
    """Return a URL suitable for SQLAlchemy ``create_async_engine``."""
    trimmed = (url or "").strip()
    if not trimmed:
        return trimmed
    if trimmed.startswith("postgresql+asyncpg://"):
        return trimmed
    if trimmed.startswith("postgres://"):
        return "postgresql+asyncpg://" + trimmed[len("postgres://") :]
    if trimmed.startswith("postgresql://"):
        return "postgresql+asyncpg://" + trimmed[len("postgresql://") :]
    return trimmed


def is_postgres_url(url: str) -> bool:
    """True when ``url`` is a PostgreSQL DSN rather than some other backend.

    ``DATABASE_URL`` being set does not imply PostgreSQL — a SQLAlchemy SQLite
    URL is the standard local-development value. Callers that hand the URL to
    a Postgres-only driver must check this first.
    """
    trimmed = (url or "").strip().lower()
    return trimmed.startswith(
        ("postgres://", "postgresql://", "postgresql+asyncpg://")
    )


def sqlite_path_from_url(url: str) -> str:
    """Return the SQLite file path in ``url``, or "" if it is not SQLite.

    Accepts the SQLAlchemy spellings (``sqlite://`` and ``sqlite+aiosqlite://``)
    and returns what ``aiosqlite.connect`` expects. In-memory URLs yield "",
    since there is nothing durable to point a state backend at.
    """
    trimmed = (url or "").strip()
    for prefix in ("sqlite+aiosqlite://", "sqlite://"):
        if trimmed.lower().startswith(prefix):
            remainder = trimmed[len(prefix) :]
            # sqlite:///relative.db -> relative.db; sqlite:////abs.db -> /abs.db
            return remainder[1:] if remainder.startswith("/") else remainder
    return ""


def as_asyncpg_url(url: str) -> str:
    """Return a URL suitable for ``asyncpg.create_pool``."""
    trimmed = (url or "").strip()
    if not trimmed:
        return trimmed
    if trimmed.startswith("postgresql+asyncpg://"):
        return "postgresql://" + trimmed[len("postgresql+asyncpg://") :]
    if trimmed.startswith("postgres://"):
        return "postgresql://" + trimmed[len("postgres://") :]
    return trimmed
