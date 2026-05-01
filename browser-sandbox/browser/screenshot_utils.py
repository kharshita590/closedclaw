from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path


def screenshot_path(prefix: str = "browser") -> Path:
    directory = Path("screenshots")
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return directory / f"{prefix}-{stamp}.png"
