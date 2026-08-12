from __future__ import annotations

from typing import Protocol, Sequence

from pydantic import BaseModel, Field

from .retrieval import HybridEvidenceRetriever, RetrievalResult
from .rules import EvidenceGate, SupplierReview
from .reporting import GeneratedEvidenceReport
from .reranking import apply_rerank_order
from .types import EvidenceRecord, SupplierQuery


class VectorEvidenceRanker(Protocol):
    def rank(self, query: SupplierQuery, question: str, limit: int) -> Sequence[str]: ...


class SupplierEvidenceReport(BaseModel):
    review: SupplierReview
    retrieved_evidence: list[dict[str, object]] = Field(default_factory=list)
    output_gate_passed: bool
    output_gate_reason: str
    retrieval_mode: str = "bm25"
    rerank_mode: str = "未请求重排"
    generated_report: GeneratedEvidenceReport | None = None
    generated_report_status: str = "未请求生成"


class SupplierEvidenceService:
    def __init__(
        self,
        retriever: HybridEvidenceRetriever | None = None,
        gate: EvidenceGate | None = None,
        vector_ranker: VectorEvidenceRanker | None = None,
    ) -> None:
        self.retriever = retriever or HybridEvidenceRetriever()
        self.gate = gate or EvidenceGate()
        self.vector_ranker = vector_ranker

    def review_supplier(
        self,
        query: SupplierQuery,
        question: str,
        evidence: list[EvidenceRecord],
        vector_ranked_ids: Sequence[str] = (),
        report_generator: object | None = None,
        reranker: object | None = None,
    ) -> SupplierEvidenceReport:
        vector_ids = list(vector_ranked_ids)
        retrieval_mode = "bm25"
        if not vector_ids and self.vector_ranker is not None:
            vector_ids = list(self.vector_ranker.rank(query, question, limit=12))
        if vector_ids:
            retrieval_mode = "hybrid_bm25_vector_rrf"
        retrieved = self.retriever.search(
            query=query,
            question=question,
            evidence=evidence,
            vector_ranked_ids=vector_ids,
        )
        rerank_mode = "未请求重排"
        if reranker is not None and len(retrieved) > 1:
            original_ids = [result.evidence.evidence_id for result in retrieved]
            try:
                ranked_ids = reranker.rerank(query, question, retrieved)  # type: ignore[attr-defined]
                if set(ranked_ids) == set(original_ids):
                    retrieved = apply_rerank_order(retrieved, ranked_ids)
                    rerank_mode = "模型重排已通过候选集校验"
                else:
                    rerank_mode = "模型重排越出候选集，已保留 RRF 顺序"
            except Exception:
                rerank_mode = "模型重排失败，已保留 RRF 顺序"
        review = self.gate.review(query, [result.evidence for result in retrieved])
        output_gate_passed, output_gate_reason = self._validate_output(review, retrieved)
        generated_report: GeneratedEvidenceReport | None = None
        generated_report_status = "未请求生成"
        if report_generator is not None and output_gate_passed:
            try:
                candidate = report_generator.generate(review, retrieved)  # type: ignore[attr-defined]
                valid_ids = {result.evidence.evidence_id for result in retrieved}
                if set(candidate.cited_evidence_ids).issubset(valid_ids):
                    generated_report = candidate
                    generated_report_status = "已生成并通过引用校验"
                else:
                    generated_report_status = "生成内容包含非当前检索证据，已被输出门禁拦截"
            except Exception:
                generated_report_status = "模型说明生成失败，已保留确定性核验结果"
        return SupplierEvidenceReport(
            review=review,
            retrieved_evidence=[self._serialize_result(result) for result in retrieved],
            output_gate_passed=output_gate_passed,
            output_gate_reason=output_gate_reason,
            retrieval_mode=retrieval_mode,
            rerank_mode=rerank_mode,
            generated_report=generated_report,
            generated_report_status=generated_report_status,
        )

    @staticmethod
    def _serialize_result(result: RetrievalResult) -> dict[str, object]:
        return {
            "evidence_id": result.evidence.evidence_id,
            "source_title": result.evidence.source_title,
            "source_location": result.evidence.source_location,
            "evidence_type": result.evidence.evidence_type,
            "lexical_rank": result.lexical_rank,
            "vector_rank": result.vector_rank,
            "fused_rank": result.fused_rank,
        }

    @staticmethod
    def _validate_output(review: SupplierReview, retrieved: list[RetrievalResult]) -> tuple[bool, str]:
        available_ids = {result.evidence.evidence_id for result in retrieved}
        cited_ids = {citation.evidence_id for citation in review.evidence}
        if not retrieved:
            return False, "未检索到目标范围内证据，禁止生成确定性结论。"
        if not cited_ids.issubset(available_ids):
            return False, "报告包含未在当前检索结果中的引用。"
        if review.conflicts and any(not finding.citations for finding in review.conflicts):
            return False, "冲突结论缺少可追溯证据。"
        return True, "结构化结论与当前检索证据一致，可以生成带引用的说明。"
