from __future__ import annotations

from fastapi import APIRouter, Depends

from api.auth import require_auth
from api.schemas import BrowserRunRequest, BrowserRunResponse
from browser.playwright_runner import PlaywrightRunner

router = APIRouter()
runner = PlaywrightRunner()


@router.get("/health", dependencies=[Depends(require_auth)])
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/run", response_model=BrowserRunResponse, dependencies=[Depends(require_auth)])
async def run_browser(request: BrowserRunRequest) -> BrowserRunResponse:
    return await runner.run(request)
