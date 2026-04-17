# Agent Router Service — Dockerfile
# Multi-stage build, Python 3.11+

FROM python:3.11-slim AS builder

WORKDIR /app
RUN pip install --no-cache-dir --upgrade pip

COPY pyproject.toml requirements.txt ./
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ---------------------------------------------------------------------------

FROM python:3.11-slim

WORKDIR /app

# Install runtime dependencies only
COPY --from=builder /install /usr/local

COPY router_service/ ./router_service/

# Run as non-root
RUN useradd --create-home --shell /bin/bash router && \
    chown -R router:router /app
USER router

ENV PYTHONPATH=/app
ENV ROUTER_HOST=0.0.0.0
ENV ROUTER_PORT=8002
ENV ROUTER_DEBUG=false

EXPOSE 8002

CMD ["python", "-m", "router_service.main"]
