"""Entry point for Hermes ACP Server (TCP/HTTP mode) for Aetheris integration.

This module provides the `hermes acp-server` command which starts Hermes as an
ACP Server that:
- Receives job.dispatch messages from Aetheris via HTTP POST
- Creates Hermes sessions and runs AI tasks
- Sends tool call events back to Aetheris via HTTP callbacks

Usage::

    hermes acp-server --port 9090
    # or
    python -m acp_adapter.acp_server_entry --port 9090
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from aiohttp import web

# Ensure project root is on path
from pathlib import Path
project_root = str(Path(__file__).parent.parent.resolve())
if project_root not in sys.path:
    sys.path.insert(0, project_root)


def _setup_logging() -> None:
    """Configure logging for ACP server."""
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


async def handle_job_dispatch(request: web.Request) -> web.Response:
    """Handle POST /api/acp/jobs - job.dispatch from Aetheris."""
    try:
        body = await request.read()
    except Exception as e:
        return web.json_response(
            {"error": "invalid_request", "message": f"Failed to read body: {e}"},
            status=400,
        )

    # Get the job handler from app
    handler = request.app["job_handler"]
    result = await handler.handle_job_dispatch_raw(body)

    if "error" in result:
        return web.json_response(result, status=400)

    return web.json_response(result, status=200)


async def handle_events(request: web.Request) -> web.Response:
    """Handle POST /api/acp/events - legacy callback endpoint."""
    # This endpoint is called by Hermes (as callback) not by Aetheris directly
    # For now, just acknowledge
    return web.json_response({"status": "ok"})


async def handle_checkpoints(request: web.Request) -> web.Response:
    """Handle POST /api/acp/checkpoints - checkpoint callback."""
    return web.json_response({"status": "ok"})


async def handle_job_status(request: web.Request) -> web.Response:
    """Handle GET /api/acp/jobs/:job_id/status - query job status."""
    job_id = request.match_info.get("job_id")
    if not job_id:
        return web.json_response(
            {"error": "invalid_request", "message": "Missing job_id"},
            status=400,
        )

    handler = request.app["job_handler"]
    status = await handler.get_job_status(job_id)

    if status is None:
        return web.json_response(
            {"error": "job_not_found", "message": f"Job {job_id} not found"},
            status=404,
        )

    return web.json_response(status)


async def handle_ping(request: web.Request) -> web.Response:
    """Handle GET /api/acp/ping - heartbeat/ping endpoint."""
    return web.json_response({"type": "pong"})


def create_app(job_handler) -> web.Application:
    """Create and configure the aiohttp application."""
    app = web.Application()
    app["job_handler"] = job_handler

    # Routes for Aetheris -> Hermes communication
    app.router.add_post("/api/acp/jobs", handle_job_dispatch)
    app.router.add_get("/api/acp/jobs/{job_id}/status", handle_job_status)

    # Routes for Hermes -> Aetheris callbacks (mostly for testing/compatibility)
    app.router.add_post("/api/acp/events", handle_events)
    app.router.add_post("/api/acp/checkpoints", handle_checkpoints)

    # Heartbeat
    app.router.add_get("/api/acp/ping", handle_ping)

    return app


def main(host: str = "0.0.0.0", port: int = 9090) -> None:
    """Start the Hermes ACP Server.

    Args:
        host: Host to bind to (default: 0.0.0.0)
        port: Port to listen on (default: 9090)
    """
    _setup_logging()
    logger = logging.getLogger(__name__)
    logger.info("Starting Hermes ACP Server on %s:%d", host, port)

    # Import here to avoid circular imports and allow module to load without aiohttp
    from acp_adapter.hermes_job_handler import HermesJobHandler
    from acp_adapter.session import SessionManager

    # Create job handler with session manager
    session_manager = SessionManager()
    job_handler = HermesJobHandler(session_manager=session_manager)

    # Create and run app
    app = create_app(job_handler)

    try:
        web.run_app(app, host=host, port=port, access_log=None)
    except KeyboardInterrupt:
        logger.info("Shutting down (KeyboardInterrupt)")
    except Exception:
        logger.exception("ACP server crashed")
        sys.exit(1)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Hermes ACP Server for Aetheris")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind to")
    parser.add_argument("--port", "-p", type=int, default=9090, help="Port to listen on")
    args = parser.parse_args()

    main(host=args.host, port=args.port)
