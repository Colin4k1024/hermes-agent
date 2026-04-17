"""Skills Registry Service — FastAPI Application.

Hermes Enterprise SaaS Platform Control Plane
Manages org-level Skills CRUD, version control, NAS storage, and hot-update notifications.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .database import health_check as db_health_check, init_db
from .file_storage import get_storage
from .redis_publisher import redis_health_check
from .routers import admin, internal, skills
from .schemas import HealthResponse


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: initialize DB tables. Shutdown: cleanup resources."""
    # Startup
    await init_db()
    yield
    # Shutdown — close Redis pool
    from . import redis_publisher

    if redis_publisher._redis_pool:
        await redis_publisher._redis_pool.aclose()
        redis_publisher._redis_pool = None


app = FastAPI(
    title="Skills Registry",
    description=(
        "Hermes Enterprise SaaS — Skills Registry Service.\n\n"
        "Manages org-level Skills: CRUD, version control, NAS file storage, "
        "and Redis PubSub hot-update notifications to Agent Pods."
    ),
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS for Admin Console frontend (Phase 1 dev: allow all)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount routers
app.include_router(skills.router)
app.include_router(admin.router)
app.include_router(internal.router)


@app.get("/health", response_model=HealthResponse, tags=["Health"])
async def health() -> HealthResponse:
    """Full health check including DB, storage, and Redis."""
    db_ok = await db_health_check()
    storage_ok = get_storage().health_check()
    redis_ok = await redis_health_check()
    return HealthResponse(
        db_ok=db_ok,
        storage_ok=storage_ok,
        redis_ok=redis_ok,
        version="0.1.0",
    )


@app.get("/", tags=["Root"])
async def root() -> dict:
    return {
        "service": "skills-registry",
        "version": "0.1.0",
        "docs": "/docs",
        "health": "/health",
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "skills_registry.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
    )
