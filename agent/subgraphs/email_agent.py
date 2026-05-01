from __future__ import annotations

from tools.email_tools import EmailTools


class EmailAgent:
    def __init__(self) -> None:
        self.tools = EmailTools()

    def latest_email(self) -> str:
        messages = self.tools.list_messages(query="in:inbox", limit=1)
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

    def summarize_inbox(self, query: str = "in:inbox newer_than:7d") -> str:
        messages = self.tools.list_messages(query=query, limit=10)
        if not messages:
            return "No matching emails found."
        lines = ["Recent matching emails:"]
        for msg in messages:
            lines.append(f"- {msg['subject']} from {msg.get('from')}: {msg.get('snippet')}")
        return "\n".join(lines)
