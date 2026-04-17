"""Internal HTTP client for talking to other platform services (Auth Service, Router)."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

import httpx

from fbot.config import get_settings
from fbot.models.events import AuthUserByFeishuIdResponse

logger = logging.getLogger(__name__)


async def lookup_user_by_feishu_id(
    union_id: str,
) -> tuple[Optional[AuthUserByFeishuIdResponse], Optional[str]]:
    """
    Query Auth Service for the platform user_id mapped to a Feishu union_id.

    Returns
    -------
    (response, None)         — user found; response.user_id is the platform user_id
    (None, "not_bound")      — union_id not found in the platform
    (None, "error")          — Auth Service itself returned an error
    """
    settings = get_settings()
    url = f"{settings.AUTH_SERVICE_URL}{settings.AUTH_BY_FEISHU_ID_PATH}"
    params = {"union_id": union_id}

    try:
        async with httpx.AsyncClient(timeout=settings.AUTH_INTERNAL_TIMEOUT_SECONDS) as client:
            resp = await client.get(url, params=params)

        if resp.status_code == 404:
            logger.debug("union_id=%s not bound to any platform user", union_id)
            return None, "not_bound"

        if resp.status_code == 200:
            data = resp.json()
            logger.debug("union_id=%s → user_id=%s", union_id, data.get("user_id"))
            return AuthUserByFeishuIdResponse(**data), None

        # Unexpected status
        logger.warning(
            "Auth Service /by-feishu-id returned %s for union_id=%s: %s",
            resp.status_code,
            union_id,
            resp.text[:200],
        )
        return None, "error"

    except httpx.TimeoutException:
        logger.warning("Auth Service timeout looking up union_id=%s", union_id)
        return None, "error"
    except httpx.RequestError as exc:
        logger.error("Auth Service connection error for union_id=%s: %s", union_id, exc)
        return None, "error"
