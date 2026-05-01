from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Sequence

from dotenv import load_dotenv
from google.auth.transport.requests import Request
from google.auth.exceptions import GoogleAuthError, TransportError
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

from auth.token_store import TokenStore

def _detect_project_root() -> Path:
    here = Path(__file__).resolve()
    candidates = [
        Path(os.getenv("PROJECT_ROOT", "")) if os.getenv("PROJECT_ROOT") else None,
        here.parents[2] if len(here.parents) > 2 else None,
        here.parents[1] if len(here.parents) > 1 else None,
        Path.cwd(),
    ]
    for candidate in candidates:
        if candidate and ((candidate / ".env").exists() or (candidate / "secrets").exists()):
            return candidate
    return here.parents[1]


PROJECT_ROOT = _detect_project_root()
load_dotenv(PROJECT_ROOT / ".env")


def load_credentials(token_name: str, scopes: Sequence[str]) -> Credentials | None:
    """Loads encrypted Google credentials, returning None if refresh is unavailable."""

    store = TokenStore(str(_project_path(os.getenv("SECRETS_DIR", "secrets"))))
    raw = store.read(token_name)
    creds = Credentials.from_authorized_user_info(json.loads(raw), scopes) if raw else None
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            store.write(token_name, creds.to_json().encode("utf-8"))
        except (GoogleAuthError, TransportError, OSError):
            return None
    return creds if creds and creds.valid else None


def run_local_oauth(token_name: str, scopes: Sequence[str]) -> Credentials:
    """Runs an interactive local OAuth flow and stores encrypted credentials."""

    credentials_file = _project_path(os.getenv("GOOGLE_CLIENT_SECRET_FILE", "secrets/google_client_secret.json"))
    if not credentials_file.exists():
        raise FileNotFoundError(
            "Missing Google OAuth client secret. Set GOOGLE_CLIENT_SECRET_FILE or place "
            f"secrets/google_client_secret.json. Looked for: {credentials_file}"
        )
    flow = InstalledAppFlow.from_client_secrets_file(str(credentials_file), scopes)
    creds = flow.run_local_server(port=int(os.getenv("OAUTH_PORT", "8765")))
    TokenStore(str(_project_path(os.getenv("SECRETS_DIR", "secrets")))).write(token_name, creds.to_json().encode("utf-8"))
    return creds


def _project_path(value: str) -> Path:
    """Resolves project-relative paths while handling Docker container roots."""

    path = Path(value).expanduser()
    if path == Path("/secrets") and (PROJECT_ROOT / "secrets").exists():
        return PROJECT_ROOT / "secrets"
    return path if path.is_absolute() else PROJECT_ROOT / path
