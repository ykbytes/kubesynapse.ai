import base64
import copy
import importlib
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

# Ensure local references point to the actual installed mocks so that
# isinstance() checks and exception class comparisons work across the
# test file and the implementation modules.
kopf_module = sys.modules["kopf"]
rest_module = sys.modules["kubernetes.client.rest"]

import builders.manifests as _builders_manifests  # noqa: E402
import config as _config  # noqa: E402
import controllers.agent_controller as _agent_ctrl  # noqa: E402
import controllers.tenant_controller as _tenant_ctrl  # noqa: E402
import main as operator_main  # noqa: E402
import reconcile as _reconcile  # noqa: E402
import services.k8s as _services_k8s  # noqa: E402


def _api_exception(status: int) -> Exception:
    exc = rest_module.ApiException(f"status={status}")
    exc.status = status
    return exc


class OperatorManifestTests(unittest.TestCase):
    def test_classify_reconcile_error_marks_4xx_api_failures_permanent(self) -> None:
        exc = rest_module.ApiException("invalid resource")
        exc.status = 422
        exc.reason = "Unprocessable Entity"
        exc.body = '{"error":"invalid"}'

        error = _reconcile.classify_reconcile_error("create-agent", exc, default_delay=7)

        self.assertIsInstance(error, kopf_module.PermanentError)
        self.assertIn("create-agent failed:", str(error))
        self.assertIn("status=422", str(error))
        self.assertIn("reason=Unprocessable Entity", str(error))

    def test_classify_reconcile_error_uses_backoff_for_5xx_api_failures(self) -> None:
        exc = rest_module.ApiException("upstream unavailable")
        exc.status = 503
        exc.reason = "Service Unavailable"

        error = _reconcile.classify_reconcile_error("run-workflow", exc, default_delay=5)

        self.assertIsInstance(error, kopf_module.TemporaryError)
        self.assertEqual(error.delay, 30)
        self.assertIn("status=503", str(error))

    def test_create_tenant_rejects_operator_namespace(self) -> None:
        logger = Mock()

        with patch.object(_tenant_ctrl, "OPERATOR_NAMESPACE", "ai-platform"):  # noqa: SIM117 — nested with for clarity
            with self.assertRaises(kopf_module.PermanentError):
                _tenant_ctrl.create_tenant(
                    {"tenantName": "team-a", "namespace": "ai-platform"},
                    "team-a",
                    logger,
                )

        logger.log.assert_called()

    def test_statefulset_manifest_includes_state_volume_init_container(self) -> None:
        manifest = _builders_manifests.create_agent_statefulset_manifest(
            "workspace-assistant",
            "default",
            {
                "model": "gpt-4",
                "runtime": {"kind": "opencode", "opencode": {}},
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
        self.assertEqual(init_container["image"], _config.OPENCODE_RUNTIME_IMAGE)
        self.assertEqual(init_container["securityContext"]["runAsUser"], 0)
        self.assertEqual(
            init_container["volumeMounts"],
            [{"name": "state-volume", "mountPath": "/app/state"}],
        )
        self.assertIn("set -e;", init_container["command"][2])
        self.assertIn("chown -R 1000:1000 /app/state || true", init_container["command"][2])
        self.assertIn("chmod -R ug+rwX /app/state || true", init_container["command"][2])

    def test_statefulset_manifest_honors_partial_agent_resource_overrides(self) -> None:
        manifest = _builders_manifests.create_agent_statefulset_manifest(
            "workspace-assistant",
            "default",
            {
                "model": "gpt-4",
                "runtime": {"kind": "opencode", "opencode": {}},
                "storage": {"size": "1Gi"},
                "resources": {
                    "requests": {"memory": "512Mi"},
                    "limits": {"memory": "2Gi"},
                },
                "systemPrompt": "Be precise.",
            },
            None,
            {},
        )

        resources = manifest["spec"]["template"]["spec"]["containers"][0]["resources"]

        self.assertEqual(resources["requests"]["cpu"], _config.AGENT_CPU_REQUEST)
        self.assertEqual(resources["requests"]["memory"], "512Mi")
        self.assertEqual(resources["limits"]["cpu"], _config.AGENT_CPU_LIMIT)
        self.assertEqual(resources["limits"]["memory"], "2Gi")

    def test_statefulset_manifest_includes_a2a_env(self) -> None:
        manifest = _builders_manifests.create_agent_statefulset_manifest(
            "workspace-assistant",
            "default",
            {
                "model": "gpt-4",
                "runtime": {"kind": "opencode", "opencode": {}},
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
            json.loads(env[_config.A2A_ALLOWED_CALLERS_ENV]),
            [{"name": "research-agent", "namespace": "team-a"}],
        )
        self.assertEqual(
            json.loads(env[_config.A2A_ALLOWED_TARGETS_ENV]),
            [{"name": "analysis-agent", "namespace": "team-b"}],
        )
        self.assertEqual(env[_config.A2A_REQUIRE_HITL_ENV], "true")
        self.assertEqual(env[_config.A2A_MAX_TIMEOUT_SECONDS_ENV], "45.0")
        self.assertEqual(
            env["API_GATEWAY_INTERNAL_URL"],
            "http://kubesynapse-api-gateway.default.svc.cluster.local:8080",
        )
        self.assertNotIn("API_GATEWAY_SHARED_TOKEN", env_refs)

    def test_statefulset_manifest_prefers_policy_output_token_limit(self) -> None:
        with patch.object(
            _builders_manifests,
            "OPENCODE_RUNTIME_EXTRA_ENV",
            {"OPENCODE_MODEL_OUTPUT_LIMIT": "16384", "OPENCODE_PLAN_THRESHOLD_CHARS": "4096"},
        ):
            manifest = _builders_manifests.create_agent_statefulset_manifest(
                "workspace-assistant",
                "default",
                {
                    "model": "openrouter-gpt-4o-mini",
                    "runtime": {"kind": "opencode", "opencode": {}},
                    "storage": {"size": "1Gi"},
                    "systemPrompt": "Be precise.",
                },
                "budget-policy",
                {"outputGuardrails": {"maxOutputTokens": 64}},
            )

        env_items = [
            item
            for item in manifest["spec"]["template"]["spec"]["containers"][0]["env"]
            if item.get("name") == "OPENCODE_MODEL_OUTPUT_LIMIT"
        ]

        self.assertEqual(env_items, [{"name": "OPENCODE_MODEL_OUTPUT_LIMIT", "value": "64"}])

    def test_statefulset_manifest_includes_skill_files_env(self) -> None:
        manifest = _builders_manifests.create_agent_statefulset_manifest(
            "workspace-assistant",
            "default",
            {
                "model": "gpt-4",
                "runtime": {"kind": "opencode", "opencode": {}},
                "storage": {"size": "1Gi"},
                "systemPrompt": "Be precise.",
                "skills": {
                    "files": {
                        "skills/repo-review/SKILL.md": (
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

        self.assertIn(_config.AGENT_SKILL_FILES_ENV, env)
        self.assertEqual(
            json.loads(env[_config.AGENT_SKILL_FILES_ENV]),
            {
                "skills/repo-review/SKILL.md": (
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

    def test_statefulset_manifest_includes_skill_files_env_detailed(self) -> None:
        manifest = _builders_manifests.create_agent_statefulset_manifest(
            "workspace-assistant",
            "default",
            {
                "model": "gpt-4",
                "runtime": {"kind": "opencode", "opencode": {}},
                "storage": {"size": "1Gi"},
                "systemPrompt": "Be precise.",
                "skills": {
                    "files": {
                        "skills/repo-review/SKILL.md": (
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

        self.assertIn(_config.AGENT_SKILL_FILES_ENV, env)
        self.assertEqual(
            json.loads(env[_config.AGENT_SKILL_FILES_ENV]),
            {
                "skills/repo-review/SKILL.md": (
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

    def test_statefulset_manifest_rejects_duplicate_sidecar_ports(self) -> None:
        with self.assertRaises(operator_main.kopf.PermanentError):
            _builders_manifests.create_agent_statefulset_manifest(
                "workspace-assistant",
                "default",
                {
                    "model": "gpt-4",
                    "runtime": {"kind": "opencode", "opencode": {}},
                    "storage": {"size": "1Gi"},
                    "systemPrompt": "Be precise.",
                    "mcpSidecars": [
                        {"name": "browser", "image": "example/browser:latest", "port": 8081},
                        {"name": "documents", "image": "example/documents:latest", "port": 8081},
                    ],
                },
                None,
                {},
            )

    def test_statefulset_manifest_rejects_reserved_sidecar_port(self) -> None:
        with self.assertRaisesRegex(operator_main.kopf.PermanentError, "reserved"):
            _builders_manifests.create_agent_statefulset_manifest(
                "workspace-assistant",
                "default",
                {
                    "model": "gpt-4",
                    "runtime": {"kind": "opencode", "opencode": {}},
                    "storage": {"size": "1Gi"},
                    "systemPrompt": "Be precise.",
                    "mcpSidecars": [
                        {"name": "browser", "image": "example/browser:latest", "port": 8080},
                    ],
                },
                None,
                {},
            )

    def test_statefulset_manifest_rejects_sidecar_image_with_metacharacters(self) -> None:
        with self.assertRaisesRegex(operator_main.kopf.PermanentError, "invalid characters"):
            _builders_manifests.create_agent_statefulset_manifest(
                "workspace-assistant",
                "default",
                {
                    "model": "gpt-4",
                    "runtime": {"kind": "opencode", "opencode": {}},
                    "storage": {"size": "1Gi"},
                    "systemPrompt": "Be precise.",
                    "mcpSidecars": [
                        {"name": "evil", "image": "example/evil;rm -rf /", "port": 8081},
                    ],
                },
                None,
                {},
            )

    def test_statefulset_manifest_rejects_missing_sidecar_image(self) -> None:
        with self.assertRaises(operator_main.kopf.PermanentError):
            _builders_manifests.create_agent_statefulset_manifest(
                "workspace-assistant",
                "default",
                {
                    "model": "gpt-4",
                    "runtime": {"kind": "opencode", "opencode": {}},
                    "storage": {"size": "1Gi"},
                    "systemPrompt": "Be precise.",
                    "mcpSidecars": [{"name": "browser", "port": 8081}],
                },
                None,
                {},
            )

    def test_statefulset_manifest_rejects_invalid_auto_injected_sidecar_image(self) -> None:
        with patch.dict(_builders_manifests.MCP_SIDECAR_CATALOG, {"browser": {"port": 8081}}, clear=True):  # noqa: SIM117 — nested with for clarity
            with self.assertRaises(operator_main.kopf.PermanentError):
                _builders_manifests.create_agent_statefulset_manifest(
                    "workspace-assistant",
                    "default",
                    {
                        "model": "gpt-4",
                        "runtime": {"kind": "opencode", "opencode": {}},
                        "storage": {"size": "1Gi"},
                        "systemPrompt": "Be precise.",
                        "skills": {
                            "files": {
                                "skills/browser/SKILL.md": (
                                    "---\n"
                                    "name: browser\n"
                                    "allowedMcpServers:\n"
                                    "  - browser\n"
                                    "---\n"
                                    "Use the browser MCP server.\n"
                                )
                            }
                        },
                    },
                    None,
                    {},
                )

    def test_statefulset_manifest_sets_revision_hash_annotation_and_changes_with_storage(self) -> None:
        base_spec = {
            "model": "gpt-4",
            "runtime": {"kind": "opencode", "opencode": {}},
            "storage": {"size": "1Gi"},
            "systemPrompt": "Be precise.",
        }
        updated_spec = {
            "model": "gpt-4",
            "runtime": {"kind": "opencode", "opencode": {}},
            "storage": {"size": "2Gi"},
            "systemPrompt": "Be precise.",
        }

        manifest = _builders_manifests.create_agent_statefulset_manifest(
            "workspace-assistant",
            "default",
            base_spec,
            None,
            {},
        )
        updated_manifest = _builders_manifests.create_agent_statefulset_manifest(
            "workspace-assistant",
            "default",
            updated_spec,
            None,
            {},
        )

        annotations = manifest["spec"]["template"]["metadata"]["annotations"]
        revision = annotations[_builders_manifests.POD_TEMPLATE_REVISION_ANNOTATION]
        updated_revision = updated_manifest["spec"]["template"]["metadata"]["annotations"][
            _builders_manifests.POD_TEMPLATE_REVISION_ANNOTATION
        ]

        self.assertEqual(len(revision), 12)
        self.assertTrue(all(character in "0123456789abcdef" for character in revision))
        self.assertNotEqual(revision, updated_revision)

    def test_a2a_network_policy_manifests_scope_to_named_agents(self) -> None:
        ingress = _builders_manifests.create_a2a_ingress_network_policy_manifest(
            "workspace-assistant",
            "default",
            [{"name": "research-agent", "namespace": "team-a"}],
        )
        egress = _builders_manifests.create_a2a_egress_network_policy_manifest(
            "workspace-assistant",
            "default",
            [{"name": "analysis-agent", "namespace": "team-b"}],
        )

        ingress_sources = ingress["spec"]["ingress"][0]["from"]
        ingress_rule = next(
            peer for peer in ingress_sources if peer["podSelector"]["matchLabels"].get("agent-name") == "research-agent"
        )
        egress_rule = next(
            rule["to"][0]
            for rule in egress["spec"]["egress"]
            if rule.get("to")
            and rule["to"][0].get("podSelector", {}).get("matchLabels", {}).get("agent-name") == "analysis-agent"
        )

        self.assertEqual(ingress["metadata"]["labels"]["kubesynapse.ai/policy-type"], "a2a-ingress")
        self.assertEqual(egress["metadata"]["labels"]["kubesynapse.ai/policy-type"], "a2a-egress")
        self.assertTrue(any(peer["podSelector"]["matchLabels"].get("app") == "api-gateway" for peer in ingress_sources))
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
        manifest = _builders_manifests.create_mcp_network_policy_manifest("workspace-assistant", "tenant-a", ["github"])
        rules = manifest["spec"]["egress"]

        self.assertTrue(
            any(
                rule.get("ports") == [{"protocol": "UDP", "port": 53}, {"protocol": "TCP", "port": 53}]
                for rule in rules
            )
        )
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
                rule.get("to", [{}])[0]
                .get("podSelector", {})
                .get("matchLabels", {})
                .get("mcp.kubesynapse.ai/type")
                == "github"
                for rule in rules
            )
        )

    def test_runtime_namespace_secret_includes_gateway_token_when_configured(self) -> None:
        logger = Mock()

        with (
            patch.object(_services_k8s, "SECRET_PROVISIONING_MODE", "native"),
            patch.object(
                _services_k8s,
                "DEFAULT_LITELLM_MASTER_KEY",
                "litellm-secret",
            ),
            patch.object(
                _services_k8s,
                "DEFAULT_API_GATEWAY_SHARED_TOKEN",
                "gateway-secret",
            ),
            patch.object(_services_k8s, "OPENCODE_IMMUTABLE_CONFIG", False),
            patch.object(_services_k8s, "PI_IMMUTABLE_CONFIG", False),
            patch.object(_services_k8s, "ensure_secret") as ensure_secret,
        ):
            _services_k8s.ensure_runtime_namespace_secret("tenant-a", "workspace-assistant", logger)

        manifest = ensure_secret.call_args.args[1]
        self.assertEqual(manifest["stringData"]["LITELLM_MASTER_KEY"], "litellm-secret")
        self.assertEqual(manifest["stringData"]["API_GATEWAY_SHARED_TOKEN"], "gateway-secret")

    def test_runtime_namespace_secret_provisions_immutable_runtime_config_maps(self) -> None:
        logger = Mock()
        source_opencode_config = {
            "metadata": {
                "name": "kubesynapse-opencode-safe-config",
                "labels": {"app.kubernetes.io/component": "opencode-runtime-config"},
            },
            "immutable": True,
            "data": {"opencode.json": '{"permission":{"bash":"ask"}}'},
        }
        source_pi_config = {
            "metadata": {
                "name": "kubesynapse-pi-safe-config",
                "labels": {"app.kubernetes.io/component": "pi-runtime-config"},
            },
            "immutable": True,
            "data": {"pi-config.json": '{"permissionLevel":"strict"}'},
        }
        core_api = Mock()
        # Mock returns for read_namespaced_config_map:
        # Call 1: source opencode config (operator namespace)
        # Call 2: target opencode config (tenant namespace) - 404
        # Call 3: source pi config (operator namespace)
        # Call 4: target pi config (tenant namespace) - 404
        # Use the ApiException class that k8s.py actually imports (avoids test isolation issues)
        _ApiException = _services_k8s.kubernetes.client.rest.ApiException
        not_found_exc = _ApiException()
        not_found_exc.status = 404
        not_found_exc.reason = "Not Found"
        core_api.read_namespaced_config_map.side_effect = [
            source_opencode_config, not_found_exc,
            source_pi_config, not_found_exc,
        ]

        with (
            patch.object(_services_k8s, "SECRET_PROVISIONING_MODE", "native"),
            patch.object(_services_k8s, "DEFAULT_LITELLM_MASTER_KEY", "litellm-secret"),
            patch.object(_services_k8s, "DEFAULT_API_GATEWAY_SHARED_TOKEN", "gateway-secret"),
            patch.object(_services_k8s, "HELM_RELEASE_NAME", "kubesynapse"),
            patch.object(_services_k8s, "OPERATOR_NAMESPACE", "kubesynapse"),
            patch.object(_services_k8s, "OPENCODE_IMMUTABLE_CONFIG", True),
            patch.object(_services_k8s, "PI_IMMUTABLE_CONFIG", True),
            patch.object(_services_k8s, "ensure_secret") as ensure_secret,
            patch.object(_services_k8s, "ensure_config_map") as ensure_config_map,
            patch.object(_services_k8s.kubernetes.client, "CoreV1Api", return_value=core_api, create=True),
        ):
            _services_k8s.ensure_runtime_namespace_secret("tenant-a", "workspace-assistant", logger)

        secret_manifest = ensure_secret.call_args.args[1]
        self.assertEqual(secret_manifest["metadata"]["namespace"], "tenant-a")
        self.assertEqual(ensure_config_map.call_count, 2)

        config_map_manifests = [call.args[1] for call in ensure_config_map.call_args_list]
        self.assertEqual(
            [manifest["metadata"]["name"] for manifest in config_map_manifests],
            ["kubesynapse-opencode-safe-config", "kubesynapse-pi-safe-config"],
        )
        self.assertTrue(all(manifest["metadata"]["namespace"] == "tenant-a" for manifest in config_map_manifests))
        self.assertTrue(all(manifest["immutable"] is True for manifest in config_map_manifests))
        self.assertEqual(
            config_map_manifests[0]["metadata"]["labels"]["app.kubernetes.io/component"],
            "opencode-runtime-config",
        )
        self.assertEqual(
            config_map_manifests[1]["metadata"]["labels"]["app.kubernetes.io/component"],
            "pi-runtime-config",
        )

    def test_agent_manifests_include_orphan_pruning_owner_labels(self) -> None:
        service_manifest = _builders_manifests.create_agent_service_manifest("workspace-assistant", "default")
        statefulset_manifest = _builders_manifests.create_agent_statefulset_manifest(
            "workspace-assistant",
            "default",
            {
                "model": "gpt-4",
                "runtime": {"kind": "opencode", "opencode": {}},
                "storage": {"size": "1Gi"},
                "systemPrompt": "Be precise.",
            },
            None,
            {},
        )
        mcp_policy = _builders_manifests.create_mcp_network_policy_manifest(
            "workspace-assistant", "default", ["github"]
        )
        a2a_egress = _builders_manifests.create_a2a_egress_network_policy_manifest("workspace-assistant", "default", [])
        a2a_ingress = _builders_manifests.create_a2a_ingress_network_policy_manifest(
            "workspace-assistant", "default", []
        )

        manifests = [
            service_manifest,
            statefulset_manifest,
            mcp_policy,
            a2a_egress,
            a2a_ingress,
        ]

        for manifest in manifests:
            labels = manifest["metadata"]["labels"]
            self.assertEqual(labels["kubesynapse.ai/managed-by"], "operator")
            self.assertEqual(labels["kubesynapse.ai/agent-name"], "workspace-assistant")

        template_labels = statefulset_manifest["spec"]["template"]["metadata"]["labels"]
        self.assertEqual(template_labels["kubesynapse.ai/managed-by"], "operator")
        self.assertEqual(template_labels["kubesynapse.ai/agent-name"], "workspace-assistant")

    def test_agent_service_targets_public_port_not_container_name(self) -> None:
        manifest = _builders_manifests.create_agent_service_manifest("workspace-assistant", "default")

        self.assertEqual(manifest["spec"]["ports"], [{"name": "http", "port": 8080, "targetPort": 8080}])


class StatefulSetReconcileTests(unittest.TestCase):
    def test_ensure_statefulset_preserves_immutable_fields_and_resizes_pvc(self) -> None:
        with patch.object(_builders_manifests, "CREDENTIAL_PROXY_ENABLED", False):
            current_manifest = _builders_manifests.create_agent_statefulset_manifest(
                "workspace-assistant",
                "default",
                {
                    "model": "gpt-4",
                    "runtime": {"kind": "opencode", "opencode": {}},
                    "storage": {"size": "1Gi"},
                    "systemPrompt": "Use opencode.",
                },
                None,
                {},
            )
            desired_manifest = _builders_manifests.create_agent_statefulset_manifest(
                "workspace-assistant",
                "default",
                {
                    "model": "gpt-4",
                    "runtime": {"kind": "opencode", "opencode": {"configFiles": {"opencode.json": {"default_agent": "build"}}}},
                    "storage": {"size": "4Gi"},
                    "systemPrompt": "Use opencode with sidecars.",
                    "mcpSidecars": [{"name": "browser", "image": "example/browser:latest", "port": 8081}],
                },
                None,
                {},
            )
        reconciled_manifest = copy.deepcopy(desired_manifest)
        reconciled_manifest["spec"]["volumeClaimTemplates"] = current_manifest["spec"]["volumeClaimTemplates"]

        apps_api = Mock()
        apps_api.create_namespaced_stateful_set.side_effect = _api_exception(409)
        apps_api.read_namespaced_stateful_set.side_effect = [current_manifest, reconciled_manifest]

        core_api = Mock()
        core_api.read_namespaced_persistent_volume_claim.return_value = {
            "spec": {"resources": {"requests": {"storage": "1Gi"}}}
        }

        with (
            patch.object(_services_k8s.kubernetes.client, "AppsV1Api", return_value=apps_api, create=True),
            patch.object(
                _services_k8s.kubernetes.client,
                "CoreV1Api",
                return_value=core_api,
                create=True,
            ),
        ):
            _services_k8s.ensure_statefulset("default", desired_manifest)

        patched_statefulset = apps_api.patch_namespaced_stateful_set.call_args.kwargs["body"]
        self.assertEqual(
            apps_api.patch_namespaced_stateful_set.call_args.kwargs["_content_type"],
            "application/merge-patch+json",
        )
        self.assertEqual(
            patched_statefulset["spec"]["volumeClaimTemplates"][0]["spec"]["resources"]["requests"]["storage"],
            "1Gi",
        )
        self.assertEqual(patched_statefulset["spec"]["template"]["metadata"]["labels"]["runtime-kind"], "opencode")
        self.assertEqual(
            patched_statefulset["spec"]["template"]["metadata"]["annotations"][
                _builders_manifests.POD_TEMPLATE_REVISION_ANNOTATION
            ],
            desired_manifest["spec"]["template"]["metadata"]["annotations"][
                _builders_manifests.POD_TEMPLATE_REVISION_ANNOTATION
            ],
        )
        self.assertEqual(
            patched_statefulset["spec"]["template"]["spec"]["containers"][0]["image"],
            _config.OPENCODE_RUNTIME_IMAGE,
        )
        self.assertEqual(patched_statefulset["spec"]["template"]["spec"]["containers"][1]["name"], "mcp-browser")

        pvc_patch = core_api.patch_namespaced_persistent_volume_claim.call_args.kwargs
        self.assertEqual(pvc_patch["name"], "state-volume-workspace-assistant-sandbox-0")
        self.assertEqual(pvc_patch["namespace"], "default")
        self.assertEqual(pvc_patch["body"]["spec"]["resources"]["requests"]["storage"], "4Gi")

    def test_ensure_statefulset_falls_back_to_low_level_merge_patch_when_client_rejects_content_type(self) -> None:
        desired_manifest = _builders_manifests.create_agent_statefulset_manifest(
            "workspace-assistant",
            "default",
            {
                "model": "gpt-4",
                "runtime": {"kind": "opencode", "opencode": {}},
                "storage": {"size": "1Gi"},
                "systemPrompt": "Use opencode.",
            },
            None,
            {},
        )

        apps_api = Mock()
        apps_api.create_namespaced_stateful_set.side_effect = _api_exception(409)
        apps_api.patch_namespaced_stateful_set.side_effect = _services_k8s.ApiTypeError("unsupported kwarg")
        apps_api.read_namespaced_stateful_set.side_effect = [desired_manifest, desired_manifest]
        apps_api.api_client = Mock()
        apps_api.api_client.select_header_accept.return_value = "application/json"

        core_api = Mock()
        core_api.read_namespaced_persistent_volume_claim.return_value = {
            "spec": {"resources": {"requests": {"storage": "1Gi"}}}
        }

        with (
            patch.object(_services_k8s.kubernetes.client, "AppsV1Api", return_value=apps_api, create=True),
            patch.object(
                _services_k8s.kubernetes.client,
                "CoreV1Api",
                return_value=core_api,
                create=True,
            ),
        ):
            _services_k8s.ensure_statefulset("default", desired_manifest)

        apps_api.patch_namespaced_stateful_set.assert_called_once()
        low_level_patch = apps_api.api_client.call_api.call_args
        self.assertEqual(low_level_patch.args[0], "/apis/apps/v1/namespaces/{namespace}/statefulsets/{name}")
        self.assertEqual(low_level_patch.args[1], "PATCH")
        self.assertEqual(low_level_patch.args[2], {"name": "workspace-assistant-sandbox", "namespace": "default"})
        self.assertEqual(low_level_patch.args[4]["Content-Type"], "application/merge-patch+json")
        self.assertEqual(low_level_patch.kwargs["body"]["metadata"]["name"], "workspace-assistant-sandbox")

    def test_ensure_statefulset_accepts_live_template_with_defaulted_tcp_protocols(self) -> None:
        desired_manifest = _builders_manifests.create_agent_statefulset_manifest(
            "workspace-assistant",
            "default",
            {
                "model": "gpt-4",
                "runtime": {"kind": "opencode", "opencode": {}},
                "storage": {"size": "1Gi"},
                "systemPrompt": "Use opencode.",
                "mcpSidecars": [{"name": "browser", "image": "example/browser:latest", "port": 8081}],
            },
            None,
            {},
        )
        current_manifest = copy.deepcopy(desired_manifest)
        reconciled_manifest = copy.deepcopy(desired_manifest)

        for container in reconciled_manifest["spec"]["template"]["spec"]["containers"]:
            for port in container.get("ports") or []:
                port.setdefault("protocol", "TCP")

        apps_api = Mock()
        apps_api.create_namespaced_stateful_set.side_effect = _api_exception(409)
        apps_api.read_namespaced_stateful_set.side_effect = [current_manifest, reconciled_manifest]

        core_api = Mock()
        core_api.read_namespaced_persistent_volume_claim.return_value = {
            "spec": {"resources": {"requests": {"storage": "1Gi"}}}
        }

        with (
            patch.object(_services_k8s.kubernetes.client, "AppsV1Api", return_value=apps_api, create=True),
            patch.object(
                _services_k8s.kubernetes.client,
                "CoreV1Api",
                return_value=core_api,
                create=True,
            ),
        ):
            _services_k8s.ensure_statefulset("default", desired_manifest)

        apps_api.patch_namespaced_stateful_set.assert_called_once()
        core_api.patch_namespaced_persistent_volume_claim.assert_not_called()


class OrphanPruningTests(unittest.TestCase):
    def test_prune_orphaned_resources_deletes_only_non_desired_resources(self) -> None:
        networking_api = Mock()
        core_api = Mock()

        networking_api.list_namespaced_network_policy.return_value = {
            "items": [
                {"metadata": {"name": "workspace-assistant-sandbox-mcp-egress"}},
                {"metadata": {"name": "workspace-assistant-sandbox-old-egress"}},
            ]
        }
        core_api.list_namespaced_service.return_value = {
            "items": [
                {"metadata": {"name": "workspace-assistant-sandbox"}},
                {"metadata": {"name": "workspace-assistant-legacy-svc"}},
            ]
        }
        core_api.list_namespaced_secret.return_value = {
            "items": [
                {"metadata": {"name": "workspace-assistant-unused-secret"}},
            ]
        }

        desired_names = {
            "workspace-assistant-sandbox",
            "workspace-assistant-sandbox-mcp-egress",
        }

        with (
            patch.object(_services_k8s, "ORPHAN_PRUNING_ENABLED", True),
            patch.object(
                _services_k8s.kubernetes.client,
                "NetworkingV1Api",
                return_value=networking_api,
                create=True,
            ),
            patch.object(
                _services_k8s.kubernetes.client,
                "CoreV1Api",
                return_value=core_api,
                create=True,
            ),
        ):
            pruned = _services_k8s.prune_orphaned_resources("default", "workspace-assistant", desired_names)

        self.assertEqual(
            sorted(pruned),
            [
                "workspace-assistant-legacy-svc",
                "workspace-assistant-sandbox-old-egress",
                "workspace-assistant-unused-secret",
            ],
        )
        networking_api.delete_namespaced_network_policy.assert_called_once_with(
            name="workspace-assistant-sandbox-old-egress",
            namespace="default",
        )
        core_api.delete_namespaced_service.assert_called_once_with(
            name="workspace-assistant-legacy-svc",
            namespace="default",
        )
        core_api.delete_namespaced_secret.assert_called_once_with(
            name="workspace-assistant-unused-secret",
            namespace="default",
        )
        expected_selector = (
            "kubesynapse.ai/managed-by=operator,kubesynapse.ai/agent-name=workspace-assistant"
        )
        self.assertEqual(
            networking_api.list_namespaced_network_policy.call_args.kwargs["label_selector"],
            expected_selector,
        )

    def test_prune_orphaned_resources_returns_empty_when_disabled(self) -> None:
        with patch.object(_services_k8s, "ORPHAN_PRUNING_ENABLED", False):
            pruned = _services_k8s.prune_orphaned_resources("default", "workspace-assistant", {"keep-me"})

        self.assertEqual(pruned, [])


class AgentControllerTests(unittest.TestCase):
    def test_create_agent_resources_prunes_after_reconcile(self) -> None:
        logger = Mock()
        outputs = Mock()
        outputs.policy_name = None
        outputs.allowed_mcp_servers = []
        outputs.has_tenant = False
        outputs.runtime_kind = "opencode"
        outputs.mcp_auth_secret = None
        outputs.provider_bootstrap_secret = None
        outputs.service = {"metadata": {"name": "workspace-assistant-sandbox"}}
        outputs.statefulset = {"metadata": {"name": "workspace-assistant-sandbox"}}
        outputs.mcp_network_policy = {"metadata": {"name": "workspace-assistant-sandbox-mcp-egress"}}
        outputs.a2a_egress_network_policy = {"metadata": {"name": "workspace-assistant-sandbox-a2a-egress"}}
        outputs.a2a_ingress_network_policy = {"metadata": {"name": "workspace-assistant-sandbox-a2a-ingress"}}
        outputs.owned_manifests.return_value = [outputs.service, outputs.statefulset]
        outputs.desired_resource_names.return_value = {
            "workspace-assistant-sandbox",
            "workspace-assistant-sandbox-mcp-egress",
            "workspace-assistant-sandbox-a2a-egress",
            "workspace-assistant-sandbox-a2a-ingress",
        }

        with (
            patch.object(_agent_ctrl, "ensure_runtime_access") as ensure_runtime_access,
            patch.object(
                _agent_ctrl,
                "ensure_runtime_namespace_secret",
            ) as ensure_runtime_namespace_secret,
            patch.object(
                _agent_ctrl,
                "resolve_agent_policy",
                return_value=(None, {}),
            ),
            patch.object(
                _agent_ctrl,
                "resolve_tenant_for_namespace",
                return_value=None,
            ),
            patch.object(
                _agent_ctrl,
                "validate_agent_model",
            ) as validate_agent_model,
            patch.object(
                _agent_ctrl,
                "translate_agent",
                return_value=outputs,
            ),
            patch.object(
                _agent_ctrl.kopf,
                "adopt",
            ) as adopt,
            patch.object(
                _agent_ctrl,
                "ensure_service",
            ) as ensure_service,
            patch.object(
                _agent_ctrl,
                "ensure_statefulset",
            ) as ensure_statefulset,
            patch.object(
                _agent_ctrl,
                "ensure_network_policy",
            ) as ensure_network_policy,
            patch.object(
                _agent_ctrl,
                "prune_orphaned_resources",
                return_value=["workspace-assistant-legacy-svc"],
            ) as prune_orphaned_resources,
            patch.object(
                _agent_ctrl,
                "log_operator_event",
            ) as log_operator_event,
            patch.object(
                _agent_ctrl,
                "_validate_agent_dependencies",
                return_value=[],
            ),
            patch.object(
                _agent_ctrl,
                "_record_agent_event",
            ),
            patch.object(
                _agent_ctrl,
                "_patch_agent_status",
            ),
            patch.object(
                _agent_ctrl,
                "_check_revision_change",
                return_value=False,
            ),
            patch.object(
                _agent_ctrl,
                "_verify_reconcile_idempotency",
            ),
        ):
            _agent_ctrl.create_agent_resources(
                {"model": "gpt-4", "runtime": {"kind": "opencode"}},
                "workspace-assistant",
                "default",
                logger,
            )

        ensure_runtime_access.assert_called_once_with("default")
        ensure_runtime_namespace_secret.assert_called_once_with("default", "workspace-assistant", logger)
        validate_agent_model.assert_called_once_with("gpt-4", {}, None)
        adopt.assert_any_call(outputs.service)
        adopt.assert_any_call(outputs.statefulset)
        ensure_service.assert_called_once_with("default", outputs.service)
        ensure_statefulset.assert_called_once_with("default", outputs.statefulset)
        self.assertEqual(ensure_network_policy.call_count, 3)
        prune_orphaned_resources.assert_called_once_with(
            "default",
            "workspace-assistant",
            outputs.desired_resource_names.return_value,
        )
        self.assertEqual(log_operator_event.call_count, 2)

    def test_create_agent_resources_rejects_blank_model(self) -> None:
        logger = Mock()

        with (
            patch.object(_agent_ctrl, "ensure_runtime_access"),
            patch.object(_agent_ctrl, "ensure_runtime_namespace_secret"),
            patch.object(_agent_ctrl, "resolve_agent_policy", return_value=(None, {})),
            patch.object(_agent_ctrl, "resolve_tenant_for_namespace", return_value=None),
            patch.object(_agent_ctrl, "validate_agent_cross_namespace_targets"),
            patch.object(_agent_ctrl, "_validate_agent_dependencies", return_value=[]),
            patch.object(_agent_ctrl, "_record_agent_event"),
            patch.object(_agent_ctrl, "_patch_agent_status"),
            patch.object(_agent_ctrl, "_check_revision_change", return_value=False),
            patch.object(_agent_ctrl, "_verify_reconcile_idempotency"),
            self.assertRaises(kopf_module.PermanentError) as context,
        ):
            _agent_ctrl.create_agent_resources(
                {"model": "   ", "runtime": {"kind": "opencode"}},
                "workspace-assistant",
                "default",
                logger,
            )

        self.assertIn("spec.model", str(context.exception))

    def test_compute_revision_hash_is_deterministic(self) -> None:
        spec = {"model": "gpt-4", "runtime": {"kind": "opencode"}, "mcpServers": [], "mcpSidecars": []}
        hash1 = _agent_ctrl._compute_revision_hash(spec)
        hash2 = _agent_ctrl._compute_revision_hash(spec)
        self.assertEqual(hash1, hash2)

    def test_compute_revision_hash_changes_with_model(self) -> None:
        spec1 = {"model": "gpt-4", "runtime": {"kind": "opencode"}}
        spec2 = {"model": "gpt-3.5", "runtime": {"kind": "opencode"}}
        self.assertNotEqual(_agent_ctrl._compute_revision_hash(spec1), _agent_ctrl._compute_revision_hash(spec2))

    def test_parse_quantity_handles_units(self) -> None:
        self.assertAlmostEqual(_agent_ctrl._parse_quantity("100m"), 0.1)
        self.assertAlmostEqual(_agent_ctrl._parse_quantity("1"), 1.0)
        self.assertAlmostEqual(_agent_ctrl._parse_quantity("1.5"), 1.5)
        self.assertAlmostEqual(_agent_ctrl._parse_quantity("1Gi"), 1024.0)
        self.assertAlmostEqual(_agent_ctrl._parse_quantity("512Mi"), 512.0)

    def test_config_map_hash_computation(self) -> None:
        from services.k8s import _compute_config_map_hash
        data1 = {"opencode.json": '{"permission":{"bash":"ask"}}'}
        data2 = {"opencode.json": '{"permission":{"bash":"free"}}'}
        hash1 = _compute_config_map_hash(data1, None)
        hash2 = _compute_config_map_hash(data2, None)
        self.assertNotEqual(hash1, hash2)
        self.assertEqual(_compute_config_map_hash(data1, None), _compute_config_map_hash(data1, None))


class OptionalCrdWatchingTests(unittest.TestCase):
    def test_crd_exists_returns_true_for_matching_version(self) -> None:
        api = Mock()
        api.read_custom_resource_definition.return_value = {
            "spec": {"versions": [{"name": "v1alpha1"}, {"name": "v1beta1"}]}
        }

        with patch.object(_services_k8s.kubernetes.client, "ApiextensionsV1Api", return_value=api, create=True):
            exists = _services_k8s.crd_exists("kubesynapse.ai", "v1alpha1", "agentpolicies")

        self.assertTrue(exists)
        api.read_custom_resource_definition.assert_called_once_with(name="agentpolicies.kubesynapse.ai")

    def test_crd_exists_returns_false_for_missing_crd(self) -> None:
        api = Mock()
        api.read_custom_resource_definition.side_effect = _api_exception(404)

        with patch.object(_services_k8s.kubernetes.client, "ApiextensionsV1Api", return_value=api, create=True):
            exists = _services_k8s.crd_exists("kubesynapse.ai", "v1alpha1", "agentpolicies")

        self.assertFalse(exists)

    def test_controllers_package_skips_optional_modules_when_crds_missing(self) -> None:
        imported: list[str] = []
        real_import_module = importlib.import_module

        def fake_import(name: str):
            if name == "controllers":
                return real_import_module(name)
            imported.append(name)
            return types.SimpleNamespace(__name__=name)

        def fake_crd_exists(group: str, version: str, plural: str) -> bool:
            del group, version
            return plural == "agentpolicies"

        sys.modules.pop("controllers", None)

        with (
            patch("services.crd_exists", side_effect=fake_crd_exists),
            patch("importlib.import_module", side_effect=fake_import),
        ):
            controllers_pkg = importlib.import_module("controllers")

        self.assertEqual(controllers_pkg.__name__, "controllers")
        self.assertIn("controllers.agent_controller", imported)
        self.assertIn("controllers.workflow_controller", imported)
        self.assertIn("controllers.status_projection", imported)
        self.assertIn("controllers.policy_controller", imported)
        self.assertNotIn("controllers.approval_controller", imported)
        self.assertNotIn("controllers.tenant_controller", imported)
        sys.modules.pop("controllers", None)


class AllowedNamespacesTests(unittest.TestCase):
    def test_validate_cross_namespace_ref_allows_same_namespace(self) -> None:
        _reconcile.validate_cross_namespace_ref(
            source_namespace="team-a",
            target_namespace="team-a",
            allowed_namespaces=None,
            field_path="AIAgent.spec.policyRef",
            target_kind="AgentPolicy",
        )

    def test_validate_cross_namespace_ref_blocks_cross_namespace_by_default(self) -> None:
        with self.assertRaises(kopf_module.PermanentError):
            _reconcile.validate_cross_namespace_ref(
                source_namespace="team-a",
                target_namespace="shared-policies",
                allowed_namespaces=None,
                field_path="AIAgent.spec.policyRef",
                target_kind="AgentPolicy",
            )

    def test_validate_cross_namespace_ref_allows_all_mode(self) -> None:
        _reconcile.validate_cross_namespace_ref(
            source_namespace="team-a",
            target_namespace="shared-policies",
            allowed_namespaces={"from": "All"},
            field_path="AIAgent.spec.policyRef",
            target_kind="AgentPolicy",
        )

    def test_validate_cross_namespace_ref_allows_selector_match_names(self) -> None:
        _reconcile.validate_cross_namespace_ref(
            source_namespace="team-a",
            target_namespace="shared-policies",
            allowed_namespaces={"from": "Selector", "selector": {"matchNames": ["team-a", "team-b"]}},
            field_path="AIAgent.spec.policyRef",
            target_kind="AgentPolicy",
        )

    def test_resolve_agent_policy_supports_namespace_name_ref_when_allowed(self) -> None:
        custom_api = Mock()
        custom_api.get_namespaced_custom_object.return_value = {
            "metadata": {"name": "shared-policy", "namespace": "shared-policies"},
            "spec": {"allowedNamespaces": {"from": "All"}, "allowedModels": ["gpt-4"]},
        }

        with patch.object(_agent_ctrl.kubernetes.client, "CustomObjectsApi", return_value=custom_api, create=True):
            policy_name, policy_spec = _agent_ctrl.resolve_agent_policy("team-a", "shared-policies/shared-policy")

        self.assertEqual(policy_name, "shared-policy")
        self.assertEqual(policy_spec["allowedModels"], ["gpt-4"])
        self.assertEqual(custom_api.get_namespaced_custom_object.call_args.kwargs["namespace"], "shared-policies")
        self.assertEqual(custom_api.get_namespaced_custom_object.call_args.kwargs["name"], "shared-policy")

    def test_resolve_agent_policy_blocks_cross_namespace_ref_by_default(self) -> None:
        custom_api = Mock()
        custom_api.get_namespaced_custom_object.return_value = {
            "metadata": {"name": "shared-policy", "namespace": "shared-policies"},
            "spec": {"allowedModels": ["gpt-4"]},
        }

        with patch.object(_agent_ctrl.kubernetes.client, "CustomObjectsApi", return_value=custom_api, create=True):  # noqa: SIM117 — nested with for clarity
            with self.assertRaises(kopf_module.PermanentError):
                _agent_ctrl.resolve_agent_policy("team-a", "shared-policies/shared-policy")

    def test_validate_agent_cross_namespace_targets_blocks_cross_namespace_by_default(self) -> None:
        with self.assertRaises(kopf_module.PermanentError):
            _agent_ctrl.validate_agent_cross_namespace_targets(
                {},
                {
                    "a2a": {
                        "allowedTargets": [
                            {"name": "reviewer", "namespace": "shared-agents"},
                        ]
                    }
                },
                "team-a",
            )

    def test_validate_agent_cross_namespace_targets_allows_all_mode(self) -> None:
        _agent_ctrl.validate_agent_cross_namespace_targets(
            {"allowedNamespaces": {"from": "All"}},
            {
                "a2a": {
                    "allowedTargets": [
                        {"name": "reviewer", "namespace": "shared-agents"},
                    ]
                }
            },
            "team-a",
        )

    def test_ensure_statefulset_raises_when_pvc_resize_is_forbidden(self) -> None:
        current_manifest = _builders_manifests.create_agent_statefulset_manifest(
            "workspace-assistant",
            "default",
            {
                "model": "gpt-4",
                "runtime": {"kind": "opencode", "opencode": {}},
                "storage": {"size": "1Gi"},
                "systemPrompt": "Use opencode.",
            },
            None,
            {},
        )
        desired_manifest = _builders_manifests.create_agent_statefulset_manifest(
            "workspace-assistant",
            "default",
            {
                "model": "gpt-4",
                "runtime": {"kind": "opencode", "opencode": {"configFiles": {"opencode.json": {"default_agent": "build"}}}},
                "storage": {"size": "4Gi"},
                "systemPrompt": "Use opencode.",
            },
            None,
            {},
        )
        reconciled_manifest = copy.deepcopy(desired_manifest)
        reconciled_manifest["spec"]["volumeClaimTemplates"] = current_manifest["spec"]["volumeClaimTemplates"]

        apps_api = Mock()
        apps_api.create_namespaced_stateful_set.side_effect = _api_exception(409)
        apps_api.read_namespaced_stateful_set.side_effect = [current_manifest, reconciled_manifest]

        core_api = Mock()
        core_api.read_namespaced_persistent_volume_claim.return_value = {
            "spec": {"resources": {"requests": {"storage": "1Gi"}}}
        }
        core_api.patch_namespaced_persistent_volume_claim.side_effect = _api_exception(403)

        with (
            patch.object(_services_k8s.kubernetes.client, "AppsV1Api", return_value=apps_api, create=True),
            patch.object(
                _services_k8s.kubernetes.client,
                "CoreV1Api",
                return_value=core_api,
                create=True,
            ),self.assertRaises(operator_main.kopf.PermanentError)
        ):
            _services_k8s.ensure_statefulset("default", desired_manifest)

        apps_api.patch_namespaced_stateful_set.assert_called_once()
        core_api.patch_namespaced_persistent_volume_claim.assert_called_once()
        pvc_patch = core_api.patch_namespaced_persistent_volume_claim.call_args.kwargs
        self.assertEqual(pvc_patch["name"], "state-volume-workspace-assistant-sandbox-0")
        self.assertEqual(pvc_patch["namespace"], "default")
        self.assertEqual(pvc_patch["body"]["spec"]["resources"]["requests"]["storage"], "4Gi")

    def test_ensure_statefulset_raises_when_live_template_keeps_removed_sidecar(self) -> None:
        current_manifest = _builders_manifests.create_agent_statefulset_manifest(
            "workspace-assistant",
            "default",
            {
                "model": "gpt-4",
                "runtime": {"kind": "opencode", "opencode": {}},
                "storage": {"size": "1Gi"},
                "systemPrompt": "Use opencode.",
                "mcpSidecars": [
                    {"name": "browser", "image": "example/browser:latest", "port": 8081},
                    {"name": "documents", "image": "example/documents:latest", "port": 8092},
                ],
            },
            None,
            {},
        )
        desired_manifest = _builders_manifests.create_agent_statefulset_manifest(
            "workspace-assistant",
            "default",
            {
                "model": "gpt-4",
                "runtime": {"kind": "opencode", "opencode": {}},
                "storage": {"size": "1Gi"},
                "systemPrompt": "Use opencode.",
                "mcpSidecars": [{"name": "browser", "image": "example/browser:latest", "port": 8081}],
            },
            None,
            {},
        )

        apps_api = Mock()
        apps_api.create_namespaced_stateful_set.side_effect = _api_exception(409)
        apps_api.read_namespaced_stateful_set.side_effect = [current_manifest, current_manifest]

        core_api = Mock()

        with (
            patch.object(_services_k8s.kubernetes.client, "AppsV1Api", return_value=apps_api, create=True),
            patch.object(
                _services_k8s.kubernetes.client,
                "CoreV1Api",
                return_value=core_api,
                create=True,
            ),self.assertRaises(operator_main.kopf.TemporaryError)
        ):
            _services_k8s.ensure_statefulset("default", desired_manifest)

        apps_api.patch_namespaced_stateful_set.assert_called_once()
        core_api.patch_namespaced_persistent_volume_claim.assert_not_called()

    def test_ensure_statefulset_skips_pvc_shrink_requests(self) -> None:
        current_manifest = _builders_manifests.create_agent_statefulset_manifest(
            "workspace-assistant",
            "default",
            {
                "model": "gpt-4",
                "runtime": {"kind": "opencode", "opencode": {}},
                "storage": {"size": "4Gi"},
                "systemPrompt": "Original prompt.",
            },
            None,
            {},
        )
        desired_manifest = _builders_manifests.create_agent_statefulset_manifest(
            "workspace-assistant",
            "default",
            {
                "model": "gpt-4",
                "runtime": {"kind": "opencode", "opencode": {}},
                "storage": {"size": "1Gi"},
                "systemPrompt": "Updated prompt.",
            },
            None,
            {},
        )
        reconciled_manifest = copy.deepcopy(desired_manifest)
        reconciled_manifest["spec"]["volumeClaimTemplates"] = current_manifest["spec"]["volumeClaimTemplates"]

        apps_api = Mock()
        apps_api.create_namespaced_stateful_set.side_effect = _api_exception(409)
        apps_api.read_namespaced_stateful_set.side_effect = [current_manifest, reconciled_manifest]

        core_api = Mock()
        core_api.read_namespaced_persistent_volume_claim.return_value = {
            "spec": {"resources": {"requests": {"storage": "4Gi"}}}
        }

        with (
            patch.object(_services_k8s.kubernetes.client, "AppsV1Api", return_value=apps_api, create=True),
            patch.object(
                _services_k8s.kubernetes.client,
                "CoreV1Api",
                return_value=core_api,
                create=True,
            ),
        ):
            _services_k8s.ensure_statefulset("default", desired_manifest)

        apps_api.patch_namespaced_stateful_set.assert_called_once()
        core_api.patch_namespaced_persistent_volume_claim.assert_not_called()

    def test_opencode_statefulset_manifest_includes_runtime_env_and_sidecars(self) -> None:
        sidecars = [{"name": "browser", "image": "example/browser:latest", "port": 8081}]
        with patch.object(_builders_manifests, "CREDENTIAL_PROXY_ENABLED", False):
            manifest = _builders_manifests.create_agent_statefulset_manifest(
                "workspace-assistant",
                "default",
                {
                    "model": "gpt-4",
                    "runtime": {
                        "kind": "opencode",
                        "opencode": {
                            "configFiles": {
                                "agents/reviewer.md": "---\ndescription: Review only\nmode: subagent\n---\nReview conservatively."
                            }
                        },
                    },
                    "storage": {"size": "1Gi"},
                    "systemPrompt": "Be precise.",
                    "mcpServers": ["documents"],
                    "mcpSidecars": sidecars,
                },
                None,
                {},
            )

        pod_spec = manifest["spec"]["template"]["spec"]
        env = {item["name"]: item.get("value") for item in pod_spec["containers"][0]["env"] if "value" in item}
        env_refs = {
            item["name"]: item.get("valueFrom") for item in pod_spec["containers"][0]["env"] if "valueFrom" in item
        }
        container_names = [item["name"] for item in pod_spec["containers"]]

        self.assertEqual(pod_spec["containers"][0]["image"], _config.OPENCODE_RUNTIME_IMAGE)
        self.assertEqual(env["OPENCODE_PROVIDER"], "litellm")  # "gpt-4" has no slash -> falls back to default
        self.assertEqual(env["OPENCODE_MODEL"], "gpt-4")
        self.assertEqual(env["MCP_SERVERS"], "documents")
        self.assertEqual(env["HELM_RELEASE_NAME"], _config.HELM_RELEASE_NAME)
        self.assertIn("agents/reviewer.md", json.loads(env[_config.OPENCODE_RUNTIME_CONFIG_FILES_ENV]))
        self.assertEqual(json.loads(env[_config.OPENCODE_MCP_SIDECARS_ENV]), sidecars)
        self.assertEqual(
            env_refs["MCP_BEARER_TOKEN"]["secretKeyRef"]["key"],
            "bearer-token",
        )
        self.assertIn("mcp-browser", container_names)

    def test_opencode_runtime_manifest_makes_hub_bearer_optional_for_saved_remote_mcp_connections(self) -> None:
        with patch.object(_builders_manifests, "CREDENTIAL_PROXY_ENABLED", False):
            manifest = _builders_manifests.create_agent_statefulset_manifest(
                "workspace-assistant",
                "default",
                {
                    "model": "gpt-4",
                    "runtime": {"kind": "opencode"},
                    "storage": {"size": "1Gi"},
                    "systemPrompt": "Be precise.",
                    "mcpConnections": [
                        {
                            "connectionId": "conn-docs",
                            "serverId": "microsoft-learn",
                            "transport": "remote",
                            "runtime": {
                                "kind": "remote",
                                "configKey": "microsoft-learn",
                                "url": "https://learn.microsoft.com/api/mcp",
                                "headers": [],
                            },
                        }
                    ],
                    "mcpServers": ["microsoft-learn"],
                },
                None,
                {},
            )

        env_refs = {
            item["name"]: item.get("valueFrom") for item in manifest["spec"]["template"]["spec"]["containers"][0]["env"] if "valueFrom" in item
        }
        env_values = {
            item["name"]: item.get("value") for item in manifest["spec"]["template"]["spec"]["containers"][0]["env"] if "value" in item
        }

        self.assertEqual(
            env_refs["MCP_BEARER_TOKEN"]["secretKeyRef"]["optional"],
            True,
        )
        self.assertIn(_config.OPENCODE_MCP_CONNECTIONS_ENV, env_values)

    def test_opencode_runtime_rejects_shared_github_adapter_config(self) -> None:
        with self.assertRaises(operator_main.kopf.PermanentError) as context:
            _builders_manifests.create_agent_statefulset_manifest(
                "workspace-assistant",
                "default",
                {
                    "model": "gpt-4",
                    "runtime": {"kind": "opencode"},
                    "storage": {"size": "1Gi"},
                    "systemPrompt": "Be precise.",
                    "githubConfig": {"credentialSecretRef": "github-creds"},
                },
                None,
                {},
            )

        self.assertIn("sidecar-based GitHub MCP", str(context.exception))

    def test_opencode_runtime_manifest_requires_explicit_model(self) -> None:
        with self.assertRaises(operator_main.kopf.PermanentError) as context:
            _builders_manifests.create_agent_statefulset_manifest(
                "workspace-assistant",
                "default",
                {
                    "model": "   ",
                    "runtime": {"kind": "opencode"},
                    "storage": {"size": "1Gi"},
                    "systemPrompt": "Be precise.",
                },
                None,
                {},
            )

        self.assertIn("spec.model", str(context.exception))

    def test_build_provider_auth_content_encodes_copilot_as_oauth(self) -> None:
        auth_content = _builders_manifests._build_provider_auth_content(
            {
                "GITHUB_COPILOT_TOKEN": base64.b64encode(b"gho-test-token").decode("ascii"),
                "OPENCODE_API_KEY": base64.b64encode(b"opencode-test-key").decode("ascii"),
            }
        )

        payload = json.loads(auth_content)

        self.assertEqual(
            payload["github-copilot"],
            {
                "type": "oauth",
                "refresh": "gho-test-token",
                "access": "gho-test-token",
            },
        )
        self.assertEqual(payload["opencode"], {"type": "api", "key": "opencode-test-key"})

    def test_mistral_vibe_runtime_manifest_includes_bridge_env(self) -> None:
        manifest = _builders_manifests.create_agent_statefulset_manifest(
            "vibe-assistant",
            "default",
            {
                "model": "devstral-small",
                "runtime": {
                    "kind": "mistral-vibe",
                    "mistralVibe": {"model": "mistral-medium", "noSession": True},
                },
                "storage": {"size": "1Gi"},
                "systemPrompt": "Stay precise.",
            },
            None,
            {},
        )

        pod_spec = manifest["spec"]["template"]["spec"]
        runtime_container = pod_spec["containers"][0]
        env = {item["name"]: item.get("value") for item in runtime_container["env"] if "value" in item}
        env_refs = {
            item["name"]: item.get("valueFrom") for item in runtime_container["env"] if "valueFrom" in item
        }

        self.assertEqual(runtime_container["image"], _config.MISTRAL_VIBE_RUNTIME_IMAGE)
        self.assertEqual(manifest["metadata"]["annotations"]["kubesynapse.ai/runtime"], "mistral-vibe")
        self.assertEqual(env["VIBE_ACTIVE_MODEL"], "mistral-medium")
        self.assertEqual(env["VIBE_NO_SESSION"], "true")
        self.assertEqual(env["VIBE_SYSTEM_PROMPT"], "Stay precise.")
        self.assertEqual(env_refs["MISTRAL_API_KEY"]["secretKeyRef"]["key"], "MISTRAL_API_KEY")
        self.assertEqual(runtime_container["readinessProbe"]["httpGet"]["path"], "/ready")

    # ------------------------------------------------------------------
    # §2.7 — MAX_PARALLEL_STEPS env injected into worker job manifest
    # ------------------------------------------------------------------

    def test_worker_job_manifest_includes_max_parallel_steps_default(self) -> None:
        manifest = _builders_manifests.create_worker_job_manifest(
            "workflow",
            "ns-a",
            "my-wf",
            1,
            "pvc-1",
            "/artifacts/run.json",
        )
        env_map = {
            e["name"]: e["value"] for e in manifest["spec"]["template"]["spec"]["containers"][0]["env"] if "value" in e
        }
        self.assertIn("MAX_PARALLEL_STEPS", env_map)
        self.assertEqual(env_map["MAX_PARALLEL_STEPS"], str(_config.DEFAULT_MAX_PARALLEL_STEPS))

    def test_worker_job_manifest_max_parallel_steps_override(self) -> None:
        manifest = _builders_manifests.create_worker_job_manifest(
            "workflow",
            "ns-a",
            "my-wf",
            1,
            "pvc-1",
            "/artifacts/run.json",
            max_parallel_steps=8,
        )
        env_map = {
            e["name"]: e["value"] for e in manifest["spec"]["template"]["spec"]["containers"][0]["env"] if "value" in e
        }
        self.assertEqual(env_map["MAX_PARALLEL_STEPS"], "8")

    def test_worker_artifact_pvc_manifest_skips_cross_namespace_owner_refs(self) -> None:
        resource_namespace = "other-ns" if _config.OPERATOR_NAMESPACE != "other-ns" else "another-ns"
        manifest = _builders_manifests.create_worker_artifact_pvc_manifest(
            "workflow",
            resource_namespace,
            "my-wf",
            owner_references=[{"apiVersion": "kubesynapse.ai/v1alpha1", "kind": "AgentWorkflow", "name": "my-wf", "uid": "u1"}],
        )

        self.assertNotIn("ownerReferences", manifest["metadata"])

    def test_worker_artifact_pvc_manifest_keeps_same_namespace_owner_refs(self) -> None:
        manifest = _builders_manifests.create_worker_artifact_pvc_manifest(
            "workflow",
            _config.OPERATOR_NAMESPACE,
            "my-wf",
            owner_references=[{"apiVersion": "kubesynapse.ai/v1alpha1", "kind": "AgentWorkflow", "name": "my-wf", "uid": "u1"}],
        )

        self.assertEqual(manifest["metadata"]["ownerReferences"][0]["name"], "my-wf")

    def test_worker_job_manifest_deterministic_naming_from_run_id(self) -> None:
        """§reliability-P2: Same run_id always produces same job name (idempotent)."""
        manifest_a = _builders_manifests.create_worker_job_manifest(
            "workflow", "default", "standup", 1, "pvc-1", "/artifacts/run.json",
            run_id="wf-run-default-standup-1-abc123",
        )
        manifest_b = _builders_manifests.create_worker_job_manifest(
            "workflow", "default", "standup", 1, "pvc-1", "/artifacts/run.json",
            run_id="wf-run-default-standup-1-abc123",
        )
        # Same run_id → same job name (deterministic)
        self.assertEqual(manifest_a["metadata"]["name"], manifest_b["metadata"]["name"])

        # Different run_id → different job name
        manifest_c = _builders_manifests.create_worker_job_manifest(
            "workflow", "default", "standup", 1, "pvc-1", "/artifacts/run.json",
            run_id="wf-run-default-standup-1-xyz789",
        )
        self.assertNotEqual(manifest_a["metadata"]["name"], manifest_c["metadata"]["name"])

    def test_worker_job_manifest_includes_target_uid_env(self) -> None:
        """§reliability-P2: Worker job must carry TARGET_UID for UID validation."""
        manifest = _builders_manifests.create_worker_job_manifest(
            "workflow", "default", "standup", 1, "pvc-1", "/artifacts/run.json",
            run_id="run-1", resource_uid="uid-abcdef",
        )
        env_map = {
            e["name"]: e["value"] for e in manifest["spec"]["template"]["spec"]["containers"][0]["env"] if "value" in e
        }
        self.assertEqual(env_map["TARGET_UID"], "uid-abcdef")

    def test_worker_job_manifest_includes_resource_uid_label(self) -> None:
        """§reliability-P2: Job labels must include resource UID for label-based queries."""
        manifest = _builders_manifests.create_worker_job_manifest(
            "workflow", "default", "standup", 1, "pvc-1", "/artifacts/run.json",
            run_id="run-1", resource_uid="uid-label-test",
        )
        labels = manifest["metadata"]["labels"]
        self.assertEqual(labels["kubesynapse.ai/resource-uid"], "uid-label-test")

    def test_credential_proxy_enabled_injects_sidecar_container(self) -> None:
        """When CREDENTIAL_PROXY_ENABLED=true, a credential-proxy sidecar must be added."""
        with patch.object(_builders_manifests, "CREDENTIAL_PROXY_ENABLED", True):
            manifest = _builders_manifests.create_agent_statefulset_manifest(
                "test-agent",
                "default",
                {
                    "model": "litellm/gpt-4",
                    "runtime": {"kind": "opencode"},
                    "storage": {"size": "1Gi"},
                    "systemPrompt": "Test.",
                },
                None,
                {},
            )

        container_names = [c["name"] for c in manifest["spec"]["template"]["spec"]["containers"]]
        self.assertIn("credential-proxy", container_names)

        proxy_container = next(c for c in manifest["spec"]["template"]["spec"]["containers"] if c["name"] == "credential-proxy")
        self.assertEqual(proxy_container["image"], _config.CREDENTIAL_PROXY_IMAGE)

        proxy_env = {e["name"]: e.get("value") for e in proxy_container["env"] if "value" in e}
        self.assertIn("PROXY_ROUTES", proxy_env)

        routes = json.loads(proxy_env["PROXY_ROUTES"])
        listen_ports = [r["listen"] for r in routes]
        self.assertIn(":4001", listen_ports)
        self.assertIn(":8080", listen_ports)

    def test_credential_proxy_enabled_adds_provider_route_for_opencode_go(self) -> None:
        with patch.object(_builders_manifests, "CREDENTIAL_PROXY_ENABLED", True):
            manifest = _builders_manifests.create_agent_statefulset_manifest(
                "test-agent",
                "default",
                {
                    "model": "opencode-go/mimo-v2.5-pro",
                    "runtime": {"kind": "opencode"},
                    "storage": {"size": "1Gi"},
                    "systemPrompt": "Test.",
                },
                None,
                {},
            )

        proxy_container = next(c for c in manifest["spec"]["template"]["spec"]["containers"] if c["name"] == "credential-proxy")
        proxy_env = {e["name"]: e.get("value") for e in proxy_container["env"] if "value" in e}
        routes = json.loads(proxy_env["PROXY_ROUTES"])

        provider_route = next(r for r in routes if r["listen"] == ":4003")
        self.assertEqual(provider_route["target"], "https://opencode.ai/zen/go/v1")
        self.assertEqual(provider_route["secret_env"], "OPENCODE_GO_API_KEY")

    def test_credential_proxy_enabled_removes_secrets_from_agent_container(self) -> None:
        """When CREDENTIAL_PROXY_ENABLED=true, agent container must NOT have secret env vars."""
        with patch.object(_builders_manifests, "CREDENTIAL_PROXY_ENABLED", True):
            manifest = _builders_manifests.create_agent_statefulset_manifest(
                "test-agent",
                "default",
                {
                    "model": "litellm/gpt-4",
                    "runtime": {"kind": "opencode"},
                    "storage": {"size": "1Gi"},
                    "systemPrompt": "Test.",
                },
                None,
                {},
            )

        agent_container = manifest["spec"]["template"]["spec"]["containers"][0]
        agent_env_names = [e["name"] for e in agent_container["env"]]

        self.assertNotIn("LITELLM_API_KEY", agent_env_names)
        self.assertNotIn("MCP_BEARER_TOKEN", agent_env_names)
        self.assertNotIn("OPENCODE_AUTH_CONTENT", agent_env_names)

        agent_env_values = {e["name"]: e.get("value") for e in agent_container["env"] if "value" in e}
        self.assertEqual(agent_env_values["CREDENTIAL_PROXY_ENABLED"], "true")
        self.assertIn("localhost:4001", agent_env_values["LITELLM_HOST"])

    def test_credential_proxy_disabled_preserves_backward_compatibility(self) -> None:
        """When CREDENTIAL_PROXY_ENABLED=false, secrets must be in agent container (backward compat)."""
        with patch.object(_builders_manifests, "CREDENTIAL_PROXY_ENABLED", False):
            manifest = _builders_manifests.create_agent_statefulset_manifest(
                "test-agent",
                "default",
                {
                    "model": "litellm/gpt-4",
                    "runtime": {"kind": "opencode"},
                    "storage": {"size": "1Gi"},
                    "systemPrompt": "Test.",
                },
                None,
                {},
            )

        container_names = [c["name"] for c in manifest["spec"]["template"]["spec"]["containers"]]
        self.assertNotIn("credential-proxy", container_names)

        agent_container = manifest["spec"]["template"]["spec"]["containers"][0]
        agent_env_refs = {e["name"]: e.get("valueFrom") for e in agent_container["env"] if "valueFrom" in e}

        self.assertIn("LITELLM_API_KEY", agent_env_refs)
        self.assertEqual(
            agent_env_refs["LITELLM_API_KEY"]["secretKeyRef"]["key"],
            "LITELLM_MASTER_KEY",
        )

    def test_credential_proxy_agent_listens_on_internal_port(self) -> None:
        """When CREDENTIAL_PROXY_ENABLED=true, agent container must listen on port 8081."""
        with patch.object(_builders_manifests, "CREDENTIAL_PROXY_ENABLED", True):
            manifest = _builders_manifests.create_agent_statefulset_manifest(
                "test-agent",
                "default",
                {
                    "model": "litellm/gpt-4",
                    "runtime": {"kind": "opencode"},
                    "storage": {"size": "1Gi"},
                    "systemPrompt": "Test.",
                },
                None,
                {},
            )

        agent_container = manifest["spec"]["template"]["spec"]["containers"][0]
        agent_ports = [p["containerPort"] for p in agent_container["ports"]]
        self.assertIn(8081, agent_ports)


if __name__ == "__main__":
    unittest.main()
