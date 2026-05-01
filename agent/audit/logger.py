from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class AuditLogger:
    def __init__(self, log_dir: str = "logs") -> None:
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.audit_file = self.log_dir / "audit.jsonl"
        self.llm_file = self.log_dir / "llm_decisions.jsonl"

    def event(self, kind: str, **payload: Any) -> None:
        self._write(self.audit_file, {"kind": kind, **payload})

    def decision(self, **payload: Any) -> None:
        self._write(self.llm_file, payload)

    def _write(self, path: Path, payload: dict[str, Any]) -> None:
        record = {"ts": datetime.now(timezone.utc).isoformat(), **payload}
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, default=str) + "\n")
