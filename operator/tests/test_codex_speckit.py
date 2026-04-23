"""Tests for Codex runtime integration and Spec Kit workflow patterns."""

import importlib.util
import json
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

parse_goose_config_files = operator_utils.parse_goose_config_files
render_prompt = operator_utils.render_prompt
validate_workflow_graph = operator_utils.validate_workflow_graph


class CodexConfigFileTests(unittest.TestCase):
    """Validates that parse_goose_config_files (reused for codex) handles
    codex-specific configFiles the same way as goose config files."""

    def test_accepts_valid_codex_config_files(self) -> None:
        parsed = parse_goose_config_files(
            {
                "config.yaml": {"CODEX_MODE": "auto"},
                "prompts/system.md": "You are a helpful assistant.",
            },
            source="AIAgent.spec.runtime.codex.configFiles",
        )
        self.assertEqual(parsed["config.yaml"], {"CODEX_MODE": "auto"})
        self.assertEqual(parsed["prompts/system.md"], "You are a helpful assistant.")

    def test_accepts_none_config_files(self) -> None:
        parsed = parse_goose_config_files(
            None,
            source="AIAgent.spec.runtime.codex.configFiles",
        )
        self.assertEqual(parsed, {})

    def test_rejects_secrets_yaml_in_codex_config(self) -> None:
        with self.assertRaisesRegex(ValueError, "environment variables"):
            parse_goose_config_files(
                {"secrets.yaml": {"API_KEY": "secret"}},
                source="AIAgent.spec.runtime.codex.configFiles",
            )


class SpecKitWorkflowGraphTests(unittest.TestCase):
    """Validates the DAG structure of the Spec Kit pipeline workflow."""

    SPECKIT_STEPS = [
        {"name": "write-spec", "agentRef": "spec-writer"},
        {
            "name": "scrum-review",
            "agentRef": "scrum-master",
            "dependsOn": ["write-spec"],
            "requireApproval": True,
        },
        {
            "name": "create-plan",
            "agentRef": "planner",
            "dependsOn": ["scrum-review"],
        },
        {
            "name": "generate-tasks",
            "agentRef": "task-generator",
            "dependsOn": ["create-plan"],
        },
        {
            "name": "implement",
            "agentRef": "implementer",
            "dependsOn": ["generate-tasks"],
            "requireApproval": True,
        },
    ]

    def test_speckit_pipeline_is_valid_dag(self) -> None:
        result = validate_workflow_graph(self.SPECKIT_STEPS)
        self.assertEqual(
            result["topologicalOrder"],
            ["write-spec", "scrum-review", "create-plan", "generate-tasks", "implement"],
        )

    def test_speckit_pipeline_root_is_write_spec(self) -> None:
        result = validate_workflow_graph(self.SPECKIT_STEPS)
        self.assertEqual(result["roots"], ["write-spec"])


class SpecKitPromptRenderingTests(unittest.TestCase):
    """Validates that structured JSON placeholders resolve correctly
    through the five Spec Kit pipeline stages."""

    MOCK_STEP_RESULTS = {
        "write-spec": {
            "output": {
                "json": {
                    "spec_markdown": "# Feature: Auth\n\nUsers can log in.",
                    "feature_name": "user-auth",
                    "clarifications_needed": [],
                },
                "text": json.dumps({
                    "spec_markdown": "# Feature: Auth\n\nUsers can log in.",
                    "feature_name": "user-auth",
                    "clarifications_needed": [],
                }),
            },
        },
        "scrum-review": {
            "output": {
                "json": {
                    "approved": True,
                    "score": 92,
                    "issues": [],
                    "revised_spec_markdown": "# Feature: Auth\n\nUsers can log in securely.",
                },
            },
        },
        "create-plan": {
            "output": {
                "json": {
                    "plan_markdown": "## Phase 1\nSet up auth module.",
                    "tech_stack": ["python", "fastapi"],
                    "phase_count": 3,
                    "entities": ["User", "Session"],
                },
            },
        },
        "generate-tasks": {
            "output": {
                "json": {
                    "tasks_markdown": "- [ ] T001 Create auth module in src/auth.py",
                    "total_tasks": 5,
                    "phases": [{"name": "Setup", "task_count": 2}],
                    "parallel_opportunities": 2,
                },
            },
        },
    }

    def test_scrum_review_prompt_resolves_spec_fields(self) -> None:
        template = (
            "Feature name: {{write-spec.output.json.feature_name}}\n"
            "Specification:\n{{write-spec.output.json.spec_markdown}}"
        )
        rendered = render_prompt(template, "", "", self.MOCK_STEP_RESULTS)
        self.assertIn("user-auth", rendered)
        self.assertIn("# Feature: Auth", rendered)

    def test_plan_prompt_resolves_revised_spec(self) -> None:
        template = "Spec:\n{{scrum-review.output.json.revised_spec_markdown}}"
        rendered = render_prompt(template, "", "", self.MOCK_STEP_RESULTS)
        self.assertIn("Users can log in securely.", rendered)

    def test_tasks_prompt_resolves_plan_fields(self) -> None:
        template = (
            "Tech stack: {{create-plan.output.json.tech_stack}}\n"
            "Entities: {{create-plan.output.json.entities}}\n"
            "Plan:\n{{create-plan.output.json.plan_markdown}}"
        )
        rendered = render_prompt(template, "", "", self.MOCK_STEP_RESULTS)
        self.assertIn("python", rendered)
        self.assertIn("fastapi", rendered)
        self.assertIn("User", rendered)
        self.assertIn("Set up auth module.", rendered)

    def test_implement_prompt_resolves_tasks(self) -> None:
        template = "Task list:\n{{generate-tasks.output.json.tasks_markdown}}"
        rendered = render_prompt(template, "", "", self.MOCK_STEP_RESULTS)
        self.assertIn("T001 Create auth module", rendered)

    def test_write_spec_prompt_uses_workflow_input(self) -> None:
        template = "Feature description:\n{{input}}"
        rendered = render_prompt(
            template, "Add OAuth2 login", "", self.MOCK_STEP_RESULTS
        )
        self.assertIn("Add OAuth2 login", rendered)

    def test_unresolved_placeholder_cleared(self) -> None:
        template = "Value: {{nonexistent-step.output.json.field}}"
        rendered = render_prompt(template, "", "", self.MOCK_STEP_RESULTS)
        self.assertEqual(rendered, "Value: ")


if __name__ == "__main__":
    unittest.main()
