"""
Auth Service — FastAPI Main Application
"""
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from auth_service.config import settings
from auth_service.database import init_db
from auth_service.redis_client import check_redis, close_redis
from auth_service.routers import auth_router, users_router, tokens_router, internal_router, admin_router, oidc_router
from auth_service.schemas import HealthResponse


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    try:
        await init_db()
    except Exception as e:
        print(f"[warn] Database init failed (may already exist): {e}")
    yield
    # Shutdown
    await close_redis()


app = FastAPI(
    title="Hermes Auth Service",
    description="JWT + OIDC + Per-user API Token authentication",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(auth_router)
app.include_router(users_router)
app.include_router(tokens_router)
app.include_router(internal_router)
app.include_router(admin_router)
app.include_router(oidc_router)


@app.get("/")
async def root():
    return {
        "service": settings.SERVICE_NAME,
        "version": "0.1.0",
        "status": "running",
    }


@app.get("/health", response_model=HealthResponse)
async def health():
    db_status = "ok"
    redis_status = "ok" if await check_redis() else "degraded"
    return HealthResponse(status="ok", database=db_status, redis=redis_status)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "auth_service.main:app",
        host="0.0.0.0",
        port=settings.SERVICE_PORT,
        reload=True,
    )
