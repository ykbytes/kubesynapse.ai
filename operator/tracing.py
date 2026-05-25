"""OpenTelemetry tracing skeleton — §7.1 of the road-to-prod plan.

Provides a ``get_tracer()`` helper and ``trace_reconcile()`` context manager that
wraps reconciliation spans.  When ``opentelemetry`` is not installed the module
degrades gracefully — ``get_tracer()`` returns ``None`` and ``trace_reconcile``
becomes a no-op context manager.
"""

from __future__ import annotations

import importlib
import logging
import os
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

logger = logging.getLogger("operator.tracing")

# ---------------------------------------------------------------------------
# Optional OTEL import — graceful degradation when not installed
# ---------------------------------------------------------------------------

try:
    trace = importlib.import_module("opentelemetry.trace")
    Resource = importlib.import_module("opentelemetry.sdk.resources").Resource
    TracerProvider = importlib.import_module("opentelemetry.sdk.trace").TracerProvider
    BatchSpanProcessor = importlib.import_module("opentelemetry.sdk.trace.export").BatchSpanProcessor
    OTLPSpanExporter = importlib.import_module(
        "opentelemetry.exporter.otlp.proto.grpc.trace_exporter"
    ).OTLPSpanExporter
    StatusCode = trace.StatusCode

    _OTEL_AVAILABLE = True
except (ModuleNotFoundError, ImportError, AttributeError):
    _OTEL_AVAILABLE = False
    trace = None
    StatusCode = None

_tracer: Any = None
_initialized = False


def init_tracing(service_name: str = "kubesynapse-operator") -> None:
    """Initialize the global TracerProvider if OTEL is available and configured."""
    global _tracer, _initialized
    if _initialized:
        return
    _initialized = True

    if not _OTEL_AVAILABLE:
        logger.info("OpenTelemetry SDK not installed — tracing disabled.")
        return

    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip()
    if not endpoint:
        logger.info("OTEL_EXPORTER_OTLP_ENDPOINT not set — tracing disabled.")
        return

    resource = Resource.create({"service.name": service_name})  # type: ignore[possibly-undefined]
    provider = TracerProvider(resource=resource)  # type: ignore[possibly-undefined]
    otel_insecure = os.getenv("OTEL_EXPORTER_OTLP_INSECURE", "true").strip().lower() in {"1", "true", "yes"}
    exporter = OTLPSpanExporter(endpoint=endpoint, insecure=otel_insecure)  # type: ignore[possibly-undefined]
    provider.add_span_processor(BatchSpanProcessor(exporter))  # type: ignore[possibly-undefined]
    trace.set_tracer_provider(provider)  # type: ignore[union-attr]
    _tracer = trace.get_tracer(service_name)  # type: ignore[union-attr]
    logger.info("OpenTelemetry tracing initialized (endpoint=%s).", endpoint)


def get_tracer() -> Any:
    """Return the active tracer, or None if tracing is not available."""
    return _tracer


def get_trace_id() -> str | None:
    """Return the current OTEL trace ID as a hex string, or None."""
    if not _OTEL_AVAILABLE or trace is None:
        return None
    span = trace.get_current_span()
    if span is None:
        return None
    ctx = span.get_span_context()
    if ctx is None or not ctx.trace_id:
        return None
    return format(ctx.trace_id, "032x")


@contextmanager
def trace_reconcile(
    action: str,
    *,
    resource_kind: str = "",
    name: str = "",
    namespace: str = "",
    generation: int = 0,
    **extra: Any,
) -> Iterator[Any]:
    """Context manager that creates an OTEL span for a reconciliation operation."""
    if _tracer is None:
        yield None
        return

    attributes: dict[str, str | int] = {
        "k8s.resource.kind": resource_kind,
        "k8s.resource.name": name,
        "k8s.resource.namespace": namespace,
        "k8s.resource.generation": generation,
        "reconcile.action": action,
    }
    for key, value in extra.items():
        if isinstance(value, (str, int)):
            attributes[f"reconcile.{key}"] = value

    with _tracer.start_as_current_span(f"reconcile.{action}", attributes=attributes) as span:
        try:
            yield span
        except Exception as exc:
            if StatusCode is not None:
                span.set_status(StatusCode.ERROR, str(exc))
            span.record_exception(exc)
            raise
