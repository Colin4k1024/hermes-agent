FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml /app/
COPY state_service /app/state_service
COPY alembic.ini /app/alembic.ini
COPY alembic /app/alembic
RUN pip install --no-cache-dir .

EXPOSE 8006
CMD ["sh", "-c", "alembic upgrade head && uvicorn state_service.main:app --host ${STATE_HOST:-0.0.0.0} --port ${STATE_PORT:-8006}"]
