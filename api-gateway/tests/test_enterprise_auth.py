import importlib.util
import json
import os
import sys
import types
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch


MODULE_PATH = Path(__file__).resolve().parents[1] / "enterprise_auth.py"


def build_fake_onelogin_modules() -> dict[str, types.ModuleType]:
    onelogin_module = types.ModuleType("onelogin")
    saml2_module = types.ModuleType("onelogin.saml2")
    auth_module = types.ModuleType("onelogin.saml2.auth")

    class FakeSettings:
        def get_sp_metadata(self) -> str:
            return "<EntityDescriptor entityID='https://gateway.example.com/api/auth/saml/metadata/corp'/>"

        def validate_metadata(self, metadata: str) -> list[str]:
            return [] if metadata else ["missing-metadata"]

    class FakeAuth:
        def __init__(self, request_data, old_settings=None, custom_base_path=None):
            self.request_data = request_data
            self.old_settings = old_settings or {}

        def login(self, return_to=None):
            return f"https://idp.example.com/sso?RelayState={return_to}"

        def get_last_request_id(self):
            return "request-123"

        def process_response(self, request_id=None):
            self.request_id = request_id

        def get_errors(self):
            return []

        def is_authenticated(self):
            return True

        def get_attributes(self):
            return {
                "uid": ["sam.user"],
                "mail": ["sam.user@example.com"],
                "displayName": ["Sam User"],
                "groups": ["platform-operators"],
            }

        def get_nameid(self):
            return "sam.user@example.com"

        def get_settings(self):
            return FakeSettings()

    auth_module.OneLogin_Saml2_Auth = FakeAuth
    return {
        "onelogin": onelogin_module,
        "onelogin.saml2": saml2_module,
        "onelogin.saml2.auth": auth_module,
    }


def load_enterprise_auth() -> tuple[str, object]:
    module_name = f"enterprise_auth_test_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(module_name, MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Failed to load enterprise_auth module for tests")

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(module_name, None)
        raise

    return module_name, module


class EnterpriseAuthSamlTests(unittest.TestCase):
    def setUp(self) -> None:
        saml_config = json.dumps(
            [
                {
                    "id": "corp",
                    "name": "Corporate SSO",
                    "idp_entity_id": "https://idp.example.com/metadata",
                    "sso_url": "https://idp.example.com/sso",
                    "x509cert": "-----BEGIN CERTIFICATE-----test-----END CERTIFICATE-----",
                    "group_role_mapping": {
                        "platform-operators": {
                            "role": "operator",
                            "allowed_namespaces": ["team-a", "team-b"],
                        }
                    },
                }
            ]
        )
        env_patcher = patch.dict(os.environ, {"SAML_PROVIDERS_JSON": saml_config}, clear=False)
        modules_patcher = patch.dict(sys.modules, build_fake_onelogin_modules(), clear=False)
        env_patcher.start()
        modules_patcher.start()
        self.addCleanup(env_patcher.stop)
        self.addCleanup(modules_patcher.stop)

        self.module_name, self.enterprise_auth = load_enterprise_auth()
        self.addCleanup(lambda: sys.modules.pop(self.module_name, None))

    def test_build_saml_authorization_request_and_metadata(self) -> None:
        providers = self.enterprise_auth.saml_providers()

        self.assertEqual(providers, [{"id": "corp", "name": "Corporate SSO", "kind": "saml", "supported": True}])

        auth_request = self.enterprise_auth.build_saml_authorization_request(
            "corp",
            "https://gateway.example.com",
            "/workspace",
        )
        cookie_payload = self.enterprise_auth.decode_transaction_cookie(auth_request["cookie_value"])

        self.assertEqual(cookie_payload["kind"], "saml")
        self.assertEqual(cookie_payload["provider_id"], "corp")
        self.assertEqual(cookie_payload["request_id"], "request-123")
        self.assertEqual(cookie_payload["next"], "/workspace")
        self.assertIn(cookie_payload["relay_state"], auth_request["authorization_url"])

        metadata = self.enterprise_auth.saml_metadata_xml("corp", "https://gateway.example.com")
        self.assertIn("EntityDescriptor", metadata)

    def test_exchange_saml_response_maps_identity_and_role(self) -> None:
        auth_request = self.enterprise_auth.build_saml_authorization_request(
            "corp",
            "https://gateway.example.com",
            "/team-a",
        )
        cookie_payload = self.enterprise_auth.decode_transaction_cookie(auth_request["cookie_value"])

        identity = self.enterprise_auth.exchange_saml_response(
            "corp",
            saml_response="encoded-response",
            relay_state=cookie_payload["relay_state"],
            cookie_value=auth_request["cookie_value"],
            base_url="https://gateway.example.com",
            request_path="/api/auth/saml/callback/corp",
            post_data={
                "SAMLResponse": "encoded-response",
                "RelayState": cookie_payload["relay_state"],
            },
        )

        self.assertEqual(identity["username"], "sam.user")
        self.assertEqual(identity["email"], "sam.user@example.com")
        self.assertEqual(identity["display_name"], "Sam User")
        self.assertEqual(identity["auth_provider"], "saml:corp")
        self.assertEqual(identity["role"], "operator")
        self.assertEqual(identity["allowed_namespaces"], ["team-a", "team-b"])
        self.assertEqual(identity["next"], "/team-a")


class LdapEscapeTests(unittest.TestCase):
    """Tests for the _ldap_escape helper (RFC 4515 special characters)."""

    def setUp(self) -> None:
        self.module_name, self.ea = load_enterprise_auth()
        self.addCleanup(lambda: sys.modules.pop(self.module_name, None))

    def test_plain_value_unchanged(self) -> None:
        self.assertEqual(self.ea._ldap_escape("alice"), "alice")

    def test_escapes_backslash(self) -> None:
        self.assertEqual(self.ea._ldap_escape("a\\b"), "a\\5cb")

    def test_escapes_asterisk(self) -> None:
        self.assertEqual(self.ea._ldap_escape("user*"), "user\\2a")

    def test_escapes_parentheses(self) -> None:
        self.assertEqual(self.ea._ldap_escape("(admin)"), "\\28admin\\29")

    def test_escapes_null_byte(self) -> None:
        self.assertEqual(self.ea._ldap_escape("a\x00b"), "a\\00b")

    def test_escapes_combined(self) -> None:
        self.assertEqual(
            self.ea._ldap_escape("user\\*(name)"),
            "user\\5c\\2a\\28name\\29",
        )