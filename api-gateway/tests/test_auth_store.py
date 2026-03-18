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