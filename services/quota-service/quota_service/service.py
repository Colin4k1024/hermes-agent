"""Quota Service business logic layer."""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import NamedTuple
from uuid import UUID

import redis.asyncio as redis
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from quota_service import schemas as S
from quota_service.config import settings
from quota_service.models import QuotaConfig, UsageRecord
from quota_service.redis_client import check_quota_in_redis, get_daily_usage, increment_daily_usage


class QuotaInfo(NamedTuple):
    """Resolved quota for a user."""

    user_id: UUID
    role: str
    quota_group: str
    daily_token_limit: int
    daily_request_limit: int
    is_unlimited: bool
    used_tokens: int
    used_requests: int
    reset_at: str


def _utc_midnight(d: date | None = None) -> datetime:
    """Return the UTC midnight that starts today (quota reset boundary)."""
    if d is None:
        d = date.today(timezone.utc)
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)


async def resolve_user_quota(
    session: AsyncSession,
    redis_client: redis.Redis,
    user_id: UUID,
) -> QuotaInfo:
    """Look up the user's role and quota config, merge with Redis hot counter."""
    # TODO (Phase 2): call Auth Service to get user role
    # For Phase 1 dev, we look up from local users table via a join.
    # Since Auth Service owns users, we provide a lightweight user cache here.

    # Default fallback: treat as 'user' role
    role = "user"
    quota_group = "user"

    # Query quota config for the role
    stmt = select(QuotaConfig).where(QuotaConfig.quota_group == quota_group)
    result = await session.execute(stmt)
    config = result.scalar_one_or_none()

    if config is None:
        # Insert default config
        config = QuotaConfig(
            quota_group=quota_group,
            daily_token_limit=settings.default_quota_user,
            daily_request_limit=500,
        )
        session.add(config)
        await session.flush()

    daily_limit = config.daily_token_limit
    daily_request_limit = config.daily_request_limit

    # Read hot counter from Redis
    used_tokens, used_requests = await get_daily_usage(redis_client, str(user_id))

    is_unlimited = daily_limit < 0  # -1 means unlimited

    # Reset at next midnight UTC
    today = date.today(timezone.utc)
    reset_at = _utc_midnight(today).replace(hour=23, minute=59, second=59).isoformat()

    return QuotaInfo(
        user_id=user_id,
        role=role,
        quota_group=quota_group,
        daily_token_limit=daily_limit,
        daily_request_limit=daily_request_limit,
        is_unlimited=is_unlimited,
        used_tokens=used_tokens,
        used_requests=used_requests,
        reset_at=reset_at,
    )


async def check_quota(
    session: AsyncSession,
    redis_client: redis.Redis,
    user_id: UUID,
    estimated_tokens: int = 0,
) -> S.QuotaCheckResponse:
    """Pre-request quota check. Returns whether the request is allowed."""
    info = await resolve_user_quota(session, redis_client, user_id)

    if info.is_unlimited:
        return S.QuotaCheckResponse(
            allowed=True,
            result=S.QuotaCheckResult.UNLIMITED,
            user_id=user_id,
            role=info.role,
            quota_group=info.quota_group,
            daily_limit=info.daily_token_limit,
            used_tokens=info.used_tokens,
            remaining_tokens=-1,
            daily_request_limit=info.daily_request_limit,
            used_requests=info.used_requests,
            remaining_requests=-1,
            reset_at=info.reset_at,
        )

    remaining_tokens = max(0, info.daily_token_limit - info.used_tokens)
    remaining_requests = max(0, info.daily_request_limit - info.used_requests)
    allowed = remaining_tokens >= estimated_tokens and remaining_requests > 0

    return S.QuotaCheckResponse(
        allowed=allowed,
        result=S.QuotaCheckResult.ALLOWED if allowed else S.QuotaCheckResult.DENIED,
        user_id=user_id,
        role=info.role,
        quota_group=info.quota_group,
        daily_limit=info.daily_token_limit,
        used_tokens=info.used_tokens,
        remaining_tokens=remaining_tokens,
        daily_request_limit=info.daily_request_limit,
        used_requests=info.used_requests,
        remaining_requests=remaining_requests,
        reset_at=info.reset_at,
    )


async def consume_quota(
    session: AsyncSession,
    redis_client: redis.Redis,
    user_id: UUID,
    input_tokens: int,
    output_tokens: int,
    model: str | None = None,
    metadata: dict | None = None,
) -> S.QuotaConsumeResponse:
    """Record token consumption and persist to PostgreSQL."""
    total_tokens = input_tokens + output_tokens

    # Atomically increment Redis counter
    new_total_tokens, new_request_count = await increment_daily_usage(
        redis_client, str(user_id), total_tokens
    )

    # Persist to PostgreSQL (upsert today's record)
    today = date.today(timezone.utc)
    stmt = select(UsageRecord).where(
        UsageRecord.user_id == user_id,
        UsageRecord.record_date == today,
    )
    result = await session.execute(stmt)
    record = result.scalar_one_or_none()

    if record is None:
        record = UsageRecord(
            user_id=user_id,
            record_date=today,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            request_count=1,
        )
        session.add(record)
    else:
        record.input_tokens += input_tokens
        record.output_tokens += output_tokens
        record.total_tokens += total_tokens
        record.request_count += 1
        if model:
            record.model = model

    await session.flush()

    return S.QuotaConsumeResponse(
        success=True,
        user_id=user_id,
        tokens_consumed=total_tokens,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_daily_tokens=new_total_tokens,
        request_count=new_request_count,
        daily_limit=settings.default_quota_user,  # TODO: lookup from config
        remaining_tokens=max(0, settings.default_quota_user - new_total_tokens),
    )


async def process_llm_callback(
    session: AsyncSession,
    redis_client: redis.Redis,
    payload: S.LitellmCallbackRequest,
) -> S.QuotaConsumeResponse | None:
    """Process a LiteLLM usage callback.

    LiteLLM sends callbacks with user_id in the `user` field.
    We parse token counts from `usage` and record consumption.
    """
    if not payload.user:
        return None

    try:
        user_id = UUID(payload.user)
    except ValueError:
        # LiteLLM may send arbitrary user identifiers
        return None

    input_tokens = 0
    output_tokens = 0
    if payload.usage:
        input_tokens = payload.usage.prompt_tokens or 0
        output_tokens = payload.usage.completion_tokens or 0

    total = input_tokens + output_tokens
    if total == 0:
        return None

    return await consume_quota(
        session=session,
        redis_client=redis_client,
        user_id=user_id,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        model=payload.model,
        metadata={"call_type": payload.call_type, "total_cost": payload.total_cost},
    )


async def get_quota_status(
    session: AsyncSession,
    redis_client: redis.Redis,
    user_id: UUID,
) -> S.QuotaStatusResponse:
    """Return current quota status for a user."""
    info = await resolve_user_quota(session, redis_client, user_id)

    remaining_tokens = -1 if info.is_unlimited else max(0, info.daily_token_limit - info.used_tokens)
    remaining_requests = -1 if info.is_unlimited else max(0, info.daily_request_limit - info.used_requests)

    return S.QuotaStatusResponse(
        user_id=user_id,
        role=info.role,
        quota_group=info.quota_group,
        daily_limit=info.daily_token_limit,
        is_unlimited=info.is_unlimited,
        used_tokens=info.used_tokens,
        remaining_tokens=remaining_tokens,
        used_requests=info.used_requests,
        remaining_requests=remaining_requests,
        daily_request_limit=info.daily_request_limit,
        record_date=date.today(timezone.utc),
        reset_at=info.reset_at,
    )
