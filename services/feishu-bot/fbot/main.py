"""
Feishu Bot Service — FastAPI application.

Handles:
1. POST /feishu/webhook   — receive and validate Feishu events
2. POST /feishu/event     — Feishu URL verification challenge
3. GET  /health           — liveness probe
4. GET  /health/ready     — readiness probe (includes Redis)

The FBot consumer loop runs as a background task that:
1. Reads from feishu:requests (XREADGROUP)
2. Calls the Agent Router via /internal/route
3. Waits for the response on its private feishu:responses:{instance_id} stream
4. Sends the assembled response back to Feishu via send_card_message
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import os
import random
import secrets
import signal
import sys
import time
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# Local modules
from fbot.config import get_settings, Settings
from fbot.models.events import (
    AuthUserByFeishuIdResponse,
    BindingStatus,
    FeishuInboundEvent,
    FeishuMessageContent,
    FeishuResponseChunk,
    HealthStatus,
)
from fbot.redis_client import (
    add_feishu_request,
    add_response_marker,
    check_and_set_dedup,
    close_redis,
    get_redis,
    healthcheck_redis,
    read_response_chunks,
    store_bind_nonce,
)
from fbot.signature import verify_lark_signature
from fbot.auth_client import lookup_user_by_feishu_id
from fbot.feishu_client import (
    _build_binding_card,
    _build_reply_card,
    _build_error_card,
    reply_to_message,
    send_card_message,
)

# ── Logging ───────────────────────────────────────────────────────────────────

LOGGER = logging.getLogger("feishu-bot")
_handler = logging.StreamHandler(sys.stdout)
_handler.setFormatter(logging.Formatter(
    "%(asctime)s %(levelname)s %(name)s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
))
LOGGER.addHandler(_handler)


# ── Lifespan ─────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start/stop the background consumer task."""
    settings = get_settings()
    LOGGER.setLevel(settings.LOG_LEVEL)

    # Seed logger with instance ID
    LOGGER.info("Feishu Bot Service starting — instance=%s", settings.FBOT_INSTANCE_ID)

    # Start background consumer
    consumer_task = asyncio.create_task(_consumer_loop())

    yield

    # Shutdown
    LOGGER.info("Shutting down Feishu Bot Service …")
    consumer_task.cancel()
    try:
        await consumer_task
    except asyncio.CancelledError:
        pass
    await close_redis()
    LOGGER.info("Shutdown complete")


# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Feishu Bot Service",
    description="Hermes Enterprise SaaS — Feishu Webhook receiver and message router",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS — Feishu bot receives webhooks from Feishu servers (preflight from various origins)
# Restrict credentials in production; ingress controller handles access control
_cors_origins = settings.cors_origins if hasattr(settings, "cors_origins") and settings.cors_origins else ([] if not settings.debug else ["*"])
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=False,  # Credentials require explicit origins; disable for webhook receiver
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Feishu-Event", "X-Feishu-Signature"],
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _extract_text_from_event(event_data: Dict[str, Any]) -> str:
    """
    Extract plain-text content from a Feishu im.message.receive_v1 event.

    Handles message_type: text, post, image, file, etc.
    Falls back to a description string for unsupported types.
    """
    msg = event_data.get("message", {})
    msg_type = msg.get("message_type", "")

    if msg_type == "text":
        try:
            content = json.loads(msg.get("content", "{}"))
            return content.get("text", "").strip()
        except (json.JSONDecodeError, TypeError):
            return ""

    if msg_type == "post":
        try:
            content = json.loads(msg.get("content", "{}"))
            # Walk the post structure — extract all text elements
            texts: List[str] = []

            def walk(obj: Any) -> None:
                if isinstance(obj, dict):
                    if obj.get("tag") == "text":
                        texts.append(obj.get("text", ""))
                    for v in obj.values():
                        walk(v)
                elif isinstance(obj, list):
                    for item in obj:
                        walk(item)

            walk(content)
            return " ".join(texts).strip()
        except (json.JSONDecodeError, TypeError):
            return ""

    if msg_type in ("image", "file", "audio", "video", "media"):
        return f"[{msg_type.title()} attachment]"

    if msg_type == "card":
        return "[Interactive card]"

    return ""


def _extract_union_id(event_data: Dict[str, Any]) -> str:
    """Extract sender union_id from a Feishu message event."""
    sender = event_data.get("message", {}).get("sender", {})
    return sender.get("union_id", "") or sender.get("open_id", "")


def _extract_chat_id(event_data: Dict[str, Any]) -> str:
    """Extract chat_id from a Feishu message event."""
    return event_data.get("message", {}).get("chat_id", "")


def _extract_feishu_msg_id(event_data: Dict[str, Any]) -> str:
    """Extract Feishu message ID."""
    return event_data.get("message", {}).get("message_id", "")


async def _send_binding_card(
    chat_id: str,
    union_id: str,
) -> None:
    """
    Send the identity-binding card to an unbound user.

    1. Generate a short-lived nonce
    2. Store nonce → union_id in Redis
    3. Compute HMAC signature for the bind URL
    4. Send the interactive card to the user's chat
    """
    settings = get_settings()

    # Generate nonce
    nonce = secrets.token_hex(16)
    timestamp = str(int(time.time()))

    # Store nonce in Redis
    await store_bind_nonce(nonce, union_id)

    # Compute bind URL signature: HMAC-SHA256(nonce + timestamp + app_secret)
    sign_msg = f"{nonce}{timestamp}".encode("utf-8")
    sign = hmac.new(
        settings.FEISHU_APP_SECRET.encode("utf-8"),
        sign_msg,
        hashlib.sha256,
    ).hexdigest()

    # Build card
    card = _build_binding_card(
        union_id=union_id,
        nonce=nonce,
        timestamp=timestamp,
        sign=sign,
    )

    # Send
    ok, err = await send_card_message(chat_id, card)
    if not ok:
        LOGGER.error("Failed to send binding card to chat_id=%s: %s", chat_id, err)


async def _send_error_reply(chat_id: str, msg_id: str, error_text: str) -> None:
    """Send an error card back to the user."""
    card = _build_error_card(error_text)
    if msg_id:
        await reply_to_message(msg_id, card)
    else:
        await send_card_message(chat_id, card)


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/health")
async def health() -> Dict[str, str]:
    """Liveness probe — service is running."""
    return {"status": "ok", "service": "feishu-bot"}


@app.get("/health/ready")
async def health_ready() -> HealthStatus:
    """Readiness probe — checks Redis connectivity."""
    redis_ok = await healthcheck_redis()
    settings = get_settings()
    return HealthStatus(
        status="ok" if redis_ok else "degraded",
        version="0.1.0",
        fbot_instance_id=settings.FBOT_INSTANCE_ID,
        redis_connected=redis_ok,
    )


@app.post("/feishu/event")
async def feishu_event_endpoint(request: Request) -> Dict[str, str]:
    """
    Handle Feishu URL verification challenge.

    Feishu sends a GET with query param challenge when first setting up the webhook URL.
    We respond with {"challenge": "<challenge_value>"}.
    """
    body = await request.body()
    try:
        data = json.loads(body)
        challenge = data.get("challenge", "")
        if challenge:
            LOGGER.info("URL verification challenge received, responding")
            return {"challenge": challenge}
    except json.JSONDecodeError:
        pass

    # Also handle GET-style challenge from query params
    params = dict(request.query_params)
    if "challenge" in params:
        LOGGER.info("URL verification via query params")
        return {"challenge": params["challenge"]}

    return {"status": "ok"}


@app.post("/feishu/webhook")
async def feishu_webhook(request: Request) -> Dict[str, Any]:
    """
    Main Webhook endpoint — receive and process Feishu events.

    Processing steps (per ADR-005 §B.7):
    1. Verify HMAC-SHA256 signature
    2. Extract event_id → check dedup (Redis SETNX)
    3. Parse message content
    4. Query Auth Service: union_id → user_id
    5a. Not bound → send binding card, return 200
    5b. Bound → XADD feishu:requests + XADD response marker, return 200
    """
    # ── 1. Signature verification ──────────────────────────────────────────
    try:
        body = await verify_lark_signature(request)
    except HTTPException:
        # All failures return 200 to prevent Feishu retry storms
        return {"code": 0, "message": "ok"}

    # ── 2. Parse payload ────────────────────────────────────────────────────
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        LOGGER.warning("Non-JSON webhook payload: %s", body[:200])
        return {"code": 0, "message": "ok"}

    header = payload.get("header", {})
    event_type = header.get("event_type", "")
    event_id = header.get("event_id", "")

    LOGGER.debug("Feishu event received: type=%s event_id=%s", event_type, event_id)

    # ── Only handle im.message.receive_v1 ────────────────────────────────
    if event_type != "im.message.receive_v1":
        LOGGER.debug("Ignoring event type=%s", event_type)
        return {"code": 0, "message": "ok"}

    event_data = payload.get("event", {})

    # ── 3. Event ID dedup ──────────────────────────────────────────────────
    is_new = await check_and_set_dedup(event_id)
    if not is_new:
        LOGGER.debug("Duplicate event_id=%s, skipping", event_id)
        return {"code": 0, "message": "ok"}

    # ── 4. Extract fields ────────────────────────────────────────────────
    union_id = _extract_union_id(event_data)
    chat_id = _extract_chat_id(event_data)
    feishu_msg_id = _extract_feishu_msg_id(event_data)
    text_content = _extract_text_from_event(event_data)

    if not text_content:
        LOGGER.debug("Empty message content, skipping")
        return {"code": 0, "message": "ok"}

    if not union_id:
        LOGGER.warning("No sender union_id in event_id=%s", event_id)
        return {"code": 0, "message": "ok"}

    # ── 5. Identity lookup ────────────────────────────────────────────────
    auth_resp, reason = await lookup_user_by_feishu_id(union_id)

    if reason == "not_bound":
        LOGGER.info("union_id=%s not bound, sending binding card", union_id)
        await _send_binding_card(chat_id, union_id)
        return {"code": 0, "message": "ok"}

    if reason == "error" or auth_resp is None:
        LOGGER.error("Auth Service error for union_id=%s, sending error card", union_id)
        await _send_error_reply(chat_id, feishu_msg_id, "身份验证服务暂时不可用，请稍后重试。")
        return {"code": 0, "message": "ok"}

    user_id = auth_resp.user_id

    # ── 6. Enqueue to Redis Streams ───────────────────────────────────────
    settings = get_settings()
    reply_channel = settings.feishu_responses_stream

    # XADD feishu:requests
    request_stream_id = await add_feishu_request(
        user_id=user_id,
        union_id=union_id,
        feishu_msg_id=feishu_msg_id,
        feishu_chat_id=chat_id,
        message=text_content,
        reply_channel=reply_channel,
        fbot_instance_id=settings.FBOT_INSTANCE_ID,
    )

    # XADD response marker (FBot will XREADBLOCK on this)
    await add_response_marker(
        response_stream=reply_channel,
        request_id=request_stream_id,
    )

    LOGGER.info(
        "Enqueued request: event_id=%s user_id=%s msg_id=%s stream_id=%s",
        event_id,
        user_id,
        feishu_msg_id,
        request_stream_id,
    )

    return {"code": 0, "message": "ok"}


# ── Background Consumer Loop ──────────────────────────────────────────────────

# Track the last-read position in the feishu:requests stream.
# Key: fbot_instance_id → last processed stream ID (e.g. "1700000000000-0")
_last_stream_pos: Dict[str, str] = {}


async def _consumer_loop() -> None:
    """
    Background task: reads feishu:requests, waits for Router response, sends to Feishu.

    Architecture (BE-3 confirmed):
    - FBot writes feishu:requests (Router consumes)
    - FBot writes feishu:responses:{fbot_instance_id} (FBot reads)
    - Router writes chunks to the response stream
    - FBot XREADBLOCK waits up to XREAD_TIMEOUT_SECONDS per request

    Consumer group: g1, consumer: {fbot_instance_id}
    """
    settings = get_settings()
    group_name = "g1"
    consumer_name = settings.FBOT_INSTANCE_ID
    stream_name = settings.FEISHU_REQUESTS_STREAM

    r = await get_redis()

    # Ensure consumer group exists (idempotent — OK if already exists)
    try:
        await r.xgroup_create(stream_name, group_name, id="0", mkstream=True)
    except Exception:
        pass  # Group already exists

    LOGGER.info(
        "Consumer loop started: stream=%s group=%s consumer=%s",
        stream_name, group_name, consumer_name,
    )

    while True:
        try:
            # XREADGROUP BLOCK — read new messages for this consumer
            result = await r.xreadgroup(
                group_name,
                consumer_name,
                {stream_name: ">"},   # ">" means "only new messages"
                block=settings.XREAD_TIMEOUT_SECONDS * 1000,
                count=10,
            )

            if not result:
                continue

            for stream_name, messages in result:
                for msg_id, fields in messages:
                    await _process_request(fields, msg_id)

                    # ACK after processing (Router uses idempotent POST, so ACK is safe)
                    await r.xack(stream_name, group_name, msg_id)

        except asyncio.CancelledError:
            raise
        except Exception as exc:
            LOGGER.exception("Consumer loop error: %s", exc)
            await asyncio.sleep(5)


async def _process_request(fields: Dict[str, str], msg_id: str) -> None:
    """Process a single feishu:requests entry: wait for Router response, send reply."""
    settings = get_settings()
    user_id = fields.get("user_id", "")
    chat_id = fields.get("feishu_chat_id", "")
    feishu_msg_id = fields.get("feishu_msg_id", "")
    text_content = fields.get("message", "")
    reply_channel = fields.get("reply_channel", "") or settings.feishu_responses_stream

    LOGGER.debug(
        "Processing request: msg_id=%s user_id=%s chat_id=%s",
        msg_id, user_id, chat_id,
    )

    # Wait for Router to write chunks to the response stream
    chunks: List[str] = []
    last_id = "$"
    timeout_ms = settings.XREAD_TIMEOUT_SECONDS * 1000
    start_time = time.monotonic()

    while True:
        response_chunks = await read_response_chunks(
            response_stream=reply_channel,
            last_id=last_id,
            timeout_ms=min(timeout_ms, 55000),  # cap per-call at 55s
        )

        if not response_chunks:
            elapsed = time.monotonic() - start_time
            LOGGER.warning(
                "Response timeout for request %s after %.1fs — no chunks received",
                msg_id, elapsed,
            )
            # Send timeout card
            await _send_error_reply(
                chat_id, feishu_msg_id,
                "请求处理超时（> 55s），Hermes Agent 可能正在忙碌，请稍后重试。",
            )
            return

        all_done = False
        for chunk_record in response_chunks:
            chunk_text = chunk_record.get("chunk", "")
            done = chunk_record.get("done", False)
            rid = chunk_record.get("id", last_id)
            last_id = rid

            if chunk_text:
                chunks.append(chunk_text)

            if done:
                all_done = True
                break  # Final chunk received

        if all_done:
            break

    full_text = "".join(chunks).strip()
    if not full_text:
        LOGGER.warning("Empty response assembled for request %s", msg_id)
        full_text = "Hermes Agent 未能生成有效回复，请稍后重试。"

    LOGGER.info(
        "Assembled response for request %s: %d chars from %d chunks",
        msg_id, len(full_text), len(chunks),
    )

    # Send reply card
    card = _build_reply_card(full_text, msg_id=feishu_msg_id)
    if feishu_msg_id:
        ok, err = await reply_to_message(feishu_msg_id, card)
    else:
        ok, err = await send_card_message(chat_id, card)

    if not ok:
        LOGGER.error("Failed to send reply for request %s: %s", msg_id, err)
    else:
        LOGGER.info("Reply sent for request %s", msg_id)
