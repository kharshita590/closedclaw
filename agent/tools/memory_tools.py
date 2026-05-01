from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class MemoryStore:
    def __init__(self, db_path: str = "memory/knowledge_base.db", contacts_path: str = "memory/contacts.json") -> None:
        self.db_path = Path(db_path)
        self.contacts_path = Path(contacts_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.contacts_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as con:
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    channel TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    content TEXT NOT NULL,
                    metadata TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                )
                """
            )
            con.execute("CREATE INDEX IF NOT EXISTS idx_memories_lookup ON memories(user_id, kind, created_at)")

    def remember(self, channel: str, user_id: str, kind: str, content: str, metadata: dict[str, Any] | None = None) -> int:
        with sqlite3.connect(self.db_path) as con:
            cur = con.execute(
                "INSERT INTO memories(channel, user_id, kind, content, metadata, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    channel,
                    user_id,
                    kind,
                    content,
                    json.dumps(metadata or {}),
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            return int(cur.lastrowid)

    def search(self, user_id: str, query: str, limit: int = 10) -> list[dict[str, Any]]:
        pattern = f"%{query}%"
        with sqlite3.connect(self.db_path) as con:
            con.row_factory = sqlite3.Row
            rows = con.execute(
                """
                SELECT * FROM memories
                WHERE user_id = ? AND (content LIKE ? OR metadata LIKE ?)
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (user_id, pattern, pattern, limit),
            ).fetchall()
        return [dict(row) | {"metadata": json.loads(row["metadata"])} for row in rows]

    def upsert_contact(self, key: str, data: dict[str, Any]) -> None:
        contacts = self.contacts()
        contacts[key] = {**contacts.get(key, {}), **data, "updated_at": datetime.now(timezone.utc).isoformat()}
        self.contacts_path.write_text(json.dumps(contacts, indent=2), encoding="utf-8")

    def contacts(self) -> dict[str, Any]:
        if not self.contacts_path.exists() or not self.contacts_path.read_text().strip():
            return {}
        return json.loads(self.contacts_path.read_text(encoding="utf-8"))
