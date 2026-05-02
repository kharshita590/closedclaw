"""PostgreSQL channel allowlist and pairing storage for bridge processes.

Bridges use this module before forwarding any channel message to the agent. It
keeps allowed sender IDs and short-lived pairing codes in PostgreSQL so multiple
bridge processes share one consistent security state.
"""

from __future__ import annotations

import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

for candidate in (Path(__file__).resolve().parents[1] / "agent", Path("/app/agent")):
    if candidate.exists():
        sys.path.insert(0, str(candidate))

from db.connection import connection_context  # noqa: E402


class ChannelPolicy:
    """PostgreSQL-backed per-channel sender allowlist."""

    def __init__(self, path: str | Path = "channel_policy.yaml") -> None:
        """Create the channel_policy table.

        Args:
            path: Kept for backward compatibility with the former YAML
                constructor. It is ignored because PostgreSQL is authoritative.
        """

        self.path = path
        self._init_db()

    def _init_db(self) -> None:
        """Create the channel allowlist table if it does not exist."""

        with connection_context() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS channel_policy (
                        channel TEXT NOT NULL,
                        sender_id TEXT NOT NULL,
                        added_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                        PRIMARY KEY(channel, sender_id)
                    )
                    """
                )

    def is_allowed(self, channel: str, sender_id: str) -> bool:
        """Return whether a sender is allowed to use one channel.

        Args:
            channel: Channel name such as slack, telegram, or whatsapp.
            sender_id: Platform sender id.

        Returns:
            True if the sender exists in the allowlist.
        """

        with connection_context() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM channel_policy WHERE channel = %s AND sender_id = %s",
                    (channel, str(sender_id)),
                )
                return cur.fetchone() is not None

    def add_sender(self, channel: str, sender_id: str) -> None:
        """Add a sender to the PostgreSQL allowlist.

        Args:
            channel: Channel name.
            sender_id: Sender id to allow.
        """

        with connection_context() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO channel_policy(channel, sender_id, added_at)
                    VALUES (%s, %s, now())
                    ON CONFLICT(channel, sender_id) DO NOTHING
                    """,
                    (channel, str(sender_id)),
                )


class PairingStore:
    """Stores short-lived one-time pairing codes in PostgreSQL."""

    def __init__(self, db_path: str | Path = "memory/pairing_requests.db", ttl_seconds: int = 600) -> None:
        """Create the pairing table.

        Args:
            db_path: Kept for backward compatibility with the former SQLite
                constructor. It is ignored because PostgreSQL is authoritative.
            ttl_seconds: Number of seconds a generated code remains valid.
        """

        self.db_path = db_path
        self.ttl_seconds = ttl_seconds
        self._init_db()

    def _init_db(self) -> None:
        """Create the pairing_requests table if it does not exist."""

        with connection_context() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS pairing_requests (
                        channel TEXT NOT NULL,
                        sender_id TEXT NOT NULL,
                        code TEXT NOT NULL,
                        expires_at TIMESTAMPTZ NOT NULL,
                        attempts INTEGER NOT NULL DEFAULT 0,
                        PRIMARY KEY(channel, sender_id)
                    )
                    """
                )

    def create_code(self, channel: str, sender_id: str) -> str:
        """Create and persist a new six-digit pairing code.

        Args:
            channel: Channel requesting pairing.
            sender_id: Sender that must prove possession of the channel.

        Returns:
            The generated six-digit pairing code.
        """

        code = f"{random.SystemRandom().randint(0, 999999):06d}"
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=self.ttl_seconds)
        with connection_context() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO pairing_requests(channel, sender_id, code, expires_at, attempts)
                    VALUES (%s, %s, %s, %s, 0)
                    ON CONFLICT(channel, sender_id) DO UPDATE
                    SET code = excluded.code, expires_at = excluded.expires_at, attempts = 0
                    """,
                    (channel, str(sender_id), code, expires_at),
                )
        return code

    def verify_code(self, channel: str, sender_id: str, code: str) -> tuple[bool, str]:
        """Verify a pairing code and enforce brute-force attempt limits.

        Args:
            channel: Channel name.
            sender_id: Sender id attempting to pair.
            code: Six-digit code supplied by the sender.

        Returns:
            A tuple of (success, reason).
        """

        with connection_context() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT code, expires_at, attempts FROM pairing_requests WHERE channel = %s AND sender_id = %s",
                    (channel, str(sender_id)),
                )
                row = cur.fetchone()
                if not row:
                    return False, "No pairing request found"
                stored_code, expires_at, attempts = row
                if attempts >= 5:
                    cur.execute("DELETE FROM pairing_requests WHERE channel = %s AND sender_id = %s", (channel, str(sender_id)))
                    return False, "Too many incorrect attempts. Request a new pairing code."
                if expires_at < datetime.now(timezone.utc):
                    cur.execute("DELETE FROM pairing_requests WHERE channel = %s AND sender_id = %s", (channel, str(sender_id)))
                    return False, "Pairing code expired"
                cur.execute(
                    "UPDATE pairing_requests SET attempts = attempts + 1 WHERE channel = %s AND sender_id = %s",
                    (channel, str(sender_id)),
                )
                if str(stored_code) != code.strip():
                    return False, "Incorrect pairing code"
                cur.execute("DELETE FROM pairing_requests WHERE channel = %s AND sender_id = %s", (channel, str(sender_id)))
        return True, "paired"
