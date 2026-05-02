"""PostgreSQL connection pooling for durable agent state.

This module centralizes database access so approvals, memory, pairing, and channel
policy all use the same PostgreSQL connection pool configured by DATABASE_URL.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Iterator

import psycopg2
from psycopg2.extensions import connection
from psycopg2.pool import ThreadedConnectionPool

DEFAULT_DATABASE_URL = "postgresql://closedclaw:closedclaw@postgres:5432/closedclaw"
_pool: ThreadedConnectionPool | None = None


def get_database_url() -> str:
    """Return the configured PostgreSQL URL or the Docker Compose default."""

    return os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL)


def get_pool() -> ThreadedConnectionPool:
    """Return a process-wide PostgreSQL threaded connection pool."""

    global _pool
    if _pool is None:
        _pool = ThreadedConnectionPool(2, 10, dsn=get_database_url())
    return _pool


def get_connection() -> connection:
    """Borrow a PostgreSQL connection from the shared pool.

    The caller must return it with `put_connection()` after use.
    """

    return get_pool().getconn()


def put_connection(conn: connection) -> None:
    """Return a borrowed PostgreSQL connection to the shared pool."""

    get_pool().putconn(conn)


@contextmanager
def connection_context() -> Iterator[connection]:
    """Yield a pooled connection and always return it to the pool."""

    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        put_connection(conn)
