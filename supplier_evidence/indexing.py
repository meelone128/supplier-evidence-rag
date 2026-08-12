from __future__ import annotations

from pathlib import Path

from cli.config import load_config
from ingestion.pipeline import clean_text, embed_texts_concurrent, load_docs
from ingestion.chunkers.hybrid import hybrid_chunk
from ingestion.types import Page
from stores.base import Chunk, make_store_from_config

from .ingestion import enrich_chunks_with_catalog
from .uploads import PendingUploadStore


def rebuild_approved_uploads(
    upload_store: PendingUploadStore, config_path: str | Path, catalog_path: str | Path
) -> dict[str, int]:
    """Explicitly index only approved upload records, then mark them indexed.

    This function performs model and Qdrant calls. It is intentionally never
    called by the upload/approval paths.
    """

    pending = [item for item in upload_store.list() if item.get("status") == "approved_for_index"]
    if not pending:
        return {"files": 0, "chunks": 0}
    cfg = load_config(str(config_path))
    source_root = Path(catalog_path).parent
    paths = [str(source_root / "uploads" / item["approved_source_location"]) for item in pending]
    docs = load_docs(paths, cfg.data.include_extensions, [])
    for document in docs:
        document.text = clean_text(document.text)
        document.pages = [Page(number=page.number, text=clean_text(page.text)) for page in document.pages]
    chunks = [
        chunk
        for document in docs
        for chunk in hybrid_chunk(document, cfg.chunking.target_token_range, cfg.chunking.overlap_tokens)
    ]
    chunks = enrich_chunks_with_catalog(chunks, catalog_path)
    embeddings = embed_texts_concurrent(
        [chunk.text for chunk in chunks], cfg.embeddings.model, cfg.embeddings.batch_size, cfg
    )
    store = make_store_from_config(cfg)
    store.upsert([
        Chunk(id=chunk.id, doc_id=chunk.doc_id, text=chunk.text, embedding=embeddings[index], metadata=chunk.metadata)
        for index, chunk in enumerate(chunks)
    ])
    rows = upload_store._read()
    ids = {item["id"] for item in pending}
    for item in rows:
        if item["id"] in ids:
            item["status"] = "indexed"
    upload_store._write(rows)
    return {"files": len(pending), "chunks": len(chunks)}
