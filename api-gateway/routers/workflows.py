"""Auto-generated router — extracted from api-gateway main.py."""
from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import UTC, datetime
from typing import Any, cast

# Re-import all shared symbols from the gateway core
from _core import *
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

router = APIRouter(tags=["workflows"])

@router.get("/workflows", response_model=list[WorkflowInfo])
def list_workflows(namespace: str = "default", user=Depends(verify_token)):
    ensure_namespace_access(user, namespace)
    workflows = sorted(
        [workflow_info_from_resource(item) for item in list_custom_resources("agentworkflows", namespace)],
        key=lambda item: item.name,
    )
    for wf in workflows:
        _sync_workflow_run_history(wf)
    return workflows


@router.post("/workflows", response_model=WorkflowInfo, status_code=201)
def create_workflow(
    body: WorkflowRequest,
    namespace: str = "default",
    user=Depends(verify_token),
):
    ensure_namespace_access(user, namespace, "operator")
    created = create_custom_resource(
        "agentworkflows",
        namespace,
        body.name,
        build_workflow_spec(body),
    )
    return workflow_info_from_resource(created)


def _sync_workflow_run_history(info: WorkflowInfo) -> None:
    """Best-effort upsert of workflow run into run history based on current K8s state.

    Called on every status fetch so that runs appear in history regardless of
    whether the workflow was triggered via the API gateway or kubectl apply.
    """
    if not info.run_id or info.phase == "pending":
        return
    try:
        summary = info.summary or {}
        started_at = None
        completed_at = None
        if isinstance(summary.get("startedAt"), str):
            with contextlib.suppress(ValueError, TypeError):
                started_at = datetime.fromisoformat(summary["startedAt"].replace("Z", "+00:00"))
        terminal = info.phase in {"completed", "failed", "cancelled"}
        if terminal and isinstance(summary.get("completedAt"), str):
            with contextlib.suppress(ValueError, TypeError):
                completed_at = datetime.fromisoformat(summary["completedAt"].replace("Z", "+00:00"))

        record_workflow_run(
            workflow_name=info.name,
            namespace=info.namespace,
            run_id=info.run_id,
            phase=info.phase,
            total_steps=summary.get("totalSteps"),
            completed_steps=summary.get("completedSteps"),
            failed_steps=summary.get("failedSteps"),
            started_at=started_at,
            completed_at=completed_at,
        )
        if info.phase in {"completed", "failed"}:
            primary_agent = info.steps[0].agent_ref if info.steps else None
            if primary_agent:
                record_workflow_outcome_memory(
                    info.namespace,
                    primary_agent,
                    info.name,
                    run_id=info.run_id,
                    phase=info.phase,
                    summary=summary,
                )
                apply_memory_feedback(
                    info.namespace,
                    primary_agent,
                    session_id=info.run_id,
                    success=(info.phase == "completed"),
                )
    except Exception as exc:
        logger.debug("Failed to sync workflow run history for %s: %s", info.name, exc)


@router.get("/workflows/{workflow_name}", response_model=WorkflowInfo)
def get_workflow(
    workflow_name: str,
    namespace: str = "default",
    user=Depends(verify_token),
):
    ensure_namespace_access(user, namespace)
    info = workflow_info_from_resource(read_custom_resource("agentworkflows", workflow_name, namespace, "Workflow"))
    _sync_workflow_run_history(info)
    return info


@router.patch("/workflows/{workflow_name}", response_model=WorkflowInfo)
def update_workflow(
    workflow_name: str,
    body: WorkflowUpdateRequest,
    namespace: str = "default",
    user=Depends(verify_token),
):
    ensure_namespace_access(user, namespace, "operator")
    updated = replace_custom_resource_spec("agentworkflows", workflow_name, namespace, build_workflow_spec(body))
    return workflow_info_from_resource(updated)


@router.delete("/workflows/{workflow_name}", response_model=DeleteResponse)
def delete_workflow(
    workflow_name: str,
    namespace: str = "default",
    user=Depends(verify_token),
):
    ensure_namespace_access(user, namespace, "operator")
    delete_custom_resource("agentworkflows", workflow_name, namespace, "Workflow")
    return DeleteResponse(status="deleted", kind="workflow", name=workflow_name, namespace=namespace)


class WorkflowTriggerRequest(BaseModel):
    input: str = Field(default="", max_length=4000)
    factory_mode: str | None = Field(default=None, max_length=32)

    @model_validator(mode="after")
    def normalize_fields(self) -> WorkflowTriggerRequest:
        self.input = self.input.strip()
        self.factory_mode = normalize_factory_mode(self.factory_mode)
        return self


@router.post("/workflows/{workflow_name}/trigger", response_model=WorkflowInfo)
def trigger_workflow(
    workflow_name: str,
    body: WorkflowTriggerRequest | None = None,
    namespace: str = "default",
    user=Depends(verify_token),
):
    """Trigger a workflow run by updating only spec.input, preserving all other spec fields.

    This bumps the resource generation, which causes the operator to re-reconcile.
    """
    ensure_namespace_access(user, namespace, "operator")
    try:
        from kubernetes import client

        api = client.CustomObjectsApi()
        current = cast(
            dict[str, Any],
            api.get_namespaced_custom_object(
                group=RESOURCE_GROUP,
                version=RESOURCE_VERSION,
                namespace=namespace,
                plural="agentworkflows",
                name=workflow_name,
            ),
        )
    except Exception as exc:
        status = getattr(exc, "status", None)
        if status == 404:
            raise HTTPException(status_code=404, detail=f"Workflow '{workflow_name}' not found") from exc
        raise HTTPException(status_code=502, detail=f"Failed to read workflow: {exc}") from exc

    existing_spec = current.get("spec", {}) or {}
    if body and body.factory_mode and not is_factory_workflow_resource(workflow_name, existing_spec):
        raise HTTPException(status_code=400, detail="factory_mode is only supported for the kubesynapse factory workflow.")

    existing_input = str(existing_spec.get("input", "") or "")
    _, unwrapped_existing_request = unwrap_factory_workflow_input(existing_input)
    base_input = body.input if body and body.input else (unwrapped_existing_request or existing_input)
    if body and body.factory_mode:
        new_input = build_factory_workflow_input(base_input, body.factory_mode)
    else:
        new_input = base_input
    updated_spec = {**existing_spec, "input": new_input}

    try:
        from kubernetes import client as k8s_client

        updated = cast(
            dict[str, Any],
            k8s_client.CustomObjectsApi().replace_namespaced_custom_object(
                group=RESOURCE_GROUP,
                version=RESOURCE_VERSION,
                namespace=namespace,
                plural="agentworkflows",
                name=workflow_name,
                body={
                    "apiVersion": f"{RESOURCE_GROUP}/{RESOURCE_VERSION}",
                    "kind": RESOURCE_KIND_BY_PLURAL["agentworkflows"],
                    "metadata": {
                        "name": workflow_name,
                        "namespace": namespace,
                        "resourceVersion": current.get("metadata", {}).get("resourceVersion"),
                    },
                    "spec": updated_spec,
                },
            ),
        )
    except Exception as exc:
        status = getattr(exc, "status", None)
        if status == 409:
            raise HTTPException(status_code=409, detail="Workflow was modified concurrently. Retry.") from exc
        logger.error("Failed to trigger workflow: %s", exc)
        raise HTTPException(status_code=502, detail="Failed to trigger workflow") from exc

    # Reset status so the operator re-reconciles even when the spec
    # (and therefore metadata.generation) did not change.
    try:
        from kubernetes import client as k8s_reset

        k8s_reset.CustomObjectsApi().patch_namespaced_custom_object_status(
            group=RESOURCE_GROUP,
            version=RESOURCE_VERSION,
            namespace=namespace,
            plural="agentworkflows",
            name=workflow_name,
            body={
                "status": {
                    "phase": "pending",
                    "observedGeneration": None,
                    "pendingApproval": None,
                    "stepStates": None,
                    "summary": None,
                    "currentStep": "",
                    "workerJob": None,
                    "runId": None,
                    "artifactRef": None,
                    "journalRef": None,
                }
            },
        )
        # Re-read to return the freshest state
        updated = cast(
            dict[str, Any],
            k8s_client.CustomObjectsApi().get_namespaced_custom_object(
                group=RESOURCE_GROUP,
                version=RESOURCE_VERSION,
                namespace=namespace,
                plural="agentworkflows",
                name=workflow_name,
            ),
        )
    except Exception:
        logger.warning("Workflow status reset failed after spec replace (best-effort)", exc_info=True)

    result = workflow_info_from_resource(updated)

    # Record in run history
    try:
        record_workflow_run(
            workflow_name=workflow_name,
            namespace=namespace,
            run_id=result.run_id,
            phase=result.phase,
            total_steps=result.summary.get("totalSteps") if isinstance(result.summary, dict) else None,
            triggered_by=str(user.get("sub", "unknown")),
            input_text=new_input[:2000] if new_input else None,
        )
    except Exception as exc:
        logger.warning("Failed to record workflow run history: %s", exc)

    return result


@router.post("/workflows/{workflow_name}/retry-failed", response_model=WorkflowInfo)
def retry_failed_workflow_steps(
    workflow_name: str,
    namespace: str = "default",
    user=Depends(verify_token),
):
    """Retry only the failed steps of a workflow.

    Resets failed step states back to 'pending' while preserving completed
    steps, preserves the current artifact generation, and assigns a fresh
    runId so session-aware runtimes perform a new failed-step attempt.
    """
    ensure_namespace_access(user, namespace, "operator")
    try:
        from kubernetes import client

        api = client.CustomObjectsApi()
        current = cast(
            dict[str, Any],
            api.get_namespaced_custom_object(
                group=RESOURCE_GROUP,
                version=RESOURCE_VERSION,
                namespace=namespace,
                plural="agentworkflows",
                name=workflow_name,
            ),
        )
    except Exception as exc:
        status_code = getattr(exc, "status", None)
        if status_code == 404:
            raise HTTPException(status_code=404, detail=f"Workflow '{workflow_name}' not found") from exc
        raise HTTPException(status_code=502, detail=f"Failed to read workflow: {exc}") from exc

    current_status = current.get("status") or {}
    current_phase = str(current_status.get("phase", "pending") or "pending")
    if current_phase != "failed":
        raise HTTPException(
            status_code=409,
            detail=f"Workflow is in '{current_phase}' phase. Only failed workflows can retry failed steps.",
        )

    step_states = current_status.get("stepStates") or {}
    failed_step_names: list[str] = []
    patched_step_states: dict[str, Any] = {}
    for step_name, state in step_states.items():
        if not isinstance(state, dict):
            patched_step_states[step_name] = state
            continue
        step_status = str(state.get("status", "") or "")
        if step_status == "failed":
            failed_step_names.append(step_name)
            patched_step_states[step_name] = {
                "status": "pending",
                "error": None,
                "failureClass": None,
                "startedAt": None,
                "completedAt": None,
                "iterationFailures": None,
            }
        else:
            patched_step_states[step_name] = state

    if not failed_step_names:
        raise HTTPException(status_code=409, detail="No failed steps found to retry.")

    current_generation = int((current.get("metadata") or {}).get("generation") or 1)
    retry_run_id = build_retry_workflow_run_id(namespace, workflow_name, current_generation)

    # Patch status only. Keeping the current generation preserves the existing
    # artifact path so dependent downstream steps can still read the completed
    # step outputs they rely on. A fresh runId forces session-aware runtimes
    # such as OpenCode to use a new thread instead of replaying the previous
    # failed step session.
    try:
        from kubernetes import client as k8s_client

        k8s_client.CustomObjectsApi().patch_namespaced_custom_object_status(
            group=RESOURCE_GROUP,
            version=RESOURCE_VERSION,
            namespace=namespace,
            plural="agentworkflows",
            name=workflow_name,
            body={
                "status": {
                    "phase": "pending",
                    "runId": retry_run_id,
                    "observedGeneration": None,
                    "pendingApproval": None,
                    "stepStates": patched_step_states,
                    "workerJob": None,
                    "summary": {
                        **(current_status.get("summary") or {}),
                        "runId": retry_run_id,
                        "failedSteps": 0,
                        "waitingApprovalSteps": 0,
                        "error": None,
                        "updatedAt": now_iso(),
                    },
                }
            },
        )
    except Exception as exc:
        logger.error("Failed to patch workflow status for retry-failed: %s", exc)
        raise HTTPException(status_code=502, detail="Failed to reset failed steps") from exc

    # Re-read and return freshest state.
    try:
        updated = cast(
            dict[str, Any],
            api.get_namespaced_custom_object(
                group=RESOURCE_GROUP,
                version=RESOURCE_VERSION,
                namespace=namespace,
                plural="agentworkflows",
                name=workflow_name,
            ),
        )
    except Exception:
        current["status"] = {
            **current_status,
            "phase": "pending",
            "runId": retry_run_id,
            "observedGeneration": None,
            "pendingApproval": None,
            "workerJob": None,
            "stepStates": patched_step_states,
            "summary": {
                **(current_status.get("summary") or {}),
                "runId": retry_run_id,
                "failedSteps": 0,
                "waitingApprovalSteps": 0,
                "error": None,
                "updatedAt": now_iso(),
            },
        }
        return workflow_info_from_resource(current)

    result = workflow_info_from_resource(updated)

    try:
        record_workflow_run(
            workflow_name=workflow_name,
            namespace=namespace,
            run_id=result.run_id,
            phase=result.phase,
            total_steps=result.summary.get("totalSteps") if isinstance(result.summary, dict) else None,
            triggered_by=str(user.get("sub", "unknown")),
        )
    except Exception as exc:
        logger.warning("Failed to record workflow retry-failed run history: %s", exc)

    logger.info(
        "Retrying failed steps %s for workflow '%s/%s'",
        failed_step_names,
        namespace,
        workflow_name,
    )
    return result


@router.post("/workflows/{workflow_name}/cancel", response_model=WorkflowInfo)
def cancel_workflow(
    workflow_name: str,
    namespace: str = "default",
    user=Depends(verify_token),
):
    """Cancel a running, queued, or waiting-approval workflow by patching its status phase."""
    ensure_namespace_access(user, namespace, "operator")
    try:
        from kubernetes import client

        api = client.CustomObjectsApi()
        current = cast(
            dict[str, Any],
            api.get_namespaced_custom_object(
                group=RESOURCE_GROUP,
                version=RESOURCE_VERSION,
                namespace=namespace,
                plural="agentworkflows",
                name=workflow_name,
            ),
        )
    except Exception as exc:
        status_code = getattr(exc, "status", None)
        if status_code == 404:
            raise HTTPException(status_code=404, detail=f"Workflow '{workflow_name}' not found") from exc
        logger.error("Failed to read workflow %s for cancel: %s", workflow_name, exc)
        raise HTTPException(status_code=502, detail="Failed to read workflow") from exc

    current_phase = (current.get("status") or {}).get("phase", "pending")
    if current_phase not in ("queued", "running", "waiting-approval"):
        raise HTTPException(
            status_code=409,
            detail=f"Workflow is in '{current_phase}' phase and cannot be cancelled",
        )

    try:
        from kubernetes import client as k8s_client

        k8s_client.CustomObjectsApi().patch_namespaced_custom_object_status(
            group=RESOURCE_GROUP,
            version=RESOURCE_VERSION,
            namespace=namespace,
            plural="agentworkflows",
            name=workflow_name,
            body={
                "status": {
                    "phase": "cancelled",
                    "pendingApproval": None,
                }
            },
        )
    except Exception as exc:
        logger.error("Failed to cancel workflow: %s", exc)
        raise HTTPException(status_code=502, detail="Failed to cancel workflow") from exc

    try:
        updated = cast(
            dict[str, Any],
            api.get_namespaced_custom_object(
                group=RESOURCE_GROUP,
                version=RESOURCE_VERSION,
                namespace=namespace,
                plural="agentworkflows",
                name=workflow_name,
            ),
        )
    except Exception:
        # Status was already patched successfully — return a minimal response
        # rather than failing the entire cancel operation.
        current["status"] = {**(current.get("status") or {}), "phase": "cancelled", "pendingApproval": None}
        return workflow_info_from_resource(current)
    return workflow_info_from_resource(updated)


@router.get("/workflows/{workflow_name}/status/stream")
def stream_workflow_status(
    workflow_name: str,
    namespace: str = "default",
    user=Depends(verify_token),
):
    """SSE stream that pushes workflow status updates until the workflow reaches a terminal phase."""
    ensure_namespace_access(user, namespace)
    import asyncio

    async def event_generator():
        terminal_phases = {"completed", "failed", "cancelled"}
        prev_hash = ""
        try:
            while True:
                try:
                    from kubernetes import client as k8s_client

                    resource = cast(
                        dict[str, Any],
                        k8s_client.CustomObjectsApi().get_namespaced_custom_object(
                            group=RESOURCE_GROUP,
                            version=RESOURCE_VERSION,
                            namespace=namespace,
                            plural="agentworkflows",
                            name=workflow_name,
                        ),
                    )
                    info = workflow_info_from_resource(resource)
                    _sync_workflow_run_history(info)
                    info_dict = info.model_dump(mode="json")
                    current_hash = json.dumps(info_dict, sort_keys=True, default=str)
                    if current_hash != prev_hash:
                        prev_hash = current_hash
                        yield sse_event("status", info_dict)
                    if info.phase in terminal_phases:
                        yield sse_event("done", {"phase": info.phase})
                        return
                except Exception as exc:
                    yield sse_event("error", {"error": str(exc)})
                    return
                await asyncio.sleep(2)
        except asyncio.CancelledError:
            return

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/workflows/{workflow_name}/activities/stream")
async def stream_workflow_activities(
    workflow_name: str,
    request: Request,
    namespace: str = "default",
    tail: int = 100,
    user=Depends(verify_token_or_query),
):
    """SSE stream that pushes workflow journal/activity events in real-time.

    Tails the workflow's journal file (if available) and streams structured
    activity events: reasoning steps, tool operations, A2A calls, and system
    events.  For active workflows the file is watched; for completed
    workflows the tail is sent once and the stream closes.
    """
    ensure_namespace_access(user, namespace)
    tail = max(1, min(tail, 5000))

    resource = read_custom_resource("agentworkflows", workflow_name, namespace, "Workflow")
    status = (resource.get("status") or {}) if isinstance(resource, dict) else {}
    artifact_ref = status.get("artifactRef") or {}
    journal_path = str(artifact_ref.get("journalPath") or "").strip()
    phase = str(status.get("phase") or "").strip()
    is_active = phase in {"queued", "running", "waiting-approval"}

    # Resolve PVC + path so we can read the journal from the operator namespace.
    # These fields can change as a queued workflow becomes active, so the stream
    # refreshes them during polling instead of relying only on the initial snapshot.
    pvc_name = str(artifact_ref.get("pvcName") or "").strip()
    artifact_namespace = str(artifact_ref.get("namespace") or "").strip()
    generation = int(status.get("observedGeneration") or 1)
    run_id = str(status.get("runId") or "").strip()
    worker_job = status.get("workerJob") or {}
    worker_job_name = str(worker_job.get("name") or "").strip()
    worker_namespace = str(worker_job.get("namespace") or artifact_namespace or "").strip()

    async def activity_event_generator():
        import time

        yield sse_event(
            "activities.started",
            {"workflow_name": workflow_name, "phase": phase, "run_id": run_id, "is_active": is_active},
        )

        # If we have no journal path for a terminal workflow, return a graceful
        # empty stream. Active workflows may populate it shortly after enqueue.
        if not journal_path and not is_active:
            yield sse_event("activities.done", {"reason": "no_journal_path"})
            return

        seen_ids: set[str] = set()
        last_event_time = time.monotonic()
        seen_status_ids: set[str] = set()

        try:
            if is_active:
                # Active workflow — tail the journal file via k8s exec into a
                # lightweight sidecar or by polling the artifact read endpoint.
                # For simplicity we poll the artifact endpoint every second.
                prev_size = 0
                while True:
                    if await request.is_disconnected():
                        break
                    try:
                        fresh = read_custom_resource("agentworkflows", workflow_name, namespace, "Workflow")
                        fresh_status = (fresh.get("status") or {}) if isinstance(fresh, dict) else {}
                        fresh_artifact_ref = fresh_status.get("artifactRef") or {}
                        fresh_worker_job = fresh_status.get("workerJob") or {}
                        fresh_phase = str(fresh_status.get("phase") or phase).strip()
                        current_journal_path = str(fresh_artifact_ref.get("journalPath") or journal_path).strip()
                        current_pvc_name = str(fresh_artifact_ref.get("pvcName") or pvc_name).strip()
                        current_worker_job_name = str(fresh_worker_job.get("name") or worker_job_name).strip()
                        current_worker_namespace = str(
                            fresh_worker_job.get("namespace") or fresh_artifact_ref.get("namespace") or worker_namespace
                        ).strip()

                        if not current_journal_path or not current_pvc_name:
                            if fresh_phase in {"completed", "failed", "cancelled"}:
                                yield sse_event("activities.done", {"phase": fresh_phase, "reason": "no_journal_path"})
                                return
                            await asyncio.sleep(1)
                            continue

                        artifact_rel = current_journal_path
                        if artifact_rel.startswith("/artifacts/"):
                            artifact_rel = artifact_rel[len("/artifacts/"):]

                        content = await asyncio.get_event_loop().run_in_executor(
                            None,
                            lambda: _read_artifact_from_pvc_sync(
                                current_pvc_name,
                                artifact_rel,
                                namespace,
                                worker_job_name=current_worker_job_name,
                                worker_namespace=current_worker_namespace,
                            ),
                        )
                        if content:
                            lines = content.strip().splitlines()
                            # Only yield new lines
                            start_idx = max(0, len(lines) - tail) if len(lines) > prev_size else 0
                            for line in lines[start_idx:]:
                                event_id = hashlib.sha256(line.encode()).hexdigest()[:16]
                                if event_id not in seen_ids:
                                    seen_ids.add(event_id)
                                    parsed = _parse_journal_line(line)
                                    if parsed:
                                        yield sse_event("activity", parsed)
                            prev_size = len(lines)
                        else:
                            prev_size = 0

                        if not content:
                            for activity in _status_step_state_activities(fresh_status, run_id):
                                activity_id = str(activity.get("id") or "")
                                if activity_id and activity_id not in seen_status_ids:
                                    seen_status_ids.add(activity_id)
                                    yield sse_event("activity", activity)
                    except Exception as exc:
                        logger.debug("Activity stream poll error for %s: %s", workflow_name, exc)
                    await asyncio.sleep(1)
                    if time.monotonic() - last_event_time > STREAM_KEEPALIVE_SECONDS:
                        yield sse_keepalive_comment()
                        last_event_time = time.monotonic()
                    # Stop polling if workflow reached terminal phase
                    try:
                        if fresh_phase in {"completed", "failed", "cancelled"}:
                            yield sse_event("activities.done", {"phase": fresh_phase})
                            return
                    except Exception:
                        pass
            else:
                # Terminal workflow — one-shot read
                artifact_rel = journal_path
                if artifact_rel.startswith("/artifacts/"):
                    artifact_rel = artifact_rel[len("/artifacts/"):]
                content = await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: _read_artifact_from_pvc_sync(
                        pvc_name,
                        artifact_rel,
                        namespace,
                        worker_job_name=worker_job_name,
                        worker_namespace=worker_namespace,
                    ),
                )
                if content:
                    lines = content.strip().splitlines()
                    for line in lines[-tail:]:
                        parsed = _parse_journal_line(line)
                        if parsed:
                            yield sse_event("activity", parsed)
                yield sse_event("activities.done", {"phase": phase})
        except asyncio.CancelledError:
            return
        except Exception as exc:
            yield sse_event("activities.error", {"error": str(exc)})

    return StreamingResponse(
        activity_event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


_ARTIFACT_REL_SAFE = re.compile(r"^[A-Za-z0-9._/-]+$")


def _read_artifact_from_pvc_sync(
    pvc_name: str,
    artifact_rel: str,
    namespace: str,
    worker_job_name: str = "",
    worker_namespace: str = "",
) -> str | None:
    """Best-effort read of an artifact file from a PVC via a transient pod."""
    if not pvc_name or not artifact_rel:
        return None
    # §security-R6: reject any artifact path containing path-traversal
    # sequences, option-injection sequences, or unsafe characters
    # before constructing the exec command. The exec fallback is
    # also gated behind the TENANT_EXEC_ACCESS / pods/exec RBAC
    # which is disabled by default in the chart; this is
    # defense-in-depth.
    if (
        artifact_rel.startswith("-")
        or ".." in artifact_rel
        or not _ARTIFACT_REL_SAFE.fullmatch(artifact_rel)
    ):
        logger.warning(
            "Rejected unsafe artifact_rel %r for pvc %s/%s (path traversal attempt)",
            artifact_rel, namespace, pvc_name,
        )
        return None
    try:
        from kubernetes import client as k8s_client
        from kubernetes import config as k8s_config

        try:
            k8s_config.load_incluster_config()
        except Exception:
            k8s_config.load_kube_config()

        core = k8s_client.CoreV1Api()
        # Use the operator namespace for artifact PVCs
        op_ns = worker_namespace or os.getenv("OPERATOR_NAMESPACE", namespace).strip() or namespace

        candidate_pod = None

        if worker_job_name:
            pods = core.list_namespaced_pod(namespace=op_ns, label_selector=f"job-name={worker_job_name}")
            if pods.items:
                candidate_pod = pods.items[0].metadata.name

        if not candidate_pod:
            # Fallback: find any pod that currently mounts the artifact PVC.
            pods = core.list_namespaced_pod(namespace=op_ns)
            for pod in pods.items:
                if not pod.spec or not pod.spec.volumes:
                    continue
                for vol in pod.spec.volumes:
                    if getattr(vol, "persistent_volume_claim", None) and vol.persistent_volume_claim.claim_name == pvc_name:
                        candidate_pod = pod.metadata.name
                        break
                if candidate_pod:
                    break

        if not candidate_pod:
            return None

        # Find a container that mounts the volume
        containers = core.read_namespaced_pod(name=candidate_pod, namespace=op_ns).spec.containers
        container_name = containers[0].name if containers else "worker"

        # The artifact path inside the pod is usually under /artifacts
        pod_path = f"/artifacts/{artifact_rel}"
        exec_resp = core.connect_get_namespaced_pod_exec(
            name=candidate_pod,
            namespace=op_ns,
            container=container_name,
            command=["cat", pod_path],
            stderr=False,
            stdin=False,
            stdout=True,
            tty=False,
        )
        if isinstance(exec_resp, str):
            return exec_resp
    except Exception as exc:
        logger.debug("Failed to read artifact %s from PVC %s: %s", artifact_rel, pvc_name, exc)
    return None


def _parse_journal_line(line: str) -> dict[str, Any] | None:
    """Parse a journal NDJSON line into a frontend-friendly activity event."""
    try:
        record = json.loads(line)
        if not isinstance(record, dict):
            return None
        event_type = str(record.get("event") or "").strip()
        if not event_type:
            return None

        # Map journal event types to UI activity types
        activity_type = "system"
        severity = "info"
        event_lower = event_type.lower()
        if ("step" in event_lower and "started" in event_lower) or ("step" in event_lower and ("completed" in event_lower or "failed" in event_lower)):
            activity_type = "operation"
        elif "loop" in event_lower:
            activity_type = "reasoning"
        elif "verify" in event_lower:
            activity_type = "operation"
        elif "approval" in event_lower:
            activity_type = "system"
        elif "invoke" in event_lower or "runtime" in event_lower:
            activity_type = "operation"
        elif "a2a" in event_lower:
            activity_type = "a2a"
        elif "plan" in event_lower:
            activity_type = "reasoning"
        elif "handoff" in event_lower:
            activity_type = "a2a"
        elif "artifact" in event_lower:
            activity_type = "file"
        elif "tool" in event_lower:
            activity_type = "operation"
        elif "decision" in event_lower or "branch" in event_lower:
            activity_type = "reasoning"
        elif "error" in event_lower:
            activity_type = "error"

        # Determine severity from event type or payload
        if "failed" in event_lower or "error" in event_lower:
            severity = "error"
        elif "warning" in event_lower:
            severity = "warning"
        elif "completed" in event_lower or "success" in event_lower:
            severity = "success"
        elif "started" in event_lower or "pending" in event_lower:
            severity = "info"
        elif "approval" in event_lower:
            severity = "warning"

        payload = record.get("payload")
        if not isinstance(payload, dict):
            payload = {
                key: value
                for key, value in record.items()
                if key not in {"timestamp", "event", "kind", "resource", "payload"}
            }

        # Extract tool information from payload
        tool_name = str(payload.get("tool_name") or payload.get("tool") or "").strip()
        duration = payload.get("duration_ms") or payload.get("durationMs") or payload.get("latencyMs")

        # Build summary (short message suitable for compact display)
        step = payload.get("step") or payload.get("stepName") or ""
        if "artifact" in event_lower and step:
            path = payload.get("path") or payload.get("name") or ""
            summary_msg = f"Artifact: {path}" if path else f"Artifact: {step}"
        elif tool_name and "tool" in event_lower:
            summary_msg = f"Tool: {tool_name}"
        elif "decision" in event_lower:
            summary_msg = f"Decision: {step}"
        else:
            summary_msg = ""

        return {
            "id": hashlib.sha256(line.encode()).hexdigest()[:16],
            "timestamp": record.get("timestamp") or datetime.now(UTC).isoformat(),
            "type": activity_type,
            "severity": severity,
            "event": event_type,
            "agentRef": payload.get("agentRef") or payload.get("agent") or record.get("agentRef") or "",
            "step": step,
            "runId": payload.get("runId") or record.get("runId") or "",
            "message": _activity_message(event_type, payload),
            "summary": summary_msg,
            "tool": tool_name if tool_name else None,
            "durationMs": duration,
            "details": payload,
            "source": "journal",
        }
    except Exception:
        return None


def _build_status_activity(
    *,
    event_type: str,
    timestamp: str | None,
    payload: dict[str, Any],
) -> dict[str, Any] | None:
    record = {
        "timestamp": timestamp or datetime.now(UTC).isoformat(),
        "event": event_type,
        "payload": payload,
    }
    parsed = _parse_journal_line(json.dumps(record, sort_keys=True))
    if parsed:
        parsed["source"] = "status"
    return parsed


def _status_step_state_activities(status: dict[str, Any], run_id: str) -> list[dict[str, Any]]:
    step_states = status.get("stepStates") or {}
    if not isinstance(step_states, dict):
        return []

    activities: list[dict[str, Any]] = []
    for step_name, raw_state in step_states.items():
        if not isinstance(raw_state, dict):
            continue
        state = raw_state
        status_name = str(state.get("status") or "").strip().lower()
        if not status_name:
            continue

        event_type = {
            "running": "workflow.step.started",
            "completed": "workflow.step.completed",
            "failed": "workflow.step.failed",
            "denied": "workflow.step.failed",
            "cancelled": "workflow.step.failed",
            "waiting-approval": "workflow.review.started",
        }.get(status_name, "workflow.step.updated")

        payload: dict[str, Any] = {
            "runId": run_id,
            "step": str(state.get("stepName") or step_name),
            "agentRef": str(state.get("agentRef") or ""),
            "status": status_name,
            "latencyMs": state.get("latencyMs"),
            "toolCallCount": state.get("toolCallCount"),
            "artifactCount": state.get("artifactCount"),
            "warnings": state.get("warnings") or [],
            "error": state.get("error"),
            "responsePreview": state.get("responsePreview"),
            "verificationResult": state.get("verificationResult"),
            "reviewResult": state.get("reviewResult"),
        }

        timestamp = (
            str(state.get("updatedAt") or "").strip()
            or str(state.get("completedAt") or "").strip()
            or str(state.get("startedAt") or "").strip()
            or None
        )
        activity = _build_status_activity(event_type=event_type, timestamp=timestamp, payload=payload)
        if activity:
            activities.append(activity)

    activities.sort(key=lambda item: str(item.get("timestamp") or ""))
    return activities


def _activity_message(event_type: str, payload: dict[str, Any]) -> str:
    """Build a human-readable message from a journal event."""
    step = payload.get("step") or payload.get("stepName") or ""
    if event_type == "workflow.step.started":
        return f"Step '{step}' started"
    if event_type == "workflow.step.completed":
        tc = payload.get("toolCallCount")
        ac = payload.get("artifactCount")
        parts = []
        if tc is not None:
            parts.append(f"{tc} tool calls")
        if ac is not None:
            parts.append(f"{ac} artifacts")
        suffix = f" ({', '.join(parts)})" if parts else ""
        return f"Step '{step}' completed{suffix}"
    if event_type == "workflow.step.failed":
        err = (payload.get("error") or "")[:120]
        return f"Step '{step}' failed: {err}" if err else f"Step '{step}' failed"
    if event_type == "workflow.step.updated":
        status = payload.get("status", "")
        tc = payload.get("toolCallCount")
        ac = payload.get("artifactCount")
        parts = []
        if tc is not None:
            parts.append(f"{tc} tools")
        if ac is not None:
            parts.append(f"{ac} files")
        suffix = f" ({', '.join(parts)})" if parts else ""
        return f"Step '{step}' {status}{suffix}"
    if event_type == "workflow.loop.iteration.completed":
        completed = payload.get("completedItems", 0)
        return f"Loop iteration completed ({completed} items done)"
    if event_type == "workflow.loop.iteration.failed":
        return f"Loop iteration failed: {payload.get('error', '')}"
    if event_type == "workflow.step.verify.started":
        return f"Verifying step '{step}'"
    if event_type == "workflow.step.verify.completed":
        result = payload.get("result", "done")
        passed = payload.get("passed")
        if passed is not None:
            return f"Verification for '{step}': {'PASSED' if passed else 'FAILED'}"
        return f"Verification for '{step}': {result}"
    if "approval" in event_type:
        return f"Approval: {payload.get('status', event_type)} for '{step}'"
    if "artifact" in event_type:
        path = payload.get("path") or payload.get("name") or ""
        return f"Artifact: {path}" if path else f"Artifact in '{step}'"
    if "tool" in event_type:
        tool = payload.get("tool_name") or payload.get("tool") or ""
        return f"Tool: {tool}" if tool else f"Tool call in '{step}'"
    if "handoff" in event_type:
        target = payload.get("target_agent") or payload.get("target") or ""
        return f"Handoff to {target}" if target else f"Agent handoff in '{step}'"
    if "decision" in event_type or "branch" in event_type:
        return f"Decision in '{step}'"
    return event_type.replace(".", " ").replace("_", " ").title()


@router.get("/workflows/{workflow_name}/runs")
def get_workflow_runs(
    workflow_name: str,
    namespace: str = "default",
    limit: int = 20,
    user=Depends(verify_token),
):
    """Return the recent run history for a workflow."""
    ensure_namespace_access(user, namespace)
    return list_workflow_runs(workflow_name, namespace, limit=limit)


@router.get("/workflows/{workflow_name}/runs/{run_id}/trace")
def get_workflow_run_trace_endpoint(
    workflow_name: str,
    run_id: str,
    namespace: str = "default",
    tail: int = 4000,
    user=Depends(verify_token),
):
    ensure_namespace_access(user, namespace)
    tail = max(1, min(tail, 20000))
    return _resolve_workflow_run_trace_payload(
        workflow_name,
        namespace,
        run_id,
        tail=tail,
        persist_live_fallback=True,
    )


@router.get("/workflows/{workflow_name}/runs/{run_id}/export")
def export_workflow_run_trace(
    workflow_name: str,
    run_id: str,
    namespace: str = "default",
    user=Depends(verify_token),
):
    ensure_namespace_access(user, namespace)
    payload = _resolve_workflow_run_trace_payload(
        workflow_name,
        namespace,
        run_id,
        tail=None,
        persist_live_fallback=True,
    )
    response = JSONResponse(payload)
    response.headers["Content-Disposition"] = f'attachment; filename="{workflow_name}-{run_id}-trace.json"'
    return response


@router.get("/workflows/{workflow_name}/logs")
def get_workflow_logs(
    workflow_name: str,
    namespace: str = "default",
    tail: int = 200,
    user=Depends(verify_token),
):
    ensure_namespace_access(user, namespace)
    tail = max(1, min(tail, 5000))
    resource = read_custom_resource("agentworkflows", workflow_name, namespace, "Workflow")
    status = (resource.get("status") or {}) if isinstance(resource, dict) else {}
    run_id = str(status.get("runId") or "") or None
    worker_job = status.get("workerJob") or {}
    job_name = str(worker_job.get("name") or "")
    job_namespace = str(worker_job.get("namespace") or namespace)
    if not job_name:
        archived_logs = _fallback_workflow_logs_from_run(workflow_name, namespace, run_id, tail=tail)
        if archived_logs is not None:
            return archived_logs
        raise HTTPException(status_code=404, detail=f"No worker job found for workflow '{workflow_name}'")

    try:
        logs, pod_name = _read_workflow_job_logs(job_name, job_namespace, tail)
        return {
            "workflow_name": workflow_name,
            "run_id": run_id,
            "job_name": job_name,
            "pod_name": pod_name,
            "source": "live-worker",
            "archived_log_available": False,
            "logs": logs,
        }
    except HTTPException:
        archived_logs = _fallback_workflow_logs_from_run(workflow_name, namespace, run_id, tail=tail)
        if archived_logs is not None:
            return archived_logs
        raise
    except Exception as exc:
        logger.warning("Could not retrieve workflow logs for %s: %s", workflow_name, exc)
        archived_logs = _fallback_workflow_logs_from_run(workflow_name, namespace, run_id, tail=tail)
        if archived_logs is not None:
            return archived_logs
        raise HTTPException(status_code=404, detail="Could not retrieve workflow logs") from exc


@router.get("/workflows/{workflow_name}/logs/stream")
async def stream_workflow_logs(
    workflow_name: str,
    request: Request,
    namespace: str = "default",
    tail: int = 50,
    user=Depends(verify_token),
):
    ensure_namespace_access(user, namespace)
    tail = max(1, min(tail, 5000))
    resource = read_custom_resource("agentworkflows", workflow_name, namespace, "Workflow")
    status = (resource.get("status") or {}) if isinstance(resource, dict) else {}
    worker_job = status.get("workerJob") or {}
    job_name = str(worker_job.get("name") or "")
    job_namespace = str(worker_job.get("namespace") or namespace)
    if not job_name:
        raise HTTPException(status_code=404, detail=f"No worker job found for workflow '{workflow_name}'")

    pods = list_job_pods(job_name, job_namespace)
    if not pods:
        raise HTTPException(status_code=404, detail=f"No worker pod found for workflow '{workflow_name}'")

    pod_name = str(getattr(pods[0].metadata, "name", "") or "")
    if not pod_name:
        raise HTTPException(status_code=404, detail=f"No worker pod found for workflow '{workflow_name}'")

    async def log_event_generator():
        import time

        from kubernetes import client as k8s_client
        from kubernetes import watch as k8s_watch

        yield sse_event("log.started", {"workflow_name": workflow_name, "job_name": job_name, "pod_name": pod_name})

        w = k8s_watch.Watch()
        try:
            log_stream = w.stream(
                k8s_client.CoreV1Api().read_namespaced_pod_log,
                name=pod_name,
                namespace=job_namespace,
                container="worker",
                follow=True,
                tail_lines=tail,
                timestamps=True,
                _request_timeout=0,
            )
            last_event_time = time.monotonic()
            for line in log_stream:
                if await request.is_disconnected():
                    break
                yield sse_event("log.line", {"line": line})
                last_event_time = time.monotonic()
                await asyncio.sleep(0)
                if time.monotonic() - last_event_time > STREAM_KEEPALIVE_SECONDS:
                    yield sse_keepalive_comment()
                    last_event_time = time.monotonic()
        except Exception as exc:
            yield sse_event("log.error", {"error": str(exc)})
        finally:
            w.stop()
            yield sse_event("log.stopped", {"workflow_name": workflow_name, "job_name": job_name})

    return StreamingResponse(log_event_generator(), media_type="text/event-stream")


@router.get("/workflows/{workflow_name}/next-action")
def get_workflow_next_action(
    workflow_name: str,
    namespace: str = "default",
    user=Depends(verify_token),
):
    """Return a suggested next action based on the workflow's current state."""
    ensure_namespace_access(user, namespace)
    try:
        resource = read_custom_resource("agentworkflows", workflow_name, namespace, "Workflow")
    except Exception:
        return {"action": "Create a workflow", "reason": "Workflow not found."}

    status = (resource.get("status") or {}) if isinstance(resource, dict) else {}
    phase = str(status.get("phase", "") or "").strip()
    step_states = status.get("stepStates") or {}

    # Determine failed steps
    failed_steps = [
        name
        for name, state in step_states.items()
        if isinstance(state, dict) and str(state.get("status", "")).strip() == "failed"
    ]
    # Determine review results
    rejected_reviews = [
        name
        for name, state in step_states.items()
        if isinstance(state, dict)
        and isinstance(state.get("reviewResult"), dict)
        and not state["reviewResult"].get("approved", True)
    ]
    # Determine verification failures
    verify_failures = [
        name
        for name, state in step_states.items()
        if isinstance(state, dict)
        and isinstance(state.get("verificationResult"), dict)
        and not state["verificationResult"].get("passed", True)
    ]

    if phase == "failed":
        if failed_steps:
            return {
                "action": "Retry failed steps",
                "reason": f"Workflow failed at step(s): {', '.join(failed_steps)}. Use retry-failed to re-run only the failed steps while preserving completed work.",
                "failedSteps": failed_steps,
                "retryAvailable": True,
            }
        return {"action": "Inspect workflow failure and retry", "reason": "Workflow is in failed state."}

    if phase == "waiting-approval":
        pending = status.get("pendingApproval") or {}
        step_name = pending.get("stepName", "unknown")
        return {
            "action": f"Approve or reject step '{step_name}'",
            "reason": "Workflow is waiting for human approval.",
        }

    if phase == "completed":
        if rejected_reviews:
            return {
                "action": f"Address review findings in step(s): {', '.join(rejected_reviews)}",
                "reason": "One or more review steps were rejected.",
                "rejectedReviews": rejected_reviews,
            }
        if verify_failures:
            return {
                "action": f"Fix verification failures in step(s): {', '.join(verify_failures)}",
                "reason": "One or more steps failed verification.",
                "verifyFailures": verify_failures,
            }
        return {"action": "Deploy or promote", "reason": "All steps completed and verified successfully."}

    if phase == "running":
        current = str(status.get("currentStep", "") or "")
        return {"action": "Wait for completion", "reason": f"Workflow is running (current: {current})."}

    return {"action": "Trigger workflow", "reason": "Workflow has not been started."}
