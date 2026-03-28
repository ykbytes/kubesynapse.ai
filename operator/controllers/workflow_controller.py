"""AgentWorkflow reconciler — create, update, resume, delete, and watchdog handlers.

§2.1d of the road-to-prod plan: workflow controller extracted from main.py.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import kopf

from builders import (
    artifact_file_path,
    build_artifact_ref,
    build_journal_ref,
)
from config import (
    OPERATOR_NAMESPACE,
    WORKFLOW_POLL_SECONDS,
    WORKFLOW_QUEUE_STALE_SECONDS,
    WORKFLOW_RUNNING_STALE_SECONDS,
)
from controllers.agent_controller import resolve_tenant_for_namespace
from reconcile import execute_reconcile, inject_conditions, log_operator_event
from services import (
    cancel_worker_job,
    ensure_worker_artifact_storage,
    enqueue_worker_job,
    patch_custom_status,
    read_job_state,
)
from utils import build_workflow_run_id, now_iso, validate_workflow_graph, workflow_journal_path

logger = logging.getLogger("operator.controllers.workflow")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def parse_iso_datetime(value: str | None) -> datetime | None:
    """Parse an ISO-8601 datetime string, normalising 'Z' and missing tz."""
    if value is None or not str(value).strip():
        return None

    normalized = str(value).strip()
    if normalized.endswith("Z"):
        normalized = f"{normalized[:-1]}+00:00"

    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def validate_workflow_spec(spec: dict[str, Any]) -> dict[str, Any]:
    """Validate the AgentWorkflow spec and return the parsed graph."""
    message_bus = str(spec.get("messageBus") or "in-memory").strip() or "in-memory"
    if message_bus != "in-memory":
        raise kopf.PermanentError(
            "AgentWorkflow.spec.messageBus is reserved for future use. Only 'in-memory' is supported today."
        )

    try:
        return validate_workflow_graph(spec.get("steps") or [])
    except ValueError as exc:
        raise kopf.PermanentError(str(exc)) from exc


def workflow_should_requeue(status: dict[str, Any], job_state: str) -> str | None:
    """Return a human-readable reason if the workflow should be re-enqueued, else None."""
    phase = str(status.get("phase", "") or "")
    if phase not in {"queued", "running"}:
        return None

    summary = status.get("summary", {}) or {}
    now = datetime.now(timezone.utc)

    if phase == "queued":
        queued_at = parse_iso_datetime(str(summary.get("queuedAt") or ""))
        if queued_at is None:
            logger.warning("Workflow stuck in 'queued' with no queuedAt timestamp (job_state=%s)", job_state)
            return f"queued workflow missing queuedAt timestamp with worker job state '{job_state}'"
        queue_age_seconds = (now - queued_at).total_seconds()
        if job_state in {"active", "pending"} and queue_age_seconds < WORKFLOW_QUEUE_STALE_SECONDS:
            return None
        if queue_age_seconds >= WORKFLOW_QUEUE_STALE_SECONDS:
            return f"queued workflow exceeded {WORKFLOW_QUEUE_STALE_SECONDS}s with worker job state '{job_state}'"
        if job_state in {"missing", "failed"}:
            return f"queued workflow lost worker job with state '{job_state}'"
        if job_state == "succeeded":
            return f"queued workflow has succeeded worker job but phase is still 'queued'"
        return None

    updated_at = parse_iso_datetime(str(summary.get("updatedAt") or summary.get("startedAt") or ""))
    if updated_at is None:
        logger.warning("Workflow stuck in '%s' with no updatedAt/startedAt timestamp (job_state=%s)", phase, job_state)
        return f"running workflow missing updatedAt/startedAt timestamp with worker job state '{job_state}'"
    running_age_seconds = (now - updated_at).total_seconds()
    if job_state == "succeeded":
        return f"running workflow has succeeded worker job but phase is still '{phase}'"
    if job_state in {"active", "pending"} and running_age_seconds < WORKFLOW_RUNNING_STALE_SECONDS:
        return None
    if job_state in {"missing", "failed"}:
        return f"running workflow lost worker job with state '{job_state}'"
    if running_age_seconds >= WORKFLOW_RUNNING_STALE_SECONDS:
        return f"running workflow exceeded {WORKFLOW_RUNNING_STALE_SECONDS}s without progress"
    return None


def enqueue_workflow_job(
    spec: dict[str, Any],
    meta: dict[str, Any],
    name: str,
    namespace: str,
    logger: logging.Logger,
    *,
    current_status: dict[str, Any] | None = None,
    run_id: str | None = None,
    requeue_reason: str | None = None,
) -> str:
    """Create a worker Job for an AgentWorkflow and patch CRD status to 'queued'."""
    graph = validate_workflow_spec(spec)
    steps = spec.get("steps") or []
    generation = int((meta or {}).get("generation", 1))
    workflow_status = current_status or {}

    # Cancel any stale worker job from a previous run before creating a new one.
    previous_job = workflow_status.get("workerJob", {}) or {}
    previous_job_name = str(previous_job.get("name") or "")
    if previous_job_name:
        cancel_worker_job(previous_job_name, str(previous_job.get("namespace") or OPERATOR_NAMESPACE))

    resolved_run_id = (
        run_id
        or str(workflow_status.get("runId") or "")
        or build_workflow_run_id(
            namespace,
            name,
            generation,
        )
    )
    artifact_pvc_name = ensure_worker_artifact_storage("workflow", namespace, name)
    artifact_path = artifact_file_path("workflow", namespace, name, generation)
    journal_path = workflow_journal_path(artifact_path)
    git_config = spec.get("gitConfig") or {}

    # §2.7 — Resolve per-tenant concurrency limit for parallel steps.
    max_parallel_steps: int | None = None
    try:
        tenant_spec = resolve_tenant_for_namespace(namespace)
        if tenant_spec:
            quota = tenant_spec.get("resourceQuota") or {}
            raw_mps = quota.get("maxParallelSteps")
            if raw_mps is not None:
                max_parallel_steps = max(int(raw_mps), 1)
    except Exception:
        logger.debug("Could not resolve tenant for namespace '%s'; using default concurrency.", namespace)

    job_name = enqueue_worker_job(
        "workflow",
        namespace,
        name,
        generation,
        artifact_pvc_name,
        artifact_path,
        run_id=resolved_run_id,
        git_config=git_config if git_config else None,
        max_parallel_steps=max_parallel_steps,
    )
    existing_summary = workflow_status.get("summary", {}) or {}
    summary: dict[str, Any] = {
        **existing_summary,
        "queuedAt": now_iso(),
        "updatedAt": now_iso(),
        "completedSteps": int(existing_summary.get("completedSteps", 0) or 0),
        "totalSteps": len(steps),
        "rootSteps": graph.get("roots") or [],
        "runId": resolved_run_id,
    }
    if requeue_reason:
        summary["lastRequeueReason"] = requeue_reason

    patch_custom_status(
        "agentworkflows",
        namespace,
        name,
        inject_conditions(
            {
                "phase": "queued",
                "runId": resolved_run_id,
                "currentStep": str(workflow_status.get("currentStep", "") or ""),
                "observedGeneration": generation,
                "artifactRef": build_artifact_ref(
                    artifact_pvc_name,
                    artifact_path,
                    generation,
                    journal_path=journal_path,
                ),
                "journalRef": build_journal_ref(artifact_pvc_name, journal_path, generation),
                "workerJob": {"name": job_name, "namespace": OPERATOR_NAMESPACE},
                "summary": summary,
                "pendingApproval": None,
                "stepStates": workflow_status.get("stepStates", {}) or {},
            }
        ),
    )
    # §2.5 — DB mirroring is now handled by the status projection controller.
    logger.info(
        "Queued workflow '%s/%s' for background execution in job '%s' with run '%s'.",
        namespace,
        name,
        job_name,
        resolved_run_id,
    )
    log_operator_event(
        logger,
        logging.INFO,
        "Queued AgentWorkflow for worker execution.",
        resource_kind="AgentWorkflow",
        name=name,
        namespace=namespace,
        meta=meta,
        generation=generation,
        workerJob=job_name,
        runId=resolved_run_id,
        requeueReason=requeue_reason,
        stepCount=len(steps),
    )
    return job_name


# ---------------------------------------------------------------------------
# Kopf handlers
# ---------------------------------------------------------------------------


@kopf.on.create("sandbox.enterprise.ai", "v1alpha1", "agentworkflows")  # type: ignore[arg-type]
@kopf.on.update("sandbox.enterprise.ai", "v1alpha1", "agentworkflows")  # type: ignore[arg-type]
def run_workflow(
    spec: dict[str, Any],
    status: dict[str, Any],
    meta: dict[str, Any],
    name: str,
    namespace: str,
    logger: logging.Logger,
    retry: int = 0,
    **kwargs: Any,
) -> None:
    del kwargs
    graph = validate_workflow_spec(spec)
    steps = spec.get("steps") or []

    current_status = status or {}
    generation = int((meta or {}).get("generation", 1))
    observed_generation = int(current_status.get("observedGeneration", 0) or 0)
    phase = str(current_status.get("phase", ""))
    if observed_generation == generation and phase in {
        "queued",
        "running",
        "waiting-approval",
        "completed",
        "failed",
        "cancelled",
    }:
        log_operator_event(
            logger,
            logging.INFO,
            "Skipping workflow enqueue because the current generation is already reconciled.",
            resource_kind="AgentWorkflow",
            name=name,
            namespace=namespace,
            meta=meta,
            generation=generation,
            action="run-workflow",
            observedGeneration=observed_generation,
            phase=phase,
        )
        return

    execute_reconcile(
        lambda: (
            patch_custom_status(
                "agentworkflows",
                namespace,
                name,
                inject_conditions(
                    {
                        **current_status,
                        "summary": {
                            **(current_status.get("summary", {}) or {}),
                            "totalSteps": len(steps),
                            "rootSteps": graph.get("roots") or [],
                            "updatedAt": now_iso(),
                        },
                    }
                ),
            ),
            enqueue_workflow_job(spec, meta, name, namespace, logger, current_status=current_status),
        ),
        logger=logger,
        action="run-workflow",
        resource_kind="AgentWorkflow",
        name=name,
        namespace=namespace,
        meta=meta,
        generation=generation,
        default_delay=10,
        retry=retry,
        start_message="Reconciling AgentWorkflow for execution.",
        success_message="AgentWorkflow queued successfully.",
        observedGeneration=observed_generation,
        stepCount=len(steps),
    )


@kopf.timer(
    "sandbox.enterprise.ai",
    "v1alpha1",
    "agentworkflows",
    interval=WORKFLOW_POLL_SECONDS,
)  # type: ignore[arg-type]
def run_workflow_watchdog(
    spec: dict[str, Any],
    status: dict[str, Any],
    meta: dict[str, Any],
    name: str,
    namespace: str,
    logger: logging.Logger,
    retry: int = 0,
    **kwargs: Any,
) -> None:  # type: ignore[misc]
    del kwargs

    current_status = status or {}
    worker_job = current_status.get("workerJob", {}) or {}
    job_state = read_job_state(
        str(worker_job.get("name") or ""),
        str(worker_job.get("namespace") or OPERATOR_NAMESPACE),
    )
    reason = workflow_should_requeue(current_status, job_state)
    if reason is None:
        return

    logger.warning(
        "Workflow '%s/%s' will be re-enqueued by watchdog: %s",
        namespace,
        name,
        reason,
    )
    execute_reconcile(
        lambda: enqueue_workflow_job(
            spec,
            meta,
            name,
            namespace,
            logger,
            current_status=current_status,
            run_id=str(current_status.get("runId") or "") or None,
            requeue_reason=reason,
        ),
        logger=logger,
        action="watchdog-requeue-workflow",
        resource_kind="AgentWorkflow",
        name=name,
        namespace=namespace,
        meta=meta,
        default_delay=10,
        retry=retry,
        start_message="Re-enqueueing stale AgentWorkflow from watchdog.",
        success_message="Watchdog re-enqueued AgentWorkflow.",
        reason=reason,
        phase=str(current_status.get("phase", "") or ""),
        workerJob=current_status.get("workerJob", {}) or {},
        jobState=job_state,
    )


@kopf.on.field("sandbox.enterprise.ai", "v1alpha1", "agentworkflows", field="status.phase")  # type: ignore[arg-type]
def on_workflow_phase_cancelled(
    old: str | None,
    new: str | None,
    status: dict[str, Any],
    name: str,
    namespace: str,
    logger: logging.Logger,
    **kwargs: Any,
) -> None:
    """Kill the worker Job when a workflow is cancelled."""
    del kwargs
    if new != "cancelled":
        return
    worker_job = (status or {}).get("workerJob", {}) or {}
    job_name = str(worker_job.get("name") or "")
    job_namespace = str(worker_job.get("namespace") or OPERATOR_NAMESPACE)
    cancelled = cancel_worker_job(job_name, job_namespace)
    log_operator_event(
        logger,
        logging.INFO,
        "Cancelled worker Job %s (deleted=%s)." % (job_name or "<none>", cancelled),
        resource_kind="AgentWorkflow",
        name=name,
        namespace=namespace,
    )


@kopf.on.resume("sandbox.enterprise.ai", "v1alpha1", "agentworkflows")  # type: ignore[arg-type]
def resume_workflow(
    spec: dict[str, Any],
    status: dict[str, Any],
    meta: dict[str, Any],
    name: str,
    namespace: str,
    logger: logging.Logger,
    retry: int = 0,
    **kwargs: Any,
) -> None:
    del kwargs
    current_status = status or {}
    phase = str(current_status.get("phase", "") or "")
    if phase not in {"queued", "running", "waiting-approval"}:
        return
    worker_job = current_status.get("workerJob", {}) or {}
    job_state = read_job_state(
        str(worker_job.get("name") or ""),
        str(worker_job.get("namespace") or OPERATOR_NAMESPACE),
    )
    if job_state == "active":
        log_operator_event(
            logger,
            logging.INFO,
            "AgentWorkflow resume: worker job still active, skipping re-enqueue.",
            resource_kind="AgentWorkflow",
            name=name,
            namespace=namespace,
            action="resume-workflow",
            phase=phase,
            jobState=job_state,
        )
        return
    log_operator_event(
        logger,
        logging.INFO,
        "AgentWorkflow resume: re-enqueueing workflow whose worker job is no longer active.",
        resource_kind="AgentWorkflow",
        name=name,
        namespace=namespace,
        action="resume-workflow",
        phase=phase,
        jobState=job_state,
    )
    execute_reconcile(
        lambda: enqueue_workflow_job(
            spec,
            meta,
            name,
            namespace,
            logger,
            current_status=current_status,
            run_id=str(current_status.get("runId") or "") or None,
            requeue_reason=f"operator restart (previous phase: {phase}, job state: {job_state})",
        ),
        logger=logger,
        action="resume-workflow",
        resource_kind="AgentWorkflow",
        name=name,
        namespace=namespace,
        meta=meta,
        default_delay=10,
        retry=retry,
        start_message="Re-enqueueing AgentWorkflow after operator restart.",
        success_message="AgentWorkflow re-enqueued after operator restart.",
        phase=phase,
        jobState=job_state,
    )


@kopf.on.delete("sandbox.enterprise.ai", "v1alpha1", "agentworkflows")  # type: ignore[arg-type]
def delete_workflow(
    status: dict[str, Any],
    name: str,
    namespace: str,
    logger: logging.Logger,
    **kwargs: Any,
) -> None:
    del kwargs
    current_status = status or {}
    worker_job = current_status.get("workerJob", {}) or {}
    job_name = str(worker_job.get("name") or "")
    job_namespace = str(worker_job.get("namespace") or OPERATOR_NAMESPACE)
    cancelled = cancel_worker_job(job_name, job_namespace)
    log_operator_event(
        logger,
        logging.INFO,
        "AgentWorkflow deleted; worker job cancelled."
        if cancelled
        else "AgentWorkflow deleted; no active worker job to cancel.",
        resource_kind="AgentWorkflow",
        name=name,
        namespace=namespace,
        action="delete-workflow",
        workerJobCancelled=cancelled,
        workerJobName=job_name,
    )
