FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml /app/
COPY state_service /app/state_service
RUN pip install --no-cache-dir .

EXPOSE 8006
CMD ["uvicorn", "state_service.main:app", "--host", "0.0.0.0", "--port", "8006"]
