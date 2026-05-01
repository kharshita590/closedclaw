from __future__ import annotations

from fastapi import APIRouter

from api.schemas import BrowserRunRequest, BrowserRunResponse
from browser.playwright_runner import PlaywrightRunner

router = APIRouter()
runner = PlaywrightRunner()


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/run", response_model=BrowserRunResponse)
async def run_browser(request: BrowserRunRequest) -> BrowserRunResponse:
    return await runner.run(request)
