import concurrent.futures
import json
import logging
import os
import random
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import kubernetes.client  # type: ignore[import-untyped]
import kubernetes.config  # type: ignore[import-untyped]

from utils import (
    build_eval_run_id,
    build_thread_id,
    build_workflow_run_id,
    estimate_toxicity,
    exact_match_score,
    invoke_agent_runtime,
    normalize_step_execution,
    now_iso,
    parse_json_output,
    ready_workflow_steps,
    render_prompt,
    validate_workflow_graph,
    workflow_journal_path,
)
from state_store import init_database as init_state_database, safe_record_eval_state, safe_record_workflow_state

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("operator-worker")

GROUP = "sandbox.enterprise.ai"
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
EVAL_RUN_ID = os.getenv("EVAL_RUN_ID", "").strip()


def resource_plural() -> str:
    if WORKER_KIND == "workflow":
        return "agentworkflows"
    if WORKER_KIND == "eval":
        return "agentevals"
    raise ValueError(f"Unsupported WORKER_KIND '{WORKER_KIND}'")


def load_kubernetes_config() -> None:
    try:
        kubernetes.config.load_incluster_config()
        logger.info("Loaded in-cluster Kubernetes config for worker.")
    except kubernetes.config.ConfigException:
        kubernetes.config.load_kube_config()
        logger.info("Loaded local kubeconfig for worker.")


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
                backoff = (2 ** attempt) + random.uniform(0, 1)
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
            body={"metadata": {"labels": {"sandbox.enterprise.ai/pending-approval": label_value}}},
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
        logger.error("Failed to read artifact '%s': %s", path, exc)
        raise RuntimeError(f"Corrupt or unreadable artifact at {path}: {exc}") from exc


def write_artifact(payload: dict[str, Any]) -> None:
    path = Path(ARTIFACT_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    try:
        serialized = json.dumps(payload, indent=2, sort_keys=True, default=str)
    except (TypeError, ValueError) as exc:
        logger.error("Failed to serialize artifact payload: %s", exc)
        raise RuntimeError(f"Artifact serialization failed: {exc}") from exc
    temp_path.write_text(serialized, encoding="utf-8")
    temp_path.replace(path)


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
    summary = workflow_summary(step_states, total_steps, run_id)
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
    parts: list[str] = []
    for dependency in dependencies:
        result = step_results.get(dependency, {})
        response_text = str(result.get("response", ""))
        output_data = result.get("output", {})
        structured_json = output_data.get("json") if isinstance(output_data, dict) else None
        if structured_json is not None:
            parts.append(
                f"[Step: {dependency}]\n{response_text}\n[Structured Output]\n"
                + json.dumps(structured_json, ensure_ascii=False, indent=2)
            )
        else:
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
        parsed = parsed.replace(tzinfo=timezone.utc)
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
) -> dict[str, Any]:
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
    }
    if error:
        state["error"] = error
    if failure_class:
        state["failureClass"] = failure_class
    if approval_wait_ms is not None:
        state["approvalWaitMs"] = approval_wait_ms
    return state


def execute_workflow_step(
    step: dict[str, Any],
    workflow_input: str,
    step_results: dict[str, dict[str, Any]],
    run_id: str,
    pending_approval: dict[str, Any] | None,
    worker_job: dict[str, Any],
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
    )
    thread_id = build_thread_id("workflow", TARGET_NAME, run_id, step_name)
    started_at = now_iso()
    approval_wait_ms: int | None = None

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
        append_journal_event(
            "workflow.step.attempt.started",
            {
                "runId": run_id,
                "step": step_name,
                "attempt": attempt,
                "threadId": thread_id,
                "agentRef": step.get("agentRef", ""),
            },
        )
        try:
            result = invoke_agent_runtime(
                str(step.get("agentRef", "")),
                TARGET_NAMESPACE,
                {
                    "prompt": prompt,
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
                },
                timeout_seconds=float(execution_policy["timeoutSeconds"]),
            )
            latency_ms = int((time.perf_counter() - started) * 1000)
            response_text = str(result.get("response", ""))
            result_status = str(
                result.get("status", "completed") or "completed"
            )
            completed_at = now_iso()

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
                },
            )
            return {
                "state": "completed",
                "stepName": step_name,
                "stepResult": step_result,
                "stepState": build_step_state(
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
                ),
            }
        except Exception as exc:
            latency_ms = int((time.perf_counter() - started) * 1000)
            completed_at = now_iso()
            error_text = str(exc)
            failure_class = type(exc).__name__
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
            step_result = {
                "agentRef": step.get("agentRef", ""),
                "response": "",
                "thread_id": thread_id,
                "status": terminal_state,
                "error": error_text,
                "output": {"text": "", "json": None, "type": "empty"},
                "attempts": attempt,
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
            previous_response[:2000],
            "",
        ])
    if base_prompt:
        parts.extend([
            "### Instructions:",
            base_prompt,
            "",
        ])
    commit_after = loop_config.get("commitAfterEachItem", True)
    parts.extend([
        "### Requirements:",
        f"- Work on the current task item only",
        f"- {'Commit your changes after completing the task' if commit_after else 'Do not commit yet'}",
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

    # Parse or generate plan
    if plan_source == "prompt" or not plan_text:
        # Agent generates plan from first iteration
        plan_prompt = f"Generate a numbered TODO checklist for the following work:\n\n{workflow_input}\n\n{step.get('prompt', '')}\n\nRespond with ONLY a markdown checklist (- [ ] item format), nothing else."
        thread_id = build_thread_id("workflow", TARGET_NAME, run_id, f"{step_name}-plan")
        try:
            plan_result = invoke_agent_runtime(
                str(step.get("agentRef", "")),
                TARGET_NAMESPACE,
                {
                    "prompt": plan_prompt,
                    "thread_id": thread_id,
                    "caller_agent_name": TARGET_NAME,
                    "caller_agent_namespace": TARGET_NAMESPACE,
                    "parent_thread_id": run_id,
                },
                timeout_seconds=120.0,
            )
            plan_text = str(plan_result.get("response", ""))
        except Exception as exc:
            logger.error("Failed to generate plan for loop step '%s': %s", step_name, exc)
            return {
                "state": "failed",
                "stepName": step_name,
                "stepResult": {"agentRef": step.get("agentRef", ""), "response": "", "status": "failed", "error": str(exc), "output": {"text": "", "json": None, "type": "empty"}, "attempts": 0},
                "stepState": build_step_state(step_name=step_name, step=step, status_name="failed", attempts=0, started_at=started_at, completed_at=now_iso(), latency_ms=0, worker_job=worker_job, execution_policy=execution_policy, error=f"Plan generation failed: {exc}"),
            }

    checklist = parse_plan_checklist(plan_text)
    if not checklist:
        checklist = [{"text": "Complete the assigned work", "done": False}]

    # Use a single thread_id across all loop iterations so runtimes with
    # session persistence (e.g. opencode) maintain context between iterations.
    loop_thread_id = build_thread_id("workflow", TARGET_NAME, run_id, f"{step_name}-loop")

    previous_response = ""
    consecutive_completion_signals = 0
    all_responses: list[str] = []
    all_artifacts: list[dict[str, Any]] = []
    all_tool_calls: list[dict[str, Any]] = []
    all_loop_warnings: list[str] = []
    loop_progress: dict[str, Any] = {
        "iteration": 0,
        "maxIterations": max_iterations,
        "completedItems": 0,
        "totalItems": len(checklist),
        "circuitBreakerState": circuit_breaker.to_dict(),
        "exitReason": None,
    }

    append_journal_event(
        "workflow.loop.started",
        {"runId": run_id, "step": step_name, "totalItems": len(checklist), "maxIterations": max_iterations},
    )

    for iteration in range(1, max_iterations + 1):
        loop_progress["iteration"] = iteration

        # Check circuit breaker
        if circuit_breaker.is_open():
            loop_progress["exitReason"] = "circuit_breaker_open"
            append_journal_event("workflow.loop.circuit_breaker_open", {"runId": run_id, "step": step_name, "iteration": iteration})
            break

        # Build iteration prompt
        prompt = build_loop_iteration_prompt(step, iteration, checklist, previous_response, workflow_input)
        thread_id = loop_thread_id

        append_journal_event(
            "workflow.loop.iteration.started",
            {"runId": run_id, "step": step_name, "iteration": iteration, "completedItems": sum(1 for c in checklist if c.get("done"))},
        )

        try:
            result = invoke_agent_runtime(
                str(step.get("agentRef", "")),
                TARGET_NAMESPACE,
                {
                    "prompt": prompt,
                    "thread_id": thread_id,
                    "caller_agent_name": TARGET_NAME,
                    "caller_agent_namespace": TARGET_NAMESPACE,
                    "parent_thread_id": run_id,
                },
                timeout_seconds=float(execution_policy.get("timeoutSeconds", 300)),
            )
            response_text = str(result.get("response", ""))
            all_responses.append(response_text)
            previous_response = response_text
            # Collect rich response fields from runtimes that provide them
            all_artifacts.extend(result.get("artifacts") or [])
            all_tool_calls.extend(result.get("tool_calls") or [])
            all_loop_warnings.extend(result.get("warnings") or [])
        except Exception as exc:
            logger.warning("Loop iteration %d failed for step '%s': %s", iteration, step_name, exc)
            circuit_breaker.record_progress(False)
            loop_progress["circuitBreakerState"] = circuit_breaker.to_dict()
            append_journal_event("workflow.loop.iteration.failed", {"runId": run_id, "step": step_name, "iteration": iteration, "error": str(exc)})
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
        loop_progress["circuitBreakerState"] = circuit_breaker.to_dict()

        append_journal_event(
            "workflow.loop.iteration.completed",
            {"runId": run_id, "step": step_name, "iteration": iteration, "signals": signals, "completedItems": loop_progress["completedItems"]},
        )

        # Notify caller of iteration progress
        if on_iteration_complete:
            try:
                on_iteration_complete(loop_progress)
            except Exception:
                pass

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

    append_journal_event(
        "workflow.loop.completed",
        {"runId": run_id, "step": step_name, "iterations": loop_progress["iteration"], "completedItems": loop_progress["completedItems"], "exitReason": loop_progress["exitReason"]},
    )

    exit_reason = loop_progress.get("exitReason", "")
    result_status = "continued" if exit_reason in ("max_iterations", "circuit_breaker_open") else "completed"
    result_state = result_status

    step_result = {
        "agentRef": step.get("agentRef", ""),
        "response": combined_response,
        "status": result_status,
        "output": {"text": combined_response, "json": {"loopProgress": loop_progress, "checklist": checklist}, "type": "json"},
        "attempts": loop_progress["iteration"],
        "artifacts": all_artifacts,
        "tool_calls": all_tool_calls,
        "metadata": {"loopProgress": loop_progress},
        "warnings": all_loop_warnings,
    }

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
    )
    step_state["loopProgress"] = loop_progress

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
        elif depth == 0 and in_quote is None:
            if lowered[i: i + len(connective)] == connective:
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
        logger.error("Conditional expression evaluation failed for step '%s': %s", step_name, exc)
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


def run_workflow_worker() -> None:
    plural = resource_plural()
    resource = get_resource(plural)
    spec = resource.get("spec", {})
    metadata = resource.get("metadata", {})
    status = resource.get("status", {}) or {}
    steps = spec.get("steps") or []
    graph = validate_workflow_graph(steps)

    generation = int(metadata.get("generation", 1))
    artifact = load_artifact()
    run_id = (
        str(
            status.get("runId")
            or artifact.get("runId")
            or WORKFLOW_RUN_ID
            or ""
        )
        or build_workflow_run_id(
            TARGET_NAMESPACE,
            TARGET_NAME,
            generation,
        )
    )
    worker_job = {
        "name": WORKER_JOB_NAME,
        "namespace": OPERATOR_NAMESPACE,
    }
    artifact_matches_generation = (
        artifact.get("generation") == generation
        and artifact.get("runId") == run_id
    )
    step_results = (
        dict(artifact.get("stepResults", {}) or {})
        if artifact_matches_generation
        else {}
    )
    step_states = (
        dict(artifact.get("stepStates", {}) or {})
        if artifact_matches_generation
        else {}
    )
    pending_approval = (
        dict(artifact.get("pendingApproval", {}) or {})
        if artifact_matches_generation
        else {}
    )
    started_at = str(artifact.get("startedAt") or now_iso())
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
    current_step = str(status.get("currentStep", "") or "")
    if str(status.get("phase", "") or "") == "waiting-approval":
        _patch_pending_approval_label(None)
    workflow_status_payload = patch_workflow_status(
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
    safe_record_workflow_state(
        namespace=TARGET_NAMESPACE,
        resource_name=TARGET_NAME,
        generation=generation,
        run_id=run_id,
        phase="running",
        spec=spec,
        status=workflow_status_payload,
    )

    try:
        while len(completed) + len(skipped) < len(steps):
            ready = ready_workflow_steps(steps, completed, skipped_steps=skipped)
            if not ready:
                raise ValueError(
                    "Workflow contains a dependency cycle "
                    "or unresolved dependency"
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
            workflow_status_payload = patch_workflow_status(
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
            safe_record_workflow_state(
                namespace=TARGET_NAMESPACE,
                resource_name=TARGET_NAME,
                generation=generation,
                run_id=run_id,
                phase="running",
                spec=spec,
                status=workflow_status_payload,
            )

            outcome_by_name: dict[str, dict[str, Any]] = {}
            if len(frontier) == 1:
                step = frontier[0]
                step_type = str(step.get("type", "agent")).strip()
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
                    outcome = execute_loop_step(
                        step, str(spec.get("input", "")), step_results, run_id, worker_job,
                        on_iteration_complete=_on_iteration,
                    )
                elif step_type == "conditional":
                    outcome = execute_conditional_step(
                        step, str(spec.get("input", "")), step_results, run_id, worker_job,
                    )
                else:
                    outcome = execute_workflow_step(
                        step,
                        str(spec.get("input", "")),
                        step_results,
                        run_id,
                        pending_approval or None,
                        worker_job,
                    )
                outcome_by_name[outcome["stepName"]] = outcome
            else:
                frontier_timeout = max(
                    float(normalize_step_execution(frontier[0]).get("timeoutSeconds", 600))
                    for f_step in frontier
                ) + 120  # step timeout + buffer
                with ThreadPoolExecutor(max_workers=len(frontier)) as executor:
                    future_map = {
                        executor.submit(
                            execute_workflow_step,
                            step,
                            str(spec.get("input", "")),
                            step_results,
                            run_id,
                            None,
                            worker_job,
                        ): str(step.get("name", ""))
                        for step in frontier
                    }
                    try:
                        for future in concurrent.futures.as_completed(future_map, timeout=frontier_timeout):
                            outcome = future.result()
                            outcome_by_name[outcome["stepName"]] = outcome
                    except concurrent.futures.TimeoutError:
                        for f in future_map:
                            f.cancel()
                        raise RuntimeError(
                            f"Parallel frontier [{frontier_label}] timed out after {frontier_timeout:.0f}s"
                        )

            pending_approval = {}
            fatal_failures: list[dict[str, Any]] = []
            for step in frontier:
                step_name = str(step.get("name", ""))
                outcome = outcome_by_name[step_name]
                step_states[step_name] = outcome["stepState"]

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
                    workflow_status_payload = patch_workflow_status(
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
                    safe_record_workflow_state(
                        namespace=TARGET_NAMESPACE,
                        resource_name=TARGET_NAME,
                        generation=generation,
                        run_id=run_id,
                        phase="waiting-approval",
                        spec=spec,
                        status=workflow_status_payload,
                    )
                    _patch_pending_approval_label(str(pending_approval.get("name") or ""))
                    return

                step_results[step_name] = outcome["stepResult"]
                if outcome["state"] in {"completed", "continued"}:
                    completed.add(step_name)
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
            workflow_status_payload = patch_workflow_status(
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
            safe_record_workflow_state(
                namespace=TARGET_NAMESPACE,
                resource_name=TARGET_NAME,
                generation=generation,
                run_id=run_id,
                phase="running",
                spec=spec,
                status=workflow_status_payload,
            )
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
        append_journal_event(
            "workflow.completed",
            {"runId": run_id, "completedAt": completed_at},
        )
        workflow_status_payload = patch_workflow_status(
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
        safe_record_workflow_state(
            namespace=TARGET_NAMESPACE,
            resource_name=TARGET_NAME,
            generation=generation,
            run_id=run_id,
            phase="completed",
            spec=spec,
            status=workflow_status_payload,
        )
    except Exception as exc:
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
        workflow_status_payload = patch_workflow_status(
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
        safe_record_workflow_state(
            namespace=TARGET_NAMESPACE,
            resource_name=TARGET_NAME,
            generation=generation,
            run_id=run_id,
            phase="failed",
            spec=spec,
            status=workflow_status_payload,
        )
        raise


def run_eval_worker() -> None:
    plural = resource_plural()
    resource = get_resource(plural)
    spec = resource.get("spec", {})
    metadata = resource.get("metadata", {})
    test_suite = spec.get("testSuite") or []
    if not test_suite:
        raise ValueError("AgentEval must contain at least one test case")

    generation = int(metadata.get("generation", 1))
    artifact = load_artifact()
    run_id = str(
        resource.get("status", {}).get("runId")
        or artifact.get("runId")
        or EVAL_RUN_ID
        or build_eval_run_id(TARGET_NAMESPACE, TARGET_NAME, generation)
    ).strip()
    failure_threshold = spec.get("failureThreshold", {})
    results: list[dict[str, Any]] = []
    passed = True
    started_at = now_iso()
    worker_job = {"name": WORKER_JOB_NAME, "namespace": OPERATOR_NAMESPACE}

    eval_status_payload = {
        "phase": "running",
        "runId": run_id,
        "observedGeneration": generation,
        "artifactRef": artifact_ref(generation),
        "workerJob": worker_job,
        "summary": {
            "caseCount": len(test_suite),
            "completedCases": 0,
            "updatedAt": now_iso(),
            "runId": run_id,
            "startedAt": started_at,
        },
    }
    patch_custom_status(plural, eval_status_payload)
    safe_record_eval_state(
        namespace=TARGET_NAMESPACE,
        resource_name=TARGET_NAME,
        generation=generation,
        run_id=run_id,
        phase="running",
        passed=None,
        spec=spec,
        status=eval_status_payload,
    )

    try:
        for index, test_case in enumerate(test_suite):
            started = time.perf_counter()
            response_text = ""
            error_msg = ""
            result_status = "completed"
            thread_id = build_thread_id("eval", TARGET_NAME, generation, index)
            try:
                response = invoke_agent_runtime(
                    spec["agentRef"],
                    TARGET_NAMESPACE,
                    {
                        "prompt": test_case["input"],
                        "thread_id": thread_id,
                    },
                )
                response_text = str(response.get("response", ""))
                result_status = str(
                    response.get("status", "completed") or "completed"
                )
                # Accept "incomplete" as usable partial output (e.g. opencode
                # context overflow that still produced a response).
                if result_status == "incomplete":
                    result_status = "completed"
                # Prefer structured output from metadata when available
                eval_metadata = response.get("metadata") or {}
                if isinstance(eval_metadata, dict) and eval_metadata.get("structured_output"):
                    response_text = json.dumps(
                        eval_metadata["structured_output"], ensure_ascii=False
                    )
                if result_status != "completed":
                    error_msg = (
                        f"Runtime returned status '{result_status}': "
                        f"{response_text}"
                    )
                    passed = False
                elif response_text.startswith("Request blocked"):
                    error_msg = response_text
                    result_status = "blocked"
                    passed = False
            except Exception as exc:
                logger.error("Eval step failed: %s", exc)
                error_msg = str(exc)
                result_status = "failed"
                passed = False

            latency_ms = int((time.perf_counter() - started) * 1000)
            expected_output = test_case.get("expectedOutput", "")
            metrics = test_case.get("metrics", [])

            relevance = (
                exact_match_score(response_text, expected_output)
                if not error_msg
                else 0.0
            )
            if expected_output:
                faithfulness = (
                    exact_match_score(response_text, expected_output)
                    if not error_msg
                    else 0.0
                )
            else:
                faithfulness = 1.0 if not error_msg else 0.0
            toxicity = (
                estimate_toxicity(response_text) if not error_msg else 0.0
            )

            case_result = {
                "input": test_case["input"],
                "expectedOutput": expected_output,
                "response": response_text,
                "error": error_msg,
                "latencyMs": latency_ms,
                "status": result_status,
                "threadId": thread_id,
                "metrics": {
                    "relevance": relevance,
                    "faithfulness": faithfulness,
                    "toxicity": toxicity,
                },
            }
            results.append(case_result)

            if (
                "relevance" in metrics
                and failure_threshold.get("minRelevance") is not None
            ):
                passed = passed and relevance >= float(
                    failure_threshold["minRelevance"]
                )
            if (
                "faithfulness" in metrics
                and failure_threshold.get("minFaithfulness") is not None
            ):
                passed = passed and faithfulness >= float(
                    failure_threshold["minFaithfulness"]
                )
            if (
                "toxicity" in metrics
                and failure_threshold.get("maxToxicity") is not None
            ):
                passed = passed and toxicity <= float(
                    failure_threshold["maxToxicity"]
                )
            if (
                "latency" in metrics
                and failure_threshold.get("maxLatencyMs") is not None
            ):
                passed = passed and latency_ms <= int(
                    failure_threshold["maxLatencyMs"]
                )

            write_artifact(
                {
                    "kind": "eval",
                    "generation": generation,
                    "runId": run_id,
                    "updatedAt": now_iso(),
                    "startedAt": started_at,
                    "cases": results,
                }
            )
            eval_status_payload = {
                "phase": "running",
                "runId": run_id,
                "observedGeneration": generation,
                "artifactRef": artifact_ref(generation),
                "workerJob": worker_job,
                "summary": {
                    "caseCount": len(test_suite),
                    "completedCases": len(results),
                    "updatedAt": now_iso(),
                    "runId": run_id,
                    "startedAt": started_at,
                },
            }
            patch_custom_status(plural, eval_status_payload)
            safe_record_eval_state(
                namespace=TARGET_NAMESPACE,
                resource_name=TARGET_NAME,
                generation=generation,
                run_id=run_id,
                phase="running",
                passed=None,
                spec=spec,
                status=eval_status_payload,
            )

        completed_at = now_iso()
        summary = {
            "caseCount": len(results),
            "passed": passed,
            "scheduleConfigured": bool(spec.get("schedule")),
            "completedCases": len(results),
            "startedAt": started_at,
            "completedAt": completed_at,
            "runId": run_id,
        }
        write_artifact(
            {
                "kind": "eval",
                "generation": generation,
                "runId": run_id,
                "updatedAt": completed_at,
                "startedAt": started_at,
                "completedAt": completed_at,
                "summary": summary,
                "cases": results,
            }
        )
        eval_status_payload = {
            "phase": "completed",
            "runId": run_id,
            "lastRun": completed_at,
            "passed": passed,
            "observedGeneration": generation,
            "artifactRef": artifact_ref(generation),
            "workerJob": worker_job,
            "summary": summary,
            "cases": results,
        }
        patch_custom_status(plural, eval_status_payload)
        safe_record_eval_state(
            namespace=TARGET_NAMESPACE,
            resource_name=TARGET_NAME,
            generation=generation,
            run_id=run_id,
            phase="completed",
            passed=passed,
            spec=spec,
            status=eval_status_payload,
        )
    except Exception as exc:
        failed_at = now_iso()
        write_artifact(
            {
                "kind": "eval",
                "generation": generation,
                "runId": run_id,
                "updatedAt": failed_at,
                "startedAt": started_at,
                "failedAt": failed_at,
                "error": str(exc),
                "cases": results,
            }
        )
        eval_status_payload = {
            "phase": "failed",
            "runId": run_id,
            "lastRun": failed_at,
            "passed": False,
            "observedGeneration": generation,
            "artifactRef": artifact_ref(generation),
            "workerJob": worker_job,
            "summary": {
                "caseCount": len(test_suite),
                "completedCases": len(results),
                "failedAt": failed_at,
                "error": str(exc),
                "runId": run_id,
            },
            "cases": results,
        }
        patch_custom_status(plural, eval_status_payload)
        safe_record_eval_state(
            namespace=TARGET_NAMESPACE,
            resource_name=TARGET_NAME,
            generation=generation,
            run_id=run_id,
            phase="failed",
            passed=False,
            spec=spec,
            status=eval_status_payload,
        )
        raise


def main() -> int:
    if not WORKER_KIND or not TARGET_NAMESPACE or not TARGET_NAME:
        logger.error(
            "WORKER_KIND, TARGET_NAMESPACE, and TARGET_NAME are required."
        )
        return 2

    load_kubernetes_config()
    init_state_database()

    try:
        if WORKER_KIND == "workflow":
            run_workflow_worker()
        elif WORKER_KIND == "eval":
            run_eval_worker()
        else:
            raise ValueError(f"Unsupported WORKER_KIND '{WORKER_KIND}'")
    except Exception:
        logger.exception(
            "Worker failed for %s '%s/%s'",
            WORKER_KIND,
            TARGET_NAMESPACE,
            TARGET_NAME,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
