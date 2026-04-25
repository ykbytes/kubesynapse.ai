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
            "kubesynth-factory-pipeline",
            24,
            workflow_status={
                "runId": "wf-run-default-kubesynth-factory-pipeline-23-old",
                "observedGeneration": 23,
                "artifactRef": {"generation": 23},
            },
        )

        self.assertEqual(resolved, "wf-run-default-kubesynth-factory-pipeline-24-new")

    def test_resolve_workflow_run_id_preserves_same_generation_retry_run(self) -> None:
        resolved = self.controller.resolve_workflow_run_id(
            "default",
            "kubesynth-factory-pipeline",
            7,
            workflow_status={
                "runId": "wf-run-default-kubesynth-factory-pipeline-7-retry",
                "observedGeneration": None,
                "artifactRef": {"generation": 7},
            },
        )

        self.assertEqual(resolved, "wf-run-default-kubesynth-factory-pipeline-7-retry")

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
                name="kubesynth-factory-pipeline",
                namespace="default",
                logger=logging.getLogger("test"),
                current_status={
                    "runId": "wf-run-default-kubesynth-factory-pipeline-23-old",
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
        self.assertEqual(patched_status["runId"], "wf-run-default-kubesynth-factory-pipeline-24-new")
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
                name="kubesynth-factory-pipeline",
                namespace="default",
                logger=logging.getLogger("test"),
                current_status={
                    "runId": "wf-run-default-kubesynth-factory-pipeline-7-retry",
                    "observedGeneration": None,
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
        self.assertEqual(patched_status["runId"], "wf-run-default-kubesynth-factory-pipeline-7-retry")
        self.assertEqual(patched_status["currentStep"], "deploy-bundle")
        self.assertEqual(patched_status["stepStates"]["draft-blueprint"]["status"], "completed")
        self.assertEqual(patched_status["summary"]["completedSteps"], 1)
        self.assertIsNone(patched_status["summary"]["error"])
        self.assertIsNone(patched_status["summary"]["failedAt"])
        self.assertIsNone(patched_status["summary"]["completedAt"])

    def test_resolve_failed_workflow_auto_retry_plan_accepts_recoverable_failures(self) -> None:
        plan = self.controller.resolve_failed_workflow_auto_retry_plan(
            spec={"steps": [{"name": "draft-blueprint"}]},
            status={
                "phase": "failed",
                "runId": "wf-run-default-kubesynth-factory-pipeline-7-old",
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
            name="kubesynth-factory-pipeline",
            namespace="default",
        )

        self.assertIsNotNone(plan)
        assert plan is not None
        self.assertEqual(plan["runId"], "wf-run-default-kubesynth-factory-pipeline-7-new")
        self.assertEqual(plan["failedSteps"], ["draft-blueprint"])
        self.assertEqual(plan["stepStates"]["draft-blueprint"]["status"], "pending")
        self.assertEqual(plan["stepStates"]["review"]["status"], "completed")
        self.assertEqual(plan["summary"]["autoRetryCount"], 1)
        self.assertEqual(plan["summary"]["runId"], "wf-run-default-kubesynth-factory-pipeline-7-new")

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
            name="kubesynth-factory-pipeline",
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
            name="kubesynth-factory-pipeline",
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
            name="kubesynth-factory-pipeline",
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
                    "runId": "wf-run-default-kubesynth-factory-pipeline-7-old",
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
                name="kubesynth-factory-pipeline",
                namespace="default",
                logger=logging.getLogger("test"),
            )

        enqueue_mock.assert_called_once()
        enqueue_kwargs = enqueue_mock.call_args.kwargs
        self.assertEqual(enqueue_kwargs["run_id"], "wf-run-default-kubesynth-factory-pipeline-7-new")
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
                    "runId": "wf-run-default-kubesynth-factory-pipeline-9-old",
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
                name="kubesynth-factory-pipeline",
                namespace="default",
                logger=logging.getLogger("test"),
            )

        enqueue_mock.assert_called_once()
        enqueue_kwargs = enqueue_mock.call_args.kwargs
        self.assertEqual(enqueue_kwargs["run_id"], "wf-run-default-kubesynth-factory-pipeline-9-new")
