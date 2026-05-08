"""Celery tasks for approved action execution.

Tasks load typed action plans from the PostgreSQL approval ledger, run policy
checks, execute the appropriate tool through scoped permissions, and write the
result back to the ledger.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from actions.executor import ActionExecutor
from approvals.ledger import ApprovalLedger
from policy.policy_engine import PolicyEngine
from schedule.cron import next_run_from_cron
from schedule.store import ScheduledActionStore
from worker.celery_app import celery_app


@celery_app.task(name="worker.tasks.execute_action_task")
def execute_action_task(action_id: str) -> dict[str, Any]:
    """Execute one approved action in the background.

    Args:
        action_id: Approval ledger UUID to execute.

    Returns:
        Execution result written to the approval ledger.
    """

    ledger = ApprovalLedger()
    policy = PolicyEngine(ledger)
    action = ledger.claim_for_execution(action_id)
    if action is None:
        return {"ok": False, "skipped": True, "reason": "Approval was not queued for execution"}
    policy_result = policy.check(action)
    if not policy_result.allowed:
        result = {"ok": False, "policy_allowed": False, "reason": policy_result.reason}
        ledger.decide(action_id, "rejected", "worker", result)
        return result

    executor = ActionExecutor(policy)
    result = asyncio.run(executor.execute_approved(action))
    final_status = "approved" if result.get("ok") else "rejected"
    ledger.decide(action_id, final_status, "worker", result)
    return result


@celery_app.task(name="worker.tasks.tick_scheduled_actions")
def tick_scheduled_actions() -> dict[str, Any]:
    """Check scheduled_actions and enqueue due work safely."""

    store = ScheduledActionStore()
    ledger = ApprovalLedger()
    policy = PolicyEngine(ledger)
    now = datetime.now(timezone.utc)  # type: ignore[name-defined]
    due = store.list_due(now)
    enqueued: list[str] = []
    for row in due:
        # Compute next run up front to avoid duplicate triggering loops.
        next_run = next_run_from_cron(row.cron_expression, now=now)
        store.update_run_times(row.id, last_run=now, next_run=next_run)

        from actions.models import action_from_payload

        action = action_from_payload({**row.payload, "action_type": row.action_type})

        policy_result = policy.check(action)
        if not policy_result.allowed:
            ledger.create(action, row.owner_user_id, status="rejected", result={"reason": policy_result.reason, "scheduled_action_id": row.id})
            continue

        # Conservative safety: anything not obviously read-only goes to approval.
        # (A richer risk model is added via Skills/Profiles in later parts.)
        pending = ledger.create(action, row.owner_user_id)
        enqueued.append(pending.id)
    return {"ok": True, "due": len(due), "approvals_created": enqueued}
