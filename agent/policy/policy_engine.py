from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Protocol
from urllib.parse import urlparse

from actions.models import AgentAction, BrowserNavigateAction, SendEmailAction
from security.config import get_security_settings


class ApprovalLedgerProtocol(Protocol):
    """Minimal ledger interface required by rate-limit checks."""

    def count_executed_since(self, action_type: str, since: datetime) -> int:
        """Counts executed approvals for an action type after a timestamp."""


@dataclass(frozen=True)
class PolicyResult:
    """Result returned by the policy engine before action execution."""

    allowed: bool
    reason: str = ""


class PolicyEngine:
    """Central policy gate for URLs, recipients, payload sizes, and action rates."""

    def __init__(self, ledger: ApprovalLedgerProtocol | None = None) -> None:
        """Creates a policy engine with optional ledger-backed rate limiting."""

        self.settings = get_security_settings()
        self.ledger = ledger

    def check(self, action: AgentAction) -> PolicyResult:
        """Runs every policy check and returns the first rejection reason."""

        for check in (self._payload_size_policy, self._url_policy, self._email_recipient_policy, self._rate_limit_policy):
            result = check(action)
            if not result.allowed:
                return result
        return PolicyResult(True, "allowed")

    def _url_policy(self, action: AgentAction) -> PolicyResult:
        """Rejects browser actions targeting blocked domains."""

        if not isinstance(action, BrowserNavigateAction) or not action.url:
            return PolicyResult(True, "not a browser URL action")
        domain = urlparse(action.url).netloc.lower().split(":")[0]
        if any(domain == blocked or domain.endswith(f".{blocked}") for blocked in self.settings.blocked_url_domains):
            return PolicyResult(False, f"Blocked URL domain: {domain}")
        return PolicyResult(True, "URL allowed")

    def _email_recipient_policy(self, action: AgentAction) -> PolicyResult:
        """Rejects outbound email to domains outside the configured allowlist."""

        if not isinstance(action, SendEmailAction) or not self.settings.allowed_email_domains:
            return PolicyResult(True, "not constrained by recipient domain policy")
        domain = str(action.recipient).split("@", 1)[1].lower()
        if domain not in self.settings.allowed_email_domains:
            return PolicyResult(False, f"Recipient domain is not allowed: {domain}")
        return PolicyResult(True, "recipient domain allowed")

    def _payload_size_policy(self, action: AgentAction) -> PolicyResult:
        """Rejects actions whose serialized payload or email body is too large."""

        payload = json.dumps(action.model_dump(mode="json"), default=str)
        if len(payload.encode("utf-8")) > self.settings.max_action_payload_bytes:
            return PolicyResult(False, "Action payload exceeds configured size limit")
        if isinstance(action, SendEmailAction) and len(action.body) > self.settings.max_email_body_chars:
            return PolicyResult(False, "Email body exceeds configured size limit")
        return PolicyResult(True, "payload size allowed")

    def _rate_limit_policy(self, action: AgentAction) -> PolicyResult:
        """Rejects repeated execution of the same action type above hourly limits."""

        if not self.ledger:
            return PolicyResult(True, "no ledger configured for rate limit")
        since = datetime.now(timezone.utc) - timedelta(hours=1)
        count = self.ledger.count_executed_since(action.action_type, since)
        if count >= self.settings.action_rate_limit_per_hour:
            return PolicyResult(False, f"Rate limit exceeded for {action.action_type}")
        return PolicyResult(True, "rate allowed")
