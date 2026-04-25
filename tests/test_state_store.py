from agent.state_store import RuntimeContext
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
