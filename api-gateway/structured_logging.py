"""Structured JSON logging for the KubeSynapse API gateway.

Provides ``structured_log()`` — a drop-in replacement for ``logger.info`` etc.
that emits JSON-logfmt lines with standardised fields:

  level, timestamp, component, namespace, agent_name,
  request_id, trace_id, duration_ms, message

Usage:
    from structured_logging import structured_log
    structured_log("info", "Invoke completed", agent_name=agent_name, duration_ms=123.4)
"""

from __future__ import annotations

import contextvars
import json
import logging
import sys
import time
from datetime import UTC, datetime
from typing import Any

# ---------------------------------------------------------------------------
# Request ID context — set by middleware, read by logging filter
# ---------------------------------------------------------------------------

_REQUEST_ID_CTX: contextvars.ContextVar[str] = contextvars.ContextVar("gateway_request_id", default="")


def set_request_id(request_id: str) -> contextvars.Token[str]:
    """Set the current request ID in context. Returns a token for reset."""
    return _REQUEST_ID_CTX.set(request_id)


def get_request_id() -> str:
    """Get the current request ID from context."""
    return _REQUEST_ID_CTX.get()


# ---------------------------------------------------------------------------
# Logging filter — auto-injects request_id into every log record
# ---------------------------------------------------------------------------


class _RequestIdFilter(logging.Filter):
    """Inject the current request_id from context into every log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        rid = _REQUEST_ID_CTX.get()
        if rid:
            record.request_id = rid
        else:
            record.request_id = ""
        return True


_request_id_filter = _RequestIdFilter()


class StructuredFormatter(logging.Formatter):
    """JSON formatter that emits one JSON object per log line."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "level": record.levelname.lower(),
            "timestamp": datetime.now(UTC).isoformat(),
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Attach extra fields passed via `extra=` kwarg
        for key in (
            "component", "namespace", "agent_name", "request_id",
            "trace_id", "duration_ms", "status_code", "route",
        ):
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value

        if record.exc_info and record.exc_info[1]:
            payload["exception"] = str(record.exc_info[1])

        return json.dumps(payload, default=str)


def setup_structured_logging(*, level: int = logging.INFO) -> None:
    """Replace all root handlers with a structured JSON handler."""
    root = logging.getLogger()
    root.setLevel(level)
    # Remove existing handlers
    for handler in list(root.handlers):
        root.removeHandler(handler)
    # Add structured JSON handler
    stream = logging.StreamHandler(sys.stdout)
    stream.setFormatter(StructuredFormatter())
    root.addHandler(stream)


def structured_log(
    level: str,
    message: str,
    *,
    component: str | None = None,
    namespace: str | None = None,
    agent_name: str | None = None,
    request_id: str | None = None,
    trace_id: str | None = None,
    duration_ms: float | None = None,
    status_code: int | None = None,
    route: str | None = None,
    **extra: Any,
) -> None:
    """Emit a structured log entry.

    Fields are attached as structured metadata and appear in the JSON output.
    All kwargs beyond the first two are treated as extra fields.

    Example:
        structured_log("info", "Agent invoked",
            agent_name="my-agent", namespace="default",
            request_id="abc123", duration_ms=234.5)
    """
    logger = logging.getLogger("kubesynapse")
    log_level = getattr(logging, level.upper(), logging.INFO)
    if not logger.isEnabledFor(log_level):
        return

    extra_fields: dict[str, Any] = {}
    if component:
        extra_fields["component"] = component
    if namespace:
        extra_fields["namespace"] = namespace
    if agent_name:
        extra_fields["agent_name"] = agent_name
    if request_id:
        extra_fields["request_id"] = request_id
    if trace_id:
        extra_fields["trace_id"] = trace_id
    if duration_ms is not None:
        extra_fields["duration_ms"] = duration_ms
    if status_code is not None:
        extra_fields["status_code"] = status_code
    if route:
        extra_fields["route"] = route
    extra_fields.update(extra)

    logger.log(log_level, message, extra=extra_fields)
