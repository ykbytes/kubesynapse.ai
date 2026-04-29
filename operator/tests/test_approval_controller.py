import importlib.util
import logging
import sys
import types
import unittest
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

MODULE_PATH = Path(__file__).resolve().parents[1] / "controllers" / "approval_controller.py"
STUB_MODULE_NAMES = [
    "kopf",
    "kubernetes",
    "kubernetes.client",
    "kubernetes.client.rest",
    "builders",
    "config",
    "controllers",
    "controllers.workflow_controller",
    "reconcile",
    "services",
    "utils",
]


def _install_stub_modules() -> dict[str, object | None]:
    kopf_module = types.ModuleType("kopf")

    class _KopfOn:
        @staticmethod
        def field(*_args, **_kwargs):
            def decorator(func):
                return func

            return decorator

    kopf_module.on = _KopfOn()

    kubernetes_module = types.ModuleType("kubernetes")
    kubernetes_client_module = types.ModuleType("kubernetes.client")
    kubernetes_rest_module = types.ModuleType("kubernetes.client.rest")
    kubernetes_rest_module.ApiException = type("ApiException", (Exception,), {})
    kubernetes_client_module.CustomObjectsApi = lambda: None
    kubernetes_client_module.rest = kubernetes_rest_module
    kubernetes_module.client = kubernetes_client_module

    builders_module = types.ModuleType("builders")
    builders_module.artifact_file_path = lambda *_args, **_kwargs: "/tmp/workflow.json"  # noqa: S108
    builders_module.build_artifact_ref = lambda *args, **kwargs: {"args": args, "kwargs": kwargs}
    builders_module.build_journal_ref = lambda *args, **kwargs: {"args": args, "kwargs": kwargs}

    config_module = types.ModuleType("config")
    config_module.OPERATOR_NAMESPACE = "ai-agent-sandbox"

    controllers_module = types.ModuleType("controllers")
    workflow_controller_module = types.ModuleType("controllers.workflow_controller")
    workflow_controller_module.enqueue_workflow_job = lambda *_args, **_kwargs: "job-from-stub"
    controllers_module.workflow_controller = workflow_controller_module

    reconcile_module = types.ModuleType("reconcile")
    reconcile_module.execute_reconcile = lambda fn, **_kwargs: fn()
    reconcile_module.inject_conditions = lambda payload: payload
    reconcile_module.log_operator_event = lambda *_args, **_kwargs: None

    services_module = types.ModuleType("services")
    services_module.cancel_worker_job = lambda *_args, **_kwargs: True
    services_module.ensure_worker_artifact_storage = lambda *_args, **_kwargs: "artifact-pvc"
    services_module.patch_custom_status = lambda *_args, **_kwargs: None

    utils_module = types.ModuleType("utils")
    utils_module.now_iso = lambda: "2026-04-06T00:00:00+00:00"
    utils_module.workflow_journal_path = lambda path: f"{path}.journal"

    previous_modules: dict[str, object | None] = {}
    for name, module in [
        ("kopf", kopf_module),
        ("kubernetes", kubernetes_module),
        ("kubernetes.client", kubernetes_client_module),
        ("kubernetes.client.rest", kubernetes_rest_module),
        ("builders", builders_module),
        ("config", config_module),
        ("controllers", controllers_module),
        ("controllers.workflow_controller", workflow_controller_module),
        ("reconcile", reconcile_module),
        ("services", services_module),
        ("utils", utils_module),
    ]:
        previous_modules[name] = sys.modules.get(name)
        sys.modules[name] = module

    return previous_modules


def load_approval_controller() -> tuple[str, object, dict[str, object | None]]:
    previous_modules = _install_stub_modules()
    module_name = f"operator_approval_controller_test_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(module_name, MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Failed to load approval_controller module for tests")

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(module_name, None)
        raise
    return module_name, module, previous_modules


class _FakeCustomObjectsApi:
    def __init__(self, workflows: list[dict]):
        self.workflows = workflows
        self.calls: list[dict] = []

    def list_namespaced_custom_object(self, **kwargs):
        self.calls.append(kwargs)
        return {"items": self.workflows}


class ApprovalControllerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.module_name, self.controller, self.previous_modules = load_approval_controller()
        self.addCleanup(lambda: sys.modules.pop(self.module_name, None))
        self.addCleanup(self._cleanup_stub_modules)

    def _cleanup_stub_modules(self) -> None:
        for module_name in reversed(STUB_MODULE_NAMES):
            previous_module = self.previous_modules.get(module_name)
            if previous_module is None:
                sys.modules.pop(module_name, None)
            else:
                sys.modules[module_name] = previous_module

    def test_none_to_approved_resumes_waiting_workflow(self) -> None:
        workflow = {
            "metadata": {"name": "workflow-one", "generation": 3},
            "spec": {"steps": [{"name": "deploy"}]},
            "status": {
                "phase": "waiting-approval",
                "pendingApproval": {"name": "approval-one"},
                "observedGeneration": 3,
                "runId": "run-123",
            },
        }
        fake_api = _FakeCustomObjectsApi([workflow])

        enqueue_mock = MagicMock(return_value="job-123")
        execute_mock = MagicMock(side_effect=lambda fn, **_kwargs: fn())
        log_mock = MagicMock()

        with patch.object(self.controller.kubernetes.client, "CustomObjectsApi", return_value=fake_api), \
             patch.object(self.controller, "enqueue_workflow_job", enqueue_mock), \
             patch.object(self.controller, "execute_reconcile", execute_mock), \
             patch.object(self.controller, "log_operator_event", log_mock):
            self.controller.on_approval_decision(
                old=None,
                new="approved",
                name="approval-one",
                namespace="default",
                logger=logging.getLogger("test"),
            )

        enqueue_mock.assert_called_once()
        execute_mock.assert_called_once()
        self.assertTrue(any(call.get("label_selector") == "kubesynapse.ai/pending-approval=approval-one" for call in fake_api.calls))

    def test_terminal_decision_does_not_reprocess(self) -> None:
        fake_api = _FakeCustomObjectsApi([])
        enqueue_mock = MagicMock(return_value="job-123")
        execute_mock = MagicMock(side_effect=lambda fn, **_kwargs: fn())

        with patch.object(self.controller.kubernetes.client, "CustomObjectsApi", return_value=fake_api), \
             patch.object(self.controller, "enqueue_workflow_job", enqueue_mock), \
             patch.object(self.controller, "execute_reconcile", execute_mock):
            self.controller.on_approval_decision(
                old="approved",
                new="approved",
                name="approval-one",
                namespace="default",
                logger=logging.getLogger("test"),
            )

        enqueue_mock.assert_not_called()
        execute_mock.assert_not_called()

    def test_none_to_denied_marks_waiting_workflow_failed(self) -> None:
        workflow = {
            "metadata": {"name": "workflow-one", "generation": 7},
            "spec": {"steps": [{"name": "draft"}, {"name": "deploy"}]},
            "status": {
                "phase": "waiting-approval",
                "pendingApproval": {"name": "approval-one", "stepName": "deploy"},
                "observedGeneration": 7,
                "runId": "run-456",
                "currentStep": "deploy",
                "stepStates": {
                    "draft": {"status": "completed"},
                    "deploy": {"status": "waiting-approval"},
                },
                "summary": {"totalSteps": 2, "completedSteps": 1},
                "artifactRef": {"path": "/artifacts/workflow.json", "journalPath": "/artifacts/workflow.json.journal"},
            },
        }
        fake_api = _FakeCustomObjectsApi([workflow])

        execute_mock = MagicMock(side_effect=lambda fn, **_kwargs: fn())
        patch_status_mock = MagicMock()
        ensure_storage_mock = MagicMock(return_value="artifact-pvc")
        build_artifact_ref_mock = MagicMock(return_value={"pvcName": "artifact-pvc", "path": "/artifacts/workflow.json"})
        build_journal_ref_mock = MagicMock(return_value={"pvcName": "artifact-pvc", "path": "/artifacts/workflow.json.journal"})

        with patch.object(self.controller.kubernetes.client, "CustomObjectsApi", return_value=fake_api), \
             patch.object(self.controller, "execute_reconcile", execute_mock), \
             patch.object(self.controller, "patch_custom_status", patch_status_mock), \
             patch.object(self.controller, "ensure_worker_artifact_storage", ensure_storage_mock), \
             patch.object(self.controller, "build_artifact_ref", build_artifact_ref_mock), \
             patch.object(self.controller, "build_journal_ref", build_journal_ref_mock):
            self.controller.on_approval_decision(
                old=None,
                new="denied",
                name="approval-one",
                namespace="default",
                logger=logging.getLogger("test"),
            )

        execute_mock.assert_called_once()
        patch_status_mock.assert_called_once()
        patch_args = patch_status_mock.call_args.args
        self.assertEqual(patch_args[:3], ("agentworkflows", "default", "workflow-one"))
        patched_status = patch_args[3]
        self.assertEqual(patched_status["phase"], "failed")
        self.assertEqual(patched_status["pendingApproval"], {"name": "approval-one", "namespace": "default", "decision": "denied"})
        self.assertEqual(patched_status["stepStates"]["deploy"]["status"], "denied")
        self.assertEqual(patched_status["stepStates"]["deploy"]["failureClass"], "approval_denied")
        self.assertIn("Approval 'approval-one' was denied", patched_status["summary"]["error"])
