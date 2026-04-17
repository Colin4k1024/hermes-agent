"""
Auth Service — Admin Router
"""
from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional
import uuid
from datetime import datetime, timezone

from auth_service.database import get_db
from auth_service.models import User, AuditLog
from auth_service.service import hash_password, verify_jwt, create_audit_log
from auth_service.schemas import UserResponse
from auth_service.routers.users import get_current_user

router = APIRouter(prefix="/admin", tags=["admin"])


def require_admin(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return current_user


@router.post("/users")
async def create_user(
    email: str,
    password: str,
    role: str = "user",
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Admin: create a new user."""
    from sqlalchemy import select
    result = await db.execute(select(User).where(User.email == email))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Email already exists")

    user = User(
        id=str(uuid.uuid4()),
        email=email,
        password_hash=hash_password(password),
        role=role,
        is_active=True,
    )
    db.add(user)
    await create_audit_log(db, admin.id, "user_create",
                           detail=f"Created user {email} as {role}")
    await db.commit()
    return {"id": user.id, "email": user.email, "role": user.role}


@router.get("/users/{user_id}", response_model=UserResponse)
async def get_user(
    user_id: str,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Admin: get user by ID."""
    from sqlalchemy import select
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return UserResponse(
        id=user.id,
        email=user.email,
        role=user.role,
        feishu_union_id=user.feishu_union_id,
        is_active=user.is_active,
        created_at=user.created_at,
        updated_at=user.updated_at,
    )


@router.delete("/users/{user_id}")
async def deactivate_user(
    user_id: str,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Admin: deactivate a user."""
    from sqlalchemy import select
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.is_active = False
    await create_audit_log(db, admin.id, "user_deactivate",
                           detail=f"Deactivated user {user.email}")
    await db.commit()
    return {"ok": True}


@router.get("/audit-logs")
async def list_audit_logs(
    limit: int = 50,
    offset: int = 0,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Admin: list audit logs."""
    from sqlalchemy import select, desc
    result = await db.execute(
        select(AuditLog).order_by(desc(AuditLog.created_at)).offset(offset).limit(limit)
    )
    logs = result.scalars().all()
    total_result = await db.execute(select(AuditLog.id.count()))
    total = total_result.scalar()
    return {"logs": [{
        "id": log.id,
        "user_id": log.user_id,
        "event_type": log.event_type,
        "ip_address": log.ip_address,
        "detail": log.detail,
        "created_at": log.created_at.isoformat(),
    } for log in logs], "total": total}
