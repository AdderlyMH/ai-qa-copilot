"""One shared, non-pooling SQLAlchemy engine per process (ADR-018, INFRA-006)."""

from __future__ import annotations

from collections.abc import Mapping
import os

from sqlalchemy import create_engine
from sqlalchemy.engine import URL, Engine, make_url
from sqlalchemy.exc import ArgumentError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool


DEFAULT_CONNECT_TIMEOUT_SECONDS = 10


class DatabaseEngineUnavailable(RuntimeError):
    """Raised when the shared engine cannot be built from configuration."""


def create_shared_engine(database_url: str) -> Engine:
    """Build the process engine without a pool, so no idle connection remains.

    `NullPool` opens a fresh connection per unit of work and closes it on
    release, so `pool_pre_ping` has nothing to check and stays off. Error
    messages never include the URL, which may carry a password.
    """

    url_text = database_url.strip()
    if not url_text:
        raise DatabaseEngineUnavailable("DATABASE_URL is not configured")
    try:
        url = make_url(url_text)
    except ArgumentError:
        raise DatabaseEngineUnavailable(
            "DATABASE_URL is not a valid database URL"
        ) from None

    connect_args: dict[str, object] = {}
    if url.get_backend_name() == "postgresql":
        connect_args["connect_timeout"] = _connect_timeout_seconds(url)
        url = url.difference_update_query(["connect_timeout"])
    return create_engine(
        url,
        poolclass=NullPool,
        pool_pre_ping=False,
        connect_args=connect_args,
    )


def database_engine_from_environment(
    environ: Mapping[str, str] = os.environ,
) -> Engine:
    """Build the shared engine only from an explicit DATABASE_URL; fail closed."""

    return create_shared_engine(environ.get("DATABASE_URL", ""))


def session_factory(engine: Engine) -> sessionmaker[Session]:
    """Return the session factory every repository uses over a shared engine."""

    return sessionmaker(engine, expire_on_commit=False)


def _connect_timeout_seconds(url: URL) -> int:
    raw = url.query.get("connect_timeout")
    if raw is None:
        return DEFAULT_CONNECT_TIMEOUT_SECONDS
    if not isinstance(raw, str):
        raise DatabaseEngineUnavailable("DATABASE_URL connect_timeout is repeated")
    try:
        seconds = int(raw)
    except ValueError:
        raise DatabaseEngineUnavailable(
            "DATABASE_URL connect_timeout must be an integer"
        ) from None
    if seconds <= 0:
        raise DatabaseEngineUnavailable("DATABASE_URL connect_timeout must be positive")
    return seconds
