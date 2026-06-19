"""HTTP trace reporter that streams workflow execution events to the api-gateway.

Design goals:
- Fire-and-forget: tracing must never block or crash workflow execution.
- Batched: accumulate events in memory and flush asynchronously.
- Thread-safe: worker uses ThreadPoolExecutor for parallel steps.
- Graceful degradation: if the gateway is unreachable, drop events after a warning.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from typing import Any

import httpx

logger = logging.getLogger("operator.trace-client")


class TraceClient:
    """Batched, asynchronous HTTP client for execution observability.

    Mirrors the high-level API of ``api-gateway/trace_store.ExecutionTracer`` but
    reports over HTTP instead of writing to a local database.
    """

    def __init__(
        self,
        *,
        gateway_url: str,
        token: str | None = None,
        batch_size: int = 50,
        flush_interval_sec: int = 5,
        enabled: bool = True,
    ) -> None:
        self._gateway_url = gateway_url.rstrip("/")
        self._token = token
        self._batch_size = max(batch_size, 1)
        self._flush_interval_sec = max(flush_interval_sec, 1)
        self._enabled = enabled
        self._buffer: list[dict[str, Any]] = []
        self._lock = threading.Lock()
        self._shutdown_event = threading.Event()
        self._timer_thread: threading.Thread | None = None

        if self._enabled:
            self._timer_thread = threading.Thread(target=self._timer_loop, daemon=True)
            self._timer_thread.start()

    # ------------------------------------------------------------------
    # Public API (mirrors ExecutionTracer)
    # ------------------------------------------------------------------

    def start_execution(
        self,
        namespace: str,
        workflow_name: str,
        agent_name: str,
        run_id: str,
        inputs: dict[str, Any] | None = None,
        triggered_by: str | None = None,
    ) -> str:
        execution_id = f"exec-{uuid.uuid4().hex[:16]}"
        self._append_event(
            event_type="execution_started",
            execution_id=execution_id,
            payload={
                "namespace": namespace,
                "workflow_name": workflow_name,
                "agent_name": agent_name,
                "run_id": run_id,
                "inputs": inputs,
                "triggered_by": triggered_by,
            },
        )
        return execution_id

    def end_execution(
        self,
        execution_id: str,
        status: str,
        outputs: dict[str, Any] | None = None,
        error_message: str | None = None,
        metrics: dict[str, Any] | None = None,
    ) -> None:
        self._append_event(
            event_type="execution_completed" if status == "completed" else "execution_failed",
            execution_id=execution_id,
            payload={
                "status": status,
                "outputs": outputs,
                "error": error_message,
                "metrics": metrics,
            },
        )
        self.flush()

    def start_step(
        self,
        execution_id: str,
        step_name: str,
        step_type: str | None = None,
        step_index: int | None = None,
        parent_step_id: str | None = None,
        inputs: dict[str, Any] | None = None,
    ) -> str:
        step_id = f"step-{uuid.uuid4().hex[:12]}"
        payload: dict[str, Any] = {
            "step_name": step_name,
            "step_type": step_type,
            "parent_step_id": parent_step_id,
            "inputs": inputs,
        }
        if step_index is not None:
            payload["step_index"] = step_index
        self._append_event(
            event_type="step_started",
            execution_id=execution_id,
            step_id=step_id,
            payload=payload,
        )
        return step_id

    def end_step(
        self,
        execution_id: str,
        step_id: str,
        status: str,
        outputs: dict[str, Any] | None = None,
        error_message: str | None = None,
    ) -> None:
        event_type = {
            "completed": "step_completed",
            "failed": "step_failed",
            "skipped": "step_skipped",
            "cancelled": "step_skipped",
        }.get(status, "step_completed")
        self._append_event(
            event_type=event_type,
            execution_id=execution_id,
            step_id=step_id,
            payload={
                "status": status,
                "outputs": outputs,
                "error": error_message,
            },
        )

    def record_llm_call(
        self,
        execution_id: str,
        step_id: str,
        model: str,
        prompt: str,
        response: str,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        cache_read_tokens: int = 0,
        cache_write_tokens: int = 0,
        reasoning_tokens: int = 0,
        cost_usd: float | None = None,
        latency_ms: float | None = None,
        provider: str | None = None,
        reasoning_text: str = "",
        finish_reason: str = "",
    ) -> None:
        self._append_event(
            event_type="llm_call_completed",
            execution_id=execution_id,
            step_id=step_id,
            payload={
                "model": model,
                "provider": provider,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "cache_read_tokens": cache_read_tokens,
                "cache_write_tokens": cache_write_tokens,
                "reasoning_tokens": reasoning_tokens,
                "cost_usd": cost_usd,
                "latency_ms": latency_ms,
                "prompt_preview": prompt[:1024],
                "response_preview": response[:2048],
                "reasoning_text": reasoning_text,
                "finish_reason": finish_reason,
            },
        )

    def record_tool_call(
        self,
        execution_id: str,
        step_id: str,
        tool_name: str,
        tool_args: dict[str, Any],
        tool_result: dict[str, Any] | None = None,
        error_message: str | None = None,
        duration_ms: float | None = None,
    ) -> None:
        self._append_event(
            event_type="tool_call_completed" if not error_message else "tool_call_failed",
            execution_id=execution_id,
            step_id=step_id,
            payload={
                "tool_name": tool_name,
                "tool_args": tool_args,
                "tool_result": tool_result,
                "error": error_message,
                "duration_ms": duration_ms,
            },
        )

    def record_event(
        self,
        execution_id: str,
        event_type: str,
        step_id: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        self._append_event(
            event_type=event_type,
            execution_id=execution_id,
            step_id=step_id,
            payload=payload,
        )

    def flush(self) -> None:
        if not self._enabled:
            return
        with self._lock:
            batch = self._buffer[:]
            self._buffer = []
        if not batch:
            return
        self._post_batch(batch)

    def stop(self) -> None:
        self._shutdown_event.set()
        if self._timer_thread is not None:
            self._timer_thread.join(timeout=2.0)
        self.flush()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _append_event(
        self,
        event_type: str,
        execution_id: str,
        step_id: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        if not self._enabled:
            return
        event: dict[str, Any] = {
            "event_type": event_type,
            "execution_id": execution_id,
            "step_id": step_id,
            "timestamp": time.time(),
            "payload": payload or {},
        }
        with self._lock:
            self._buffer.append(event)
            should_flush = len(self._buffer) >= self._batch_size
        if should_flush:
            self.flush()

    def _post_batch(self, batch: list[dict[str, Any]]) -> None:
        url = f"{self._gateway_url}/api/v1/traces/batch"
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        try:
            with httpx.Client(timeout=10.0) as client:
                response = client.post(url, json={"events": batch}, headers=headers)
            if response.status_code >= 400:
                logger.warning(
                    "Trace batch rejected by gateway (%s): %s",
                    response.status_code,
                    response.text[:200],
                )
        except Exception as exc:
            logger.warning("Trace batch failed to reach gateway: %s", exc)

    def _timer_loop(self) -> None:
        while not self._shutdown_event.wait(timeout=self._flush_interval_sec):
            self.flush()
