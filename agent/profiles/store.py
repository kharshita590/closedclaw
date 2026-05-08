from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from db.connection import connection_context


@dataclass(frozen=True)
class AgentProfile:
    id: str
    name: str
    system_prompt: str
    allowed_intents: list[str]
    assigned_channels: list[str]
    llm_provider: str
    llm_model: str


class AgentProfileStore:
    def __init__(self) -> None:
        self._init_db()

    def _init_db(self) -> None:
        with connection_context() as conn:
            with conn.cursor() as cur:
                cur.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS agent_profiles (
                        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                        name TEXT NOT NULL,
                        system_prompt TEXT NOT NULL,
                        allowed_intents JSONB NOT NULL DEFAULT '[]'::jsonb,
                        assigned_channels JSONB NOT NULL DEFAULT '[]'::jsonb,
                        llm_provider TEXT NOT NULL DEFAULT 'none',
                        llm_model TEXT NOT NULL DEFAULT ''
                    )
                    """
                )

    def find_for_sender(self, channel: str, sender_id: str) -> AgentProfile | None:
        key = f"{channel}:{sender_id}"
        with connection_context() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, name, system_prompt, allowed_intents, assigned_channels, llm_provider, llm_model
                    FROM agent_profiles
                    WHERE assigned_channels @> %s::jsonb
                    LIMIT 1
                    """,
                    (json.dumps([key]),),
                )
                row = cur.fetchone()
        if not row:
            return None
        return self._row(row)

    def _row(self, row: tuple[Any, ...]) -> AgentProfile:
        id_, name, system_prompt, allowed_intents, assigned_channels, llm_provider, llm_model = row
        if isinstance(allowed_intents, str):
            allowed_intents = json.loads(allowed_intents)
        if isinstance(assigned_channels, str):
            assigned_channels = json.loads(assigned_channels)
        return AgentProfile(
            id=str(id_),
            name=str(name),
            system_prompt=str(system_prompt),
            allowed_intents=list(allowed_intents) if isinstance(allowed_intents, list) else [],
            assigned_channels=list(assigned_channels) if isinstance(assigned_channels, list) else [],
            llm_provider=str(llm_provider),
            llm_model=str(llm_model),
        )

