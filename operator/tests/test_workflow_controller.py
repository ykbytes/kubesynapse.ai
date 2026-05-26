import importlib.util
import logging
import sys
import types
import unittest
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

MODULE_PATH = Path(__file__).resolve().parents[1] / "controllers" / "workflow_controller.py"
STUB_MODULE_NAMES = [
    "kopf",
    "builders",
    "config",
    "controllers",
    "controllers.agent_controller",
    "reconcile",
    "services",
    "utils",
]


def _identity_decorator(*_args, **_kwargs):
    def decorator(func):
        return func

    return decorator


def _install_stub_modules() -> dict[str, object | None]:
    kopf_module = types.ModuleType("kopf")

    class _KopfOn:
        create = staticmethod(_identity_decorator)
        update = staticmethod(_identity_decorator)
        resume = staticmethod(_identity_decorator)
        delete = staticmethod(_identity_decorator)
        field = staticmethod(_identity_decorator)

    kopf_module.on = _KopfOn()
    kopf_module.timer = _identity_decorator
    kopf_module.PermanentError = type("PermanentError", (Exception,), {})

    builders_module = types.ModuleType("builders")
    builders_module.artifact_file_path = lambda *_args, **_kwargs: "/tmp/workflow.json"  # noqa: S108
    builders_module.build_artifact_ref = lambda pvc_name, path, generation, **kwargs: {
        "pvcName": pvc_name,
        "path": path,
        "generation": generation,
        **kwargs,
    }
    builders_module.build_journal_ref = lambda pvc_name, path, generation: {
        "pvcName": pvc_name,
        "path": path,
        "generation": generation,
    }

    config_module = types.ModuleType("config")
    config_module.OPERATOR_NAMESPACE = "ai-agent-sandbox"
    config_module.WORKFLOW_POLL_SECONDS = 30
    config_module.WORKFLOW_QUEUE_STALE_SECONDS = 60
    config_module.WORKFLOW_RUNNING_STALE_SECONDS = 120

    controllers_module = types.ModuleType("controllers")
    agent_controller_module = types.ModuleType("controllers.agent_controller")
    agent_controller_module.resolve_tenant_for_namespace = lambda _namespace: None
    controllers_module.agent_controller = agent_controller_module

    reconcile_module = types.ModuleType("reconcile")
    reconcile_module.execute_reconcile = lambda fn, **_kwargs: fn()
    reconcile_module.inject_conditions = lambda payload: payload
    reconcile_module.log_operator_event = lambda *_args, **_kwargs: None

    services_module = types.ModuleType("services")
    services_module.cancel_worker_job = lambda *_args, **_kwargs: True
    services_module.ensure_worker_artifact_storage = lambda *_args, **_kwargs: "artifact-pvc"
    services_module.enqueue_worker_job = lambda *_args, **_kwargs: "worker-job"
    services_module.patch_custom_status = lambda *_args, **_kwargs: None
    services_module.read_job_state = lambda *_args, **_kwargs: "missing"
    services_module.read_worker_lease_freshness = lambda *_args, **_kwargs: (False, "")

    utils_module = types.ModuleType("utils")
    utils_module.build_workflow_run_id = (
        lambda namespace, workflow_name, generation: f"wf-run-{namespace}-{workflow_name}-{generation}-new"
    )
    utils_module.now_iso = lambda: "2026-04-08T12:00:00Z"
    utils_module.validate_workflow_graph = lambda steps: {"roots": [steps[0]["name"]] if steps else []}
    utils_module.workflow_journal_path = lambda path: f"{path}.journal"

    previous_modules: dict[str, object | None] = {}
    for name, module in [
        ("kopf", kopf_module),
        ("builders", builders_module),
        ("config", config_module),
        ("controllers", controllers_module),
        ("controllers.agent_controller", agent_controller_module),
        ("reconcile", reconcile_module),
        ("services", services_module),
        ("utils", utils_module),
    ]:
        previous_modules[name] = sys.modules.get(name)
        sys.modules[name] = module

    return previous_modules


def load_workflow_controller() -> tuple[str, object, dict[str, object | None]]:
    previous_modules = _install_stub_modules()
    module_name = f"operator_workflow_controller_test_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(module_name, MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Failed to load workflow_controller module for tests")

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(module_name, None)
        raise
    return module_name, module, previous_modules


class WorkflowControllerRunIdTests(unittest.TestCase):
    def setUp(self) -> None:
        self.module_name, self.controller, self.previous_modules = load_workflow_controller()
        self.addCleanup(lambda: sys.modules.pop(self.module_name, None))
        self.addCleanup(self._cleanup_stub_modules)

    def _cleanup_stub_modules(self) -> None:
        for module_name in reversed(STUB_MODULE_NAMES):
            previous_module = self.previous_modules.get(module_name)
            if previous_module is None:
                sys.modules.pop(module_name, None)
            else:
                sys.modules[module_name] = previous_module

    def test_resolve_workflow_run_id_mints_new_id_for_new_generation(self) -> None:
        resolved = self.controller.resolve_workflow_run_id(
            "default",
            "kubesynapse-factory-pipeline",
            24,
            workflow_status={
                "runId": "wf-run-default-kubesynapse-factory-pipeline-23-old",
                "observedGeneration": 23,
                "artifactRef": {"generation": 23},
            },
        )

        self.assertEqual(resolved, "wf-run-default-kubesynapse-factory-pipeline-24-new")

    def test_resolve_workflow_run_id_preserves_same_generation_retry_run(self) -> None:
        resolved = self.controller.resolve_workflow_run_id(
            "default",
            "kubesynapse-factory-pipeline",
            7,
            workflow_status={
                "runId": "wf-run-default-kubesynapse-factory-pipeline-7-retry",
                "observedGeneration": 7,
                "artifactRef": {"generation": 7},
            },
        )

        self.assertEqual(resolved, "wf-run-default-kubesynapse-factory-pipeline-7-retry")

    def test_enqueue_workflow_job_clears_stale_progress_for_new_generation(self) -> None:
        patch_status_mock = MagicMock()
        enqueue_mock = MagicMock(return_value="job-24")
        cancel_mock = MagicMock(return_value=True)

        with patch.object(self.controller, "patch_custom_status", patch_status_mock), \
             patch.object(self.controller, "enqueue_worker_job", enqueue_mock), \
             patch.object(self.controller, "cancel_worker_job", cancel_mock):
            self.controller.enqueue_workflow_job(
                spec={"steps": [{"name": "draft-blueprint"}, {"name": "deploy-bundle"}]},
                meta={"generation": 24},
                name="kubesynapse-factory-pipeline",
                namespace="default",
                logger=logging.getLogger("test"),
                current_status={
                    "runId": "wf-run-default-kubesynapse-factory-pipeline-23-old",
                    "observedGeneration": 23,
                    "artifactRef": {"generation": 23, "path": "/tmp/old.json"},  # noqa: S108
                    "currentStep": "deploy-bundle",
                    "pendingApproval": {"name": "approval-old"},
                    "stepStates": {"draft-blueprint": {"status": "completed"}},
                    "summary": {"completedSteps": 1, "error": "old failure"},
                    "workerJob": {"name": "job-23", "namespace": "ai-agent-sandbox"},
                },
            )

        cancel_mock.assert_called_once_with("job-23", "ai-agent-sandbox")
        enqueue_mock.assert_called_once()
        patched_status = patch_status_mock.call_args.args[3]
        self.assertEqual(patched_status["runId"], "wf-run-default-kubesynapse-factory-pipeline-24-new")
        self.assertEqual(patched_status["currentStep"], "")
        self.assertIsNone(patched_status["pendingApproval"])
        self.assertEqual(patched_status["stepStates"], {})
        self.assertEqual(patched_status["summary"]["completedSteps"], 0)
        self.assertNotIn("error", patched_status["summary"])

    def test_enqueue_workflow_job_preserves_same_generation_retry_progress(self) -> None:
        patch_status_mock = MagicMock()
        enqueue_mock = MagicMock(return_value="job-7")

        with patch.object(self.controller, "patch_custom_status", patch_status_mock), \
             patch.object(self.controller, "enqueue_worker_job", enqueue_mock):
            self.controller.enqueue_workflow_job(
                spec={"steps": [{"name": "draft-blueprint"}, {"name": "deploy-bundle"}]},
                meta={"generation": 7},
                name="kubesynapse-factory-pipeline",
                namespace="default",
                logger=logging.getLogger("test"),
                current_status={
                    "runId": "wf-run-default-kubesynapse-factory-pipeline-7-retry",
                    "observedGeneration": 7,
                    "artifactRef": {"generation": 7, "path": "/tmp/gen-7.json"},  # noqa: S108
                    "currentStep": "deploy-bundle",
                    "stepStates": {
                        "draft-blueprint": {"status": "completed"},
                        "deploy-bundle": {"status": "pending"},
                    },
                    "summary": {
                        "completedSteps": 1,
                        "error": "stale failure",
                        "failedAt": "2026-04-09T09:00:00Z",
                        "completedAt": "2026-04-09T08:00:00Z",
                    },
                },
            )

        patched_status = patch_status_mock.call_args.args[3]
        self.assertEqual(patched_status["runId"], "wf-run-default-kubesynapse-factory-pipeline-7-retry")
        self.assertEqual(patched_status["currentStep"], "deploy-bundle")
        self.assertEqual(patched_status["stepStates"]["draft-blueprint"]["status"], "completed")
        self.assertEqual(patched_status["summary"]["completedSteps"], 1)
        self.assertIsNone(patched_status["summary"]["error"])
        self.assertIsNone(patched_status["summary"]["failedAt"])
        self.assertIsNone(patched_status["summary"]["completedAt"])

    def test_enqueue_workflow_job_uses_workflow_constants_for_owner_ref_and_status_patch(self) -> None:
        patch_status_mock = MagicMock()
        enqueue_mock = MagicMock(return_value="job-42")
        ensure_storage_mock = MagicMock(return_value="artifact-pvc")

        with patch.object(self.controller, "patch_custom_status", patch_status_mock), \
             patch.object(self.controller, "enqueue_worker_job", enqueue_mock), \
             patch.object(self.controller, "ensure_worker_artifact_storage", ensure_storage_mock):
            self.controller.enqueue_workflow_job(
                spec={"steps": [{"name": "plan"}]},
                meta={"generation": 42, "uid": "uid-42"},
                name="jupiter8-web-synth",
                namespace="default",
                logger=logging.getLogger("test"),
            )

        owner_refs = ensure_storage_mock.call_args.args[3]
        self.assertEqual(owner_refs[0]["apiVersion"], f"{self.controller.GROUP}/{self.controller.VERSION}")
        self.assertEqual(owner_refs[0]["kind"], "AgentWorkflow")
        self.assertEqual(owner_refs[0]["name"], "jupiter8-web-synth")
        self.assertEqual(patch_status_mock.call_args.args[0], self.controller.WORKFLOW_PLURAL)

    def test_resolve_failed_workflow_auto_retry_plan_accepts_recoverable_failures(self) -> None:
        plan = self.controller.resolve_failed_workflow_auto_retry_plan(
            spec={"steps": [{"name": "draft-blueprint"}]},
            status={
                "phase": "failed",
                "runId": "wf-run-default-kubesynapse-factory-pipeline-7-old",
                "observedGeneration": 7,
                "artifactRef": {"generation": 7},
                "stepStates": {
                    "draft-blueprint": {
                        "status": "failed",
                        "failureClass": "TimeoutError",
                        "error": "agent runtime timed out",
                    },
                    "review": {"status": "completed"},
                },
                "summary": {"autoRetryCount": 0, "completedSteps": 1},
            },
            meta={
                "generation": 7,
                "annotations": {
                    self.controller.AUTO_RETRY_FAILED_ANNOTATION: "true",
                    self.controller.AUTO_RETRY_LIMIT_ANNOTATION: "2",
                },
            },
            name="kubesynapse-factory-pipeline",
            namespace="default",
        )

        self.assertIsNotNone(plan)
        assert plan is not None
        self.assertEqual(plan["runId"], "wf-run-default-kubesynapse-factory-pipeline-7-new")
        self.assertEqual(plan["failedSteps"], ["draft-blueprint"])
        self.assertEqual(plan["stepStates"]["draft-blueprint"]["status"], "pending")
        self.assertEqual(plan["stepStates"]["review"]["status"], "completed")
        self.assertEqual(plan["summary"]["autoRetryCount"], 1)
        self.assertEqual(plan["summary"]["runId"], "wf-run-default-kubesynapse-factory-pipeline-7-new")

    def test_resolve_failed_workflow_auto_retry_plan_skips_quality_gate_failures(self) -> None:
        plan = self.controller.resolve_failed_workflow_auto_retry_plan(
            spec={"steps": [{"name": "deploy-bundle"}]},
            status={
                "phase": "failed",
                "stepStates": {
                    "deploy-bundle": {
                        "status": "failed",
                        "failureClass": "RuntimeError",
                        "error": "Verification failed for step 'deploy-bundle' after 1 attempt(s): FAIL",
                    }
                },
                "summary": {"autoRetryCount": 0},
            },
            meta={
                "generation": 11,
                "annotations": {
                    self.controller.AUTO_RETRY_FAILED_ANNOTATION: "true",
                    self.controller.AUTO_RETRY_LIMIT_ANNOTATION: "2",
                    self.controller.AUTO_RETRY_FAILURE_CLASSES_ANNOTATION: "RuntimeError,TimeoutError",
                },
            },
            name="kubesynapse-factory-pipeline",
            namespace="default",
        )

        self.assertIsNone(plan)

    def test_resolve_auto_retry_config_uses_spec_fields(self) -> None:
        config = self.controller.resolve_auto_retry_config(
            {
                "autoRetry": {
                    "enabled": True,
                    "maxAttempts": 3,
                    "retryableFailureClasses": ["TimeoutError", "HTTPStatusError"],
                    "nonRetryableFailureClasses": ["ValueError"],
                }
            },
            {},
        )

        self.assertTrue(config["enabled"])
        self.assertEqual(config["maxAttempts"], 3)
        self.assertEqual(config["retryableFailureClasses"], {"TimeoutError", "HTTPStatusError"})
        self.assertIn("valueerror", config["nonRetryableFailureClasses"])
        self.assertIn("reviewrejectederror", config["nonRetryableFailureClasses"])

    def test_resolve_auto_retry_config_prefers_spec_over_annotations(self) -> None:
        config = self.controller.resolve_auto_retry_config(
            {
                "autoRetry": {
                    "enabled": False,
                    "maxAttempts": 4,
                    "retryableFailureClasses": ["ReadTimeout"],
                }
            },
            {
                self.controller.AUTO_RETRY_FAILED_ANNOTATION: "true",
                self.controller.AUTO_RETRY_LIMIT_ANNOTATION: "1",
                self.controller.AUTO_RETRY_FAILURE_CLASSES_ANNOTATION: "TimeoutError,ConnectTimeout",
            },
        )

        self.assertFalse(config["enabled"])
        self.assertEqual(config["maxAttempts"], 4)
        self.assertEqual(config["retryableFailureClasses"], {"ReadTimeout"})

    def test_resolve_failed_workflow_auto_retry_plan_uses_spec_without_annotations(self) -> None:
        plan = self.controller.resolve_failed_workflow_auto_retry_plan(
            spec={
                "autoRetry": {
                    "enabled": True,
                    "maxAttempts": 2,
                    "retryableFailureClasses": ["TimeoutError"],
                },
                "steps": [{"name": "draft-blueprint"}],
            },
            status={
                "phase": "failed",
                "stepStates": {
                    "draft-blueprint": {
                        "status": "failed",
                        "failureClass": "TimeoutError",
                        "error": "agent runtime timed out",
                    }
                },
                "summary": {"autoRetryCount": 0},
            },
            meta={"generation": 12, "annotations": {}},
            name="kubesynapse-factory-pipeline",
            namespace="default",
        )

        self.assertIsNotNone(plan)
        assert plan is not None
        self.assertEqual(plan["stepStates"]["draft-blueprint"]["status"], "pending")

    def test_spec_non_retryable_failure_classes_override_retryable_set(self) -> None:
        plan = self.controller.resolve_failed_workflow_auto_retry_plan(
            spec={
                "autoRetry": {
                    "enabled": True,
                    "maxAttempts": 2,
                    "retryableFailureClasses": ["HTTPStatusError"],
                    "nonRetryableFailureClasses": ["HTTPStatusError"],
                },
                "steps": [{"name": "draft-blueprint"}],
            },
            status={
                "phase": "failed",
                "stepStates": {
                    "draft-blueprint": {
                        "status": "failed",
                        "failureClass": "HTTPStatusError",
                        "error": "status code 503 from upstream",
                    }
                },
                "summary": {"autoRetryCount": 0},
            },
            meta={"generation": 13, "annotations": {}},
            name="kubesynapse-factory-pipeline",
            namespace="default",
        )

        self.assertIsNone(plan)

    def test_watchdog_auto_retries_failed_workflow_when_enabled(self) -> None:
        enqueue_mock = MagicMock(return_value="job-7")

        with patch.object(self.controller, "enqueue_workflow_job", enqueue_mock):
            self.controller.run_workflow_watchdog(
                spec={"steps": [{"name": "draft-blueprint"}]},
                status={
                    "phase": "failed",
                    "runId": "wf-run-default-kubesynapse-factory-pipeline-7-old",
                    "observedGeneration": 7,
                    "artifactRef": {"generation": 7},
                    "workerJob": {"name": "job-7-old", "namespace": "ai-agent-sandbox"},
                    "stepStates": {
                        "draft-blueprint": {
                            "status": "failed",
                            "failureClass": "TimeoutError",
                            "error": "agent runtime timed out",
                        }
                    },
                    "summary": {"autoRetryCount": 0},
                },
                meta={
                    "generation": 7,
                    "annotations": {
                        self.controller.AUTO_RETRY_FAILED_ANNOTATION: "true",
                        self.controller.AUTO_RETRY_LIMIT_ANNOTATION: "1",
                    },
                },
                name="kubesynapse-factory-pipeline",
                namespace="default",
                logger=logging.getLogger("test"),
            )

        enqueue_mock.assert_called_once()
        enqueue_kwargs = enqueue_mock.call_args.kwargs
        self.assertEqual(enqueue_kwargs["run_id"], "wf-run-default-kubesynapse-factory-pipeline-7-new")
        retry_status = enqueue_kwargs["current_status"]
        self.assertEqual(retry_status["phase"], "pending")
        self.assertEqual(retry_status["stepStates"]["draft-blueprint"]["status"], "pending")
        self.assertEqual(retry_status["summary"]["autoRetryCount"], 1)

    def test_watchdog_auto_retries_failed_workflow_using_spec_config(self) -> None:
        enqueue_mock = MagicMock(return_value="job-9")

        with patch.object(self.controller, "enqueue_workflow_job", enqueue_mock):
            self.controller.run_workflow_watchdog(
                spec={
                    "autoRetry": {
                        "enabled": True,
                        "maxAttempts": 1,
                        "retryableFailureClasses": ["TimeoutError"],
                    },
                    "steps": [{"name": "draft-blueprint"}],
                },
                status={
                    "phase": "failed",
                    "runId": "wf-run-default-kubesynapse-factory-pipeline-9-old",
                    "observedGeneration": 9,
                    "artifactRef": {"generation": 9},
                    "workerJob": {"name": "job-9-old", "namespace": "ai-agent-sandbox"},
                    "stepStates": {
                        "draft-blueprint": {
                            "status": "failed",
                            "failureClass": "TimeoutError",
                            "error": "agent runtime timed out",
                        }
                    },
                    "summary": {"autoRetryCount": 0},
                },
                meta={"generation": 9, "annotations": {}},
                name="kubesynapse-factory-pipeline",
                namespace="default",
                logger=logging.getLogger("test"),
            )

        enqueue_mock.assert_called_once()
        enqueue_kwargs = enqueue_mock.call_args.kwargs
        self.assertEqual(enqueue_kwargs["run_id"], "wf-run-default-kubesynapse-factory-pipeline-9-new")


class WorkflowDispatchReliabilityTests(unittest.TestCase):
    """§reliability-P2: Regression tests for workflow dispatch fixes."""

    def setUp(self) -> None:
        self.module_name, self.controller, self.previous_modules = load_workflow_controller()
        self.addCleanup(lambda: sys.modules.pop(self.module_name, None))
        self.addCleanup(self._cleanup_stub_modules)

    def _cleanup_stub_modules(self) -> None:
        for module_name in reversed(STUB_MODULE_NAMES):
            previous_module = self.previous_modules.get(module_name)
            if previous_module is None:
                sys.modules.pop(module_name, None)
            else:
                sys.modules[module_name] = previous_module

    def test_workflow_should_requeue_returns_none_when_lease_is_fresh(self) -> None:
        """Watchdog must NOT requeue when worker lease is still fresh."""
        # Simulate a fresh lease — patch the controller module's reference
        with patch.object(
            self.controller,
            "read_worker_lease_freshness",
            return_value=(True, "workflow-default-standup-af4f22a46b"),
        ):
            reason = self.controller.workflow_should_requeue(
                {"phase": "queued", "summary": {"queuedAt": "2026-04-08T11:00:00Z"}},
                "active",
                name="standup",
                generation=1,
            )
        self.assertIsNone(reason)

    def test_workflow_should_requeue_falls_through_when_lease_expired(self) -> None:
        """Watchdog should requeue when the lease has expired and job is missing."""
        with patch.object(
            self.controller,
            "read_worker_lease_freshness",
            return_value=(False, ""),
        ):
            reason = self.controller.workflow_should_requeue(
                {
                    "phase": "queued",
                    "summary": {"queuedAt": "2020-01-01T00:00:00Z"},
                },
                "missing",
                name="standup",
                generation=1,
            )
        self.assertIsNotNone(reason)
        self.assertIn("missing", reason)

    def test_enqueue_workflow_job_passes_resource_uid_to_service(self) -> None:
        """resource_uid from meta.uid must propagate to enqueue_worker_job."""
        enqueue_mock = MagicMock(return_value="job-uid-test")
        patch_mock = MagicMock()

        with patch.object(self.controller, "enqueue_worker_job", enqueue_mock), \
             patch.object(self.controller, "patch_custom_status", patch_mock):
            self.controller.enqueue_workflow_job(
                spec={"steps": [{"name": "plan"}]},
                meta={"generation": 1, "uid": "uid-abc123"},
                name="test-workflow",
                namespace="default",
                logger=logging.getLogger("test"),
            )

        enqueue_mock.assert_called_once()
        _, kwargs = enqueue_mock.call_args
        self.assertEqual(kwargs.get("resource_uid"), "uid-abc123")

    def test_enqueue_workflow_job_stores_resource_uid_in_summary(self) -> None:
        """Summary must contain resourceUid for DB conflict scoping."""
        patch_mock = MagicMock()
        enqueue_mock = MagicMock(return_value="job-sum-test")

        with patch.object(self.controller, "enqueue_worker_job", enqueue_mock), \
             patch.object(self.controller, "patch_custom_status", patch_mock):
            self.controller.enqueue_workflow_job(
                spec={"steps": [{"name": "plan"}]},
                meta={"generation": 1, "uid": "uid-xyz789"},
                name="test-workflow",
                namespace="default",
                logger=logging.getLogger("test"),
            )

        patched_status = patch_mock.call_args.args[3]
        self.assertEqual(patched_status["summary"]["resourceUid"], "uid-xyz789")

    def test_enqueue_workflow_job_clears_stale_step_lifecycle_on_run_id_change(self) -> None:
        """When run_id changes within same generation, stale error/latency fields are cleared."""
        patch_mock = MagicMock()
        enqueue_mock = MagicMock(return_value="job-clear-test")

        with patch.object(self.controller, "enqueue_worker_job", enqueue_mock), \
             patch.object(self.controller, "patch_custom_status", patch_mock):
            self.controller.enqueue_workflow_job(
                spec={"steps": [{"name": "plan"}, {"name": "execute"}]},
                meta={"generation": 3, "uid": "uid-333"},
                name="test-workflow",
                namespace="default",
                logger=logging.getLogger("test"),
                current_status={
                    "runId": "old-run-id",
                    "observedGeneration": 3,
                    "stepStates": {
                        "plan": {
                            "status": "completed",
                            "completedAt": "2026-04-08T10:00:00Z",
                            "latencyMs": 5000,
                        },
                        "execute": {
                            "status": "failed",
                            "error": "timeout after 300s",
                            "failureClass": "TimeoutError",
                            "latencyMs": 300000,
                            "completedAt": "2026-04-08T10:05:00Z",
                        },
                    },
                    "summary": {"completedSteps": 1, "runId": "old-run-id"},
                    "workerJob": {"name": "old-job", "namespace": "ai-agent-sandbox"},
                },
                # A new run_id is explicitly passed (different from current status runId)
                run_id="new-run-id",
            )

        patched_status = patch_mock.call_args.args[3]
        step_states = patched_status["stepStates"]
        # Completed step keeps all lifecycle fields intact
        self.assertEqual(step_states["plan"]["status"], "completed")
        self.assertEqual(step_states["plan"]["completedAt"], "2026-04-08T10:00:00Z")
        self.assertEqual(step_states["plan"]["latencyMs"], 5000)
        # Failed step has stale lifecycle fields stripped
        self.assertEqual(step_states["execute"]["status"], "failed")
        self.assertNotIn("error", step_states["execute"])
        self.assertNotIn("failureClass", step_states["execute"])
        self.assertNotIn("latencyMs", step_states["execute"])
        self.assertNotIn("completedAt", step_states["execute"])

    def test_run_workflow_skips_when_live_status_shows_generation_reconciled(self) -> None:
        """run_workflow must not re-enqueue if live API shows generation already queued."""
        enqueue_mock = MagicMock(return_value="job-skip")

        # Simulate: event payload says observedGeneration=0, but live read shows generation=5 queued
        with patch.object(self.controller, "enqueue_workflow_job", enqueue_mock), \
             patch.object(
                 self.controller,
                 "_read_live_workflow_status",
                 return_value={"observedGeneration": 5, "phase": "queued"},
             ):
            self.controller.run_workflow(
                spec={"steps": [{"name": "plan"}]},
                status={"observedGeneration": 0, "phase": ""},
                meta={"generation": 5, "uid": "uid-live"},
                name="test-workflow",
                namespace="default",
                logger=logging.getLogger("test"),
            )

        # enqueue_workflow_job should NOT have been called
        enqueue_mock.assert_not_called()

    def test_run_workflow_proceeds_when_live_status_is_stale(self) -> None:
        """run_workflow must enqueue if live API also shows stale generation."""
        enqueue_mock = MagicMock(return_value="job-proceed")
        patch_mock = MagicMock()

        with patch.object(self.controller, "enqueue_workflow_job", enqueue_mock), \
             patch.object(self.controller, "patch_custom_status", patch_mock), \
             patch.object(
                 self.controller,
                 "_read_live_workflow_status",
                 return_value={"observedGeneration": 0, "phase": ""},
             ):
            self.controller.run_workflow(
                spec={"steps": [{"name": "plan"}]},
                status={"observedGeneration": 0, "phase": ""},
                meta={"generation": 5, "uid": "uid-proceed"},
                name="test-workflow",
                namespace="default",
                logger=logging.getLogger("test"),
            )

        # enqueue_workflow_job IS called (inside execute_reconcile lambda)
        # The reconcile lambda calls both patch_custom_status and enqueue_workflow_job
        enqueue_mock.assert_called_once()
