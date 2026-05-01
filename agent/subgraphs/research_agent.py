from __future__ import annotations

from tools.browser_client import BrowserClient


class ResearchAgent:
    def __init__(self) -> None:
        self.browser = BrowserClient()

    async def research(self, goal: str, start_url: str | None = None) -> dict:
        return await self.browser.run(goal=goal, start_url=start_url)
