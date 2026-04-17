"""SQLAlchemy models for Skills Registry (mirrors arch-design §5.1)."""

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import Column, DateTime, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


class OrgSkill(Base):
    """org_skills table — stores skill metadata."""

    __tablename__ = "org_skills"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    name = Column(String(64), nullable=False, unique=True, index=True)
    description = Column(String(1024), nullable=False, default="")
    version = Column(Integer, nullable=False, default=1)
    status = Column(String(32), nullable=False, default="active")  # active | archived
    nas_path = Column(String(512), nullable=False)
    published_by = Column(UUID(as_uuid=True), nullable=True)
    tags = Column(Text, nullable=True, default="")  # JSON-serialized list
    create_time = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    update_time = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "status": self.status,
            "nas_path": self.nas_path,
            "published_by": str(self.published_by) if self.published_by else None,
            "tags": self.tags or "",
            "create_time": self.create_time,
            "update_time": self.update_time,
        }
