"""Concurrency tests for multi-user session isolation.

Tests that multiple users sharing a Hermes agent instance do not experience:
- Message confusion / session mixing
- State pollution between users
- Race conditions in session locking
- Resource contention issues
"""

import asyncio
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from unittest.mock import MagicMock

import httpx
import pytest

from agent.state_store import RemoteStateStore, RuntimeContext

# Skip Redis-dependent tests if redis is not available
redis_available = True
try:
    import redis
except (ImportError, ModuleNotFoundError):
    redis_available = False


# =============================================================================
# 1. RuntimeContext Isolation Tests
# =============================================================================

def test_runtime_context_is_frozen_and_immutable():
    """RuntimeContext is frozen=True, preventing accidental mutation."""
    ctx = RuntimeContext(
        tenant_id="tenant-a",
        user_id="user-1",
        session_id="session-1",
        state_token="token-1",
    )
    with pytest.raises((TypeError, AttributeError)):
        ctx.user_id = "user-2"


def test_runtime_context_from_mapping_creates_independent_instances():
    """Each call creates independent RuntimeContext instances."""
    mapping = {"user_id": "u-1", "session_id": "s-1", "tenant_id": "t-1"}

    ctx1 = RuntimeContext.from_mapping(mapping)
    ctx2 = RuntimeContext.from_mapping(mapping)

    # Verify they are separate objects
    assert ctx1 is not ctx2
    assert ctx1.user_id == ctx2.user_id == "u-1"


def test_concurrent_runtime_context_creation():
    """Creating many RuntimeContext instances concurrently is thread-safe."""
    results = []
    errors = []

    def create_ctx(user_id: str):
        try:
            ctx = RuntimeContext(
                tenant_id="shared-tenant",
                user_id=user_id,
                session_id=f"session-{user_id}",
                state_token=f"token-{user_id}",
            )
            results.append((user_id, ctx))
        except Exception as e:
            errors.append((user_id, e))

    with ThreadPoolExecutor(max_workers=20) as executor:
        futures = [executor.submit(create_ctx, f"user-{i}") for i in range(100)]
        for f in as_completed(futures):
            pass

    assert len(errors) == 0, f"Errors during creation: {errors}"
    assert len(results) == 100


# =============================================================================
# 2. RemoteStateStore Thread Safety Tests
# =============================================================================

def test_remote_state_store_headers_require_user_id():
    """RemoteStateStore requires user_id in RuntimeContext."""
    store = RemoteStateStore(
        "http://state-service",
        RuntimeContext(tenant_id="corp", user_id=None, state_token="tok"),
    )
    try:
        with pytest.raises(RuntimeError, match="requires user_id"):
            store._headers()
    finally:
        store.close()


def test_validated_sessions_cache_basic_functionality():
    """_validated_sessions cache works correctly for basic operations."""
    store = RemoteStateStore(
        "http://state-service",
        RuntimeContext(tenant_id="test-tenant", user_id="user-1"),
    )
    try:
        # Initially empty
        assert len(store._validated_sessions) == 0

        # Add entries
        store._validated_sessions["session-1"] = True
        store._validated_sessions["session-2"] = True

        assert len(store._validated_sessions) == 2
        assert "session-1" in store._validated_sessions
        assert "session-3" not in store._validated_sessions
    finally:
        store.close()


def test_validated_sessions_cache_concurrent_writes():
    """_validated_sessions cache handles concurrent writes from multiple threads."""

    store = RemoteStateStore(
        "http://state-service",
        RuntimeContext(tenant_id="test-tenant", user_id="user-1"),
    )

    try:
        session_ids = [f"session-{i}" for i in range(100)]

        def add_session(sid):
            store._validated_sessions[sid] = True

        with ThreadPoolExecutor(max_workers=20) as executor:
            futures = [executor.submit(add_session, sid) for sid in session_ids]
            for f in as_completed(futures):
                f.result()

        # All sessions should be cached
        assert len(store._validated_sessions) == 100
        for sid in session_ids:
            assert sid in store._validated_sessions
    finally:
        store.close()


# =============================================================================
# 3. Tenant Isolation Tests
# =============================================================================

def test_cross_tenant_access_is_rejected():
    """User from tenant-A cannot access tenant-B's sessions."""

    def create_mock_handler():
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"tenant_id": "tenant-b"})
        return handler

    mock_transport = MagicMock()
    mock_transport.handle_request = create_mock_handler()
    mock_http_client = httpx.Client(transport=mock_transport, timeout=10.0)

    store = RemoteStateStore(
        "http://state-service",
        RuntimeContext(tenant_id="tenant-a", user_id="user-a"),
    )
    store._client = mock_http_client

    try:
        with pytest.raises(PermissionError, match="Cross-tenant access denied"):
            store._validate_tenant("session-from-tenant-b")
    finally:
        mock_http_client.close()


def test_concurrent_cross_tenant_access_attempts():
    """Multiple concurrent cross-tenant access attempts are all rejected."""

    def create_mock_handler():
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"tenant_id": "other-tenant"})
        return handler

    mock_transport = MagicMock()
    mock_transport.handle_request = create_mock_handler()
    mock_http_client = httpx.Client(transport=mock_transport, timeout=10.0)

    store = RemoteStateStore(
        "http://state-service",
        RuntimeContext(tenant_id="my-tenant", user_id="my-user"),
    )
    store._client = mock_http_client

    try:
        results = []
        errors = []

        def try_access(sid):
            try:
                store._validate_tenant(sid)
                results.append(("allowed", sid))
            except PermissionError:
                results.append(("denied", sid))
            except Exception as e:
                errors.append((sid, str(e)))

        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(try_access, f"foreign-session-{i}") for i in range(20)]
            for f in as_completed(futures):
                pass

        assert len(errors) == 0, f"Unexpected errors: {errors}"
        denied = [r for r in results if r[0] == "denied"]
        assert len(denied) == 20, f"Expected all denied, got {len(denied)}/20"
    finally:
        mock_http_client.close()


# =============================================================================
# 4. Session Lock Atomicity Tests
# =============================================================================

@pytest.mark.skipif(not redis_available, reason="redis not installed")
def test_session_lock_acquire_release_cycle():
    """Test basic session lock acquire and release cycle."""
    from services.router.router_service import redis_client as rc

    user_id = "test-user-123"

    # Ensure clean state
    rc.release_session_lock(user_id)

    # Test acquire
    acquired, holder = rc.acquire_session_lock(user_id)
    # On first acquire, should succeed (acquired=True)
    assert acquired is True

    # Test that the same user can release
    released = rc.release_session_lock(user_id)
    assert released is True


@pytest.mark.skipif(not redis_available, reason="redis not installed")
def test_session_lock_prevents_concurrent_access():
    """Session lock prevents two holders from acquiring simultaneously."""
    from services.router.router_service import redis_client as rc

    user_id = "test-user-concurrent"

    # Ensure clean state
    rc.release_session_lock(user_id)

    # First acquire — should succeed
    acquired1, holder1 = rc.acquire_session_lock(user_id)
    assert acquired1 is True, "First acquire should succeed"

    # Second acquire — should fail (lock already held)
    acquired2, holder2 = rc.acquire_session_lock(user_id)
    assert acquired2 is False, "Second acquire should fail"
    assert holder2 is not None, "Should return current holder"

    # Release
    released = rc.release_session_lock(user_id)
    assert released is True

    # Now acquire should succeed again
    acquired3, holder3 = rc.acquire_session_lock(user_id)
    assert acquired3 is True, "Acquire after release should succeed"


# =============================================================================
# 5. Cache Eviction Under Memory Pressure
# =============================================================================

def test_validated_sessions_cache_eviction():
    """_validated_sessions cache evicts old entries when full."""

    store = RemoteStateStore(
        "http://state-service",
        RuntimeContext(tenant_id="t", user_id="u"),
    )

    try:
        max_size = store._validated_sessions_max_size

        # Fill cache beyond max size
        session_ids = [f"session-{i}" for i in range(max_size + 100)]

        for sid in session_ids:
            store._validated_sessions[sid] = True

        # Cache should not exceed max_size by too much (due to batch eviction)
        assert len(store._validated_sessions) <= max_size + (max_size // 10) + 10

        # Most recent entries should still be present
        for sid in session_ids[-50:]:
            assert sid in store._validated_sessions, f"Recent session {sid} was evicted"
    finally:
        store.close()


# =============================================================================
# 6. Asyncio Concurrency Tests
# =============================================================================

@pytest.mark.asyncio
async def test_asyncio_concurrent_context_creation():
    """Test concurrent RuntimeContext creation using asyncio."""

    async def create_ctx(user_id: str):
        return RuntimeContext(
            tenant_id="shared-tenant",
            user_id=user_id,
            session_id=f"session-{user_id}",
        )

    results = await asyncio.gather(*[create_ctx(f"user-{i}") for i in range(50)])

    assert len(results) == 50
    user_ids = [ctx.user_id for ctx in results]
    assert len(set(user_ids)) == 50


@pytest.mark.asyncio
async def test_asyncio_concurrent_cache_operations():
    """Test concurrent cache operations using asyncio."""

    store = RemoteStateStore(
        "http://state-service",
        RuntimeContext(tenant_id="t", user_id="u"),
    )

    try:
        async def add_and_check(sid: str):
            store._validated_sessions[sid] = True
            await asyncio.sleep(0.001)  # Simulate some async work
            return sid in store._validated_sessions

        results = await asyncio.gather(*[
            add_and_check(f"session-{i}") for i in range(30)
        ])

        assert all(results), "All entries should be in cache"
        assert len(store._validated_sessions) == 30
    finally:
        store.close()


# =============================================================================
# 7. ThreadPoolExecutor Concurrency Tests
# =============================================================================

def test_threadpool_concurrent_cache_writes():
    """ThreadPoolExecutor handles concurrent cache writes correctly."""

    store = RemoteStateStore(
        "http://state-service",
        RuntimeContext(tenant_id="t", user_id="u"),
    )

    try:
        errors = []

        def writer(thread_id: int):
            try:
                for i in range(100):
                    store._validated_sessions[f"thread-{thread_id}-session-{i}"] = True
            except Exception as e:
                errors.append((thread_id, str(e)))

        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(writer, i) for i in range(10)]
            for f in as_completed(futures):
                pass

        assert len(errors) == 0, f"Errors during concurrent writes: {errors}"
        assert len(store._validated_sessions) == 1000  # 10 threads * 100 sessions
    finally:
        store.close()


def test_concurrent_reads_after_concurrent_writes():
    """Concurrent reads see consistent state after concurrent writes."""

    store = RemoteStateStore(
        "http://state-service",
        RuntimeContext(tenant_id="t", user_id="u"),
    )

    try:
        # Pre-populate cache
        for i in range(100):
            store._validated_sessions[f"session-{i}"] = True

        read_results = []
        write_count = [0]
        lock = threading.Lock()

        def reader():
            count = 0
            for _ in range(100):
                for sid in list(store._validated_sessions.keys())[:10]:
                    if sid in store._validated_sessions:
                        count += 1
            return count

        def writer():
            for i in range(100, 200):
                store._validated_sessions[f"session-{i}"] = True
                with lock:
                    write_count[0] += 1

        read_futures = []
        write_futures = []
        with ThreadPoolExecutor(max_workers=10) as executor:
            # Start readers and writers
            read_futures = [executor.submit(reader) for _ in range(5)]
            write_futures = [executor.submit(writer) for _ in range(3)]

            # Wait for all to complete
            for f in as_completed(read_futures + write_futures):
                pass

            # Collect read results separately
            for f in read_futures:
                read_results.append(f.result())

        # Writes completed
        assert write_count[0] == 300  # 3 writers * 100 writes

        # All reads completed without errors
        assert len(read_results) == 5

        # Final cache should have 200 sessions
        assert len(store._validated_sessions) == 200
    finally:
        store.close()


# =============================================================================
# 8. Stress Test: High Concurrency
# =============================================================================

def test_high_concurrency_stress():
    """Stress test with very high concurrency."""

    store = RemoteStateStore(
        "http://state-service",
        RuntimeContext(tenant_id="t", user_id="u"),
    )

    try:
        num_threads = 50
        operations_per_thread = 50

        def worker(thread_id: int):
            for i in range(operations_per_thread):
                sid = f"session-{thread_id}-{i}"
                store._validated_sessions[sid] = True
                # Random read
                _ = f"sid in store._validated_sessions"
                store._validated_sessions.get(sid)

        with ThreadPoolExecutor(max_workers=num_threads) as executor:
            futures = [executor.submit(worker, i) for i in range(num_threads)]
            for f in as_completed(futures):
                f.result()

        # Total entries: 50 threads * 50 operations = 2500
        expected = num_threads * operations_per_thread
        actual = len(store._validated_sessions)
        # Due to eviction, actual may be less
        assert actual >= expected * 0.9, f"Expected ~{expected}, got {actual} (possible data loss)"
    finally:
        store.close()
