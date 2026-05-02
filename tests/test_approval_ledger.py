from __future__ import annotations

from actions.models import SendEmailAction
from approvals.ledger import ApprovalLedger


def test_approval_ledger_persists_and_decides_action(postgres_database: str) -> None:
    """Approval ledger persists pending actions and records final decisions."""

    ledger = ApprovalLedger()
    action = SendEmailAction(recipient="person@example.com", subject="Hi", body="Hello")

    pending = ledger.create(action, requested_by="user-1")
    assert pending.status == "pending"
    assert ledger.list_pending()[0].id == pending.id

    decided = ledger.decide(pending.id, "approved", "tester", {"ok": True})
    assert decided.status == "approved"
    assert ledger.list_pending() == []
    assert ledger.get_action(pending.id).action_type == "email.send"
