import copy
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


def _api_exception(status: int) -> Exception:
    exc = operator_main.ApiException(f"status={status}")
    exc.status = status
    return exc


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

    def test_statefulset_manifest_includes_autonomy_and_model_env(self) -> None:
        with patch.object(
            operator_main,
            "AGENT_ALLOWED_MODELS",
            ["gpt-4", "openrouter-gpt-4o-mini"],
        ), patch.object(operator_main, "AGENT_MAX_STEPS", "6"), patch.object(
            operator_main,
            "AGENT_MAX_STEPS_LIMIT",
            "16",
        ), patch.object(operator_main, "AGENT_DOOM_LOOP_THRESHOLD", "4"), patch.object(
            operator_main,
            "AGENT_SUPERVISOR_HISTORY_LIMIT",
            "10",
        ), patch.object(operator_main, "AGENT_SUPERVISOR_RESPONSE_CHARS", "8000"), patch.object(
            operator_main,
            "AGENT_AUTONOMY_CONTINUE_ON_ACTION_ERROR",
            "false",
        ):
            manifest = operator_main.create_agent_statefulset_manifest(
                "workspace-assistant",
                "default",
                {
                    "model": "gpt-4",
                    "runtime": {"kind": "langgraph"},
                    "storage": {"size": "1Gi"},
                    "systemPrompt": "Be precise.",
                },
                "team-policy",
                {},
            )

        env = {
            item["name"]: item["value"]
            for item in manifest["spec"]["template"]["spec"]["containers"][0]["env"]
            if "value" in item
        }

        self.assertEqual(env["AGENT_MODEL"], "gpt-4")
        self.assertEqual(env["AGENT_DEFAULT_MODEL"], "gpt-4")
        self.assertEqual(env["AGENT_ALLOWED_MODELS"], "gpt-4,openrouter-gpt-4o-mini")
        self.assertEqual(env["AGENT_MAX_STEPS"], "6")
        self.assertEqual(env["AGENT_MAX_STEPS_LIMIT"], "16")
        self.assertEqual(env["AGENT_DOOM_LOOP_THRESHOLD"], "4")
        self.assertEqual(env["AGENT_SUPERVISOR_HISTORY_LIMIT"], "10")
        self.assertEqual(env["AGENT_SUPERVISOR_RESPONSE_CHARS"], "8000")
        self.assertEqual(env["AGENT_AUTONOMY_CONTINUE_ON_ACTION_ERROR"], "false")

    def test_langgraph_manifest_includes_local_tool_env_and_workspace_mount(self) -> None:
        with patch.object(operator_main, "AGENT_LOCAL_TOOL_MOUNT_WORKSPACE", True), patch.object(
            operator_main,
            "AGENT_LOCAL_TOOL_DISCOVERY_ENABLED",
            "false",
        ), patch.object(operator_main, "AGENT_LOCAL_TOOL_ALLOWLIST", "curl,rg"), patch.object(
            operator_main,
            "AGENT_LOCAL_TOOL_ALLOWED_ROOTS",
            "/app/state,/workspace,/tmp",
        ), patch.object(operator_main, "AGENT_LOCAL_TOOL_TIMEOUT_SECONDS", "45.0"), patch.object(
            operator_main,
            "AGENT_LOCAL_TOOL_MAX_OUTPUT_CHARS",
            "20000",
        ), patch.object(operator_main, "AGENT_LOCAL_TOOL_MAX_ARGS", "12"), patch.object(
            operator_main,
            "AGENT_LOCAL_TOOL_MAX_ARG_CHARS",
            "1024",
        ), patch.object(operator_main, "AGENT_LOCAL_TOOL_LIST_LIMIT", "18"), patch.object(
            operator_main,
            "AGENT_AUTONOMY_ACTION_RETRY_LIMIT",
            "4",
        ), patch.object(operator_main, "AGENT_AUTONOMY_ACTION_RETRY_BACKOFF_SECONDS", "2.5"), patch.object(
            operator_main,
            "AGENT_AUTONOMY_FAILURE_HISTORY_LIMIT",
            "9",
        ):
            manifest = operator_main.create_agent_statefulset_manifest(
                "workspace-assistant",
                "default",
                {
                    "model": "gpt-4",
                    "runtime": {"kind": "langgraph"},
                    "storage": {"size": "1Gi"},
                    "systemPrompt": "Be precise.",
                },
                None,
                {},
            )

        pod_spec = manifest["spec"]["template"]["spec"]
        env = {
            item["name"]: item["value"]
            for item in pod_spec["containers"][0]["env"]
            if "value" in item
        }
        volume_mounts = pod_spec["containers"][0]["volumeMounts"]
        volumes = pod_spec["volumes"]

        self.assertIn({"name": "workspace-volume", "mountPath": "/workspace"}, volume_mounts)
        self.assertIn({"name": "workspace-volume", "emptyDir": {}}, volumes)
        self.assertEqual(env["AGENT_LOCAL_TOOL_DISCOVERY_ENABLED"], "false")
        self.assertEqual(env["AGENT_LOCAL_TOOL_ALLOWLIST"], "curl,rg")
        self.assertEqual(env["AGENT_LOCAL_TOOL_ALLOWED_ROOTS"], "/app/state,/workspace,/tmp")
        self.assertEqual(env["AGENT_LOCAL_TOOL_TIMEOUT_SECONDS"], "45.0")
        self.assertEqual(env["AGENT_LOCAL_TOOL_MAX_OUTPUT_CHARS"], "20000")
        self.assertEqual(env["AGENT_LOCAL_TOOL_MAX_ARGS"], "12")
        self.assertEqual(env["AGENT_LOCAL_TOOL_MAX_ARG_CHARS"], "1024")
        self.assertEqual(env["AGENT_LOCAL_TOOL_LIST_LIMIT"], "18")
        self.assertEqual(env["AGENT_AUTONOMY_ACTION_RETRY_LIMIT"], "4")
        self.assertEqual(env["AGENT_AUTONOMY_ACTION_RETRY_BACKOFF_SECONDS"], "2.5")
        self.assertEqual(env["AGENT_AUTONOMY_FAILURE_HISTORY_LIMIT"], "9")

    def test_langgraph_manifest_skips_workspace_mount_when_disabled(self) -> None:
        with patch.object(operator_main, "AGENT_LOCAL_TOOL_MOUNT_WORKSPACE", False):
            manifest = operator_main.create_agent_statefulset_manifest(
                "workspace-assistant",
                "default",
                {
                    "model": "gpt-4",
                    "runtime": {"kind": "langgraph"},
                    "storage": {"size": "1Gi"},
                    "systemPrompt": "Be precise.",
                },
                None,
                {},
            )

        pod_spec = manifest["spec"]["template"]["spec"]
        volume_mounts = pod_spec["containers"][0]["volumeMounts"]
        volume_names = {item["name"] for item in pod_spec["volumes"]}

        self.assertNotIn({"name": "workspace-volume", "mountPath": "/workspace"}, volume_mounts)
        self.assertNotIn("workspace-volume", volume_names)

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

    def test_codex_runtime_extra_env_allows_auth_json_but_not_codex_home(self) -> None:
        with patch.object(
            operator_main,
            "CODEX_RUNTIME_EXTRA_ENV",
            {
                "CODEX_AUTH_JSON": {"auth_mode": "apikey", "OPENAI_API_KEY": "sk-test-key"},
                "CODEX_HOME": "/tmp/custom-codex-home",
            },
        ):
            items = operator_main.codex_runtime_extra_env_items()

        self.assertEqual(
            items,
            [
                {
                    "name": "CODEX_AUTH_JSON",
                    "value": '{"auth_mode": "apikey", "OPENAI_API_KEY": "sk-test-key"}',
                }
            ],
        )

    def test_codex_statefulset_manifest_includes_sidecar_env_and_containers(self) -> None:
        sidecars = [{"name": "browser", "image": "example/browser:latest", "port": 8081}]
        manifest = operator_main.create_agent_statefulset_manifest(
            "workspace-assistant",
            "default",
            {
                "model": "gpt-4",
                "runtime": {"kind": "codex", "codex": {"configFiles": {"config.toml": "model = \"gpt-4\""}}},
                "storage": {"size": "1Gi"},
                "systemPrompt": "Be precise.",
                "mcpSidecars": sidecars,
            },
            None,
            {},
        )

        pod_spec = manifest["spec"]["template"]["spec"]
        env = {
            item["name"]: item["value"]
            for item in pod_spec["containers"][0]["env"]
            if "value" in item
        }

        self.assertEqual(env[operator_main.CODEX_MCP_SIDECARS_ENV], json.dumps(sidecars, ensure_ascii=False, sort_keys=True))
        self.assertEqual(json.loads(env[operator_main.CODEX_RUNTIME_CONFIG_FILES_ENV]), {"config.toml": 'model = "gpt-4"'})
        self.assertEqual(pod_spec["containers"][1]["name"], "mcp-browser")
        self.assertEqual(pod_spec["containers"][1]["ports"], [{"containerPort": 8081, "protocol": "TCP"}])
        self.assertEqual(
            pod_spec["containers"][1]["env"],
            [{"name": "MCP_LISTEN_PORT", "value": "8081"}],
        )
        self.assertEqual(
            pod_spec["containers"][1]["readinessProbe"],
            {
                "tcpSocket": {"port": 8081},
                "initialDelaySeconds": 1,
                "periodSeconds": 5,
                "timeoutSeconds": 3,
                "failureThreshold": 6,
            },
        )
        self.assertEqual(
            pod_spec["containers"][1]["livenessProbe"],
            {
                "tcpSocket": {"port": 8081},
                "initialDelaySeconds": 15,
                "periodSeconds": 20,
                "timeoutSeconds": 3,
                "failureThreshold": 3,
            },
        )

    def test_statefulset_manifest_rejects_duplicate_sidecar_ports(self) -> None:
        with self.assertRaises(operator_main.kopf.PermanentError):
            operator_main.create_agent_statefulset_manifest(
                "workspace-assistant",
                "default",
                {
                    "model": "gpt-4",
                    "runtime": {"kind": "codex", "codex": {}},
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

    def test_statefulset_manifest_rejects_missing_sidecar_image(self) -> None:
        with self.assertRaises(operator_main.kopf.PermanentError):
            operator_main.create_agent_statefulset_manifest(
                "workspace-assistant",
                "default",
                {
                    "model": "gpt-4",
                    "runtime": {"kind": "langgraph"},
                    "storage": {"size": "1Gi"},
                    "systemPrompt": "Be precise.",
                    "mcpSidecars": [{"name": "browser", "port": 8081}],
                },
                None,
                {},
            )

    def test_statefulset_manifest_rejects_invalid_auto_injected_sidecar_image(self) -> None:
        with patch.dict(operator_main.MCP_SIDECAR_CATALOG, {"browser": {"port": 8081}}, clear=True):
            with self.assertRaises(operator_main.kopf.PermanentError):
                operator_main.create_agent_statefulset_manifest(
                    "workspace-assistant",
                    "default",
                    {
                        "model": "gpt-4",
                        "runtime": {"kind": "codex", "codex": {}},
                        "storage": {"size": "1Gi"},
                        "systemPrompt": "Be precise.",
                        "skills": {
                            "files": {
                                ".github/skills/browser/SKILL.md": (
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
            "runtime": {"kind": "langgraph"},
            "storage": {"size": "1Gi"},
            "systemPrompt": "Be precise.",
        }
        updated_spec = {
            "model": "gpt-4",
            "runtime": {"kind": "langgraph"},
            "storage": {"size": "2Gi"},
            "systemPrompt": "Be precise.",
        }

        manifest = operator_main.create_agent_statefulset_manifest(
            "workspace-assistant",
            "default",
            base_spec,
            None,
            {},
        )
        updated_manifest = operator_main.create_agent_statefulset_manifest(
            "workspace-assistant",
            "default",
            updated_spec,
            None,
            {},
        )

        annotations = manifest["spec"]["template"]["metadata"]["annotations"]
        revision = annotations[operator_main.POD_TEMPLATE_REVISION_ANNOTATION]
        updated_revision = updated_manifest["spec"]["template"]["metadata"]["annotations"][
            operator_main.POD_TEMPLATE_REVISION_ANNOTATION
        ]

        self.assertEqual(len(revision), 12)
        self.assertTrue(all(character in "0123456789abcdef" for character in revision))
        self.assertNotEqual(revision, updated_revision)

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


class StatefulSetReconcileTests(unittest.TestCase):
    def test_ensure_statefulset_preserves_immutable_fields_and_resizes_pvc(self) -> None:
        current_manifest = operator_main.create_agent_statefulset_manifest(
            "workspace-assistant",
            "default",
            {
                "model": "gpt-4",
                "runtime": {"kind": "langgraph"},
                "storage": {"size": "1Gi"},
                "systemPrompt": "Use langgraph.",
            },
            None,
            {},
        )
        desired_manifest = operator_main.create_agent_statefulset_manifest(
            "workspace-assistant",
            "default",
            {
                "model": "gpt-4",
                "runtime": {"kind": "codex", "codex": {"configFiles": {"config.toml": "model = \"gpt-4\""}}},
                "storage": {"size": "4Gi"},
                "systemPrompt": "Use codex.",
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

        with patch.object(operator_main.kubernetes.client, "AppsV1Api", return_value=apps_api, create=True), patch.object(
            operator_main.kubernetes.client,
            "CoreV1Api",
            return_value=core_api,
            create=True,
        ):
            operator_main.ensure_statefulset("default", desired_manifest)

        patched_statefulset = apps_api.patch_namespaced_stateful_set.call_args.kwargs["body"]
        self.assertEqual(
            apps_api.patch_namespaced_stateful_set.call_args.kwargs["_content_type"],
            "application/merge-patch+json",
        )
        self.assertEqual(
            patched_statefulset["spec"]["volumeClaimTemplates"][0]["spec"]["resources"]["requests"]["storage"],
            "1Gi",
        )
        self.assertEqual(patched_statefulset["spec"]["template"]["metadata"]["labels"]["runtime-kind"], "codex")
        self.assertEqual(
            patched_statefulset["spec"]["template"]["metadata"]["annotations"][
                operator_main.POD_TEMPLATE_REVISION_ANNOTATION
            ],
            desired_manifest["spec"]["template"]["metadata"]["annotations"][
                operator_main.POD_TEMPLATE_REVISION_ANNOTATION
            ],
        )
        self.assertEqual(
            patched_statefulset["spec"]["template"]["spec"]["containers"][0]["image"],
            operator_main.CODEX_RUNTIME_IMAGE,
        )
        self.assertEqual(patched_statefulset["spec"]["template"]["spec"]["containers"][1]["name"], "mcp-browser")

        pvc_patch = core_api.patch_namespaced_persistent_volume_claim.call_args.kwargs
        self.assertEqual(pvc_patch["name"], "state-volume-workspace-assistant-sandbox-0")
        self.assertEqual(pvc_patch["namespace"], "default")
        self.assertEqual(pvc_patch["body"]["spec"]["resources"]["requests"]["storage"], "4Gi")

    def test_ensure_statefulset_falls_back_to_low_level_merge_patch_when_client_rejects_content_type(self) -> None:
        desired_manifest = operator_main.create_agent_statefulset_manifest(
            "workspace-assistant",
            "default",
            {
                "model": "gpt-4",
                "runtime": {"kind": "langgraph"},
                "storage": {"size": "1Gi"},
                "systemPrompt": "Use langgraph.",
            },
            None,
            {},
        )

        apps_api = Mock()
        apps_api.create_namespaced_stateful_set.side_effect = _api_exception(409)
        apps_api.patch_namespaced_stateful_set.side_effect = operator_main.ApiTypeError("unsupported kwarg")
        apps_api.read_namespaced_stateful_set.side_effect = [desired_manifest, desired_manifest]
        apps_api.api_client = Mock()
        apps_api.api_client.select_header_accept.return_value = "application/json"

        core_api = Mock()
        core_api.read_namespaced_persistent_volume_claim.return_value = {
            "spec": {"resources": {"requests": {"storage": "1Gi"}}}
        }

        with patch.object(operator_main.kubernetes.client, "AppsV1Api", return_value=apps_api, create=True), patch.object(
            operator_main.kubernetes.client,
            "CoreV1Api",
            return_value=core_api,
            create=True,
        ):
            operator_main.ensure_statefulset("default", desired_manifest)

        apps_api.patch_namespaced_stateful_set.assert_called_once()
        low_level_patch = apps_api.api_client.call_api.call_args
        self.assertEqual(low_level_patch.args[0], "/apis/apps/v1/namespaces/{namespace}/statefulsets/{name}")
        self.assertEqual(low_level_patch.args[1], "PATCH")
        self.assertEqual(low_level_patch.args[2], {"name": "workspace-assistant-sandbox", "namespace": "default"})
        self.assertEqual(low_level_patch.args[4]["Content-Type"], "application/merge-patch+json")
        self.assertEqual(low_level_patch.kwargs["body"]["metadata"]["name"], "workspace-assistant-sandbox")

    def test_ensure_statefulset_accepts_live_template_with_defaulted_tcp_protocols(self) -> None:
        desired_manifest = operator_main.create_agent_statefulset_manifest(
            "workspace-assistant",
            "default",
            {
                "model": "gpt-4",
                "runtime": {"kind": "codex", "codex": {}},
                "storage": {"size": "1Gi"},
                "systemPrompt": "Use codex.",
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

        with patch.object(operator_main.kubernetes.client, "AppsV1Api", return_value=apps_api, create=True), patch.object(
            operator_main.kubernetes.client,
            "CoreV1Api",
            return_value=core_api,
            create=True,
        ):
            operator_main.ensure_statefulset("default", desired_manifest)

        apps_api.patch_namespaced_stateful_set.assert_called_once()
        core_api.patch_namespaced_persistent_volume_claim.assert_not_called()

    def test_ensure_statefulset_raises_when_pvc_resize_is_forbidden(self) -> None:
        current_manifest = operator_main.create_agent_statefulset_manifest(
            "workspace-assistant",
            "default",
            {
                "model": "gpt-4",
                "runtime": {"kind": "langgraph"},
                "storage": {"size": "1Gi"},
                "systemPrompt": "Use langgraph.",
            },
            None,
            {},
        )
        desired_manifest = operator_main.create_agent_statefulset_manifest(
            "workspace-assistant",
            "default",
            {
                "model": "gpt-4",
                "runtime": {"kind": "codex", "codex": {"configFiles": {"config.toml": "model = \"gpt-4\""}}},
                "storage": {"size": "4Gi"},
                "systemPrompt": "Use codex.",
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

        with patch.object(operator_main.kubernetes.client, "AppsV1Api", return_value=apps_api, create=True), patch.object(
            operator_main.kubernetes.client,
            "CoreV1Api",
            return_value=core_api,
            create=True,
        ):
            with self.assertRaises(operator_main.kopf.PermanentError):
                operator_main.ensure_statefulset("default", desired_manifest)

        apps_api.patch_namespaced_stateful_set.assert_called_once()
        core_api.patch_namespaced_persistent_volume_claim.assert_called_once()
        pvc_patch = core_api.patch_namespaced_persistent_volume_claim.call_args.kwargs
        self.assertEqual(pvc_patch["name"], "state-volume-workspace-assistant-sandbox-0")
        self.assertEqual(pvc_patch["namespace"], "default")
        self.assertEqual(pvc_patch["body"]["spec"]["resources"]["requests"]["storage"], "4Gi")

    def test_ensure_statefulset_raises_when_live_template_keeps_removed_sidecar(self) -> None:
        current_manifest = operator_main.create_agent_statefulset_manifest(
            "workspace-assistant",
            "default",
            {
                "model": "gpt-4",
                "runtime": {"kind": "codex", "codex": {}},
                "storage": {"size": "1Gi"},
                "systemPrompt": "Use codex.",
                "mcpSidecars": [
                    {"name": "browser", "image": "example/browser:latest", "port": 8081},
                    {"name": "documents", "image": "example/documents:latest", "port": 8092},
                ],
            },
            None,
            {},
        )
        desired_manifest = operator_main.create_agent_statefulset_manifest(
            "workspace-assistant",
            "default",
            {
                "model": "gpt-4",
                "runtime": {"kind": "codex", "codex": {}},
                "storage": {"size": "1Gi"},
                "systemPrompt": "Use codex.",
                "mcpSidecars": [{"name": "browser", "image": "example/browser:latest", "port": 8081}],
            },
            None,
            {},
        )

        apps_api = Mock()
        apps_api.create_namespaced_stateful_set.side_effect = _api_exception(409)
        apps_api.read_namespaced_stateful_set.side_effect = [current_manifest, current_manifest]

        core_api = Mock()

        with patch.object(operator_main.kubernetes.client, "AppsV1Api", return_value=apps_api, create=True), patch.object(
            operator_main.kubernetes.client,
            "CoreV1Api",
            return_value=core_api,
            create=True,
        ):
            with self.assertRaises(operator_main.kopf.TemporaryError):
                operator_main.ensure_statefulset("default", desired_manifest)

        apps_api.patch_namespaced_stateful_set.assert_called_once()
        core_api.patch_namespaced_persistent_volume_claim.assert_not_called()

    def test_ensure_statefulset_skips_pvc_shrink_requests(self) -> None:
        current_manifest = operator_main.create_agent_statefulset_manifest(
            "workspace-assistant",
            "default",
            {
                "model": "gpt-4",
                "runtime": {"kind": "langgraph"},
                "storage": {"size": "4Gi"},
                "systemPrompt": "Original prompt.",
            },
            None,
            {},
        )
        desired_manifest = operator_main.create_agent_statefulset_manifest(
            "workspace-assistant",
            "default",
            {
                "model": "gpt-4",
                "runtime": {"kind": "langgraph"},
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

        with patch.object(operator_main.kubernetes.client, "AppsV1Api", return_value=apps_api, create=True), patch.object(
            operator_main.kubernetes.client,
            "CoreV1Api",
            return_value=core_api,
            create=True,
        ):
            operator_main.ensure_statefulset("default", desired_manifest)

        apps_api.patch_namespaced_stateful_set.assert_called_once()
        core_api.patch_namespaced_persistent_volume_claim.assert_not_called()


if __name__ == "__main__":
    unittest.main()