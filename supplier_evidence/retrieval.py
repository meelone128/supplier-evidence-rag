from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Iterable, Sequence

from .types import EvidenceRecord, SupplierQuery


def _tokens(text: str) -> list[str]:
    """Simple deterministic tokenizer for the project-owned demo corpus."""

    return re.findall(r"[a-z0-9_]+|[\u4e00-\u9fff]+", text.casefold())


def evidence_text(record: EvidenceRecord) -> str:
    fields = " ".join(f"{key} {value}" for key, value in record.fields.items())
    return " ".join(
        value for value in [
            record.supplier_name, record.category or "", record.region or "",
            record.evidence_type, record.source_title, fields,
        ] if value
    )


def filter_by_scope(query: SupplierQuery, evidence: Iterable[EvidenceRecord]) -> list[EvidenceRecord]:
    """Hard filters prevent same-category documents from another supplier leaking in."""

    return [
        record for record in evidence
        if record.supplier_name.casefold() == query.supplier_name.casefold()
        and (record.category is None or record.category == query.category)
        and (record.region is None or record.region == query.region)
    ]


def bm25_rank(query_text: str, evidence: Sequence[EvidenceRecord]) -> list[str]:
    """Return evidence ids in lexical relevance order without external dependencies."""

    terms = _tokens(query_text)
    if not terms or not evidence:
        return []
    docs = [_tokens(evidence_text(record)) for record in evidence]
    doc_freq = Counter(term for doc in docs for term in set(doc))
    avg_len = sum(len(doc) for doc in docs) / len(docs)
    scores: list[tuple[str, float]] = []
    for record, doc in zip(evidence, docs):
        counts = Counter(doc)
        score = 0.0
        for term in terms:
            if not counts[term]:
                continue
            idf = math.log(1 + (len(docs) - doc_freq[term] + 0.5) / (doc_freq[term] + 0.5))
            numerator = counts[term] * 2.2
            denominator = counts[term] + 1.2 * (1 - 0.75 + 0.75 * len(doc) / max(avg_len, 1))
            score += idf * numerator / denominator
        if score > 0:
            scores.append((record.evidence_id, score))
    return [evidence_id for evidence_id, _ in sorted(scores, key=lambda pair: (-pair[1], pair[0]))]


def reciprocal_rank_fusion(rankings: Iterable[Sequence[str]], k: int = 60) -> list[str]:
    """Fuse lexical and vector rankings while retaining a transparent score rule."""

    fused: dict[str, float] = defaultdict(float)
    for ranking in rankings:
        for index, evidence_id in enumerate(ranking, start=1):
            fused[evidence_id] += 1 / (k + index)
    return [evidence_id for evidence_id, _ in sorted(fused.items(), key=lambda pair: (-pair[1], pair[0]))]


@dataclass(frozen=True)
class RetrievalResult:
    evidence: EvidenceRecord
    lexical_rank: int | None
    vector_rank: int | None
    fused_rank: int


class HybridEvidenceRetriever:
    """Supplier-scoped retrieval that accepts vector candidates from Qdrant later.

    The retriever has no model dependency. A vector-store adapter can supply
    ``vector_ranked_ids``; until embeddings are connected the lexical leg still
    provides a fully testable baseline.
    """

    def search(
        self,
        query: SupplierQuery,
        question: str,
        evidence: Iterable[EvidenceRecord],
        vector_ranked_ids: Sequence[str] = (),
        top_k: int = 8,
    ) -> list[RetrievalResult]:
        scoped = filter_by_scope(query, evidence)
        lexical_ids = bm25_rank(
            f"{query.supplier_name} {query.category} {query.region} {question}", scoped
        )
        allowed = {record.evidence_id for record in scoped}
        vector_ids = [evidence_id for evidence_id in vector_ranked_ids if evidence_id in allowed]
        fused_ids = reciprocal_rank_fusion([lexical_ids, vector_ids])[:top_k]
        by_id = {record.evidence_id: record for record in scoped}
        lexical_rank = {evidence_id: i for i, evidence_id in enumerate(lexical_ids, start=1)}
        vector_rank = {evidence_id: i for i, evidence_id in enumerate(vector_ids, start=1)}
        return [
            RetrievalResult(
                evidence=by_id[evidence_id], lexical_rank=lexical_rank.get(evidence_id),
                vector_rank=vector_rank.get(evidence_id), fused_rank=index,
            )
            for index, evidence_id in enumerate(fused_ids, start=1)
        ]
