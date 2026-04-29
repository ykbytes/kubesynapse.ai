"""Pi RPC Client — communicates with pi --mode rpc subprocess.

Implements the JSON-over-stdin/stdout RPC protocol used by pi.
See packages/coding-agent/docs/rpc.md for the full protocol spec.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
from asyncio.subprocess import Process
from collections.abc import AsyncGenerator
from typing import Any, TextIO

from pi_types import (
    EVENT_TYPE_MAP,
    PiRpcCommand,
    PiRpcEvent,
    PiResponse,
)

logger = logging.getLogger("opencode-runtime.pi_client")


class PiRpcError(Exception):
    """Raised when pi RPC communication fails."""


class PiRpcTimeoutError(PiRpcError):
    """Raised when a command times out."""


class PiRpcClient:
    """Async client for pi's RPC mode over stdin/stdout."""

    def __init__(
        self,
        *,
        provider: str | None = None,
        model: str | None = None,
        thinking_level: str | None = None,
        no_session: bool = False,
        session_dir: str | None = None,
        tools: str | None = None,
        no_tools: bool = False,
        system_prompt: str | None = None,
        working_directory: str | None = None,
        extensions: list[str] | None = None,
        env: dict[str, str] | None = None,
    ) -> None:
        self._provider = provider
        self._model = model
        self._thinking_level = thinking_level
        self._no_session = no_session
        self._session_dir = session_dir
        self._tools = tools
        self._no_tools = no_tools
        self._system_prompt = system_prompt
        self._working_directory = working_directory or os.getcwd()
        self._extensions = extensions or []
        self._extra_env = env or {}

        self._process: Process | None = None
        self._command_id_counter = 0
        self._response_futures: dict[str, asyncio.Future[PiResponse]] = {}
        self._event_queue: asyncio.Queue[PiRpcEvent | PiResponse] = asyncio.Queue(maxsize=1000)
        self._reader_task: asyncio.Task[Any] | None = None
        self._running = False

    @property
    def running(self) -> bool:
        return self._running

    def _build_command(self) -> list[str]:
        """Build the pi command line."""
        cmd = ["pi", "--mode", "rpc"]

        if self._no_session:
            cmd.append("--no-session")
        elif self._session_dir:
            cmd.extend(["--session-dir", self._session_dir])

        if self._provider:
            cmd.extend(["--provider", self._provider])

        if self._model:
            cmd.extend(["--model", self._model])

        if self._thinking_level:
            cmd.extend(["--thinking", self._thinking_level])

        if self._no_tools:
            cmd.append("--no-tools")
        elif self._tools:
            cmd.extend(["--tools", self._tools])

        if self._system_prompt:
            cmd.extend(["--append-system-prompt", self._system_prompt])

        for ext in self._extensions:
            cmd.extend(["-e", ext])

        return cmd

    async def start(self) -> None:
        """Launch the pi RPC subprocess."""
        if self._running:
            return

        cmd = self._build_command()
        logger.info("Starting pi RPC: %s", " ".join(cmd))

        env = os.environ.copy()
        env.update(self._extra_env)
        env["NODE_ENV"] = "production"
        env["PI_TELEMETRY"] = "0"

        try:
            self._process = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self._working_directory,
                env=env,
                preexec_fn=os.setsid if hasattr(os, "setsid") else None,
            )
        except FileNotFoundError:
            raise PiRpcError(
                "pi command not found. Is @mariozechner/pi-coding-agent installed?"
            ) from None
        except Exception as exc:
            raise PiRpcError(f"Failed to start pi: {exc}") from exc

        self._running = True
        self._reader_task = asyncio.ensure_future(self._read_stdout_loop())
        asyncio.ensure_future(self._read_stderr_loop())

        # Wait briefly for pi to be ready
        try:
            await asyncio.wait_for(self._send_health_check(), timeout=30.0)
        except asyncio.TimeoutError:
            await self.close()
            raise PiRpcError("pi RPC process did not become ready within 30s")

    async def _send_health_check(self) -> None:
        """Send a get_state command to verify pi is responsive."""
        await self.send_command({"type": "get_state"}, timeout=15.0)

    async def close(self) -> None:
        """Gracefully shut down the pi process."""
        if not self._running:
            return

        logger.info("Shutting down pi RPC client")
        self._running = False

        if self._reader_task:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except asyncio.CancelledError:
                pass

        if self._process and self._process.returncode is None:
            try:
                # Send abort first to stop any in-progress work
                await self.send_command({"type": "abort"}, timeout=5.0)
            except Exception:
                pass

            try:
                self._process.send_signal(signal.SIGTERM)
                await asyncio.wait_for(self._process.wait(), timeout=10.0)
            except asyncio.TimeoutError:
                logger.warning("pi process did not exit on SIGTERM, sending SIGKILL")
                try:
                    self._process.kill()
                    await self._process.wait()
                except Exception:
                    pass
            except ProcessLookupError:
                pass  # Already exited

        self._process = None
        logger.info("pi RPC client shut down")

    def _next_command_id(self) -> str:
        self._command_id_counter += 1
        return f"cmd-{self._command_id_counter}"

    async def send_command(
        self,
        command: dict[str, Any] | PiRpcCommand,
        *,
        timeout: float = 120.0,
    ) -> PiResponse:
        """Send a command to pi and wait for the response."""
        if not self._running or not self._process or not self._process.stdin:
            raise PiRpcError("pi RPC client is not running")

        # Serialize command
        if not isinstance(command, dict):
            command_dict = command.model_dump(by_alias=True, exclude_none=True)
        else:
            command_dict = command

        command_id = command_dict.get("id") or self._next_command_id()
        command_dict["id"] = command_id

        payload = json.dumps(command_dict, ensure_ascii=False) + "\n"
        logger.debug("pi RPC send: %s", command_dict.get("type", "unknown"))

        try:
            self._process.stdin.write(payload.encode("utf-8"))
            await self._process.stdin.drain()
        except (BrokenPipeError, ConnectionResetError) as exc:
            raise PiRpcError(f"pi process closed stdin: {exc}") from exc

        # Wait for response with matching id
        future: asyncio.Future[PiResponse] = asyncio.get_event_loop().create_future()
        self._response_futures[command_id] = future

        try:
            response = await asyncio.wait_for(future, timeout=timeout)
            return response
        except asyncio.TimeoutError:
            self._response_futures.pop(command_id, None)
            raise PiRpcTimeoutError(
                f"Command '{command_dict.get('type')}' timed out after {timeout}s"
            ) from None

    async def send_command_fire_and_forget(
        self, command: dict[str, Any] | PiRpcCommand
    ) -> None:
        """Send a command without waiting for the response."""
        if not self._running or not self._process or not self._process.stdin:
            raise PiRpcError("pi RPC client is not running")

        if not isinstance(command, dict):
            command_dict = command.model_dump(by_alias=True, exclude_none=True)
        else:
            command_dict = command

        if "id" not in command_dict:
            command_dict["id"] = self._next_command_id()

        payload = json.dumps(command_dict, ensure_ascii=False) + "\n"

        try:
            self._process.stdin.write(payload.encode("utf-8"))
            await self._process.stdin.drain()
        except (BrokenPipeError, ConnectionResetError) as exc:
            raise PiRpcError(f"pi process closed stdin: {exc}") from exc

    async def read_events(
        self,
    ) -> AsyncGenerator[PiRpcEvent, None]:
        """Async generator yielding pi RPC events as they arrive."""
        while self._running:
            try:
                event = await asyncio.wait_for(self._event_queue.get(), timeout=1.0)
                yield event
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break

    async def _read_stdout_loop(self) -> None:
        """Read JSONL lines from pi's stdout and dispatch them."""
        if not self._process or not self._process.stdout:
            return

        buffer = b""
        while self._running:
            try:
                chunk = await self._process.stdout.read(4096)
                if not chunk:
                    logger.warning("pi stdout closed unexpectedly")
                    break
                buffer += chunk

                while b"\n" in buffer:
                    line_bytes, buffer = buffer.split(b"\n", 1)
                    line = line_bytes.decode("utf-8", errors="replace").rstrip("\r")
                    if not line.strip():
                        continue
                    await self._dispatch_line(line)

            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("Error reading pi stdout: %s", exc)
                break

        self._running = False
        logger.info("pi stdout reader stopped")

    async def _read_stderr_loop(self) -> None:
        """Read pi's stderr for logging."""
        if not self._process or not self._process.stderr:
            return

        while self._running:
            try:
                line = await self._process.stderr.readline()
                if not line:
                    break
                text = line.decode("utf-8", errors="replace").strip()
                if text:
                    logger.debug("pi stderr: %s", text)
            except asyncio.CancelledError:
                break
            except Exception:
                break

    async def _dispatch_line(self, line: str) -> None:
        """Parse a JSON line from pi and route it appropriately."""
        try:
            data = json.loads(line)
        except json.JSONDecodeError as exc:
            logger.warning("Failed to parse pi stdout line: %s (line: %s)", exc, line[:200])
            return

        msg_type = data.get("type", "")

        # Response to a command
        if msg_type == "response":
            cmd_id = data.get("id", "")
            future = self._response_futures.pop(cmd_id, None)
            if future and not future.done():
                try:
                    response = PiResponse(**data)
                    future.set_result(response)
                except Exception as exc:
                    future.set_exception(exc)
            return

        # Event
        model_class = EVENT_TYPE_MAP.get(msg_type)
        if model_class is not None:
            try:
                event = model_class(**data)
                try:
                    self._event_queue.put_nowait(event)
                except asyncio.QueueFull:
                    logger.warning("pi event queue full, dropping event: %s", msg_type)
            except Exception as exc:
                logger.debug("Failed to parse pi event '%s': %s", msg_type, exc)
        else:
            logger.debug("Unknown pi event type: %s", msg_type)
