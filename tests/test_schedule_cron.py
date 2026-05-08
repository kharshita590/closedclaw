from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent"))

from schedule.cron import next_run_from_cron  # noqa: E402


def test_next_run_every_minute() -> None:
    now = datetime(2026, 5, 7, 10, 0, 30, tzinfo=timezone.utc)
    nxt = next_run_from_cron("* * * * *", now=now)
    assert nxt == datetime(2026, 5, 7, 10, 1, 0, tzinfo=timezone.utc)


def test_next_run_step_minutes() -> None:
    now = datetime(2026, 5, 7, 10, 0, 30, tzinfo=timezone.utc)
    nxt = next_run_from_cron("*/5 * * * *", now=now)
    assert nxt == datetime(2026, 5, 7, 10, 5, 0, tzinfo=timezone.utc)

