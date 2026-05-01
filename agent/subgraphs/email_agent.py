from __future__ import annotations

from tools.email_tools import EmailTools


class EmailAgent:
    def __init__(self) -> None:
        self.tools = EmailTools()

    def summarize_inbox(self, query: str = "in:inbox newer_than:7d") -> str:
        messages = self.tools.list_messages(query=query, limit=10)
        if not messages:
            return "No matching emails found."
        lines = ["Recent matching emails:"]
        for msg in messages:
            lines.append(f"- {msg['subject']} from {msg.get('from')}: {msg.get('snippet')}")
        return "\n".join(lines)
