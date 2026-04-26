"""Integration tests: Gateway → RemoteStateStore (PostgreSQL)

Run with:
    cd /path/to/hermes-agent
    HERMES_STATE_URL=http://localhost:8080 .venv/bin/python -m pytest tests/integration/test_state_service_gateway.py -v -s
"""

import asyncio
import os
import uuid

import pytest

pytestmark = pytest.mark.integration

from agent.state_store import RemoteStateStore, RuntimeContext


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def state_service_url(monkeypatch):
    """Configure remote state only while these integration tests are running."""
    url = os.environ.get("HERMES_STATE_URL", "http://localhost:8080")
    token = os.environ.get("HERMES_STATE_SERVICE_TOKEN", "dev-state-key-change-in-prod")
    monkeypatch.setenv("HERMES_STATE_MODE", "remote")
    monkeypatch.setenv("HERMES_STATE_URL", url)
    monkeypatch.setenv("HERMES_STATE_SERVICE_TOKEN", token)
    return url


@pytest.fixture
def state_service_token():
    return os.environ.get("HERMES_STATE_SERVICE_TOKEN", "dev-state-key-change-in-prod")


@pytest.fixture
def store(state_service_url, state_service_token):
    """RemoteStateStore connected to the real State Service."""
    return RemoteStateStore(
        state_service_url,
        RuntimeContext(tenant_id="test-tenant", user_id="test-user", state_token=state_service_token)
    )


@pytest.fixture
def cross_tenant_store(state_service_url, state_service_token):
    """RemoteStateStore with a different tenant to test isolation."""
    return RemoteStateStore(
        state_service_url,
        RuntimeContext(tenant_id="other-tenant", user_id="test-user", state_token=state_service_token)
    )


# ---------------------------------------------------------------------------
# Tests: Session lifecycle
# ---------------------------------------------------------------------------

class TestSessionLifecycle:
    def test_create_and_get_session(self, store):
        sid = f"test-{uuid.uuid4().hex[:8]}"
        store.sessions.create_session(sid, source="feishu", model="claude-sonnet-4")
        s = store.sessions.get_session(sid)
        assert s is not None
        assert s["tenant_id"] == "test-tenant"
        assert s["model"] == "claude-sonnet-4"
        assert s["source"] == "feishu"

    def test_set_title(self, store):
        sid = f"test-{uuid.uuid4().hex[:8]}"
        store.sessions.create_session(sid, source="feishu")
        store.sessions.set_session_title(sid, "My Test Session")
        s = store.sessions.get_session(sid)
        assert s["title"] == "My Test Session"

    def test_end_and_reopen(self, store):
        sid = f"test-{uuid.uuid4().hex[:8]}"
        store.sessions.create_session(sid, source="feishu")
        store.sessions.end_session(sid, "user_disconnect")
        s = store.sessions.get_session(sid)
        assert s["end_reason"] == "user_disconnect"
        assert s["ended_at"] is not None

        store.sessions.reopen_session(sid)
        s = store.sessions.get_session(sid)
        assert s["ended_at"] is None
        assert s["end_reason"] is None

    def test_list_sessions(self, store):
        sid = f"test-{uuid.uuid4().hex[:8]}"
        store.sessions.create_session(sid, source="feishu")
        sessions = store.sessions.list_sessions_rich()
        assert isinstance(sessions, list)
        assert len(sessions) >= 1

    def test_create_duplicate_id_is_idempotent(self, store):
        sid = f"test-{uuid.uuid4().hex[:8]}"
        store.sessions.create_session(sid, source="feishu")
        store.sessions.create_session(sid, source="feishu")  # Should not raise


# ---------------------------------------------------------------------------
# Tests: Message lifecycle
# ---------------------------------------------------------------------------

class TestMessageLifecycle:
    def test_append_and_retrieve_messages(self, store):
        sid = f"test-{uuid.uuid4().hex[:8]}"
        store.sessions.create_session(sid, source="feishu")

        store.sessions.append_message(sid, role="user", content="Hello!")
        store.sessions.append_message(sid, role="assistant", content="Hi there!")

        msgs = store.sessions.get_messages_as_conversation(sid)
        assert len(msgs) == 2
        assert msgs[0]["role"] == "user"
        assert msgs[1]["role"] == "assistant"

    def test_search_messages(self, store):
        sid = f"test-{uuid.uuid4().hex[:8]}"
        store.sessions.create_session(sid, source="feishu")
        store.sessions.append_message(sid, role="user", content="Searchable content XYZ")
        store.sessions.append_message(sid, role="assistant", content="Response about XYZ")

        results = store.sessions.search_messages("Searchable content")
        assert len(results) >= 1


# ---------------------------------------------------------------------------
# Tests: Tenant isolation
# ---------------------------------------------------------------------------

class TestTenantIsolation:
    def test_same_tenant_session_accessible(self, store):
        sid = f"test-{uuid.uuid4().hex[:8]}"
        store.sessions.create_session(sid, source="feishu")
        # Should not raise
        store._validate_tenant(sid)

    def test_cross_tenant_rejected(self, store, cross_tenant_store):
        sid = f"test-{uuid.uuid4().hex[:8]}"
        store.sessions.create_session(sid, source="feishu")

        # Cross-tenant store tries to validate → must fail
        with pytest.raises(PermissionError) as exc_info:
            cross_tenant_store._validate_tenant(sid)
        assert "belongs to a different tenant" in str(exc_info.value) or \
               "Cross-tenant access denied" in str(exc_info.value)

    def test_cross_tenant_cannot_get_session(self, state_service_url, state_service_token, cross_tenant_store):
        sid = f"test-{uuid.uuid4().hex[:8]}"
        store = RemoteStateStore(
            state_service_url,
            RuntimeContext(tenant_id="test-tenant", user_id="test-user", state_token=state_service_token)
        )
        store.sessions.create_session(sid, source="feishu")

        # Other tenant cannot see it
        s = cross_tenant_store.sessions.get_session(sid)
        assert s is None  # 404, not found

    def test_cross_tenant_cannot_append_message(self, state_service_url, state_service_token, cross_tenant_store):
        sid = f"test-{uuid.uuid4().hex[:8]}"
        store = RemoteStateStore(
            state_service_url,
            RuntimeContext(tenant_id="test-tenant", user_id="test-user", state_token=state_service_token)
        )
        store.sessions.create_session(sid, source="feishu")

        # Other tenant cannot append → server returns 404
        with pytest.raises(Exception):  # httpx.HTTPStatusError 404
            cross_tenant_store.sessions.append_message(sid, role="user", content="hack")


# ---------------------------------------------------------------------------
# Tests: Memory
# ---------------------------------------------------------------------------

class TestMemory:
    def test_upsert_and_list(self, store):
        key = f"test-key-{uuid.uuid4().hex[:6]}"
        store.memory.upsert_memory("memory", key, "test value")
        items = store.memory.list_memory("memory")
        keys = [m.get("key") for m in items]
        assert key in keys

    def test_delete(self, store):
        key = f"test-key-{uuid.uuid4().hex[:6]}"
        store.memory.upsert_memory("memory", key, "test value")
        store.memory.delete_memory("memory", key)
        items = store.memory.list_memory("memory")
        keys = [m.get("key") for m in items]
        assert key not in keys

    def test_memory_isolation_between_tenants(self, store, cross_tenant_store):
        key = f"test-key-{uuid.uuid4().hex[:6]}"
        store.memory.upsert_memory("memory", key, "private value")
        items = cross_tenant_store.memory.list_memory("memory")
        # cross_tenant should not see test-tenant's memories
        keys = [m.get("key") for m in items]
        assert key not in keys


# ---------------------------------------------------------------------------
# Tests: Config
# ---------------------------------------------------------------------------

class TestConfig:
    def test_get_effective_config(self, store):
        store._request(
            "PUT",
            "/state/config",
            json={"scope": "user", "key": "model", "value": {"default": "e2e-model"}},
        )
        cfg = store.config.get_effective_config()
        assert "model" in cfg
        assert cfg["model"]["default"] == "e2e-model"


# ---------------------------------------------------------------------------
# Tests: End-to-end conversation simulation
# ---------------------------------------------------------------------------

class TestEndToEndConversation:
    def test_full_conversation_flow(self, state_service_url, state_service_token, store):
        """Simulate a complete user → assistant → user conversation."""
        tenant_id = f"tenant-{uuid.uuid4().hex[:6]}"
        user_id = f"user-{uuid.uuid4().hex[:6]}"
        store = RemoteStateStore(
            state_service_url,
            RuntimeContext(tenant_id=tenant_id, user_id=user_id, state_token=state_service_token)
        )

        sid = f"conv-{uuid.uuid4().hex[:8]}"
        store.sessions.create_session(sid, source="feishu", model="claude-sonnet-4")

        # User message 1
        store.sessions.append_message(sid, role="user",
            content="Hello, what can you do?",
            token_count=8)

        # Assistant response
        store.sessions.append_message(sid, role="assistant",
            content="I can help you with coding, research, and more!",
            token_count=15)

        # User message 2
        store.sessions.append_message(sid, role="user",
            content="Tell me about Python",
            token_count=4)

        # Search the conversation
        results = store.sessions.search_messages("Python")
        assert len(results) >= 1
        assert "Python" in results[0].get("content", "")

        # End session
        store.sessions.end_session(sid, "completed")
        s = store.sessions.get_session(sid)
        assert s["end_reason"] == "completed"

        # Tenant isolation: another tenant cannot see this session
        other = RemoteStateStore(
            state_service_url,
            RuntimeContext(tenant_id="stranger-tenant", user_id=user_id, state_token=state_service_token)
        )
        assert other.sessions.get_session(sid) is None


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
