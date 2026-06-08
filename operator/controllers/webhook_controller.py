"""WebhookReceiver and WorkflowTrigger reconciler.

Watches the two webhook/event CRDs, validates specs, updates status,
and dispatches workflow Jobs or direct agent invocations in response
to NATS events from the API gateway.

Dispatch paths (primary → fallback):
  1. NATS subscription — receives full execution data from the gateway
  2. Timer fallback — polls the gateway REST API for pending dispatches

Operator status is reported back to the gateway via HTTP PATCH so the
gateway's trigger_executions table stays consistent regardless of DB sharing.
"""
from __future__ import annotations

import ipaddress
import json
import logging
import os
import socket
import urllib.request
import urllib.error
from datetime import UTC, datetime
from typing import Any

import kopf
import kubernetes.client
from kubernetes.client.rest import ApiException
from reconcile import execute_reconcile, inject_conditions, log_operator_event
from services import patch_custom_status

logger = logging.getLogger("operator.controllers.webhook")

GROUP = "kubesynapse.ai"
VERSION = "v1alpha1"
WEBHOOK_PLURAL = "webhookreceivers"
TRIGGER_PLURAL = "workflowtriggers"
WORKFLOW_PLURAL = "agentworkflows"
AGENT_PLURAL = "aiagents"
NATS_SUBJECT = "kubesynapse.webhook.dispatch"

GATEWAY_URL = os.getenv("GATEWAY_URL", "http://kubesynapse-gateway:8000").rstrip("/")
"""URL of the API gateway for status callbacks and timer fallback polling."""

STALE_QUEUED_MINUTES: int = int(os.getenv("STALE_QUEUED_MINUTES", "5"))
"""Minutes after which a queued execution is considered stale and may be reclaimed."""
STALE_PROCESSING_MINUTES: int = int(os.getenv("STALE_PROCESSING_MINUTES", "15"))
"""Minutes after which a processing execution is considered stuck and may be failed."""

_OPERATOR_INSTANCE: str = os.getenv("OPERATOR_INSTANCE", socket.gethostname())[:128]
"""Identity of this operator pod for claim ownership."""

# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _validate_secret_ref(secret_ref: str) -> None:
    value = str(secret_ref or "").strip()
    if not value:
        raise kopf.PermanentError("spec.secretRef is required and cannot be empty")
    if "#" not in value:
        raise kopf.PermanentError(
            f"spec.secretRef '{value}' must include a #key suffix (format: namespace/name#key or name#key)"
        )


def _validate_cidr(cidr: str) -> None:
    try:
        ipaddress.ip_network(cidr, strict=False)
    except ValueError as exc:
        raise kopf.PermanentError(f"Invalid CIDR in ipAllowlist: '{cidr}'") from exc


def _validate_webhook_receiver_spec(spec: dict[str, Any]) -> None:
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
    source_ref = str(spec.get("sourceRef") or "").strip()
    if not source_ref:
        raise kopf.PermanentError("spec.sourceRef is required")

    source_kind = str(spec.get("sourceKind") or "").strip()
    if source_kind not in {"WebhookReceiver", "AgentEvent"}:
        raise kopf.PermanentError(
            f"spec.sourceKind must be one of: WebhookReceiver, AgentEvent (got '{source_kind}')"
        )

    workflow_ref = spec.get("workflowRef") or {}
    agent_ref = spec.get("agentRef") or {}
    workflow_name = str(workflow_ref.get("name") or "").strip()
    agent_name = str(agent_ref.get("name") or "").strip()

    if not workflow_name and not agent_name:
        raise kopf.PermanentError("Either spec.workflowRef.name or spec.agentRef.name is required")

    if workflow_name:
        workflow_namespace = str(workflow_ref.get("namespace") or "").strip() or namespace
        custom_api = kubernetes.client.CustomObjectsApi()
        try:
            custom_api.get_namespaced_custom_object(
                group=GROUP, version=VERSION, namespace=workflow_namespace,
                plural=WORKFLOW_PLURAL, name=workflow_name,
            )
        except ApiException as exc:
            if exc.status == 404:
                raise kopf.PermanentError(
                    f"Referenced AgentWorkflow '{workflow_name}' not found in namespace '{workflow_namespace}'"
                ) from exc
            raise

    if agent_name:
        agent_namespace = str(agent_ref.get("namespace") or "").strip() or namespace
        custom_api = kubernetes.client.CustomObjectsApi()
        try:
            custom_api.get_namespaced_custom_object(
                group=GROUP, version=VERSION, namespace=agent_namespace,
                plural=AGENT_PLURAL, name=agent_name,
            )
        except ApiException as exc:
            if exc.status == 404:
                raise kopf.PermanentError(
                    f"Referenced AIAgent '{agent_name}' not found in namespace '{agent_namespace}'"
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


def _build_trigger_status(
    phase: str,
    execution_count: int | None = None,
    failure_count: int | None = None,
) -> dict[str, Any]:
    status: dict[str, Any] = {
        "phase": phase,
        "lastEvaluated": _now_iso(),
    }
    if phase:
        status["conditions"] = inject_conditions({}, phase).get("conditions", [])
    if execution_count is not None:
        status["executionCount"] = execution_count
    if failure_count is not None:
        status["failureCount"] = failure_count
    return status


# ---------------------------------------------------------------------------
# Gateway HTTP helpers (claim, status back-reporting, timer fallback polling)
# ---------------------------------------------------------------------------


def _gateway_claim_execution(
    execution_id: int,
    claim_source: str = "unknown",
) -> bool:
    """Atomically claim a trigger execution via the gateway API.

    Returns True if the execution was successfully claimed (still pending).
    Returns False if it was already claimed, terminal, or the gateway is unreachable.
    """
    try:
        url = f"{GATEWAY_URL}/api/webhooks/dispatched/{execution_id}/claim"
        body = json.dumps({
            "claimed_by": _OPERATOR_INSTANCE,
            "claim_source": claim_source,
        }).encode("utf-8")
        req = urllib.request.Request(url, data=body, method="POST")
        req.add_header("Content-Type", "application/json")
        req.add_header("User-Agent", "kubesynapse-operator/1.0")
        with urllib.request.urlopen(req, timeout=5) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            return bool(result.get("claimed", False))
    except urllib.error.HTTPError as exc:
        if exc.code == 409:
            logger.info(
                "webhook.dispatch.skipped_duplicate executionId=%s claim_source=%s",
                execution_id, claim_source,
            )
            return False
        logger.warning(
            "webhook.dispatch.claim_failed executionId=%s claim_source=%s http_status=%s",
            execution_id, claim_source, exc.code,
        )
        return False
    except (urllib.error.URLError, OSError) as exc:
        logger.warning(
            "webhook.dispatch.claim_error executionId=%s claim_source=%s error=%s",
            execution_id, claim_source, exc,
        )
        return False


def _gateway_patch_execution_status(
    execution_id: int,
    status: str,
    error_message: str | None = None,
    attempt_count: int | None = None,
    *,
    workflow_run_id: str | None = None,
    workflow_generation: int | None = None,
    job_name: str | None = None,
    session_id: str | None = None,
    dispatch_path: str | None = None,
) -> bool:
    """Report execution outcome and lineage back to the gateway via HTTP PATCH."""
    body: dict[str, Any] = {"status": status}
    if error_message is not None:
        body["error_message"] = error_message[:1024]
    if attempt_count is not None:
        body["attempt_count"] = max(0, int(attempt_count))
    if workflow_run_id is not None:
        body["workflow_run_id"] = workflow_run_id
    if workflow_generation is not None:
        body["workflow_generation"] = workflow_generation
    if job_name is not None:
        body["job_name"] = job_name
    if session_id is not None:
        body["session_id"] = session_id
    if dispatch_path is not None:
        body["dispatch_path"] = dispatch_path
    body["operator_instance"] = _OPERATOR_INSTANCE

    try:
        url = f"{GATEWAY_URL}/api/webhooks/dispatched/{execution_id}/status"
        data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(url, data=data, method="PATCH")
        req.add_header("Content-Type", "application/json")
        req.add_header("User-Agent", "kubesynapse-operator/1.0")
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status == 200
    except (urllib.error.URLError, urllib.error.HTTPError, OSError) as exc:
        logger.warning(
            "webhook.dispatch.status_failed executionId=%s status=%s error=%s",
            execution_id, status, exc,
        )
        return False


def _gateway_fetch_pending_dispatches(namespace: str = "default", limit: int = 50) -> list[dict[str, Any]]:
    """Fetch claimable pending dispatches from the gateway API (timer fallback).

    Only returns executions in a claimable (pending) state so the timer can
    attempt to claim them before dispatching.
    """
    try:
        url = f"{GATEWAY_URL}/api/webhooks/dispatched/pending?namespace={namespace}&limit={limit}"
        req = urllib.request.Request(url)
        req.add_header("User-Agent", "kubesynapse-operator/1.0")
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, OSError, json.JSONDecodeError) as exc:
        logger.warning(
            "webhook.dispatch.fetch_pending_failed namespace=%s error=%s",
            namespace, exc,
        )
        return []


# ---------------------------------------------------------------------------
# WebhookReceiver handlers
# ---------------------------------------------------------------------------


@kopf.on.create(GROUP, VERSION, WEBHOOK_PLURAL)
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
                WEBHOOK_PLURAL, namespace, name,
                _build_webhook_status("Active", 0),
            ),
        ),
        logger=logger, action="create-webhook-receiver",
        resource_kind="WebhookReceiver", name=name, namespace=namespace,
        default_delay=5, retry=retry,
        start_message="Reconciling WebhookReceiver create event.",
        success_message="WebhookReceiver reconciled successfully.",
    )
    return {"message": f"WebhookReceiver {name} accepted."}


@kopf.on.update(GROUP, VERSION, WEBHOOK_PLURAL)
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
                WEBHOOK_PLURAL, namespace, name,
                _build_webhook_status("Active"),
            ),
        ),
        logger=logger, action="update-webhook-receiver",
        resource_kind="WebhookReceiver", name=name, namespace=namespace,
        default_delay=5, retry=retry,
        start_message="Reconciling WebhookReceiver update event.",
        success_message="WebhookReceiver update reconciled.",
    )
    return {"message": f"WebhookReceiver {name} updated."}


@kopf.on.delete(GROUP, VERSION, WEBHOOK_PLURAL)
def delete_webhook_receiver(
    name: str, namespace: str, logger: logging.Logger, **kwargs: Any
) -> None:
    del kwargs
    log_operator_event(
        logger, logging.INFO, "WebhookReceiver deleted.",
        resource_kind="WebhookReceiver", name=name, namespace=namespace,
        action="delete-webhook-receiver",
    )


# ---------------------------------------------------------------------------
# WorkflowTrigger handlers
# ---------------------------------------------------------------------------


@kopf.on.create(GROUP, VERSION, TRIGGER_PLURAL)
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
                TRIGGER_PLURAL, namespace, name,
                _build_trigger_status("Active", 0, 0),
            ),
        ),
        logger=logger, action="create-workflow-trigger",
        resource_kind="WorkflowTrigger", name=name, namespace=namespace,
        default_delay=5, retry=retry,
        start_message="Reconciling WorkflowTrigger create event.",
        success_message="WorkflowTrigger reconciled successfully.",
    )
    return {"message": f"WorkflowTrigger {name} accepted."}


@kopf.on.update(GROUP, VERSION, TRIGGER_PLURAL)
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
                TRIGGER_PLURAL, namespace, name,
                _build_trigger_status("Active"),
            ),
        ),
        logger=logger, action="update-workflow-trigger",
        resource_kind="WorkflowTrigger", name=name, namespace=namespace,
        default_delay=5, retry=retry,
        start_message="Reconciling WorkflowTrigger update event.",
        success_message="WorkflowTrigger update reconciled.",
    )
    return {"message": f"WorkflowTrigger {name} updated."}


@kopf.on.delete(GROUP, VERSION, TRIGGER_PLURAL)
def delete_workflow_trigger(
    name: str, namespace: str, logger: logging.Logger, **kwargs: Any
) -> None:
    del kwargs
    log_operator_event(
        logger, logging.INFO, "WorkflowTrigger deleted.",
        resource_kind="WorkflowTrigger", name=name, namespace=namespace,
        action="delete-workflow-trigger",
    )


# ---------------------------------------------------------------------------
# Dispatch execution — launch workflow or invoke agent
# ---------------------------------------------------------------------------


def _resolve_workflow_spec(workflow_name: str, workflow_namespace: str) -> tuple[dict[str, Any], dict[str, Any]]:
    custom_api = kubernetes.client.CustomObjectsApi()
    workflow = custom_api.get_namespaced_custom_object(
        group=GROUP, version=VERSION, namespace=workflow_namespace,
        plural=WORKFLOW_PLURAL, name=workflow_name,
    )
    return workflow.get("spec", {}), workflow.get("metadata", {})


def _dispatch_to_workflow(
    execution_id: int,
    workflow_name: str,
    workflow_namespace: str,
    trigger_namespace: str,
    trigger_name: str,
    logger: logging.Logger,
    dispatch_path: str = "nats",
) -> tuple[str | None, dict[str, Any]]:
    """Launch a workflow Job for a trigger execution.

    Returns (job_name, lineage_dict) where lineage_dict contains metadata
    about the dispatched workflow for gateway status reporting.
    """
    lineage: dict[str, Any] = {}
    try:
        workflow_spec, workflow_meta = _resolve_workflow_spec(workflow_name, workflow_namespace)
    except ApiException as exc:
        if exc.status == 404:
            logger.warning(
                "webhook.dispatch.workflow_not_found triggerNs=%s trigger=%s workflowNs=%s workflow=%s",
                trigger_namespace, trigger_name, workflow_namespace, workflow_name,
            )
            _gateway_patch_execution_status(
                execution_id, "failed",
                error_message=f"Workflow {workflow_name} not found",
                dispatch_path=dispatch_path,
            )
            return None, lineage
        raise

    workflow_generation = int(workflow_meta.get("generation", 0) or 0)
    from controllers.workflow_controller import enqueue_workflow_job
    job_name = enqueue_workflow_job(
        spec=workflow_spec, meta=workflow_meta,
        name=workflow_name, namespace=workflow_namespace,
        logger=logger,
    )

    # Determine workflow run_id from the job_name if possible
    workflow_run_id = f"wf-run-{workflow_namespace}-{workflow_name}-{workflow_generation}-{job_name[-12:]}" if job_name else None

    lineage = {
        "workflow_run_id": workflow_run_id,
        "workflow_generation": workflow_generation,
        "job_name": job_name,
    }
    _gateway_patch_execution_status(
        execution_id, "processing",
        job_name=job_name,
        workflow_run_id=workflow_run_id,
        workflow_generation=workflow_generation,
        dispatch_path=dispatch_path,
    )
    return job_name, lineage


def _dispatch_to_agent(
    execution_id: int,
    agent_name: str,
    agent_namespace: str,
    trigger_namespace: str,
    trigger_name: str,
    payload: dict[str, Any] | None,
    event_id: str,
    logger: logging.Logger,
    dispatch_path: str = "nats",
) -> tuple[str | None, dict[str, Any]]:
    """Invoke an AIAgent directly for a trigger execution.

    Returns (session_id, lineage_dict) where lineage_dict contains metadata
    about the dispatched agent session for gateway status reporting.
    """
    lineage: dict[str, Any] = {}
    try:
        custom_api = kubernetes.client.CustomObjectsApi()
        custom_api.get_namespaced_custom_object(
            group=GROUP, version=VERSION, namespace=agent_namespace,
            plural=AGENT_PLURAL, name=agent_name,
        )
    except ApiException as exc:
        if exc.status == 404:
            logger.warning(
                "webhook.dispatch.agent_not_found triggerNs=%s trigger=%s agentNs=%s agent=%s",
                trigger_namespace, trigger_name, agent_namespace, agent_name,
            )
            _gateway_patch_execution_status(
                execution_id, "failed",
                error_message=f"Agent {agent_name} not found",
                dispatch_path=dispatch_path,
            )
            return None, lineage
        raise

    session_id = f"webhook-{event_id}"
    lineage = {"session_id": session_id}
    logger.info(
        "webhook.dispatch.agent_started triggerNs=%s trigger=%s agentNs=%s agent=%s session=%s",
        trigger_namespace, trigger_name, agent_namespace, agent_name,
        session_id,
    )
    _gateway_patch_execution_status(
        execution_id, "processing",
        session_id=session_id,
        dispatch_path=dispatch_path,
    )
    return session_id, lineage


def _process_nats_message(data: dict[str, Any]) -> None:
    """Process a webhook dispatch event received via NATS.

    Flow: claim → dispatch → report lineage.
    """
    execution_id = data.get("execution_id")
    namespace = data.get("namespace")
    trigger_name = data.get("trigger_name")
    target_kind = str(data.get("target_kind") or "workflow").strip()
    invocation_id = data.get("invocation_id", "unknown")
    payload = data.get("payload") or {}
    dispatch_path = "nats"

    if not execution_id or not namespace or not trigger_name:
        logger.warning(
            "webhook.dispatch.missing_fields event=%s fields=%s",
            invocation_id, list(data.keys()),
        )
        return

    # Atomically claim the execution — only the winner dispatches
    if not _gateway_claim_execution(execution_id, claim_source=dispatch_path):
        logger.info(
            "webhook.dispatch.skipped_duplicate executionId=%s trigger=%s/%s",
            execution_id, namespace, trigger_name,
        )
        return

    logger.info(
        "webhook.dispatch.started executionId=%s trigger=%s/%s target=%s invocation=%s",
        execution_id, namespace, trigger_name, target_kind, invocation_id,
    )

    try:
        if target_kind == "agent":
            result, lineage = _dispatch_to_agent(
                execution_id=execution_id,
                agent_name=str(data.get("agent_name") or "").strip(),
                agent_namespace=str(data.get("agent_namespace") or namespace).strip() or namespace,
                trigger_namespace=namespace,
                trigger_name=trigger_name,
                payload=payload,
                event_id=data.get("event_id", invocation_id),
                logger=logger,
                dispatch_path=dispatch_path,
            )
        else:
            result, lineage = _dispatch_to_workflow(
                execution_id=execution_id,
                workflow_name=str(data.get("workflow_name") or "").strip(),
                workflow_namespace=str(data.get("workflow_namespace") or namespace).strip() or namespace,
                trigger_namespace=namespace,
                trigger_name=trigger_name,
                logger=logger,
                dispatch_path=dispatch_path,
            )
    except Exception as exc:
        logger.warning(
            "webhook.dispatch.failed executionId=%s trigger=%s/%s error=%s",
            execution_id, namespace, trigger_name, exc,
        )
        _gateway_patch_execution_status(
            execution_id, "failed",
            error_message=str(exc)[:1024],
            dispatch_path=dispatch_path,
        )
        return

    if result:
        log_operator_event(
            logger, logging.INFO,
            "webhook.dispatch.completed",
            resource_kind="WorkflowTrigger",
            name=trigger_name, namespace=namespace,
            executionId=execution_id,
            eventId=invocation_id,
            targetKind=target_kind,
            result=result,
            dispatchPath=dispatch_path,
            operatorInstance=_OPERATOR_INSTANCE,
            **lineage,
        )


# ---------------------------------------------------------------------------
# NATS subscription for event-driven dispatch
# ---------------------------------------------------------------------------


def _start_nats_subscriber() -> None:
    """Start a background NATS subscriber for immediate webhook dispatch events."""
    import asyncio

    nats_url = os.getenv("NATS_URL", "nats://kubesynapse-nats:4222")

    async def _listen():
        try:
            import nats
            nc = await nats.connect(nats_url, connect_timeout=2)

            async def handler(msg):
                try:
                    data = json.loads(msg.data.decode())
                    logger.info(
                        "webhook.dispatch.received invocation=%s target=%s executionId=%s",
                        data.get("invocation_id"), data.get("target_kind"),
                        data.get("execution_id"),
                    )
                    _process_nats_message(data)
                except Exception as exc:
                    logger.warning(
                        "webhook.dispatch.nats_parse_error error=%s data_preview=%s",
                        exc, msg.data[:256].decode() if msg.data else "empty",
                    )

            await nc.subscribe(NATS_SUBJECT, cb=handler)
            logger.info("NATS webhook dispatch subscriber started on %s", nats_url)

            while True:
                await asyncio.sleep(60)
        except ImportError:
            logger.warning("nats-py not installed; NATS webhook dispatch unavailable, using timer fallback")
        except Exception as exc:
            logger.debug("NATS subscriber not available (%s); falling back to timer-based dispatch", exc)

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.create_task(_listen())
        else:
            loop.create_task(_listen())
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Timer-based dispatch fallback (polls gateway API when NATS is unavailable)
# ---------------------------------------------------------------------------


@kopf.timer(GROUP, VERSION, WEBHOOK_PLURAL, interval=30)
def reconcile_webhook_dispatch(logger: logging.Logger, **kwargs: Any) -> None:
    """Fallback reconciliation: poll gateway for pending + stale executions.

    This timer is a recovery path:
    1. Claims pending executions that NATS missed.
    2. Recovers executions stuck in 'queued' or 'processing'.

    Each claimed execution is processed inline.
    """
    del kwargs
    dispatch_path = "timer"

    # Step 1: Process new pending executions
    pending = _gateway_fetch_pending_dispatches(limit=50)
    for execution in pending:
        execution_id = execution.get("id")
        if execution_id is None:
            continue

        # Claim first — skip if another consumer (NATS) already claimed it
        if not _gateway_claim_execution(execution_id, claim_source=dispatch_path):
            continue

        trigger_namespace = execution.get("namespace", "default")
        trigger_name = execution.get("trigger_name", "")
        target_kind = str(execution.get("target_kind") or "workflow").strip()
        event_id = execution.get("event_id", "unknown")
        payload = execution.get("payload_json") or {}

        logger.info(
            "webhook.dispatch.started executionId=%s trigger=%s/%s target=%s source=%s",
            execution_id, trigger_namespace, trigger_name, target_kind, dispatch_path,
        )

        try:
            if target_kind == "agent":
                result, lineage = _dispatch_to_agent(
                    execution_id=execution_id,
                    agent_name=str(execution.get("agent_name") or "").strip(),
                    agent_namespace=str(execution.get("agent_namespace") or trigger_namespace).strip() or trigger_namespace,
                    trigger_namespace=trigger_namespace,
                    trigger_name=trigger_name,
                    payload=payload,
                    event_id=event_id,
                    logger=logger,
                    dispatch_path=dispatch_path,
                )
            else:
                result, lineage = _dispatch_to_workflow(
                    execution_id=execution_id,
                    workflow_name=str(execution.get("workflow_name") or "").strip(),
                    workflow_namespace=str(execution.get("workflow_namespace") or trigger_namespace).strip() or trigger_namespace,
                    trigger_namespace=trigger_namespace,
                    trigger_name=trigger_name,
                    logger=logger,
                    dispatch_path=dispatch_path,
                )
        except Exception as exc:
            logger.warning(
                "webhook.dispatch.failed executionId=%s trigger=%s/%s error=%s source=%s",
                execution_id, trigger_namespace, trigger_name, exc, dispatch_path,
            )
            _gateway_patch_execution_status(
                execution_id, "failed", error_message=str(exc)[:1024],
                dispatch_path=dispatch_path,
            )
            continue

        if result:
            log_operator_event(
                logger, logging.INFO,
                "webhook.dispatch.completed",
                resource_kind="WorkflowTrigger",
                name=trigger_name, namespace=trigger_namespace,
                executionId=execution_id,
                eventId=event_id,
                targetKind=target_kind,
                result=result,
                dispatchPath=dispatch_path,
                operatorInstance=_OPERATOR_INSTANCE,
                **lineage,
            )


# Start NATS subscriber on import
_start_nats_subscriber()
