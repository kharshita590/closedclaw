"""Shared pytest fixtures for PostgreSQL-backed safety tests."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bridges"))


@pytest.fixture()
def postgres_database(monkeypatch: pytest.MonkeyPatch):
    """Provide a PostgreSQL database connection or skip when unavailable."""

    psycopg2 = pytest.importorskip("psycopg2")
    database_url = os.getenv("TEST_DATABASE_URL") or os.getenv("DATABASE_URL")
    if not database_url:
        pytest.skip("TEST_DATABASE_URL or DATABASE_URL is required for PostgreSQL tests")
    monkeypatch.setenv("DATABASE_URL", database_url)
    try:
        conn = psycopg2.connect(database_url)
    except psycopg2.OperationalError as exc:
        pytest.skip(f"PostgreSQL unavailable for tests: {exc}")
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute("DROP TABLE IF EXISTS approval_ledger CASCADE")
        cur.execute("DROP TABLE IF EXISTS pairing_requests CASCADE")
        cur.execute("DROP TABLE IF EXISTS channel_policy CASCADE")
        cur.execute("DROP TABLE IF EXISTS memories CASCADE")
        cur.execute("DROP TABLE IF EXISTS contacts CASCADE")
    yield database_url
    with conn.cursor() as cur:
        cur.execute("DROP TABLE IF EXISTS approval_ledger CASCADE")
        cur.execute("DROP TABLE IF EXISTS pairing_requests CASCADE")
        cur.execute("DROP TABLE IF EXISTS channel_policy CASCADE")
        cur.execute("DROP TABLE IF EXISTS memories CASCADE")
        cur.execute("DROP TABLE IF EXISTS contacts CASCADE")
    conn.close()
