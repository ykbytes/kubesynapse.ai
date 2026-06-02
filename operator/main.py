"""Operator entrypoint — configures logging, K8s auth, and imports controllers.

All Kopf handlers are registered via the ``controllers`` package import.
"""

from __future__ import annotations

import logging
import os
import signal
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import kopf
import kubernetes.config  # type: ignore[import-untyped]

from state_store import init_database as init_state_database

try:
    from pythonjsonlogger import jsonlogger as _jsonlogger  # type: ignore[import-untyped]
except ModuleNotFoundError:  # pragma: no cover
    _jsonlogger = None


def _configure_logging() -> None:
    log_level = os.getenv("OPERATOR_LOG_LEVEL", "INFO").upper()
    handler = logging.StreamHandler()
    if os.getenv("JSON_LOGS", "true").lower() in {"1", "true"} and _jsonlogger is not None:
        handler.setFormatter(_jsonlogger.JsonFormatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    else:
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
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
# §7.2 — Readiness server for operator probes
# ---------------------------------------------------------------------------

_READINESS_PORT = int(os.getenv("OPERATOR_READINESS_PORT", "8081"))


def _render_prometheus_metrics() -> str:
    return (
        "# HELP KUBESYNAPSE_operator_reconcile_total Total reconciliation operations\n"
        "# TYPE KUBESYNAPSE_operator_reconcile_total counter\n"
        f"KUBESYNAPSE_operator_reconcile_total 0\n"
        "# HELP KUBESYNAPSE_operator_reconcile_errors Total reconciliation errors\n"
        "# TYPE KUBESYNAPSE_operator_reconcile_errors counter\n"
        f"KUBESYNAPSE_operator_reconcile_errors 0\n"
        "# HELP KUBESYNAPSE_operator_reconcile_latency_sum Sum of reconciliation latency (ms)\n"
        "# TYPE KUBESYNAPSE_operator_reconcile_latency_sum counter\n"
        f"KUBESYNAPSE_operator_reconcile_latency_sum 0.0\n"
    )


def _start_readiness_server() -> None:
    try:
        with HTTPServer(("0.0.0.0", _READINESS_PORT), _ReadinessHandler) as httpd:
            logger.info("Operator readiness server listening on :%d", _READINESS_PORT)
            httpd.serve_forever()
    except Exception as exc:
        logger.warning("Readiness server failed: %s", exc)


threading.Thread(target=_start_readiness_server, daemon=True, name="readiness-server").start()


# ---------------------------------------------------------------------------
# Startup / shutdown hooks
# ---------------------------------------------------------------------------

@kopf.on.startup()
def configure(settings: kopf.OperatorSettings, **_) -> None:
    """Ensure K8s client is authenticated when the operator starts."""
    settings.persistence.finalizer = "kubesynapse.ai/finalizer"
    settings.peering.name = OPERATOR_PEERING_NAME
    # §7.1 — Leader election: 30s lease duration
    settings.peering.lifetime = 30
    settings.peering.standby_delay = 15
    _load_kubernetes_config()
    init_state_database()
    init_tracing("kubesynapse-operator")

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
