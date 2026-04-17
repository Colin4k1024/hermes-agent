"""Admin endpoints for quota configuration and usage monitoring."""
from __future__ import annotations

from datetime import date, datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from quota_service import schemas as S
from quota_service.database import get_session
from quota_service.models import QuotaConfig, UsageRecord
from quota_service.redis_client import get_redis
from quota_service.auth_client import auth_client

router = APIRouter(prefix="/admin/quota", tags=["admin"])


async def _verify_admin_key(x_admin_key: str | None = Header(None)) -> str:
    """Dependency: verify X-Admin-Key header."""
    from quota_service.config import settings

    if x_admin_key is None or x_admin_key != settings.admin_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing X-Admin-Key",
        )
    return x_admin_key


@router.get("/configs", response_model=list[S.QuotaConfigResponse])
async def list_quota_configs(
    session: AsyncSession = Depends(get_session),
    _admin: str = Depends(_verify_admin_key),
) -> list[S.QuotaConfigResponse]:
    """List all quota configurations."""
    stmt = select(QuotaConfig).order_by(QuotaConfig.quota_group)
    result = await session.execute(stmt)
    return list(result.scalars().all())


@router.put("/configs/{quota_group}", response_model=S.QuotaConfigResponse)
async def update_quota_config(
    quota_group: str,
    update: S.QuotaConfigUpdate,
    session: AsyncSession = Depends(get_session),
    _admin: str = Depends(_verify_admin_key),
) -> S.QuotaConfigResponse:
    """Update an existing quota configuration."""
    stmt = select(QuotaConfig).where(QuotaConfig.quota_group == quota_group)
    result = await session.execute(stmt)
    config = result.scalar_one_or_none()

    if config is None:
        raise HTTPException(status_code=404, detail=f"Quota config '{quota_group}' not found")

    if update.daily_token_limit is not None:
        config.daily_token_limit = update.daily_token_limit
    if update.daily_request_limit is not None:
        config.daily_request_limit = update.daily_request_limit
    if update.model_allowlist is not None:
        config.model_allowlist = update.model_allowlist

    config.update_time = datetime.now(timezone.utc)
    await session.flush()
    await session.refresh(config)
    return config


@router.get("/usage", response_model=list[S.AdminQuotaUsageResponse])
async def get_usage(
    user_id: UUID | None = Query(default=None, description="Filter by user"),
    from_date: date | None = Query(default=None, description="Start date (YYYY-MM-DD)"),
    to_date: date | None = Query(default=None, description="End date (YYYY-MM-DD)"),
    limit: int = Query(default=100, ge=1, le=1000),
    session: AsyncSession = Depends(get_session),
    _admin: str = Depends(_verify_admin_key),
) -> list[S.AdminQuotaUsageResponse]:
    """Query usage records with optional filters."""
    if from_date is None:
        from_date = date.today(timezone.utc)
    if to_date is None:
        to_date = from_date

    stmt = (
        select(
            UsageRecord.user_id,
            func.sum(UsageRecord.total_tokens).label("total_tokens"),
            func.sum(UsageRecord.request_count).label("total_requests"),
            func.count(UsageRecord.id).label("record_count"),
        )
        .where(UsageRecord.record_date >= from_date)
        .where(UsageRecord.record_date <= to_date)
        .group_by(UsageRecord.user_id)
    )

    if user_id is not None:
        stmt = stmt.where(UsageRecord.user_id == user_id)

    stmt = stmt.order_by(func.sum(UsageRecord.total_tokens).desc()).limit(limit)
    result = await session.execute(stmt)
    rows = result.all()

    # Build response, fetching user info from auth-service and quota config
    responses = []
    for row in rows:
        user_id_str = str(row.user_id)

        # Get user info from auth-service
        try:
            user_info = await auth_client.get_user_info(user_id_str)
            username = user_info.get("email", "unknown")
            role = user_info.get("role", "user")
            quota_group = role  # quota_group maps to role
        except Exception:
            username = "unknown"
            role = "user"
            quota_group = "user"

        # Look up daily_limit from QuotaConfig
        stmt_cfg = select(QuotaConfig).where(QuotaConfig.quota_group == quota_group)
        result_cfg = await session.execute(stmt_cfg)
        quota_cfg = result_cfg.scalar_one_or_none()
        daily_limit = quota_cfg.daily_token_limit if quota_cfg else 100_000
        usage_percentage = (int(row.total_tokens or 0) / daily_limit * 100) if daily_limit > 0 else 0.0

        responses.append(
            S.AdminQuotaUsageResponse(
                user_id=row.user_id,
                username=username,
                role=role,
                quota_group=quota_group,
                record_date=from_date,
                used_tokens=int(row.total_tokens or 0),
                used_requests=int(row.total_requests or 0),
                daily_limit=daily_limit,
                usage_percentage=usage_percentage,
            )
        )

    return responses


@router.get("/dashboard", response_model=S.AdminDashboardResponse)
async def dashboard(
    session: AsyncSession = Depends(get_session),
    _admin: str = Depends(_verify_admin_key),
) -> S.AdminDashboardResponse:
    """Aggregate quota usage dashboard."""
    today = date.today(timezone.utc)

    # Total tokens/requests today
    stmt = select(
        func.count(func.distinct(UsageRecord.user_id)).label("total_users"),
        func.coalesce(func.sum(UsageRecord.total_tokens), 0).label("total_tokens"),
        func.coalesce(func.sum(UsageRecord.request_count), 0).label("total_requests"),
    ).where(UsageRecord.record_date == today)
    result = await session.execute(stmt)
    row = result.one()

    return S.AdminDashboardResponse(
        total_users=int(row.total_users or 0),
        total_tokens_today=int(row.total_tokens or 0),
        total_requests_today=int(row.total_requests or 0),
        users_at_limit=0,
        top_users=[],
    )
