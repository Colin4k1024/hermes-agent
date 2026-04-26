"""Core scheduling logic for Agent Router.

Implements hot/cold pod routing, session locking, and cold-start coordination
with the Pod Sidecar /internal/prepare endpoint.
"""

import asyncio
import hashlib
import logging
import time
from typing import TYPE_CHECKING

import httpx

from .config import settings
from . import redis_client as rc
from .schemas import (
    InternalRouteRequest,
    InternalRouteResponse,
    InternalPrepareRequest,
    InternalPrepareResponse,
    QuotaCheckRequest,
    QuotaCheckResponse,
    RouteSource,
    PodStatus,
    InternalHealthResponse,
    PodHealthDetail,
)

if TYPE_CHECKING:
    from .config import Settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Sidecar release helper
# ---------------------------------------------------------------------------

async def call_sidecar_release(pod_id: str, pod_host: str | None = None) -> bool:
    """Call the agent sidecar's /internal/release endpoint.

    Signals the pod sidecar to perform a WAL checkpoint and mark the pod
    as idle in Redis before the router returns it to the idle pool.

    Args:
        pod_id: The pod identifier.
        pod_host: Optional sidecar URL. If not provided, defaults to
            http://{pod_id}:8643 using the configured sidecar port.

    Returns:
        True if the sidecar returned HTTP 200, False otherwise.
    """
    if pod_host is None:
        pod_host = f"http://{pod_id}:8643"

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{pod_host}/internal/release",
                headers={"X-Pod-ID": pod_id},
                json={"pod_id": pod_id, "reason": "idle_recycle"},
            )
            return resp.status_code == 200
    except (httpx.RequestError, httpx.TimeoutException):
        return False


# ---------------------------------------------------------------------------
# Quota check (calls Quota Service)
# ---------------------------------------------------------------------------

async def check_quota(user_id: str, estimated_tokens: int = 0) -> QuotaCheckResponse:
    """Call Quota Service to verify user has remaining quota."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(
                f"{settings.quota_service_url}{settings.quota_check_endpoint}",
                json=QuotaCheckRequest(
                    user_id=user_id,
                    estimated_tokens=estimated_tokens,
                ).model_dump(),
            )
            if resp.status_code == 200:
                return QuotaCheckResponse(**resp.json())
            logger.warning(
                "Quota check failed for %s: %s %s",
                user_id, resp.status_code, resp.text,
            )
            # On Quota Service error, fail open with warning
            return QuotaCheckResponse(
                allowed=True,
                remaining_tokens=0,
                message="quota_service_unavailable",
            )
    except httpx.TimeoutException:
        logger.warning("Quota service timeout for %s, allowing request", user_id)
        return QuotaCheckResponse(allowed=True, remaining_tokens=0)
    except Exception as exc:
        logger.error("Quota service error for %s: %s", user_id, exc)
        return QuotaCheckResponse(allowed=True, remaining_tokens=0)


# ---------------------------------------------------------------------------
# Pod selection — hot route first, then cold start
# ---------------------------------------------------------------------------

def _get_pod_url(pod_id: str) -> str:
    """Build the HTTP URL for an Agent Pod's main service (port 8642)."""
    # In K8s: http://<pod-name>.<namespace>.svc.cluster.local:8642
    return f"http://{pod_id}.default.svc.cluster.local:8642"


def _get_sidecar_url(pod_id: str) -> str:
    """Build the HTTP URL for a Pod's Sidecar (port 8643)."""
    return f"http://{pod_id}.default.svc.cluster.local:8643"


def _stateless_home_component(route_subject: str) -> str:
    """Return a deterministic filesystem-safe component for a route subject."""
    return hashlib.sha256(route_subject.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Cold start: select idle Pod and trigger prepare
# ---------------------------------------------------------------------------

async def _cold_start_pod(
    user_id: str,
    hermes_home_path: str,
    runtime_context: dict | None = None,
    stateless: bool = False,
) -> tuple[str | None, int, int]:
    """Select an idle Pod and trigger cold-start via Sidecar.

    Returns:
        (pod_id, cold_start_ms, retries) on success
        (None, elapsed_ms, retries) on failure
    """
    # Step 1: Select from idle pool
    pod_id = rc.get_idle_pod()
    if not pod_id:
        logger.warning("No idle pods available for user %s", user_id)
        return None, 0, 0

    # Step 2: Call Pod Sidecar /internal/prepare
    start = time.monotonic()
    retry_interval = settings.prepare_retry_interval
    max_retries = settings.prepare_max_retries

    async with httpx.AsyncClient(timeout=settings.prepare_timeout) as client:
        for attempt in range(max_retries):
            try:
                resp = await client.post(
                    f"{_get_sidecar_url(pod_id)}/internal/prepare",
                    json=InternalPrepareRequest(
                        user_id=user_id,
                        hermes_home_path=hermes_home_path,
                        runtime_context=runtime_context,
                        stateless=stateless,
                        env_vars={
                            "HERMES_STATE_MODE": "remote",
                            "HERMES_STATE_SERVICE_URL": settings.state_service_url,
                            "HERMES_STATE_SERVICE_TOKEN": settings.state_service_token,
                        } if stateless else None,
                    ).model_dump(),
                )
                if resp.status_code == 200:
                    data = resp.json()
                    if data.get("ready"):
                        elapsed_ms = int((time.monotonic() - start) * 1000)
                        rc.set_pod_health(pod_id)
                        return pod_id, elapsed_ms, attempt + 1
            except httpx.RequestError as exc:
                logger.debug(
                    "Prepare attempt %d failed for pod %s: %s",
                    attempt + 1, pod_id, exc,
                )

            if attempt < max_retries - 1:
                await asyncio.sleep(retry_interval)

    elapsed_ms = int((time.monotonic() - start) * 1000)
    # If prepare failed, return pod to idle pool
    rc.add_pod_to_idle(pod_id)
    return None, elapsed_ms, max_retries


# ---------------------------------------------------------------------------
# Route request — main entry point
# ---------------------------------------------------------------------------

async def route_request(
    req: InternalRouteRequest,
) -> InternalRouteResponse:
    """Route a user request to an Agent Pod.

    Flow:
    1. Acquire session lock (atomic SET NX EX)
    2. Check quota
    3. Try hot route (Redis GET)
    4. On miss: cold start (idle Pod + Sidecar prepare)
    5. Set route in Redis
    6. Release session lock
    """
    user_id = req.user_id
    route_subject = req.session_id or user_id
    start_time = time.monotonic()

    # Step 1: Acquire session lock — prevents concurrent routing for same user
    lock_ok, holder = rc.acquire_session_lock(route_subject)
    if not lock_ok:
        logger.info(
            "Session lock denied for route subject %s, held by %s", route_subject, holder
        )
        return InternalRouteResponse(
            success=False,
            message=f"Session already active for this user (held by {holder})",
        )

    try:
        # Step 2: Quota check
        quota = await check_quota(
            user_id, req.estimated_tokens or 0
        )
        if not quota.allowed:
            return InternalRouteResponse(
                success=False,
                quota_allowed=False,
                quota_message=quota.message,
                message="Quota exceeded",
            )

        # Step 3: Try hot route
        hot_pod_id = rc.get_route(route_subject)
        if hot_pod_id:
            # Verify pod is still healthy
            if rc.is_pod_healthy(hot_pod_id):
                rc.set_pod_health(hot_pod_id)
                return InternalRouteResponse(
                    success=True,
                    pod_id=hot_pod_id,
                    pod_url=_get_pod_url(hot_pod_id),
                    source=RouteSource.HOT,
                    quota_allowed=True,
                )
            else:
                # Pod went unhealthy — clear stale route
                logger.info(
                    "Hot route found for %s (pod %s) but pod unhealthy, "
                    "triggering cold start",
                    route_subject, hot_pod_id,
                )
                rc.delete_route(route_subject)

        # Step 4: Cold start
        runtime_context = req.runtime_context
        if runtime_context is None:
            runtime_context = {
                "tenant_id": req.tenant_id or "default",
                "user_id": user_id,
                "session_id": req.session_id,
                "request_id": req.request_id,
                "state_service_url": settings.state_service_url,
                "state_token": settings.state_service_token,
            }
        else:
            runtime_context = runtime_context.model_dump()
            if not runtime_context.get("state_service_url"):
                runtime_context["state_service_url"] = settings.state_service_url
            if not runtime_context.get("state_token"):
                runtime_context["state_token"] = settings.state_service_token

        if settings.stateless_runtime:
            subject_component = _stateless_home_component(route_subject)
            hermes_home_path = f"/tmp/hermes-runtime/{subject_component}"
        else:
            # Get NAS shard from user_id for hermes_home_path construction.
            nas_shard = hashlib.sha256(user_id.encode()).hexdigest()[:2]
            hermes_home_path = (
                req.user_id
                if req.user_id.startswith("/")
                else f"/nas/hermes-homes/{nas_shard}/user-{user_id}"
            )

        pod_id, cold_start_ms, retries = await _cold_start_pod(
            user_id,
            hermes_home_path,
            runtime_context=runtime_context,
            stateless=settings.stateless_runtime,
        )

        if not pod_id:
            return InternalRouteResponse(
                success=False,
                message="No available pods (pool exhausted)",
                quota_allowed=True,
            )

        # Step 5: Set hot route in Redis
        rc.set_route(route_subject, pod_id)
        rc.set_pod_health(pod_id)

        elapsed_ms = int((time.monotonic() - start_time) * 1000)
        logger.info(
            "Cold start for route subject %s → pod %s in %dms (retries=%d)",
            route_subject, pod_id, cold_start_ms, retries,
        )

        return InternalRouteResponse(
            success=True,
            pod_id=pod_id,
            pod_url=_get_pod_url(pod_id),
            source=RouteSource.COLD,
            quota_allowed=True,
            cold_start_ms=cold_start_ms,
            prepare_retries=retries,
        )

    finally:
        # Step 6: Always release lock
        rc.release_session_lock(route_subject)


# ---------------------------------------------------------------------------
# Pool health check
# ---------------------------------------------------------------------------

async def get_pool_health() -> InternalHealthResponse:
    """Gather pool statistics from Redis. Gracefully degrades when Redis is unavailable."""
    redis_ok = rc.redis_health_check()

    try:
        idle_pods = rc.get_idle_count()
        active_pods = rc.get_active_pod_count()
        idle_details = rc.peek_idle_pods(limit=100)
    except Exception as exc:
        logger.warning("Redis error in pool health check: %s", exc)
        idle_pods = 0
        active_pods = 0
        idle_details = []

    pod_details: list[PodHealthDetail] = []

    for pod_id, score in idle_details:
        status = PodStatus.IDLE
        ts = rc.get_pod_health_ts(pod_id)
        pod_details.append(
            PodHealthDetail(
                pod_id=pod_id,
                status=status,
                last_heartbeat=(
                    time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))
                    if ts else None
                ),
            )
        )

    # Active pods — gracefully handle Redis errors
    try:
        for pod_id in rc.get_all_active_pods():
            ts = rc.get_pod_health_ts(pod_id)
            healthy = rc.is_pod_healthy(pod_id)
            pod_details.append(
                PodHealthDetail(
                    pod_id=pod_id,
                    status=PodStatus.BUSY if healthy else PodStatus.UNHEALTHY,
                    last_heartbeat=(
                        time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))
                        if ts else None
                    ),
                )
            )
    except Exception as exc:
        logger.warning("Redis error gathering active pods: %s", exc)

    unhealthy = sum(
        1 for p in pod_details if p.status == PodStatus.UNHEALTHY
    )

    return InternalHealthResponse(
        ok=redis_ok,
        pool_size=idle_pods + active_pods,
        idle_pods=idle_pods,
        active_pods=active_pods,
        preparing_pods=0,  # tracked separately if needed
        unhealthy_pods=unhealthy,
        pod_details=pod_details,
        redis_ok=redis_ok,
    )


# ---------------------------------------------------------------------------
# Background scheduler: idle timeout recycling
# ---------------------------------------------------------------------------

async def idle_recycler(interval: int = 60) -> None:
    """Background task: detect and recycle stale active pods.

    Runs every `interval` seconds.
    Finds active pods whose route TTL has expired, then:
    1. Call Pod /internal/release (WAL checkpoint)
    2. Add back to idle pool
    """
    while True:
        await asyncio.sleep(interval)
        try:
            stale_pods = rc.get_stale_active_pods()
            for pod_id in stale_pods:
                logger.info("Recycling stale active pod %s", pod_id)

                # Get the pod's sidecar address
                pod_host = rc.get_pod_host(pod_id)

                # Try graceful release via sidecar (WAL checkpoint + idle mark)
                released = False
                if pod_host:
                    released = await call_sidecar_release(pod_id, pod_host)

                if not released:
                    logger.warning(
                        "Sidecar release failed for pod %s, forcing recycle",
                        pod_id,
                    )

                # Always recycle the pod, even if sidecar call failed
                rc.add_pod_to_idle(pod_id)
                rc.delete_pod_health(pod_id)
        except Exception as exc:
            logger.error("Idle recycler error: %s", exc)


# ---------------------------------------------------------------------------
# Skills hot-update subscriber
# ---------------------------------------------------------------------------

async def skill_update_subscriber() -> None:
    """Subscribe to channel:skill-update and trigger Pod restarts.

    Router receives PubSub notification, then:
    1. SMEMBERS active-pods
    2. Batch SIGTERM pods (batch_size=20, interval=5s)
    Each batch triggers Hermes restart → picks up new skills from NAS.
    """
    pubsub = rc.get_skill_update_pubsub()
    pubsub.subscribe(settings.key_skill_update)

    logger.info(
        "Subscribed to skill update channel: %s",
        settings.key_skill_update,
    )

    try:
        for message in pubsub.listen():
            if message["type"] != "message":
                continue

            try:
                import json
                payload = json.loads(message["data"])
                skill_name = payload.get("skill_name", "unknown")
                version = payload.get("version", "?")
                action = payload.get("action", "updated")
                logger.info(
                    "Skill update received: %s v%s (%s)",
                    skill_name, version, action,
                )

                # Batch restart active pods
                active_pods = list(rc.get_all_active_pods())
                total = len(active_pods)

                for i in range(0, total, settings.skill_reload_batch_size):
                    batch = active_pods[i:i + settings.skill_reload_batch_size]
                    for pod_id in batch:
                        try:
                            async with httpx.AsyncClient(
                                timeout=settings.health_check_timeout,
                            ) as client:
                                await client.post(
                                    f"{_get_sidecar_url(pod_id)}/internal/skills/reload",
                                    json={"skill_name": skill_name, "version": version},
                                )
                        except Exception as exc:
                            logger.warning(
                                "Failed to reload skill on pod %s: %s",
                                pod_id, exc,
                            )
                    if i + settings.skill_reload_batch_size < total:
                        await asyncio.sleep(settings.skill_reload_batch_interval)

            except Exception as exc:
                logger.error("Error processing skill update: %s", exc)
    finally:
        pubsub.close()
