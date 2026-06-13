import importlib.util
import os
import sys
import tempfile
import types
import unittest
import uuid
from contextlib import contextmanager, nullcontext
from pathlib import Path
from unittest.mock import Mock, patch

from sqlalchemy import inspect

MODULE_PATH = Path(__file__).resolve().parents[1] / "auth_store.py"


def _passlib_overrides() -> dict[str, object]:
    try:
        import passlib.context  # type: ignore[import-not-found]  # noqa: F401
    except ModuleNotFoundError:
        passlib_module = types.ModuleType("passlib")
        context_module = types.ModuleType("passlib.context")

        class _FakeCryptContext:
            def __init__(self, *args, **kwargs) -> None:
                pass

            def hash(self, value: str) -> str:
                return f"hash::{value}"

            def verify(self, plain: str, hashed: str) -> bool:
                return hashed == f"hash::{plain}"

        context_module.CryptContext = _FakeCryptContext
        passlib_module.context = context_module
        return {"passlib": passlib_module, "passlib.context": context_module}
    return {}


def load_auth_store(database_path: Path) -> tuple[str, object]:
    module_name = f"api_gateway_auth_store_test_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(module_name, MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Failed to load auth_store module for tests")

    module = importlib.util.module_from_spec(spec)
    with patch.dict(
        os.environ,
        {
            "DATABASE_URL": "",
            "DATABASE_HOST": "",
            "DATABASE_SQLITE_PATH": str(database_path),
        },
        clear=False,
    ), patch.dict(sys.modules, _passlib_overrides()):
        sys.modules[module_name] = module
        try:
            spec.loader.exec_module(module)
        except Exception:
            sys.modules.pop(module_name, None)
            raise

    return module_name, module


def load_auth_store_with_env(env: dict[str, str], *, create_engine_mock: Mock | None = None) -> tuple[str, object]:
    module_name = f"api_gateway_auth_store_env_test_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(module_name, MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Failed to load auth_store module for tests")

    module = importlib.util.module_from_spec(spec)
    create_engine_patch = patch("sqlalchemy.create_engine", create_engine_mock) if create_engine_mock is not None else nullcontext()
    with patch.dict(os.environ, env, clear=False), patch.dict(sys.modules, _passlib_overrides()), create_engine_patch:
        sys.modules[module_name] = module
        try:
            spec.loader.exec_module(module)
        except Exception:
            sys.modules.pop(module_name, None)
            raise

    return module_name, module


class AuthStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)

        database_path = Path(self.temp_dir.name) / "auth-store.db"
        self.module_name, self.auth_store = load_auth_store(database_path)
        self.addCleanup(self.auth_store.ENGINE.dispose)
        self.addCleanup(lambda: sys.modules.pop(self.module_name, None))

        self.auth_store.init_database()

    def test_create_local_user_and_rotate_refresh_session(self) -> None:
        user = self.auth_store.create_local_user(
            username="Alice",
            password="CorrectH0rse!",
            email="alice@example.com",
            display_name="Alice Operator",
            role="operator",
            allowed_namespaces=["team-b", "team-a", "team-b"],
        )

        self.assertEqual(user["username"], "alice")
        self.assertEqual(user["allowed_namespaces"], ["team-a", "team-b"])

        session_record, refresh_token = self.auth_store.create_session_for_user(
            int(user["id"]),
            auth_provider="local",
            ip_address="127.0.0.1",
            user_agent="pytest",
            ttl_seconds=600,
        )

        verified_user, verified_session = self.auth_store.verify_refresh_session(refresh_token)
        self.assertEqual(verified_user["id"], user["id"])
        self.assertEqual(verified_session["id"], session_record["id"])

        rotated_user, rotated_session, rotated_refresh_token = self.auth_store.rotate_refresh_session(
            refresh_token,
            ip_address="127.0.0.2",
            user_agent="pytest-rotate",
            ttl_seconds=900,
        )

        self.assertEqual(rotated_user["id"], user["id"])
        self.assertNotEqual(rotated_session["id"], session_record["id"])
        self.assertNotEqual(rotated_refresh_token, refresh_token)
        self.assertTrue(self.auth_store.is_session_active(rotated_session["id"], user_id=int(user["id"])))

        with self.assertRaises(ValueError):
            self.auth_store.verify_refresh_session(refresh_token)

    def test_browser_auth_storage_requires_user_sessions_table(self) -> None:
        user = self.auth_store.create_local_user(
            username="Carol",
            password="CorrectH0rse!",
            email="carol@example.com",
            display_name="Carol Operator",
            role="operator",
            allowed_namespaces=["default"],
        )

        session_record, refresh_token = self.auth_store.create_session_for_user(
            int(user["id"]),
            auth_provider="local",
            ip_address="127.0.0.1",
            user_agent="pytest",
            ttl_seconds=600,
        )

        with self.auth_store.ENGINE.begin() as connection:
            connection.exec_driver_sql("DROP TABLE user_sessions")

        self.assertTrue(self.auth_store.auth_storage_ready())
        self.assertFalse(self.auth_store.auth_storage_ready(require_sessions=True))
        self.assertFalse(self.auth_store.is_session_active(session_record["id"], user_id=int(user["id"])))

        with self.assertRaises(ValueError):
            self.auth_store.verify_refresh_session(refresh_token)

        self.auth_store.revoke_session(session_record["id"])

    def test_change_user_password_updates_stored_hash(self) -> None:
        user = self.auth_store.create_local_user(
            username="Bob",
            password="OldPassw0rd",
            email="bob@example.com",
            display_name="Bob Viewer",
            role="viewer",
            allowed_namespaces=["default"],
        )

        with self.assertRaises(ValueError):
            self.auth_store.change_user_password(int(user["id"]), "WrongPw1", "NewPassw0rd")

        updated_user = self.auth_store.change_user_password(
            int(user["id"]),
            "OldPassw0rd",
            "NewPassw0rd",
        )
        stored_user = self.auth_store.get_user_by_id(int(user["id"]))

        self.assertEqual(updated_user["id"], user["id"])
        self.assertIsNotNone(stored_user)
        self.assertTrue(self.auth_store.verify_password("NewPassw0rd", stored_user.password_hash))
        self.assertFalse(self.auth_store.verify_password("OldPassw0rd", stored_user.password_hash))

    def test_admin_users_are_serialized_with_wildcard_namespace_access(self) -> None:
        user = self.auth_store.create_local_user(
            username="Admin",
            password="Str0ngP4ssword!",
            email="admin@example.com",
            display_name="Admin User",
            role="admin",
            allowed_namespaces=["team-a"],
        )

        self.assertEqual(user["allowed_namespaces"], ["*"])

        updated = self.auth_store.update_user_fields(
            int(user["id"]),
            role="operator",
            allowed_namespaces=["team-b", "*"],
        )

        self.assertEqual(updated["allowed_namespaces"], ["team-b"])

        promoted = self.auth_store.update_user_fields(
            int(user["id"]),
            role="admin",
            allowed_namespaces=["team-c"],
        )

        self.assertEqual(promoted["allowed_namespaces"], ["*"])

    def test_init_database_adds_namespace_columns_to_legacy_intelligence_tables(self) -> None:
        database_path = Path(self.temp_dir.name) / "legacy-auth-store.db"
        module_name, auth_store = load_auth_store(database_path)
        self.addCleanup(auth_store.ENGINE.dispose)
        self.addCleanup(lambda: sys.modules.pop(module_name, None))

        with auth_store.ENGINE.begin() as connection:
            connection.exec_driver_sql(
                """
                CREATE TABLE intelligence_collectors (
                    id VARCHAR(128) PRIMARY KEY,
                    name VARCHAR(256) NOT NULL,
                    url VARCHAR(1024) NOT NULL,
                    token_hash VARCHAR(128) NOT NULL,
                    cluster VARCHAR(256) NOT NULL DEFAULT 'unknown',
                    tags JSON NOT NULL,
                    registered_at DATETIME NOT NULL,
                    registered_by VARCHAR(256) NOT NULL DEFAULT 'unknown'
                )
                """
            )
            connection.exec_driver_sql(
                """
                CREATE TABLE intelligence_tasks (
                    task_id VARCHAR(16) PRIMARY KEY,
                    collector_id VARCHAR(128) NOT NULL DEFAULT 'all',
                    payload JSON NOT NULL,
                    results JSON NOT NULL,
                    submitted_by VARCHAR(256) NOT NULL DEFAULT 'unknown',
                    submitted_at DATETIME NOT NULL,
                    total INTEGER NOT NULL DEFAULT 0,
                    completed INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            connection.exec_driver_sql(
                """
                INSERT INTO intelligence_tasks (
                    task_id, collector_id, payload, results, submitted_by, submitted_at, total, completed
                ) VALUES (
                    'task-1', 'collector-1', '{}', '{}', 'tester', '2026-04-06T00:00:00+00:00', 1, 1
                )
                """
            )
            connection.exec_driver_sql(
                """
                CREATE TABLE intelligence_schedules (
                    id VARCHAR(16) PRIMARY KEY,
                    name VARCHAR(256) NOT NULL,
                    cron VARCHAR(128) NOT NULL,
                    collector_id VARCHAR(128) NOT NULL DEFAULT 'all',
                    builtin VARCHAR(128),
                    script VARCHAR,
                    script_type VARCHAR(16) NOT NULL DEFAULT 'bash',
                    timeout INTEGER NOT NULL DEFAULT 30,
                    agent_name VARCHAR(256),
                    enabled BOOLEAN NOT NULL DEFAULT 1,
                    created_by VARCHAR(256) NOT NULL DEFAULT 'unknown',
                    created_at DATETIME NOT NULL,
                    last_run DATETIME,
                    next_run DATETIME
                )
                """
            )
            connection.exec_driver_sql(
                """
                CREATE TABLE intelligence_alerts (
                    id VARCHAR(16) PRIMARY KEY,
                    name VARCHAR(256) NOT NULL,
                    schedule_id VARCHAR(16),
                    condition_type VARCHAR(32) NOT NULL,
                    condition_value VARCHAR(1024) NOT NULL DEFAULT '',
                    action VARCHAR(32) NOT NULL DEFAULT 'notify',
                    agent_name VARCHAR(256),
                    prompt_template VARCHAR,
                    enabled BOOLEAN NOT NULL DEFAULT 1,
                    created_by VARCHAR(256) NOT NULL DEFAULT 'unknown',
                    created_at DATETIME NOT NULL,
                    last_triggered DATETIME,
                    trigger_count INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            connection.exec_driver_sql(
                """
                CREATE TABLE alert_history (
                    id VARCHAR(16) PRIMARY KEY,
                    alert_id VARCHAR(16) NOT NULL,
                    alert_name VARCHAR(256) NOT NULL,
                    triggered_at DATETIME NOT NULL,
                    condition_matched VARCHAR(512) NOT NULL DEFAULT '',
                    action_taken VARCHAR(32) NOT NULL DEFAULT 'notify',
                    agent_invoked VARCHAR(256),
                    invoke_status INTEGER,
                    invoke_error VARCHAR,
                    task_id VARCHAR(16),
                    snippet VARCHAR(1024)
                )
                """
            )

        auth_store.init_database()

        inspector = inspect(auth_store.ENGINE)
        for table_name in (
            "intelligence_collectors",
            "intelligence_tasks",
            "intelligence_schedules",
            "intelligence_alerts",
            "alert_history",
        ):
            columns = {column["name"] for column in inspector.get_columns(table_name)}
            self.assertIn("namespace", columns)

        collector_columns = {column["name"] for column in inspector.get_columns("intelligence_collectors")}
        self.assertIn("encrypted_token", collector_columns)

        with auth_store.ENGINE.begin() as connection:
            namespace = connection.exec_driver_sql(
                "SELECT namespace FROM intelligence_tasks WHERE task_id = 'task-1'"
            ).scalar_one()
        self.assertEqual(namespace, "default")

    def test_workflow_archive_migration_uses_dialect_specific_datetime_ddl(self) -> None:
        from sqlalchemy.dialects import postgresql

        executed_sql: list[str] = []

        class FakeConnection:
            def __init__(self) -> None:
                self.dialect = postgresql.dialect()

            def execute(self, statement: object) -> None:
                executed_sql.append(str(statement))

        class FakeInspector:
            def get_table_names(self) -> list[str]:
                return ["workflow_runs"]

            def get_columns(self, table_name: str) -> list[dict[str, str]]:
                return []

        class FakeEngine:
            @contextmanager
            def begin(self) -> object:
                yield FakeConnection()

        with patch.object(self.auth_store, "ENGINE", FakeEngine()), patch.object(
            self.auth_store,
            "inspect",
            new=lambda _connection: FakeInspector(),
        ):
            self.auth_store._ensure_workflow_run_archive_columns()

        archive_timestamp_sql = next(sql for sql in executed_sql if "log_archive_captured_at" in sql)
        self.assertIn("TIMESTAMP WITH TIME ZONE", archive_timestamp_sql)
        self.assertNotIn("DATETIME", archive_timestamp_sql)

    # -- Password policy tests ------------------------------------------------

    def test_password_meets_policy_accepts_strong_password(self) -> None:
        self.assertTrue(self.auth_store.password_meets_policy("Passw0rd"))

    def test_password_meets_policy_rejects_too_short(self) -> None:
        self.assertFalse(self.auth_store.password_meets_policy("Ab1"))

    def test_password_meets_policy_rejects_no_uppercase(self) -> None:
        self.assertFalse(self.auth_store.password_meets_policy("password1"))

    def test_password_meets_policy_rejects_no_lowercase(self) -> None:
        self.assertFalse(self.auth_store.password_meets_policy("PASSWORD1"))

    def test_password_meets_policy_rejects_no_digit(self) -> None:
        self.assertFalse(self.auth_store.password_meets_policy("Password"))

    def test_create_user_rejects_weak_password(self) -> None:
        with self.assertRaises(ValueError):
            self.auth_store.create_local_user(
                username="weakpw",
                password="short",
                email="weak@example.com",
                display_name="Weak",
                role="viewer",
                allowed_namespaces=["default"],
            )

    # -- Email validation tests -----------------------------------------------

    def test_validate_email_accepts_valid(self) -> None:
        self.assertEqual(self.auth_store.validate_email("user@example.com"), "user@example.com")

    def test_validate_email_strips_whitespace(self) -> None:
        self.assertEqual(self.auth_store.validate_email("  user@example.com  "), "user@example.com")

    def test_validate_email_returns_none_for_none(self) -> None:
        self.assertIsNone(self.auth_store.validate_email(None))

    def test_validate_email_returns_none_for_empty(self) -> None:
        self.assertIsNone(self.auth_store.validate_email("  "))

    def test_validate_email_rejects_invalid(self) -> None:
        for bad in ["not-an-email", "@nope.com", "user@", "user@.com", "a" * 321 + "@example.com"]:
            with self.assertRaises(ValueError, msg=f"Expected ValueError for '{bad}'"):
                self.auth_store.validate_email(bad)

    def test_create_user_rejects_invalid_email(self) -> None:
        with self.assertRaises(ValueError):
            self.auth_store.create_local_user(
                username="bademail",
                password="Passw0rd1",
                email="not-valid",
                display_name="Bad Email",
                role="viewer",
                allowed_namespaces=["default"],
            )

    # -- Duplicate user tests -------------------------------------------------

    def test_create_user_rejects_duplicate_username(self) -> None:
        self.auth_store.create_local_user(
            username="dupuser",
            password="Passw0rd1",
            email="dup1@example.com",
            display_name="Dup User",
            role="viewer",
            allowed_namespaces=["default"],
        )
        with self.assertRaises(ValueError):
            self.auth_store.create_local_user(
                username="dupuser",
                password="Passw0rd2",
                email="dup2@example.com",
                display_name="Dup User 2",
                role="viewer",
                allowed_namespaces=["default"],
            )

    def test_chat_session_summary_includes_memory_candidates(self) -> None:
        session = self.auth_store.create_chat_session(
            "default", "reviewer", "session-1", "Review run", username="alice"
        )
        self.assertEqual(session["session_id"], "session-1")

        self.auth_store.save_chat_messages(
            "session-1",
            [
                {"message_id": "m1", "role": "user", "content": "Review this patch"},
                {
                    "message_id": "m2",
                    "role": "assistant",
                    "content": "I found one regression risk and a missing test.",
                    "toolName": "github/diff",
                },
            ],
        )

        sessions = self.auth_store.list_chat_sessions("default", "reviewer", username="alice")
        self.assertEqual(len(sessions), 1)
        summary = sessions[0]["summary"]
        self.assertEqual(summary["message_count"], 2)
        self.assertEqual(summary["tool_names"], ["github/diff"])
        self.assertIn("regression risk", summary["last_assistant_message"])
        self.assertEqual(summary["memory_candidates"]["episodic"][0]["type"], "tool-usage")

        memory_records = self.auth_store.list_memory_records(
            "default", "reviewer", username="alice", session_id="session-1"
        )
        self.assertGreaterEqual(len(memory_records), 1)
        self.assertEqual(memory_records[0]["agent_name"], "reviewer")
        self.assertEqual(memory_records[0]["session_id"], "session-1")

    def test_record_runtime_memory_persists_runtime_metadata(self) -> None:
        inserted = self.auth_store.record_runtime_memory(
            "default",
            "reviewer",
            session_id="thread-123",
            username="alice",
            metadata={
                "memory": {
                    "episodic": [{"type": "tools", "names": ["filesystem.read"]}],
                    "procedural": [{"type": "response-summary", "text": "Summarized the repository layout."}],
                }
            },
        )

        self.assertEqual(inserted, 2)
        memory_records = self.auth_store.list_memory_records(
            "default", "reviewer", username="alice", session_id="thread-123"
        )
        self.assertEqual(len(memory_records), 2)

    def test_record_runtime_memory_deduplicates_identical_entries(self) -> None:
        metadata = {
            "memory": {
                "episodic": [{"type": "tools", "names": ["filesystem.read"]}],
                "procedural": [],
            }
        }

        self.auth_store.record_runtime_memory(
            "default", "reviewer", session_id="thread-dup", username="alice", metadata=metadata
        )
        self.auth_store.record_runtime_memory(
            "default", "reviewer", session_id="thread-dup", username="alice", metadata=metadata
        )

        memory_records = self.auth_store.list_memory_records(
            "default", "reviewer", username="alice", session_id="thread-dup"
        )
        self.assertEqual(len(memory_records), 1)

    def test_memory_record_promote_and_delete(self) -> None:
        self.auth_store.record_runtime_memory(
            "default",
            "reviewer",
            session_id="thread-manage",
            username="alice",
            metadata={
                "memory": {
                    "episodic": [],
                    "procedural": [{"type": "response-summary", "text": "Important durable note."}],
                }
            },
        )

        memory_records = self.auth_store.list_memory_records(
            "default", "reviewer", username="alice", session_id="thread-manage"
        )
        self.assertEqual(len(memory_records), 1)
        record_id = memory_records[0]["id"]

        updated = self.auth_store.set_memory_record_promoted(record_id, True, username="alice")
        self.assertIsNotNone(updated)
        self.assertTrue(updated["promoted"])

        deleted = self.auth_store.delete_memory_record(record_id, username="alice")
        self.assertTrue(deleted)
        remaining = self.auth_store.list_memory_records(
            "default", "reviewer", username="alice", session_id="thread-manage"
        )
        self.assertEqual(remaining, [])

    def test_update_memory_record_edits_topic_and_content(self) -> None:
        self.auth_store.record_runtime_memory(
            "default",
            "reviewer",
            session_id="thread-edit",
            username="alice",
            metadata={
                "memory": {
                    "episodic": [],
                    "procedural": [{"type": "response-summary", "text": "Old summary."}],
                }
            },
        )
        record = self.auth_store.list_memory_records("default", "reviewer", username="alice", session_id="thread-edit")[
            0
        ]

        updated = self.auth_store.update_memory_record(
            record["id"],
            topic="repo-convention",
            content="Use make test before pushing.",
            username="alice",
        )

        self.assertIsNotNone(updated)
        self.assertEqual(updated["topic"], "repo-convention")
        self.assertEqual(updated["content"], "Use make test before pushing.")

    def test_list_promoted_memory_records_returns_only_promoted_items(self) -> None:
        self.auth_store.record_runtime_memory(
            "default",
            "reviewer",
            session_id="thread-promoted",
            username="alice",
            metadata={
                "memory": {
                    "episodic": [],
                    "procedural": [{"type": "response-summary", "text": "Keep this context."}],
                }
            },
        )
        records = self.auth_store.list_memory_records(
            "default", "reviewer", username="alice", session_id="thread-promoted"
        )
        self.auth_store.set_memory_record_promoted(records[0]["id"], True, username="alice")

        promoted = self.auth_store.list_promoted_memory_records("default", "reviewer", username="alice")
        self.assertEqual(len(promoted), 1)
        self.assertTrue(promoted[0]["promoted"])

    def test_record_runtime_memory_auto_promotes_high_signal_entries(self) -> None:
        self.auth_store.record_runtime_memory(
            "default",
            "reviewer",
            session_id="thread-auto",
            username="alice",
            metadata={
                "memory": {
                    "episodic": [],
                    "procedural": [
                        {"type": "response-summary", "text": "Use make test before pushing changes to the repo."}
                    ],
                }
            },
            auto_promote=True,
        )

        records = self.auth_store.list_memory_records("default", "reviewer", username="alice", session_id="thread-auto")
        self.assertEqual(len(records), 1)
        self.assertTrue(records[0]["promoted"])
        self.assertGreater(records[0]["score"], 0.0)
        self.assertEqual(records[0]["promote_reason"], "high-signal-memory")

    def test_record_workflow_outcome_memory_and_feedback(self) -> None:
        inserted = self.auth_store.record_workflow_outcome_memory(
            "default",
            "reviewer",
            "repo-check",
            run_id="run-1",
            phase="completed",
            summary={"completedSteps": 3, "totalSteps": 3},
        )
        self.assertGreaterEqual(inserted, 1)

        records = self.auth_store.list_memory_records("default", "reviewer", session_id="run-1")
        self.assertTrue(any(record["topic"] == "workflow-success" for record in records))
        before = max(float(record["score"]) for record in records)

        updated = self.auth_store.apply_memory_feedback("default", "reviewer", session_id="run-1", success=True)
        self.assertGreater(updated, 0)

        after_records = self.auth_store.list_memory_records("default", "reviewer", session_id="run-1")
        after = max(float(record["score"]) for record in after_records)
        self.assertGreaterEqual(after, before)

    def test_workflow_run_trace_helpers_expose_archived_logs(self) -> None:
        with self.auth_store.db_session() as session:
            session.add(
                self.auth_store.WorkflowRun(
                    namespace="default",
                    resource_name="feature-pipeline",
                    run_id="run-123",
                    generation=7,
                    phase="failed",
                    spec_json={
                        "description": "Workflow trace",
                        "input": "Investigate the production regression",
                        "steps": [{"name": "draft-plan", "agentRef": "planner", "prompt": "Draft a recovery plan"}],
                    },
                    status_json={
                        "phase": "failed",
                        "runId": "run-123",
                        "summary": {"totalSteps": 1, "failedSteps": 1},
                        "stepStates": {
                            "draft-plan": {"stepName": "draft-plan", "agentRef": "planner", "status": "failed"}
                        },
                    },
                    summary_json={"totalSteps": 1, "failedSteps": 1},
                    step_states_json={
                        "draft-plan": {"stepName": "draft-plan", "agentRef": "planner", "status": "failed"}
                    },
                    artifact_path="/artifacts/feature-pipeline/run-123",
                    journal_path="/artifacts/feature-pipeline/run-123/journal.ndjson",
                    worker_job_name="worker-job-run-123",
                )
            )

        self.auth_store.record_workflow_run(
            workflow_name="feature-pipeline",
            namespace="default",
            run_id="run-123",
            phase="failed",
            total_steps=1,
            completed_steps=0,
            failed_steps=1,
            triggered_by="alice",
            input_text="Investigate the production regression",
        )
        self.auth_store.record_workflow_run_log_archive(
            workflow_name="feature-pipeline",
            namespace="default",
            run_id="run-123",
            log_text="2026-04-09T10:00:00Z INFO start\n2026-04-09T10:00:05Z ERROR crash",
            source="operator-terminal-archive",
            truncated=False,
        )

        trace = self.auth_store.get_workflow_run_trace(
            "feature-pipeline",
            "default",
            "run-123",
            include_logs=True,
        )
        self.assertIsNotNone(trace)
        assert trace is not None
        self.assertEqual(trace["workflow_name"], "feature-pipeline")
        self.assertEqual(trace["run_id"], "run-123")
        self.assertTrue(trace["archived_log_available"])
        self.assertEqual(trace["archived_log_source"], "operator-terminal-archive")
        self.assertIn("ERROR crash", trace["logs"])

        runs = self.auth_store.list_workflow_runs("feature-pipeline", "default", limit=5)
        self.assertEqual(len(runs), 1)
        self.assertTrue(runs[0]["trace_available"])
        self.assertTrue(runs[0]["archived_log_available"])
        self.assertTrue(runs[0]["journal_available"])

    def test_list_workflow_runs_falls_back_to_mirrored_rows_when_history_missing(self) -> None:
        with self.auth_store.db_session() as session:
            session.add(
                self.auth_store.WorkflowRun(
                    namespace="default",
                    resource_name="mirror-only-workflow",
                    run_id="run-mirror-only",
                    generation=3,
                    phase="completed",
                    spec_json={"input": "Deploy the mirrored bundle"},
                    summary_json={"totalSteps": 2, "completedSteps": 2, "failedSteps": 0},
                    journal_path="/artifacts/mirror-only-workflow/run-mirror-only/journal.ndjson",
                    log_archive_text="2026-04-09T11:00:00Z INFO archived",
                    log_archive_source="operator-terminal-archive",
                )
            )

        runs = self.auth_store.list_workflow_runs("mirror-only-workflow", "default", limit=5)

        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["run_id"], "run-mirror-only")
        self.assertTrue(runs[0]["trace_available"])
        self.assertTrue(runs[0]["archived_log_available"])
        self.assertTrue(runs[0]["journal_available"])
        self.assertEqual(runs[0]["input_text"], "Deploy the mirrored bundle")

    def test_create_update_and_delete_mcp_connection(self) -> None:
        created = self.auth_store.create_mcp_connection(
            namespace="default",
            name="Qdrant Prod",
            server_id="qdrant",
            transport="sidecar",
            auth_type="api_key",
            config={"url": "http://qdrant:6333", "sidecar_port": 9101},
            credential_metadata=[{"key": "api_key", "configured": True}],
            secret_name="mcp-conn-test",
            validation_status="draft",
        )

        self.assertEqual(created["name"], "Qdrant Prod")
        self.assertEqual(created["slug"], "qdrant-prod")
        self.assertEqual(created["server_id"], "qdrant")

        listed = self.auth_store.list_mcp_connections("default")
        self.assertEqual(len(listed), 1)
        self.assertEqual(listed[0]["id"], created["id"])

        updated = self.auth_store.update_mcp_connection(
            "default",
            created["id"],
            name="Qdrant Primary",
            config={"url": "http://qdrant.internal:6333", "sidecar_port": 9102},
            validation_status="valid",
            validation_message="Reachable",
        )
        self.assertEqual(updated["name"], "Qdrant Primary")
        self.assertEqual(updated["config"]["sidecar_port"], 9102)
        self.assertEqual(updated["validation"]["status"], "valid")

        self.assertTrue(self.auth_store.delete_mcp_connection("default", created["id"]))
        self.assertEqual(self.auth_store.list_mcp_connections("default"), [])


class AuthStorePostgresConfigTests(unittest.TestCase):
    def test_postgres_engine_uses_psycopg_compatible_connect_args(self) -> None:
        create_engine_mock = Mock(return_value=types.SimpleNamespace(dispose=lambda: None))
        module_name, auth_store = load_auth_store_with_env(
            {
                "DATABASE_URL": "",
                "DATABASE_HOST": "postgres.test",
                "DATABASE_PORT": "5432",
                "DATABASE_USER": "kubesynapse",
                "DATABASE_PASSWORD": "secret",
                "DATABASE_NAME": "kubesynapse",
                "DATABASE_DRIVER": "postgresql+psycopg",
            },
            create_engine_mock=create_engine_mock,
        )
        self.addCleanup(lambda: sys.modules.pop(module_name, None))
        self.addCleanup(auth_store.ENGINE.dispose)

        create_engine_mock.assert_called_once()
        _, kwargs = create_engine_mock.call_args
        self.assertEqual(
            kwargs["connect_args"],
            {
                "connect_timeout": 10,
                "options": "-c statement_timeout=30000ms",
            },
        )
