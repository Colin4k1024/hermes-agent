"""Callback HTTP client for Hermes ACP Server to send events to Aetheris.

This module provides the CallbackClient class that handles:
- POST /api/acp/events  — tool.call, tool.result, session.start, session.end
- POST /api/acp/checkpoints — checkpoint data
- GET /api/acp/jobs/:job_id/status — job status queries

All HTTP calls include automatic retry with exponential backoff (3 retries).
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# Retry configuration
MAX_RETRIES = 3
INITIAL_BACKOFF = 1.0  # seconds
EXPONENTIAL_BASE = 2.0


class CallbackError(Exception):
    """Raised when callback to Aetheris fails after all retries."""

    def __init__(self, url: str, status_code: int, message: str):
        self.url = url
        self.status_code = status_code
        self.message = message
        super().__init__(f"Callback to {url} failed ({status_code}): {message}")


class CallbackClient:
    """HTTP client for sending events and queries to Aetheris.

    All public methods retry automatically with exponential backoff.
    Fire-and-forget semantics: failures are logged but do not raise
    exceptions after retries are exhausted (unless explicitly requested).
    """

    def __init__(
        self,
        aetheris_callback_url: str,
        http_client: Optional[Any] = None,
        max_retries: int = MAX_RETRIES,
    ):
        """
        Args:
            aetheris_callback_url: Base URL of Aetheris API (e.g., "http://localhost:8080")
            http_client: Optional aiohttp ClientSession instance. If None, creates one per request.
            max_retries: Maximum number of retry attempts (default 3).
        """
        self.base_url = aetheris_callback_url.rstrip("/")
        self._http_client = http_client
        self._own_client = False
        self.max_retries = max_retries

    async def _get_client(self) -> Any:
        """Get or create an HTTP client session."""
        if self._http_client is not None:
            return self._http_client

        import aiohttp
        self._http_client = aiohttp.ClientSession()
        self._own_client = True
        return self._http_client

    async def close(self) -> None:
        """Close the underlying HTTP client if we own it."""
        if self._own_client and self._http_client is not None:
            await self._http_client.close()
            self._http_client = None
            self._own_client = False

    async def _post(
        self,
        path: str,
        data: Dict[str, Any],
        timeout: float = 10.0,
    ) -> Dict[str, Any]:
        """POST JSON data to Aetheris with retry logic.

        Args:
            path: URL path (appended to base_url)
            data: JSON-serializable payload
            timeout: Request timeout in seconds

        Returns:
            Parsed JSON response dict

        Raises:
            CallbackError: If all retries fail
        """
        url = f"{self.base_url}{path}"
        backoff = INITIAL_BACKOFF

        last_error: Optional[Exception] = None
        last_status: Optional[int] = None

        for attempt in range(self.max_retries + 1):
            client = await self._get_client()
            try:
                async with client.post(
                    url,
                    json=data,
                    timeout=aiohttp.ClientTimeout(total=timeout),
                    headers={"Content-Type": "application/json"},
                ) as resp:
                    status = resp.status
                    body = await resp.json()

                    if status == 200:
                        return body

                    last_status = status
                    error_msg = body.get("error", "") or body.get("message", "") or f"HTTP {status}"

                    # Don't retry client errors (4xx)
                    if 400 <= status < 500:
                        raise CallbackError(url, status, error_msg)

                    # Retry server errors (5xx)
                    last_error = CallbackError(url, status, error_msg)

            except CallbackError:
                raise
            except asyncio.TimeoutError as e:
                last_error = e
                logger.warning("Callback timeout on attempt %d/%d: %s", attempt + 1, self.max_retries + 1, url)
            except aiohttp.ClientError as e:
                last_error = e
                logger.warning("Callback client error on attempt %d/%d: %s - %s", attempt + 1, self.max_retries + 1, url, e)

            if attempt < self.max_retries:
                await asyncio.sleep(backoff)
                backoff *= EXPONENTIAL_BASE

        raise CallbackError(url, last_status or 0, str(last_error))

    async def _get(
        self,
        path: str,
        timeout: float = 10.0,
    ) -> Dict[str, Any]:
        """GET JSON from Aetheris with retry logic.

        Args:
            path: URL path
            timeout: Request timeout in seconds

        Returns:
            Parsed JSON response dict

        Raises:
            CallbackError: If all retries fail
        """
        url = f"{self.base_url}{path}"
        backoff = INITIAL_BACKOFF

        last_error: Optional[Exception] = None
        last_status: Optional[int] = None

        for attempt in range(self.max_retries + 1):
            client = await self._get_client()
            try:
                async with client.get(
                    url,
                    timeout=aiohttp.ClientTimeout(total=timeout),
                    headers={"Accept": "application/json"},
                ) as resp:
                    status = resp.status
                    body = await resp.json()

                    if status == 200:
                        return body

                    last_status = status
                    error_msg = body.get("error", "") or body.get("message", "") or f"HTTP {status}"

                    if 400 <= status < 500:
                        raise CallbackError(url, status, error_msg)

                    last_error = CallbackError(url, status, error_msg)

            except CallbackError:
                raise
            except asyncio.TimeoutError as e:
                last_error = e
                logger.warning("GET timeout on attempt %d/%d: %s", attempt + 1, self.max_retries + 1, url)
            except aiohttp.ClientError as e:
                last_error = e
                logger.warning("GET client error on attempt %d/%d: %s - %s", attempt + 1, self.max_retries + 1, url, e)

            if attempt < self.max_retries:
                await asyncio.sleep(backoff)
                backoff *= EXPONENTIAL_BASE

        raise CallbackError(url, last_status or 0, str(last_error))

    # ---- Public API ---------------------------------------------------------

    async def send_event(
        self,
        event_type: str,
        job_id: str,
        session_id: str,
        call_id: Optional[str] = None,
        tool_name: Optional[str] = None,
        arguments: Optional[Dict[str, Any]] = None,
        result: Optional[Any] = None,
        error: Optional[str] = None,
        status: Optional[str] = None,
        final_response: Optional[str] = None,
    ) -> bool:
        """Send a tool call, tool result, session.start, or session.end event.

        Args:
            event_type: One of "tool.call", "tool.result", "session.start", "session.end"
            job_id: Aetheris job/run ID
            session_id: Hermes session ID
            call_id: Tool call ID (for tool.call and tool.result)
            tool_name: Name of the tool (for tool.call and tool.result)
            arguments: Tool arguments (for tool.call)
            result: Tool result (for tool.result)
            error: Error message (for tool.result)
            status: Session end status (for session.end: "completed", "failed", "canceled")
            final_response: Final agent response (for session.end)

        Returns:
            True if event was sent successfully, False otherwise
        """
        payload: Dict[str, Any] = {
            "type": event_type,
            "job_id": job_id,
            "session_id": session_id,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }

        if call_id is not None:
            payload["call_id"] = call_id
        if tool_name is not None:
            payload["tool_name"] = tool_name
        if arguments is not None:
            payload["arguments"] = arguments
        if result is not None:
            payload["result"] = result
        if error is not None:
            payload["error"] = error
        if status is not None:
            payload["status"] = status
        if final_response is not None:
            payload["final_response"] = final_response

        try:
            await self._post("/api/acp/events", payload)
            logger.debug("Sent %s event for job %s", event_type, job_id)
            return True
        except CallbackError as e:
            logger.error("Failed to send %s event for job %s: %s", event_type, job_id, e)
            return False

    async def send_session_start(
        self,
        job_id: str,
        session_id: str,
    ) -> bool:
        """Send session.start event."""
        return await self.send_event(
            event_type="session.start",
            job_id=job_id,
            session_id=session_id,
        )

    async def send_session_end(
        self,
        job_id: str,
        session_id: str,
        status: str,
        final_response: Optional[str] = None,
    ) -> bool:
        """Send session.end event."""
        return await self.send_event(
            event_type="session.end",
            job_id=job_id,
            session_id=session_id,
            status=status,
            final_response=final_response,
        )

    async def send_tool_call(
        self,
        job_id: str,
        session_id: str,
        call_id: str,
        tool_name: str,
        arguments: Dict[str, Any],
    ) -> bool:
        """Send tool.call event."""
        return await self.send_event(
            event_type="tool.call",
            job_id=job_id,
            session_id=session_id,
            call_id=call_id,
            tool_name=tool_name,
            arguments=arguments,
        )

    async def send_tool_result(
        self,
        job_id: str,
        session_id: str,
        call_id: str,
        tool_name: str,
        result: Any,
        error: Optional[str] = None,
    ) -> bool:
        """Send tool.result event."""
        return await self.send_event(
            event_type="tool.result",
            job_id=job_id,
            session_id=session_id,
            call_id=call_id,
            tool_name=tool_name,
            result=result,
            error=error,
        )

    async def send_checkpoint(
        self,
        job_id: str,
        session_id: str,
        checkpoint_id: str,
        cursor: str,
        history: Optional[list] = None,
        snapshot_size: int = 0,
    ) -> bool:
        """Send checkpoint data to Aetheris.

        Args:
            job_id: Aetheris job/run ID
            session_id: Hermes session ID
            checkpoint_id: Unique checkpoint ID
            cursor: Message ID or position for resumption
            history: Optional conversation history snapshot
            snapshot_size: Size of snapshot in bytes

        Returns:
            True if checkpoint was saved successfully, False otherwise
        """
        payload = {
            "job_id": job_id,
            "session_id": session_id,
            "checkpoint": {
                "id": checkpoint_id,
                "cursor": cursor,
                "history": history or [],
                "snapshot_size": snapshot_size,
            },
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }

        try:
            result = await self._post("/api/acp/checkpoints", payload)
            logger.debug("Checkpoint %s saved for job %s", checkpoint_id, job_id)
            return result.get("status") == "ok"
        except CallbackError as e:
            logger.error("Failed to save checkpoint for job %s: %s", job_id, e)
            return False

    async def send_checkpoint_v2(
        self,
        session_id: str,
        run_id: str,
        step_id: str,
        state_json: str,
    ) -> bool:
        """Send checkpoint data to Aetheris (Phase 3 version).

        Args:
            session_id: Hermes session ID
            run_id: Aetheris run/job ID
            step_id: Current step ID
            state_json: JSON-encoded session state

        Returns:
            True if checkpoint was saved successfully, False otherwise
        """
        import json
        payload = {
            "job_id": run_id,
            "session_id": session_id,
            "step_id": step_id,
            "state": json.loads(state_json) if isinstance(state_json, str) else state_json,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }

        try:
            result = await self._post("/api/acp/checkpoints", payload)
            logger.debug("Checkpoint saved for run %s, step %s", run_id, step_id)
            return result.get("status") == "ok"
        except CallbackError as e:
            logger.error("Failed to save checkpoint for run %s: %s", run_id, e)
            return False

    async def get_job_status(
        self,
        job_id: str,
    ) -> Optional[Dict[str, Any]]:
        """Query job status from Aetheris.

        Args:
            job_id: Aetheris job/run ID

        Returns:
            Dict with job status info, or None if query failed

            Success response:
            {
                "job_id": "run_xxx",
                "status": "running",
                "is_canceled": false
            }

            Canceled response:
            {
                "job_id": "run_xxx",
                "status": "canceled",
                "is_canceled": true
            }
        """
        try:
            return await self._get(f"/api/acp/jobs/{job_id}/status")
        except CallbackError as e:
            logger.error("Failed to get status for job %s: %s", job_id, e)
            return None
