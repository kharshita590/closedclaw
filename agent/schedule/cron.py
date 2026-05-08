from __future__ import annotations

from datetime import datetime, timedelta, timezone


def next_run_from_cron(cron_expression: str, now: datetime | None = None) -> datetime | None:
    """Very small cron helper: supports only '* * * * *' and '*/N * * * *' minutes.

    This keeps scheduling deterministic without adding heavy dependencies. It can
    be extended later to full croniter support.
    """

    now = now or datetime.now(timezone.utc)
    parts = cron_expression.strip().split()
    if len(parts) != 5:
        return None
    minute = parts[0]
    if minute == "*":
        base = now.replace(second=0, microsecond=0) + timedelta(minutes=1)
        return base
    if minute.startswith("*/"):
        try:
            step = int(minute.removeprefix("*/"))
        except ValueError:
            return None
        if step <= 0:
            return None
        base = now.replace(second=0, microsecond=0) + timedelta(minutes=1)
        # align to step
        minute_val = base.minute
        remainder = minute_val % step
        if remainder:
            base = base + timedelta(minutes=(step - remainder))
        return base
    return None

