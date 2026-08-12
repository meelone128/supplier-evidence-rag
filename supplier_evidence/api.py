from __future__ import annotations

import json
import os
from pathlib import Path
import requests

from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from pydantic import BaseModel, Field

from .catalog import load_evidence_catalog
from .service import SupplierEvidenceReport, SupplierEvidenceService
from .types import SupplierQuery
from .vector_search import QdrantEvidenceRanker
from .reporting import EvidenceReportGenerator
from .reranking import EvidenceReranker
from .evaluation import run_fixed_evaluation
from .ted_review import TedReviewQueue
from .audit import AuditLog
from .privacy import scan_sensitive_data
from cli.config import load_config


router = APIRouter(prefix="/supplier-evidence", tags=["supplier-evidence"])
PROJECT_ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = PROJECT_ROOT / "data" / "supplier_evidence" / "evidence_catalog.json"
CONFIG_PATH = PROJECT_ROOT / os.getenv("RAG_CONFIG", "configs/supplier_evidence.qdrant.yaml")
TED_REVIEW_PATH = PROJECT_ROOT / "data" / "supplier_evidence" / "ted" / "review_queue.json"
PENDING_UPLOAD_ROOT = PROJECT_ROOT / "data" / "supplier_evidence" / "pending_uploads"
AUDIT_LOG_PATH = PROJECT_ROOT / "data" / "supplier_evidence" / "audit" / "events.jsonl"
CONFLICT_RESOLUTION_PATH = PROJECT_ROOT / "data" / "supplier_evidence" / "conflicts" / "resolutions.json"


class SupplierReviewRequest(SupplierQuery):
    question: str = Field(
        default="核验该供应商的准入材料、有效期与跨文档信息是否一致。",
        min_length=4,
    )
    generate_summary: bool = False
    enable_rerank: bool = False


class TedSyncRequest(SupplierQuery):
    limit: int = Field(default=5, ge=1, le=20)


class ConflictResolutionRequest(BaseModel):
    conflict_id: str = Field(min_length=4)
    status: str = Field(pattern="^(pending|confirmed|resolved)$")
    note: str = Field(default="", max_length=500)


def _service() -> SupplierEvidenceService:
    return SupplierEvidenceService(vector_ranker=QdrantEvidenceRanker(CONFIG_PATH))


@router.post("/reviews", response_model=SupplierEvidenceReport)
async def create_supplier_review(request: SupplierReviewRequest) -> SupplierEvidenceReport:
    try:
        evidence = load_evidence_catalog(CATALOG_PATH)
    except (OSError, ValueError) as error:
        raise HTTPException(status_code=500, detail="无法读取演示证据目录") from error
    report_generator = EvidenceReportGenerator(CONFIG_PATH) if request.generate_summary else None
    reranker = EvidenceReranker(CONFIG_PATH) if request.enable_rerank else None
    return _service().review_supplier(
        query=SupplierQuery(
            supplier_name=request.supplier_name,
            category=request.category,
            region=request.region,
        ),
        question=request.question,
        evidence=evidence,
        report_generator=report_generator,
        reranker=reranker,
    )


@router.get("/demo-suppliers")
async def list_demo_suppliers() -> dict[str, list[dict[str, str]]]:
    evidence = load_evidence_catalog(CATALOG_PATH)
    suppliers = sorted({
        (record.supplier_name, record.category or "", record.region or "")
        for record in evidence
    })
    return {
        "suppliers": [
            {"supplier_name": name, "category": category, "region": region}
            for name, category, region in suppliers
        ]
    }


@router.get("/evaluations/latest")
async def latest_evaluation() -> dict[str, object]:
    """Expose deterministic regression results without an LLM judge."""

    return run_fixed_evaluation(
        PROJECT_ROOT / "evals" / "supplier_evidence_cases.jsonl",
        CATALOG_PATH,
    )


@router.get("/index/status")
async def index_status() -> dict[str, object]:
    source_root = PROJECT_ROOT / "data" / "supplier_evidence"
    source_files = [
        path
        for path in source_root.rglob("*")
        if path.suffix in {".md", ".txt", ".csv", ".pdf", ".docx"}
        and "pending_uploads" not in path.parts
    ]
    try:
        config = load_config(str(CONFIG_PATH))
        qdrant = config.vector_store.custom.qdrant
        if qdrant is None:
            raise ValueError("Qdrant configuration is required")
        payload = requests.get(
            f"{qdrant.url.rstrip('/')}/collections/{qdrant.collection}", timeout=2
        ).json()
        points = payload.get("result", {}).get("points_count", 0)
        return {
            "ready": True,
            "source_files": len(source_files),
            "vector_points": points,
            "collection": qdrant.collection,
        }
    except (requests.RequestException, ValueError, AttributeError):
        return {
            "ready": False,
            "source_files": len(source_files),
            "vector_points": 0,
            "collection": "supplier_evidence",
        }


@router.get("/uploads/pending")
async def pending_uploads() -> dict[str, object]:
    from .uploads import PendingUploadStore
    return {"items": PendingUploadStore(PENDING_UPLOAD_ROOT).list()}


@router.get("/uploads/privacy-scan")
async def upload_privacy_note() -> dict[str, str]:
    return {"notice": "上传前扫描只提供风险提示；PDF/Word 及复杂表格仍需人工完成脱敏确认。"}


@router.get("/audit/events")
async def audit_events() -> dict[str, object]:
    return {"items": AuditLog(AUDIT_LOG_PATH).latest()}


@router.post("/uploads/stage")
async def stage_upload(
    file: UploadFile = File(...),
    supplier_name: str = Form(...),
    category: str = Form(...),
    region: str = Form(...),
    evidence_type: str = Form(...),
    source_title: str = Form(...),
    source_version: str = Form("v1"),
    authority: str = Form("internal"),
    contains_personal_data: bool = Form(False),
    masking_confirmed: bool = Form(False),
    annotation_note: str = Form(""),
) -> dict[str, object]:
    from .uploads import PendingUploadStore, UploadEvidenceMetadata
    try:
        metadata = UploadEvidenceMetadata(
            supplier_name=supplier_name, category=category, region=region,
            evidence_type=evidence_type, source_title=source_title,
            source_version=source_version, authority=authority,
            contains_personal_data=contains_personal_data,
            masking_confirmed=masking_confirmed,
            annotation_note=annotation_note,
        )
        data = await file.read()
        scan = scan_sensitive_data(file.filename or "upload", data)
        item = PendingUploadStore(PENDING_UPLOAD_ROOT).stage(file.filename or "upload", data, metadata)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    AuditLog(AUDIT_LOG_PATH).append("upload_staged", subject_id=item["id"], details={
        "filename": item["original_name"], "privacy_status": item["privacy_status"], "scan": scan,
    })
    return {"item": item, "scan": scan, "notice": "文件已进入待入库区；确认重建索引前不会参与检索或发送给模型。"}


@router.post("/uploads/pending/{upload_id}/approve")
async def approve_pending_upload(upload_id: str) -> dict[str, object]:
    from .uploads import PendingUploadStore, approve_upload_for_index
    try:
        item = approve_upload_for_index(
            PendingUploadStore(PENDING_UPLOAD_ROOT), upload_id, CATALOG_PATH,
            PROJECT_ROOT / "data" / "supplier_evidence",
        )
    except KeyError as error:
        raise HTTPException(status_code=404, detail="未找到待入库文件") from error
    except (ValueError, FileNotFoundError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    AuditLog(AUDIT_LOG_PATH).append("upload_approved", subject_id=upload_id, details={"filename": item["original_name"]})
    return {"item": item, "notice": "已纳入知识源；请单独确认重建索引后才会进入 Qdrant。"}


@router.post("/index/rebuild-approved")
async def rebuild_approved_index() -> dict[str, object]:
    """Explicitly send approved documents through chunking, embedding and Qdrant."""

    from .uploads import PendingUploadStore
    from .indexing import rebuild_approved_uploads
    try:
        result = rebuild_approved_uploads(PendingUploadStore(PENDING_UPLOAD_ROOT), CONFIG_PATH, CATALOG_PATH)
    except Exception as error:
        raise HTTPException(status_code=500, detail=f"重建索引失败：{type(error).__name__}") from error
    if not result["files"]:
        return {"result": result, "notice": "没有已批准且待索引的文件。"}
    AuditLog(AUDIT_LOG_PATH).append("approved_uploads_indexed", details=result)
    return {"result": result, "notice": f"已索引 {result['files']} 个文件、{result['chunks']} 个片段。"}


@router.get("/ted/review-queue")
async def ted_review_queue() -> dict[str, object]:
    return {"items": TedReviewQueue(TED_REVIEW_PATH).list()}


@router.post("/ted/sync")
async def sync_ted_candidates(request: TedSyncRequest) -> dict[str, object]:
    """Fetch a small public TED batch and queue only conservative name matches.

    This endpoint never indexes external records and never makes a compliance
    decision. The reviewer must explicitly confirm every candidate first.
    """

    from .ted import TedConnector, propose_supplier_matches

    try:
        connector = TedConnector(PROJECT_ROOT / "data" / "supplier_evidence" / "ted" / "cache")
        notices = connector.search_supplier(request.supplier_name, limit=request.limit)
    except requests.RequestException as error:
        raise HTTPException(status_code=502, detail="TED 公开接口暂时不可用，请稍后重试") from error

    queue = TedReviewQueue(TED_REVIEW_PATH)
    matches = propose_supplier_matches(request.supplier_name, notices)
    queued = [
        queue.add(match, request.category, request.region)
        for match in matches
        if match.status == "manual_confirmation_required"
    ]
    AuditLog(AUDIT_LOG_PATH).append("ted_sync", details={"supplier": request.supplier_name, "fetched": len(notices), "queued": len(queued)})
    return {
        "fetched_notices": len(notices),
        "candidate_matches": len(matches),
        "queued": len(queued),
        "notice": "TED 结果仅以候选形式进入人工审核队列，尚未成为知识源。",
    }


@router.post("/ted/review-queue/{review_id}/confirm")
async def confirm_ted_candidate(review_id: str) -> dict[str, object]:
    try:
        item = TedReviewQueue(TED_REVIEW_PATH).confirm(review_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="未找到待确认的 TED 候选记录") from error
    if item.get("evidence"):
        catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
        evidence = item["evidence"]
        if not any(row.get("evidence_id") == evidence.get("evidence_id") for row in catalog):
            catalog.append(evidence)
            CATALOG_PATH.write_text(json.dumps(catalog, ensure_ascii=False, indent=2), encoding="utf-8")
    AuditLog(AUDIT_LOG_PATH).append("ted_candidate_confirmed", subject_id=review_id, details={"supplier": item.get("target_supplier")})
    return {"item": item, "next_step": "已纳入本地证据目录；需要显式重建索引后才会进入向量检索。"}


@router.get("/evidence/{evidence_id}")
async def get_evidence_detail(evidence_id: str) -> dict[str, object]:
    """Return a traceable evidence card and its project-owned source text."""

    evidence = load_evidence_catalog(CATALOG_PATH)
    record = next((item for item in evidence if item.evidence_id == evidence_id), None)
    if record is None:
        raise HTTPException(status_code=404, detail="未找到证据记录")
    source_path = PROJECT_ROOT / "data" / "supplier_evidence" / record.source_location
    if not source_path.exists():
        matches = list((PROJECT_ROOT / "data" / "supplier_evidence").rglob(record.source_location))
        source_path = matches[0] if matches else source_path
    return {
        "evidence": record.model_dump(mode="json"),
        "source_text": source_path.read_text(encoding="utf-8") if source_path.exists() else None,
    }


@router.get("/evidence/{evidence_id}/chunks")
async def get_evidence_chunks(evidence_id: str) -> dict[str, object]:
    """Expose the persisted Qdrant chunks for one evidence item.

    This is an explainability endpoint: it reads only chunks already written to
    Qdrant and never invokes embeddings or a language model.
    """

    try:
        from qdrant_client import QdrantClient
        from qdrant_client.models import FieldCondition, Filter, MatchValue

        config = load_config(str(CONFIG_PATH))
        qdrant = config.vector_store.custom.qdrant
        if qdrant is None:
            raise ValueError("Qdrant configuration is required")
        client = QdrantClient(url=qdrant.url, api_key=qdrant.api_key, timeout=3)
        points, _ = client.scroll(
            collection_name=qdrant.collection,
            scroll_filter=Filter(
                must=[FieldCondition(key="evidence_id", match=MatchValue(value=evidence_id))]
            ),
            limit=100,
            with_payload=True,
            with_vectors=False,
        )
        chunks: list[dict[str, object]] = []
        seen: set[tuple[str, str]] = set()
        duplicate_points = 0
        for point in points:
            payload = point.payload or {}
            doc_id = str(payload.get("doc_id", ""))
            text = str(payload.get("text", ""))
            key = (doc_id, text)
            if key in seen:
                duplicate_points += 1
                continue
            seen.add(key)
            chunks.append({
                "chunk_id": str(point.id),
                "doc_id": doc_id,
                "text": text,
                "metadata": {key: value for key, value in payload.items() if key not in {"text", "doc_id"}},
            })
        return {
            "evidence_id": evidence_id,
            "chunks": chunks,
            "storage": "qdrant",
            "duplicate_points_collapsed": duplicate_points,
        }
    except (ValueError, AttributeError, requests.RequestException) as error:
        raise HTTPException(status_code=503, detail=f"分片索引暂不可用：{type(error).__name__}") from error
    except Exception as error:
        raise HTTPException(status_code=503, detail=f"分片索引暂不可用：{type(error).__name__}") from error


def _read_conflict_resolutions() -> dict[str, dict[str, str]]:
    if not CONFLICT_RESOLUTION_PATH.exists():
        return {}
    payload = json.loads(CONFLICT_RESOLUTION_PATH.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


@router.get("/conflicts/resolutions")
async def list_conflict_resolutions() -> dict[str, object]:
    return {"items": _read_conflict_resolutions()}


@router.put("/conflicts/resolutions")
async def save_conflict_resolution(request: ConflictResolutionRequest) -> dict[str, object]:
    resolutions = _read_conflict_resolutions()
    resolutions[request.conflict_id] = {"status": request.status, "note": request.note}
    CONFLICT_RESOLUTION_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFLICT_RESOLUTION_PATH.write_text(
        json.dumps(resolutions, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    AuditLog(AUDIT_LOG_PATH).append(
        "conflict_resolution_updated",
        subject_id=request.conflict_id,
        details={"status": request.status},
    )
    return {"conflict_id": request.conflict_id, **resolutions[request.conflict_id]}
