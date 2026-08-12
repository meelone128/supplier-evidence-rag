from __future__ import annotations

import json
from pathlib import Path
from typing import Sequence

from .retrieval import RetrievalResult
from .types import SupplierQuery


class EvidenceReranker:
    """Optional LLM reranker constrained to the already retrieved evidence ids."""

    def __init__(self, config_path: str | Path) -> None:
        self.config_path = str(config_path)

    def rerank(
        self, query: SupplierQuery, question: str, results: list[RetrievalResult]
    ) -> list[str]:
        from cli.config import load_config
        from cli.env_utils import build_openai_client

        allowed_ids = [result.evidence.evidence_id for result in results]
        if len(allowed_ids) < 2:
            return allowed_ids
        candidates = [
            {
                "evidence_id": result.evidence.evidence_id,
                "title": result.evidence.source_title,
                "type": result.evidence.evidence_type,
                "fields": result.evidence.fields,
            }
            for result in results
        ]
        instruction = {
            "task": "按与供应商核验问题的相关性重排候选证据。",
            "supplier_scope": query.model_dump(),
            "question": question,
            "candidates": candidates,
            "constraints": [
                "只允许返回给定的 evidence_id。",
                "不得添加、删除或修改证据内容。",
                "严格返回 JSON：{\"ranked_evidence_ids\":[...] }。",
            ],
        }
        cfg = load_config(self.config_path)
        client = build_openai_client(cfg)
        response = client.chat.completions.create(
            model=cfg.synthesis.model,
            temperature=0,
            messages=[
                {"role": "system", "content": "你是受约束的采购证据重排序器。"},
                {"role": "user", "content": json.dumps(instruction, ensure_ascii=False)},
            ],
        )
        content = (response.choices[0].message.content or "{}").strip()
        if content.startswith("```"):
            content = content.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        ranked = json.loads(content).get("ranked_evidence_ids", [])
        if not isinstance(ranked, list) or any(item not in allowed_ids for item in ranked):
            return allowed_ids
        # Preserve every RRF candidate even if the model omits one.
        return list(dict.fromkeys([*ranked, *allowed_ids]))


def apply_rerank_order(results: list[RetrievalResult], ranked_ids: Sequence[str]) -> list[RetrievalResult]:
    by_id = {result.evidence.evidence_id: result for result in results}
    return [by_id[evidence_id] for evidence_id in ranked_ids if evidence_id in by_id]
