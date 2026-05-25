"""Status projection controller — mirrors workflow CRD status to PostgreSQL.

§2.5 of the road-to-prod plan: CRD status is authoritative for K8s
consumers; PostgreSQL is the derived store for the API gateway, UI,
and historical queries. This controller watches `.status.phase`
changes on AgentWorkflow CRDs and projects the current state into the
database, replacing the previous dual-write pattern.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import kopf

from state_store import record_workflow_log_archive, safe_record_workflow_state

logger = logging.getLogger("operator.controllers.status_projection")
WORKFLOW_LOG_ARCHIVE_MAX_CHARS = max(int(os.getenv("WORKFLOW_LOG_ARCHIVE_MAX_CHARS", "0") or "0"), 0)
_TERMINAL_WORKFLOW_PHASES = {"completed", "failed", "cancelled"}


def _select_latest_job_pod(pods: list[Any]) -> Any | None:
    if not pods:
        return None

    def pod_sort_key(item: Any) -> float:
        metadata = getattr(item, "metadata", None)
        creation_timestamp = getattr(metadata, "creation_timestamp", None)
        if creation_timestamp is None:
            return 0.0
        try:
            return creation_timestamp.timestamp()
        except Exception:
            return 0.0

    return sorted(pods, key=pod_sort_key, reverse=True)[0]


def _trim_log_archive(raw_text: str) -> tuple[str, bool]:
    if WORKFLOW_LOG_ARCHIVE_MAX_CHARS <= 0 or len(raw_text) <= WORKFLOW_LOG_ARCHIVE_MAX_CHARS:
        return raw_text, False
    return raw_text[-WORKFLOW_LOG_ARCHIVE_MAX_CHARS :], True


def _archive_terminal_workflow_logs(*, name: str, namespace: str, status: dict[str, Any]) -> None:
    phase = str((status or {}).get("phase") or "")
    run_id = str((status or {}).get("runId") or "")
    if phase not in _TERMINAL_WORKFLOW_PHASES or not run_id:
        return

    worker_job = (status or {}).get("workerJob") or {}
    job_name = str(worker_job.get("name") or "").strip()
    job_namespace = str(worker_job.get("namespace") or namespace).strip() or namespace
    if not job_name:
        return

    try:
        from kubernetes import client as k8s_client  # type: ignore[import-untyped]

        core_api = k8s_client.CoreV1Api()
        pods = core_api.list_namespaced_pod(
            namespace=job_namespace,
            label_selector=f"job-name={job_name}",
        )
        pod = _select_latest_job_pod(list(getattr(pods, "items", []) or []))
        if pod is None:
            logger.debug("No worker pod found to archive logs for workflow '%s/%s' run %s.", namespace, name, run_id)
            return

        pod_name = str(getattr(getattr(pod, "metadata", None), "name", "") or "").strip()
        if not pod_name:
            return

        raw_logs = core_api.read_namespaced_pod_log(
            name=pod_name,
            namespace=job_namespace,
            container="worker",
            timestamps=True,
        )
        if not isinstance(raw_logs, str) or not raw_logs:
            return

        archived_logs, truncated = _trim_log_archive(raw_logs)
        record_workflow_log_archive(
            namespace=namespace,
            resource_name=name,
            run_id=run_id,
            log_text=archived_logs,
            source="worker-pod",
            truncated=truncated,
        )
    except Exception:
        logger.warning(
            "Failed to archive worker logs for workflow '%s/%s' run %s.",
            namespace,
            name,
            run_id,
            exc_info=True,
        )


def _project_workflow_status_snapshot(
    *,
    name: str,
    namespace: str,
    spec: dict[str, Any],
    status: dict[str, Any],
    meta: dict[str, Any],
) -> None:
    phase = str((status or {}).get("phase") or "")
    if not phase:
        return
    generation = int((meta or {}).get("generation", 1))
    run_id = str((status or {}).get("runId") or "")
    if not run_id:
        return
    safe_record_workflow_state(
        namespace=namespace,
        resource_name=name,
        generation=generation,
        run_id=run_id,
        phase=phase,
        spec=spec or {},
        status=status or {},
    )


@kopf.on.field("kubesynapse.ai", "v1alpha1", "agentworkflows", field="status.phase")  # type: ignore[arg-type]
def project_workflow_status(
    old: str | None,
    new: str | None,
    name: str,
    namespace: str,
    spec: dict[str, Any],
    status: dict[str, Any],
    meta: dict[str, Any],
    **kwargs: Any,
) -> None:
    """Mirror workflow CRD status to PostgreSQL whenever phase changes."""
    del kwargs
    if not new:
        return
    _project_workflow_status_snapshot(
        name=name,
        namespace=namespace,
        spec=spec,
        status=status,
        meta=meta,
    )
    _archive_terminal_workflow_logs(name=name, namespace=namespace, status=status)
    logger.debug(
        "Projected workflow '%s/%s' phase %s → %s (run=%s).",
        namespace,
        name,
        old,
        new,
        str((status or {}).get("runId") or ""),
    )


@kopf.on.field("kubesynapse.ai", "v1alpha1", "agentworkflows", field="status.runId")  # type: ignore[arg-type]
def project_workflow_run_id(
    old: str | None,
    new: str | None,
    name: str,
    namespace: str,
    spec: dict[str, Any],
    status: dict[str, Any],
    meta: dict[str, Any],
    **kwargs: Any,
) -> None:
    """Mirror workflow CRD status to PostgreSQL whenever runId changes."""
    del kwargs
    if not new:
        return
    _project_workflow_status_snapshot(
        name=name,
        namespace=namespace,
        spec=spec,
        status=status,
        meta=meta,
    )
    logger.debug(
        "Projected workflow '%s/%s' runId %s → %s (phase=%s).",
        namespace,
        name,
        old,
        new,
        str((status or {}).get("phase") or ""),
    )
