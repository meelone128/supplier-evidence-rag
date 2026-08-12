from __future__ import annotations

import json
from pathlib import Path

from .types import EvidenceRecord


def load_evidence_catalog(path: str | Path) -> list[EvidenceRecord]:
    """Load the project-owned demo catalog before connecting real data sources."""

    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("Evidence catalog must be a JSON array")
    return [EvidenceRecord.model_validate(item) for item in payload]
