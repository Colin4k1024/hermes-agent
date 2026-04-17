"""Redis publisher for skill hot-update notifications.

Router subscribes to channel:skill-update and initiates batch Pod restarts
(batch_size=20, interval=5s) for zero-downtime skill propagation.
"""

import redis.asyncio as redis

from .config import settings
from .schemas import SkillUpdateNotification

_redis_pool: redis.Redis | None = None


async def _get_redis() -> redis.Redis:
    global _redis_pool
    if _redis_pool is None:
        _redis_pool = redis.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
        )
    return _redis_pool


async def publish_skill_update(
    skill_name: str,
    version: str,
    action: str = "updated",
) -> bool:
    """Publish a skill-update notification to Redis PubSub.

    Returns True if published successfully, False otherwise.
    Does NOT raise — caller should not fail if Redis is temporarily unavailable.
    """
    try:
        r = await _get_redis()
        payload = SkillUpdateNotification(
            skill_name=skill_name,
            version=version,
            action=action,
        )
        await r.publish(
            settings.skill_update_channel,
            payload.model_dump_json(),
        )
        return True
    except Exception:
        return False


async def redis_health_check() -> bool:
    """Check Redis connectivity."""
    try:
        r = await _get_redis()
        await r.ping()
        return True
    except Exception:
        return False
