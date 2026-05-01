from __future__ import annotations

import re
import uuid

from audit.logger import AuditLogger
from graph.state import ChatRequest, ChatResponse, PendingAction
from subgraphs.email_agent import EmailAgent
from subgraphs.research_agent import ResearchAgent
from tools.calendar_tools import CalendarTools
from tools.memory_tools import MemoryStore


class SupervisorAgent:
    def __init__(self) -> None:
        self.audit = AuditLogger()
        self.memory = MemoryStore()
        self.email = EmailAgent()
        self.calendar = CalendarTools()
        self.research_agent = ResearchAgent()

    async def handle(self, request: ChatRequest) -> ChatResponse:
        text = request.message.strip()
        lowered = text.lower()
        self.audit.event("message_received", channel=request.channel, user_id=request.user_id, message=text)
        self.memory.remember(request.channel, request.user_id, "conversation", text, request.metadata)

        if any(word in lowered for word in ["send email", "reply to", "draft email"]):
            return self._draft_email_action(request)
        if "delete email" in lowered or "clear spam" in lowered:
            return self._destructive_email_action(request)
        if any(word in lowered for word in ["latest email", "last email", "recent email", "newest email"]):
            try:
                return ChatResponse(response=self.email.latest_email())
            except Exception as exc:
                return ChatResponse(response=f"Email is not ready: {exc}")
        if any(word in lowered for word in ["summarize email", "summarise email", "inbox", "email", "emails", "mail"]):
            try:
                return ChatResponse(response=self.email.summarize_inbox())
            except Exception as exc:
                return ChatResponse(response=f"Email is not ready: {exc}")
        if any(word in lowered for word in ["calendar", "meeting", "schedule", "free slot", "reschedule"]):
            return self._calendar_response(request)
        if any(word in lowered for word in ["browse", "website", "compare", "price", "research", "scrape", "flight", "book"]):
            try:
                result = await self.research_agent.research(text, self._first_url(text))
                return ChatResponse(response=result.get("summary", "Browser task completed."), data={"browser": result})
            except Exception as exc:
                return ChatResponse(response=f"Browser automation failed: {exc}")
        if lowered.startswith("remember "):
            content = text.removeprefix("remember ").strip()
            memory_id = self.memory.remember(request.channel, request.user_id, "note", content)
            return ChatResponse(response=f"Saved memory #{memory_id}.")
        if lowered.startswith("search memory "):
            query = text.removeprefix("search memory ").strip()
            hits = self.memory.search(request.user_id, query)
            if not hits:
                return ChatResponse(response="No matching memory found.")
            return ChatResponse(response="\n".join(f"- {hit['content']}" for hit in hits), data={"memories": hits})

        return ChatResponse(
            response=(
                "I can manage email, calendar, browser research, memory/CRM notes, and group-chat summaries. "
                "For risky actions like sending mail, deleting mail, or booking purchases, I will create an approval first."
            )
        )

    def _draft_email_action(self, request: ChatRequest) -> ChatResponse:
        action = PendingAction(
            id=str(uuid.uuid4()),
            action_type="email.send_or_draft",
            summary="Review the email draft before it is created or sent.",
            payload={"instruction": request.message, "mode": "draft_first"},
            channel=request.channel,
            user_id=request.user_id,
        )
        return ChatResponse(response="I prepared an email action for approval.", actions=[action])

    def _destructive_email_action(self, request: ChatRequest) -> ChatResponse:
        action = PendingAction(
            id=str(uuid.uuid4()),
            action_type="email.destructive",
            summary="This may delete or permanently remove email. Approval required.",
            payload={"instruction": request.message},
            channel=request.channel,
            user_id=request.user_id,
        )
        return ChatResponse(response="This email cleanup needs approval before I run it.", actions=[action])

    def _calendar_response(self, request: ChatRequest) -> ChatResponse:
        try:
            events = self.calendar.upcoming_events()
            if not events:
                return ChatResponse(response="No upcoming calendar events found.")
            lines = ["Upcoming calendar events:"]
            for event in events[:10]:
                start = event.get("start", {}).get("dateTime") or event.get("start", {}).get("date")
                lines.append(f"- {start}: {event.get('summary', '(no title)')}")
            return ChatResponse(response="\n".join(lines), data={"events": events})
        except Exception as exc:
            return ChatResponse(response=f"Calendar is not ready: {exc}")

    def _first_url(self, text: str) -> str | None:
        match = re.search(r"https?://\S+", text)
        return match.group(0) if match else None
