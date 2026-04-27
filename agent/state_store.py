"""State store abstractions for stateless Hermes runtimes.

The CLI still defaults to local files and SQLite.  Enterprise/runtime
deployments can pass a RemoteStateStore so Agent pods can be disposable while
user/session state lives behind a service boundary.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol

from agent.retry_utils import jittered_backoff

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RuntimeContext:
    """Identity and routing context for one agent execution."""

    tenant_id: str = "default"
    user_id: str | None = None
    session_id: str | None = None
    request_id: str | None = None
    role: str | None = None
    quota_group: str | None = None
    allowed_tools: tuple[str, ...] = ()
    state_token: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | None) -> "RuntimeContext":
        if not value:
            return cls()
        allowed = value.get("allowed_tools") or ()
        if isinstance(allowed, str):
            allowed = tuple(t.strip() for t in allowed.split(",") if t.strip())
        return cls(
            tenant_id=str(value.get("tenant_id") or "default"),
            user_id=value.get("user_id"),
            session_id=value.get("session_id"),
            request_id=value.get("request_id"),
            role=value.get("role"),
            quota_group=value.get("quota_group"),
            allowed_tools=tuple(allowed),
            state_token=value.get("state_token"),
            metadata=value.get("metadata") or {},
        )


class SessionStore(Protocol):
    def create_session(self, session_id: str, source: str, model: str = None,
                       model_config: dict[str, Any] = None,
                       system_prompt: str = None, user_id: str = None,
                       parent_session_id: str = None) -> str: ...

    def append_message(self, session_id: str, role: str, content: str = None,
                       tool_name: str = None, tool_calls: Any = None,
                       tool_call_id: str = None, token_count: int = None,
                       finish_reason: str = None, reasoning: str = None,
                       reasoning_details: Any = None,
                       codex_reasoning_items: Any = None) -> int: ...

    def get_session(self, session_id: str) -> dict[str, Any] | None: ...

    def get_messages_as_conversation(self, session_id: str) -> list[dict[str, Any]]: ...

    def update_token_counts(self, session_id: str, **kwargs: Any) -> None: ...

    def ensure_session(self, session_id: str, source: str = "unknown", model: str = None) -> None: ...

    def list_sessions_rich(self, limit: int = 50, offset: int = 0, source: str = None,
                           exclude_sources: list[str] = None) -> list[dict[str, Any]]: ...

    def search_messages(self, query: str, role_filter: list[str] = None,
                        exclude_sources: list[str] = None, limit: int = 20,
                        offset: int = 0) -> list[dict[str, Any]]: ...


class ConfigStore(Protocol):
    def get_effective_config(self) -> dict[str, Any]: ...


class MemoryStoreBackend(Protocol):
    def list_memory(self, namespace: str = "memory") -> list[dict[str, Any]]: ...

    def upsert_memory(self, namespace: str, key: str, value: str,
                      metadata: dict[str, Any] | None = None) -> dict[str, Any]: ...

    def delete_memory(self, namespace: str, key: str) -> None: ...


class CacheStore(Protocol):
    def put_metadata(self, cache_key: str, kind: str, metadata: dict[str, Any]) -> dict[str, Any]: ...

    def get_metadata(self, cache_key: str) -> dict[str, Any] | None: ...


class StateStore(Protocol):
    runtime_context: RuntimeContext
    sessions: SessionStore
    config: ConfigStore
    memory: MemoryStoreBackend
    cache: CacheStore


class LocalStateStore:
    """Compatibility wrapper around existing local Hermes storage."""

    def __init__(self, runtime_context: RuntimeContext | Mapping[str, Any] | None = None, session_db=None):
        from hermes_state import SessionDB

        self.runtime_context = (
            runtime_context
            if isinstance(runtime_context, RuntimeContext)
            else RuntimeContext.from_mapping(runtime_context)
        )
        self.sessions = session_db or SessionDB()
        self.config = _LocalConfigStore()
        self.memory = _UnavailableMemoryStore()
        self.cache = _UnavailableCacheStore()


class _LocalConfigStore:
    def get_effective_config(self) -> dict[str, Any]:
        from hermes_cli.config import load_config

        return load_config()


class _UnavailableMemoryStore:
    def list_memory(self, namespace: str = "memory") -> list[dict[str, Any]]:
        return []

    def upsert_memory(self, namespace: str, key: str, value: str,
                      metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        raise RuntimeError("LocalStateStore does not expose remote memory operations")

    def delete_memory(self, namespace: str, key: str) -> None:
        raise RuntimeError("LocalStateStore does not expose remote memory operations")


class _UnavailableCacheStore:
    def put_metadata(self, cache_key: str, kind: str, metadata: dict[str, Any]) -> dict[str, Any]:
        raise RuntimeError("LocalStateStore does not expose remote cache operations")

    def get_metadata(self, cache_key: str) -> dict[str, Any] | None:
        return None


class RemoteStateStore:
    """Synchronous client used by the currently synchronous AIAgent loop.

    SaaS/multi-tenant ready: all requests include tenant/user authentication
    headers and validate tenant isolation on each session access.
    """

    def __init__(
        self,
        base_url: str,
        runtime_context: RuntimeContext | Mapping[str, Any],
        *,
        timeout: float = 10.0,
        max_connections: int = 20,
        max_keepalive_connections: int = 10,
    ):
        import httpx

        self.base_url = base_url.rstrip("/")
        self.runtime_context = (
            runtime_context
            if isinstance(runtime_context, RuntimeContext)
            else RuntimeContext.from_mapping(runtime_context)
        )
        # Connection pooling for stateless gateway pods
        limits = httpx.Limits(
            max_connections=max_connections,
            max_keepalive_connections=max_keepalive_connections,
        )
        self._client = httpx.Client(timeout=timeout, limits=limits)
        self._validated_sessions: dict[str, bool] = {}
        self._validated_sessions_lock = threading.Lock()
        self._validated_sessions_max_size: int = 10000
        self.sessions = _RemoteSessionStore(self)
        self.config = _RemoteConfigStore(self)
        self.memory = _RemoteMemoryStore(self)
        self.cache = _RemoteCacheStore(self)

    def close(self) -> None:
        self._client.close()

    def _headers(self) -> dict[str, str]:
        ctx = self.runtime_context
        if not ctx.user_id:
            raise RuntimeError("RemoteStateStore requires user_id in RuntimeContext")
        headers = {
            "X-Tenant-ID": ctx.tenant_id,
            "X-User-ID": ctx.user_id,
        }
        if ctx.session_id:
            headers["X-Session-ID"] = ctx.session_id
        if ctx.request_id:
            headers["X-Request-ID"] = ctx.request_id
        if ctx.state_token:
            headers["Authorization"] = f"Bearer {ctx.state_token}"
        return headers

    def _auth_headers(self) -> dict[str, str]:
        """Return only the authentication headers: tenant ID, user ID, and bearer token.

        Used for requests where session-specific headers (X-Session-ID, X-Request-ID)
        are not yet available or not needed.
        """
        ctx = self.runtime_context
        if not ctx.user_id:
            raise RuntimeError("RemoteStateStore requires user_id in RuntimeContext")
        headers = {
            "X-Tenant-ID": ctx.tenant_id,
            "X-User-ID": ctx.user_id,
        }
        if ctx.state_token:
            headers["Authorization"] = f"Bearer {ctx.state_token}"
        return headers

    def _validate_tenant(self, session_id: str) -> None:
        """Validate that the given session_id belongs to the current tenant.

        Results are cached per session_id for the lifetime of this store instance.

        Raises:
            PermissionError: If cross-tenant access is detected.
        """
        # Fast path: check without lock (dict read is thread-safe in CPython for simple ops)
        if session_id in self._validated_sessions:
            return

        import httpx

        # Perform HTTP validation OUTSIDE the lock — lock only protects cache write
        try:
            data = self._request("GET", f"/state/sessions/{session_id}/metadata")
            session_tenant = data.get("tenant_id") if data else None
            if session_tenant and session_tenant != self.runtime_context.tenant_id:
                raise PermissionError(
                    f"Cross-tenant access denied: session {session_id} "
                    f"belongs to tenant {session_tenant}, "
                    f"current tenant is {self.runtime_context.tenant_id}"
                )
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                data = None
            else:
                raise

        # Lock only protects the cache write — brief, no I/O
        with self._validated_sessions_lock:
            # Double-check after acquiring lock (another thread may have cached it)
            if session_id in self._validated_sessions:
                return
            # Evict oldest entry if at capacity
            if len(self._validated_sessions) >= self._validated_sessions_max_size:
                # Remove oldest ~10%
                keys_to_remove = list(self._validated_sessions.keys())[:max(1, self._validated_sessions_max_size // 10)]
                for k in keys_to_remove:
                    del self._validated_sessions[k]
            self._validated_sessions[session_id] = True

    _MAX_RETRIES = 3

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        import httpx

        merged_headers = {**self._headers(), **kwargs.pop("headers", {})}
        last_exc: Exception | None = None
        last_response: httpx.Response | None = None

        for attempt in range(1, self._MAX_RETRIES + 1):
            try:
                response = self._client.request(
                    method,
                    f"{self.base_url}{path}",
                    headers=merged_headers,
                    **kwargs,
                )
                last_response = response
                # Retry on 5xx errors (except on last attempt)
                if response.status_code >= 500 and attempt < self._MAX_RETRIES:
                    delay = jittered_backoff(attempt, base_delay=0.5, max_delay=5.0)
                    logger.warning(
                        "state-service %s %s returned %s, retrying in %.1fs (attempt %d/%d)",
                        method, path, response.status_code, delay, attempt, self._MAX_RETRIES,
                    )
                    time.sleep(delay)
                    continue
                # Always raise for 4xx/5xx status codes
                response.raise_for_status()
                if response.content:
                    return response.json()
                return None
            except (httpx.TransportError, httpx.TimeoutException) as exc:
                last_exc = exc
                if attempt < self._MAX_RETRIES:
                    delay = jittered_backoff(attempt, base_delay=0.5, max_delay=5.0)
                    logger.warning(
                        "state-service %s %s network error: %s, retrying in %.1fs (attempt %d/%d)",
                        method, path, exc, delay, attempt, self._MAX_RETRIES,
                    )
                    time.sleep(delay)
                    continue
                raise
            except httpx.HTTPStatusError:
                raise

        # All retries exhausted — raise last exception or last response error
        if last_exc is not None:
            raise last_exc
        if last_response is not None:
            last_response.raise_for_status()
        raise RuntimeError(f"state-service {method} {path} failed after {self._MAX_RETRIES} retries")


class _RemoteConfigStore:
    def __init__(self, root: RemoteStateStore):
        self._root = root

    def get_effective_config(self) -> dict[str, Any]:
        data = self._root._request("GET", "/state/config/effective")
        return data.get("config", data)


class _RemoteSessionStore:
    def __init__(self, root: RemoteStateStore):
        self._root = root

    def create_session(self, session_id: str, source: str, model: str = None,
                       model_config: dict[str, Any] = None,
                       system_prompt: str = None, user_id: str = None,
                       parent_session_id: str = None) -> str:
        self._root._request("POST", "/state/sessions", json={
            "session_id": session_id,
            "source": source,
            "model": model,
            "model_config": model_config,
            "system_prompt": system_prompt,
            "user_id": user_id,
            "parent_session_id": parent_session_id,
        })
        return session_id

    def ensure_session(self, session_id: str, source: str = "unknown", model: str = None) -> None:
        self.create_session(
            session_id=session_id,
            source=source,
            model=model,
            user_id=self._root.runtime_context.user_id,
        )

    def append_message(self, session_id: str, role: str, content: str = None,
                       tool_name: str = None, tool_calls: Any = None,
                       tool_call_id: str = None, token_count: int = None,
                       finish_reason: str = None, reasoning: str = None,
                       reasoning_details: Any = None,
                       codex_reasoning_items: Any = None) -> int:
        self._root._validate_tenant(session_id)
        data = self._root._request("POST", f"/state/sessions/{session_id}/messages", json={
            "role": role,
            "content": content,
            "tool_name": tool_name,
            "tool_calls": tool_calls,
            "tool_call_id": tool_call_id,
            "token_count": token_count,
            "finish_reason": finish_reason,
            "reasoning": reasoning,
            "reasoning_details": reasoning_details,
            "codex_reasoning_items": codex_reasoning_items,
        })
        return int(data.get("id", 0))

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        self._root._validate_tenant(session_id)
        try:
            return self._root._request("GET", f"/state/sessions/{session_id}")
        except Exception as exc:
            response = getattr(exc, "response", None)
            if getattr(response, "status_code", None) == 404:
                return None
            raise

    def get_session_title(self, session_id: str) -> str | None:
        session = self.get_session(session_id) or {}
        return session.get("title")

    def set_session_title(self, session_id: str, title: str) -> bool:
        self._root._validate_tenant(session_id)
        self._root._request("PATCH", f"/state/sessions/{session_id}", json={"title": title})
        return True

    def get_messages_as_conversation(self, session_id: str) -> list[dict[str, Any]]:
        self._root._validate_tenant(session_id)
        data = self._root._request("GET", f"/state/sessions/{session_id}/messages")
        return data.get("messages", [])

    def update_token_counts(self, session_id: str, **kwargs: Any) -> None:
        self._root._request("POST", f"/state/sessions/{session_id}/usage", json=kwargs)

    def list_sessions_rich(self, limit: int = 50, offset: int = 0, source: str = None,
                           exclude_sources: list[str] = None) -> list[dict[str, Any]]:
        params = {"limit": limit, "offset": offset}
        if source:
            params["source"] = source
        if exclude_sources:
            params["exclude_sources"] = ",".join(exclude_sources)
        data = self._root._request("GET", "/state/sessions", params=params)
        return data.get("sessions", [])

    def search_messages(self, query: str, role_filter: list[str] = None,
                        exclude_sources: list[str] = None, limit: int = 20,
                        offset: int = 0) -> list[dict[str, Any]]:
        params = {"query": query, "limit": limit, "offset": offset}
        if role_filter:
            params["role_filter"] = ",".join(role_filter)
        if exclude_sources:
            params["exclude_sources"] = ",".join(exclude_sources)
        data = self._root._request("GET", "/state/messages/search", params=params)
        return data.get("results", [])

    def end_session(self, session_id: str, end_reason: str) -> None:
        self._root._validate_tenant(session_id)
        self._root._request("POST", f"/state/sessions/{session_id}/end", json={"end_reason": end_reason})

    def reopen_session(self, session_id: str) -> None:
        self._root._request("POST", f"/state/sessions/{session_id}/reopen", json={})


class _RemoteMemoryStore:
    def __init__(self, root: RemoteStateStore):
        self._root = root

    def list_memory(self, namespace: str = "memory") -> list[dict[str, Any]]:
        data = self._root._request("GET", f"/state/memory?namespace={namespace}")
        return data.get("items", [])

    def upsert_memory(self, namespace: str, key: str, value: str,
                      metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        return self._root._request("PUT", f"/state/memory/{namespace}/{key}", json={
            "value": value,
            "metadata": metadata or {},
        })

    def delete_memory(self, namespace: str, key: str) -> None:
        self._root._request("DELETE", f"/state/memory/{namespace}/{key}")


class _RemoteCacheStore:
    def __init__(self, root: RemoteStateStore):
        self._root = root

    def put_metadata(self, cache_key: str, kind: str, metadata: dict[str, Any]) -> dict[str, Any]:
        return self._root._request("PUT", f"/state/cache/{cache_key}", json={
            "kind": kind,
            "metadata": metadata,
        })

    def get_metadata(self, cache_key: str) -> dict[str, Any] | None:
        try:
            return self._root._request("GET", f"/state/cache/{cache_key}")
        except Exception as exc:
            response = getattr(exc, "response", None)
            if getattr(response, "status_code", None) == 404:
                return None
            raise
