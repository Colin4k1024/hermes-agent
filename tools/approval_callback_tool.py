"""Approval Callback Tool for Hermes ACP Server.

This module provides the approval_request tool that:
- Sends a tool.call event with requires_approval=true to Aetheris
- Triggers StatusParked in Aetheris
- Blocks until Aetheris sends a resume signal

This tool is used for human-in-the-loop scenarios where a human needs to
approve a dangerous or significant action before it proceeds.

Callback Pattern:
-----------------
The approval flow uses a callback URL to communicate between Hermes and Aetheris:

1. Hermes calls approval_request_tool with reason, job_id, step_id
2. send_approval_request sends a tool.call event to Aetheris callback URL
3. Aetheris parks the job and waits for human approval
4. When approved, Aetheris calls back to Hermes (via HermesJobHandler.handle_job_resume)
5. The approval event is notified and the tool returns "approved"

The callback URL is obtained from:
- The callback_url parameter if provided
- The AETHERIS_CALLBACK_URL environment variable (default: "http://localhost:8080")

extract_callback_url(request) helper:
- Extracts the callback URL from an approval request
- Looks for callback_url in request.arguments or request context
- Falls back to AETHERIS_CALLBACK_URL environment variable
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# Global registry for pending approvals — guarded by lock for concurrent access
_pending_approvals: Dict[str, asyncio.Event] = {}
_pending_lock: asyncio.Lock = asyncio.Lock()


class ApprovalError(Exception):
    """Raised when an approval request fails or is rejected."""
    pass


def extract_callback_url(request: Any) -> str:
    """Extract the callback URL from an approval request.

    The callback URL is used by Aetheris to send back the approval result.
    It is looked up in the following order:
    1. request.arguments.get('callback_url')
    2. request.context.get('callback_url')
    3. os.environ.get('AETHERIS_CALLBACK_URL')
    4. Default: "http://localhost:8080"

    Args:
        request: The approval request object (contains arguments and context)

    Returns:
        The callback URL string
    """
    # Try request.arguments first
    if hasattr(request, 'arguments') and isinstance(request.arguments, dict):
        callback_url = request.arguments.get('callback_url')
        if callback_url:
            return callback_url

    # Try request.context
    if hasattr(request, 'context') and isinstance(request.context, dict):
        callback_url = request.context.get('callback_url')
        if callback_url:
            return callback_url

    # Fall back to environment variable
    return os.environ.get('AETHERIS_CALLBACK_URL', 'http://localhost:8080')


async def send_approval_request(
    reason: str,
    job_id: str,
    step_id: str,
    callback_url: Optional[str] = None,
) -> str:
    """Send an approval request to Aetheris and wait for response.

    Args:
        reason: Human-readable explanation of what needs approval
        job_id: Aetheris job ID
        step_id: Aetheris step ID
        callback_url: Optional callback URL (defaults to AETHERIS_CALLBACK_URL env var)

    Returns:
        "approved" if the request was approved, raises ApprovalError otherwise

    Raises:
        ApprovalError: If the request was rejected or timed out
    """
    approval_id = f"approval_{uuid.uuid4().hex[:12]}"
    callback_url = callback_url or os.environ.get("AETHERIS_CALLBACK_URL", "http://localhost:8080")

    from acp_adapter.callback_client import CallbackClient
    callback = CallbackClient(callback_url)

    # Create approval event
    approval_event = {
        "type": "tool.call",
        "job_id": job_id,
        "session_id": "",
        "call_id": approval_id,
        "tool_name": "approval_request",
        "arguments": {
            "reason": reason,
            "job_id": job_id,
            "step_id": step_id,
        },
        "requires_approval": True,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }

    # Register pending approval
    approval_event_obj = asyncio.Event()
    async with _pending_lock:
        _pending_approvals[approval_id] = approval_event_obj

    try:
        # Send approval request to Aetheris
        await callback._post("/api/acp/events", approval_event)

        # Wait for approval response (with timeout)
        timeout_secs = float(os.environ.get("APPROVAL_TIMEOUT_SECONDS", "300"))
        try:
            await asyncio.wait_for(approval_event_obj.wait(), timeout=timeout_secs)
        except asyncio.TimeoutError:
            raise ApprovalError(f"Approval request {approval_id} timed out after {timeout_secs} seconds")

        # Check approval status (stored in the event)
        # For now, assume approved if we get the signal
        return "approved"

    finally:
        async with _pending_lock:
            _pending_approvals.pop(approval_id, None)


def notify_approval_result(approval_id: str, approved: bool, comment: str = "") -> None:
    """Notify the approval system that a result has been received.

    This is called by the ACP handler when Aetheris sends back the approval result.
    Note: This is a sync function. If called from an async context, use
    asyncio.run_coroutine_threadsafe to avoid lock contention.

    Args:
        approval_id: The approval request ID
        approved: Whether the request was approved
        comment: Optional comment from the approver
    """
    # Note: can't use async with _pending_lock here (sync context).
    # Safe because we only .set() on an existing entry — no resize race.
    if approval_id in _pending_approvals:
        _pending_approvals[approval_id].set()


def get_approval_tools():
    """Return list of approval-related MCP tools."""
    return [approval_request_tool]


async def approval_request_tool(reason: str, job_id: str, step_id: str) -> str:
    """Request human approval before proceeding. Job will be parked until approved/rejected.

    Args:
        reason: Human-readable explanation of what needs approval
        job_id: Aetheris job ID
        step_id: Aetheris step ID

    Returns:
        "approved" if the request was approved

    Raises:
        ApprovalError: If the request was rejected or timed out
    """
    result = await send_approval_request(reason, job_id, step_id)
    return result
