import importlib.util
import os
import sys
import sysconfig
import tempfile
import types
import unittest
import uuid
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import Mock, patch

MODULE_PATH = Path(__file__).resolve().parents[1] / "state_store.py"


def _ensure_stdlib_operator_module() -> None:
    current = sys.modules.get("operator")
    if current is not None and hasattr(current, "attrgetter"):
        return

    stdlib_operator_path = Path(sysconfig.get_paths()["stdlib"]) / "operator.py"
    spec = importlib.util.spec_from_file_location("python_stdlib_operator_state_store_tests", stdlib_operator_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Failed to load stdlib operator module for state_store tests")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    sys.modules["operator"] = module


def load_state_store(database_path: Path) -> tuple[str, object]:
    module_name = f"operator_state_store_test_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(module_name, MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Failed to load state_store module for tests")

    module = importlib.util.module_from_spec(spec)
    with patch.dict(
        os.environ,
        {
            "DATABASE_URL": "",
            "DATABASE_HOST": "",
            "DATABASE_SQLITE_PATH": str(database_path),
            "STATE_DB_ENABLED": "true",
        },
        clear=False,
    ):
        sys.modules[module_name] = module
        try:
            spec.loader.exec_module(module)
        except Exception:
            sys.modules.pop(module_name, None)
            raise

    return module_name, module


def load_state_store_with_env(env: dict[str, str], *, create_engine_mock: Mock | None = None) -> tuple[str, object]:
    module_name = f"operator_state_store_env_test_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(module_name, MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Failed to load state_store module for tests")

    module = importlib.util.module_from_spec(spec)
    _ensure_stdlib_operator_module()
    create_engine_patch = patch("sqlalchemy.create_engine", create_engine_mock) if create_engine_mock is not None else nullcontext()
    with patch.dict(os.environ, env, clear=False), create_engine_patch:
        sys.modules[module_name] = module
        try:
            spec.loader.exec_module(module)
        except Exception:
            sys.modules.pop(module_name, None)
            raise

    return module_name, module


class StateStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)

        database_path = Path(self.temp_dir.name) / "state-store.db"
        self.module_name, self.state_store = load_state_store(database_path)
        self.addCleanup(self.state_store.ENGINE.dispose)
        self.addCleanup(lambda: sys.modules.pop(self.module_name, None))

        self.state_store.init_database()

    def test_safe_record_workflow_state_upserts_single_run(self) -> None:
        self.state_store.safe_record_workflow_state(
            namespace="team-a",
            resource_name="workflow-one",
            generation=3,
            run_id="workflow-one-3",
            phase="waiting-approval",
            spec={"steps": [{"name": "review"}]},
            status={
                "summary": {"phase": "waiting-approval"},
                "stepResults": {"review": {"status": "pending"}},
                "stepStates": {"review": "pending"},
                "artifactRef": {"path": "/tmp/workflow.json", "journalPath": "/tmp/workflow.log"},  # noqa: S108
                "workerJob": {"name": "workflow-worker"},
                "pendingApproval": {"name": "approval-one"},
            },
        )

        self.state_store.safe_record_workflow_state(
            namespace="team-a",
            resource_name="workflow-one",
            generation=3,
            run_id="workflow-one-3",
            phase="completed",
            spec={"steps": [{"name": "review"}]},
            status={
                "summary": {"phase": "completed", "completedAt": "2026-03-12T00:00:00Z"},
                "stepResults": {"review": {"status": "completed"}},
                "stepStates": {"review": "completed"},
                "artifactRef": {"path": "/tmp/workflow.json", "journalPath": "/tmp/workflow.log"},  # noqa: S108
                "workerJob": {"name": "workflow-worker"},
            },
        )

        with self.state_store.db_session() as session:
            records = session.query(self.state_store.WorkflowRun).all()

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].phase, "completed")
        self.assertEqual(records[0].artifact_path, "/tmp/workflow.json")  # noqa: S108
        self.assertEqual(records[0].journal_path, "/tmp/workflow.log")  # noqa: S108
        self.assertEqual(records[0].worker_job_name, "workflow-worker")
        self.assertIsNotNone(records[0].completed_at)

    def test_safe_record_workflow_state_supersedes_previous_active_run_same_generation(self) -> None:
        self.state_store.safe_record_workflow_state(
            namespace="team-a",
            resource_name="workflow-one",
            generation=5,
            run_id="workflow-one-5-old",
            phase="queued",
            spec={"steps": [{"name": "draft"}]},
            status={"summary": {"phase": "queued"}},
        )

        self.state_store.safe_record_workflow_state(
            namespace="team-a",
            resource_name="workflow-one",
            generation=5,
            run_id="workflow-one-5-new",
            phase="queued",
            spec={"steps": [{"name": "draft"}]},
            status={"summary": {"phase": "queued"}},
        )

        with self.state_store.db_session() as session:
            records = (
                session.query(self.state_store.WorkflowRun)
                .filter(self.state_store.WorkflowRun.namespace == "team-a")
                .order_by(self.state_store.WorkflowRun.run_id)
                .all()
            )

        self.assertEqual(len(records), 2)
        self.assertEqual(records[0].run_id, "workflow-one-5-new")
        self.assertEqual(records[0].phase, "queued")
        self.assertEqual(records[1].run_id, "workflow-one-5-old")
        self.assertEqual(records[1].phase, "cancelled")
        self.assertIsNotNone(records[1].completed_at)

    def test_record_workflow_log_archive_updates_existing_run(self) -> None:
        self.state_store.safe_record_workflow_state(
            namespace="team-a",
            resource_name="workflow-one",
            generation=5,
            run_id="workflow-one-5-new",
            phase="completed",
            spec={"steps": [{"name": "draft"}]},
            status={
                "summary": {"phase": "completed", "completedAt": "2026-03-12T00:00:00Z"},
                "workerJob": {"name": "workflow-worker"},
            },
        )

        self.state_store.record_workflow_log_archive(
            namespace="team-a",
            resource_name="workflow-one",
            run_id="workflow-one-5-new",
            log_text="2026-03-12T00:00:00Z INFO completed",
            source="worker-pod",
            truncated=False,
        )

        with self.state_store.db_session() as session:
            record = (
                session.query(self.state_store.WorkflowRun)
                .filter(self.state_store.WorkflowRun.run_id == "workflow-one-5-new")
                .one()
            )

        self.assertEqual(record.log_archive_text, "2026-03-12T00:00:00Z INFO completed")
        self.assertEqual(record.log_archive_source, "worker-pod")
        self.assertFalse(record.log_archive_truncated)
        self.assertIsNotNone(record.log_archive_captured_at)

    def test_check_workflow_run_conflict_ignores_superseded_active_run(self) -> None:
        self.state_store.safe_record_workflow_state(
            namespace="team-a",
            resource_name="workflow-one",
            generation=5,
            run_id="workflow-one-5-old",
            phase="queued",
            spec={"steps": [{"name": "draft"}]},
            status={"summary": {"phase": "queued"}},
        )

        self.state_store.safe_record_workflow_state(
            namespace="team-a",
            resource_name="workflow-one",
            generation=5,
            run_id="workflow-one-5-new",
            phase="queued",
            spec={"steps": [{"name": "draft"}]},
            status={"summary": {"phase": "queued"}},
        )

        conflict = self.state_store.check_workflow_run_conflict(
            "team-a",
            "workflow-one",
            5,
            "workflow-one-5-new",
        )

        self.assertIsNone(conflict)

    def test_check_workflow_run_conflict_scopes_by_resource_uid_without_json_query(self) -> None:
        self.state_store.safe_record_workflow_state(
            namespace="team-a",
            resource_name="workflow-one",
            generation=5,
            run_id="workflow-one-5-old",
            phase="queued",
            spec={"steps": [{"name": "draft"}]},
            status={"summary": {"phase": "queued", "resourceUid": "uid-old"}},
        )

        self.state_store.safe_record_workflow_state(
            namespace="team-a",
            resource_name="workflow-one",
            generation=5,
            run_id="workflow-one-5-current",
            phase="queued",
            spec={"steps": [{"name": "draft"}]},
            status={"summary": {"phase": "queued", "resourceUid": "uid-current"}},
        )

        conflict = self.state_store.check_workflow_run_conflict(
            "team-a",
            "workflow-one",
            5,
            "workflow-one-5-next",
            resource_uid="uid-current",
        )

        self.assertEqual(conflict, "workflow-one-5-current")

    def test_init_database_stamps_existing_tables_into_operator_version_table(self) -> None:
        inspector = unittest.mock.Mock()
        inspector.has_table.side_effect = lambda table_name: table_name == "workflow_runs"
        alembic_command = types.SimpleNamespace(
            upgrade=unittest.mock.Mock(),
            stamp=unittest.mock.Mock(),
        )
        alembic_config = unittest.mock.Mock()
        alembic_module = types.SimpleNamespace(
            command=alembic_command,
            config=types.SimpleNamespace(Config=alembic_config),
        )

        with (
            patch.object(self.state_store, "inspect", return_value=inspector),
            patch.object(self.state_store.Base.metadata, "create_all") as create_all,
            patch.dict(sys.modules, {"alembic": alembic_module, "alembic.command": alembic_command, "alembic.config": alembic_module.config}),
        ):
            self.state_store.init_database()

        create_all.assert_called_once_with(bind=self.state_store.ENGINE)
        alembic_command.stamp.assert_called_once()
        alembic_command.upgrade.assert_not_called()


class DatabaseDriverValidationTests(unittest.TestCase):
    """state_store rejects unsupported DATABASE_DRIVER values."""

    def test_rejects_invalid_driver(self) -> None:
        module_name = f"operator_state_store_driver_test_{uuid.uuid4().hex}"
        spec = importlib.util.spec_from_file_location(module_name, MODULE_PATH)
        if spec is None or spec.loader is None:
            self.skipTest("Could not load state_store module")
        module = importlib.util.module_from_spec(spec)
        with patch.dict(
            os.environ,
            {
                "DATABASE_URL": "",
                "DATABASE_HOST": "localhost",
                "DATABASE_DRIVER": "sqlite3; DROP TABLE x; --",
                "STATE_DB_ENABLED": "false",
            },
            clear=False,
        ), self.assertRaises(ValueError):
            spec.loader.exec_module(module)

    def test_postgres_engine_uses_psycopg_compatible_connect_args(self) -> None:
        create_engine_mock = Mock(return_value=types.SimpleNamespace(dispose=lambda: None))
        module_name, state_store = load_state_store_with_env(
            {
                "DATABASE_URL": "",
                "DATABASE_HOST": "postgres.test",
                "DATABASE_PORT": "5432",
                "DATABASE_USER": "kubesynapse",
                "DATABASE_PASSWORD": "secret",
                "DATABASE_NAME": "kubesynapse",
                "DATABASE_DRIVER": "postgresql+psycopg",
                "STATE_DB_ENABLED": "false",
            },
            create_engine_mock=create_engine_mock,
        )
        self.addCleanup(lambda: sys.modules.pop(module_name, None))
        self.addCleanup(state_store.ENGINE.dispose)

        create_engine_mock.assert_called_once()
        _, kwargs = create_engine_mock.call_args
        self.assertEqual(kwargs["connect_args"], {"connect_timeout": 10})
