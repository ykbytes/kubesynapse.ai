"""Regression tests for streaming runtime parsing helpers."""

import importlib.util
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
CONFIG_PATH = Path(__file__).resolve().parents[1] / "config.py"
CONFIG_SPEC = importlib.util.spec_from_file_location("operator_config_under_test", CONFIG_PATH)
if CONFIG_SPEC is None or CONFIG_SPEC.loader is None:
    raise RuntimeError("Failed to load operator config module for tests")
operator_config = importlib.util.module_from_spec(CONFIG_SPEC)
previous_config = sys.modules.get("config")
sys.modules[CONFIG_SPEC.name] = operator_config
sys.modules["config"] = operator_config
CONFIG_SPEC.loader.exec_module(operator_config)

MODULE_PATH = Path(__file__).resolve().parents[1] / "utils.py"
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


class InvokeAgentRuntimeStreamTests(unittest.TestCase):
    def test_keepalive_comments_do_not_repeat_prior_event_type(self) -> None:
        stream_response = MagicMock()
        stream_response.status_code = 200
        stream_response.iter_lines.return_value = [
            "event: response.turn_started",
            'data: {"turn": 1, "agent": "build"}',
            "",
            ": keepalive",
            "",
            "event: response.delta",
            'data: {"delta": "hello"}',
            "",
            ": keepalive",
            "",
            "event: response.turn_completed",
            'data: {"status": "completed", "response_length": 5}',
            "",
            "event: response.completed",
            'data: {"response": "hello", "status": "completed"}',
            "",
            "data: [DONE]",
        ]
        stream_response.__enter__ = MagicMock(return_value=stream_response)
        stream_response.__exit__ = MagicMock(return_value=False)

        client = MagicMock()
        client.stream.return_value = stream_response
        client.__enter__ = MagicMock(return_value=client)
        client.__exit__ = MagicMock(return_value=False)

        with (
            patch.object(operator_utils.httpx, "Client", return_value=client) as mock_client_cls,
            patch.object(operator_utils, "invoke_agent_runtime") as mock_invoke,
            self.assertLogs("operator-utils", level="INFO") as logs,
        ):
            result = operator_utils.invoke_agent_runtime_stream(
                "agent-1",
                "default",
                {"prompt": "hello"},
                step_name="draft-blueprint",
                iteration=1,
            )

        self.assertEqual(result["response"], "hello")
        log_output = "\n".join(logs.output)
        self.assertEqual(log_output.count("turn 1 started"), 1)
        self.assertNotIn("turn 2 started", log_output)
        mock_invoke.assert_not_called()


if __name__ == "__main__":
    unittest.main()