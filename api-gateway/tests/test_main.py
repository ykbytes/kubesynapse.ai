import asyncio
import importlib.util
import json
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

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

    def test_goose_invoke_rejects_a2a_fields(self) -> None:
        request = api_gateway_main.InvokeRequest(
            prompt="hello",
            a2a_target_agent="analysis-agent",
            a2a_target_namespace="team-b",
            a2a_timeout_seconds=15,
        )

        with self.assertRaises(HTTPException) as context:
            api_gateway_main.validate_invoke_runtime_compatibility("goose", request)

        self.assertEqual(context.exception.status_code, 400)
        self.assertIn("a2a_target", str(context.exception.detail))
        self.assertIn("a2a_timeout_seconds", str(context.exception.detail))

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
            a2a_target_agent=" analysis-agent ",
            a2a_target_namespace=" team-b ",
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
        self.assertEqual(request.a2a_target_agent, "analysis-agent")
        self.assertEqual(request.a2a_target_namespace, "team-b")
        self.assertEqual(request.working_directory, "nested/project")
        self.assertEqual(request.builtin_extensions, ["developer"])
        self.assertEqual(request.stdio_extensions, ["echo tool"])
        self.assertEqual(request.streamable_http_extensions, ["https://example.com/mcp"])

    def test_invoke_request_requires_complete_a2a_target(self) -> None:
        with self.assertRaises(ValueError):
            api_gateway_main.InvokeRequest(prompt="hello", a2a_target_agent="analysis-agent")

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

    def test_build_agent_spec_includes_a2a_config(self) -> None:
        request = api_gateway_main.CreateAgentRequest(
            name="langgraph-agent",
            model="gpt-4",
            a2a_config={
                "allowed_callers": [
                    {"name": "research-agent", "namespace": "team-a"},
                ]
            },
        )

        spec = api_gateway_main.build_agent_spec(request)

        self.assertEqual(
            spec["a2a"],
            {"allowedCallers": [{"name": "research-agent", "namespace": "team-a"}]},
        )

    def test_build_agent_spec_preserves_existing_a2a_config_on_update(self) -> None:
        request = api_gateway_main.UpdateAgentRequest(model="gpt-4")

        spec = api_gateway_main.build_agent_spec(
            request,
            existing_spec={
                "model": "gpt-4",
                "a2a": {"allowedCallers": [{"name": "research-agent", "namespace": "team-a"}]},
                "runtime": {"kind": "langgraph"},
            },
        )

        self.assertEqual(
            spec["a2a"],
            {"allowedCallers": [{"name": "research-agent", "namespace": "team-a"}]},
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

    def test_agent_detail_from_resource_exposes_a2a_config(self) -> None:
        detail = api_gateway_main.agent_detail_from_resource(
            {
                "metadata": {
                    "name": "langgraph-agent",
                    "namespace": "default",
                    "creationTimestamp": "2026-03-11T00:00:00Z",
                },
                "spec": {
                    "model": "gpt-4",
                    "a2a": {"allowedCallers": [{"name": "research-agent", "namespace": "team-a"}]},
                    "runtime": {"kind": "langgraph"},
                },
            }
        )

        self.assertEqual(
            detail.a2a_config,
            {"allowedCallers": [{"name": "research-agent", "namespace": "team-a"}]},
        )


class GatewayAgentDiscoveryTests(unittest.TestCase):
    def test_discover_agent_peers_reports_reachable_and_blocked_targets(self) -> None:
        caller_agent = {
            "metadata": {"name": "planner", "namespace": "default"},
            "spec": {
                "model": "gpt-4",
                "policyRef": "planner-policy",
                "runtime": {"kind": "langgraph"},
            },
        }
        policy = {
            "spec": {
                "a2a": {
                    "allowedTargets": [
                        {"name": "researcher", "namespace": "team-b"},
                        {"name": "reviewer", "namespace": "team-b"},
                        {"name": "missing", "namespace": "team-c"},
                    ]
                }
            }
        }
        researcher_agent = {
            "metadata": {"name": "researcher", "namespace": "team-b"},
            "spec": {
                "model": "gpt-4o",
                "runtime": {"kind": "langgraph"},
                "a2a": {"allowedCallers": [{"name": "planner", "namespace": "default"}]},
            },
        }
        reviewer_agent = {
            "metadata": {"name": "reviewer", "namespace": "team-b"},
            "spec": {
                "model": "gpt-4o-mini",
                "runtime": {"kind": "goose"},
                "a2a": {"allowedCallers": [{"name": "someone-else", "namespace": "default"}]},
            },
        }

        def fake_read_agent(name: str, namespace: str) -> dict[str, object]:
            if (namespace, name) == ("default", "planner"):
                return caller_agent
            if (namespace, name) == ("team-b", "researcher"):
                return researcher_agent
            if (namespace, name) == ("team-b", "reviewer"):
                return reviewer_agent
            raise HTTPException(status_code=404, detail=f"Agent '{name}' not found")

        def fake_get_agent_status(name: str, namespace: str) -> str:
            if (namespace, name) == ("team-b", "researcher"):
                return "running"
            if (namespace, name) == ("team-b", "reviewer"):
                return "running"
            return "unknown"

        with patch.object(api_gateway_main, "read_agent", side_effect=fake_read_agent), patch.object(
            api_gateway_main,
            "read_custom_resource",
            return_value=policy,
        ), patch.object(api_gateway_main, "get_agent_status", side_effect=fake_get_agent_status):
            response = api_gateway_main.discover_agent_peers("planner", "default")

        self.assertEqual(response.agent_name, "planner")
        self.assertEqual(response.policy_ref, "planner-policy")
        self.assertEqual(len(response.peers), 3)
        self.assertTrue(response.peers[0].reachable)
        self.assertEqual(response.peers[0].name, "researcher")
        self.assertEqual(response.peers[0].runtime_kind, "langgraph")
        self.assertFalse(response.peers[1].reachable)
        self.assertFalse(response.peers[1].accepts_caller)
        self.assertIn("allowedCallers", response.peers[1].reason or "")
        self.assertFalse(response.peers[2].exists)
        self.assertEqual(response.peers[2].reason, "Target agent does not exist.")

    def test_discover_agent_peers_marks_non_running_target_unreachable(self) -> None:
        caller_agent = {
            "metadata": {"name": "planner", "namespace": "default"},
            "spec": {
                "model": "gpt-4",
                "policyRef": "planner-policy",
                "runtime": {"kind": "langgraph"},
            },
        }
        policy = {
            "spec": {
                "a2a": {
                    "allowedTargets": [
                        {"name": "researcher", "namespace": "team-b"},
                    ]
                }
            }
        }
        researcher_agent = {
            "metadata": {"name": "researcher", "namespace": "team-b"},
            "spec": {
                "model": "gpt-4o",
                "runtime": {"kind": "langgraph"},
                "a2a": {"allowedCallers": [{"name": "planner", "namespace": "default"}]},
            },
        }

        def fake_read_agent(name: str, namespace: str) -> dict[str, object]:
            if (namespace, name) == ("default", "planner"):
                return caller_agent
            if (namespace, name) == ("team-b", "researcher"):
                return researcher_agent
            raise HTTPException(status_code=404, detail=f"Agent '{name}' not found")

        with patch.object(api_gateway_main, "read_agent", side_effect=fake_read_agent), patch.object(
            api_gateway_main,
            "read_custom_resource",
            return_value=policy,
        ), patch.object(api_gateway_main, "get_agent_status", return_value="pending"):
            response = api_gateway_main.discover_agent_peers("planner", "default")

        self.assertFalse(response.peers[0].reachable)
        self.assertEqual(response.peers[0].status, "pending")
        self.assertIn("status is 'pending'", response.peers[0].reason or "")


class GatewayA2AProtocolTests(unittest.TestCase):
    def setUp(self) -> None:
        api_gateway_main.A2A_TASK_STORE.clear()

    def tearDown(self) -> None:
        api_gateway_main.A2A_TASK_STORE.clear()

    def test_build_agent_card_exposes_jsonrpc_interface_and_skills(self) -> None:
        agent = {
            "metadata": {
                "name": "planner",
                "namespace": "default",
                "creationTimestamp": "2026-03-11T00:00:00Z",
                "generation": 7,
            },
            "spec": {
                "model": "gpt-4o",
                "systemPrompt": "Plan research tasks and delegate specialized work when needed.",
                "policyRef": "planner-policy",
                "runtime": {"kind": "langgraph"},
                "mcpServers": ["github"],
            },
        }
        policy = {
            "spec": {
                "a2a": {
                    "allowedTargets": [
                        {"name": "researcher", "namespace": "team-b"},
                    ]
                }
            }
        }

        with patch.object(api_gateway_main, "read_agent", return_value=agent), patch.object(
            api_gateway_main,
            "get_agent_status",
            return_value="running",
        ), patch.object(api_gateway_main, "read_custom_resource", return_value=policy):
            card = api_gateway_main.build_agent_card(
                "planner",
                "default",
                types.SimpleNamespace(base_url="http://gateway.local/"),
            )

        self.assertEqual(card["name"], "planner")
        self.assertEqual(card["url"], "http://gateway.local/a2a/planner?namespace=default")
        self.assertEqual(card["supportedInterfaces"][0]["protocolBinding"], "JSONRPC")
        self.assertEqual(card["supportedInterfaces"][0]["tenant"], "default")
        self.assertTrue(card["capabilities"]["streaming"])
        self.assertFalse(card["capabilities"]["pushNotifications"])
        self.assertEqual(card["version"], "1.0.7")
        self.assertTrue(any(skill["id"] == "peer-delegation" for skill in card["skills"]))
        self.assertTrue(any(skill["id"] == "mcp-github" for skill in card["skills"]))


class GatewayA2AProtocolAsyncTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        api_gateway_main.A2A_TASK_STORE.clear()

    def tearDown(self) -> None:
        api_gateway_main.A2A_TASK_STORE.clear()

    async def test_handle_a2a_send_message_returns_completed_task_and_supports_get(self) -> None:
        invoke_response = api_gateway_main.InvokeResponse(
            agent_name="planner",
            response="Delegated summary",
            thread_id="ctx-123",
            model="gpt-4o",
            status="completed",
        )

        with patch.object(api_gateway_main, "invoke_agent", AsyncMock(return_value=invoke_response)):
            response = await api_gateway_main.handle_a2a_send_message(
                "planner",
                "default",
                {
                    "message": {
                        "messageId": "msg-1",
                        "role": "ROLE_USER",
                        "parts": [{"text": "Summarize the research"}],
                    }
                },
                "req-1",
                "gateway-req-1",
            )

        task = response["result"]["task"]
        self.assertEqual(task["status"]["state"], "TASK_STATE_COMPLETED")
        self.assertEqual(task["artifacts"][0]["parts"][0]["text"], "Delegated summary")
        self.assertEqual(len(task["history"]), 2)

        get_response = api_gateway_main.handle_a2a_get_task(
            "planner",
            "default",
            {"id": task["id"], "historyLength": 1},
            "req-2",
        )

        fetched_task = get_response["result"]["task"]
        self.assertEqual(fetched_task["status"]["state"], "TASK_STATE_COMPLETED")
        self.assertEqual(len(fetched_task["history"]), 1)
        self.assertEqual(fetched_task["artifacts"][0]["parts"][0]["text"], "Delegated summary")

    async def test_handle_a2a_stream_message_translates_runtime_events(self) -> None:
        async def upstream_events():
            yield 'event: response.delta\ndata: {"delta": "Hel"}\n\n'
            yield 'event: response.delta\ndata: {"delta": "lo"}\n\n'
            yield 'event: response.completed\ndata: {"status": "completed", "policy_name": "strict-enterprise-policy"}\n\n'

        async def fake_invoke_agent_stream(*_args, **_kwargs):
            return api_gateway_main.StreamingResponse(upstream_events(), media_type="text/event-stream")

        with patch.object(api_gateway_main, "invoke_agent_stream", side_effect=fake_invoke_agent_stream):
            response = await api_gateway_main.handle_a2a_stream_message(
                "planner",
                "default",
                {
                    "message": {
                        "messageId": "msg-stream-1",
                        "role": "ROLE_USER",
                        "parts": [{"text": "Say hello"}],
                    }
                },
                "req-stream-1",
                "gateway-stream-1",
            )
            chunks: list[str] = []
            async for chunk in response.body_iterator:
                chunks.append(chunk if isinstance(chunk, str) else chunk.decode("utf-8"))

        payload = "".join(chunks)
        self.assertIn('"artifactUpdate"', payload)
        self.assertIn('"statusUpdate"', payload)
        self.assertIn('TASK_STATE_COMPLETED', payload)

        stored_record = next(iter(api_gateway_main.A2A_TASK_STORE.values()))
        task_id = stored_record["task"]["id"]
        get_response = api_gateway_main.handle_a2a_get_task(
            "planner",
            "default",
            {"id": task_id},
            "req-stream-2",
        )
        fetched_task = get_response["result"]["task"]
        self.assertEqual(fetched_task["artifacts"][0]["parts"][0]["text"], "Hello")
        self.assertEqual(fetched_task["metadata"]["policyName"], "strict-enterprise-policy")

    async def test_a2a_jsonrpc_accepts_langsmith_method_names(self) -> None:
        raw_request = types.SimpleNamespace(
            headers={},
            query_params={},
            base_url="http://gateway.local/",
            json=AsyncMock(
                return_value={
                    "jsonrpc": "2.0",
                    "id": "rpc-1",
                    "method": "message/send",
                    "params": {
                        "message": {
                            "messageId": "msg-1",
                            "role": "ROLE_USER",
                            "parts": [{"text": "Hello"}],
                        }
                    },
                }
            ),
        )

        with patch.object(
            api_gateway_main,
            "handle_a2a_send_message",
            AsyncMock(return_value={"jsonrpc": "2.0", "id": "rpc-1", "result": {"task": {"id": "task-1"}}}),
        ):
            response = await api_gateway_main.a2a_jsonrpc("planner", raw_request, namespace="default", user={})

        payload = json.loads(response.body)
        self.assertEqual(payload["id"], "rpc-1")
        self.assertEqual(payload["result"]["task"]["id"], "task-1")


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

    async def test_invoke_agent_returns_a2a_metadata(self) -> None:
        request = api_gateway_main.InvokeRequest(
            prompt="hello",
            a2a_target_agent="analysis-agent",
            a2a_target_namespace="team-b",
        )
        raw_request = types.SimpleNamespace(headers={})
        response = httpx.Response(
            200,
            json={
                "response": "done",
                "thread_id": "caller-thread",
                "model": "gpt-4",
                "status": "completed",
                "a2a": {
                    "targetAgent": "analysis-agent",
                    "targetNamespace": "team-b",
                    "targetThreadId": "callee-thread",
                    "responseStatus": "completed",
                },
            },
        )

        class FakeAsyncClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def post(self, *args, **kwargs):
                return response

        with patch.object(
            api_gateway_main.asyncio,
            "to_thread",
            return_value={"spec": {"model": "gpt-4", "runtime": {"kind": "langgraph"}}},
        ), patch.object(api_gateway_main.httpx, "AsyncClient", return_value=FakeAsyncClient()):
            invoke_response = await api_gateway_main.invoke_agent("demo", request, raw_request, "default", user={})

        self.assertEqual(invoke_response.a2a["targetAgent"], "analysis-agent")
        self.assertEqual(invoke_response.a2a["targetThreadId"], "callee-thread")

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