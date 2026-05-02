"""PostgreSQL-backed approval ledger for sensitive action execution.

The ledger is the durable source of truth for approval requests, decisions, and
execution results. It replaces the earlier in-memory and SQLite stores so worker
processes and API processes can coordinate safely.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from actions.models import AgentAction, action_from_payload
from db.connection import connection_context
from graph.state import PendingAction


class ApprovalLedger:
    """Persistent PostgreSQL approval ledger for every sensitive action plan."""

    def __init__(self, db_path: str | None = None) -> None:
        """Initialize the ledger and create the PostgreSQL schema.

        Args:
            db_path: Kept for backward compatibility with the previous SQLite
                constructor. PostgreSQL now uses DATABASE_URL instead.
        """

        self.db_path = db_path
        self._init_db()

    def _init_db(self) -> None:
        """Create the approval ledger table and indexes if they do not exist."""

        with connection_context() as conn:
            with conn.cursor() as cur:
                cur.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS approval_ledger (
                        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                        action_type TEXT NOT NULL,
                        action_payload JSONB NOT NULL,
                        requested_by TEXT NOT NULL,
                        requested_at TIMESTAMPTZ NOT NULL,
                        status TEXT NOT NULL,
                        decided_at TIMESTAMPTZ,
                        decided_by TEXT,
                        execution_result JSONB NOT NULL DEFAULT '{}'::jsonb
                    )
                    """
                )
                cur.execute("CREATE INDEX IF NOT EXISTS idx_approval_status ON approval_ledger(status)")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_approval_action_time ON approval_ledger(action_type, decided_at)")

    def create(self, action: AgentAction, requested_by: str, status: str = "pending", result: dict[str, Any] | None = None) -> PendingAction:
        """Persist a new approval row and return the API-facing action.

        Args:
            action: Typed action plan to store.
            requested_by: User or channel sender that requested the action.
            status: Initial ledger status.
            result: Optional policy rejection or execution metadata.

        Returns:
            A PendingAction model for API/UI display.
        """

        now = datetime.now(timezone.utc)
        decided_at = now if status != "pending" else None
        decided_by = "policy" if status != "pending" else None
        with connection_context() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO approval_ledger(
                        action_type, action_payload, requested_by, requested_at,
                        status, decided_at, decided_by, execution_result
                    )
                    VALUES (%s, %s::jsonb, %s, %s, %s, %s, %s, %s::jsonb)
                    RETURNING id
                    """,
                    (
                        action.action_type,
                        json.dumps(action.model_dump(mode="json")),
                        requested_by,
                        now,
                        status,
                        decided_at,
                        decided_by,
                        json.dumps(result or {}),
                    ),
                )
                action_id = str(cur.fetchone()[0])
        return self._pending_from_action(action_id, action, requested_by, status)

    def list_pending(self) -> list[PendingAction]:
        """Return all approvals that are still pending."""

        with connection_context() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM approval_ledger WHERE status = 'pending' ORDER BY requested_at")
                rows = cur.fetchall()
                columns = [desc[0] for desc in cur.description]
        return [self._pending_from_row(dict(zip(columns, row))) for row in rows]

    def list_queued(self) -> list[PendingAction]:
        """Return approvals that have been queued but not yet completed."""

        with connection_context() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM approval_ledger WHERE status = 'queued' ORDER BY requested_at")
                rows = cur.fetchall()
                columns = [desc[0] for desc in cur.description]
        return [self._pending_from_row(dict(zip(columns, row))) for row in rows]

    def get(self, action_id: str) -> dict[str, Any] | None:
        """Load one approval ledger row by UUID.

        Args:
            action_id: Approval UUID.

        Returns:
            A dictionary row or None if the id is unknown.
        """

        with connection_context() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM approval_ledger WHERE id = %s", (action_id,))
                row = cur.fetchone()
                if not row:
                    return None
                columns = [desc[0] for desc in cur.description]
        return dict(zip(columns, row))

    def get_action(self, action_id: str) -> AgentAction:
        """Return the typed action stored in a ledger row.

        Args:
            action_id: Approval UUID.

        Returns:
            The typed action model stored in action_payload.
        """

        row = self.get(action_id)
        if not row:
            raise KeyError(action_id)
        payload = row["action_payload"]
        return action_from_payload(payload if isinstance(payload, dict) else json.loads(payload))

    def mark_queued(self, action_id: str, decided_by: str) -> PendingAction:
        """Move a pending approval to queued so repeated clicks cannot enqueue it again."""

        with connection_context() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE approval_ledger
                    SET status = 'queued', decided_by = %s, execution_result = %s::jsonb
                    WHERE id = %s AND status = 'pending'
                    """,
                    (decided_by, json.dumps({"queued": True}), action_id),
                )
                if cur.rowcount != 1:
                    raise ValueError("Approval is not pending")
        updated = self.get(action_id)
        return self._pending_from_row(updated)

    def claim_for_execution(self, action_id: str) -> AgentAction | None:
        """Atomically claim one queued approval for execution.

        Returns None if another worker already claimed or completed it.
        """

        with connection_context() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE approval_ledger
                    SET status = 'executing'
                    WHERE id = %s AND status = 'queued'
                    RETURNING action_payload
                    """,
                    (action_id,),
                )
                row = cur.fetchone()
        if not row:
            return None
        payload = row[0]
        return action_from_payload(payload if isinstance(payload, dict) else json.loads(payload))

    def decide(self, action_id: str, status: str, decided_by: str, result: dict[str, Any] | None = None) -> PendingAction:
        """Mark an approval approved/rejected and store execution result.

        Args:
            action_id: Approval UUID.
            status: New status.
            decided_by: Human or worker identity making the decision.
            result: Optional execution or rejection details.

        Returns:
            The updated PendingAction view.
        """

        row = self.get(action_id)
        if not row:
            raise KeyError(action_id)
        now = datetime.now(timezone.utc)
        with connection_context() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE approval_ledger
                    SET status = %s, decided_at = %s, decided_by = %s, execution_result = %s::jsonb
                    WHERE id = %s
                    """,
                    (status, now, decided_by, json.dumps(result or {}), action_id),
                )
        updated = self.get(action_id)
        return self._pending_from_row(updated)

    def count_executed_since(self, action_type: str, since: datetime) -> int:
        """Count approved actions of one type since a timestamp.

        Args:
            action_type: Typed action name such as email.send.
            since: Earliest decision timestamp to include.

        Returns:
            Number of approved actions in the interval.
        """

        with connection_context() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT COUNT(*) FROM approval_ledger
                    WHERE action_type = %s AND status = 'approved' AND decided_at >= %s
                    """,
                    (action_type, since),
                )
                return int(cur.fetchone()[0])

    def _pending_from_action(self, action_id: str, action: AgentAction, user_id: str, status: str) -> PendingAction:
        """Convert a typed action into the API response shape."""

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
        """Convert a PostgreSQL ledger row into the API response shape."""

        payload = row["action_payload"]
        action = action_from_payload(payload if isinstance(payload, dict) else json.loads(payload))
        return self._pending_from_action(str(row["id"]), action, row["requested_by"], row["status"])
