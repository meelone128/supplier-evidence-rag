from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from pydantic import BaseModel, Field


ALLOWED_UPLOAD_SUFFIXES = {".md", ".txt", ".csv", ".pdf", ".docx"}
MAX_UPLOAD_BYTES = 10 * 1024 * 1024


class PendingUploadStore:
    """Local staging area. Uploading does not imply indexing or model access."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.manifest = self.root / "manifest.json"

    def _read(self) -> list[dict[str, Any]]:
        return json.loads(self.manifest.read_text(encoding="utf-8")) if self.manifest.exists() else []

    def _write(self, items: list[dict[str, Any]]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self.manifest.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")

    def list(self) -> list[dict[str, Any]]:
        return self._read()

    def stage(self, original_name: str, data: bytes, metadata: "UploadEvidenceMetadata") -> dict[str, Any]:
        safe_name = Path(original_name).name
        suffix = Path(safe_name).suffix.lower()
        if suffix not in ALLOWED_UPLOAD_SUFFIXES:
            raise ValueError("仅支持 Markdown、TXT、CSV、PDF、Word 文档")
        if not data:
            raise ValueError("上传文件不能为空")
        if len(data) > MAX_UPLOAD_BYTES:
            raise ValueError("单个文件不能超过 10 MB")
        if metadata.contains_personal_data and not metadata.masking_confirmed:
            raise ValueError("检测到可能包含个人信息时，需先确认已完成脱敏后才能暂存")
        upload_id = str(uuid.uuid4())
        stored_name = f"{upload_id}{suffix}"
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / stored_name).write_bytes(data)
        item = {
            "id": upload_id,
            "original_name": re.sub(r"[\r\n]", "", safe_name),
            "stored_name": stored_name,
            "size_bytes": len(data),
            "status": "pending_index",
            "metadata": metadata.model_dump(),
            "privacy_status": "masked_confirmed" if metadata.masking_confirmed else "declared_no_personal_data",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        items = self._read(); items.append(item); self._write(items)
        return item


class UploadEvidenceMetadata(BaseModel):
    supplier_name: str = Field(min_length=2, max_length=160)
    category: str = Field(min_length=2, max_length=80)
    region: str = Field(min_length=2, max_length=80)
    evidence_type: str = Field(pattern="^(qualification|contract|historical_review)$")
    source_title: str = Field(min_length=2, max_length=200)
    source_version: str = Field(default="v1", min_length=1, max_length=50)
    authority: str = Field(pattern="^(official|contractual|internal)$")
    contains_personal_data: bool = False
    masking_confirmed: bool = False
    annotation_note: str = Field(default="", max_length=500)


def approve_upload_for_index(
    store: PendingUploadStore, upload_id: str, catalog_path: str | Path, source_root: str | Path
) -> dict[str, Any]:
    """Make staged data eligible for the next explicit index rebuild, not immediately searchable."""

    rows = store._read()
    item = next((row for row in rows if row["id"] == upload_id), None)
    if item is None:
        raise KeyError(upload_id)
    if item["status"] == "approved_for_index":
        return item
    metadata = item["metadata"]
    target_dir = Path(source_root) / "uploads"
    target_dir.mkdir(parents=True, exist_ok=True)
    target_name = f"{item['id']}_{item['original_name']}"
    source = store.root / item["stored_name"]
    target = target_dir / target_name
    if not source.exists():
        raise FileNotFoundError(item["original_name"])
    target.write_bytes(source.read_bytes())
    catalog_file = Path(catalog_path)
    catalog = json.loads(catalog_file.read_text(encoding="utf-8"))
    evidence_id = f"upload-{item['id']}"
    if not any(record.get("evidence_id") == evidence_id for record in catalog):
        catalog.append({
            "evidence_id": evidence_id,
            **metadata,
            "source_location": target_name,
            "fields": {"material_type": "uploaded_supporting_document", "upload_id": item["id"]},
        })
        catalog_file.write_text(json.dumps(catalog, ensure_ascii=False, indent=2), encoding="utf-8")
    item["status"] = "approved_for_index"
    item["approved_source_location"] = target_name
    store._write(rows)
    return item
