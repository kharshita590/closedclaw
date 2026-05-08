from __future__ import annotations

from tools.browser_client import BrowserClient, WEB_UNTRUSTED_HEADER, sanitize_browser_text


class ResearchAgent:
    def __init__(self) -> None:
        self.browser = BrowserClient()

    async def research(self, goal: str, start_url: str | None = None) -> dict:
        result = await self.browser.run(goal=goal, start_url=start_url)
        summary = result.get("summary")
        if isinstance(summary, str) and summary:
            summary = sanitize_browser_text(summary)
            if not summary.startswith(WEB_UNTRUSTED_HEADER):
                summary = f"{WEB_UNTRUSTED_HEADER}{summary}"
            result["summary"] = summary
        return result
