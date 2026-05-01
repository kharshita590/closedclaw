from __future__ import annotations

import re
from typing import Any

from markdownify import markdownify as md
from playwright.async_api import async_playwright

from api.schemas import BrowserRunRequest, BrowserRunResponse
from browser.screenshot_utils import screenshot_path


class PlaywrightRunner:
    async def run(self, request: BrowserRunRequest) -> BrowserRunResponse:
        observations: list[dict[str, Any]] = []
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True, args=["--disable-dev-shm-usage", "--no-sandbox"])
            page = await browser.new_page(viewport={"width": 1365, "height": 900})
            try:
                start_url = request.start_url or self._url_from_goal(request.goal)
                if start_url:
                    await page.goto(start_url, wait_until="domcontentloaded", timeout=30000)
                    observations.append({"action": "goto", "url": start_url})

                for step in request.steps:
                    if step.action == "goto" and step.url:
                        await page.goto(step.url, wait_until="domcontentloaded", timeout=step.timeout_ms)
                    elif step.action == "click" and step.selector:
                        await page.click(step.selector, timeout=step.timeout_ms)
                    elif step.action == "fill" and step.selector is not None:
                        await page.fill(step.selector, step.value or "", timeout=step.timeout_ms)
                    elif step.action == "press" and step.selector and step.value:
                        await page.press(step.selector, step.value, timeout=step.timeout_ms)
                    elif step.action == "wait":
                        await page.wait_for_timeout(step.timeout_ms)
                    elif step.action == "extract":
                        observations.append({"action": "extract", "text": await page.locator("body").inner_text(timeout=step.timeout_ms)})
                    observations.append(step.model_dump())

                html = await page.content()
                text = md(html)
                shot = screenshot_path()
                await page.screenshot(path=str(shot), full_page=True)
                title = await page.title()
                url = page.url
                return BrowserRunResponse(
                    summary=self._summarize(request.goal, title, text),
                    url=url,
                    title=title,
                    text=text[:12000],
                    screenshot=str(shot),
                    observations=observations,
                )
            finally:
                await browser.close()

    def _url_from_goal(self, goal: str) -> str | None:
        match = re.search(r"https?://\S+", goal)
        if match:
            return match.group(0)
        return None

    def _summarize(self, goal: str, title: str, text: str) -> str:
        compact = " ".join(line.strip() for line in text.splitlines() if line.strip())
        excerpt = compact[:900]
        if title:
            return f"Browser result for '{goal}' on {title}: {excerpt}"
        return f"Browser result for '{goal}': {excerpt}" if excerpt else "Browser opened, but no readable page text was found."
