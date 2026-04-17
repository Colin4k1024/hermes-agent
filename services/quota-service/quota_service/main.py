"""FastAPI application entry point for Quota Service."""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from quota_service.config import settings
from quota_service.database import close_db, init_db
from quota_service.redis_client import close_redis, get_redis
from quota_service.routers import admin, quota
from quota_service.schemas import HealthResponse, InternalHealthResponse


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle: startup → init DB/Redis; shutdown → cleanup."""
    await init_db()
    # Warm up Redis connection
    r = await get_redis()
    await r.ping()
    await r.aclose()
    yield
    await close_db()
    await close_redis()


app = FastAPI(
    title="Quota Service",
    description="Token metering and role-based quota enforcement for Hermes Agent",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS (allow all for dev; tighten in production)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(quota.router)
app.include_router(admin.router)


@app.get("/health", response_model=HealthResponse, tags=["health"])
async def health() -> HealthResponse:
    """Full health check (DB + Redis)."""
    db_ok = False
    redis_ok = False
    try:
        from quota_service.database import async_session_factory
        async with async_session_factory() as s:
            await s.execute("SELECT 1")
        db_ok = True
    except Exception:
        pass

    try:
        r = await get_redis()
        await r.ping()
        await r.aclose()
        redis_ok = True
    except Exception:
        pass

    return HealthResponse(db_ok=db_ok, redis_ok=redis_ok)


@app.get("/internal/health", response_model=InternalHealthResponse, tags=["health"])
async def internal_health() -> InternalHealthResponse:
    """Lightweight internal health check (no DB/Redis calls)."""
    return InternalHealthResponse(ok=True)


def run() -> None:
    import uvicorn

    uvicorn.run(
        "quota_service.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
    )


if __name__ == "__main__":
    run()
