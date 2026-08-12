from __future__ import annotations

from pathlib import Path

from ingestion.types import ChunkRecord

from .catalog import load_evidence_catalog


def enrich_chunks_with_catalog(
    chunks: list[ChunkRecord], catalog_path: str | Path
) -> list[ChunkRecord]:
    """Attach supplier-scope and source-version metadata to every evidence chunk."""

    catalog = load_evidence_catalog(catalog_path)
    by_filename = {
        Path(record.source_location).name: record
        for record in catalog
    }
    for chunk in chunks:
        filename = Path(str(chunk.metadata.get("path", ""))).name
        record = by_filename.get(filename)
        if not record:
            continue
        chunk.metadata.update({
            "evidence_id": record.evidence_id,
            "supplier_name": record.supplier_name,
            "category": record.category,
            "region": record.region,
            "evidence_type": record.evidence_type,
            "source_version": record.source_version,
            "source_authority": record.authority,
            "source_location": record.source_location,
            "issued_on": record.issued_on.isoformat() if record.issued_on else None,
            "expires_on": record.expires_on.isoformat() if record.expires_on else None,
            "evidence_fields": record.fields,
        })
    return chunks
