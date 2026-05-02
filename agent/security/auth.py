"""FastAPI API-key authentication helpers."""

from __future__ import annotations

from fastapi import Header, HTTPException, status

from security.config import get_security_settings


def is_valid_api_key(authorization: str | None, x_api_key: str | None) -> bool:
    """Returns whether the provided headers contain a configured API key."""

    settings = get_security_settings()
    return bool(settings.api_keys and _extract_token(authorization, x_api_key) in settings.api_keys)


def require_auth(
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None),
) -> str:
    """FastAPI dependency that requires a configured API key on protected routes."""

    settings = get_security_settings()
    if not settings.api_keys:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API authentication is not configured. Set AGENT_API_KEYS.",
        )
    token = _extract_token(authorization, x_api_key)
    if not is_valid_api_key(authorization, x_api_key):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or missing API key")
    return token


def auth_headers() -> dict[str, str]:
    """Builds an Authorization header for internal clients such as the UI or bridges."""

    settings = get_security_settings()
    key = next(iter(settings.api_keys), "")
    return {"Authorization": f"Bearer {key}"} if key else {}


def _extract_token(authorization: str | None, x_api_key: str | None) -> str:
    if x_api_key:
        return x_api_key.strip()
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return ""
