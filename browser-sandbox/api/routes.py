"""Authenticated browser sandbox API routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from api.auth import require_auth
from api.schemas import BrowserFormSubmitRequest, BrowserRunRequest, BrowserRunResponse, FormFieldsResponse
from browser.playwright_runner import PlaywrightRunner

router = APIRouter()
runner = PlaywrightRunner()


@router.get("/health", dependencies=[Depends(require_auth)])
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/run", response_model=BrowserRunResponse, dependencies=[Depends(require_auth)])
async def run_browser(request: BrowserRunRequest) -> BrowserRunResponse:
    return await runner.run(request)


@router.post("/submit-form", response_model=BrowserRunResponse, dependencies=[Depends(require_auth)])
async def submit_form(request: BrowserFormSubmitRequest) -> BrowserRunResponse:
    return await runner.submit_form(request)


@router.get("/form-fields", response_model=FormFieldsResponse, dependencies=[Depends(require_auth)])
async def form_fields(url: str = Query(..., min_length=4, max_length=2000)) -> FormFieldsResponse:
    return await runner.form_fields(url)
