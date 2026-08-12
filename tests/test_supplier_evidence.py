from datetime import date
from pathlib import Path

from ingestion.types import ChunkRecord
from supplier_evidence import EvidenceGate, EvidenceRecord, HybridEvidenceRetriever, SupplierEvidenceService, SupplierQuery
from supplier_evidence.api import SupplierReviewRequest, create_supplier_review, get_evidence_detail
from supplier_evidence.catalog import load_evidence_catalog
from supplier_evidence.evaluation import run_fixed_evaluation
from supplier_evidence.ingestion import enrich_chunks_with_catalog
from supplier_evidence.reporting import GeneratedEvidenceReport
from supplier_evidence.reranking import apply_rerank_order


ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "data/supplier_evidence/evidence_catalog.json"


def test_gate_detects_missing_material_and_address_conflict() -> None:
    query = SupplierQuery(supplier_name="Northstar Components GmbH", category="industrial_components", region="EU")
    review = EvidenceGate(today=date(2026, 8, 11)).review(query, load_evidence_catalog(CATALOG))
    assert review.missing_materials == ["quality_inspection"]
    assert review.conflicts[0].code == "conflicting_evidence"
    assert review.decision == "证据不足或存在重大缺口，建议人工复核"


def test_gate_refuses_to_pass_without_evidence() -> None:
    query = SupplierQuery(supplier_name="Unknown Supplier", category="industrial_components", region="EU")
    review = EvidenceGate(today=date(2026, 8, 11)).review(query, [])
    assert review.evidence_score < 60
    assert review.decision == "证据不足，需补充供应商材料后再核验"


def test_catalog_flags_expiring_certificate() -> None:
    query = SupplierQuery(supplier_name="Eurofast Parts S.A.", category="industrial_components", region="EU")
    review = EvidenceGate(today=date(2026, 8, 11)).review(query, load_evidence_catalog(CATALOG))
    assert review.missing_materials == []
    assert any(finding.code == "expiring_material" for finding in review.findings)


def test_expired_or_conflicting_evidence_never_auto_passes() -> None:
    query = SupplierQuery(supplier_name="Safety Supplier", category="industrial_components", region="EU")
    evidence = [
        EvidenceRecord(evidence_id="license", supplier_name=query.supplier_name, category=query.category, region=query.region, evidence_type="qualification", source_title="license", fields={"material_type": "business_license", "registered_address": "A"}),
        EvidenceRecord(evidence_id="iso", supplier_name=query.supplier_name, category=query.category, region=query.region, evidence_type="qualification", source_title="expired iso", expires_on=date(2026, 1, 1), fields={"material_type": "iso_9001", "registered_address": "B"}),
        EvidenceRecord(evidence_id="quality", supplier_name=query.supplier_name, category=query.category, region=query.region, evidence_type="qualification", source_title="quality", fields={"material_type": "quality_inspection"}),
    ]
    review = EvidenceGate(today=date(2026, 8, 11)).review(query, evidence)
    assert review.decision == "存在待处理风险项，暂不建议自动通过"


def test_hybrid_retriever_scopes_supplier_and_fuses_vector_ranking() -> None:
    query = SupplierQuery(supplier_name="Northstar Components GmbH", category="industrial_components", region="EU")
    results = HybridEvidenceRetriever().search(
        query=query,
        question="注册地址和 ISO 质量体系证书是否一致？",
        evidence=load_evidence_catalog(CATALOG),
        vector_ranked_ids=["northstar-contract-v1", "northstar-iso-9001-v1", "eurofast-iso-9001-v1"],
    )
    assert [result.evidence.evidence_id for result in results] == ["northstar-contract-v1", "northstar-iso-9001-v1"]
    assert results[0].vector_rank == 1


def test_service_only_allows_retrieved_citations() -> None:
    query = SupplierQuery(supplier_name="Northstar Components GmbH", category="industrial_components", region="EU")
    report = SupplierEvidenceService(gate=EvidenceGate(today=date(2026, 8, 11))).review_supplier(query, "核验必需材料与地址是否一致。", load_evidence_catalog(CATALOG))
    assert report.output_gate_passed
    assert report.retrieval_mode == "bm25"


def test_generated_report_is_blocked_when_it_cites_unknown_evidence() -> None:
    class UnsafeGenerator:
        def generate(self, *_args):
            return GeneratedEvidenceReport(
                summary="不应被接受的说明",
                cited_evidence_ids=["not-in-current-results"],
            )

    query = SupplierQuery(supplier_name="Northstar Components GmbH", category="industrial_components", region="EU")
    report = SupplierEvidenceService(gate=EvidenceGate(today=date(2026, 8, 11))).review_supplier(
        query, "核验材料。", load_evidence_catalog(CATALOG), report_generator=UnsafeGenerator()
    )
    assert report.generated_report is None
    assert "输出门禁拦截" in report.generated_report_status


def test_rerank_cannot_escape_retrieved_candidate_set() -> None:
    class UnsafeReranker:
        def rerank(self, *_args):
            return ["northstar-contract-v1", "invented-evidence"]

    query = SupplierQuery(supplier_name="Northstar Components GmbH", category="industrial_components", region="EU")
    report = SupplierEvidenceService(gate=EvidenceGate(today=date(2026, 8, 11))).review_supplier(
        query, "核验材料。", load_evidence_catalog(CATALOG), reranker=UnsafeReranker()
    )
    assert "候选集" in report.rerank_mode
    assert {item["evidence_id"] for item in report.retrieved_evidence} == {"northstar-iso-9001-v1", "northstar-contract-v1"}


def test_api_returns_traceable_report() -> None:
    import asyncio
    report = asyncio.run(create_supplier_review(SupplierReviewRequest(supplier_name="Northstar Components GmbH", category="industrial_components", region="EU")))
    assert report.review.missing_materials == ["quality_inspection"]
    assert report.output_gate_passed


def test_catalog_metadata_is_attached_to_ingestion_chunks() -> None:
    chunks = [ChunkRecord(id="chunk-1", doc_id="doc-1", text="certificate", page=1, start_offset=0, end_offset=11, metadata={"path": str(ROOT / "data/supplier_evidence/suppliers/northstar/northstar_iso_certificate.md")})]
    enriched = enrich_chunks_with_catalog(chunks, CATALOG)
    assert enriched[0].metadata["supplier_name"] == "Northstar Components GmbH"
    assert enriched[0].metadata["evidence_id"] == "northstar-iso-9001-v1"


def test_fixed_evaluation_covers_retrieval_and_gate_behaviour() -> None:
    summary = run_fixed_evaluation(ROOT / "evals/supplier_evidence_cases.jsonl", CATALOG)
    assert summary["passed"] == summary["total"] == 3


def test_evidence_detail_exposes_source_text() -> None:
    import asyncio
    detail = asyncio.run(get_evidence_detail("northstar-iso-9001-v1"))
    assert detail["evidence"]["source_version"] == "v1"
    assert "Northstar Components GmbH" in detail["source_text"]
