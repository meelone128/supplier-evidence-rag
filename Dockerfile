FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# The upstream starter also ships an optional Streamlit UI. SupplierEvidence
# serves only FastAPI, so keep the runtime image independent of Streamlit,
# pandas and pyarrow (large dependencies that are not imported here).
RUN pip install --upgrade pip && pip install \
    typer rich pyyaml pydantic pydantic-settings openai httpx \
    fastapi "uvicorn[standard]" qdrant-client beautifulsoup4 python-docx \
    langdetect lxml pypdf regex structlog requests tiktoken rapidfuzz \
    python-dotenv python-multipart

COPY . .

EXPOSE 8002
CMD ["uvicorn", "app.supplier_main:app", "--app-dir", "/app/app/backend", "--host", "0.0.0.0", "--port", "8002"]
