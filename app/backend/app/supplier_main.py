"""Standalone API entrypoint for SupplierEvidence.

Unlike the upstream ChatKit demo, this service has no agent runtime dependency.
It exposes only the deterministic supplier-evidence workflow and can be run
before model credentials or Qdrant are configured.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import requests

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

from supplier_evidence.api import router as supplier_evidence_router  # noqa: E402
from cli.config import load_config  # noqa: E402

app = FastAPI(
    title="SupplierEvidence API",
    version="0.1.0",
    description="Evidence-grounded supplier admission and procurement review API.",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5172", "http://127.0.0.1:5172"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type"],
)
app.include_router(supplier_evidence_router)


@app.get("/health")
async def health_check() -> dict[str, str]:
    return {"status": "healthy", "service": "supplier-evidence"}


@app.get("/ready", response_model=None)
async def readiness_check():
    """Return ready only after the configured vector store is reachable.

    This is intentionally separate from ``/health``: the latter proves that
    FastAPI is alive, while this endpoint proves that the RAG retrieval path
    has its essential dependency available.
    """

    try:
        config_path = PROJECT_ROOT / os.getenv(
            "RAG_CONFIG", "configs/supplier_evidence.qdrant.yaml"
        )
        config = load_config(str(config_path))
        qdrant = config.vector_store.custom.qdrant
        if qdrant is None:
            raise ValueError("Qdrant configuration is required")
        response = requests.get(
            f"{qdrant.url.rstrip('/')}/collections/{qdrant.collection}", timeout=2
        )
        response.raise_for_status()
        points = response.json().get("result", {}).get("points_count", 0)
        return {
            "status": "ready",
            "service": "supplier-evidence",
            "vector_store": "qdrant",
            "collection": qdrant.collection,
            "vector_points": points,
        }
    except (OSError, ValueError, AttributeError, requests.RequestException) as error:
        return JSONResponse(
            status_code=503,
            content={
                "status": "not_ready",
                "service": "supplier-evidence",
                "reason": type(error).__name__,
            },
        )
