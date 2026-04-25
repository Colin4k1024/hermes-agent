"""Pydantic schemas for Agent Router Service."""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class PodStatus(str, Enum):
    IDLE = "idle"
    BUSY = "busy"
    PREPARING = "preparing"
    UNHEALTHY = "unhealthy"


class RouteSource(str, Enum):
    HOT = "hot"      # Existing route found in Redis
    COLD = "cold"    # Cold start: selected from idle pool


class RuntimeContext(BaseModel):
    """Identity and state context forwarded to a stateless Agent Pod."""

    tenant_id: str = Field(default="default")
    user_id: str
    session_id: str | None = None
    request_id: str | None = None
    role: str | None = None
    quota_group: str | None = None
    allowed_tools: list[str] = Field(default_factory=list)
    state_service_url: str | None = None
    state_token: str | None = None


# ---------------------------------------------------------------------------
# Internal route request/response
# ---------------------------------------------------------------------------


class InternalRouteRequest(BaseModel):
    """POST /internal/route — Feishu Bot routes a message to an Agent Pod."""

    user_id: str = Field(..., description="Platform user ID")
    message: str = Field(..., description="User message content")
    feishu_msg_id: str | None = Field(
        default=None, description="Feishu message ID for deduplication"
    )
    feishu_chat_id: str | None = Field(
        default=None, description="Feishu chat ID"
    )
    reply_channel: str | None = Field(
        default=None,
        description=(
            "Redis response stream key, e.g. 'feishu:responses:{fbot_instance_id}'. "
            "Router writes response chunks to this stream."
        ),
    )
    # feishu_bot_id is extracted from reply_channel by Router if needed
    estimated_tokens: int | None = Field(
        default=None, description="Estimated token count for quota check"
    )
    tenant_id: str = Field(default="default", description="Tenant boundary for remote state")
    session_id: str | None = Field(
        default=None,
        description="Conversation/session ID. Stateless routing locks on this when present.",
    )
    request_id: str | None = Field(default=None, description="Trace/request ID")
    runtime_context: RuntimeContext | None = Field(
        default=None,
        description="Pre-authenticated runtime context from the caller/Auth Service.",
    )


class InternalRouteResponse(BaseModel):
    """Response for /internal/route."""

    success: bool
    pod_id: str | None = None
    pod_url: str | None = None
    source: RouteSource | None = None  # hot or cold
    message: str | None = None
    # Quota check result
    quota_allowed: bool = True
    quota_message: str | None = None
    # Cold-start metadata
    cold_start_ms: int | None = None
    prepare_retries: int | None = None


# ---------------------------------------------------------------------------
# Internal prepare request/response
# ---------------------------------------------------------------------------


class InternalPrepareRequest(BaseModel):
    """POST /internal/prepare — Trigger cold-start for a Pod.

    Called by Router when assigning a user to a specific Pod.
    The Sidecar writes /tmp/pending_user.json and triggers Hermes restart.
    """

    user_id: str = Field(..., description="Platform user ID to assign")
    hermes_home_path: str = Field(
        ..., description="NAS path to the user's HERMES_HOME directory"
    )
    env_vars: dict[str, str] | None = Field(
        default=None, description="Optional additional env vars"
    )
    runtime_context: RuntimeContext | None = Field(
        default=None,
        description="Remote-state runtime context for stateless Agent pods",
    )
    stateless: bool = Field(
        default=False,
        description="True when the pod should avoid user-local persistent HERMES_HOME state",
    )


class InternalPrepareResponse(BaseModel):
    """Response for /internal/prepare (from Pod Sidecar)."""

    ready: bool
    pod_id: str
    user_id: str
    hermes_home_path: str
    message: str | None = None
    error: str | None = None


# ---------------------------------------------------------------------------
# Internal health
# ---------------------------------------------------------------------------


class PodHealthDetail(BaseModel):
    pod_id: str
    status: PodStatus
    last_heartbeat: str | None  # ISO timestamp


class InternalHealthResponse(BaseModel):
    """GET /internal/health — Pool status for operators."""

    ok: bool
    pool_size: int = Field(
        ..., description="Total Pods in the pool (idle + active + preparing)"
    )
    idle_pods: int = Field(..., description="Pods available for assignment")
    active_pods: int = Field(..., description="Pods currently serving users")
    preparing_pods: int = Field(
        ..., description="Pods in cold-start process"
    )
    unhealthy_pods: int = Field(
        default=0, description="Pods that failed health check"
    )
    pod_details: list[PodHealthDetail] = Field(default_factory=list)
    redis_ok: bool = True
    version: str = "0.1.0"


# ---------------------------------------------------------------------------
# Quota check
# ---------------------------------------------------------------------------


class QuotaCheckRequest(BaseModel):
    """Request to Quota Service."""

    user_id: str
    estimated_tokens: int = 0


class QuotaCheckResponse(BaseModel):
    """Response from Quota Service."""

    allowed: bool
    remaining_tokens: int = 0
    message: str | None = None


# ---------------------------------------------------------------------------
# Auth verification (internal)
# ---------------------------------------------------------------------------


class TokenVerifyResponse(BaseModel):
    """Response from Auth Service /auth/token/verify."""

    user_id: str
    username: str
    role: str
    quota_group: str
    nas_shard: str | None = None


# ---------------------------------------------------------------------------
# Error responses
# ---------------------------------------------------------------------------


class ErrorResponse(BaseModel):
    detail: str


# ---------------------------------------------------------------------------
# OpenAI-compatible proxy schemas (passthrough to Pod)
# ---------------------------------------------------------------------------


class ChatCompletionsRequest(BaseModel):
    """Minimal schema for OpenAI /v1/chat/completions proxy.

    Actual passthrough preserves full request body as dict.
    """

    model: str = "hermes-default"
    messages: list[dict] = Field(default_factory=list)
    stream: bool = False
