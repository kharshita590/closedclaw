from __future__ import annotations

from typing import Dict

from db.connection import connection_context


class SkillStateStore:
    """PostgreSQL-backed enabled/disabled state for installed skills."""

    def __init__(self) -> None:
        self._memory: Dict[str, bool] = {}
        self._db_ready = self._init_db()

    def _init_db(self) -> bool:
        try:
            with connection_context() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        CREATE TABLE IF NOT EXISTS skill_state (
                            name TEXT PRIMARY KEY,
                            enabled BOOLEAN NOT NULL DEFAULT true,
                            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
                        )
                        """
                    )
            return True
        except Exception:
            # Local unit tests may not have PostgreSQL running; fall back to memory.
            return False

    def get_enabled(self, name: str) -> bool | None:
        if not self._db_ready:
            return self._memory.get(name)
        try:
            with connection_context() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT enabled FROM skill_state WHERE name = %s", (name,))
                    row = cur.fetchone()
                    return bool(row[0]) if row else None
        except Exception:
            return self._memory.get(name)

    def set_enabled(self, name: str, enabled: bool) -> None:
        if not self._db_ready:
            self._memory[name] = enabled
            return
        try:
            with connection_context() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO skill_state(name, enabled, updated_at)
                        VALUES (%s, %s, now())
                        ON CONFLICT(name) DO UPDATE SET enabled = excluded.enabled, updated_at = now()
                        """,
                        (name, enabled),
                    )
        except Exception:
            self._memory[name] = enabled

