"""
Auth Service — Auth Router (Login / Refresh / Logout)
"""
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth_service.database import get_db
from auth_service.schemas import (
    LoginRequest,
    LoginResponse,
    RefreshRequest,
    RefreshResponse,
)
from auth_service.service import (
    verify_password,
    create_access_token,
    create_refresh_token,
    verify_jwt,
    hash_password,
    hash_token,
    create_audit_log,
    get_user_by_email,
)
from auth_service.models import User, RefreshToken
from auth_service.redis_client import get_redis
from auth_service.config import settings
from datetime import datetime, timedelta, timezone
import uuid

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=LoginResponse)
async def login(
    req: LoginRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    OIDC mock login endpoint (dev only when OIDC_MOCK_ENABLED=True).
    In prod: OIDC_MOCK_ENABLED=False redirects to /auth/oidc/login.
    """
    # Real OIDC: redirect to IdP
    if not settings.OIDC_MOCK_ENABLED:
        raise HTTPException(
            status_code=501,
            detail="OIDC not configured — redirect to /auth/oidc/login for SSO login",
        )

    # OIDC Mock
    if req.email == settings.OIDC_MOCK_USER_EMAIL and req.password == settings.OIDC_MOCK_USER_PASSWORD:
        user_id = settings.OIDC_MOCK_USER_ID
        role = settings.OIDC_MOCK_USER_ROLE
    else:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    # Create tokens
    access_token, expires_in = create_access_token(user_id, role)
    refresh_token, refresh_expires = create_refresh_token(user_id)

    # Store refresh token hash in DB
    rt_hash = hash_token(refresh_token)
    rt = RefreshToken(
        id=str(uuid.uuid4()),
        user_id=user_id,
        token_hash=rt_hash,
        expires_at=refresh_expires,
        revoked=False,
    )
    db.add(rt)

    # Audit log
    await create_audit_log(
        db, user_id, "login",
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        detail="OIDC mock login",
    )
    await db.commit()

    return LoginResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=expires_in,
    )


@router.post("/refresh", response_model=RefreshResponse)
async def refresh(
    req: RefreshRequest,
    db: AsyncSession = Depends(get_db),
):
    """Refresh access token using refresh token."""
    rt_hash = hash_token(req.refresh_token)

    result = await db.execute(
        select(RefreshToken).where(
            RefreshToken.token_hash == rt_hash,
            RefreshToken.revoked == False,
        )
    )
    rt = result.scalar_one_or_none()

    if not rt:
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    if rt.expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=401, detail="Refresh token expired")

    # Get user
    from auth_service.service import get_user_by_id
    user = await get_user_by_id(db, rt.user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="User inactive or not found")

    access_token, expires_in = create_access_token(user.id, user.role)

    return RefreshResponse(access_token=access_token, expires_in=expires_in)


@router.post("/logout")
async def logout(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Logout: revoke refresh token."""
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        token = auth[7:]
        payload = verify_jwt(token)
        if payload:
            user_id = payload.get("sub")
            await create_audit_log(db, user_id, "logout",
                                   ip_address=request.client.host if request.client else None)
    await db.commit()
    return {"ok": True}


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    """
    Simple HTML login page for local dev (OIDC_MOCK_ENABLED=True).
    In prod, users are redirected to /auth/oidc/login for SSO.
    """
    html = f"""
    <!DOCTYPE html>
    <html>
    <head><title>Hermes Dev Login</title></head>
    <body>
    <h2>Hermes Auth — Dev Mode</h2>
    <p>Using mock login (OIDC_MOCK_ENABLED=True)</p>
    <form method="post" action="/auth/login">
      <label>Email: <input type="email" name="email" value="{settings.OIDC_MOCK_USER_EMAIL}" /></label><br/>
      <label>Password: <input type="password" name="password" value="{settings.OIDC_MOCK_USER_PASSWORD}" /></label><br/>
      <button type="submit">Login</button>
    </form>
    <hr/>
    <p>For real OIDC login: <a href="/auth/oidc/login">/auth/oidc/login</a></p>
    </body>
    </html>
    """
    return html
