"""PostgreSQL-backed personal memory and contact store.

This module preserves the original MemoryStore class while moving durable memory
records out of SQLite and local JSON files so API and worker processes share one
consistent database.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from db.connection import connection_context


class MemoryStore:
    """Stores conversation memories and lightweight CRM contacts in PostgreSQL."""

    def __init__(self, db_path: str = "memory/knowledge_base.db", contacts_path: str = "memory/contacts.json") -> None:
        """Initialize tables while preserving the old constructor signature.

        Args:
            db_path: Deprecated SQLite path kept for compatibility.
            contacts_path: Deprecated JSON contacts path kept for compatibility.
        """

        self.db_path = Path(db_path)
        self.contacts_path = Path(contacts_path)
        self._init_db()

    def _init_db(self) -> None:
        """Create memory and contact tables if they do not exist."""

        with connection_context() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS memories (
                        id BIGSERIAL PRIMARY KEY,
                        channel TEXT NOT NULL,
                        user_id TEXT NOT NULL,
                        kind TEXT NOT NULL,
                        content TEXT NOT NULL,
                        metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
                        created_at TIMESTAMPTZ NOT NULL
                    )
                    """
                )
                cur.execute("CREATE INDEX IF NOT EXISTS idx_memories_lookup ON memories(user_id, kind, created_at)")
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS contacts (
                        key TEXT PRIMARY KEY,
                        data JSONB NOT NULL,
                        updated_at TIMESTAMPTZ NOT NULL
                    )
                    """
                )

    def remember(self, channel: str, user_id: str, kind: str, content: str, metadata: dict[str, Any] | None = None) -> int:
        """Persist a memory row and return its numeric id."""

        with connection_context() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO memories(channel, user_id, kind, content, metadata, created_at)
                    VALUES (%s, %s, %s, %s, %s::jsonb, %s)
                    RETURNING id
                    """,
                    (channel, user_id, kind, content, json.dumps(metadata or {}), datetime.now(timezone.utc)),
                )
                return int(cur.fetchone()[0])

    def search(self, user_id: str, query: str, limit: int = 10) -> list[dict[str, Any]]:
        """Search recent memories by content or metadata text."""

        pattern = f"%{query}%"
        with connection_context() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, channel, user_id, kind, content, metadata, created_at
                    FROM memories
                    WHERE user_id = %s AND (content ILIKE %s OR metadata::text ILIKE %s)
                    ORDER BY created_at DESC
                    LIMIT %s
                    """,
                    (user_id, pattern, pattern, limit),
                )
                rows = cur.fetchall()
        return [
            {
                "id": row[0],
                "channel": row[1],
                "user_id": row[2],
                "kind": row[3],
                "content": row[4],
                "metadata": row[5],
                "created_at": row[6].isoformat(),
            }
            for row in rows
        ]

    def upsert_contact(self, key: str, data: dict[str, Any]) -> None:
        """Insert or update a CRM contact document by key."""

        updated_at = datetime.now(timezone.utc)
        merged = {**self.contacts().get(key, {}), **data, "updated_at": updated_at.isoformat()}
        with connection_context() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO contacts(key, data, updated_at)
                    VALUES (%s, %s::jsonb, %s)
                    ON CONFLICT(key) DO UPDATE SET data = excluded.data, updated_at = excluded.updated_at
                    """,
                    (key, json.dumps(merged), updated_at),
                )

    def contacts(self) -> dict[str, Any]:
        """Return all contact documents keyed by contact id."""

        with connection_context() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT key, data FROM contacts")
                rows = cur.fetchall()
        return {row[0]: row[1] for row in rows}
