from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from db.connection import connection_context


@dataclass(frozen=True)
class ScheduledActionRow:
    id: str
    cron_expression: str
    action_type: str
    payload: dict[str, Any]
    owner_user_id: str
    enabled: bool
    last_run: datetime | None
    next_run: datetime | None


class ScheduledActionStore:
    def __init__(self) -> None:
        self._init_db()

    def _init_db(self) -> None:
        with connection_context() as conn:
            with conn.cursor() as cur:
                cur.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS scheduled_actions (
                        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                        cron_expression TEXT NOT NULL,
                        action_type TEXT NOT NULL,
                        payload JSONB NOT NULL,
                        owner_user_id TEXT NOT NULL,
                        enabled BOOLEAN NOT NULL DEFAULT true,
                        last_run TIMESTAMPTZ,
                        next_run TIMESTAMPTZ
                    )
                    """
                )
                cur.execute("CREATE INDEX IF NOT EXISTS idx_scheduled_next_run ON scheduled_actions(enabled, next_run)")

    def list_all(self) -> list[ScheduledActionRow]:
        with connection_context() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM scheduled_actions ORDER BY next_run NULLS LAST")
                rows = cur.fetchall()
                cols = [d[0] for d in cur.description]
        return [self._row(dict(zip(cols, row))) for row in rows]

    def list_due(self, now: datetime) -> list[ScheduledActionRow]:
        with connection_context() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM scheduled_actions WHERE enabled = true AND next_run IS NOT NULL AND next_run <= %s ORDER BY next_run",
                    (now,),
                )
                rows = cur.fetchall()
                cols = [d[0] for d in cur.description]
        return [self._row(dict(zip(cols, row))) for row in rows]

    def insert(self, cron_expression: str, action_type: str, payload: dict[str, Any], owner_user_id: str, next_run: datetime | None) -> str:
        with connection_context() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO scheduled_actions(cron_expression, action_type, payload, owner_user_id, enabled, last_run, next_run)
                    VALUES (%s, %s, %s::jsonb, %s, true, NULL, %s)
                    RETURNING id
                    """,
                    (cron_expression, action_type, json.dumps(payload), owner_user_id, next_run),
                )
                return str(cur.fetchone()[0])

    def update_run_times(self, scheduled_id: str, last_run: datetime | None, next_run: datetime | None) -> None:
        with connection_context() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE scheduled_actions SET last_run = %s, next_run = %s WHERE id = %s",
                    (last_run, next_run, scheduled_id),
                )

    def _row(self, raw: dict[str, Any]) -> ScheduledActionRow:
        payload = raw.get("payload")
        if isinstance(payload, str):
            payload = json.loads(payload)
        return ScheduledActionRow(
            id=str(raw["id"]),
            cron_expression=str(raw["cron_expression"]),
            action_type=str(raw["action_type"]),
            payload=payload if isinstance(payload, dict) else {},
            owner_user_id=str(raw["owner_user_id"]),
            enabled=bool(raw["enabled"]),
            last_run=raw.get("last_run"),
            next_run=raw.get("next_run"),
        )

