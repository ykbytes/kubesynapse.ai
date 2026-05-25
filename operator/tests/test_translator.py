"""Tests for builders.translator — the AgentOutputs bundle and translate_agent().

§kagent-pattern-2 test coverage.
"""

import sys
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _passthrough_decorator(*args, **kwargs):
    def decorator(func):
        return func

    return decorator


class _PermanentError(Exception):
    pass


class _TemporaryError(Exception):
    def __init__(self, *args, delay=None, **kwargs):
        super().__init__(*args)
        self.delay = delay


croniter_module = types.ModuleType("croniter")


class _CroniterBadCronError(Exception):
    pass


def _croniter(*args, **kwargs):
    raise AssertionError("croniter should not be invoked")


croniter_module.CroniterBadCronError = _CroniterBadCronError
croniter_module.croniter = _croniter
sys.modules["croniter"] = croniter_module

kopf_module = types.ModuleType("kopf")
kopf_module.on = types.SimpleNamespace(
    startup=_passthrough_decorator,
    cleanup=_passthrough_decorator,
    create=_passthrough_decorator,
    update=_passthrough_decorator,
    delete=_passthrough_decorator,
    resume=_passthrough_decorator,
    field=_passthrough_decorator,
)
kopf_module.timer = _passthrough_decorator
kopf_module.adopt = lambda *args, **kwargs: None
kopf_module.PermanentError = _PermanentError
kopf_module.TemporaryError = _TemporaryError
kopf_module.OperatorSettings = type("OperatorSettings", (), {})
sys.modules["kopf"] = kopf_module

kubernetes_module = types.ModuleType("kubernetes")
client_module = types.ModuleType("kubernetes.client")
config_module = types.ModuleType("kubernetes.config")
rest_module = types.ModuleType("kubernetes.client.rest")
rest_module.ApiException = type("ApiException", (Exception,), {"status": None})
config_module.ConfigException = type("ConfigException", (Exception,), {})
kubernetes_module.client = client_module
kubernetes_module.config = config_module
client_module.rest = rest_module
client_module.CoreV1Api = MagicMock
client_module.AppsV1Api = MagicMock
client_module.CustomObjectsApi = MagicMock
client_module.NetworkingV1Api = MagicMock
client_module.BatchV1Api = MagicMock
client_module.RbacAuthorizationV1Api = MagicMock
client_module.ApiTypeError = TypeError
sys.modules["kubernetes"] = kubernetes_module
sys.modules["kubernetes.client"] = client_module
sys.modules["kubernetes.config"] = config_module
sys.modules["kubernetes.client.rest"] = rest_module

for module_name in [
    "builders.translator",
    "builders.manifests",
    "builders.helpers",
    "builders",
]:
    sys.modules.pop(module_name, None)

from builders.helpers import sandbox_name  # noqa: E402
from builders.translator import AgentOutputs, translate_agent  # noqa: E402


class TestAgentOutputsDataclass(unittest.TestCase):
    """Tests for the AgentOutputs dataclass methods."""

    def _make_outputs(self, *, with_secret: bool = False) -> AgentOutputs:
        """Build a minimal AgentOutputs for testing."""
        return AgentOutputs(
            service={"metadata": {"name": "test-sandbox"}, "kind": "Service"},
            statefulset={"metadata": {"name": "test-sandbox"}, "kind": "StatefulSet"},
            mcp_network_policy={"metadata": {"name": "test-sandbox-mcp-egress"}, "kind": "NetworkPolicy"},
            a2a_egress_network_policy={"metadata": {"name": "test-sandbox-a2a-egress"}, "kind": "NetworkPolicy"},
            a2a_ingress_network_policy={"metadata": {"name": "test-sandbox-a2a-ingress"}, "kind": "NetworkPolicy"},
            mcp_auth_secret={"metadata": {"name": "mcp-auth"}, "kind": "Secret"} if with_secret else None,
            agent_name="test",
            agent_namespace="ns-test",
            policy_name="my-policy",
            runtime_kind="opencode",
            allowed_mcp_servers=["github"] if with_secret else [],
            has_tenant=True,
        )

    def test_owned_manifests_excludes_secret(self) -> None:
        outputs = self._make_outputs(with_secret=True)
        owned = outputs.owned_manifests()
        # Secret should NOT be in owned (it's not kopf.adopt-ed)
        kinds = [m.get("kind") for m in owned]
        self.assertNotIn("Secret", kinds)
        self.assertEqual(len(owned), 5)

    def test_all_manifests_includes_secret(self) -> None:
        outputs = self._make_outputs(with_secret=True)
        all_m = outputs.all_manifests()
        kinds = [m.get("kind") for m in all_m]
        self.assertIn("Secret", kinds)
        self.assertEqual(len(all_m), 6)

    def test_all_manifests_without_secret(self) -> None:
        outputs = self._make_outputs(with_secret=False)
        self.assertEqual(len(outputs.all_manifests()), 5)

    def test_desired_resource_names(self) -> None:
        outputs = self._make_outputs(with_secret=True)
        names = outputs.desired_resource_names()
        self.assertIn("test-sandbox", names)
        self.assertIn("test-sandbox-mcp-egress", names)
        self.assertIn("test-sandbox-a2a-egress", names)
        self.assertIn("test-sandbox-a2a-ingress", names)
        self.assertIn("mcp-auth", names)

    def test_desired_resource_names_no_secret(self) -> None:
        outputs = self._make_outputs(with_secret=False)
        names = outputs.desired_resource_names()
        self.assertNotIn("mcp-auth", names)
        self.assertEqual(len(names), 4)  # sandbox name appears twice (service + sts) -> 4 unique

    def test_default_field_values(self) -> None:
        outputs = AgentOutputs(
            service={"metadata": {"name": "x"}},
            statefulset={"metadata": {"name": "x"}},
            mcp_network_policy={"metadata": {"name": "x"}},
            a2a_egress_network_policy={"metadata": {"name": "x"}},
            a2a_ingress_network_policy={"metadata": {"name": "x"}},
        )
        self.assertEqual(outputs.agent_name, "")
        self.assertEqual(outputs.agent_namespace, "")
        self.assertIsNone(outputs.policy_name)
        self.assertEqual(outputs.runtime_kind, "opencode")
        self.assertEqual(outputs.allowed_mcp_servers, [])
        self.assertFalse(outputs.has_tenant)
        self.assertIsNone(outputs.mcp_auth_secret)


class TestTranslateAgent(unittest.TestCase):
    """Tests for the translate_agent() function."""

    def test_translate_opencode_agent_without_policy(self) -> None:
        spec = {
            "model": "gpt-4",
            "systemPrompt": "You are helpful.",
            "runtime": {"kind": "opencode"},
        }
        outputs = translate_agent(
            spec=spec,
            name="my-agent",
            namespace="team-alpha",
            policy_name=None,
            policy_spec=None,
        )
        self.assertIsInstance(outputs, AgentOutputs)
        self.assertEqual(outputs.agent_name, "my-agent")
        self.assertEqual(outputs.agent_namespace, "team-alpha")
        self.assertIsNone(outputs.policy_name)
        self.assertEqual(outputs.runtime_kind, "opencode")
        self.assertFalse(outputs.has_tenant)
        self.assertEqual(outputs.allowed_mcp_servers, [])
        self.assertIsNone(outputs.mcp_auth_secret)

        # Service manifest check
        self.assertEqual(outputs.service["kind"], "Service")
        self.assertEqual(outputs.service["metadata"]["name"], sandbox_name("my-agent"))
        self.assertEqual(outputs.service["metadata"]["namespace"], "team-alpha")

        # StatefulSet manifest check
        self.assertEqual(outputs.statefulset["kind"], "StatefulSet")
        self.assertEqual(outputs.statefulset["metadata"]["name"], sandbox_name("my-agent"))

        # Network policies
        self.assertEqual(outputs.mcp_network_policy["kind"], "NetworkPolicy")
        self.assertEqual(outputs.a2a_egress_network_policy["kind"], "NetworkPolicy")
        self.assertEqual(outputs.a2a_ingress_network_policy["kind"], "NetworkPolicy")

    def test_translate_agent_with_policy_and_mcp(self) -> None:
        spec = {
            "model": "gpt-4o",
            "systemPrompt": "Test",
            "runtime": {"kind": "opencode"},
        }
        policy_spec = {"allowedMcpServers": ["github", "jira"]}

        outputs = translate_agent(
            spec=spec,
            name="smart-agent",
            namespace="team-beta",
            policy_name="strict-policy",
            policy_spec=policy_spec,
        )

        self.assertEqual(outputs.policy_name, "strict-policy")
        self.assertEqual(outputs.allowed_mcp_servers, ["github", "jira"])
        self.assertIsNone(outputs.mcp_auth_secret)

    def test_translate_agent_with_saved_remote_mcp_connections_skips_hub_auth_secret(self) -> None:
        spec = {
            "model": "gpt-4o",
            "systemPrompt": "Test",
            "runtime": {"kind": "opencode"},
            "mcpConnections": [
                {
                    "connectionId": "conn-123",
                    "serverId": "context7",
                    "transport": "remote",
                }
            ],
            "mcpServers": ["context7"],
        }

        outputs = translate_agent(
            spec=spec,
            name="saved-mcp-agent",
            namespace="team-gamma",
            policy_name=None,
            policy_spec=None,
        )

        self.assertEqual(outputs.allowed_mcp_servers, [])
        self.assertIsNone(outputs.mcp_auth_secret)

    def test_translate_agent_with_legacy_shared_mcp_servers_requires_hub_auth_secret(self) -> None:
        spec = {
            "model": "gpt-4o",
            "systemPrompt": "Test",
            "runtime": {"kind": "opencode"},
            "mcpServers": ["documents"],
        }

        mock_secret = MagicMock()
        mock_secret.data = {"bearer-token": "dG9rZW4="}
        mock_secret.type = "Opaque"

        mock_core_api = MagicMock()
        mock_core_api.read_namespaced_secret.return_value = mock_secret

        kube_client = sys.modules["kubernetes.client"]
        with patch.object(kube_client, "CoreV1Api", return_value=mock_core_api, create=True):
            outputs = translate_agent(
                spec=spec,
                name="legacy-mcp-agent",
                namespace="team-gamma",
                policy_name=None,
                policy_spec=None,
            )

        self.assertIsNotNone(outputs.mcp_auth_secret)
        self.assertEqual(outputs.mcp_auth_secret["metadata"]["namespace"], "team-gamma")

    def test_translate_agent_with_tenant(self) -> None:
        spec = {"model": "gpt-4", "runtime": {"kind": "opencode"}}
        outputs = translate_agent(
            spec=spec,
            name="t-agent",
            namespace="ns-1",
            policy_name=None,
            policy_spec=None,
            tenant_spec={"namespace": "ns-1", "allowedModels": ["gpt-4"]},
        )
        self.assertTrue(outputs.has_tenant)

    def test_translate_agent_requires_explicit_runtime_kind(self) -> None:
        spec = {"model": "gpt-4", "systemPrompt": "You are helpful."}

        with self.assertRaises(kopf_module.PermanentError) as context:
            translate_agent(
                spec=spec,
                name="my-agent",
                namespace="team-alpha",
                policy_name=None,
                policy_spec=None,
            )

        self.assertIn("AIAgent.spec.runtime.kind must be explicitly set to 'opencode'", str(context.exception))

    def test_translate_goose_runtime_is_rejected(self) -> None:
        spec = {"model": "gpt-4", "runtime": {"kind": "goose"}}

        with self.assertRaises(kopf_module.PermanentError) as context:
            translate_agent(
                spec=spec,
                name="goose-agent",
                namespace="ns-goose",
                policy_name=None,
                policy_spec=None,
            )

        self.assertIn("Unsupported AIAgent.spec.runtime.kind 'goose'", str(context.exception))

    def test_translate_opencode_runtime(self) -> None:
        spec = {"model": "gpt-4", "runtime": {"kind": "opencode"}}
        outputs = translate_agent(
            spec=spec,
            name="oc-agent",
            namespace="ns-oc",
            policy_name=None,
            policy_spec=None,
        )
        self.assertEqual(outputs.runtime_kind, "opencode")

    def test_translate_mistral_vibe_runtime(self) -> None:
        spec = {
            "model": "devstral-small",
            "runtime": {
                "kind": "mistral-vibe",
                "mistralVibe": {"model": "devstral-small", "noSession": True},
            },
        }
        outputs = translate_agent(
            spec=spec,
            name="vibe-agent",
            namespace="ns-vibe",
            policy_name=None,
            policy_spec=None,
        )
        self.assertEqual(outputs.runtime_kind, "mistral-vibe")
        self.assertIsNone(outputs.provider_bootstrap_secret)

    def test_translate_codex_runtime_is_rejected(self) -> None:
        spec = {"model": "gpt-4", "runtime": {"kind": "codex"}}

        with self.assertRaises(kopf_module.PermanentError) as context:
            translate_agent(
                spec=spec,
                name="cx-agent",
                namespace="ns-cx",
                policy_name=None,
                policy_spec=None,
            )

        self.assertIn("Unsupported AIAgent.spec.runtime.kind 'codex'", str(context.exception))

    def test_translate_agent_owned_manifests_count(self) -> None:
        spec = {"model": "gpt-4", "runtime": {"kind": "opencode"}}
        outputs = translate_agent(
            spec=spec,
            name="count-agent",
            namespace="ns-count",
            policy_name=None,
            policy_spec=None,
        )
        # Without MCP, should have 5 owned manifests
        self.assertEqual(len(outputs.owned_manifests()), 5)

    def test_translate_agent_desired_names_consistent(self) -> None:
        spec = {"model": "gpt-4", "runtime": {"kind": "opencode"}}
        outputs = translate_agent(
            spec=spec,
            name="named-agent",
            namespace="ns-named",
            policy_name=None,
            policy_spec=None,
        )
        names = outputs.desired_resource_names()
        # All manifest names should be present
        for m in outputs.all_manifests():
            self.assertIn(m["metadata"]["name"], names)


if __name__ == "__main__":
    unittest.main()
