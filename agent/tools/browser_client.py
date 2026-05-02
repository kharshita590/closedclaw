from __future__ import annotations

import os
from typing import Any

import httpx

from permissions.registry import require_scope


class BrowserClient:
    def __init__(self, base_url: str | None = None) -> None:
        self.base_url = (base_url or os.getenv("BROWSER_SANDBOX_URL") or "http://browser-sandbox:8000").rstrip("/")
        self.api_key = os.getenv("BROWSER_SANDBOX_API_KEY") or os.getenv("AGENT_API_KEY") or os.getenv("AGENT_API_KEYS", "").split(",")[0].strip()

    @require_scope("browser:navigate")
    async def run(self, goal: str, start_url: str | None = None, steps: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post(
                f"{self.base_url}/run",
                headers=self._headers(),
                json={"goal": goal, "start_url": start_url, "steps": steps or []},
            )
            response.raise_for_status()
            return response.json()

    @require_scope("browser:navigate")
    async def submit_form(self, url: str, fields: dict[str, str], submit: bool = True) -> dict[str, Any]:
        """Fill a browser form and optionally submit it through the sandbox."""

        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post(
                f"{self.base_url}/submit-form",
                headers=self._headers(),
                json={"url": url, "fields": fields, "submit": submit},
            )
            response.raise_for_status()
            return response.json()

    def _headers(self) -> dict[str, str]:
        """Builds auth headers for calls into the browser sandbox."""

        return {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
