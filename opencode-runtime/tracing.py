"""§7.1 — OpenTelemetry tracing helpers (graceful degradation)."""
from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger("opencode-runtime")

_OTEL_AVAILABLE = False
try:
    from opentelemetry import trace  # type: ignore[import-untyped]
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter  # type: ignore[import-untyped]
    from opentelemetry.sdk.resources import Resource  # type: ignore[import-untyped]
    from opentelemetry.sdk.trace import TracerProvider  # type: ignore[import-untyped]
    from opentelemetry.sdk.trace.export import BatchSpanProcessor  # type: ignore[import-untyped]
    from opentelemetry.trace import StatusCode  # type: ignore[import-untyped]
    _OTEL_AVAILABLE = True
except ImportError:
    StatusCode = None  # type: ignore[assignment,misc]

_tracer: Any = None


def init_tracing(service_name: str = "opencode-runtime") -> None:
    """Initialise OTEL tracing if the SDK is installed and OTEL endpoint is set."""
    global _tracer
    if not _OTEL_AVAILABLE:
        logger.info("OpenTelemetry SDK not installed; tracing disabled.")
        return
    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip()
    if not endpoint:
        logger.info("OTEL_EXPORTER_OTLP_ENDPOINT not set; tracing disabled.")
        return
    resource = Resource.create({"service.name": service_name})  # type: ignore[possibly-undefined]
    provider = TracerProvider(resource=resource)  # type: ignore[possibly-undefined]
    exporter = OTLPSpanExporter(endpoint=endpoint, insecure=True)  # type: ignore[possibly-undefined]
    provider.add_span_processor(BatchSpanProcessor(exporter))  # type: ignore[possibly-undefined]
    trace.set_tracer_provider(provider)  # type: ignore[possibly-undefined]
    _tracer = trace.get_tracer(service_name)  # type: ignore[possibly-undefined]
    logger.info("OpenTelemetry tracing initialised for %s → %s", service_name, endpoint)


def get_tracer() -> Any:
    """Return the OTEL tracer, or None if tracing is disabled."""
    return _tracer
