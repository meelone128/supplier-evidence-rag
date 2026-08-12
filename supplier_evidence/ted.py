from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Iterable, Literal

import requests

from .types import EvidenceRecord


TED_SEARCH_URL = "https://api.ted.europa.eu/v3/notices/search"
LEGAL_SUFFIXES = {"gmbh", "sa", "sarl", "spa", "ltd", "limited", "inc", "bv", "ag", "llc"}


def normalise_organisation_name(name: str) -> str:
    """Conservative normalization used only to propose a manual match."""

    tokens = re.findall(r"[a-z0-9]+", name.casefold())
    return " ".join(token for token in tokens if token not in LEGAL_SUFFIXES)


@dataclass(frozen=True)
class TedNotice:
    publication_id: str
    title: str
    publication_date: date | None
    notice_type: str | None
    buyer: str | None
    cpv_codes: tuple[str, ...]
    region: str | None
    supplier_names: tuple[str, ...]
    source_url: str
    raw: dict[str, Any]


@dataclass(frozen=True)
class TedCandidateMatch:
    notice: TedNotice
    target_supplier: str
    matched_supplier_name: str
    score: float
    status: Literal["manual_confirmation_required", "below_threshold"]

    def to_evidence(self) -> EvidenceRecord:
        """Create RAG evidence only after a reviewer explicitly confirms the match."""

        raise RuntimeError(
            "TED candidate matches must be confirmed by a reviewer before they become supplier evidence."
        )


def confirmed_candidate_to_evidence(
    candidate: TedCandidateMatch,
    *,
    category: str,
    region: str,
) -> EvidenceRecord:
    """Convert a reviewer-confirmed public notice into a traceable RAG record."""

    notice = candidate.notice
    return EvidenceRecord(
        evidence_id=f"ted-{notice.publication_id}",
        supplier_name=candidate.target_supplier,
        category=category,
        region=region,
        evidence_type="procurement_notice",
        source_title=notice.title or f"TED notice {notice.publication_id}",
        source_version=notice.publication_id,
        source_location=notice.source_url,
        authority="public",
        issued_on=notice.publication_date,
        fields={
            "ted_publication_id": notice.publication_id,
            "notice_type": notice.notice_type,
            "buyer": notice.buyer,
            "cpv_codes": list(notice.cpv_codes),
            "place_of_performance": notice.region,
            "matched_supplier_name": candidate.matched_supplier_name,
            "match_score": round(candidate.score, 4),
            "match_status": "reviewer_confirmed",
        },
    )


def _first(value: Any) -> Any:
    return value[0] if isinstance(value, list) and value else value


def _text(value: Any) -> str | None:
    value = _first(value)
    if isinstance(value, dict):
        value = (
            value.get("value")
            or value.get("text")
            or value.get("name")
            or _first(value.get("eng"))
            or _first(next(iter(value.values()), None))
        )
    return str(value).strip() if value not in {None, ""} else None


def _date(value: Any) -> date | None:
    text = _text(value)
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def parse_ted_search_response(payload: dict[str, Any]) -> list[TedNotice]:
    """Normalize the published-notice subset returned by a TED search response.

    Field aliases make the connector tolerant of the compact and expanded API
    response forms. Raw responses are still cached for audit and later parser
    refinement instead of silently discarding unfamiliar fields.
    """

    rows = payload.get("notices") or payload.get("results") or payload.get("items") or []
    if isinstance(rows, dict):
        rows = rows.get("items") or rows.get("results") or []
    notices: list[TedNotice] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        publication_id = _text(
            row.get("publication-number") or row.get("publicationNumber") or row.get("publication_id") or row.get("id")
        )
        if not publication_id:
            continue
        organisations = row.get("winner-name") or row.get("organisations") or row.get("suppliers") or row.get("winner") or []
        if isinstance(organisations, dict):
            organisations = [organisations]
        names = tuple(filter(None, (_text(item) for item in organisations)))
        cpv = row.get("cpvCodes") or row.get("cpv") or []
        if isinstance(cpv, str):
            cpv = [cpv]
        notices.append(TedNotice(
            publication_id=publication_id,
            title=_text(row.get("title") or row.get("noticeTitle")) or f"TED 公共采购公告 {publication_id}",
            publication_date=_date(row.get("publication-date") or row.get("publicationDate") or row.get("publication_date")),
            notice_type=_text(row.get("noticeType") or row.get("notice_type")),
            buyer=_text(row.get("buyer-name") or row.get("buyer") or row.get("contractingAuthority")),
            cpv_codes=tuple(str(item) for item in cpv),
            region=_text(row.get("placeOfPerformance") or row.get("region")),
            supplier_names=names,
            source_url=f"https://ted.europa.eu/en/notice/-/detail/{publication_id}",
            raw=row,
        ))
    return notices


def propose_supplier_matches(
    target_supplier: str, notices: Iterable[TedNotice], threshold: float = 0.82
) -> list[TedCandidateMatch]:
    target = normalise_organisation_name(target_supplier)
    candidates: list[TedCandidateMatch] = []
    for notice in notices:
        for supplier_name in notice.supplier_names:
            score = SequenceMatcher(None, target, normalise_organisation_name(supplier_name)).ratio()
            candidates.append(TedCandidateMatch(
                notice=notice,
                target_supplier=target_supplier,
                matched_supplier_name=supplier_name,
                score=score,
                status="manual_confirmation_required" if score >= threshold else "below_threshold",
            ))
    return sorted(candidates, key=lambda item: item.score, reverse=True)


class TedConnector:
    """Fetch and cache official TED notices; search payload stays explicit."""

    def __init__(self, cache_dir: str | Path, endpoint: str = TED_SEARCH_URL) -> None:
        self.cache_dir = Path(cache_dir)
        self.endpoint = endpoint

    def search(self, request_payload: dict[str, Any], timeout_seconds: int = 30) -> list[TedNotice]:
        response = requests.post(self.endpoint, json=request_payload, timeout=timeout_seconds)
        response.raise_for_status()
        payload = response.json()
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        (self.cache_dir / "latest-search-response.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return parse_ted_search_response(payload)

    def search_supplier(self, supplier_name: str, *, limit: int = 10) -> list[TedNotice]:
        """Run a bounded, read-only public search for a supplier name.

        TED field names are intentionally kept to the official API vocabulary.
        A result is still only a candidate and is never indexed automatically.
        """

        safe_limit = max(1, min(limit, 20))
        payload = {
            # A quoted exact phrase is deliberately conservative here. TED
            # search syntax rejects a bare multi-word full-text expression;
            # more importantly, supplier identity must not be broadened by
            # guesswork before the human review stage.
            "query": f'FT="{supplier_name.replace(chr(34), "")}"',
            "fields": ["publication-number", "publication-date", "winner-name", "buyer-name"],
            "page": 1,
            "limit": safe_limit,
            "scope": "ALL",
            "onlyLatestVersions": True,
        }
        return self.search(payload)
