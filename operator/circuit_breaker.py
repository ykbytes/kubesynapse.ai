"""Circuit breaker for Kubernetes API calls — §7.2 of the road-to-prod plan.

Provides a ``CircuitBreaker`` class that tracks consecutive failures and opens
after a threshold, preventing cascading overload against an unhealthy K8s API.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

logger = logging.getLogger("operator.circuit_breaker")


class CircuitBreaker:
    """Three-state circuit breaker: CLOSED → OPEN → HALF_OPEN.

    When *closed* all calls pass through. After *failure_threshold*
    consecutive failures the breaker *opens* and subsequent calls fail fast
    with ``CircuitBreakerOpen``. After *recovery_timeout* seconds the breaker
    transitions to *half_open*: the next call is allowed as a probe. If it
    succeeds the breaker closes again; otherwise it re-opens.
    """

    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
        half_open_max_calls: int = 1,
    ) -> None:
        self.name = name
        self.failure_threshold = max(failure_threshold, 1)
        self.recovery_timeout = max(recovery_timeout, 1.0)
        self.half_open_max_calls = max(half_open_max_calls, 1)

        self._state = "closed"
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time: float = 0.0
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # State queries
    # ------------------------------------------------------------------

    def is_open(self) -> bool:
        with self._lock:
            if self._state == "open":
                if time.time() - self._last_failure_time >= self.recovery_timeout:
                    self._state = "half_open"
                    self._success_count = 0
                    logger.info("Circuit breaker '%s' entering half_open.", self.name)
                    return False
                return True
            return False

    def state(self) -> str:
        with self._lock:
            return self._state

    # ------------------------------------------------------------------
    # Result recording
    # ------------------------------------------------------------------

    def record_success(self) -> None:
        with self._lock:
            if self._state == "half_open":
                self._success_count += 1
                if self._success_count >= self.half_open_max_calls:
                    self._state = "closed"
                    self._failure_count = 0
                    logger.info("Circuit breaker '%s' closed after recovery probe.", self.name)
            elif self._state == "closed":
                self._failure_count = 0

    def record_failure(self) -> None:
        with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.time()
            if self._state == "half_open":
                self._state = "open"
                logger.warning(
                    "Circuit breaker '%s' re-opened after half-open probe failure (%d/%d).",
                    self.name,
                    self._failure_count,
                    self.failure_threshold,
                )
            elif self._state == "closed" and self._failure_count >= self.failure_threshold:
                self._state = "open"
                logger.warning(
                    "Circuit breaker '%s' opened after %d consecutive failures.",
                    self.name,
                    self._failure_count,
                )

    # ------------------------------------------------------------------
    # Context-manager / decorator interface
    # ------------------------------------------------------------------

    def __call__(self, func: Any) -> Any:
        """Decorator that wraps a function in the circuit breaker."""

        def wrapper(*args: Any, **kwargs: Any) -> Any:
            self.call()
            try:
                result = func(*args, **kwargs)
                self.record_success()
                return result
            except Exception:
                self.record_failure()
                raise

        return wrapper

    def call(self) -> None:
        """Fail fast if the breaker is open."""
        if self.is_open():
            raise CircuitBreakerOpen(
                f"Circuit breaker '{self.name}' is OPEN — K8s API call rejected."
            )


class CircuitBreakerOpen(RuntimeError):
    """Raised when a call is made while the circuit breaker is open."""


# ---------------------------------------------------------------------------
# Singleton breakers for the K8s service layer
# ---------------------------------------------------------------------------

_k8s_circuit_breaker: CircuitBreaker | None = None


def get_k8s_circuit_breaker() -> CircuitBreaker:
    """Return the shared K8s API circuit breaker."""
    global _k8s_circuit_breaker
    if _k8s_circuit_breaker is None:
        _k8s_circuit_breaker = CircuitBreaker(
            name="k8s-api",
            failure_threshold=5,
            recovery_timeout=30.0,
        )
    return _k8s_circuit_breaker
