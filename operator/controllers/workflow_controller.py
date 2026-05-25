"""AgentWorkflow reconciler — create, update, resume, delete, and watchdog handlers.

§2.1d of the road-to-prod plan: workflow controller extracted from main.py.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
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
from reconcile import execute_reconcile, inject_conditions, log_operator_event
from services import (
    cancel_worker_job,
    enqueue_worker_job,
    ensure_worker_artifact_storage,
    patch_custom_status,
    read_job_state,
)

from controllers.agent_controller import resolve_tenant_for_namespace
from utils import build_workflow_run_id, now_iso, validate_workflow_graph, workflow_journal_path

logger = logging.getLogger("operator.controllers.workflow")

GROUP = "kubesynapse.ai"
VERSION = "v1alpha1"
WORKFLOW_PLURAL = "agentworkflows"

AUTO_RETRY_SPEC_FIELD = "autoRetry"
AUTO_RETRY_FAILED_ANNOTATION = "kubesynapse.ai/auto-retry-failed"
AUTO_RETRY_LIMIT_ANNOTATION = "kubesynapse.ai/auto-retry-limit"
AUTO_RETRY_FAILURE_CLASSES_ANNOTATION = "kubesynapse.ai/auto-retry-failure-classes"
DEFAULT_AUTO_RETRY_LIMIT = 1
DEFAULT_AUTO_RETRY_FAILURE_CLASSES = frozenset(
    {
        "TimeoutError",
        "ConnectTimeout",
        "ReadTimeout",
        "PoolTimeout",
        "RemoteProtocolError",
        "ConnectError",
        "ReadError",
        "ApiException",
    }
)
NON_RETRYABLE_FAILURE_CLASSES = frozenset({"reviewrejectederror", "approval_denied"})
NON_RETRYABLE_ERROR_FRAGMENTS = (
    "verification failed",
    "did not return json output",
    "missing required json paths",
    "request blocked",
    "unprocessable entity",
    "status code 422",
    " 422 ",
)


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
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


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


def parse_bool_annotation(value: Any) -> bool:
    normalized = str(value or "").strip().lower()
    return normalized in {"1", "true", "yes", "on"}


def parse_bool_value(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return bool(value)
    normalized = str(value).strip().lower()
    if not normalized:
        return default
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


def parse_int_annotation(value: Any, default: int, *, minimum: int = 0) -> int:
    try:
        return max(int(str(value).strip()), minimum)
    except (TypeError, ValueError):
        return max(default, minimum)


def parse_int_value(value: Any, default: int, *, minimum: int = 0) -> int:
    if value is None:
        return max(default, minimum)
    try:
        return max(int(value), minimum)
    except (TypeError, ValueError):
        return max(default, minimum)


def parse_csv_annotation(value: Any) -> set[str]:
    items: set[str] = set()
    for raw_item in str(value or "").split(","):
        item = raw_item.strip()
        if item:
            items.add(item)
    return items


def parse_string_set(value: Any) -> set[str]:
    if value is None:
        return set()
    if isinstance(value, str):
        return parse_csv_annotation(value)
    if isinstance(value, (list, tuple, set, frozenset)):
        items: set[str] = set()
        for raw_item in value:
            item = str(raw_item).strip()
            if item:
                items.add(item)
        return items
    return parse_csv_annotation(value)


def resolve_auto_retry_config(spec: dict[str, Any], annotations: dict[str, Any]) -> dict[str, Any]:
    raw_config = spec.get(AUTO_RETRY_SPEC_FIELD) or {}
    if not isinstance(raw_config, dict):
        raw_config = {}

    enabled = (
        parse_bool_value(raw_config.get("enabled"), default=False)
        if "enabled" in raw_config
        else parse_bool_annotation(annotations.get(AUTO_RETRY_FAILED_ANNOTATION))
    )
    max_attempts = (
        parse_int_value(raw_config.get("maxAttempts"), DEFAULT_AUTO_RETRY_LIMIT, minimum=0)
        if "maxAttempts" in raw_config
        else parse_int_annotation(
            annotations.get(AUTO_RETRY_LIMIT_ANNOTATION),
            DEFAULT_AUTO_RETRY_LIMIT,
            minimum=0,
        )
    )
    retryable_failure_classes = (
        parse_string_set(raw_config.get("retryableFailureClasses"))
        if "retryableFailureClasses" in raw_config
        else parse_csv_annotation(annotations.get(AUTO_RETRY_FAILURE_CLASSES_ANNOTATION))
    )
    if not retryable_failure_classes:
        retryable_failure_classes = set(DEFAULT_AUTO_RETRY_FAILURE_CLASSES)

    non_retryable_failure_classes = {item.lower() for item in NON_RETRYABLE_FAILURE_CLASSES}
    non_retryable_failure_classes.update(
        item.lower() for item in parse_string_set(raw_config.get("nonRetryableFailureClasses"))
    )

    return {
        "enabled": enabled,
        "maxAttempts": max_attempts,
        "retryableFailureClasses": retryable_failure_classes,
        "nonRetryableFailureClasses": non_retryable_failure_classes,
    }


def is_non_retryable_failure(
    failure_class: str,
    error_text: str,
    *,
    non_retryable_failure_classes: set[str] | None = None,
) -> bool:
    normalized_class = failure_class.strip().lower()
    blocked_classes = non_retryable_failure_classes or {item.lower() for item in NON_RETRYABLE_FAILURE_CLASSES}
    if normalized_class in blocked_classes:
        return True

    normalized_error = error_text.strip().lower()
    return any(fragment in normalized_error for fragment in NON_RETRYABLE_ERROR_FRAGMENTS)


def resolve_failed_workflow_auto_retry_plan(
    *,
    spec: dict[str, Any],
    status: dict[str, Any],
    meta: dict[str, Any],
    name: str,
    namespace: str,
) -> dict[str, Any] | None:

    if str(status.get("phase", "") or "") != "failed":
        return None

    annotations = (meta or {}).get("annotations") or {}
    auto_retry_config = resolve_auto_retry_config(spec, annotations)
    if not auto_retry_config["enabled"]:
        return None

    step_states = status.get("stepStates") or {}
    if not isinstance(step_states, dict):
        return None

    failed_steps: list[tuple[str, dict[str, Any]]] = []
    for step_name, raw_state in step_states.items():
        if not isinstance(raw_state, dict):
            continue
        step_status = str(raw_state.get("status", "") or "").strip().lower()
        if step_status in {"failed", "denied"}:
            failed_steps.append((str(step_name), raw_state))

    if not failed_steps:
        return None

    summary = status.get("summary", {}) or {}
    retry_limit = int(auto_retry_config["maxAttempts"])
    auto_retry_count = parse_int_annotation(summary.get("autoRetryCount"), 0, minimum=0)
    if auto_retry_count >= retry_limit:
        return None

    allowed_failure_classes = set(auto_retry_config["retryableFailureClasses"])
    allowed_failure_classes_lower = {item.lower() for item in allowed_failure_classes}
    allow_all_failure_classes = "*" in allowed_failure_classes_lower

    blocked_failures: list[str] = []
    retryable_failed_steps: list[str] = []
    for step_name, state in failed_steps:
        failure_class = str(state.get("failureClass") or "").strip()
        error_text = str(state.get("error") or "").strip()
        if is_non_retryable_failure(
            failure_class,
            error_text,
            non_retryable_failure_classes=set(auto_retry_config["nonRetryableFailureClasses"]),
        ):
            blocked_failures.append(f"{step_name}={failure_class or 'unknown'}")
            continue

        if allow_all_failure_classes or failure_class.lower() in allowed_failure_classes_lower:
            retryable_failed_steps.append(step_name)
            continue

        blocked_failures.append(f"{step_name}={failure_class or 'unknown'}")

    if blocked_failures or not retryable_failed_steps:
        return None

    generation = int((meta or {}).get("generation", 1) or 1)
    retry_run_id = build_workflow_run_id(namespace, name, generation)
    retry_started_at = now_iso()

    patched_step_states: dict[str, Any] = {}
    retryable_step_set = set(retryable_failed_steps)
    for step_name, raw_state in step_states.items():
        if not isinstance(raw_state, dict):
            patched_step_states[step_name] = raw_state
            continue
        if str(step_name) not in retryable_step_set:
            patched_step_states[step_name] = raw_state
            continue
        patched_step_states[step_name] = {
            **raw_state,
            "status": "pending",
            "error": None,
            "failureClass": None,
            "startedAt": None,
            "completedAt": None,
            "iterationFailures": None,
            "planProgress": None,
            "loopProgress": None,
            "updatedAt": retry_started_at,
        }

    reason = (
        "auto-retry failed steps after recoverable failures: "
        + ", ".join(retryable_failed_steps)
    )
    patched_summary = {
        **clear_summary_lifecycle_fields(summary),
        "runId": retry_run_id,
        "failedSteps": 0,
        "waitingApprovalSteps": 0,
        "error": None,
        "updatedAt": retry_started_at,
        "autoRetryCount": auto_retry_count + 1,
        "lastAutoRetryAt": retry_started_at,
        "lastAutoRetryRunId": retry_run_id,
        "lastAutoRetryFailedSteps": retryable_failed_steps,
        "lastAutoRetryReason": reason,
    }

    return {
        "reason": reason,
        "runId": retry_run_id,
        "failedSteps": retryable_failed_steps,
        "stepStates": patched_step_states,
        "summary": patched_summary,
        "autoRetryCount": auto_retry_count + 1,
    }


def workflow_should_requeue(status: dict[str, Any], job_state: str) -> str | None:
    """Return a human-readable reason if the workflow should be re-enqueued, else None."""
    phase = str(status.get("phase", "") or "")
    if phase not in {"queued", "running"}:
        return None

    summary = status.get("summary", {}) or {}
    now = datetime.now(UTC)

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
            return "queued workflow has succeeded worker job but phase is still 'queued'"
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


def workflow_status_matches_generation(workflow_status: dict[str, Any], generation: int) -> bool:
    """Return True when status belongs to the requested generation.

    Only trusts ``observedGeneration`` — the authoritative field set by the
    worker when it begins execution.  The ``artifactRef.generation`` fallback
    was removed because it caused the controller to treat a re-triggered
    workflow (whose trigger reset ``observedGeneration`` to None but left
    ``artifactRef`` intact) as already-reconciled, restoring stale
    ``stepStates`` and preventing actual step re-execution.
    """
    observed_generation = int((workflow_status or {}).get("observedGeneration", 0) or 0)
    return observed_generation == generation


def resolve_workflow_run_id(
    namespace: str,
    workflow_name: str,
    generation: int,
    *,
    workflow_status: dict[str, Any] | None = None,
    run_id: str | None = None,
) -> str:
    """Resolve the run ID for a workflow enqueue.

    New workflow generations must mint a fresh run ID so session-aware runtimes
    cannot reuse stale threads. Same-generation retries may intentionally carry a
    fresh status.runId while reusing the same artifact generation.
    """
    explicit_run_id = str(run_id or "").strip()
    if explicit_run_id:
        return explicit_run_id

    current_status = workflow_status or {}
    status_run_id = str(current_status.get("runId") or "").strip()
    if status_run_id and workflow_status_matches_generation(current_status, generation):
        return status_run_id

    return build_workflow_run_id(namespace, workflow_name, generation)


def clear_summary_lifecycle_fields(summary: dict[str, Any]) -> dict[str, Any]:
    """Clear summary lifecycle fields that would otherwise survive merge patches."""
    cleared = dict(summary or {})
    for field_name in ("completedAt", "failedAt", "error"):
        if field_name in cleared:
            cleared[field_name] = None
    return cleared


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
    preserve_generation_state = workflow_status_matches_generation(workflow_status, generation)

    # Cancel any stale worker job from a previous run before creating a new one.
    previous_job = workflow_status.get("workerJob", {}) or {}
    previous_job_name = str(previous_job.get("name") or "")
    if previous_job_name:
        cancel_worker_job(previous_job_name, str(previous_job.get("namespace") or OPERATOR_NAMESPACE))

    resolved_run_id = resolve_workflow_run_id(
        namespace,
        name,
        generation,
        workflow_status=workflow_status,
        run_id=run_id,
    )
    owner_uid = str(meta.get("uid") or "") if meta else ""
    owner_references: list[dict[str, Any]] | None = None
    if owner_uid:
        owner_references = [{
            "apiVersion": f"{GROUP}/{VERSION}",
            "kind": "AgentWorkflow",
            "name": name,
            "uid": owner_uid,
            "controller": True,
            "blockOwnerDeletion": False,
        }]
    artifact_pvc_name = ensure_worker_artifact_storage("workflow", namespace, name, owner_references)
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
    preserved_summary = clear_summary_lifecycle_fields(existing_summary) if preserve_generation_state else {}
    summary: dict[str, Any] = {
        **preserved_summary,
        "queuedAt": now_iso(),
        "updatedAt": now_iso(),
        "completedSteps": int(preserved_summary.get("completedSteps", 0) or 0),
        "totalSteps": len(steps),
        "rootSteps": graph.get("roots") or [],
        "runId": resolved_run_id,
    }
    if requeue_reason:
        summary["lastRequeueReason"] = requeue_reason

    current_step = str(workflow_status.get("currentStep", "") or "") if preserve_generation_state else ""
    pending_approval = workflow_status.get("pendingApproval") if preserve_generation_state else None
    step_states = workflow_status.get("stepStates", {}) or {} if preserve_generation_state else {}

    patch_custom_status(
        WORKFLOW_PLURAL,
        namespace,
        name,
        inject_conditions(
            {
                "phase": "queued",
                "runId": resolved_run_id,
                "currentStep": current_step,
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
                "pendingApproval": pending_approval,
                "stepStates": step_states,
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


@kopf.on.create(GROUP, VERSION, WORKFLOW_PLURAL)  # type: ignore[arg-type]
@kopf.on.update(GROUP, VERSION, WORKFLOW_PLURAL)  # type: ignore[arg-type]
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
                WORKFLOW_PLURAL,
                namespace,
                name,
                inject_conditions(
                    {
                        **current_status,
                        "summary": {
                            **clear_summary_lifecycle_fields(current_status.get("summary", {}) or {}),
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


@kopf.timer(GROUP, VERSION, WORKFLOW_PLURAL, interval=WORKFLOW_POLL_SECONDS)  # type: ignore[arg-type]
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
    phase = str(current_status.get("phase", "") or "")

    # §reliability-P1: Short-circuit for terminal phases to avoid Kopf event spam.
    # Completed and cancelled workflows do not need watchdog polling.
    # NOTE: "failed" is intentionally NOT short-circuited — auto-retry logic
    # in the watchdog can re-enqueue recoverable failures.
    if phase in {"completed", "cancelled"}:
        return

    worker_job = current_status.get("workerJob", {}) or {}
    job_state = read_job_state(
        str(worker_job.get("name") or ""),
        str(worker_job.get("namespace") or OPERATOR_NAMESPACE),
    )
    reason = workflow_should_requeue(current_status, job_state)
    if reason is not None:
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
        return

    auto_retry_plan = resolve_failed_workflow_auto_retry_plan(
        spec=spec,
        status=current_status,
        meta=meta,
        name=name,
        namespace=namespace,
    )
    if auto_retry_plan is None:
        return

    logger.warning(
        "Workflow '%s/%s' will auto-retry failed steps: %s",
        namespace,
        name,
        auto_retry_plan["reason"],
    )

    retry_status = {
        **current_status,
        "phase": "pending",
        "runId": auto_retry_plan["runId"],
        "observedGeneration": None,
        "pendingApproval": None,
        "stepStates": auto_retry_plan["stepStates"],
        "summary": auto_retry_plan["summary"],
    }

    execute_reconcile(
        lambda: enqueue_workflow_job(
            spec,
            meta,
            name,
            namespace,
            logger,
            current_status=retry_status,
            run_id=str(auto_retry_plan["runId"]),
            requeue_reason=str(auto_retry_plan["reason"]),
        ),
        logger=logger,
        action="watchdog-auto-retry-failed-workflow",
        resource_kind="AgentWorkflow",
        name=name,
        namespace=namespace,
        meta=meta,
        default_delay=10,
        retry=retry,
        start_message="Auto-retrying recoverable AgentWorkflow failures.",
        success_message="Watchdog auto-retried failed AgentWorkflow steps.",
        reason=auto_retry_plan["reason"],
        phase=str(current_status.get("phase", "") or ""),
        workerJob=current_status.get("workerJob", {}) or {},
        jobState=job_state,
        failedSteps=auto_retry_plan["failedSteps"],
        autoRetryCount=auto_retry_plan["autoRetryCount"],
    )


@kopf.on.field(GROUP, VERSION, WORKFLOW_PLURAL, field="status.phase")  # type: ignore[arg-type]
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
        "Cancelled worker Job {} (deleted={}).".format(job_name or "<none>", cancelled),
        resource_kind="AgentWorkflow",
        name=name,
        namespace=namespace,
    )


@kopf.on.resume(GROUP, VERSION, WORKFLOW_PLURAL)  # type: ignore[arg-type]
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


@kopf.on.delete(GROUP, VERSION, WORKFLOW_PLURAL)  # type: ignore[arg-type]
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
