from __future__ import annotations

import json
import os
from typing import Any, Literal

import httpx
from dotenv import load_dotenv
from pydantic import BaseModel, Field

load_dotenv()

Intent = Literal[
    "latest_email",
    "summarize_email",
    "draft_email",
    "destructive_email",
    "calendar",
    "browser",
    "remember",
    "search_memory",
    "general",
]


class LLMDecision(BaseModel):
    intent: Intent = "general"
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    response: str | None = None
    query: str | None = None
    start_url: str | None = None


class LLMClient:
    def __init__(self) -> None:
        self.provider = os.getenv("LLM_PROVIDER", "none").strip().lower()
        self.model = os.getenv("LLM_MODEL", self._default_model())
        self.api_key = os.getenv("LLM_API_KEY", "")
        self.api_base_url = os.getenv("LLM_API_BASE_URL", "https://api.openai.com/v1").rstrip("/")
        self.ollama_base_url = os.getenv("OLLAMA_BASE_URL", "http://host.docker.internal:11434").rstrip("/")

    def enabled(self) -> bool:
        if self.provider == "ollama":
            return bool(self.model)
        if self.provider in {"api", "openai", "openai-compatible"}:
            return bool(self.model and self.api_key)
        return False

    async def decide(self, message: str, context: dict[str, Any] | None = None) -> LLMDecision:
        if not self.enabled():
            return LLMDecision()
        prompt = self._router_prompt(message, context or {})
        raw = await self._complete(prompt, temperature=0.0)
        return self._parse_decision(raw)

    async def general_response(self, message: str, context: dict[str, Any] | None = None) -> str:
        if not self.enabled():
            return ""
        prompt = (
            "You are a concise personal productivity and coding agent. "
            "Answer directly. If the user asks you to perform email, calendar, browser, memory, "
            "or destructive actions, say what you would do and mention that tool execution requires routing.\n\n"
            f"Context: {json.dumps(context or {}, default=str)}\n"
            f"User: {message}"
        )
        return await self._complete(prompt, temperature=0.3)

    async def _complete(self, prompt: str, temperature: float) -> str:
        if self.provider == "ollama":
            return await self._ollama_complete(prompt, temperature)
        return await self._api_complete(prompt, temperature)

    async def _api_complete(self, prompt: str, temperature: float) -> str:
        headers = {"authorization": f"Bearer {self.api_key}", "content-type": "application/json"}
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature,
        }
        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post(f"{self.api_base_url}/chat/completions", headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()
        return data["choices"][0]["message"]["content"]

    async def _ollama_complete(self, prompt: str, temperature: float) -> str:
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "options": {"temperature": temperature},
        }
        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post(f"{self.ollama_base_url}/api/chat", json=payload)
            response.raise_for_status()
            data = response.json()
        return data.get("message", {}).get("content", "")

    def _router_prompt(self, message: str, context: dict[str, Any]) -> str:
        return f"""
Classify this user request for a personal agent. Return only valid JSON.

Allowed intents:
- latest_email: user asks for newest/latest/recent email.
- summarize_email: user asks to read, summarize, search, or inspect inbox/email/mail.
- draft_email: user asks to send, reply, compose, or draft email.
- destructive_email: user asks to delete email, clear spam, archive/delete messages.
- calendar: user asks about meetings, calendar, scheduling, free slots, reminders.
- browser: user asks to browse, research web, compare prices, scrape, check flight, book, fill web forms.
- remember: user asks to save a note/contact/fact to memory or CRM.
- search_memory: user asks to search/recall memory/CRM.
- general: anything else.

JSON shape:
{{
  "intent": "one_allowed_intent",
  "confidence": 0.0,
  "response": "optional direct response for general intent",
  "query": "optional cleaned search/memory/email query",
  "start_url": "optional first URL if present"
}}

Context: {json.dumps(context, default=str)}
User request: {message}
""".strip()

    def _parse_decision(self, raw: str) -> LLMDecision:
        try:
            start = raw.index("{")
            end = raw.rindex("}") + 1
            return LLMDecision.model_validate_json(raw[start:end])
        except Exception:
            return LLMDecision(intent="general", confidence=0.0, response=raw.strip() or None)

    def _default_model(self) -> str:
        provider = os.getenv("LLM_PROVIDER", "none").strip().lower()
        if provider == "ollama":
            return "llama3.1"
        return "gpt-4o-mini"
