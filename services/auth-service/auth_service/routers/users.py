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
