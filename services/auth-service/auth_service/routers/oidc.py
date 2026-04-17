"""
Auth Service — OIDC Router (Keycloak Authorization Code Flow)
"""
import json
import secrets
import time
import uuid
from typing import Optional

import requests
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from jose import jwt, JWTError
from sqlalchemy.ext.asyncio import AsyncSession

from auth_service.config import settings
from auth_service.database import get_db
from auth_service.models import RefreshToken, User
from auth_service.redis_client import get_redis
from auth_service.schemas import LoginResponse
from auth_service.service import (
    create_access_token,
    create_audit_log,
    create_refresh_token,
    hash_token,
    provision_user_from_oidc,
)

router = APIRouter(prefix="/auth/oidc", tags=["oidc"])

# ─── JWKS Caching ─────────────────────────────────────────────────────────────

_JWKS_CACHE: dict = {}
_JWKS_CACHE_TTL: int = 3600  # seconds


def _get_cached_jwks(issuer: str) -> dict:
    """
    Fetch and cache JWKS from {issuer}/.well-known/jwks.json.
    Returns the JWKS dict. Raises HTTPException(503) if Keycloak unreachable.
    """
    global _JWKS_CACHE, _JWKS_CACHE_TTL

    cache_key = issuer
    now = time.time()

    if cache_key in _JWKS_CACHE:
        jwks_data, fetched_at = _JWKS_CACHE[cache_key]
        if now - fetched_at < _JWKS_CACHE_TTL:
            return jwks_data

    jwks_url = f"{issuer.rstrip('/')}/.well-known/jwks.json"
    try:
        resp = requests.get(jwks_url, timeout=10)
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Keycloak JWKS endpoint unreachable ({jwks_url}): {exc}",
        )

    _JWKS_CACHE[cache_key] = (resp.json(), now)
    return resp.json()


def _get_signing_key(jwks: dict, kid: str) -> Optional[dict]:
    """Find the signing key in JWKS by kid."""
    for key in jwks.get("keys", []):
        if key.get("kid") == kid:
            return key
    return None


# ─── OIDC Authorization Endpoint helpers ──────────────────────────────────────

def _build_authorization_url(state: str, nonce: str) -> str:
    """Build Keycloak authorization URL."""
    params = {
        "response_type": "code",
        "client_id": settings.OIDC_CLIENT_ID,
        "redirect_uri": settings.OIDC_REDIRECT_URI,
        "scope": "openid profile email",
        "state": state,
        "nonce": nonce,
    }
    query = "&".join(f"{k}={requests.utils.quote(v)}" for k, v in params.items())
    return f"{settings.OIDC_ISSUER.rstrip('/')}/protocol/openid-connect/auth?{query}"


async def _store_oidc_state(state: str, nonce: str, expires: int = 600) -> None:
    """Store state + nonce in Redis for CSRF/replay protection."""
    redis = await get_redis()
    key = f"oidc:state:{state}"
    await redis.setex(key, expires, json.dumps({"nonce": nonce}))


async def _get_and_clear_oidc_state(state: str) -> Optional[str]:
    """
    Retrieve and delete the stored nonce for a given state (single-use).
    Returns the nonce string or None if state not found/expired.
    """
    redis = await get_redis()
    key = f"oidc:state:{state}"
    value = await redis.get(key)
    if value is None:
        return None
    await redis.delete(key)
    return json.loads(value).get("nonce")


# ─── Routes ───────────────────────────────────────────────────────────────────

@router.get("/login", status_code=302)
async def oidc_login(request: Request):
    """
    Step 1 of OIDC Authorization Code Flow.
    Redirects the browser to Keycloak's authorization endpoint.
    """
    if settings.OIDC_MOCK_ENABLED:
        raise HTTPException(
            status_code=501,
            detail="OIDC not configured (OIDC_MOCK_ENABLED=True). Use POST /auth/login for mock login.",
        )

    # Generate CSRF state and nonce
    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)

    # Store state → nonce mapping (single-use, 10 min TTL)
    await _store_oidc_state(state, nonce)

    # Build redirect to Keycloak
    redirect = RedirectResponse(
        url=_build_authorization_url(state, nonce),
        status_code=302,
    )
    redirect.set_cookie(
        key="oidc_state",
        value=state,
        httponly=True,
        secure=False,  # Set True in production with HTTPS
        samesite="lax",
        max_age=600,
    )
    return redirect


@router.get("/callback")
async def oidc_callback(
    request: Request,
    code: str = Query(..., description="Authorization code from Keycloak"),
    state: str = Query(..., description="CSRF state parameter"),
    db: AsyncSession = Depends(get_db),
):
    """
    Step 2 of OIDC Authorization Code Flow.
    Exchanges the authorization code for tokens, validates the ID token,
    provisions the user, and returns JWT access + refresh tokens.
    """
    if settings.OIDC_MOCK_ENABLED:
        raise HTTPException(
            status_code=501,
            detail="OIDC not configured (OIDC_MOCK_ENABLED=True). Use POST /auth/login for mock login.",
        )

    # ── 1. Validate state (CSRF protection) ──────────────────────────────────
    expected_state_cookie = request.cookies.get("oidc_state")
    if expected_state_cookie is None or expected_state_cookie != state:
        raise HTTPException(status_code=400, detail="Invalid or missing state parameter")

    stored_nonce = await _get_and_clear_oidc_state(state)
    if stored_nonce is None:
        raise HTTPException(status_code=400, detail="State expired or already used")

    # ── 2. Exchange code for tokens at Keycloak token endpoint ────────────────
    token_url = f"{settings.OIDC_ISSUER.rstrip('/')}/protocol/openid-connect/token"
    token_data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": settings.OIDC_REDIRECT_URI,
        "client_id": settings.OIDC_CLIENT_ID,
        "client_secret": settings.OIDC_CLIENT_SECRET,
    }

    try:
        token_resp = requests.post(token_url, data=token_data, timeout=15)
        token_resp.raise_for_status()
    except requests.RequestException as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Keycloak token endpoint unreachable: {exc}",
        )

    tokens = token_resp.json()

    id_token_str = tokens.get("id_token")
    if not id_token_str:
        raise HTTPException(status_code=502, detail="No ID token returned by Keycloak")

    # ── 3. Fetch JWKS and validate ID token signature ─────────────────────────
    try:
        jwks = _get_cached_jwks(settings.OIDC_ISSUER)
    except HTTPException:
        raise

    try:
        # Decode without verification first to get the kid
        unverified = jwt.get_unverified_header(id_token_str)
        kid = unverified.get("kid")
        if not kid:
            raise HTTPException(status_code=502, detail="ID token missing 'kid' header")

        signing_key = _get_signing_key(jwks, kid)
        if not signing_key:
            # Key not found — invalidate cache and retry once (key rotation)
            global _JWKS_CACHE
            _JWKS_CACHE.pop(settings.OIDC_ISSUER, None)
            jwks = _get_cached_jwks(settings.OIDC_ISSUER)
            signing_key = _get_signing_key(jwks, kid)
            if not signing_key:
                raise HTTPException(status_code=502, detail=f"Signing key '{kid}' not found in JWKS")

        id_token = jwt.decode(
            id_token_str,
            signing_key,
            algorithms=["RS256"],
            audience=settings.OIDC_CLIENT_ID,
            issuer=settings.OIDC_ISSUER,
        )
    except JWTError as exc:
        raise HTTPException(status_code=401, detail=f"ID token validation failed: {exc}")

    # ── 4. Validate nonce (replay attack protection) ─────────────────────────
    token_nonce = id_token.get("nonce")
    if token_nonce != stored_nonce:
        raise HTTPException(status_code=401, detail="Nonce mismatch — possible replay attack")

    # ── 5. Extract user claims ───────────────────────────────────────────────
    sub: str = id_token.get("sub", "")
    email: str = id_token.get("email", "")
    preferred_username: str = id_token.get("preferred_username", id_token.get("username", ""))
    roles: list[str] = (
        id_token.get("realm_access", {}).get("roles", [])
        + id_token.get("resource_access", {}).get(settings.OIDC_CLIENT_ID, {}).get("roles", [])
    )

    if not sub:
        raise HTTPException(status_code=502, detail="ID token missing 'sub' claim")
    if not email:
        raise HTTPException(status_code=502, detail="ID token missing 'email' claim")

    # ── 6. Provision user in DB ───────────────────────────────────────────────
    user = await provision_user_from_oidc(db, sub, email, preferred_username, roles)

    # ── 7. Issue JWT access + refresh tokens ─────────────────────────────────
    jwt_access, expires_in = create_access_token(user.id, user.role)
    refresh_tok, refresh_expires = create_refresh_token(user.id)

    # Store refresh token hash
    rt_hash = hash_token(refresh_tok)
    rt = RefreshToken(
        id=str(uuid.uuid4()),
        user_id=user.id,
        token_hash=rt_hash,
        expires_at=refresh_expires,
        revoked=False,
    )
    db.add(rt)

    # ── 8. Audit log ──────────────────────────────────────────────────────────
    await create_audit_log(
        db, user.id, "login",
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        detail="OIDC/Keycloak login",
    )
    await db.commit()

    # ── 9. Redirect to frontend with tokens in fragment ─────────────────────
    response_data = LoginResponse(
        access_token=jwt_access,
        refresh_token=refresh_tok,
        expires_in=expires_in,
    )

    frontend_url = settings.CORS_ORIGINS[0] if settings.CORS_ORIGINS else "http://localhost:3000"
    fragment = response_data.model_dump_json()
    redirect_url = f"{frontend_url}/auth/callback#{fragment}"

    redirect = RedirectResponse(url=redirect_url, status_code=302)
    redirect.delete_cookie("oidc_state")
    return redirect


@router.get("/userinfo")
async def oidc_userinfo(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Returns the current user's OIDC claims (for debugging/introspection).
    Requires a valid Hermes JWT access token.
    """
    from auth_service.service import verify_jwt

    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Authorization header")

    payload = verify_jwt(auth[7:])
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired access token")

    user_id = payload.get("sub")
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    return {
        "sub": user.keycloak_sub,
        "email": user.email,
        "role": user.role,
        "is_active": user.is_active,
    }
