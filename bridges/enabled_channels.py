from __future__ import annotations

import os


def enabled_channels() -> set[str]:
    raw = os.getenv("ENABLED_CHANNELS", "ui,telegram")
    return {part.strip().lower() for part in raw.split(",") if part.strip()}


def channel_enabled(name: str) -> bool:
    return name.strip().lower() in enabled_channels()

