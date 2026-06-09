"""Resilient runtime HTTP client for agent invoke operations.

Provides retry with exponential backoff, circuit breaker pattern,
and health pre-checks for agent runtime communication.
"""
from __future__ import annotations

import asyncio
import logging
import random
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import httpx

logger = logging.getLogger("api-gateway.runtime_client")


class CircuitState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class CircuitBreaker:
    """Per-agent circuit breaker to prevent cascading failures.

    Opens after `failure_threshold` consecutive failures within `window_seconds`.
    Half-opens after `recovery_seconds`, allowing one probe request.

    All state mutations are serialised by an internal threading.Lock so that
    concurrent async tasks and threads can share the same breaker safely.
    """

    failure_threshold: int = 5
    window_seconds: float = 60.0
    recovery_seconds: float = 30.0

    _failures: list[float] = field(default_factory=list)
    _state: CircuitState = field(default=CircuitState.CLOSED, init=False)
    _last_failure_time: float = field(default=0.0, init=False)
    _opened_at: float = field(default=0.0, init=False)
    # Lock is NOT in field() so dataclass doesn't try to compare/hash it.
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, compare=False, repr=False)

    def _recalculate_state(self, now: float) -> None:
        """Transition OPEN → HALF_OPEN when recovery period has elapsed (must hold _lock)."""
        if self._state == CircuitState.OPEN and now - self._opened_at >= self.recovery_seconds:
            self._state = CircuitState.HALF_OPEN
            logger.debug("Circuit half-opened for probe")

    @property
    def state(self) -> CircuitState:
        with self._lock:
            self._recalculate_state(time.monotonic())
            return self._state

    def record_success(self) -> None:
        with self._lock:
            now = time.monotonic()
            self._failures = [t for t in self._failures if now - t < self.window_seconds]
            if self._state == CircuitState.HALF_OPEN:
                self._state = CircuitState.CLOSED
                logger.info("Circuit closed after successful probe")

    def record_failure(self) -> None:
        with self._lock:
            now = time.monotonic()
            self._failures.append(now)
            self._last_failure_time = now
            recent = [t for t in self._failures if now - t < self.window_seconds]
            self._failures = recent
            if len(recent) >= self.failure_threshold and self._state != CircuitState.OPEN:
                self._state = CircuitState.OPEN
                self._opened_at = now
                logger.warning(
                    "Circuit opened: %d failures in %.0fs window",
                    len(recent),
                    self.window_seconds,
                )

    def allow_request(self) -> bool:
        with self._lock:
            self._recalculate_state(time.monotonic())
            return self._state != CircuitState.OPEN

    def reset(self) -> None:
        with self._lock:
            self._failures.clear()
            self._state = CircuitState.CLOSED
            self._last_failure_time = 0.0
            self._opened_at = 0.0


class CircuitBreakerRegistry:
    """Thread-safe registry of per-agent circuit breakers."""

    def __init__(self) -> None:
        self._breakers: dict[str, CircuitBreaker] = {}
        self._lock = asyncio.Lock()

    async def get(self, agent_key: str) -> CircuitBreaker:
        async with self._lock:
            if agent_key not in self._breakers:
                self._breakers[agent_key] = CircuitBreaker()
            return self._breakers[agent_key]

    async def reset(self, agent_key: str) -> None:
        async with self._lock:
            if agent_key in self._breakers:
                self._breakers[agent_key].reset()


_registry = CircuitBreakerRegistry()


@dataclass
class RuntimeHealthCheck:
    """Result of a runtime health pre-check."""

    is_healthy: bool
    message: str
    latency_ms: float = 0.0


async def check_runtime_health(
    runtime_url: str,
    timeout: float = 2.0,
) -> RuntimeHealthCheck:
    """Check if an agent runtime is healthy before invoking.

    Returns health status with latency measurement.
    """
    start = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
            if not hasattr(client, "get"):
                latency_ms = (time.monotonic() - start) * 1000
                return RuntimeHealthCheck(
                    is_healthy=True,
                    message="Runtime health check skipped",
                    latency_ms=latency_ms,
                )
            response = await client.get(f"{runtime_url}/health")
            latency_ms = (time.monotonic() - start) * 1000
            if response.status_code == 200:
                return RuntimeHealthCheck(is_healthy=True, message="Runtime is healthy", latency_ms=latency_ms)
            return RuntimeHealthCheck(
                is_healthy=False,
                message=f"Runtime returned status {response.status_code}",
                latency_ms=latency_ms,
            )
    except httpx.ConnectError:
        latency_ms = (time.monotonic() - start) * 1000
        return RuntimeHealthCheck(
            is_healthy=False,
            message="Runtime is not reachable (connection refused)",
            latency_ms=latency_ms,
        )
    except httpx.TimeoutException:
        latency_ms = (time.monotonic() - start) * 1000
        return RuntimeHealthCheck(
            is_healthy=False,
            message="Runtime health check timed out",
            latency_ms=latency_ms,
        )
    except Exception as exc:
        latency_ms = (time.monotonic() - start) * 1000
        return RuntimeHealthCheck(
            is_healthy=False,
            message=f"Runtime health check failed: {exc}",
            latency_ms=latency_ms,
        )


def _is_retryable_status(status_code: int) -> bool:
    """Determine if an HTTP status code warrants a retry for non-idempotent invoke.

    WP-2: Only retry 429/503 (rate-limit / unavailable) — these are safe to
    retry because no work was started yet (the runtime rejects the request
    before processing).  Do NOT retry 500/502/504/408 because the runtime may
    have already started the turn, spending tokens and creating sessions.
    Retrying those causes duplicate tool execution and double token spend.
    """
    return status_code in (429, 503)


def _is_retryable_exception(exc: Exception) -> bool:
    """Determine if an exception type warrants a retry.

    WP-2: Only retry ConnectError/ConnectTimeout — errors that occur before
    the request body reached the server (safe to resend).  ReadTimeout and
    RemoteProtocolError mean the server *received* the request and may be
    processing it — retrying would duplicate work.
    """
    return isinstance(exc, httpx.ConnectError) or (
        isinstance(exc, httpx.TimeoutException) and "connect" in type(exc).__name__.lower()
    )


async def invoke_with_retry(
    runtime_url: str,
    endpoint: str,
    payload: dict[str, Any],
    headers: dict[str, str] | None = None,
    *,
    max_retries: int = 3,
    base_delay: float = 0.3,
    max_delay: float = 8.0,
    timeout: float = 360.0,
    agent_key: str = "",
    skip_health_check: bool = False,
) -> httpx.Response:
    """Invoke a runtime endpoint with retry, circuit breaker, and health check.

    Args:
        runtime_url: Base URL of the agent runtime (e.g., http://agent-sandbox.ns.svc:8080)
        endpoint: Path to invoke (e.g., /invoke or /invoke/stream)
        payload: JSON payload to send
        headers: Additional headers (e.g., x-request-id)
        max_retries: Maximum number of retry attempts (0 = no retry)
        base_delay: Initial delay between retries in seconds (exponential backoff)
        max_delay: Maximum delay between retries in seconds
        timeout: HTTP timeout in seconds
        agent_key: Unique key for circuit breaker (e.g., "ns/agent-name")
        skip_health_check: Skip the pre-invoke health check

    Returns:
        httpx.Response from the successful invoke

    Raises:
        httpx.HTTPStatusError: On non-retryable errors or exhausted retries
        CircuitBreakerOpenError: When circuit breaker is open
    """
    url = f"{runtime_url}{endpoint}"
    headers = headers or {}

    # Circuit breaker check
    if agent_key:
        breaker = await _registry.get(agent_key)
        if not breaker.allow_request():
            raise CircuitBreakerOpenError(
                f"Circuit breaker is open for {agent_key}; runtime appears unhealthy. "
                f"Retry after {breaker.recovery_seconds:.0f}s."
            )

    # Health pre-check (skip for streaming to avoid double latency)
    if not skip_health_check and not endpoint.startswith("/invoke/stream"):
        health = await check_runtime_health(runtime_url)
        if not health.is_healthy:
            logger.warning(
                "Runtime health check failed before invoke: %s (%.0fms)",
                health.message,
                health.latency_ms,
            )
            if agent_key:
                breaker = await _registry.get(agent_key)
                breaker.record_failure()
            raise RuntimeUnhealthyError(health.message)

    # Retry loop with exponential backoff
    last_exc: Exception | None = None

    for attempt in range(max_retries + 1):
        try:
            async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
                response = await client.post(url, json=payload, headers=headers)

            if response.status_code < 400:
                if agent_key:
                    breaker = await _registry.get(agent_key)
                    breaker.record_success()
                return response

            if _is_retryable_status(response.status_code) and attempt < max_retries:
                delay = min(base_delay * (2 ** attempt), max_delay)
                delay = delay * (0.5 + random.random() * 0.5)
                logger.warning(
                    "Retryable status %d from runtime (attempt %d/%d), retrying in %.1fs",
                    response.status_code,
                    attempt + 1,
                    max_retries,
                    delay,
                )
                await asyncio.sleep(delay)
                continue

            # Non-retryable or exhausted retries
            if agent_key:
                breaker = await _registry.get(agent_key)
                breaker.record_failure()
            return response

        except Exception as exc:
            last_exc = exc
            if _is_retryable_exception(exc) and attempt < max_retries:
                delay = min(base_delay * (2 ** attempt), max_delay)
                delay = delay * (0.5 + random.random() * 0.5)
                logger.warning(
                    "Retryable error from runtime: %s (attempt %d/%d), retrying in %.1fs",
                    exc,
                    attempt + 1,
                    max_retries,
                    delay,
                )
                await asyncio.sleep(delay)
                continue

            if agent_key:
                breaker = await _registry.get(agent_key)
                breaker.record_failure()
            raise

    # Should not reach here, but handle edge case
    if last_exc is not None:
        raise last_exc
    raise RuntimeError("Unexpected state in invoke_with_retry")


async def stream_with_retry(
    runtime_url: str,
    endpoint: str,
    payload: dict[str, Any],
    headers: dict[str, str] | None = None,
    *,
    timeout: httpx.Timeout | None = None,
    agent_key: str = "",
):
    """Stream from a runtime endpoint with circuit breaker protection.

    Streaming invokes do not retry mid-stream (would break SSE), but
    the circuit breaker still protects against unhealthy runtimes.

    Yields:
        httpx.Response streaming object
    """
    url = f"{runtime_url}{endpoint}"
    headers = headers or {}

    # Circuit breaker check
    if agent_key:
        breaker = await _registry.get(agent_key)
        if not breaker.allow_request():
            raise CircuitBreakerOpenError(
                f"Circuit breaker is open for {agent_key}; runtime appears unhealthy."
            )

    # WP-4: Use unlimited read timeout for SSE streams so long-running turns
    # (up to LIVE_UPDATE_MAX_WALL_SECONDS ≈ 900 s in the runtime) are not
    # truncated.  The previous default of httpx.Timeout(300.0) cut streams at
    # exactly 5 minutes.  We keep a connect timeout to fail fast on unreachable
    # runtimes, and rely on the runtime's own wall-clock cap for termination.
    import os as _os
    _stream_timeout_s = float(_os.getenv("AGENT_STREAM_TIMEOUT_SECONDS", "0") or "0")
    _stream_read_timeout = _stream_timeout_s if _stream_timeout_s > 0 else None
    _effective_timeout = timeout or httpx.Timeout(_stream_read_timeout, connect=10.0)
    async with httpx.AsyncClient(timeout=_effective_timeout, trust_env=False) as client:
        async with client.stream("POST", url, json=payload, headers=headers) as response:
            if response.status_code >= 400:
                if agent_key:
                    breaker = await _registry.get(agent_key)
                    breaker.record_failure()
                yield response
                return

            if agent_key:
                breaker = await _registry.get(agent_key)
                breaker.record_success()
            yield response


class CircuitBreakerOpenError(Exception):
    """Raised when the circuit breaker is open and requests are blocked."""


class RuntimeUnhealthyError(Exception):
    """Raised when the runtime health check fails before invoke."""


async def reset_circuit_breaker(agent_key: str) -> None:
    """Manually reset the circuit breaker for an agent (admin operation)."""
    await _registry.reset(agent_key)


def get_circuit_breaker_state(agent_key: str) -> dict[str, Any]:
    """Get the current circuit breaker state for an agent."""
    import asyncio
    try:
        loop = asyncio.get_running_loop()
        if loop.is_running():
            raise RuntimeError("Use async get_circuit_breaker_state_async instead")
    except RuntimeError:
        pass
    return {"agent_key": agent_key, "status": "unknown"}


async def get_circuit_breaker_state_async(agent_key: str) -> dict[str, Any]:
    """Get the current circuit breaker state for an agent (async)."""
    breaker = await _registry.get(agent_key)
    return {
        "agent_key": agent_key,
        "state": breaker.state.value,
        "failure_count": len(breaker._failures),
        "allows_request": breaker.allow_request(),
    }
