"""API key authentication for the browser sandbox service."""

from __future__ import annotations

import os

from fastapi import Header, HTTPException, status


def require_auth(authorization: str | None = Header(default=None), x_api_key: str | None = Header(default=None)) -> str:
    """Requires a shared API key before browser automation endpoints can run."""

    keys = _configured_keys()
    if not keys:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Browser API key is not configured")
    token = x_api_key or ""
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    if token not in keys:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or missing API key")
    return token


def _configured_keys() -> set[str]:
    """Returns accepted browser sandbox API keys from environment variables."""

    raw = os.getenv("BROWSER_SANDBOX_API_KEY") or os.getenv("AGENT_API_KEYS") or os.getenv("AGENT_API_KEY") or ""
    return {item.strip() for item in raw.split(",") if item.strip()}
