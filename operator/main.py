"""Operator entrypoint — configures logging, K8s auth, and imports controllers.

All Kopf handlers are registered via the ``controllers`` package import.
Features:
- Graceful shutdown on SIGTERM/SIGINT
- Health check HTTP endpoint
- Request context propagation
- Structured error logging
"""

from __future__ import annotations

import contextvars
import http.server
import json
import logging
import os
import signal
import socketserver
import sys
import threading
from typing import Any

import kopf
import kubernetes.config  # type: ignore[import-untyped]

from state_store import init_database as init_state_database

try:
    from pythonjsonlogger import jsonlogger as _jsonlogger  # type: ignore[import-untyped]
except ModuleNotFoundError:  # pragma: no cover
    _jsonlogger = None


# Context variable for request tracing
REQUEST_ID = contextvars.ContextVar("request_id", default="")
OPERATOR_STATE = {"shutdown_requested": False, "ready": False}


class StructuredFormatter(logging.Formatter):
    """Add request_id to all log records."""

    def format(self, record: logging.LogRecord) -> str:
        record.request_id = REQUEST_ID.get() or "-"
        return super().format(record)


def _configure_logging() -> None:
    log_level = os.getenv("OPERATOR_LOG_LEVEL", "INFO").upper()
    handler = logging.StreamHandler()
    
    if os.getenv("JSON_LOGS", "true").lower() in {"1", "true"} and _jsonlogger is not None:
        fmt = "%(asctime)s %(levelname)s %(name)s %(request_id)s %(message)s"
        handler.setFormatter(_jsonlogger.JsonFormatter(fmt))
    else:
        fmt = "%(asctime)s %(levelname)s %(name)s [%(request_id)s] %(message)s"
        formatter = StructuredFormatter(fmt)
        handler.setFormatter(formatter)
    
    logging.basicConfig(level=log_level, handlers=[handler], force=True)


_configure_logging()
logger = logging.getLogger("operator")


def _load_kubernetes_config() -> None:
    """Load in-cluster config when available, otherwise fall back to kubeconfig."""
    load_incluster_config = getattr(kubernetes.config, "load_incluster_config", None)
    load_kube_config = getattr(kubernetes.config, "load_kube_config", None)
    config_exception = getattr(kubernetes.config, "ConfigException", Exception)

    if load_incluster_config is None and load_kube_config is None:
        logger.warning("Kubernetes config loaders are unavailable; skipping client initialization.")
        return

    try:
        if load_incluster_config is None:
            raise config_exception()
        load_incluster_config()
        logger.info("Loaded in-cluster Kubernetes config.")
    except config_exception:
        if load_kube_config is None:
            logger.warning(
                "In-cluster config unavailable and kubeconfig loader missing; skipping client initialization."
            )
            return
        try:
            load_kube_config()
            logger.info("Loaded local kubeconfig file.")
        except config_exception:
            logger.warning("No Kubernetes configuration found (in-cluster or kubeconfig).")


from config import (  # noqa: E402 — after logging setup
    OPERATOR_NAMESPACE,
    OPERATOR_PEERING_NAME,
    SECRET_PROVISIONING_MODE,
    WORKER_IMAGE,
    WORKFLOW_POLL_SECONDS,
)
from reconcile import log_operator_event  # noqa: E402
from tracing import init_tracing  # noqa: E402

# Controllers perform CRD existence checks at import time, so K8s auth must be
# configured before importing the package.
_load_kubernetes_config()

# Import the controllers package — Kopf handler registration happens at import time.
import controllers  # noqa: E402,F401


# ---------------------------------------------------------------------------
# Health check HTTP server (§7.3 — Observability)
# ---------------------------------------------------------------------------

class HealthCheckHandler(http.server.SimpleHTTPRequestHandler):
    """Minimal health check endpoint for Kubernetes probes."""

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/healthz":
            response = {"status": "ok", "ready": OPERATOR_STATE["ready"]}
            self.send_response(200 if OPERATOR_STATE["ready"] else 503)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(response).encode())
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format: str, *args: Any) -> None:  # type: ignore[override]
        """Suppress default HTTP logging."""
        pass


def _start_health_check_server() -> threading.Thread:
    """Start health check HTTP server on a dedicated port (8081)."""
    port = int(os.getenv("OPERATOR_HEALTH_PORT", "8081"))
    server = socketserver.TCPServer(("0.0.0.0", port), HealthCheckHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    logger.info("Health check server listening on port %d", port)
    return thread


def _handle_shutdown_signal(signum: int, frame: Any) -> None:  # type: ignore[no-untyped-def]
    """Handle SIGTERM/SIGINT gracefully."""
    OPERATOR_STATE["shutdown_requested"] = True
    logger.info("Shutdown signal received (sig=%d)", signum)


# ---------------------------------------------------------------------------
# Startup / shutdown hooks
# ---------------------------------------------------------------------------

@kopf.on.startup()
def configure(settings: kopf.OperatorSettings, **_) -> None:
    """Ensure K8s client is authenticated when the operator starts."""
    logger.info("Operator startup: version=%s", os.getenv("OPERATOR_VERSION", "unknown"))

    # Graceful shutdown handlers (only available on main thread)
    try:
        if threading.current_thread() is threading.main_thread():
            signal.signal(signal.SIGTERM, _handle_shutdown_signal)
            signal.signal(signal.SIGINT, _handle_shutdown_signal)
        else:
            logger.info("Skipping signal handlers: not on main thread")
    except ValueError as exc:
        logger.warning("Skipping signal handlers: %s", exc)

    # Health check server
    _start_health_check_server()

    # Kopf configuration
    settings.persistence.finalizer = "kubesynapse.ai/finalizer"
    settings.peering.name = OPERATOR_PEERING_NAME
    # §7.1 — Leader election: 30s lease duration
    settings.peering.lifetime = 30
    settings.peering.standby_delay = 15
    settings.posting.strategy = "permanent"  # Never lose resource event logs
    
    _load_kubernetes_config()
    init_state_database()
    init_tracing("kubesynapse-operator")
    
    # Mark operator ready after all init completes
    OPERATOR_STATE["ready"] = True
    logger.info("Operator ready for reconciliation")

    # §S6-1 — Migrate existing DB MCP connections to CRD resources
    try:
        from controllers.mcp_connection_controller import _migrate_db_connections_to_crds

        _migrate_db_connections_to_crds(logger)
    except Exception as exc:
        logger.info("McpConnection migration skipped or failed: %s", exc)
    log_operator_event(
        logger,
        logging.INFO,
        "Operator startup configuration loaded.",
        action="startup",
        operatorNamespace=OPERATOR_NAMESPACE,
        peering=OPERATOR_PEERING_NAME,
        secretProvisioningMode=SECRET_PROVISIONING_MODE,
        workflowPollSeconds=WORKFLOW_POLL_SECONDS,
        workerImage=WORKER_IMAGE,
    )


# ---------------------------------------------------------------------------
# §7.2 — Graceful shutdown
# ---------------------------------------------------------------------------

_shutting_down = False


def is_shutting_down() -> bool:
    """Return True once the operator is draining."""
    return _shutting_down


@kopf.on.cleanup()  # type: ignore[arg-type]
async def cleanup(logger: logging.Logger, **_kwargs: object) -> None:
    """Mark operator as shutting down."""
    global _shutting_down
    _shutting_down = True
    log_operator_event(
        logger,
        logging.INFO,
        "Operator cleanup initiated — graceful shutdown.",
        action="cleanup",
    )
    log_operator_event(
        logger,
        logging.INFO,
        "Operator cleanup complete.",
        action="cleanup",
    )


def _sigterm_handler(signum: int, _frame: object) -> None:
    """Mark operator as shutting down on SIGTERM."""
    global _shutting_down
    _shutting_down = True
    logger.info("Received signal %s — graceful shutdown initiated.", signum)


signal.signal(signal.SIGTERM, _sigterm_handler)
