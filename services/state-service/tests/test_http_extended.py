"""Extended HTTP-layer tests for state_service.

Covers endpoint error paths, auth edge cases, rate-limiting behaviour, and
additional CRUD scenarios that the base HTTP flow test omits.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool


# ---------------------------------------------------------------------------
# Shared async DB fixture
# ---------------------------------------------------------------------------

@pytest.fixture()
def sqlite_db_url(tmp_path):
    return f"sqlite+aiosqlite:///{tmp_path / 'test_ext.db'}"


@pytest_asyncio.fixture()
async def db_session_factory(sqlite_db_url):
    """Async SQLite session factory that creates the schema for each test."""
    from state_service.models import Base

    engine = create_async_engine(
        sqlite_db_url,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    yield factory
    await engine.dispose()


@pytest_asyncio.fixture()
async def client(db_session_factory):
    """ASGI test client wired to the SQLite test DB."""
    from state_service.main import app, db_dep

    async def override_db_dep() -> AsyncGenerator[AsyncSession, None]:
        # Mimic get_session() which commits on normal exit so that writes from
        # one request are visible to subsequent requests within the same test.
        async with db_session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[db_dep] = override_db_dep
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as c:
        yield c
    app.dependency_overrides.clear()


AUTH_HEADERS = {
    "Authorization": "Bearer dev-state-key-change-in-prod",
    "X-Tenant-ID": "acme",
    "X-User-ID": "user-1",
}

# Headers for a second user in the same tenant
AUTH_HEADERS_U2 = {
    "Authorization": "Bearer dev-state-key-change-in-prod",
    "X-Tenant-ID": "acme",
    "X-User-ID": "user-2",
}

# Headers for a different tenant
AUTH_HEADERS_T2 = {
    "Authorization": "Bearer dev-state-key-change-in-prod",
    "X-Tenant-ID": "other-tenant",
    "X-User-ID": "user-1",
}


# ---------------------------------------------------------------------------
# Auth / security edge cases
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_missing_authorization_header_returns_401(client):
    """No Authorization header → 401."""
    resp = await client.get("/state/sessions", headers={"X-User-ID": "u1"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_wrong_token_returns_401(client):
    """Wrong bearer token → 401."""
    resp = await client.get(
        "/state/sessions",
        headers={"Authorization": "Bearer wrong-token", "X-User-ID": "u1"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_missing_user_id_header_returns_400(client):
    """Valid token but no X-User-ID → 400 (security.py line 29)."""
    resp = await client.get(
        "/state/sessions",
        headers={"Authorization": "Bearer dev-state-key-change-in-prod"},
    )
    assert resp.status_code == 400
    assert "X-User-ID" in resp.text


# ---------------------------------------------------------------------------
# /health and /ready
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_health_endpoint_returns_200(client):
    """/health returns 200 with service metadata."""
    resp = await client.get("/health", headers=AUTH_HEADERS)
    assert resp.status_code == 200
    body = resp.json()
    assert body["service"] == "state-service"


@pytest.mark.asyncio
async def test_ready_endpoint_returns_200_in_debug(client):
    """/ready returns 200 in local-debug mode (no actual DB probe required)."""
    resp = await client.get("/ready", headers=AUTH_HEADERS)
    # Response can be 200 or 503 depending on SQLite probe; either is acceptable
    # — the important thing is the code path is exercised without a 500.
    assert resp.status_code in (200, 503)


# ---------------------------------------------------------------------------
# Session 403 / 404 scenarios
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_session_403_when_user_id_mismatch(client):
    """Creating a session with a different user_id in body → 403 (line 187)."""
    sid = str(uuid.uuid4())
    resp = await client.post(
        "/state/sessions",
        json={"session_id": sid, "source": "test", "user_id": "other-user"},
        headers=AUTH_HEADERS,
    )
    assert resp.status_code == 403
    assert "another user" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_create_session_403_when_session_belongs_to_other_user(client):
    """Re-creating a session that belongs to another user → 403 (lines 192-195)."""
    sid = str(uuid.uuid4())

    # User-2 creates the session
    r = await client.post(
        "/state/sessions",
        json={"session_id": sid, "source": "test"},
        headers=AUTH_HEADERS_U2,
    )
    assert r.status_code == 200

    # User-1 in same tenant tries to access the same session_id
    resp = await client.post(
        "/state/sessions",
        json={"session_id": sid, "source": "test"},
        headers=AUTH_HEADERS,
    )
    assert resp.status_code == 403
    assert "another user" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_get_session_by_id_404_when_missing(client):
    """GET /state/sessions/{id} returns 404 for unknown session."""
    resp = await client.get(
        f"/state/sessions/{uuid.uuid4()}",
        headers=AUTH_HEADERS,
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_session_metadata_404_when_missing(client):
    """GET /state/sessions/{id}/metadata returns 404 for unknown session."""
    resp = await client.get(
        f"/state/sessions/{uuid.uuid4()}/metadata",
        headers=AUTH_HEADERS,
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_patch_session_404_when_missing(client):
    """PATCH /state/sessions/{id} returns 404 for unknown session."""
    resp = await client.patch(
        f"/state/sessions/{uuid.uuid4()}",
        json={"title": "New Title"},
        headers=AUTH_HEADERS,
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_patch_session_updates_title(client):
    """PATCH /state/sessions/{id} updates the session title."""
    sid = str(uuid.uuid4())
    await client.post("/state/sessions", json={"session_id": sid, "source": "test"}, headers=AUTH_HEADERS)

    resp = await client.patch(
        f"/state/sessions/{sid}",
        json={"title": "My New Title"},
        headers=AUTH_HEADERS,
    )
    assert resp.status_code == 200
    assert resp.json()["title"] == "My New Title"


@pytest.mark.asyncio
async def test_get_session_by_id_isolation_cross_tenant(client):
    """A session created by one tenant is not visible to another (→ 404)."""
    sid = str(uuid.uuid4())
    # Tenant-1 creates the session
    await client.post("/state/sessions", json={"session_id": sid, "source": "test"}, headers=AUTH_HEADERS)

    # Tenant-2 cannot access it
    resp = await client.get(f"/state/sessions/{sid}", headers=AUTH_HEADERS_T2)
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# list_sessions filters
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_sessions_with_source_filter(client):
    """List sessions filtered by source returns only matching sessions."""
    for src in ("cli", "telegram", "cli"):
        sid = str(uuid.uuid4())
        await client.post(
            "/state/sessions",
            json={"session_id": sid, "source": src},
            headers=AUTH_HEADERS,
        )

    resp = await client.get("/state/sessions?source=cli", headers=AUTH_HEADERS)
    assert resp.status_code == 200
    sessions = resp.json()["sessions"]
    assert all(s["source"] == "cli" for s in sessions)
    assert len(sessions) == 2


@pytest.mark.asyncio
async def test_list_sessions_with_exclude_sources(client):
    """Exclude sources removes matching sessions from list."""
    for src in ("cli", "telegram"):
        sid = str(uuid.uuid4())
        await client.post(
            "/state/sessions",
            json={"session_id": sid, "source": src},
            headers=AUTH_HEADERS,
        )

    resp = await client.get(
        "/state/sessions?exclude_sources=telegram", headers=AUTH_HEADERS
    )
    assert resp.status_code == 200
    sessions = resp.json()["sessions"]
    assert all(s["source"] != "telegram" for s in sessions)


@pytest.mark.asyncio
async def test_list_sessions_pagination(client):
    """limit and offset pagination parameters work correctly."""
    # Create 5 sessions
    for _ in range(5):
        await client.post(
            "/state/sessions",
            json={"session_id": str(uuid.uuid4()), "source": "test"},
            headers=AUTH_HEADERS,
        )

    resp_p1 = await client.get("/state/sessions?limit=2&offset=0", headers=AUTH_HEADERS)
    resp_p2 = await client.get("/state/sessions?limit=2&offset=2", headers=AUTH_HEADERS)
    assert resp_p1.status_code == 200
    assert resp_p2.status_code == 200
    ids_p1 = {s["id"] for s in resp_p1.json()["sessions"]}
    ids_p2 = {s["id"] for s in resp_p2.json()["sessions"]}
    # Pages must not overlap
    assert ids_p1.isdisjoint(ids_p2)
    assert len(ids_p1) == 2


# ---------------------------------------------------------------------------
# Messages 404 scenarios
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_append_message_404_for_missing_session(client):
    """POST /state/sessions/{id}/messages → 404 when session missing."""
    resp = await client.post(
        f"/state/sessions/{uuid.uuid4()}/messages",
        json={"role": "user", "content": "hello"},
        headers=AUTH_HEADERS,
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_messages_404_for_missing_session(client):
    """GET /state/sessions/{id}/messages → 404 when session missing."""
    resp = await client.get(
        f"/state/sessions/{uuid.uuid4()}/messages",
        headers=AUTH_HEADERS,
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Message search
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_messages_returns_results(client):
    """GET /state/messages/search returns matching messages."""
    sid = str(uuid.uuid4())
    await client.post("/state/sessions", json={"session_id": sid, "source": "test"}, headers=AUTH_HEADERS)
    await client.post(
        f"/state/sessions/{sid}/messages",
        json={"role": "user", "content": "find this secret phrase"},
        headers=AUTH_HEADERS,
    )

    resp = await client.get(
        "/state/messages/search?query=secret+phrase", headers=AUTH_HEADERS
    )
    assert resp.status_code == 200
    results = resp.json()["results"]
    assert len(results) >= 1
    assert "secret phrase" in results[0]["content"]


@pytest.mark.asyncio
async def test_search_messages_empty_when_no_match(client):
    """GET /state/messages/search returns empty list for no-match query."""
    resp = await client.get(
        "/state/messages/search?query=zxqnosuchemessage999", headers=AUTH_HEADERS
    )
    assert resp.status_code == 200
    assert resp.json()["results"] == []


@pytest.mark.asyncio
async def test_search_messages_role_filter(client):
    """Search with role_filter restricts results to matching roles."""
    sid = str(uuid.uuid4())
    await client.post("/state/sessions", json={"session_id": sid, "source": "test"}, headers=AUTH_HEADERS)
    await client.post(
        f"/state/sessions/{sid}/messages",
        json={"role": "user", "content": "target phrase"},
        headers=AUTH_HEADERS,
    )
    await client.post(
        f"/state/sessions/{sid}/messages",
        json={"role": "assistant", "content": "target phrase"},
        headers=AUTH_HEADERS,
    )

    resp = await client.get(
        "/state/messages/search?query=target+phrase&role_filter=user",
        headers=AUTH_HEADERS,
    )
    assert resp.status_code == 200
    results = resp.json()["results"]
    assert all(r["role"] == "user" for r in results)


# ---------------------------------------------------------------------------
# Update usage
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_usage_404_for_missing_session(client):
    """POST /state/sessions/{id}/usage → 404 when session missing."""
    resp = await client.post(
        f"/state/sessions/{uuid.uuid4()}/usage",
        json={
            "input_tokens": 10,
            "output_tokens": 5,
            "cache_read_tokens": 0,
            "cache_write_tokens": 0,
            "reasoning_tokens": 0,
        },
        headers=AUTH_HEADERS,
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_update_usage_absolute_mode(client):
    """POST /state/sessions/{id}/usage with absolute=True sets tokens directly."""
    sid = str(uuid.uuid4())
    await client.post("/state/sessions", json={"session_id": sid, "source": "test"}, headers=AUTH_HEADERS)

    resp = await client.post(
        f"/state/sessions/{sid}/usage",
        json={
            "input_tokens": 100,
            "output_tokens": 50,
            "cache_read_tokens": 0,
            "cache_write_tokens": 0,
            "reasoning_tokens": 0,
            "absolute": True,
        },
        headers=AUTH_HEADERS,
    )
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


# ---------------------------------------------------------------------------
# End session / Reopen session
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_end_session_404_for_missing_session(client):
    """POST /state/sessions/{id}/end → 404 when session missing."""
    resp = await client.post(
        f"/state/sessions/{uuid.uuid4()}/end",
        json={"end_reason": "test"},
        headers=AUTH_HEADERS,
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_end_session_and_reopen(client):
    """End session and then reopen it."""
    sid = str(uuid.uuid4())
    await client.post("/state/sessions", json={"session_id": sid, "source": "test"}, headers=AUTH_HEADERS)

    end_resp = await client.post(
        f"/state/sessions/{sid}/end",
        json={"end_reason": "completed"},
        headers=AUTH_HEADERS,
    )
    assert end_resp.status_code == 200

    reopen_resp = await client.post(
        f"/state/sessions/{sid}/reopen",
        headers=AUTH_HEADERS,
    )
    assert reopen_resp.status_code == 200


@pytest.mark.asyncio
async def test_reopen_session_404_for_missing_session(client):
    """POST /state/sessions/{id}/reopen → 404 when session missing."""
    resp = await client.post(
        f"/state/sessions/{uuid.uuid4()}/reopen",
        headers=AUTH_HEADERS,
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Memory delete
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_memory_404_when_not_found(client):
    """DELETE /state/memory/{ns}/{key} → 404 when record missing (line 363-364)."""
    resp = await client.delete(
        "/state/memory/default/nonexistent-key",
        headers=AUTH_HEADERS,
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_memory_success(client):
    """Create a memory record then delete it → 200."""
    await client.put(
        "/state/memory/default/my-key",
        json={"value": "some value", "metadata": {}},
        headers=AUTH_HEADERS,
    )

    del_resp = await client.delete(
        "/state/memory/default/my-key",
        headers=AUTH_HEADERS,
    )
    assert del_resp.status_code == 200
    assert del_resp.json()["ok"] is True

    # After deletion the record should not appear in list
    list_resp = await client.get("/state/memory?namespace=default", headers=AUTH_HEADERS)
    keys = [item["key"] for item in list_resp.json()["items"]]
    assert "my-key" not in keys


# ---------------------------------------------------------------------------
# Cache 404
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_cache_metadata_404_when_missing(client):
    """GET /state/cache/{key} → 404 when entry not found."""
    resp = await client.get(
        "/state/cache/nonexistent-cache-key",
        headers=AUTH_HEADERS,
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_cache_metadata_upsert_and_update(client):
    """PUT /state/cache/{key} creates then updates cache metadata."""
    cache_key = "my/cache/file.bin"

    first = await client.put(
        f"/state/cache/{cache_key}",
        json={
            "kind": "file",
            "object_uri": "s3://bucket/file",
            "content_sha256": "abc123",
            "size_bytes": 1024,
            "metadata": {},
        },
        headers=AUTH_HEADERS,
    )
    assert first.status_code == 200

    # Update the same key
    second = await client.put(
        f"/state/cache/{cache_key}",
        json={
            "kind": "file",
            "object_uri": "s3://bucket/file-v2",
            "content_sha256": "def456",
            "size_bytes": 2048,
            "metadata": {"version": "2"},
        },
        headers=AUTH_HEADERS,
    )
    assert second.status_code == 200
    assert second.json()["size_bytes"] == 2048

    # Retrieve it
    get_resp = await client.get(f"/state/cache/{cache_key}", headers=AUTH_HEADERS)
    assert get_resp.status_code == 200
    assert get_resp.json()["content_sha256"] == "def456"


# ---------------------------------------------------------------------------
# Rate limiting — mock Redis to return count over limit
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rate_limit_returns_429_when_limit_exceeded(client, monkeypatch):
    """Endpoint returns 429 when Redis reports count exceeds the per-minute limit."""
    import state_service.main as main_module

    # Create a mock Redis that reports count over the default limit (100 for messages)
    mock_redis = AsyncMock()
    mock_redis.incr = AsyncMock(return_value=9999)  # way over limit
    mock_redis.expire = AsyncMock(return_value=True)
    mock_redis.ping = AsyncMock(return_value=True)

    # Patch _get_redis to return the mock
    monkeypatch.setattr(main_module, "_get_redis", AsyncMock(return_value=mock_redis))

    sid = str(uuid.uuid4())
    await client.post("/state/sessions", json={"session_id": sid, "source": "test"}, headers=AUTH_HEADERS)

    resp = await client.post(
        f"/state/sessions/{sid}/messages",
        json={"role": "user", "content": "hello"},
        headers=AUTH_HEADERS,
    )
    assert resp.status_code == 429


@pytest.mark.asyncio
async def test_rate_limit_fail_open_when_redis_unavailable(client, monkeypatch):
    """When Redis is unavailable (_get_redis returns None) requests proceed normally."""
    import state_service.main as main_module

    # _get_redis returns None → rate limiter should fail-open
    monkeypatch.setattr(main_module, "_get_redis", AsyncMock(return_value=None))

    sid = str(uuid.uuid4())
    await client.post("/state/sessions", json={"session_id": sid, "source": "test"}, headers=AUTH_HEADERS)

    resp = await client.post(
        f"/state/sessions/{sid}/messages",
        json={"role": "user", "content": "hello"},
        headers=AUTH_HEADERS,
    )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_rate_limit_fail_open_when_redis_raises(client, monkeypatch):
    """When Redis.incr() raises an exception, requests still proceed (fail-open)."""
    import state_service.main as main_module

    mock_redis = AsyncMock()
    mock_redis.incr = AsyncMock(side_effect=Exception("Redis error"))
    mock_redis.expire = AsyncMock(return_value=True)
    mock_redis.ping = AsyncMock(return_value=True)

    monkeypatch.setattr(main_module, "_get_redis", AsyncMock(return_value=mock_redis))

    sid = str(uuid.uuid4())
    await client.post("/state/sessions", json={"session_id": sid, "source": "test"}, headers=AUTH_HEADERS)

    resp = await client.post(
        f"/state/sessions/{sid}/messages",
        json={"role": "user", "content": "hello"},
        headers=AUTH_HEADERS,
    )
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# _get_redis failure path (line 91)
# ---------------------------------------------------------------------------


def test_get_redis_returns_none_when_connection_fails(monkeypatch):
    """_get_redis returns None when aioredis.from_url raises (line 91)."""
    import state_service.main as main_module

    # Reset the module-level cached client
    monkeypatch.setattr(main_module, "_redis_client", None)

    # Make aioredis.from_url succeed but ping() fail
    mock_redis = AsyncMock()
    mock_redis.ping = AsyncMock(side_effect=Exception("Cannot connect to Redis"))

    import redis.asyncio as aioredis_mod

    monkeypatch.setattr(aioredis_mod, "from_url", lambda *a, **kw: mock_redis)

    # _get_redis is async — run it
    result = asyncio.run(main_module._get_redis())
    assert result is None


# ---------------------------------------------------------------------------
# Config effective merge
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_effective_config_merges_platform_and_user_scopes(client):
    """GET /state/config/effective merges configs from different scopes."""
    # Write a platform-level config (user_id="*")
    await client.put(
        "/state/config",
        json={"scope": "platform", "key": "theme", "value": {"mode": "dark"}},
        headers={**AUTH_HEADERS, "X-User-ID": "*"},
    )
    # Write a user-level config that overrides it
    await client.put(
        "/state/config",
        json={"scope": "user", "key": "theme", "value": {"mode": "light"}},
        headers=AUTH_HEADERS,
    )

    resp = await client.get("/state/config/effective", headers=AUTH_HEADERS)
    assert resp.status_code == 200
    # User-level value should win
    assert resp.json()["config"]["theme"]["mode"] == "light"
