from __future__ import annotations

import re

from actions.models import BrowserNavigateAction, ClearSpamAction, DeleteEmailAction, SendEmailAction
from approvals.ledger import ApprovalLedger
from audit.logger import AuditLogger
from graph.state import ChatRequest, ChatResponse, PendingAction
from llm.client import LLMClient
from policy.policy_engine import PolicyEngine
from subgraphs.intent_router import HierarchicalIntentRouter, RouteDecision
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
        self.router = HierarchicalIntentRouter(self.llm)
        self.approvals = ApprovalLedger()
        self.policy = PolicyEngine(self.approvals)

    async def handle(self, request: ChatRequest) -> ChatResponse:
        text = request.message.strip()
        self.audit.event("message_received", channel=request.channel, user_id=request.user_id, message=text)
        self.memory.remember(request.channel, request.user_id, "conversation", text, request.metadata)

        decision = await self.router.route(
            request.message,
            {"channel": request.channel, "user_id": request.user_id, "metadata": request.metadata},
        )
        self.audit.decision(
            provider=self.llm.provider,
            domain=decision.domain,
            intent=decision.intent,
            confidence=decision.confidence,
            user_id=request.user_id,
            channel=request.channel,
        )
        return await self._execute_route(request, decision)

    async def _execute_route(self, request: ChatRequest, decision: RouteDecision) -> ChatResponse:
        text = request.message.strip()
        if decision.domain == "email" and decision.intent == "draft_email":
            return self._send_email_action(request)
        if decision.domain == "email" and decision.intent == "destructive_email":
            return self._destructive_email_action(request)
        if decision.domain == "email" and decision.intent == "latest_email":
            try:
                return ChatResponse(response=await self.email.latest_email())
            except Exception as exc:
                return ChatResponse(response=f"Email is not ready: {exc}")
        if decision.domain == "email" and decision.intent == "summarize_email":
            try:
                return ChatResponse(response=await self.email.summarize_inbox())
            except Exception as exc:
                return ChatResponse(response=f"Email is not ready: {exc}")
        if decision.domain == "calendar":
            return await self._calendar_response(request)
        if decision.domain == "browser":
            try:
                action = BrowserNavigateAction(goal=text, url=decision.start_url or self._first_url(text))
                policy = self.policy.check(action)
                if not policy.allowed:
                    self.approvals.create(action, request.user_id, status="rejected", result={"reason": policy.reason})
                    return ChatResponse(response=f"Browser action rejected by policy: {policy.reason}")
                result = await self.research_agent.research(action.goal, action.url)
                return ChatResponse(response=result.get("summary", "Browser task completed."), data={"browser": result})
            except Exception as exc:
                return ChatResponse(response=f"Browser automation failed: {exc}")
        if decision.domain == "memory" and decision.intent == "remember":
            content = decision.query or re.sub(r"^remember\s+", "", text, flags=re.IGNORECASE).strip()
            memory_id = self.memory.remember(request.channel, request.user_id, "note", content)
            return ChatResponse(response=f"Saved memory #{memory_id}.")
        if decision.domain == "memory" and decision.intent == "search_memory":
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

    def _send_email_action(self, request: ChatRequest) -> ChatResponse:
        try:
            action_plan = self._parse_send_email(request.message)
        except ValueError as exc:
            return ChatResponse(response=f"I need a safer email format before creating an approval: {exc}")
        policy = self.policy.check(action_plan)
        if not policy.allowed:
            self.approvals.create(action_plan, request.user_id, status="rejected", result={"reason": policy.reason})
            return ChatResponse(response=f"Email action rejected by policy: {policy.reason}")
        action = self.approvals.create(action_plan, request.user_id)
        return ChatResponse(response="I prepared an email action for approval.", actions=[action])

    def _destructive_email_action(self, request: ChatRequest) -> ChatResponse:
        lowered = request.message.lower()
        if "clear spam" in lowered:
            action_plan = ClearSpamAction()
        else:
            match = re.search(r"(?:message|email)\s+id\s+([A-Za-z0-9_-]+)", request.message)
            if not match:
                return ChatResponse(response="To delete mail safely, include the exact message id, for example: delete email id abc123.")
            action_plan = DeleteEmailAction(message_id=match.group(1))
        policy = self.policy.check(action_plan)
        if not policy.allowed:
            self.approvals.create(action_plan, request.user_id, status="rejected", result={"reason": policy.reason})
            return ChatResponse(response=f"Email cleanup rejected by policy: {policy.reason}")
        action = self.approvals.create(action_plan, request.user_id)
        return ChatResponse(response="This email cleanup needs approval before I run it.", actions=[action])

    async def _calendar_response(self, request: ChatRequest) -> ChatResponse:
        """Return upcoming calendar events through the async CalendarTools wrapper."""

        try:
            events = await self.calendar.upcoming_events()
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

    def _parse_send_email(self, text: str) -> SendEmailAction:
        """Builds a typed SendEmailAction from a constrained natural-language format."""

        recipient_match = re.search(r"\bto\s+([^\s,;]+@[^\s,;]+)", text, flags=re.IGNORECASE)
        if not recipient_match:
            raise ValueError("include a recipient like 'to name@example.com'")
        subject_match = re.search(r"\bsubject\s*:?\s+(.+?)(?:\s+(?:body|message)\s*:?\s+|$)", text, flags=re.IGNORECASE)
        body_match = re.search(r"\b(?:body|message)\s*:?\s+(.+)$", text, flags=re.IGNORECASE)
        subject = subject_match.group(1).strip(" :\"'") if subject_match else "No subject"
        body = body_match.group(1).strip(" :\"'") if body_match else ""
        if not body:
            raise ValueError("include a body like 'body hello, following up...'")
        return SendEmailAction(recipient=recipient_match.group(1), subject=subject, body=body)
