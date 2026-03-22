"""Operator entrypoint — configures logging, K8s auth, and imports controllers.

All Kopf handlers are registered via the ``controllers`` package import.
"""

from __future__ import annotations

import logging
import os
import signal

from state_store import init_database as init_state_database
import kopf

import kubernetes.config  # type: ignore[import-untyped]

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

from config import (  # noqa: E402 — after logging setup
    EVAL_SCHEDULE_POLL_SECONDS,
    OPERATOR_NAMESPACE,
    OPERATOR_PEERING_NAME,
    SECRET_PROVISIONING_MODE,
    WORKER_IMAGE,
    WORKFLOW_POLL_SECONDS,
)
from reconcile import log_operator_event  # noqa: E402
from tracing import init_tracing  # noqa: E402

# Import the controllers package — Kopf handler registration happens at import time.
import controllers  # noqa: E402,F401


@kopf.on.startup()
def configure(settings: kopf.OperatorSettings, **_) -> None:
    """Ensure K8s client is authenticated when the operator starts."""
    settings.persistence.finalizer = "sandbox.enterprise.ai/finalizer"
    settings.peering.name = OPERATOR_PEERING_NAME
    try:
        kubernetes.config.load_incluster_config()
        logger.info("Loaded in-cluster Kubernetes config.")
    except kubernetes.config.ConfigException:
        kubernetes.config.load_kube_config()
        logger.info("Loaded local kubeconfig file.")
    init_state_database()
    init_tracing("kubemininions-operator")
    log_operator_event(
        logger,
        logging.INFO,
        "Operator startup configuration loaded.",
        action="startup",
        operatorNamespace=OPERATOR_NAMESPACE,
        peering=OPERATOR_PEERING_NAME,
        secretProvisioningMode=SECRET_PROVISIONING_MODE,
        workflowPollSeconds=WORKFLOW_POLL_SECONDS,
        evalSchedulePollSeconds=EVAL_SCHEDULE_POLL_SECONDS,
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
    """Drain in-flight reconciliations on operator shutdown."""
    global _shutting_down  # noqa: PLW0603
    _shutting_down = True
    log_operator_event(
        logger,
        logging.INFO,
        "Operator cleanup initiated — draining in-flight reconciliations.",
        action="cleanup",
    )


def _sigterm_handler(signum: int, _frame: object) -> None:
    """Mark operator as shutting down on SIGTERM."""
    global _shutting_down  # noqa: PLW0603
    _shutting_down = True
    logger.info("Received signal %s — graceful shutdown initiated.", signum)


signal.signal(signal.SIGTERM, _sigterm_handler)


