"""WebhookReceiver and WorkflowTrigger reconciler.

Watches the two webhook/event CRDs, validates specs, updates status,
and dispatches workflow Jobs in response to trigger_executions rows
written by the API gateway.

§2.1d of the road-to-prod plan: controller-per-CRD architecture.
"""

from __future__ import annotations

import ipaddress
import logging
from datetime import UTC, datetime
from typing import Any

import kopf
import kubernetes.client  # type: ignore[import-untyped]
from kubernetes.client.rest import ApiException  # type: ignore[import-untyped]
from reconcile import execute_reconcile, inject_conditions, log_operator_event
from services import patch_custom_status
from sqlalchemy import text

logger = logging.getLogger("operator.controllers.webhook")

GROUP = "kubesynapse.ai"
VERSION = "v1alpha1"
WEBHOOK_PLURAL = "webhookreceivers"
TRIGGER_PLURAL = "workflowtriggers"
WORKFLOW_PLURAL = "agentworkflows"

# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _validate_secret_ref(secret_ref: str) -> None:
    """Validate secretRef format: namespace/name#key or name#key."""
    value = str(secret_ref or "").strip()
    if not value:
        raise kopf.PermanentError("spec.secretRef is required and cannot be empty")
    if "#" not in value:
        raise kopf.PermanentError(
            f"spec.secretRef '{value}' must include a #key suffix (format: namespace/name#key or name#key)"
        )


def _validate_cidr(cidr: str) -> None:
    """Validate a single CIDR entry."""
    try:
        ipaddress.ip_network(cidr, strict=False)
    except ValueError as exc:
        raise kopf.PermanentError(f"Invalid CIDR in ipAllowlist: '{cidr}'") from exc


def _validate_webhook_receiver_spec(spec: dict[str, Any]) -> None:
    """Validate WebhookReceiver spec fields."""
    secret_ref = spec.get("secretRef")
    _validate_secret_ref(secret_ref)

    for cidr in spec.get("ipAllowlist") or []:
        _validate_cidr(str(cidr))

    rate_limit = spec.get("rateLimit")
    if rate_limit is not None and int(rate_limit) < 1:
        raise kopf.PermanentError("spec.rateLimit must be at least 1")

    max_payload = spec.get("maxPayloadBytes")
    if max_payload is not None and int(max_payload) < 1:
        raise kopf.PermanentError("spec.maxPayloadBytes must be at least 1")


def _validate_workflow_trigger_spec(spec: dict[str, Any], namespace: str) -> None:
    """Validate WorkflowTrigger spec and resolve workflowRef."""
    source_ref = str(spec.get("sourceRef") or "").strip()
    if not source_ref:
        raise kopf.PermanentError("spec.sourceRef is required")

    source_kind = str(spec.get("sourceKind") or "").strip()
    if source_kind not in {"WebhookReceiver", "AgentEvent"}:
        raise kopf.PermanentError(
            f"spec.sourceKind must be one of: WebhookReceiver, AgentEvent (got '{source_kind}')"
        )

    workflow_ref = spec.get("workflowRef") or {}
    workflow_name = str(workflow_ref.get("name") or "").strip()
    if not workflow_name:
        raise kopf.PermanentError("spec.workflowRef.name is required")

    workflow_namespace = str(workflow_ref.get("namespace") or "").strip() or namespace
    custom_api = kubernetes.client.CustomObjectsApi()
    try:
        custom_api.get_namespaced_custom_object(
            group=GROUP,
            version=VERSION,
            namespace=workflow_namespace,
            plural=WORKFLOW_PLURAL,
            name=workflow_name,
        )
    except ApiException as exc:
        if exc.status == 404:
            raise kopf.PermanentError(
                f"Referenced AgentWorkflow '{workflow_name}' not found in namespace '{workflow_namespace}'"
            ) from exc
        raise

    max_retries = spec.get("maxRetries")
    if max_retries is not None and int(max_retries) < 0:
        raise kopf.PermanentError("spec.maxRetries must be non-negative")

    backoff = spec.get("backoffSeconds")
    if backoff is not None and int(backoff) < 0:
        raise kopf.PermanentError("spec.backoffSeconds must be non-negative")


# ---------------------------------------------------------------------------
# Status helpers
# ---------------------------------------------------------------------------


def _build_webhook_status(phase: str, invocation_count: int | None = None) -> dict[str, Any]:
    status: dict[str, Any] = {
        "phase": phase,
        "lastEvaluated": _now_iso(),
    }
    if phase:
        status["conditions"] = inject_conditions({}, phase).get("conditions", [])
    if invocation_count is not None:
        status["invocationCount"] = invocation_count
    return status


def _build_trigger_status(phase: str, execution_count: int | None = None) -> dict[str, Any]:
    status: dict[str, Any] = {
        "phase": phase,
        "lastEvaluated": _now_iso(),
    }
    if phase:
        status["conditions"] = inject_conditions({}, phase).get("conditions", [])
    if execution_count is not None:
        status["executionCount"] = execution_count
    return status


# ---------------------------------------------------------------------------
# WebhookReceiver handlers
# ---------------------------------------------------------------------------


@kopf.on.create(GROUP, VERSION, WEBHOOK_PLURAL)  # type: ignore[arg-type]
def create_webhook_receiver(
    spec: dict[str, Any],
    name: str,
    namespace: str,
    logger: logging.Logger,
    retry: int = 0,
    **kwargs: Any,
) -> dict[str, Any]:
    del kwargs
    execute_reconcile(
        lambda: (
            _validate_webhook_receiver_spec(spec),
            patch_custom_status(
                WEBHOOK_PLURAL,
                namespace,
                name,
                _build_webhook_status("Active", 0),
            ),
        ),
        logger=logger,
        action="create-webhook-receiver",
        resource_kind="WebhookReceiver",
        name=name,
        namespace=namespace,
        default_delay=5,
        retry=retry,
        start_message="Reconciling WebhookReceiver create event.",
        success_message="WebhookReceiver reconciled successfully.",
    )
    return {"message": f"WebhookReceiver {name} accepted."}


@kopf.on.update(GROUP, VERSION, WEBHOOK_PLURAL)  # type: ignore[arg-type]
def update_webhook_receiver(
    spec: dict[str, Any],
    name: str,
    namespace: str,
    logger: logging.Logger,
    retry: int = 0,
    **kwargs: Any,
) -> dict[str, Any]:
    del kwargs
    execute_reconcile(
        lambda: (
            _validate_webhook_receiver_spec(spec),
            patch_custom_status(
                WEBHOOK_PLURAL,
                namespace,
                name,
                _build_webhook_status("Active"),
            ),
        ),
        logger=logger,
        action="update-webhook-receiver",
        resource_kind="WebhookReceiver",
        name=name,
        namespace=namespace,
        default_delay=5,
        retry=retry,
        start_message="Reconciling WebhookReceiver update event.",
        success_message="WebhookReceiver update reconciled.",
    )
    return {"message": f"WebhookReceiver {name} updated."}


@kopf.on.delete(GROUP, VERSION, WEBHOOK_PLURAL)  # type: ignore[arg-type]
def delete_webhook_receiver(
    name: str, namespace: str, logger: logging.Logger, **kwargs: Any
) -> None:
    del kwargs
    log_operator_event(
        logger,
        logging.INFO,
        "WebhookReceiver deleted.",
        resource_kind="WebhookReceiver",
        name=name,
        namespace=namespace,
        action="delete-webhook-receiver",
    )


# ---------------------------------------------------------------------------
# WorkflowTrigger handlers
# ---------------------------------------------------------------------------


@kopf.on.create(GROUP, VERSION, TRIGGER_PLURAL)  # type: ignore[arg-type]
def create_workflow_trigger(
    spec: dict[str, Any],
    name: str,
    namespace: str,
    logger: logging.Logger,
    retry: int = 0,
    **kwargs: Any,
) -> dict[str, Any]:
    del kwargs
    execute_reconcile(
        lambda: (
            _validate_workflow_trigger_spec(spec, namespace),
            patch_custom_status(
                TRIGGER_PLURAL,
                namespace,
                name,
                _build_trigger_status("Active", 0),
            ),
        ),
        logger=logger,
        action="create-workflow-trigger",
        resource_kind="WorkflowTrigger",
        name=name,
        namespace=namespace,
        default_delay=5,
        retry=retry,
        start_message="Reconciling WorkflowTrigger create event.",
        success_message="WorkflowTrigger reconciled successfully.",
    )
    return {"message": f"WorkflowTrigger {name} accepted."}


@kopf.on.update(GROUP, VERSION, TRIGGER_PLURAL)  # type: ignore[arg-type]
def update_workflow_trigger(
    spec: dict[str, Any],
    name: str,
    namespace: str,
    logger: logging.Logger,
    retry: int = 0,
    **kwargs: Any,
) -> dict[str, Any]:
    del kwargs
    execute_reconcile(
        lambda: (
            _validate_workflow_trigger_spec(spec, namespace),
            patch_custom_status(
                TRIGGER_PLURAL,
                namespace,
                name,
                _build_trigger_status("Active"),
            ),
        ),
        logger=logger,
        action="update-workflow-trigger",
        resource_kind="WorkflowTrigger",
        name=name,
        namespace=namespace,
        default_delay=5,
        retry=retry,
        start_message="Reconciling WorkflowTrigger update event.",
        success_message="WorkflowTrigger update reconciled.",
    )
    return {"message": f"WorkflowTrigger {name} updated."}


@kopf.on.delete(GROUP, VERSION, TRIGGER_PLURAL)  # type: ignore[arg-type]
def delete_workflow_trigger(
    name: str, namespace: str, logger: logging.Logger, **kwargs: Any
) -> None:
    del kwargs
    log_operator_event(
        logger,
        logging.INFO,
        "WorkflowTrigger deleted.",
        resource_kind="WorkflowTrigger",
        name=name,
        namespace=namespace,
        action="delete-workflow-trigger",
    )


# ---------------------------------------------------------------------------
# Dispatch loop — timer on WebhookReceiver
# ---------------------------------------------------------------------------


def _get_db_engine() -> Any:
    """Import the shared SQLAlchemy engine lazily to avoid startup deps."""
    try:
        from state_store import ENGINE

        return ENGINE
    except Exception as exc:
        logger.debug("Database engine not available for webhook dispatch: %s", exc)
        return None


def _fetch_dispatched_executions(limit: int = 50) -> list[dict[str, Any]]:
    """Fetch trigger_executions with status='dispatched' from the shared DB."""
    engine = _get_db_engine()
    if engine is None:
        return []
    try:
        with engine.connect() as conn:
            result = conn.execute(
                text(
                    """
                    SELECT id, trigger_namespace, trigger_name, event_id,
                           workflow_name, workflow_namespace, payload_json, created_at
                    FROM trigger_executions
                    WHERE status = 'dispatched'
                    ORDER BY created_at ASC
                    LIMIT :limit
                    """
                ),
                {"limit": limit},
            )
            return [dict(row) for row in result.mappings()]
    except Exception as exc:
        logger.warning("Failed to fetch dispatched trigger executions: %s", exc)
        return []


def _mark_execution_queued(execution_id: int) -> bool:
    """Atomically mark a trigger execution as queued. Returns True if we won the race."""
    engine = _get_db_engine()
    if engine is None:
        return False
    try:
        with engine.begin() as conn:
            result = conn.execute(
                text(
                    """
                    UPDATE trigger_executions
                    SET status = 'queued', updated_at = NOW(), attempt_count = attempt_count + 1
                    WHERE id = :id AND status = 'dispatched'
                    """
                ),
                {"id": execution_id},
            )
            return int(result.rowcount) > 0
    except Exception as exc:
        logger.warning("Failed to mark execution %d as queued: %s", execution_id, exc)
        return False


def _resolve_workflow_spec(workflow_name: str, workflow_namespace: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Resolve an AgentWorkflow CRD and return (spec, meta)."""
    custom_api = kubernetes.client.CustomObjectsApi()
    workflow = custom_api.get_namespaced_custom_object(
        group=GROUP,
        version=VERSION,
        namespace=workflow_namespace,
        plural=WORKFLOW_PLURAL,
        name=workflow_name,
    )
    return workflow.get("spec", {}), workflow.get("metadata", {})


def _launch_workflow_for_trigger(
    execution: dict[str, Any],
    logger: logging.Logger,
) -> str | None:
    """Launch a workflow job for a trigger execution. Returns job name or None."""
    trigger_namespace = execution.get("trigger_namespace", "default")
    trigger_name = execution.get("trigger_name", "")
    workflow_name = execution.get("workflow_name", "")
    workflow_namespace = execution.get("workflow_namespace") or trigger_namespace

    try:
        workflow_spec, workflow_meta = _resolve_workflow_spec(workflow_name, workflow_namespace)
    except ApiException as exc:
        if exc.status == 404:
            logger.warning(
                "Trigger %s/%s references missing workflow %s/%s; skipping.",
                trigger_namespace,
                trigger_name,
                workflow_namespace,
                workflow_name,
            )
            return None
        raise

    # Import here to avoid circular imports at module load time.
    from controllers.workflow_controller import enqueue_workflow_job

    job_name = enqueue_workflow_job(
        spec=workflow_spec,
        meta=workflow_meta,
        name=workflow_name,
        namespace=workflow_namespace,
        logger=logger,
    )
    return job_name


def _process_trigger_executions(logger: logging.Logger) -> None:
    """Process all dispatched trigger executions and launch workflows."""
    executions = _fetch_dispatched_executions(limit=50)
    if not executions:
        return

    for execution in executions:
        execution_id = execution.get("id")
        if execution_id is None:
            continue

        # Race-safe claim: only one operator replica will successfully update the row.
        if not _mark_execution_queued(execution_id):
            logger.debug("Execution %s was already claimed by another replica; skipping.", execution_id)
            continue

        try:
            job_name = _launch_workflow_for_trigger(execution, logger)
        except Exception as exc:
            logger.warning(
                "Failed to launch workflow for execution %s: %s",
                execution_id,
                exc,
            )
            continue

        if job_name:
            log_operator_event(
                logger,
                logging.INFO,
                "Launched workflow from trigger execution.",
                resource_kind="WorkflowTrigger",
                name=execution.get("trigger_name"),
                namespace=execution.get("trigger_namespace"),
                executionId=execution_id,
                eventId=execution.get("event_id"),
                workflowName=execution.get("workflow_name"),
                workflowNamespace=execution.get("workflow_namespace"),
                jobName=job_name,
            )


@kopf.timer(GROUP, VERSION, WEBHOOK_PLURAL, interval=30)  # type: ignore[arg-type]
def reconcile_webhook_dispatch(logger: logging.Logger, **kwargs: Any) -> None:
    """Periodic reconciliation: dispatch webhook trigger executions to workflow Jobs.

    The timer is attached to WebhookReceiver resources, but the actual work
    scans the shared trigger_executions table so every invocation is handled
    exactly once (race-safe via atomic UPDATE ... WHERE status='dispatched').
    """
    del kwargs
    _process_trigger_executions(logger)
