import importlib.util
import sys
import types
import unittest
import uuid
from pathlib import Path
from unittest.mock import MagicMock

MODULE_PATH = Path(__file__).resolve().parents[1] / "controllers" / "status_projection.py"
STUB_MODULE_NAMES = ["kopf", "services", "state_store"]


def _identity_decorator(*_args, **_kwargs):
    def decorator(func):
        return func

    return decorator


def _install_stub_modules() -> tuple[object, dict[str, object]]:
    kopf_module = types.ModuleType("kopf")

    class _KopfOn:
        field = staticmethod(_identity_decorator)

    kopf_module.on = _KopfOn()

    services_module = types.ModuleType("services")
    services_module.crd_exists = lambda *_args, **_kwargs: True

    state_store_module = types.ModuleType("state_store")
    state_store_module.safe_record_workflow_state = MagicMock()
    state_store_module.record_workflow_log_archive = MagicMock()

    # Save originals before overwriting
    originals = {}
    for name, module in [
        ("kopf", kopf_module),
        ("services", services_module),
        ("state_store", state_store_module),
    ]:
        originals[name] = sys.modules.get(name)
        sys.modules[name] = module

    return state_store_module.safe_record_workflow_state, originals


def load_status_projection() -> tuple[str, object, object, dict[str, object]]:
    workflow_mock, originals = _install_stub_modules()
    module_name = f"operator_status_projection_test_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(module_name, MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Failed to load status_projection module for tests")

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(module_name, None)
        raise
    return module_name, module, workflow_mock, originals


class StatusProjectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.module_name, self.module, self.workflow_record_mock, self._originals = load_status_projection()
        self.addCleanup(lambda: sys.modules.pop(self.module_name, None))
        self.addCleanup(self._cleanup_stub_modules)

    def _cleanup_stub_modules(self) -> None:
        # Restore original modules
        for name, original in self._originals.items():
            if original is not None:
                sys.modules[name] = original
            else:
                sys.modules.pop(name, None)

    def test_projects_workflow_state_on_run_id_change(self) -> None:
        self.module.project_workflow_run_id(
            old="wf-run-old",
            new="wf-run-new",
            name="workflow-one",
            namespace="default",
            spec={"input": "hello"},
            status={"phase": "queued", "runId": "wf-run-new"},
            meta={"generation": 9},
        )

        self.workflow_record_mock.assert_called_once_with(
            namespace="default",
            resource_name="workflow-one",
            generation=9,
            run_id="wf-run-new",
            phase="queued",
            spec={"input": "hello"},
            status={"phase": "queued", "runId": "wf-run-new"},
        )

    def test_projects_workflow_state_on_terminal_phase_and_attempts_log_archive(self) -> None:
        with unittest.mock.patch.object(self.module, "_archive_terminal_workflow_logs") as archive_mock:
            self.module.project_workflow_status(
                old="running",
                new="completed",
                name="workflow-one",
                namespace="default",
                spec={"input": "hello"},
                status={
                    "phase": "completed",
                    "runId": "wf-run-new",
                    "workerJob": {"name": "worker-job", "namespace": "operators"},
                },
                meta={"generation": 9},
            )

        archive_mock.assert_called_once_with(
            name="workflow-one",
            namespace="default",
            status={
                "phase": "completed",
                "runId": "wf-run-new",
                "workerJob": {"name": "worker-job", "namespace": "operators"},
            },
        )
