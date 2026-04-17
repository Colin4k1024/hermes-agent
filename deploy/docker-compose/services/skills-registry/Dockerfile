# Skills Registry — FastAPI (local dev, reuse existing structure)
# Multi-stage: dev (hot reload) | prod

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

COPY services/skills-registry/pyproject.toml /app/
RUN uv pip install --system --no-cache -e ".[dev]" 2>/dev/null || \
    (uv pip install --system --no-cache \
        fastapi uvicorn[standard] pydantic pydantic-settings \
        sqlalchemy asyncpg psycopg2-binary redis pyyaml httpx python-multipart \
        python-jose[cryptography] \
        pytest pytest-asyncio pytest-cov httpx aiosqlite)

COPY services/skills-registry/ /app/

HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=5 \
    CMD curl -sf http://localhost:8004/health || exit 1

EXPOSE 8004
CMD ["uvicorn", "skills_registry.main:app", "--host", "0.0.0.0", "--port", "8004", "--reload"]

# ── Prod stage ────────────────────────────────────────────────────────────────
FROM base AS prod
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/* && \
    pip install --no-cache-dir uv

COPY services/skills-registry/pyproject.toml /app/
RUN uv pip install --system --no-cache -e .

COPY services/skills-registry/ /app/

HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=5 \
    CMD curl -sf http://localhost:8004/health || exit 1

EXPOSE 8004
RUN useradd -r -m appuser || true
USER appuser
CMD ["uvicorn", "skills_registry.main:app", "--host", "0.0.0.0", "--port", "8004"]
