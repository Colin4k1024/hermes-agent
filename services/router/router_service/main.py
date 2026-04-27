"""Agent Router Service — FastAPI Application.

Hermes Enterprise SaaS Platform Control Plane
Routes user requests to Agent Pods via Redis routing table.
"""

import asyncio
import logging
import secrets
import time
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, HTTPException, Header, Request
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from . import redis_client as rc
from .schemas import (
    InternalRouteRequest,
    InternalRouteResponse,
    InternalHealthResponse,
    ErrorResponse,
    ChatCompletionsRequest,
)
from .scheduler import route_request, get_pool_health, _get_pod_url

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Lifespan — startup / shutdown
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: verify Redis. Shutdown: close connection pool."""
    logger.info("Agent Router starting on %s:%s", settings.host, settings.port)

    # Verify Redis connectivity
    if not rc.redis_health_check():
        logger.error("Redis health check failed on startup!")
    else:
        logger.info("Redis connected: %s", settings.redis_url)

    # Start background tasks
    idle_task = asyncio.create_task(_idle_recycler_loop())
    skill_task = asyncio.create_task(_skill_update_loop())

    yield

    # Shutdown
    idle_task.cancel()
    skill_task.cancel()
    rc.close_pool()
    await scheduler._close_http_client()
    logger.info("Agent Router shutdown complete")


async def _idle_recycler_loop() -> None:
    """Wrapper to run idle recycler with error handling."""
    try:
        from .scheduler import idle_recycler
        await idle_recycler(interval=settings.scheduler_interval)
    except asyncio.CancelledError:
        pass
    except Exception as exc:
        logger.error("Idle recycler crashed: %s", exc)


async def _skill_update_loop() -> None:
    """Wrapper to run skill subscriber with error handling."""
    try:
        from .scheduler import skill_update_subscriber
        await skill_update_subscriber()
    except asyncio.CancelledError:
        pass
    except Exception as exc:
        logger.error("Skill subscriber crashed: %s", exc)


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Agent Router",
    description=(
        "Hermes Enterprise SaaS — Agent Router Service.\n\n"
        "Routes user requests to Agent Pods via Redis routing table. "
        "Handles hot/cold pod scheduling, session locking, and "
        "cold-start coordination with Pod Sidecars."
    ),
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS — restrict to known origins in production; credentials require explicit origins
_cors_origins = (
    settings.cors_origins if hasattr(settings, "cors_origins") and settings.cors_origins
    else ([] if not settings.debug else ["http://localhost:3000"])
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=bool(_cors_origins),  # Only allow credentials when origins are explicitly set
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-User-ID", "X-Tenant-ID", "X-Session-ID", "X-Request-ID"],
)

# ---------------------------------------------------------------------------
# Health endpoints
# ---------------------------------------------------------------------------

@app.get(
    "/internal/health",
    response_model=InternalHealthResponse,
    tags=["Internal"],
    summary="Pool health and statistics",
)
async def internal_health() -> InternalHealthResponse:
    """Internal health check — returns pool statistics from Redis.

    Includes: pool_size, idle_pods, active_pods, unhealthy_pods.
    """
    return await get_pool_health()


@app.get(
    "/health",
    tags=["Health"],
    summary="Basic liveness",
)
async def health() -> dict:
    """Basic liveness probe."""
    return {
        "status": "ok",
        "service": "agent-router",
        "version": "0.1.0",
    }


@app.get(
    "/health/ready",
    tags=["Health"],
    summary="Readiness with Redis check",
)
async def health_ready() -> dict:
    """Readiness probe — includes Redis connectivity."""
    redis_ok = rc.redis_health_check()
    pool = await get_pool_health()
    return {
        "status": "ok" if redis_ok else "degraded",
        "service": "agent-router",
        "version": "0.1.0",
        "redis_connected": redis_ok,
        "idle_pods": pool.idle_pods,
        "active_pods": pool.active_pods,
    }


# ---------------------------------------------------------------------------
# Internal route endpoint (Feishu Bot calls this)
# ---------------------------------------------------------------------------

@app.post(
    "/internal/route",
    response_model=InternalRouteResponse,
    tags=["Internal"],
    summary="Route a user message to an Agent Pod",
    responses={
        409: {"model": ErrorResponse, "description": "Session already locked"},
        503: {"model": ErrorResponse, "description": "No pods available"},
    },
)
async def internal_route(req: InternalRouteRequest) -> InternalRouteResponse:
    """Route a user message to an Agent Pod.

    **Flow**:
    1. Acquire session lock (atomic SET NX EX, 30s TTL)
    2. Verify quota with Quota Service
    3. Hot path: return existing pod from Redis route:{user_id}
    4. Cold path: select idle pod, call Sidecar /internal/prepare, set route

    **reply_channel** (optional): Redis stream key for Feishu response chunks.
    If provided, Router will stream response chunks to this channel.
    """
    result = await route_request(req)

    if not result.success:
        if "Session already active" in (result.message or ""):
            raise HTTPException(status_code=409, detail=result.message)
        raise HTTPException(
            status_code=503,
            detail=result.message or "No pods available",
        )

    return result


# ---------------------------------------------------------------------------
# OpenAI-compatible proxy endpoints (passthrough to Agent Pod)
# ---------------------------------------------------------------------------

@app.post(
    "/v1/chat/completions",
    tags=["Proxy"],
    summary="OpenAI /v1/chat/completions proxy",
    response_model=None,
)
async def chat_completions(
    request: Request,
    authorization: str | None = Header(None, alias="Authorization"),
    x_user_id: str | None = Header(None, alias="X-User-ID"),
    x_tenant_id: str | None = Header(None, alias="X-Tenant-ID"),
    x_session_id: str | None = Header(None, alias="X-Session-ID"),
    x_request_id: str | None = Header(None, alias="X-Request-ID"),
) -> StreamingResponse | JSONResponse:
    """Proxy /v1/chat/completions to the assigned Agent Pod.

    Requires either:
    - JWT in Authorization header (validated by Auth Service)
    - X-User-ID header (internal calls only)

    Flow:
    1. Validate token / user_id
    2. Get pod from Redis route:{user_id}
    3. On miss: cold start
    4. Forward request to Pod :8642
    5. Stream response back (passthrough)
    """
    user_id = x_user_id if not authorization else None
    role = None
    quota_group = None
    if not user_id and authorization:
        # Validate JWT via Auth Service
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"{settings.auth_service_url}/users/me",
                    headers={"Authorization": authorization},
                    timeout=5.0,
                )
                if resp.status_code == 200:
                    user_data = resp.json()
                    user_id = user_data.get("id")
                    role = user_data.get("role")
                    quota_group = user_data.get("quota_group") or role
                else:
                    raise HTTPException(status_code=401, detail="Invalid token")
        except httpx.RequestError:
            raise HTTPException(status_code=503, detail="Auth Service unavailable")

    if not user_id:
        raise HTTPException(
            status_code=401,
            detail="Missing X-User-ID or Authorization header",
        )

    # Get or assign pod
    route_subject = x_session_id or user_id
    pod_id = rc.get_route(route_subject)
    if not pod_id:
        # Cold start
        route_resp = await route_request(
            InternalRouteRequest(
                user_id=user_id,
                message="",
                tenant_id=x_tenant_id or "default",
                session_id=x_session_id,
                request_id=x_request_id,
                runtime_context={
                    "tenant_id": x_tenant_id or "default",
                    "user_id": user_id,
                    "session_id": x_session_id,
                    "request_id": x_request_id,
                    "role": role,
                    "quota_group": quota_group,
                    "state_service_url": settings.state_service_url,
                    "state_token": settings.state_service_token,
                },
            )
        )
        if not route_resp.success:
            raise HTTPException(status_code=503, detail=route_resp.message)
        pod_id = route_resp.pod_id

    pod_url = _get_pod_url(pod_id)

    # Read raw request body for passthrough
    body = await request.body()

    # Forward to Pod
    headers = {}
    if authorization:
        headers["Authorization"] = authorization
    headers["X-User-ID"] = user_id
    headers["X-Tenant-ID"] = x_tenant_id or "default"
    if x_session_id:
        headers["X-Session-ID"] = x_session_id
    if x_request_id:
        headers["X-Request-ID"] = x_request_id
    headers["X-State-Service-URL"] = settings.state_service_url

    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            # Check if original request wants streaming
            # Heuristic: check body for "stream": true
            is_streaming = b'"stream"' in body and b"true" in body.lower()

            resp = await client.post(
                f"{pod_url}/v1/chat/completions",
                content=body,
                headers={
                    **headers,
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
            )

            if is_streaming or resp.headers.get("content-type", "").startswith("text/event-stream"):
                return StreamingResponse(
                    resp.aiter_bytes(),
                    media_type="text/event-stream",
                    headers={
                        "x-pod-id": pod_id,
                        "x-user-id": user_id,
                        "x-tenant-id": x_tenant_id or "default",
                        "x-session-id": x_session_id or "",
                    },
                )

            return JSONResponse(
                content=resp.json(),
                headers={
                    "x-pod-id": pod_id,
                    "x-user-id": user_id,
                    "x-tenant-id": x_tenant_id or "default",
                    "x-session-id": x_session_id or "",
                },
            )

    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Agent Pod timeout")
    except httpx.RequestError as exc:
        logger.error("Failed to proxy to pod %s: %s", pod_id, exc)
        raise HTTPException(status_code=502, detail=f"Pod unreachable: {exc}")


@app.post(
    "/v1/responses",
    tags=["Proxy"],
    summary="OpenAI /v1/responses proxy",
    response_model=None,
)
async def responses_endpoint(
    request: Request,
    authorization: str | None = Header(None, alias="Authorization"),
    x_user_id: str | None = Header(None, alias="X-User-ID"),
    x_tenant_id: str | None = Header(None, alias="X-Tenant-ID"),
    x_session_id: str | None = Header(None, alias="X-Session-ID"),
    x_request_id: str | None = Header(None, alias="X-Request-ID"),
) -> StreamingResponse | JSONResponse:
    """Proxy /v1/responses to the assigned Agent Pod. Same flow as chat/completions."""
    # Delegate to the same logic
    return await chat_completions(
        request,
        authorization,
        x_user_id,
        x_tenant_id,
        x_session_id,
        x_request_id,
    )


@app.get(
    "/v1/models",
    tags=["Proxy"],
    summary="List available models",
)
async def list_models() -> JSONResponse:
    """Return available models from Hermes Agent.

    Proxied from a healthy Pod. Falls back to static list in dev.
    """
    # Try to get model list from any active pod
    active_pods = rc.get_all_active_pods()
    if active_pods:
        pod_id = next(iter(active_pods))
        pod_url = _get_pod_url(pod_id)
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{pod_url}/v1/models")
                if resp.status_code == 200:
                    return JSONResponse(content=resp.json())
        except Exception:
            pass

    # Fallback for dev / no pods
    return JSONResponse(
        content={
            "object": "list",
            "data": [
                {
                    "id": "hermes-default",
                    "object": "model",
                    "created": 1700000000,
                    "owned_by": "hermes",
                }
            ],
        },
    )


# ---------------------------------------------------------------------------
# Admin / debug endpoints
# ---------------------------------------------------------------------------

@app.post(
    "/admin/pools/idle",
    tags=["Admin"],
    summary="Manually register a pod as idle",
)
async def register_idle_pod(
    pod_id: str,
    x_api_key: str = Header(..., alias="X-Api-Key"),
) -> dict:
    """Register a new idle pod (called by Pod startup probe or K8s init).

    Requires internal API key.
    """
    if not secrets.compare_digest(x_api_key, settings.internal_api_key):
        raise HTTPException(status_code=401, detail="Invalid API key")

    rc.add_pod_to_idle(pod_id)
    rc.set_pod_health(pod_id)
    logger.info("Registered idle pod: %s", pod_id)
    return {"pod_id": pod_id, "status": "idle"}


@app.delete(
    "/admin/routes/{user_id}",
    tags=["Admin"],
    summary="Force-delete a user's route",
)
async def delete_user_route(
    user_id: str,
    x_api_key: str = Header(..., alias="X-Api-Key"),
) -> dict:
    """Force-delete a user's route and release their pod (admin only)."""
    if not secrets.compare_digest(x_api_key, settings.internal_api_key):
        raise HTTPException(status_code=401, detail="Invalid API key")

    pod_id = rc.delete_route(user_id)
    if pod_id:
        rc.add_pod_to_idle(pod_id)
    rc.release_session_lock(user_id)
    logger.info("Admin deleted route for user %s (pod %s)", user_id, pod_id)
    return {"user_id": user_id, "released_pod": pod_id}


@app.get(
    "/debug/routes",
    tags=["Debug"],
    summary="List all active routes (debug only)",
)
async def debug_routes(
    x_api_key: str = Header(..., alias="X-Api-Key"),
) -> dict:
    """List all active routes and idle pods (debug endpoint)."""
    if not secrets.compare_digest(x_api_key, settings.internal_api_key):
        raise HTTPException(status_code=401, detail="Invalid API key")

    active_pods = rc.get_all_active_pods()
    idle_info = rc.peek_idle_pods(limit=100)

    routes = {}
    for pod_id in active_pods:
        user_id = rc.get_redis().get(f"{settings.key_pod_active}:{pod_id}")
        if user_id:
            routes[user_id] = pod_id

    return {
        "active_routes": routes,
        "idle_pods": [pod_id for pod_id, _ in idle_info],
        "pool_stats": {
            "total_active": len(active_pods),
            "total_idle": len(idle_info),
        },
    }


# ---------------------------------------------------------------------------
# Root
# ---------------------------------------------------------------------------

@app.get("/", tags=["Root"])
async def root() -> dict:
    return {
        "service": "agent-router",
        "version": "0.1.0",
        "docs": "/docs",
        "health": "/health",
        "internal_health": "/internal/health",
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "router_service.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
    )
