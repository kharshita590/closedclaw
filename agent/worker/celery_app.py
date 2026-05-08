"""Celery application configured from environment variables.

The API process enqueues approved action IDs here, and worker processes consume
them so long-running browser or email actions do not block HTTP requests.
"""

from __future__ import annotations

import os

from celery import Celery
from celery import signals

from approvals.ledger import ApprovalLedger

celery_app = Celery(
    "closedclaw",
    broker=os.getenv("CELERY_BROKER_URL", "redis://redis:6379/0"),
    backend=os.getenv("CELERY_RESULT_BACKEND", os.getenv("CELERY_BROKER_URL", "redis://redis:6379/0")),
)
app = celery_app
celery_app.conf.update(
    imports=("worker.tasks",),
    task_routes={"worker.tasks.execute_action_task": {"queue": "actions"}},
)

# Celery beat schedule for proactive tasks.
celery_app.conf.beat_schedule = {
    "tick-scheduled-actions-every-minute": {
        "task": "worker.tasks.tick_scheduled_actions",
        "schedule": 60.0,
        "options": {"queue": "actions"},
    }
}


@signals.worker_ready.connect
def _requeue_queued_approvals(sender=None, **kwargs) -> None:
    """Resubmit queued approvals so a missed enqueue can recover after restart."""

    ledger = ApprovalLedger()
    for row in ledger.list_queued():
        celery_app.send_task("worker.tasks.execute_action_task", args=[row.id], queue="actions")
