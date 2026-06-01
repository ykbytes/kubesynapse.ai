"""Run Intelligence Layer — Runtime event emitter.

Emits structured runtime events to the API gateway's ingestion endpoint:
  POST /api/v1/traces/runtime-events

Features:
- Bounded async queue with batch flushing (max 50 events, 2s interval)
- Idempotent event_id generation (UUID v4 + seq)
- Per-execution_id sequence tracking
- Payload sanitization (secrets, full prompts redacted)
- Graceful shutdown with queue flush
- Non-blocking: failures are logged, never raised to caller
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
import time
import uuid
from collections.abc import Callable
from queue import Queue
from typing import Any

import httpx

logger = logging.getLogger("opencode-runtime.events")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_API_GATEWAY_URL = os.getenv("API_GATEWAY_INTERNAL_URL", "").strip().rstrip("/")
_API_GATEWAY_TOKEN = os.getenv("API_GATEWAY_SHARED_TOKEN", "").strip()
_EMIT_ENABLED = bool(_API_GATEWAY_URL and _API_GATEWAY_TOKEN)
_RUNTIME_KIND = "opencode"
_AGENT_NAME = os.getenv("AGENT_NAME", "opencode-agent").strip() or "opencode-agent"
_NAMESPACE = os.getenv("AGENT_NAMESPACE", "default").strip() or "default"

_QUEUE_MAX_SIZE = int(os.getenv("RUNTIME_EVENTS_QUEUE_SIZE", "500"))
_BATCH_MAX_SIZE = int(os.getenv("RUNTIME_EVENTS_BATCH_SIZE", "50"))
_FLUSH_INTERVAL_S = float(os.getenv("RUNTIME_EVENTS_FLUSH_INTERVAL", "2.0"))
_MAX_RETRIES = int(os.getenv("RUNTIME_EVENTS_MAX_RETRIES", "3"))
_HTTP_TIMEOUT_S = float(os.getenv("RUNTIME_EVENTS_HTTP_TIMEOUT", "10.0"))

# Secret patterns to redact from payloads
_SECRET_KEYS = frozenset({
    "api_key", "secret", "token", "password", "credential",
    "authorization", "bearer", "x-api-key", "x-auth-token",
})

# ---------------------------------------------------------------------------
# Sequence tracker (thread-safe)
# ---------------------------------------------------------------------------

_seq_lock = threading.Lock()
_sequences: dict[str, int] = {}


def _next_seq(execution_id: str) -> int:
    with _seq_lock:
        seq = _sequences.get(execution_id, 0) + 1
        _sequences[execution_id] = seq
        return seq


# ---------------------------------------------------------------------------
# Payload sanitization
# ---------------------------------------------------------------------------

def _sanitize_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Redact secrets and truncate large fields."""
    result = {}
    for key, value in payload.items():
        key_lower = key.lower()
        if any(sk in key_lower for sk in _SECRET_KEYS):
            result[key] = "[REDACTED]"
        elif isinstance(value, str) and len(value) > 4096:
            result[key] = value[:4096] + "...[truncated]"
        elif isinstance(value, dict):
            result[key] = _sanitize_payload(value)
        else:
            result[key] = value
    return result


# ---------------------------------------------------------------------------
# Sync event queue (for sync invoke path)
# ---------------------------------------------------------------------------

_sync_queue: Queue[dict[str, Any] | None] = Queue(maxsize=_QUEUE_MAX_SIZE)
_sync_flusher_thread: threading.Thread | None = None
_sync_running = False
_sync_sent = 0
_sync_dropped = 0


def _sync_flush_loop() -> None:
    """Background thread that flushes sync queue to API gateway."""
    global _sync_sent, _sync_dropped
    batch: list[dict[str, Any]] = []

    while _sync_running or batch:
        try:
            event = _sync_queue.get(timeout=_FLUSH_INTERVAL_S)
        except Exception:
            event = None

        if event is not None:
            batch.append(event)

        should_flush = len(batch) >= _BATCH_MAX_SIZE
        if event is None and batch:
            should_flush = True
        if event is None and not _sync_running and batch:
            should_flush = True

        if should_flush:
            _sync_flush_batch(batch)
            batch.clear()


def _sync_emit(event: dict[str, Any]) -> None:
    """Queue event from sync code (non-blocking)."""
    if not _sync_running:
        return
    execution_id = event.get("execution_id", "")
    seq = _next_seq(execution_id)

    runtime_event = {
        "id": f"rre-{uuid.uuid4().hex[:16]}",
        "event_id": f"{execution_id}-{seq}",
        "execution_id": execution_id,
        "session_id": event.get("session_id"),
        "thread_id": event.get("thread_id"),
        "namespace": event.get("namespace", _NAMESPACE),
        "agent_name": event.get("agent_name", _AGENT_NAME),
        "runtime_kind": _RUNTIME_KIND,
        "event_type": event.get("event_type", "custom"),
        "seq": seq,
        "severity": event.get("severity", "info"),
        "payload": _sanitize_payload(event.get("payload", {})),
        "duration_ms": event.get("duration_ms"),
        "prompt_tokens": event.get("prompt_tokens"),
        "completion_tokens": event.get("completion_tokens"),
        "total_tokens": event.get("total_tokens"),
        "cost_usd": event.get("cost_usd"),
        "cache_read_tokens": event.get("cache_read_tokens"),
        "cache_write_tokens": event.get("cache_write_tokens"),
        "reasoning_tokens": event.get("reasoning_tokens"),
    }

    try:
        _sync_queue.put_nowait(runtime_event)
    except Exception:
        global _sync_dropped
        _sync_dropped += 1


def _sync_flush_batch(batch: list[dict[str, Any]]) -> None:
    """Send a batch of events to the API gateway. Used by both the background flusher and explicit flush."""
    global _sync_sent, _sync_dropped
    if not batch:
        return
    try:
        resp = httpx.post(
            f"{_API_GATEWAY_URL}/api/v1/traces/runtime-events",
            json={"events": batch},
            headers={
                "Authorization": f"Bearer {_API_GATEWAY_TOKEN}",
                "Content-Type": "application/json",
            },
            timeout=_HTTP_TIMEOUT_S,
        )
        if resp.status_code in (200, 201):
            _sync_sent += len(batch)
        else:
            logger.warning("Runtime event ingestion failed: status=%d", resp.status_code)
    except Exception:
        logger.warning("Runtime event batch send failed", exc_info=True)


def start_sync_emitter() -> None:
    global _sync_running, _sync_flusher_thread
    if _sync_running or not _EMIT_ENABLED:
        return
    _sync_running = True
    _sync_flusher_thread = threading.Thread(target=_sync_flush_loop, daemon=True, name="runtime-event-flusher-sync")
    _sync_flusher_thread.start()
    logger.info("Runtime event emitter (sync) started → %s", _API_GATEWAY_URL)


def stop_sync_emitter() -> None:
    global _sync_running
    if not _sync_running:
        return
    _sync_running = False
    _sync_queue.put(None)
    if _sync_flusher_thread:
        _sync_flusher_thread.join(timeout=10)
    logger.info("Runtime event emitter (sync) stopped (sent=%d, dropped=%d)", _sync_sent, _sync_dropped)


def flush_sync_queue() -> None:
    """Drain and send all queued sync events immediately.

    Called after each invoke to ensure observability data reaches the
    gateway promptly rather than waiting for the batch threshold or
    process shutdown.
    """
    batch: list[dict[str, Any]] = []
    while True:
        try:
            event = _sync_queue.get_nowait()
        except Exception:
            break
        if event is not None:
            batch.append(event)
    if batch:
        _sync_flush_batch(batch)


# ---------------------------------------------------------------------------
# Async event emitter (for streaming path)
# ---------------------------------------------------------------------------

class RuntimeEventEmitter:
    """Async event emitter with bounded queue and batch flush."""

    def __init__(self) -> None:
        self._queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue(maxsize=_QUEUE_MAX_SIZE)
        self._task: asyncio.Task[None] | None = None
        self._running = False
        self._dropped = 0
        self._sent = 0

    async def start(self) -> None:
        if self._running or not _EMIT_ENABLED:
            return
        self._running = True
        self._task = asyncio.create_task(self._flush_loop(), name="runtime-event-flusher")
        logger.info(
            "Runtime event emitter started → %s/api/v1/traces/runtime-events",
            _API_GATEWAY_URL,
        )

    async def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        await self._queue.put(None)
        if self._task:
            try:
                await asyncio.wait_for(self._task, timeout=10.0)
            except asyncio.TimeoutError:
                self._task.cancel()
        logger.info(
            "Runtime event emitter stopped (sent=%d, dropped=%d)",
            self._sent,
            self._dropped,
        )

    async def emit(self, event: dict[str, Any]) -> None:
        """Queue a single event for batch ingestion."""
        if not self._running:
            return

        execution_id = event.get("execution_id", "")
        seq = _next_seq(execution_id)

        runtime_event = {
            "id": f"rre-{uuid.uuid4().hex[:16]}",
            "event_id": f"{execution_id}-{seq}",
            "execution_id": execution_id,
            "session_id": event.get("session_id"),
            "thread_id": event.get("thread_id"),
            "namespace": event.get("namespace", _NAMESPACE),
            "agent_name": event.get("agent_name", _AGENT_NAME),
            "runtime_kind": _RUNTIME_KIND,
            "event_type": event.get("event_type", "custom"),
            "seq": seq,
            "severity": event.get("severity", "info"),
            "payload": _sanitize_payload(event.get("payload", {})),
            "duration_ms": event.get("duration_ms"),
            "prompt_tokens": event.get("prompt_tokens"),
            "completion_tokens": event.get("completion_tokens"),
            "total_tokens": event.get("total_tokens"),
            "cost_usd": event.get("cost_usd"),
        }

        try:
            self._queue.put_nowait(runtime_event)
        except asyncio.QueueFull:
            self._dropped += 1
            logger.warning("Runtime event queue full, dropping event (type=%s)", runtime_event["event_type"])

    async def _flush_loop(self) -> None:
        batch: list[dict[str, Any]] = []

        while self._running or batch:
            try:
                event = await asyncio.wait_for(self._queue.get(), timeout=_FLUSH_INTERVAL_S)
            except asyncio.TimeoutError:
                event = None

            if event is not None:
                batch.append(event)

            should_flush = len(batch) >= _BATCH_MAX_SIZE
            if event is None and batch:
                should_flush = True
            if event is None and not self._running and batch:
                should_flush = True

            if should_flush:
                await self._send_batch(batch)
                batch.clear()

    async def _send_batch(self, batch: list[dict[str, Any]]) -> None:
        if not batch:
            return

        try:
            async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT_S) as client:
                resp = await client.post(
                    f"{_API_GATEWAY_URL}/api/v1/traces/runtime-events",
                    json={"events": batch},
                    headers={
                        "Authorization": f"Bearer {_API_GATEWAY_TOKEN}",
                        "Content-Type": "application/json",
                    },
                )
                if resp.status_code in (200, 201):
                    self._sent += len(batch)
                    logger.debug("Sent %d runtime events (status=%d)", len(batch), resp.status_code)
                else:
                    logger.warning(
                        "Runtime event ingestion failed: status=%d, body=%s",
                        resp.status_code,
                        resp.text[:512],
                    )
        except Exception:
            logger.warning("Runtime event batch send failed", exc_info=True)


# ---------------------------------------------------------------------------
# Global singleton
# ---------------------------------------------------------------------------

EMITTER = RuntimeEventEmitter()


# ---------------------------------------------------------------------------
# Convenience helpers for common event types (sync)
# ---------------------------------------------------------------------------

def emit_run_started(
    execution_id: str,
    session_id: str | None = None,
    thread_id: str | None = None,
    model: str | None = None,
) -> None:
    _sync_emit({
        "event_type": "run.started",
        "execution_id": execution_id,
        "session_id": session_id,
        "thread_id": thread_id,
        "severity": "info",
        "payload": {"model": model},
    })


def emit_run_completed(
    execution_id: str,
    session_id: str | None = None,
    thread_id: str | None = None,
    status: str = "completed",
    total_tokens: int = 0,
    cost_usd: float = 0.0,
    duration_ms: int = 0,
    finish_reason: str | None = None,
) -> None:
    _sync_emit({
        "event_type": "run.completed",
        "execution_id": execution_id,
        "session_id": session_id,
        "thread_id": thread_id,
        "severity": "info",
        "payload": {"status": status, "finish_reason": finish_reason},
        "total_tokens": total_tokens,
        "cost_usd": cost_usd,
        "duration_ms": duration_ms,
    })


def emit_run_error(
    execution_id: str,
    session_id: str | None = None,
    thread_id: str | None = None,
    error: str = "",
    error_code: str | None = None,
) -> None:
    _sync_emit({
        "event_type": "run.error",
        "execution_id": execution_id,
        "session_id": session_id,
        "thread_id": thread_id,
        "severity": "error",
        "payload": {"error": error[:2048], "error_code": error_code},
    })


def emit_tool_call(
    execution_id: str,
    tool_name: str,
    tool_args: dict[str, Any] | None = None,
    status: str = "started",
    duration_ms: int | None = None,
    session_id: str | None = None,
    thread_id: str | None = None,
) -> None:
    _sync_emit({
        "event_type": f"tool.{status}",
        "execution_id": execution_id,
        "session_id": session_id,
        "thread_id": thread_id,
        "severity": "error" if status == "failed" else "info",
        "payload": {"tool_name": tool_name, "tool_args": tool_args, "status": status},
        "duration_ms": duration_ms,
    })


def emit_llm_call(
    execution_id: str,
    model: str | None = None,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
    reasoning_tokens: int = 0,
    total_tokens: int = 0,
    cost_usd: float = 0.0,
    duration_ms: int | None = None,
    session_id: str | None = None,
    thread_id: str | None = None,
) -> None:
    _sync_emit({
        "event_type": "llm.call",
        "execution_id": execution_id,
        "session_id": session_id,
        "thread_id": thread_id,
        "severity": "info",
        "payload": {"model": model},
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "cache_read_tokens": cache_read_tokens,
        "cache_write_tokens": cache_write_tokens,
        "reasoning_tokens": reasoning_tokens,
        "total_tokens": total_tokens,
        "cost_usd": cost_usd,
        "duration_ms": duration_ms,
    })


def emit_agent_call(
    execution_id: str,
    caller_agent: str,
    target_agent: str,
    status: str = "started",
    duration_ms: int | None = None,
    session_id: str | None = None,
    thread_id: str | None = None,
) -> None:
    _sync_emit({
        "event_type": f"agent.call.{status}",
        "execution_id": execution_id,
        "session_id": session_id,
        "thread_id": thread_id,
        "severity": "error" if status == "failed" else "info",
        "payload": {"caller_agent": caller_agent, "target_agent": target_agent, "status": status},
        "duration_ms": duration_ms,
    })


def emit_question_asked(
    execution_id: str,
    question: str,
    options: list[str] | None = None,
    session_id: str | None = None,
    thread_id: str | None = None,
) -> None:
    _sync_emit({
        "event_type": "human.question",
        "execution_id": execution_id,
        "session_id": session_id,
        "thread_id": thread_id,
        "severity": "info",
        "payload": {"question": question[:1024], "options": options},
    })


def emit_todo_updated(
    execution_id: str,
    todos: list[dict[str, Any]] | None = None,
    session_id: str | None = None,
    thread_id: str | None = None,
) -> None:
    _sync_emit({
        "event_type": "todo.updated",
        "execution_id": execution_id,
        "session_id": session_id,
        "thread_id": thread_id,
        "severity": "info",
        "payload": {"todo_count": len(todos) if todos else 0},
    })
