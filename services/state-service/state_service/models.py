"""SQLAlchemy models for remote user state."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

SqliteAutoincrementBigInt = BigInteger().with_variant(Integer, "sqlite")


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class UserConfig(Base):
    __tablename__ = "state_user_configs"
    __table_args__ = (
        UniqueConstraint("tenant_id", "user_id", "scope", "key", name="uq_state_user_config"),
        Index("ix_state_user_configs_owner", "tenant_id", "user_id"),
    )

    id: Mapped[int] = mapped_column(SqliteAutoincrementBigInt, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, default="default")
    user_id: Mapped[str] = mapped_column(String(128), nullable=False)
    scope: Mapped[str] = mapped_column(String(32), nullable=False, default="user")
    key: Mapped[str] = mapped_column(String(256), nullable=False)
    value: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now_utc, onupdate=now_utc, nullable=False
    )


class Session(Base):
    __tablename__ = "state_sessions"
    __table_args__ = (
        Index("ix_state_sessions_owner_id", "tenant_id", "user_id", "id"),
        Index("ix_state_sessions_owner_started", "tenant_id", "user_id", "started_at"),
        Index("ix_state_sessions_parent", "parent_session_id"),
    )

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, default="default")
    user_id: Mapped[str] = mapped_column(String(128), nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    model: Mapped[str | None] = mapped_column(String(256), nullable=True)
    model_config: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    system_prompt_ref: Mapped[str | None] = mapped_column(String(256), nullable=True)
    parent_session_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    end_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    message_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    tool_call_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    input_tokens: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    output_tokens: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    cache_read_tokens: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    cache_write_tokens: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    reasoning_tokens: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)


class Message(Base):
    __tablename__ = "state_messages"
    __table_args__ = (
        Index("ix_state_messages_session_order", "tenant_id", "user_id", "session_id", "timestamp", "id"),
    )

    id: Mapped[int] = mapped_column(SqliteAutoincrementBigInt, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, default="default")
    user_id: Mapped[str] = mapped_column(String(128), nullable=False)
    session_id: Mapped[str] = mapped_column(String(128), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    tool_call_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    tool_calls: Mapped[dict | list | None] = mapped_column(JSON, nullable=True)
    tool_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)
    token_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    finish_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reasoning: Mapped[str | None] = mapped_column(Text, nullable=True)
    reasoning_details: Mapped[dict | list | None] = mapped_column(JSON, nullable=True)
    codex_reasoning_items: Mapped[dict | list | None] = mapped_column(JSON, nullable=True)


class MemoryRecord(Base):
    __tablename__ = "state_memory"
    __table_args__ = (
        UniqueConstraint("tenant_id", "user_id", "namespace", "key", name="uq_state_memory"),
        Index("ix_state_memory_owner", "tenant_id", "user_id", "namespace"),
    )

    id: Mapped[int] = mapped_column(SqliteAutoincrementBigInt, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, default="default")
    user_id: Mapped[str] = mapped_column(String(128), nullable=False)
    namespace: Mapped[str] = mapped_column(String(64), nullable=False, default="memory")
    key: Mapped[str] = mapped_column(String(256), nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now_utc, onupdate=now_utc, nullable=False
    )


class CacheMetadata(Base):
    __tablename__ = "state_cache_metadata"
    __table_args__ = (
        UniqueConstraint("tenant_id", "user_id", "cache_key", name="uq_state_cache_key"),
        Index("ix_state_cache_owner_kind", "tenant_id", "user_id", "kind"),
    )

    id: Mapped[int] = mapped_column(SqliteAutoincrementBigInt, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, default="default")
    user_id: Mapped[str] = mapped_column(String(128), nullable=False)
    session_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    cache_key: Mapped[str] = mapped_column(String(512), nullable=False)
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    object_uri: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    content_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    metadata_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now_utc, onupdate=now_utc, nullable=False
    )


class AuditEvent(Base):
    __tablename__ = "state_audit_events"
    __table_args__ = (
        Index("ix_state_audit_owner_created", "tenant_id", "user_id", "created_at"),
        Index("ix_state_audit_resource", "tenant_id", "resource_type", "resource_id"),
    )

    id: Mapped[int] = mapped_column(SqliteAutoincrementBigInt, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, default="default")
    user_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    session_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_id: Mapped[str | None] = mapped_column(String(512), nullable=True)
    metadata_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, nullable=False)
