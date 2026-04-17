"""Redis client — single module so all services import from here."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import redis.asyncio as redis
from redis.asyncio.client import Redis

from fbot.config import get_settings

logger = logging.getLogger(__name__)

# ── Global client (lazy initialised) ────────────────────────────────────────


_client: Optional[Redis] = None


async def get_redis() -> Redis:
    """Return the shared async Redis client, creating it on first call."""
    global _client
    if _client is None:
        settings = get_settings()
        _client = redis.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
        )
        logger.info("Redis client connected to %s", settings.redis_url)
    return _client


async def close_redis() -> None:
    """Close the shared Redis client."""
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None
        logger.info("Redis client closed")


# ── Dedup helpers ─────────────────────────────────────────────────────────────


async def check_and_set_dedup(event_id: str) -> bool:
    """
    Attempt to claim ownership of an event_id for deduplication.

    Returns
    -------
    bool
        True  — this is the first time we've seen event_id; caller should process it.
        False — event_id was already claimed by another request (duplicate).

    The SETNX + EX (atomic) guarantees that even under concurrent requests with
    the same event_id, only one will see True.
    """
    r = await get_redis()
    settings = get_settings()
    key = f"dedup:feishu:{event_id}"
    # SET NX EX = atomic set-if-not-exists with TTL
    result = await r.set(key, "1", nx=True, ex=settings.DEDUP_TTL_SECONDS)
    return result is not None  # redis-py returns True/False or None for NX


# ── Nonce helpers (binding flow) ───────────────────────────────────────────────


async def store_bind_nonce(nonce: str, union_id: str) -> None:
    """Store a binding nonce for a union_id with TTL."""
    r = await get_redis()
    settings = get_settings()
    key = f"feishu:bind:nonce:{nonce}"
    await r.set(key, union_id, ex=settings.NONCE_TTL_SECONDS)


async def get_bind_nonce(nonce: str) -> Optional[str]:
    """Retrieve the union_id associated with a binding nonce."""
    r = await get_redis()
    key = f"feishu:bind:nonce:{nonce}"
    return await r.get(key)


async def delete_bind_nonce(nonce: str) -> None:
    """Delete a used binding nonce."""
    r = await get_redis()
    await r.delete(f"feishu:bind:nonce:{nonce}")


# ── Redis Streams helpers ────────────────────────────────────────────────────


async def add_feishu_request(
    user_id: str,
    union_id: str,
    feishu_msg_id: str,
    feishu_chat_id: str,
    message: str,
    reply_channel: str,
    fbot_instance_id: str,
) -> str:
    """
    Write an inbound Feishu message to the feishu:requests stream.

    Returns the Redis stream-assigned message ID (e.g. "1700000000000-0").
    """
    r = await get_redis()
    settings = get_settings()
    stream = settings.FEISHU_REQUESTS_STREAM
    fields = {
        "user_id": user_id,
        "union_id": union_id,
        "feishu_msg_id": feishu_msg_id,
        "feishu_chat_id": feishu_chat_id,
        "message": message,
        "reply_channel": reply_channel,
        "fbot_instance_id": fbot_instance_id,
    }
    msg_id = await r.xadd(stream, fields)
    logger.debug("XADD %s id=%s fields=%s", stream, msg_id, fields)
    return msg_id


async def add_response_marker(
    response_stream: str,
    request_id: str,
) -> str:
    """
    Write a response-waiting marker to the FBot's private response stream.

    The Router reads this marker, then writes chunks into this same stream.
    FBot XREADBLOCKs on this stream waiting for those chunks.
    """
    r = await get_redis()
    settings = get_settings()
    fields = {
        "request_id": request_id,
        "status": "waiting",
    }
    msg_id = await r.xadd(response_stream, fields)
    # Set TTL so abandoned streams don't leak memory
    await r.expire(response_stream, settings.RESPONSE_STREAM_TTL_SECONDS)
    return msg_id


async def read_response_chunks(
    response_stream: str,
    last_id: str = "$",
    timeout_ms: int = 55000,
) -> List[Dict[str, Any]]:
    """
    XREADBLOCK on the response stream and return all chunks received.

    This is called by the FBot consumer loop. It blocks up to `timeout_ms`
    milliseconds waiting for the Router to write chunks.

    Returns
    -------
    List[Dict]
        List of {id, request_id, chunk, done} records. Empty if timeout.
    """
    r = await get_redis()
    # XREAD BLOCK waits for new entries after last_id
    result = await r.xread(
        {response_stream: last_id},
        block=timeout_ms,
    )
    if not result:
        return []

    chunks: List[Dict[str, Any]] = []
    # result format: [(stream_name, [(id, {field: value, ...}), ...])]
    for stream_name, entries in result:
        for entry_id, fields in entries:
            chunks.append({
                "id": entry_id,
                "request_id": fields.get("request_id", ""),
                "chunk": fields.get("chunk", ""),
                "done": fields.get("done", "false").lower() == "true",
            })
    return chunks


async def healthcheck_redis() -> bool:
    """Ping Redis and return True if reachable."""
    try:
        r = await get_redis()
        return await r.ping()
    except Exception as exc:
        logger.warning("Redis healthcheck failed: %s", exc)
        return False
