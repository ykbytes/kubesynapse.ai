import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from utils import (  # noqa: E402
    compute_execution_waves,
    merge_goose_config_files,
    normalize_step_execution,
    parse_agent_a2a_config,
    parse_policy_a2a_config,
    parse_goose_config_files,
    ready_workflow_steps,
    render_prompt,
    validate_supported_policy_spec,
    validate_workflow_graph,
    invoke_agent_runtime,
)


class WorkflowUtilsTests(unittest.TestCase):
    def test_validate_workflow_graph_rejects_disconnected_steps(self) -> None:
        steps = [
            {"name": "research", "agentRef": "research-agent"},
            {
                "name": "analysis",
                "agentRef": "analysis-agent",
                "dependsOn": ["research"],
            },
            {"name": "orphan", "agentRef": "orphan-agent"},
        ]

        with self.assertRaisesRegex(ValueError, "single connected DAG"):
            validate_workflow_graph(steps)

    def test_validate_workflow_graph_rejects_cycles(self) -> None:
        steps = [
            {"name": "a", "agentRef": "agent-a", "dependsOn": ["c"]},
            {"name": "b", "agentRef": "agent-b", "dependsOn": ["a"]},
            {"name": "c", "agentRef": "agent-c", "dependsOn": ["b"]},
        ]

        with self.assertRaisesRegex(ValueError, "root step"):
            validate_workflow_graph(steps)

    def test_render_prompt_supports_structured_placeholders(self) -> None:
        rendered = render_prompt(
            (
                "Topic: {{input}}\n"
                "Summary: {{research.output.json.summary}}\n"
                "Prior: {{previous_output}}"
            ),
            "private 5G",
            "Detailed prior output",
            {
                "research": {
                    "response": "Detailed prior output",
                    "output": {
                        "json": {
                            "summary": (
                                "Factories adopt private 5G for "
                                "low-latency robotics."
                            ),
                        }
                    },
                }
            },
        )

        self.assertIn("private 5G", rendered)
        self.assertIn("Factories adopt private 5G", rendered)
        self.assertIn("Detailed prior output", rendered)

    def test_render_prompt_prepends_project_context(self) -> None:
        rendered = render_prompt(
            "Implement feature for {{input}}",
            "rate limiting",
            "",
            {},
            project_context="Language: Python\nFramework: FastAPI",
        )

        self.assertIn("[Project Context]", rendered)
        self.assertIn("Language: Python", rendered)
        self.assertTrue(rendered.endswith("Implement feature for rate limiting"))

    def test_ready_workflow_steps_returns_parallel_frontier(self) -> None:
        steps = [
            {"name": "research", "agentRef": "research-agent"},
            {"name": "finance", "agentRef": "finance-agent"},
            {
                "name": "summary",
                "agentRef": "summary-agent",
                "dependsOn": ["research", "finance"],
            },
        ]

        ready_names = [
            step["name"] for step in ready_workflow_steps(steps, set())
        ]
        self.assertEqual(ready_names, ["research", "finance"])

    def test_compute_execution_waves_groups_by_dependency_layers(self) -> None:
        steps = [
            {"name": "research", "agentRef": "research-agent"},
            {"name": "finance", "agentRef": "finance-agent"},
            {
                "name": "analysis",
                "agentRef": "analysis-agent",
                "dependsOn": ["research", "finance"],
            },
            {
                "name": "report",
                "agentRef": "report-agent",
                "dependsOn": ["analysis"],
            },
        ]

        waves = compute_execution_waves(steps)
        self.assertEqual([[step["name"] for step in wave] for wave in waves], [["research", "finance"], ["analysis"], ["report"]])

    def test_normalize_step_execution_applies_defaults_and_overrides(
        self,
    ) -> None:
        execution = normalize_step_execution(
            {
                "execution": {
                    "timeoutSeconds": 45,
                    "maxAttempts": 3,
                    "backoffSeconds": 1.5,
                    "retryable": False,
                    "continueOnError": True,
                }
            }
        )

        self.assertEqual(execution["timeoutSeconds"], 45.0)
        self.assertEqual(execution["maxAttempts"], 3)
        self.assertEqual(execution["backoffSeconds"], 1.5)
        self.assertFalse(execution["retryable"])
        self.assertTrue(execution["continueOnError"])

    def test_validate_supported_policy_spec_rejects_budget_fields(self) -> None:
        with self.assertRaisesRegex(ValueError, "reserved for future distributed enforcement"):
            validate_supported_policy_spec(
                {
                    "budget": {
                        "maxTokensPerHour": 100000,
                        "maxRequestsPerMinute": 30,
                    }
                }
            )

    def test_validate_supported_policy_spec_allows_policy_without_budget(self) -> None:
        validate_supported_policy_spec(
            {
                "inputGuardrails": {"maxInputTokens": 4096},
                "outputGuardrails": {"maxOutputTokens": 4096},
                "allowedModels": ["gpt-4"],
            }
        )

    def test_parse_policy_a2a_config_normalizes_targets(self) -> None:
        parsed = parse_policy_a2a_config(
            {
                "a2a": {
                    "allowedTargets": [
                        {"name": "analysis-agent", "namespace": "tenant-a"},
                        {"name": "analysis-agent", "namespace": "tenant-a"},
                    ],
                    "maxTimeoutSeconds": 45,
                    "requireHitl": True,
                }
            }
        )

        self.assertEqual(
            parsed,
            {
                "allowedTargets": [{"name": "analysis-agent", "namespace": "tenant-a"}],
                "maxTimeoutSeconds": 45.0,
                "requireHitl": True,
            },
        )

    def test_parse_policy_a2a_config_rejects_invalid_timeout(self) -> None:
        with self.assertRaisesRegex(ValueError, "maxTimeoutSeconds"):
            parse_policy_a2a_config(
                {
                    "a2a": {
                        "allowedTargets": [{"name": "analysis-agent", "namespace": "tenant-a"}],
                        "maxTimeoutSeconds": 0,
                    }
                }
            )

    def test_parse_agent_a2a_config_normalizes_allowed_callers(self) -> None:
        parsed = parse_agent_a2a_config(
            {
                "allowedCallers": [
                    {"name": "research-agent", "namespace": "tenant-a"},
                    {"name": "research-agent", "namespace": "tenant-a"},
                ]
            }
        )

        self.assertEqual(
            parsed,
            {
                "allowedCallers": [{"name": "research-agent", "namespace": "tenant-a"}],
            },
        )

    def test_parse_goose_config_files_normalizes_relative_paths(self) -> None:
        parsed = parse_goose_config_files(
            {
                " config.yaml ": {"GOOSE_MODE": "smart_approve"},
                "prompts\\review.md": "Review conservatively.",
            },
            source="AIAgent.spec.runtime.goose.configFiles",
        )

        self.assertEqual(
            parsed,
            {
                "config.yaml": {"GOOSE_MODE": "smart_approve"},
                "prompts/review.md": "Review conservatively.",
            },
        )

    def test_parse_goose_config_files_rejects_runtime_managed_paths(self) -> None:
        with self.assertRaisesRegex(ValueError, "runtime-managed"):
            parse_goose_config_files(
                {"permissions/tool_permissions.json": {}},
                source="AIAgent.spec.runtime.goose.configFiles",
            )

    def test_parse_goose_config_files_rejects_secrets_yaml(self) -> None:
        with self.assertRaisesRegex(ValueError, "environment variables"):
            parse_goose_config_files(
                {"secrets.yaml": {"OPENAI_API_KEY": "secret"}},
                source="AIAgent.spec.runtime.goose.configFiles",
            )

    def test_merge_goose_config_files_prefers_later_entries(self) -> None:
        merged = merge_goose_config_files(
            (
                {
                    "config.yaml": {"GOOSE_MODE": "approve"},
                    "prompts/review.md": "Base review prompt.",
                },
                "chart",
            ),
            (
                {
                    "config.yaml": {"GOOSE_MODE": "smart_approve"},
                },
                "agent",
            ),
        )

        self.assertEqual(
            merged,
            {
                "config.yaml": {"GOOSE_MODE": "smart_approve"},
                "prompts/review.md": "Base review prompt.",
            },
        )


    def test_validate_workflow_graph_rejects_too_many_steps(self) -> None:
        import utils
        original = utils.MAX_WORKFLOW_STEPS
        utils.MAX_WORKFLOW_STEPS = 2
        try:
            steps = [
                {"name": "a", "agentRef": "agent"},
                {"name": "b", "agentRef": "agent", "dependsOn": ["a"]},
                {"name": "c", "agentRef": "agent", "dependsOn": ["b"]},
            ]
            with self.assertRaisesRegex(ValueError, "exceeding the limit"):
                validate_workflow_graph(steps)
        finally:
            utils.MAX_WORKFLOW_STEPS = original

    def test_invoke_agent_runtime_rejects_invalid_names(self) -> None:
        with self.assertRaises(ValueError):
            invoke_agent_runtime("INVALID NAME", "ns", {"prompt": "hi"})
        with self.assertRaises(ValueError):
            invoke_agent_runtime("agent", "BAD NS!", {"prompt": "hi"})
        with self.assertRaises(ValueError):
            invoke_agent_runtime("", "ns", {"prompt": "hi"})


if __name__ == "__main__":
    unittest.main()
