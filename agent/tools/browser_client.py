from __future__ import annotations

import os
from typing import Any

import httpx


class BrowserClient:
    def __init__(self, base_url: str | None = None) -> None:
        self.base_url = (base_url or os.getenv("BROWSER_SANDBOX_URL") or "http://browser-sandbox:8000").rstrip("/")

    async def run(self, goal: str, start_url: str | None = None, steps: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post(
                f"{self.base_url}/run",
                json={"goal": goal, "start_url": start_url, "steps": steps or []},
            )
            response.raise_for_status()
            return response.json()
