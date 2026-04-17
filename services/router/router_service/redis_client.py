"""Redis client for Agent Router — routing table, locks, pool state.

All Redis operations are synchronous (redis-py) for simplicity.
For production with heavy load, consider switching to async redis.asyncio.
"""

import json
import logging
import time
from contextlib import contextmanager
from typing import Any

import redis

logger = logging.getLogger(__name__)

from .config import settings


# ---------------------------------------------------------------------------
# Global connection pool
# ---------------------------------------------------------------------------

_redis_pool: redis.ConnectionPool | None = None


def get_redis_pool() -> redis.ConnectionPool:
    """Get or create the shared Redis connection pool.

    Uses socket_timeout=2 to fail fast when Redis is unavailable.
    """
    global _redis_pool
    if _redis_pool is None:
        _redis_pool = redis.ConnectionPool.from_url(
            settings.redis_url,
            max_connections=50,
            decode_responses=True,
            socket_timeout=2.0,
            socket_connect_timeout=2.0,
        )
    return _redis_pool


def get_redis() -> redis.Redis:
    """Get a Redis client from the shared pool."""
    return redis.Redis(connection_pool=get_redis_pool())


def close_pool() -> None:
    """Close the global connection pool on shutdown."""
    global _redis_pool
    if _redis_pool is not None:
        _redis_pool.disconnect()
        _redis_pool = None


# ---------------------------------------------------------------------------
# Key helpers
# ---------------------------------------------------------------------------

route_key = lambda uid: f"{settings.key_route}:{uid}"
pod_active_key = lambda pid: f"{settings.key_pod_active}:{pid}"
pod_health_key = lambda pid: f"{settings.key_pod_health}:{pid}"
session_lock_key = lambda uid: f"{settings.key_session_lock}:{uid}"


# ---------------------------------------------------------------------------
# Session lock — SET NX EX (atomic, per user)
# ---------------------------------------------------------------------------

LOCK_ACQUIRED = "acquired"
LOCK_ALREADY_HELD = "already_held"


def acquire_session_lock(
    user_id: str, pod_id: str | None = None
) -> tuple[bool, str | None]:
    """Atomically acquire a session lock for a user.

    Uses SET key value NX EX — single atomic operation (BE-1 confirmed).

    Returns:
        (True, pod_id)   — lock acquired
        (False, holder)   — lock already held by another request
        (False, None)    — Redis unavailable or error
    """
    try:
        client = get_redis()
        holder = client.get(session_lock_key(user_id))
        if holder is not None:
            return False, holder

        # NX: only set if not exists; EX: expire after TTL
        result = client.set(
            session_lock_key(user_id),
            pod_id or "pending",
            nx=True,
            ex=settings.session_lock_ttl,
        )
        if result:
            return True, pod_id or "pending"
        # Race: another request grabbed it between our GET and SET
        holder = client.get(session_lock_key(user_id))
        return False, holder
    except Exception:
        # Redis unavailable — fail open with a warning
        logger.warning("Redis unavailable during session lock for %s", user_id)
        return True, None


def release_session_lock(user_id: str) -> None:
    """Release a user's session lock. Silently fails on Redis error."""
    try:
        get_redis().delete(session_lock_key(user_id))
    except Exception as exc:
        logger.warning("Failed to release session lock for %s: %s", user_id, exc)


# ---------------------------------------------------------------------------
# Route management — hot routing
# ---------------------------------------------------------------------------

def get_route(user_id: str) -> str | None:
    """Get the assigned Pod ID for a user (hot route). Returns None on error."""
    try:
        return get_redis().get(route_key(user_id))
    except Exception:
        return None


def set_route(user_id: str, pod_id: str) -> None:
    """Set a user's route mapping with TTL."""
    try:
        client = get_redis()
        pipe = client.pipeline()
        pipe.set(route_key(user_id), pod_id, ex=settings.route_ttl)
        pipe.set(pod_active_key(pod_id), user_id, ex=settings.route_ttl)
        pipe.sadd(settings.key_active_pods, pod_id)
        pipe.execute()
    except Exception as exc:
        logger.warning("Failed to set route for %s → %s: %s", user_id, pod_id, exc)


def delete_route(user_id: str) -> str | None:
    """Delete a user's route. Returns the pod_id that was serving them."""
    try:
        client = get_redis()
        pipe = client.pipeline()
        pod_id = client.get(route_key(user_id))
        pipe.delete(route_key(user_id))
        if pod_id:
            pipe.delete(pod_active_key(pod_id))
            pipe.srem(settings.key_active_pods, pod_id)
        pipe.execute()
        return pod_id
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Pod idle pool — ZSET (score = idle_since_ts)
# ---------------------------------------------------------------------------

def add_pod_to_idle(pod_id: str) -> None:
    """Add a Pod to the idle pool (or update its score). Silently fails on Redis error."""
    try:
        client = get_redis()
        pipe = client.pipeline()
        pipe.zadd(settings.key_pod_idle, {pod_id: time.time()})
        pipe.srem(settings.key_active_pods, pod_id)
        pipe.delete(pod_active_key(pod_id))
        pipe.execute()
    except Exception as exc:
        logger.warning("Failed to add pod %s to idle pool: %s", pod_id, exc)


def get_idle_pod() -> str | None:
    """Pop the oldest idle Pod (lowest score = earliest idle time).

    Uses ZPOPMIN for atomic pop.
    Returns None if no idle pods available or on Redis error.
    """
    try:
        result = get_redis().zpopmin(settings.key_pod_idle, count=1)
        if not result:
            return None
        pod_id = result[0][0]
        get_redis().sadd(settings.key_active_pods, pod_id)
        return pod_id
    except Exception:
        return None


def peek_idle_pods(limit: int = 10) -> list[tuple[str, float]]:
    """Peek at idle pods without removing them. Returns empty list on error."""
    try:
        return get_redis().zrange(settings.key_pod_idle, 0, limit - 1, withscores=True)
    except Exception:
        return []


def get_idle_count() -> int:
    """Number of pods in the idle pool."""
    try:
        return get_redis().zcard(settings.key_pod_idle)
    except Exception:
        return 0


# ---------------------------------------------------------------------------
# Pod health
# ---------------------------------------------------------------------------

def set_pod_health(pod_id: str) -> None:
    """Record a pod's health heartbeat with TTL. Silently fails on Redis error."""
    try:
        get_redis().set(
            pod_health_key(pod_id),
            time.time(),
            ex=settings.pod_health_ttl,
        )
    except Exception as exc:
        logger.warning("Failed to set health for pod %s: %s", pod_id, exc)


def is_pod_healthy(pod_id: str) -> bool:
    """Check if a pod has a recent health heartbeat. Returns False on error."""
    try:
        return get_redis().exists(pod_health_key(pod_id)) == 1
    except Exception:
        return True  # fail open


def get_pod_health_ts(pod_id: str) -> float | None:
    """Get the last health heartbeat timestamp. Returns None on error."""
    try:
        val = get_redis().get(pod_health_key(pod_id))
        return float(val) if val else None
    except Exception:
        return None


def delete_pod_health(pod_id: str) -> None:
    """Remove health record for a pod. Silently fails on Redis error."""
    try:
        get_redis().delete(pod_health_key(pod_id))
    except Exception as exc:
        logger.warning("Failed to delete health for pod %s: %s", pod_id, exc)


# ---------------------------------------------------------------------------
# Pool statistics
# ---------------------------------------------------------------------------

def get_active_pod_count() -> int:
    """Number of pods currently serving users. Returns 0 on error."""
    try:
        return get_redis().scard(settings.key_active_pods)
    except Exception:
        return 0


def get_all_active_pods() -> set[str]:
    """Get all pod IDs in the active set. Returns empty set on error."""
    try:
        return get_redis().smembers(settings.key_active_pods)
    except Exception:
        return set()


# ---------------------------------------------------------------------------
# Pod idle timeout — detect and recycle idle pods
# ---------------------------------------------------------------------------

IDLE_TIMEOUT_SECONDS = 1800  # 30 minutes — matches route_ttl


def get_stale_active_pods() -> list[str]:
    """Find active pods whose routes have expired.

    Compares pod:active TTL expiry against current time.
    Returns list of pod_ids that should be recycled.
    """
    try:
        active_pods = get_all_active_pods()
        stale = []
        for pod_id in active_pods:
            ttl = get_redis().ttl(pod_active_key(pod_id))
            if ttl <= 0:
                stale.append(pod_id)
        return stale
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Feishu Streams
# ---------------------------------------------------------------------------

def add_feishu_request(
    user_id: str,
    message: str,
    feishu_msg_id: str | None = None,
    feishu_chat_id: str | None = None,
    reply_channel: str | None = None,
    fbot_instance_id: str | None = None,
) -> str | None:
    """Add a Feishu message request to the stream.

    Returns the stream entry ID, or None on Redis error.
    """
    try:
        fields = {
            "user_id": user_id,
            "message": message,
        }
        if feishu_msg_id:
            fields["feishu_msg_id"] = feishu_msg_id
        if feishu_chat_id:
            fields["feishu_chat_id"] = feishu_chat_id
        if reply_channel:
            fields["reply_channel"] = reply_channel
        if fbot_instance_id:
            fields["fbot_instance_id"] = fbot_instance_id
        return get_redis().xadd(settings.key_feishu_requests, fields)
    except Exception as exc:
        logger.warning("Failed to add Feishu request: %s", exc)
        return None


def read_feishu_request(
    group: str,
    consumer: str,
    count: int = 10,
    block_ms: int = 0,
) -> list[tuple[str, dict]]:
    """Read new messages from feishu:requests stream.

    Returns list of (message_id, fields_dict).
    Set block_ms > 0 for blocking read.
    """
    try:
        result = get_redis().xreadgroup(
            group,
            consumer,
            {settings.key_feishu_requests: ">"},
            count=count,
            block=block_ms,
        )
        if not result:
            return []
        _, entries = result[0]
        return entries
    except Exception:
        return []


def ack_feishu_request(message_ids: str | list[str]) -> int:
    """ACK one or more feishu:requests messages. Returns 0 on error."""
    try:
        if isinstance(message_ids, str):
            message_ids = [message_ids]
        return get_redis().xack(
            settings.key_feishu_requests,
            "router-group",
            *message_ids,
        )
    except Exception:
        return 0


def write_feishu_response(
    stream_key: str,
    request_id: str,
    chunk: str,
    done: bool = False,
) -> str | None:
    """Write a response chunk to a Feishu response stream. Returns stream ID or None."""
    try:
        fields = {
            "request_id": request_id,
            "chunk": chunk,
            "done": "1" if done else "0",
        }
        return get_redis().xadd(stream_key, fields, maxlen=1000, approximate=True)
    except Exception as exc:
        logger.warning("Failed to write Feishu response: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Skills hot-update PubSub
# ---------------------------------------------------------------------------

def publish_skill_update(skill_name: str, version: int | str, action: str) -> int:
    """Publish a skill update notification. Returns 0 on error."""
    try:
        payload = json.dumps({
            "skill_name": skill_name,
            "version": str(version),
            "action": action,
        })
        return get_redis().publish(settings.key_skill_update, payload)
    except Exception:
        return 0


def get_skill_update_pubsub():
    """Get a PubSub object for skill updates."""
    return get_redis().pubsub()


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

def redis_health_check() -> bool:
    """Ping Redis to verify connectivity. Returns False on any error."""
    try:
        return bool(get_redis().ping())
    except Exception:
        return False
