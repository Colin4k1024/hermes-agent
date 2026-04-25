"""Async database wiring for State Service."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from state_service.config import settings
from state_service.models import Base


engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,
    pool_pre_ping=True,
    pool_size=settings.db_pool_size,
    max_overflow=20,
)

async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def init_db() -> None:
    if not settings.auto_create_schema:
        return
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def close_db() -> None:
    await engine.dispose()


async def health_check() -> bool:
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


async def current_migration_revision() -> str | None:
    """Return the Alembic revision stamped in the database, if present."""
    try:
        async with engine.connect() as conn:
            result = await conn.execute(text("SELECT version_num FROM alembic_version"))
            return result.scalar_one_or_none()
    except Exception:
        return None


async def readiness_check() -> dict:
    """Return dependency and migration readiness for Kubernetes probes."""
    db_ok = await health_check()
    revision = await current_migration_revision()
    return {
        "db_ok": db_ok,
        "migration_revision": revision,
        "expected_migration_revision": settings.expected_migration_revision,
        "migration_ok": revision == settings.expected_migration_revision,
    }


@asynccontextmanager
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    session = async_session_factory()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()
