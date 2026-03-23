import importlib.util
import os
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch


MODULE_PATH = Path(__file__).resolve().parents[1] / "auth_store.py"


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
    ):
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

    def test_record_eval_outcome_memory_and_feedback(self) -> None:
        inserted = self.auth_store.record_eval_outcome_memory(
            "default",
            "reviewer",
            "reviewer-eval",
            phase="completed",
            passed=True,
            summary={"score": 0.91},
        )
        self.assertGreaterEqual(inserted, 1)

        records = self.auth_store.list_memory_records("default", "reviewer", session_id="reviewer-eval")
        self.assertTrue(any(record["topic"] == "eval-success" for record in records))
        before = max(float(record["score"]) for record in records)
        updated = self.auth_store.apply_memory_feedback("default", "reviewer", session_id="reviewer-eval", success=True)
        self.assertGreater(updated, 0)
        after_records = self.auth_store.list_memory_records("default", "reviewer", session_id="reviewer-eval")
        after = max(float(record["score"]) for record in after_records)
        self.assertGreaterEqual(after, before)
