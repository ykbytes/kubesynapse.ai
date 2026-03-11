import json
import sys
import types
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _passthrough_decorator(*args, **kwargs):
    def decorator(func):
        return func

    return decorator


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
kopf_module.PermanentError = type("PermanentError", (Exception,), {})
kopf_module.TemporaryError = type("TemporaryError", (Exception,), {})
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

        ingress_rule = ingress["spec"]["ingress"][0]["from"][0]
        egress_rule = egress["spec"]["egress"][0]["to"][0]

        self.assertEqual(ingress["metadata"]["labels"]["sandbox.enterprise.ai/policy-type"], "a2a-ingress")
        self.assertEqual(egress["metadata"]["labels"]["sandbox.enterprise.ai/policy-type"], "a2a-egress")
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


if __name__ == "__main__":
    unittest.main()