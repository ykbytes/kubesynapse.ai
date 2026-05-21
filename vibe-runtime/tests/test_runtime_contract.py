from __future__ import annotations

import asyncio
import importlib.util
import json
import subprocess
import sys
import sysconfig
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import importlib_metadata
from importlib_metadata.compat import py39 as importlib_metadata_py39
from fastapi.testclient import TestClient

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
SPEC = importlib.util.spec_from_file_location("vibe_runtime_main_contract", MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("Failed to load vibe-runtime main module for contract tests")
vibe_runtime_main = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = vibe_runtime_main
SPEC.loader.exec_module(vibe_runtime_main)


class VibeRuntimeContractTests(unittest.TestCase):
    def setUp(self) -> None:
        vibe_runtime_main._active_sessions.clear()

    def tearDown(self) -> None:
        vibe_runtime_main._active_sessions.clear()

    def test_openapi_uses_published_runtime_contract(self) -> None:
        schema = vibe_runtime_main.app.openapi()

        self.assertEqual(schema["info"]["title"], "KubeSynapse Runtime API")
        self.assertIn("/abort", schema["paths"])
        self.assertIn("/invoke", schema["paths"])

    def test_info_reports_v1_contract(self) -> None:
        payload = vibe_runtime_main.get_info()

        self.assertEqual(payload["runtime"], "mistral-vibe")
        self.assertEqual(payload["contract_version"], "v1")
        self.assertEqual(payload["version"], vibe_runtime_main.app.version)

    def test_capabilities_advertise_supported_tiers(self) -> None:
        payload = vibe_runtime_main.get_capabilities()

        self.assertEqual(payload["capabilities"]["tiers"], ["core", "session", "artifacts"])

    def test_ready_returns_not_ready_payload_when_checks_fail(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            missing_state = workspace / "missing-state"
            with (
                patch.object(vibe_runtime_main, "VIBE_BIN", str(workspace / "missing-vibe")),
                patch.object(vibe_runtime_main, "WORKSPACE_DIR", workspace),
                patch.object(vibe_runtime_main, "STATE_DIR", missing_state),
                patch.object(vibe_runtime_main.os, "access", return_value=False),
            ):
                response = vibe_runtime_main.ready()

        self.assertEqual(response.status_code, 503)
        data = json.loads(response.body)
        self.assertEqual(data["status"], "not_ready")
        self.assertFalse(data["checks"]["binary_exists"])
        self.assertFalse(data["checks"]["workspace_writable"])
        self.assertFalse(data["checks"]["state_dir_exists"])

    def test_health_reports_runtime_identity(self) -> None:
        payload = vibe_runtime_main.health()

        self.assertEqual(payload["runtime"], "mistral-vibe")
        self.assertEqual(payload["status"], "healthy")
        self.assertIn("timestamp", payload)

    def test_invoke_persists_truthful_session_state(self) -> None:
        response = vibe_runtime_main.InvokeResponse(
            thread_id="thread-1",
            response="Done.",
            model="devstral-small",
            tool_calls=[{"name": "bash", "args": {"command": "pwd"}, "status": "completed"}],
            metadata={
                "tokens": {"total": 192, "input": 80, "output": 112},
                "finish_reason": "stop",
            },
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            with (
                patch.object(vibe_runtime_main, "WORKSPACE_DIR", workspace),
                patch.object(vibe_runtime_main, "_run_vibe", return_value=response),
            ):
                invoke_response = vibe_runtime_main.invoke(
                    vibe_runtime_main.InvokeRequest(prompt="Inspect workspace files", thread_id="thread-1")
                )

                payload = json.loads(invoke_response.body)
                self.assertEqual(payload["thread_id"], "thread-1")
                self.assertTrue(payload["continuity"]["created_new_session"])

                todo_response = vibe_runtime_main.get_todo_state(thread_id="thread-1", request=None)
                todo_data = json.loads(todo_response.body)
                self.assertEqual(todo_data["thread_id"], "thread-1")
                self.assertGreaterEqual(len(todo_data["todos"]), 2)
                self.assertEqual(todo_data["todos"][0]["status"], "completed")
                self.assertIn("Inspect workspace files", todo_data["todos"][0]["content"])
                self.assertEqual(todo_data["todos"][1]["content"], "Run tool bash")

                context_budget = vibe_runtime_main.get_context_budget(thread_id="thread-1")
                self.assertEqual(context_budget["tokens_used"], 192)
                self.assertEqual(context_budget["tokens_remaining"], vibe_runtime_main.DEFAULT_MODEL_CONTEXT_LIMIT - 192)
                self.assertEqual(context_budget["status"], "ok")

                diff_payload = vibe_runtime_main.get_diff(thread_id="thread-1")
                self.assertEqual(diff_payload["thread_id"], "thread-1")
                self.assertIn("session_id", diff_payload)

    def test_reused_thread_preserves_session_id_and_marks_existing_session(self) -> None:
        first_response = vibe_runtime_main.InvokeResponse(
            thread_id="thread-2",
            response="first",
            model="devstral-small",
        )
        second_response = vibe_runtime_main.InvokeResponse(
            thread_id="thread-2",
            response="second",
            model="devstral-small",
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            with (
                patch.object(vibe_runtime_main, "WORKSPACE_DIR", workspace),
                patch.object(vibe_runtime_main, "_run_vibe", side_effect=[first_response, second_response]),
            ):
                first_payload = json.loads(
                    vibe_runtime_main.invoke(
                        vibe_runtime_main.InvokeRequest(prompt="First", thread_id="thread-2")
                    ).body
                )
                first_todo = json.loads(vibe_runtime_main.get_todo_state(thread_id="thread-2", request=None).body)

                second_payload = json.loads(
                    vibe_runtime_main.invoke(
                        vibe_runtime_main.InvokeRequest(prompt="Second", thread_id="thread-2")
                    ).body
                )
                second_todo = json.loads(vibe_runtime_main.get_todo_state(thread_id="thread-2", request=None).body)

        self.assertTrue(first_payload["continuity"]["created_new_session"])
        self.assertFalse(second_payload["continuity"]["created_new_session"])
        self.assertEqual(first_todo["session_id"], second_todo["session_id"])

    def test_invoke_stream_keeps_started_session_id_consistent(self) -> None:
        response = vibe_runtime_main.InvokeResponse(
            thread_id="thread-3",
            response="streamed",
            model="devstral-small",
        )

        async def collect_stream_body() -> str:
            stream_response = await vibe_runtime_main.invoke_stream(
                vibe_runtime_main.InvokeRequest(prompt="Stream hello", thread_id="thread-3")
            )
            parts: list[str] = []
            async for chunk in stream_response.body_iterator:
                parts.append(chunk.decode() if isinstance(chunk, bytes) else chunk)
            return "".join(parts)

        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            with (
                patch.object(vibe_runtime_main, "WORKSPACE_DIR", workspace),
                patch.object(vibe_runtime_main, "_run_vibe", return_value=response),
            ):
                body = asyncio.run(collect_stream_body())

        started_payload = None
        body_lines = body.splitlines()
        for index, line in enumerate(body_lines):
            if line == "event: response.started":
                started_payload = json.loads(body_lines[index + 1].split("data: ", 1)[1])
                break

        self.assertIsNotNone(started_payload)
        self.assertEqual(started_payload["session_id"], vibe_runtime_main._active_sessions["thread-3"]["session_id"])

    def test_unknown_question_reply_returns_404(self) -> None:
        with self.assertRaises(vibe_runtime_main.HTTPException) as context:
            vibe_runtime_main.reply_to_question("missing", {"answer": "yes"})

        self.assertEqual(context.exception.status_code, 404)

    def test_timeout_maps_to_http_408(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            state_dir = workspace / "state"
            state_dir.mkdir()
            with (
                patch.object(vibe_runtime_main, "WORKSPACE_DIR", workspace),
                patch.object(vibe_runtime_main, "STATE_DIR", state_dir),
                patch.object(vibe_runtime_main, "VIBE_BIN", "vibe"),
                patch.object(
                    vibe_runtime_main.subprocess,
                    "run",
                    side_effect=subprocess.TimeoutExpired(cmd=["vibe"], timeout=1),
                ),
            ):
                with self.assertRaises(vibe_runtime_main.HTTPException) as context:
                    vibe_runtime_main._run_vibe(
                        vibe_runtime_main.InvokeRequest(prompt="hello", timeout_seconds=1),
                        thread_id="thread-3",
                    )

        self.assertEqual(context.exception.status_code, 408)

    def test_artifact_roots_outside_workspace_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as workspace_dir, tempfile.TemporaryDirectory() as outside_dir:
            workspace = Path(workspace_dir)
            outside = Path(outside_dir)
            with patch.object(vibe_runtime_main, "WORKSPACE_DIR", workspace):
                vibe_runtime_main._register_session("thread-4", "session-4", "devstral-small", prompt="List files")

                with self.assertRaises(vibe_runtime_main.HTTPException) as list_error:
                    vibe_runtime_main.list_artifacts(thread_id="thread-4", root=str(outside))
                with self.assertRaises(vibe_runtime_main.HTTPException) as zip_error:
                    vibe_runtime_main.download_zip(thread_id="thread-4", root=str(outside))

        self.assertEqual(list_error.exception.status_code, 403)
        self.assertEqual(zip_error.exception.status_code, 403)

    def test_invoke_validation_errors_use_canonical_error_envelope(self) -> None:
        with TestClient(vibe_runtime_main.app, raise_server_exceptions=False) as client:
            response = client.post("/invoke", json={}, headers={"x-request-id": "trace-vibe-1"})

        self.assertEqual(response.status_code, 422)
        payload = response.json()
        self.assertEqual(payload["error"]["code"], "invalid_request")
        self.assertEqual(payload["error"]["message"], "prompt must not be blank")
        self.assertEqual(payload["error"]["trace_id"], "trace-vibe-1")

    def test_http_exceptions_use_canonical_error_envelope(self) -> None:
        with TestClient(vibe_runtime_main.app, raise_server_exceptions=False) as client:
            response = client.get("/todo", headers={"x-request-id": "trace-vibe-2"})

        self.assertEqual(response.status_code, 400)
        payload = response.json()
        self.assertEqual(payload["error"]["code"], "invalid_request")
        self.assertEqual(payload["error"]["message"], "thread_id query parameter is required")
        self.assertEqual(payload["error"]["trace_id"], "trace-vibe-2")