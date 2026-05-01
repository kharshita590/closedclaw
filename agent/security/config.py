from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(os.getenv("PROJECT_ROOT", Path(__file__).resolve().parents[2]))
load_dotenv(PROJECT_ROOT / ".env")


class SecuritySettings:
    """Loads security-sensitive runtime settings from environment variables."""

    def __init__(self) -> None:
        """Reads API keys, policy thresholds, and persistent database paths."""

        self.api_keys = self._csv("AGENT_API_KEYS") or self._csv("AGENT_API_KEY")
        self.allowed_email_domains = self._csv("ALLOWED_EMAIL_DOMAINS")
        self.blocked_url_domains = self._csv("BLOCKED_URL_DOMAINS") or {
            "paypal.com",
            "stripe.com",
            "adult.example",
            "phishing.example",
        }
        self.max_email_body_chars = int(os.getenv("MAX_EMAIL_BODY_CHARS", "10000"))
        self.max_action_payload_bytes = int(os.getenv("MAX_ACTION_PAYLOAD_BYTES", "20000"))
        self.action_rate_limit_per_hour = int(os.getenv("ACTION_RATE_LIMIT_PER_HOUR", "10"))
        self.pairing_code_ttl_seconds = int(os.getenv("PAIRING_CODE_TTL_SECONDS", "600"))
        self.channel_policy_path = self._path(os.getenv("CHANNEL_POLICY_PATH", "channel_policy.yaml"))
        self.approval_db_path = self._path(os.getenv("APPROVAL_DB_PATH", "memory/approval_ledger.db"))
        self.pairing_db_path = self._path(os.getenv("PAIRING_DB_PATH", "memory/pairing_requests.db"))

    def _csv(self, name: str) -> set[str]:
        """Parses a comma-separated environment variable into a set."""

        value = os.getenv(name, "")
        return {item.strip() for item in value.split(",") if item.strip()}

    def _path(self, value: str) -> Path:
        """Resolves a configured path relative to the project root."""

        path = Path(value).expanduser()
        return path if path.is_absolute() else PROJECT_ROOT / path


@lru_cache(maxsize=1)
def get_security_settings() -> SecuritySettings:
    """Returns cached security settings so modules agree on paths and limits."""

    return SecuritySettings()
