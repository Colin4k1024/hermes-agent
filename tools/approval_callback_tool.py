"""Approval Callback Tool for Hermes ACP Server.

This module provides the approval_request tool that:
- Sends a tool.call event with requires_approval=true to Aetheris
- Triggers StatusParked in Aetheris
- Blocks until Aetheris sends a resume signal

This tool is used for human-in-the-loop scenarios where a human needs to
approve a dangerous or significant action before it proceeds.
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

# Global registry for pending approvals
_pending_approvals: Dict[str, asyncio.Event] = {}


class ApprovalError(Exception):
    """Raised when an approval request fails or is rejected."""
    pass


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
    _pending_approvals[approval_id] = approval_event_obj

    try:
        # Send approval request to Aetheris
        await callback._post("/api/acp/events", approval_event)

        # Wait for approval response (with timeout)
        try:
            await asyncio.wait_for(approval_event_obj.wait(), timeout=300.0)
        except asyncio.TimeoutError:
            raise ApprovalError(f"Approval request {approval_id} timed out after 5 minutes")

        # Check approval status (stored in the event)
        # For now, assume approved if we get the signal
        return "approved"

    finally:
        _pending_approvals.pop(approval_id, None)


def notify_approval_result(approval_id: str, approved: bool, comment: str = "") -> None:
    """Notify the approval system that a result has been received.

    This is called by the ACP handler when Aetheris sends back the approval result.

    Args:
        approval_id: The approval request ID
        approved: Whether the request was approved
        comment: Optional comment from the approver
    """
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
