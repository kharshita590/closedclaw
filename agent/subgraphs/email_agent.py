from __future__ import annotations

from typing import Any

from tools.email_tools import EmailTools


class EmailAgent:
    """Specialized email helper used by the supervisor."""

    def __init__(self) -> None:
        """Initialize Gmail tools."""

        self.tools = EmailTools()

    async def get_latest_raw(self, sender: str | None = None) -> dict[str, Any]:
        """Return structured data for the newest inbox email.

        Args:
            sender: Optional Gmail sender filter to narrow the inbox lookup.

        Returns:
            A dictionary with from_address, subject, body, thread_id, date, and
            message_id keys so downstream supervisor steps can use email context.
        """

        query = "in:inbox"
        if sender:
            query = f"{query} from:{sender}"
        messages = await self.tools.list_messages(query=query, limit=1)
        if not messages:
            return {}
        metadata = messages[0]
        message_id = metadata.get("id")
        msg = await self.tools.get_message(message_id, metadata_only=False) if message_id else metadata
        return {
            "from_address": msg.get("from"),
            "subject": msg.get("subject"),
            "body": msg.get("body") or msg.get("snippet") or "",
            "thread_id": msg.get("thread_id"),
            "date": msg.get("date"),
            "message_id": msg.get("id") or message_id,
        }

    async def latest_email(self) -> str:
        """Return a short summary of the newest inbox email."""

        msg = await self.get_latest_raw()
        if not msg:
            return "No inbox emails found."
        return (
            "Latest inbox email:\n"
            f"From: {msg.get('from_address')}\n"
            f"Subject: {msg.get('subject')}\n"
            f"Date: {msg.get('date')}\n"
            f"Preview: {msg.get('body')}"
        )

    async def summarize_inbox(self, query: str = "in:inbox newer_than:7d") -> str:
        """Return a compact summary of recent matching inbox messages."""

        messages = await self.tools.list_messages(query=query, limit=10)
        if not messages:
            return "No matching emails found."
        lines = ["Recent matching emails:"]
        for msg in messages:
            lines.append(f"- {msg['subject']} from {msg.get('from')}: {msg.get('snippet')}")
        return "\n".join(lines)
