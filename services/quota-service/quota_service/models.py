"""SQLAlchemy ORM models for Quota Service."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger,
    Date,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class QuotaConfig(Base):
    """Role-level quota configuration. One row per quota_group (maps to role)."""

    __tablename__ = "quota_configs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    quota_group: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    daily_token_limit: Mapped[int] = mapped_column(BigInteger, nullable=False, default=100_000)
    daily_request_limit: Mapped[int] = mapped_column(Integer, nullable=False, default=500)
    model_allowlist: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)
    create_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    update_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class UsageRecord(Base):
    """Daily usage record per user. Partitioned by record_date."""

    __tablename__ = "usage_records"
    __table_args__ = (
        Index("ix_usage_records_user_date", "user_id", "record_date"),
        Index("ix_usage_records_record_date", "record_date"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    record_date: Mapped[datetime] = mapped_column(Date, nullable=False, default=lambda: datetime.now(timezone.utc).date())
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    input_tokens: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    output_tokens: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    total_tokens: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    request_count: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    create_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
