"""Pydantic schemas for State Service APIs."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field
from pydantic import ConfigDict


class RequestContext(BaseModel):
    tenant_id: str = "default"
    user_id: str
    session_id: str | None = None
    request_id: str | None = None


class EffectiveConfigResponse(BaseModel):
    tenant_id: str
    user_id: str
    config: dict[str, Any] = Field(default_factory=dict)


class ConfigUpsertRequest(BaseModel):
    scope: str = "user"
    key: str
    value: dict[str, Any] = Field(default_factory=dict)


class SessionCreateRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    session_id: str
    source: str
    model: str | None = None
    model_config_data: dict[str, Any] | None = Field(default=None, alias="model_config")
    system_prompt: str | None = None
    user_id: str | None = None
    parent_session_id: str | None = None


class SessionPatchRequest(BaseModel):
    title: str | None = None


class SessionResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    tenant_id: str
    user_id: str
    source: str
    model: str | None = None
    model_config_data: dict[str, Any] | None = Field(default=None, alias="model_config")
    parent_session_id: str | None = None
    title: str | None = None
    started_at: datetime
    ended_at: datetime | None = None
    end_reason: str | None = None
    message_count: int = 0
    tool_call_count: int = 0


class SessionMetadataResponse(BaseModel):
    id: str
    tenant_id: str
    user_id: str
    source: str
    model: str | None = None
    parent_session_id: str | None = None
    title: str | None = None
    started_at: datetime
    ended_at: datetime | None = None
    end_reason: str | None = None
    message_count: int = 0
    tool_call_count: int = 0


class MessageCreateRequest(BaseModel):
    role: str
    content: str | None = None
    tool_name: str | None = None
    tool_calls: Any = None
    tool_call_id: str | None = None
    token_count: int | None = None
    finish_reason: str | None = None
    reasoning: str | None = None
    reasoning_details: Any = None
    codex_reasoning_items: Any = None


class MessageResponse(BaseModel):
    id: int
    role: str
    content: str | None = None
    tool_call_id: str | None = None
    tool_calls: Any = None
    tool_name: str | None = None
    reasoning: str | None = None
    reasoning_details: Any = None
    codex_reasoning_items: Any = None


class MessagesResponse(BaseModel):
    messages: list[dict[str, Any]]


class SessionsListResponse(BaseModel):
    sessions: list[dict[str, Any]]


class MessageSearchResponse(BaseModel):
    results: list[dict[str, Any]]


class UsageUpdateRequest(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    reasoning_tokens: int = 0
    absolute: bool = False
    model: str | None = None


class EndSessionRequest(BaseModel):
    end_reason: str = "ended"


class MemoryUpsertRequest(BaseModel):
    value: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class MemoryItem(BaseModel):
    namespace: str
    key: str
    value: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    updated_at: datetime


class MemoryListResponse(BaseModel):
    items: list[MemoryItem]


class CacheMetadataRequest(BaseModel):
    kind: str
    object_uri: str | None = None
    content_sha256: str | None = None
    size_bytes: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class CacheMetadataResponse(BaseModel):
    cache_key: str
    kind: str
    object_uri: str | None = None
    content_sha256: str | None = None
    size_bytes: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
