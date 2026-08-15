"""Normalize database URLs for SQLAlchemy vs raw asyncpg consumers.

Railway and many hosts provide ``postgresql://...``. SQLAlchemy async needs
``postgresql+asyncpg://...``. Raw ``asyncpg.create_pool`` rejects the
``+asyncpg`` driver suffix.
"""

from __future__ import annotations

from urllib.parse import parse_qsl


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
    """Return the **durable** SQLite file path in ``url``, or "" otherwise.

    Accepts the SQLAlchemy spellings (``sqlite://`` and ``sqlite+aiosqlite://``)
    and returns what ``aiosqlite.connect`` expects.

    In-memory URLs return "" on purpose. They are valid SQLite, but a state
    store pointed at one keeps nothing across a restart, so treating one as
    durable would reintroduce exactly the silent non-durability this function
    exists to prevent. Callers get "" and fall through to their next option.
    """
    trimmed = (url or "").strip()
    for prefix in ("sqlite+aiosqlite://", "sqlite://"):
        if trimmed.lower().startswith(prefix):
            remainder = trimmed[len(prefix) :]
            # sqlite:///relative.db -> relative.db; sqlite:////abs.db -> /abs.db
            path = remainder[1:] if remainder.startswith("/") else remainder
            if _is_in_memory_sqlite(path):
                return ""
            return path
    return ""


def _is_in_memory_sqlite(path: str) -> bool:
    """True for the SQLite spellings that never touch disk.

    ``mode=memory`` counts only as a query parameter on a ``file:`` URI. A
    substring test would classify the durable filename ``mode=memory.db`` — or
    any directory named that — as ephemeral and route its state to memory.
    """
    normalized = path.strip().lower()
    if not normalized or normalized == ":memory:":
        return True
    if normalized.startswith("file::memory:"):
        return True
    if not normalized.startswith("file:"):
        return False
    _, _, query = normalized.partition("?")
    return any(
        key == "mode" and value == "memory"
        for key, value in parse_qsl(query, keep_blank_values=True)
    )


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
