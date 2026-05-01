from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class SQLiteCheckpointer:
    def __init__(self, db_path: str = "memory/graph_state.db") -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.db_path) as con:
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS conversations (
                    thread_id TEXT PRIMARY KEY,
                    state TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )

    def get(self, thread_id: str) -> dict[str, Any]:
        with sqlite3.connect(self.db_path) as con:
            row = con.execute("SELECT state FROM conversations WHERE thread_id = ?", (thread_id,)).fetchone()
        return json.loads(row[0]) if row else {"messages": []}

    def put(self, thread_id: str, state: dict[str, Any]) -> None:
        with sqlite3.connect(self.db_path) as con:
            con.execute(
                """
                INSERT INTO conversations(thread_id, state, updated_at) VALUES (?, ?, ?)
                ON CONFLICT(thread_id) DO UPDATE SET state = excluded.state, updated_at = excluded.updated_at
                """,
                (thread_id, json.dumps(state), datetime.now(timezone.utc).isoformat()),
            )
