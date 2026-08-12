from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from .ted import TedCandidateMatch, TedNotice, confirmed_candidate_to_evidence


class TedReviewQueue:
    """Small local review queue; only confirmed notices can become RAG evidence."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def _read(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        return json.loads(self.path.read_text(encoding="utf-8"))

    def _write(self, rows: list[dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")

    def add(self, candidate: TedCandidateMatch, category: str, region: str) -> dict[str, Any]:
        rows = self._read()
        existing = next(
            (
                row for row in rows
                if row.get("target_supplier") == candidate.target_supplier
                and str(row.get("notice", {}).get("publication-number") or row.get("notice", {}).get("publicationNumber") or row.get("notice", {}).get("id"))
                == candidate.notice.publication_id
            ),
            None,
        )
        if existing is not None:
            return existing
        row = {
            "id": str(uuid.uuid4()), "status": "pending", "target_supplier": candidate.target_supplier,
            "matched_supplier_name": candidate.matched_supplier_name, "score": candidate.score,
            "category": category, "region": region, "notice": candidate.notice.raw,
        }
        rows.append(row); self._write(rows)
        return row

    def list(self) -> list[dict[str, Any]]:
        return self._read()

    def confirm(self, review_id: str) -> dict[str, Any]:
        rows = self._read()
        row = next((item for item in rows if item["id"] == review_id), None)
        if not row:
            raise KeyError(review_id)
        if row["status"] == "confirmed":
            return row
        raw = row["notice"]
        notice = TedNotice(
            publication_id=str(raw.get("publicationNumber") or raw.get("id")),
            title=str(raw.get("title") or "TED notice"), publication_date=None,
            notice_type=raw.get("noticeType"), buyer=raw.get("buyer"),
            cpv_codes=tuple(raw.get("cpvCodes") or []), region=raw.get("region"),
            supplier_names=(row["matched_supplier_name"],),
            source_url=f"https://ted.europa.eu/en/notice/-/detail/{raw.get('publicationNumber') or raw.get('id')}", raw=raw,
        )
        candidate = TedCandidateMatch(notice, row["target_supplier"], row["matched_supplier_name"], row["score"], "manual_confirmation_required")
        evidence = confirmed_candidate_to_evidence(candidate, category=row["category"], region=row["region"])
        row["status"] = "confirmed"; row["evidence"] = evidence.model_dump(mode="json"); self._write(rows)
        return row
