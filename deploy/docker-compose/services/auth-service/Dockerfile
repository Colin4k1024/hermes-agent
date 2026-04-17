# Auth Service — FastAPI
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

# Install uv for fast dependency installation
RUN pip install --no-cache-dir uv

COPY services/auth-service/pyproject.toml /app/
RUN uv pip install --system --no-cache -e ".[dev]" 2>/dev/null || \
    (uv pip install --system --no-cache \
        fastapi uvicorn[standard] pydantic pydantic-settings \
        python-jose[cryptography] httpx asyncpg sqlalchemy redis && \
    uv pip install --system --no-cache \
        pytest pytest-asyncio pytest-cov httpx)

# Copy source (bind mount from host in compose)
COPY services/auth-service/ /app/

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=5 \
    CMD curl -sf http://localhost:8001/health || exit 1

EXPOSE 8001
CMD ["uvicorn", "auth_service.main:app", "--host", "0.0.0.0", "--port", "8001", "--reload"]

# ── Prod stage ────────────────────────────────────────────────────────────────
FROM base AS prod
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/* && \
    pip install --no-cache-dir uv

COPY services/auth-service/pyproject.toml /app/
RUN uv pip install --system --no-cache -e .

COPY services/auth-service/ /app/

HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=5 \
    CMD curl -sf http://localhost:8001/health || exit 1

EXPOSE 8001
RUN useradd -r -m appuser || true
USER appuser
CMD ["uvicorn", "auth_service.main:app", "--host", "0.0.0.0", "--port", "8001"]
