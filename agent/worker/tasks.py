"""Celery tasks for approved action execution.

Tasks load typed action plans from the PostgreSQL approval ledger, run policy
checks, execute the appropriate tool through scoped permissions, and write the
result back to the ledger.
"""

from __future__ import annotations

import asyncio
from typing import Any

from actions.executor import ActionExecutor
from approvals.ledger import ApprovalLedger
from policy.policy_engine import PolicyEngine
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
