FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source
COPY fbot/ fbot/

# Non-root user
RUN useradd -m -r fbot && chown -R fbot:fbot /app
USER fbot

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import httpx; httpx.get('http://localhost:8005/health').raise_for_status()"

EXPOSE 8005

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# In K8s, inject FBOT_INSTANCE_ID via downward API:
# env:
#   - name: FBOT_INSTANCE_ID
#     valueFrom:
#       fieldRef:
#         fieldPath: metadata.name
ENTRYPOINT ["python", "-m", "uvicorn"]
CMD ["fbot.main:app", "--host", "0.0.0.0", "--port", "8005"]
