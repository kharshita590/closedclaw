#!/usr/bin/env python3
"""Migrate legacy SQLite state into the PostgreSQL safety database.

This script preserves data for users upgrading from the SQLite implementation by
copying approval ledger rows, pairing requests, memories, and JSON contacts into
the new PostgreSQL tables.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent"))
sys.path.insert(0, str(ROOT / "bridges"))

from approvals.ledger import ApprovalLedger  # noqa: E402
from channel_policy import ChannelPolicy, PairingStore  # noqa: E402
from db.connection import connection_context  # noqa: E402
from tools.memory_tools import MemoryStore  # noqa: E402


def migrate_approvals(sqlite_path: Path) -> int:
    """Copy legacy approval_ledger rows from SQLite to PostgreSQL.

    Args:
        sqlite_path: Path to the old SQLite approval database.

    Returns:
        Number of rows migrated.
    """

    ApprovalLedger()
    if not sqlite_path.exists():
        return 0
    count = 0
    with sqlite3.connect(sqlite_path) as source, connection_context() as target:
        source.row_factory = sqlite3.Row
        rows = source.execute("SELECT * FROM approval_ledger").fetchall()
        with target.cursor() as cur:
            for row in rows:
                cur.execute(
                    """
                    INSERT INTO approval_ledger(
                        id, action_type, action_payload, requested_by, requested_at,
                        status, decided_at, decided_by, execution_result
                    )
                    VALUES (%s, %s, %s::jsonb, %s, %s, %s, %s, %s, %s::jsonb)
                    ON CONFLICT(id) DO NOTHING
                    """,
                    (
                        row["id"],
                        row["action_type"],
                        row["action_payload"],
                        row["requested_by"],
                        row["requested_at"],
                        row["status"],
                        row["decided_at"],
                        row["decided_by"],
                        row["execution_result"] or "{}",
                    ),
                )
                count += 1
    return count


def migrate_pairing(sqlite_path: Path) -> int:
    """Copy legacy pairing_requests rows from SQLite to PostgreSQL."""

    PairingStore()
    if not sqlite_path.exists():
        return 0
    count = 0
    with sqlite3.connect(sqlite_path) as source, connection_context() as target:
        source.row_factory = sqlite3.Row
        rows = source.execute("SELECT * FROM pairing_requests").fetchall()
        with target.cursor() as cur:
            for row in rows:
                cur.execute(
                    """
                    INSERT INTO pairing_requests(channel, sender_id, code, expires_at, attempts)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT(channel, sender_id) DO UPDATE
                    SET code = excluded.code, expires_at = excluded.expires_at, attempts = excluded.attempts
                    """,
                    (row["channel"], row["sender_id"], row["code"], row["expires_at"], row["attempts"]),
                )
                count += 1
    return count


def migrate_channel_policy(policy_path: Path) -> int:
    """Copy legacy channel_policy.yaml JSON-formatted allowlists to PostgreSQL."""

    ChannelPolicy()
    if not policy_path.exists() or not policy_path.read_text().strip():
        return 0
    data = json.loads(policy_path.read_text(encoding="utf-8"))
    count = 0
    with connection_context() as target:
        with target.cursor() as cur:
            for channel, config in data.get("channels", {}).items():
                for sender_id in config.get("allowed_senders", []):
                    cur.execute(
                        """
                        INSERT INTO channel_policy(channel, sender_id, added_at)
                        VALUES (%s, %s, now())
                        ON CONFLICT(channel, sender_id) DO NOTHING
                        """,
                        (channel, str(sender_id)),
                    )
                    count += 1
    return count


def migrate_memories(sqlite_path: Path) -> int:
    """Copy legacy memories from SQLite to PostgreSQL."""

    MemoryStore()
    if not sqlite_path.exists():
        return 0
    count = 0
    with sqlite3.connect(sqlite_path) as source, connection_context() as target:
        source.row_factory = sqlite3.Row
        rows = source.execute("SELECT * FROM memories").fetchall()
        with target.cursor() as cur:
            for row in rows:
                cur.execute(
                    """
                    INSERT INTO memories(channel, user_id, kind, content, metadata, created_at)
                    VALUES (%s, %s, %s, %s, %s::jsonb, %s)
                    """,
                    (row["channel"], row["user_id"], row["kind"], row["content"], row["metadata"], row["created_at"]),
                )
                count += 1
    return count


def migrate_contacts(json_path: Path) -> int:
    """Copy legacy contacts.json data into PostgreSQL."""

    MemoryStore()
    if not json_path.exists() or not json_path.read_text().strip():
        return 0
    contacts = json.loads(json_path.read_text(encoding="utf-8"))
    count = 0
    with connection_context() as target:
        with target.cursor() as cur:
            for key, data in contacts.items():
                cur.execute(
                    """
                    INSERT INTO contacts(key, data, updated_at)
                    VALUES (%s, %s::jsonb, now())
                    ON CONFLICT(key) DO UPDATE SET data = excluded.data, updated_at = excluded.updated_at
                    """,
                    (key, json.dumps(data)),
                )
                count += 1
    return count


def main() -> None:
    """Run every available legacy migration and print migrated row counts."""

    print(f"approval rows: {migrate_approvals(ROOT / 'memory' / 'approval_ledger.db')}")
    print(f"channel policy rows: {migrate_channel_policy(ROOT / 'channel_policy.yaml')}")
    print(f"pairing rows: {migrate_pairing(ROOT / 'memory' / 'pairing_requests.db')}")
    print(f"memory rows: {migrate_memories(ROOT / 'memory' / 'knowledge_base.db')}")
    print(f"contact rows: {migrate_contacts(ROOT / 'memory' / 'contacts.json')}")


if __name__ == "__main__":
    main()
