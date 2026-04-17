"""
Auth Service — Pydantic Schemas
"""
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


# === Auth / Login ===

class LoginRequest(BaseModel):
    email: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds


class RefreshRequest(BaseModel):
    refresh_token: str


class RefreshResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


# === User ===

class User(BaseModel):
    id: str
    email: str
    role: str = "user"
    feishu_union_id: Optional[str] = None
    is_active: bool = True
    created_at: datetime
    updated_at: datetime


class UserResponse(BaseModel):
    id: str
    email: str
    role: str
    feishu_union_id: Optional[str] = None
    is_active: bool
    created_at: datetime
    updated_at: datetime


# === API Token ===

class ApiTokenCreateResponse(BaseModel):
    token: str = Field(description="明文 Token，仅此时返回，请妥善保存")
    token_prefix: str = Field(description="Token 前缀（hms_xxx...）")
    expires_at: Optional[datetime] = None
    created_at: datetime


class ApiTokenInfo(BaseModel):
    id: str
    token_prefix: str
    description: Optional[str] = None
    expires_at: Optional[datetime] = None
    created_at: datetime
    last_used_at: Optional[datetime] = None
    is_active: bool


class ApiTokenListResponse(BaseModel):
    tokens: list[ApiTokenInfo]


class ApiTokenRevokeRequest(BaseModel):
    token_id: str


# === Feishu ===

class FeishuBindRequest(BaseModel):
    union_id: str
    nonce: str
    timestamp: str
    sign: str


class FeishuUserResponse(BaseModel):
    user_id: str
    email: str
    role: str
    feishu_union_id: Optional[str] = None


# === Internal ===

class InternalVerifyRequest(BaseModel):
    token: str


class InternalVerifyResponse(BaseModel):
    valid: bool
    user_id: Optional[str] = None
    role: Optional[str] = None
    error: Optional[str] = None


# === Health ===

class HealthResponse(BaseModel):
    status: str
    database: str
    redis: str


class TokenVerifyRequest(BaseModel):
    token: str
