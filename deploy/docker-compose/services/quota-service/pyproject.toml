# Quota Service — FastAPI
# Multi-stage: dev (hot reload) | prod (optimized)

FROM python:3.11-slim AS base
WORKDIR /app
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# ── Dev stage ────────────────────────────────────────────────────────────────
FROM base AS dev
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv

COPY services/quota-service/pyproject.toml /app/
RUN uv pip install --system --no-cache -e . 2>/dev/null || \
    (uv pip install --system --no-cache \
        fastapi uvicorn[standard] pydantic pydantic-settings \
        asyncpg sqlalchemy psycopg2-binary redis httpx pytest pytest-asyncio)

COPY services/quota-service/ /app/

HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=5 \
    CMD curl -sf http://localhost:8003/health || exit 1

EXPOSE 8003
CMD ["uvicorn", "quota_service.main:app", "--host", "0.0.0.0", "--port", "8003", "--reload"]

# ── Prod stage ────────────────────────────────────────────────────────────────
FROM base AS prod
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/* && \
    pip install --no-cache-dir uv

COPY services/quota-service/pyproject.toml /app/
RUN uv pip install --system --no-cache -e .

COPY services/quota-service/ /app/

HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=5 \
    CMD curl -sf http://localhost:8003/health || exit 1

EXPOSE 8003
RUN useradd -r -m appuser || true
USER appuser
CMD ["uvicorn", "quota_service.main:app", "--host", "0.0.0.0", "--port", "8003"]
