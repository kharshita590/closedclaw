"""Integration tests for browser sandbox API authentication."""

from __future__ import annotations

import sys
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "browser-sandbox"))

from api import routes  # noqa: E402
from api.server import app  # noqa: E402
from api.schemas import BrowserRunResponse  # noqa: E402


class FakeRunner:
    """Browser runner test double that avoids launching Playwright."""

    async def run(self, request):
        """Return a deterministic browser result for auth tests."""

        return BrowserRunResponse(summary="ok", url=request.start_url, title="test", text="", screenshot=None)


def test_browser_routes_reject_missing_api_key(monkeypatch) -> None:
    """Every browser sandbox route returns 401 without a valid API key."""

    monkeypatch.setenv("BROWSER_SANDBOX_API_KEY", "secret")
    client = TestClient(app)
    assert client.get("/health").status_code == 401
    assert client.post("/run", json={"goal": "test"}).status_code == 401


def test_browser_routes_accept_valid_api_key(monkeypatch) -> None:
    """Every browser sandbox route accepts a valid API key."""

    monkeypatch.setenv("BROWSER_SANDBOX_API_KEY", "secret")
    monkeypatch.setattr(routes, "runner", FakeRunner())
    client = TestClient(app)
    headers = {"authorization": "Bearer secret"}
    assert client.get("/health", headers=headers).status_code != 401
    assert client.post("/run", headers=headers, json={"goal": "test"}).status_code != 401
