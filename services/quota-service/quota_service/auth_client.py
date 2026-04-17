"""Auth Service HTTP client for user role lookups."""
from __future__ import annotations

from typing import Any

import httpx

from quota_service.config import settings


class AuthServiceError(Exception):
    pass


class AuthServiceClient:
    """Minimal client for the Auth Service internal API."""

    def __init__(self, base_url: str | None = None) -> None:
        self.base_url = base_url or settings.auth_service_url
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(base_url=self.base_url, timeout=5.0)
        return self._client

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def verify_token(self, token: str) -> dict[str, Any]:
        """Verify a JWT or API token and return user info."""
        client = await self._get_client()
        resp = await client.post(
            "/auth/token/verify",
            headers={"Authorization": f"Bearer {token}"},
        )
        if resp.status_code == 401:
            raise AuthServiceError("Invalid token")
        if resp.status_code != 200:
            raise AuthServiceError(f"Auth service error: {resp.status_code}")
        return resp.json()

    async def get_user_info(self, user_id: str) -> dict[str, Any]:
        """Get user info by user_id."""
        client = await self._get_client()
        resp = await client.get(f"/auth/users/{user_id}")
        if resp.status_code == 404:
            raise AuthServiceError("User not found")
        if resp.status_code != 200:
            raise AuthServiceError(f"Auth service error: {resp.status_code}")
        return resp.json()


auth_client = AuthServiceClient()
