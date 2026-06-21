import asyncio
import copy
import hashlib
import importlib.util
import json
import sys
import tempfile
import types
import unittest
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import httpx
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

try:
    import jose  # noqa: F401
except ModuleNotFoundError:
    jose_module = types.ModuleType("jose")
    jose_module.jwk = types.SimpleNamespace(construct=lambda *_args, **_kwargs: None)
    jose_module.jwt = types.SimpleNamespace(
        get_unverified_header=lambda _token: {},
        get_unverified_claims=lambda _token: {},
    )
    jose_utils_module = types.ModuleType("jose.utils")
    jose_utils_module.base64url_decode = lambda value: value
    sys.modules["jose"] = jose_module
    sys.modules["jose.utils"] = jose_utils_module


MODULE_DIR = Path(__file__).resolve().parents[1]
if str(MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(MODULE_DIR))


def _load_gateway_module(module_name: str, file_name: str):
    module_path = MODULE_DIR / file_name
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Failed to load api-gateway module {file_name} for tests")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


api_gateway_main = _load_gateway_module("api_gateway_core", "_core.py")
sys.modules["_core"] = api_gateway_main
api_gateway_auth = _load_gateway_module("api_gateway_auth", "routers/auth.py")
sys.modules["routers.auth"] = api_gateway_auth
api_gateway_observability = _load_gateway_module("api_gateway_observability", "routers/observability.py")
sys.modules["routers.observability"] = api_gateway_observability
api_gateway_admin = _load_gateway_module("api_gateway_admin", "routers/admin.py")
sys.modules["routers.admin"] = api_gateway_admin
api_gateway_agents = _load_gateway_module("api_gateway_agents", "routers/agents.py")
sys.modules["routers.agents"] = api_gateway_agents
api_gateway_llm = _load_gateway_module("api_gateway_llm", "routers/llm.py")
sys.modules["routers.llm"] = api_gateway_llm
api_gateway_workflows = _load_gateway_module("api_gateway_workflows", "routers/workflows.py")
sys.modules["routers.workflows"] = api_gateway_workflows
api_gateway_a2a = _load_gateway_module("api_gateway_a2a", "routers/a2a.py")
sys.modules["routers.a2a"] = api_gateway_a2a
api_gateway_app = _load_gateway_module("api_gateway_app", "main.py")
api_gateway_auth_middleware = sys.modules["auth_middleware"]

api_gateway_auth.get_tool_categories = api_gateway_observability.get_tool_categories


def _bind_gateway_module(test_case: unittest.TestCase, module) -> None:
    original_module = globals()["api_gateway_main"]
    globals()["api_gateway_main"] = module
    test_case.addCleanup(lambda: globals().__setitem__("api_gateway_main", original_module))


class GatewayRuntimeValidationTests(unittest.TestCase):
    def test_unsupported_agent_runtime_is_rejected(self) -> None:
        with self.assertRaises(HTTPException) as context:
            api_gateway_main.validate_agent_runtime_compatibility(
                {
                    "runtime": {"kind": "legacy"},
                    "mcpServers": ["github"],
                    "mcpSidecars": [],
                }
            )

        self.assertEqual(context.exception.status_code, 400)
        self.assertIn("runtime kind must be 'opencode'", str(context.exception.detail))


class AuthConfigurationTests(unittest.TestCase):
    def test_auth_configuration_payload_hides_browser_auth_when_storage_is_unavailable(self) -> None:
        with (
            patch.object(api_gateway_auth_middleware, "AUTH_MODE", "shared_token"),
            patch.object(api_gateway_auth_middleware, "LOCAL_AUTH_ENABLED", True),
            patch.object(api_gateway_auth_middleware, "REGISTRATION_ENABLED", True),
            patch.object(api_gateway_auth_middleware, "SHARED_TOKEN", "test-shared-token"),
            patch.object(api_gateway_auth_middleware, "auth_storage_ready", return_value=False),
            patch.object(api_gateway_auth_middleware, "ldap_enabled", return_value=True),
            patch.object(api_gateway_auth_middleware, "oidc_providers", return_value=[{"id": "oidc"}]),
            patch.object(api_gateway_auth_middleware, "saml_providers", return_value=[{"id": "saml"}]),
        ):
            payload = api_gateway_auth_middleware.auth_configuration_payload()

        self.assertTrue(payload["shared_token_enabled"])
        self.assertFalse(payload["local_enabled"])
        self.assertFalse(payload["registration_enabled"])
        self.assertFalse(payload["browser_auth_enabled"])
        self.assertFalse(payload["bootstrap_complete"])
        self.assertEqual(payload["password_providers"], [])
        self.assertEqual(payload["oidc_providers"], [])
        self.assertEqual(payload["saml_providers"], [])

    def test_refresh_session_returns_service_unavailable_when_auth_storage_is_missing(self) -> None:
        raw_request = Mock()
        raw_request.headers = {"user-agent": "pytest"}
        raw_request.client = None

        with patch.object(api_gateway_auth_middleware, "auth_storage_ready", return_value=False):
            with self.assertRaises(HTTPException) as context:
                api_gateway_auth.refresh_session(raw_request, refresh_token="session.secret")

        self.assertEqual(context.exception.status_code, 503)
        self.assertEqual(str(context.exception.detail), "Browser authentication is temporarily unavailable")


class AdminUserNamespaceProvisioningTests(unittest.TestCase):
    def setUp(self) -> None:
        self.admin_user = {
            "sub": "1",
            "username": "platform-admin",
            "role": "admin",
            "allowed_namespaces": ["*"],
        }

    def test_admin_create_user_provisions_dedicated_tenant_namespace(self) -> None:
        body = api_gateway_admin.CreateUserRequest(
            username="Alice.User",
            password="Str0ngP4ssword!",
            display_name="Alice",
            role="operator",
            allowed_namespaces=["team-a"],
        )
        created = {
            "id": 7,
            "username": "alice.user",
            "display_name": "Alice",
            "role": "operator",
            "allowed_namespaces": ["team-a", "user-alice-user"],
            "auth_provider": "local",
            "is_active": True,
        }
        custom_api = Mock()

        with (
            patch.object(api_gateway_admin, "create_local_user", return_value=created) as create_local_user,
            patch.object(api_gateway_admin, "safe_record_audit"),
            patch.object(api_gateway_admin, "request_client_ip", return_value="127.0.0.1"),
            patch.object(api_gateway_admin, "_custom_objects_api", return_value=custom_api),
        ):
            response = api_gateway_admin.admin_create_user(body, object(), user=self.admin_user)

        self.assertEqual(response, created)
        create_local_user.assert_called_once_with(
            username="Alice.User",
            password="Str0ngP4ssword!",
            email=None,
            display_name="Alice",
            role="operator",
            allowed_namespaces=["team-a", "user-alice-user"],
        )
        custom_api.create_cluster_custom_object.assert_called_once()
        tenant_body = custom_api.create_cluster_custom_object.call_args.kwargs["body"]
        self.assertEqual(tenant_body["metadata"]["name"], "user-alice-user")
        self.assertEqual(tenant_body["spec"]["namespace"], "user-alice-user")
        self.assertEqual(tenant_body["spec"]["adminUsers"], ["alice.user"])

    def test_admin_update_user_replaces_existing_user_tenant_and_drops_admin_wildcard(self) -> None:
        body = api_gateway_admin.UpdateUserRequest(role="operator")
        existing_user = types.SimpleNamespace(
            id=8,
            username="legacy.admin",
            role="admin",
            allowed_namespaces=["*"],
            is_active=True,
        )
        updated = {
            "id": 8,
            "username": "legacy.admin",
            "display_name": "Legacy Admin",
            "role": "operator",
            "allowed_namespaces": ["user-legacy-admin"],
            "auth_provider": "local",
            "is_active": True,
        }
        conflict = type("ConflictError", (Exception,), {"status": 409})()
        custom_api = Mock()
        custom_api.create_cluster_custom_object.side_effect = conflict
        custom_api.get_cluster_custom_object.return_value = {
            "apiVersion": "kubesynapse.ai/v1alpha1",
            "kind": "AgentTenant",
            "metadata": {"name": "user-legacy-admin", "resourceVersion": "1"},
            "spec": {"tenantName": "legacy-admin", "namespace": "user-legacy-admin", "adminUsers": ["legacy.admin"]},
        }

        with (
            patch.object(api_gateway_admin, "get_user_by_id", return_value=existing_user),
            patch.object(api_gateway_admin, "update_user_fields", return_value=updated) as update_user_fields,
            patch.object(api_gateway_admin, "safe_record_audit"),
            patch.object(api_gateway_admin, "request_client_ip", return_value="127.0.0.1"),
            patch.object(api_gateway_admin, "_custom_objects_api", return_value=custom_api),
        ):
            response = api_gateway_admin.admin_update_user(8, body, object(), user=self.admin_user)

        self.assertEqual(response, updated)
        update_user_fields.assert_called_once_with(
            8,
            display_name=None,
            role="operator",
            is_active=None,
            allowed_namespaces=["user-legacy-admin"],
            capabilities=None,
        )
        custom_api.replace_cluster_custom_object.assert_called_once()
        tenant_body = custom_api.replace_cluster_custom_object.call_args.kwargs["body"]
        self.assertEqual(tenant_body["spec"]["namespace"], "user-legacy-admin")
        self.assertEqual(tenant_body["spec"]["adminUsers"], ["legacy.admin"])

    def test_mistral_vibe_agent_runtime_is_accepted(self) -> None:
        api_gateway_main.validate_agent_runtime_compatibility(
            {
                "runtime": {"kind": "mistral-vibe"},
                "model": "devstral-small",
            }
        )

    def test_opencode_agent_rejects_github_config(self) -> None:
        with self.assertRaises(HTTPException) as context:
            api_gateway_main.validate_agent_runtime_compatibility(
                {
                    "runtime": {"kind": "opencode"},
                    "githubConfig": {"credentialSecretRef": "github-creds"},
                }
            )

        self.assertEqual(context.exception.status_code, 400)
        self.assertIn("github_config", str(context.exception.detail))

    def test_unsupported_invoke_runtime_is_rejected(self) -> None:
        request = api_gateway_main.InvokeRequest(prompt="hello")

        with self.assertRaises(HTTPException) as context:
            api_gateway_main.validate_invoke_runtime_compatibility("legacy", request)

        self.assertEqual(context.exception.status_code, 400)
        self.assertIn("Unsupported AIAgent runtime kind", str(context.exception.detail))

    def test_mistral_vibe_invoke_runtime_accepts_core_request(self) -> None:
        request = api_gateway_main.InvokeRequest(prompt="hello")

        api_gateway_main.validate_invoke_runtime_compatibility("mistral-vibe", request)

    def test_opencode_invoke_rejects_tool_style_fields(self) -> None:
        request = api_gateway_main.InvokeRequest(
            prompt="hello",
            tool_name="tool.run",
            mcp_server="github",
            sandbox_session={"id": "session-1"},
        )

        with self.assertRaises(HTTPException) as context:
            api_gateway_main.validate_invoke_runtime_compatibility("opencode", request)

        self.assertEqual(context.exception.status_code, 400)
        self.assertIn("tool_name", str(context.exception.detail))
        self.assertIn("mcp_server", str(context.exception.detail))
        self.assertIn("sandbox_session", str(context.exception.detail))

    def test_opencode_invoke_rejects_subagents(self) -> None:
        request = api_gateway_main.InvokeRequest(
            prompt="Coordinate the investigation",
            subagents=[{"name": "analysis-agent", "namespace": "team-b"}],
        )

        with self.assertRaises(HTTPException) as context:
            api_gateway_main.validate_invoke_runtime_compatibility("opencode", request)

        self.assertEqual(context.exception.status_code, 400)
        self.assertIn("subagents", str(context.exception.detail))

    def test_opencode_invoke_allows_opencode_only_fields(self) -> None:
        request = api_gateway_main.InvokeRequest(
            prompt="hello",
            output_format="json",
            output_schema={"type": "object", "properties": {"ok": {"type": "boolean"}}},
            max_retries=2,
            structured_output_retry_count=3,
            autonomous=False,
        )

        api_gateway_main.validate_invoke_runtime_compatibility("opencode", request)

    def test_opencode_invoke_allows_a2a_fields(self) -> None:
        request = api_gateway_main.InvokeRequest(
            prompt="hello",
            a2a_target_agent="analysis-agent",
            a2a_target_namespace="team-b",
            a2a_timeout_seconds=15,
        )

        api_gateway_main.validate_invoke_runtime_compatibility("opencode", request)

    def test_resolve_invoke_agent_reference_accepts_namespace_path(self) -> None:
        agent_name, namespace = api_gateway_main.resolve_invoke_agent_reference(
            "analysis-agent",
            "team-b",
            path_namespace="team-b",
        )

        self.assertEqual(agent_name, "analysis-agent")
        self.assertEqual(namespace, "team-b")

    def test_resolve_invoke_agent_reference_rejects_namespace_mismatch(self) -> None:
        with self.assertRaises(HTTPException) as context:
            api_gateway_main.resolve_invoke_agent_reference(
                "analysis-agent",
                "team-a",
                path_namespace="team-b",
            )

        self.assertEqual(context.exception.status_code, 400)
        self.assertIn("namespace query parameter must match", str(context.exception.detail))

    def test_delete_is_allowed_for_cors(self) -> None:
        cors_middleware = next(
            middleware
            for middleware in api_gateway_app.app.user_middleware
            if middleware.cls.__name__ == "CORSMiddleware"
        )

        self.assertIn("DELETE", cors_middleware.kwargs["allow_methods"])

    def test_invoke_request_normalizes_whitespace(self) -> None:
        request = api_gateway_main.InvokeRequest(
            prompt="  hello  ",
            thread_id="   ",
            model="  ",
            system="   ",
            approval_action="   ",
            tool_name="  ",
            mcp_server="   ",
            a2a_target_agent=" analysis-agent ",
            a2a_target_namespace=" team-b ",
            working_directory="  nested/project  ",
            builtin_extensions=[" developer ", "   "],
            stdio_extensions=[" echo tool ", "   "],
            streamable_http_extensions=[" https://example.com/mcp ", "   "],
            subagent_strategy=" Parallel ",
        )

        self.assertEqual(request.prompt, "hello")
        self.assertIsNone(request.thread_id)
        self.assertIsNone(request.model)
        self.assertIsNone(request.system)
        self.assertIsNone(request.approval_action)
        self.assertEqual(request.tool_name, "")
        self.assertIsNone(request.mcp_server)
        self.assertEqual(request.a2a_target_agent, "analysis-agent")
        self.assertEqual(request.a2a_target_namespace, "team-b")
        self.assertEqual(request.working_directory, "nested/project")
        self.assertEqual(request.builtin_extensions, ["developer"])
        self.assertEqual(request.stdio_extensions, ["echo tool"])
        self.assertEqual(request.streamable_http_extensions, ["https://example.com/mcp"])
        self.assertEqual(request.subagent_strategy, "parallel")

    def test_invoke_request_requires_complete_a2a_target(self) -> None:
        with self.assertRaises(ValueError):
            api_gateway_main.InvokeRequest(prompt="hello", a2a_target_agent="analysis-agent")

    def test_policy_info_from_resource_includes_tool_policy(self) -> None:
        info = api_gateway_main.policy_info_from_resource(
            {
                "metadata": {"name": "team-policy", "namespace": "default"},
                "spec": {
                    "allowedModels": ["gpt-4"],
                    "allowedMcpServers": ["github"],
                    "mcpRequireHitl": True,
                    "toolPolicy": {
                        "maxDelegationDepth": 2,
                        "allowedToolPrefixes": ["github/"],
                    },
                },
            }
        )

        self.assertEqual(info.tool_policy["maxDelegationDepth"], 2)
        self.assertEqual(info.tool_policy["allowedToolPrefixes"], ["github/"])

    def test_build_memory_context_system_note_formats_promoted_records(self) -> None:
        note = api_gateway_main.build_memory_context_system_note(
            [
                {"topic": "response-summary", "content": "Repository uses a monorepo layout."},
                {"topic": "tools", "content": "filesystem.read, github/diff"},
            ]
        )

        self.assertIn("persistent memory", note)
        self.assertIn("response-summary", note)
        self.assertIn("monorepo layout", note)

    def test_rank_promoted_memory_records_respects_policy_bounds(self) -> None:
        ranked = api_gateway_main.rank_promoted_memory_records(
            "Use the repo root Make targets before direct docker builds",
            [
                {
                    "memory_type": "procedural",
                    "topic": "response-summary",
                    "content": "Use the repo root Make targets first.",
                    "created_at": "2026-03-23T00:00:00+00:00",
                },
                {
                    "memory_type": "episodic",
                    "topic": "tools",
                    "content": "filesystem.read, github/diff",
                    "created_at": "2026-03-20T00:00:00+00:00",
                },
            ],
            memory_policy={"maxInjectedMemories": 1, "maxInjectedChars": 200, "allowedMemoryTypes": ["procedural"]},
        )

        self.assertEqual(len(ranked), 1)
        self.assertEqual(ranked[0]["memory_type"], "procedural")

    def test_rank_promoted_memory_records_uses_stored_score(self) -> None:
        ranked = api_gateway_main.rank_promoted_memory_records(
            "unrelated prompt",
            [
                {
                    "memory_type": "episodic",
                    "topic": "tools",
                    "content": "filesystem.read",
                    "score": 0.0,
                    "created_at": "2026-03-23T00:00:00+00:00",
                },
                {
                    "memory_type": "procedural",
                    "topic": "repo-convention",
                    "content": "Use make test before pushing.",
                    "score": 5.0,
                    "created_at": "2026-03-20T00:00:00+00:00",
                },
            ],
            memory_policy={"maxInjectedMemories": 1, "maxInjectedChars": 200},
        )

        self.assertEqual(len(ranked), 1)
        self.assertEqual(ranked[0]["topic"], "repo-convention")

    def test_rank_promoted_memory_records_skips_false_no_memory_boilerplate(self) -> None:
        ranked = api_gateway_main.rank_promoted_memory_records(
            "What do you remember about chickens? Answer from your persistent memory if you have it.",
            [
                {
                    "memory_type": "procedural",
                    "topic": "assistant-summary",
                    "content": "I don't have persistent memory across sessions. What do you want to know?",
                    "score": 5.0,
                    "created_at": "2026-03-23T00:00:00+00:00",
                },
                {
                    "memory_type": "procedural",
                    "topic": "assistant-summary",
                    "content": "Noted. Chickens must be black. What next?",
                    "score": 5.0,
                    "created_at": "2026-03-23T00:00:00+00:00",
                },
            ],
            memory_policy={"maxInjectedMemories": 1, "maxInjectedChars": 200},
        )

        self.assertEqual(len(ranked), 1)
        self.assertEqual(ranked[0]["content"], "Noted. Chickens must be black. What next?")

    def test_sync_workflow_run_history_records_memory_feedback_for_terminal_workflow(self) -> None:
        info = api_gateway_main.WorkflowInfo(
            name="repo-check",
            namespace="default",
            phase="completed",
            run_id="run-1",
            steps=[api_gateway_main.WorkflowStepRequest(name="step-1", agent_ref="reviewer", prompt="check repo")],
            summary={
                "completedSteps": 3,
                "totalSteps": 3,
                "startedAt": "2026-03-23T00:00:00Z",
                "completedAt": "2026-03-23T00:10:00Z",
            },
        )

        with (
            patch.object(api_gateway_workflows, "record_workflow_run") as record_workflow_run,
            patch.object(
                api_gateway_workflows,
                "record_workflow_outcome_memory",
            ) as record_workflow_outcome_memory,
            patch.object(
                api_gateway_workflows,
                "apply_memory_feedback",
            ) as apply_memory_feedback,
        ):
            api_gateway_workflows._sync_workflow_run_history(info)

        record_workflow_run.assert_called_once()
        record_workflow_outcome_memory.assert_called_once()
        apply_memory_feedback.assert_called_once()


class IntelligenceNamespaceIsolationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.admin_module = api_gateway_admin
        self.observability_module = api_gateway_observability
        self.engine = create_engine(
            "sqlite:///:memory:",
            future=True,
            connect_args={"check_same_thread": False},
        )
        self.admin_module.IntelligenceCollectorRow.metadata.create_all(bind=self.engine)
        self.SessionLocal = sessionmaker(
            bind=self.engine,
            autoflush=False,
            autocommit=False,
            expire_on_commit=False,
            future=True,
        )
        self.db_patcher = patch.object(self.admin_module, "db_session", self._db_session)
        self.audit_patcher = patch.object(self.admin_module, "safe_record_audit")
        self.observability_db_patcher = patch.object(self.observability_module, "db_session", self._db_session)
        self.observability_audit_patcher = patch.object(self.observability_module, "safe_record_audit")
        self.db_patcher.start()
        self.audit_patcher.start()
        self.observability_db_patcher.start()
        self.observability_audit_patcher.start()
        self.addCleanup(self.db_patcher.stop)
        self.addCleanup(self.audit_patcher.stop)
        self.addCleanup(self.observability_db_patcher.stop)
        self.addCleanup(self.observability_audit_patcher.stop)
        self.addCleanup(self.engine.dispose)

        self.observability_module._collector_registry.clear()
        self.observability_module._collection_tasks.clear()
        self.addCleanup(self.observability_module._collector_registry.clear)
        self.addCleanup(self.observability_module._collection_tasks.clear)

        self.operator_user = {
            "sub": "operator-1",
            "role": "operator",
            "allowed_namespaces": ["team-a", "team-b"],
        }

    @contextmanager
    def _db_session(self):
        session = self.SessionLocal()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def test_build_auto_intelligence_context_filters_by_namespace(self) -> None:
        now = datetime.now(UTC)
        self.observability_module._collection_tasks.update(
            {
                "task-a": {
                    "task_id": "task-a",
                    "namespace": "team-a",
                    "collector_id": "collector-a",
                    "payload": {"builtin": "cluster_overview"},
                    "results": {"collector-a": {"status": "completed", "stdout": "team-a-output"}},
                    "submitted_by": "operator-1",
                    "submitted_at": (now - timedelta(minutes=1)).isoformat(),
                    "total": 1,
                    "completed": 1,
                },
                "task-b": {
                    "task_id": "task-b",
                    "namespace": "team-b",
                    "collector_id": "collector-b",
                    "payload": {"builtin": "cluster_overview"},
                    "results": {"collector-b": {"status": "completed", "stdout": "team-b-output"}},
                    "submitted_by": "operator-1",
                    "submitted_at": now.isoformat(),
                    "total": 1,
                    "completed": 1,
                },
            }
        )

        context = self.observability_module._build_auto_intelligence_context("team-a")

        self.assertIn("team-a-output", context)
        self.assertNotIn("team-b-output", context)

    def test_register_intelligence_collectors_are_namespaced(self) -> None:
        first = self.admin_module.register_intelligence_collector(
            body={
                "name": "Shared Collector",
                "url": "https://collector-a.example.test",
                "token": "token-a",
            },
            namespace="team-a",
            user=self.operator_user,
        )
        second = self.admin_module.register_intelligence_collector(
            body={
                "name": "Shared Collector",
                "url": "https://collector-b.example.test",
                "token": "token-b",
            },
            namespace="team-b",
            user=self.operator_user,
        )

        self.assertNotEqual(first["id"], second["id"])
        with self._db_session() as session:
            team_a = session.query(self.admin_module.IntelligenceCollectorRow).filter_by(namespace="team-a").all()
            team_b = session.query(self.admin_module.IntelligenceCollectorRow).filter_by(namespace="team-b").all()
        self.assertEqual(len(team_a), 1)
        self.assertEqual(len(team_b), 1)

    def test_register_intelligence_collector_persists_encrypted_token(self) -> None:
        collector = self.admin_module.register_intelligence_collector(
            body={
                "name": "Persistent Collector",
                "url": "https://collector-persist.example.test",
                "token": "super-secret-token",
            },
            namespace="team-a",
            user=self.operator_user,
        )

        with self._db_session() as session:
            row = session.query(self.admin_module.IntelligenceCollectorRow).filter_by(id=collector["id"]).one()

        self.assertIsNotNone(row.encrypted_token)
        self.assertNotEqual(row.encrypted_token, "super-secret-token")
        self.assertEqual(self.observability_module._decrypt_collector_token(row.encrypted_token), "super-secret-token")

    def test_load_collectors_from_db_recovers_legacy_default_dev_token(self) -> None:
        collector_id = self.observability_module._build_namespace_scoped_collector_id("team-a", "Legacy Collector")
        with self._db_session() as session:
            session.add(
                self.admin_module.IntelligenceCollectorRow(
                    id=collector_id,
                    namespace="team-a",
                    name="Legacy Collector",
                    url="https://collector-legacy.example.test",
                    token_hash=hashlib.sha256(b"collector-dev-token").hexdigest(),
                    encrypted_token=None,
                    cluster="legacy",
                    tags=[],
                    registered_at=datetime.now(UTC),
                    registered_by="operator-1",
                )
            )

        self.observability_module._collector_registry.clear()
        with (
            patch.object(self.observability_module, "_DEFAULT_COLLECTOR_TOKEN", "collector-dev-token"),
            patch.object(
                self.observability_module,
                "_DEFAULT_COLLECTOR_TOKEN_HASH",
                hashlib.sha256(b"collector-dev-token").hexdigest(),
            ),
        ):
            self.observability_module._load_collectors_from_db()

        recovered = self.observability_module._get_namespaced_collectors("team-a")
        self.assertEqual(recovered[collector_id]["token"], "collector-dev-token")

    def test_create_alert_rejects_cross_namespace_schedule(self) -> None:
        with self._db_session() as session:
            session.add(
                self.admin_module.IntelligenceScheduleRow(
                    id="sched-b",
                    namespace="team-b",
                    name="Foreign Schedule",
                    cron="*/5 * * * *",
                    collector_id="all",
                    builtin="node_health",
                    timeout=30,
                    created_by="operator-1",
                )
            )

        with self.assertRaises(HTTPException) as context:
            self.admin_module.create_intelligence_alert(
                body={
                    "name": "Cross Namespace Alert",
                    "schedule_id": "sched-b",
                    "condition_type": "contains",
                    "condition_value": "error",
                },
                namespace="team-a",
                user=self.operator_user,
            )

        self.assertEqual(context.exception.status_code, 400)
        self.assertIn("namespace 'team-a'", str(context.exception.detail))

    async def test_submit_collection_task_persists_namespace(self) -> None:
        class FakeResponse:
            status_code = 200

            def raise_for_status(self) -> None:
                return None

            def json(self) -> dict[str, str]:
                return {"status": "completed", "stdout": "healthy"}

        class FakeAsyncClient:
            def __init__(self, *args, **kwargs) -> None:
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb) -> bool:
                return False

            async def post(self, url, headers=None, json=None):
                return FakeResponse()

        self.admin_module._set_namespaced_collector(
            "team-a",
            "team-a-shared-collector",
            {
                "id": "team-a-shared-collector",
                "name": "Shared Collector",
                "url": "https://collector-a.example.test",
                "token": "token-a",
                "cluster": "test",
                "registered_at": "2026-04-06T00:00:00+00:00",
                "tags": [],
            },
        )

        with patch.object(self.admin_module.httpx, "AsyncClient", FakeAsyncClient):
            task = await self.admin_module.submit_collection_task(
                body={"collector_id": "team-a-shared-collector", "builtin": "node_health"},
                namespace="team-a",
                user=self.operator_user,
            )

        self.assertEqual(task["namespace"], "team-a")
        team_a_tasks = self.admin_module.list_collection_tasks(namespace="team-a", user=self.operator_user)
        team_b_tasks = self.admin_module.list_collection_tasks(namespace="team-b", user=self.operator_user)
        self.assertEqual(team_a_tasks["total"], 1)
        self.assertEqual(team_a_tasks["tasks"][0]["task_id"], task["task_id"])
        self.assertEqual(team_b_tasks["total"], 0)

    def test_delete_collection_task_removes_persisted_and_cached_task(self) -> None:
        task_record = {
            "task_id": "task-delete-one",
            "namespace": "team-a",
            "collector_id": "team-a-shared-collector",
            "payload": {"builtin": "node_health"},
            "results": {"team-a-shared-collector": {"status": "completed", "stdout": "healthy"}},
            "submitted_by": "operator-1",
            "submitted_at": datetime.now(UTC).isoformat(),
            "total": 1,
            "completed": 1,
        }

        with self._db_session() as session:
            session.add(
                self.admin_module.IntelligenceTaskRow(
                    task_id=task_record["task_id"],
                    namespace=task_record["namespace"],
                    collector_id=task_record["collector_id"],
                    payload=task_record["payload"],
                    results=task_record["results"],
                    submitted_by=task_record["submitted_by"],
                    submitted_at=datetime.fromisoformat(task_record["submitted_at"]),
                    total=task_record["total"],
                    completed=task_record["completed"],
                )
            )

        self.observability_module._collection_tasks[task_record["task_id"]] = dict(task_record)

        response = self.admin_module.delete_collection_task(
            task_record["task_id"],
            namespace="team-a",
            user=self.operator_user,
        )

        self.assertEqual(response["status"], "deleted")
        self.assertNotIn(task_record["task_id"], self.observability_module._collection_tasks)
        with self._db_session() as session:
            row = session.query(self.admin_module.IntelligenceTaskRow).filter_by(task_id=task_record["task_id"], namespace="team-a").first()
        self.assertIsNone(row)

    def test_bulk_delete_collection_tasks_deletes_selected_namespace_tasks(self) -> None:
        task_records = [
            {
                "task_id": "task-bulk-a1",
                "namespace": "team-a",
                "collector_id": "collector-a",
                "payload": {"builtin": "cluster_overview"},
                "results": {"collector-a": {"status": "completed", "stdout": "ok"}},
                "submitted_by": "operator-1",
                "submitted_at": datetime.now(UTC).isoformat(),
                "total": 1,
                "completed": 1,
            },
            {
                "task_id": "task-bulk-a2",
                "namespace": "team-a",
                "collector_id": "collector-a",
                "payload": {"builtin": "node_health"},
                "results": {"collector-a": {"status": "completed", "stdout": "ok"}},
                "submitted_by": "operator-1",
                "submitted_at": datetime.now(UTC).isoformat(),
                "total": 1,
                "completed": 1,
            },
            {
                "task_id": "task-bulk-b1",
                "namespace": "team-b",
                "collector_id": "collector-b",
                "payload": {"builtin": "pod_resources"},
                "results": {"collector-b": {"status": "completed", "stdout": "ok"}},
                "submitted_by": "operator-1",
                "submitted_at": datetime.now(UTC).isoformat(),
                "total": 1,
                "completed": 1,
            },
        ]

        with self._db_session() as session:
            for task_record in task_records:
                session.add(
                    self.admin_module.IntelligenceTaskRow(
                        task_id=task_record["task_id"],
                        namespace=task_record["namespace"],
                        collector_id=task_record["collector_id"],
                        payload=task_record["payload"],
                        results=task_record["results"],
                        submitted_by=task_record["submitted_by"],
                        submitted_at=datetime.fromisoformat(task_record["submitted_at"]),
                        total=task_record["total"],
                        completed=task_record["completed"],
                    )
                )
                self.observability_module._collection_tasks[task_record["task_id"]] = dict(task_record)

        response = self.admin_module.bulk_delete_collection_tasks(
            body={"task_ids": ["task-bulk-a1", "task-bulk-a2", "task-bulk-b1", "task-bulk-missing"]},
            namespace="team-a",
            user=self.operator_user,
        )

        self.assertEqual(response["deleted"], 2)
        self.assertEqual(response["deleted_ids"], ["task-bulk-a1", "task-bulk-a2"])
        self.assertEqual(response["missing_ids"], ["task-bulk-b1", "task-bulk-missing"])
        self.assertNotIn("task-bulk-a1", self.observability_module._collection_tasks)
        self.assertNotIn("task-bulk-a2", self.observability_module._collection_tasks)
        self.assertIn("task-bulk-b1", self.observability_module._collection_tasks)

        with self._db_session() as session:
            team_a_remaining = session.query(self.admin_module.IntelligenceTaskRow).filter_by(namespace="team-a").all()
            team_b_remaining = session.query(self.admin_module.IntelligenceTaskRow).filter_by(namespace="team-b").all()

        self.assertEqual(team_a_remaining, [])
        self.assertEqual(len(team_b_remaining), 1)

    async def test_list_collectors_marks_missing_token_degraded_without_info_probe(self) -> None:
        calls: list[tuple[str, dict[str, str] | None]] = []

        class FakeResponse:
            def __init__(self, status_code: int, payload: dict[str, object] | None = None) -> None:
                self.status_code = status_code
                self._payload = payload or {}

            def raise_for_status(self) -> None:
                if self.status_code >= 400:
                    request = httpx.Request("GET", "https://collector-a.example.test/info")
                    response = httpx.Response(self.status_code, request=request)
                    raise httpx.HTTPStatusError("collector info failed", request=request, response=response)

            def json(self) -> dict[str, object]:
                return self._payload

        class FakeAsyncClient:
            def __init__(self, *args, **kwargs) -> None:
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb) -> bool:
                return False

            async def get(self, url, headers=None):
                calls.append((url, headers))
                if url.endswith("/healthz"):
                    return FakeResponse(200)
                raise AssertionError("Collector metadata probe should not run when the token is unavailable")

        self.admin_module._set_namespaced_collector(
            "team-a",
            "team-a-missing-token",
            {
                "id": "team-a-missing-token",
                "name": "Missing Token",
                "url": "https://collector-a.example.test",
                "token": None,
                "cluster": "test",
                "registered_at": "2026-04-06T00:00:00+00:00",
                "tags": [],
            },
        )

        with patch.object(self.admin_module.httpx, "AsyncClient", FakeAsyncClient):
            result = await self.admin_module.list_intelligence_collectors(namespace="team-a", user=self.operator_user)

        self.assertEqual(result["collectors"][0]["status"], "degraded")
        self.assertIn("Re-register", result["collectors"][0]["error"])
        self.assertEqual(calls, [("https://collector-a.example.test/healthz", None)])

    async def test_submit_collection_task_reports_missing_token_without_request(self) -> None:
        class FakeAsyncClient:
            def __init__(self, *args, **kwargs) -> None:
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb) -> bool:
                return False

            async def post(self, url, headers=None, json=None):
                raise AssertionError("Collector task request should not run when the token is unavailable")

        self.admin_module._set_namespaced_collector(
            "team-a",
            "team-a-missing-token",
            {
                "id": "team-a-missing-token",
                "name": "Missing Token",
                "url": "https://collector-a.example.test",
                "token": "",
                "cluster": "test",
                "registered_at": "2026-04-06T00:00:00+00:00",
                "tags": [],
            },
        )

        with patch.object(self.admin_module.httpx, "AsyncClient", FakeAsyncClient):
            task = await self.admin_module.submit_collection_task(
                body={"collector_id": "team-a-missing-token", "builtin": "node_health"},
                namespace="team-a",
                user=self.operator_user,
            )

        self.assertEqual(task["results"]["team-a-missing-token"]["status"], "error")
        self.assertIn("Re-register", task["results"]["team-a-missing-token"]["error"])


class WorkflowSchemaTests(unittest.TestCase):
    def test_build_workflow_spec_preserves_context_and_review_fields(self) -> None:
        body = api_gateway_main.WorkflowRequest(
            name="feature-pipeline",
            description="desc",
            input="input",
            context_ref="project-rules",
            steps=[
                api_gateway_main.WorkflowStepRequest(
                    name="implement",
                    agent_ref="dev-agent",
                    prompt="Implement it",
                    verify="Run tests and report PASS or FAIL",
                ),
                api_gateway_main.WorkflowStepRequest(
                    name="review",
                    agent_ref="reviewer-agent",
                    step_type="review",
                    review_criteria="Code quality",
                    depends_on=["implement"],
                ),
            ],
        )

        spec = api_gateway_main.build_workflow_spec(body)

        self.assertEqual(spec["contextRef"], "project-rules")
        self.assertEqual(spec["steps"][0]["verify"], "Run tests and report PASS or FAIL")
        self.assertEqual(spec["steps"][1]["type"], "review")
        self.assertEqual(spec["steps"][1]["reviewCriteria"], "Code quality")

    def test_workflow_info_from_resource_maps_new_fields(self) -> None:
        workflow = {
            "metadata": {
                "name": "feature-pipeline",
                "namespace": "default",
                "creationTimestamp": "2026-03-19T00:00:00Z",
            },
            "spec": {
                "description": "desc",
                "input": "input",
                "contextRef": "project-rules",
                "messageBus": "in-memory",
                "steps": [
                    {
                        "name": "implement",
                        "agentRef": "dev-agent",
                        "prompt": "Implement",
                        "verify": "Run tests",
                    },
                    {
                        "name": "review",
                        "agentRef": "reviewer-agent",
                        "type": "review",
                        "reviewCriteria": "Code quality",
                        "dependsOn": ["implement"],
                    },
                ],
            },
            "status": {"phase": "running", "currentStep": "review"},
        }

        info = api_gateway_main.workflow_info_from_resource(workflow)

        self.assertEqual(info.context_ref, "project-rules")
        self.assertEqual(info.steps[0].verify, "Run tests")
        self.assertEqual(info.steps[1].step_type, "review")
        self.assertEqual(info.steps[1].review_criteria, "Code quality")

    def test_parse_json_object_response_rejects_invalid_json(self) -> None:
        response = httpx.Response(200, text="not-json")

        with self.assertRaises(HTTPException) as context:
            api_gateway_main.parse_json_object_response(response, context="Agent runtime /invoke")

        self.assertEqual(context.exception.status_code, 502)
        self.assertIn("invalid JSON", str(context.exception.detail))

    def test_parse_json_object_response_rejects_non_object_payload(self) -> None:
        response = httpx.Response(200, json=["not", "an", "object"])

        with self.assertRaises(HTTPException) as context:
            api_gateway_main.parse_json_object_response(response, context="Agent runtime /invoke")

        self.assertEqual(context.exception.status_code, 502)
        self.assertIn("non-object", str(context.exception.detail))

    def test_error_payload_from_body_prefers_detail_field(self) -> None:
        payload = api_gateway_main.error_payload_from_body(
            json.dumps({"detail": "runtime cold start"}).encode("utf-8"),
            "fallback",
        )

        self.assertEqual(payload, {"error": "runtime cold start"})

    def test_error_payload_from_body_sanitizes_html_error_page(self) -> None:
        payload = api_gateway_main.error_payload_from_body(
            b"<!DOCTYPE html><html><head><title>502 Bad Gateway</title></head><body><h1>502 Bad Gateway</h1><p>nginx</p></body></html>",
            "fallback",
        )

        self.assertEqual(payload, {"error": "Upstream service error: 502 Bad Gateway"})

    def test_parse_opencode_config_files_normalizes_relative_paths(self) -> None:
        parsed = api_gateway_main.parse_opencode_config_files(
            {
                " opencode.json ": {"default_agent": "build"},
                "plugins\\notify.ts": "export const NotifyPlugin = async () => ({})",
            },
            source="opencode_config_files",
        )

        self.assertEqual(
            parsed,
            {
                "opencode.json": {"default_agent": "build"},
                "plugins/notify.ts": "export const NotifyPlugin = async () => ({})",
            },
        )

    def test_parse_agent_skills_config_normalizes_markdown_paths(self) -> None:
        parsed = api_gateway_main.parse_agent_skills_config(
            {
                "files": {
                    " .github\\skills\\reviewer\\SKILL.md ": "---\nname: reviewer\n---\nReview carefully.\n",
                }
            },
            source="skills",
            strict=True,
        )

        self.assertEqual(
            parsed,
            {
                "files": {
                    ".github/skills/reviewer/SKILL.md": "---\nname: reviewer\n---\nReview carefully.\n",
                }
            },
        )

    def test_parse_agent_skills_config_rejects_non_markdown_paths(self) -> None:
        with self.assertRaises(HTTPException) as context:
            api_gateway_main.parse_agent_skills_config(
                {"files": {"skills/reviewer/config.yaml": "name: reviewer"}},
                source="skills",
                strict=True,
            )

        self.assertEqual(context.exception.status_code, 400)
        self.assertIn(".md", str(context.exception.detail))

    def test_build_agent_spec_includes_opencode_config_files(self) -> None:
        request = api_gateway_main.CreateAgentRequest(
            name="opencode-agent",
            model="gpt-4",
            runtime_kind="opencode",
            opencode_config_files={"opencode.json": {"default_agent": "build"}},
        )

        spec = api_gateway_main.build_agent_spec(request)

        self.assertEqual(spec["runtime"]["kind"], "opencode")
        self.assertEqual(
            spec["runtime"]["opencode"]["configFiles"],
            {"opencode.json": {"default_agent": "build"}},
        )

    def test_build_agent_spec_includes_a2a_config(self) -> None:
        request = api_gateway_main.CreateAgentRequest(
            name="opencode-agent",
            model="gpt-4",
            runtime_kind="opencode",
            a2a_config={
                "allowed_callers": [
                    {"name": "research-agent", "namespace": "team-a"},
                ]
            },
        )

        spec = api_gateway_main.build_agent_spec(request)

        self.assertEqual(
            spec["a2a"],
            {"allowedCallers": [{"name": "research-agent", "namespace": "team-a"}]},
        )

    def test_create_agent_request_accepts_system_prompt_up_to_shared_limit(self) -> None:
        prompt = "x" * api_gateway_main.AGENT_SYSTEM_PROMPT_MAX_CHARS

        request = api_gateway_main.CreateAgentRequest(
            name="long-prompt-agent",
            model="gpt-4",
            runtime_kind="opencode",
            system_prompt=prompt,
        )

        self.assertEqual(request.system_prompt, prompt)

    def test_update_agent_request_rejects_system_prompt_above_shared_limit(self) -> None:
        prompt = "x" * (api_gateway_main.AGENT_SYSTEM_PROMPT_MAX_CHARS + 1)

        with self.assertRaises(ValidationError):
            api_gateway_main.UpdateAgentRequest(
                model="gpt-4",
                system_prompt=prompt,
            )

    def test_build_agent_spec_includes_skill_files(self) -> None:
        request = api_gateway_main.CreateAgentRequest(
            name="opencode-agent",
            model="gpt-4",
            runtime_kind="opencode",
            skills={
                "files": {
                    "skills/research/SKILL.md": (
                        "---\n"
                        "name: research\n"
                        "description: Gather evidence carefully.\n"
                        "allowedSandboxTools:\n"
                        "  - sandbox.filesystem.read\n"
                        "---\n"
                        "Read source material before answering.\n"
                    )
                }
            },
        )

        spec = api_gateway_main.build_agent_spec(request)

        self.assertIn("skills", spec)
        self.assertIn("skills/research/SKILL.md", spec["skills"]["files"])

    def test_build_agent_spec_includes_structured_mcp_connections(self) -> None:
        request = api_gateway_main.CreateAgentRequest(
            name="opencode-agent",
            model="gpt-4",
            runtime_kind="opencode",
            mcp_connection_ids=["conn-docs"],
        )

        with patch.object(
            api_gateway_main,
            "_build_saved_agent_mcp_connections",
            return_value=[
                {
                    "connectionId": "conn-docs",
                    "name": "Docs Remote",
                    "slug": "docs-remote",
                    "serverId": "docs",
                    "transport": "remote",
                    "source": "saved",
                    "runtime": {
                        "kind": "remote",
                        "configKey": "docs-remote",
                        "url": "https://docs.example.com/mcp",
                        "headers": [],
                    },
                }
            ],
        ):
            spec = api_gateway_main.build_agent_spec(request, namespace="team-a")

        self.assertEqual(spec["mcpConnections"][0]["connectionId"], "conn-docs")
        self.assertEqual(spec["mcpServers"], ["docs"])
        self.assertEqual(spec["mcpSidecars"], [])

    def test_build_agent_spec_validates_policy_reference(self) -> None:
        request = api_gateway_main.CreateAgentRequest(
            name="opencode-agent",
            model="gpt-4",
            runtime_kind="opencode",
            policy_ref="shared-policies/planner-policy",
        )

        with patch.object(api_gateway_main, "read_custom_resource", return_value={"spec": {}}) as mock_read:
            spec = api_gateway_main.build_agent_spec(request, namespace="team-a")

        self.assertEqual(spec["policyRef"], "shared-policies/planner-policy")
        mock_read.assert_called_once_with("agentpolicies", "planner-policy", "shared-policies", "Policy")

    def test_build_agent_spec_rejects_missing_policy_reference(self) -> None:
        request = api_gateway_main.CreateAgentRequest(
            name="opencode-agent",
            model="gpt-4",
            runtime_kind="opencode",
            policy_ref="missing-policy",
        )

        with patch.object(
            api_gateway_main,
            "read_custom_resource",
            side_effect=HTTPException(status_code=404, detail="Policy 'missing-policy' not found"),
        ), self.assertRaises(HTTPException) as context:
            api_gateway_main.build_agent_spec(request, namespace="team-a")

        self.assertEqual(context.exception.status_code, 404)
        self.assertIn("missing-policy", str(context.exception.detail))

    def test_build_agent_spec_preserves_existing_a2a_config_on_update(self) -> None:
        request = api_gateway_main.UpdateAgentRequest(model="gpt-4")

        spec = api_gateway_main.build_agent_spec(
            request,
            existing_spec={
                "model": "gpt-4",
                "a2a": {"allowedCallers": [{"name": "research-agent", "namespace": "team-a"}]},
                "runtime": {"kind": "opencode"},
            },
        )

        self.assertEqual(
            spec["a2a"],
            {"allowedCallers": [{"name": "research-agent", "namespace": "team-a"}]},
        )

    def test_build_agent_spec_rejects_existing_unsupported_runtime_on_update(self) -> None:
        request = api_gateway_main.UpdateAgentRequest(model="gpt-4")

        with self.assertRaises(HTTPException) as context:
            api_gateway_main.build_agent_spec(
                request,
                existing_spec={
                    "model": "gpt-4",
                    "runtime": {
                        "kind": "legacy",
                    },
                },
            )

        self.assertEqual(context.exception.status_code, 400)
        self.assertIn("runtime kind must be 'opencode'", str(context.exception.detail))

    def test_build_agent_spec_preserves_existing_opencode_config_files_on_update(self) -> None:
        request = api_gateway_main.UpdateAgentRequest(model="gpt-4")

        spec = api_gateway_main.build_agent_spec(
            request,
            existing_spec={
                "model": "gpt-4",
                "runtime": {
                    "kind": "opencode",
                    "opencode": {"configFiles": {"opencode.json": {"default_agent": "build"}}},
                },
            },
        )

        self.assertEqual(spec["runtime"]["kind"], "opencode")
        self.assertEqual(
            spec["runtime"]["opencode"]["configFiles"],
            {"opencode.json": {"default_agent": "build"}},
        )

    def test_build_agent_spec_preserves_existing_skills_on_update(self) -> None:
        request = api_gateway_main.UpdateAgentRequest(model="gpt-4")

        spec = api_gateway_main.build_agent_spec(
            request,
            existing_spec={
                "model": "gpt-4",
                "runtime": {"kind": "opencode"},
                "skills": {
                    "files": {
                        "skills/research/SKILL.md": "---\nname: research\n---\nRead first.\n",
                    }
                },
            },
        )

        self.assertEqual(
            spec["skills"],
            {
                "files": {
                    "skills/research/SKILL.md": "---\nname: research\n---\nRead first.\n",
                }
            },
        )

    def test_build_agent_spec_preserves_existing_mcp_connections_on_update(self) -> None:
        existing_connections = [
            {
                "connectionId": "conn-docs",
                "name": "Docs Remote",
                "slug": "docs-remote",
                "serverId": "docs",
                "transport": "remote",
                "source": "saved",
                "runtime": {
                    "kind": "remote",
                    "configKey": "docs-remote",
                    "url": "https://docs.example.com/mcp",
                    "headers": [],
                },
            }
        ]

        spec = api_gateway_main.build_agent_spec(
            api_gateway_main.UpdateAgentRequest(model="gpt-4"),
            existing_spec={
                "model": "gpt-4",
                "runtime": {"kind": "opencode"},
                "mcpConnections": existing_connections,
            },
            namespace="team-a",
        )

        self.assertEqual(spec["mcpConnections"], existing_connections)
        self.assertEqual(spec["mcpServers"], ["docs"])

    def test_create_agent_request_requires_explicit_runtime_kind(self) -> None:
        with self.assertRaises(ValidationError):
            api_gateway_main.CreateAgentRequest(
                name="opencode-agent",
                model="gpt-4",
            )

    def test_create_agent_request_accepts_mistral_vibe_runtime_kind(self) -> None:
        request = api_gateway_main.CreateAgentRequest(
            name="vibe-agent",
            model="devstral-small",
            runtime_kind="mistral-vibe",
        )

        self.assertEqual(request.runtime_kind, "mistral-vibe")

    def test_runtime_kind_from_spec_requires_explicit_kind(self) -> None:
        with self.assertRaises(HTTPException) as context:
            api_gateway_main.runtime_kind_from_spec({"model": "gpt-4"})

        self.assertEqual(context.exception.status_code, 400)
        self.assertIn("runtime.kind must be explicitly set", str(context.exception.detail))

    def test_agent_detail_from_resource_exposes_opencode_config_files(self) -> None:
        detail = api_gateway_main.agent_detail_from_resource(
            {
                "metadata": {
                    "name": "opencode-agent",
                    "namespace": "default",
                    "creationTimestamp": "2026-03-11T00:00:00Z",
                },
                "spec": {
                    "model": "gpt-4",
                    "systemPrompt": "stay precise",
                    "runtime": {
                        "kind": "opencode",
                        "opencode": {"configFiles": {"opencode.json": {"default_agent": "build"}}},
                    },
                },
            }
        )

        self.assertEqual(detail.opencode_config_files, {"opencode.json": {"default_agent": "build"}})

    def test_agent_detail_from_resource_exposes_a2a_config(self) -> None:
        detail = api_gateway_main.agent_detail_from_resource(
            {
                "metadata": {
                    "name": "opencode-agent",
                    "namespace": "default",
                    "creationTimestamp": "2026-03-11T00:00:00Z",
                },
                "spec": {
                    "model": "gpt-4",
                    "a2a": {"allowedCallers": [{"name": "research-agent", "namespace": "team-a"}]},
                    "runtime": {"kind": "opencode"},
                },
            }
        )

        self.assertEqual(
            detail.a2a_config,
            {"allowedCallers": [{"name": "research-agent", "namespace": "team-a"}]},
        )

    def test_agent_detail_from_resource_exposes_structured_mcp_connections(self) -> None:
        detail = api_gateway_main.agent_detail_from_resource(
            {
                "metadata": {
                    "name": "opencode-agent",
                    "namespace": "default",
                    "creationTimestamp": "2026-03-11T00:00:00Z",
                },
                "spec": {
                    "model": "gpt-4",
                    "runtime": {"kind": "opencode"},
                    "mcpConnections": [
                        {
                            "connectionId": "conn-docs",
                            "name": "Docs Remote",
                            "slug": "docs-remote",
                            "serverId": "docs",
                            "transport": "remote",
                            "source": "saved",
                            "runtime": {
                                "kind": "remote",
                                "configKey": "docs-remote",
                                "url": "https://docs.example.com/mcp",
                                "headers": [],
                            },
                        }
                    ],
                },
            }
        )

        self.assertEqual(detail.mcp_connections[0]["connectionId"], "conn-docs")
        self.assertEqual(detail.mcp_servers, ["docs"])
        self.assertEqual(detail.mcp_sidecars, [])

    def test_agent_detail_from_resource_exposes_skill_summaries(self) -> None:
        detail = api_gateway_main.agent_detail_from_resource(
            {
                "metadata": {
                    "name": "opencode-agent",
                    "namespace": "default",
                    "creationTimestamp": "2026-03-11T00:00:00Z",
                },
                "spec": {
                    "model": "gpt-4",
                    "runtime": {"kind": "opencode"},
                    "skills": {
                        "files": {
                            "skills/research/SKILL.md": (
                                "---\n"
                                "name: research\n"
                                "description: Gather evidence carefully.\n"
                                "allowedSandboxTools:\n"
                                "  - sandbox.filesystem.read\n"
                                "allowedA2ATargets:\n"
                                "  - name: analysis-agent\n"
                                "    namespace: team-b\n"
                                "allowSubagents: true\n"
                                "---\n"
                                "Read source material before answering.\n"
                            )
                        }
                    },
                },
            }
        )

        self.assertEqual(set(detail.skills["files"].keys()), {"skills/research/SKILL.md"})
        self.assertEqual(len(detail.skill_summaries), 1)
        self.assertEqual(detail.skill_summaries[0]["name"], "research")
        self.assertEqual(detail.skill_summaries[0]["allowed_sandbox_tools"], ["sandbox.filesystem.read"])
        self.assertEqual(
            detail.skill_summaries[0]["allowed_a2a_targets"],
            [{"name": "analysis-agent", "namespace": "team-b"}],
        )
        self.assertTrue(detail.skill_summaries[0]["allow_subagents"])


class GatewayToolCatalogTests(unittest.TestCase):
    def setUp(self) -> None:
        _bind_gateway_module(self, api_gateway_auth)
        self._original_sidecar_catalog_cache = api_gateway_main._MCP_SIDECAR_CATALOG_CACHE
        api_gateway_main._MCP_SIDECAR_CATALOG_CACHE = None

    def tearDown(self) -> None:
        api_gateway_main._MCP_SIDECAR_CATALOG_CACHE = self._original_sidecar_catalog_cache

    def test_catalog_image_resolution_uses_fully_qualified_image(self) -> None:
        with patch.dict(
            api_gateway_main.os.environ,
            {
                "MCP_SIDECAR_CATALOG_JSON": json.dumps(
                    {"codeExec": {"image": "docker.io/kubesynapse/mcp-code-exec:v2", "port": 8090}}
                )
            },
            clear=False,
        ):
            api_gateway_main._MCP_SIDECAR_CATALOG_CACHE = None
            self.assertEqual(
                api_gateway_main._resolve_sidecar_image("code-exec"),
                "docker.io/kubesynapse/mcp-code-exec:v2",
            )

    def test_tool_categories_prefer_catalog_port_over_default_port(self) -> None:
        with patch.dict(
            api_gateway_main.os.environ,
            {
                "MCP_SIDECAR_CATALOG_JSON": json.dumps(
                    {"codeExec": {"image": "docker.io/kubesynapse/mcp-code-exec:v2", "port": 9012}}
                )
            },
            clear=False,
        ):
            api_gateway_main._MCP_SIDECAR_CATALOG_CACHE = None
            categories = api_gateway_main.get_tool_categories(user=None)

        code_exec = next(tool for tool in categories if tool["id"] == "code-exec")
        self.assertEqual(code_exec["default_port"], 9012)
        self.assertEqual(code_exec["sidecar_image"], "docker.io/kubesynapse/mcp-code-exec:v2")

    def test_tool_categories_fallback_to_default_port_when_catalog_port_missing_or_invalid(self) -> None:
        test_cases = [
            {"name": "missing", "catalog": {"codeExec": {"image": "docker.io/kubesynapse/mcp-code-exec:v2"}}},
            {
                "name": "invalid",
                "catalog": {"codeExec": {"image": "docker.io/kubesynapse/mcp-code-exec:v2", "port": "invalid"}},
            },
        ]

        for test_case in test_cases:
            with (
                self.subTest(name=test_case["name"]),
                patch.dict(
                    api_gateway_main.os.environ,
                    {"MCP_SIDECAR_CATALOG_JSON": json.dumps(test_case["catalog"])},
                    clear=False,
                ),
            ):
                api_gateway_main._MCP_SIDECAR_CATALOG_CACHE = None
                categories = api_gateway_main.get_tool_categories(user=None)

            code_exec = next(tool for tool in categories if tool["id"] == "code-exec")
            self.assertEqual(code_exec["default_port"], 8090)
            self.assertEqual(code_exec["sidecar_image"], "docker.io/kubesynapse/mcp-code-exec:v2")


class GatewayAgentDiscoveryTests(unittest.TestCase):
    def test_discover_agent_peers_reports_reachable_and_blocked_targets(self) -> None:
        caller_agent = {
            "metadata": {"name": "planner", "namespace": "default"},
            "spec": {
                "model": "gpt-4",
                "policyRef": "planner-policy",
                "runtime": {"kind": "opencode"},
            },
        }
        policy = {
            "spec": {
                "a2a": {
                    "allowedTargets": [
                        {"name": "researcher", "namespace": "team-b"},
                        {"name": "reviewer", "namespace": "team-b"},
                        {"name": "missing", "namespace": "team-c"},
                    ]
                }
            }
        }
        researcher_agent = {
            "metadata": {"name": "researcher", "namespace": "team-b"},
            "spec": {
                "model": "gpt-4o",
                "runtime": {"kind": "opencode"},
                "a2a": {"allowedCallers": [{"name": "planner", "namespace": "default"}]},
            },
        }
        reviewer_agent = {
            "metadata": {"name": "reviewer", "namespace": "team-b"},
            "spec": {
                "model": "gpt-4o-mini",
                "runtime": {"kind": "opencode"},
                "a2a": {"allowedCallers": [{"name": "someone-else", "namespace": "default"}]},
            },
        }

        def fake_read_agent(name: str, namespace: str) -> dict[str, object]:
            if (namespace, name) == ("default", "planner"):
                return caller_agent
            if (namespace, name) == ("team-b", "researcher"):
                return researcher_agent
            if (namespace, name) == ("team-b", "reviewer"):
                return reviewer_agent
            raise HTTPException(status_code=404, detail=f"Agent '{name}' not found")

        def fake_get_agent_status(name: str, namespace: str) -> str:
            if (namespace, name) == ("team-b", "researcher"):
                return "running"
            if (namespace, name) == ("team-b", "reviewer"):
                return "running"
            return "unknown"

        with (
            patch.object(api_gateway_main, "read_agent", side_effect=fake_read_agent),
            patch.object(
                api_gateway_main,
                "read_custom_resource",
                return_value=policy,
            ),
            patch.object(api_gateway_main, "get_agent_status", side_effect=fake_get_agent_status),
        ):
            response = api_gateway_main.discover_agent_peers("planner", "default")

        self.assertEqual(response.agent_name, "planner")
        self.assertEqual(response.policy_ref, "planner-policy")
        self.assertEqual(len(response.peers), 3)
        self.assertTrue(response.peers[0].reachable)
        self.assertEqual(response.peers[0].name, "researcher")
        self.assertEqual(response.peers[0].runtime_kind, "opencode")
        self.assertFalse(response.peers[1].reachable)
        self.assertFalse(response.peers[1].accepts_caller)
        self.assertIn("allowedCallers", response.peers[1].reason or "")
        self.assertFalse(response.peers[2].exists)
        self.assertEqual(response.peers[2].reason, "Target agent does not exist.")

    def test_discover_agent_peers_marks_non_running_target_unreachable(self) -> None:
        caller_agent = {
            "metadata": {"name": "planner", "namespace": "default"},
            "spec": {
                "model": "gpt-4",
                "policyRef": "planner-policy",
                "runtime": {"kind": "opencode"},
            },
        }
        policy = {
            "spec": {
                "a2a": {
                    "allowedTargets": [
                        {"name": "researcher", "namespace": "team-b"},
                    ]
                }
            }
        }
        researcher_agent = {
            "metadata": {"name": "researcher", "namespace": "team-b"},
            "spec": {
                "model": "gpt-4o",
                "runtime": {"kind": "opencode"},
                "a2a": {"allowedCallers": [{"name": "planner", "namespace": "default"}]},
            },
        }

        def fake_read_agent(name: str, namespace: str) -> dict[str, object]:
            if (namespace, name) == ("default", "planner"):
                return caller_agent
            if (namespace, name) == ("team-b", "researcher"):
                return researcher_agent
            raise HTTPException(status_code=404, detail=f"Agent '{name}' not found")

        with (
            patch.object(api_gateway_main, "read_agent", side_effect=fake_read_agent),
            patch.object(
                api_gateway_main,
                "read_custom_resource",
                return_value=policy,
            ),
            patch.object(api_gateway_main, "get_agent_status", return_value="pending"),
        ):
            response = api_gateway_main.discover_agent_peers("planner", "default")

        self.assertFalse(response.peers[0].reachable)
        self.assertEqual(response.peers[0].status, "pending")
        self.assertIn("status is 'pending'", response.peers[0].reason or "")


class GatewayA2AProtocolTests(unittest.TestCase):
    def setUp(self) -> None:
        api_gateway_main.A2A_TASK_STORE.clear()

    def tearDown(self) -> None:
        api_gateway_main.A2A_TASK_STORE.clear()

    def test_build_agent_card_exposes_jsonrpc_interface_and_skills(self) -> None:
        agent = {
            "metadata": {
                "name": "planner",
                "namespace": "default",
                "creationTimestamp": "2026-03-11T00:00:00Z",
                "generation": 7,
            },
            "spec": {
                "model": "gpt-4o",
                "systemPrompt": "Plan research tasks and delegate specialized work when needed.",
                "policyRef": "planner-policy",
                "runtime": {"kind": "opencode"},
                "mcpServers": ["github"],
            },
        }
        policy = {
            "spec": {
                "a2a": {
                    "allowedTargets": [
                        {"name": "researcher", "namespace": "team-b"},
                    ]
                }
            }
        }

        with (
            patch.object(api_gateway_main, "read_agent", return_value=agent),
            patch.object(
                api_gateway_main,
                "get_agent_status",
                return_value="running",
            ),
            patch.object(api_gateway_main, "read_custom_resource", return_value=policy),
        ):
            card = api_gateway_main.build_agent_card(
                "planner",
                "default",
                types.SimpleNamespace(base_url="http://gateway.local/"),
            )

        self.assertEqual(card["name"], "planner")
        self.assertNotIn("url", card)
        self.assertNotIn("protocolVersion", card)
        self.assertNotIn("preferredTransport", card)
        self.assertEqual(card["supportedInterfaces"][0]["url"], "http://gateway.local/a2a/planner?namespace=default")
        self.assertEqual(card["supportedInterfaces"][0]["protocolBinding"], "JSONRPC")
        self.assertEqual(card["supportedInterfaces"][0]["protocolVersion"], api_gateway_main.A2A_PROTOCOL_VERSION)
        self.assertEqual(card["supportedInterfaces"][0]["tenant"], "default")
        self.assertTrue(card["capabilities"]["streaming"])
        self.assertFalse(card["capabilities"]["pushNotifications"])
        self.assertEqual(card["version"], "1.0.7")
        self.assertTrue(any(skill["id"] == "peer-delegation" for skill in card["skills"]))
        self.assertTrue(any(skill["id"] == "mcp-github" for skill in card["skills"]))


class GatewayA2AProtocolAsyncTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        api_gateway_main.A2A_TASK_STORE.clear()

    def tearDown(self) -> None:
        api_gateway_main.A2A_TASK_STORE.clear()

    async def test_handle_a2a_send_message_returns_completed_task_and_supports_get(self) -> None:
        invoke_response = api_gateway_main.InvokeResponse(
            agent_name="planner",
            response="Delegated summary",
            thread_id="ctx-123",
            model="gpt-4o",
            status="completed",
        )

        with patch.object(api_gateway_agents, "invoke_agent", AsyncMock(return_value=invoke_response)) as mock_invoke:
            response = await api_gateway_main.handle_a2a_send_message(
                "planner",
                "default",
                {
                    "message": {
                        "messageId": "msg-1",
                        "role": "ROLE_USER",
                        "parts": [{"text": "Summarize the research"}],
                    },
                    "metadata": {
                        "KubeSynapseInvoke": {
                            "threadId": "peer-thread-1",
                            "system": "Return only the final answer.",
                            "model": "gpt-4.1",
                            "callerAgentName": "orchestrator",
                            "callerAgentNamespace": "team-a",
                            "parentThreadId": "root-thread",
                            "callerRequestId": "caller-req-9",
                            "sandboxSession": {"id": "shared-session"},
                            "teamContext": {"workflow": "incident-review"},
                        }
                    }
                },
                "req-1",
                "gateway-req-1",
            )

        forwarded_request = mock_invoke.await_args.args[1]
        self.assertEqual(forwarded_request.thread_id, "peer-thread-1")
        self.assertEqual(forwarded_request.system, "Return only the final answer.")
        self.assertEqual(forwarded_request.model, "gpt-4.1")
        self.assertEqual(forwarded_request.caller_agent_name, "orchestrator")
        self.assertEqual(forwarded_request.caller_agent_namespace, "team-a")
        self.assertEqual(forwarded_request.parent_thread_id, "root-thread")
        self.assertEqual(forwarded_request.caller_request_id, "caller-req-9")
        self.assertEqual(forwarded_request.sandbox_session, {"id": "shared-session"})
        self.assertEqual(forwarded_request.team_context["workflow"], "incident-review")
        self.assertEqual(forwarded_request.team_context["mode"], "a2a-jsonrpc")

        task = response["result"]["task"]
        self.assertNotIn("kind", task)
        self.assertEqual(task["status"]["state"], "TASK_STATE_COMPLETED")
        self.assertNotIn("kind", task["history"][0])
        self.assertNotIn("kind", task["history"][0]["parts"][0])
        self.assertEqual(task["artifacts"][0]["parts"][0]["text"], "Delegated summary")
        self.assertNotIn("kind", task["artifacts"][0])
        self.assertNotIn("kind", task["artifacts"][0]["parts"][0])
        self.assertEqual(len(task["history"]), 2)

        get_response = api_gateway_main.handle_a2a_get_task(
            "planner",
            "default",
            {"id": task["id"], "historyLength": 1},
            "req-2",
        )

        fetched_task = get_response["result"]["task"]
        self.assertEqual(fetched_task["status"]["state"], "TASK_STATE_COMPLETED")
        self.assertEqual(len(fetched_task["history"]), 1)
        self.assertEqual(fetched_task["artifacts"][0]["parts"][0]["text"], "Delegated summary")

    async def test_handle_a2a_stream_message_translates_runtime_events(self) -> None:
        async def upstream_events():
            yield 'event: response.delta\ndata: {"delta": "Hel"}\n\n'
            yield 'event: response.delta\ndata: {"delta": "lo"}\n\n'
            yield 'event: response.completed\ndata: {"status": "completed", "policy_name": "strict-enterprise-policy"}\n\n'

        async def fake_invoke_agent_stream(*_args, **_kwargs):
            return api_gateway_main.StreamingResponse(upstream_events(), media_type="text/event-stream")

        with patch.object(api_gateway_agents, "invoke_agent_stream", side_effect=fake_invoke_agent_stream):
            response = await api_gateway_main.handle_a2a_stream_message(
                "planner",
                "default",
                {
                    "message": {
                        "messageId": "msg-stream-1",
                        "role": "ROLE_USER",
                        "parts": [{"text": "Say hello"}],
                    }
                },
                "req-stream-1",
                "gateway-stream-1",
            )
            chunks: list[str] = []
            async for chunk in response.body_iterator:
                chunks.append(chunk if isinstance(chunk, str) else chunk.decode("utf-8"))

        payload = "".join(chunks)
        self.assertIn('"artifactUpdate"', payload)
        self.assertIn('"statusUpdate"', payload)
        self.assertNotIn('"kind": "artifact-update"', payload)
        self.assertNotIn('"kind": "status-update"', payload)
        self.assertIn("TASK_STATE_COMPLETED", payload)

        stored_record = next(iter(api_gateway_main.A2A_TASK_STORE.values()))
        task_id = stored_record["task"]["id"]
        get_response = api_gateway_main.handle_a2a_get_task(
            "planner",
            "default",
            {"id": task_id},
            "req-stream-2",
        )
        fetched_task = get_response["result"]["task"]
        self.assertEqual(fetched_task["artifacts"][0]["parts"][0]["text"], "Hello")
        self.assertEqual(fetched_task["metadata"]["policyName"], "strict-enterprise-policy")

    async def test_a2a_jsonrpc_accepts_langsmith_method_names(self) -> None:
        raw_request = types.SimpleNamespace(
            headers={},
            query_params={},
            base_url="http://gateway.local/",
            json=AsyncMock(
                return_value={
                    "jsonrpc": "2.0",
                    "id": "rpc-1",
                    "method": "message/send",
                    "params": {
                        "message": {
                            "messageId": "msg-1",
                            "role": "ROLE_USER",
                            "parts": [{"text": "Hello"}],
                        }
                    },
                }
            ),
        )

        with (
            patch.object(api_gateway_a2a, "ensure_namespace_access"),
            patch.object(
                api_gateway_a2a,
                "handle_a2a_send_message",
                AsyncMock(return_value={"jsonrpc": "2.0", "id": "rpc-1", "result": {"task": {"id": "task-1"}}}),
            ),
        ):
            response = await api_gateway_a2a.a2a_jsonrpc("planner", raw_request, namespace="default", user={})

        payload = json.loads(response.body)
        self.assertEqual(payload["id"], "rpc-1")
        self.assertEqual(payload["result"]["task"]["id"], "task-1")


class AgentReadCacheTests(unittest.TestCase):
    def tearDown(self) -> None:
        api_gateway_main.invalidate_agent_read_cache()

    def test_read_agent_cached_reuses_recent_result(self) -> None:
        api_gateway_main.invalidate_agent_read_cache()
        with (
            patch.object(api_gateway_main, "AGENT_READ_CACHE_TTL_SECONDS", 2.0),
            patch.object(
                api_gateway_main,
                "read_agent",
                side_effect=[{"spec": {"model": "gpt-4", "runtime": {"kind": "opencode"}}}],
            ) as read_agent,
        ):
            first = api_gateway_main.read_agent_cached("demo", "default")
            first["spec"]["model"] = "mutated"
            second = api_gateway_main.read_agent_cached("demo", "default")

        self.assertEqual(read_agent.call_count, 1)
        self.assertEqual(second["spec"]["model"], "gpt-4")

    def test_invalidate_agent_read_cache_evicts_matching_entry(self) -> None:
        api_gateway_main.invalidate_agent_read_cache()
        with (
            patch.object(api_gateway_main, "AGENT_READ_CACHE_TTL_SECONDS", 2.0),
            patch.object(
                api_gateway_main,
                "read_agent",
                side_effect=[
                    {"spec": {"model": "gpt-4", "runtime": {"kind": "opencode"}}},
                    {"spec": {"model": "gpt-4.1", "runtime": {"kind": "opencode"}}},
                ],
            ) as read_agent,
        ):
            first = api_gateway_main.read_agent_cached("demo", "default")
            api_gateway_main.invalidate_agent_read_cache(agent_name="demo", namespace="default")
            second = api_gateway_main.read_agent_cached("demo", "default")

        self.assertEqual(read_agent.call_count, 2)
        self.assertEqual(first["spec"]["model"], "gpt-4")
        self.assertEqual(second["spec"]["model"], "gpt-4.1")


class AgentManifestRouteTests(unittest.TestCase):
    def test_get_agent_manifest_reads_aiagent_crd_plural(self) -> None:
        manifest = {
            "apiVersion": "synapse.kubesynapse.io/v1alpha1",
            "kind": "AIAgent",
            "metadata": {"name": "standup-git", "namespace": "default"},
            "spec": {"runtime": {"kind": "opencode"}},
        }

        with (
            patch.object(api_gateway_agents, "ensure_namespace_access") as ensure_access,
            patch.object(api_gateway_agents, "read_custom_resource", return_value=manifest) as read_resource,
        ):
            response = api_gateway_agents.get_agent_manifest(
                "standup-git",
                namespace="default",
                user={"sub": "admin"},
            )

        ensure_access.assert_called_once_with({"sub": "admin"}, "default")
        read_resource.assert_called_once_with("aiagents", "standup-git", "default", "Agent")
        self.assertEqual(json.loads(response.body), manifest)


class GatewayInvokeProxyTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        _bind_gateway_module(self, api_gateway_agents)
        self.namespace_access_patcher = patch.object(api_gateway_main, "ensure_namespace_access")
        self.namespace_access_patcher.start()
        self.addCleanup(self.namespace_access_patcher.stop)

    async def test_download_agent_artifact_proxies_runtime_file_response(self) -> None:
        response = httpx.Response(
            200,
            content=b"%PDF-1.4 sample",
            headers={
                "content-type": "application/pdf",
                "content-disposition": 'attachment; filename="AZ305_summary.pdf"',
            },
        )

        class FakeAsyncClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def get(self, url, **kwargs):
                self.url = url
                self.kwargs = kwargs
                return response

        fake_client = FakeAsyncClient()

        with (
            patch.object(
                api_gateway_main.asyncio,
                "to_thread",
                return_value={"spec": {"model": "gpt-4", "runtime": {"kind": "opencode"}}},
            ) as to_thread,
            patch.object(
                api_gateway_main.httpx,
                "AsyncClient",
                return_value=fake_client,
            ),
        ):
            proxied = await api_gateway_main.download_agent_artifact(
                "demo",
                "/tmp/AZ305_summary.pdf",
                "default",
                user={},
            )

        to_thread.assert_awaited_once_with(api_gateway_main.read_agent_cached, "demo", "default")
        self.assertEqual(fake_client.kwargs["params"], {"path": "/tmp/AZ305_summary.pdf"})
        self.assertEqual(proxied.media_type, "application/pdf")
        self.assertEqual(proxied.headers.get("content-disposition"), 'attachment; filename="AZ305_summary.pdf"')
        self.assertEqual(proxied.body, b"%PDF-1.4 sample")

    async def test_list_agent_artifacts_uses_cached_agent_lookup(self) -> None:
        response = httpx.Response(
            200,
            json={
                "files": [{"path": "/workspace/notes.md", "name": "notes.md", "size": 12, "modified": 1, "directory": "/workspace"}],
                "truncated": False,
                "roots": ["/workspace"],
            },
        )

        class FakeAsyncClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def get(self, url, **kwargs):
                self.url = url
                self.kwargs = kwargs
                return response

        fake_client = FakeAsyncClient()

        with (
            patch.object(
                api_gateway_main.asyncio,
                "to_thread",
                return_value={"spec": {"model": "gpt-4", "runtime": {"kind": "opencode"}}},
            ) as to_thread,
            patch.object(
                api_gateway_main.httpx,
                "AsyncClient",
                return_value=fake_client,
            ),
        ):
            listed = await api_gateway_main.list_agent_artifacts("demo", "default", user={})

        to_thread.assert_awaited_once_with(api_gateway_main.read_agent_cached, "demo", "default")
        self.assertEqual(fake_client.kwargs["params"], {})
        self.assertEqual(listed["files"][0]["path"], "/workspace/notes.md")

    async def test_download_agent_artifacts_zip_uses_cached_agent_lookup(self) -> None:
        response = httpx.Response(
            200,
            content=b"PK\x03\x04",
            headers={
                "content-type": "application/zip",
                "content-disposition": 'attachment; filename="demo-workspace.zip"',
                "content-length": "4",
            },
        )

        class FakeAsyncClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def get(self, url, **kwargs):
                self.url = url
                self.kwargs = kwargs
                return response

        fake_client = FakeAsyncClient()

        with (
            patch.object(
                api_gateway_main.asyncio,
                "to_thread",
                return_value={"spec": {"model": "gpt-4", "runtime": {"kind": "opencode"}}},
            ) as to_thread,
            patch.object(
                api_gateway_main.httpx,
                "AsyncClient",
                return_value=fake_client,
            ),
        ):
            proxied = await api_gateway_main.download_agent_artifacts_zip("demo", "default", user={})

        to_thread.assert_awaited_once_with(api_gateway_main.read_agent_cached, "demo", "default")
        self.assertEqual(fake_client.kwargs["params"], {})
        self.assertEqual(proxied.media_type, "application/zip")
        self.assertEqual(proxied.headers.get("content-disposition"), 'attachment; filename="demo-workspace.zip"')
        self.assertEqual(proxied.body, b"PK\x03\x04")

    async def test_invoke_agent_rejects_invalid_runtime_json(self) -> None:
        request = api_gateway_main.InvokeRequest(prompt="hello")
        raw_request = types.SimpleNamespace(headers={})
        response = httpx.Response(200, text="not-json")

        class FakeAsyncClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def post(self, *args, **kwargs):
                return response

        with (
            patch.object(
                api_gateway_main.asyncio,
                "to_thread",
                return_value={"spec": {"model": "gpt-4", "runtime": {"kind": "opencode"}}},
            ),
            patch.object(
                api_gateway_main.httpx,
                "AsyncClient",
                return_value=FakeAsyncClient(),
            ),self.assertRaises(HTTPException) as context
        ):
            await api_gateway_main.invoke_agent("demo", request, raw_request, "default", user={})

        self.assertEqual(context.exception.status_code, 502)
        self.assertIn("invalid JSON", str(context.exception.detail))

    async def test_invoke_agent_uses_cached_agent_lookup(self) -> None:
        request = api_gateway_main.InvokeRequest(prompt="hello")
        raw_request = types.SimpleNamespace(headers={})
        response = httpx.Response(
            200,
            json={
                "response": "done",
                "thread_id": "thread-1",
                "model": "gpt-4",
                "status": "completed",
            },
        )
        captured: dict[str, object] = {}

        class FakeAsyncClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def post(self, *args, **kwargs):
                return response

        async def fake_to_thread(func, *args, **kwargs):
            captured["func"] = func
            return {"spec": {"model": "gpt-4", "runtime": {"kind": "opencode"}}}

        with (
            patch.object(api_gateway_main.asyncio, "to_thread", side_effect=fake_to_thread),
            patch.object(api_gateway_main.httpx, "AsyncClient", return_value=FakeAsyncClient()),
            patch.object(api_gateway_main, "list_promoted_memory_records", return_value=[]),
        ):
            await api_gateway_main.invoke_agent("demo", request, raw_request, "default", user={})

        self.assertIs(captured["func"], api_gateway_main.read_agent_cached)

    async def test_invoke_agent_records_prompt_text_in_trace(self) -> None:
        request = api_gateway_main.InvokeRequest(prompt="Optimize workflow ROI")
        raw_request = types.SimpleNamespace(headers={"x-request-id": "req-opt-trace"})
        response = httpx.Response(
            200,
            json={
                "response": "done",
                "thread_id": "thread-1",
                "model": "gpt-4",
                "status": "completed",
            },
        )

        class FakeAsyncClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def post(self, *args, **kwargs):
                return response

        with (
            patch.object(
                api_gateway_main.asyncio,
                "to_thread",
                return_value={"spec": {"model": "gpt-4", "runtime": {"kind": "opencode"}}},
            ),
            patch.object(api_gateway_main.httpx, "AsyncClient", return_value=FakeAsyncClient()),
            patch.object(api_gateway_main, "list_promoted_memory_records", return_value=[]),
            patch.object(api_gateway_main, "record_usage"),
            patch.object(api_gateway_main, "record_runtime_memory"),
            patch.object(api_gateway_main, "_record_invoke_trace") as record_invoke_trace,
        ):
            await api_gateway_main.invoke_agent("demo", request, raw_request, "default", user={"sub": "alice"})

        record_invoke_trace.assert_called_once()
        self.assertEqual(record_invoke_trace.call_args.kwargs["prompt_text"], "Optimize workflow ROI")

    async def test_invoke_agent_returns_a2a_metadata(self) -> None:
        request = api_gateway_main.InvokeRequest(
            prompt="hello",
            a2a_target_agent="analysis-agent",
            a2a_target_namespace="team-b",
        )
        raw_request = types.SimpleNamespace(headers={})
        response = httpx.Response(
            200,
            json={
                "response": "done",
                "thread_id": "caller-thread",
                "model": "gpt-4",
                "status": "completed",
                "a2a": {
                    "targetAgent": "analysis-agent",
                    "targetNamespace": "team-b",
                    "targetThreadId": "callee-thread",
                    "responseStatus": "completed",
                },
            },
        )

        class FakeAsyncClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def post(self, *args, **kwargs):
                return response

        with (
            patch.object(
                api_gateway_main.asyncio,
                "to_thread",
                return_value={"spec": {"model": "gpt-4", "runtime": {"kind": "opencode"}}},
            ),
            patch.object(api_gateway_main.httpx, "AsyncClient", return_value=FakeAsyncClient()),
        ):
            invoke_response = await api_gateway_main.invoke_agent("demo", request, raw_request, "default", user={})

        self.assertEqual(invoke_response.a2a["targetAgent"], "analysis-agent")
        self.assertEqual(invoke_response.a2a["targetThreadId"], "callee-thread")

    async def test_invoke_agent_forwards_team_context_and_caller_metadata(self) -> None:
        request = api_gateway_main.InvokeRequest(
            prompt="Investigate the incident",
            caller_agent_name="planner",
            caller_agent_namespace="team-a",
            parent_thread_id="thread-parent",
            caller_request_id="req-123",
            team_context={"objective": "Produce a reusable incident summary."},
        )
        raw_request = types.SimpleNamespace(headers={})
        captured: dict[str, object] = {}
        response = httpx.Response(
            200,
            json={
                "response": "done",
                "thread_id": "thread-1",
                "model": "gpt-4",
                "status": "completed",
            },
        )

        class FakeAsyncClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def post(self, url, **kwargs):
                captured["url"] = url
                captured["json"] = kwargs.get("json")
                return response

        with (
            patch.object(
                api_gateway_main.asyncio,
                "to_thread",
                return_value={"spec": {"model": "gpt-4", "runtime": {"kind": "opencode"}}},
            ),
            patch.object(api_gateway_main.httpx, "AsyncClient", return_value=FakeAsyncClient()),
        ):
            await api_gateway_main.invoke_agent("planner", request, raw_request, "default", user={})

        forwarded = captured["json"]
        self.assertEqual(forwarded["caller_agent_name"], "planner")
        self.assertEqual(forwarded["caller_agent_namespace"], "team-a")
        self.assertEqual(forwarded["parent_thread_id"], "thread-parent")
        self.assertEqual(forwarded["caller_request_id"], "req-123")
        self.assertEqual(forwarded["team_context"]["objective"], "Produce a reusable incident summary.")

    async def test_invoke_agent_records_runtime_memory_metadata(self) -> None:
        request = api_gateway_main.InvokeRequest(prompt="Investigate the incident")
        raw_request = types.SimpleNamespace(headers={})
        response = httpx.Response(
            200,
            json={
                "response": "done",
                "thread_id": "thread-1",
                "model": "gpt-4",
                "status": "completed",
                "metadata": {
                    "memory": {
                        "episodic": [{"type": "tools", "names": ["filesystem.read"]}],
                        "procedural": [{"type": "response-summary", "text": "Summarized the incident."}],
                    }
                },
            },
        )

        class FakeAsyncClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def post(self, *args, **kwargs):
                return response

        with (
            patch.object(
                api_gateway_main.asyncio,
                "to_thread",
                return_value={"spec": {"model": "gpt-4", "runtime": {"kind": "opencode"}}},
            ),
            patch.object(api_gateway_main.httpx, "AsyncClient", return_value=FakeAsyncClient()),
            patch.object(api_gateway_main, "record_runtime_memory") as record_runtime_memory,
        ):
            await api_gateway_main.invoke_agent("planner", request, raw_request, "default", user={"sub": "alice"})

        record_runtime_memory.assert_called_once()
        self.assertEqual(record_runtime_memory.call_args.kwargs["session_id"], "thread-1")

    async def test_invoke_agent_injects_promoted_memory_into_system_prompt(self) -> None:
        request = api_gateway_main.InvokeRequest(prompt="Investigate the incident")
        raw_request = types.SimpleNamespace(headers={})
        captured: dict[str, object] = {}
        response = httpx.Response(
            200,
            json={
                "response": "done",
                "thread_id": "thread-1",
                "model": "gpt-4",
                "status": "completed",
            },
        )

        class FakeAsyncClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def post(self, _url, **kwargs):
                captured["json"] = kwargs.get("json")
                return response

        with (
            patch.object(
                api_gateway_main.asyncio,
                "to_thread",
                return_value={"spec": {"model": "gpt-4", "runtime": {"kind": "opencode"}}},
            ),
            patch.object(api_gateway_main.httpx, "AsyncClient", return_value=FakeAsyncClient()),
            patch.object(
                api_gateway_main,
                "list_promoted_memory_records",
                return_value=[{"topic": "response-summary", "content": "Use the repo root Make targets first."}],
            ),
        ):
            await api_gateway_main.invoke_agent("planner", request, raw_request, "default", user={"sub": "alice"})

        forwarded = captured["json"]
        self.assertIn("persistent memory", forwarded["system"])
        self.assertIn("Use the repo root Make targets first.", forwarded["system"])

    def test_build_invoke_execution_id_prefers_request_id(self) -> None:
        expected = api_gateway_agents._build_invoke_execution_id(
            thread_id="thread-1",
            request_id="req-direct-1",
        )

        self.assertEqual(
            expected,
            api_gateway_agents._build_invoke_execution_id(
                thread_id="thread-1",
                request_id="req-direct-1",
            ),
        )
        self.assertNotEqual(expected, api_gateway_agents._build_invoke_execution_id(thread_id="thread-1"))

    async def test_invoke_agent_injects_collaboration_context_into_system_prompt(self) -> None:
        request = api_gateway_main.InvokeRequest(prompt="Who can I collaborate with?")
        raw_request = types.SimpleNamespace(headers={})
        captured: dict[str, object] = {}
        response = httpx.Response(
            200,
            json={
                "response": "done",
                "thread_id": "thread-1",
                "model": "gpt-4",
                "status": "completed",
            },
        )

        class FakeAsyncClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def post(self, _url, **kwargs):
                captured["json"] = kwargs.get("json")
                return response

        agent_resource = {
            "spec": {
                "model": "gpt-4",
                "runtime": {"kind": "opencode"},
                "a2a": {
                    "allowedCallers": [
                        {"name": "reviewer", "namespace": "default"},
                        {"name": "researcher", "namespace": "default"},
                    ]
                },
            }
        }

        with (
            patch.object(api_gateway_main.asyncio, "to_thread", return_value=agent_resource),
            patch.object(api_gateway_main.httpx, "AsyncClient", return_value=FakeAsyncClient()),
        ):
            await api_gateway_main.invoke_agent("planner", request, raw_request, "default", user={"sub": "alice"})

        forwarded = captured["json"]
        self.assertIn("COLLABORATION CONTEXT:", forwarded["system"])
        self.assertIn("default/reviewer", forwarded["system"])
        self.assertIn("default/researcher", forwarded["system"])
        self.assertIn("outbound policy targets): none", forwarded["system"])
        self.assertIn("OpenCode supports explicit outbound A2A through the internal API gateway", forwarded["system"])
        self.assertIn("callerAgentName='planner'", forwarded["system"])
        self.assertIn("put only the agent name in the /a2a/<agent> path", forwarded["system"])
        self.assertIn("/a2a/peer-agent?namespace=default", forwarded["system"])
        self.assertIn("SendMessage", forwarded["system"])
        self.assertIn("metadata.KubeSynapseInvoke.threadId", forwarded["system"])

    async def test_invoke_agent_with_namespace_path_alias_uses_canonical_handler(self) -> None:
        request = api_gateway_main.InvokeRequest(prompt="Who are you?")
        raw_request = types.SimpleNamespace(headers={})
        expected = api_gateway_main.InvokeResponse(
            agent_name="analysis-agent",
            response="done",
            thread_id="thread-1",
            model="gpt-4",
            status="completed",
        )

        with patch.object(api_gateway_main, "invoke_agent", AsyncMock(return_value=expected)) as invoke_agent:
            result = await api_gateway_main.invoke_agent_with_namespace_path(
                "default",
                "analysis-agent",
                request,
                raw_request,
                namespace="default",
                user={"sub": "alice"},
            )

        invoke_agent.assert_awaited_once_with(
            "analysis-agent",
            request,
            raw_request,
            "default",
            {"sub": "alice"},
        )
        self.assertIs(result, expected)

    async def test_invoke_agent_stream_emits_response_error_event_for_upstream_failure(self) -> None:
        request = api_gateway_main.InvokeRequest(prompt="hello")
        raw_request = types.SimpleNamespace(headers={})
        error_response = httpx.Response(503, text=json.dumps({"detail": "runtime cold start"}))

        class FakeStreamContext:
            async def __aenter__(self):
                return error_response

            async def __aexit__(self, exc_type, exc, tb):
                return False

        class FakeAsyncClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            def stream(self, *args, **kwargs):
                return FakeStreamContext()

        with (
            patch.object(
                api_gateway_main.asyncio,
                "to_thread",
                return_value={"spec": {"model": "gpt-4", "runtime": {"kind": "opencode"}}},
            ),
            patch.object(
                api_gateway_main.httpx,
                "AsyncClient",
                return_value=FakeAsyncClient(),
            ),
        ):
            response = await api_gateway_main.invoke_agent_stream("demo", request, raw_request, "default", user={})
            chunks: list[str] = []
            async for chunk in response.body_iterator:
                chunks.append(chunk)

        payload = "".join(chunks)
        self.assertIn("event: response.error", payload)
        self.assertIn("runtime cold start", payload)

    async def test_invoke_agent_stream_emits_keepalive_for_idle_upstream(self) -> None:
        request = api_gateway_main.InvokeRequest(prompt="hello")
        raw_request = types.SimpleNamespace(headers={})

        class FakeStreamResponse:
            status_code = 200

            async def aread(self) -> bytes:
                return b""

            async def aiter_text(self):
                await asyncio.sleep(0.02)
                yield 'event: response.completed\ndata: {"thread_id": "t-1", "status": "completed"}\n\n'

        class FakeStreamContext:
            async def __aenter__(self):
                return FakeStreamResponse()

            async def __aexit__(self, exc_type, exc, tb):
                return False

        class FakeAsyncClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            def stream(self, *args, **kwargs):
                return FakeStreamContext()

        with (
            patch.object(
                api_gateway_main.asyncio,
                "to_thread",
                return_value={"spec": {"model": "gpt-4", "runtime": {"kind": "opencode"}}},
            ),
            patch.object(
                api_gateway_main.httpx,
                "AsyncClient",
                return_value=FakeAsyncClient(),
            ),
            patch.object(api_gateway_main, "STREAM_KEEPALIVE_SECONDS", 0.01),
        ):
            response = await api_gateway_main.invoke_agent_stream("demo", request, raw_request, "default", user={})
            chunks: list[str] = []
            async for chunk in response.body_iterator:
                chunks.append(chunk)

        payload = "".join(chunks)
        self.assertIn(": keepalive", payload)
        self.assertIn("event: response.completed", payload)

    async def test_invoke_agent_stream_injects_promoted_memory_into_system_prompt(self) -> None:
        request = api_gateway_main.InvokeRequest(prompt="Investigate the incident")
        raw_request = types.SimpleNamespace(headers={})
        captured: dict[str, object] = {}

        class FakeResponse:
            status_code = 200
            content = b'{"thread_id":"t-1","response":"done","model":"gpt-4","status":"completed"}'

            def json(self):
                return {
                    "thread_id": "t-1",
                    "response": "done",
                    "model": "gpt-4",
                    "status": "completed",
                }

        class FakeStreamResponse:
            status_code = 200

            async def aread(self) -> bytes:
                return b""

            async def aiter_text(self):
                yield 'event: response.completed\ndata: {"thread_id": "t-1", "status": "completed"}\n\n'

        class FakeStreamContext:
            async def __aenter__(self):
                return FakeStreamResponse()

            async def __aexit__(self, exc_type, exc, tb):
                return False

        class FakeAsyncClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def post(self, _url, **kwargs):
                captured["json"] = kwargs.get("json")
                return FakeResponse()

            def stream(self, _method, _url, **kwargs):
                captured["json"] = kwargs.get("json")
                return FakeStreamContext()

        with (
            patch.object(
                api_gateway_main.asyncio,
                "to_thread",
                return_value={"spec": {"model": "gpt-4", "runtime": {"kind": "opencode"}}},
            ),
            patch.object(api_gateway_main.httpx, "AsyncClient", return_value=FakeAsyncClient()),
            patch.object(
                api_gateway_main,
                "list_promoted_memory_records",
                return_value=[{"topic": "response-summary", "content": "Use the repo root Make targets first."}],
            ),
        ):
            response = await api_gateway_main.invoke_agent_stream("planner", request, raw_request, "default", user={"sub": "alice"})
            async for _chunk in response.body_iterator:
                pass

        forwarded = captured["json"]
        self.assertIn("persistent memory", forwarded["system"])
        self.assertIn("Use the repo root Make targets first.", forwarded["system"])

    async def test_invoke_agent_stream_records_runtime_memory_metadata(self) -> None:
        request = api_gateway_main.InvokeRequest(prompt="Investigate the incident")
        raw_request = types.SimpleNamespace(headers={})

        class FakeStreamResponse:
            status_code = 200

            async def aread(self) -> bytes:
                return b""

            async def aiter_text(self):
                yield (
                    'event: response.completed\n'
                    'data: {"thread_id": "thread-1", "model": "gpt-4", "status": "completed", '
                    '"metadata": {"memory": {"procedural": [{"type": "response-summary", "text": "Summarized the incident."}]}}}\n\n'
                )

        class FakeStreamContext:
            async def __aenter__(self):
                return FakeStreamResponse()

            async def __aexit__(self, exc_type, exc, tb):
                return False

        class FakeAsyncClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            def stream(self, *_args, **_kwargs):
                return FakeStreamContext()

        with (
            patch.object(
                api_gateway_main.asyncio,
                "to_thread",
                return_value={"spec": {"model": "gpt-4", "runtime": {"kind": "opencode"}}},
            ),
            patch.object(api_gateway_main.httpx, "AsyncClient", return_value=FakeAsyncClient()),
            patch.object(api_gateway_main, "record_usage"),
            patch.object(api_gateway_main, "record_runtime_memory") as record_runtime_memory,
        ):
            response = await api_gateway_main.invoke_agent_stream("planner", request, raw_request, "default", user={"sub": "alice"})
            async for _chunk in response.body_iterator:
                pass

        record_runtime_memory.assert_called_once()
        self.assertEqual(record_runtime_memory.call_args.kwargs["session_id"], "thread-1")

    async def test_invoke_agent_stream_falls_back_to_nonstream_runtime_when_memory_is_injected(self) -> None:
        request = api_gateway_main.InvokeRequest(prompt="What do you remember about chickens?")
        raw_request = types.SimpleNamespace(headers={})
        captured: dict[str, object] = {"post_calls": 0, "stream_calls": 0}

        class FakeResponse:
            status_code = 200
            content = b'{"thread_id":"thread-1","response":"Chickens must be black.","model":"gpt-4","status":"completed"}'

            def json(self):
                return {
                    "thread_id": "thread-1",
                    "response": "Chickens must be black.",
                    "model": "gpt-4",
                    "status": "completed",
                }

        class FakeAsyncClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def post(self, _url, **kwargs):
                captured["post_calls"] = int(captured["post_calls"]) + 1
                captured["json"] = kwargs.get("json")
                return FakeResponse()

            def stream(self, *_args, **_kwargs):
                captured["stream_calls"] = int(captured["stream_calls"]) + 1
                raise AssertionError("stream() should not be used when recalled memory is injected")

        with (
            patch.object(
                api_gateway_main.asyncio,
                "to_thread",
                return_value={"spec": {"model": "gpt-4", "runtime": {"kind": "opencode"}}},
            ),
            patch.object(api_gateway_main.httpx, "AsyncClient", return_value=FakeAsyncClient()),
            patch.object(
                api_gateway_main,
                "list_promoted_memory_records",
                return_value=[{"topic": "assistant-summary", "content": "Noted. Chickens must be black. What next?"}],
            ),
        ):
            response = await api_gateway_main.invoke_agent_stream("planner", request, raw_request, "default", user={"sub": "alice"})
            chunks: list[str] = []
            async for chunk in response.body_iterator:
                chunks.append(chunk)

        self.assertEqual(captured["post_calls"], 1)
        self.assertEqual(captured["stream_calls"], 0)
        self.assertIn("Chickens must be black.", "".join(chunks))


class LogStreamTests(unittest.TestCase):
    """Tests for the agent log endpoints including the new SSE streaming endpoint."""

    @classmethod
    def _ensure_k8s_mock(cls):
        """Ensure a mock kubernetes module exists in sys.modules for local imports."""
        if "kubernetes" not in sys.modules:
            k8s_mod = types.ModuleType("kubernetes")
            k8s_client_mod = types.ModuleType("kubernetes.client")
            k8s_watch_mod = types.ModuleType("kubernetes.watch")
            k8s_mod.client = k8s_client_mod
            k8s_mod.watch = k8s_watch_mod
            sys.modules["kubernetes"] = k8s_mod
            sys.modules["kubernetes.client"] = k8s_client_mod
            sys.modules["kubernetes.watch"] = k8s_watch_mod

    def setUp(self):
        _bind_gateway_module(self, api_gateway_agents)
        self._ensure_k8s_mock()
        from unittest.mock import MagicMock

        self._mock_core = MagicMock()
        self._core_patcher = patch.object(
            sys.modules["kubernetes.client"],
            "CoreV1Api",
            return_value=self._mock_core,
            create=True,
        )
        self._core_patcher.start()

    def tearDown(self):
        self._core_patcher.stop()

    def test_get_agent_logs_returns_pod_log_with_timestamps(self) -> None:
        fake_pod = types.SimpleNamespace(metadata=types.SimpleNamespace(name="my-pod-0"))
        fake_log_text = "2026-03-17T10:00:00Z INFO starting\n2026-03-17T10:00:01Z INFO ready"
        self._mock_core.read_namespaced_pod_log.return_value = fake_log_text

        with (
            patch.object(api_gateway_main, "verify_token", return_value={"sub": "u1", "role": "admin", "namespaces": ["*"], "capabilities": {}}),
            patch.object(api_gateway_main, "read_agent", return_value={}),
            patch.object(api_gateway_main, "list_agent_pods", return_value=[fake_pod]),
        ):
            result = api_gateway_main.get_agent_logs(
                agent_name="myagent",
                namespace="ns1",
                tail=200,
                user={"sub": "u1", "role": "admin", "namespaces": ["*"], "capabilities": {}},
            )
            self.assertEqual(result["agent_name"], "myagent")
            self.assertEqual(result["pod_name"], "my-pod-0")
            self.assertIn("starting", result["logs"])
            call_kwargs = self._mock_core.read_namespaced_pod_log.call_args
            self.assertTrue(call_kwargs.kwargs.get("timestamps", False))

    def test_get_agent_logs_clamps_tail_parameter(self) -> None:
        """Tail parameter should be clamped between 1 and 5000."""
        fake_pod = types.SimpleNamespace(metadata=types.SimpleNamespace(name="pod-0"))
        self._mock_core.read_namespaced_pod_log.return_value = ""

        with (
            patch.object(api_gateway_main, "verify_token", return_value={"sub": "u1", "role": "admin", "namespaces": ["*"], "capabilities": {}}),
            patch.object(api_gateway_main, "read_agent", return_value={}),
            patch.object(api_gateway_main, "list_agent_pods", return_value=[fake_pod]),
        ):
            api_gateway_main.get_agent_logs(
                agent_name="myagent",
                namespace="ns1",
                tail=99999,
                user={"sub": "u1", "role": "admin", "namespaces": ["*"], "capabilities": {}},
            )
            call_kwargs = self._mock_core.read_namespaced_pod_log.call_args
            self.assertEqual(call_kwargs.kwargs.get("tail_lines"), 5000)

    def test_sse_event_format(self) -> None:
        """sse_event produces valid SSE with proper termination."""
        result = api_gateway_main.sse_event("log.line", {"line": "hello world"})
        self.assertTrue(result.startswith("event: log.line\ndata: "))
        self.assertTrue(result.endswith("\n\n"))
        data_line = result.split("\n")[1]
        payload = json.loads(data_line.removeprefix("data: "))
        self.assertEqual(payload["line"], "hello world")

    def test_get_agent_logs_404_no_pods(self) -> None:
        """Should 404 when no runtime pods exist."""
        with (
            patch.object(api_gateway_main, "verify_token", return_value={"sub": "u1", "role": "admin", "namespaces": ["*"], "capabilities": {}}),
            patch.object(api_gateway_main, "read_agent", return_value={}),
            patch.object(api_gateway_main, "list_agent_pods", return_value=[]),
        ):
            with self.assertRaises(HTTPException) as ctx:
                api_gateway_main.get_agent_logs(
                    agent_name="myagent",
                    namespace="ns1",
                    user={"sub": "u1", "role": "admin", "namespaces": ["*"], "capabilities": {}},
                )
            self.assertEqual(ctx.exception.status_code, 404)


class WorkflowRetryFailedTests(unittest.TestCase):
    @classmethod
    def _ensure_k8s_mock(cls):
        if "kubernetes" not in sys.modules:
            k8s_mod = types.ModuleType("kubernetes")
            k8s_client_mod = types.ModuleType("kubernetes.client")
            k8s_mod.client = k8s_client_mod
            sys.modules["kubernetes"] = k8s_mod
            sys.modules["kubernetes.client"] = k8s_client_mod

    def setUp(self) -> None:
        from unittest.mock import MagicMock

        self._ensure_k8s_mock()
        self._mock_custom_objects = MagicMock()
        self._custom_objects_patcher = patch.object(
            sys.modules["kubernetes.client"],
            "CustomObjectsApi",
            return_value=self._mock_custom_objects,
            create=True,
        )
        self._custom_objects_patcher.start()

    def tearDown(self) -> None:
        self._custom_objects_patcher.stop()

    async def _read_stream(self, response) -> str:
        chunks: list[str] = []
        async for chunk in response.body_iterator:
            chunks.append(chunk.decode() if isinstance(chunk, bytes) else chunk)
        return "".join(chunks)

    def test_trigger_workflow_replaces_input_and_resets_status(self) -> None:
        workflow = {
            "metadata": {
                "name": "feature-pipeline",
                "namespace": "default",
                "generation": 3,
                "resourceVersion": "17",
            },
            "spec": {
                "description": "desc",
                "input": "old input",
                "steps": [{"name": "draft-blueprint", "agentRef": "planner", "prompt": "Draft it"}],
            },
            "status": {
                "phase": "failed",
                "pendingApproval": {"name": "approval-one"},
                "observedGeneration": 3,
                "runId": "wf-run-default-feature-pipeline-3-old",
                "summary": {"totalSteps": 1},
            },
        }
        updated = copy.deepcopy(workflow)
        updated["spec"]["input"] = "fresh input"
        updated["status"] = {
            "phase": "pending",
            "pendingApproval": None,
            "observedGeneration": None,
            "runId": "wf-run-default-feature-pipeline-3-new",
            "summary": {"totalSteps": 1},
        }
        self._mock_custom_objects.get_namespaced_custom_object.side_effect = [workflow, updated]
        self._mock_custom_objects.replace_namespaced_custom_object.return_value = updated

        with (
            patch.object(api_gateway_workflows, "ensure_namespace_access"),
            patch.object(api_gateway_workflows, "record_workflow_run") as record_mock,
        ):
            result = api_gateway_workflows.trigger_workflow(
                workflow_name="feature-pipeline",
                body=api_gateway_workflows.WorkflowTriggerRequest(input="fresh input"),
                namespace="default",
                user={"sub": "user-1", "namespaces": ["default"]},
            )

        replace_kwargs = self._mock_custom_objects.replace_namespaced_custom_object.call_args.kwargs
        self.assertEqual(replace_kwargs["body"]["spec"]["input"], "fresh input")
        self.assertEqual(replace_kwargs["body"]["spec"]["description"], "desc")
        patch_kwargs = self._mock_custom_objects.patch_namespaced_custom_object_status.call_args.kwargs
        self.assertEqual(
            patch_kwargs["body"],
            {
                "status": {
                    "phase": "pending",
                    "observedGeneration": None,
                    "pendingApproval": None,
                    "stepStates": None,
                    "summary": None,
                    "currentStep": "",
                    "workerJob": None,
                    "runId": None,
                    "artifactRef": None,
                    "journalRef": None,
                }
            },
        )
        record_mock.assert_called_once()
        self.assertEqual(result.input, "fresh input")
        self.assertEqual(result.phase, "pending")
        self.assertEqual(result.run_id, "wf-run-default-feature-pipeline-3-new")

    def test_cancel_workflow_clears_pending_approval(self) -> None:
        workflow = {
            "metadata": {"name": "feature-pipeline", "namespace": "default", "generation": 4},
            "spec": {
                "description": "desc",
                "input": "input",
                "steps": [{"name": "deploy-bundle", "agentRef": "deployer", "prompt": "Deploy it"}],
            },
            "status": {
                "phase": "waiting-approval",
                "pendingApproval": {"name": "approval-one", "stepName": "deploy-bundle"},
                "summary": {"totalSteps": 1},
            },
        }
        updated = copy.deepcopy(workflow)
        updated["status"]["phase"] = "cancelled"
        updated["status"]["pendingApproval"] = None
        self._mock_custom_objects.get_namespaced_custom_object.side_effect = [workflow, updated]

        with patch.object(api_gateway_workflows, "ensure_namespace_access"):
            result = api_gateway_workflows.cancel_workflow(
                workflow_name="feature-pipeline",
                namespace="default",
                user={"sub": "user-1", "namespaces": ["default"]},
            )

        patch_kwargs = self._mock_custom_objects.patch_namespaced_custom_object_status.call_args.kwargs
        self.assertEqual(patch_kwargs["body"], {"status": {"phase": "cancelled", "pendingApproval": None}})
        self.assertEqual(result.phase, "cancelled")
        self.assertIsNone(result.pending_approval)

    def test_get_workflow_next_action_recommends_retry_for_failed_steps(self) -> None:
        workflow = {
            "metadata": {"name": "feature-pipeline", "namespace": "default"},
            "spec": {},
            "status": {
                "phase": "failed",
                "stepStates": {
                    "draft": {"status": "completed"},
                    "deploy": {"status": "failed"},
                },
            },
        }

        with (
            patch.object(api_gateway_workflows, "ensure_namespace_access"),
            patch.object(api_gateway_workflows, "read_custom_resource", return_value=workflow),
        ):
            result = api_gateway_workflows.get_workflow_next_action(
                workflow_name="feature-pipeline",
                namespace="default",
                user={"sub": "user-1", "namespaces": ["default"]},
            )

        self.assertEqual(result["action"], "Retry failed steps")
        self.assertEqual(result["failedSteps"], ["deploy"])
        self.assertTrue(result["retryAvailable"])

    def test_get_workflow_next_action_recommends_approval_decision(self) -> None:
        workflow = {
            "metadata": {"name": "feature-pipeline", "namespace": "default"},
            "spec": {},
            "status": {
                "phase": "waiting-approval",
                "pendingApproval": {"stepName": "deploy-bundle"},
                "stepStates": {},
            },
        }

        with (
            patch.object(api_gateway_workflows, "ensure_namespace_access"),
            patch.object(api_gateway_workflows, "read_custom_resource", return_value=workflow),
        ):
            result = api_gateway_workflows.get_workflow_next_action(
                workflow_name="feature-pipeline",
                namespace="default",
                user={"sub": "user-1", "namespaces": ["default"]},
            )

        self.assertEqual(result["action"], "Approve or reject step 'deploy-bundle'")
        self.assertEqual(result["reason"], "Workflow is waiting for human approval.")

    def test_get_workflow_next_action_recommends_promotion_after_success(self) -> None:
        workflow = {
            "metadata": {"name": "feature-pipeline", "namespace": "default"},
            "spec": {},
            "status": {
                "phase": "completed",
                "stepStates": {"deploy": {"status": "completed"}},
            },
        }

        with (
            patch.object(api_gateway_workflows, "ensure_namespace_access"),
            patch.object(api_gateway_workflows, "read_custom_resource", return_value=workflow),
        ):
            result = api_gateway_workflows.get_workflow_next_action(
                workflow_name="feature-pipeline",
                namespace="default",
                user={"sub": "user-1", "namespaces": ["default"]},
            )

        self.assertEqual(result, {"action": "Deploy or promote", "reason": "All steps completed and verified successfully."})

    def test_stream_workflow_status_emits_status_and_done_events(self) -> None:
        workflow = {
            "metadata": {"name": "feature-pipeline", "namespace": "default"},
            "spec": {
                "description": "desc",
                "input": "input",
                "steps": [{"name": "deploy-bundle", "agentRef": "deployer", "prompt": "Deploy it"}],
            },
            "status": {
                "phase": "completed",
                "summary": {"totalSteps": 1},
                "stepStates": {"deploy-bundle": {"status": "completed"}},
            },
        }
        self._mock_custom_objects.get_namespaced_custom_object.return_value = workflow

        with (
            patch.object(api_gateway_workflows, "ensure_namespace_access"),
            patch.object(api_gateway_workflows, "_sync_workflow_run_history"),
        ):
            response = api_gateway_workflows.stream_workflow_status(
                workflow_name="feature-pipeline",
                namespace="default",
                user={"sub": "user-1", "namespaces": ["default"]},
            )
            payload = asyncio.run(self._read_stream(response))

        self.assertIn("event: status", payload)
        self.assertIn('"phase": "completed"', payload)
        self.assertIn("event: done", payload)

    def test_stream_workflow_logs_emits_started_line_and_stopped_events(self) -> None:
        class FakeRequest:
            async def is_disconnected(self) -> bool:
                return False

        class FakeWatch:
            def __init__(self):
                self.stopped = False

            def stream(self, *_args, **_kwargs):
                return iter([
                    "2026-04-07T00:00:00Z INFO starting",
                    "2026-04-07T00:00:01Z INFO ready",
                ])

            def stop(self):
                self.stopped = True

        fake_watch = FakeWatch()
        fake_pod = types.SimpleNamespace(metadata=types.SimpleNamespace(name="workflow-pod-0"))
        sys.modules["kubernetes"].watch = types.SimpleNamespace(Watch=lambda: fake_watch)

        with (
            patch.object(api_gateway_workflows, "ensure_namespace_access"),
            patch.object(
                api_gateway_workflows,
                "read_custom_resource",
                return_value={"status": {"workerJob": {"name": "worker-job", "namespace": "default"}}},
            ),
            patch.object(api_gateway_workflows, "list_job_pods", return_value=[fake_pod]),
            patch.object(
                sys.modules["kubernetes.client"],
                "CoreV1Api",
                return_value=types.SimpleNamespace(read_namespaced_pod_log=lambda **_kwargs: None),
                create=True,
            ),
        ):
            response = asyncio.run(
                api_gateway_workflows.stream_workflow_logs(
                    workflow_name="feature-pipeline",
                    request=FakeRequest(),
                    namespace="default",
                    user={"sub": "user-1", "role": "admin", "namespaces": ["*"], "capabilities": {}},
                )
            )
            payload = asyncio.run(self._read_stream(response))

        self.assertIn("event: log.started", payload)
        self.assertIn("event: log.line", payload)
        self.assertIn("event: log.stopped", payload)
        self.assertTrue(fake_watch.stopped)

    def test_get_workflow_run_trace_endpoint_returns_archived_snapshot(self) -> None:
        trace_row = {
            "workflow_name": "feature-pipeline",
            "namespace": "default",
            "history_id": 17,
            "run_id": "run-archived-1",
            "generation": 4,
            "phase": "failed",
            "spec": {
                "description": "Deploy feature pipeline",
                "input": "Ship the validated bundle",
                "steps": [{"name": "deploy-bundle", "agentRef": "deployer", "prompt": "Deploy it"}],
            },
            "status": {
                "phase": "failed",
                "runId": "run-archived-1",
                "summary": {"totalSteps": 1, "failedSteps": 1},
                "stepStates": {
                    "deploy-bundle": {"stepName": "deploy-bundle", "agentRef": "deployer", "status": "failed"}
                },
            },
            "summary": {"totalSteps": 1, "failedSteps": 1},
            "step_states": {
                "deploy-bundle": {"stepName": "deploy-bundle", "agentRef": "deployer", "status": "failed"}
            },
            "artifact_path": "/artifacts/feature-pipeline/run-archived-1",
            "journal_path": "/artifacts/feature-pipeline/run-archived-1/journal.ndjson",
            "worker_job_name": "worker-job-archived-1",
            "pending_approval_name": None,
            "triggered_by": "alice",
            "input_text": "Ship the validated bundle",
            "created_at": "2026-04-09T10:00:00+00:00",
            "updated_at": "2026-04-09T10:03:00+00:00",
            "completed_at": "2026-04-09T10:03:00+00:00",
            "archived_log_available": True,
            "archived_log_source": "operator-terminal-archive",
            "archived_log_truncated": False,
            "archived_log_captured_at": "2026-04-09T10:03:01+00:00",
            "logs": "2026-04-09T10:00:00Z INFO start\n2026-04-09T10:03:00Z ERROR failed",
        }

        with (
            patch.object(api_gateway_workflows, "ensure_namespace_access"),
            patch.object(api_gateway_main, "load_workflow_run_trace", return_value=trace_row),
        ):
            payload = api_gateway_workflows.get_workflow_run_trace_endpoint(
                workflow_name="feature-pipeline",
                run_id="run-archived-1",
                namespace="default",
                user={"sub": "user-1", "namespaces": ["default"]},
            )

        self.assertEqual(payload["source"], "archived")
        self.assertEqual(payload["workflow"]["name"], "feature-pipeline")
        self.assertEqual(payload["workflow"]["run_id"], "run-archived-1")
        self.assertIn("ERROR failed", payload["logs"])

    def test_resolve_workflow_run_trace_payload_captures_live_fallback_logs(self) -> None:
        trace_row = {
            "workflow_name": "feature-pipeline",
            "namespace": "default",
            "history_id": 18,
            "run_id": "run-live-fallback-1",
            "generation": 5,
            "phase": "completed",
            "spec": {
                "description": "Deploy feature pipeline",
                "input": "Promote the bundle",
                "steps": [{"name": "deploy-bundle", "agentRef": "deployer", "prompt": "Deploy it"}],
            },
            "status": {
                "phase": "completed",
                "runId": "run-live-fallback-1",
                "summary": {"totalSteps": 1, "completedSteps": 1},
                "stepStates": {
                    "deploy-bundle": {"stepName": "deploy-bundle", "agentRef": "deployer", "status": "completed"}
                },
            },
            "summary": {"totalSteps": 1, "completedSteps": 1},
            "step_states": {
                "deploy-bundle": {"stepName": "deploy-bundle", "agentRef": "deployer", "status": "completed"}
            },
            "artifact_path": "/artifacts/feature-pipeline/run-live-fallback-1",
            "journal_path": "/artifacts/feature-pipeline/run-live-fallback-1/journal.ndjson",
            "worker_job_name": "worker-job-live-fallback-1",
            "pending_approval_name": None,
            "triggered_by": "alice",
            "input_text": "Promote the bundle",
            "created_at": "2026-04-09T11:00:00+00:00",
            "updated_at": "2026-04-09T11:02:00+00:00",
            "completed_at": "2026-04-09T11:02:00+00:00",
            "archived_log_available": False,
            "archived_log_source": None,
            "archived_log_truncated": False,
            "archived_log_captured_at": None,
            "logs": None,
        }

        with (
            patch.object(api_gateway_main, "load_workflow_run_trace", return_value=trace_row),
            patch.object(api_gateway_main, "_read_workflow_job_logs", return_value=("2026-04-09T11:00:00Z INFO deployed", "worker-pod-1")),
            patch.object(api_gateway_main, "record_workflow_run_log_archive") as archive_mock,
        ):
            payload = api_gateway_main._resolve_workflow_run_trace_payload(
                "feature-pipeline",
                "default",
                "run-live-fallback-1",
                tail=200,
                persist_live_fallback=True,
            )

        self.assertEqual(payload["source"], "live-worker")
        self.assertEqual(payload["pod_name"], "worker-pod-1")
        self.assertIn("INFO deployed", payload["logs"])
        archive_mock.assert_called_once()

    def test_get_workflow_logs_falls_back_to_archived_trace(self) -> None:
        archived_payload = {
            "workflow_name": "feature-pipeline",
            "run_id": "run-archived-2",
            "job_name": "worker-job-archived-2",
            "pod_name": None,
            "source": "archived",
            "archived_log_available": True,
            "archived_log_source": "operator-terminal-archive",
            "archived_log_truncated": False,
            "archived_log_captured_at": "2026-04-09T12:00:00+00:00",
            "logs": "2026-04-09T11:59:59Z INFO archived snapshot",
        }

        with (
            patch.object(api_gateway_workflows, "ensure_namespace_access"),
            patch.object(
                api_gateway_workflows,
                "read_custom_resource",
                return_value={"status": {"runId": "run-archived-2", "workerJob": {}}},
            ),
            patch.object(api_gateway_workflows, "_fallback_workflow_logs_from_run", return_value=archived_payload),
        ):
            payload = api_gateway_workflows.get_workflow_logs(
                workflow_name="feature-pipeline",
                namespace="default",
                user={"sub": "user-1", "role": "admin", "namespaces": ["*"], "capabilities": {}},
            )

        self.assertEqual(payload["source"], "archived")
        self.assertEqual(payload["run_id"], "run-archived-2")
        self.assertIn("archived snapshot", payload["logs"])

    def test_retry_failed_workflow_steps_assigns_fresh_run_id(self) -> None:
        workflow = {
            "metadata": {"name": "feature-pipeline", "namespace": "default", "generation": 5},
            "spec": {
                "description": "desc",
                "input": "input",
                "steps": [
                    {"name": "draft-blueprint", "agentRef": "planner", "prompt": "Draft it"},
                    {"name": "deploy-bundle", "agentRef": "deployer", "prompt": "Deploy it"},
                ],
            },
            "status": {
                "phase": "failed",
                "runId": "wf-run-default-feature-pipeline-5-old",
                "currentStep": "deploy-bundle",
                "stepStates": {
                    "draft-blueprint": {"status": "completed", "completedAt": "2026-04-06T00:00:00Z"},
                    "deploy-bundle": {
                        "status": "failed",
                        "error": "Forbidden",
                        "failureClass": "verification",
                        "startedAt": "2026-04-06T00:01:00Z",
                        "completedAt": "2026-04-06T00:02:00Z",
                    },
                },
                "summary": {
                    "totalSteps": 2,
                    "completedSteps": 1,
                    "failedSteps": 1,
                    "error": "deploy failed",
                    "runId": "wf-run-default-feature-pipeline-5-old",
                },
            },
        }
        updated = copy.deepcopy(workflow)
        updated["status"]["phase"] = "pending"
        updated["status"]["runId"] = "wf-run-default-feature-pipeline-5-new"
        updated["status"]["stepStates"]["deploy-bundle"] = {
            "status": "pending",
            "error": None,
            "failureClass": None,
            "startedAt": None,
            "completedAt": None,
            "iterationFailures": None,
        }
        updated["status"]["summary"] = {
            **updated["status"]["summary"],
            "runId": "wf-run-default-feature-pipeline-5-new",
            "failedSteps": 0,
            "waitingApprovalSteps": 0,
            "error": None,
        }
        self._mock_custom_objects.get_namespaced_custom_object.side_effect = [workflow, updated]

        with (
            patch.object(api_gateway_workflows, "ensure_namespace_access"),
            patch.object(
                api_gateway_workflows,
                "build_retry_workflow_run_id",
                return_value="wf-run-default-feature-pipeline-5-new",
            ),
            patch.object(api_gateway_workflows, "record_workflow_run"),
        ):
            result = api_gateway_workflows.retry_failed_workflow_steps(
                workflow_name="feature-pipeline",
                namespace="default",
                user={"sub": "user-1", "namespaces": ["default"]},
            )

        patch_kwargs = self._mock_custom_objects.patch_namespaced_custom_object_status.call_args.kwargs
        self.assertEqual(patch_kwargs["body"]["status"]["runId"], "wf-run-default-feature-pipeline-5-new")
        self.assertEqual(
            patch_kwargs["body"]["status"]["summary"]["runId"],
            "wf-run-default-feature-pipeline-5-new",
        )
        self.assertEqual(patch_kwargs["body"]["status"]["stepStates"]["draft-blueprint"]["status"], "completed")
        self.assertEqual(patch_kwargs["body"]["status"]["stepStates"]["deploy-bundle"]["status"], "pending")
        self.assertEqual(result.run_id, "wf-run-default-feature-pipeline-5-new")
        self.assertEqual(result.phase, "pending")


class GatewayProviderModelTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        _bind_gateway_module(self, api_gateway_llm)

    async def test_provider_registry_catalog_only_returns_connected_provider_models(self) -> None:
        with patch.object(
            api_gateway_main,
            "_provider_registry_response",
            AsyncMock(
                return_value={
                    "providers": [
                        {
                            "id": "github-copilot",
                            "label": "GitHub Copilot",
                            "connected": True,
                            "kind": "builtin",
                            "models": [
                                {
                                    "id": "gpt-5-mini",
                                    "name": "GPT-5 Mini",
                                    "description": "Live model",
                                }
                            ],
                        },
                        {
                            "id": "opencode",
                            "label": "OpenCode Zen",
                            "connected": False,
                            "kind": "builtin",
                            "models": [
                                {
                                    "id": "kimi-k2.6",
                                    "name": "kimi-k2.6",
                                    "description": "Should be hidden",
                                }
                            ],
                        },
                    ]
                }
            ),
        ):
            response = await api_gateway_main.provider_registry_catalog(user={"role": "viewer"})

        self.assertEqual(
            response,
            {
                "models": [
                    {
                        "provider_id": "github-copilot",
                        "provider_label": "GitHub Copilot",
                        "model_id": "gpt-5-mini",
                        "model_ref": "github-copilot/gpt-5-mini",
                        "connected": True,
                        "kind": "builtin",
                        "description": "Live model",
                    }
                ]
            },
        )

    async def test_add_copilot_model_falls_back_when_token_exchange_fails(self) -> None:
        class FakeSecret:
            data = {"GITHUB_COPILOT_TOKEN": "Z2gtb2F1dGgtdG9rZW4="}

        class FakeCoreV1Api:
            def read_namespaced_secret(self, name, namespace):
                self.name = name
                self.namespace = namespace
                return FakeSecret()

        class FakeAsyncClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def post(self, url, **kwargs):
                self.url = url
                self.kwargs = kwargs
                return httpx.Response(200, json={"ok": True}, request=httpx.Request("POST", url))

        fake_client = FakeAsyncClient()
        fake_core_v1_api = FakeCoreV1Api()
        fake_k8s_client = types.SimpleNamespace(CoreV1Api=lambda: fake_core_v1_api)

        with (
            patch.dict(api_gateway_main.os.environ, {"POD_NAMESPACE": "default"}, clear=False),
            patch.object(api_gateway_main, "LLM_SECRET_NAME", "kubesynapse-llm-api-keys"),
            patch.object(
                api_gateway_main, "_exchange_copilot_session_token", AsyncMock(side_effect=RuntimeError("boom"))
            ),
            patch.object(api_gateway_main.httpx, "AsyncClient", return_value=fake_client),
            patch.dict(sys.modules, {"kubernetes": types.SimpleNamespace(client=fake_k8s_client)}),
        ):
            response = await api_gateway_main.llm_add_provider_model(
                "GITHUB_COPILOT_TOKEN",
                api_gateway_main.ProviderModelAdd(model_id="gpt-4o-mini", alias="mini"),
                user={"role": "admin"},
            )

        self.assertEqual(response, {"ok": True})
        self.assertEqual(fake_core_v1_api.name, "kubesynapse-llm-api-keys")
        self.assertEqual(fake_core_v1_api.namespace, "default")
        self.assertEqual(fake_client.url, f"{api_gateway_main.LITELLM_INTERNAL_URL}/model/new")
        payload = fake_client.kwargs["json"]
        self.assertEqual(payload["model_name"], "copilot-mini")
        self.assertEqual(payload["litellm_params"]["model"], "openai/gpt-4o-mini")
        self.assertEqual(payload["litellm_params"]["api_key"], "gh-oauth-token")
        self.assertEqual(payload["litellm_params"]["api_base"], "https://api.githubcopilot.com")
        self.assertEqual(payload["litellm_params"]["extra_headers"], {"Copilot-Integration-Id": "vscode-chat"})


class McpOAuthSupportTests(unittest.TestCase):
    def tearDown(self) -> None:
        api_gateway_main._MCP_OAUTH_PENDING_FLOWS.clear()

    def test_oauth_registry_entries_reflect_attachability(self) -> None:
        registry = {entry["id"]: entry for entry in api_gateway_main._build_mcp_registry_results()}

        self.assertTrue(registry["notion-remote"]["attachable"])
        self.assertEqual(registry["notion-remote"]["support_level"], "ready")
        self.assertTrue(registry["gmail"]["attachable"])
        self.assertEqual(registry["gmail"]["support_level"], "limited")
        self.assertFalse(registry["figma"]["attachable"])

    def test_serialize_saved_mcp_connection_includes_oauth_status_and_runtime_header(self) -> None:
        connection_record = {
            "id": "conn-gmail",
            "namespace": "default",
            "name": "Gmail Remote",
            "slug": "gmail-remote",
            "server_id": "gmail",
            "transport": "remote",
            "auth_type": "oauth",
            "config": {
                "endpoint_url": "https://mcp.example.test/mcp",
                "client_id": "client-123",
            },
            "credential_metadata": [
                {
                    "key": "client_secret",
                    "label": "OAuth Client Secret",
                    "type": "password",
                    "group": "credentials",
                    "required": True,
                    "configured": True,
                }
            ],
            "secret_name": "mcp-conn-conn-gmail",
            "validation": {"status": "draft", "message": "Saved but not validated yet.", "detail": None},
        }
        future_expiry = (datetime.now(UTC) + timedelta(minutes=45)).isoformat()

        with patch.object(
            api_gateway_main,
            "_read_mcp_connection_secret_values",
            return_value={
                "client_secret": "top-secret",
                "access_token": "ya29.token",
                "refresh_token": "refresh-token",
                "token_type": "Bearer",
                "expires_at": future_expiry,
                "scope": "openid email profile https://www.googleapis.com/auth/gmail.modify",
            },
        ):
            serialized = api_gateway_main._serialize_saved_mcp_connection_record(connection_record)

        self.assertEqual(serialized["oauth"]["state"], "connected")
        self.assertTrue(serialized["oauth"]["connected"])
        runtime_headers = serialized["runtime_preview"]["headers"]
        self.assertEqual(runtime_headers[0]["name"], "Authorization")
        self.assertEqual(runtime_headers[0]["prefix"], "Bearer ")

    def test_start_saved_mcp_connection_oauth_builds_browser_authorization_url(self) -> None:
        connection_record = {
            "id": "conn-gmail",
            "namespace": "team-a",
            "name": "Gmail Remote",
            "slug": "gmail-remote",
            "server_id": "gmail",
            "transport": "remote",
            "auth_type": "oauth",
            "config": {
                "endpoint_url": "https://mcp.example.test/mcp",
                "client_id": "client-123",
            },
            "credential_metadata": [
                {
                    "key": "client_secret",
                    "label": "OAuth Client Secret",
                    "type": "password",
                    "group": "credentials",
                    "required": True,
                    "configured": True,
                }
            ],
            "secret_name": "mcp-conn-conn-gmail",
            "validation": {"status": "draft", "message": "Saved but not validated yet.", "detail": None},
        }

        with (
            patch.object(api_gateway_observability, "ensure_namespace_access", return_value=None),
            patch.object(api_gateway_observability, "get_mcp_connection", return_value=connection_record),
            patch.object(api_gateway_observability, "_mcp_connection_secret_values_for_record", return_value={"client_secret": "top-secret"}),
        ):
            response = api_gateway_observability.start_saved_mcp_connection_oauth(
                "conn-gmail",
                raw_request=types.SimpleNamespace(base_url="https://kubesynapse.example.test/"),
                namespace="team-a",
                user={"sub": "user-1", "role": "operator"},
            )

        self.assertIn("https://accounts.google.com/o/oauth2/v2/auth?", response["authorization_url"])
        self.assertIn("client_id=client-123", response["authorization_url"])
        self.assertIn("state=", response["authorization_url"])
        self.assertIn(
            "redirect_uri=https%3A%2F%2Fkubesynapse.example.test%2Fapi%2Fmcp%2Fconnections%2Fconn-gmail%2Foauth%2Fcallback",
            response["authorization_url"],
        )


class WebhookTriggerApiTests(unittest.TestCase):
    def setUp(self) -> None:
        from sqlalchemy.orm import sessionmaker

        import auth_store as canonical_auth_store

        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)

        self.engine = create_engine(
            f"sqlite:///{(Path(self.temp_dir.name) / 'webhooks.db').as_posix()}",
            future=True,
            connect_args={"check_same_thread": False},
        )
        self.SessionLocal = sessionmaker(
            bind=self.engine,
            autoflush=False,
            autocommit=False,
            expire_on_commit=False,
            future=True,
        )

        self.original_auth_engine = canonical_auth_store.ENGINE
        self.original_auth_session_local = canonical_auth_store.SessionLocal
        canonical_auth_store.ENGINE = self.engine
        canonical_auth_store.SessionLocal = self.SessionLocal
        self.addCleanup(setattr, canonical_auth_store, "ENGINE", self.original_auth_engine)
        self.addCleanup(setattr, canonical_auth_store, "SessionLocal", self.original_auth_session_local)
        self.addCleanup(self.engine.dispose)
        canonical_auth_store.init_database()

        self.webhooks_router = _load_gateway_module(f"api_gateway_webhooks_{uuid.uuid4().hex}", "routers/webhooks.py")
        self.addCleanup(lambda: sys.modules.pop(self.webhooks_router.__name__, None))

        self.recent_patcher = patch.object(self.webhooks_router, "count_recent_webhook_invocations", lambda *_args, **_kwargs: 0)
        self.signature_patcher = patch.object(self.webhooks_router, "verify_provider_signature", lambda *_args, **_kwargs: True)
        self.timestamp_patcher = patch.object(self.webhooks_router, "verify_webhook_timestamp", lambda *_args, **_kwargs: None)
        self.rate_limit_patcher = patch.object(self.webhooks_router, "check_webhook_rate_limit", lambda *_args, **_kwargs: None)
        self.secret_patcher = patch.object(self.webhooks_router, "_resolve_webhook_secret", lambda *_args, **_kwargs: "secret")
        self.client_ip_patcher = patch.object(self.webhooks_router, "resolve_trusted_client_ip", lambda *_args, **_kwargs: "127.0.0.1")
        self.namespace_access_patcher = patch.object(self.webhooks_router, "ensure_namespace_access", lambda *_args, **_kwargs: None)
        self.role_patcher = patch.object(self.webhooks_router, "ensure_role", lambda *_args, **_kwargs: None)

        self.recent_patcher.start()
        self.signature_patcher.start()
        self.timestamp_patcher.start()
        self.rate_limit_patcher.start()
        self.secret_patcher.start()
        self.client_ip_patcher.start()
        self.namespace_access_patcher.start()
        self.role_patcher.start()

        self.addCleanup(self.recent_patcher.stop)
        self.addCleanup(self.signature_patcher.stop)
        self.addCleanup(self.timestamp_patcher.stop)
        self.addCleanup(self.rate_limit_patcher.stop)
        self.addCleanup(self.secret_patcher.stop)
        self.addCleanup(self.client_ip_patcher.stop)
        self.addCleanup(self.namespace_access_patcher.stop)
        self.addCleanup(self.role_patcher.stop)

        self.auth_store = canonical_auth_store
        self.operator_user = {"sub": "test-user", "role": "operator", "allowed_namespaces": ["*"]}

    def test_create_trigger_returns_ui_contract_shape(self) -> None:
        created_webhook = self.webhooks_router.create_webhook(
            body=self.webhooks_router.WebhookReceiverRequest(
                name="incident-alerts",
                secret_ref="default/incident-webhook-secret#hmac-key",
                ip_allowlist=[],
                rate_limit=30,
                max_payload_bytes=1048576,
                enabled=True,
            ),
            namespace="default",
            user=self.operator_user,
        )
        self.assertEqual(created_webhook.name, "incident-alerts")

        result = self.webhooks_router.create_trigger(
            body=self.webhooks_router.WorkflowTriggerRequest(
                name="incident-alert-trigger",
                source_kind="WebhookReceiver",
                source_ref="incident-alerts",
                event_filter={
                    "conditions": [
                        {"field": "severity", "operator": "equals", "value": "critical"},
                    ]
                },
                workflow_ref={"name": "incident-webhook-response", "namespace": "default"},
                max_retries=1,
                backoff_seconds=30,
                enabled=True,
            ),
            namespace="default",
            user=self.operator_user,
        )

        self.assertIsInstance(result.id, int)
        self.assertEqual(result.source_ref, "incident-alerts")
        self.assertEqual(result.workflow_ref, {"name": "incident-webhook-response", "namespace": "default"})
        self.assertEqual(result.max_retries, 1)
        self.assertEqual(result.backoff_seconds, 30)
        self.assertEqual(result.execution_count, 0)
        self.assertIsNone(result.last_triggered)

    def test_create_trigger_accepts_legacy_body_fields(self) -> None:
        self.webhooks_router.create_webhook(
            body=self.webhooks_router.WebhookReceiverRequest(
                name="incident-alerts",
                secret_ref="default/incident-webhook-secret#hmac-key",
                ip_allowlist=[],
                rate_limit=30,
                max_payload_bytes=1048576,
                enabled=True,
            ),
            namespace="default",
            user=self.operator_user,
        )

        legacy_body = types.SimpleNamespace(
            name="incident-alert-trigger-legacy",
            source_kind="WebhookReceiver",
            source_name="incident-alerts",
            event_filter={"severity": "critical"},
            target_workflow_name="incident-webhook-response",
            target_workflow_namespace="default",
            payload_mapping={},
            max_retries=1,
            backoff_seconds=30,
            notifications_on_success=[],
            notifications_on_failure=[],
            enabled=True,
        )

        result = self.webhooks_router.create_trigger(
            body=legacy_body,
            namespace="default",
            user=self.operator_user,
        )

        self.assertEqual(result.name, "incident-alert-trigger-legacy")
        self.assertEqual(result.source_ref, "incident-alerts")
        self.assertEqual(result.workflow_ref, {"name": "incident-webhook-response", "namespace": "default"})

    def test_update_trigger_preserves_omitted_fields(self) -> None:
        self.auth_store.create_workflow_trigger(
            namespace="default",
            name="incident-alert-trigger",
            source_kind="WebhookReceiver",
            source_name="incident-alerts",
            event_filter={"conditions": [{"field": "severity", "operator": "equals", "value": "critical"}]},
            target_workflow_name="incident-webhook-response",
            target_workflow_namespace="default",
            retry_max_retries=2,
            retry_backoff_seconds=45,
            enabled=True,
        )

        result = self.webhooks_router.update_trigger(
            name="incident-alert-trigger",
            body=self.webhooks_router.WorkflowTriggerUpdateRequest(enabled=False),
            namespace="default",
            user=self.operator_user,
        )

        self.assertEqual(result.source_ref, "incident-alerts")
        self.assertEqual(result.workflow_ref, {"name": "incident-webhook-response", "namespace": "default"})
        self.assertEqual(result.max_retries, 2)
        self.assertEqual(result.backoff_seconds, 45)
        self.assertFalse(result.enabled)

    def test_invoke_webhook_records_matched_trigger_history(self) -> None:
        from starlette.requests import Request

        self.auth_store.create_webhook_receiver(
            namespace="default",
            name="incident-alerts",
            secret_ref="default/incident-webhook-secret#hmac-key",
            rate_limit=30,
            max_payload_bytes=1048576,
            enabled=True,
        )
        self.auth_store.create_workflow_trigger(
            namespace="default",
            name="incident-alert-trigger",
            source_kind="WebhookReceiver",
            source_name="incident-alerts",
            event_filter={
                "conditions": [
                    {"field": "severity", "operator": "equals", "value": "critical"},
                    {"field": "service", "operator": "equals", "value": "api-gateway"},
                ]
            },
            target_workflow_name="incident-webhook-response",
            target_workflow_namespace="default",
            retry_max_retries=1,
            retry_backoff_seconds=30,
            enabled=True,
        )

        async def receive() -> dict[str, object]:
            return {
                "type": "http.request",
                "body": json.dumps(
                    {"severity": "critical", "service": "api-gateway", "summary": "latency spike"}
                ).encode("utf-8"),
                "more_body": False,
            }

        raw_request = Request(
            {
                "type": "http",
                "http_version": "1.1",
                "method": "POST",
                "scheme": "http",
                "path": "/api/v1/webhooks/incident-alerts/invoke",
                "raw_path": b"/api/v1/webhooks/incident-alerts/invoke",
                "query_string": b"namespace=default",
                "headers": [],
                "client": ("127.0.0.1", 12345),
                "server": ("testserver", 80),
            },
            receive,
        )

        response = asyncio.run(
            self.webhooks_router.invoke_webhook(
                name="incident-alerts",
                raw_request=raw_request,
                namespace="default",
                dry_run=False,
                x_kubesynapse_signature="sha256=test",
                x_kubesynapse_timestamp="1710000000",
                x_kubesynapse_key_id=None,
                x_api_key=None,
                x_hub_signature_256=None,
                x_slack_signature=None,
                x_slack_request_timestamp=None,
                stripe_signature=None,
                x_pd_signature=None,
            )
        )
        self.assertEqual(response.status_code, 202)
        invoke_payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(invoke_payload["matched_triggers"], 1)

        history = self.webhooks_router.get_trigger_history(
            name="incident-alert-trigger",
            namespace="default",
            user=self.operator_user,
        )
        self.assertEqual(len(history), 1)
        execution = history[0]
        self.assertEqual(execution.trigger_name, "incident-alert-trigger")
        self.assertEqual(execution.webhook_name, "incident-alerts")
        self.assertEqual(execution.status, "pending")
        self.assertEqual(execution.namespace, "default")

        webhook_history = self.webhooks_router.get_webhook_history(
            name="incident-alerts",
            namespace="default",
            user=self.operator_user,
        )
        self.assertEqual(len(webhook_history), 1)
        invocation = webhook_history[0]
        self.assertEqual(invocation.webhook_name, "incident-alerts")
        self.assertEqual(invocation.matched_triggers, 1)
        self.assertEqual(invocation.status, "received")
        self.assertTrue(invocation.signature_verified)
        self.assertEqual(invocation.invocation_id, invoke_payload["invocation_id"])


class RuntimeLogsCapabilityTests(unittest.TestCase):
    """Gate: agents/workflows logs routes must enforce the runtime:logs capability
    in addition to the existing auth + namespace checks, so admins can grant
    least-privilege log access instead of inheriting it from the role."""

    def setUp(self) -> None:
        self.viewer_user = {
            "sub": "1",
            "username": "viewer.user",
            "role": "viewer",
            "allowed_namespaces": ["default"],
            "capabilities": {},
        }
        self.operator_user = {
            "sub": "2",
            "username": "operator.user",
            "role": "operator",
            "allowed_namespaces": ["default"],
            "capabilities": {"runtime:logs": True},
        }
        self.revoked_operator_user = {
            "sub": "3",
            "username": "no-logs.operator",
            "role": "operator",
            "allowed_namespaces": ["default"],
            "capabilities": {"runtime:logs": False},
        }
        self.admin_user = {
            "sub": "4",
            "username": "admin.user",
            "role": "admin",
            "allowed_namespaces": ["*"],
            "capabilities": {},
        }
        self.granted_viewer_user = {
            "sub": "5",
            "username": "granted.viewer",
            "role": "viewer",
            "allowed_namespaces": ["default"],
            "capabilities": {"runtime:logs": True},
        }

    def test_admin_is_allowed_by_role_even_without_capability_record(self) -> None:
        from auth_middleware import user_has_capability

        self.assertTrue(user_has_capability(self.admin_user, "runtime:logs"))

    def test_operator_defaults_to_allowed(self) -> None:
        from auth_middleware import user_has_capability

        self.assertTrue(user_has_capability(self.operator_user, "runtime:logs"))

    def test_operator_can_be_revoked_via_capability_record(self) -> None:
        from auth_middleware import user_has_capability

        self.assertFalse(user_has_capability(self.revoked_operator_user, "runtime:logs"))

    def test_viewer_without_capability_is_denied(self) -> None:
        from auth_middleware import user_has_capability

        self.assertFalse(user_has_capability(self.viewer_user, "runtime:logs"))

    def test_viewer_with_admin_granted_capability_is_allowed(self) -> None:
        from auth_middleware import user_has_capability

        self.assertTrue(user_has_capability(self.granted_viewer_user, "runtime:logs"))

    def test_unknown_capability_is_always_denied(self) -> None:
        from auth_middleware import user_has_capability

        self.assertFalse(user_has_capability(self.admin_user, "secrets:read"))

    def test_ensure_capability_raises_403_for_viewer(self) -> None:
        from fastapi import HTTPException

        from auth_middleware import ensure_capability

        with self.assertRaises(HTTPException) as ctx:
            ensure_capability(self.viewer_user, "runtime:logs")
        self.assertEqual(ctx.exception.status_code, 403)
        self.assertIn("runtime:logs", str(ctx.exception.detail))

    def test_ensure_capability_passes_for_admin(self) -> None:
        from auth_middleware import ensure_capability

        # Should not raise.
        self.assertIs(ensure_capability(self.admin_user, "runtime:logs"), self.admin_user)

    def test_sanitize_capabilities_rejects_non_boolean_log_flag(self) -> None:
        from auth_store import _sanitize_capabilities

        with self.assertRaises(ValueError):
            _sanitize_capabilities("operator", {"runtime:logs": "yes"})

    def test_sanitize_capabilities_drops_unknown_keys(self) -> None:
        from auth_store import _sanitize_capabilities

        sanitized = _sanitize_capabilities("operator", {"runtime:logs": False, "secrets:read": True})
        self.assertEqual(sanitized, {"runtime:logs": False})

    def test_sanitize_capabilities_drops_admin_log_flag(self) -> None:
        from auth_store import _sanitize_capabilities

        sanitized = _sanitize_capabilities("admin", {"runtime:logs": True, "anything": False})
        # Admin always has the capability; we don't store it, and unknown
        # keys are dropped silently to keep the contract forward-compatible.
        self.assertEqual(sanitized, {})


class AdminUserCapabilitiesRouteTests(unittest.TestCase):
    """The PATCH /admin/users/{id} route must forward `capabilities` and
    audit it."""

    def setUp(self) -> None:
        self.admin_user = {
            "sub": "1",
            "username": "admin.user",
            "role": "admin",
            "allowed_namespaces": ["*"],
            "capabilities": {},
        }

    def test_admin_update_user_propagates_capabilities_and_audits(self) -> None:
        body = api_gateway_admin.UpdateUserRequest(
            role="viewer",
            capabilities={"runtime:logs": True},
        )
        existing = types.SimpleNamespace(
            id=9,
            username="someone",
            role="viewer",
            allowed_namespaces=["default"],
            is_active=True,
        )
        updated = {
            "id": 9,
            "username": "someone",
            "role": "viewer",
            "allowed_namespaces": ["default"],
            "capabilities": {"runtime:logs": True},
            "auth_provider": "local",
            "is_active": True,
        }
        custom_api = Mock()

        with (
            patch.object(api_gateway_admin, "get_user_by_id", return_value=existing),
            patch.object(api_gateway_admin, "update_user_fields", return_value=updated) as update_user_fields,
            patch.object(api_gateway_admin, "safe_record_audit") as record_audit,
            patch.object(api_gateway_admin, "request_client_ip", return_value="127.0.0.1"),
            patch.object(api_gateway_admin, "_custom_objects_api", return_value=custom_api),
        ):
            response = api_gateway_admin.admin_update_user(9, body, object(), user=self.admin_user)

        self.assertEqual(response, updated)
        update_user_fields.assert_called_once_with(
            9,
            display_name=None,
            role="viewer",
            is_active=None,
            allowed_namespaces=["default", "user-someone"],
            capabilities={"runtime:logs": True},
        )
        record_audit.assert_called_once()
        audit_kwargs = record_audit.call_args.kwargs
        self.assertEqual(audit_kwargs["action"], "admin.update-user")
        self.assertEqual(audit_kwargs["detail"]["capabilities"], {"runtime:logs": True})


if __name__ == "__main__":
    unittest.main()
