from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class AuditLog:
    """Append-only local audit trail for the demo's controlled data flow."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def append(self, action: str, *, subject_id: str | None = None, details: dict[str, Any] | None = None) -> dict[str, Any]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        row = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "action": action,
            "subject_id": subject_id,
            "details": details or {},
        }
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
        return row

    def latest(self, limit: int = 20) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        rows = [json.loads(line) for line in self.path.read_text(encoding="utf-8").splitlines() if line.strip()]
        return list(reversed(rows[-max(1, min(limit, 100)):]))
