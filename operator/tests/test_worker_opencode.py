"""Tests for OpenCode workflow integration fixes in worker.py."""

import sys
import types
import unittest
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
_k8s_client.rest = _k8s_rest
for _name, _mod in [
    ("kubernetes", _k8s),
    ("kubernetes.client", _k8s_client),
    ("kubernetes.config", _k8s_config),
    ("kubernetes.client.rest", _k8s_rest),
]:
    sys.modules.setdefault(_name, _mod)


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


class ExecuteWorkflowStepOpenCodeTests(unittest.TestCase):
    """Bugs 1-3, 6: execute_workflow_step handles OpenCode fields."""

    def _patch_env_and_import(self):
        """Set required env vars and import execute_workflow_step."""
        import worker

        return worker.execute_workflow_step

    @patch("worker.append_journal_event")
    @patch("worker.invoke_agent_runtime")
    def test_captures_opencode_fields(
        self, mock_invoke: MagicMock, mock_journal: MagicMock
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

    @patch("worker.append_journal_event")
    @patch("worker.invoke_agent_runtime")
    def test_incomplete_status_accepted_with_warning(
        self, mock_invoke: MagicMock, mock_journal: MagicMock
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

    @patch("worker.append_journal_event")
    @patch("worker.invoke_agent_runtime")
    def test_error_status_still_fails(
        self, mock_invoke: MagicMock, mock_journal: MagicMock
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

    @patch("worker.append_journal_event")
    @patch("worker.invoke_agent_runtime")
    def test_structured_output_from_metadata(
        self, mock_invoke: MagicMock, mock_journal: MagicMock
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

    @patch("worker.append_journal_event")
    @patch("worker.invoke_agent_runtime")
    def test_warnings_in_journal_event(
        self, mock_invoke: MagicMock, mock_journal: MagicMock
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


class LoopStepThreadIdTests(unittest.TestCase):
    """Bug 5: loop steps use a single thread_id across iterations."""

    @patch("worker.append_journal_event")
    @patch("worker.invoke_agent_runtime")
    def test_loop_uses_consistent_thread_id(
        self, mock_invoke: MagicMock, mock_journal: MagicMock
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

    @patch("worker.append_journal_event")
    @patch("worker.invoke_agent_runtime")
    def test_loop_collects_artifacts_and_warnings(
        self, mock_invoke: MagicMock, mock_journal: MagicMock
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

    @patch("utils.httpx.Client")
    def test_creates_new_client_per_attempt(
        self, mock_client_cls: MagicMock
    ) -> None:
        from utils import invoke_agent_runtime

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"response": "ok"}
        mock_response.raise_for_status = MagicMock()
        mock_client = MagicMock()
        mock_client.post.return_value = mock_response
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client_cls.return_value = mock_client

        invoke_agent_runtime("agent-1", "ns", {"prompt": "hi"}, timeout_seconds=120.0)

        # Client should be constructed with the full timeout per request
        mock_client_cls.assert_called_once_with(timeout=120.0)

    @patch("utils.httpx.Client")
    def test_retries_on_500_with_fresh_client(
        self, mock_client_cls: MagicMock
    ) -> None:
        from utils import invoke_agent_runtime

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
        result = invoke_agent_runtime("a", "ns", {"prompt": "x"}, timeout_seconds=60.0)
        self.assertEqual(result, {"response": "ok"})
        # Should have created a new client for each of the 3 attempts
        self.assertEqual(mock_client_cls.call_count, 3)


class ConsecutiveCompletionSignalsResetTests(unittest.TestCase):
    """Bug: consecutive_completion_signals must reset on non-plan_complete signals."""

    @patch("worker.append_journal_event")
    @patch("worker.invoke_agent_runtime")
    def test_no_progress_resets_counter(
        self, mock_invoke: MagicMock, mock_journal: MagicMock
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

    @patch("worker.append_journal_event")
    @patch("worker.invoke_agent_runtime")
    def test_ambiguous_signal_resets_counter(
        self, mock_invoke: MagicMock, mock_journal: MagicMock
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


if __name__ == "__main__":
    unittest.main()
