"""Run Intelligence Layer — Runtime event emitter for operator worker.

Emits structured runtime events to the API gateway's ingestion endpoint:
  POST /api/v1/traces/runtime-events

This complements the existing TraceClient (which sends to /api/traces/batch)
by providing semantic event indexing for the Run Intelligence Layer.

Features:
- Bounded sync queue with background thread batch flushing
- Idempotent event_id generation (UUID v4 + seq)
- Per-execution_id sequence tracking
- Payload sanitization (secrets redacted)
- Graceful shutdown with queue flush
- Non-blocking: failures are logged, never raised to caller
"""
from __future__ import annotations

import logging
import os
import threading
import uuid
from queue import Empty, Queue
from typing import Any

import httpx

logger = logging.getLogger("operator.runtime-events")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_API_GATEWAY_URL = (
    os.getenv("API_GATEWAY_URL")
    or os.getenv("GATEWAY_URL")
    or os.getenv("API_GATEWAY_INTERNAL_URL")
    or ""
).strip().rstrip("/")
_API_GATEWAY_TOKEN = (
    os.getenv("WORKER_TRACE_TOKEN")
    or os.getenv("API_GATEWAY_SHARED_TOKEN")
    or os.getenv("DEFAULT_API_GATEWAY_SHARED_TOKEN")
    or ""
).strip()
_EMIT_ENABLED = bool(_API_GATEWAY_URL and _API_GATEWAY_TOKEN)
_RUNTIME_KIND = "operator-worker"
_AGENT_NAME = os.getenv("TARGET_NAME", "operator-worker").strip() or "operator-worker"
_NAMESPACE = os.getenv("TARGET_NAMESPACE", "default").strip() or "default"

_QUEUE_MAX_SIZE = int(os.getenv("RUNTIME_EVENTS_QUEUE_SIZE", "500"))
_BATCH_MAX_SIZE = int(os.getenv("RUNTIME_EVENTS_BATCH_SIZE", "50"))
_FLUSH_INTERVAL_S = float(os.getenv("RUNTIME_EVENTS_FLUSH_INTERVAL", "2.0"))
_HTTP_TIMEOUT_S = float(os.getenv("RUNTIME_EVENTS_HTTP_TIMEOUT", "10.0"))

_SECRET_KEYS = frozenset({
    "api_key", "secret", "token", "password", "credential",
    "authorization", "bearer", "x-api-key", "x-auth-token",
})

# ---------------------------------------------------------------------------
# Sequence tracker
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
# Event queue
# ---------------------------------------------------------------------------

_queue: Queue[dict[str, Any] | None] = Queue(maxsize=_QUEUE_MAX_SIZE)
_flusher_thread: threading.Thread | None = None
_running = False
_sent = 0
_dropped = 0


def _flush_loop() -> None:
    batch: list[dict[str, Any]] = []

    while _running or batch:
        try:
            event = _queue.get(timeout=_FLUSH_INTERVAL_S)
        except Exception:
            event = None

        if event is not None:
            batch.append(event)

        should_flush = len(batch) >= _BATCH_MAX_SIZE
        if event is None and batch:
            should_flush = True
        if event is None and not _running and batch:
            should_flush = True

        if should_flush:
            _flush_batch(batch)
            batch.clear()


def _flush_batch(batch: list[dict[str, Any]]) -> None:
    global _sent
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
            _sent += len(batch)
        else:
            logger.warning("Runtime event ingestion failed: status=%d", resp.status_code)
    except Exception:
        logger.warning("Runtime event batch send failed", exc_info=True)


def _emit(event: dict[str, Any]) -> None:
    if not _running:
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
        "prompt_text": event.get("prompt_text"),
        "response_text": event.get("response_text"),
        "system_prompt": event.get("system_prompt"),
        "reasoning_text": event.get("reasoning_text"),
    }

    try:
        _queue.put_nowait(runtime_event)
    except Exception:
        global _dropped
        _dropped += 1


def start_emitter() -> None:
    global _running, _flusher_thread
    if _running or not _EMIT_ENABLED:
        return
    _running = True
    _flusher_thread = threading.Thread(target=_flush_loop, daemon=True, name="worker-event-flusher")
    _flusher_thread.start()
    logger.info("Runtime event emitter started → %s", _API_GATEWAY_URL)


def stop_emitter() -> None:
    global _running, _flusher_thread
    _running = False
    thread = _flusher_thread
    if thread is not None:
        try:
            _queue.put_nowait(None)
        except Exception:
            logger.debug("Runtime event flusher wake-up signal dropped", exc_info=True)
        try:
            thread.join(timeout=10)
        except RuntimeError:
            logger.debug("Runtime event flusher thread was never started", exc_info=True)
    flush_queue()
    _flusher_thread = None
    logger.info("Runtime event emitter stopped (sent=%d, dropped=%d)", _sent, _dropped)


def flush_queue() -> None:
    """Drain and send any queued runtime events immediately."""

    batch: list[dict[str, Any]] = []
    while True:
        try:
            event = _queue.get_nowait()
        except Empty:
            break

        if event is None:
            continue
        batch.append(event)
        if len(batch) >= _BATCH_MAX_SIZE:
            _flush_batch(batch)
            batch.clear()

    if batch:
        _flush_batch(batch)


# ---------------------------------------------------------------------------
# Convenience helpers for common event types
# ---------------------------------------------------------------------------

def emit_workflow_started(execution_id: str, **kwargs: Any) -> None:
    _emit({
        "event_type": "run.started",
        "execution_id": execution_id,
        "severity": "info",
        "payload": {
            "workflow_name": kwargs.get("workflow_name"),
            "namespace": kwargs.get("namespace"),
            "run_id": kwargs.get("run_id"),
        },
    })


def emit_workflow_completed(execution_id: str, **kwargs: Any) -> None:
    _emit({
        "event_type": "run.completed",
        "execution_id": execution_id,
        "severity": "info",
        "payload": {
            "status": kwargs.get("status", "completed"),
            "workflow_name": kwargs.get("workflow_name"),
        },
        "total_tokens": kwargs.get("total_tokens"),
        "cost_usd": kwargs.get("cost_usd"),
        "duration_ms": kwargs.get("duration_ms"),
    })


def emit_workflow_error(execution_id: str, **kwargs: Any) -> None:
    _emit({
        "event_type": "run.error",
        "execution_id": execution_id,
        "severity": "error",
        "payload": {
            "error": (kwargs.get("error") or "")[:2048],
            "error_code": kwargs.get("error_code"),
            "workflow_name": kwargs.get("workflow_name"),
        },
    })


def emit_step_started(execution_id: str, **kwargs: Any) -> None:
    _emit({
        "event_type": "step.started",
        "execution_id": execution_id,
        "thread_id": kwargs.get("thread_id"),
        "severity": "info",
        "payload": {
            "step_name": kwargs.get("step_name"),
            "agent_ref": kwargs.get("agent_ref"),
            "attempt": kwargs.get("attempt", 1),
        },
    })


def emit_step_completed(execution_id: str, **kwargs: Any) -> None:
    _emit({
        "event_type": "step.completed",
        "execution_id": execution_id,
        "thread_id": kwargs.get("thread_id"),
        "severity": "info",
        "payload": {
            "step_name": kwargs.get("step_name"),
            "status": kwargs.get("status", "completed"),
        },
        "total_tokens": kwargs.get("total_tokens"),
        "cost_usd": kwargs.get("cost_usd"),
        "duration_ms": kwargs.get("duration_ms"),
    })


def emit_step_failed(execution_id: str, **kwargs: Any) -> None:
    _emit({
        "event_type": "step.failed",
        "execution_id": execution_id,
        "thread_id": kwargs.get("thread_id"),
        "severity": "error",
        "payload": {
            "step_name": kwargs.get("step_name"),
            "error": (kwargs.get("error") or "")[:2048],
            "failure_class": kwargs.get("failure_class"),
        },
        "duration_ms": kwargs.get("duration_ms"),
    })


def emit_agent_call(execution_id: str, **kwargs: Any) -> None:
    status = kwargs.get("status", "started")
    _emit({
        "event_type": f"agent.call.{status}",
        "execution_id": execution_id,
        "thread_id": kwargs.get("thread_id"),
        "severity": "error" if status == "failed" else "info",
        "payload": {
            "caller_agent": kwargs.get("caller_agent"),
            "target_agent": kwargs.get("target_agent"),
            "step_name": kwargs.get("step_name"),
            "status": status,
        },
        "duration_ms": kwargs.get("duration_ms"),
    })


def emit_tool_call(execution_id: str, **kwargs: Any) -> None:
    status = kwargs.get("status", "completed")
    _emit({
        "event_type": f"tool.{status}",
        "execution_id": execution_id,
        "thread_id": kwargs.get("thread_id"),
        "severity": "error" if status == "failed" else "info",
        "payload": {
            "tool_name": kwargs.get("tool_name"),
            "tool_args": kwargs.get("tool_args"),
            "status": status,
            "step_name": kwargs.get("step_name"),
        },
        "duration_ms": kwargs.get("duration_ms"),
    })


def emit_llm_call(execution_id: str, **kwargs: Any) -> None:
    provider_val = kwargs.get("provider")
    finish_reason_val = kwargs.get("finish_reason")
    payload: dict[str, Any] = {
        "model": kwargs.get("model"),
        "step_name": kwargs.get("step_name"),
    }
    if provider_val:
        payload["provider"] = provider_val
    if finish_reason_val:
        payload["finish_reason"] = finish_reason_val

    _emit({
        "event_type": "llm.call",
        "execution_id": execution_id,
        "thread_id": kwargs.get("thread_id"),
        "severity": "info",
        "payload": payload,
        "prompt_tokens": kwargs.get("prompt_tokens"),
        "completion_tokens": kwargs.get("completion_tokens"),
        "cache_read_tokens": kwargs.get("cache_read_tokens"),
        "cache_write_tokens": kwargs.get("cache_write_tokens"),
        "reasoning_tokens": kwargs.get("reasoning_tokens"),
        "total_tokens": kwargs.get("total_tokens"),
        "cost_usd": kwargs.get("cost_usd"),
        "duration_ms": kwargs.get("duration_ms"),
        "prompt_text": kwargs.get("prompt_text"),
        "response_text": kwargs.get("response_text"),
        "system_prompt": kwargs.get("system_prompt"),
        "reasoning_text": kwargs.get("reasoning_text"),
    })
