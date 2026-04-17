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
    action: Optional[str] = None,
    user_id: Optional[str] = None,
    keyword: Optional[str] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    page: int = 1,
    page_size: int = 50,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Admin: list audit logs with filters and pagination."""
    from sqlalchemy import select, desc, func, or_

    query = select(AuditLog)
    count_query = select(func.count(AuditLog.id))

    if action:
        query = query.where(AuditLog.event_type == action)
        count_query = count_query.where(AuditLog.event_type == action)
    if user_id:
        query = query.where(AuditLog.user_id == user_id)
        count_query = count_query.where(AuditLog.user_id == user_id)
    if keyword:
        kw_filter = or_(
            AuditLog.detail.ilike(f"%{keyword}%"),
            AuditLog.user_id.ilike(f"%{keyword}%"),
        )
        query = query.where(kw_filter)
        count_query = count_query.where(kw_filter)
    if start_date:
        query = query.where(AuditLog.created_at >= start_date)
        count_query = count_query.where(AuditLog.created_at >= start_date)
    if end_date:
        query = query.where(AuditLog.created_at <= end_date)
        count_query = count_query.where(AuditLog.created_at <= end_date)

    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    offset = (page - 1) * page_size
    result = await db.execute(
        query.order_by(desc(AuditLog.created_at)).offset(offset).limit(page_size)
    )
    logs = result.scalars().all()

    # Map event_type -> action label for frontend compatibility
    from auth_service.service import get_user_by_id
    rows = []
    for log in logs:
        user_email = ""
        if log.user_id:
            user = await get_user_by_id(db, log.user_id)
            if user:
                user_email = user.email
        rows.append({
            "id": log.id,
            "user_id": log.user_id or "",
            "username": user_email,
            "action": log.event_type,
            "resource": f"/{log.event_type}",
            "detail": log.detail or "",
            "ip": log.ip_address or "",
            "timestamp": log.created_at.isoformat(),
        })

    return {"data": rows, "total": total, "page": page, "page_size": page_size}
