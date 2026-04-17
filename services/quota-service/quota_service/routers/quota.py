"""Quota check, consume, and status endpoints."""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from quota_service import schemas as S
from quota_service.database import get_session
from quota_service.redis_client import get_redis
from quota_service.service import check_quota, consume_quota, get_quota_status

router = APIRouter(prefix="/quota", tags=["quota"])


@router.get("/check", response_model=S.QuotaCheckResponse)
async def quota_check(
    user_id: UUID = Query(..., description="User ID to check quota for"),
    estimated_tokens: int = Query(default=0, ge=0, description="Estimated token cost"),
    model: str | None = Query(default=None, description="Target LLM model"),
    session: AsyncSession = Depends(get_session),
) -> S.QuotaCheckResponse:
    """
    Pre-request quota check.

    Called by Agent Router before forwarding a request to the LLM.
    Returns whether the request is allowed and current usage stats.

    - **allowed**: true if the request should proceed
    - **429 Too Many Requests** is NOT returned here; the caller decides
      based on the `allowed` field.
    """
    redis_client = await get_redis()
    try:
        result = await check_quota(session, redis_client, user_id, estimated_tokens)
        return result
    finally:
        await redis_client.aclose()


@router.post("/consume", response_model=S.QuotaConsumeResponse)
async def quota_consume(
    req: S.QuotaConsumeRequest,
    session: AsyncSession = Depends(get_session),
) -> S.QuotaConsumeResponse:
    """
    Record token consumption after an LLM call.

    Called by Agent Router after receiving the LLM response.
    Atomically increments the Redis hot counter and persists to PostgreSQL.
    """
    redis_client = await get_redis()
    try:
        result = await consume_quota(
            session=session,
            redis_client=redis_client,
            user_id=req.user_id,
            input_tokens=req.input_tokens,
            output_tokens=req.output_tokens,
            model=req.model,
            metadata=req.metadata,
        )
        return result
    finally:
        await redis_client.aclose()


@router.post("/llm-callback", response_model=S.LLMTokensResponse)
async def llm_callback(
    payload: S.LitellmCallbackRequest,
    session: AsyncSession = Depends(get_session),
) -> S.LLMTokensResponse:
    """
    LiteLLM proxy usage callback endpoint.

    LiteLLM can be configured to POST usage data to this endpoint
    after each LLM call. We parse the user_id from the `user` field
    and record token consumption.

    Reference: https://docs.litellm.ai/docs/proxy/callbacks#usage---tracking-llm-cost-per-user

    This endpoint is lightweight and intentionally returns 200 even on
    parsing errors (LiteLLM doesn't retry failed callbacks by default).
    """
    redis_client = await get_redis()
    try:
        result = await consume_quota(
            session=session,
            redis_client=redis_client,
            user_id=UUID(payload.user),
            input_tokens=payload.usage.prompt_tokens if payload.usage else 0,
            output_tokens=payload.usage.completion_tokens if payload.usage else 0,
            model=payload.model,
            metadata={"call_type": payload.call_type, "total_cost": payload.total_cost},
        )
        return S.LLMTokensResponse(status="recorded", tokens=result.tokens_consumed)
    except (ValueError, Exception):
        # LiteLLM callbacks are fire-and-forget; don't block the proxy
        return S.LLMTokensResponse(status="ignored")
    finally:
        await redis_client.aclose()


@router.get("/status", response_model=S.QuotaStatusResponse)
async def quota_status(
    user_id: UUID = Query(..., description="User ID"),
    session: AsyncSession = Depends(get_session),
) -> S.QuotaStatusResponse:
    """
    Query current quota status for a user.

    Returns daily usage, remaining tokens, and when the quota resets.
    """
    redis_client = await get_redis()
    try:
        result = await get_quota_status(session, redis_client, user_id)
        return result
    finally:
        await redis_client.aclose()
