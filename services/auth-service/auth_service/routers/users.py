"""
Auth Service — Users Router
"""
from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional

from auth_service.database import get_db
from auth_service.schemas import UserResponse
from auth_service.service import verify_jwt, get_user_by_id, get_user_by_feishu_union_id, create_audit_log
from auth_service.models import User
from auth_service.config import settings

router = APIRouter(prefix="/users", tags=["users"])


async def get_current_user(
    authorization: Optional[str] = Header(None),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Dependency: validate JWT and return current user."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing authorization header")

    token = authorization[7:]
    payload = verify_jwt(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    user = await get_user_by_id(db, payload["sub"])
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found or inactive")
    return user


@router.get("/me", response_model=UserResponse)
async def get_me(current_user: User = Depends(get_current_user)):
    """Get current user info."""
    return UserResponse(
        id=current_user.id,
        email=current_user.email,
        role=current_user.role,
        feishu_union_id=current_user.feishu_union_id,
        is_active=current_user.is_active,
        created_at=current_user.created_at,
        updated_at=current_user.updated_at,
    )


@router.get("/by-feishu-id")
async def get_user_by_feishu_id(
    union_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Internal API: resolve feishu union_id to platform user.
    Used by Feishu Bot Service.
    Requires mTLS or internal network.
    """
    user = await get_user_by_feishu_union_id(db, union_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found or not bound to Feishu")
    return {
        "user_id": user.id,
        "email": user.email,
        "role": user.role,
        "feishu_union_id": user.feishu_union_id,
    }


# === Internal endpoints for inter-service communication ===
_internal_users_router = APIRouter(prefix="/internal/users", tags=["internal"])


async def _verify_internal_key(x_internal_api_key: str | None = Header(None)) -> str:
    """Verify X-Internal-API-Key header for internal service calls."""
    if x_internal_api_key is None or x_internal_api_key != settings.INTERNAL_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing internal API key")
    return x_internal_api_key


@_internal_users_router.get("/{user_id}/role")
async def get_user_role(
    user_id: str,
    _key: str = Depends(_verify_internal_key),
    db: AsyncSession = Depends(get_db),
):
    """
    Internal API: get user role and quota_group by user_id.
    Used by quota-service to resolve user roles.
    """
    user = await get_user_by_id(db, user_id)
    if not user:
        return {"role": "user", "quota_group": "user"}
    return {
        "role": user.role,
        "quota_group": user.role,  # quota_group maps to role in this implementation
    }


@_internal_users_router.get("/{user_id}")
async def get_user_info(
    user_id: str,
    _key: str = Depends(_verify_internal_key),
    db: AsyncSession = Depends(get_db),
):
    """
    Internal API: get user info (email, role) by user_id.
    Used by quota-service admin endpoints.
    """
    user = await get_user_by_id(db, user_id)
    if not user:
        return {"email": "unknown", "role": "user"}
    return {
        "email": user.email,
        "role": user.role,
    }
