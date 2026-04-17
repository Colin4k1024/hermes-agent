"""
Auth Service — Redis Client
"""
import redis.asyncio as redis
from auth_service.config import settings

_redis_pool: redis.Redis | None = None


async def get_redis() -> redis.Redis:
    global _redis_pool
    if _redis_pool is None:
        _redis_pool = redis.from_url(settings.REDIS_URL, decode_responses=True)
    return _redis_pool


async def close_redis():
    global _redis_pool
    if _redis_pool:
        await _redis_pool.close()
        _redis_pool = None


async def check_redis() -> bool:
    """Health check for Redis."""
    try:
        r = await get_redis()
        await r.ping()
        return True
    except Exception:
        return False
