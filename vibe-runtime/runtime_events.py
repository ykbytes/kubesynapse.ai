"""Run Intelligence Layer — Runtime event emitter for vibe-runtime.

Emits structured runtime events to the API gateway's ingestion endpoint:
  POST /api/v1/traces/runtime-events

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
from queue import Queue
from typing import Any

import httpx

logger = logging.getLogger("vibe-runtime.events")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_API_GATEWAY_URL = os.getenv("API_GATEWAY_INTERNAL_URL", "").strip().rstrip("/")
_API_GATEWAY_TOKEN = os.getenv("API_GATEWAY_SHARED_TOKEN", "").strip()
_EMIT_ENABLED = bool(_API_GATEWAY_URL and _API_GATEWAY_TOKEN)
_RUNTIME_KIND = "mistral-vibe"
_AGENT_NAME = (os.getenv("AGENT_NAME") or os.getenv("KUBESYNAPSE_AGENT_NAME") or "mistral-vibe-agent").strip() or "mistral-vibe-agent"
_NAMESPACE = (os.getenv("AGENT_NAMESPACE") or os.getenv("KUBESYNAPSE_NAMESPACE") or "default").strip() or "default"

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
    global _sent, _dropped
    batch: list[dict[str, Any]] = []

    while _running or batch:
        try:
            event = _queue.get(timeout=_FLUSH_INTERVAL_S)
        except Exception:
            event = None

        if event is not None:
            batch.append(event)

        if len(batch) >= _BATCH_MAX_SIZE or (event is None and not _running and batch):
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
            batch.clear()


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
    _flusher_thread = threading.Thread(target=_flush_loop, daemon=True, name="vibe-event-flusher")
    _flusher_thread.start()
    logger.info("Runtime event emitter started → %s", _API_GATEWAY_URL)


def stop_emitter() -> None:
    global _running
    if not _running:
        return
    _running = False
    _queue.put(None)
    if _flusher_thread:
        _flusher_thread.join(timeout=10)
    logger.info("Runtime event emitter stopped (sent=%d, dropped=%d)", _sent, _dropped)


def emit_run_started(execution_id: str, **kwargs: Any) -> None:
    _emit({
        "event_type": "run.started",
        "execution_id": execution_id,
        "thread_id": kwargs.get("thread_id"),
        "session_id": kwargs.get("session_id"),
        "severity": "info",
        "payload": {"model": kwargs.get("model")},
    })


def emit_run_completed(execution_id: str, **kwargs: Any) -> None:
    _emit({
        "event_type": "run.completed",
        "execution_id": execution_id,
        "thread_id": kwargs.get("thread_id"),
        "session_id": kwargs.get("session_id"),
        "severity": "info",
        "payload": {"status": kwargs.get("status", "completed"), "finish_reason": kwargs.get("finish_reason")},
        "total_tokens": kwargs.get("total_tokens"),
        "cost_usd": kwargs.get("cost_usd"),
        "duration_ms": kwargs.get("duration_ms"),
    })


def emit_run_error(execution_id: str, **kwargs: Any) -> None:
    _emit({
        "event_type": "run.error",
        "execution_id": execution_id,
        "thread_id": kwargs.get("thread_id"),
        "session_id": kwargs.get("session_id"),
        "severity": "error",
        "payload": {"error": (kwargs.get("error") or "")[:2048], "error_code": kwargs.get("error_code")},
    })


def emit_tool_call(execution_id: str, **kwargs: Any) -> None:
    status = kwargs.get("status", "started")
    _emit({
        "event_type": f"tool.{status}",
        "execution_id": execution_id,
        "thread_id": kwargs.get("thread_id"),
        "session_id": kwargs.get("session_id"),
        "severity": "error" if status == "failed" else "info",
        "payload": {"tool_name": kwargs.get("tool_name"), "tool_args": kwargs.get("tool_args"), "status": status},
        "duration_ms": kwargs.get("duration_ms"),
    })


def emit_llm_call(execution_id: str, **kwargs: Any) -> None:
    _emit({
        "event_type": "llm.call",
        "execution_id": execution_id,
        "thread_id": kwargs.get("thread_id"),
        "session_id": kwargs.get("session_id"),
        "severity": "info",
        "payload": {"model": kwargs.get("model")},
        "prompt_tokens": kwargs.get("prompt_tokens"),
        "completion_tokens": kwargs.get("completion_tokens"),
        "total_tokens": kwargs.get("total_tokens"),
        "cost_usd": kwargs.get("cost_usd"),
        "duration_ms": kwargs.get("duration_ms"),
    })
