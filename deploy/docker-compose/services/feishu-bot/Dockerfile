# Feishu Bot Service — FastAPI (local dev, reuse existing structure)

FROM python:3.11-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

RUN apt-get update && \
    apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/*

COPY services/feishu-bot/requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

COPY services/feishu-bot/ /app/

HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=5 \
    CMD curl -sf http://localhost:8005/health || exit 1

EXPOSE 8005

RUN useradd -r -m fbot && chown -R fbot:fbot /app
USER fbot

ENTRYPOINT ["python", "-m", "uvicorn"]
CMD ["fbot.main:app", "--host", "0.0.0.0", "--port", "8005"]