"""Initial remote state schema.

Revision ID: 20260425_0001
Revises:
Create Date: 2026-04-25
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260425_0001"
down_revision = None
branch_labels = None
depends_on = None

sqlite_autoincrement_bigint = sa.BigInteger().with_variant(sa.Integer(), "sqlite")


def upgrade() -> None:
    op.create_table(
        "state_user_configs",
        sa.Column("id", sqlite_autoincrement_bigint, autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=128), nullable=False),
        sa.Column("scope", sa.String(length=32), nullable=False),
        sa.Column("key", sa.String(length=256), nullable=False),
        sa.Column("value", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "user_id", "scope", "key", name="uq_state_user_config"),
    )
    op.create_index("ix_state_user_configs_owner", "state_user_configs", ["tenant_id", "user_id"])

    op.create_table(
        "state_sessions",
        sa.Column("id", sa.String(length=128), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=128), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("model", sa.String(length=256), nullable=True),
        sa.Column("model_config", sa.JSON(), nullable=True),
        sa.Column("system_prompt_ref", sa.String(length=256), nullable=True),
        sa.Column("parent_session_id", sa.String(length=128), nullable=True),
        sa.Column("title", sa.String(length=200), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("end_reason", sa.String(length=64), nullable=True),
        sa.Column("message_count", sa.Integer(), nullable=False),
        sa.Column("tool_call_count", sa.Integer(), nullable=False),
        sa.Column("input_tokens", sa.BigInteger(), nullable=False),
        sa.Column("output_tokens", sa.BigInteger(), nullable=False),
        sa.Column("cache_read_tokens", sa.BigInteger(), nullable=False),
        sa.Column("cache_write_tokens", sa.BigInteger(), nullable=False),
        sa.Column("reasoning_tokens", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_state_sessions_owner_id", "state_sessions", ["tenant_id", "user_id", "id"])
    op.create_index("ix_state_sessions_owner_started", "state_sessions", ["tenant_id", "user_id", "started_at"])
    op.create_index("ix_state_sessions_parent", "state_sessions", ["parent_session_id"])

    op.create_table(
        "state_messages",
        sa.Column("id", sqlite_autoincrement_bigint, autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=128), nullable=False),
        sa.Column("session_id", sa.String(length=128), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("tool_call_id", sa.String(length=128), nullable=True),
        sa.Column("tool_calls", sa.JSON(), nullable=True),
        sa.Column("tool_name", sa.String(length=128), nullable=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=True),
        sa.Column("finish_reason", sa.String(length=64), nullable=True),
        sa.Column("reasoning", sa.Text(), nullable=True),
        sa.Column("reasoning_details", sa.JSON(), nullable=True),
        sa.Column("codex_reasoning_items", sa.JSON(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_state_messages_session_order",
        "state_messages",
        ["tenant_id", "user_id", "session_id", "timestamp", "id"],
    )

    op.create_table(
        "state_memory",
        sa.Column("id", sqlite_autoincrement_bigint, autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=128), nullable=False),
        sa.Column("namespace", sa.String(length=64), nullable=False),
        sa.Column("key", sa.String(length=256), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("is_deleted", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "user_id", "namespace", "key", name="uq_state_memory"),
    )
    op.create_index("ix_state_memory_owner", "state_memory", ["tenant_id", "user_id", "namespace"])

    op.create_table(
        "state_cache_metadata",
        sa.Column("id", sqlite_autoincrement_bigint, autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=128), nullable=False),
        sa.Column("session_id", sa.String(length=128), nullable=True),
        sa.Column("cache_key", sa.String(length=512), nullable=False),
        sa.Column("kind", sa.String(length=64), nullable=False),
        sa.Column("object_uri", sa.String(length=1024), nullable=True),
        sa.Column("content_sha256", sa.String(length=64), nullable=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "user_id", "cache_key", name="uq_state_cache_key"),
    )
    op.create_index(
        "ix_state_cache_owner_kind",
        "state_cache_metadata",
        ["tenant_id", "user_id", "kind"],
    )

    op.create_table(
        "state_audit_events",
        sa.Column("id", sqlite_autoincrement_bigint, autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=128), nullable=True),
        sa.Column("session_id", sa.String(length=128), nullable=True),
        sa.Column("request_id", sa.String(length=128), nullable=True),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("resource_type", sa.String(length=64), nullable=False),
        sa.Column("resource_id", sa.String(length=512), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_state_audit_owner_created",
        "state_audit_events",
        ["tenant_id", "user_id", "created_at"],
    )
    op.create_index(
        "ix_state_audit_resource",
        "state_audit_events",
        ["tenant_id", "resource_type", "resource_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_state_audit_resource", table_name="state_audit_events")
    op.drop_index("ix_state_audit_owner_created", table_name="state_audit_events")
    op.drop_table("state_audit_events")
    op.drop_index("ix_state_cache_owner_kind", table_name="state_cache_metadata")
    op.drop_table("state_cache_metadata")
    op.drop_index("ix_state_memory_owner", table_name="state_memory")
    op.drop_table("state_memory")
    op.drop_index("ix_state_messages_session_order", table_name="state_messages")
    op.drop_table("state_messages")
    op.drop_index("ix_state_sessions_parent", table_name="state_sessions")
    op.drop_index("ix_state_sessions_owner_started", table_name="state_sessions")
    op.drop_index("ix_state_sessions_owner_id", table_name="state_sessions")
    op.drop_table("state_sessions")
    op.drop_index("ix_state_user_configs_owner", table_name="state_user_configs")
    op.drop_table("state_user_configs")
