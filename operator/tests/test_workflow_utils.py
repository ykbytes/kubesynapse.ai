import importlib.util
import sys
import unittest
from pathlib import Path

MODULE_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = MODULE_ROOT / "config.py"
CONFIG_SPEC = importlib.util.spec_from_file_location("operator_config_under_test", CONFIG_PATH)
if CONFIG_SPEC is None or CONFIG_SPEC.loader is None:
    raise RuntimeError("Failed to load operator config module for tests")
operator_config = importlib.util.module_from_spec(CONFIG_SPEC)
previous_config = sys.modules.get("config")
sys.modules[CONFIG_SPEC.name] = operator_config
sys.modules["config"] = operator_config
CONFIG_SPEC.loader.exec_module(operator_config)

MODULE_PATH = MODULE_ROOT / "utils.py"
SPEC = importlib.util.spec_from_file_location("operator_utils_under_test", MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("Failed to load operator utils module for tests")
operator_utils = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = operator_utils
try:
    SPEC.loader.exec_module(operator_utils)
finally:
    if previous_config is not None:
        sys.modules["config"] = previous_config
    else:
        sys.modules.pop("config", None)

compute_execution_waves = operator_utils.compute_execution_waves
invoke_agent_runtime = operator_utils.invoke_agent_runtime
merge_runtime_config_files = operator_utils.merge_runtime_config_files
missing_json_paths = operator_utils.missing_json_paths
normalize_step_execution = operator_utils.normalize_step_execution
parse_agent_a2a_config = operator_utils.parse_agent_a2a_config
parse_json_output = operator_utils.parse_json_output
parse_memory_policy_config = operator_utils.parse_memory_policy_config
parse_policy_a2a_config = operator_utils.parse_policy_a2a_config
parse_runtime_config_files = operator_utils.parse_runtime_config_files
parse_tool_policy_config = operator_utils.parse_tool_policy_config
ready_workflow_steps = operator_utils.ready_workflow_steps
render_prompt = operator_utils.render_prompt
validate_supported_policy_spec = operator_utils.validate_supported_policy_spec
validate_workflow_graph = operator_utils.validate_workflow_graph


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
            "Topic: {{input}}\nSummary: {{research.output.json.summary}}\nPrior: {{previous_output}}",
            "private 5G",
            "Detailed prior output",
            {
                "research": {
                    "response": "Detailed prior output",
                    "output": {
                        "json": {
                            "summary": "Factories adopt private 5G for low-latency robotics.",
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

        ready_names = [step["name"] for step in ready_workflow_steps(steps, set())]
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
        self.assertEqual(
            [[step["name"] for step in wave] for wave in waves],
            [["research", "finance"], ["analysis"], ["report"]],
        )

    def test_normalize_step_execution_applies_defaults_and_overrides(self) -> None:
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

    def test_normalize_step_execution_preserves_required_json_paths(self) -> None:
        execution = normalize_step_execution(
            {
                "execution": {
                    "requiredJsonPaths": ["intent_summary", "resource_names", "execution_plan.generated_workflow_name"],
                }
            }
        )

        self.assertEqual(
            execution["requiredJsonPaths"],
            ["intent_summary", "resource_names", "execution_plan.generated_workflow_name"],
        )

    def test_missing_json_paths_reports_blank_or_absent_paths(self) -> None:
        payload = {
            "intent_summary": {"goal": "ok"},
            "execution_plan": {"generated_workflow_name": ""},
        }

        self.assertEqual(
            missing_json_paths(payload, ["intent_summary", "resource_names", "execution_plan.generated_workflow_name"]),
            ["resource_names", "execution_plan.generated_workflow_name"],
        )

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

    def test_parse_tool_policy_config_normalizes_lists(self) -> None:
        parsed = parse_tool_policy_config(
            {
                "toolPolicy": {
                    "maxDelegationDepth": 2,
                    "allowedToolPrefixes": ["local.command.", "github/", "github/"],
                    "blockedToolNames": ["local.command.rm", "local.command.rm"],
                    "requireApprovalFor": ["github/create_issue", "github/create_issue"],
                }
            }
        )

        self.assertEqual(
            parsed,
            {
                "maxDelegationDepth": 2,
                "allowedToolPrefixes": ["github/", "local.command."],
                "blockedToolNames": ["local.command.rm"],
                "requireApprovalFor": ["github/create_issue"],
            },
        )

    def test_parse_tool_policy_config_rejects_invalid_shape(self) -> None:
        with self.assertRaisesRegex(ValueError, "toolPolicy"):
            parse_tool_policy_config({"toolPolicy": "not-an-object"})

    def test_parse_memory_policy_config_normalizes_values(self) -> None:
        parsed = parse_memory_policy_config(
            {
                "memoryPolicy": {
                    "maxInjectedMemories": 4,
                    "maxInjectedChars": 900,
                    "allowedMemoryTypes": ["procedural", "episodic", "procedural"],
                    "autoPromote": True,
                }
            }
        )

        self.assertEqual(
            parsed,
            {
                "maxInjectedMemories": 4,
                "maxInjectedChars": 900,
                "allowedMemoryTypes": ["episodic", "procedural"],
                "autoPromote": True,
            },
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

    def test_parse_runtime_config_files_normalizes_relative_paths(self) -> None:
        parsed = parse_runtime_config_files(
            {
                " config.yaml ": {"default_agent": "build"},
                "prompts\\review.md": "Review conservatively.",
            },
            source="AIAgent.spec.runtime.opencode.configFiles",
        )

        self.assertEqual(
            parsed,
            {
                "config.yaml": {"default_agent": "build"},
                "prompts/review.md": "Review conservatively.",
            },
        )

    def test_parse_runtime_config_files_rejects_parent_traversal(self) -> None:
        with self.assertRaisesRegex(ValueError, "must stay within the runtime config root"):
            parse_runtime_config_files(
                {"../secrets.json": {}},
                source="AIAgent.spec.runtime.opencode.configFiles",
            )

    def test_merge_runtime_config_files_prefers_later_entries(self) -> None:
        merged = merge_runtime_config_files(
            (
                {
                    "config.yaml": {"default_agent": "plan"},
                    "prompts/review.md": "Base review prompt.",
                },
                "chart",
            ),
            (
                {
                    "config.yaml": {"default_agent": "build"},
                },
                "agent",
            ),
        )

        self.assertEqual(
            merged,
            {
                "config.yaml": {"default_agent": "build"},
                "prompts/review.md": "Base review prompt.",
            },
        )

    def test_validate_workflow_graph_rejects_too_many_steps(self) -> None:
        original = operator_utils.MAX_WORKFLOW_STEPS
        operator_utils.MAX_WORKFLOW_STEPS = 2
        try:
            steps = [
                {"name": "a", "agentRef": "agent"},
                {"name": "b", "agentRef": "agent", "dependsOn": ["a"]},
                {"name": "c", "agentRef": "agent", "dependsOn": ["b"]},
            ]
            with self.assertRaisesRegex(ValueError, "exceeding the limit"):
                validate_workflow_graph(steps)
        finally:
            operator_utils.MAX_WORKFLOW_STEPS = original

    def test_invoke_agent_runtime_rejects_invalid_names(self) -> None:
        with self.assertRaises(ValueError):
            invoke_agent_runtime("INVALID NAME", "ns", {"prompt": "hi"})
        with self.assertRaises(ValueError):
            invoke_agent_runtime("agent", "BAD NS!", {"prompt": "hi"})
        with self.assertRaises(ValueError):
            invoke_agent_runtime("", "ns", {"prompt": "hi"})


class ParseJsonOutputTests(unittest.TestCase):
    """parse_json_output extracts JSON from raw text and markdown fences."""

    def test_pure_json_object(self) -> None:
        result = parse_json_output('{"key": "value"}')
        self.assertEqual(result, {"key": "value"})

    def test_pure_json_array(self) -> None:
        result = parse_json_output("[1, 2, 3]")
        self.assertEqual(result, [1, 2, 3])

    def test_empty_string_returns_none(self) -> None:
        self.assertIsNone(parse_json_output(""))
        self.assertIsNone(parse_json_output("   "))

    def test_plain_text_returns_none(self) -> None:
        self.assertIsNone(parse_json_output("Just some text output."))

    def test_markdown_fenced_json_object(self) -> None:
        text = 'Here is the specification:\n```json\n{"feature_name": "auth", "spec_markdown": "# Auth"}\n```\nDone.'
        result = parse_json_output(text)
        self.assertEqual(result, {"feature_name": "auth", "spec_markdown": "# Auth"})

    def test_markdown_fenced_without_json_tag(self) -> None:
        text = 'Result:\n```\n{"score": 95}\n```'
        result = parse_json_output(text)
        self.assertEqual(result, {"score": 95})

    def test_multiple_fenced_blocks_prefers_last(self) -> None:
        text = 'Draft:\n```json\n{"version": 1}\n```\nFinal:\n```json\n{"version": 2}\n```'
        result = parse_json_output(text)
        self.assertEqual(result, {"version": 2})

    def test_fenced_invalid_json_skipped(self) -> None:
        text = 'Bad block:\n```json\n{invalid json}\n```\nGood block:\n```json\n{"ok": true}\n```'
        result = parse_json_output(text)
        self.assertEqual(result, {"ok": True})

    def test_fenced_non_json_content_ignored(self) -> None:
        text = "```\nsome plain text\n```"
        result = parse_json_output(text)
        self.assertIsNone(result)

    def test_invalid_json_whole_text_falls_through_to_fences(self) -> None:
        text = '{not valid json}\n```json\n{"fallback": true}\n```'
        result = parse_json_output(text)
        self.assertEqual(result, {"fallback": True})


if __name__ == "__main__":
    unittest.main()
