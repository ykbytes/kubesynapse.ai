import importlib.util
import json
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch


class _HTTPException(Exception):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


class _FakeFastAPI:
    def __init__(self, *args, **kwargs):
        pass

    def middleware(self, *args, **kwargs):
        def decorator(func):
            return func

        return decorator

    def get(self, *args, **kwargs):
        def decorator(func):
            return func

        return decorator

    def post(self, *args, **kwargs):
        def decorator(func):
            return func

        return decorator


class _FakeStreamingResponse:
    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs


try:
    import fastapi  # noqa: F401
    import fastapi.responses  # noqa: F401
except ModuleNotFoundError:
    fastapi_module = types.ModuleType("fastapi")
    fastapi_module.FastAPI = _FakeFastAPI
    fastapi_module.HTTPException = _HTTPException
    fastapi_module.Request = type("Request", (), {})
    fastapi_module.Depends = lambda *args, **kwargs: None
    fastapi_module.Header = lambda *args, **kwargs: None
    fastapi_responses_module = types.ModuleType("fastapi.responses")
    fastapi_responses_module.StreamingResponse = _FakeStreamingResponse
    sys.modules.setdefault("fastapi", fastapi_module)
    sys.modules.setdefault("fastapi.responses", fastapi_responses_module)

env_utils_module = types.ModuleType("env_utils")
env_utils_module.get_bool_env = lambda _name, default, **_kwargs: default
env_utils_module.get_float_env = lambda _name, default, **_kwargs: default
env_utils_module.get_int_env = lambda _name, default, **_kwargs: default
sys.modules.setdefault("env_utils", env_utils_module)

guardrails_module = types.ModuleType("guardrails")


class _GuardrailsEngine:
    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def validate_input(self, text):
        return True, ""

    def sanitize_output(self, text):
        return text


guardrails_module.GuardrailsEngine = _GuardrailsEngine
sys.modules.setdefault("guardrails", guardrails_module)

hitl_module = types.ModuleType("hitl")
hitl_module.hitl_gate = lambda **_kwargs: {"decision": "approved", "approval_name": "approval-1"}
sys.modules.setdefault("hitl", hitl_module)

opensandbox_tools_module = types.ModuleType("opensandbox_tools")
opensandbox_tools_module.SandboxToolError = type("SandboxToolError", (Exception,), {})
opensandbox_tools_module.execute_sandbox_tool = lambda *_args, **_kwargs: ({}, None)
opensandbox_tools_module.format_tool_payload = lambda payload: str(payload)
opensandbox_tools_module.is_sandbox_tool = lambda _tool_name: False
opensandbox_tools_module.sandbox_runtime_metadata = lambda: {}
sys.modules.setdefault("opensandbox_tools", opensandbox_tools_module)

kubernetes_module = types.ModuleType("kubernetes")
kubernetes_client_module = types.ModuleType("kubernetes.client")
kubernetes_config_module = types.ModuleType("kubernetes.config")
kubernetes_module.client = kubernetes_client_module
kubernetes_module.config = kubernetes_config_module
sys.modules.setdefault("kubernetes", kubernetes_module)
sys.modules.setdefault("kubernetes.client", kubernetes_client_module)
sys.modules.setdefault("kubernetes.config", kubernetes_config_module)

langchain_messages_module = types.ModuleType("langchain_core.messages")


class _Message:
    def __init__(self, content=None, id=None):
        self.content = content
        self.id = id


langchain_messages_module.AIMessage = _Message
langchain_messages_module.HumanMessage = _Message
langchain_messages_module.SystemMessage = _Message
sys.modules.setdefault("langchain_core.messages", langchain_messages_module)

langchain_openai_module = types.ModuleType("langchain_openai")
langchain_openai_module.ChatOpenAI = type("ChatOpenAI", (), {"__init__": lambda self, **kwargs: None})
sys.modules.setdefault("langchain_openai", langchain_openai_module)

langgraph_sqlite_module = types.ModuleType("langgraph.checkpoint.sqlite")
langgraph_sqlite_module.SqliteSaver = type("SqliteSaver", (), {"__init__": lambda self, conn: None, "setup": lambda self: None})
sys.modules.setdefault("langgraph.checkpoint.sqlite", langgraph_sqlite_module)

langgraph_graph_module = types.ModuleType("langgraph.graph")


class _StateGraph:
    def __init__(self, *_args, **_kwargs):
        pass

    def add_node(self, *_args, **_kwargs):
        return None

    def add_edge(self, *_args, **_kwargs):
        return None

    def add_conditional_edges(self, *_args, **_kwargs):
        return None

    def compile(self, **_kwargs):
        return types.SimpleNamespace(invoke=lambda *_args, **_kwargs: {})


langgraph_graph_module.StateGraph = _StateGraph
langgraph_graph_module.START = "START"
langgraph_graph_module.END = "END"
sys.modules.setdefault("langgraph.graph", langgraph_graph_module)

langgraph_message_module = types.ModuleType("langgraph.graph.message")
langgraph_message_module.add_messages = lambda value: value
sys.modules.setdefault("langgraph.graph.message", langgraph_message_module)


class _SpanContext:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def set_attribute(self, *_args, **_kwargs):
        return None


trace_module = types.ModuleType("opentelemetry.trace")
trace_module.set_tracer_provider = lambda *_args, **_kwargs: None
trace_module.get_tracer = lambda *_args, **_kwargs: types.SimpleNamespace(start_as_current_span=lambda *_a, **_k: _SpanContext())
opentelemetry_module = types.ModuleType("opentelemetry")
opentelemetry_module.trace = trace_module
sys.modules.setdefault("opentelemetry", opentelemetry_module)
sys.modules.setdefault("opentelemetry.trace", trace_module)

otlp_exporter_module = types.ModuleType("opentelemetry.exporter.otlp.proto.grpc.trace_exporter")
otlp_exporter_module.OTLPSpanExporter = type("OTLPSpanExporter", (), {"__init__": lambda self, **kwargs: None})
sys.modules.setdefault("opentelemetry.exporter.otlp.proto.grpc.trace_exporter", otlp_exporter_module)

resource_module = types.ModuleType("opentelemetry.sdk.resources")
resource_module.Resource = type("Resource", (), {"__init__": lambda self, attributes=None: None})
sys.modules.setdefault("opentelemetry.sdk.resources", resource_module)

trace_sdk_module = types.ModuleType("opentelemetry.sdk.trace")
trace_sdk_module.TracerProvider = type("TracerProvider", (), {"__init__": lambda self, resource=None: None, "add_span_processor": lambda self, processor: None})
sys.modules.setdefault("opentelemetry.sdk.trace", trace_sdk_module)

trace_export_module = types.ModuleType("opentelemetry.sdk.trace.export")
trace_export_module.BatchSpanProcessor = type("BatchSpanProcessor", (), {"__init__": lambda self, exporter: None})
sys.modules.setdefault("opentelemetry.sdk.trace.export", trace_export_module)

instrumentator_module = types.ModuleType("prometheus_fastapi_instrumentator")
instrumentator_module.Instrumentator = type("Instrumentator", (), {"instrument": lambda self, app: self, "expose": lambda self, app, **kwargs: self})
sys.modules.setdefault("prometheus_fastapi_instrumentator", instrumentator_module)

pythonjsonlogger_module = types.ModuleType("pythonjsonlogger")
pythonjsonlogger_module.jsonlogger = types.SimpleNamespace(JsonFormatter=lambda *_args, **_kwargs: None)
sys.modules.setdefault("pythonjsonlogger", pythonjsonlogger_module)

MODULE_PATH = Path(__file__).resolve().parents[1] / "agent_logic.py"
SPEC = importlib.util.spec_from_file_location("agent_logic_main", MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("Failed to load agent runtime module for tests")
agent_logic_main = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = agent_logic_main
SPEC.loader.exec_module(agent_logic_main)


class AgentRuntimeA2ATests(unittest.TestCase):
    def test_invoke_request_requires_complete_a2a_target(self) -> None:
        with self.assertRaises(ValueError):
            agent_logic_main.InvokeRequest(prompt="hello", a2a_target_agent="analysis-agent")

    def test_invoke_request_rejects_combined_tool_and_a2a(self) -> None:
        with self.assertRaises(ValueError):
            agent_logic_main.InvokeRequest(
                prompt="hello",
                tool_name="sandbox.exec",
                a2a_target_agent="analysis-agent",
                a2a_target_namespace="team-b",
            )

    def test_invoke_request_rejects_combined_tool_and_subagents(self) -> None:
        with self.assertRaises(ValueError):
            agent_logic_main.InvokeRequest(
                prompt="hello",
                tool_name="sandbox.exec",
                subagents=[{"name": "analysis-agent", "namespace": "team-b"}],
            )

    def test_invoke_request_normalizes_subagent_strategy(self) -> None:
        request = agent_logic_main.InvokeRequest(
            prompt="Investigate the regression",
            subagent_strategy=" Parallel ",
            subagents=[
                {
                    "name": "analysis-agent",
                    "namespace": "team-b",
                    "role": " incident analyst ",
                    "task": " inspect the failing workflow ",
                    "result_file_path": " artifacts/analysis.md ",
                }
            ],
        )

        self.assertEqual(request.subagent_strategy, "parallel")
        self.assertEqual(request.subagents[0].role, "incident analyst")
        self.assertEqual(request.subagents[0].task, "inspect the failing workflow")
        self.assertEqual(request.subagents[0].result_file_path, "artifacts/analysis.md")

    def test_invoke_response_allows_non_object_tool_result(self) -> None:
        response = agent_logic_main.InvokeResponse(
            thread_id="thread-1",
            response="done",
            model="gpt-4",
            tool_result=["item-1", "item-2"],
        )

        self.assertEqual(response.tool_result, ["item-1", "item-2"])

    def test_parse_skill_definition_extracts_capabilities(self) -> None:
        definition = agent_logic_main.parse_skill_definition(
            ".github/skills/research/SKILL.md",
            (
                "---\n"
                "name: research\n"
                "description: Gather evidence carefully.\n"
                "allowedSandboxTools:\n"
                "  - sandbox.filesystem.read\n"
                "allowedMcpServers:\n"
                "  - github\n"
                "allowedA2ATargets:\n"
                "  - name: analysis-agent\n"
                "    namespace: team-b\n"
                "allowSubagents: true\n"
                "---\n"
                "Read source material before answering.\n"
            ),
        )

        self.assertEqual(definition["name"], "research")
        self.assertEqual(definition["allowedSandboxTools"], ["sandbox.filesystem.read"])
        self.assertEqual(definition["allowedMcpServers"], ["github"])
        self.assertEqual(definition["allowedA2ATargets"], [{"name": "analysis-agent", "namespace": "team-b"}])
        self.assertTrue(definition["allowSubagents"])
        self.assertIn("Read source material", definition["body"])

    def test_skill_block_reason_rejects_ungranted_capabilities(self) -> None:
        skill_config = {
            "skills": [{"name": "research"}],
            "allowedSandboxToolPatterns": frozenset({"sandbox.filesystem.read"}),
            "allowedMcpServers": frozenset({"github"}),
            "allowedA2ATargets": frozenset({("team-b", "analysis-agent")}),
            "allowSubagents": False,
            "warnings": [],
        }

        with patch.object(agent_logic_main, "SKILL_RUNTIME_CONFIG", skill_config):
            with patch.object(agent_logic_main, "is_sandbox_tool", return_value=True):
                sandbox_reason = agent_logic_main.skill_block_reason(
                    tool_name="sandbox.exec",
                    mcp_server="",
                    a2a_target_agent="",
                    a2a_target_namespace="",
                    subagents=[],
                )
            mcp_reason = agent_logic_main.skill_block_reason(
                tool_name="tool.run",
                mcp_server="prometheus",
                a2a_target_agent="",
                a2a_target_namespace="",
                subagents=[],
            )
            subagent_reason = agent_logic_main.skill_block_reason(
                tool_name="",
                mcp_server="",
                a2a_target_agent="",
                a2a_target_namespace="",
                subagents=[agent_logic_main.SubagentRequest(name="analysis-agent", namespace="team-b")],
            )

        self.assertIn("sandbox.exec", sandbox_reason)
        self.assertIn("prometheus", mcp_reason)
        self.assertIn("Specialist subagent coordination", subagent_reason)

    def test_load_skill_runtime_config_builds_prompt_and_capability_sets(self) -> None:
        with patch.dict(
            agent_logic_main.os.environ,
            {
                agent_logic_main.SKILL_FILES_ENV: json.dumps(
                    {
                        ".github/skills/research/SKILL.md": (
                            "---\n"
                            "name: research\n"
                            "description: Gather evidence carefully.\n"
                            "allowedSandboxTools:\n"
                            "  - sandbox.filesystem.read\n"
                            "allowedMcpServers:\n"
                            "  - github\n"
                            "allowSubagents: true\n"
                            "---\n"
                            "Read source material before answering.\n"
                        )
                    }
                )
            },
            clear=False,
        ):
            config = agent_logic_main.load_skill_runtime_config()

        self.assertEqual(config["skillFiles"], [".github/skills/research/SKILL.md"])
        self.assertEqual(config["allowedSandboxToolPatterns"], frozenset({"sandbox.filesystem.read"}))
        self.assertEqual(config["allowedMcpServers"], frozenset({"github"}))
        self.assertTrue(config["allowSubagents"])
        self.assertIn("research", config["prompt"])

    def test_validate_inbound_a2a_request_rejects_unauthorized_caller(self) -> None:
        request = agent_logic_main.InvokeRequest(
            prompt="hello",
            caller_agent_name="research-agent",
            caller_agent_namespace="team-a",
        )

        with patch.object(agent_logic_main, "A2A_ALLOWED_CALLERS", frozenset()):
            with self.assertRaises(agent_logic_main.HTTPException) as context:
                agent_logic_main.validate_inbound_a2a_request(request)

        self.assertEqual(context.exception.status_code, 403)
        self.assertIn("research-agent", str(context.exception.detail))

    def test_parse_effective_a2a_policy_config_prefers_policy_values(self) -> None:
        with patch.object(
            agent_logic_main,
            "A2A_ALLOWED_TARGETS_SNAPSHOT",
            frozenset({("env-ns", "env-agent")}),
        ), patch.object(agent_logic_main, "A2A_REQUIRE_HITL_DEFAULT", False), patch.object(
            agent_logic_main,
            "A2A_MAX_TIMEOUT_SECONDS",
            60.0,
        ):
            targets, timeout_seconds, require_hitl = agent_logic_main.parse_effective_a2a_policy_config(
                {
                    "a2a": {
                        "allowedTargets": [{"name": "analysis-agent", "namespace": "team-b"}],
                        "maxTimeoutSeconds": 45,
                        "requireHitl": True,
                    }
                }
            )

        self.assertEqual(targets, frozenset({("team-b", "analysis-agent")}))
        self.assertEqual(timeout_seconds, 45.0)
        self.assertTrue(require_hitl)

    def test_invoke_request_rejects_invalid_team_context_shape(self) -> None:
        with self.assertRaises(ValueError):
            agent_logic_main.InvokeRequest(prompt="hello", team_context=["not-an-object"])

    def test_build_inbound_team_context_merges_caller_metadata(self) -> None:
        request = agent_logic_main.InvokeRequest(
            prompt="Summarize the incident timeline",
            caller_agent_name="planner",
            caller_agent_namespace="team-a",
            parent_thread_id="thread-parent",
            caller_request_id="req-123",
            team_context={"objective": "Build a reusable incident summary."},
        )

        team_context = agent_logic_main.build_inbound_team_context(request)

        self.assertEqual(team_context["caller"]["name"], "planner")
        self.assertEqual(team_context["caller"]["namespace"], "team-a")
        self.assertEqual(team_context["caller"]["threadId"], "thread-parent")
        self.assertEqual(team_context["caller"]["requestId"], "req-123")
        self.assertEqual(team_context["objective"], "Build a reusable incident summary.")
        self.assertTrue(team_context["workingAgreement"])

    def test_invoke_a2a_target_uses_gateway_fallback_after_direct_failure(self) -> None:
        calls: list[tuple[str, dict[str, object]]] = []

        class FakeResponse:
            def __init__(self, payload):
                self._payload = payload
                self.status_code = 200

            def raise_for_status(self):
                return None

            def json(self):
                return self._payload

        class FakeClient:
            def __init__(self, *args, **kwargs):
                pass

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def post(self, url, **kwargs):
                calls.append((url, kwargs))
                if len(calls) == 1:
                    raise RuntimeError("network policy blocked direct access")
                return FakeResponse({"response": "done", "status": "completed", "thread_id": "callee-thread"})

        with patch.object(agent_logic_main.httpx, "Client", FakeClient), patch.object(
            agent_logic_main,
            "API_GATEWAY_INTERNAL_URL",
            "http://gateway.local",
        ), patch.object(agent_logic_main, "API_GATEWAY_SHARED_TOKEN", "shared-token"):
            result, transport, fallback_reason = agent_logic_main.invoke_a2a_target_with_fallback(
                "analysis-agent",
                "team-b",
                {"prompt": "Investigate"},
                "req-1",
                15.0,
            )

        self.assertEqual(result["response"], "done")
        self.assertEqual(transport, "gateway")
        self.assertIn("Direct A2A transport failed", fallback_reason)
        self.assertIn("analysis-agent-sandbox.team-b.svc.cluster.local", calls[0][0])
        self.assertEqual(calls[1][0], "http://gateway.local/api/agents/analysis-agent/invoke")
        self.assertEqual(calls[1][1]["params"]["namespace"], "team-b")
        self.assertEqual(calls[1][1]["headers"]["Authorization"], "Bearer shared-token")

    def test_coordinate_specialized_subagents_shares_files_and_writes_artifacts(self) -> None:
        writes: list[dict[str, object]] = []
        captured_payloads: list[dict[str, object]] = []

        async def fake_execute(tool_name, tool_args, current_session, publish_event):
            del publish_event
            if tool_name == "sandbox.filesystem.read":
                return (
                    {"content": "def bug():\n    return 'fixed'\n"},
                    {"sandbox_id": "shared", "expires_at": "2099-01-01T00:00:00+00:00"},
                )
            if tool_name == "sandbox.filesystem.mkdir":
                return (
                    {"createdPaths": tool_args["paths"]},
                    current_session,
                )
            if tool_name == "sandbox.filesystem.write":
                writes.append(dict(tool_args))
                return (
                    {"writtenPaths": [tool_args["path"]]},
                    {"sandbox_id": "shared", "expires_at": "2099-01-02T00:00:00+00:00"},
                )
            raise AssertionError(f"Unexpected sandbox tool: {tool_name}")

        def fake_invoke(target_agent, target_namespace, payload, request_id, timeout_seconds):
            del request_id, timeout_seconds
            captured_payloads.append(payload)
            self.assertEqual(target_agent, "analysis-agent")
            self.assertEqual(target_namespace, "team-b")
            return (
                {
                    "response": "Root cause isolated in src/app.py.",
                    "status": "completed",
                    "thread_id": "callee-thread",
                    "sandbox_session": {"sandbox_id": "shared", "expires_at": "2099-01-03T00:00:00+00:00"},
                },
                "gateway",
                "Direct A2A transport failed: blocked",
            )

        state = {
            "thread_id": "thread-1",
            "request_prompt": "Investigate the failing workflow and capture reusable notes.",
            "policy": {
                "a2a": {
                    "allowedTargets": [{"name": "analysis-agent", "namespace": "team-b"}],
                    "maxTimeoutSeconds": 30,
                }
            },
            "team_context": {"objective": "Investigate the failing workflow."},
            "sandbox_session": {"sandbox_id": "shared", "expires_at": "2099-01-01T00:00:00+00:00"},
            "subagents": [
                {
                    "name": "analysis-agent",
                    "namespace": "team-b",
                    "role": "incident analyst",
                    "task": "Inspect the failing workflow and explain the root cause.",
                    "input_files": [{"path": "src/app.py", "purpose": "main runtime logic", "include_content": True}],
                    "result_file_path": "artifacts/analysis.md",
                    "share_sandbox_session": True,
                }
            ],
            "subagent_strategy": "sequential",
            "warnings": [],
        }

        with patch.object(agent_logic_main, "execute_sandbox_tool", fake_execute), patch.object(
            agent_logic_main,
            "invoke_a2a_target_with_fallback",
            side_effect=fake_invoke,
        ):
            result = agent_logic_main.coordinate_specialized_subagents(
                state,
                synthesizer=lambda _objective, _strategy, _results: "Combined summary",
            )

        self.assertEqual(result["invoke_status"], "completed")
        self.assertEqual(result["messages"][0].content, "Combined summary")
        self.assertEqual(captured_payloads[0]["sandbox_session"]["sandbox_id"], "shared")
        self.assertEqual(captured_payloads[0]["team_context"]["sharedFiles"][0]["path"], "src/app.py")
        self.assertIn("Relevant files from the shared sandbox", captured_payloads[0]["prompt"])
        self.assertEqual(writes[0]["path"], "artifacts/analysis.md")
        self.assertEqual(result["subagent_results"]["results"][0]["resultFilePath"], "artifacts/analysis.md")
        self.assertTrue(
            any("Completed via API gateway fallback" in warning for warning in result["warnings"]),
        )


if __name__ == "__main__":
    unittest.main()