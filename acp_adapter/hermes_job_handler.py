"""HermesJobHandler: Handles Aetheris job.dispatch messages for Hermes ACP Server.

This module provides the HermesJobHandler class that:
- Receives job.dispatch messages from Aetheris via HTTP
- Creates Hermes sessions with the provided instruction
- Runs AI tasks using the delegate_task tool
- Sends tool call events back to Aetheris via CallbackClient
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

# Thread pool for running AIAgent (synchronous) in parallel
_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="hermes-job")


@dataclass
class JobDispatch:
    """Represents a job dispatch message from Aetheris."""
    job_id: str
    workflow_id: Optional[str] = None
    step_id: Optional[str] = None
    instruction: str = ""
    tools: List[str] = field(default_factory=list)
    context: Dict[str, Any] = field(default_factory=dict)
    callback_url: str = ""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "JobDispatch":
        """Parse a job.dispatch message from dict."""
        return cls(
            job_id=data.get("job_id", ""),
            workflow_id=data.get("workflow_id"),
            step_id=data.get("step_id"),
            instruction=data.get("instruction", ""),
            tools=data.get("tools", []),
            context=data.get("context", {}),
            callback_url=data.get("callback_url", ""),
        )

    def validate(self) -> List[str]:
        """Validate the dispatch message. Returns list of error messages (empty if valid)."""
        errors = []
        if not self.job_id:
            errors.append("Missing required field: job_id")
        if not self.instruction:
            errors.append("Missing required field: instruction")
        if not self.callback_url:
            errors.append("Missing required field: callback_url")
        return errors


@dataclass
class HermesJobState:
    """Tracks state for a job being handled by Hermes."""
    job_id: str
    session_id: str
    workflow_id: Optional[str]
    step_id: Optional[str]
    callback_url: str
    context: Dict[str, Any]
    allowed_tools: List[str]
    status: str = "pending"  # pending, running, completed, failed, canceled, parked
    cancel_event: Optional[Any] = None  # asyncio.Event
    resume_event: Optional[Any] = None  # asyncio.Event for job.resume


class HermesJobHandler:
    """Handles job dispatch messages from Aetheris and coordinates Hermes session execution.

    This handler:
    1. Receives job.dispatch HTTP POST from Aetheris
    2. Creates a Hermes session with the instruction
    3. Runs the AI task with delegate_task tool
    4. Sends all tool events back to Aetheris callback URL
    5. Sends session.end when complete
    """

    def __init__(
        self,
        session_manager: Optional[Any] = None,
        callback_client_factory: Optional[Callable[[str], Any]] = None,
    ):
        """
        Args:
            session_manager: Optional SessionManager instance. If None, creates default.
            callback_client_factory: Factory function that takes callback_url string
                                     and returns a CallbackClient. If None, uses default.
        """
        self._session_manager = session_manager
        self._callback_client_factory = callback_client_factory
        self._active_jobs: Dict[str, HermesJobState] = {}
        self._jobs_lock = asyncio.Lock()

    def _get_session_manager(self) -> Any:
        """Get or create the SessionManager."""
        if self._session_manager is None:
            from acp_adapter.session import SessionManager
            self._session_manager = SessionManager()
        return self._session_manager

    def _create_callback_client(self, callback_url: str) -> Any:
        """Create a CallbackClient for the given callback URL."""
        if self._callback_client_factory is not None:
            return self._callback_client_factory(callback_url)
        from acp_adapter.callback_client import CallbackClient
        return CallbackClient(callback_url)

    async def handle_job_dispatch(
        self,
        dispatch: JobDispatch,
    ) -> Dict[str, Any]:
        """Handle an incoming job.dispatch message.

        Args:
            dispatch: Parsed JobDispatch message

        Returns:
            Response dict with status and session_id
        """
        errors = dispatch.validate()
        if errors:
            return {
                "error": "invalid_request",
                "message": "; ".join(errors),
            }

        job_id = dispatch.job_id
        callback_url = dispatch.callback_url

        # Check if job already exists
        async with self._jobs_lock:
            if job_id in self._active_jobs:
                existing = self._active_jobs[job_id]
                return {
                    "error": "job_already_exists",
                    "message": f"Job {job_id} is already being handled",
                    "session_id": existing.session_id,
                }

        # Create callback client for this job
        callback = self._create_callback_client(callback_url)

        # Create Hermes session
        session_manager = self._get_session_manager()
        session_id = None
        try:
            state = session_manager.create_session(cwd=".")
            session_id = state.session_id
        except Exception as e:
            logger.exception("Failed to create session for job %s", job_id)
            return {
                "error": "session_creation_failed",
                "message": str(e),
            }

        # Track the job
        job_state = HermesJobState(
            job_id=job_id,
            session_id=session_id,
            workflow_id=dispatch.workflow_id,
            step_id=dispatch.step_id,
            callback_url=callback_url,
            context=dispatch.context,
            allowed_tools=dispatch.tools,
            status="running",
            cancel_event=asyncio.Event(),
        )

        async with self._jobs_lock:
            self._active_jobs[job_id] = job_state

        # Send session.start event
        await callback.send_session_start(job_id=job_id, session_id=session_id)

        # Run the job asynchronously and track the task so we can log if it dies
        task = asyncio.create_task(
            self._run_job(job_state, dispatch.instruction, dispatch.tools, dispatch.context)
        )
        task.add_done_callback(
            lambda t: logger.error("job %s task died with: %s", job_state.job_id, t.exception())
            if t.cancelled() or (t.exception() is not None)
            else None
        )

        return {
            "status": "accepted",
            "session_id": session_id,
            "message": "Job dispatched successfully",
        }

    async def handle_job_dispatch_raw(self, body: bytes) -> Dict[str, Any]:
        """Handle raw JSON body of a job.dispatch message.

        Args:
            body: Raw JSON bytes

        Returns:
            Response dict
        """
        try:
            data = json.loads(body)
        except json.JSONDecodeError as e:
            return {"error": "invalid_json", "message": str(e)}

        if data.get("type") != "job.dispatch":
            return {"error": "unexpected_message_type", "message": f"Expected job.dispatch, got {data.get('type')}"}

        dispatch = JobDispatch.from_dict(data)
        return await self.handle_job_dispatch(dispatch)

    async def _run_job(
        self,
        job_state: HermesJobState,
        instruction: str,
        allowed_tools: List[str],
        context: Dict[str, Any],
    ) -> None:
        """Run the AI task for a job.

        This runs in a background task and:
        1. Injects context (GitHub token, etc.) into the session
        2. Sends tool calls to Aetheris via callback
        3. Completes with session.end event
        """
        session_manager = self._get_session_manager()
        state = session_manager.get_session(job_state.session_id)
        if state is None:
            logger.error("Session %s not found for job %s", job_state.session_id, job_state.job_id)
            return

        callback = self._create_callback_client(job_state.callback_url)

        try:
            # Inject context into session
            context_msg = self._build_context_message(context)
            if context_msg:
                state.history.append(context_msg)

            # Set up tool tracking
            tool_call_ids: Dict[str, str] = {}
            tool_call_lock = asyncio.Lock()

            def make_progress_callback():
                """Create a tool_progress_callback for AIAgent."""
                async def on_tool_progress(event_type: str, name: str = None, preview: str = None, args: Any = None, **kwargs):
                    if event_type != "tool.started":
                        return
                    call_id = str(uuid.uuid4())
                    async with tool_call_lock:
                        tool_call_ids[name] = call_id

                    # Check if this is an approval tool
                    is_approval = name and name.lower() in (
                        "approval_request", "approval_callback", "request_approval",
                        "human_approval", "confirm_action"
                    )

                    await callback.send_tool_call(
                        job_id=job_state.job_id,
                        session_id=job_state.session_id,
                        call_id=call_id,
                        tool_name=name,
                        arguments=args if isinstance(args, dict) else {"raw": str(args)},
                    )

                    # If approval tool, set job to parked status
                    if is_approval:
                        job_state.status = "parked"
                        logger.info("Job %s parked for approval: %s", job_state.job_id, name)
                return on_tool_progress

            def make_result_callback():
                """Create a step_callback that sends tool results."""
                async def on_step(api_call_count: int, prev_tools: Any = None):
                    if not prev_tools or not isinstance(prev_tools, list):
                        return
                    for tool_info in prev_tools:
                        if isinstance(tool_info, dict):
                            tool_name = tool_info.get("name") or tool_info.get("function_name")
                            result = tool_info.get("result") or tool_info.get("output")
                            async with tool_call_lock:
                                call_id = tool_call_ids.pop(tool_name, str(uuid.uuid4()))
                            await callback.send_tool_result(
                                job_id=job_state.job_id,
                                session_id=job_state.session_id,
                                call_id=call_id,
                                tool_name=tool_name,
                                result=str(result) if result is not None else None,
                            )
                    # Send checkpoint after tool completion
                    self._send_checkpoint(job_state, state)
                return on_step

            # Set callbacks on agent
            agent = state.agent
            loop = asyncio.get_running_loop()

            progress_cb = make_progress_callback()
            result_cb = make_result_callback()

            if hasattr(agent, 'tool_progress_callback'):
                agent.tool_progress_callback = progress_cb
            if hasattr(agent, 'step_callback'):
                agent.step_callback = result_cb

            # Build the task instruction with context
            full_instruction = instruction
            if context:
                context_str = self._format_context(context)
                full_instruction = f"{instruction}\n\nContext:\n{context_str}"

            # Run agent in thread pool
            def run_agent():
                try:
                    result = agent.run_conversation(
                        user_message=full_instruction,
                        conversation_history=state.history,
                        task_id=job_state.session_id,
                    )
                    return result
                except Exception as e:
                    logger.exception("Agent error for job %s", job_state.job_id)
                    return {"final_response": f"Error: {e}", "messages": state.history}

            result = await loop.run_in_executor(_executor, run_agent)

            # Defensive: guard against None result
            if result is None:
                result = {}
                final_status = "failed"
                final_response = "Agent returned no result"
            elif job_state.cancel_event and job_state.cancel_event.is_set():
                final_status = "canceled"
                final_response = result.get("final_response", "")
            elif "error" in str(result.get("final_response", "")).lower():
                final_status = "failed"
                final_response = result.get("final_response", "")
            else:
                final_status = "completed"
                final_response = result.get("final_response", "")

            # Save session
            if result.get("messages"):
                state.history = result["messages"]
                session_manager.save_session(job_state.session_id)

            # Send session.end
            await callback.send_session_end(
                job_id=job_state.job_id,
                session_id=job_state.session_id,
                status=final_status,
                final_response=final_response,
            )

            job_state.status = final_status
            logger.info("Job %s completed with status: %s", job_state.job_id, final_status)

        except asyncio.CancelledError:
            logger.info("Job %s was canceled", job_state.job_id)
            await callback.send_session_end(
                job_id=job_state.job_id,
                session_id=job_state.session_id,
                status="canceled",
            )
            job_state.status = "canceled"
        except Exception as e:
            logger.exception("Job %s failed with error", job_state.job_id)
            await callback.send_session_end(
                job_id=job_state.job_id,
                session_id=job_state.session_id,
                status="failed",
                final_response=f"Internal error: {e}",
            )
            job_state.status = "failed"
        finally:
            async with self._jobs_lock:
                self._active_jobs.pop(job_state.job_id, None)
            await callback.close()

    def _is_sensitive_key(self, key: str) -> bool:
        """Check if a key contains sensitive information (token or secret).
        
        Uses partial matching - returns True if key.lower() contains 'token' or 'secret'.
        This is more comprehensive than exact match which only catches specific named keys.
        
        Args:
            key: The context key to check
            
        Returns:
            True if the key appears to contain sensitive information
        """
        lower_key = key.lower()
        return "token" in lower_key or "secret" in lower_key

    def _build_context_message(self, context: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Build a system message with context information.
        
        Sensitive values (keys containing 'token' or 'secret') are redacted.
        """
        if not context:
            return None

        lines = ["Context information:"]
        for key, value in context.items():
            # Skip sensitive values - check if key.lower() contains "token" or "secret"
            if self._is_sensitive_key(key):
                lines.append(f"- {key}: [REDACTED]")
            elif isinstance(value, str) and len(value) > 200:
                lines.append(f"- {key}: {value[:200]}...")
            else:
                lines.append(f"- {key}: {value}")

        return {
            "role": "system",
            "content": "\n".join(lines),
        }

    def _format_context(self, context: Dict[str, Any]) -> str:
        """Format context dict as a readable string.
        
        Sensitive values (keys containing 'token' or 'secret') are redacted.
        """
        lines = []
        for key, value in context.items():
            # Skip sensitive values - check if key.lower() contains "token" or "secret"
            if self._is_sensitive_key(key):
                lines.append(f"{key}: [REDACTED]")
            elif isinstance(value, str):
                lines.append(f"{key}: {value}")
            else:
                lines.append(f"{key}: {json.dumps(value)}")
        return "\n".join(lines)

    async def get_job_status(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Get the current status of a job.

        Args:
            job_id: The job ID to query

        Returns:
            Status dict or None if job not found
        """
        async with self._jobs_lock:
            job = self._active_jobs.get(job_id)
            if job is None:
                return None
            return {
                "job_id": job.job_id,
                "session_id": job.session_id,
                "status": job.status,
                "is_canceled": job.cancel_event.is_set() if job.cancel_event else False,
            }

    async def cancel_job(self, job_id: str) -> bool:
        """Cancel a running job.

        Args:
            job_id: The job ID to cancel

        Returns:
            True if job was found and canceled, False otherwise
        """
        async with self._jobs_lock:
            job = self._active_jobs.get(job_id)
            if job is None:
                return False
            if job.cancel_event:
                job.cancel_event.set()
            job.status = "canceled"
            return True

    async def handle_job_resume(self, job_id: str) -> Dict[str, Any]:
        """Handle job.resume message to resume a parked job.

        Args:
            job_id: The job ID to resume

        Returns:
            Response dict with status
        """
        async with self._jobs_lock:
            job = self._active_jobs.get(job_id)
            if job is None:
                return {
                    "error": "job_not_found",
                    "message": f"Job {job_id} not found or not in parked state",
                }

        # Try to load checkpoint
        try:
            from hermes_state import SessionDB
            db = SessionDB()
            checkpoint_state = db.load_checkpoint(job_id)
            if checkpoint_state:
                # Restore session state
                session_manager = self._get_session_manager()
                state = session_manager.get_session(job.session_id)
                if state and checkpoint_state.get("history"):
                    state.history = checkpoint_state.get("history", [])
                    session_manager.save_session(job.session_id)
        except Exception as e:
            logger.warning("Failed to load checkpoint for job %s: %s", job_id, e)

        # Signal resume
        if job.resume_event:
            job.resume_event.set()
        job.status = "running"

        return {
            "status": "resumed",
            "job_id": job_id,
            "message": "Job resumed successfully",
        }

    def _send_checkpoint(self, job_state: HermesJobState, session_state: Any) -> None:
        """Send checkpoint to Aetheris.

        Args:
            job_state: The job state
            session_state: The session state to checkpoint
        """
        try:
            from hermes_state import SessionDB
            db = SessionDB()
            checkpoint_state = {
                "session_id": job_state.session_id,
                "history": session_state.history if hasattr(session_state, "history") else [],
                "status": job_state.status,
            }
            db.save_checkpoint(job_state.job_id, job_state.step_id or "unknown", checkpoint_state)
        except Exception as e:
            logger.warning("Failed to send checkpoint for job %s: %s", job_state.job_id, e)
