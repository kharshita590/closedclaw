from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from actions.models import AgentAction, action_from_payload
from graph.state import PendingAction
from security.config import get_security_settings


class ApprovalLedger:
    """Persistent SQLite approval ledger for every sensitive action plan."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        """Opens the ledger database and creates the schema if needed."""

        settings = get_security_settings()
        self.db_path = Path(db_path) if db_path else settings.approval_db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        """Creates approval ledger tables and indexes."""

        with sqlite3.connect(self.db_path) as con:
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS approval_ledger (
                    id TEXT PRIMARY KEY,
                    action_type TEXT NOT NULL,
                    action_payload TEXT NOT NULL,
                    requested_by TEXT NOT NULL,
                    requested_at TEXT NOT NULL,
                    status TEXT NOT NULL,
                    decided_at TEXT,
                    decided_by TEXT,
                    execution_result TEXT
                )
                """
            )
            con.execute("CREATE INDEX IF NOT EXISTS idx_approval_status ON approval_ledger(status)")
            con.execute("CREATE INDEX IF NOT EXISTS idx_approval_action_time ON approval_ledger(action_type, decided_at)")

    def create(self, action: AgentAction, requested_by: str, status: str = "pending", result: dict[str, Any] | None = None) -> PendingAction:
        """Persists a new approval row and returns the API-facing pending action."""

        action_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        with sqlite3.connect(self.db_path) as con:
            con.execute(
                """
                INSERT INTO approval_ledger(
                    id, action_type, action_payload, requested_by, requested_at,
                    status, decided_at, decided_by, execution_result
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    action_id,
                    action.action_type,
                    json.dumps(action.model_dump(mode="json")),
                    requested_by,
                    now,
                    status,
                    now if status != "pending" else None,
                    "policy" if status != "pending" else None,
                    json.dumps(result or {}),
                ),
            )
        return self._pending_from_action(action_id, action, requested_by, status)

    def list_pending(self) -> list[PendingAction]:
        """Returns all pending approvals from durable storage."""

        with sqlite3.connect(self.db_path) as con:
            con.row_factory = sqlite3.Row
            rows = con.execute("SELECT * FROM approval_ledger WHERE status = 'pending' ORDER BY requested_at").fetchall()
        return [self._pending_from_row(dict(row)) for row in rows]

    def get(self, action_id: str) -> dict[str, Any] | None:
        """Loads one ledger row by id."""

        with sqlite3.connect(self.db_path) as con:
            con.row_factory = sqlite3.Row
            row = con.execute("SELECT * FROM approval_ledger WHERE id = ?", (action_id,)).fetchone()
        return dict(row) if row else None

    def get_action(self, action_id: str) -> AgentAction:
        """Returns the typed action stored in a ledger row."""

        row = self.get(action_id)
        if not row:
            raise KeyError(action_id)
        return action_from_payload(json.loads(row["action_payload"]))

    def decide(self, action_id: str, status: str, decided_by: str, result: dict[str, Any] | None = None) -> PendingAction:
        """Marks an approval approved/rejected and stores any execution result."""

        row = self.get(action_id)
        if not row:
            raise KeyError(action_id)
        now = datetime.now(timezone.utc).isoformat()
        with sqlite3.connect(self.db_path) as con:
            con.execute(
                """
                UPDATE approval_ledger
                SET status = ?, decided_at = ?, decided_by = ?, execution_result = ?
                WHERE id = ?
                """,
                (status, now, decided_by, json.dumps(result or {}), action_id),
            )
        updated = self.get(action_id)
        return self._pending_from_row(updated)

    def count_executed_since(self, action_type: str, since: datetime) -> int:
        """Counts approved/executed actions of one type since a timestamp."""

        with sqlite3.connect(self.db_path) as con:
            row = con.execute(
                """
                SELECT COUNT(*) FROM approval_ledger
                WHERE action_type = ? AND status = 'approved' AND decided_at >= ?
                """,
                (action_type, since.isoformat()),
            ).fetchone()
        return int(row[0])

    def _pending_from_action(self, action_id: str, action: AgentAction, user_id: str, status: str) -> PendingAction:
        """Converts a typed action into the API response shape."""

        return PendingAction(
            id=action_id,
            action_type=action.action_type,
            summary=action.to_human_readable(),
            payload=action.model_dump(mode="json"),
            channel="ledger",
            user_id=user_id,
            status=status,
        )

    def _pending_from_row(self, row: dict[str, Any]) -> PendingAction:
        """Converts a SQLite ledger row into the API response shape."""

        action = action_from_payload(json.loads(row["action_payload"]))
        return self._pending_from_action(row["id"], action, row["requested_by"], row["status"])
