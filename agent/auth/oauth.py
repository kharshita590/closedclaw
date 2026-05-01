from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Sequence

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

from auth.token_store import TokenStore


def load_credentials(token_name: str, scopes: Sequence[str]) -> Credentials | None:
    store = TokenStore(os.getenv("SECRETS_DIR", "secrets"))
    raw = store.read(token_name)
    creds = Credentials.from_authorized_user_info(json.loads(raw), scopes) if raw else None
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        store.write(token_name, creds.to_json().encode("utf-8"))
    return creds if creds and creds.valid else None


def run_local_oauth(token_name: str, scopes: Sequence[str]) -> Credentials:
    credentials_file = Path(os.getenv("GOOGLE_CLIENT_SECRET_FILE", "secrets/google_client_secret.json"))
    if not credentials_file.exists():
        raise FileNotFoundError(
            "Missing Google OAuth client secret. Set GOOGLE_CLIENT_SECRET_FILE or place "
            "secrets/google_client_secret.json."
        )
    flow = InstalledAppFlow.from_client_secrets_file(str(credentials_file), scopes)
    creds = flow.run_local_server(port=int(os.getenv("OAUTH_PORT", "8765")))
    TokenStore(os.getenv("SECRETS_DIR", "secrets")).write(token_name, creds.to_json().encode("utf-8"))
    return creds
