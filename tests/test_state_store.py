import json

import httpx

from agent.state_store import RemoteStateStore, RuntimeContext
from tools.memory_tool import RemoteMemoryStore


def test_runtime_context_defaults_and_allowed_tools_csv():
    ctx = RuntimeContext.from_mapping({
        "user_id": "u-1",
        "session_id": "s-1",
        "allowed_tools": "read_file, session_search,  ",
    })

    assert ctx.tenant_id == "default"
    assert ctx.user_id == "u-1"
    assert ctx.session_id == "s-1"
    assert ctx.allowed_tools == ("read_file", "session_search")


def test_runtime_context_empty_mapping_is_default_safe():
    ctx = RuntimeContext.from_mapping(None)

    assert ctx.tenant_id == "default"
    assert ctx.user_id is None
    assert ctx.allowed_tools == ()


class FakeMemoryBackend:
    def __init__(self):
        self.items = {}

    def list_memory(self, namespace="memory"):
        return [
            {"key": key, "value": value, "metadata": {}}
            for (ns, key), value in self.items.items()
            if ns == namespace
        ]

    def upsert_memory(self, namespace, key, value, metadata=None):
        self.items[(namespace, key)] = value
        return {"namespace": namespace, "key": key, "value": value, "metadata": metadata or {}}

    def delete_memory(self, namespace, key):
        self.items.pop((namespace, key), None)


def test_remote_memory_store_add_replace_remove():
    backend = FakeMemoryBackend()
    store = RemoteMemoryStore(backend)
    store.load_from_disk()

    added = store.add("memory", "prefers concise answers")
    assert added["success"] is True
    assert added["entries"] == ["prefers concise answers"]

    replaced = store.replace("memory", "concise", "prefers concise engineering answers")
    assert replaced["success"] is True
    assert replaced["entries"] == ["prefers concise engineering answers"]

    removed = store.remove("memory", "engineering")
    assert removed["success"] is True
    assert removed["entries"] == []


def test_remote_state_store_sends_runtime_context_headers(monkeypatch):
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        assert request.headers["x-tenant-id"] == "corp"
        assert request.headers["x-user-id"] == "u-1"
        assert request.headers["x-session-id"] == "s-1"
        assert request.headers["x-request-id"] == "r-1"
        assert request.headers["authorization"] == "Bearer state-token"
        if request.url.path == "/state/config/effective":
            return httpx.Response(200, json={"config": {"model": {"default": "test-model"}}})
        if request.url.path == "/state/sessions":
            body = json.loads(request.content.decode("utf-8"))
            assert body["session_id"] == "s-1"
            return httpx.Response(200, json={"id": "s-1"})
        return httpx.Response(404, json={"detail": "not found"})

    transport = httpx.MockTransport(handler)
    real_client = httpx.Client

    def client_factory(*args, **kwargs):
        return real_client(transport=transport, timeout=kwargs.get("timeout"))

    monkeypatch.setattr(httpx, "Client", client_factory)
    store = RemoteStateStore(
        "http://state-service",
        RuntimeContext(
            tenant_id="corp",
            user_id="u-1",
            session_id="s-1",
            request_id="r-1",
            state_token="state-token",
        ),
    )
    try:
        assert store.config.get_effective_config()["model"]["default"] == "test-model"
        assert store.sessions.create_session("s-1", "api") == "s-1"
        assert [req.url.path for req in seen] == ["/state/config/effective", "/state/sessions"]
    finally:
        store.close()
