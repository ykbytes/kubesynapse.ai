"""AgentApproval reconciler — approval decision field handler.

§2.1d of the road-to-prod plan: approval controller extracted from main.py.
"""

from __future__ import annotations

import logging
from typing import Any

import kopf
import kubernetes.client  # type: ignore[import-untyped]
from builders import artifact_file_path, build_artifact_ref, build_journal_ref
from kubernetes.client.rest import ApiException  # type: ignore[import-untyped]
from reconcile import execute_reconcile, inject_conditions, log_operator_event
from services import (
    ensure_worker_artifact_storage,
    patch_custom_status,
)

from controllers.workflow_controller import enqueue_workflow_job
from utils import now_iso, workflow_journal_path

logger = logging.getLogger("operator.controllers.approval")


# ---------------------------------------------------------------------------
# Kopf handlers
# ---------------------------------------------------------------------------


@kopf.on.field("kubesynapse.ai", "v1alpha1", "agentapprovals", field="status.decision")  # type: ignore[arg-type]
def on_approval_decision(old: str | None, new: str | None, name: str, namespace: str, logger: logging.Logger, **kwargs: Any) -> None:
    del kwargs
    previous_decision = str(old or "").strip().lower()
    next_decision = str(new or "").strip().lower()

    # CRD creates can ignore initial status when the status subresource is enabled,
    # so the first persisted decision update may be None -> approved/denied.
    if next_decision in ("approved", "denied") and previous_decision not in ("approved", "denied"):
        log_operator_event(
            logger,
            logging.INFO,
            "Observed AgentApproval decision change.",
            resource_kind="AgentApproval",
            name=name,
            namespace=namespace,
            action="approval-decision",
            previousDecision=old,
            decision=next_decision,
        )
        custom_api = kubernetes.client.CustomObjectsApi()
        try:
            workflows = custom_api.list_namespaced_custom_object(
                group="kubesynapse.ai",
                version="v1alpha1",
                namespace=namespace,
                plural="agentworkflows",
                label_selector=f"kubesynapse.ai/pending-approval={name}",
            ).get("items", [])
        except ApiException:
            workflows = custom_api.list_namespaced_custom_object(
                group="kubesynapse.ai",
                version="v1alpha1",
                namespace=namespace,
                plural="agentworkflows",
            ).get("items", [])

        for workflow in workflows:
            workflow_name = workflow.get("metadata", {}).get("name", "")
            workflow_status = workflow.get("status", {}) or {}
            pending_approval = workflow_status.get("pendingApproval", {}) or {}
            if pending_approval.get("name") != name:
                continue
            if workflow_status.get("phase") != "waiting-approval":
                continue

            workflow_meta = workflow.get("metadata", {}) or {}
            workflow_spec = workflow.get("spec", {}) or {}
            generation = int(workflow_status.get("observedGeneration") or workflow_meta.get("generation", 1))
            run_id = str(workflow_status.get("runId") or "") or None

            if next_decision == "approved":
                job_name = execute_reconcile(
                    lambda _ws=workflow_spec, _wm=workflow_meta, _wn=workflow_name, _ws2=workflow_status, _rid=run_id: enqueue_workflow_job(
                        _ws,
                        _wm,
                        _wn,
                        namespace,
                        logger,
                        current_status=_ws2,
                        run_id=_rid,
                        requeue_reason=f"approval '{name}' was approved",
                    ),
                    logger=logger,
                    action="resume-workflow-after-approval",
                    resource_kind="AgentWorkflow",
                    name=workflow_name,
                    namespace=namespace,
                    meta=workflow_meta,
                    generation=generation,
                    default_delay=10,
                    start_message="Resuming workflow after approval.",
                    success_message="Workflow resumed after approval.",
                    approval=name,
                    decision=next_decision,
                )
                log_operator_event(
                    logger,
                    logging.INFO,
                    "Workflow resumed after approval.",
                    resource_kind="AgentWorkflow",
                    name=workflow_name,
                    namespace=namespace,
                    meta=workflow_meta,
                    generation=generation,
                    action="resume-workflow-after-approval",
                    approval=name,
                    decision=next_decision,
                    workerJob=job_name,
                )
            else:
                current_step = str(workflow_status.get("currentStep", "") or "")
                step_states = workflow_status.get("stepStates", {}) or {}
                if current_step:
                    current_step_state = dict(step_states.get(current_step, {}) or {})
                    current_step_state.update(
                        {
                            "status": "denied",
                            "updatedAt": now_iso(),
                            "completedAt": now_iso(),
                            "failureClass": "approval_denied",
                            "error": f"Approval '{name}' was denied",
                        }
                    )
                    step_states[current_step] = current_step_state

                artifact_ref = workflow_status.get("artifactRef", {}) or {}
                journal_path = str(
                    workflow_status.get("journalRef", {}).get("path")
                    or artifact_ref.get("journalPath")
                    or workflow_journal_path(
                        str(artifact_ref.get("path") or artifact_file_path("workflow", namespace, workflow_name, generation))
                    )
                )
                artifact_pvc_name = str(
                    artifact_ref.get("pvcName")
                    or ensure_worker_artifact_storage("workflow", namespace, workflow_name)
                )
                artifact_path = str(
                    artifact_ref.get("path")
                    or artifact_file_path("workflow", namespace, workflow_name, generation)
                )
                denial_status: dict[str, Any] = inject_conditions({
                    "phase": "failed",
                    "runId": workflow_status.get("runId"),
                    "currentStep": current_step,
                    "observedGeneration": generation,
                    "artifactRef": build_artifact_ref(
                        artifact_pvc_name,
                        artifact_path,
                        generation,
                        journal_path=journal_path,
                    ),
                    "journalRef": build_journal_ref(artifact_pvc_name, journal_path, generation),
                    "summary": {
                        **(workflow_status.get("summary", {}) or {}),
                        "failedAt": now_iso(),
                        "error": f"Approval '{name}' was denied",
                        "updatedAt": now_iso(),
                    },
                    "pendingApproval": {
                        "name": name,
                        "namespace": namespace,
                        "decision": next_decision,
                    },
                    "stepStates": step_states,
                })
                execute_reconcile(
                    lambda _wn=workflow_name, _ds=denial_status: patch_custom_status(
                        "agentworkflows",
                        namespace,
                        _wn,
                        _ds,
                    ),
                    logger=logger,
                    action="deny-workflow-after-approval",
                    resource_kind="AgentWorkflow",
                    name=workflow_name,
                    namespace=namespace,
                    meta=workflow_meta,
                    generation=generation,
                    default_delay=10,
                    start_message="Marking workflow as failed after approval denial.",
                    success_message="Workflow marked failed after approval denial.",
                    approval=name,
                    decision=next_decision,
                    currentStep=current_step,
                )
                # §2.5 — DB mirroring is now handled by the status projection controller.
