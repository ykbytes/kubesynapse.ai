from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
import sysconfig
import unittest
from pathlib import Path
from unittest.mock import patch

import importlib_metadata
from fastapi.exceptions import RequestValidationError
from importlib_metadata.compat import py39 as importlib_metadata_py39

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.modules.pop("runtime_events", None)

_stdlib_operator_path = Path(sysconfig.get_paths()["stdlib"]) / "operator.py"
_operator_spec = importlib.util.spec_from_file_location("python_stdlib_operator", _stdlib_operator_path)
if _operator_spec is None or _operator_spec.loader is None:
    raise RuntimeError("Failed to load stdlib operator module for runtime tests")
_stdlib_operator = importlib.util.module_from_spec(_operator_spec)
_operator_spec.loader.exec_module(_stdlib_operator)
sys.modules["operator"] = _stdlib_operator
importlib_metadata.operator = _stdlib_operator
importlib_metadata_py39.operator = _stdlib_operator

MODULE_PATH = Path(__file__).resolve().parents[1] / "main.py"
SPEC = importlib.util.spec_from_file_location("opencode_runtime_main_contract", MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("Failed to load opencode-runtime main module for contract tests")
opencode_runtime_main = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = opencode_runtime_main
SPEC.loader.exec_module(opencode_runtime_main)


class OpenCodeRuntimeContractTests(unittest.TestCase):
    def _request_with_trace_id(self, trace_id: str):
        request = opencode_runtime_main.Request(
            {
                "type": "http",
                "method": "GET",
                "path": "/todo",
                "query_string": b"",
                "headers": [(b"x-request-id", trace_id.encode("utf-8"))],
                "client": ("testclient", 50000),
                "server": ("testserver", 80),
                "scheme": "http",
            }
        )
        request.state.request_id = trace_id
        return request

    def test_openapi_uses_published_runtime_contract(self) -> None:
        schema = opencode_runtime_main.app.openapi()

        self.assertEqual(schema["info"]["title"], "KubeSynapse Runtime API")
        self.assertIn("/abort", schema["paths"])
        self.assertIn("/invoke", schema["paths"])

    def test_info_reports_v1_contract(self) -> None:
        payload = opencode_runtime_main.info()

        self.assertEqual(payload["runtime"], "opencode")
        self.assertEqual(payload["contract_version"], "v1")
        self.assertEqual(payload["version"], opencode_runtime_main.app.version)

    def test_capabilities_advertise_supported_tiers(self) -> None:
        payload = opencode_runtime_main.capabilities()

        self.assertEqual(payload["capabilities"]["tiers"], ["core", "session", "artifacts"])

    def test_health_uses_runtime_api_statuses(self) -> None:
        with (
            patch.object(opencode_runtime_main._supervisor_mod, "_runtime_ready", False),
            patch.object(opencode_runtime_main, "is_shutting_down", return_value=False),
        ):
            payload = opencode_runtime_main.health()

        self.assertEqual(payload["status"], "unhealthy")
        self.assertEqual(payload["lifecycle_status"], "starting")
        self.assertIn("uptime_seconds", payload)
        self.assertIn("timestamp", payload)

    def test_ready_returns_not_ready_payload_when_binary_missing(self) -> None:
        with (
            patch.object(opencode_runtime_main, "ensure_runtime_directories", return_value=None),
            patch.object(opencode_runtime_main, "OPENCODE_BIN", "missing-opencode"),
            patch.object(opencode_runtime_main.shutil, "which", return_value=None),
        ):
            response = opencode_runtime_main.ready()

        self.assertEqual(response.status_code, 503)
        data = json.loads(response.body)
        self.assertEqual(data["status"], "not_ready")
        self.assertFalse(data["checks"]["binary_available"])

    def test_abort_alias_delegates_to_cancel(self) -> None:
        with patch.object(
            opencode_runtime_main,
            "cancel_session",
            return_value={"status": "cancelled", "session_id": "session-1", "thread_id": "thread-1"},
        ) as mock_cancel:
            payload = opencode_runtime_main.abort_session_alias(thread_id="thread-1")

        mock_cancel.assert_called_once_with(thread_id="thread-1")
        self.assertEqual(payload["status"], "cancelled")

    def test_http_exception_handler_returns_canonical_error_envelope(self) -> None:
        request = self._request_with_trace_id("trace-opencode-1")

        response = asyncio.run(
            opencode_runtime_main._handle_http_exception(
                request,
                opencode_runtime_main.HTTPException(status_code=400, detail="thread_id query parameter is required"),
            )
        )

        payload = json.loads(response.body)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(payload["error"]["code"], "invalid_request")
        self.assertEqual(payload["error"]["message"], "thread_id query parameter is required")
        self.assertEqual(payload["error"]["trace_id"], "trace-opencode-1")

    def test_validation_exception_handler_returns_canonical_error_envelope(self) -> None:
        request = self._request_with_trace_id("trace-opencode-2")
        validation_error = RequestValidationError(
            [
                {
                    "type": "value_error",
                    "loc": ["body", "prompt"],
                    "msg": "Value error, prompt must not be blank",
                    "input": "",
                }
            ]
        )

        response = asyncio.run(opencode_runtime_main._handle_validation_exception(request, validation_error))

        payload = json.loads(response.body)
        self.assertEqual(response.status_code, 422)
        self.assertEqual(payload["error"]["code"], "invalid_request")
        self.assertEqual(payload["error"]["message"], "prompt must not be blank")
        self.assertEqual(payload["error"]["trace_id"], "trace-opencode-2")