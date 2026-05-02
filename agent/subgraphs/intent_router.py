from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from llm.client import LLMClient, LLMDecision

RouteDomain = Literal["email", "calendar", "browser", "memory", "general"]


@dataclass(frozen=True)
class RouteDecision:
    """Hierarchical intent decision with a coarse domain and a fine intent."""

    domain: RouteDomain
    intent: str = "general"
    confidence: float = 0.0
    query: str | None = None
    start_url: str | None = None
    response: str | None = None


class HierarchicalIntentRouter:
    """Two-stage intent router for the supervisor.

    The router first decides the broad domain, then resolves a narrower intent
    within that domain. Rules take priority; the LLM is only used as a fallback
    when the rules are ambiguous.
    """

    def __init__(self, llm: LLMClient | None = None) -> None:
        self.llm = llm or LLMClient()

    async def route(self, message: str, context: dict[str, Any] | None = None) -> RouteDecision:
        text = message.strip()
        coarse = self._rule_domain(text)
        if coarse == "general":
            llm_decision = await self._llm_decision(text, context)
            mapped = self._map_llm_decision(llm_decision)
            if mapped.domain != "general":
                return mapped
            return mapped

        fine = self._route_domain_intent(coarse, text)
        if fine.intent != "general":
            return fine

        if self.llm.enabled():
            llm_decision = await self._llm_decision(text, context)
            mapped = self._map_llm_decision(llm_decision)
            if mapped.domain == coarse and mapped.intent != "general":
                return mapped

        return fine

    def _rule_domain(self, text: str) -> RouteDomain:
        lowered = text.lower()
        if lowered.startswith("remember ") or lowered.startswith("search memory "):
            return "memory"
        if self._has_email_signal(lowered):
            return "email"
        if self._has_calendar_signal(lowered):
            return "calendar"
        if self._has_browser_signal(text):
            return "browser"
        return "general"

    def _route_domain_intent(self, domain: RouteDomain, text: str) -> RouteDecision:
        lowered = text.lower()
        if domain == "email":
            return self._route_email(text, lowered)
        if domain == "calendar":
            return RouteDecision(domain="calendar", intent="calendar", confidence=0.7)
        if domain == "browser":
            return RouteDecision(domain="browser", intent="browser", confidence=0.7, start_url=self._first_url(text))
        if domain == "memory":
            return self._route_memory(text, lowered)
        return RouteDecision(domain="general", intent="general", confidence=0.0)

    def _route_email(self, text: str, lowered: str) -> RouteDecision:
        if self._has_draft_email_signal(lowered):
            return RouteDecision(domain="email", intent="draft_email", confidence=0.8)
        if "delete email" in lowered or "clear spam" in lowered:
            return RouteDecision(domain="email", intent="destructive_email", confidence=0.8)
        if any(word in lowered for word in ["latest email", "last email", "recent email", "newest email"]):
            return RouteDecision(domain="email", intent="latest_email", confidence=0.8)
        if any(word in lowered for word in ["summarize email", "summarise email", "inbox", "email", "emails", "mail"]):
            return RouteDecision(domain="email", intent="summarize_email", confidence=0.7)
        return RouteDecision(domain="email", intent="general", confidence=0.3)

    def _route_memory(self, text: str, lowered: str) -> RouteDecision:
        if lowered.startswith("remember "):
            return RouteDecision(domain="memory", intent="remember", confidence=0.8, query=text.removeprefix("remember ").strip())
        if lowered.startswith("search memory "):
            return RouteDecision(domain="memory", intent="search_memory", confidence=0.8, query=text.removeprefix("search memory ").strip())
        return RouteDecision(domain="memory", intent="general", confidence=0.3)

    def _has_email_signal(self, lowered: str) -> bool:
        return self._has_draft_email_signal(lowered) or any(
            word in lowered
            for word in [
                "delete email",
                "clear spam",
                "latest email",
                "last email",
                "recent email",
                "newest email",
                "summarize email",
                "summarise email",
                "inbox",
                "mail",
                "email",
                "emails",
            ]
        )

    def _has_draft_email_signal(self, lowered: str) -> bool:
        return bool(
            self._draft_email_pattern(lowered)
            or "reply to" in lowered
            or "send email" in lowered
            or "send a email" in lowered
            or "send an email" in lowered
            or "compose email" in lowered
            or "compose a email" in lowered
            or "compose an email" in lowered
        )

    def _draft_email_pattern(self, lowered: str) -> bool:
        import re

        return bool(re.search(r"\b(send|draft|compose)\s+(?:a\s+|an\s+)?(?:email|mail)\b", lowered))

    def _has_calendar_signal(self, lowered: str) -> bool:
        return any(word in lowered for word in ["calendar", "meeting", "schedule", "free slot", "reschedule"])

    def _has_browser_signal(self, text: str) -> bool:
        lowered = text.lower()
        return bool(
            any(word in lowered for word in ["browse", "website", "compare", "price", "research", "scrape", "flight", "book", "open", "go to", "fill", "form"])
            or self._first_url(text)
        )

    async def _llm_decision(self, message: str, context: dict[str, Any] | None = None) -> LLMDecision:
        if not self.llm.enabled():
            return LLMDecision()
        return await self.llm.decide(message, context or {})

    def _map_llm_decision(self, decision: LLMDecision) -> RouteDecision:
        intent_to_domain = {
            "latest_email": "email",
            "summarize_email": "email",
            "draft_email": "email",
            "destructive_email": "email",
            "calendar": "calendar",
            "browser": "browser",
            "remember": "memory",
            "search_memory": "memory",
            "general": "general",
        }
        domain = intent_to_domain.get(decision.intent, "general")
        return RouteDecision(
            domain=domain,
            intent=decision.intent,
            confidence=decision.confidence,
            query=decision.query,
            start_url=decision.start_url,
            response=decision.response,
        )

    def _first_url(self, text: str) -> str | None:
        import re

        match = re.search(r"https?://\S+", text)
        return match.group(0) if match else None
