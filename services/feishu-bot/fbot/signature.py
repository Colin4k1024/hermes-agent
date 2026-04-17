"""
Feishu Webhook signature verification.

Verifies that incoming requests genuinely originate from the Feishu Open Platform
by validating the HMAC-SHA256 signature attached as the `X-Lark-Signature` header.

Security layers (per ADR-005 Appendix B):
1. Timestamp check — reject requests older than MAX_TIMESTAMP_OFFSET (5 min)
2. HMAC-SHA256 signature — constant-time comparison to prevent timing attacks
3. Event ID dedup — Redis SETNX covers Feishu retry window
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import time
from typing import Tuple

from fastapi import HTTPException, Request, Response

from fbot.config import get_settings

logger = logging.getLogger(__name__)


async def verify_lark_signature(request: Request) -> bytes:
    """
    Verify the Feishu Webhook request signature and return the raw body.

    Returns
    -------
    bytes
        The original request body, verified to be from Feishu.

    Raises
    ------
    HTTPException(200, {"code": ...})
        All verification failures return HTTP 200 to prevent Feishu from
        retrying (Feishu docs recommendation).  The body carries an error code.

    HTTPException(401, ...)
        Only for completely malformed requests (missing mandatory headers).
    """
    settings = get_settings()

    # ── 1. Read required headers ─────────────────────────────────────────────
    timestamp = request.headers.get("X-Lark-Request-Timestamp", "").strip()
    signature = request.headers.get("X-Lark-Signature", "").strip()

    if not timestamp or not signature:
        # Return 200 per ADR-005 B.6 — avoid Feishu retry storms
        logger.warning(
            "Feishu webhook missing signature headers; returning 200 to Feishu. "
            "headers=%s",
            dict(request.headers),
        )
        raise HTTPException(
            status_code=200,
            detail={
                "code": "MISSING_SIGNATURE_HEADERS",
                "message": "Missing required headers",
            },
        )

    # ── 2. Timestamp range check ────────────────────────────────────────────
    try:
        ts = int(timestamp)
    except ValueError:
        logger.warning("Feishu webhook invalid timestamp format: %s", timestamp)
        raise HTTPException(
            status_code=200,
            detail={"code": "INVALID_TIMESTAMP", "message": "Invalid timestamp format"},
        )

    offset = abs(time.time() - ts)
    if offset > settings.MAX_TIMESTAMP_OFFSET:
        logger.warning(
            "Feishu webhook timestamp out of range: ts=%s server=%s offset=%.1fs",
            ts,
            int(time.time()),
            offset,
        )
        raise HTTPException(
            status_code=200,
            detail={
                "code": "TIMESTAMP_OUT_OF_RANGE",
                "message": f"Timestamp out of range (> {settings.MAX_TIMESTAMP_OFFSET}s)",
            },
        )

    # ── 3. Read request body ─────────────────────────────────────────────────
    body = await request.body()
    if not body:
        logger.warning("Feishu webhook empty body")
        raise HTTPException(
            status_code=200,
            detail={"code": "EMPTY_BODY", "message": "Empty request body"},
        )

    # ── 4. Compute expected signature ───────────────────────────────────────
    # Per Feishu docs: HMAC-SHA256(key=app_secret, value="{timestamp}\n{body}")
    message = f"{timestamp}\n{body.decode('utf-8')}".encode("utf-8")
    expected = hmac.new(
        settings.FEISHU_APP_SECRET.encode("utf-8"),
        message,
        hashlib.sha256,
    ).hexdigest()

    # ── 5. Constant-time comparison (timing attack mitigation) ───────────────
    if not hmac.compare_digest(expected, signature):
        logger.error(
            "Feishu webhook signature mismatch — possible forged request. "
            "timestamp=%s body_hash=%s",
            timestamp,
            hashlib.md5(body).hexdigest()[:8],
        )
        raise HTTPException(
            status_code=200,
            detail={"code": "INVALID_SIGNATURE", "message": "Signature verification failed"},
        )

    return body


def compute_signature(timestamp: str, body: str, app_secret: str) -> str:
    """
    Compute the Feishu-compatible HMAC-SHA256 signature.

    This is a standalone helper used in tests and during the URL verification
    challenge phase.
    """
    message = f"{timestamp}\n{body}".encode("utf-8")
    return hmac.new(
        app_secret.encode("utf-8"),
        message,
        hashlib.sha256,
    ).hexdigest()
