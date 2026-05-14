import concurrent.futures
import importlib
import json
import logging
import os
import random
import re
import signal
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import kubernetes.client  # type: ignore[import-untyped]
import kubernetes.config  # type: ignore[import-untyped]

try:
    from pythonjsonlogger import jsonlogger as _jsonlogger  # type: ignore[import-untyped]
except ModuleNotFoundError:  # pragma: no cover
    _jsonlogger = None


def _prefer_local_worker_modules() -> dict[str, Any]:
    worker_dir = Path(__file__).resolve().parent
    worker_dir_str = str(worker_dir)
    module_names = ("config", "utils", "state_store", "tracing", "trace_client")
    previous_path = list(sys.path)
    previous_modules = {module_name: sys.modules.get(module_name) for module_name in module_names}

    while worker_dir_str in sys.path:
        sys.path.remove(worker_dir_str)
    sys.path.insert(0, worker_dir_str)

    try:
        local_modules: dict[str, Any] = {}
        for module_name in module_names:
            sys.modules.pop(module_name, None)
            local_modules[module_name] = importlib.import_module(module_name)
        return local_modules
    finally:
        sys.path[:] = previous_path
        for module_name, previous_module in previous_modules.items():
            if previous_module is None:
                sys.modules.pop(module_name, None)
            else:
                sys.modules[module_name] = previous_module


LOCAL_WORKER_MODULES = _prefer_local_worker_modules()
worker_utils = LOCAL_WORKER_MODULES["utils"]
worker_state_store = LOCAL_WORKER_MODULES["state_store"]
worker_tracing = LOCAL_WORKER_MODULES["tracing"]

build_thread_id = worker_utils.build_thread_id
build_workflow_run_id = worker_utils.build_workflow_run_id
cancel_agent_session = worker_utils.cancel_agent_session
compute_execution_waves = worker_utils.compute_execution_waves
estimate_toxicity = worker_utils.estimate_toxicity
exact_match_score = worker_utils.exact_match_score
invoke_agent_runtime = worker_utils.invoke_agent_runtime
invoke_agent_runtime_stream = worker_utils.invoke_agent_runtime_stream
missing_json_paths = worker_utils.missing_json_paths
normalize_step_execution = worker_utils.normalize_step_execution
now_iso = worker_utils.now_iso
parse_json_output = worker_utils.parse_json_output
ready_workflow_steps = worker_utils.ready_workflow_steps
render_prompt = worker_utils.render_prompt
runtime_url = worker_utils.runtime_url
validate_workflow_graph = worker_utils.validate_workflow_graph
workflow_journal_path = worker_utils.workflow_journal_path

check_workflow_run_conflict = worker_state_store.check_workflow_run_conflict
init_state_database = worker_state_store.init_database
init_tracing = worker_tracing.init_tracing

TraceClient = LOCAL_WORKER_MODULES["trace_client"].TraceClient
worker_config = LOCAL_WORKER_MODULES["config"]

try:
    import runtime_events as _runtime_events_mod
    runtime_events = _runtime_events_mod
except ImportError:
    runtime_events = None  # type: ignore[assignment]

# ---------------------------------------------------------------------------
# §8.1 — Structured JSON logging
# ---------------------------------------------------------------------------

_LOG_LEVEL = os.getenv("WORKER_LOG_LEVEL", "INFO").upper()
_handler = logging.StreamHandler()
if os.getenv("JSON_LOGS", "true").lower() in {"1", "true"} and _jsonlogger is not None:
    _handler.setFormatter(_jsonlogger.JsonFormatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
else:
    _handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
logging.basicConfig(level=_LOG_LEVEL, handlers=[_handler], force=True)
logger = logging.getLogger("operator-worker")

_trace_token = os.getenv("WORKER_TRACE_TOKEN") or os.getenv("API_GATEWAY_SHARED_TOKEN") or os.getenv("DEFAULT_API_GATEWAY_SHARED_TOKEN")
trace_client = TraceClient(
    gateway_url=worker_config.GATEWAY_URL,
    token=_trace_token,
    batch_size=worker_config.WORKER_TRACE_BATCH_SIZE,
    flush_interval_sec=worker_config.WORKER_TRACE_FLUSH_INTERVAL_SEC,
    enabled=worker_config.WORKER_TRACE_ENABLED,
)

# Start runtime event emitter (Run Intelligence Layer)
if runtime_events is not None:
    runtime_events.start_emitter()

_CURRENT_EXECUTION_ID: str | None = None
_trace_context = threading.local()

GROUP = "kubesynapse.ai"
VERSION = "v1alpha1"
WORKER_KIND = os.getenv("WORKER_KIND", "").strip().lower()
TARGET_NAMESPACE = os.getenv("TARGET_NAMESPACE", "").strip()
TARGET_NAME = os.getenv("TARGET_NAME", "").strip()
OPERATOR_NAMESPACE = (
    os.getenv("OPERATOR_NAMESPACE", "default").strip() or "default"
)
WORKER_JOB_NAME = os.getenv("WORKER_JOB_NAME", "").strip()
_RAW_ARTIFACT_PATH = (
    os.getenv("ARTIFACT_PATH", "/artifacts/run.json").strip()
    or "/artifacts/run.json"
)
if ".." in _RAW_ARTIFACT_PATH or not _RAW_ARTIFACT_PATH.startswith("/artifacts/"):
    raise ValueError(
        f"ARTIFACT_PATH must start with /artifacts/ and contain no '..': {_RAW_ARTIFACT_PATH!r}"
    )
ARTIFACT_PATH = _RAW_ARTIFACT_PATH
ARTIFACT_JOURNAL_PATH = (
    os.getenv("ARTIFACT_JOURNAL_PATH", "").strip()
    or workflow_journal_path(ARTIFACT_PATH)
)
ARTIFACT_PVC_NAME = os.getenv("ARTIFACT_PVC_NAME", "").strip()
WORKFLOW_RUN_ID = os.getenv("WORKFLOW_RUN_ID", "").strip()
AGENT_RUNTIME_READY_TIMEOUT_SECONDS = max(
    float(os.getenv("AGENT_RUNTIME_READY_TIMEOUT_SECONDS", "180")),
    5.0,
)

# ---------------------------------------------------------------------------
# §8.2 — Worker execution timeout with configurable limits
# ---------------------------------------------------------------------------

WORKER_EXECUTION_TIMEOUT_SECONDS = max(
    float(os.getenv("WORKER_EXECUTION_TIMEOUT_SECONDS", "14400")),
    60.0,
)

# ---------------------------------------------------------------------------
# §2.7 — Per-tenant concurrency limit for parallel workflow steps
# ---------------------------------------------------------------------------

MAX_PARALLEL_STEPS: int = max(int(os.getenv("MAX_PARALLEL_STEPS", "4")), 1)

# ---------------------------------------------------------------------------
# §7.2 — Graceful shutdown
# ---------------------------------------------------------------------------

_shutting_down = threading.Event()

# Serialize status patches for the same workflow resource to eliminate
# 409 conflicts when parallel steps update status simultaneously.
_WORKFLOW_STATUS_LOCK = threading.Lock()


def is_shutting_down() -> bool:
    """Return True once the worker is draining."""
    return _shutting_down.is_set()


def _worker_sigterm_handler(signum: int, _frame: object) -> None:
    """Mark worker as shutting down on SIGTERM."""
    _shutting_down.set()
    if runtime_events is not None:
        runtime_events.stop_emitter()
    logger.info("Received signal %s — worker shutdown initiated.", signum)


signal.signal(signal.SIGTERM, _worker_sigterm_handler)


# ---------------------------------------------------------------------------
# §2.6 — Idempotency: Kubernetes Lease-based distributed lock
# ---------------------------------------------------------------------------

_LEASE_HOLDER_IDENTITY = WORKER_JOB_NAME or f"worker-{os.getpid()}"


def lease_holder_job_is_active(holder_identity: str) -> bool:
    holder = str(holder_identity or "").strip()
    if not holder:
        return False
    if holder == _LEASE_HOLDER_IDENTITY:
        return True
    if holder.startswith("worker-"):
        return True

    try:
        job = kubernetes.client.BatchV1Api().read_namespaced_job(
            name=holder,
            namespace=OPERATOR_NAMESPACE,
        )
    except kubernetes.client.ApiException as exc:
        if exc.status == 404:
            return False
        logger.warning("Failed to inspect lease holder job '%s': %s", holder, exc)
        return True
    except Exception as exc:
        logger.warning("Unexpected error inspecting lease holder job '%s': %s", holder, exc)
        return True

    job_status = getattr(job, "status", None)
    active = int(getattr(job_status, "active", 0) or 0)
    succeeded = int(getattr(job_status, "succeeded", 0) or 0)
    failed = int(getattr(job_status, "failed", 0) or 0)
    if active > 0:
        return True
    return not (succeeded > 0 or failed > 0)


def acquire_worker_lease(kind: str, namespace: str, name: str, generation: int) -> bool:
    """Acquire a Kubernetes Lease for this worker run. Returns True on success."""
    lease_name = f"{name}-gen-{generation}-{kind}"[:253]
    coord_api = kubernetes.client.CoordinationV1Api()
    now = datetime.now(UTC)
    lease_body = kubernetes.client.V1Lease(
        metadata=kubernetes.client.V1ObjectMeta(
            name=lease_name,
            namespace=OPERATOR_NAMESPACE,
            labels={
                "kubesynapse.ai/kind": kind,
                "kubesynapse.ai/resource": name,
                "kubesynapse.ai/namespace": namespace,
            },
        ),
        spec=kubernetes.client.V1LeaseSpec(
            holder_identity=_LEASE_HOLDER_IDENTITY,
            acquire_time=now,
            renew_time=now,
            lease_duration_seconds=120,
        ),
    )
    try:
        coord_api.create_namespaced_lease(namespace=OPERATOR_NAMESPACE, body=lease_body)
        logger.info("Acquired lease %s in %s.", lease_name, OPERATOR_NAMESPACE)
        return True
    except kubernetes.client.ApiException as exc:
        if exc.status == 409:
            # Lease already exists — check if it's expired
            try:
                existing = coord_api.read_namespaced_lease(name=lease_name, namespace=OPERATOR_NAMESPACE)
                renew = existing.spec.renew_time or existing.spec.acquire_time
                duration = existing.spec.lease_duration_seconds or 120
                if renew and (now - renew).total_seconds() > duration:
                    # Expired — take over
                    existing.spec.holder_identity = _LEASE_HOLDER_IDENTITY
                    existing.spec.acquire_time = now
                    existing.spec.renew_time = now
                    coord_api.replace_namespaced_lease(
                        name=lease_name,
                        namespace=OPERATOR_NAMESPACE,
                        body=existing,
                    )
                    logger.info("Took over expired lease %s.", lease_name)
                    return True
                holder_identity = str(existing.spec.holder_identity or "").strip()
                if holder_identity == _LEASE_HOLDER_IDENTITY:
                    existing.spec.renew_time = now
                    coord_api.replace_namespaced_lease(
                        name=lease_name,
                        namespace=OPERATOR_NAMESPACE,
                        body=existing,
                    )
                    logger.info("Re-acquired existing lease %s for this worker.", lease_name)
                    return True
                if holder_identity and not lease_holder_job_is_active(holder_identity):
                    existing.spec.holder_identity = _LEASE_HOLDER_IDENTITY
                    existing.spec.acquire_time = now
                    existing.spec.renew_time = now
                    coord_api.replace_namespaced_lease(
                        name=lease_name,
                        namespace=OPERATOR_NAMESPACE,
                        body=existing,
                    )
                    logger.warning("Took over orphaned lease %s from missing holder %s.", lease_name, holder_identity)
                    return True
                logger.warning(
                    "Lease %s is held by %s (not expired). Refusing to start.",
                    lease_name, existing.spec.holder_identity,
                )
                return False
            except kubernetes.client.ApiException:
                logger.exception("Failed to read existing lease %s.", lease_name)
                return False
        logger.exception("Failed to create lease %s.", lease_name)
        return False


def release_worker_lease(kind: str, name: str, generation: int) -> None:
    """Release the Kubernetes Lease for this worker run."""
    lease_name = f"{name}-gen-{generation}-{kind}"[:253]
    try:
        kubernetes.client.CoordinationV1Api().delete_namespaced_lease(
            name=lease_name, namespace=OPERATOR_NAMESPACE,
        )
        logger.info("Released lease %s.", lease_name)
    except kubernetes.client.ApiException as exc:
        if exc.status != 404:
            logger.warning("Failed to release lease %s: %s", lease_name, exc)


# ---------------------------------------------------------------------------
# §2.6b — Background lease renewal so long-running workers don't lose their lock
# ---------------------------------------------------------------------------

_lease_renewal_thread: threading.Thread | None = None
_lease_renewal_stop = threading.Event()


def _renew_lease_loop(kind: str, name: str, generation: int) -> None:
    """Renew the Kubernetes Lease every 60 seconds while the worker runs."""
    lease_name = f"{name}-gen-{generation}-{kind}"[:253]
    coord_api = kubernetes.client.CoordinationV1Api()
    while not _lease_renewal_stop.is_set():
        _lease_renewal_stop.wait(timeout=60)
        if _lease_renewal_stop.is_set():
            break
        try:
            existing = coord_api.read_namespaced_lease(
                name=lease_name, namespace=OPERATOR_NAMESPACE
            )
            existing.spec.renew_time = datetime.now(UTC)
            coord_api.replace_namespaced_lease(
                name=lease_name,
                namespace=OPERATOR_NAMESPACE,
                body=existing,
            )
            logger.debug("Renewed lease %s.", lease_name)
        except Exception as exc:
            logger.warning("Failed to renew lease %s: %s", lease_name, exc)


def start_lease_renewal(kind: str, name: str, generation: int) -> None:
    """Start a background thread that keeps the worker lease alive."""
    global _lease_renewal_thread
    _lease_renewal_stop.clear()
    _lease_renewal_thread = threading.Thread(
        target=_renew_lease_loop,
        args=(kind, name, generation),
        daemon=True,
    )
    _lease_renewal_thread.start()
    logger.info("Started lease renewal thread for %s.", name)


def stop_lease_renewal() -> None:
    """Signal the lease renewal thread to stop and wait for it to exit."""
    global _lease_renewal_thread
    _lease_renewal_stop.set()
    if _lease_renewal_thread is not None:
        _lease_renewal_thread.join(timeout=5)
        _lease_renewal_thread = None


def check_run_id_conflict(kind: str, namespace: str, name: str, generation: int, run_id: str) -> None:
    """Raise RuntimeError if a different run_id is already active for this resource+generation."""
    if kind != "workflow":
        return
    conflict = check_workflow_run_conflict(namespace, name, generation, run_id)
    if conflict:
        raise RuntimeError(
            f"Another {kind} run (run_id={conflict}) is already active "
            f"for {namespace}/{name} gen {generation}. Refusing to start."
        )


def resource_plural() -> str:
    if WORKER_KIND == "workflow":
        return "agentworkflows"
    raise ValueError(f"Unsupported WORKER_KIND '{WORKER_KIND}'")


def load_kubernetes_config() -> None:
    try:
        kubernetes.config.load_incluster_config()
        logger.info("Loaded in-cluster Kubernetes config for worker.")
    except kubernetes.config.ConfigException:
        kubernetes.config.load_kube_config()
        logger.info("Loaded local kubeconfig for worker.")


def wait_for_agent_runtime_ready(
    agent_name: str,
    namespace: str,
    *,
    timeout_seconds: float = AGENT_RUNTIME_READY_TIMEOUT_SECONDS,
    poll_interval_seconds: float = 2.0,
) -> None:
    """Wait for an agent runtime /ready endpoint before first invoke.

    This avoids burning a full workflow attempt on cold-starting pods.
    """
    deadline = time.time() + timeout_seconds
    url = f"{runtime_url(agent_name, namespace)}/ready"
    last_error = "runtime not ready"
    with httpx.Client(timeout=min(poll_interval_seconds, 5.0)) as client:
        while time.time() < deadline:
            if is_shutting_down():
                raise RuntimeError("Worker shutdown initiated while waiting for agent runtime")
            try:
                response = client.get(url)
                if response.status_code == 200:
                    return
                last_error = f"HTTP {response.status_code}"
            except Exception as exc:
                last_error = str(exc)
            time.sleep(min(poll_interval_seconds, max(deadline - time.time(), 0.1)))
    raise RuntimeError(
        f"Agent runtime '{agent_name}' in namespace '{namespace}' did not become ready within "
        f"{timeout_seconds:.0f}s: {last_error}"
    ) from None


def patch_custom_status(plural: str, status: dict[str, Any]) -> None:
    max_retries = 3
    for attempt in range(max_retries):
        try:
            kubernetes.client.CustomObjectsApi().patch_namespaced_custom_object_status(
                group=GROUP,
                version=VERSION,
                namespace=TARGET_NAMESPACE,
                plural=plural,
                name=TARGET_NAME,
                body={"status": status},
            )
            return
        except kubernetes.client.ApiException as exc:
            if exc.status == 409 and attempt < max_retries - 1:
                backoff = (2 ** attempt) + random.uniform(0, 1)  # noqa: S311 — non-cryptographic jitter for retry backoff
                logging.getLogger(__name__).warning(
                    "Conflict patching %s/%s status (409), retry %d/%d in %.1fs.",
                    plural, TARGET_NAME, attempt + 1, max_retries, backoff,
                )
                time.sleep(backoff)
                continue
            logging.getLogger(__name__).error(
                "Failed to patch %s/%s status: %s",
                plural, TARGET_NAME, exc,
            )
            raise


def _patch_pending_approval_label(pending_approval_name: str | None) -> None:
    """Set or clear the pending-approval label on the workflow resource."""
    label_value = pending_approval_name if pending_approval_name else None
    try:
        kubernetes.client.CustomObjectsApi().patch_namespaced_custom_object(
            group=GROUP,
            version=VERSION,
            namespace=TARGET_NAMESPACE,
            plural="agentworkflows",
            name=TARGET_NAME,
            body={"metadata": {"labels": {"kubesynapse.ai/pending-approval": label_value}}},
        )
    except kubernetes.client.ApiException as exc:
        if exc.status == 404:
            logging.getLogger(__name__).warning(
                "Workflow %s/%s not found when patching pending-approval label.",
                "agentworkflows", TARGET_NAME,
            )
            return
        logging.getLogger(__name__).error(
            "Failed to patch pending-approval label on %s/%s: %s",
            "agentworkflows", TARGET_NAME, exc,
        )
        raise
    except Exception:
        # Intentionally broad: any failure patching the label must not crash the worker.
        logging.getLogger(__name__).warning(
            "Failed to patch pending-approval label on %s/%s, approval lookup will use full scan.",
            "agentworkflows", TARGET_NAME,
            exc_info=True,
        )


def get_resource(plural: str) -> dict[str, Any]:
    return kubernetes.client.CustomObjectsApi().get_namespaced_custom_object(
        group=GROUP,
        version=VERSION,
        namespace=TARGET_NAMESPACE,
        plural=plural,
        name=TARGET_NAME,
    )


def artifact_ref(generation: int) -> dict[str, Any]:
    return {
        "namespace": OPERATOR_NAMESPACE,
        "pvcName": ARTIFACT_PVC_NAME,
        "path": ARTIFACT_PATH,
        "journalPath": ARTIFACT_JOURNAL_PATH,
        "generation": generation,
        "updatedAt": now_iso(),
    }


def journal_ref(generation: int) -> dict[str, Any]:
    return {
        "namespace": OPERATOR_NAMESPACE,
        "pvcName": ARTIFACT_PVC_NAME,
        "path": ARTIFACT_JOURNAL_PATH,
        "generation": generation,
        "updatedAt": now_iso(),
    }


def load_artifact() -> dict[str, Any]:
    path = Path(ARTIFACT_PATH)
    if not path.exists():
        logger.info("Artifact path '%s' does not exist yet; starting fresh.", path)
        return {}

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError(f"Expected JSON object, got {type(data).__name__}")
        return data
    except Exception as exc:
        logger.exception("Failed to read artifact '%s': %s", path, exc)
        raise RuntimeError(f"Corrupt or unreadable artifact at {path}: {exc}") from exc


def write_artifact(payload: dict[str, Any]) -> None:
    path = Path(ARTIFACT_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    try:
        serialized = json.dumps(payload, indent=2, sort_keys=True, default=str)
    except (TypeError, ValueError) as exc:
        logger.exception("Failed to serialize artifact payload: %s", exc)
        raise RuntimeError(f"Artifact serialization failed: {exc}") from exc
    temp_path.write_text(serialized, encoding="utf-8")
    temp_path.replace(path)


def resume_workflow_state_from_artifact(
    status: dict[str, Any],
    artifact: dict[str, Any],
    generation: int,
    run_id: str,
) -> tuple[bool, dict[str, Any], dict[str, Any], dict[str, Any], str]:
    artifact_generation_matches = artifact.get("generation") == generation
    status_step_states = dict(status.get("stepStates") or {})
    # §2.6 — Strict run_id match: the controller always passes
    # WORKFLOW_RUN_ID to worker Jobs, so the artifact must match it.
    # The old `preserved_status_progress` fallback is removed because it
    # caused ghost runs: a race between the previous worker's final status
    # patch and the trigger's status reset let stale stepStates survive,
    # making the new worker believe the artifact was still valid.
    artifact_matches_generation = artifact_generation_matches and (
        artifact.get("runId") == run_id
    )

    if not artifact_matches_generation:
        return False, {}, {}, {}, str(artifact.get("startedAt") or now_iso())

    step_results = dict(artifact.get("stepResults", {}) or {})
    step_states = status_step_states if "stepStates" in status else dict(artifact.get("stepStates", {}) or {})
    if "pendingApproval" in status:
        pending_approval = dict(status.get("pendingApproval") or {})
    else:
        pending_approval = dict(artifact.get("pendingApproval", {}) or {})
    started_at = str(artifact.get("startedAt") or now_iso())
    return artifact_matches_generation, step_results, step_states, pending_approval, started_at


def resolve_workflow_run_id_for_worker(
    status: dict[str, Any],
    artifact: dict[str, Any],
    generation: int,
) -> str:
    """Resolve the worker run ID, preferring the Job-provided value.

    The controller passes the intended run ID via WORKFLOW_RUN_ID when it
    creates the Job. Prefer that over status.runId so a fast-starting worker
    cannot race against a stale status patch from the previous generation.
    """
    return (
        str(
            WORKFLOW_RUN_ID
            or status.get("runId")
            or artifact.get("runId")
            or ""
        ).strip()
        or build_workflow_run_id(
            TARGET_NAMESPACE,
            TARGET_NAME,
            generation,
        )
    )


def append_journal_event(event_type: str, payload: dict[str, Any]) -> None:
    try:
        path = Path(ARTIFACT_JOURNAL_PATH)
        path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "timestamp": now_iso(),
            "event": event_type,
            "kind": WORKER_KIND,
            "resource": {
                "namespace": TARGET_NAMESPACE,
                "name": TARGET_NAME,
                "workerJob": WORKER_JOB_NAME,
            },
            **payload,
        }
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True))
            handle.write("\n")
    except Exception:
        # Intentionally broad: journal is best-effort; never crash the worker for I/O errors.
        logging.getLogger(__name__).warning(
            "Failed to write journal event '%s' for %s/%s",
            event_type, TARGET_NAMESPACE, TARGET_NAME,
            exc_info=True,
        )


def workflow_summary(
    step_states: dict[str, dict[str, Any]],
    total_steps: int,
    run_id: str,
) -> dict[str, Any]:
    status_counts = {
        "completed": 0,
        "continued": 0,
        "failed": 0,
        "waiting-approval": 0,
        "denied": 0,
        "skipped": 0,
    }
    for state in step_states.values():
        status_name = str(state.get("status", "")).strip()
        if status_name in status_counts:
            status_counts[status_name] += 1

    return {
        "completedSteps": (
            status_counts["completed"] + status_counts["continued"]
        ),
        "continuedSteps": status_counts["continued"],
        "failedSteps": status_counts["failed"] + status_counts["denied"],
        "skippedSteps": status_counts["skipped"],
        "waitingApprovalSteps": status_counts["waiting-approval"],
        "totalSteps": total_steps,
        "runId": run_id,
        "updatedAt": now_iso(),
    }


def clear_workflow_summary_lifecycle_fields(summary: dict[str, Any]) -> dict[str, Any]:
    """Explicitly null lifecycle fields so status merge patches clear stale data."""
    cleared = dict(summary)
    for field_name in ("error", "failedAt", "completedAt"):
        cleared[field_name] = None
    return cleared


def workflow_snapshot(
    *,
    generation: int,
    run_id: str,
    started_at: str,
    current_step: str,
    step_results: dict[str, dict[str, Any]],
    step_states: dict[str, dict[str, Any]],
    pending_approval: dict[str, Any] | None = None,
    error: str | None = None,
    completed_at: str | None = None,
    failed_at: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "kind": "workflow",
        "generation": generation,
        "runId": run_id,
        "updatedAt": now_iso(),
        "startedAt": started_at,
        "currentStep": current_step,
        "stepResults": step_results,
        "stepStates": step_states,
    }
    if pending_approval is not None:
        payload["pendingApproval"] = pending_approval
    if error:
        payload["error"] = error
    if completed_at:
        payload["completedAt"] = completed_at
    if failed_at:
        payload["failedAt"] = failed_at
    return payload


def patch_workflow_status(
    *,
    plural: str,
    phase: str,
    generation: int,
    run_id: str,
    total_steps: int,
    current_step: str,
    started_at: str,
    step_states: dict[str, dict[str, Any]],
    worker_job: dict[str, Any],
    pending_approval: dict[str, Any] | None = None,
    extra_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    with _WORKFLOW_STATUS_LOCK:
        summary = clear_workflow_summary_lifecycle_fields(
            workflow_summary(step_states, total_steps, run_id)
        )
        summary["startedAt"] = started_at
        if extra_summary:
            summary.update(extra_summary)

        status_payload = {
            "phase": phase,
            "runId": run_id,
            "currentStep": current_step,
            "observedGeneration": generation,
            "artifactRef": artifact_ref(generation),
            "journalRef": journal_ref(generation),
            "workerJob": worker_job,
            "summary": summary,
            "pendingApproval": pending_approval,
            "stepStates": step_states,
        }
        patch_custom_status(plural, status_payload)
        return status_payload


def previous_output_for_dependencies(
    dependencies: list[str],
    step_results: dict[str, dict[str, Any]],
) -> str:
    MAX_RESPONSE_TEXT_CHARS = 8000  # limit raw response to avoid prompt bloat
    parts: list[str] = []
    for dependency in dependencies:
        result = step_results.get(dependency, {})
        response_text = str(result.get("response", ""))
        output_data = result.get("output", {})
        structured_json = output_data.get("json") if isinstance(output_data, dict) else None
        if structured_json is not None:
            # Prefer structured output; truncate raw response since JSON has the data
            truncated_response = response_text[:2000]
            if len(response_text) > 2000:
                truncated_response += f"\n... (truncated {len(response_text) - 2000} chars; see Structured Output below)"
            parts.append(
                f"[Step: {dependency}]\n{truncated_response}\n[Structured Output]\n"
                + json.dumps(structured_json, ensure_ascii=False, indent=2)
            )
        else:
            if len(response_text) > MAX_RESPONSE_TEXT_CHARS:
                response_text = response_text[:MAX_RESPONSE_TEXT_CHARS] + f"\n... (truncated, {len(response_text)} total chars)"
            parts.append(f"[Step: {dependency}]\n{response_text}")
        # Include artifact summaries from runtimes that produce them (e.g. opencode)
        artifacts = result.get("artifacts") or []
        if artifacts:
            artifact_lines = []
            for art in artifacts[:50]:
                if not isinstance(art, dict):
                    continue
                art_path = art.get("path") or art.get("name") or ""
                if not art_path:
                    continue
                art_path = str(art_path)
                art_tool = art.get("tool") or ""
                art_status = art.get("status") or ""
                detail = f"{art_path} ({art_tool})" if art_tool else art_path
                if art_status and art_status != "completed":
                    detail += f" [{art_status}]"
                artifact_lines.append(f"  - {detail}")
            if artifact_lines:
                parts.append(
                    f"[Step: {dependency} — Artifacts]\n" + "\n".join(artifact_lines)
                )
        # Include tool call summaries so downstream agents know what operations ran
        tool_calls = result.get("tool_calls") or []
        if tool_calls:
            tc_lines = []
            for tc in tool_calls[:30]:
                if not isinstance(tc, dict):
                    continue
                tc_tool = str(tc.get("tool") or "unknown")
                tc_status = tc.get("status") or ""
                tc_input = tc.get("input")
                summary_text = tc_tool
                if isinstance(tc_input, dict):
                    path = tc_input.get("filePath") or tc_input.get("file") or tc_input.get("path") or ""
                    cmd = tc_input.get("command") or tc_input.get("cmd") or ""
                    if path:
                        summary_text = f"{tc_tool}: {path}"
                    elif cmd:
                        summary_text = f"{tc_tool}: {str(cmd)[:120]}"
                if tc_status and tc_status not in ("completed", "unknown"):
                    summary_text += f" [{tc_status}]"
                tc_lines.append(f"  - {summary_text}")
            if tc_lines:
                parts.append(
                    f"[Step: {dependency} — Tool Calls]\n" + "\n".join(tc_lines)
                )
    return "\n\n".join(parts)


def parse_iso_timestamp(value: Any) -> float | None:
    if not isinstance(value, str) or not value:
        return None

    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.timestamp()


def build_step_state(
    *,
    step_name: str,
    step: dict[str, Any],
    status_name: str,
    attempts: int,
    started_at: str,
    completed_at: str,
    latency_ms: int,
    worker_job: dict[str, Any],
    execution_policy: dict[str, Any],
    error: str | None = None,
    failure_class: str | None = None,
    approval_wait_ms: int | None = None,
    response_preview: str | None = None,
    artifact_count: int | None = None,
    tool_call_count: int | None = None,
    artifacts: list[dict[str, Any]] | None = None,
    tool_calls: list[dict[str, Any]] | None = None,
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    # Explicit nulls ensure merge-patched CRD status clears stale failure
    # fields after a later successful attempt for the same step name.
    state = {
        "stepName": step_name,
        "agentRef": step.get("agentRef", ""),
        "status": status_name,
        "attempts": attempts,
        "startedAt": started_at,
        "completedAt": completed_at,
        "updatedAt": now_iso(),
        "latencyMs": latency_ms,
        "workerJob": worker_job,
        "execution": execution_policy,
        "error": error,
        "failureClass": failure_class,
        "approvalWaitMs": approval_wait_ms,
        "responsePreview": response_preview,
        "artifactCount": artifact_count,
        "toolCallCount": tool_call_count,
        "artifacts": artifacts,
        "toolCalls": tool_calls,
        "warnings": warnings,
    }
    return state


def summarize_preview_text(value: Any, *, limit: int = 280) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    collapsed = re.sub(r"\s+", " ", text)
    if len(collapsed) <= limit:
        return collapsed
    return f"{collapsed[: max(limit - 3, 1)].rstrip()}..."


def summarize_tool_input(tool_input: Any) -> str | None:
    if isinstance(tool_input, dict):
        for key in (
            "command",
            "path",
            "filePath",
            "file_path",
            "target_dir",
            "workingDirectory",
            "working_directory",
            "query",
            "url",
            "repo",
            "name",
        ):
            preview = summarize_preview_text(tool_input.get(key), limit=160)
            if preview:
                return preview
        return summarize_preview_text(json.dumps(tool_input, sort_keys=True, default=str), limit=160)
    if isinstance(tool_input, list):
        return summarize_preview_text(json.dumps(tool_input, sort_keys=True, default=str), limit=160)
    return summarize_preview_text(tool_input, limit=160)


def summarize_step_artifacts(artifacts: Any, *, limit: int = 8) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    for artifact in artifacts or []:
        if not isinstance(artifact, dict):
            continue
        summary: dict[str, Any] = {}
        for field in ("path", "name", "tool", "status", "type"):
            value = artifact.get(field)
            if value not in (None, "", [], {}):
                summary[field] = value
        if not summary:
            preview = summarize_preview_text(json.dumps(artifact, sort_keys=True, default=str), limit=200)
            if preview:
                summary["preview"] = preview
        if summary:
            summaries.append(summary)
        if len(summaries) >= limit:
            break
    return summaries


def summarize_step_tool_calls(tool_calls: Any, *, limit: int = 8) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    for tool_call in tool_calls or []:
        if not isinstance(tool_call, dict):
            continue
        summary: dict[str, Any] = {}
        tool_name = str(tool_call.get("tool") or tool_call.get("name") or "").strip()
        status_name = str(tool_call.get("status") or "").strip()
        input_preview = summarize_tool_input(tool_call.get("input") or tool_call.get("args"))
        if tool_name:
            summary["tool"] = tool_name
        if status_name:
            summary["status"] = status_name
        if input_preview:
            summary["inputPreview"] = input_preview
        if not summary:
            preview = summarize_preview_text(json.dumps(tool_call, sort_keys=True, default=str), limit=200)
            if preview:
                summary["preview"] = preview
        if summary:
            summaries.append(summary)
        if len(summaries) >= limit:
            break
    return summaries


# ---------------------------------------------------------------------------
# Plan seeding — extract task items from prompt structure so progress is
# visible even when the model doesn't call todowrite.
# ---------------------------------------------------------------------------
_HEADER_RE = re.compile(r"^##\s+(.+?)$", re.MULTILINE)
TIMEOUT_TRANSPORT_FAILURE_CLASSES = frozenset(
    {
        "TimeoutError",
        "ConnectTimeout",
        "ReadTimeout",
        "PoolTimeout",
        "RemoteProtocolError",
        "ConnectError",
        "ReadError",
    }
)
TIMEOUT_TRANSPORT_ERROR_FRAGMENTS = (
    "timed out",
    "timeout",
    "connection reset",
    "connection aborted",
    "connection refused",
    "connect error",
    "read error",
    "remote protocol error",
)
VERIFICATION_ERROR_FRAGMENTS = (
    "verification failed",
    "verification invocation failed",
)
RUNTIME_STATUS_ERROR_FRAGMENTS = (
    "returned status '",
    "request blocked",
    "unprocessable entity",
    "status code ",
)
QUALITY_GATE_FAILURE_CLASSES = frozenset({"ReviewRejectedError"})


def extract_plan_items(prompt: str) -> list[dict[str, Any]]:
    """Parse ``##`` markdown headers from *prompt* and return synthetic todo items."""
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for match in _HEADER_RE.finditer(prompt):
        text = match.group(1).strip()
        if text.lower() in ("overview", "introduction", "summary", "notes", "context"):
            continue
        if text not in seen:
            seen.add(text)
            items.append({"content": text, "status": "pending"})
    return items[:20]


def classify_retry_failure(
    failure_class: str,
    error_text: str,
    missing_paths: list[str] | None = None,
) -> str:
    normalized_class = str(failure_class or "").strip()
    normalized_error = str(error_text or "").strip().lower()
    if missing_paths or "missing required json paths" in normalized_error or "did not return json output" in normalized_error:
        return "json_contract"
    if normalized_class in QUALITY_GATE_FAILURE_CLASSES:
        return "quality_gate"
    if any(fragment in normalized_error for fragment in VERIFICATION_ERROR_FRAGMENTS):
        return "verification"
    if normalized_class in TIMEOUT_TRANSPORT_FAILURE_CLASSES:
        return "timeout_transport"
    if any(fragment in normalized_error for fragment in TIMEOUT_TRANSPORT_ERROR_FRAGMENTS):
        return "timeout_transport"
    if normalized_class in {"RuntimeError", "HTTPStatusError"}:
        return "runtime_status"
    if any(fragment in normalized_error for fragment in RUNTIME_STATUS_ERROR_FRAGMENTS):
        return "runtime_status"
    return "generic"


def build_retry_prompt(
    *,
    base_prompt: str,
    attempt: int,
    step_name: str,
    failure_class: str,
    error_text: str,
    missing_paths: list[str] | None = None,
) -> str:
    failure_kind = classify_retry_failure(failure_class, error_text, missing_paths)
    if failure_kind == "json_contract":
        missing_paths_note = (
            "Missing required JSON paths from the previous attempt:\n- "
            + "\n- ".join(missing_paths or [])
            + "\n\n"
            if missing_paths
            else ""
        )
        failure_note = error_text.strip() or (
            f"Workflow step '{step_name}' failed JSON contract validation."
        )
        return (
            f"[RETRY ATTEMPT {attempt}] The previous attempt failed JSON validation.\n"
            f"Failure details: {failure_note}\n\n"
            f"{missing_paths_note}"
            "Retry requirements:\n"
            "1. Return ONLY a single valid JSON object. No markdown fences, no prose, no status summary.\n"
            "2. Preserve the intended blueprint content from the prior attempt, but fix every missing or invalid required field.\n"
            "3. Ensure every required JSON path is present with a non-empty value before you finish.\n"
            "4. If a field cannot be fully populated, include the best concrete value you can and explain blockers inside the JSON itself, not outside it.\n\n"
            + base_prompt
        )
    if failure_kind == "timeout_transport":
        return (
            f"[RETRY ATTEMPT {attempt}] The previous attempt was interrupted by a timeout or transport failure.\n"
            f"Failure details: {error_text}\n\n"
            "Recovery strategy:\n"
            "1. Inspect the current workspace and session state before making new changes.\n"
            "2. Resume from the last completed work instead of starting over.\n"
            "3. Reuse any valid files, artifacts, or structured output that were already produced.\n"
            "4. Redo only the incomplete or inconsistent parts.\n\n"
            + base_prompt
        )
    if failure_kind == "verification":
        return (
            f"[RETRY ATTEMPT {attempt}] The previous attempt failed verification.\n"
            f"Failure details: {error_text}\n\n"
            "Recovery strategy:\n"
            "1. Identify the exact gap between the delivered output and the verification criteria.\n"
            "2. Preserve the valid parts of the previous attempt.\n"
            "3. Revise only what is needed to satisfy the failed criteria.\n"
            "4. Produce a result that will pass verification without adding unrelated changes.\n\n"
            + base_prompt
        )
    if failure_kind == "runtime_status":
        return (
            f"[RETRY ATTEMPT {attempt}] The previous attempt failed after the runtime returned a non-completed status or runtime error.\n"
            f"Failure details: {error_text}\n\n"
            "Recovery strategy:\n"
            "1. Review what was already produced before making new changes.\n"
            "2. Diagnose the specific runtime or status failure.\n"
            "3. Continue from the last good state instead of restarting from scratch.\n"
            "4. Avoid repeating the exact failing action unless you have corrected the cause.\n\n"
            + base_prompt
        )
    return (
        f"[RETRY ATTEMPT {attempt}] The previous attempt failed. "
        "Before restarting, check what was already accomplished:\n"
        "1. List files/changes from the previous attempt.\n"
        "2. Identify what failed and why.\n"
        "3. Continue from where you left off rather than starting over.\n\n"
        + base_prompt
    )


def _emit_traces_from_result(result: dict[str, Any]) -> None:
    """Emit tool-call and LLM-call trace events from a runtime result."""
    execution_id = getattr(_trace_context, "execution_id", None)
    step_id = getattr(_trace_context, "step_id", None)
    if not execution_id or not step_id:
        return
    try:
        for tc in result.get("tool_calls") or []:
            if isinstance(tc, dict):
                trace_client.record_tool_call(
                    execution_id=execution_id,
                    step_id=step_id,
                    tool_name=str(tc.get("tool") or tc.get("name") or "unknown"),
                    tool_args=tc.get("input") or tc.get("arguments") or {},
                    tool_result=tc.get("output") or tc.get("result") or {},
                    error_message=tc.get("error") or None,
                    duration_ms=tc.get("duration_ms") or tc.get("duration") or None,
                )
        metadata = result.get("metadata") or {}
        if not isinstance(metadata, dict):
            metadata = {}
        model = str(result.get("model") or metadata.get("model") or "")
        response_text = str(result.get("response") or "")
        if response_text:
            trace_client.record_llm_call(
                execution_id=execution_id,
                step_id=step_id,
                model=model or "unknown",
                prompt=str(result.get("prompt", "")),
                response=response_text,
                prompt_tokens=int(metadata.get("prompt_tokens") or metadata.get("promptTokens") or 0),
                completion_tokens=int(metadata.get("completion_tokens") or metadata.get("completionTokens") or 0),
                cost_usd=float(metadata.get("cost_usd") or metadata.get("costUsd") or 0.0) or None,
                latency_ms=float(metadata.get("latency_ms") or metadata.get("latency") or 0.0) or None,
                provider=str(metadata.get("provider") or result.get("provider") or "") or None,
            )
    except Exception:
        logger.debug("Trace emission failed", exc_info=True)


def execute_workflow_step(
    step: dict[str, Any],
    workflow_input: str,
    step_results: dict[str, dict[str, Any]],
    run_id: str,
    pending_approval: dict[str, Any] | None,
    worker_job: dict[str, Any],
    project_context: str = "",
    on_todo_update: Any = None,
) -> dict[str, Any]:
    step_name = str(step.get("name", "")).strip()
    dependencies = [
        str(dep).strip()
        for dep in step.get("dependsOn") or []
        if str(dep).strip()
    ]
    execution_policy = normalize_step_execution(step)
    prompt = render_prompt(
        str(step.get("prompt", "")),
        workflow_input,
        previous_output_for_dependencies(dependencies, step_results),
        step_results,
        project_context=project_context,
    )
    if not prompt.strip():
        prompt = workflow_input
    # Share session with dependency steps when shareSession is set,
    # so that runtimes with session persistence (e.g. opencode) maintain
    # workspace context across sequential steps.
    session_group = str(execution_policy.get("sessionGroup") or "").strip()
    if session_group:
        thread_id = build_thread_id("workflow", TARGET_NAME, run_id, session_group)
    else:
        thread_id = build_thread_id("workflow", TARGET_NAME, run_id, step_name)
    started_at = now_iso()
    approval_wait_ms: int | None = None
    agent_ref = str(step.get("agentRef", ""))
    required_json_paths = list(execution_policy.get("requiredJsonPaths") or [])
    previous_failure_class = ""
    previous_error_text = ""
    previous_missing_paths: list[str] = []

    if (
        pending_approval
        and str(pending_approval.get("stepName") or "") == step_name
    ):
        requested_epoch = parse_iso_timestamp(
            pending_approval.get("requestedAt")
        )
        if requested_epoch is not None:
            approval_wait_ms = max(
                int((time.time() - requested_epoch) * 1000),
                0,
            )

    for attempt in range(1, int(execution_policy["maxAttempts"]) + 1):
        started = time.perf_counter()
        latest_result: dict[str, Any] | None = None
        # On retry attempts, prepend context about the previous failure
        # so the agent can resume rather than restart from scratch.
        effective_prompt = prompt
        # Soft nudge: encourage the agent to update its todowrite plan
        # as it works.  The initial plan is auto-seeded from the prompt
        # structure, so the agent only needs to mark items in_progress/done.
        planning_preamble = (
            "As you work, use the todowrite tool to mark tasks 'in_progress' "
            "when you start them and 'done' when you finish them.\n\n"
        )
        effective_prompt = planning_preamble + effective_prompt
        if attempt > 1:
            effective_prompt = build_retry_prompt(
                base_prompt=prompt,
                attempt=attempt,
                step_name=step_name,
                failure_class=previous_failure_class,
                error_text=previous_error_text,
                missing_paths=previous_missing_paths,
            )
        append_journal_event(
            "workflow.step.attempt.started",
            {
                "runId": run_id,
                "step": step_name,
                "attempt": attempt,
                "threadId": thread_id,
                "agentRef": agent_ref,
            },
        )
        try:
            wait_for_agent_runtime_ready(agent_ref, TARGET_NAMESPACE)
            if runtime_events is not None:
                runtime_events.emit_step_started(
                    execution_id=getattr(_trace_context, "execution_id", ""),
                    step_name=step_name,
                    agent_ref=agent_ref,
                    attempt=attempt,
                    thread_id=thread_id,
                )
                runtime_events.emit_agent_call(
                    execution_id=getattr(_trace_context, "execution_id", ""),
                    caller_agent=TARGET_NAME,
                    target_agent=agent_ref,
                    status="started",
                    thread_id=thread_id,
                )
            invoke_payload: dict[str, Any] = {
                    "prompt": effective_prompt,
                    "thread_id": thread_id,
                    "require_approval": bool(
                        step.get("requireApproval", False)
                    ),
                    "approval_action": (
                        f"Workflow '{TARGET_NAME}' step '{step_name}'"
                    ),
                    "caller_agent_name": TARGET_NAME,
                    "caller_agent_namespace": TARGET_NAMESPACE,
                    "parent_thread_id": run_id,
                    "pre_authorized_actions": list(
                        execution_policy.get("preAuthorizedActions") or []
                    ),
            }
            if int(execution_policy.get("maxTurns", 0)):
                invoke_payload["max_turns"] = int(execution_policy["maxTurns"])
            # Seed plan from prompt structure so progress is visible immediately.
            if on_todo_update and attempt == 1:
                seed = extract_plan_items(effective_prompt)
                if seed:
                    on_todo_update(seed)
            # Use streaming invoke for real-time turn-by-turn visibility
            result = invoke_agent_runtime_stream(
                agent_ref,
                TARGET_NAMESPACE,
                invoke_payload,
                timeout_seconds=float(execution_policy["timeoutSeconds"]),
                step_name=step_name,
                iteration=attempt,
                on_todo_update=on_todo_update,
            )
            latest_result = result
            _emit_traces_from_result(result)
            latency_ms = int((time.perf_counter() - started) * 1000)
            response_text = str(result.get("response", ""))
            result_status = str(
                result.get("status", "completed") or "completed"
            )
            completed_at = now_iso()

            if runtime_events is not None:
                exec_id = getattr(_trace_context, "execution_id", "")
                metadata = result.get("metadata") or {}
                total_tokens = int(metadata.get("total_tokens") or metadata.get("context_budget", {}).get("total_tokens") or 0)
                cost_usd = float(metadata.get("cost_usd") or metadata.get("costUsd") or 0.0) or None
                runtime_events.emit_agent_call(
                    execution_id=exec_id,
                    caller_agent=TARGET_NAME,
                    target_agent=agent_ref,
                    status="completed",
                    thread_id=thread_id,
                    duration_ms=latency_ms,
                )
                runtime_events.emit_step_completed(
                    execution_id=exec_id,
                    step_name=step_name,
                    status=result_status,
                    thread_id=thread_id,
                    total_tokens=total_tokens,
                    cost_usd=cost_usd,
                    duration_ms=latency_ms,
                )
                for tc in result.get("tool_calls") or []:
                    if isinstance(tc, dict):
                        runtime_events.emit_tool_call(
                            execution_id=exec_id,
                            tool_name=tc.get("tool") or tc.get("name") or "unknown",
                            tool_args=tc.get("input") or tc.get("args"),
                            status=tc.get("status") or "completed",
                            thread_id=thread_id,
                            step_name=step_name,
                            duration_ms=tc.get("duration_ms") or tc.get("duration"),
                        )

            if result_status == "approval_pending":
                approval_payload = {
                    "name": result.get("approval_name"),
                    "namespace": TARGET_NAMESPACE,
                    "action": (
                        f"Workflow '{TARGET_NAME}' step '{step_name}'"
                    ),
                    "stepName": step_name,
                    "requestedAt": completed_at,
                    "runId": run_id,
                    "threadId": thread_id,
                    "attempt": attempt,
                }
                append_journal_event(
                    "workflow.step.approval.pending",
                    {
                        "runId": run_id,
                        "step": step_name,
                        "attempt": attempt,
                        "approval": approval_payload,
                    },
                )
                return {
                    "state": "approval_pending",
                    "stepName": step_name,
                    "pendingApproval": approval_payload,
                    "stepState": build_step_state(
                        step_name=step_name,
                        step=step,
                        status_name="waiting-approval",
                        attempts=attempt,
                        started_at=started_at,
                        completed_at=completed_at,
                        latency_ms=latency_ms,
                        worker_job=worker_job,
                        execution_policy=execution_policy,
                    ),
                }

            # Treat "incomplete" as usable partial output (e.g. opencode
            # context overflow that still produced a response).
            step_warnings: list[str] = list(result.get("warnings") or [])
            if result_status == "incomplete":
                step_warnings.append(
                    f"Step '{step_name}' returned status 'incomplete'; "
                    "partial output accepted."
                )
                result_status = "completed"

            if (
                result_status != "completed"
                or response_text.startswith("Request blocked")
            ):
                raise RuntimeError(
                    "Workflow step "
                    f"'{step_name}' returned status '{result_status}': "
                    f"{response_text}"
                )

            # Extract structured output: prefer metadata.structured_output
            # (populated by runtimes like opencode when output_format is
            # set), then fall back to parsing the raw response text.
            result_metadata = result.get("metadata") or {}
            structured_output = (
                result_metadata.get("structured_output")
                if isinstance(result_metadata, dict)
                else None
            )
            if structured_output is None:
                structured_output = parse_json_output(response_text)
            if required_json_paths:
                if structured_output is None:
                    previous_missing_paths = []
                    previous_error_text = (
                        f"Workflow step '{step_name}' did not return JSON output; required JSON paths: {required_json_paths}"
                    )
                    raise RuntimeError(
                        f"Workflow step '{step_name}' did not return JSON output; required JSON paths: {required_json_paths}"
                    )
                missing_paths = missing_json_paths(structured_output, required_json_paths)
                if missing_paths:
                    previous_missing_paths = list(missing_paths)
                    previous_error_text = (
                        f"Workflow step '{step_name}' missing required JSON paths: {missing_paths}"
                    )
                    raise RuntimeError(
                        f"Workflow step '{step_name}' missing required JSON paths: {missing_paths}"
                    )
                previous_missing_paths = []
                previous_error_text = ""
            step_result = {
                "agentRef": step.get("agentRef", ""),
                "response": response_text,
                "thread_id": result.get("thread_id", thread_id),
                "model": result.get("model"),
                "policy_name": result.get("policy_name"),
                "status": result_status,
                "output": {
                    "text": response_text,
                    "json": structured_output,
                    "type": (
                        "json" if structured_output is not None else "text"
                    ),
                },
                "attempts": attempt,
                "artifacts": list(result.get("artifacts") or []),
                "tool_calls": list(result.get("tool_calls") or []),
                "metadata": result.get("metadata"),
                "warnings": step_warnings,
            }
            # --- Verification gate ---
            verify_prompt_template = str(step.get("verify", "") or "").strip()
            verification_result: dict[str, Any] | None = None
            if verify_prompt_template:
                # Truncate long output to avoid overloading the verifier's context
                verify_output = response_text
                if len(verify_output) > 6000:
                    verify_output = (
                        response_text[:3000]
                        + f"\n\n... ({len(response_text) - 6000} chars omitted) ...\n\n"
                        + response_text[-3000:]
                    )
                verify_prompt = (
                    f"Verify the following output using goal-backward analysis.\n\n"
                    f"Verification criteria: {verify_prompt_template}\n\n"
                    f"Output to verify:\n{verify_output}\n\n"
                    f"Work backwards from the goal:\n"
                    f"1. What must be TRUE for the criteria to be satisfied?\n"
                    f"2. Is each condition actually met by the output — not just claimed?\n"
                    f"3. Are there gaps between what was delivered and what was required?\n"
                    f"4. Ignore deprecation warnings, linting notices, and informational output "
                    f"that do not affect functional correctness.\n\n"
                    f"Respond with exactly PASS or FAIL on the first line, "
                    f"followed by a brief explanation covering each condition checked."
                )
                append_journal_event(
                    "workflow.step.verify.started",
                    {"runId": run_id, "step": step_name, "attempt": attempt},
                )
                try:
                    verify_max_attempts = 1 + int(execution_policy.get("verifyRetries", 0))
                    for verify_attempt in range(verify_max_attempts):
                        verify_result_raw = invoke_agent_runtime(
                            str(step.get("agentRef", "")),
                            TARGET_NAMESPACE,
                            {
                                "prompt": verify_prompt,
                                "thread_id": build_thread_id("verify", TARGET_NAME, run_id, step_name),
                                "caller_agent_name": TARGET_NAME,
                                "caller_agent_namespace": TARGET_NAMESPACE,
                                "parent_thread_id": run_id,
                            },
                            timeout_seconds=float(execution_policy["timeoutSeconds"]),
                        )
                        verify_response = str(verify_result_raw.get("response", "")).strip()
                        verify_first_line = verify_response.split("\n", 1)[0].strip().upper()
                        verify_passed = verify_first_line.startswith("PASS")
                        verification_result = {
                            "passed": verify_passed,
                            "response": verify_response,
                            "criteria": verify_prompt_template,
                            "verifyAttempt": verify_attempt + 1,
                        }
                        step_result["verificationResult"] = verification_result
                        append_journal_event(
                            "workflow.step.verify.completed",
                            {
                                "runId": run_id,
                                "step": step_name,
                                "passed": verify_passed,
                                "verifyAttempt": verify_attempt + 1,
                            },
                        )
                        if verify_passed:
                            break
                        if verify_attempt < verify_max_attempts - 1:
                            append_journal_event(
                                "workflow.step.verify.retry",
                                {"runId": run_id, "step": step_name, "verifyAttempt": verify_attempt + 1},
                            )
                            continue
                        raise RuntimeError(
                            f"Verification failed for step '{step_name}' after {verify_max_attempts} attempt(s): {verify_response[:500]}"
                        )
                except RuntimeError:
                    raise
                except Exception as verify_exc:
                    append_journal_event(
                        "workflow.step.verify.error",
                        {"runId": run_id, "step": step_name, "error": str(verify_exc)},
                    )
                    raise RuntimeError(
                        f"Verification invocation failed for step '{step_name}': {verify_exc}"
                    ) from verify_exc

            append_journal_event(
                "workflow.step.completed",
                {
                    "runId": run_id,
                    "step": step_name,
                    "attempt": attempt,
                    "latencyMs": latency_ms,
                    "threadId": thread_id,
                    "structuredOutput": structured_output is not None,
                    "artifactCount": len(step_result["artifacts"]),
                    "toolCallCount": len(step_result["tool_calls"]),
                    "warnings": step_warnings,
                    "verified": verification_result["passed"] if verification_result else None,
                },
            )
            completed_step_state = build_step_state(
                step_name=step_name,
                step=step,
                status_name="completed",
                attempts=attempt,
                started_at=started_at,
                completed_at=completed_at,
                latency_ms=latency_ms,
                worker_job=worker_job,
                execution_policy=execution_policy,
                approval_wait_ms=approval_wait_ms,
                response_preview=summarize_preview_text(response_text, limit=400),
                artifact_count=len(step_result["artifacts"]),
                tool_call_count=len(step_result["tool_calls"]),
                artifacts=summarize_step_artifacts(step_result["artifacts"]),
                tool_calls=summarize_step_tool_calls(step_result["tool_calls"]),
                warnings=step_warnings,
            )
            if verification_result:
                completed_step_state["verificationResult"] = verification_result
            return {
                "state": "completed",
                "stepName": step_name,
                "stepResult": step_result,
                "stepState": completed_step_state,
            }
        except Exception as exc:
            latency_ms = int((time.perf_counter() - started) * 1000)
            completed_at = now_iso()
            error_text = str(exc)
            failure_class = type(exc).__name__
            previous_failure_class = failure_class
            previous_error_text = error_text
            if classify_retry_failure(failure_class, error_text, previous_missing_paths) != "json_contract":
                previous_missing_paths = []

            # Attempt to cancel the running session to prevent orphaned
            # agent processes from consuming resources after a timeout.
            try:
                cancel_agent_session(
                    str(step.get("agentRef", "")),
                    TARGET_NAMESPACE,
                    thread_id,
                )
            except Exception as exc:
                logger.debug("Failed to cancel agent session during step cleanup: %s", exc, exc_info=True)

            append_journal_event(
                "workflow.step.attempt.failed",
                {
                    "runId": run_id,
                    "step": step_name,
                    "attempt": attempt,
                    "latencyMs": latency_ms,
                    "error": error_text,
                    "failureClass": failure_class,
                },
            )
            if runtime_events is not None:
                exec_id = getattr(_trace_context, "execution_id", "")
                runtime_events.emit_agent_call(
                    execution_id=exec_id,
                    caller_agent=TARGET_NAME,
                    target_agent=agent_ref,
                    status="failed",
                    thread_id=thread_id,
                    duration_ms=latency_ms,
                )
                runtime_events.emit_step_failed(
                    execution_id=exec_id,
                    step_name=step_name,
                    error=error_text[:2048],
                    failure_class=failure_class,
                    thread_id=thread_id,
                    duration_ms=latency_ms,
                )
            should_retry = (
                bool(execution_policy["retryable"])
                and attempt < int(execution_policy["maxAttempts"])
            )
            if should_retry:
                backoff_seconds = min(
                    float(execution_policy["backoffSeconds"]) * (2 ** (attempt - 1)),
                    300.0,
                )
                append_journal_event(
                    "workflow.step.retrying",
                    {
                        "runId": run_id,
                        "step": step_name,
                        "attempt": attempt,
                        "sleepSeconds": backoff_seconds,
                    },
                )
                if backoff_seconds > 0:
                    time.sleep(backoff_seconds)
                continue

            terminal_state = (
                "continued"
                if bool(execution_policy["continueOnError"])
                else "failed"
            )
            partial_response = ""
            partial_structured_output = None
            partial_artifacts: list[dict[str, Any]] = []
            partial_tool_calls: list[dict[str, Any]] = []
            partial_metadata = None
            partial_warnings: list[str] = []
            if isinstance(latest_result, dict):
                partial_response = str(latest_result.get("response", ""))
                partial_artifacts = list(latest_result.get("artifacts") or [])
                partial_tool_calls = list(latest_result.get("tool_calls") or [])
                partial_metadata = latest_result.get("metadata")
                partial_warnings = list(latest_result.get("warnings") or [])
                if isinstance(partial_metadata, dict):
                    partial_structured_output = partial_metadata.get("structured_output")
                if partial_structured_output is None and partial_response:
                    partial_structured_output = parse_json_output(partial_response)
            step_result = {
                "agentRef": step.get("agentRef", ""),
                "response": partial_response,
                "thread_id": thread_id,
                "status": terminal_state,
                "error": error_text,
                "output": {
                    "text": partial_response,
                    "json": partial_structured_output,
                    "type": (
                        "json"
                        if partial_structured_output is not None
                        else ("text" if partial_response else "empty")
                    ),
                },
                "attempts": attempt,
                "artifacts": partial_artifacts,
                "tool_calls": partial_tool_calls,
                "metadata": partial_metadata,
                "warnings": partial_warnings,
            }
            append_journal_event(
                f"workflow.step.{terminal_state}",
                {
                    "runId": run_id,
                    "step": step_name,
                    "attempt": attempt,
                    "error": error_text,
                    "failureClass": failure_class,
                },
            )
            return {
                "state": terminal_state,
                "stepName": step_name,
                "stepResult": step_result,
                "stepState": build_step_state(
                    step_name=step_name,
                    step=step,
                    status_name=terminal_state,
                    attempts=attempt,
                    started_at=started_at,
                    completed_at=completed_at,
                    latency_ms=latency_ms,
                    worker_job=worker_job,
                    execution_policy=execution_policy,
                    error=error_text,
                    failure_class=failure_class,
                    approval_wait_ms=approval_wait_ms,
                    response_preview=summarize_preview_text(partial_response, limit=400),
                    artifact_count=len(partial_artifacts),
                    tool_call_count=len(partial_tool_calls),
                    artifacts=summarize_step_artifacts(partial_artifacts),
                    tool_calls=summarize_step_tool_calls(partial_tool_calls),
                    warnings=partial_warnings,
                ),
            }

    raise RuntimeError(
        f"Workflow step '{step_name}' exhausted retries unexpectedly"
    )


# ---- Loop step engine (Ralph-style dev-loop) ----


class LoopCircuitBreaker:
    """Three-state circuit breaker: CLOSED → HALF_OPEN → OPEN.

    Tracks consecutive iterations with no progress. Opens when threshold is reached.
    """

    def __init__(self, no_progress_threshold: int = 3, cooldown_minutes: int = 30):
        self.no_progress_threshold = no_progress_threshold
        self.cooldown_minutes = cooldown_minutes
        self.state = "closed"  # closed | half_open | open
        self.consecutive_no_progress = 0

    def record_progress(self, made_progress: bool) -> None:
        if made_progress:
            self.consecutive_no_progress = 0
            self.state = "closed"
        else:
            self.consecutive_no_progress += 1
            if self.consecutive_no_progress >= self.no_progress_threshold:
                self.state = "open"
            elif self.consecutive_no_progress >= max(1, self.no_progress_threshold - 1):
                self.state = "half_open"

    def is_open(self) -> bool:
        return self.state == "open"

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "consecutiveNoProgress": self.consecutive_no_progress,
            "threshold": self.no_progress_threshold,
        }


def parse_plan_checklist(plan_text: str) -> list[dict[str, Any]]:
    """Parse a markdown checklist into structured items.

    Supports formats:
      - [ ] Item description
      - [x] Completed item
      1. Item description
      - Item description
    """
    items: list[dict[str, Any]] = []
    for line in plan_text.strip().splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        # Checkbox format
        if stripped.startswith("- ["):
            done = stripped[3] == "x" or stripped[3] == "X"
            text = stripped[5:].strip() if len(stripped) > 5 else ""
            items.append({"text": text, "done": done})
        # Numbered list
        elif len(stripped) > 2 and stripped[0].isdigit() and "." in stripped[:4]:
            text = stripped.split(".", 1)[1].strip()
            items.append({"text": text, "done": False})
        # Bullet list
        elif stripped.startswith("- ") or stripped.startswith("* "):
            items.append({"text": stripped[2:].strip(), "done": False})
    return items


def build_loop_iteration_prompt(
    step: dict[str, Any],
    iteration: int,
    checklist: list[dict[str, Any]],
    previous_response: str,
    workflow_input: str,
    project_context: str = "",
) -> str:
    """Build the prompt for a single loop iteration."""
    loop_config = step.get("loopConfig", {})
    base_prompt = step.get("prompt", "")

    # Find current TODO item
    current_item = None
    for idx, item in enumerate(checklist):
        if not item.get("done"):
            current_item = {"index": idx, **item}
            break

    # Build checklist status
    checklist_status = []
    for idx, item in enumerate(checklist):
        marker = "[x]" if item.get("done") else "[ ]"
        checklist_status.append(f"  {marker} {idx + 1}. {item['text']}")

    parts = [
        f"## Dev-Loop Iteration {iteration}",
        "",
        "### Work Plan Status:",
        *checklist_status,
        "",
    ]
    if current_item:
        parts.extend([
            f"### Current Task (Item {current_item['index'] + 1}):",
            f"{current_item['text']}",
            "",
        ])
    if previous_response:
        parts.extend([
            "### Previous Iteration Result:",
            previous_response[:4000],
            "",
        ])
    if base_prompt:
        parts.extend([
            "### Instructions:",
            base_prompt,
            "",
        ])
    if project_context:
        parts.extend([
            "### Project Context:",
            project_context,
            "",
        ])
    commit_after = loop_config.get("commitAfterEachItem", True)
    parts.extend([
        "### Requirements:",
        "- Work on the current task item only — complete it fully before moving on",
        f"- {'Commit your changes after completing the task' if commit_after else 'Do not commit yet'}",
        "- Before marking done: verify the change actually works (run it, test it, read it back)",
        "- If the task cannot be completed as planned, explain what changed and how you are adapting",
        "- If you have been stuck on this same item for 2+ iterations, try a fundamentally different approach",
        "- When done with this item, respond with: ITEM_COMPLETE",
        "- If all items are done, respond with: PLAN_COMPLETE",
        "- If you are stuck and cannot make progress, respond with: NO_PROGRESS",
    ])
    return "\n".join(parts)


# Word-boundary patterns for loop signal detection to avoid false positives
# from e.g. "NO_PROGRESS_REPORT" or "ITEM_COMPLETED".
_SIGNAL_ITEM_COMPLETE = re.compile(r"\bITEM_COMPLETE\b")
_SIGNAL_PLAN_COMPLETE = re.compile(r"\b(?:PLAN_COMPLETE|ALL_ITEMS_DONE)\b")
_SIGNAL_NO_PROGRESS = re.compile(r"\b(?:NO_PROGRESS|STUCK)\b")


def detect_iteration_signals(response_text: str) -> dict[str, bool]:
    """Detect completion/progress signals from agent response.

    Signals are only recognised near the end of the response (last 500
    characters) to avoid false positives from casual mentions of these
    keywords in reasoning, comments, or error messages.
    """
    tail = response_text[-500:].upper() if len(response_text) > 500 else response_text.upper()
    return {
        "item_complete": _SIGNAL_ITEM_COMPLETE.search(tail) is not None,
        "plan_complete": _SIGNAL_PLAN_COMPLETE.search(tail) is not None,
        "no_progress": _SIGNAL_NO_PROGRESS.search(tail) is not None,
    }


def execute_loop_step(
    step: dict[str, Any],
    workflow_input: str,
    step_results: dict[str, dict[str, Any]],
    run_id: str,
    worker_job: dict[str, Any],
    *,
    on_iteration_complete: Any = None,
    project_context: str = "",
) -> dict[str, Any]:
    """Execute a loop-type step: iterate over a work plan calling the agent per item."""
    step_name = str(step.get("name", "")).strip()
    loop_config = step.get("loopConfig", {})
    max_iterations = min(int(loop_config.get("maxIterations", 20)), 100)  # hard cap at 100
    plan_source = loop_config.get("planSource", "inline")
    plan_text = loop_config.get("plan", "")

    cb_config = loop_config.get("circuitBreaker", {})
    circuit_breaker = LoopCircuitBreaker(
        no_progress_threshold=int(cb_config.get("noProgressThreshold", 3)),
        cooldown_minutes=int(cb_config.get("cooldownMinutes", 30)),
    )

    exit_conditions = loop_config.get("exitConditions", {})
    completion_signal_threshold = int(exit_conditions.get("completionSignalCount", 2))
    plan_complete_exit = exit_conditions.get("planComplete", True)

    started_perf = time.perf_counter()
    started_at = now_iso()
    execution_policy = normalize_step_execution(step)
    agent_ref = str(step.get("agentRef", ""))

    # Parse or generate plan
    if plan_source == "prompt" or not plan_text:
        # Agent generates plan from first iteration
        context_block = f"[Project Context]\n{project_context}\n\n" if project_context else ""
        dependencies = [str(dep).strip() for dep in step.get("dependsOn") or [] if str(dep).strip()]
        dependency_block = ""
        if dependencies:
            prev_output = previous_output_for_dependencies(dependencies, step_results)
            if prev_output:
                dependency_block = f"[Previous Step Output]\n{prev_output}\n\n"
        plan_prompt = (
            f"{context_block}"
            f"{dependency_block}"
            f"Generate a short TODO checklist for the following work:\n\n"
            f"{workflow_input}\n\n"
            f"{step.get('prompt', '')}\n\n"
            f"CRITICAL FORMAT RULES — follow EXACTLY:\n"
            f"- Output ONLY a markdown checklist using '- [ ] item' format.\n"
            f"- Maximum 5-8 items. Group related work into single items.\n"
            f"- Each item = a meaningful chunk of work, not a single file.\n"
            f"- DO NOT include any prose, explanation, status report, or headings.\n"
            f"- DO NOT number the items. Use ONLY '- [ ]' prefix.\n"
            f"- DO NOT create files or run commands — ONLY output the checklist.\n"
            f"- Last item should verify the result (e.g. run build/tests).\n\n"
            f"Example format:\n"
            f"- [ ] Create project config files (package.json, tsconfig, vite.config)\n"
            f"- [ ] Define TypeScript interfaces in src/types/\n"
            f"- [ ] Verify with pnpm install && pnpm tsc --noEmit\n"
        )
        thread_id = build_thread_id("workflow", TARGET_NAME, run_id, f"{step_name}-plan")
        logger.info("[opencode %s] generating plan from prompt...", step_name)
        try:
            wait_for_agent_runtime_ready(agent_ref, TARGET_NAMESPACE)
            plan_result = invoke_agent_runtime(
                agent_ref,
                TARGET_NAMESPACE,
                {
                    "prompt": plan_prompt,
                    "thread_id": thread_id,
                    "caller_agent_name": TARGET_NAME,
                    "caller_agent_namespace": TARGET_NAMESPACE,
                    "parent_thread_id": run_id,
                },
                timeout_seconds=float(execution_policy.get("timeoutSeconds", 300)),
            )
            _emit_traces_from_result(plan_result)
            plan_text = str(plan_result.get("response", ""))
        except Exception as exc:
            logger.exception("Failed to generate plan for loop step '%s': %s", step_name, exc)
            return {
                "state": "failed",
                "stepName": step_name,
                "stepResult": {"agentRef": step.get("agentRef", ""), "response": "", "status": "failed", "error": str(exc), "output": {"text": "", "json": None, "type": "empty"}, "attempts": 1},
                "stepState": build_step_state(step_name=step_name, step=step, status_name="failed", attempts=1, started_at=started_at, completed_at=now_iso(), latency_ms=0, worker_job=worker_job, execution_policy=execution_policy, error=f"Plan generation failed: {exc}"),
            }

    checklist = parse_plan_checklist(plan_text)
    if not checklist:
        checklist = [{"text": "Complete the assigned work", "done": False}]

    # Cap at 10 items — if the model returned too many, consolidate
    if len(checklist) > 10:
        logger.warning("[opencode %s] plan had %d items, truncating to 10", step_name, len(checklist))
        checklist = checklist[:10]

    logger.info("[opencode %s] plan generated — %d checklist items:", step_name, len(checklist))
    for i, item in enumerate(checklist, 1):
        logger.info("[opencode %s]   %d. %s", step_name, i, item.get("text", "?")[:120])

    # Use a single thread_id across all loop iterations so runtimes with
    # session persistence (e.g. opencode) maintain context between iterations.
    loop_thread_id = build_thread_id("workflow", TARGET_NAME, run_id, f"{step_name}-loop")

    previous_response = ""
    consecutive_completion_signals = 0
    successful_iterations = 0
    all_responses: list[str] = []
    all_artifacts: list[dict[str, Any]] = []
    all_tool_calls: list[dict[str, Any]] = []
    all_loop_warnings: list[str] = []
    iteration_failures: list[dict[str, Any]] = []
    loop_progress: dict[str, Any] = {
        "iteration": 0,
        "maxIterations": max_iterations,
        "completedItems": 0,
        "totalItems": len(checklist),
        "checklistItems": [{"text": c["text"], "done": c.get("done", False)} for c in checklist],
        "circuitBreakerState": circuit_breaker.to_dict(),
        "exitReason": None,
    }

    append_journal_event(
        "workflow.loop.started",
        {"runId": run_id, "step": step_name, "totalItems": len(checklist), "maxIterations": max_iterations},
    )
    try:
        wait_for_agent_runtime_ready(agent_ref, TARGET_NAMESPACE)
    except Exception as exc:
        logger.exception("Agent runtime not ready for loop step '%s': %s", step_name, exc)
        return {
            "state": "failed",
            "stepName": step_name,
            "stepResult": {
                "agentRef": agent_ref,
                "response": "",
                "status": "failed",
                "error": str(exc),
                "output": {"text": "", "json": None, "type": "empty"},
                "attempts": 0,
            },
            "stepState": build_step_state(
                step_name=step_name,
                step=step,
                status_name="failed",
                attempts=0,
                started_at=started_at,
                completed_at=now_iso(),
                latency_ms=0,
                worker_job=worker_job,
                execution_policy=execution_policy,
                error=str(exc),
                failure_class=type(exc).__name__,
            ),
        }

    for iteration in range(1, max_iterations + 1):
        loop_progress["iteration"] = iteration

        # Check circuit breaker
        if circuit_breaker.is_open():
            loop_progress["exitReason"] = "circuit_breaker_open"
            append_journal_event("workflow.loop.circuit_breaker_open", {"runId": run_id, "step": step_name, "iteration": iteration})
            break

        # Build iteration prompt
        prompt = build_loop_iteration_prompt(step, iteration, checklist, previous_response, workflow_input, project_context=project_context)
        thread_id = loop_thread_id

        append_journal_event(
            "workflow.loop.iteration.started",
            {"runId": run_id, "step": step_name, "iteration": iteration, "completedItems": sum(1 for c in checklist if c.get("done"))},
        )

        completed_items = sum(1 for c in checklist if c.get("done"))
        logger.info(
            "[opencode %s] === iteration %d/%d started — %d/%d items done ===",
            step_name, iteration, max_iterations, completed_items, len(checklist),
        )

        try:
            loop_invoke_payload: dict[str, Any] = {
                    "prompt": prompt,
                    "thread_id": thread_id,
                    "caller_agent_name": TARGET_NAME,
                    "caller_agent_namespace": TARGET_NAMESPACE,
                    "parent_thread_id": run_id,
                    "pre_authorized_actions": list(
                        execution_policy.get("preAuthorizedActions") or []
                    ),
            }
            if int(execution_policy.get("maxTurns", 0)):
                loop_invoke_payload["max_turns"] = int(execution_policy["maxTurns"])
            result = invoke_agent_runtime_stream(
                agent_ref,
                TARGET_NAMESPACE,
                loop_invoke_payload,
                timeout_seconds=float(execution_policy.get("timeoutSeconds", 300)),
                step_name=step_name,
                iteration=iteration,
            )
            _emit_traces_from_result(result)
            response_text = str(result.get("response", ""))
            successful_iterations += 1
            all_responses.append(response_text)
            previous_response = response_text
            # Collect rich response fields from runtimes that provide them
            all_artifacts.extend(result.get("artifacts") or [])
            all_tool_calls.extend(result.get("tool_calls") or [])
            all_loop_warnings.extend(result.get("warnings") or [])
            logger.info(
                "[opencode %s] iteration %d response: %d chars, tool_calls: %d",
                step_name, iteration, len(response_text),
                len(result.get("tool_calls") or []),
            )
        except Exception as exc:
            logger.warning("Loop iteration %d failed for step '%s': %s", iteration, step_name, exc)
            # Cancel the agent session to prevent orphaned processes.
            try:
                cancel_agent_session(agent_ref, TARGET_NAMESPACE, thread_id)
            except Exception as exc:
                logger.debug("Failed to cancel agent session after loop iteration failure: %s", exc, exc_info=True)
            circuit_breaker.record_progress(False)
            loop_progress["circuitBreakerState"] = circuit_breaker.to_dict()
            failure_entry = {
                "iteration": iteration,
                "error": str(exc),
                "failureClass": type(exc).__name__,
            }
            iteration_failures.append(failure_entry)
            append_journal_event(
                "workflow.loop.iteration.failed",
                {
                    "runId": run_id,
                    "step": step_name,
                    "iteration": iteration,
                    "error": str(exc),
                    "failureClass": type(exc).__name__,
                },
            )
            continue

        # Detect signals
        signals = detect_iteration_signals(response_text)

        if signals["no_progress"]:
            circuit_breaker.record_progress(False)
            consecutive_completion_signals = 0
        elif signals["item_complete"]:
            circuit_breaker.record_progress(True)
            # Mark current incomplete item as done
            for item in checklist:
                if not item.get("done"):
                    item["done"] = True
                    break
            consecutive_completion_signals = 0
        elif signals["plan_complete"]:
            consecutive_completion_signals += 1
            circuit_breaker.record_progress(True)
            # Mark all items done
            for item in checklist:
                item["done"] = True
        else:
            # Ambiguous — assume some progress
            circuit_breaker.record_progress(True)
            consecutive_completion_signals = 0

        loop_progress["completedItems"] = sum(1 for c in checklist if c.get("done"))
        loop_progress["checklistItems"] = [{"text": c["text"], "done": c.get("done", False)} for c in checklist]
        loop_progress["circuitBreakerState"] = circuit_breaker.to_dict()

        append_journal_event(
            "workflow.loop.iteration.completed",
            {"runId": run_id, "step": step_name, "iteration": iteration, "signals": signals, "completedItems": loop_progress["completedItems"]},
        )

        # Notify caller of iteration progress
        if on_iteration_complete:
            try:
                on_iteration_complete(loop_progress)
            except Exception as exc:
                logger.warning("on_iteration_complete callback failed: %s", exc, exc_info=True)

        # Check exit conditions
        all_done = all(c.get("done") for c in checklist)
        if plan_complete_exit and all_done:
            loop_progress["exitReason"] = "plan_complete"
            break
        if consecutive_completion_signals >= completion_signal_threshold:
            loop_progress["exitReason"] = "completion_signal_threshold"
            break
    else:
        loop_progress["exitReason"] = "max_iterations"

    completed_at = now_iso()
    latency_ms = int((time.perf_counter() - started_perf) * 1000)
    combined_response = "\n\n---\n\n".join(all_responses[-3:]) if all_responses else "(no iterations completed)"

    # When the loop had many iterations, the last-3 tail loses important
    # context for downstream agents.  Ask the agent (which still has its
    # full session) to produce a comprehensive handoff summary.
    if successful_iterations > 3 and all_responses:
        try:
            summary_prompt = (
                "Summarize ALL work completed across every iteration of this task. "
                "List every file created or modified with a one-line description of its purpose. "
                "List all TypeScript/code interfaces and types you defined. "
                "List all key architecture or configuration decisions. "
                "Be comprehensive — this summary is the ONLY context downstream agents will receive."
            )
            summary_result = invoke_agent_runtime(
                agent_ref,
                TARGET_NAMESPACE,
                {
                    "prompt": summary_prompt,
                    "thread_id": loop_thread_id,
                    "caller_agent_name": TARGET_NAME,
                    "caller_agent_namespace": TARGET_NAMESPACE,
                    "parent_thread_id": run_id,
                },
                timeout_seconds=float(execution_policy.get("timeoutSeconds", 300)),
            )
            summary_text = str(summary_result.get("response", "")).strip()
            if summary_text:
                combined_response = summary_text
                logger.info("Loop '%s': generated handoff summary (%d chars)", step_name, len(summary_text))
        except Exception as summary_exc:
            logger.warning("Loop '%s': handoff summary failed, using last-3 tail: %s", step_name, summary_exc)

    append_journal_event(
        "workflow.loop.completed",
        {
            "runId": run_id,
            "step": step_name,
            "iterations": loop_progress["iteration"],
            "completedItems": loop_progress["completedItems"],
            "exitReason": loop_progress["exitReason"],
            "successfulIterations": successful_iterations,
            "failedIterations": len(iteration_failures),
        },
    )

    exit_reason = loop_progress.get("exitReason", "")
    if successful_iterations == 0:
        result_status = "failed"
        loop_progress["exitReason"] = "all_iterations_failed"
    else:
        result_status = "continued" if exit_reason in ("max_iterations", "circuit_breaker_open") else "completed"
    result_state = result_status

    step_result = {
        "agentRef": agent_ref,
        "response": combined_response,
        "status": result_status,
        "output": {
            "text": combined_response,
            "json": {
                "loopProgress": loop_progress,
                "checklist": checklist,
                "iterationFailures": iteration_failures[-10:],
            },
            "type": "json",
        },
        "attempts": loop_progress["iteration"],
        "artifacts": all_artifacts,
        "tool_calls": all_tool_calls,
        "metadata": {"loopProgress": loop_progress, "iterationFailures": iteration_failures[-10:]},
        "warnings": all_loop_warnings,
    }
    if iteration_failures:
        step_result["warnings"].append(
            f"{len(iteration_failures)} loop iteration(s) failed; see iterationFailures for details."
        )
    if successful_iterations == 0 and iteration_failures:
        step_result["error"] = iteration_failures[-1]["error"]

    step_state = build_step_state(
        step_name=step_name,
        step=step,
        status_name=result_status,
        attempts=loop_progress["iteration"],
        started_at=started_at,
        completed_at=completed_at,
        latency_ms=latency_ms,
        worker_job=worker_job,
        execution_policy=execution_policy,
        error=(iteration_failures[-1]["error"] if successful_iterations == 0 and iteration_failures else None),
        failure_class=(iteration_failures[-1]["failureClass"] if successful_iterations == 0 and iteration_failures else None),
    )
    step_state["loopProgress"] = loop_progress
    if iteration_failures:
        step_state["iterationFailures"] = iteration_failures[-10:]

    return {
        "state": result_state,
        "stepName": step_name,
        "stepResult": step_result,
        "stepState": step_state,
    }


# ---------------------------------------------------------------------------
# Conditional step execution
# ---------------------------------------------------------------------------

# Allowed operators for safe condition expression evaluation.
_CONDITION_OPS: dict[str, Any] = {
    "contains": lambda text, substr: str(substr).lower() in str(text).lower(),
    "equals": lambda text, target: str(text).strip() == str(target).strip(),
    "not_equals": lambda text, target: str(text).strip() != str(target).strip(),
    "starts_with": lambda text, prefix: str(text).lower().startswith(str(prefix).lower()),
    "ends_with": lambda text, suffix: str(text).lower().endswith(str(suffix).lower()),
    "length_gt": lambda text, n: len(str(text)) > int(n),
    "length_lt": lambda text, n: len(str(text)) < int(n),
    "is_empty": lambda text: len(str(text).strip()) == 0,
    "not_empty": lambda text: len(str(text).strip()) > 0,
    "matches": lambda text, pattern: bool(re.search(str(pattern), str(text))),
}


def evaluate_condition_expr(
    expr: str,
    context: dict[str, Any],
) -> bool:
    """Evaluate a safe condition expression against step results context.

    Supported expression forms:
        contains("substring")
        equals("value")
        not_equals("value")
        starts_with("prefix")
        ends_with("suffix")
        length_gt(100)
        length_lt(10)
        is_empty()
        not_empty()
        matches("regex_pattern")
        not <expr>           — negation
        <expr> and <expr>    — conjunction
        <expr> or <expr>     — disjunction
        true / false         — literals

    The implicit input is ``context["previous_output"]``.
    """
    expr = expr.strip()
    if not expr:
        return True

    # Boolean literals
    if expr.lower() == "true":
        return True
    if expr.lower() == "false":
        return False

    # Negation
    if expr.lower().startswith("not "):
        return not evaluate_condition_expr(expr[4:], context)

    # Conjunction / disjunction (split on outermost 'and'/'or')
    for connective, combiner in [(" or ", any), (" and ", all)]:
        # Only split at the outermost level (not inside parens/quotes)
        parts = _split_connective(expr, connective)
        if len(parts) > 1:
            return combiner(evaluate_condition_expr(p, context) for p in parts)

    # Function-style: op("arg") or op(number) or op()
    match = re.match(r'^(\w+)\((.*)?\)$', expr, re.DOTALL)
    if match:
        op_name = match.group(1).lower()
        raw_arg = (match.group(2) or "").strip()
        if op_name not in _CONDITION_OPS:
            raise ValueError(f"Unknown condition operator: {op_name}")

        previous_output = str(context.get("previous_output", ""))
        func = _CONDITION_OPS[op_name]

        # Unary operators (no argument)
        if op_name in ("is_empty", "not_empty"):
            return func(previous_output)

        # Strip surrounding quotes from argument
        arg = raw_arg.strip("\"'")
        return func(previous_output, arg)

    raise ValueError(f"Cannot parse condition expression: {expr!r}")


def _split_connective(expr: str, connective: str) -> list[str]:
    """Split *expr* on *connective* only when not inside quotes or parentheses."""
    parts: list[str] = []
    depth = 0
    in_quote: str | None = None
    start = 0
    i = 0
    lowered = expr.lower()
    while i < len(expr):
        ch = expr[i]
        if in_quote:
            if ch == in_quote and (i == 0 or expr[i - 1] != "\\"):
                in_quote = None
        elif ch in ('"', "'"):
            in_quote = ch
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif depth == 0 and in_quote is None and lowered[i: i + len(connective)] == connective:
            parts.append(expr[start:i].strip())
            i += len(connective)
            start = i
            continue
        i += 1
    parts.append(expr[start:].strip())
    return parts


def execute_conditional_step(
    step: dict[str, Any],
    workflow_input: str,
    step_results: dict[str, dict[str, Any]],
    run_id: str,
    worker_job: dict[str, Any],
) -> dict[str, Any]:
    """Execute a conditional-type workflow step.

    Evaluates the ``conditionExpr`` against previous step outputs and returns
    the list of branch step names to activate (thenSteps or elseSteps) and
    the list to skip.
    """
    step_name = str(step.get("name", "")).strip()
    condition_expr = str(step.get("conditionExpr", "true")).strip()
    then_steps: list[str] = [str(s).strip() for s in (step.get("thenSteps") or []) if str(s).strip()]
    else_steps: list[str] = [str(s).strip() for s in (step.get("elseSteps") or []) if str(s).strip()]

    dependencies = [str(dep).strip() for dep in step.get("dependsOn") or [] if str(dep).strip()]
    previous_output = previous_output_for_dependencies(dependencies, step_results)

    execution_policy = normalize_step_execution(step)
    started_at = now_iso()
    started_perf = time.perf_counter()

    context = {
        "previous_output": previous_output,
        "workflow_input": workflow_input,
        "step_results": step_results,
    }

    append_journal_event(
        "workflow.conditional.evaluating",
        {"runId": run_id, "step": step_name, "expression": condition_expr},
    )

    try:
        result = evaluate_condition_expr(condition_expr, context)
    except Exception as exc:
        latency_ms = int((time.perf_counter() - started_perf) * 1000)
        completed_at = now_iso()
        logger.exception("Conditional expression evaluation failed for step '%s': %s", step_name, exc)
        append_journal_event(
            "workflow.conditional.error",
            {"runId": run_id, "step": step_name, "error": str(exc)},
        )
        return {
            "state": "failed",
            "stepName": step_name,
            "stepResult": {"response": f"Condition evaluation error: {exc}", "status": "error"},
            "stepState": build_step_state(
                step_name=step_name,
                step=step,
                status_name="failed",
                attempts=1,
                started_at=started_at,
                completed_at=completed_at,
                latency_ms=latency_ms,
                worker_job=worker_job,
                execution_policy=execution_policy,
                error=str(exc),
                failure_class="condition_eval_error",
            ),
            "branchTaken": None,
            "activateSteps": [],
            "skipSteps": then_steps + else_steps,
        }

    latency_ms = int((time.perf_counter() - started_perf) * 1000)
    completed_at = now_iso()
    branch_taken = "then" if result else "else"
    activate_steps = then_steps if result else else_steps
    skip_steps = else_steps if result else then_steps

    append_journal_event(
        "workflow.conditional.resolved",
        {
            "runId": run_id,
            "step": step_name,
            "expression": condition_expr,
            "result": result,
            "branchTaken": branch_taken,
            "activateSteps": activate_steps,
            "skipSteps": skip_steps,
        },
    )

    response_text = (
        f"Condition '{condition_expr}' evaluated to {result}. "
        f"Branch taken: {branch_taken}. "
        f"Activating steps: {activate_steps or ['(none)']}."
    )

    return {
        "state": "completed",
        "stepName": step_name,
        "stepResult": {
            "response": response_text,
            "status": "completed",
            "conditionResult": result,
            "branchTaken": branch_taken,
        },
        "stepState": build_step_state(
            step_name=step_name,
            step=step,
            status_name="completed",
            attempts=1,
            started_at=started_at,
            completed_at=completed_at,
            latency_ms=latency_ms,
            worker_job=worker_job,
            execution_policy=execution_policy,
        ),
        "branchTaken": branch_taken,
        "activateSteps": activate_steps,
        "skipSteps": skip_steps,
    }


# Patterns that indicate actionable review criteria (commands to execute,
# not just evaluation criteria to judge against).
_ACTIONABLE_CRITERIA_RE = re.compile(
    r"""
    (?:^|\s)(?:run|execute|merge|build|install|test|deploy|start|create|clone|pull|push|checkout)\s  # imperative verbs
    | `[^`]{3,}`           # inline code spans (likely commands)
    | (?:^|\s)(?:pnpm|npm|npx|yarn|pip|pytest|git|make|cargo|docker|kubectl)\s  # CLI tool names
    | \$\s*\w              # shell-style $command
    """,
    re.IGNORECASE | re.VERBOSE,
)


def _review_criteria_is_actionable(criteria: str) -> bool:
    """Return True if *criteria* contains executable actions (commands, tool invocations).

    When actionable, the review prompt should instruct the agent to *execute*
    the criteria rather than merely evaluate the output text.
    """
    if not criteria:
        return False
    return _ACTIONABLE_CRITERIA_RE.search(criteria) is not None


class ReviewRejectedError(RuntimeError):
    def __init__(self, message: str, review_result: dict[str, Any]):
        super().__init__(message)
        self.review_result = review_result


def execute_review_step(
    step: dict[str, Any],
    workflow_input: str,
    step_results: dict[str, dict[str, Any]],
    run_id: str,
    worker_job: dict[str, Any],
    project_context: str = "",
) -> dict[str, Any]:
    """Execute a review-type workflow step.

    Constructs a review prompt from ``reviewCriteria`` + dependency outputs,
    invokes the agent, and parses the response for APPROVED / REJECTED with
    structured findings.
    """
    step_name = str(step.get("name", "")).strip()
    review_criteria = str(step.get("reviewCriteria", "") or "").strip()
    dependencies = [
        str(dep).strip()
        for dep in step.get("dependsOn") or []
        if str(dep).strip()
    ]
    previous_output = previous_output_for_dependencies(dependencies, step_results)
    execution_policy = normalize_step_execution(step)
    started_at = now_iso()
    agent_ref = str(step.get("agentRef", ""))
    previous_failure_class = ""
    previous_error_text = ""

    actionable = _review_criteria_is_actionable(review_criteria)
    if actionable:
        review_prompt_body = (
            "You are a reviewer with execution authority. Execute the review criteria "
            "step by step in the workspace, then determine whether the work passes.\n\n"
            f"## Review Criteria (execute each item)\n{review_criteria}\n\n"
            f"## Prior Step Output (for reference)\n{previous_output}\n\n"
            "## Important\n"
            "- Check the actual files in /workspace rather than relying solely on the summaries above.\n"
            "- Run every command listed in the criteria and report its output.\n"
            "- After executing all criteria, respond with exactly APPROVED or REJECTED on the first line.\n"
            "- Then provide specific findings as a numbered list."
        )
    else:
        review_prompt_body = (
            "You are a reviewer. Evaluate the following output against the review criteria.\n\n"
            f"## Review Criteria\n{review_criteria}\n\n"
            f"## Output to Review\n{previous_output}\n\n"
            "## Instructions\n"
            "- Check the actual files in /workspace rather than relying solely on the summaries above.\n"
            "- Respond with exactly APPROVED or REJECTED on the first line.\n"
            "- Then provide specific findings as a numbered list."
        )
    review_prompt = f"[Project Context]\n{project_context}\n\n{review_prompt_body}" if project_context else review_prompt_body

    append_journal_event(
        "workflow.review.started",
        {"runId": run_id, "step": step_name, "criteria": review_criteria, "actionable": actionable},
    )

    for attempt in range(1, int(execution_policy["maxAttempts"]) + 1):
        started_perf = time.perf_counter()
        try:
            wait_for_agent_runtime_ready(agent_ref, TARGET_NAMESPACE)
            thread_id = build_thread_id("review", TARGET_NAME, run_id, step_name)
            effective_review_prompt = review_prompt
            if attempt > 1:
                effective_review_prompt = build_retry_prompt(
                    base_prompt=review_prompt,
                    attempt=attempt,
                    step_name=step_name,
                    failure_class=previous_failure_class,
                    error_text=previous_error_text,
                    missing_paths=[],
                )
            review_invoke_payload: dict[str, Any] = {
                    "prompt": effective_review_prompt,
                    "thread_id": thread_id,
                    "caller_agent_name": TARGET_NAME,
                    "caller_agent_namespace": TARGET_NAMESPACE,
                    "parent_thread_id": run_id,
            }
            if int(execution_policy.get("maxTurns", 0)):
                review_invoke_payload["max_turns"] = int(execution_policy["maxTurns"])
            result = invoke_agent_runtime(
                agent_ref,
                TARGET_NAMESPACE,
                review_invoke_payload,
                timeout_seconds=float(execution_policy["timeoutSeconds"]),
            )
            latency_ms = int((time.perf_counter() - started_perf) * 1000)
            response_text = str(result.get("response", "")).strip()
            first_line = response_text.split("\n", 1)[0].strip().upper()
            approved = first_line.startswith("APPROVED")

            review_result = {
                "approved": approved,
                "verdict": "APPROVED" if approved else "REJECTED",
                "response": response_text,
                "criteria": review_criteria,
            }

            if not approved:
                raise ReviewRejectedError(
                    f"Review rejected for step '{step_name}': {response_text[:500]}",
                    review_result,
                )

            completed_at = now_iso()
            append_journal_event(
                "workflow.review.completed",
                {
                    "runId": run_id,
                    "step": step_name,
                    "approved": approved,
                    "latencyMs": latency_ms,
                },
            )

            step_state = build_step_state(
                step_name=step_name,
                step=step,
                status_name="completed",
                attempts=attempt,
                started_at=started_at,
                completed_at=completed_at,
                latency_ms=latency_ms,
                worker_job=worker_job,
                execution_policy=execution_policy,
            )
            step_state["reviewResult"] = review_result

            return {
                "state": "completed",
                "stepName": step_name,
                "stepResult": {
                    "agentRef": step.get("agentRef", ""),
                    "response": response_text,
                    "thread_id": result.get("thread_id", thread_id),
                    "status": "completed",
                    "reviewResult": review_result,
                    "output": {"text": response_text, "json": None, "type": "text"},
                    "attempts": attempt,
                },
                "stepState": step_state,
            }
        except Exception as exc:
            latency_ms = int((time.perf_counter() - started_perf) * 1000)
            completed_at = now_iso()
            thread_id = build_thread_id("review", TARGET_NAME, run_id, step_name)
            previous_failure_class = type(exc).__name__
            previous_error_text = str(exc)

            # Cancel the running session to prevent orphaned agent
            # processes from consuming resources after a timeout.
            try:
                cancel_agent_session(agent_ref, TARGET_NAMESPACE, thread_id)
            except Exception as exc:
                logger.debug("Failed to cancel agent session during review attempt cleanup: %s", exc, exc_info=True)

            append_journal_event(
                "workflow.review.attempt.failed",
                {
                    "runId": run_id,
                    "step": step_name,
                    "attempt": attempt,
                    "latencyMs": latency_ms,
                    "error": str(exc),
                    "failureClass": type(exc).__name__,
                },
            )
            should_retry = (
                bool(execution_policy["retryable"])
                and attempt < int(execution_policy["maxAttempts"])
            )
            if should_retry:
                backoff = min(
                    float(execution_policy["backoffSeconds"]) * (2 ** (attempt - 1)),
                    300.0,
                )
                append_journal_event(
                    "workflow.review.retrying",
                    {
                        "runId": run_id,
                        "step": step_name,
                        "attempt": attempt,
                        "sleepSeconds": backoff,
                    },
                )
                if backoff > 0:
                    time.sleep(backoff)
                continue

            append_journal_event(
                "workflow.review.failed",
                {"runId": run_id, "step": step_name, "error": str(exc)},
            )
            terminal_state = "continued" if bool(execution_policy["continueOnError"]) else "failed"
            review_result = exc.review_result if isinstance(exc, ReviewRejectedError) else None
            step_state = build_step_state(
                step_name=step_name,
                step=step,
                status_name=terminal_state,
                attempts=attempt,
                started_at=started_at,
                completed_at=completed_at,
                latency_ms=latency_ms,
                worker_job=worker_job,
                execution_policy=execution_policy,
                error=str(exc),
                failure_class=type(exc).__name__,
            )
            if review_result:
                step_state["reviewResult"] = review_result
            return {
                "state": terminal_state,
                "stepName": step_name,
                "stepResult": {
                    "agentRef": step.get("agentRef", ""),
                    "response": "",
                    "thread_id": thread_id,
                    "status": terminal_state,
                    "error": str(exc),
                    "reviewResult": review_result,
                    "output": {"text": "", "json": None, "type": "empty"},
                    "attempts": attempt,
                },
                "stepState": step_state,
            }

    # Should not reach here but satisfy type checker
    raise RuntimeError(f"Review step '{step_name}' exhausted all attempts")


def run_workflow_worker() -> None:
    plural = resource_plural()
    resource = get_resource(plural)
    spec = resource.get("spec", {})
    metadata = resource.get("metadata", {})
    status = resource.get("status", {}) or {}
    steps = spec.get("steps") or []
    step_order = {
        str(step.get("name", "")).strip(): index
        for index, step in enumerate(steps)
        if str(step.get("name", "")).strip()
    }
    graph = validate_workflow_graph(steps)

    generation = int(metadata.get("generation", 1))
    artifact = load_artifact()
    run_id = resolve_workflow_run_id_for_worker(status, artifact, generation)
    worker_job = {
        "name": WORKER_JOB_NAME,
        "namespace": OPERATOR_NAMESPACE,
    }
    artifact_matches_generation, step_results, step_states, pending_approval, started_at = (
        resume_workflow_state_from_artifact(
            status,
            artifact,
            generation,
            run_id,
        )
    )
    completed = {
        step_name
        for step_name, result in step_results.items()
        if str(result.get("status", "")).strip() in {"completed", "continued"}
    }
    skipped: set[str] = set()  # steps skipped by conditional branches

    append_journal_event(
        (
            "workflow.started"
            if not artifact_matches_generation
            else "workflow.resumed"
        ),
        {
            "runId": run_id,
            "generation": generation,
            "topology": graph.get("topologicalOrder") or [],
        },
    )

    # Load project context from ConfigMap if contextRef is set
    project_context = ""
    context_ref = str(spec.get("contextRef", "") or "").strip()
    if context_ref:
        try:
            cm = kubernetes.client.CoreV1Api().read_namespaced_config_map(
                name=context_ref, namespace=TARGET_NAMESPACE,
            )
            cm_data = cm.data or {}
            project_context = "\n\n".join(
                f"## {key}\n{value}" for key, value in sorted(cm_data.items())
            )
            append_journal_event(
                "workflow.context.loaded",
                {"runId": run_id, "contextRef": context_ref, "keys": sorted(cm_data.keys())},
            )
            logger.info("Loaded project context from ConfigMap '%s' (%d keys)", context_ref, len(cm_data))
        except Exception as ctx_exc:
            logger.warning("Failed to load contextRef ConfigMap '%s': %s", context_ref, ctx_exc)
            append_journal_event(
                "workflow.context.error",
                {"runId": run_id, "contextRef": context_ref, "error": str(ctx_exc)},
            )

    # Inject git repository context so agents know the repo URL and workspace setup
    git_repo_url = os.getenv("GIT_REPO_URL", "").strip()
    if git_repo_url:
        git_context = (
            "## Git Repository\n"
            f"Target repository: {git_repo_url}\n"
            "The workspace directory is /workspace. "
            "If /workspace is not already a git repo, clone the repository into /workspace "
            "using `git_clone` with target_dir='/workspace' before creating files. "
            "After making changes, commit and push to the repository."
        )
        project_context = f"{project_context}\n\n{git_context}" if project_context else git_context

    current_step = str(status.get("currentStep", "") or "")
    if str(status.get("phase", "") or "") == "waiting-approval":
        _patch_pending_approval_label(None)
    patch_workflow_status(
        plural=plural,
        phase="running",
        generation=generation,
        run_id=run_id,
        total_steps=len(steps),
        current_step=current_step,
        started_at=started_at,
        step_states=step_states,
        worker_job=worker_job,
        pending_approval=None,
    )
    # §2.5 — DB mirroring is now handled by the status projection controller.

    global _CURRENT_EXECUTION_ID  # noqa: PLW0603 — module-level used by nested funcs

    # §2.6 — Detect "ghost" executions: if the artifact was loaded and ALL
    # steps are already completed, this worker has nothing to do.  Skip trace
    # reporting so the Observatory only shows real runs.
    _is_ghost_run = artifact_matches_generation and len(completed) >= len(steps) and len(steps) > 0

    execution_id = ""
    try:
        if not _is_ghost_run:
            try:
                execution_id = trace_client.start_execution(
                    namespace=TARGET_NAMESPACE,
                    workflow_name=TARGET_NAME,
                    agent_name=TARGET_NAME,
                    run_id=run_id,
                    inputs={"input": spec.get("input")},
                    triggered_by="workflow-worker",
                )
            except Exception:
                logger.warning("Trace start_execution failed", exc_info=True)
                execution_id = ""
            if execution_id:
                _CURRENT_EXECUTION_ID = execution_id
                if runtime_events is not None:
                    runtime_events.emit_workflow_started(
                        execution_id=execution_id,
                        workflow_name=TARGET_NAME,
                        namespace=TARGET_NAMESPACE,
                        run_id=run_id,
                    )
        logger.info(
            "Trace state: execution_id=%s, artifact_matches=%s, completed=%d/%d, run_id=%s, ghost=%s",
            execution_id or "(none)", artifact_matches_generation, len(completed), len(steps), run_id, _is_ghost_run,
        )

        # Compute execution waves for logging and progress visibility
        waves = compute_execution_waves(steps, completed, skipped)
        wave_names = [
            [str(s.get("name", "")) for s in w] for w in waves
        ]
        append_journal_event(
            "workflow.waves.computed",
            {"runId": run_id, "waveCount": len(waves), "waves": wave_names},
        )
        logger.info("Computed %d execution waves for workflow '%s'", len(waves), TARGET_NAME)

        # §2.6 — Ghost-run early exit: artifact loaded everything as already
        # completed.  Nothing to execute.  Do NOT write a new artifact, do NOT
        # patch CRD status (the previous worker already did both), and do NOT
        # emit trace events.  Just release the lease and exit cleanly.
        if _is_ghost_run:
            logger.info(
                "Ghost run detected for workflow '%s' (run_id=%s) — "
                "all %d steps already completed from stale artifact.  Exiting early.",
                TARGET_NAME, run_id, len(steps),
            )
            append_journal_event(
                "workflow.ghost_run.skipped",
                {"runId": run_id, "completedSteps": len(completed), "totalSteps": len(steps)},
            )
            return  # ← exits the try block; finally/lease-release still runs

        current_wave_index = 0

        def _execute_frontier_step(
            step: dict[str, Any],
            pending: dict[str, Any] | None,
            on_iteration_complete: Any = None,
            on_todo_update: Any = None,
        ) -> dict[str, Any]:
            step_name = str(step.get("name", "")).strip()
            step_type = str(step.get("type", "agent")).strip()
            _trace_step_id = ""
            if _CURRENT_EXECUTION_ID:
                try:
                    _trace_step_id = trace_client.start_step(
                        execution_id=_CURRENT_EXECUTION_ID,
                        step_name=step_name,
                        step_type=step_type,
                        step_index=step_order.get(step_name),
                        inputs={"step": step_name, "type": step_type},
                    )
                except Exception:
                    logger.warning("Trace start_step failed", exc_info=True)
            if _CURRENT_EXECUTION_ID and _trace_step_id:
                _trace_context.execution_id = _CURRENT_EXECUTION_ID
                _trace_context.step_id = _trace_step_id
            _trace_status = "failed"
            _trace_error: str | None = None
            try:
                if step_type == "loop":
                    outcome = execute_loop_step(
                        step,
                        str(spec.get("input", "")),
                        step_results,
                        run_id,
                        worker_job,
                        on_iteration_complete=on_iteration_complete,
                        project_context=project_context,
                    )
                elif step_type == "review":
                    outcome = execute_review_step(
                        step,
                        str(spec.get("input", "")),
                        step_results,
                        run_id,
                        worker_job,
                        project_context=project_context,
                    )
                elif step_type == "conditional":
                    outcome = execute_conditional_step(
                        step,
                        str(spec.get("input", "")),
                        step_results,
                        run_id,
                        worker_job,
                    )
                else:
                    outcome = execute_workflow_step(
                        step,
                        str(spec.get("input", "")),
                        step_results,
                        run_id,
                        pending,
                        worker_job,
                        project_context=project_context,
                        on_todo_update=on_todo_update,
                    )
                _trace_status = "completed" if outcome.get("state") in {"completed", "continued"} else (
                    "cancelled" if outcome.get("state") == "approval_pending" else "failed"
                )
                return outcome
            except Exception as _step_exc:
                _trace_error = str(_step_exc)
                raise
            finally:
                if hasattr(_trace_context, "execution_id"):
                    delattr(_trace_context, "execution_id")
                if hasattr(_trace_context, "step_id"):
                    delattr(_trace_context, "step_id")
                if _CURRENT_EXECUTION_ID and _trace_step_id:
                    try:
                        trace_client.end_step(
                            execution_id=_CURRENT_EXECUTION_ID,
                            step_id=_trace_step_id,
                            status=_trace_status,
                            error_message=_trace_error,
                        )
                    except Exception:
                        logger.warning("Trace end_step failed", exc_info=True)

        fatal_failures: list[dict[str, Any]] = []
        while len(completed) + len(skipped) < len(steps):
            if is_shutting_down():
                raise RuntimeError("Worker shutdown initiated — aborting workflow execution")
            ready = ready_workflow_steps(steps, completed, skipped_steps=skipped)
            if not ready:
                raise ValueError(
                    "Workflow contains a dependency cycle "
                    "or unresolved dependency"
                )

            # Track wave transitions
            ready_names_set = {str(s.get("name", "")) for s in ready}
            if current_wave_index < len(waves):
                wave_step_names = {str(s.get("name", "")) for s in waves[current_wave_index]}
                if not wave_step_names & ready_names_set:
                    current_wave_index += 1
                    if current_wave_index < len(waves):
                        append_journal_event(
                            "workflow.wave.started",
                            {"runId": run_id, "wave": current_wave_index, "steps": sorted(ready_names_set)},
                        )

            non_approval_frontier = [
                step
                for step in ready
                if not bool(step.get("requireApproval", False))
            ]
            frontier = non_approval_frontier or ready[:1]
            frontier_names = [str(step.get("name", "")) for step in frontier]
            frontier_label = ", ".join(frontier_names)
            current_step = frontier_label
            append_journal_event(
                "workflow.frontier.started",
                {"runId": run_id, "steps": frontier_names},
            )
            # Mark frontier steps as "running" before execution so the UI
            # shows the correct status instead of "pending".
            for f_step in frontier:
                f_name = str(f_step.get("name", ""))
                existing = step_states.get(f_name, {})
                step_states[f_name] = {
                    **existing,
                    "stepName": f_name,
                    "agentRef": str(f_step.get("agentRef", "")),
                    "status": "running",
                    "startedAt": existing.get("startedAt") or now_iso(),
                    "updatedAt": now_iso(),
                }
            patch_workflow_status(
                plural=plural,
                phase="running",
                generation=generation,
                run_id=run_id,
                total_steps=len(steps),
                current_step=frontier_label,
                started_at=started_at,
                step_states=step_states,
                worker_job=worker_job,
                pending_approval=None,
                extra_summary={"currentFrontier": frontier_names},
            )
            # §2.5 — DB mirroring is now handled by the status projection controller.

            # Build a todo-update callback that propagates agent plan/progress
            # to the CRD stepStates so the UI can show plan items.
            # Track the last-seen todo signature per step so that stale todos
            # from a shared session (sessionGroup) are not propagated to a
            # new step that hasn't created its own todos yet.
            _todo_first_seen: dict[str, bool] = {}

            def _make_todo_callback(sn: str):
                _todo_first_seen[sn] = False  # noqa: B023 — _todo_first_seen is initialized once, not a loop var

                def _on_todo(
                    todos: list[dict[str, Any]],
                    _sn: str = sn,
                    _seen: dict[str, bool] = _todo_first_seen,  # noqa: B023 � initialized once, not a loop var
                ) -> None:
                    checklist = [
                        {"text": str(t.get("content", t.get("text", ""))), "done": str(t.get("status", "")).lower() in {"done", "completed"}}
                        for t in todos
                        if isinstance(t, dict) and (t.get("content") or t.get("text"))
                    ]
                    if not checklist:
                        return
                    # On the very first callback for this step, if ALL items
                    # are already done this is stale data from a previous step
                    # in the same shared session — skip it.
                    if not _seen.get(_sn):
                        _seen[_sn] = True
                        if all(c["done"] for c in checklist):
                            return
                    done_count = sum(1 for c in checklist if c["done"])
                    step_states[sn] = step_states.get(sn, {})
                    step_states[sn]["planProgress"] = {
                        "items": checklist,
                        "completedItems": done_count,
                        "totalItems": len(checklist),
                    }
                    step_states[sn]["updatedAt"] = now_iso()
                    patch_workflow_status(
                        plural=plural, phase="running", generation=generation,
                        run_id=run_id, total_steps=len(steps), current_step=sn,
                        started_at=started_at, step_states=step_states, worker_job=worker_job,
                        pending_approval=None,
                    )
                return _on_todo

            outcome_by_name: dict[str, dict[str, Any]] = {}
            if len(frontier) == 1:
                step = frontier[0]
                step_type = str(step.get("type", "agent")).strip()
                _on_iteration_cb = None
                if step_type == "loop":
                    def _on_iteration(progress: dict[str, Any], _step_name: str = str(step.get("name", ""))) -> None:
                        step_states[_step_name] = step_states.get(_step_name, {})
                        step_states[_step_name]["loopProgress"] = progress
                        patch_workflow_status(
                            plural=plural, phase="running", generation=generation,
                            run_id=run_id, total_steps=len(steps), current_step=_step_name,
                            started_at=started_at, step_states=step_states, worker_job=worker_job,
                            pending_approval=None, extra_summary={"loopProgress": progress},
                        )
                    _on_iteration_cb = _on_iteration
                outcome = _execute_frontier_step(
                    step,
                    pending_approval or None,
                    on_iteration_complete=_on_iteration_cb,
                    on_todo_update=_make_todo_callback(str(step.get("name", ""))),
                )
                outcome_by_name[outcome["stepName"]] = outcome
            else:
                frontier_timeout = max(
                    float(normalize_step_execution(f_step).get("timeoutSeconds", 600))
                    for f_step in frontier
                ) + 120  # step timeout + buffer
                # Thread-safe progress callback for parallel loop steps
                _progress_lock = threading.Lock()

                def _make_parallel_on_iteration(step_name: str):
                    def _on_iter(
                        progress: dict[str, Any],
                        _sn: str = step_name,
                        _lock: threading.Lock = _progress_lock,  # noqa: B023 — initialized once, not a loop var
                    ) -> None:
                        with _lock:
                            step_states[_sn] = step_states.get(_sn, {})
                            step_states[_sn]["loopProgress"] = progress
                            patch_workflow_status(
                                plural=plural, phase="running", generation=generation,
                                run_id=run_id, total_steps=len(steps), current_step=_sn,
                                started_at=started_at, step_states=step_states, worker_job=worker_job,
                                pending_approval=None, extra_summary={"loopProgress": progress},
                            )
                    return _on_iter

                def _make_parallel_todo_callback(step_name: str):
                    _todo_first_seen[step_name] = False  # noqa: B023 — initialized once, not a loop var

                    def _on_todo(
                        todos: list[dict[str, Any]],
                        _sn: str = step_name,
                        _seen: dict[str, bool] = _todo_first_seen,  # noqa: B023 — initialized once, not a loop var
                        _lock: threading.Lock = _progress_lock,  # noqa: B023 — initialized once, not a loop var
                    ) -> None:
                        checklist = [
                            {"text": str(t.get("content", t.get("text", ""))), "done": str(t.get("status", "")).lower() in {"done", "completed"}}
                            for t in todos
                            if isinstance(t, dict) and (t.get("content") or t.get("text"))
                        ]
                        if not checklist:
                            return
                        # Skip stale todos from a previous step in a shared session.
                        with _lock:
                            if not _seen.get(_sn):
                                _seen[_sn] = True
                                if all(c["done"] for c in checklist):
                                    return
                            done_count = sum(1 for c in checklist if c["done"])
                            step_states[step_name] = step_states.get(step_name, {})
                            step_states[step_name]["planProgress"] = {
                                "items": checklist,
                                "completedItems": done_count,
                                "totalItems": len(checklist),
                            }
                            step_states[step_name]["updatedAt"] = now_iso()
                            patch_workflow_status(
                                plural=plural, phase="running", generation=generation,
                                run_id=run_id, total_steps=len(steps), current_step=step_name,
                                started_at=started_at, step_states=step_states, worker_job=worker_job,
                                pending_approval=None,
                            )
                    return _on_todo

                # §2.7 — Cap parallel workers to MAX_PARALLEL_STEPS.
                effective_workers = min(len(frontier), MAX_PARALLEL_STEPS)
                if effective_workers < len(frontier):
                    logger.info(
                        "Throttling parallel frontier [%s]: %d steps capped to %d workers (MAX_PARALLEL_STEPS=%d).",
                        frontier_label, len(frontier), effective_workers, MAX_PARALLEL_STEPS,
                    )
                with ThreadPoolExecutor(max_workers=effective_workers) as executor:
                    future_map = {
                        executor.submit(
                            _execute_frontier_step,
                            step,
                            None,
                            _make_parallel_on_iteration(str(step.get("name", "")))
                            if str(step.get("type", "agent")).strip() == "loop"
                            else None,
                            _make_parallel_todo_callback(str(step.get("name", ""))),
                        ): str(step.get("name", ""))
                        for step in frontier
                    }
                    try:
                        # §2.7 — Fail fast: cancel siblings when the first step raises.
                        done, not_done = concurrent.futures.wait(
                            future_map, timeout=frontier_timeout, return_when=concurrent.futures.FIRST_EXCEPTION,
                        )
                        # Collect results from completed futures; re-raise the first exception.
                        first_exception: BaseException | None = None
                        for future in done:
                            exc = future.exception()
                            if exc is not None:
                                first_exception = first_exception or exc
                            else:
                                outcome = future.result()
                                outcome_by_name[outcome["stepName"]] = outcome
                        if first_exception is not None:
                            for f in not_done:
                                f.cancel()
                            raise first_exception from None
                        # If FIRST_EXCEPTION returned but some are still pending, gather remaining.
                        if not_done:
                            done2, timed_out = concurrent.futures.wait(
                                not_done, timeout=frontier_timeout, return_when=concurrent.futures.ALL_COMPLETED,
                            )
                            for future in done2:
                                exc = future.exception()
                                if exc is not None:
                                    raise exc from None
                                outcome = future.result()
                                outcome_by_name[outcome["stepName"]] = outcome
                            if timed_out:
                                for f in timed_out:
                                    f.cancel()
                                raise RuntimeError(
                                    f"Parallel frontier [{frontier_label}] timed out after {frontier_timeout:.0f}s"
                                )
                    except concurrent.futures.TimeoutError:
                        for f in future_map:
                            f.cancel()
                        raise RuntimeError(
                            f"Parallel frontier [{frontier_label}] timed out after {frontier_timeout:.0f}s"
                        ) from None

            pending_approval = {}
            fatal_failures: list[dict[str, Any]] = []
            for step in frontier:
                step_name = str(step.get("name", ""))
                outcome = outcome_by_name[step_name]
                # Preserve planProgress that was set by the todo callback
                # before overwriting with the final step state.
                existing_plan = (step_states.get(step_name) or {}).get("planProgress")
                step_states[step_name] = outcome["stepState"]
                if existing_plan:
                    step_states[step_name]["planProgress"] = existing_plan

                if outcome["state"] == "approval_pending":
                    pending_approval = outcome["pendingApproval"]
                    current_step = step_name
                    if "stepResult" in outcome:
                        step_results[step_name] = outcome["stepResult"]
                    snapshot = workflow_snapshot(
                        generation=generation,
                        run_id=run_id,
                        started_at=started_at,
                        current_step=step_name,
                        step_results=step_results,
                        step_states=step_states,
                        pending_approval=pending_approval,
                    )
                    write_artifact(snapshot)
                    patch_workflow_status(
                        plural=plural,
                        phase="waiting-approval",
                        generation=generation,
                        run_id=run_id,
                        total_steps=len(steps),
                        current_step=step_name,
                        started_at=started_at,
                        step_states=step_states,
                        worker_job=worker_job,
                        pending_approval=pending_approval,
                        extra_summary={"currentFrontier": frontier_names},
                    )
                    # §2.5 — DB mirroring is now handled by the status projection controller.
                    _patch_pending_approval_label(str(pending_approval.get("name") or ""))
                    return

                step_results[step_name] = outcome["stepResult"]
                if outcome["state"] in {"completed", "continued"}:
                    completed.add(step_name)
                    # Mark all plan items as done since step completed.
                    plan = step_states[step_name].get("planProgress")
                    if plan and plan.get("items"):
                        for item in plan["items"]:
                            item["done"] = True
                        plan["completedItems"] = plan["totalItems"]
                    # Handle conditional branch routing
                    if "skipSteps" in outcome:
                        for skip_name in outcome["skipSteps"]:
                            skipped.add(str(skip_name).strip())
                            step_states[str(skip_name).strip()] = {
                                "status": "skipped",
                                "reason": f"Conditional branch not taken (step '{step_name}')",
                                "updatedAt": now_iso(),
                            }
                if outcome["state"] == "failed":
                    fatal_failures.append(outcome)

            snapshot = workflow_snapshot(
                generation=generation,
                run_id=run_id,
                started_at=started_at,
                current_step=frontier_label,
                step_results=step_results,
                step_states=step_states,
            )
            write_artifact(snapshot)
            patch_workflow_status(
                plural=plural,
                phase="running",
                generation=generation,
                run_id=run_id,
                total_steps=len(steps),
                current_step=frontier_label,
                started_at=started_at,
                step_states=step_states,
                worker_job=worker_job,
                pending_approval=None,
                extra_summary={"currentFrontier": frontier_names},
            )
            # §2.5 — DB mirroring is now handled by the status projection controller.
            append_journal_event(
                "workflow.frontier.completed",
                {"runId": run_id, "steps": frontier_names},
            )

            if fatal_failures:
                failure_messages = ", ".join(
                    (
                        f"{item['stepName']}: "
                        f"{item['stepState'].get('error', 'step failed')}"
                    )
                    for item in fatal_failures
                )
                raise RuntimeError(
                    f"Workflow frontier failed: {failure_messages}"
                )

        completed_at = now_iso()
        payload = workflow_snapshot(
            generation=generation,
            run_id=run_id,
            started_at=started_at,
            current_step="",
            step_results=step_results,
            step_states=step_states,
            completed_at=completed_at,
        )
        write_artifact(payload)
        if execution_id:
            try:
                trace_client.end_execution(
                    execution_id=execution_id,
                    status="completed",
                    outputs={"completedAt": completed_at},
                    metrics={
                        "total_steps": len(steps),
                        "completed_steps": len(completed),
                        "failed_steps": len(fatal_failures) if fatal_failures else 0,
                    },
                )
            except Exception:
                logger.warning("Trace end_execution failed", exc_info=True)
            if runtime_events is not None:
                runtime_events.emit_workflow_completed(
                    execution_id=execution_id,
                    workflow_name=TARGET_NAME,
                    status="completed",
                    duration_ms=int((time.time() - parse_iso_timestamp(started_at) or time.time()) * 1000),
                )
        append_journal_event(
            "workflow.completed",
            {"runId": run_id, "completedAt": completed_at},
        )
        patch_workflow_status(
            plural=plural,
            phase="completed",
            generation=generation,
            run_id=run_id,
            total_steps=len(steps),
            current_step="",
            started_at=started_at,
            step_states=step_states,
            worker_job=worker_job,
            pending_approval=None,
            extra_summary={"completedAt": completed_at},
        )
        # §2.5 — DB mirroring is now handled by the status projection controller.
    except Exception as exc:
        if execution_id:
            try:
                trace_client.end_execution(
                    execution_id=execution_id,
                    status="failed",
                    error_message=str(exc),
                )
            except Exception:
                logger.warning("Trace end_execution failed", exc_info=True)
            if runtime_events is not None:
                runtime_events.emit_workflow_error(
                    execution_id=execution_id,
                    workflow_name=TARGET_NAME,
                    error=str(exc)[:2048],
                )
        _patch_pending_approval_label(None)
        failed_at = now_iso()
        failure_payload = workflow_snapshot(
            generation=generation,
            run_id=run_id,
            started_at=started_at,
            current_step=current_step,
            step_results=step_results,
            step_states=step_states,
            error=str(exc),
            failed_at=failed_at,
        )
        write_artifact(failure_payload)
        append_journal_event(
            "workflow.failed",
            {"runId": run_id, "failedAt": failed_at, "error": str(exc)},
        )
        patch_workflow_status(
            plural=plural,
            phase="failed",
            generation=generation,
            run_id=run_id,
            total_steps=len(steps),
            current_step=str(failure_payload.get("currentStep", "")),
            started_at=started_at,
            step_states=step_states,
            worker_job=worker_job,
            pending_approval=None,
            extra_summary={"failedAt": failed_at, "error": str(exc)},
        )
        # §2.5 — DB mirroring is now handled by the status projection controller.
        raise
    finally:
        _CURRENT_EXECUTION_ID = None
        try:
            trace_client.flush()
        except Exception:
            logger.warning("Trace flush failed", exc_info=True)


# ---------------------------------------------------------------------------
# §8.3 — Dead-letter queue for failed jobs
# ---------------------------------------------------------------------------


def record_dead_letter(
    kind: str,
    namespace: str,
    name: str,
    generation: int,
    run_id: str,
    error: str,
) -> None:
    """Append a dead-letter entry to the artifact so failed jobs are trackable."""
    try:
        dlq_path = Path(ARTIFACT_PATH).with_suffix(".dlq.json")
        dlq_entries: list[dict[str, Any]] = []
        if dlq_path.exists():
            try:
                data = json.loads(dlq_path.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    dlq_entries = data
            except Exception:
                logger.warning("Failed to read existing DLQ file %s", dlq_path, exc_info=True)
        dlq_entries.append({
            "timestamp": now_iso(),
            "kind": kind,
            "namespace": namespace,
            "name": name,
            "generation": generation,
            "runId": run_id,
            "error": error,
            "workerJob": WORKER_JOB_NAME,
        })
        # Keep last 50 entries
        dlq_entries = dlq_entries[-50:]
        dlq_path.write_text(json.dumps(dlq_entries, indent=2, default=str), encoding="utf-8")
    except Exception:
        logger.warning("Failed to write dead-letter queue entry", exc_info=True)


# ---------------------------------------------------------------------------
# §8.4 — Job cancellation with proper cleanup
# ---------------------------------------------------------------------------


def cancel_running_sessions(step_results: dict[str, dict[str, Any]], steps: list[dict[str, Any]]) -> None:
    """Cancel any active agent sessions referenced by step results."""
    for step in steps:
        step_name = str(step.get("name", "")).strip()
        result = step_results.get(step_name, {})
        thread_id = str(result.get("thread_id", "")).strip()
        agent_ref = str(step.get("agentRef", "")).strip()
        if agent_ref and thread_id:
            try:
                cancel_agent_session(agent_ref, TARGET_NAMESPACE, thread_id)
                logger.info("Cancelled agent session for step '%s' (thread=%s)", step_name, thread_id)
            except Exception as exc:
                logger.debug("Failed to cancel agent session for step '%s': %s", step_name, exc)


def main() -> int:
    if not WORKER_KIND or not TARGET_NAMESPACE or not TARGET_NAME:
        logger.error(
            "WORKER_KIND, TARGET_NAMESPACE, and TARGET_NAME are required."
        )
        return 2

    load_kubernetes_config()
    init_state_database()
    init_tracing("kubesynapse-worker")

    # §2.6 — Acquire distributed lease before execution
    resource = get_resource(resource_plural())
    generation = int(resource.get("metadata", {}).get("generation", 1))
    run_id = (
        str(
            WORKFLOW_RUN_ID
            or (resource.get("status", {}) or {}).get("runId")
            or ""
        ).strip()
    )

    if run_id:
        try:
            check_run_id_conflict(WORKER_KIND, TARGET_NAMESPACE, TARGET_NAME, generation, run_id)
        except RuntimeError:
            logger.exception("Run ID conflict detected. Exiting.")
            return 1

    if not acquire_worker_lease(WORKER_KIND, TARGET_NAMESPACE, TARGET_NAME, generation):
        logger.error("Could not acquire lease for %s %s/%s gen %d. Exiting.", WORKER_KIND, TARGET_NAMESPACE, TARGET_NAME, generation)
        return 1

    start_lease_renewal(WORKER_KIND, TARGET_NAME, generation)

    try:
        # §8.2 — Run worker with a global execution timeout
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(run_workflow_worker)
            try:
                deadline = time.monotonic() + WORKER_EXECUTION_TIMEOUT_SECONDS
                while not future.done():
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise concurrent.futures.TimeoutError
                    try:
                        future.result(timeout=min(remaining, 2.0))
                    except concurrent.futures.TimeoutError:
                        if is_shutting_down():
                            raise RuntimeError(
                                "Worker shutdown initiated — aborting workflow execution"
                            )
                        continue
            except concurrent.futures.TimeoutError:
                logger.error(
                    "Worker timed out after %.0fs for %s '%s/%s'",
                    WORKER_EXECUTION_TIMEOUT_SECONDS,
                    WORKER_KIND,
                    TARGET_NAMESPACE,
                    TARGET_NAME,
                )
                # Cancel active agent sessions before exiting
                try:
                    resource = get_resource(resource_plural())
                    spec = resource.get("spec", {})
                    steps = spec.get("steps") or []
                    artifact = load_artifact()
                    step_results = dict(artifact.get("stepResults", {}) or {})
                    cancel_running_sessions(step_results, steps)
                except Exception:
                    logger.debug("Failed to cancel sessions during timeout cleanup", exc_info=True)
                record_dead_letter(
                    WORKER_KIND,
                    TARGET_NAMESPACE,
                    TARGET_NAME,
                    generation,
                    run_id,
                    f"Worker timed out after {WORKER_EXECUTION_TIMEOUT_SECONDS:.0f}s",
                )
                return 1
    except Exception as exc:
        # Intentionally broad: catch-all so the worker exits cleanly and releases its lease.
        error_text = str(exc)
        if is_shutting_down():
            logger.warning(
                "Worker interrupted by shutdown for %s '%s/%s'",
                WORKER_KIND,
                TARGET_NAMESPACE,
                TARGET_NAME,
            )
            record_dead_letter(WORKER_KIND, TARGET_NAMESPACE, TARGET_NAME, generation, run_id, error_text)
            return 1
        logger.exception(
            "Worker failed for %s '%s/%s'",
            WORKER_KIND,
            TARGET_NAMESPACE,
            TARGET_NAME,
        )
        record_dead_letter(WORKER_KIND, TARGET_NAMESPACE, TARGET_NAME, generation, run_id, error_text)
        return 1
    finally:
        stop_lease_renewal()
        release_worker_lease(WORKER_KIND, TARGET_NAME, generation)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
