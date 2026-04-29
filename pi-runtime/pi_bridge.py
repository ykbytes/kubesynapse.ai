#!/usr/bin/env python3
"""HTTP-to-pi-RPC Bridge Sidecar.

Listens on an HTTP port and forwards requests to a pi RPC subprocess
running on stdin/stdout. This allows the existing kubesynapse worker.py
(which uses HTTP) to communicate with pi agents without modification.

Endpoints:
  POST /prompt          — Send a prompt to pi, get streaming events back
  POST /prompt_sync     — Send a prompt and wait for completion
  GET  /state           — Get current pi session state
  POST /abort           — Abort the current operation
  GET  /health          — Health check (returns 200 if pi is alive)
  GET  /ready           — Readiness check (pi process running + FIFO writable)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import sys
import time
from collections.abc import AsyncGenerator
from typing import Any

from aiohttp import web

# ── Configuration ────────────────────────────────────────────────────────

PI_FIFO_PATH = os.getenv("PI_FIFO_PATH", "/tmp/pi-stdin")
PI_STDOUT_PATH = os.getenv("PI_STDOUT_PATH", "/proc/1/fd/1")  # Read from pi's stdout
HTTP_PORT = int(os.getenv("PI_BRIDGE_PORT", "8080"))
HTTP_HOST = os.getenv("PI_BRIDGE_HOST", "0.0.0.0")

logger = logging.getLogger("pi-bridge")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [pi-bridge] %(message)s")


# ── Pi RPC Communication ─────────────────────────────────────────────────

class PiRpcBridge:
    """Wraps communication with pi's RPC mode via FIFO and stdout."""

    def __init__(self, fifo_path: str, stdout_fd: int = 1) -> None:
        self._fifo_path = fifo_path
        self._stdout_fd = stdout_fd
        self._command_counter = 0
        self._lock = asyncio.Lock()

    def _next_id(self) -> str:
        self._command_counter += 1
        return f"bridge-{self._command_counter}"

    async def send_command(self, command: dict[str, Any], timeout: float = 60.0) -> dict[str, Any]:
        """Send a command to pi via the FIFO and wait for the response."""
        cmd = {**command, "id": self._next_id()}
        payload = json.dumps(cmd, ensure_ascii=False) + "\n"

        async with self._lock:
            # Write to pi's FIFO
            try:
                with open(self._fifo_path, "w") as f:
                    f.write(payload)
                    f.flush()
            except OSError as exc:
                raise RuntimeError(f"Failed to write to pi FIFO: {exc}") from exc

            # Pi writes responses to its stdout (PID 1's stdout).
            # In a pod, the container's stdout is available at /proc/1/fd/1.
            # We need to read the response. Since multiple commands may interleave,
            # we read lines until we find a response with our command ID.
            deadline = time.monotonic() + timeout
            try:
                with open(f"/proc/1/fd/1", "r") as stdout:
                    while time.monotonic() < deadline:
                        line = stdout.readline()
                        if not line:
                            await asyncio.sleep(0.1)
                            continue
                        try:
                            data = json.loads(line.strip())
                            if data.get("type") == "response" and data.get("id") == cmd.get("id"):
                                return data
                        except json.JSONDecodeError:
                            continue
            except Exception:
                pass

            raise TimeoutError(f"No response from pi for command '{cmd.get('type')}' within {timeout}s")

    async def send_prompt(self, message: str, timeout: float = 300.0) -> dict[str, Any]:
        """Send a prompt and wait for agent_end."""
        return await self.send_command({"type": "prompt", "message": message}, timeout=timeout)

    async def get_state(self) -> dict[str, Any]:
        """Get pi session state."""
        response = await self.send_command({"type": "get_state"}, timeout=10.0)
        return response.get("data", {})

    async def abort(self) -> dict[str, Any]:
        """Abort the current operation."""
        return await self.send_command({"type": "abort"}, timeout=5.0)

    def is_alive(self) -> bool:
        """Check if pi process is running via PID 1."""
        try:
            with open("/proc/1/cmdline", "rb") as f:
                return b"pi" in f.read()
        except Exception:
            return False


# ── HTTP Handlers ─────────────────────────────────────────────────────────

pi_bridge = PiRpcBridge(PI_FIFO_PATH)


async def handle_health(request: web.Request) -> web.Response:
    """Health check."""
    if pi_bridge.is_alive():
        return web.json_response({"status": "healthy", "pi": "running"}, status=200)
    return web.json_response({"status": "unhealthy", "pi": "not running"}, status=503)


async def handle_ready(request: web.Request) -> web.Response:
    """Readiness check — verify pi responds to commands."""
    try:
        await pi_bridge.get_state()
        return web.json_response({"status": "ready"}, status=200)
    except Exception as exc:
        return web.json_response({"status": "not ready", "error": str(exc)}, status=503)


async def handle_get_state(request: web.Request) -> web.Response:
    """Get pi session state."""
    try:
        state = await pi_bridge.get_state()
        return web.json_response(state, status=200)
    except Exception as exc:
        return web.json_response({"error": str(exc)}, status=500)


async def handle_prompt(request: web.Request) -> web.StreamResponse:
    """Send a prompt to pi and stream the response."""
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "Invalid JSON"}, status=400)

    message = body.get("message") or body.get("prompt", "")
    if not message:
        return web.json_response({"error": "message is required"}, status=400)

    # Create streaming response
    response = web.StreamResponse(
        status=200,
        headers={
            "Content-Type": "text/event-stream",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )
    await response.prepare(request)

    try:
        # Send prompt to pi (fire-and-forget, then read events from stdout)
        cmd = {"type": "prompt", "message": message}
        await pi_bridge.send_command(cmd, timeout=5.0)

        # Stream events from pi's stdout
        with open("/proc/1/fd/1", "r") as stdout:
            deadline = time.monotonic() + 300.0
            while time.monotonic() < deadline:
                line = stdout.readline()
                if not line:
                    await asyncio.sleep(0.05)
                    continue
                try:
                    data = json.loads(line.strip())
                    event_type = data.get("type", "")
                    # Forward all events except responses (which we already got)
                    if event_type and event_type != "response":
                        await response.write(f"data: {json.dumps(data)}\n\n".encode())
                    # Stop on agent_end
                    if event_type == "agent_end":
                        break
                except json.JSONDecodeError:
                    continue
    except Exception as exc:
        logger.error("Prompt error: %s", exc)
        await response.write(f"data: {json.dumps({'error': str(exc)})}\n\n".encode())

    await response.write_eof()
    return response


async def handle_abort(request: web.Request) -> web.Response:
    """Abort the current operation."""
    try:
        await pi_bridge.abort()
        return web.json_response({"status": "aborted"}, status=200)
    except Exception as exc:
        return web.json_response({"error": str(exc)}, status=500)


# ── Application ───────────────────────────────────────────────────────────

def create_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/health", handle_health)
    app.router.add_get("/ready", handle_ready)
    app.router.add_get("/api/state", handle_get_state)
    app.router.add_post("/api/prompt", handle_prompt)
    app.router.add_post("/api/abort", handle_abort)
    return app


async def main() -> None:
    logger.info("Starting pi-bridge on %s:%d", HTTP_HOST, HTTP_PORT)
    logger.info("Pi FIFO: %s", PI_FIFO_PATH)

    if not os.path.exists(PI_FIFO_PATH):
        logger.error("Pi FIFO not found at %s — is pi running?", PI_FIFO_PATH)
        sys.exit(1)

    app = create_app()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, HTTP_HOST, HTTP_PORT)
    await site.start()

    logger.info("pi-bridge ready — pi process alive: %s", pi_bridge.is_alive())

    # Keep running
    stop_event = asyncio.Event()
    loop = asyncio.get_event_loop()

    def _shutdown() -> None:
        logger.info("Shutdown signal received")
        stop_event.set()

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, _shutdown)
        except NotImplementedError:
            pass  # Windows

    await stop_event.wait()
    await runner.cleanup()
    logger.info("pi-bridge shut down")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
