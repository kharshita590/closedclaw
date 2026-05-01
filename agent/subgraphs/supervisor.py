from __future__ import annotations

import re
import uuid

from audit.logger import AuditLogger
from graph.state import ChatRequest, ChatResponse, PendingAction
from llm.client import LLMClient, LLMDecision
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
        self.llm = LLMClient()

    async def handle(self, request: ChatRequest) -> ChatResponse:
        text = request.message.strip()
        self.audit.event("message_received", channel=request.channel, user_id=request.user_id, message=text)
        self.memory.remember(request.channel, request.user_id, "conversation", text, request.metadata)

        decision = await self._decide(request)
        self.audit.decision(
            provider=self.llm.provider,
            intent=decision.intent,
            confidence=decision.confidence,
            user_id=request.user_id,
            channel=request.channel,
        )
        return await self._execute_decision(request, decision)

    async def _decide(self, request: ChatRequest) -> LLMDecision:
        if self.llm.enabled():
            try:
                decision = await self.llm.decide(
                    request.message,
                    {"channel": request.channel, "user_id": request.user_id, "metadata": request.metadata},
                )
                if decision.confidence >= 0.45 or decision.intent != "general":
                    return decision
            except Exception as exc:
                self.audit.event("llm_router_failed", provider=self.llm.provider, error=str(exc))
        return self._rule_decision(request.message)

    async def _execute_decision(self, request: ChatRequest, decision: LLMDecision) -> ChatResponse:
        text = request.message.strip()
        if decision.intent == "draft_email":
            return self._draft_email_action(request)
        if decision.intent == "destructive_email":
            return self._destructive_email_action(request)
        if decision.intent == "latest_email":
            try:
                return ChatResponse(response=self.email.latest_email())
            except Exception as exc:
                return ChatResponse(response=f"Email is not ready: {exc}")
        if decision.intent == "summarize_email":
            try:
                return ChatResponse(response=self.email.summarize_inbox())
            except Exception as exc:
                return ChatResponse(response=f"Email is not ready: {exc}")
        if decision.intent == "calendar":
            return self._calendar_response(request)
        if decision.intent == "browser":
            try:
                result = await self.research_agent.research(text, decision.start_url or self._first_url(text))
                return ChatResponse(response=result.get("summary", "Browser task completed."), data={"browser": result})
            except Exception as exc:
                return ChatResponse(response=f"Browser automation failed: {exc}")
        if decision.intent == "remember":
            content = decision.query or re.sub(r"^remember\s+", "", text, flags=re.IGNORECASE).strip()
            memory_id = self.memory.remember(request.channel, request.user_id, "note", content)
            return ChatResponse(response=f"Saved memory #{memory_id}.")
        if decision.intent == "search_memory":
            query = decision.query or re.sub(r"^search memory\s+", "", text, flags=re.IGNORECASE).strip()
            hits = self.memory.search(request.user_id, query)
            if not hits:
                return ChatResponse(response="No matching memory found.")
            return ChatResponse(response="\n".join(f"- {hit['content']}" for hit in hits), data={"memories": hits})

        if self.llm.enabled():
            try:
                answer = decision.response or await self.llm.general_response(text)
                if answer:
                    return ChatResponse(response=answer)
            except Exception as exc:
                self.audit.event("llm_general_failed", provider=self.llm.provider, error=str(exc))
        return ChatResponse(
            response=(
                "I can manage email, calendar, browser research, memory/CRM notes, and group-chat summaries. "
                "For risky actions like sending mail, deleting mail, or booking purchases, I will create an approval first."
            )
        )

    def _rule_decision(self, text: str) -> LLMDecision:
        lowered = text.lower()
        if any(word in lowered for word in ["send email", "reply to", "draft email"]):
            return LLMDecision(intent="draft_email", confidence=0.8)
        if "delete email" in lowered or "clear spam" in lowered:
            return LLMDecision(intent="destructive_email", confidence=0.8)
        if any(word in lowered for word in ["latest email", "last email", "recent email", "newest email"]):
            return LLMDecision(intent="latest_email", confidence=0.8)
        if any(word in lowered for word in ["summarize email", "summarise email", "inbox", "email", "emails", "mail"]):
            return LLMDecision(intent="summarize_email", confidence=0.7)
        if any(word in lowered for word in ["calendar", "meeting", "schedule", "free slot", "reschedule"]):
            return LLMDecision(intent="calendar", confidence=0.7)
        if any(word in lowered for word in ["browse", "website", "compare", "price", "research", "scrape", "flight", "book"]):
            return LLMDecision(intent="browser", confidence=0.7, start_url=self._first_url(text))
        if lowered.startswith("remember "):
            return LLMDecision(intent="remember", confidence=0.8, query=text.removeprefix("remember ").strip())
        if lowered.startswith("search memory "):
            return LLMDecision(intent="search_memory", confidence=0.8, query=text.removeprefix("search memory ").strip())
        return LLMDecision(intent="general", confidence=0.0)

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
