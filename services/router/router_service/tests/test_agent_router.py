"""Unit tests for Agent Router Service.

Tests cover:
- Redis routing table operations (mocked)
- Session lock atomicity (SET NX EX)
- Route hot/cold flow
- Health endpoint
- API endpoints
"""

import asyncio
import hashlib
import importlib
import time
from unittest.mock import patch, MagicMock, AsyncMock

import pytest

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def mock_redis_pool():
    """Mock Redis for all tests."""
    mock = MagicMock()
    importlib.import_module("router_service.redis_client")
    with patch("router_service.redis_client.get_redis_pool", return_value=mock):
        with patch("router_service.redis_client.get_redis", return_value=mock):
            yield mock


@pytest.fixture
def mock_settings():
    """Override settings for testing."""
    from router_service.config import Settings
    s = Settings(
        redis_host="localhost",
        redis_port=6379,
        redis_db=0,
        route_ttl=1800,
        session_lock_ttl=30,
        pod_health_ttl=60,
        internal_api_key="test-key",
    )
    with patch("router_service.config.settings", s):
        with patch("router_service.scheduler.settings", s):
            with patch("router_service.main.settings", s):
                yield s


# ---------------------------------------------------------------------------
# Redis client tests — session lock
# ---------------------------------------------------------------------------

class TestSessionLock:
    """Test Redis Lua-backed atomic session locks."""

    def test_acquire_lock_success(self, mock_redis_pool):
        """Lock is acquired when key does not exist."""
        from router_service.redis_client import acquire_session_lock, session_lock_key

        mock_client = MagicMock()
        script = MagicMock(return_value=None)
        mock_client.register_script.return_value = script
        with (
            patch("router_service.redis_client._acquire_lock_script", None),
            patch("router_service.redis_client.get_redis", return_value=mock_client),
        ):
            ok, holder = acquire_session_lock("user-1", "pod-1")

        assert ok is True
        assert holder == "pod-1"
        script.assert_called_once_with(
            keys=[session_lock_key("user-1")],
            args=["pod-1", 30],
        )

    def test_acquire_lock_already_held(self, mock_redis_pool):
        """Lock denied when another request holds it."""
        from router_service.redis_client import acquire_session_lock

        mock_client = MagicMock()
        mock_client.register_script.return_value = MagicMock(return_value="pod-2")
        with (
            patch("router_service.redis_client._acquire_lock_script", None),
            patch("router_service.redis_client.get_redis", return_value=mock_client),
        ):
            ok, holder = acquire_session_lock("user-1", "pod-1")

        assert ok is False
        assert holder == "pod-2"

    def test_release_lock(self, mock_redis_pool):
        """Lock is deleted on release."""
        from router_service.redis_client import release_session_lock, session_lock_key

        mock_client = MagicMock()
        script = MagicMock(return_value=1)
        mock_client.register_script.return_value = script
        with (
            patch("router_service.redis_client._release_lock_script", None),
            patch("router_service.redis_client.get_redis", return_value=mock_client),
        ):
            assert release_session_lock("user-1") is True

        script.assert_called_once_with(
            keys=[session_lock_key("user-1")],
            args=["pending"],
        )


# ---------------------------------------------------------------------------
# Redis client tests — route management
# ---------------------------------------------------------------------------

class TestRouteManagement:
    """Test hot route GET/SET/DELETE."""

    def test_get_route_exists(self, mock_redis_pool):
        """Returns pod_id when hot route exists."""
        from router_service.redis_client import get_route

        mock_client = MagicMock()
        mock_client.get.return_value = "pod-42"
        with patch("router_service.redis_client.get_redis", return_value=mock_client):
            result = get_route("user-1")
        assert result == "pod-42"

    def test_get_route_not_found(self, mock_redis_pool):
        """Returns None when no hot route."""
        from router_service.redis_client import get_route

        mock_client = MagicMock()
        mock_client.get.return_value = None
        with patch("router_service.redis_client.get_redis", return_value=mock_client):
            result = get_route("user-1")
        assert result is None

    def test_set_route_pipeline(self, mock_redis_pool):
        """set_route uses pipeline for atomic multi-key write."""
        from router_service.redis_client import set_route

        mock_client = MagicMock()
        mock_pipe = MagicMock()
        mock_client.pipeline.return_value = mock_pipe
        with patch("router_service.redis_client.get_redis", return_value=mock_client):
            set_route("user-1", "pod-42")
        mock_pipe.set.assert_called()
        mock_pipe.sadd.assert_called()
        mock_pipe.execute.assert_called()

    def test_delete_route_returns_pod(self, mock_redis_pool):
        """delete_route returns the pod_id that was serving the user."""
        from router_service.redis_client import delete_route

        mock_client = MagicMock()
        mock_client.get.return_value = "pod-42"
        with patch("router_service.redis_client.get_redis", return_value=mock_client):
            pod_id = delete_route("user-1")
        assert pod_id == "pod-42"


# ---------------------------------------------------------------------------
# Redis client tests — idle pool
# ---------------------------------------------------------------------------

class TestIdlePool:
    """Test ZSET idle pool operations."""

    def test_add_pod_to_idle(self, mock_redis_pool):
        """Pod added to ZSET with current timestamp as score."""
        from router_service.redis_client import add_pod_to_idle

        mock_client = MagicMock()
        mock_pipe = MagicMock()
        mock_client.pipeline.return_value = mock_pipe
        with patch("router_service.redis_client.get_redis", return_value=mock_client):
            add_pod_to_idle("pod-1")
        mock_pipe.zadd.assert_called()
        mock_pipe.execute.assert_called()

    def test_get_idle_pod_pops_oldest(self, mock_redis_pool):
        """get_idle_pod uses ZPOPMIN to atomically pop oldest."""
        from router_service.redis_client import get_idle_pod

        mock_client = MagicMock()
        mock_client.zpopmin.return_value = [("pod-1", 1700000000.0)]
        with patch("router_service.redis_client.get_redis", return_value=mock_client):
            pod_id = get_idle_pod()
        assert pod_id == "pod-1"
        mock_client.sadd.assert_called()  # re-add to active set

    def test_get_idle_pod_empty(self, mock_redis_pool):
        """Returns None when no idle pods."""
        from router_service.redis_client import get_idle_pod

        mock_client = MagicMock()
        mock_client.zpopmin.return_value = []
        with patch("router_service.redis_client.get_redis", return_value=mock_client):
            pod_id = get_idle_pod()
        assert pod_id is None


# ---------------------------------------------------------------------------
# Redis client tests — health
# ---------------------------------------------------------------------------

class TestPodHealth:
    """Test pod health heartbeat management."""

    def test_set_health_with_ttl(self, mock_redis_pool):
        """Health record set with TTL."""
        from router_service.redis_client import set_pod_health

        mock_client = MagicMock()
        with patch("router_service.redis_client.get_redis", return_value=mock_client):
            set_pod_health("pod-1")
        mock_client.set.assert_called()
        # Verify TTL is passed
        call_args = mock_client.set.call_args
        assert call_args[1]["ex"] > 0

    def test_is_pod_healthy_true(self, mock_redis_pool):
        """Pod is healthy when health key exists."""
        from router_service.redis_client import is_pod_healthy

        mock_client = MagicMock()
        mock_client.exists.return_value = 1
        with patch("router_service.redis_client.get_redis", return_value=mock_client):
            result = is_pod_healthy("pod-1")
        assert result is True

    def test_is_pod_healthy_false(self, mock_redis_pool):
        """Pod is unhealthy when health key expired."""
        from router_service.redis_client import is_pod_healthy

        mock_client = MagicMock()
        mock_client.exists.return_value = 0
        with patch("router_service.redis_client.get_redis", return_value=mock_client):
            result = is_pod_healthy("pod-1")
        assert result is False


# ---------------------------------------------------------------------------
# Health endpoint tests
# ---------------------------------------------------------------------------

class TestHealthEndpoint:
    """Test /internal/health endpoint response shape."""

    def test_health_response_model(self):
        """InternalHealthResponse validates correctly."""
        from router_service.schemas import InternalHealthResponse

        resp = InternalHealthResponse(
            ok=True,
            pool_size=100,
            idle_pods=80,
            active_pods=20,
            preparing_pods=0,
            unhealthy_pods=0,
        )
        assert resp.ok is True
        assert resp.pool_size == 100
        assert resp.idle_pods == 80
        assert resp.active_pods == 20

    def test_health_detail_model(self):
        """PodHealthDetail validates correctly."""
        from router_service.schemas import PodHealthDetail, PodStatus

        detail = PodHealthDetail(
            pod_id="pod-1",
            status=PodStatus.IDLE,
            last_heartbeat="2026-04-16T10:00:00Z",
        )
        assert detail.pod_id == "pod-1"
        assert detail.status == PodStatus.IDLE


# ---------------------------------------------------------------------------
# Route request/response schema tests
# ---------------------------------------------------------------------------

class TestSchemas:
    """Test Pydantic schema validation."""

    def test_internal_route_request_all_fields(self):
        """InternalRouteRequest accepts all documented fields."""
        from router_service.schemas import InternalRouteRequest

        req = InternalRouteRequest(
            user_id="user-123",
            message="Hello Hermes",
            feishu_msg_id="msg-abc",
            feishu_chat_id="chat-xyz",
            reply_channel="feishu:responses:fbp-001",
            estimated_tokens=500,
        )
        assert req.user_id == "user-123"
        assert req.reply_channel == "feishu:responses:fbp-001"

    def test_internal_route_request_minimal(self):
        """InternalRouteRequest requires only user_id and message."""
        from router_service.schemas import InternalRouteRequest

        req = InternalRouteRequest(
            user_id="user-123",
            message="Hello",
        )
        assert req.feishu_msg_id is None
        assert req.reply_channel is None

    def test_internal_route_response_hot(self):
        """InternalRouteResponse with hot route."""
        from router_service.schemas import InternalRouteResponse, RouteSource

        resp = InternalRouteResponse(
            success=True,
            pod_id="pod-42",
            pod_url="http://pod-42.hermes-platform.svc.cluster.local:8642",
            source=RouteSource.HOT,
            quota_allowed=True,
        )
        assert resp.source == RouteSource.HOT
        assert resp.cold_start_ms is None

    def test_internal_route_response_cold(self):
        """InternalRouteResponse with cold start metadata."""
        from router_service.schemas import InternalRouteResponse, RouteSource

        resp = InternalRouteResponse(
            success=True,
            pod_id="pod-42",
            source=RouteSource.COLD,
            cold_start_ms=2500,
            prepare_retries=3,
            quota_allowed=True,
        )
        assert resp.source == RouteSource.COLD
        assert resp.cold_start_ms == 2500
        assert resp.prepare_retries == 3

    def test_prepare_request(self):
        """InternalPrepareRequest schema."""
        from router_service.schemas import InternalPrepareRequest

        req = InternalPrepareRequest(
            user_id="user-123",
            hermes_home_path="/nas/hermes-homes/00/user-user-123",
            env_vars={"EXTRA_VAR": "value"},
        )
        assert req.hermes_home_path == "/nas/hermes-homes/00/user-user-123"
        assert req.env_vars["EXTRA_VAR"] == "value"


# ---------------------------------------------------------------------------
# Scheduler tests
# ---------------------------------------------------------------------------

class TestScheduler:
    """Test router scheduling behavior."""

    def test_stateless_runtime_hashes_home_path_subject_without_changing_route_key(
        self, mock_settings
    ):
        """Stateless HERMES_HOME path uses hashed subject while routing stays raw."""
        from router_service.schemas import InternalRouteRequest, QuotaCheckResponse
        from router_service.scheduler import route_request

        route_subject = "tenant-a/../../sessions/chat-123"
        expected_component = hashlib.sha256(route_subject.encode()).hexdigest()
        prepare_mock = AsyncMock(return_value=("pod-42", 12, 1))

        req = InternalRouteRequest(
            user_id="user-123",
            message="Hello",
            session_id=route_subject,
        )

        with (
            patch(
                "router_service.scheduler.check_quota",
                AsyncMock(return_value=QuotaCheckResponse(allowed=True)),
            ),
            patch("router_service.scheduler._cold_start_pod", prepare_mock),
            patch(
                "router_service.scheduler.rc.acquire_session_lock",
                return_value=(True, "pending"),
            ) as lock_mock,
            patch(
                "router_service.scheduler.rc.get_route",
                return_value=None,
            ) as get_route_mock,
            patch("router_service.scheduler.rc.set_route") as set_route_mock,
            patch("router_service.scheduler.rc.set_pod_health"),
            patch("router_service.scheduler.rc.release_session_lock") as release_mock,
        ):
            resp = asyncio.run(route_request(req))

        assert resp.success is True
        lock_mock.assert_called_once_with(route_subject)
        get_route_mock.assert_called_once_with(route_subject)
        set_route_mock.assert_called_once_with(route_subject, "pod-42")
        release_mock.assert_called_once_with(route_subject)

        _, hermes_home_path = prepare_mock.call_args.args[:2]
        assert hermes_home_path == f"/tmp/hermes-runtime/{expected_component}"
        assert route_subject not in hermes_home_path


# ---------------------------------------------------------------------------
# Error response tests
# ---------------------------------------------------------------------------

class TestErrorResponses:
    """Test error response format."""

    def test_error_response_format(self):
        """Error responses use {detail: string} format."""
        from router_service.schemas import ErrorResponse

        err = ErrorResponse(detail="No pods available")
        assert err.model_dump() == {"detail": "No pods available"}


# ---------------------------------------------------------------------------
# Settings tests
# ---------------------------------------------------------------------------

class TestSettings:
    """Test configuration defaults."""

    def test_redis_url_no_password(self):
        """Redis URL built correctly without password."""
        from router_service.config import Settings

        s = Settings(redis_host="redis.local", redis_port=6380, redis_db=1)
        assert s.redis_url == "redis://redis.local:6380/1"

    def test_redis_url_with_password(self):
        """Redis URL built correctly with password."""
        from router_service.config import Settings

        s = Settings(
            redis_host="redis.local",
            redis_port=6379,
            redis_db=0,
            redis_password="secret",
        )
        assert "secret@" in s.redis_url

    def test_default_port(self):
        """Default port is 8002 per spec."""
        from router_service.config import Settings

        s = Settings()
        assert s.port == 8002

    def test_default_route_ttl(self):
        """Default route TTL is 1800s (30 minutes)."""
        from router_service.config import Settings

        s = Settings()
        assert s.route_ttl == 1800

    def test_session_lock_ttl(self):
        """Session lock TTL is 30s per BE-1."""
        from router_service.config import Settings

        s = Settings()
        assert s.session_lock_ttl == 30
