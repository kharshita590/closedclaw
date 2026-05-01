from __future__ import annotations

import random
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


class ChannelPolicy:
    """Loads and updates the per-channel sender allowlist used by bridges."""

    def __init__(self, path: str | Path = "channel_policy.yaml") -> None:
        """Initializes the channel policy file if it does not exist."""

        self.path = Path(path)
        if not self.path.exists():
            self.path.write_text(json.dumps(self._empty_policy(), indent=2), encoding="utf-8")

    def is_allowed(self, channel: str, sender_id: str) -> bool:
        """Returns whether a sender can forward messages to the agent."""

        return sender_id in self._allowed(channel)

    def add_sender(self, channel: str, sender_id: str) -> None:
        """Adds a sender id to the allowlist if it is not already present."""

        data = self._load()
        channel_data = data.setdefault("channels", {}).setdefault(channel, {})
        allowed = channel_data.setdefault("allowed_senders", [])
        if sender_id not in allowed:
            allowed.append(sender_id)
        self.path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")

    def _allowed(self, channel: str) -> list[str]:
        """Reads the allowlist for one channel from policy YAML."""

        data = self._load()
        return [str(item) for item in data.get("channels", {}).get(channel, {}).get("allowed_senders", [])]

    def _load(self) -> dict[str, Any]:
        """Loads JSON-formatted YAML policy as a dictionary."""

        loaded = json.loads(self.path.read_text(encoding="utf-8") or "{}")
        return loaded if isinstance(loaded, dict) else {}

    def _empty_policy(self) -> dict[str, Any]:
        """Builds the default channel policy document."""

        return {
            "channels": {
                "slack": {"allowed_senders": []},
                "telegram": {"allowed_senders": []},
                "whatsapp": {"allowed_senders": []},
            }
        }


class PairingStore:
    """Stores short-lived one-time pairing codes in SQLite."""

    def __init__(self, db_path: str | Path = "memory/pairing_requests.db", ttl_seconds: int = 600) -> None:
        """Opens the pairing database and creates the pairing table."""

        self.db_path = Path(db_path)
        self.ttl_seconds = ttl_seconds
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        """Creates the pairing_requests table used by all bridges."""

        with sqlite3.connect(self.db_path) as con:
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS pairing_requests (
                    channel TEXT NOT NULL,
                    sender_id TEXT NOT NULL,
                    code TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY(channel, sender_id)
                )
                """
            )

    def create_code(self, channel: str, sender_id: str) -> str:
        """Creates and persists a new six-digit pairing code."""

        code = f"{random.SystemRandom().randint(0, 999999):06d}"
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=self.ttl_seconds)
        with sqlite3.connect(self.db_path) as con:
            con.execute(
                """
                INSERT INTO pairing_requests(channel, sender_id, code, expires_at, attempts)
                VALUES (?, ?, ?, ?, 0)
                ON CONFLICT(channel, sender_id) DO UPDATE
                SET code = excluded.code, expires_at = excluded.expires_at, attempts = 0
                """,
                (channel, sender_id, code, expires_at.isoformat()),
            )
        return code

    def verify_code(self, channel: str, sender_id: str, code: str) -> tuple[bool, str]:
        """Verifies a code and deletes it on success or expiry."""

        with sqlite3.connect(self.db_path) as con:
            con.row_factory = sqlite3.Row
            row = con.execute(
                "SELECT * FROM pairing_requests WHERE channel = ? AND sender_id = ?",
                (channel, sender_id),
            ).fetchone()
            if not row:
                return False, "No pairing request found"
            expires_at = datetime.fromisoformat(row["expires_at"])
            if expires_at < datetime.now(timezone.utc):
                con.execute("DELETE FROM pairing_requests WHERE channel = ? AND sender_id = ?", (channel, sender_id))
                return False, "Pairing code expired"
            con.execute(
                "UPDATE pairing_requests SET attempts = attempts + 1 WHERE channel = ? AND sender_id = ?",
                (channel, sender_id),
            )
            if str(row["code"]) != code.strip():
                return False, "Incorrect pairing code"
            con.execute("DELETE FROM pairing_requests WHERE channel = ? AND sender_id = ?", (channel, sender_id))
        return True, "paired"
