from __future__ import annotations

from tools.email_tools import EmailTools


class EmailAgent:
    """Specialized email helper used by the supervisor."""

    def __init__(self) -> None:
        """Initialize Gmail tools."""

        self.tools = EmailTools()

    async def latest_email(self) -> str:
        """Return a short summary of the newest inbox email."""

        messages = await self.tools.list_messages(query="in:inbox", limit=1)
        if not messages:
            return "No inbox emails found."
        msg = messages[0]
        return (
            "Latest inbox email:\n"
            f"From: {msg.get('from')}\n"
            f"Subject: {msg.get('subject')}\n"
            f"Date: {msg.get('date')}\n"
            f"Preview: {msg.get('snippet')}"
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
