"""Celery application configured from environment variables.

The API process enqueues approved action IDs here, and worker processes consume
them so long-running browser or email actions do not block HTTP requests.
"""

from __future__ import annotations

import os

from celery import Celery

celery_app = Celery(
    "closedclaw",
    broker=os.getenv("CELERY_BROKER_URL", "redis://redis:6379/0"),
    backend=os.getenv("CELERY_RESULT_BACKEND", os.getenv("CELERY_BROKER_URL", "redis://redis:6379/0")),
)
app = celery_app
celery_app.conf.task_routes = {"worker.tasks.execute_action_task": {"queue": "actions"}}
