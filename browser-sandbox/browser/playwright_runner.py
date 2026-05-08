from __future__ import annotations

import re
from typing import Any

from markdownify import markdownify as md
from playwright.async_api import async_playwright

from api.schemas import BrowserFormSubmitRequest, BrowserRunRequest, BrowserRunResponse, FormField, FormFieldsResponse
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

    async def submit_form(self, request: BrowserFormSubmitRequest) -> BrowserRunResponse:
        """Fill matching form controls and submit the form after approval."""

        observations: list[dict[str, Any]] = []
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True, args=["--disable-dev-shm-usage", "--no-sandbox"])
            page = await browser.new_page(viewport={"width": 1365, "height": 900})
            try:
                await page.goto(request.url, wait_until="domcontentloaded", timeout=30000)
                await page.wait_for_timeout(2000)
                observations.append({"action": "goto", "url": request.url})
                for label, value in request.fields.items():
                    filled = await self._fill_google_form_field(page, label, value)
                    observations.append({"action": "fill", "label": label, "value": value, "filled": filled})
                if request.submit:
                    await page.get_by_role("button", name=re.compile(r"submit", re.I)).click(timeout=10000)
                    await page.wait_for_timeout(2000)
                    observations.append({"action": "submit"})
                html = await page.content()
                text = md(html)
                shot = screenshot_path()
                await page.screenshot(path=str(shot), full_page=True)
                return BrowserRunResponse(
                    summary=self._summarize("submit form", await page.title(), text),
                    url=page.url,
                    title=await page.title(),
                    text=text[:12000],
                    screenshot=str(shot),
                    observations=observations,
                )
            finally:
                await browser.close()

    async def form_fields(self, url: str) -> FormFieldsResponse:
        """Discover visible form-like input fields for a URL."""

        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True, args=["--disable-dev-shm-usage", "--no-sandbox"])
            page = await browser.new_page(viewport={"width": 1365, "height": 900})
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                await page.wait_for_timeout(1500)
                items = await self._discover_fields(page)
                return FormFieldsResponse(url=page.url, fields=[FormField(**item) for item in items])
            finally:
                await browser.close()

    async def _discover_fields(self, page: Any) -> list[dict[str, Any]]:
        """Return a best-effort list of visible inputs with labels and types."""

        script = """
() => {
  const isVisible = (el) => {
    if (!el) return false;
    const style = window.getComputedStyle(el);
    if (style.visibility === 'hidden' || style.display === 'none') return false;
    const rect = el.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0;
  };

  const guessLabel = (el) => {
    const aria = el.getAttribute('aria-label') || el.getAttribute('aria-labelledby');
    if (aria) return aria;
    const id = el.getAttribute('id');
    if (id) {
      const lbl = document.querySelector(`label[for="${id}"]`);
      if (lbl && lbl.innerText) return lbl.innerText;
    }
    const parentLabel = el.closest('label');
    if (parentLabel && parentLabel.innerText) return parentLabel.innerText;
    const ph = el.getAttribute('placeholder');
    if (ph) return ph;
    const name = el.getAttribute('name');
    if (name) return name;
    return '';
  };

  const normalize = (s) => (s || '').replace(/\\s+/g, ' ').trim();

  const controls = Array.from(document.querySelectorAll('input, textarea, select'))
    .filter(isVisible)
    .filter(el => !['hidden', 'submit', 'button', 'image', 'reset'].includes((el.getAttribute('type') || '').toLowerCase()));

  const seen = new Set();
  const out = [];
  for (const el of controls) {
    const tag = el.tagName.toLowerCase();
    const type = tag === 'input' ? ((el.getAttribute('type') || 'text').toLowerCase()) : tag;
    const required = el.hasAttribute('required') || el.getAttribute('aria-required') === 'true';
    const label = normalize(guessLabel(el));
    const key = `${label}::${type}::${required}`;
    if (!label) continue;
    if (seen.has(key)) continue;
    seen.add(key);
    out.push({ label, input_type: type, required });
    if (out.length >= 60) break;
  }
  return out;
}
"""
        try:
            result = await page.evaluate(script)
        except Exception:
            result = []
        if not isinstance(result, list):
            return []
        cleaned: list[dict[str, Any]] = []
        for item in result:
            if not isinstance(item, dict):
                continue
            label = str(item.get("label", "")).strip()
            input_type = str(item.get("input_type", "")).strip() or "text"
            required = bool(item.get("required", False))
            if label:
                cleaned.append({"label": label, "input_type": input_type, "required": required})
        return cleaned

    async def _fill_google_form_field(self, page: Any, label: str, value: str) -> bool:
        """Best-effort fill for Google Forms text inputs and radio/list options."""

        label_text = re.escape(label).replace(r"\ ", r"\s+")
        question = page.locator("div[role='listitem']").filter(has_text=re.compile(label_text, re.I)).first
        if await question.count() == 0:
            question = page.locator("body")
        textbox = question.locator("input[type='text'], input[type='email'], input[type='tel'], textarea").first
        if await textbox.count() > 0:
            await textbox.fill(value, timeout=5000)
            return True
        option = question.get_by_text(re.compile(rf"^{re.escape(value)}$", re.I)).first
        if await option.count() > 0:
            await option.click(timeout=5000)
            return True
        combobox = question.locator("div[role='listbox']").first
        if await combobox.count() > 0:
            await combobox.click(timeout=5000)
            await page.get_by_text(re.compile(rf"^{re.escape(value)}$", re.I)).click(timeout=5000)
            return True
        return False

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
