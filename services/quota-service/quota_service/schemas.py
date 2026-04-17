"""Pydantic schemas — request/response models."""
from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class Role(str, Enum):
    USER = "user"
    POWER_USER = "power_user"
    ADMIN = "admin"


class QuotaCheckResult(str, Enum):
    ALLOWED = "allowed"
    DENIED = "denied"
    UNLIMITED = "unlimited"


# ---------------------------------------------------------------------------
# Quota check
# ---------------------------------------------------------------------------


class QuotaCheckRequest(BaseModel):
    user_id: UUID
    estimated_tokens: int = Field(default=0, ge=0, description="Estimated token cost for the request")
    model: str | None = Field(default=None, description="Target LLM model")


class QuotaCheckResponse(BaseModel):
    allowed: bool
    result: QuotaCheckResult
    user_id: UUID
    role: str
    quota_group: str
    daily_limit: int
    used_tokens: int
    remaining_tokens: int
    daily_request_limit: int
    used_requests: int
    remaining_requests: int
    reset_at: str = Field(description="ISO 8601 datetime when the daily quota resets")


# ---------------------------------------------------------------------------
# Quota consume
# ---------------------------------------------------------------------------


class QuotaConsumeRequest(BaseModel):
    user_id: UUID
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    model: str | None = None
    metadata: dict[str, Any] | None = Field(default=None, description="Arbitrary key-value metadata")


class QuotaConsumeResponse(BaseModel):
    success: bool
    user_id: UUID
    tokens_consumed: int
    input_tokens: int
    output_tokens: int
    total_daily_tokens: int
    request_count: int
    daily_limit: int
    remaining_tokens: int


# ---------------------------------------------------------------------------
# LLM callback (LiteLLM format)
# ---------------------------------------------------------------------------


class LLMTokens(BaseModel):
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None


class LitellmUsage(BaseModel):
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    cost: float | None = None


class LitellmCallbackRequest(BaseModel):
    """Callback payload sent by LiteLLM proxy.

    Reference: https://docs.litellm.ai/docs/proxy/callbacks#usage---tracking-llm-cost-per-user
    """

    user: str | None = Field(default=None, description="user_id passed to LiteLLM call")
    model: str | None = None
    total_cost: float = 0.0
    usage: LitellmUsage | None = None
    call_type: str | None = None
    metadata: dict[str, Any] | None = None
    start_time: str | None = None
    end_time: str | None = None

    @field_validator("user", mode="before")
    @classmethod
    def normalize_user(cls, v: str | None) -> str | None:
        # LiteLLM may send "user" as the platform user_id
        return v


class LLMTokensResponse(BaseModel):
    """Response returned to LiteLLM callback endpoint."""

    status: str = "success"
    tokens: int | None = Field(default=None, description="Total tokens recorded")


# ---------------------------------------------------------------------------
# Quota status
# ---------------------------------------------------------------------------


class QuotaStatusResponse(BaseModel):
    user_id: UUID
    role: str
    quota_group: str
    daily_limit: int
    is_unlimited: bool
    used_tokens: int
    remaining_tokens: int
    used_requests: int
    remaining_requests: int
    daily_request_limit: int
    record_date: date
    reset_at: str
    model_allowlist: list[str] | None = None


# ---------------------------------------------------------------------------
# Admin
# ---------------------------------------------------------------------------


class QuotaConfigCreate(BaseModel):
    quota_group: str = Field(max_length=64)
    daily_token_limit: int = Field(ge=-1)
    daily_request_limit: int = Field(ge=1)
    model_allowlist: list[str] | None = None


class QuotaConfigUpdate(BaseModel):
    daily_token_limit: int | None = Field(default=None, ge=-1)
    daily_request_limit: int | None = Field(default=None, ge=1)
    model_allowlist: list[str] | None = None


class QuotaConfigResponse(BaseModel):
    id: UUID
    quota_group: str
    daily_token_limit: int
    daily_request_limit: int
    model_allowlist: list[str] | None
    create_time: datetime
    update_time: datetime

    model_config = {"from_attributes": True}


class AdminQuotaUsageResponse(BaseModel):
    user_id: UUID
    username: str | None
    role: str
    quota_group: str
    record_date: date
    used_tokens: int
    used_requests: int
    daily_limit: int
    usage_percentage: float


class AdminDashboardResponse(BaseModel):
    total_users: int
    total_tokens_today: int
    total_requests_today: int
    users_at_limit: int
    top_users: list[AdminQuotaUsageResponse]


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


class HealthResponse(BaseModel):
    db_ok: bool
    redis_ok: bool
    version: str = "0.1.0"


class InternalHealthResponse(BaseModel):
    ok: bool
    service: str = "quota-service"


# ---------------------------------------------------------------------------
# Error
# ---------------------------------------------------------------------------


class ErrorResponse(BaseModel):
    detail: str
