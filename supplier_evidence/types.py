from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field


class SupplierQuery(BaseModel):
    supplier_name: str = Field(min_length=2)
    category: str = Field(min_length=2)
    region: str = Field(min_length=2)


class EvidenceRecord(BaseModel):
    """A citable, normalized fact extracted from an evidence document."""

    evidence_id: str
    supplier_name: str
    category: str | None = None
    region: str | None = None
    evidence_type: Literal[
        "qualification", "contract", "historical_review", "procurement_notice", "policy"
    ]
    source_title: str
    source_version: str = "v1"
    source_location: str = "page 1"
    authority: Literal["official", "contractual", "internal", "public"] = "internal"
    issued_on: date | None = None
    expires_on: date | None = None
    fields: dict[str, Any] = Field(default_factory=dict)


class Citation(BaseModel):
    evidence_id: str
    source_title: str
    source_version: str
    source_location: str


class Finding(BaseModel):
    code: str
    severity: Literal["info", "medium", "high"]
    message: str
    citations: list[Citation] = Field(default_factory=list)
    # Machine-readable evidence comparison. This keeps a conflict explainable
    # in the UI without parsing a natural-language finding message.
    metadata: dict[str, Any] = Field(default_factory=dict)
