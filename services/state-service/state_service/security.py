"""Request authentication and isolation helpers."""

from __future__ import annotations

from fastapi import Header, HTTPException, status

from state_service.config import settings
from state_service.schemas import RequestContext


def get_request_context(
    authorization: str | None = Header(default=None, alias="Authorization"),
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-ID"),
    x_user_id: str | None = Header(default=None, alias="X-User-ID"),
    x_session_id: str | None = Header(default=None, alias="X-Session-ID"),
    x_request_id: str | None = Header(default=None, alias="X-Request-ID"),
) -> RequestContext:
    """Validate caller and bind every operation to tenant/user context."""
    expected = f"Bearer {settings.internal_api_key}"
    if authorization != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid state service token",
        )
    if not x_user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="X-User-ID is required",
        )
    return RequestContext(
        tenant_id=x_tenant_id or settings.default_tenant_id,
        user_id=x_user_id,
        session_id=x_session_id,
        request_id=x_request_id,
    )
