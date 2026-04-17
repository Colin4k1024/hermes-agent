"""
Auth Service — JWT Utilities
"""
import hmac
import hashlib
import uuid
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

from jose import jwt, JWTError
import bcrypt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth_service.config import settings
from auth_service.models import User, ApiToken, RefreshToken, AuditLog

ALGORITHM = "HS256"


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))


def create_access_token(user_id: str, role: str) -> tuple[str, int]:
    """Create JWT access token. Returns (token, expires_in_seconds)."""
    expires = datetime.now(timezone.utc) + timedelta(minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES)
    expires_ts = int(expires.timestamp())
    payload = {
        "sub": user_id,
        "role": role,
        "type": "access",
        "exp": expires_ts,
        "iat": int(datetime.now(timezone.utc).timestamp()),
    }
    token = jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=ALGORITHM)
    return token, settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60


def create_refresh_token(user_id: str) -> tuple[str, datetime]:
    """Create refresh token. Returns (token, expires_at)."""
    token = str(uuid.uuid4())
    expires = datetime.now(timezone.utc) + timedelta(days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS)
    return token, expires


def verify_jwt(token: str) -> Optional[dict]:
    """Verify JWT and return payload. Returns None if invalid."""
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[ALGORITHM])
        if payload.get("type") != "access":
            return None
        return payload
    except JWTError:
        return None


def generate_api_token() -> tuple[str, str]:
    """Generate a new API token. Returns (full_token, prefix)."""
    token = f"hms_{uuid.uuid4().hex}{uuid.uuid4().hex[:16]}"
    prefix = token[:16]
    return token, prefix


def create_audit_log(
    db: AsyncSession,
    user_id: Optional[str],
    event_type: str,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
    detail: Optional[str] = None,
):
    """Create an audit log entry."""
    log = AuditLog(
        id=str(uuid.uuid4()),
        user_id=user_id,
        event_type=event_type,
        ip_address=ip_address,
        user_agent=user_agent,
        detail=detail,
        created_at=datetime.now(timezone.utc),
    )
    db.add(log)
    return log


async def get_user_by_feishu_union_id(db: AsyncSession, union_id: str) -> Optional[User]:
    result = await db.execute(select(User).where(User.feishu_union_id == union_id))
    return result.scalar_one_or_none()


async def get_user_by_id(db: AsyncSession, user_id: str) -> Optional[User]:
    result = await db.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()


async def get_user_by_email(db: AsyncSession, email: str) -> Optional[User]:
    result = await db.execute(select(User).where(User.email == email))
    return result.scalar_one_or_none()


async def get_user_by_keycloak_sub(db: AsyncSession, keycloak_sub: str) -> Optional[User]:
    result = await db.execute(select(User).where(User.keycloak_sub == keycloak_sub))
    return result.scalar_one_or_none()


async def provision_user_from_oidc(
    db: AsyncSession,
    keycloak_sub: str,
    email: str,
    username: str,
    roles: list[str],
) -> User:
    """
    Provision or update a user from OIDC/Keycloak claims.
    Creates a new user if none exists (upsert by keycloak_sub).
    """
    import uuid

    # Try to find existing user by keycloak_sub
    user = await get_user_by_keycloak_sub(db, keycloak_sub)

    if user is None:
        # Check if a user with this email already exists (unclaimed)
        user = await get_user_by_email(db, email)
        if user is not None:
            # Claim this existing user
            user.keycloak_sub = keycloak_sub
        else:
            # Create brand new user
            user = User(
                id=str(uuid.uuid4()),
                email=email,
                password_hash=hash_password(str(uuid.uuid4())),  # Placeholder - no password login
                role="admin" if "admin" in roles else "user",
                keycloak_sub=keycloak_sub,
                is_active=True,
            )
            db.add(user)
    else:
        # Update existing user claims
        user.email = email
        user.role = "admin" if "admin" in roles else "user"

    await db.flush()
    return user
