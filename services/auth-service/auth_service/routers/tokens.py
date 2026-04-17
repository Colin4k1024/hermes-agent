"""
Auth Service — API Token Router
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime, timedelta, timezone
import uuid

from auth_service.database import get_db
from auth_service.schemas import (
    ApiTokenCreateResponse,
    ApiTokenInfo,
    ApiTokenListResponse,
    ApiTokenRevokeRequest,
    InternalVerifyRequest,
    InternalVerifyResponse,
)
from auth_service.service import (
    generate_api_token,
    hash_token,
    create_audit_log,
    verify_jwt,
    get_user_by_id,
)
from auth_service.redis_client import get_redis
from auth_service.config import settings
from auth_service.models import User, ApiToken
from auth_service.routers.users import get_current_user

router = APIRouter(prefix="/tokens", tags=["tokens"])


@router.post("", response_model=ApiTokenCreateResponse)
async def create_token(
    description: str | None = None,
    expires_days: int | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new API token for the current user."""
    token, prefix = generate_api_token()
    token_hash = hash_token(token)

    expires_at = None
    if expires_days:
        expires_at = datetime.now(timezone.utc) + timedelta(days=expires_days)

    api_token = ApiToken(
        id=str(uuid.uuid4()),
        user_id=current_user.id,
        token_hash=token_hash,
        token_prefix=prefix,
        description=description,
        expires_at=expires_at,
        is_active=True,
    )
    db.add(api_token)
    await create_audit_log(db, current_user.id, "token_create",
                           detail=f"Created token {prefix}...")
    await db.commit()

    return ApiTokenCreateResponse(
        token=token,
        token_prefix=prefix,
        expires_at=expires_at,
        created_at=api_token.created_at,
    )


@router.get("", response_model=ApiTokenListResponse)
async def list_tokens(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all API tokens for the current user."""
    from sqlalchemy import select
    result = await db.execute(
        select(ApiToken).where(
            ApiToken.user_id == current_user.id,
            ApiToken.is_active == True,
        ).order_by(ApiToken.created_at.desc())
    )
    tokens = result.scalars().all()
    return ApiTokenListResponse(
        tokens=[
            ApiTokenInfo(
                id=t.id,
                token_prefix=t.token_prefix,
                description=t.description,
                expires_at=t.expires_at,
                created_at=t.created_at,
                last_used_at=t.last_used_at,
                is_active=t.is_active,
            )
            for t in tokens
        ]
    )


@router.delete("/{token_id}")
async def revoke_token(
    token_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Revoke an API token."""
    from sqlalchemy import select
    result = await db.execute(
        select(ApiToken).where(
            ApiToken.id == token_id,
            ApiToken.user_id == current_user.id,
        )
    )
    token = result.scalar_one_or_none()
    if not token:
        raise HTTPException(status_code=404, detail="Token not found")

    token.is_active = False
    await create_audit_log(db, current_user.id, "token_revoke",
                           detail=f"Revoked token {token.token_prefix}...")
    await db.commit()
    return {"ok": True}


# === Internal API ===

_internal_router = APIRouter(prefix="/internal", tags=["internal"])


@_internal_router.post("/verify", response_model=InternalVerifyResponse)
async def verify_token(
    req: InternalVerifyRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Internal API: verify an API token.
    Returns user_id and role if valid.
    """
    # Check Redis cache first
    r = await get_redis()
    cache_key = f"{settings.REDIS_TOKEN_PREFIX}{hash_token(req.token)}"
    cached = await r.get(cache_key)
    if cached:
        # Parse cached result
        parts = cached.split("|")
        if len(parts) == 2:
            return InternalVerifyResponse(valid=True, user_id=parts[0], role=parts[1])

    # Hash and look up in DB
    token_hash = hash_token(req.token)
    from sqlalchemy import select
    result = await db.execute(
        select(ApiToken, User).join(User, ApiToken.user_id == User.id).where(
            ApiToken.token_hash == token_hash,
            ApiToken.is_active == True,
            User.is_active == True,
        )
    )
    row = result.one_or_none()
    if not row:
        return InternalVerifyResponse(valid=False, error="Invalid or revoked token")

    api_token, user = row[0], row[1]

    # Check expiry
    if api_token.expires_at and api_token.expires_at < datetime.now(timezone.utc):
        return InternalVerifyResponse(valid=False, error="Token expired")

    # Update last_used_at
    api_token.last_used_at = datetime.now(timezone.utc)

    # Cache in Redis (5 min TTL)
    await r.setex(cache_key, 300, f"{user.id}|{user.role}")
    await db.commit()

    return InternalVerifyResponse(valid=True, user_id=user.id, role=user.role)


@_internal_router.get("/health")
async def internal_health():
    """Lightweight health check for internal services."""
    return {"status": "ok"}
