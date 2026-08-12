from __future__ import annotations

from pathlib import Path

from .types import SupplierQuery


class QdrantEvidenceRanker:
    """Optional semantic retrieval leg for the supplier evidence workbench.

    The service continues with lexical retrieval when the vector collection or
    model connection is not ready. This keeps the evidence gate available, but
    the response explicitly reports the retrieval mode.
    """

    def __init__(self, config_path: str | Path) -> None:
        self.config_path = str(config_path)

    def rank(self, query: SupplierQuery, question: str, limit: int = 12) -> list[str]:
        try:
            return self._rank(query, question, limit)
        except Exception:
            # Network and model errors must never create a fabricated vector rank.
            # The caller falls back to BM25 and still applies the evidence gate.
            return []

    def _rank(self, query: SupplierQuery, question: str, limit: int) -> list[str]:
        from qdrant_client.models import FieldCondition, Filter, MatchValue

        from cli.config import load_config
        from cli.env_utils import build_openai_client
        from stores.custom_qdrant import QdrantStore

        cfg = load_config(self.config_path)
        client = build_openai_client(cfg)
        embedding_request: dict[str, object] = {
            "model": cfg.embeddings.model,
            "input": f"{query.supplier_name} {query.category} {query.region} {question}",
        }
        if cfg.embeddings.dimensions:
            embedding_request["dimensions"] = cfg.embeddings.dimensions
        vector = client.embeddings.create(**embedding_request).data[0].embedding
        store = QdrantStore(cfg)
        scope = Filter(must=[
            FieldCondition(key="supplier_name", match=MatchValue(value=query.supplier_name)),
            FieldCondition(key="category", match=MatchValue(value=query.category)),
            FieldCondition(key="region", match=MatchValue(value=query.region)),
        ])
        response = store.client.query_points(
            collection_name=store.collection,
            query=vector,
            query_filter=scope,
            limit=limit,
            with_payload=["evidence_id"],
            with_vectors=False,
        )
        # A document may have several chunks in Qdrant. The hybrid retriever
        # ranks evidence records, not chunks, so keep only the first (best)
        # occurrence of each evidence id while preserving vector rank order.
        ranked_ids: list[str] = []
        seen: set[str] = set()
        for point in response.points:
            evidence_id = str(point.payload.get("evidence_id", "")) if point.payload else ""
            if evidence_id and evidence_id not in seen:
                ranked_ids.append(evidence_id)
                seen.add(evidence_id)
        return ranked_ids
