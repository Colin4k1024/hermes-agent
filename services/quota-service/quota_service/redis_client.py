"""Async Redis client for hot counters."""
from __future__ import annotations

from datetime import date, datetime, timezone

import redis.asyncio as redis

from quota_service.config import settings


def _make_redis_client() -> redis.Redis:
    return redis.Redis(
        host=settings.redis_host,
        port=settings.redis_port,
        password=settings.redis_password or None,
        db=settings.redis_db,
        decode_responses=True,
    )


_redis: redis.Redis | None = None


async def get_redis() -> redis.Redis:
    global _redis
    if _redis is None:
        _redis = _make_redis_client()
    return _redis


async def close_redis() -> None:
    global _redis
    if _redis is not None:
        await _redis.aclose()
        _redis = None


# ---------------------------------------------------------------------------
# Hot counter helpers
# ---------------------------------------------------------------------------

def _daily_key(user_id: str, d: date | None = None) -> str:
    if d is None:
        d = datetime.now(timezone.utc).date()
    return f"quota:daily:{user_id}:{d.isoformat()}"


async def get_daily_usage(redis_client: redis.Redis, user_id: str, d: date | None = None) -> tuple[int, int]:
    """Return (used_tokens, used_requests) from Redis hash."""
    key = _daily_key(user_id, d)
    data = await redis_client.hgetall(key)
    tokens = int(data.get("tokens", 0))
    requests = int(data.get("requests", 0))
    return tokens, requests


async def increment_daily_usage(
    redis_client: redis.Redis,
    user_id: str,
    tokens: int,
    d: date | None = None,
) -> tuple[int, int]:
    """Atomically increment daily token and request counters.

    Returns (total_tokens, total_requests) after increment.
    """
    key = _daily_key(user_id, d)
    pipe = redis_client.pipeline()
    pipe.hincrby(key, "tokens", tokens)
    pipe.hincrby(key, "requests", 1)
    # Set TTL so keys don't leak memory
    pipe.expire(key, settings.daily_counter_ttl)
    results = await pipe.execute()
    total_tokens = int(results[0])
    total_requests = int(results[1])
    return total_tokens, total_requests


async def check_quota_in_redis(
    redis_client: redis.Redis,
    user_id: str,
    estimated_tokens: int,
    daily_limit: int,
) -> tuple[bool, int, int]:
    """Check if user has remaining quota in Redis.

    Returns (has_quota, used_tokens, used_requests).
    """
    used_tokens, used_requests = await get_daily_usage(redis_client, user_id)
    # -1 means unlimited
    if daily_limit < 0:
        return True, used_tokens, used_requests
    remaining = daily_limit - used_tokens
    has_quota = remaining >= estimated_tokens
    return has_quota, used_tokens, used_requests
