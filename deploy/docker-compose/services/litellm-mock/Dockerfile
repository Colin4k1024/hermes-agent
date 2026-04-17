# LiteLLM Proxy — Mock LLM endpoint for local development
# Serves as a stand-in for the real intranet LLM service.

FROM python:3.11-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

RUN apt-get update && \
    apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/*

# Install LiteLLM
RUN pip install --no-cache-dir \
    'litellm[proxy]==1.51.0' \
    'redis>=5.0.0'

# LiteLLM config is mounted via volume in compose
COPY services/litellm-mock/config.yaml /app/config.yaml

EXPOSE 4000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=5 \
    CMD wget -qO- http://localhost:4000/health || exit 1

# Run as non-root
RUN useradd -r -m litellm && chown -R litellm:litellm /