from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field

from .rules import SupplierReview
from .retrieval import RetrievalResult


class GeneratedEvidenceReport(BaseModel):
    """A concise narrative that is only valid when every cited id was retrieved."""

    summary: str = Field(min_length=1, max_length=700)
    recommended_actions: list[str] = Field(default_factory=list, max_length=5)
    cited_evidence_ids: list[str] = Field(default_factory=list)


class EvidenceReportGenerator:
    def __init__(self, config_path: str | Path) -> None:
        self.config_path = str(config_path)

    def generate(
        self, review: SupplierReview, retrieved: list[RetrievalResult]
    ) -> GeneratedEvidenceReport:
        """Generate a Chinese summary with an OpenAI-compatible chat endpoint.

        The output stays untrusted until SupplierEvidenceService verifies that all
        citation ids belong to the current retrieval result.
        """

        from cli.config import load_config
        from cli.env_utils import build_openai_client

        cfg = load_config(self.config_path)
        evidence = [
            {
                "evidence_id": item.evidence.evidence_id,
                "source_title": item.evidence.source_title,
                "evidence_type": item.evidence.evidence_type,
                "source_version": item.evidence.source_version,
                "fields": item.evidence.fields,
                "issued_on": str(item.evidence.issued_on or ""),
                "expires_on": str(item.evidence.expires_on or ""),
            }
            for item in retrieved
        ]
        prompt = {
            "task": "基于给定证据生成供应商准入核验说明。",
            "constraints": [
                "仅陈述输入中的事实，不推断信用、法律或制裁结论。",
                "不得称供应商已经自动通过。",
                "summary 使用中文，最多 220 字。",
                "cited_evidence_ids 只能使用给定 evidence_id。",
                "推荐动作应优先处理缺失材料、过期或冲突。",
                "必须返回严格 JSON：summary、recommended_actions、cited_evidence_ids。",
            ],
            "rule_review": review.model_dump(mode="json"),
            "evidence": evidence,
        }
        client = build_openai_client(cfg)
        response = client.chat.completions.create(
            model=cfg.synthesis.model,
            messages=[
                {"role": "system", "content": "你是采购证据核验助手，只能依据提供的证据回答。"},
                {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
            ],
            temperature=0,
        )
        content = response.choices[0].message.content or "{}"
        if content.startswith("```"):
            content = content.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        return GeneratedEvidenceReport.model_validate_json(content)
