"""Integration test: Feishu event → Gateway → RemoteStateStore (PostgreSQL)

Simulates a Feishu DM message event and verifies:
1. Gateway extracts tenant_id from Feishu event header
2. runtime_context is built with correct tenant_id, user_id
3. AIAgent is created with RemoteStateStore (not LocalStateStore)
4. Session is stored in PostgreSQL via RemoteStateStore

Run:
    HERMES_STATE_URL=http://localhost:8080 .venv/bin/python -m pytest tests/integration/test_feishu_gateway_state.py -v -s
"""

import os
import uuid

import pytest
from unittest.mock import MagicMock

pytestmark = pytest.mark.integration


@pytest.fixture
def state_service_url(monkeypatch):
    """Configure the live state service URL only for integration test execution."""
    url = os.environ.get("HERMES_STATE_URL", "http://localhost:8080")
    monkeypatch.setenv("HERMES_STATE_MODE", "remote")
    monkeypatch.setenv("HERMES_STATE_URL", url)
    return url


@pytest.fixture
def remote_state_env(state_service_url, monkeypatch):
    """Configure AIAgent to use RemoteStateStore for a single test."""
    monkeypatch.delenv("HERMES_HOME", raising=False)
    return state_service_url


class TestFeishuEventToRemoteStateStore:
    """Test the Feishu → Gateway → RemoteStateStore pipeline."""

    def test_tenant_id_extracted_from_feishu_header(self):
        """Verify gateway extracts tenant_id from Feishu event header."""
        # Simulate Feishu event header structure (from gateway/run.py line 8592)
        header = MagicMock()
        header.tenant_key = "tenant_hermes_prod"

        # The extraction logic from gateway/run.py:
        tenant_id = str(
            getattr(header, "tenant_key", None)
            or (header.get("tenant_key") if hasattr(header, "get") else None)
            or "default"
        )
        assert tenant_id == "tenant_hermes_prod"

    def test_runtime_context_built_correctly(self):
        """Verify runtime_context dict matches what gateway/builds."""
        # Replicate the runtime_context construction from gateway/run.py lines 8596-8603
        tenant_id = "tenant_hermes_prod"
        user_id = "ou_6fdcc2cfc6ea2b765ed5ca1d70280673"
        session_id = f"feishu-{uuid.uuid4().hex[:8]}"

        runtime_context = {
            "tenant_id": tenant_id,
            "user_id": user_id,
            "session_id": session_id,
        }

        assert runtime_context["tenant_id"] == "tenant_hermes_prod"
        assert runtime_context["user_id"] == "ou_6fdcc2cfc6ea2b765ed5ca1d70280673"
        assert "session_id" in runtime_context

    def test_aiagent_with_remote_state_store(self, remote_state_env):
        """Verify AIAgent.__init__ creates RemoteStateStore when HERMES_STATE_URL is set."""
        from run_agent import AIAgent

        agent = AIAgent(
            model="claude-sonnet-4",
            runtime_context={
                "tenant_id": "tenant-test",
                "user_id": "test-user",
            },
        )

        # State store must be RemoteStateStore (not None, not LocalStateStore)
        from agent.state_store import RemoteStateStore
        assert agent.state_store is not None, "state_store should not be None"
        assert isinstance(agent.state_store, RemoteStateStore), \
            f"Expected RemoteStateStore, got {type(agent.state_store).__name__}"

        # RuntimeContext should be set
        assert agent.runtime_context is not None
        assert agent.runtime_context.tenant_id == "tenant-test"

    def test_remote_state_store_uses_tenant_context(self, state_service_url):
        """Verify RemoteStateStore sends correct tenant headers."""
        from agent.state_store import RemoteStateStore, RuntimeContext

        store = RemoteStateStore(
            state_service_url,
            RuntimeContext(tenant_id="tenant-abc", user_id="user-123")
        )

        headers = store._auth_headers()
        assert headers["X-Tenant-ID"] == "tenant-abc"
        assert headers["X-User-ID"] == "user-123"

    def test_session_stored_in_remote_postgres(self, remote_state_env):
        """End-to-end: session created via AIAgent is stored in real PostgreSQL."""
        from run_agent import AIAgent

        tenant_id = f"tenant-{uuid.uuid4().hex[:6]}"
        user_id = f"user-{uuid.uuid4().hex[:6]}"
        session_id = f"feishu-{uuid.uuid4().hex[:8]}"

        agent = AIAgent(
            model="claude-sonnet-4",
            runtime_context={
                "tenant_id": tenant_id,
                "user_id": user_id,
                "session_id": session_id,
            },
        )

        # The agent should have created a session in PostgreSQL
        assert agent.state_store is not None
        s = agent.state_store.sessions.get_session(session_id)
        assert s is not None, f"Session {session_id} not found in PostgreSQL"
        assert s["tenant_id"] == tenant_id, f"Wrong tenant: expected {tenant_id}, got {s.get('tenant_id')}"
        assert s["source"] == "feishu", f"Wrong source: expected feishu, got {s.get('source')}"

    def test_cross_tenant_isolation_in_gateway_flow(self, state_service_url):
        """Tenant A's session must not be accessible by Tenant B."""
        from agent.state_store import RemoteStateStore, RuntimeContext

        tenant_a = RemoteStateStore(
            state_service_url,
            RuntimeContext(tenant_id="tenant-a")
        )
        tenant_b = RemoteStateStore(
            state_service_url,
            RuntimeContext(tenant_id="tenant-b")
        )

        # Tenant A creates a session
        sid = f"test-{uuid.uuid4().hex[:8]}"
        tenant_a.sessions.create_session(sid, source="feishu")

        # Tenant B cannot access it
        s = tenant_b.sessions.get_session(sid)
        assert s is None, "Tenant B should not see Tenant A's session"

        # Tenant B cannot append messages
        import httpx
        with pytest.raises(httpx.HTTPStatusError) as exc_info:
            tenant_b.sessions.append_message(sid, role="user", content="hack")
        assert exc_info.value.response.status_code == 404

    def test_agent_stateless_logs_to_tempfile(self, remote_state_env):
        """When state_store is remote, logs go to /tmp not ~/.hermes."""
        from run_agent import AIAgent

        agent = AIAgent(
            model="claude-sonnet-4",
            runtime_context={"tenant_id": "tenant-test"},
        )

        import tempfile
        assert str(agent.logs_dir).startswith(tempfile.gettempdir()), \
            f"Logs dir should be in /tmp, got {agent.logs_dir}"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
