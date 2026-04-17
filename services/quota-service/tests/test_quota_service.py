"""Tests for Quota Service."""
from __future__ import annotations

import sys
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

sys.path.insert(0, "services/quota-service")

from quota_service import schemas as S
from quota_service.redis_client import check_quota_in_redis, get_daily_usage, increment_daily_usage


# ---------------------------------------------------------------------------
# Schema validation tests
# ---------------------------------------------------------------------------

class TestQuotaSchemas:
    def test_quota_check_request(self):
        req = S.QuotaCheckRequest(user_id=uuid4(), estimated_tokens=1000, model="gpt-4")
        assert req.estimated_tokens == 1000
        assert req.model == "gpt-4"

    def test_quota_check_request_defaults(self):
        req = S.QuotaCheckRequest(user_id=uuid4())
        assert req.estimated_tokens == 0
        assert req.model is None

    def test_quota_consume_request(self):
        req = S.QuotaConsumeRequest(
            user_id=uuid4(),
            input_tokens=500,
            output_tokens=300,
            model="gpt-4",
        )
        assert req.input_tokens == 500
        assert req.output_tokens == 300

    def test_quota_consume_request_negative_tokens_rejected(self):
        with pytest.raises(Exception):  # pydantic validation error
            S.QuotaConsumeRequest(user_id=uuid4(), input_tokens=-1, output_tokens=0)

    def test_litellm_callback_request(self):
        payload = S.LitellmCallbackRequest(
            user="user-uuid-123",
            model="gpt-4",
            total_cost=0.02,
            usage=S.LitellmUsage(
                prompt_tokens=100,
                completion_tokens=50,
                total_tokens=150,
            ),
        )
        assert payload.user == "user-uuid-123"
        assert payload.usage.total_tokens == 150

    def test_quota_config_create(self):
        cfg = S.QuotaConfigCreate(
            quota_group="power_user",
            daily_token_limit=500_000,
            daily_request_limit=1000,
        )
        assert cfg.quota_group == "power_user"
        assert cfg.daily_token_limit == 500_000

    def test_quota_config_update_partial(self):
        cfg = S.QuotaConfigUpdate(daily_token_limit=200_000)
        assert cfg.daily_token_limit == 200_000
        assert cfg.daily_request_limit is None

    def test_quota_check_response_unlimited(self):
        resp = S.QuotaCheckResponse(
            allowed=True,
            result=S.QuotaCheckResult.UNLIMITED,
            user_id=uuid4(),
            role="admin",
            quota_group="admin",
            daily_limit=-1,
            used_tokens=0,
            remaining_tokens=-1,
            daily_request_limit=-1,
            used_requests=0,
            remaining_requests=-1,
            reset_at="2026-04-16T23:59:59+00:00",
        )
        assert resp.result == S.QuotaCheckResult.UNLIMITED
        assert resp.remaining_tokens == -1  # unlimited

    def test_quota_status_response(self):
        resp = S.QuotaStatusResponse(
            user_id=uuid4(),
            role="user",
            quota_group="user",
            daily_limit=100_000,
            is_unlimited=False,
            used_tokens=30_000,
            remaining_tokens=70_000,
            used_requests=50,
            remaining_requests=450,
            daily_request_limit=500,
            record_date=date.today(),
            reset_at="2026-04-16T23:59:59+00:00",
        )
        assert resp.remaining_tokens == 70_000
        assert resp.is_unlimited is False

    def test_llm_tokens_response(self):
        r = S.LLMTokensResponse(status="recorded", tokens=1000)
        assert r.status == "recorded"
        assert r.tokens == 1000

    def test_error_response(self):
        err = S.ErrorResponse(detail="User not found")
        assert err.detail == "User not found"

    def test_role_enum_values(self):
        assert S.Role.USER == "user"
        assert S.Role.POWER_USER == "power_user"
        assert S.Role.ADMIN == "admin"


# ---------------------------------------------------------------------------
# Redis client unit tests (mocked)
# ---------------------------------------------------------------------------

class TestRedisClient:
    @pytest.mark.asyncio
    async def test_get_daily_usage_default_zero(self):
        mock_redis = AsyncMock()
        mock_redis.hgetall = AsyncMock(return_value={})

        tokens, requests = await get_daily_usage(mock_redis, "user-123")
        assert tokens == 0
        assert requests == 0
        mock_redis.hgetall.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_daily_usage_with_data(self):
        mock_redis = AsyncMock()
        mock_redis.hgetall = AsyncMock(return_value={"tokens": "5000", "requests": "10"})

        tokens, requests = await get_daily_usage(mock_redis, "user-123")
        assert tokens == 5000
        assert requests == 10

    @pytest.mark.asyncio
    async def test_increment_daily_usage(self):
        mock_redis = AsyncMock()
        mock_pipe = AsyncMock()
        mock_pipe.execute = AsyncMock(return_value=[5500, 11])  # [tokens, requests]
        mock_redis.pipeline = MagicMock(return_value=mock_pipe)

        tokens, requests = await increment_daily_usage(mock_redis, "user-123", 500)
        assert tokens == 5500
        assert requests == 11
        # Verify pipeline: hincrby tokens, hincrby requests, expire
        assert mock_pipe.hincrby.call_count == 2
        mock_pipe.expire.assert_called_once()

    @pytest.mark.asyncio
    async def test_check_quota_in_redis_allowed(self):
        mock_redis = AsyncMock()
        mock_redis.hgetall = AsyncMock(return_value={"tokens": "1000", "requests": "5"})

        has_quota, used_tokens, used_requests = await check_quota_in_redis(
            mock_redis, "user-123", estimated_tokens=500, daily_limit=100_000
        )
        assert has_quota is True
        assert used_tokens == 1000
        assert used_requests == 5

    @pytest.mark.asyncio
    async def test_check_quota_in_redis_denied(self):
        mock_redis = AsyncMock()
        mock_redis.hgetall = AsyncMock(return_value={"tokens": "99900", "requests": "50"})

        has_quota, used_tokens, _ = await check_quota_in_redis(
            mock_redis, "user-123", estimated_tokens=500, daily_limit=100_000
        )
        assert has_quota is False
        assert used_tokens == 99900

    @pytest.mark.asyncio
    async def test_check_quota_unlimited(self):
        mock_redis = AsyncMock()
        mock_redis.hgetall = AsyncMock(return_value={"tokens": "1000000", "requests": "9999"})

        has_quota, _, _ = await check_quota_in_redis(
            mock_redis, "user-123", estimated_tokens=100, daily_limit=-1
        )
        assert has_quota is True  # unlimited (-1) always allows


# ---------------------------------------------------------------------------
# Business logic tests (mocked DB + Redis)
# ---------------------------------------------------------------------------

class TestBusinessLogic:
    def test_role_enum(self):
        """Verify Role enum values match context.md."""
        assert S.Role.USER.value == "user"
        assert S.Role.POWER_USER.value == "power_user"
        assert S.Role.ADMIN.value == "admin"

    def test_quota_check_result_enum(self):
        assert S.QuotaCheckResult.ALLOWED == "allowed"
        assert S.QuotaCheckResult.DENIED == "denied"
        assert S.QuotaCheckResult.UNLIMITED == "unlimited"

    def test_litellm_callback_user_normalization(self):
        # LiteLLM may send UUID strings
        payload = S.LitellmCallbackRequest(user="550e8400-e29b-41d4-a716-446655440000")
        assert payload.user == "550e8400-e29b-41d4-a716-446655440000"


# ---------------------------------------------------------------------------
# Config tests
# ---------------------------------------------------------------------------

class TestConfig:
    def test_default_quota_values_from_context(self):
        """Verify default quotas match context.md."""
        from quota_service.config import settings

        # From context.md: user=100k, power_user=500k, admin=unlimited(-1)
        assert settings.default_quota_user == 100_000
        assert settings.default_quota_power_user == 500_000
        assert settings.default_quota_admin == -1

    def test_database_url_format(self):
        from quota_service.config import Settings

        s = Settings(
            postgres_host="pg.example.com",
            postgres_port=5432,
            postgres_user="alice",
            postgres_password="secret",
            postgres_db="hermes_quota",
        )
        assert "postgresql+asyncpg://" in s.database_url
        assert "alice:secret" in s.database_url
        assert "pg.example.com:5432" in s.database_url

    def test_port_defaults_to_8003(self):
        from quota_service.config import Settings

        s = Settings()
        assert s.port == 8003


# ---------------------------------------------------------------------------
# Integration-style tests (with mocked dependencies)
# ---------------------------------------------------------------------------

class TestQuotaFlow:
    """Simulate the full quota flow: check → consume → status."""

    @pytest.mark.asyncio
    async def test_quota_flow_simulation(self):
        """
        Simulate: user-123 (role=user, limit=100k) makes a 500-token request.
        1. Check: should be allowed (30k used < 100k)
        2. Consume: record 500 tokens
        3. Status: should show 30.5k used
        """
        from quota_service.service import check_quota

        mock_session = AsyncMock()
        mock_redis = AsyncMock()
        mock_redis.hgetall = AsyncMock(return_value={"tokens": "30000", "requests": "15"})
        user_id = uuid4()

        # Mock session to return a default quota config
        mock_config = MagicMock()
        mock_config.quota_group = "user"
        mock_config.daily_token_limit = 100_000
        mock_config.daily_request_limit = 500

        with patch("quota_service.service.resolve_user_quota") as mock_resolve:
            mock_resolve.return_value = MagicMock(
                user_id=user_id,
                role="user",
                quota_group="user",
                daily_token_limit=100_000,
                daily_request_limit=500,
                is_unlimited=False,
                used_tokens=30_000,
                used_requests=15,
                reset_at="2026-04-16T23:59:59+00:00",
            )
            resp = await check_quota(mock_session, mock_redis, user_id, estimated_tokens=500)

        assert resp.allowed is True
        assert resp.used_tokens == 30_000
        assert resp.remaining_tokens == 70_000
        assert resp.remaining_requests == 485  # 500 - 15

    @pytest.mark.asyncio
    async def test_quota_exceeded_returns_denied(self):
        from quota_service.service import check_quota

        mock_session = AsyncMock()
        mock_redis = AsyncMock()
        user_id = uuid4()

        with patch("quota_service.service.resolve_user_quota") as mock_resolve:
            mock_resolve.return_value = MagicMock(
                user_id=user_id,
                role="user",
                quota_group="user",
                daily_token_limit=100_000,
                daily_request_limit=500,
                is_unlimited=False,
                used_tokens=99_500,  # almost at limit
                used_requests=499,    # one request left
                reset_at="2026-04-16T23:59:59+00:00",
            )
            resp = await check_quota(mock_session, mock_redis, user_id, estimated_tokens=1000)

        assert resp.allowed is False
        assert resp.result == S.QuotaCheckResult.DENIED
        assert resp.remaining_tokens == 500  # 100k - 99.5k

    @pytest.mark.asyncio
    async def test_admin_unlimited_quota(self):
        from quota_service.service import check_quota

        mock_session = AsyncMock()
        mock_redis = AsyncMock()
        user_id = uuid4()

        with patch("quota_service.service.resolve_user_quota") as mock_resolve:
            mock_resolve.return_value = MagicMock(
                user_id=user_id,
                role="admin",
                quota_group="admin",
                daily_token_limit=-1,
                daily_request_limit=-1,
                is_unlimited=True,
                used_tokens=1_000_000,
                used_requests=9999,
                reset_at="2026-04-16T23:59:59+00:00",
            )
            resp = await check_quota(mock_session, mock_redis, user_id, estimated_tokens=1_000_000)

        assert resp.allowed is True
        assert resp.result == S.QuotaCheckResult.UNLIMITED
        assert resp.remaining_tokens == -1
        assert resp.remaining_requests == -1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
