from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent"))

from actions.models import BrowserNavigateAction, SendEmailAction
from policy.policy_engine import PolicyEngine
from security.config import get_security_settings


class FakeLedger:
    """Small ledger double used to exercise rate-limit behavior."""

    def __init__(self, count: int) -> None:
        self.count = count

    def count_executed_since(self, action_type: str, since: datetime) -> int:
        """Returns a fixed count regardless of action type for deterministic tests."""

        return self.count


def reset_settings(**env: str) -> None:
    """Clears cached settings and applies test-specific environment variables."""

    for key, value in env.items():
        os.environ[key] = value
    get_security_settings.cache_clear()


def test_blocks_configured_url_domain() -> None:
    """Policy engine rejects blocked browser domains."""

    reset_settings(BLOCKED_URL_DOMAINS="blocked.example")
    result = PolicyEngine().check(BrowserNavigateAction(url="https://blocked.example/path", goal="open site"))
    assert not result.allowed
    assert "Blocked URL domain" in result.reason


def test_rejects_unapproved_email_domain() -> None:
    """Policy engine rejects email recipients outside the allowlist."""

    reset_settings(ALLOWED_EMAIL_DOMAINS="example.com")
    action = SendEmailAction(recipient="person@other.com", subject="Hi", body="Hello")
    result = PolicyEngine().check(action)
    assert not result.allowed
    assert "Recipient domain" in result.reason


def test_rate_limit_rejects_after_threshold() -> None:
    """Policy engine rejects actions once the hourly ledger limit is reached."""

    reset_settings(ACTION_RATE_LIMIT_PER_HOUR="2")
    action = SendEmailAction(recipient="person@example.com", subject="Hi", body="Hello")
    result = PolicyEngine(FakeLedger(count=2)).check(action)
    assert not result.allowed
    assert "Rate limit" in result.reason
