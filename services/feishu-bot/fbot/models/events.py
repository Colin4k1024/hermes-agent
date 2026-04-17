"""Pydantic models for Feishu Bot Service."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ── Enums ────────────────────────────────────────────────────────────────────


class MessageDirection(str, Enum):
    """Whether the message was sent TO the bot or BY the bot."""

    INBOUND = "inbound"   # user → bot
    OUTBOUND = "outbound"  # bot → user


class BindingStatus(str, Enum):
    """User feishu binding status as determined by Auth Service."""

    BOUND = "bound"         # union_id → user_id mapping exists
    NOT_BOUND = "not_bound"  # union_id not found in platform
    AUTH_ERROR = "auth_error"  # Auth Service itself returned an error


# ── Inbound / Outbound ────────────────────────────────────────────────────────


class FeishuEventHeader(BaseModel):
    """Common header fields from Feishu event envelope."""

    event_id: str = Field(..., description="Feishu-assigned unique event ID")
    event_type: str = Field(..., description="Event type, e.g. im.message.receive_v1")
    create_time: str = Field(..., description="ISO-8601 event creation time")


class FeishuMessageContent(BaseModel):
    """Parsed message content from Feishu im.message.receive_v1 event."""

    # Message-level fields
    message_type: str = Field(..., description="e.g. text, post, image, card")
    message_id: str = Field(..., description="Feishu message ID")
    root_id: str = Field(default="", description="Root message ID for reply chains")
    parent_id: str = Field(default="", description="Parent message ID")
    create_time: str = Field(..., description="Message creation timestamp")
    chat_id: str = Field(..., description="Chat/conversation ID")
    chat_type: str = Field(..., description="p2p or group")
    body: str = Field(default="", description="Raw body content")

    # Sender
    sender_id_type: str = Field(default="", description="open_id / union_id / user_id")
    sender_id: str = Field(default="", description="Sender's ID per sender_id_type")
    sender: Dict[str, Any] = Field(default_factory=dict)

    # Extracted text (populated by normalizer)
    text_content: str = Field(default="", description="Normalized plain-text content")


class FeishuInboundEvent(BaseModel):
    """Normalized representation of a received Feishu message event."""

    header: FeishuEventHeader
    event: Dict[str, Any] = Field(
        default_factory=dict,
        description="Raw event object from Feishu payload",
    )
    message: Optional[FeishuMessageContent] = Field(
        default=None,
        description="Parsed message content, None if parsing failed",
    )

    # Convenience fields extracted during processing
    event_id: str = Field(default="")
    union_id: str = Field(default="")
    chat_id: str = Field(default="")
    text_content: str = Field(default="")
    message_id: str = Field(default="")
    chat_type: str = Field(default="")

    def model_post_init(self, __ctx: Any) -> None:
        # Promote convenience fields from nested models so handlers don't need
        # to drill into .message / .header every time.
        if self.header:
            self.event_id = self.header.event_id
        if self.message:
            self.chat_id = self.message.chat_id
            self.text_content = self.message.text_content
            self.message_id = self.message.message_id
            self.chat_type = self.message.chat_type
            # Try to extract union_id from sender
            sender = self.message.sender
            if isinstance(sender, dict):
                self.union_id = sender.get("union_id", "")


# ── Redis Streams ────────────────────────────────────────────────────────────


class FeishuRequestRecord(BaseModel):
    """Fields written to feishu:requests stream."""

    user_id: str = Field(..., description="Platform user_id (from Auth Service)")
    union_id: str = Field(default="", description="Feishu union_id")
    feishu_msg_id: str = Field(..., description="Feishu message ID")
    feishu_chat_id: str = Field(..., description="Feishu chat ID")
    message: str = Field(..., description="Normalized text content")
    reply_channel: str = Field(
        ...,
        description="Redis response stream name for Router to write back",
    )
    fbot_instance_id: str = Field(
        default="",
        description="FBot instance that originated this request",
    )


class FeishuResponseChunk(BaseModel):
    """One chunk written by Router to the response stream."""

    request_id: str = Field(..., description="Stream ID from feishu:requests")
    chunk: str = Field(default="", description="Text chunk of the response")
    done: bool = Field(default=False, description="True = this is the final chunk")


class FeishuResponseFinal(BaseModel):
    """Complete response assembled from stream chunks."""

    request_id: str
    full_text: str
    error: Optional[str] = None


# ── Auth Service integration ─────────────────────────────────────────────────


class AuthUserByFeishuIdResponse(BaseModel):
    """Response from Auth Service GET /auth/user/by-feishu-id."""

    user_id: str
    username: str


# ── Internal API ─────────────────────────────────────────────────────────────


class RouteRequest(BaseModel):
    """Request body for POST /internal/route (from Router → Pod)."""

    user_id: str
    message: str
    feishu_msg_id: str = ""
    feishu_chat_id: str = ""
    reply_channel: str = ""
    fbot_instance_id: str = ""


# ── Webhook payload shapes ────────────────────────────────────────────────────


class FeishuUrlVerificationPayload(BaseModel):
    """Payload for feishu event type: endpoint.event.verify."""

    type: str
    token: str
    challenge: str


class FeishuWebhookPayload(BaseModel):
    """Top-level envelope of Feishu Webhook POST /feishu/webhook."""

    payload_schema: str = Field(default="2.0", alias="schema")
    header: FeishuEventHeader
    event: Dict[str, Any] = Field(default_factory=dict)

    model_config = {"populate_by_name": True}


# ── Health ────────────────────────────────────────────────────────────────────


class HealthStatus(BaseModel):
    """Health check response."""

    status: str = "ok"
    version: str = "0.1.0"
    fbot_instance_id: str = ""
    redis_connected: bool = False
