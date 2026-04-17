"""
Auth Service — SQLAlchemy Models
"""
from sqlalchemy import Column, String, Boolean, DateTime, Text, Index
from sqlalchemy.orm import declarative_base
from datetime import datetime

Base = declarative_base()


class User(Base):
    __tablename__ = "users"

    id = Column(String(64), primary_key=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(32), default="user", nullable=False)  # user / power_user / admin
    feishu_union_id = Column(String(128), unique=True, nullable=True, index=True)
    keycloak_sub = Column(String(128), unique=True, nullable=True, index=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class ApiToken(Base):
    __tablename__ = "api_tokens"

    id = Column(String(64), primary_key=True)
    user_id = Column(String(64), nullable=False, index=True)
    token_hash = Column(String(255), unique=True, nullable=False, index=True)
    token_prefix = Column(String(16), nullable=False)  # hms_xxx...
    description = Column(Text, nullable=True)
    expires_at = Column(DateTime, nullable=True)
    last_used_at = Column(DateTime, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id = Column(String(64), primary_key=True)
    user_id = Column(String(64), nullable=False, index=True)
    token_hash = Column(String(255), unique=True, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    revoked = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(String(64), primary_key=True)
    user_id = Column(String(64), nullable=True)
    event_type = Column(String(64), nullable=False, index=True)  # login / logout / token_create / token_revoke / feishu_bind
    ip_address = Column(String(64), nullable=True)
    user_agent = Column(String(512), nullable=True)
    detail = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
