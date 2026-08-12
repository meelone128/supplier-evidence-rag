from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import Iterable

from pydantic import BaseModel, Field

from .types import Citation, EvidenceRecord, Finding, SupplierQuery


DEFAULT_REQUIRED_MATERIALS = {
    "industrial_components": {"business_license", "iso_9001", "quality_inspection"}
}
WATCHED_FIELDS = {"registered_address", "legal_name", "certificate_scope"}


def _citation(record: EvidenceRecord) -> Citation:
    return Citation(
        evidence_id=record.evidence_id,
        source_title=record.source_title,
        source_version=record.source_version,
        source_location=record.source_location,
    )


class SupplierReview(BaseModel):
    query: SupplierQuery
    evidence_score: int = Field(ge=0, le=100)
    risk_score: int = Field(ge=0, le=100)
    evidence_score_breakdown: dict[str, int] = Field(default_factory=dict)
    decision: str
    missing_materials: list[str] = Field(default_factory=list)
    conflicts: list[Finding] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)
    evidence: list[Citation] = Field(default_factory=list)


class EvidenceGate:
    """A deterministic pre-generation gate, not a legal or credit decision."""

    def __init__(self, today: date | None = None) -> None:
        self.today = today or date.today()

    def review(self, query: SupplierQuery, evidence: Iterable[EvidenceRecord]) -> SupplierReview:
        matched = [
            record for record in evidence
            if record.supplier_name.casefold() == query.supplier_name.casefold()
            and (record.category is None or record.category == query.category)
            and (record.region is None or record.region == query.region)
        ]
        required = DEFAULT_REQUIRED_MATERIALS.get(query.category, set())
        supplied = {
            str(record.fields["material_type"])
            for record in matched
            if record.fields.get("material_type")
        }
        missing = sorted(required - supplied)
        findings = self._validity_findings(matched)
        conflicts = self._conflicts(matched)
        if missing:
            findings.append(Finding(
                code="missing_required_material",
                severity="high",
                message="缺少必需材料：" + "、".join(missing),
            ))

        authoritative = sum(record.authority in {"official", "contractual"} for record in matched)
        document_coverage = min(25, len(matched) * 5)
        material_coverage = round(25 * len(required & supplied) / len(required)) if required else 0
        authority_bonus = min(15, authoritative * 5)
        conflict_penalty = min(20, len(conflicts) * 10)
        missing_penalty = min(20, len(missing) * 7)
        evidence_score = 35 + document_coverage + material_coverage + authority_bonus
        evidence_score -= conflict_penalty + missing_penalty
        evidence_score = max(0, min(100, evidence_score))
        risk_score = min(100, len(missing) * 25 + len(conflicts) * 20 + sum(
            30 if item.code == "expired_material" else 10 for item in findings
        ))
        if not matched:
            decision = "证据不足，需补充供应商材料后再核验"
        elif evidence_score < 60:
            decision = "证据不足或存在重大缺口，建议人工复核"
        elif risk_score >= 40 or conflicts or any(item.code == "expired_material" for item in findings):
            decision = "存在待处理风险项，暂不建议自动通过"
        else:
            decision = "现有材料满足演示规则，可进入人工准入复核"
        return SupplierReview(
            query=query,
            evidence_score=evidence_score,
            risk_score=risk_score,
            evidence_score_breakdown={
                "base_score": 35,
                "document_coverage": document_coverage,
                "material_coverage": material_coverage,
                "authority_bonus": authority_bonus,
                "conflict_penalty": -conflict_penalty,
                "missing_material_penalty": -missing_penalty,
            },
            decision=decision,
            missing_materials=missing,
            conflicts=conflicts,
            findings=findings,
            evidence=[_citation(record) for record in matched],
        )

    def _validity_findings(self, evidence: list[EvidenceRecord]) -> list[Finding]:
        findings: list[Finding] = []
        for record in evidence:
            if record.expires_on and record.expires_on < self.today:
                findings.append(Finding(
                    code="expired_material",
                    severity="high",
                    message=f"材料已过期：{record.source_title}",
                    citations=[_citation(record)],
                ))
            elif record.expires_on and (record.expires_on - self.today).days <= 90:
                findings.append(Finding(
                    code="expiring_material",
                    severity="medium",
                    message=f"材料将在 90 天内到期：{record.source_title}",
                    citations=[_citation(record)],
                ))
        return findings

    def _conflicts(self, evidence: list[EvidenceRecord]) -> list[Finding]:
        values: dict[str, dict[str, list[EvidenceRecord]]] = defaultdict(lambda: defaultdict(list))
        for record in evidence:
            for field, value in record.fields.items():
                if field in WATCHED_FIELDS and value not in {None, ""}:
                    values[field][str(value).strip()].append(record)
        return [
            Finding(
                code="conflicting_evidence",
                severity="medium",
                message=f"字段“{field}”存在相互不一致的证据，需人工核验。",
                citations=[_citation(record) for group in groups.values() for record in group],
                metadata={
                    "field": field,
                    "values": {
                        value: [record.evidence_id for record in records]
                        for value, records in groups.items()
                    },
                },
            )
            for field, groups in values.items()
            if len(groups) > 1
        ]
