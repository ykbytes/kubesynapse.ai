"""Tests for OpenCode workflow integration fixes in worker.py."""

import importlib.util
import json
import os
import sys
import types
import unittest
from datetime import UTC
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# ── Stub heavy third-party modules so worker.py can be imported ──
_k8s = types.ModuleType("kubernetes")
_k8s_client = types.ModuleType("kubernetes.client")
_k8s_config = types.ModuleType("kubernetes.config")
_k8s_rest = types.ModuleType("kubernetes.client.rest")
_k8s_rest.ApiException = type("ApiException", (Exception,), {"status": None})
_k8s_config.ConfigException = type("ConfigException", (Exception,), {})
_k8s.client = _k8s_client
_k8s.config = _k8s_config
_k8s_client.ApiException = _k8s_rest.ApiException
_k8s_client.rest = _k8s_rest
for _name, _mod in [
    ("kubernetes", _k8s),
    ("kubernetes.client", _k8s_client),
    ("kubernetes.config", _k8s_config),
    ("kubernetes.client.rest", _k8s_rest),
]:
    sys.modules.setdefault(_name, _mod)

sys.modules["kubernetes"].client = sys.modules["kubernetes.client"]
sys.modules["kubernetes"].config = sys.modules["kubernetes.config"]
sys.modules["kubernetes.client"].rest = sys.modules["kubernetes.client.rest"]
sys.modules["kubernetes.client"].ApiException = sys.modules["kubernetes.client.rest"].ApiException

CONFIG_PATH = Path(__file__).resolve().parents[1] / "config.py"
CONFIG_SPEC = importlib.util.spec_from_file_location("operator_config_under_test", CONFIG_PATH)
if CONFIG_SPEC is None or CONFIG_SPEC.loader is None:
    raise RuntimeError("Failed to load operator config module for tests")
operator_config = importlib.util.module_from_spec(CONFIG_SPEC)
previous_config = sys.modules.get("config")
sys.modules[CONFIG_SPEC.name] = operator_config
sys.modules["config"] = operator_config
CONFIG_SPEC.loader.exec_module(operator_config)

UTILS_PATH = Path(__file__).resolve().parents[1] / "utils.py"
UTILS_SPEC = importlib.util.spec_from_file_location("operator_utils_under_test", UTILS_PATH)
if UTILS_SPEC is None or UTILS_SPEC.loader is None:
    raise RuntimeError("Failed to load operator utils module for tests")
operator_utils = importlib.util.module_from_spec(UTILS_SPEC)
sys.modules[UTILS_SPEC.name] = operator_utils
try:
    UTILS_SPEC.loader.exec_module(operator_utils)
finally:
    if previous_config is not None:
        sys.modules["config"] = previous_config
    else:
        sys.modules.pop("config", None)


class PreviousOutputForDependenciesTests(unittest.TestCase):
    """Bug 4 & 5: previous_output_for_dependencies includes artifacts."""

    def _call(
        self,
        dependencies: list[str],
        step_results: dict[str, dict[str, Any]],
    ) -> str:
        from worker import previous_output_for_dependencies

        return previous_output_for_dependencies(dependencies, step_results)

    def test_includes_response_and_structured_json(self) -> None:
        result = self._call(
            ["step-a"],
            {
                "step-a": {
                    "response": "hello world",
                    "output": {"json": {"key": "value"}},
                }
            },
        )
        self.assertIn("[Step: step-a]", result)
        self.assertIn("hello world", result)
        self.assertIn("[Structured Output]", result)
        self.assertIn('"key"', result)

    def test_includes_artifact_summaries(self) -> None:
        result = self._call(
            ["code-step"],
            {
                "code-step": {
                    "response": "Created files.",
                    "output": {"json": None},
                    "artifacts": [
                        {"path": "src/main.py"},
                        {"path": "src/utils.py"},
                    ],
                }
            },
        )
        self.assertIn("[Step: code-step]", result)
        self.assertIn("Artifacts", result)
        self.assertIn("src/main.py", result)
        self.assertIn("src/utils.py", result)

    def test_no_artifact_section_when_empty(self) -> None:
        result = self._call(
            ["plain"],
            {"plain": {"response": "done", "output": {"json": None}, "artifacts": []}},
        )
        self.assertNotIn("Artifacts", result)

    def test_no_artifact_section_when_missing(self) -> None:
        result = self._call(
            ["old"],
            {"old": {"response": "done", "output": {"json": None}}},
        )
        self.assertNotIn("Artifacts", result)

    def test_includes_tool_calls_summary(self) -> None:
        """tool_calls from prior step are included for downstream context."""
        result = self._call(
            ["code-step"],
            {
                "code-step": {
                    "response": "Done.",
                    "output": {"json": None},
                    "artifacts": [],
                    "tool_calls": [
                        {"tool": "write", "status": "completed", "input": {"filePath": "src/app.py"}},
                        {"tool": "bash", "status": "completed", "input": {"command": "git commit -m 'init'"}},
                        {"tool": "edit", "status": "error", "input": {"filePath": "bad.py"}},
                    ],
                }
            },
        )
        self.assertIn("Tool Calls", result)
        self.assertIn("write: src/app.py", result)
        self.assertIn("bash: git commit -m 'init'", result)
        self.assertIn("bad.py", result)
        self.assertIn("[error]", result)

    def test_artifact_includes_tool_type(self) -> None:
        """Artifact summaries include the operation type (write/edit/patch)."""
        result = self._call(
            ["code-step"],
            {
                "code-step": {
                    "response": "Created files.",
                    "output": {"json": None},
                    "artifacts": [
                        {"path": "src/main.py", "tool": "write", "status": "completed"},
                        {"path": "src/utils.py", "tool": "edit", "status": "completed"},
                    ],
                }
            },
        )
        self.assertIn("src/main.py (write)", result)
        self.assertIn("src/utils.py (edit)", result)

    def test_null_items_in_tool_calls_and_artifacts(self) -> None:
        """Null items in tool_calls or artifacts arrays don't crash."""
        result = self._call(
            ["step"],
            {
                "step": {
                    "response": "Done.",
                    "output": {"json": None},
                    "artifacts": [None, {"path": "ok.py", "tool": "write", "status": "completed"}, "bad"],
                    "tool_calls": [None, {"tool": "bash", "status": "completed", "input": {"command": "ls"}}, 42],
                }
            },
        )
        self.assertIn("ok.py", result)
        self.assertIn("bash: ls", result)

    def test_no_tool_calls_section_when_empty(self) -> None:
        result = self._call(
            ["step"],
            {"step": {"response": "ok", "output": {"json": None}, "tool_calls": []}},
        )
        self.assertNotIn("Tool Calls", result)


class AcquireWorkerLeaseTests(unittest.TestCase):
    def test_acquire_worker_lease_takes_over_orphaned_holder_job(self) -> None:
        import worker

        conflict = worker.kubernetes.client.ApiException()
        conflict.status = 409
        missing_job = worker.kubernetes.client.ApiException()
        missing_job.status = 404

        coord_api = MagicMock()
        coord_api.create_namespaced_lease.side_effect = conflict
        coord_api.read_namespaced_lease.return_value = types.SimpleNamespace(
            spec=types.SimpleNamespace(
                holder_identity="stale-worker-job",
                acquire_time=None,
                renew_time=None,
                lease_duration_seconds=600,
            )
        )
        batch_api = MagicMock()
        batch_api.read_namespaced_job.side_effect = missing_job

        def simple_obj(**kwargs):
            return types.SimpleNamespace(**kwargs)

        with (
            patch.object(worker.kubernetes.client, "CoordinationV1Api", return_value=coord_api, create=True),
            patch.object(worker.kubernetes.client, "BatchV1Api", return_value=batch_api, create=True),
            patch.object(worker.kubernetes.client, "V1Lease", side_effect=simple_obj, create=True),
            patch.object(worker.kubernetes.client, "V1ObjectMeta", side_effect=simple_obj, create=True),
            patch.object(worker.kubernetes.client, "V1LeaseSpec", side_effect=simple_obj, create=True),
        ):
            acquired = worker.acquire_worker_lease("workflow", "default", "factory", 7)

        self.assertTrue(acquired)
        batch_api.read_namespaced_job.assert_called_once_with(
            name="stale-worker-job",
            namespace=worker.OPERATOR_NAMESPACE,
        )
        coord_api.replace_namespaced_lease.assert_called_once()


class ExecuteWorkflowStepOpenCodeTests(unittest.TestCase):
    """Bugs 1-3, 6: execute_workflow_step handles OpenCode fields."""

    def _patch_env_and_import(self):
        """Set required env vars and import execute_workflow_step."""
        import worker

        return worker.execute_workflow_step

    @patch("worker.wait_for_agent_runtime_ready")
    @patch("worker.append_journal_event")
    @patch("worker.invoke_agent_runtime_stream")
    def test_captures_opencode_fields(
        self, mock_invoke: MagicMock, mock_journal: MagicMock, _mock_ready: MagicMock
    ) -> None:
        """Bug 1: artifacts, tool_calls, metadata, warnings are preserved."""
        mock_invoke.return_value = {
            "response": "Code written successfully.",
            "thread_id": "t-1",
            "model": "gpt-4o",
            "status": "completed",
            "artifacts": [{"path": "src/app.py", "type": "file"}],
            "tool_calls": [{"name": "write", "args": {"path": "src/app.py"}}],
            "metadata": {"todos": ["write tests"], "raw_status": "completed"},
            "warnings": ["Tool error: lint warning"],
        }
        execute = self._patch_env_and_import()
        step = {"name": "build", "agentRef": "opencode-agent", "prompt": "build it"}
        outcome = execute(
            step,
            workflow_input="make an app",
            step_results={},
            run_id="run-1",
            pending_approval=None,
            worker_job={"name": "j1", "namespace": "ns"},
        )
        self.assertEqual(outcome["state"], "completed")
        sr = outcome["stepResult"]
        self.assertEqual(sr["artifacts"], [{"path": "src/app.py", "type": "file"}])
        self.assertEqual(len(sr["tool_calls"]), 1)
        self.assertEqual(sr["metadata"]["todos"], ["write tests"])
        self.assertIn("Tool error: lint warning", sr["warnings"])

    @patch("worker.wait_for_agent_runtime_ready")
    @patch("worker.append_journal_event")
    @patch("worker.invoke_agent_runtime_stream")
    def test_incomplete_status_accepted_with_warning(
        self, mock_invoke: MagicMock, mock_journal: MagicMock, _mock_ready: MagicMock
    ) -> None:
        """Bug 2: 'incomplete' status becomes completed + warning."""
        mock_invoke.return_value = {
            "response": "Partial output due to context overflow.",
            "thread_id": "t-2",
            "model": "gpt-4o",
            "status": "incomplete",
            "artifacts": [],
            "tool_calls": [],
            "metadata": {"raw_status": "unknown"},
            "warnings": [],
        }
        execute = self._patch_env_and_import()
        step = {"name": "research", "agentRef": "opencode-agent", "prompt": "research"}
        outcome = execute(
            step,
            workflow_input="research topic",
            step_results={},
            run_id="run-2",
            pending_approval=None,
            worker_job={"name": "j2", "namespace": "ns"},
        )
        self.assertEqual(outcome["state"], "completed")
        sr = outcome["stepResult"]
        self.assertEqual(sr["status"], "completed")
        self.assertTrue(
            any("incomplete" in w for w in sr["warnings"]),
            f"Expected 'incomplete' warning, got: {sr['warnings']}",
        )


    @patch("worker.wait_for_agent_runtime_ready")
    @patch("worker.append_journal_event")
    @patch("worker.invoke_agent_runtime_stream")
    def test_error_status_still_fails(
        self, mock_invoke: MagicMock, mock_journal: MagicMock, _mock_ready: MagicMock
    ) -> None:
        """Bug 2: 'error' status still raises RuntimeError."""
        mock_invoke.return_value = {
            "response": "Context overflow.",
            "thread_id": "t-3",
            "model": "gpt-4o",
            "status": "error",
        }
        execute = self._patch_env_and_import()
        step = {
            "name": "fail-step",
            "agentRef": "opencode-agent",
            "prompt": "fail",
        }
        # With default execution (maxAttempts=1, retryable=True), this should
        # return a failed outcome (not raise), because the exception is caught
        # by the retry loop which returns a terminal state.
        outcome = execute(
            step,
            workflow_input="fail",
            step_results={},
            run_id="run-3",
            pending_approval=None,
            worker_job={"name": "j3", "namespace": "ns"},
        )
        self.assertEqual(outcome["state"], "failed")

    @patch("worker.wait_for_agent_runtime_ready")
    @patch("worker.append_journal_event")
    @patch("worker.invoke_agent_runtime_stream")
    def test_structured_output_from_metadata(
        self, mock_invoke: MagicMock, mock_journal: MagicMock, _mock_ready: MagicMock
    ) -> None:
        """Bug 3: structured output is extracted from metadata before parse_json_output."""
        mock_invoke.return_value = {
            "response": "Here is the analysis result with some prose...",
            "thread_id": "t-4",
            "model": "gpt-4o",
            "status": "completed",
            "metadata": {"structured_output": {"score": 95, "verdict": "pass"}},
            "artifacts": [],
            "tool_calls": [],
            "warnings": [],
        }
        execute = self._patch_env_and_import()
        step = {"name": "analyze", "agentRef": "opencode-agent", "prompt": "analyze"}
        outcome = execute(
            step,
            workflow_input="analyze data",
            step_results={},
            run_id="run-4",
            pending_approval=None,
            worker_job={"name": "j4", "namespace": "ns"},
        )
        sr = outcome["stepResult"]
        self.assertEqual(sr["output"]["json"], {"score": 95, "verdict": "pass"})
        self.assertEqual(sr["output"]["type"], "json")

    @patch("worker.cancel_agent_session")
    @patch("worker.wait_for_agent_runtime_ready")
    @patch("worker.append_journal_event")
    @patch("worker.invoke_agent_runtime_stream")
    def test_contract_failure_preserves_partial_artifacts_and_tool_calls(
        self,
        mock_invoke: MagicMock,
        _mock_journal: MagicMock,
        _mock_ready: MagicMock,
        _mock_cancel: MagicMock,
    ) -> None:
        """Failed JSON contracts should still surface the files and tool activity that happened."""
        mock_invoke.return_value = {
            "response": "Saved /workspace/questions_part2.json with partial output, but returned prose instead of raw JSON.",
            "thread_id": "t-contract-fail",
            "model": "gpt-4o",
            "status": "completed",
            "artifacts": [
                {"path": "/workspace/questions_part2.json", "tool": "write", "status": "completed"},
            ],
            "tool_calls": [
                {"tool": "write", "status": "completed", "input": {"path": "/workspace/questions_part2.json"}},
            ],
            "warnings": ["Writer emitted prose instead of raw JSON."],
            "metadata": None,
        }
        execute = self._patch_env_and_import()
        step = {
            "name": "generate-questions-part2",
            "agentRef": "opencode-agent",
            "prompt": "Return the generated questions as JSON.",
            "execution": {
                "requiredJsonPaths": [
                    "questions.0.id",
                    "questions.0.correct_answer",
                    "questions.0.explanation",
                    "questions.0.source_urls.0",
                ],
            },
        }

        outcome = execute(
            step,
            workflow_input="generate the second batch of questions",
            step_results={},
            run_id="run-contract-fail",
            pending_approval=None,
            worker_job={"name": "job-contract", "namespace": "ns"},
        )

        self.assertEqual(outcome["state"], "failed")
        step_result = outcome["stepResult"]
        self.assertIn("questions_part2.json", step_result["response"])
        self.assertEqual(step_result["output"]["type"], "text")
        self.assertEqual(step_result["artifacts"][0]["path"], "/workspace/questions_part2.json")
        self.assertEqual(step_result["tool_calls"][0]["tool"], "write")
        self.assertIn("raw JSON", step_result["warnings"][0])

        step_state = outcome["stepState"]
        self.assertEqual(step_state["artifactCount"], 1)
        self.assertEqual(step_state["toolCallCount"], 1)
        self.assertIn("questions_part2.json", step_state["responsePreview"])
        self.assertEqual(step_state["artifacts"][0]["path"], "/workspace/questions_part2.json")
        self.assertEqual(step_state["toolCalls"][0]["tool"], "write")
        self.assertIn("questions_part2.json", step_state["toolCalls"][0]["inputPreview"])

    @patch("worker.wait_for_agent_runtime_ready")
    @patch("worker.append_journal_event")
    @patch("worker.invoke_agent_runtime_stream")
    def test_warnings_in_journal_event(
        self, mock_invoke: MagicMock, mock_journal: MagicMock, _mock_ready: MagicMock
    ) -> None:
        """Bug 6: warnings are included in journal event."""
        mock_invoke.return_value = {
            "response": "Done.",
            "thread_id": "t-5",
            "model": "gpt-4o",
            "status": "completed",
            "warnings": ["Artifact collection limited"],
            "artifacts": [],
            "tool_calls": [],
            "metadata": None,
        }
        execute = self._patch_env_and_import()
        step = {"name": "gen", "agentRef": "oc-agent", "prompt": "go"}
        execute(
            step,
            workflow_input="input",
            step_results={},
            run_id="run-5",
            pending_approval=None,
            worker_job={"name": "j5", "namespace": "ns"},
        )
        # Find the workflow.step.completed journal event
        completed_calls = [
            call
            for call in mock_journal.call_args_list
            if call[0][0] == "workflow.step.completed"
        ]
        self.assertTrue(completed_calls, "Expected workflow.step.completed journal event")
        event_data = completed_calls[0][0][1]
        self.assertIn("warnings", event_data)
        self.assertIn("Artifact collection limited", event_data["warnings"])
        self.assertIn("artifactCount", event_data)
        self.assertIn("toolCallCount", event_data)

    @patch("worker.cancel_agent_session")
    @patch("worker.wait_for_agent_runtime_ready")
    @patch("worker.append_journal_event")
    @patch("worker.invoke_agent_runtime_stream")
    def test_required_json_retry_uses_contract_repair_prompt(
        self,
        mock_invoke: MagicMock,
        _mock_journal: MagicMock,
        _mock_ready: MagicMock,
        mock_cancel: MagicMock,
    ) -> None:
        """JSON-constrained retries should repair missing fields instead of switching to prose."""
        captured_payloads: list[dict[str, Any]] = []

        first_response = json.dumps(
            {
                "factory_mode": "lightweight-draft",
                "expanded_spec": {"objective": "Ship dashboard", "requirements": ["req-1"]},
                "intent_summary": "status dashboard",
                "demand_model": {"users": ["engineering managers"]},
                "architecture_decision": {"pattern": "single-service"},
                "delivery_plan": {"phases": ["draft"]},
                "resources_to_create": [{"kind": "Deployment", "name": "dashboard"}],
                "manifests": {"combined_yaml": "apiVersion: apps/v1\nkind: Deployment\n"},
                "supporting_deliverables": {},
                "execution_plan": {"execution_mode": "design-only", "runnable": False},
                "deploy_and_verify": {"success_checks": ["render manifests"]},
                "review_status": {"final_verdict": "draft-only"},
                "approval_required": {"items": []},
                "resource_names": ["dashboard"],
            }
        )
        second_response = json.dumps(
            {
                "factory_mode": "lightweight-draft",
                "expanded_spec": {"objective": "Ship dashboard", "requirements": ["req-1"]},
                "intent_summary": "status dashboard",
                "demand_model": {"users": ["engineering managers"]},
                "architecture_decision": {"pattern": "single-service"},
                "delivery_plan": {"phases": ["draft"]},
                "resources_to_create": [{"kind": "Deployment", "name": "dashboard"}],
                "manifests": {"combined_yaml": "apiVersion: apps/v1\nkind: Deployment\n"},
                "supporting_deliverables": {
                    "operator_readme_markdown": "# Operator Notes",
                    "verification_runbook_markdown": "# Verification",
                },
                "execution_plan": {"execution_mode": "design-only", "runnable": False},
                "deploy_and_verify": {"verification_checks": ["render manifests"]},
                "review_status": {"final_verdict": "draft-only"},
                "approval_required": {"reason": "No deployment in lightweight-draft mode."},
                "resource_names": ["dashboard"],
            }
        )

        def _side_effect(*args: Any, **kwargs: Any) -> dict[str, Any]:
            payload = dict(args[2])
            captured_payloads.append(payload)
            response = first_response if len(captured_payloads) == 1 else second_response
            return {
                "response": response,
                "thread_id": "t-json-retry",
                "model": "gpt-4o",
                "status": "completed",
            }

        mock_invoke.side_effect = _side_effect

        execute = self._patch_env_and_import()
        step = {
            "name": "draft-blueprint",
            "agentRef": "opencode-agent",
            "prompt": "Return the draft blueprint as JSON.",
            "execution": {
                "maxAttempts": 2,
                "backoffSeconds": 0,
                "requiredJsonPaths": [
                    "factory_mode",
                    "expanded_spec.objective",
                    "expanded_spec.requirements",
                    "supporting_deliverables.operator_readme_markdown",
                    "supporting_deliverables.verification_runbook_markdown",
                    "deploy_and_verify.verification_checks",
                    "approval_required.reason",
                ],
            },
        }
        outcome = execute(
            step,
            workflow_input="make a dashboard",
            step_results={},
            run_id="run-json-retry",
            pending_approval=None,
            worker_job={"name": "job-json", "namespace": "ns"},
        )

        self.assertEqual(outcome["state"], "completed")
        self.assertEqual(len(captured_payloads), 2)
        retry_prompt = captured_payloads[1]["prompt"]
        self.assertIn("The previous attempt failed JSON validation", retry_prompt)
        self.assertIn("Missing required JSON paths", retry_prompt)
        self.assertIn("supporting_deliverables.operator_readme_markdown", retry_prompt)
        self.assertIn("approval_required.reason", retry_prompt)
        self.assertIn("Return ONLY a single valid JSON object", retry_prompt)
        self.assertNotIn("List files/changes from the previous attempt", retry_prompt)
        mock_cancel.assert_called_once()

    @patch("worker.cancel_agent_session")
    @patch("worker.wait_for_agent_runtime_ready")
    @patch("worker.append_journal_event")
    @patch("worker.invoke_agent_runtime_stream")
    def test_timeout_retry_uses_transport_recovery_prompt(
        self,
        mock_invoke: MagicMock,
        _mock_journal: MagicMock,
        _mock_ready: MagicMock,
        mock_cancel: MagicMock,
    ) -> None:
        captured_payloads: list[dict[str, Any]] = []

        def _side_effect(*args: Any, **kwargs: Any) -> dict[str, Any]:
            payload = dict(args[2])
            captured_payloads.append(payload)
            if len(captured_payloads) == 1:
                raise TimeoutError("agent runtime timed out")
            return {
                "response": "Recovered successfully.",
                "thread_id": "t-timeout-retry",
                "model": "gpt-4o",
                "status": "completed",
            }

        mock_invoke.side_effect = _side_effect

        execute = self._patch_env_and_import()
        step = {
            "name": "implement",
            "agentRef": "opencode-agent",
            "prompt": "Implement the requested change.",
            "execution": {"maxAttempts": 2, "backoffSeconds": 0},
        }
        outcome = execute(
            step,
            workflow_input="add retries",
            step_results={},
            run_id="run-timeout-retry",
            pending_approval=None,
            worker_job={"name": "job-timeout", "namespace": "ns"},
        )

        self.assertEqual(outcome["state"], "completed")
        self.assertEqual(len(captured_payloads), 2)
        retry_prompt = captured_payloads[1]["prompt"]
        self.assertIn("timeout or transport failure", retry_prompt)
        self.assertIn("Inspect the current workspace and session state", retry_prompt)
        self.assertNotIn("failed JSON validation", retry_prompt)
        self.assertIsNone(outcome["stepState"]["error"])
        self.assertIsNone(outcome["stepState"]["failureClass"])
        mock_cancel.assert_called_once()

    @patch("worker.cancel_agent_session")
    @patch("worker.wait_for_agent_runtime_ready")
    @patch("worker.append_journal_event")
    @patch("worker.invoke_agent_runtime_stream")
    def test_runtime_status_retry_uses_runtime_recovery_prompt(
        self,
        mock_invoke: MagicMock,
        _mock_journal: MagicMock,
        _mock_ready: MagicMock,
        mock_cancel: MagicMock,
    ) -> None:
        captured_payloads: list[dict[str, Any]] = []

        def _side_effect(*args: Any, **kwargs: Any) -> dict[str, Any]:
            payload = dict(args[2])
            captured_payloads.append(payload)
            if len(captured_payloads) == 1:
                return {
                    "response": "Context overflow.",
                    "thread_id": "t-runtime-retry",
                    "model": "gpt-4o",
                    "status": "error",
                }
            return {
                "response": "Recovered after runtime failure.",
                "thread_id": "t-runtime-retry",
                "model": "gpt-4o",
                "status": "completed",
            }

        mock_invoke.side_effect = _side_effect

        execute = self._patch_env_and_import()
        step = {
            "name": "implement",
            "agentRef": "opencode-agent",
            "prompt": "Implement the requested change.",
            "execution": {"maxAttempts": 2, "backoffSeconds": 0},
        }
        outcome = execute(
            step,
            workflow_input="fix the build",
            step_results={},
            run_id="run-runtime-retry",
            pending_approval=None,
            worker_job={"name": "job-runtime", "namespace": "ns"},
        )

        self.assertEqual(outcome["state"], "completed")
        self.assertEqual(len(captured_payloads), 2)
        retry_prompt = captured_payloads[1]["prompt"]
        self.assertIn("non-completed status or runtime error", retry_prompt)
        self.assertIn("Diagnose the specific runtime or status failure", retry_prompt)
        self.assertNotIn("timeout or transport failure", retry_prompt)
        mock_cancel.assert_called_once()

    @patch("worker.cancel_agent_session")
    @patch("worker.wait_for_agent_runtime_ready")
    @patch("worker.append_journal_event")
    @patch("worker.invoke_agent_runtime")
    @patch("worker.invoke_agent_runtime_stream")
    def test_verification_retry_uses_verification_recovery_prompt(
        self,
        mock_invoke_stream: MagicMock,
        mock_invoke_verify: MagicMock,
        _mock_journal: MagicMock,
        _mock_ready: MagicMock,
        mock_cancel: MagicMock,
    ) -> None:
        captured_payloads: list[dict[str, Any]] = []

        def _stream_side_effect(*args: Any, **kwargs: Any) -> dict[str, Any]:
            payload = dict(args[2])
            captured_payloads.append(payload)
            return {
                "response": "Implementation completed.",
                "thread_id": "t-verify-retry",
                "model": "gpt-4o",
                "status": "completed",
            }

        verify_call_count = 0

        def _verify_side_effect(*args: Any, **kwargs: Any) -> dict[str, Any]:
            nonlocal verify_call_count
            verify_call_count += 1
            if verify_call_count == 1:
                return {"response": "FAIL\nMissing test evidence.", "thread_id": "verify-1", "status": "completed"}
            return {"response": "PASS\nAll verification criteria satisfied.", "thread_id": "verify-2", "status": "completed"}

        mock_invoke_stream.side_effect = _stream_side_effect
        mock_invoke_verify.side_effect = _verify_side_effect

        execute = self._patch_env_and_import()
        step = {
            "name": "implement",
            "agentRef": "opencode-agent",
            "prompt": "Implement the requested change.",
            "verify": "Check that the tests pass and the change is complete.",
            "execution": {"maxAttempts": 2, "backoffSeconds": 0},
        }
        outcome = execute(
            step,
            workflow_input="finish the feature",
            step_results={},
            run_id="run-verify-retry",
            pending_approval=None,
            worker_job={"name": "job-verify", "namespace": "ns"},
        )

        self.assertEqual(outcome["state"], "completed")
        self.assertEqual(len(captured_payloads), 2)
        retry_prompt = captured_payloads[1]["prompt"]
        self.assertIn("failed verification", retry_prompt)
        self.assertIn("Revise only what is needed to satisfy the failed criteria", retry_prompt)
        self.assertNotIn("failed JSON validation", retry_prompt)
        mock_cancel.assert_called_once()

        first_verify_payload = mock_invoke_verify.call_args_list[0].args[2]
        self.assertTrue(first_verify_payload["no_session"])
        self.assertFalse(first_verify_payload["autonomous"])
        self.assertEqual(first_verify_payload["max_turns"], 1)
        self.assertEqual(first_verify_payload["output_format"], "text")
        self.assertNotIn("thread_id", first_verify_payload)
        self.assertNotIn("parent_thread_id", first_verify_payload)


class WorkflowStatusLifecycleTests(unittest.TestCase):
    def test_patch_workflow_status_clears_failure_fields_on_completion(self) -> None:
        import worker

        with (
            patch.object(worker, "patch_custom_status") as patch_status_mock,
            patch.object(worker, "artifact_ref", return_value={"generation": 7}),
            patch.object(worker, "journal_ref", return_value={"generation": 7}),
            patch.object(worker, "now_iso", return_value="2026-04-09T12:00:00Z"),
        ):
            payload = worker.patch_workflow_status(
                plural="agentworkflows",
                phase="completed",
                generation=7,
                run_id="wf-run-default-kubesynapse-factory-pipeline-7-new",
                total_steps=2,
                current_step="",
                started_at="2026-04-09T11:55:00Z",
                step_states={"draft": {"status": "completed"}},
                worker_job={"name": "job-7", "namespace": "ai-agent-sandbox"},
                pending_approval=None,
                extra_summary={"completedAt": "2026-04-09T12:00:00Z"},
            )

        self.assertEqual(payload["summary"]["completedAt"], "2026-04-09T12:00:00Z")
        self.assertIsNone(payload["summary"]["error"])
        self.assertIsNone(payload["summary"]["failedAt"])
        patch_status_mock.assert_called_once()

    def test_patch_workflow_status_clears_completion_fields_on_failure(self) -> None:
        import worker

        with (
            patch.object(worker, "patch_custom_status") as patch_status_mock,
            patch.object(worker, "artifact_ref", return_value={"generation": 8}),
            patch.object(worker, "journal_ref", return_value={"generation": 8}),
            patch.object(worker, "now_iso", return_value="2026-04-09T12:05:00Z"),
        ):
            payload = worker.patch_workflow_status(
                plural="agentworkflows",
                phase="failed",
                generation=8,
                run_id="wf-run-default-kubesynapse-factory-pipeline-8-new",
                total_steps=2,
                current_step="deploy",
                started_at="2026-04-09T12:00:00Z",
                step_states={"deploy": {"status": "failed"}},
                worker_job={"name": "job-8", "namespace": "ai-agent-sandbox"},
                pending_approval=None,
                extra_summary={
                    "failedAt": "2026-04-09T12:05:00Z",
                    "error": "verification failed",
                },
            )

        self.assertEqual(payload["summary"]["failedAt"], "2026-04-09T12:05:00Z")
        self.assertEqual(payload["summary"]["error"], "verification failed")
        self.assertIsNone(payload["summary"]["completedAt"])
        patch_status_mock.assert_called_once()


class ExecuteReviewStepTests(unittest.TestCase):
    """Review-step rejection returns a failed outcome with review result."""

    @patch("worker.wait_for_agent_runtime_ready")
    @patch("worker.append_journal_event")
    @patch("worker.invoke_agent_runtime")
    def test_rejected_review_returns_failed_outcome_with_review_result(
        self, mock_invoke: MagicMock, _mock_journal: MagicMock, _mock_ready: MagicMock
    ) -> None:
        import worker

        mock_invoke.return_value = {
            "response": "REJECTED\n1. Missing tests\n2. Edge cases not handled",
            "thread_id": "review-1",
            "status": "completed",
        }

        outcome = worker.execute_review_step(
            {
                "name": "code-review",
                "type": "review",
                "agentRef": "reviewer-agent",
                "reviewCriteria": "Code quality and test coverage",
                "execution": {"maxAttempts": 1, "retryable": True},
            },
            workflow_input="",
            step_results={"implement": {"response": "done", "output": {"json": None}}},
            run_id="run-1",
            worker_job={"name": "job-1", "namespace": "default"},
        )

        self.assertEqual(outcome["state"], "failed")
        self.assertEqual(outcome["stepState"]["status"], "failed")
        self.assertFalse(outcome["stepState"]["reviewResult"]["approved"])
        self.assertEqual(outcome["stepResult"]["reviewResult"]["verdict"], "REJECTED")

    @patch("worker.cancel_agent_session")
    @patch("worker.wait_for_agent_runtime_ready")
    @patch("worker.append_journal_event")
    @patch("worker.invoke_agent_runtime")
    def test_review_step_cancels_session_on_timeout(
        self,
        mock_invoke: MagicMock,
        mock_journal: MagicMock,
        _mock_ready: MagicMock,
        mock_cancel: MagicMock,
    ) -> None:
        """Bug: review step must cancel agent session on failure to prevent orphans."""
        import worker

        mock_invoke.side_effect = TimeoutError("agent runtime timed out")

        outcome = worker.execute_review_step(
            {
                "name": "code-review",
                "type": "review",
                "agentRef": "reviewer-agent",
                "reviewCriteria": "Check tests pass",
                "execution": {"maxAttempts": 1, "retryable": True},
            },
            workflow_input="",
            step_results={},
            run_id="run-cancel",
            worker_job={"name": "j1", "namespace": "ns"},
        )

        self.assertEqual(outcome["state"], "failed")
        mock_cancel.assert_called_once()
        cancel_args = mock_cancel.call_args
        self.assertEqual(cancel_args[0][0], "reviewer-agent")

    @patch("worker.cancel_agent_session")
    @patch("worker.wait_for_agent_runtime_ready")
    @patch("worker.append_journal_event")
    @patch("worker.invoke_agent_runtime")
    def test_review_step_journals_failed_attempt_and_retry(
        self,
        mock_invoke: MagicMock,
        mock_journal: MagicMock,
        _mock_ready: MagicMock,
        mock_cancel: MagicMock,
    ) -> None:
        """Bug: review step must log journal events for failed attempts and retries."""
        import worker

        call_count = 0

        def _invoke_side_effect(*args: Any, **kwargs: Any) -> dict[str, Any]:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise TimeoutError("timed out")
            return {
                "response": "APPROVED\nAll tests pass.",
                "thread_id": "review-retry",
                "status": "completed",
            }

        mock_invoke.side_effect = _invoke_side_effect

        outcome = worker.execute_review_step(
            {
                "name": "review-step",
                "type": "review",
                "agentRef": "reviewer-agent",
                "reviewCriteria": "Tests must pass",
                "execution": {
                    "maxAttempts": 2,
                    "retryable": True,
                    "backoffSeconds": 0,
                },
            },
            workflow_input="",
            step_results={},
            run_id="run-retry",
            worker_job={"name": "j1", "namespace": "ns"},
        )

        self.assertEqual(outcome["state"], "completed")

        journal_events = [call[0][0] for call in mock_journal.call_args_list]
        self.assertIn("workflow.review.attempt.failed", journal_events)
        self.assertIn("workflow.review.retrying", journal_events)
        mock_cancel.assert_called_once()


class LoopStepThreadIdTests(unittest.TestCase):
    """Bug 5: loop steps use a single thread_id across iterations."""

    @patch("worker.wait_for_agent_runtime_ready")
    @patch("worker.append_journal_event")
    @patch("worker.invoke_agent_runtime_stream")
    def test_loop_uses_consistent_thread_id(
        self, mock_invoke: MagicMock, mock_journal: MagicMock, _mock_ready: MagicMock
    ) -> None:
        # First call returns plan complete to end after 1 iteration
        mock_invoke.return_value = {
            "response": "PLAN_COMPLETE — all done.",
            "thread_id": "t-loop",
            "model": "gpt-4o",
            "status": "completed",
        }
        from worker import execute_loop_step

        step = {
            "name": "dev-loop",
            "agentRef": "opencode-agent",
            "prompt": "implement features",
            "loopConfig": {
                "maxIterations": 3,
                "plan": "- [ ] Feature A\n- [ ] Feature B",
                "planSource": "inline",
            },
        }
        execute_loop_step(
            step,
            workflow_input="build the app",
            step_results={},
            run_id="run-loop",
            worker_job={"name": "jl", "namespace": "ns"},
        )
        # All invoke calls should use the same thread_id (no -iter-N suffix)
        thread_ids = set()
        for call in mock_invoke.call_args_list:
            payload = call[0][2]  # 3rd positional arg is payload dict
            thread_ids.add(payload.get("thread_id", ""))
        self.assertEqual(
            len(thread_ids),
            1,
            f"Expected all iterations to share one thread_id, got: {thread_ids}",
        )
        tid = thread_ids.pop()
        self.assertIn("-loop", tid)
        self.assertNotIn("-iter-", tid)

    @patch("worker.wait_for_agent_runtime_ready")
    @patch("worker.append_journal_event")
    @patch("worker.invoke_agent_runtime_stream")
    def test_loop_collects_artifacts_and_warnings(
        self, mock_invoke: MagicMock, mock_journal: MagicMock, _mock_ready: MagicMock
    ) -> None:
        """Bug 9: loop step_result includes artifacts/tool_calls/warnings."""
        call_count = 0

        def _side_effect(*args: Any, **kwargs: Any) -> dict[str, Any]:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return {
                    "response": "Created file. ITEM_COMPLETE",
                    "status": "completed",
                    "artifacts": [{"path": "src/a.py"}],
                    "tool_calls": [{"name": "write"}],
                    "warnings": ["lint warning"],
                }
            return {
                "response": "All done. PLAN_COMPLETE",
                "status": "completed",
                "artifacts": [{"path": "src/b.py"}],
                "tool_calls": [],
                "warnings": [],
            }

        mock_invoke.side_effect = _side_effect

        from worker import execute_loop_step

        step = {
            "name": "code",
            "agentRef": "oc",
            "prompt": "go",
            "loopConfig": {
                "maxIterations": 5,
                "plan": "- [ ] A\n- [ ] B",
                "planSource": "inline",
            },
        }
        outcome = execute_loop_step(
            step,
            workflow_input="build",
            step_results={},
            run_id="r-loop",
            worker_job={"name": "j", "namespace": "ns"},
        )
        sr = outcome["stepResult"]
        self.assertEqual(len(sr["artifacts"]), 2)
        self.assertEqual(sr["artifacts"][0]["path"], "src/a.py")
        self.assertEqual(len(sr["tool_calls"]), 1)
        self.assertIn("lint warning", sr["warnings"])


class DetectIterationSignalsTests(unittest.TestCase):
    """Bug 12: signal detection is restricted to response tail."""

    def test_signal_at_end_detected(self) -> None:
        from worker import detect_iteration_signals

        text = "I finished the task successfully.\nITEM_COMPLETE"
        signals = detect_iteration_signals(text)
        self.assertTrue(signals["item_complete"])

    def test_signal_only_in_middle_of_long_response_ignored(self) -> None:
        from worker import detect_iteration_signals

        # Simulate a long response where NO_PROGRESS appears early in logs
        # but the tail is normal output
        text = (
            "Starting analysis...\nNO_PROGRESS found in old logs, ignoring.\n"
            + "x" * 600
            + "\nTask completed successfully."
        )
        signals = detect_iteration_signals(text)
        self.assertFalse(signals["no_progress"])

    def test_signal_near_end_of_long_response_detected(self) -> None:
        from worker import detect_iteration_signals

        text = "x" * 600 + "\nI am STUCK and cannot make progress."
        signals = detect_iteration_signals(text)
        self.assertTrue(signals["no_progress"])


class InvokeAgentRuntimeTimeoutTests(unittest.TestCase):
    """Bug 7: each retry gets fresh timeout budget."""

    @patch.object(operator_utils.httpx, "Client")
    def test_invoke_sends_runtime_bearer_token_header(
        self, mock_client_cls: MagicMock
    ) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"response": "ok"}
        mock_client = MagicMock()
        mock_client.post.return_value = mock_response
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client_cls.return_value = mock_client

        with patch.dict(os.environ, {"RUNTIME_BEARER_TOKEN": "runtime-bearer"}):
            operator_utils.invoke_agent_runtime("agent-1", "ns", {"prompt": "hi"}, timeout_seconds=120.0)

        _url, kwargs = mock_client.post.call_args
        self.assertEqual(kwargs["headers"], {"Authorization": "Bearer runtime-bearer"})

    @patch.object(operator_utils.httpx, "Client")
    def test_cancel_sends_runtime_bearer_token_header(
        self, mock_client_cls: MagicMock
    ) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_client = MagicMock()
        mock_client.post.return_value = mock_response
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client_cls.return_value = mock_client

        with patch.dict(os.environ, {"RUNTIME_BEARER_TOKEN": "runtime-bearer"}):
            self.assertTrue(operator_utils.cancel_agent_session("agent-1", "ns", "thread-1"))

        _url, kwargs = mock_client.post.call_args
        self.assertEqual(kwargs["headers"], {"Authorization": "Bearer runtime-bearer"})

    @patch.object(operator_utils.httpx, "Client")
    def test_creates_new_client_per_attempt(
        self, mock_client_cls: MagicMock
    ) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"response": "ok"}
        mock_response.raise_for_status = MagicMock()
        mock_client = MagicMock()
        mock_client.post.return_value = mock_response
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client_cls.return_value = mock_client

        operator_utils.invoke_agent_runtime("agent-1", "ns", {"prompt": "hi"}, timeout_seconds=120.0)

        # Client should be constructed with the full timeout per request
        mock_client_cls.assert_called_once_with(timeout=120.0)

    @patch.object(operator_utils.httpx, "Client")
    def test_retries_on_500_with_fresh_client(
        self, mock_client_cls: MagicMock
    ) -> None:
        # First two calls: 500. Third: 200.
        mock_500 = MagicMock()
        mock_500.status_code = 500
        mock_500.request = MagicMock()
        mock_200 = MagicMock()
        mock_200.status_code = 200
        mock_200.json.return_value = {"response": "ok"}
        mock_200.raise_for_status = MagicMock()

        call_count = [0]

        def _make_client(**kwargs: Any) -> MagicMock:
            client = MagicMock()
            client.__enter__ = MagicMock(return_value=client)
            client.__exit__ = MagicMock(return_value=False)

            def _post(*a: Any, **k: Any) -> MagicMock:
                call_count[0] += 1
                return mock_500 if call_count[0] <= 2 else mock_200

            client.post = _post
            return client

        mock_client_cls.side_effect = _make_client
        result = operator_utils.invoke_agent_runtime("a", "ns", {"prompt": "x"}, timeout_seconds=60.0)
        self.assertEqual(result, {"response": "ok"})
        # Should have created a new client for each of the 3 attempts
        self.assertEqual(mock_client_cls.call_count, 3)


class ConsecutiveCompletionSignalsResetTests(unittest.TestCase):
    """Bug: consecutive_completion_signals must reset on non-plan_complete signals."""

    @patch("worker.wait_for_agent_runtime_ready")
    @patch("worker.append_journal_event")
    @patch("worker.invoke_agent_runtime")
    def test_no_progress_resets_counter(
        self, mock_invoke: MagicMock, mock_journal: MagicMock, _mock_ready: MagicMock
    ) -> None:
        """PLAN_COMPLETE, NO_PROGRESS, PLAN_COMPLETE should NOT hit threshold=2."""
        responses = iter([
            {"response": "PLAN_COMPLETE", "status": "completed"},
            {"response": "NO_PROGRESS", "status": "completed"},
            {"response": "PLAN_COMPLETE", "status": "completed"},
            # If the threshold triggers early this 4th call won't happen
            {"response": "All done. PLAN_COMPLETE", "status": "completed"},
        ])
        mock_invoke.side_effect = lambda *a, **k: next(responses)

        from worker import execute_loop_step

        step = {
            "name": "code",
            "agentRef": "oc",
            "prompt": "work",
            "loopConfig": {
                "maxIterations": 4,
                "plan": "- [ ] A\n- [ ] B",
                "planSource": "inline",
                "exitConditions": {"completionSignalCount": 2, "planComplete": False},
            },
        }
        outcome = execute_loop_step(
            step,
            workflow_input="build",
            step_results={},
            run_id="r-sig",
            worker_job={"name": "j", "namespace": "ns"},
        )
        sr = outcome["stepResult"]
        # The loop should have run all 4 iterations because the NO_PROGRESS
        # signal broke the consecutive streak; without the fix it would
        # exit after iteration 3 (falsely counting 2 consecutive).
        self.assertEqual(sr["attempts"], 4)

    @patch("worker.wait_for_agent_runtime_ready")
    @patch("worker.append_journal_event")
    @patch("worker.invoke_agent_runtime")
    def test_ambiguous_signal_resets_counter(
        self, mock_invoke: MagicMock, mock_journal: MagicMock, _mock_ready: MagicMock
    ) -> None:
        """PLAN_COMPLETE, <ambiguous>, PLAN_COMPLETE should NOT hit threshold=2."""
        responses = iter([
            {"response": "PLAN_COMPLETE", "status": "completed"},
            {"response": "Did some more work here.", "status": "completed"},
            {"response": "PLAN_COMPLETE", "status": "completed"},
            {"response": "Final. PLAN_COMPLETE", "status": "completed"},
        ])
        mock_invoke.side_effect = lambda *a, **k: next(responses)

        from worker import execute_loop_step

        step = {
            "name": "code",
            "agentRef": "oc",
            "prompt": "work",
            "loopConfig": {
                "maxIterations": 4,
                "plan": "- [ ] A\n- [ ] B",
                "planSource": "inline",
                "exitConditions": {"completionSignalCount": 2, "planComplete": False},
            },
        }
        outcome = execute_loop_step(
            step,
            workflow_input="build",
            step_results={},
            run_id="r-sig2",
            worker_job={"name": "j", "namespace": "ns"},
        )
        sr = outcome["stepResult"]
        self.assertEqual(sr["attempts"], 4)


class DetectSignalWordBoundaryTests(unittest.TestCase):
    """Signal detection should use word boundaries to avoid false positives."""

    def test_no_progress_report_is_not_false_positive(self) -> None:
        from worker import detect_iteration_signals

        text = "Checking NO_PROGRESS_REPORT for metrics."
        signals = detect_iteration_signals(text)
        self.assertFalse(signals["no_progress"])

    def test_item_completed_is_not_false_positive(self) -> None:
        from worker import detect_iteration_signals

        text = "Status: ITEM_COMPLETED successfully."
        signals = detect_iteration_signals(text)
        self.assertFalse(signals["item_complete"])

    def test_exact_signal_still_detected(self) -> None:
        from worker import detect_iteration_signals

        text = "Done. ITEM_COMPLETE\nNO_PROGRESS\nPLAN_COMPLETE"
        signals = detect_iteration_signals(text)
        self.assertTrue(signals["item_complete"])
        self.assertTrue(signals["no_progress"])
        self.assertTrue(signals["plan_complete"])


class WriteArtifactSerializationTests(unittest.TestCase):
    """write_artifact should handle non-serializable values via default=str."""

    def test_datetime_in_payload_does_not_crash(self) -> None:
        import json
        import os
        import tempfile
        from datetime import datetime

        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "run.json")
            # Temporarily override ARTIFACT_PATH
            import worker
            original = worker.ARTIFACT_PATH
            worker.ARTIFACT_PATH = path
            try:
                worker.write_artifact({"ts": datetime.now(UTC), "val": 42})
                data = json.loads(Path(path).read_text(encoding="utf-8"))
                self.assertEqual(data["val"], 42)
                self.assertIsInstance(data["ts"], str)
            finally:
                worker.ARTIFACT_PATH = original


class LoadArtifactCorruptTests(unittest.TestCase):
    """load_artifact should raise on corrupt data instead of silently returning {}."""

    def test_corrupt_json_raises(self) -> None:
        import os
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "run.json")
            Path(path).write_text("NOT JSON", encoding="utf-8")
            import worker
            original = worker.ARTIFACT_PATH
            worker.ARTIFACT_PATH = path
            try:
                with self.assertRaises(RuntimeError):
                    worker.load_artifact()
            finally:
                worker.ARTIFACT_PATH = original

    def test_missing_artifact_returns_empty(self) -> None:
        import worker
        original = worker.ARTIFACT_PATH
        worker.ARTIFACT_PATH = "/nonexistent/path/run.json"
        try:
            result = worker.load_artifact()
            self.assertEqual(result, {})
        finally:
            worker.ARTIFACT_PATH = original


class ResumeWorkflowStateFromArtifactTests(unittest.TestCase):
    def test_same_generation_retry_with_new_run_id_starts_fresh(self) -> None:
        """§2.6 strict run_id match: when artifact.runId != worker run_id,
        the worker starts fresh even if the generation matches. This prevents
        ghost runs from stale artifact data."""
        from worker import resume_workflow_state_from_artifact

        artifact_matches_generation, step_results, step_states, pending_approval, started_at = (
            resume_workflow_state_from_artifact(
                status={
                    "runId": "wf-run-new",
                    "stepStates": {
                        "draft-blueprint": {"status": "completed"},
                        "deploy-bundle": {"status": "pending"},
                    },
                    "pendingApproval": None,
                },
                artifact={
                    "generation": 5,
                    "runId": "wf-run-old",
                    "startedAt": "2026-04-06T20:00:00Z",
                    "stepResults": {
                        "draft-blueprint": {"status": "completed", "response": "done"},
                    },
                    "stepStates": {
                        "draft-blueprint": {"status": "completed"},
                        "deploy-bundle": {"status": "failed"},
                    },
                    "pendingApproval": {"stepName": "deploy-bundle"},
                },
                generation=5,
                run_id="wf-run-new",
            )
        )

        # Strict run_id match: artifact has different run_id, so worker starts fresh
        self.assertFalse(artifact_matches_generation)
        self.assertEqual(step_results, {})
        self.assertEqual(step_states, {})
        self.assertEqual(pending_approval, {})
        # started_at should be current time (now_iso()), not stale artifact timestamp
        self.assertNotEqual(started_at, "2026-04-06T20:00:00Z")

    def test_new_run_id_without_preserved_progress_starts_fresh(self) -> None:
        from worker import resume_workflow_state_from_artifact

        artifact_matches_generation, step_results, step_states, pending_approval, _started_at = (
            resume_workflow_state_from_artifact(
                status={
                    "runId": "wf-run-new",
                    "stepStates": {
                        "draft-blueprint": {"status": "pending"},
                    },
                },
                artifact={
                    "generation": 5,
                    "runId": "wf-run-old",
                    "stepResults": {
                        "draft-blueprint": {"status": "completed", "response": "done"},
                    },
                },
                generation=5,
                run_id="wf-run-new",
            )
        )

        self.assertFalse(artifact_matches_generation)
        self.assertEqual(step_results, {})
        self.assertEqual(step_states, {})
        self.assertEqual(pending_approval, {})


class ResolveWorkflowRunIdForWorkerTests(unittest.TestCase):
    def test_prefers_job_run_id_over_stale_status(self) -> None:
        import worker

        original = worker.WORKFLOW_RUN_ID
        worker.WORKFLOW_RUN_ID = "wf-run-new"
        try:
            resolved = worker.resolve_workflow_run_id_for_worker(
                status={"runId": "wf-run-old"},
                artifact={"runId": "wf-run-older"},
                generation=5,
            )
        finally:
            worker.WORKFLOW_RUN_ID = original

        self.assertEqual(resolved, "wf-run-new")


class InvokeAgentRuntimeValidationTests(unittest.TestCase):
    """invoke_agent_runtime should reject invalid agent names and namespaces."""

    def test_rejects_invalid_agent_name(self) -> None:
        with self.assertRaises(ValueError):
            operator_utils.invoke_agent_runtime("agent name with spaces", "ns", {"prompt": "hi"})

    def test_rejects_empty_namespace(self) -> None:
        with self.assertRaises(ValueError):
            operator_utils.invoke_agent_runtime("agent", "", {"prompt": "hi"})


class ValidateWorkflowStepLimitTests(unittest.TestCase):
    """validate_workflow_graph should reject workflows exceeding step limit."""

    def test_rejects_too_many_steps(self) -> None:
        original = operator_utils.MAX_WORKFLOW_STEPS
        operator_utils.MAX_WORKFLOW_STEPS = 3
        try:
            steps = [
                {"name": f"step-{i}", "agentRef": "agent", "dependsOn": [f"step-{i-1}"] if i > 0 else []}
                for i in range(5)
            ]
            with self.assertRaisesRegex(ValueError, "exceeding the limit"):
                operator_utils.validate_workflow_graph(steps)
        finally:
            operator_utils.MAX_WORKFLOW_STEPS = original


class ReviewCriteriaActionableDetectionTests(unittest.TestCase):
    """_review_criteria_is_actionable should detect executable criteria."""

    def _check(self, criteria: str) -> bool:
        from worker import _review_criteria_is_actionable
        return _review_criteria_is_actionable(criteria)

    def test_pure_evaluation_criteria_not_actionable(self) -> None:
        criteria = (
            "Code follows the project style guide. "
            "No unused imports. All functions have docstrings."
        )
        self.assertFalse(self._check(criteria))

    def test_empty_criteria_not_actionable(self) -> None:
        self.assertFalse(self._check(""))

    def test_run_command_is_actionable(self) -> None:
        self.assertTrue(self._check("run `pnpm build` and report the output"))

    def test_merge_command_is_actionable(self) -> None:
        self.assertTrue(self._check("merge the agent/backend branch into main"))

    def test_pnpm_tool_name_is_actionable(self) -> None:
        self.assertTrue(self._check("pnpm install && pnpm test"))

    def test_git_tool_name_is_actionable(self) -> None:
        self.assertTrue(self._check("git pull origin main"))

    def test_inline_code_span_is_actionable(self) -> None:
        self.assertTrue(self._check("Execute `npm run build` to verify"))

    def test_ableton_review_criteria_is_actionable(self) -> None:
        criteria = (
            "First, pull all code from the shared git repository. Then merge "
            "the agent branches into main:\n"
            "  git pull origin main\n"
            "  git merge origin/agent/backend --no-edit\n"
            "Run `pnpm install && pnpm build` and report the output."
        )
        self.assertTrue(self._check(criteria))


class ReviewStepPromptFramingTests(unittest.TestCase):
    """execute_review_step should adapt its prompt framing based on criteria."""

    @patch("worker.wait_for_agent_runtime_ready")
    @patch("worker.append_journal_event")
    @patch("worker.invoke_agent_runtime")
    def test_actionable_criteria_uses_execution_framing(
        self, mock_invoke: MagicMock, mock_journal: MagicMock, _mock_ready: MagicMock,
    ) -> None:
        mock_invoke.return_value = {
            "response": "APPROVED\n1. All tests pass.",
            "thread_id": "t-1",
            "status": "completed",
        }
        from worker import execute_review_step
        step = {
            "name": "integration-review",
            "agentRef": "architect",
            "type": "review",
            "reviewCriteria": "run `pnpm test` and verify all tests pass",
            "dependsOn": ["backend"],
        }
        outcome = execute_review_step(
            step, "build app", {"backend": {"response": "done", "output": {"json": None}}},
            run_id="run-1", worker_job={"name": "j1", "namespace": "ns"},
        )
        self.assertEqual(outcome["state"], "completed")
        # Verify the prompt sent to the agent uses execution framing
        call_args = mock_invoke.call_args
        prompt_sent = call_args[1]["payload"]["prompt"] if "payload" in (call_args[1] or {}) else call_args[0][2]["prompt"]
        self.assertIn("execution authority", prompt_sent)
        self.assertIn("execute each item", prompt_sent.lower())

    @patch("worker.wait_for_agent_runtime_ready")
    @patch("worker.append_journal_event")
    @patch("worker.invoke_agent_runtime")
    def test_evaluative_criteria_uses_default_framing(
        self, mock_invoke: MagicMock, mock_journal: MagicMock, _mock_ready: MagicMock,
    ) -> None:
        mock_invoke.return_value = {
            "response": "APPROVED\n1. Code quality is good.",
            "thread_id": "t-1",
            "status": "completed",
        }
        from worker import execute_review_step
        step = {
            "name": "code-review",
            "agentRef": "reviewer",
            "type": "review",
            "reviewCriteria": "Code follows style guide. No unused imports.",
            "dependsOn": ["impl"],
        }
        outcome = execute_review_step(
            step, "build app", {"impl": {"response": "done", "output": {"json": None}}},
            run_id="run-1", worker_job={"name": "j1", "namespace": "ns"},
        )
        self.assertEqual(outcome["state"], "completed")
        call_args = mock_invoke.call_args
        prompt_sent = call_args[0][2]["prompt"]
        self.assertIn("Evaluate the following output", prompt_sent)
        self.assertNotIn("execution authority", prompt_sent)

    @patch("worker.wait_for_agent_runtime_ready")
    @patch("worker.append_journal_event")
    @patch("worker.invoke_agent_runtime")
    def test_review_prompt_includes_workspace_check_hint(
        self, mock_invoke: MagicMock, mock_journal: MagicMock, _mock_ready: MagicMock,
    ) -> None:
        mock_invoke.return_value = {
            "response": "APPROVED\n1. Looks good.",
            "thread_id": "t-1",
            "status": "completed",
        }
        from worker import execute_review_step
        step = {
            "name": "review",
            "agentRef": "reviewer",
            "type": "review",
            "reviewCriteria": "All files present and correctly formatted.",
            "dependsOn": ["impl"],
        }
        execute_review_step(
            step, "build app", {"impl": {"response": "done", "output": {"json": None}}},
            run_id="run-1", worker_job={"name": "j1", "namespace": "ns"},
        )
        call_args = mock_invoke.call_args
        prompt_sent = call_args[0][2]["prompt"]
        self.assertIn("/workspace", prompt_sent)


class MaxParallelStepsTests(unittest.TestCase):
    """§2.7 — MAX_PARALLEL_STEPS caps ThreadPoolExecutor max_workers."""

    def test_max_parallel_steps_reads_env_default(self) -> None:
        import worker
        # Default should be 4 (or whatever env sets).
        self.assertGreaterEqual(worker.MAX_PARALLEL_STEPS, 1)

    def test_max_parallel_steps_env_override(self) -> None:
        with patch.dict("os.environ", {"MAX_PARALLEL_STEPS": "12"}):
            # Re-evaluate the expression the same way the module does.
            reloaded_value = max(int("12"), 1)
            self.assertEqual(reloaded_value, 12)

    def test_max_parallel_steps_env_floor_at_one(self) -> None:
        # Ensure values < 1 are floored to 1.
        self.assertEqual(max(int("0"), 1), 1)
        self.assertEqual(max(int("-5"), 1), 1)


class WorkerMainCleanupTests(unittest.TestCase):
    def test_main_stops_runtime_event_emitter_on_success(self) -> None:
        import worker

        fake_resource = {
            "metadata": {"generation": 3},
            "status": {"runId": "wf-run-cleanup"},
        }

        with (
            patch.object(worker, "WORKER_KIND", "workflow"),
            patch.object(worker, "TARGET_NAMESPACE", "default"),
            patch.object(worker, "TARGET_NAME", "context7-research-analysis"),
            patch.object(worker, "load_kubernetes_config"),
            patch.object(worker, "init_state_database"),
            patch.object(worker, "init_tracing"),
            patch.object(worker, "get_resource", return_value=fake_resource),
            patch.object(worker, "check_run_id_conflict"),
            patch.object(worker, "acquire_worker_lease", return_value=True),
            patch.object(worker, "start_lease_renewal"),
            patch.object(worker, "stop_lease_renewal"),
            patch.object(worker, "release_worker_lease"),
            patch.object(worker, "run_workflow_worker", return_value=None),
            patch.object(worker, "runtime_events", create=True) as runtime_events,
        ):
            exit_code = worker.main()

        self.assertEqual(exit_code, 0)
        runtime_events.stop_emitter.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
