"""AgentEval reconciler — create, update, resume, delete, and scheduled eval handlers.

§2.1d of the road-to-prod plan: eval controller extracted from main.py.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import kopf

from croniter import CroniterBadCronError, croniter  # type: ignore[import-untyped]

from builders import artifact_file_path, build_artifact_ref
from config import (
    EVAL_SCHEDULE_POLL_SECONDS,
    OPERATOR_NAMESPACE,
    SCHEDULED_EVAL_QUEUE_STALE_SECONDS,
)
from reconcile import execute_reconcile, inject_conditions, log_operator_event
from services import (
    cancel_worker_job,
    enqueue_worker_job,
    ensure_worker_artifact_storage,
    patch_custom_status,
    read_job_state,
)
from utils import build_eval_run_id, now_iso

logger = logging.getLogger("operator.controllers.eval")


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


def validate_eval_schedule(schedule: str) -> None:
    """Raise kopf.PermanentError if *schedule* is not a valid cron expression."""
    try:
        croniter(schedule, datetime.now(timezone.utc))
    except (CroniterBadCronError, ValueError) as exc:
        raise kopf.PermanentError(f"Invalid AgentEval schedule '{schedule}': {exc}") from exc


def scheduled_eval_due(schedule: str, last_run_value: str | None) -> bool:
    """Return True if the next scheduled run is due."""
    last_run = parse_iso_datetime(last_run_value)
    if last_run is None:
        return False

    next_run = croniter(schedule, last_run).get_next(datetime)
    if next_run.tzinfo is None:
        next_run = next_run.replace(tzinfo=timezone.utc)
    else:
        next_run = next_run.astimezone(timezone.utc)
    return datetime.now(timezone.utc) >= next_run


def enqueue_eval_job(
    spec: dict[str, Any],
    meta: dict[str, Any],
    name: str,
    namespace: str,
    logger: logging.Logger,
    *,
    scheduled: bool = False,
) -> None:
    """Create a worker Job for an AgentEval and patch CRD status to 'queued'."""
    test_suite = spec.get("testSuite") or []
    generation = int((meta or {}).get("generation", 1))
    run_id = build_eval_run_id(namespace, name, generation)
    artifact_pvc_name = ensure_worker_artifact_storage("eval", namespace, name)
    artifact_path = artifact_file_path("eval", namespace, name, generation)
    job_name = enqueue_worker_job(
        "eval",
        namespace,
        name,
        generation,
        artifact_pvc_name,
        artifact_path,
        run_id=run_id,
    )
    summary: dict[str, Any] = {
        "queuedAt": now_iso(),
        "caseCount": len(test_suite),
        "completedCases": 0,
        "runId": run_id,
    }
    if scheduled:
        summary["scheduleTriggered"] = True
    status_payload: dict[str, Any] = {
        "phase": "queued",
        "runId": run_id,
        "observedGeneration": generation,
        "artifactRef": build_artifact_ref(artifact_pvc_name, artifact_path, generation),
        "workerJob": {"name": job_name, "namespace": OPERATOR_NAMESPACE},
        "summary": summary,
    }
    patch_custom_status(
        "agentevals",
        namespace,
        name,
        inject_conditions(status_payload),
    )
    # §2.5 — DB mirroring is now handled by the status projection controller.
    log_operator_event(
        logger,
        logging.INFO,
        "Queued AgentEval for worker execution.",
        resource_kind="AgentEval",
        name=name,
        namespace=namespace,
        meta=meta,
        generation=generation,
        workerJob=job_name,
        caseCount=len(test_suite),
        scheduled=scheduled,
    )


# ---------------------------------------------------------------------------
# Kopf handlers
# ---------------------------------------------------------------------------


@kopf.on.create("kubesynth.ai", "v1alpha1", "agentevals")  # type: ignore[arg-type]
@kopf.on.update("kubesynth.ai", "v1alpha1", "agentevals")  # type: ignore[arg-type]
def run_eval(
    spec: dict[str, Any],
    status: dict[str, Any],
    meta: dict[str, Any],
    name: str,
    namespace: str,
    logger: logging.Logger,
    **kwargs: Any,
) -> None:
    test_suite = spec.get("testSuite") or []
    if not test_suite:
        raise kopf.PermanentError("AgentEval must contain at least one test case")

    schedule = str(spec.get("schedule") or "").strip()
    if schedule:
        validate_eval_schedule(schedule)

    current_status = status or {}
    generation = int((meta or {}).get("generation", 1))
    observed_generation = int(current_status.get("observedGeneration", 0) or 0)
    phase = str(current_status.get("phase", ""))
    if observed_generation == generation and phase in {"queued", "running", "completed", "failed"}:
        log_operator_event(
            logger,
            logging.INFO,
            "Skipping eval enqueue because the current generation is already reconciled.",
            resource_kind="AgentEval",
            name=name,
            namespace=namespace,
            meta=meta,
            generation=generation,
            action="run-eval",
            observedGeneration=observed_generation,
            phase=phase,
        )
        return

    execute_reconcile(
        lambda: enqueue_eval_job(spec, meta, name, namespace, logger),
        logger=logger,
        action="run-eval",
        resource_kind="AgentEval",
        name=name,
        namespace=namespace,
        meta=meta,
        generation=generation,
        default_delay=10,
        start_message="Reconciling AgentEval for execution.",
        success_message="AgentEval queued successfully.",
        observedGeneration=observed_generation,
        caseCount=len(test_suite),
        schedule=schedule,
    )


@kopf.on.resume("kubesynth.ai", "v1alpha1", "agentevals")  # type: ignore[arg-type]
def resume_eval(
    spec: dict[str, Any],
    status: dict[str, Any],
    meta: dict[str, Any],
    name: str,
    namespace: str,
    logger: logging.Logger,
    **kwargs: Any,
) -> None:
    del kwargs
    current_status = status or {}
    phase = str(current_status.get("phase", "") or "")
    if phase not in {"queued", "running"}:
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
            "AgentEval resume: worker job still active, skipping re-enqueue.",
            resource_kind="AgentEval",
            name=name,
            namespace=namespace,
            action="resume-eval",
            phase=phase,
            jobState=job_state,
        )
        return
    log_operator_event(
        logger,
        logging.WARNING,
        "AgentEval resume: worker job not active, re-enqueueing.",
        resource_kind="AgentEval",
        name=name,
        namespace=namespace,
        action="resume-eval",
        phase=phase,
        jobState=job_state,
    )
    execute_reconcile(
        lambda: enqueue_eval_job(spec, meta, name, namespace, logger),
        logger=logger,
        action="resume-eval",
        resource_kind="AgentEval",
        name=name,
        namespace=namespace,
        meta=meta,
        default_delay=10,
        start_message="Re-enqueueing AgentEval after operator restart.",
        success_message="AgentEval re-enqueued after operator restart.",
        phase=phase,
        jobState=job_state,
    )


@kopf.on.delete("kubesynth.ai", "v1alpha1", "agentevals")  # type: ignore[arg-type]
def delete_eval(
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
        "AgentEval deleted; worker job cancelled."
        if cancelled
        else "AgentEval deleted; no active worker job to cancel.",
        resource_kind="AgentEval",
        name=name,
        namespace=namespace,
        action="delete-eval",
        workerJobCancelled=cancelled,
        workerJobName=job_name,
    )


@kopf.timer(
    "kubesynth.ai",
    "v1alpha1",
    "agentevals",
    interval=EVAL_SCHEDULE_POLL_SECONDS,
)  # type: ignore[arg-type]
def run_scheduled_eval(
    spec: dict[str, Any],
    status: dict[str, Any],
    meta: dict[str, Any],
    name: str,
    namespace: str,
    logger: logging.Logger,
    **kwargs: Any,
) -> None:
    del kwargs

    schedule = str(spec.get("schedule") or "").strip()
    if not schedule:
        return

    validate_eval_schedule(schedule)

    current_status = status or {}
    phase = str(current_status.get("phase", ""))
    if phase == "running":
        return

    retry_stale_queue = False
    if phase == "queued":
        summary = current_status.get("summary", {}) or {}
        queued_at = parse_iso_datetime(str(summary.get("queuedAt") or ""))
        if queued_at is None:
            logger.warning(
                "Scheduled eval '%s/%s' is queued without queuedAt metadata; waiting for the next timer tick.",
                namespace,
                name,
            )
            return

        worker_job = current_status.get("workerJob", {}) or {}
        job_state = read_job_state(
            str(worker_job.get("name") or ""),
            str(worker_job.get("namespace") or OPERATOR_NAMESPACE),
        )
        queue_age_seconds = (datetime.now(timezone.utc) - queued_at).total_seconds()
        if job_state in {"active", "pending"}:
            return
        if queue_age_seconds < SCHEDULED_EVAL_QUEUE_STALE_SECONDS:
            return

        retry_stale_queue = True
        logger.warning(
            "Scheduled eval '%s/%s' is stuck in phase 'queued' with worker job state '%s'; re-enqueueing.",
            namespace,
            name,
            job_state,
        )

    if not retry_stale_queue and not scheduled_eval_due(schedule, str(current_status.get("lastRun") or "")):
        return

    execute_reconcile(
        lambda: enqueue_eval_job(spec, meta, name, namespace, logger, scheduled=True),
        logger=logger,
        action="schedule-eval",
        resource_kind="AgentEval",
        name=name,
        namespace=namespace,
        meta=meta,
        default_delay=10,
        start_message="Enqueuing scheduled AgentEval run.",
        success_message="Scheduled AgentEval queued successfully.",
        schedule=schedule,
        retryStaleQueue=retry_stale_queue,
        phase=phase,
    )
