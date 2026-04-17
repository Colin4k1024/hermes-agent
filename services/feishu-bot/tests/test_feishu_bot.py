"""
Feishu Bot Service — self-test suite.

Tests cover:
1. Signature verification (HMAC-SHA256, timing-safe, timestamp window)
2. Event ID deduplication (Redis SETNX)
3. Message text extraction (text, post, image, etc.)


4. Binding card generation
5. Reply card generation
6. Full webhook flow (mock Feishu Webhook → Redis → response stream)
7. Health endpoints

Run with:
    pytest services/feishu-bot/tests/ -v
    # or with mock Redis (no real Redis needed):
    pytest services/feishu-bot/tests/ -v -k "not redis"
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ── Signature computation helpers ─────────────────────────────────────────────


def _make_signature(timestamp: str, body: str, app_secret: str) -> str:
    """Compute Feishu-compatible HMAC-SHA256 signature."""
    message = f"{timestamp}\n{body}".encode("utf-8")
    return hmac.new(
        app_secret.encode("utf-8"),
        message,
        hashlib.sha256,
    ).hexdigest()


# ── Signature verification tests ──────────────────────────────────────────────


class TestSignatureVerification:
    """ADR-005 Appendix B: HMAC-SHA256 signature verification."""

    APP_SECRET = "test_secret_abc123"
    TIMESTAMP_VALID = str(int(time.time()))
    TIMESTAMP_OLD = str(int(time.time()) - 600)  # 10 min ago — out of window
    BODY = '{"header":{"event_id":"evt_001","event_type":"im.message.receive_v1"}}'
    SIGNATURE_VALID = _make_signature(TIMESTAMP_VALID, BODY, APP_SECRET)
    SIGNATURE_INVALID = "deadbeef" * 8  # wrong signature

    @pytest.fixture
    def mock_request(self):
        """Build a mock FastAPI Request with Feishu headers."""
        def _build(timestamp: str, signature: str, body: bytes) -> MagicMock:
            req = MagicMock()
            req.headers = {
                "X-Lark-Request-Timestamp": timestamp,
                "X-Lark-Signature": signature,
            }
            req.body = AsyncMock(return_value=body)
            return req
        return _build

    @pytest.mark.asyncio
    async def test_valid_signature_passes(self, mock_request):
        from fbot.signature import verify_lark_signature

        with patch("fbot.signature.get_settings") as mock_settings:
            s = MagicMock()
            s.FEISHU_APP_SECRET = self.APP_SECRET
            s.MAX_TIMESTAMP_OFFSET = 300
            mock_settings.return_value = s

            req = mock_request(self.TIMESTAMP_VALID, self.SIGNATURE_VALID, self.BODY.encode())
            result = await verify_lark_signature(req)
            assert result == self.BODY.encode()

    @pytest.mark.asyncio
    async def test_invalid_signature_raises(self, mock_request):
        from fbot.signature import verify_lark_signature

        with patch("fbot.signature.get_settings") as mock_settings:
            s = MagicMock()
            s.FEISHU_APP_SECRET = self.APP_SECRET
            s.MAX_TIMESTAMP_OFFSET = 300
            mock_settings.return_value = s

            req = mock_request(self.TIMESTAMP_VALID, self.SIGNATURE_INVALID, self.BODY.encode())
            with pytest.raises(Exception) as exc_info:
                await verify_lark_signature(req)
            # Must be HTTPException with body-returning status
            assert exc_info.value.status_code == 200

    @pytest.mark.asyncio
    async def test_expired_timestamp_rejected(self, mock_request):
        from fbot.signature import verify_lark_signature

        with patch("fbot.signature.get_settings") as mock_settings:
            s = MagicMock()
            s.FEISHU_APP_SECRET = self.APP_SECRET
            s.MAX_TIMESTAMP_OFFSET = 300
            mock_settings.return_value = s

            sig = _make_signature(self.TIMESTAMP_OLD, self.BODY, self.APP_SECRET)
            req = mock_request(self.TIMESTAMP_OLD, sig, self.BODY.encode())
            with pytest.raises(Exception) as exc_info:
                await verify_lark_signature(req)
            assert exc_info.value.status_code == 200

    @pytest.mark.asyncio
    async def test_missing_headers_returns_200(self):
        from fbot.signature import verify_lark_signature

        req = MagicMock()
        req.headers = {}
        req.body = AsyncMock(return_value=b'{}')

        with pytest.raises(Exception) as exc_info:
            await verify_lark_signature(req)
        assert exc_info.value.status_code == 200


# ── Text extraction tests ──────────────────────────────────────────────────────


class TestTextExtraction:
    """Extract normalized text from various Feishu message types."""

    def test_text_message(self):
        from fbot.main import _extract_text_from_event
        event = {
            "message": {
                "message_type": "text",
                "content": '{"text": "Hello Hermes, how are you?"}',
            }
        }
        assert _extract_text_from_event(event) == "Hello Hermes, how are you?"

    def test_post_message(self):
        from fbot.main import _extract_text_from_event
        event = {
            "message": {
                "message_type": "post",
                "content": json.dumps({
                    "zh_cn": {
                        "title": "Meeting Notes",
                        "content": [
                            [{"tag": "text", "text": "Discussed Q2 roadmap."}],
                        ]
                    }
                })
            }
        }
        text = _extract_text_from_event(event)
        assert "roadmap" in text

    def test_image_message_returns_placeholder(self):
        from fbot.main import _extract_text_from_event
        event = {
            "message": {
                "message_type": "image",
                "content": '{"image_key": "img_xxx"}',
            }
        }
        assert _extract_text_from_event(event) == "[Image attachment]"

    def test_empty_text_returns_empty(self):
        from fbot.main import _extract_text_from_event
        assert _extract_text_from_event({}) == ""
        assert _extract_text_from_event({"message": {}}) == ""


# ── Dedup tests ───────────────────────────────────────────────────────────────


class TestDedup:
    """Event ID deduplication via Redis SETNX."""

    @pytest.mark.asyncio
    async def test_first_request_returns_true(self):
        with patch("fbot.redis_client.get_redis") as mock_redis:
            r = AsyncMock()
            r.set = AsyncMock(return_value=True)  # NX succeeded → first time
            mock_redis.return_value = r

            from fbot.redis_client import check_and_set_dedup
            result = await check_and_set_dedup("evt_001")
            assert result is True
            r.set.assert_called_once()
            call_args = r.set.call_args
            assert "nx" in call_args.kwargs
            assert "ex" in call_args.kwargs

    @pytest.mark.asyncio
    async def test_duplicate_returns_false(self):
        with patch("fbot.redis_client.get_redis") as mock_redis:
            r = AsyncMock()
            r.set = AsyncMock(return_value=None)  # NX failed → already exists
            mock_redis.return_value = r

            from fbot.redis_client import check_and_set_dedup
            result = await check_and_set_dedup("evt_001")
            assert result is False


# ── Auth client tests ──────────────────────────────────────────────────────────


class TestAuthClient:
    """Auth Service integration: union_id → user_id lookup."""

    @pytest.mark.asyncio
    async def test_user_found(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json = MagicMock(return_value={"user_id": "u-12345", "username": "alice"})

        mock_client = MagicMock()
        # async with returns the client itself; client.get returns the mock response (awaited below)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.get = AsyncMock(return_value=mock_resp)

        with patch("fbot.auth_client.httpx.AsyncClient", return_value=mock_client):
            from fbot.auth_client import lookup_user_by_feishu_id
            resp, reason = await lookup_user_by_feishu_id("on_xxx")
            assert resp is not None
            assert resp.user_id == "u-12345"
            assert reason is None

    @pytest.mark.asyncio
    async def test_user_not_bound(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 404

        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.get = AsyncMock(return_value=mock_resp)

        with patch("fbot.auth_client.httpx.AsyncClient", return_value=mock_client):
            from fbot.auth_client import lookup_user_by_feishu_id
            resp, reason = await lookup_user_by_feishu_id("on_xxx")
            assert resp is None
            assert reason == "not_bound"

    @pytest.mark.asyncio
    async def test_auth_service_error(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 500

        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.get = AsyncMock(return_value=mock_resp)

        with patch("fbot.auth_client.httpx.AsyncClient", return_value=mock_client):
            from fbot.auth_client import lookup_user_by_feishu_id
            resp, reason = await lookup_user_by_feishu_id("on_xxx")
            assert resp is None
            assert reason == "error"


# ── Binding card tests ────────────────────────────────────────────────────────


class TestBindingCard:
    """Binding card generation and send logic."""

    @pytest.mark.asyncio
    async def test_binding_card_generated(self):
        from fbot.feishu_client import _build_binding_card

        card = _build_binding_card(
            union_id="on_test123",
            nonce="abc123def456",
            timestamp="1715000000",
            sign="deadbeef",
        )

        assert card["msg_type"] == "interactive"
        assert "Hermes" in card["card"]["header"]["title"]["content"]
        assert "绑定" in card["card"]["elements"][0]["content"]

        # Verify button has a URL — action element is at index 2 (0=markdown, 1=hr, 2=action, 3=note)
        actions = card["card"]["elements"][2]["actions"]
        assert len(actions) == 1
        assert "union_id=on_test123" in actions[0]["url"]

    @pytest.mark.asyncio
    async def test_reply_card_generated(self):
        from fbot.feishu_client import _build_reply_card

        card = _build_reply_card("Hello from Hermes!", msg_id="msg_001")
        assert card["msg_type"] == "interactive"
        assert "Hermes" in card["card"]["header"]["title"]["content"]
        assert "Hello from Hermes" in card["card"]["elements"][0]["content"]

    @pytest.mark.asyncio
    async def test_error_card_generated(self):
        from fbot.feishu_client import _build_error_card

        card = _build_error_card("Something went wrong")
        assert card["msg_type"] == "interactive"
        assert "失败" in card["card"]["header"]["title"]["content"]


# ── Redis Streams tests ───────────────────────────────────────────────────────


class TestRedisStreams:
    """XADD / XREADBLOCK operations for feishu:requests and feishu:responses."""

    @pytest.mark.asyncio
    async def test_add_feishu_request(self):
        with patch("fbot.redis_client.get_redis") as mock_redis:
            r = AsyncMock()
            r.xadd = AsyncMock(return_value="1700000000000-0")
            mock_redis.return_value = r

            from fbot.redis_client import add_feishu_request
            msg_id = await add_feishu_request(
                user_id="u-001",
                union_id="on_xxx",
                feishu_msg_id="msg_001",
                feishu_chat_id="chat_001",
                message="Hello",
                reply_channel="feishu:responses:fbp-001",
                fbot_instance_id="fbp-001",
            )

            assert msg_id == "1700000000000-0"
            r.xadd.assert_called_once()
            # xadd is called as: xadd(stream, fields_dict) — positional
            call_args = r.xadd.call_args
            fields = call_args[0][1]  # positional: (stream, fields_dict)
            assert "user_id" in fields
            assert fields["user_id"] == "u-001"

    @pytest.mark.asyncio
    async def test_add_response_marker(self):
        with patch("fbot.redis_client.get_redis") as mock_redis:
            r = AsyncMock()
            r.xadd = AsyncMock(return_value="1700000000001-0")
            r.expire = AsyncMock()
            mock_redis.return_value = r

            from fbot.redis_client import add_response_marker
            msg_id = await add_response_marker(
                response_stream="feishu:responses:fbp-001",
                request_id="1700000000000-0",
            )

            assert msg_id == "1700000000001-0"
            r.expire.assert_called_once()

    @pytest.mark.asyncio
    async def test_read_response_chunks(self):
        with patch("fbot.redis_client.get_redis") as mock_redis:
            r = AsyncMock()
            r.xread = AsyncMock(return_value=[
                ("feishu:responses:fbp-001", [
                    ("1700000000001-0", {"request_id": "req_001", "chunk": "Hello ", "done": "false"}),
                    ("1700000000002-0", {"request_id": "req_001", "chunk": "Hermes", "done": "true"}),
                ])
            ])
            mock_redis.return_value = r

            from fbot.redis_client import read_response_chunks
            chunks = await read_response_chunks("feishu:responses:fbp-001", last_id="$", timeout_ms=1000)

            assert len(chunks) == 2
            assert chunks[0]["chunk"] == "Hello "
            assert chunks[0]["done"] is False
            assert chunks[1]["chunk"] == "Hermes"
            assert chunks[1]["done"] is True

    @pytest.mark.asyncio
    async def test_read_response_chunks_timeout(self):
        with patch("fbot.redis_client.get_redis") as mock_redis:
            r = AsyncMock()
            r.xread = AsyncMock(return_value=None)  # timeout
            mock_redis.return_value = r

            from fbot.redis_client import read_response_chunks
            chunks = await read_response_chunks("feishu:responses:fbp-001", timeout_ms=100)
            assert chunks == []


# ── Full webhook flow integration test ────────────────────────────────────────


class TestWebhookFlow:
    """End-to-end webhook handler test with mocked dependencies."""

    @pytest.fixture
    def valid_webhook_payload(self) -> Dict[str, Any]:
        return {
            "schema": "2.0",
            "header": {
                "event_id": "evt_test_001",
                "event_type": "im.message.receive_v1",
                "create_time": "1700000000",
            },
            "event": {
                "message": {
                    "message_id": "msg_001",
                    "message_type": "text",
                    "create_time": "1700000000",
                    "chat_id": "chat_test_001",
                    "chat_type": "p2p",
                    "content": '{"text": "Hello Hermes!"}',
                    "sender": {
                        "sender_id": {"union_id": "on_test_union_001", "open_id": "ou_test_001"},
                        "union_id": "on_test_union_001",
                    },
                }
            },
        }

    @pytest.mark.asyncio
    async def test_webhook_unbound_user_gets_binding_card(self, valid_webhook_payload):
        """When Auth returns 404 (not bound), FBot sends binding card."""
        from fbot.main import feishu_webhook
        from unittest.mock import AsyncMock

        body = json.dumps(valid_webhook_payload).encode()
        timestamp = str(int(time.time()))
        sig = _make_signature(timestamp, body.decode(), "test_secret")

        mock_request = MagicMock()
        mock_request.headers = {
            "X-Lark-Request-Timestamp": timestamp,
            "X-Lark-Signature": sig,
        }
        mock_request.body = AsyncMock(return_value=body)

        with patch("fbot.main.verify_lark_signature", AsyncMock(return_value=body)), \
             patch("fbot.main.check_and_set_dedup", AsyncMock(return_value=True)), \
             patch("fbot.main.lookup_user_by_feishu_id", AsyncMock(return_value=(None, "not_bound"))), \
             patch("fbot.main._send_binding_card", AsyncMock()) as mock_bind:

            resp = await feishu_webhook(mock_request)
            assert resp["code"] == 0
            mock_bind.assert_called_once()
            call_args = mock_bind.call_args
            assert call_args[0][0] == "chat_test_001"  # chat_id
            assert call_args[0][1] == "on_test_union_001"  # union_id

    @pytest.mark.asyncio
    async def test_webhook_bound_user_enqueue(self, valid_webhook_payload):
        """When Auth returns user_id, FBot enqueues to Redis Streams."""
        from fbot.main import feishu_webhook
        from unittest.mock import AsyncMock

        body = json.dumps(valid_webhook_payload).encode()
        timestamp = str(int(time.time()))
        sig = _make_signature(timestamp, body.decode(), "test_secret")

        mock_request = MagicMock()
        mock_request.headers = {
            "X-Lark-Request-Timestamp": timestamp,
            "X-Lark-Signature": sig,
        }
        mock_request.body = AsyncMock(return_value=body)

        auth_resp = MagicMock()
        auth_resp.user_id = "u-12345"

        with patch("fbot.main.verify_lark_signature", AsyncMock(return_value=body)), \
             patch("fbot.main.check_and_set_dedup", AsyncMock(return_value=True)), \
             patch("fbot.main.lookup_user_by_feishu_id", AsyncMock(return_value=(auth_resp, None))), \
             patch("fbot.main.add_feishu_request", AsyncMock(return_value="1700000000000-0")), \
             patch("fbot.main.add_response_marker", AsyncMock(return_value="1700000000001-0")) as mock_marker:

            resp = await feishu_webhook(mock_request)
            assert resp["code"] == 0
            mock_marker.assert_called_once()
            # Verify reply_channel contains fbot instance
            call_kwargs = mock_marker.call_args.kwargs
            assert "feishu:responses" in call_kwargs.get("response_stream", "")

    @pytest.mark.asyncio
    async def test_webhook_duplicate_event_skipped(self, valid_webhook_payload):
        """Duplicate event_id (SETNX returned False) → skip processing."""
        from fbot.main import feishu_webhook
        from unittest.mock import AsyncMock

        body = json.dumps(valid_webhook_payload).encode()
        timestamp = str(int(time.time()))
        sig = _make_signature(timestamp, body.decode(), "test_secret")

        mock_request = MagicMock()
        mock_request.headers = {
            "X-Lark-Request-Timestamp": timestamp,
            "X-Lark-Signature": sig,
        }
        mock_request.body = AsyncMock(return_value=body)

        with patch("fbot.main.verify_lark_signature", AsyncMock(return_value=body)), \
             patch("fbot.main.check_and_set_dedup", AsyncMock(return_value=False)):
            # No auth call, no enqueue
            with patch("fbot.main.lookup_user_by_feishu_id") as mock_auth, \
                 patch("fbot.main.add_feishu_request") as mock_add:

                resp = await feishu_webhook(mock_request)
                assert resp["code"] == 0
                mock_auth.assert_not_called()
                mock_add.assert_not_called()


# ── Health endpoints ──────────────────────────────────────────────────────────


class TestHealthEndpoints:
    """GET /health and GET /health/ready."""

    @pytest.mark.asyncio
    async def test_liveness_returns_ok(self):
        from fbot.main import health

        result = await health()
        assert result["status"] == "ok"
        assert result["service"] == "feishu-bot"

    @pytest.mark.asyncio
    async def test_readiness_checks_redis(self):
        from fbot.main import health_ready

        with patch("fbot.main.healthcheck_redis", AsyncMock(return_value=True)):
            result = await health_ready()
            assert result.status == "ok"
            assert result.redis_connected is True


# ── Nonce flow tests ───────────────────────────────────────────────────────────


class TestNonceFlow:
    """Binding nonce: store / retrieve / delete."""

    @pytest.mark.asyncio
    async def test_store_and_retrieve_nonce(self):
        with patch("fbot.redis_client.get_redis") as mock_redis:
            r = AsyncMock()
            r.set = AsyncMock()
            r.get = AsyncMock(return_value="on_test_union")
            r.delete = AsyncMock()
            mock_redis.return_value = r

            from fbot.redis_client import store_bind_nonce, get_bind_nonce, delete_bind_nonce

            await store_bind_nonce("nonce_abc123", "on_test_union")
            r.set.assert_called_once()

            val = await get_bind_nonce("nonce_abc123")
            assert val == "on_test_union"

            await delete_bind_nonce("nonce_abc123")
            r.delete.assert_called_once()


# ── Config tests ───────────────────────────────────────────────────────────────


class TestConfig:
    """Configuration property derivations."""

    def test_redis_url_without_password(self):
        from fbot.config import Settings
        s = Settings(REDIS_HOST="localhost", REDIS_PORT=6379, REDIS_PASSWORD="")
        assert s.redis_url == "redis://localhost:6379/0"

    def test_redis_url_with_password(self):
        from fbot.config import Settings
        s = Settings(REDIS_HOST="redis.internal", REDIS_PORT=6380, REDIS_PASSWORD="secret")
        assert s.redis_url == "redis://:secret@redis.internal:6380/0"

    def test_feishu_responses_stream(self):
        from fbot.config import Settings
        s = Settings(FBOT_INSTANCE_ID="fbp-pod-xyz", FEISHU_RESPONSES_PREFIX="feishu:responses")
        assert s.feishu_responses_stream == "feishu:responses:fbp-pod-xyz"


# ── Run all ───────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
