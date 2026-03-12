import json
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

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
    raise AssertionError("croniter should not be invoked in manifest tests")


croniter_module.CroniterBadCronError = _CroniterBadCronError
croniter_module.croniter = _croniter
sys.modules.setdefault("croniter", croniter_module)

kopf_module = types.ModuleType("kopf")
kopf_module.on = types.SimpleNamespace(
    startup=_passthrough_decorator,
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
sys.modules.setdefault("kopf", kopf_module)

kubernetes_module = types.ModuleType("kubernetes")
client_module = types.ModuleType("kubernetes.client")
config_module = types.ModuleType("kubernetes.config")
rest_module = types.ModuleType("kubernetes.client.rest")
rest_module.ApiException = type("ApiException", (Exception,), {"status": None})
config_module.ConfigException = type("ConfigException", (Exception,), {})
kubernetes_module.client = client_module
kubernetes_module.config = config_module
client_module.rest = rest_module
sys.modules.setdefault("kubernetes", kubernetes_module)
sys.modules.setdefault("kubernetes.client", client_module)
sys.modules.setdefault("kubernetes.config", config_module)
sys.modules.setdefault("kubernetes.client.rest", rest_module)

import main as operator_main  # noqa: E402


class OperatorManifestTests(unittest.TestCase):
    def test_classify_reconcile_error_marks_4xx_api_failures_permanent(self) -> None:
        exc = operator_main.ApiException("invalid resource")
        exc.status = 422
        exc.reason = "Unprocessable Entity"
        exc.body = '{"error":"invalid"}'

        error = operator_main.classify_reconcile_error("create-agent", exc, default_delay=7)

        self.assertIsInstance(error, operator_main.kopf.PermanentError)
        self.assertIn("create-agent failed:", str(error))
        self.assertIn("status=422", str(error))
        self.assertIn("reason=Unprocessable Entity", str(error))

    def test_classify_reconcile_error_uses_backoff_for_5xx_api_failures(self) -> None:
        exc = operator_main.ApiException("upstream unavailable")
        exc.status = 503
        exc.reason = "Service Unavailable"

        error = operator_main.classify_reconcile_error("run-workflow", exc, default_delay=5)

        self.assertIsInstance(error, operator_main.kopf.TemporaryError)
        self.assertEqual(error.delay, 30)
        self.assertIn("status=503", str(error))

    def test_create_tenant_rejects_operator_namespace(self) -> None:
        logger = Mock()

        with patch.object(operator_main, "OPERATOR_NAMESPACE", "ai-platform"):
            with self.assertRaises(operator_main.kopf.PermanentError):
                operator_main.create_tenant(
                    {"tenantName": "team-a", "namespace": "ai-platform"},
                    "team-a",
                    logger,
                )

        logger.log.assert_called()

    def test_statefulset_manifest_includes_state_volume_init_container(self) -> None:
        manifest = operator_main.create_agent_statefulset_manifest(
            "workspace-assistant",
            "default",
            {
                "model": "gpt-4",
                "runtime": {"kind": "goose", "goose": {}},
                "storage": {"size": "1Gi"},
                "systemPrompt": "Be precise.",
            },
            None,
            {},
        )

        pod_spec = manifest["spec"]["template"]["spec"]

        self.assertEqual(pod_spec["securityContext"]["fsGroup"], 1000)
        self.assertEqual(pod_spec["securityContext"]["runAsGroup"], 1000)

        init_container = pod_spec["initContainers"][0]
        self.assertEqual(init_container["name"], "init-state-volume")
        self.assertEqual(init_container["image"], operator_main.GOOSE_RUNTIME_IMAGE)
        self.assertEqual(init_container["securityContext"]["runAsUser"], 0)
        self.assertEqual(
            init_container["volumeMounts"],
            [{"name": "state-volume", "mountPath": "/app/state"}],
        )
        self.assertIn("chown -R 1000:1000 /app/state", init_container["command"][2])

    def test_statefulset_manifest_includes_a2a_env(self) -> None:
        manifest = operator_main.create_agent_statefulset_manifest(
            "workspace-assistant",
            "default",
            {
                "model": "gpt-4",
                "runtime": {"kind": "langgraph"},
                "storage": {"size": "1Gi"},
                "systemPrompt": "Be precise.",
                "a2a": {
                    "allowedCallers": [
                        {"name": "research-agent", "namespace": "team-a"},
                    ]
                },
            },
            "team-policy",
            {
                "a2a": {
                    "allowedTargets": [
                        {"name": "analysis-agent", "namespace": "team-b"},
                    ],
                    "maxTimeoutSeconds": 45,
                    "requireHitl": True,
                }
            },
        )

        env = {
            item["name"]: item["value"]
            for item in manifest["spec"]["template"]["spec"]["containers"][0]["env"]
            if "value" in item
        }
        env_refs = {
            item["name"]: item["valueFrom"]
            for item in manifest["spec"]["template"]["spec"]["containers"][0]["env"]
            if "valueFrom" in item
        }

        self.assertEqual(
            json.loads(env[operator_main.A2A_ALLOWED_CALLERS_ENV]),
            [{"name": "research-agent", "namespace": "team-a"}],
        )
        self.assertEqual(
            json.loads(env[operator_main.A2A_ALLOWED_TARGETS_ENV]),
            [{"name": "analysis-agent", "namespace": "team-b"}],
        )
        self.assertEqual(env[operator_main.A2A_REQUIRE_HITL_ENV], "true")
        self.assertEqual(env[operator_main.A2A_MAX_TIMEOUT_SECONDS_ENV], "45.0")
        self.assertEqual(
            env["API_GATEWAY_INTERNAL_URL"],
            "http://ai-agent-sandbox-api-gateway.default.svc.cluster.local:8080",
        )
        self.assertEqual(
            env_refs["API_GATEWAY_SHARED_TOKEN"]["secretKeyRef"]["key"],
            "API_GATEWAY_SHARED_TOKEN",
        )

    def test_statefulset_manifest_includes_skill_files_env(self) -> None:
        manifest = operator_main.create_agent_statefulset_manifest(
            "workspace-assistant",
            "default",
            {
                "model": "gpt-4",
                "runtime": {"kind": "langgraph"},
                "storage": {"size": "1Gi"},
                "systemPrompt": "Be precise.",
                "skills": {
                    "files": {
                        ".github/skills/repo-review/SKILL.md": (
                            "---\n"
                            "name: repo-review\n"
                            "description: Review code changes carefully.\n"
                            "allowedSandboxTools:\n"
                            "  - sandbox.filesystem.read\n"
                            "---\n"
                            "Inspect the repository before making changes.\n"
                        )
                    }
                },
            },
            None,
            {},
        )

        env = {
            item["name"]: item["value"]
            for item in manifest["spec"]["template"]["spec"]["containers"][0]["env"]
            if "value" in item
        }

        self.assertIn(operator_main.AGENT_SKILL_FILES_ENV, env)
        self.assertEqual(
            json.loads(env[operator_main.AGENT_SKILL_FILES_ENV]),
            {
                ".github/skills/repo-review/SKILL.md": (
                    "---\n"
                    "name: repo-review\n"
                    "description: Review code changes carefully.\n"
                    "allowedSandboxTools:\n"
                    "  - sandbox.filesystem.read\n"
                    "---\n"
                    "Inspect the repository before making changes.\n"
                )
            },
        )

    def test_a2a_network_policy_manifests_scope_to_named_agents(self) -> None:
        ingress = operator_main.create_a2a_ingress_network_policy_manifest(
            "workspace-assistant",
            "default",
            [{"name": "research-agent", "namespace": "team-a"}],
        )
        egress = operator_main.create_a2a_egress_network_policy_manifest(
            "workspace-assistant",
            "default",
            [{"name": "analysis-agent", "namespace": "team-b"}],
        )

        ingress_sources = ingress["spec"]["ingress"][0]["from"]
        ingress_rule = next(
            peer
            for peer in ingress_sources
            if peer["podSelector"]["matchLabels"].get("agent-name") == "research-agent"
        )
        egress_rule = egress["spec"]["egress"][0]["to"][0]

        self.assertEqual(ingress["metadata"]["labels"]["sandbox.enterprise.ai/policy-type"], "a2a-ingress")
        self.assertEqual(egress["metadata"]["labels"]["sandbox.enterprise.ai/policy-type"], "a2a-egress")
        self.assertTrue(
            any(peer["podSelector"]["matchLabels"].get("app") == "api-gateway" for peer in ingress_sources)
        )
        self.assertTrue(
            any(peer["podSelector"]["matchLabels"].get("app") == "operator-worker" for peer in ingress_sources)
        )
        self.assertEqual(
            ingress_rule["namespaceSelector"]["matchLabels"]["kubernetes.io/metadata.name"],
            "team-a",
        )
        self.assertEqual(ingress_rule["podSelector"]["matchLabels"]["agent-name"], "research-agent")
        self.assertEqual(
            egress_rule["namespaceSelector"]["matchLabels"]["kubernetes.io/metadata.name"],
            "team-b",
        )
        self.assertEqual(egress_rule["podSelector"]["matchLabels"]["agent-name"], "analysis-agent")

    def test_mcp_network_policy_includes_platform_baseline_egress(self) -> None:
        manifest = operator_main.create_mcp_network_policy_manifest("workspace-assistant", "tenant-a", ["github"])
        rules = manifest["spec"]["egress"]

        self.assertTrue(any(rule.get("ports") == [{"protocol": "UDP", "port": 53}, {"protocol": "TCP", "port": 53}] for rule in rules))
        self.assertTrue(
            any(
                rule.get("to", [{}])[0].get("podSelector", {}).get("matchLabels", {}).get("app") == "api-gateway"
                for rule in rules
            )
        )
        self.assertTrue(
            any(
                rule.get("to", [{}])[0].get("podSelector", {}).get("matchLabels", {}).get("app") == "litellm"
                for rule in rules
            )
        )
        self.assertTrue(
            any(
                rule.get("to", [{}])[0].get("podSelector", {}).get("matchLabels", {}).get("app") == "qdrant"
                for rule in rules
            )
        )
        self.assertTrue(
            any(
                rule.get("to", [{}])[0].get("podSelector", {}).get("matchLabels", {}).get("mcp.sandbox.enterprise.ai/type")
                == "github"
                for rule in rules
            )
        )

    def test_runtime_namespace_secret_includes_gateway_token_when_configured(self) -> None:
        logger = Mock()

        with patch.object(operator_main, "SECRET_PROVISIONING_MODE", "native"), patch.object(
            operator_main,
            "DEFAULT_LITELLM_MASTER_KEY",
            "litellm-secret",
        ), patch.object(
            operator_main,
            "DEFAULT_API_GATEWAY_SHARED_TOKEN",
            "gateway-secret",
        ), patch.object(operator_main, "ensure_secret") as ensure_secret:
            operator_main.ensure_runtime_namespace_secret("tenant-a", "workspace-assistant", logger)

        manifest = ensure_secret.call_args.args[1]
        self.assertEqual(manifest["stringData"]["LITELLM_MASTER_KEY"], "litellm-secret")
        self.assertEqual(manifest["stringData"]["API_GATEWAY_SHARED_TOKEN"], "gateway-secret")


if __name__ == "__main__":
    unittest.main()