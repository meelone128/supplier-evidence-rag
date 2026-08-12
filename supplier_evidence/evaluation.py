from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .catalog import load_evidence_catalog
from .rules import EvidenceGate
from .service import SupplierEvidenceService
from .types import SupplierQuery


def run_fixed_evaluation(cases_path: str | Path, catalog_path: str | Path) -> dict[str, Any]:
    """Run reproducible business cases without an LLM judge.

    This is intentionally deterministic: failures show whether retrieval,
    material completeness, conflict detection, or refusal behaviour regressed.
    """

    cases = [json.loads(line) for line in Path(cases_path).read_text(encoding="utf-8").splitlines() if line]
    evidence = load_evidence_catalog(catalog_path)
    service = SupplierEvidenceService(gate=EvidenceGate())
    results: list[dict[str, Any]] = []
    for case in cases:
        query = SupplierQuery(
            supplier_name=case["supplier_name"], category=case["category"], region=case["region"]
        )
        report = service.review_supplier(query, case["question"], evidence)
        retrieved_ids = [item["evidence_id"] for item in report.retrieved_evidence]
        finding_codes = {finding.code for finding in report.review.findings}
        conflict_codes = {conflict.code for conflict in report.review.conflicts}
        checks = {
            "evidence": set(case["expected_evidence_ids"]).issubset(retrieved_ids),
            "missing_materials": report.review.missing_materials == case["expected_missing_materials"],
            "decision": report.review.decision == case["expected_decision"],
            "findings": set(case.get("expected_finding_codes", [])).issubset(finding_codes),
            "conflicts": set(case.get("expected_conflict_codes", [])).issubset(conflict_codes),
            "output_gate": report.output_gate_passed == case.get("expected_output_gate", report.output_gate_passed),
        }
        results.append({"id": case["id"], "passed": all(checks.values()), "checks": checks})
    passed = sum(item["passed"] for item in results)
    metric_keys = ("evidence", "missing_materials", "findings", "conflicts", "decision", "output_gate")
    metrics = {
        key: {
            "passed": sum(bool(item["checks"].get(key)) for item in results),
            "total": len(results),
        }
        for key in metric_keys
    }
    for item in metrics.values():
        item["rate"] = item["passed"] / item["total"] if item["total"] else 0
    return {
        "total": len(results),
        "passed": passed,
        "pass_rate": passed / len(results) if results else 0,
        "metrics": metrics,
        "results": results,
    }
