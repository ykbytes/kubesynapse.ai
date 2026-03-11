import asyncio
import importlib.util
import json
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
from fastapi import HTTPException


try:
    import jose  # noqa: F401
except ModuleNotFoundError:
    jose_module = types.ModuleType("jose")
    jose_module.jwk = types.SimpleNamespace(construct=lambda *_args, **_kwargs: None)
    jose_module.jwt = types.SimpleNamespace(
        get_unverified_header=lambda _token: {},
        get_unverified_claims=lambda _token: {},
    )
    jose_utils_module = types.ModuleType("jose.utils")
    jose_utils_module.base64url_decode = lambda value: value
    sys.modules["jose"] = jose_module
    sys.modules["jose.utils"] = jose_utils_module


MODULE_PATH = Path(__file__).resolve().parents[1] / "main.py"
SPEC = importlib.util.spec_from_file_location("api_gateway_main", MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("Failed to load api-gateway main module for tests")
api_gateway_main = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = api_gateway_main
SPEC.loader.exec_module(api_gateway_main)


class GatewayRuntimeValidationTests(unittest.TestCase):
    def test_goose_agent_rejects_mcp_servers(self) -> None:
        with self.assertRaises(HTTPException) as context:
            api_gateway_main.validate_agent_runtime_compatibility(
                {
                    "runtime": {"kind": "goose"},
                    "mcpServers": ["github"],
                    "mcpSidecars": [],
                }
            )

        self.assertEqual(context.exception.status_code, 400)
        self.assertIn("mcp_servers", str(context.exception.detail))

    def test_goose_agent_rejects_mcp_sidecars(self) -> None:
        with self.assertRaises(HTTPException) as context:
            api_gateway_main.validate_agent_runtime_compatibility(
                {
                    "runtime": {"kind": "goose"},
                    "mcpServers": [],
                    "mcpSidecars": [{"name": "tool-bridge", "port": 8081}],
                }
            )

        self.assertEqual(context.exception.status_code, 400)
        self.assertIn("mcp_sidecars", str(context.exception.detail))

    def test_goose_invoke_rejects_unsupported_fields(self) -> None:
        request = api_gateway_main.InvokeRequest(
            prompt="hello",
            require_approval=True,
            tool_name="tool.run",
            mcp_server="github",
            sandbox_session={"id": "session-1"},
        )

        with self.assertRaises(HTTPException) as context:
            api_gateway_main.validate_invoke_runtime_compatibility("goose", request)

        self.assertEqual(context.exception.status_code, 400)
        self.assertIn("require_approval", str(context.exception.detail))
        self.assertIn("tool_name", str(context.exception.detail))
        self.assertIn("mcp_server", str(context.exception.detail))
        self.assertIn("sandbox_session", str(context.exception.detail))

    def test_langgraph_invoke_keeps_extended_fields(self) -> None:
        request = api_gateway_main.InvokeRequest(
            prompt="hello",
            require_approval=True,
            tool_name="tool.run",
            mcp_server="github",
            sandbox_session={"id": "session-1"},
        )

        api_gateway_main.validate_invoke_runtime_compatibility("langgraph", request)

    def test_goose_invoke_allows_goose_run_controls(self) -> None:
        request = api_gateway_main.InvokeRequest(
            prompt="hello",
            system="stay read-only",
            no_session=True,
            max_turns=12,
            debug=True,
            working_directory="nested/project",
            builtin_extensions=["developer"],
            stdio_extensions=["echo custom-tool"],
            streamable_http_extensions=["https://example.com/mcp"],
        )

        api_gateway_main.validate_invoke_runtime_compatibility("goose", request)

    def test_delete_is_allowed_for_cors(self) -> None:
        cors_middleware = next(
            middleware
            for middleware in api_gateway_main.app.user_middleware
            if middleware.cls.__name__ == "CORSMiddleware"
        )

        self.assertIn("DELETE", cors_middleware.kwargs["allow_methods"])

    def test_invoke_request_normalizes_whitespace(self) -> None:
        request = api_gateway_main.InvokeRequest(
            prompt="  hello  ",
            thread_id="   ",
            model="  ",
            system="   ",
            approval_action="   ",
            tool_name="  ",
            mcp_server="   ",
            working_directory="  nested/project  ",
            builtin_extensions=[" developer ", "   "],
            stdio_extensions=[" echo tool ", "   "],
            streamable_http_extensions=[" https://example.com/mcp ", "   "],
        )

        self.assertEqual(request.prompt, "hello")
        self.assertIsNone(request.thread_id)
        self.assertIsNone(request.model)
        self.assertIsNone(request.system)
        self.assertIsNone(request.approval_action)
        self.assertEqual(request.tool_name, "")
        self.assertIsNone(request.mcp_server)
        self.assertEqual(request.working_directory, "nested/project")
        self.assertEqual(request.builtin_extensions, ["developer"])
        self.assertEqual(request.stdio_extensions, ["echo tool"])
        self.assertEqual(request.streamable_http_extensions, ["https://example.com/mcp"])

    def test_parse_json_object_response_rejects_invalid_json(self) -> None:
        response = httpx.Response(200, text="not-json")

        with self.assertRaises(HTTPException) as context:
            api_gateway_main.parse_json_object_response(response, context="Agent runtime /invoke")

        self.assertEqual(context.exception.status_code, 502)
        self.assertIn("invalid JSON", str(context.exception.detail))

    def test_parse_json_object_response_rejects_non_object_payload(self) -> None:
        response = httpx.Response(200, json=["not", "an", "object"])

        with self.assertRaises(HTTPException) as context:
            api_gateway_main.parse_json_object_response(response, context="Agent runtime /invoke")

        self.assertEqual(context.exception.status_code, 502)
        self.assertIn("non-object", str(context.exception.detail))

    def test_error_payload_from_body_prefers_detail_field(self) -> None:
        payload = api_gateway_main.error_payload_from_body(
            json.dumps({"detail": "runtime cold start"}).encode("utf-8"),
            "fallback",
        )

        self.assertEqual(payload, {"error": "runtime cold start"})

    def test_parse_goose_config_files_normalizes_relative_paths(self) -> None:
        parsed = api_gateway_main.parse_goose_config_files(
            {
                " config.yaml ": {"GOOSE_MODE": "smart_approve"},
                "prompts\\review.md": "Review conservatively.",
            },
            source="goose_config_files",
        )

        self.assertEqual(
            parsed,
            {
                "config.yaml": {"GOOSE_MODE": "smart_approve"},
                "prompts/review.md": "Review conservatively.",
            },
        )

    def test_parse_goose_config_files_rejects_runtime_managed_paths(self) -> None:
        with self.assertRaises(HTTPException) as context:
            api_gateway_main.parse_goose_config_files(
                {"permissions/tool_permissions.json": {}},
                source="goose_config_files",
            )

        self.assertEqual(context.exception.status_code, 400)
        self.assertIn("permissions", str(context.exception.detail))

    def test_build_agent_spec_includes_goose_config_files(self) -> None:
        request = api_gateway_main.CreateAgentRequest(
            name="goose-agent",
            model="gpt-4",
            runtime_kind="goose",
            goose_config_files={"config.yaml": {"GOOSE_MODE": "smart_approve"}},
        )

        spec = api_gateway_main.build_agent_spec(request)

        self.assertEqual(spec["runtime"]["kind"], "goose")
        self.assertEqual(
            spec["runtime"]["goose"]["configFiles"],
            {"config.yaml": {"GOOSE_MODE": "smart_approve"}},
        )

    def test_build_agent_spec_preserves_existing_goose_config_files_on_update(self) -> None:
        request = api_gateway_main.UpdateAgentRequest(model="gpt-4")

        spec = api_gateway_main.build_agent_spec(
            request,
            existing_spec={
                "model": "gpt-4",
                "runtime": {
                    "kind": "goose",
                    "goose": {"configFiles": {"config.yaml": {"GOOSE_MODE": "smart_approve"}}},
                },
            },
        )

        self.assertEqual(spec["runtime"]["kind"], "goose")
        self.assertEqual(
            spec["runtime"]["goose"]["configFiles"],
            {"config.yaml": {"GOOSE_MODE": "smart_approve"}},
        )

    def test_build_agent_spec_rejects_goose_config_files_for_langgraph(self) -> None:
        request = api_gateway_main.CreateAgentRequest(
            name="langgraph-agent",
            model="gpt-4",
            runtime_kind="langgraph",
            goose_config_files={"config.yaml": {"GOOSE_MODE": "smart_approve"}},
        )

        with self.assertRaises(HTTPException) as context:
            api_gateway_main.build_agent_spec(request)

        self.assertEqual(context.exception.status_code, 400)
        self.assertIn("runtime_kind", str(context.exception.detail))

    def test_agent_detail_from_resource_exposes_goose_config_files(self) -> None:
        detail = api_gateway_main.agent_detail_from_resource(
            {
                "metadata": {
                    "name": "goose-agent",
                    "namespace": "default",
                    "creationTimestamp": "2026-03-11T00:00:00Z",
                },
                "spec": {
                    "model": "gpt-4",
                    "systemPrompt": "stay read-only",
                    "runtime": {
                        "kind": "goose",
                        "goose": {"configFiles": {"config.yaml": {"GOOSE_MODE": "smart_approve"}}},
                    },
                },
            }
        )

        self.assertEqual(detail.goose_config_files, {"config.yaml": {"GOOSE_MODE": "smart_approve"}})


class GatewayInvokeProxyTests(unittest.IsolatedAsyncioTestCase):
    async def test_invoke_agent_rejects_invalid_runtime_json(self) -> None:
        request = api_gateway_main.InvokeRequest(prompt="hello")
        raw_request = types.SimpleNamespace(headers={})
        response = httpx.Response(200, text="not-json")

        class FakeAsyncClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def post(self, *args, **kwargs):
                return response

        with patch.object(api_gateway_main.asyncio, "to_thread", return_value={"spec": {"model": "gpt-4"}}), patch.object(
            api_gateway_main.httpx,
            "AsyncClient",
            return_value=FakeAsyncClient(),
        ):
            with self.assertRaises(HTTPException) as context:
                await api_gateway_main.invoke_agent("demo", request, raw_request, "default", user={})

        self.assertEqual(context.exception.status_code, 502)
        self.assertIn("invalid JSON", str(context.exception.detail))

    async def test_invoke_agent_stream_emits_response_error_event_for_upstream_failure(self) -> None:
        request = api_gateway_main.InvokeRequest(prompt="hello")
        raw_request = types.SimpleNamespace(headers={})
        error_response = httpx.Response(503, text=json.dumps({"detail": "runtime cold start"}))

        class FakeStreamContext:
            async def __aenter__(self):
                return error_response

            async def __aexit__(self, exc_type, exc, tb):
                return False

        class FakeAsyncClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            def stream(self, *args, **kwargs):
                return FakeStreamContext()

        with patch.object(api_gateway_main.asyncio, "to_thread", return_value={"spec": {"model": "gpt-4"}}), patch.object(
            api_gateway_main.httpx,
            "AsyncClient",
            return_value=FakeAsyncClient(),
        ):
            response = await api_gateway_main.invoke_agent_stream("demo", request, raw_request, "default", user={})
            chunks: list[str] = []
            async for chunk in response.body_iterator:
                chunks.append(chunk)

        payload = "".join(chunks)
        self.assertIn("event: response.error", payload)
        self.assertIn("runtime cold start", payload)

    async def test_invoke_agent_stream_emits_keepalive_for_idle_upstream(self) -> None:
        request = api_gateway_main.InvokeRequest(prompt="hello")
        raw_request = types.SimpleNamespace(headers={})

        class FakeStreamResponse:
            status_code = 200

            async def aread(self) -> bytes:
                return b""

            async def aiter_text(self):
                await asyncio.sleep(0.02)
                yield "event: response.completed\ndata: {\"thread_id\": \"t-1\", \"status\": \"completed\"}\n\n"

        class FakeStreamContext:
            async def __aenter__(self):
                return FakeStreamResponse()

            async def __aexit__(self, exc_type, exc, tb):
                return False

        class FakeAsyncClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            def stream(self, *args, **kwargs):
                return FakeStreamContext()

        with patch.object(api_gateway_main.asyncio, "to_thread", return_value={"spec": {"model": "gpt-4"}}), patch.object(
            api_gateway_main.httpx,
            "AsyncClient",
            return_value=FakeAsyncClient(),
        ), patch.object(api_gateway_main, "STREAM_KEEPALIVE_SECONDS", 0.01):
            response = await api_gateway_main.invoke_agent_stream("demo", request, raw_request, "default", user={})
            chunks: list[str] = []
            async for chunk in response.body_iterator:
                chunks.append(chunk)

        payload = "".join(chunks)
        self.assertIn(": keepalive", payload)
        self.assertIn("event: response.completed", payload)


if __name__ == "__main__":
    unittest.main()