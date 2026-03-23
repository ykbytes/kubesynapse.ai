import asyncio
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
langgraph_sqlite_module.SqliteSaver = type(
    "SqliteSaver", (), {"__init__": lambda self, conn: None, "setup": lambda self: None}
)
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
trace_module.get_tracer = lambda *_args, **_kwargs: types.SimpleNamespace(
    start_as_current_span=lambda *_a, **_k: _SpanContext()
)
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
trace_sdk_module.TracerProvider = type(
    "TracerProvider",
    (),
    {"__init__": lambda self, resource=None: None, "add_span_processor": lambda self, processor: None},
)
sys.modules.setdefault("opentelemetry.sdk.trace", trace_sdk_module)

trace_export_module = types.ModuleType("opentelemetry.sdk.trace.export")
trace_export_module.BatchSpanProcessor = type("BatchSpanProcessor", (), {"__init__": lambda self, exporter: None})
sys.modules.setdefault("opentelemetry.sdk.trace.export", trace_export_module)

instrumentator_module = types.ModuleType("prometheus_fastapi_instrumentator")
instrumentator_module.Instrumentator = type(
    "Instrumentator", (), {"instrument": lambda self, app: self, "expose": lambda self, app, **kwargs: self}
)
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


def _streaming_response_iterator(response):
    iterator = getattr(response, "body_iterator", None)
    if iterator is not None:
        return iterator
    return response.args[0]


def _parse_sse_chunk(chunk):
    text = chunk.decode() if isinstance(chunk, bytes) else str(chunk)
    lines = [line for line in text.strip().splitlines() if line]
    event = next(line.split(": ", 1)[1] for line in lines if line.startswith("event: "))
    data = next(line.split(": ", 1)[1] for line in lines if line.startswith("data: "))
    return event, json.loads(data)


async def _collect_sse_events(response):
    events = []
    async for chunk in _streaming_response_iterator(response):
        events.append(_parse_sse_chunk(chunk))
    return events


class AgentRuntimeA2ATests(unittest.TestCase):
    def test_resolve_requested_model_allows_configured_alias(self) -> None:
        with patch.object(
            agent_logic_main,
            "CONFIGURED_ALLOWED_MODELS",
            frozenset({"gpt-4", "openrouter-gpt-4o-mini"}),
        ):
            selected = agent_logic_main.resolve_requested_model(
                "openrouter-gpt-4o-mini",
                {"allowedModels": ["gpt-4", "openrouter-gpt-4o-mini"]},
            )

        self.assertEqual(selected, "openrouter-gpt-4o-mini")

    def test_resolve_requested_model_rejects_unallowlisted_alias(self) -> None:
        with patch.object(agent_logic_main, "CONFIGURED_ALLOWED_MODELS", frozenset()):
            with self.assertRaises(agent_logic_main.HTTPException) as context:
                agent_logic_main.resolve_requested_model(
                    "openrouter-gpt-4o-mini",
                    {"allowedModels": ["gpt-4"]},
                )

        self.assertEqual(context.exception.status_code, 400)
        self.assertIn("openrouter-gpt-4o-mini", str(context.exception.detail))

    def test_extract_json_object_accepts_fenced_json(self) -> None:
        parsed = agent_logic_main.extract_json_object('```json\n{"action":"respond","response":"done"}\n```')

        self.assertEqual(parsed, {"action": "respond", "response": "done"})

    def test_run_autonomous_session_returns_structured_response(self) -> None:
        execute_calls: list[dict[str, object]] = []
        state = {
            "request_prompt": "Summarize the incident.",
            "messages": [agent_logic_main.HumanMessage(content="Summarize the incident.")],
            "context": "",
            "team_context": None,
            "system_prompt": "",
            "selected_model": "gpt-4",
            "max_steps": 4,
            "step_count": 0,
            "workspace_scanned": True,
        }

        result = agent_logic_main.run_autonomous_session(
            state,
            plan_invoke=lambda _messages: agent_logic_main.AIMessage(
                content='{"action":"respond","response":"Incident summarized."}'
            ),
            execute_action=lambda action, loop_state: execute_calls.append({"action": action, "state": loop_state})
            or {},
        )

        self.assertEqual(result["invoke_status"], "completed")
        self.assertEqual(result["stop_reason"], "response")
        self.assertEqual(result["step_count"], 0)
        self.assertEqual(result["messages"][0].content, "Incident summarized.")
        self.assertEqual(execute_calls, [])

    def test_run_autonomous_session_detects_doom_loop(self) -> None:
        calls: list[dict[str, object]] = []
        state = {
            "request_prompt": "Inspect the workspace.",
            "messages": [agent_logic_main.HumanMessage(content="Inspect the workspace.")],
            "context": "",
            "team_context": None,
            "system_prompt": "",
            "selected_model": "gpt-4",
            "max_steps": 6,
            "step_count": 0,
            "workspace_scanned": True,
        }

        with patch.object(agent_logic_main, "DOOM_LOOP_THRESHOLD", 3):
            result = agent_logic_main.run_autonomous_session(
                state,
                plan_invoke=lambda _messages: agent_logic_main.AIMessage(
                    content='{"action":"sandbox_tool","tool_name":"sandbox.filesystem.read","tool_args":{"path":"src/app.py"}}'
                ),
                execute_action=lambda action, loop_state: calls.append({"action": action, "state": dict(loop_state)})
                or {
                    "messages": [
                        agent_logic_main.AIMessage(
                            content="Sandbox tool sandbox.filesystem.read result:\nfile contents"
                        )
                    ],
                    "invoke_status": "continue",
                },
            )

        self.assertEqual(result["invoke_status"], "blocked")
        self.assertEqual(result["stop_reason"], "doom_loop_detected")
        self.assertEqual(len(calls), 2)
        self.assertIn("repeated action cycle detected", result["messages"][0].content)

    def test_run_autonomous_session_stops_after_step_budget(self) -> None:
        state = {
            "request_prompt": "Inspect the workspace.",
            "messages": [agent_logic_main.HumanMessage(content="Inspect the workspace.")],
            "context": "",
            "team_context": None,
            "system_prompt": "",
            "selected_model": "gpt-4",
            "max_steps": 1,
            "step_count": 0,
            "workspace_scanned": True,
        }

        result = agent_logic_main.run_autonomous_session(
            state,
            plan_invoke=lambda _messages: agent_logic_main.AIMessage(
                content='{"action":"sandbox_tool","tool_name":"sandbox.filesystem.read","tool_args":{"path":"src/app.py"}}'
            ),
            execute_action=lambda _action, _loop_state: {
                "messages": [
                    agent_logic_main.AIMessage(content="Sandbox tool sandbox.filesystem.read result:\nfile contents")
                ],
                "invoke_status": "continue",
            },
        )

        self.assertEqual(result["invoke_status"], "blocked")
        self.assertEqual(result["stop_reason"], "max_steps_exceeded")
        self.assertEqual(result["step_count"], 1)
        self.assertIn("step budget", result["messages"][0].content)

    def test_run_autonomous_session_preserves_accumulated_state_on_response(self) -> None:
        decisions = iter(
            [
                agent_logic_main.AIMessage(
                    content='{"action":"sandbox_tool","tool_name":"sandbox.filesystem.read","tool_args":{"path":"src/app.py"}}'
                ),
                agent_logic_main.AIMessage(content='{"action":"respond","response":"Done after inspecting the file."}'),
            ]
        )
        state = {
            "request_prompt": "Inspect the workspace.",
            "messages": [agent_logic_main.HumanMessage(content="Inspect the workspace.")],
            "context": "",
            "team_context": None,
            "system_prompt": "",
            "selected_model": "gpt-4",
            "max_steps": 3,
            "step_count": 0,
            "workspace_scanned": True,
        }

        result = agent_logic_main.run_autonomous_session(
            state,
            plan_invoke=lambda _messages: next(decisions),
            execute_action=lambda _action, _loop_state: {
                "messages": [
                    agent_logic_main.AIMessage(content="Sandbox tool sandbox.filesystem.read result:\nfile contents")
                ],
                "invoke_status": "continue",
                "sandbox_session": {"sandbox_id": "sbx-123"},
                "warnings": ["filesystem read used cached sandbox"],
            },
        )

        self.assertEqual(result["invoke_status"], "completed")
        self.assertEqual(result["stop_reason"], "response")
        self.assertEqual(result["sandbox_session"], {"sandbox_id": "sbx-123"})
        self.assertEqual(result["warnings"], ["filesystem read used cached sandbox"])
        self.assertEqual(result["step_count"], 1)

    def test_normalize_autonomous_action_result_continues_after_recoverable_block(self) -> None:
        result = agent_logic_main.normalize_autonomous_action_result(
            "Sandbox tool sandbox.filesystem.read",
            {
                "messages": [agent_logic_main.AIMessage(content="AGENT BLOCKED: Sandbox tool failed: file not found")],
                "invoke_status": "blocked",
                "stop_reason": "tool_error",
            },
        )

        self.assertEqual(result["invoke_status"], "continue")
        self.assertEqual(result["stop_reason"], "")
        self.assertIn("returned status 'blocked'", result["messages"][0].content)

    def test_normalize_autonomous_action_result_preserves_approval_pending_stop(self) -> None:
        result = agent_logic_main.normalize_autonomous_action_result(
            "A2A call team-b/analysis-agent",
            {
                "messages": [agent_logic_main.AIMessage(content="AGENT BLOCKED: human approval required")],
                "invoke_status": "approval_pending",
                "approval_name": "approval-123",
                "retry_after_seconds": 30,
            },
        )

        self.assertEqual(result["invoke_status"], "approval_pending")
        self.assertEqual(result["approval_name"], "approval-123")
        self.assertEqual(result["retry_after_seconds"], 30)

    def test_execute_autonomous_action_with_retries_retries_retryable_blocks(self) -> None:
        attempts = {"count": 0}

        def executor() -> dict[str, object]:
            attempts["count"] += 1
            if attempts["count"] == 1:
                return {
                    "messages": [agent_logic_main.AIMessage(content=agent_logic_main.blocked_response("timeout"))],
                    "invoke_status": "blocked",
                    "retryable": True,
                    "error": "timeout",
                    "error_type": "mcp_timeout",
                    "stop_reason": "mcp_timeout",
                }
            return {
                "messages": [agent_logic_main.AIMessage(content="Recovered after retry")],
                "invoke_status": "completed",
            }

        with (
            patch.object(agent_logic_main, "AUTONOMY_ACTION_RETRY_LIMIT", 2),
            patch.object(
                agent_logic_main,
                "AUTONOMY_ACTION_RETRY_BACKOFF_SECONDS",
                0.0,
            ),
        ):
            result = agent_logic_main.execute_autonomous_action_with_retries("MCP tool github/search", executor)

        self.assertEqual(attempts["count"], 2)
        self.assertEqual(result["invoke_status"], "completed")
        self.assertEqual(result["retry_count"], 1)
        self.assertTrue(any("retrying attempt 2 of 3" in warning for warning in result["warnings"]))

    def test_execute_local_runtime_tool_runs_allowlisted_command(self) -> None:
        metadata = {
            "availableCommands": [{"name": "curl", "path": "/usr/bin/curl"}],
            "supportedTools": ["local.command.list", "local.command.run"],
        }

        with (
            patch.object(agent_logic_main, "local_runtime_metadata", return_value=metadata),
            patch.object(
                agent_logic_main,
                "resolve_local_tool_cwd",
                return_value="/app/state",
            ),
            patch.object(
                agent_logic_main.subprocess,
                "run",
                return_value=types.SimpleNamespace(returncode=0, stdout="curl 8.7.1", stderr=""),
            ),
        ):
            result = agent_logic_main.execute_local_runtime_tool(
                "local.command.run",
                {"command": "curl", "args": ["--version"]},
            )

        self.assertEqual(result["invoke_status"], "completed")
        self.assertEqual(result["tool_result"]["command"], "curl")
        self.assertEqual(result["tool_result"]["cwd"], "/app/state")
        self.assertEqual(result["available_local_commands"], metadata["availableCommands"])

    def test_execute_local_runtime_tool_marks_timeout_as_retryable(self) -> None:
        metadata = {
            "availableCommands": [{"name": "curl", "path": "/usr/bin/curl"}],
            "supportedTools": ["local.command.list", "local.command.run"],
        }

        with (
            patch.object(agent_logic_main, "local_runtime_metadata", return_value=metadata),
            patch.object(
                agent_logic_main,
                "resolve_local_tool_cwd",
                return_value="/app/state",
            ),
            patch.object(
                agent_logic_main.subprocess,
                "run",
                side_effect=agent_logic_main.subprocess.TimeoutExpired("curl", timeout=5),
            ),
        ):
            result = agent_logic_main.execute_local_runtime_tool(
                "local.command.run",
                {"command": "curl", "args": ["--version"]},
            )

        self.assertEqual(result["invoke_status"], "blocked")
        self.assertEqual(result["error_type"], "local_tool_timeout")
        self.assertTrue(result["retryable"])

    def test_build_supervisor_messages_includes_local_runtime_and_recent_failures(self) -> None:
        state = {
            "request_prompt": "Diagnose the deployment failure.",
            "messages": [agent_logic_main.HumanMessage(content="Diagnose the deployment failure.")],
            "context": "",
            "team_context": None,
            "step_count": 1,
            "max_steps": 4,
            "system_prompt": "",
            "last_step_error": {"action": "MCP tool github/search", "errorType": "mcp_timeout"},
            "recent_failures": [
                {
                    "action": "MCP tool github/search",
                    "status": "blocked",
                    "errorType": "mcp_timeout",
                    "message": "Timed out",
                    "retryable": True,
                    "retryCount": 1,
                    "stopReason": "mcp_timeout",
                }
            ],
        }

        with (
            patch.object(
                agent_logic_main, "supervisor_visible_sandbox_tools", return_value=["sandbox.filesystem.read"]
            ),
            patch.object(
                agent_logic_main,
                "supervisor_visible_local_runtime",
                return_value={
                    "supportedTools": ["local.command.list", "local.command.run"],
                    "availableCommands": [{"name": "curl", "path": "/usr/bin/curl"}],
                },
            ),
        ):
            messages = agent_logic_main.build_supervisor_messages(state)

        payload = json.loads(messages[-1].content)
        self.assertEqual(payload["capabilities"]["localRuntime"]["availableCommands"][0]["name"], "curl")
        self.assertEqual(payload["recentFailures"][0]["errorType"], "mcp_timeout")
        self.assertEqual(payload["lastStepError"]["action"], "MCP tool github/search")

    def test_invoke_request_requires_complete_a2a_target(self) -> None:
        with self.assertRaises(ValueError):
            agent_logic_main.InvokeRequest(prompt="hello", a2a_target_agent="analysis-agent")

    def test_invoke_request_rejects_runtime_tool_with_mcp_server(self) -> None:
        with self.assertRaises(ValueError):
            agent_logic_main.InvokeRequest(
                prompt="",
                tool_name="local.command.run",
                tool_args={"command": "curl"},
                mcp_server="github",
            )

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

    def test_invoke_graph_returns_model_step_count_and_stop_reason(self) -> None:
        events = []
        captured = {}

        class FakeGraph:
            def invoke(self, initial_state, config):
                captured["initial_state"] = initial_state
                captured["config"] = config
                return {
                    "messages": [agent_logic_main.AIMessage(content="Autonomy finished.")],
                    "invoke_status": "completed",
                    "selected_model": initial_state["selected_model"],
                    "step_count": 2,
                    "stop_reason": "response",
                }

        request = agent_logic_main.InvokeRequest(
            prompt="Summarize the incident.",
            model="openrouter-gpt-4o-mini",
        )

        with (
            patch.object(
                agent_logic_main,
                "load_active_policy",
                return_value=("team-policy", {"allowedModels": ["gpt-4", "openrouter-gpt-4o-mini"]}),
            ),
            patch.object(
                agent_logic_main,
                "local_runtime_metadata",
                return_value={"availableCommands": [{"name": "curl", "path": "/usr/bin/curl"}]},
            ),
            patch.object(agent_logic_main, "get_runtime", return_value={"graph": FakeGraph()}),
        ):
            response = agent_logic_main.invoke_graph(
                request,
                lambda event, payload: events.append((event, payload)),
            )

        self.assertEqual(response.model, "openrouter-gpt-4o-mini")
        self.assertEqual(response.step_count, 2)
        self.assertEqual(response.stop_reason, "response")
        self.assertEqual(captured["initial_state"]["selected_model"], "openrouter-gpt-4o-mini")
        self.assertTrue(captured["initial_state"]["autonomy_enabled"])
        self.assertEqual(
            captured["initial_state"]["available_local_commands"],
            [{"name": "curl", "path": "/usr/bin/curl"}],
        )
        started_event = next(payload for event, payload in events if event == "response.started")
        self.assertEqual(started_event["model"], "openrouter-gpt-4o-mini")

    def test_invoke_stream_completion_event_includes_model_step_count_and_stop_reason(self) -> None:
        def fake_invoke_graph(request, publisher=None):
            del publisher
            return agent_logic_main.InvokeResponse(
                thread_id=request.thread_id or "thread-1",
                response="Autonomy finished.",
                model="openrouter-gpt-4o-mini",
                step_count=2,
                stop_reason="response",
                policy_name="team-policy",
                status="completed",
            )

        request = agent_logic_main.InvokeRequest(
            prompt="Summarize the incident.",
            thread_id="thread-123",
            model="openrouter-gpt-4o-mini",
        )

        with patch.object(agent_logic_main, "invoke_graph", side_effect=fake_invoke_graph):
            stream_response = asyncio.run(agent_logic_main.invoke_stream(request))
            events = asyncio.run(_collect_sse_events(stream_response))

        completed_payload = next(payload for event, payload in events if event == "response.completed")

        self.assertEqual(completed_payload["model"], "openrouter-gpt-4o-mini")
        self.assertEqual(completed_payload["step_count"], 2)
        self.assertEqual(completed_payload["stop_reason"], "response")
        self.assertEqual(
            next(payload for event, payload in events if event == "response.delta")["delta"], "Autonomy finished."
        )

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

    def test_validate_inbound_a2a_request_allows_when_no_caller_allowlist_configured(self) -> None:
        request = agent_logic_main.InvokeRequest(
            prompt="hello",
            caller_agent_name="research-agent",
            caller_agent_namespace="team-a",
        )

        with patch.object(agent_logic_main, "A2A_ALLOWED_CALLERS", frozenset()):
            agent_logic_main.validate_inbound_a2a_request(request)

    def test_validate_inbound_a2a_request_rejects_caller_not_in_allowlist(self) -> None:
        request = agent_logic_main.InvokeRequest(
            prompt="hello",
            caller_agent_name="research-agent",
            caller_agent_namespace="team-a",
        )

        with patch.object(agent_logic_main, "A2A_ALLOWED_CALLERS", frozenset({("team-b", "analysis-agent")})):
            with self.assertRaises(agent_logic_main.HTTPException) as context:
                agent_logic_main.validate_inbound_a2a_request(request)

        self.assertEqual(context.exception.status_code, 403)
        self.assertIn("research-agent", str(context.exception.detail))

    def test_parse_effective_a2a_policy_config_prefers_policy_values(self) -> None:
        with (
            patch.object(
                agent_logic_main,
                "A2A_ALLOWED_TARGETS_SNAPSHOT",
                frozenset({("env-ns", "env-agent")}),
            ),
            patch.object(agent_logic_main, "A2A_REQUIRE_HITL_DEFAULT", False),
            patch.object(
                agent_logic_main,
                "A2A_MAX_TIMEOUT_SECONDS",
                60.0,
            ),
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

        with (
            patch.object(agent_logic_main.httpx, "Client", FakeClient),
            patch.object(
                agent_logic_main,
                "API_GATEWAY_INTERNAL_URL",
                "http://gateway.local",
            ),
            patch.object(agent_logic_main, "API_GATEWAY_SHARED_TOKEN", "shared-token"),
        ):
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

        with (
            patch.object(agent_logic_main, "execute_sandbox_tool", fake_execute),
            patch.object(
                agent_logic_main,
                "invoke_a2a_target_with_fallback",
                side_effect=fake_invoke,
            ),
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

    # ── New action tests ──────────────────────────────────────────────

    def test_normalize_supervisor_action_plan(self) -> None:
        action = agent_logic_main.normalize_supervisor_action(
            {
                "action": "plan",
                "thinking": "I need to plan this",
                "steps": ["Read the file", "Edit the function", "Run tests"],
            }
        )
        self.assertIsNotNone(action)
        self.assertEqual(action["action"], "plan")
        self.assertEqual(len(action["steps"]), 3)
        self.assertEqual(action["thinking"], "I need to plan this")

    def test_normalize_supervisor_action_plan_empty_steps_returns_none(self) -> None:
        action = agent_logic_main.normalize_supervisor_action(
            {
                "action": "plan",
                "steps": [],
            }
        )
        self.assertIsNone(action)

    def test_normalize_supervisor_action_edit_file(self) -> None:
        action = agent_logic_main.normalize_supervisor_action(
            {
                "action": "edit_file",
                "thinking": "Fix the bug",
                "path": "/src/app.py",
                "old_text": "def old():",
                "new_text": "def new():",
            }
        )
        self.assertIsNotNone(action)
        self.assertEqual(action["action"], "edit_file")
        self.assertEqual(action["path"], "/src/app.py")
        self.assertEqual(action["old_text"], "def old():")
        self.assertEqual(action["new_text"], "def new():")

    def test_normalize_supervisor_action_edit_file_missing_path_returns_none(self) -> None:
        action = agent_logic_main.normalize_supervisor_action(
            {
                "action": "edit_file",
                "old_text": "x",
                "new_text": "y",
            }
        )
        self.assertIsNone(action)

    def test_normalize_supervisor_action_batch_read(self) -> None:
        action = agent_logic_main.normalize_supervisor_action(
            {
                "action": "batch_read",
                "thinking": "Need to read multiple files",
                "reads": [
                    {"path": "/src/a.py"},
                    {"path": "/src/b.py", "start_line": 1, "end_line": 50},
                ],
            }
        )
        self.assertIsNotNone(action)
        self.assertEqual(action["action"], "batch_read")
        self.assertEqual(len(action["reads"]), 2)

    def test_normalize_supervisor_action_batch_read_empty_returns_none(self) -> None:
        action = agent_logic_main.normalize_supervisor_action(
            {
                "action": "batch_read",
                "reads": [],
            }
        )
        self.assertIsNone(action)

    def test_describe_autonomous_action_new_types(self) -> None:
        self.assertEqual(
            agent_logic_main.describe_autonomous_action({"action": "edit_file", "path": "/a.py"}),
            "Edit file /a.py",
        )
        self.assertEqual(
            agent_logic_main.describe_autonomous_action({"action": "batch_read", "reads": [{}, {}]}),
            "Batch read 2 files",
        )
        self.assertEqual(
            agent_logic_main.describe_autonomous_action({"action": "plan", "steps": ["a", "b"]}),
            "Plan (2 steps)",
        )

    def test_classify_error_known_categories(self) -> None:
        cat, hint = agent_logic_main.classify_error("FileNotFoundError: No such file or directory")
        self.assertEqual(cat, "file_not_found")
        self.assertIn("ls", hint.lower())

        cat2, hint2 = agent_logic_main.classify_error("SyntaxError: invalid syntax at line 10")
        self.assertEqual(cat2, "syntax_error")

        cat3, hint3 = agent_logic_main.classify_error("Something totally unexpected")
        self.assertEqual(cat3, "unknown")

    def test_format_plan_status(self) -> None:
        result = agent_logic_main.format_plan_status(["Step A", "Step B", "Step C"], 1)
        self.assertIn("[done]", result)
        self.assertIn("[current]", result)
        self.assertIn("[pending]", result)

    def test_build_reflection_prompt_includes_error_category(self) -> None:
        msg = agent_logic_main.build_reflection_prompt(
            "Fix the bug",
            "Sandbox tool filesystem.read",
            "FileNotFoundError: No such file or directory",
            [],
        )
        self.assertIn("file_not_found", msg.content)
        self.assertIn("Recovery hint", msg.content)

    def test_execute_edit_file_success(self) -> None:
        file_content = "line1\ndef old():\n    pass\nline4"

        def fake_sandbox(tool_name, tool_args):
            if tool_name == "filesystem.read":
                return {
                    "messages": [agent_logic_main.AIMessage(content=file_content)],
                    "invoke_status": "completed",
                }
            if tool_name == "filesystem.write":
                return {
                    "messages": [agent_logic_main.AIMessage(content="Written")],
                    "invoke_status": "completed",
                }
            return {"invoke_status": "blocked"}

        result = agent_logic_main.execute_edit_file("/src/app.py", "def old():", "def new():", fake_sandbox)
        self.assertEqual(result["invoke_status"], "completed")
        self.assertIn("Successfully edited", result["messages"][0].content)

    def test_execute_edit_file_old_text_not_found(self) -> None:
        def fake_sandbox(tool_name, tool_args):
            return {
                "messages": [agent_logic_main.AIMessage(content="file content without match")],
                "invoke_status": "completed",
            }

        result = agent_logic_main.execute_edit_file("/src/app.py", "nonexistent", "replacement", fake_sandbox)
        self.assertEqual(result["invoke_status"], "blocked")
        self.assertIn("old_text not found", result["messages"][0].content)

    def test_execute_edit_file_ambiguous_match(self) -> None:
        def fake_sandbox(tool_name, tool_args):
            return {
                "messages": [agent_logic_main.AIMessage(content="dup\ndup\n")],
                "invoke_status": "completed",
            }

        result = agent_logic_main.execute_edit_file("/src/app.py", "dup", "new", fake_sandbox)
        self.assertEqual(result["invoke_status"], "blocked")
        self.assertIn("matches 2 locations", result["messages"][0].content)

    def test_execute_batch_read_success(self) -> None:
        def fake_sandbox(tool_name, tool_args):
            path = tool_args.get("path", "unknown")
            return {
                "messages": [agent_logic_main.AIMessage(content=f"content of {path}")],
                "invoke_status": "completed",
            }

        result = agent_logic_main.execute_batch_read([{"path": "/a.py"}, {"path": "/b.py"}], fake_sandbox)
        self.assertEqual(result["invoke_status"], "completed")
        self.assertIn("/a.py", result["messages"][0].content)
        self.assertIn("/b.py", result["messages"][0].content)

    def test_run_autonomous_session_plan_action_does_not_consume_step(self) -> None:
        decisions = iter(
            [
                agent_logic_main.AIMessage(
                    content='{"action":"plan","thinking":"plan it","steps":["Read file","Edit file"]}'
                ),
                agent_logic_main.AIMessage(content='{"action":"respond","response":"Done."}'),
            ]
        )
        state = {
            "request_prompt": "Fix the bug",
            "messages": [agent_logic_main.HumanMessage(content="Fix the bug")],
            "context": "",
            "team_context": None,
            "system_prompt": "",
            "selected_model": "gpt-4",
            "max_steps": 3,
            "step_count": 0,
        }

        result = agent_logic_main.run_autonomous_session(
            state,
            plan_invoke=lambda _m: next(decisions),
            execute_action=lambda _a, _s: {},
        )
        self.assertEqual(result["invoke_status"], "completed")
        self.assertEqual(result["step_count"], 0)
        self.assertIn("Done.", result["messages"][0].content)

    def test_run_autonomous_session_appends_change_summary(self) -> None:
        decisions = iter(
            [
                agent_logic_main.AIMessage(
                    content='{"action":"edit_file","thinking":"fix it","path":"/app.py","old_text":"old","new_text":"new"}'
                ),
                agent_logic_main.AIMessage(content='{"action":"respond","response":"Fixed."}'),
            ]
        )

        def fake_execute(action, loop_state):
            if action["action"] == "edit_file":
                return {
                    "messages": [agent_logic_main.AIMessage(content="Successfully edited '/app.py'")],
                    "invoke_status": "completed",
                }
            return {}

        state = {
            "request_prompt": "Fix bug",
            "messages": [agent_logic_main.HumanMessage(content="Fix bug")],
            "context": "",
            "team_context": None,
            "system_prompt": "",
            "selected_model": "gpt-4",
            "max_steps": 5,
            "step_count": 0,
        }

        result = agent_logic_main.run_autonomous_session(
            state,
            plan_invoke=lambda _m: next(decisions),
            execute_action=fake_execute,
        )
        self.assertEqual(result["invoke_status"], "completed")
        response_text = result["messages"][0].content
        self.assertIn("Changes made", response_text)
        self.assertIn("/app.py", response_text)

    # ------------------------------------------------------------------
    # Phase C: note action
    # ------------------------------------------------------------------

    def test_normalize_supervisor_action_note(self):
        result = agent_logic_main.normalize_supervisor_action(
            {"action": "note", "note": "remember the API uses v2", "thinking": "t"}
        )
        self.assertIsNotNone(result)
        self.assertEqual(result["action"], "note")
        self.assertEqual(result["note"], "remember the API uses v2")

    def test_normalize_supervisor_action_note_truncates_long(self):
        long_note = "x" * 600
        result = agent_logic_main.normalize_supervisor_action({"action": "note", "note": long_note})
        self.assertIsNotNone(result)
        self.assertEqual(len(result["note"]), 500)

    def test_normalize_supervisor_action_note_empty_returns_none(self):
        result = agent_logic_main.normalize_supervisor_action({"action": "note", "note": ""})
        self.assertIsNone(result)

    def test_normalize_supervisor_action_note_missing_returns_none(self):
        result = agent_logic_main.normalize_supervisor_action({"action": "note"})
        self.assertIsNone(result)

    def test_describe_autonomous_action_note(self):
        label = agent_logic_main.describe_autonomous_action({"action": "note"})
        self.assertEqual(label, "Note to scratchpad")

    # ------------------------------------------------------------------
    # Phase C: _is_decision_anchor
    # ------------------------------------------------------------------

    def test_is_decision_anchor_plan(self):
        msg = agent_logic_main.AIMessage(content="Plan created with 3 steps")
        self.assertTrue(agent_logic_main._is_decision_anchor(msg))

    def test_is_decision_anchor_reflection(self):
        msg = agent_logic_main.AIMessage(content="REFLECTION: need to use a different approach")
        self.assertTrue(agent_logic_main._is_decision_anchor(msg))

    def test_is_decision_anchor_note(self):
        msg = agent_logic_main.AIMessage(content="Note saved: API is on port 8080")
        self.assertTrue(agent_logic_main._is_decision_anchor(msg))

    def test_is_decision_anchor_regular_message(self):
        msg = agent_logic_main.AIMessage(content="The code looks correct")
        self.assertFalse(agent_logic_main._is_decision_anchor(msg))

    def test_is_decision_anchor_empty(self):
        msg = agent_logic_main.AIMessage(content="")
        self.assertFalse(agent_logic_main._is_decision_anchor(msg))

    # ------------------------------------------------------------------
    # Phase C: summarize_message_history preserves anchors
    # ------------------------------------------------------------------

    def test_summarize_message_history_preserves_anchors(self):
        msgs = [
            agent_logic_main.HumanMessage(content="Fix the bug"),
            agent_logic_main.AIMessage(content="Plan created with 2 steps"),
            agent_logic_main.AIMessage(content="step 1 output"),
            agent_logic_main.AIMessage(content="step 2 output"),
            agent_logic_main.AIMessage(content="REFLECTION: learned X"),
            agent_logic_main.AIMessage(content="filler 1"),
            agent_logic_main.AIMessage(content="filler 2"),
            agent_logic_main.AIMessage(content="filler 3"),
            agent_logic_main.AIMessage(content="filler 4"),
            agent_logic_main.AIMessage(content="last message"),
        ]
        result = agent_logic_main.summarize_message_history(msgs, limit=4)
        contents = [m["content"] for m in result]
        # The plan and reflection anchors should survive compression
        self.assertTrue(any("Plan created" in c for c in contents))
        self.assertTrue(any("REFLECTION" in c for c in contents))
        # The first message (objective) should be preserved
        self.assertEqual(result[0]["content"], "Fix the bug")
        # Last message should be preserved
        self.assertTrue(any("last message" in c for c in contents))

    # ------------------------------------------------------------------
    # Phase C: _is_destructive_action
    # ------------------------------------------------------------------

    def test_is_destructive_action_filesystem_delete(self):
        decision = {"action": "sandbox_tool", "tool_name": "filesystem.delete"}
        self.assertTrue(agent_logic_main._is_destructive_action(decision))

    def test_is_destructive_action_filesystem_read_not_destructive(self):
        decision = {"action": "sandbox_tool", "tool_name": "filesystem.read"}
        self.assertFalse(agent_logic_main._is_destructive_action(decision))

    def test_is_destructive_action_rm_command(self):
        decision = {"action": "local_shell", "command": "rm", "args": ["-rf", "/tmp/foo"]}
        self.assertTrue(agent_logic_main._is_destructive_action(decision))

    def test_is_destructive_action_git_push(self):
        decision = {"action": "local_shell", "command": "git push", "args": ["--force"]}
        self.assertTrue(agent_logic_main._is_destructive_action(decision))

    def test_is_destructive_action_ls_not_destructive(self):
        decision = {"action": "local_shell", "command": "ls", "args": []}
        self.assertFalse(agent_logic_main._is_destructive_action(decision))

    def test_is_destructive_action_edit_file_not_destructive(self):
        decision = {"action": "edit_file", "path": "/app.py"}
        self.assertFalse(agent_logic_main._is_destructive_action(decision))

    # ------------------------------------------------------------------
    # Phase C: _auto_lint_command
    # ------------------------------------------------------------------

    def test_auto_lint_command_python(self):
        result = agent_logic_main._auto_lint_command("/app.py", {"projectType": "python"})
        self.assertIsNotNone(result)
        cmd, args = result
        self.assertEqual(cmd, "python")
        self.assertIn("py_compile", " ".join(args))

    def test_auto_lint_command_go(self):
        result = agent_logic_main._auto_lint_command("/main.go", {"projectType": "go"})
        self.assertIsNotNone(result)
        cmd, args = result
        self.assertEqual(cmd, "go")
        self.assertIn("vet", args)

    def test_auto_lint_command_no_profile(self):
        result = agent_logic_main._auto_lint_command("/app.py", None)
        self.assertIsNone(result)

    def test_auto_lint_command_unknown_extension(self):
        result = agent_logic_main._auto_lint_command("/data.csv", {"projectType": "python"})
        self.assertIsNone(result)

    # ------------------------------------------------------------------
    # Phase C: _build_file_tree
    # ------------------------------------------------------------------

    def test_build_file_tree_basic(self):
        """Tree builder returns compact listing from sandbox filesystem.ls calls."""
        call_log = []

        def fake_sandbox(tool_name, args):
            call_log.append((tool_name, args))
            path = args.get("path", "")
            if path == "/":
                return {"messages": [agent_logic_main.AIMessage(content="src/, README.md")]}
            if path == "/src":
                return {"messages": [agent_logic_main.AIMessage(content="main.py, utils.py")]}
            return {"messages": [agent_logic_main.AIMessage(content="")]}

        tree = agent_logic_main._build_file_tree(fake_sandbox, max_depth=2)
        self.assertIn("src", tree)
        self.assertIn("README.md", tree)

    def test_build_file_tree_skips_hidden_dirs(self):
        def fake_sandbox(tool_name, args):
            path = args.get("path", "")
            if path == "/":
                return {"messages": [agent_logic_main.AIMessage(content=".git, node_modules, src/")]}
            if path == "/src":
                return {"messages": [agent_logic_main.AIMessage(content="app.py")]}
            return {"messages": [agent_logic_main.AIMessage(content="")]}

        tree = agent_logic_main._build_file_tree(fake_sandbox, max_depth=2)
        self.assertIn("[skipped]", tree)
        self.assertNotIn(".git\n", tree.replace("[skipped]", ""))

    # ------------------------------------------------------------------
    # Phase C: _scan_git_status
    # ------------------------------------------------------------------

    def test_scan_git_status_with_branch(self):
        def fake_sandbox(tool_name, args):
            path = args.get("path", "")
            if path == "/.git":
                return {"messages": [agent_logic_main.AIMessage(content="HEAD, refs, objects")]}
            if path == "/.git/HEAD":
                return {"messages": [agent_logic_main.AIMessage(content="ref: refs/heads/main")]}
            return {"messages": [agent_logic_main.AIMessage(content="")]}

        git_info = agent_logic_main._scan_git_status(fake_sandbox)
        self.assertIsNotNone(git_info)
        self.assertTrue(git_info["enabled"])
        self.assertEqual(git_info["branch"], "main")

    def test_scan_git_status_no_git(self):
        def fake_sandbox(tool_name, args):
            return {"messages": [agent_logic_main.AIMessage(content="")]}

        git_info = agent_logic_main._scan_git_status(fake_sandbox)
        self.assertIsNone(git_info)

    def test_scan_git_status_detached_head(self):
        def fake_sandbox(tool_name, args):
            path = args.get("path", "")
            if path == "/.git":
                return {"messages": [agent_logic_main.AIMessage(content="HEAD")]}
            if path == "/.git/HEAD":
                return {"messages": [agent_logic_main.AIMessage(content="abc123def456789")]}
            return {"messages": [agent_logic_main.AIMessage(content="")]}

        git_info = agent_logic_main._scan_git_status(fake_sandbox)
        self.assertIsNotNone(git_info)
        self.assertEqual(git_info["branch"], "abc123def456")  # first 12 chars

    # ------------------------------------------------------------------
    # Phase C: build_supervisor_messages includes scratchpad + workspace extras
    # ------------------------------------------------------------------

    def test_build_supervisor_messages_includes_scratchpad(self):
        state = {
            "messages": [agent_logic_main.HumanMessage(content="do X")],
            "request_prompt": "do X",
            "workspace_scanned": True,
            "scratchpad": ["note A", "note B"],
            "workspace_profile": {
                "projectType": "python",
                "rootFiles": "main.py",
                "fileTree": "src/\n  app.py",
                "git": {"enabled": True, "branch": "main"},
                "lintCommand": "python -m py_compile",
                "testCommand": "pytest",
            },
        }
        result = agent_logic_main.build_supervisor_messages(state)
        # Find the payload message (JSON string that has workspaceProfile)
        payload_msg = None
        for msg in result:
            content = agent_logic_main.get_message_content(msg)
            if "workspaceProfile" in content:
                payload_msg = content
                break

        self.assertIsNotNone(payload_msg)
        payload = json.loads(payload_msg)
        self.assertIn("scratchpad", payload)
        self.assertEqual(payload["scratchpad"], ["note A", "note B"])
        wp = payload["workspaceProfile"]
        self.assertIn("fileTree", wp)
        self.assertIn("git", wp)
        self.assertEqual(wp["git"]["branch"], "main")
        self.assertIn("lintCommand", wp)
        self.assertIn("testCommand", wp)

    # ------------------------------------------------------------------
    # Phase C: run_autonomous_session — note action doesn't consume step
    # ------------------------------------------------------------------

    def test_run_autonomous_session_note_does_not_consume_step(self):
        """The note action is free — it should not increment step_count."""
        decisions = iter(
            [
                # Step 1: agent takes a note (should be free)
                {"thinking": "saving for later", "action": "note", "note": "API on port 3000"},
                # Step 2: agent finishes
                {"thinking": "done", "action": "done", "summary": "Noted."},
            ]
        )

        def fake_invoke(messages):
            d = next(decisions)
            return agent_logic_main.AIMessage(content=json.dumps(d))

        state = {
            "request_prompt": "Help me",
            "messages": [agent_logic_main.HumanMessage(content="Help me")],
            "context": "",
            "team_context": None,
            "system_prompt": "",
            "selected_model": "gpt-4",
            "max_steps": 5,
            "step_count": 0,
        }

        result = agent_logic_main.run_autonomous_session(
            state,
            plan_invoke=fake_invoke,
            execute_action=lambda d, s: {"messages": [], "invoke_status": "completed"},
        )
        self.assertEqual(result["invoke_status"], "completed")
        # step_count should be 1 (only the done action), not 2
        self.assertLessEqual(result.get("step_count", 0), 1)

    # ------------------------------------------------------------------
    # Phase C: run_autonomous_session — adaptive re-planning
    # ------------------------------------------------------------------

    def test_run_autonomous_session_adaptive_replan(self):
        """After consecutive failures, a REPLAN hint should be injected."""
        call_count = [0]

        def fake_invoke(messages):
            call_count[0] += 1
            if call_count[0] <= 3:
                # First three: plan then fail twice
                if call_count[0] == 1:
                    return agent_logic_main.AIMessage(
                        content=json.dumps(
                            {
                                "thinking": "plan",
                                "action": "plan",
                                "steps": [{"description": "step A"}, {"description": "step B"}],
                            }
                        )
                    )
                return agent_logic_main.AIMessage(
                    content=json.dumps(
                        {
                            "thinking": "try",
                            "action": "sandbox_tool",
                            "tool_name": "filesystem.read",
                            "tool_args": {"path": "/x"},
                        }
                    )
                )
            # After replan hint should appear — just finish
            return agent_logic_main.AIMessage(
                content=json.dumps(
                    {
                        "thinking": "done",
                        "action": "done",
                        "summary": "Gave up.",
                    }
                )
            )

        failure_count = [0]

        def failing_execute(decision, local_state):
            failure_count[0] += 1
            return {
                "messages": [agent_logic_main.AIMessage(content="Error: file not found")],
                "invoke_status": "error",
            }

        state = {
            "request_prompt": "Do X",
            "messages": [agent_logic_main.HumanMessage(content="Do X")],
            "context": "",
            "team_context": None,
            "system_prompt": "",
            "selected_model": "gpt-4",
            "max_steps": 10,
            "step_count": 0,
        }

        result = agent_logic_main.run_autonomous_session(
            state,
            plan_invoke=fake_invoke,
            execute_action=failing_execute,
        )
        self.assertEqual(result["invoke_status"], "completed")
        # Verify we had failures
        self.assertGreaterEqual(failure_count[0], 2)

    # ------------------------------------------------------------------
    # Phase C: scan_workspace_profile enhanced
    # ------------------------------------------------------------------

    def test_scan_workspace_profile_derives_lint_test_commands(self):
        """scan_workspace_profile should derive lint/test commands for python projects."""

        def fake_sandbox(tool_name, args):
            path = args.get("path", "")
            if tool_name == "filesystem.ls" and path == "/":
                return {"messages": [agent_logic_main.AIMessage(content="main.py, requirements.txt, src/")]}
            if tool_name == "filesystem.ls" and path == "/.git":
                return {"messages": [agent_logic_main.AIMessage(content="HEAD, refs")]}
            if tool_name == "filesystem.read" and path == "/.git/HEAD":
                return {"messages": [agent_logic_main.AIMessage(content="ref: refs/heads/develop")]}
            # Config file reads — return content so project type is detected
            if tool_name == "filesystem.read" and path == "/requirements.txt":
                return {"messages": [agent_logic_main.AIMessage(content="flask\nrequests")]}
            if tool_name == "filesystem.read":
                return {"messages": [agent_logic_main.AIMessage(content="")]}
            # Sub-directory listing for _build_file_tree
            if tool_name == "filesystem.ls":
                return {"messages": [agent_logic_main.AIMessage(content="app.py")]}
            return {"messages": [agent_logic_main.AIMessage(content="")]}

        profile = agent_logic_main.scan_workspace_profile(fake_sandbox)
        self.assertEqual(profile["projectType"], "python")
        self.assertIn("fileTree", profile)
        self.assertIn("git", profile)
        self.assertTrue(profile["git"]["enabled"])
        self.assertEqual(profile["git"]["branch"], "develop")
        # Python projects get lint/test commands
        self.assertIn("lintCommand", profile)
        self.assertIn("testCommand", profile)

    # ------------------------------------------------------------------
    # Phase D: safe_json_dumps
    # ------------------------------------------------------------------

    def test_safe_json_dumps_basic(self):
        result = agent_logic_main.safe_json_dumps({"b": 2, "a": 1})
        self.assertEqual(result, '{"a": 1, "b": 2}')

    def test_safe_json_dumps_non_serializable_uses_str(self):
        import datetime

        result = agent_logic_main.safe_json_dumps({"ts": datetime.date(2024, 1, 1)})
        self.assertIn("2024-01-01", result)

    def test_safe_json_dumps_unicode(self):
        result = agent_logic_main.safe_json_dumps({"emoji": "\U0001f600"})
        self.assertIn("\U0001f600", result)

    # ------------------------------------------------------------------
    # Phase D: execute_batch_read parallel
    # ------------------------------------------------------------------

    def test_batch_read_parallel_multiple_files(self):
        call_log = []

        def fake_sandbox(tool_name, tool_args):
            path = tool_args.get("path", "")
            call_log.append(path)
            return {"messages": [agent_logic_main.AIMessage(content=f"content of {path}")]}

        reads = [
            {"path": "/a.py"},
            {"path": "/b.py"},
            {"path": "/c.py"},
        ]
        result = agent_logic_main.execute_batch_read(reads, fake_sandbox)
        self.assertEqual(result["invoke_status"], "completed")
        self.assertIn("=== /a.py ===", result["messages"][0].content)
        self.assertIn("=== /b.py ===", result["messages"][0].content)
        self.assertIn("=== /c.py ===", result["messages"][0].content)
        self.assertEqual(len(call_log), 3)

    def test_batch_read_preserves_order(self):
        """Parallel reads should return results in input order."""
        import time as _time

        def slow_sandbox(tool_name, tool_args):
            path = tool_args.get("path", "")
            if path == "/first.py":
                _time.sleep(0.05)
            return {"messages": [agent_logic_main.AIMessage(content=f"data:{path}")]}

        reads = [{"path": "/first.py"}, {"path": "/second.py"}]
        result = agent_logic_main.execute_batch_read(reads, slow_sandbox)
        content = result["messages"][0].content
        first_idx = content.index("=== /first.py ===")
        second_idx = content.index("=== /second.py ===")
        self.assertLess(first_idx, second_idx, "Results should preserve input order")

    def test_batch_read_single_file_no_threadpool(self):
        call_count = 0

        def fake_sandbox(tool_name, tool_args):
            nonlocal call_count
            call_count += 1
            return {"messages": [agent_logic_main.AIMessage(content="ok")]}

        reads = [{"path": "/only.py"}]
        result = agent_logic_main.execute_batch_read(reads, fake_sandbox)
        self.assertEqual(result["invoke_status"], "completed")
        self.assertEqual(call_count, 1)

    def test_batch_read_empty_returns_blocked(self):
        result = agent_logic_main.execute_batch_read([], lambda *a: {})
        self.assertEqual(result["invoke_status"], "blocked")

    # ------------------------------------------------------------------
    # Phase D: Token accumulation
    # ------------------------------------------------------------------

    def test_token_accumulation_in_autonomous_session(self):
        """Token usage is accumulated from LLM responses with usage_metadata."""
        call_count = 0

        class FakeMessage:
            def __init__(self, content):
                self.content = content
                self.id = None
                self.usage_metadata = {
                    "input_tokens": 100,
                    "output_tokens": 50,
                    "total_tokens": 150,
                }

        def plan_invoke(messages):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return FakeMessage('{"action":"respond","response":"done","thinking":"ok"}')
            return FakeMessage('{"action":"respond","response":"done","thinking":"ok"}')

        state = {
            "request_prompt": "Test tokens",
            "messages": [agent_logic_main.HumanMessage(content="Test")],
            "context": "",
            "team_context": None,
            "system_prompt": "",
            "selected_model": "gpt-4",
            "max_steps": 4,
            "step_count": 0,
            "workspace_scanned": True,
        }

        result = agent_logic_main.run_autonomous_session(
            state,
            plan_invoke=plan_invoke,
            execute_action=lambda action, s: {"messages": [], "invoke_status": "completed"},
        )
        self.assertIn("token_usage", result)
        self.assertEqual(result["token_usage"]["prompt_tokens"], 100)
        self.assertEqual(result["token_usage"]["completion_tokens"], 50)

    # ------------------------------------------------------------------
    # Phase D: Tool result caching
    # ------------------------------------------------------------------

    def test_tool_cache_returns_cached_read(self):
        """Cached execute should return same result for repeated reads."""
        call_count = 0
        step = 0

        def plan_invoke(messages):
            nonlocal step
            step += 1
            if step <= 2:
                return agent_logic_main.AIMessage(
                    content='{"action":"sandbox_tool","tool_name":"filesystem.read","tool_args":{"path":"/test.py"},"thinking":"read"}'
                )
            return agent_logic_main.AIMessage(content='{"action":"respond","response":"done","thinking":"ok"}')

        def execute_action(action, s):
            nonlocal call_count
            if action.get("action") == "sandbox_tool":
                call_count += 1
                return {
                    "messages": [agent_logic_main.AIMessage(content="file content")],
                    "invoke_status": "completed",
                }
            return {"messages": [], "invoke_status": "completed"}

        state = {
            "request_prompt": "Read test",
            "messages": [agent_logic_main.HumanMessage(content="Read")],
            "context": "",
            "team_context": None,
            "system_prompt": "",
            "selected_model": "gpt-4",
            "max_steps": 5,
            "step_count": 0,
            "workspace_scanned": True,
        }

        agent_logic_main.run_autonomous_session(
            state,
            plan_invoke=plan_invoke,
            execute_action=execute_action,
        )
        # Second read should be cached
        self.assertEqual(call_count, 1)

    # ------------------------------------------------------------------
    # Phase D: git_commit normalization
    # ------------------------------------------------------------------

    def test_normalize_git_commit(self):
        result = agent_logic_main.normalize_supervisor_action(
            {
                "action": "git_commit",
                "message": "fix: resolve bug",
                "all": True,
                "thinking": "committing changes",
            }
        )
        self.assertIsNotNone(result)
        self.assertEqual(result["action"], "git_commit")
        self.assertEqual(result["message"], "fix: resolve bug")
        self.assertTrue(result["all"])

    def test_normalize_git_commit_empty_message_returns_none(self):
        result = agent_logic_main.normalize_supervisor_action(
            {
                "action": "git_commit",
                "message": "",
            }
        )
        self.assertIsNone(result)

    def test_describe_git_commit(self):
        desc = agent_logic_main.describe_autonomous_action(
            {
                "action": "git_commit",
                "message": "feat: add new feature",
            }
        )
        self.assertIn("Git commit", desc)
        self.assertIn("feat: add new feature", desc)

    # ------------------------------------------------------------------
    # Phase D: execute_git_commit
    # ------------------------------------------------------------------

    def test_execute_git_commit_success(self):
        calls = []

        def fake_local(cmd, args):
            calls.append((cmd, args))
            return {
                "messages": [agent_logic_main.AIMessage(content="[main abc1234] fix bug")],
                "invoke_status": "completed",
            }

        result = agent_logic_main.execute_git_commit("fix bug", execute_local_tool=fake_local)
        self.assertEqual(result["invoke_status"], "completed")
        self.assertEqual(len(calls), 2)  # git add -A, git commit -m
        self.assertEqual(calls[0], ("git", ["add", "-A"]))
        self.assertEqual(calls[1][0], "git")
        self.assertIn("-m", calls[1][1])

    def test_execute_git_commit_add_failure(self):
        def fake_local(cmd, args):
            if "add" in args:
                return {"messages": [agent_logic_main.AIMessage(content="error")], "invoke_status": "blocked"}
            return {"messages": [agent_logic_main.AIMessage(content="ok")], "invoke_status": "completed"}

        result = agent_logic_main.execute_git_commit("fix", execute_local_tool=fake_local)
        self.assertEqual(result["invoke_status"], "blocked")

    def test_execute_git_commit_no_stage(self):
        calls = []

        def fake_local(cmd, args):
            calls.append((cmd, args))
            return {
                "messages": [agent_logic_main.AIMessage(content="committed")],
                "invoke_status": "completed",
            }

        result = agent_logic_main.execute_git_commit("manual commit", commit_all=False, execute_local_tool=fake_local)
        self.assertEqual(result["invoke_status"], "completed")
        self.assertEqual(len(calls), 1)  # only git commit, no git add

    # ------------------------------------------------------------------
    # Phase D: _auto_test_command
    # ------------------------------------------------------------------

    def test_auto_test_command_python(self):
        result = agent_logic_main._auto_test_command(
            {
                "testCommand": "python -m pytest --tb=short -q",
            }
        )
        self.assertIsNotNone(result)
        cmd, args = result
        self.assertEqual(cmd, "python")
        self.assertIn("-m", args)

    def test_auto_test_command_none_when_no_profile(self):
        self.assertIsNone(agent_logic_main._auto_test_command(None))

    def test_auto_test_command_none_when_empty(self):
        self.assertIsNone(agent_logic_main._auto_test_command({"testCommand": ""}))

    # ------------------------------------------------------------------
    # Phase D: Streaming events (tool_start / tool_complete)
    # ------------------------------------------------------------------

    def test_autonomous_session_emits_tool_events(self):
        """Tool start/complete events should be emitted around action execution."""
        events = []

        def plan_invoke(messages):
            return agent_logic_main.AIMessage(content='{"action":"respond","response":"done","thinking":"immediate"}')

        state = {
            "request_prompt": "Test events",
            "messages": [agent_logic_main.HumanMessage(content="Test")],
            "context": "",
            "team_context": None,
            "system_prompt": "",
            "selected_model": "gpt-4",
            "max_steps": 4,
            "step_count": 0,
            "workspace_scanned": True,
        }

        with patch.object(agent_logic_main, "publish_runtime_event", side_effect=lambda e, d: events.append(e)):
            agent_logic_main.run_autonomous_session(
                state,
                plan_invoke=plan_invoke,
                execute_action=lambda a, s: {"messages": [], "invoke_status": "completed"},
            )

        # respond action doesn't go through tool execution path, so no tool_start/tool_complete
        # But we should see agent.step and agent.tokens events
        event_types = set(events)
        self.assertIn("agent.step", event_types)


class BuildToolSchemasTests(unittest.TestCase):
    """Tests for build_tool_schemas() — tool schema filtering based on capabilities."""

    def test_all_schemas_returned_when_all_capabilities_enabled(self) -> None:
        caps = {"a2aTargets": [("ns", "agent")], "allowSubagents": True, "mcpServers": ["server1"]}
        schemas = agent_logic_main.build_tool_schemas(caps)
        names = {s["function"]["name"] for s in schemas}
        self.assertIn("a2a_call", names)
        self.assertIn("subagent_team", names)
        self.assertIn("mcp_tool", names)
        self.assertIn("respond", names)
        self.assertIn("edit_file", names)
        self.assertIn("undo_edit", names)

    def test_a2a_removed_when_no_targets(self) -> None:
        caps = {"a2aTargets": [], "allowSubagents": True, "mcpServers": ["s1"]}
        schemas = agent_logic_main.build_tool_schemas(caps)
        names = {s["function"]["name"] for s in schemas}
        self.assertNotIn("a2a_call", names)
        self.assertNotIn("subagent_team", names)

    def test_mcp_removed_when_no_servers(self) -> None:
        caps = {"a2aTargets": [("ns", "a")], "allowSubagents": True, "mcpServers": []}
        schemas = agent_logic_main.build_tool_schemas(caps)
        names = {s["function"]["name"] for s in schemas}
        self.assertNotIn("mcp_tool", names)

    def test_subagent_removed_when_not_allowed(self) -> None:
        caps = {"a2aTargets": [("ns", "a")], "allowSubagents": False, "mcpServers": ["s1"]}
        schemas = agent_logic_main.build_tool_schemas(caps)
        names = {s["function"]["name"] for s in schemas}
        self.assertNotIn("subagent_team", names)
        self.assertIn("a2a_call", names)

    def test_schema_structure_is_openai_compatible(self) -> None:
        caps = {"a2aTargets": [], "allowSubagents": False, "mcpServers": []}
        schemas = agent_logic_main.build_tool_schemas(caps)
        for schema in schemas:
            self.assertEqual(schema["type"], "function")
            self.assertIn("name", schema["function"])
            self.assertIn("parameters", schema["function"])


class ParseToolCallToActionTests(unittest.TestCase):
    """Tests for parse_tool_call_to_action() — converting OpenAI tool_calls to actions."""

    def test_parses_respond_tool_call(self) -> None:
        tool_call = {"name": "respond", "args": {"thinking": "done", "response": "Here is the answer"}}
        action = agent_logic_main.parse_tool_call_to_action(tool_call)
        self.assertIsNotNone(action)
        self.assertEqual(action["action"], "respond")
        self.assertEqual(action["response"], "Here is the answer")

    def test_parses_edit_file_tool_call(self) -> None:
        tool_call = {
            "name": "edit_file",
            "args": {"thinking": "fix bug", "path": "app.py", "old_text": "old", "new_text": "new"},
        }
        action = agent_logic_main.parse_tool_call_to_action(tool_call)
        self.assertIsNotNone(action)
        self.assertEqual(action["action"], "edit_file")
        self.assertEqual(action["path"], "app.py")

    def test_parses_sandbox_tool_call(self) -> None:
        tool_call = {"name": "sandbox_tool", "args": {"tool_name": "filesystem.read", "tool_args": {"path": "x.py"}}}
        action = agent_logic_main.parse_tool_call_to_action(tool_call)
        self.assertIsNotNone(action)
        self.assertEqual(action["action"], "sandbox_tool")
        self.assertEqual(action["tool_name"], "filesystem.read")

    def test_parses_undo_edit_tool_call(self) -> None:
        tool_call = {"name": "undo_edit", "args": {"thinking": "revert last"}}
        action = agent_logic_main.parse_tool_call_to_action(tool_call)
        self.assertIsNotNone(action)
        self.assertEqual(action["action"], "undo_edit")

    def test_returns_none_for_invalid_args(self) -> None:
        result = agent_logic_main.parse_tool_call_to_action({"name": "respond", "args": "not valid json {"})
        self.assertIsNone(result)

    def test_returns_none_for_empty_name(self) -> None:
        result = agent_logic_main.parse_tool_call_to_action({"name": "", "args": {}})
        self.assertIsNone(result)

    def test_parses_string_args_as_json(self) -> None:
        tool_call = {"name": "respond", "args": '{"thinking":"t","response":"ok"}'}
        action = agent_logic_main.parse_tool_call_to_action(tool_call)
        self.assertIsNotNone(action)
        self.assertEqual(action["action"], "respond")
        self.assertEqual(action["response"], "ok")


class ExecuteUndoEditTests(unittest.TestCase):
    """Tests for execute_undo_edit() — undo last edit."""

    def test_empty_history_returns_blocked(self) -> None:
        result = agent_logic_main.execute_undo_edit([], lambda t, a: {})
        self.assertEqual(result["invoke_status"], "blocked")
        self.assertEqual(result["error_type"], "undo_empty_history")

    def test_undo_pops_and_reverses_edit(self) -> None:
        tool_calls: list[tuple[str, dict]] = []

        def mock_sandbox_tool(tool_name: str, tool_args: dict) -> dict:
            tool_calls.append((tool_name, tool_args))
            if tool_name == "filesystem.read":
                return {
                    "messages": [agent_logic_main.AIMessage(content="line1\nnew_content\nline3")],
                    "invoke_status": "completed",
                }
            return {"messages": [agent_logic_main.AIMessage(content="written")], "invoke_status": "completed"}

        history = [{"path": "test.py", "old_text": "new_content", "new_text": "old_content"}]
        result = agent_logic_main.execute_undo_edit(history, mock_sandbox_tool)

        self.assertEqual(result["invoke_status"], "completed")
        self.assertEqual(len(history), 0)  # Record was popped
        # Should have called filesystem.read then filesystem.write
        self.assertEqual(tool_calls[0][0], "filesystem.read")
        self.assertEqual(tool_calls[1][0], "filesystem.write")
        # The write should contain the reversed content
        written_content = tool_calls[1][1]["content"]
        self.assertIn("old_content", written_content)
        self.assertNotIn("new_content", written_content)


class FuzzyEditMatchingTests(unittest.TestCase):
    """Tests for fuzzy matching in execute_edit_file()."""

    def test_exact_match_succeeds(self) -> None:
        def mock_sandbox_tool(tool_name: str, tool_args: dict) -> dict:
            if tool_name == "filesystem.read":
                return {
                    "messages": [agent_logic_main.AIMessage(content="line1\nold_text\nline3")],
                    "invoke_status": "completed",
                }
            return {"messages": [agent_logic_main.AIMessage(content="ok")], "invoke_status": "completed"}

        result = agent_logic_main.execute_edit_file("test.py", "old_text", "new_text", mock_sandbox_tool)
        self.assertEqual(result["invoke_status"], "completed")
        self.assertIn("_edit_record", result)
        self.assertEqual(result["_edit_record"]["path"], "test.py")

    def test_fuzzy_match_provides_hint(self) -> None:
        original = "def hello_world():\n    print('Hello World')\n    return True"
        # Similar but not exact — whitespace/case differs
        wrong_old = "def hello_world():\n    print('hello world')\n    return True"

        def mock_sandbox_tool(tool_name: str, tool_args: dict) -> dict:
            if tool_name == "filesystem.read":
                return {
                    "messages": [agent_logic_main.AIMessage(content=original)],
                    "invoke_status": "completed",
                }
            return {"messages": [agent_logic_main.AIMessage(content="ok")], "invoke_status": "completed"}

        with patch.object(agent_logic_main, "FUZZY_MATCH_THRESHOLD", 0.7):
            result = agent_logic_main.execute_edit_file("test.py", wrong_old, "replacement", mock_sandbox_tool)

        self.assertEqual(result["invoke_status"], "blocked")
        self.assertEqual(result["error_type"], "edit_old_text_not_found")
        # Should contain fuzzy match hint
        msg = result["messages"][0].content
        self.assertIn("close match", msg.lower())
        self.assertIn("similar", msg.lower())

    def test_no_fuzzy_hint_when_below_threshold(self) -> None:
        original = "completely different content here"
        wrong_old = "nothing like the original at all xyz"

        def mock_sandbox_tool(tool_name: str, tool_args: dict) -> dict:
            if tool_name == "filesystem.read":
                return {
                    "messages": [agent_logic_main.AIMessage(content=original)],
                    "invoke_status": "completed",
                }
            return {"messages": [agent_logic_main.AIMessage(content="ok")], "invoke_status": "completed"}

        with patch.object(agent_logic_main, "FUZZY_MATCH_THRESHOLD", 0.85):
            result = agent_logic_main.execute_edit_file("test.py", wrong_old, "new", mock_sandbox_tool)

        self.assertEqual(result["invoke_status"], "blocked")
        msg = result["messages"][0].content
        self.assertIn("old_text not found", msg)
        # Should NOT contain fuzzy match hint
        self.assertNotIn("close match", msg.lower())

    def test_edit_record_has_inverse_mapping(self) -> None:
        """The _edit_record should swap old_text and new_text for undo."""

        def mock_sandbox_tool(tool_name: str, tool_args: dict) -> dict:
            if tool_name == "filesystem.read":
                return {
                    "messages": [agent_logic_main.AIMessage(content="before\ntarget_text\nafter")],
                    "invoke_status": "completed",
                }
            return {"messages": [agent_logic_main.AIMessage(content="ok")], "invoke_status": "completed"}

        result = agent_logic_main.execute_edit_file("f.py", "target_text", "replacement", mock_sandbox_tool)
        self.assertEqual(result["invoke_status"], "completed")
        record = result["_edit_record"]
        # Record should reverse: old_text = new_text (what was written), new_text = old_text (what was there)
        self.assertEqual(record["old_text"], "replacement")
        self.assertEqual(record["new_text"], "target_text")


class TokenBudgetTests(unittest.TestCase):
    """Tests for token budget enforcement in run_autonomous_session."""

    def test_token_budget_stops_session_when_exceeded(self) -> None:
        state = {
            "request_prompt": "Do work.",
            "messages": [agent_logic_main.HumanMessage(content="Do work.")],
            "context": "",
            "team_context": None,
            "system_prompt": "",
            "selected_model": "gpt-4",
            "max_steps": 10,
            "step_count": 0,
            "workspace_scanned": True,
        }

        call_count = [0]

        def plan_invoke(_messages):
            call_count[0] += 1
            msg = agent_logic_main.AIMessage(
                content='{"action":"sandbox_tool","tool_name":"filesystem.ls","tool_args":{"path":"."}}'
            )
            # Simulate token usage that exceeds budget
            msg.usage_metadata = {"input_tokens": 5000, "output_tokens": 5000}
            return msg

        with (
            patch.object(agent_logic_main, "MAX_TOKEN_BUDGET", 100),
            patch.object(agent_logic_main, "publish_runtime_event", lambda e, d: None),
        ):
            result = agent_logic_main.run_autonomous_session(
                state,
                plan_invoke=plan_invoke,
                execute_action=lambda a, s: {
                    "messages": [agent_logic_main.AIMessage(content="done")],
                    "invoke_status": "continue",
                },
            )

        self.assertEqual(result["invoke_status"], "blocked")
        self.assertEqual(result["stop_reason"], "token_budget_exceeded")
        # Should stop after first LLM call since 10000 > 100
        self.assertEqual(call_count[0], 1)

    def test_zero_budget_means_unlimited(self) -> None:
        state = {
            "request_prompt": "Sum up.",
            "messages": [agent_logic_main.HumanMessage(content="Sum up.")],
            "context": "",
            "team_context": None,
            "system_prompt": "",
            "selected_model": "gpt-4",
            "max_steps": 4,
            "step_count": 0,
            "workspace_scanned": True,
        }

        def plan_invoke(_messages):
            msg = agent_logic_main.AIMessage(content='{"action":"respond","response":"done"}')
            msg.usage_metadata = {"input_tokens": 50000, "output_tokens": 50000}
            return msg

        with (
            patch.object(agent_logic_main, "MAX_TOKEN_BUDGET", 0),
            patch.object(agent_logic_main, "publish_runtime_event", lambda e, d: None),
        ):
            result = agent_logic_main.run_autonomous_session(
                state,
                plan_invoke=plan_invoke,
                execute_action=lambda a, s: {
                    "messages": [agent_logic_main.AIMessage(content="done")],
                    "invoke_status": "continue",
                },
            )

        self.assertEqual(result["invoke_status"], "completed")
        self.assertEqual(result["stop_reason"], "response")


class ToolCallIntegrationTests(unittest.TestCase):
    """Tests for native tool calling path in run_autonomous_session."""

    def test_tool_call_parsed_from_response(self) -> None:
        state = {
            "request_prompt": "Read file.",
            "messages": [agent_logic_main.HumanMessage(content="Read file.")],
            "context": "",
            "team_context": None,
            "system_prompt": "",
            "selected_model": "gpt-4",
            "max_steps": 4,
            "step_count": 0,
            "workspace_scanned": True,
        }

        call_count = [0]

        def plan_invoke(_messages):
            call_count[0] += 1
            if call_count[0] == 1:
                # First call: return a tool call for sandbox_tool
                msg = agent_logic_main.AIMessage(content="")
                msg.tool_calls = [
                    {
                        "name": "sandbox_tool",
                        "args": {"thinking": "read", "tool_name": "filesystem.ls", "tool_args": {"path": "."}},
                    }
                ]
                msg.usage_metadata = {"input_tokens": 100, "output_tokens": 50}
                return msg
            else:
                # Second call: respond
                msg = agent_logic_main.AIMessage(content='{"action":"respond","response":"files listed"}')
                msg.usage_metadata = {"input_tokens": 100, "output_tokens": 50}
                return msg

        execute_calls: list[dict] = []

        def execute_action(action, loop_state):
            execute_calls.append(action)
            return {
                "messages": [agent_logic_main.AIMessage(content="file.txt\ndir/")],
                "invoke_status": "continue",
            }

        with patch.object(agent_logic_main, "publish_runtime_event", lambda e, d: None):
            result = agent_logic_main.run_autonomous_session(
                state,
                plan_invoke=plan_invoke,
                execute_action=execute_action,
            )

        self.assertEqual(result["invoke_status"], "completed")
        self.assertEqual(len(execute_calls), 1)
        self.assertEqual(execute_calls[0]["action"], "sandbox_tool")
        self.assertEqual(execute_calls[0]["tool_name"], "filesystem.ls")

    def test_falls_back_to_text_when_no_tool_calls(self) -> None:
        state = {
            "request_prompt": "Hello.",
            "messages": [agent_logic_main.HumanMessage(content="Hello.")],
            "context": "",
            "team_context": None,
            "system_prompt": "",
            "selected_model": "gpt-4",
            "max_steps": 4,
            "step_count": 0,
            "workspace_scanned": True,
        }

        def plan_invoke(_messages):
            msg = agent_logic_main.AIMessage(content='{"action":"respond","response":"hi"}')
            msg.tool_calls = []  # Empty — no tool calling
            msg.usage_metadata = {"input_tokens": 100, "output_tokens": 50}
            return msg

        with patch.object(agent_logic_main, "publish_runtime_event", lambda e, d: None):
            result = agent_logic_main.run_autonomous_session(
                state,
                plan_invoke=plan_invoke,
                execute_action=lambda a, s: {},
            )

        self.assertEqual(result["invoke_status"], "completed")
        self.assertEqual(result["messages"][0].content, "hi")


class EditHistoryWiringTests(unittest.TestCase):
    """Tests for edit_history tracking in the autonomy loop."""

    def test_edit_history_populated_after_successful_edit(self) -> None:
        state = {
            "request_prompt": "Fix bug.",
            "messages": [agent_logic_main.HumanMessage(content="Fix bug.")],
            "context": "",
            "team_context": None,
            "system_prompt": "",
            "selected_model": "gpt-4",
            "max_steps": 4,
            "step_count": 0,
            "workspace_scanned": True,
        }

        call_count = [0]

        def plan_invoke(_messages):
            call_count[0] += 1
            if call_count[0] == 1:
                msg = agent_logic_main.AIMessage(
                    content='{"action":"edit_file","path":"test.py","old_text":"old","new_text":"new"}'
                )
                msg.usage_metadata = {"input_tokens": 100, "output_tokens": 50}
                return msg
            else:
                msg = agent_logic_main.AIMessage(content='{"action":"respond","response":"done"}')
                msg.usage_metadata = {"input_tokens": 100, "output_tokens": 50}
                return msg

        def execute_action(action, loop_state):
            if action["action"] == "edit_file":
                return {
                    "messages": [agent_logic_main.AIMessage(content="edited")],
                    "invoke_status": "completed",
                    "_edit_record": {"path": "test.py", "old_text": "new", "new_text": "old"},
                }
            return {
                "messages": [agent_logic_main.AIMessage(content="ok")],
                "invoke_status": "continue",
            }

        with patch.object(agent_logic_main, "publish_runtime_event", lambda e, d: None):
            result = agent_logic_main.run_autonomous_session(
                state,
                plan_invoke=plan_invoke,
                execute_action=execute_action,
            )

        self.assertEqual(result["invoke_status"], "completed")
        # The edit_history should have been populated
        self.assertIn("edit_history", result)
        self.assertEqual(len(result["edit_history"]), 1)
        self.assertEqual(result["edit_history"][0]["path"], "test.py")


# ===================================================================
#  Phase 3 Tests — Remaining Competitive Gaps
# ===================================================================


class EstimateTokensTests(unittest.TestCase):
    """Tests for _estimate_tokens helper."""

    def test_basic_english_text(self) -> None:
        # 4 chars ≈ 1 token
        self.assertEqual(agent_logic_main._estimate_tokens("abcdefgh"), 2)

    def test_empty_returns_one(self) -> None:
        self.assertEqual(agent_logic_main._estimate_tokens(""), 1)

    def test_short_text_minimum(self) -> None:
        # 3 chars -> max(0, 1) = 1
        self.assertEqual(agent_logic_main._estimate_tokens("abc"), 1)


class CalculateCostUsdTests(unittest.TestCase):
    """Tests for _calculate_cost_usd."""

    def test_known_model_exact(self) -> None:
        # gpt-4o: input $2.5/M, output $10/M
        cost = agent_logic_main._calculate_cost_usd(1_000_000, 1_000_000, "gpt-4o")
        self.assertAlmostEqual(cost, 12.5, places=4)

    def test_known_model_small_usage(self) -> None:
        # gpt-4o: 1000 input, 500 output
        cost = agent_logic_main._calculate_cost_usd(1000, 500, "gpt-4o")
        expected = (1000 / 1_000_000) * 2.5 + (500 / 1_000_000) * 10.0
        self.assertAlmostEqual(cost, round(expected, 6), places=6)

    def test_prefix_match(self) -> None:
        # "claude-3.5-sonnet-20241022" should prefix-match "claude-3.5-sonnet"
        cost = agent_logic_main._calculate_cost_usd(1_000_000, 0, "claude-3.5-sonnet-20241022")
        self.assertAlmostEqual(cost, 3.0, places=4)

    def test_unknown_model_returns_zero(self) -> None:
        cost = agent_logic_main._calculate_cost_usd(100000, 100000, "totally-unknown-model")
        self.assertEqual(cost, 0.0)

    def test_zero_tokens(self) -> None:
        cost = agent_logic_main._calculate_cost_usd(0, 0, "gpt-4")
        self.assertEqual(cost, 0.0)


class SummarizeMessageHistoryTokenBudgetTests(unittest.TestCase):
    """Tests for summarize_message_history with token_budget parameter."""

    def _make_msgs(self, contents: list[str]) -> list:
        return [agent_logic_main.HumanMessage(content=c) for c in contents]

    def test_budget_truncates_long_messages(self) -> None:
        msgs = self._make_msgs(["objective"] + ["x" * 4000] * 5)
        result = agent_logic_main.summarize_message_history(msgs, limit=100, token_budget=500)
        total = sum(agent_logic_main._estimate_tokens(m["content"]) for m in result)
        self.assertLessEqual(total, 500)

    def test_no_budget_keeps_all(self) -> None:
        msgs = self._make_msgs(["a", "b", "c"])
        result = agent_logic_main.summarize_message_history(msgs, limit=100, token_budget=0)
        self.assertEqual(len(result), 3)

    def test_budget_with_many_messages_compresses_middle(self) -> None:
        msgs = self._make_msgs(["obj"] + ["m" * 2000] * 20 + ["tail"])
        result = agent_logic_main.summarize_message_history(msgs, limit=8, token_budget=200)
        total = sum(agent_logic_main._estimate_tokens(m["content"]) for m in result)
        self.assertLessEqual(total, 200)


class ExecuteEditFilesTests(unittest.TestCase):
    """Tests for transactional multi-file execute_edit_files."""

    def _make_sandbox(self, file_contents: dict[str, str], fail_write_for: str | None = None):
        """Create a mock execute_sandbox_tool that simulates filesystem ops."""
        storage = {k: v for k, v in file_contents.items()}

        def sandbox(tool_name: str, args: dict) -> dict:
            path = args.get("path", "")
            if tool_name == "filesystem.read":
                if path in storage:
                    return {
                        "invoke_status": "completed",
                        "messages": [agent_logic_main.AIMessage(content=storage[path])],
                    }
                return {"invoke_status": "blocked", "messages": []}
            if tool_name == "filesystem.write":
                if fail_write_for and path == fail_write_for:
                    return {"invoke_status": "blocked", "messages": []}
                storage[path] = args.get("content", "")
                return {
                    "invoke_status": "completed",
                    "messages": [agent_logic_main.AIMessage(content="ok")],
                }
            return {"invoke_status": "blocked", "messages": []}

        return sandbox, storage

    def test_successful_multi_edit(self) -> None:
        sandbox, storage = self._make_sandbox(
            {
                "a.py": "hello world",
                "b.py": "foo bar baz",
            }
        )
        with patch.object(agent_logic_main, "publish_runtime_event", lambda e, d: None):
            result = agent_logic_main.execute_edit_files(
                [
                    {"path": "a.py", "old_text": "hello", "new_text": "hi"},
                    {"path": "b.py", "old_text": "bar", "new_text": "qux"},
                ],
                sandbox,
            )
        self.assertEqual(result["invoke_status"], "completed")
        self.assertEqual(storage["a.py"], "hi world")
        self.assertEqual(storage["b.py"], "foo qux baz")
        self.assertEqual(len(result["_edit_records"]), 2)
        self.assertIn("_diff", result)

    def test_empty_edits_returns_blocked(self) -> None:
        sandbox, _ = self._make_sandbox({})
        result = agent_logic_main.execute_edit_files([], sandbox)
        self.assertEqual(result["invoke_status"], "blocked")
        self.assertIn("edit_files_empty", result.get("error_type", ""))

    def test_missing_path_returns_blocked(self) -> None:
        sandbox, _ = self._make_sandbox({"a.py": "content"})
        result = agent_logic_main.execute_edit_files([{"path": "", "old_text": "x", "new_text": "y"}], sandbox)
        self.assertEqual(result["invoke_status"], "blocked")

    def test_old_text_not_found_returns_blocked(self) -> None:
        sandbox, _ = self._make_sandbox({"a.py": "hello world"})
        result = agent_logic_main.execute_edit_files(
            [{"path": "a.py", "old_text": "NOTFOUND", "new_text": "y"}], sandbox
        )
        self.assertEqual(result["invoke_status"], "blocked")
        self.assertEqual(result.get("error_type"), "edit_old_text_not_found")

    def test_ambiguous_match_returns_blocked(self) -> None:
        sandbox, _ = self._make_sandbox({"a.py": "foo foo foo"})
        result = agent_logic_main.execute_edit_files([{"path": "a.py", "old_text": "foo", "new_text": "bar"}], sandbox)
        self.assertEqual(result["invoke_status"], "blocked")
        self.assertEqual(result.get("error_type"), "edit_ambiguous_match")

    def test_write_failure_triggers_rollback(self) -> None:
        sandbox, storage = self._make_sandbox(
            {"a.py": "hello world", "b.py": "foo bar"},
            fail_write_for="b.py",
        )
        with patch.object(agent_logic_main, "publish_runtime_event", lambda e, d: None):
            result = agent_logic_main.execute_edit_files(
                [
                    {"path": "a.py", "old_text": "hello", "new_text": "hi"},
                    {"path": "b.py", "old_text": "foo", "new_text": "baz"},
                ],
                sandbox,
            )
        self.assertEqual(result["invoke_status"], "blocked")
        self.assertIn("edit_files_write_failed", result.get("error_type", ""))
        # a.py should be rolled back (undo record restoring old content via the write)
        # The rollback writes the undo record's "new_text" which is old_text (original)


class ExecuteSearchCodeTests(unittest.TestCase):
    """Tests for execute_search_code."""

    def _make_local_tool(self, output: str, status: str = "completed"):
        def execute(command: str, args: list[str]) -> dict:
            return {
                "invoke_status": status,
                "messages": [agent_logic_main.AIMessage(content=output)],
            }

        return execute

    def test_matches_parsed(self) -> None:
        output = "src/a.py:10:def hello():\nsrc/b.py:20:import os"
        tool = self._make_local_tool(output)
        result = agent_logic_main.execute_search_code({"pattern": "hello", "path": "src/"}, tool)
        self.assertEqual(result["invoke_status"], "completed")
        matches = result["tool_result"]["results"]
        self.assertEqual(len(matches), 2)
        self.assertEqual(matches[0]["file"], "src/a.py")
        self.assertEqual(matches[0]["line"], "10")

    def test_no_matches(self) -> None:
        tool = self._make_local_tool("")
        result = agent_logic_main.execute_search_code({"pattern": "nonexistent"}, tool)
        self.assertEqual(result["invoke_status"], "completed")
        self.assertEqual(result["tool_result"]["matches"], 0)

    def test_empty_pattern_blocked(self) -> None:
        tool = self._make_local_tool("")
        result = agent_logic_main.execute_search_code({"pattern": ""}, tool)
        self.assertEqual(result["invoke_status"], "blocked")

    def test_max_results_cap(self) -> None:
        lines = "\n".join(f"f.py:{i}:line{i}" for i in range(100))
        tool = self._make_local_tool(lines)
        result = agent_logic_main.execute_search_code({"pattern": "line", "max_results": 5}, tool)
        self.assertLessEqual(len(result["tool_result"]["results"]), 5)


class NormalizeNewActionsTests(unittest.TestCase):
    """Tests for normalize_supervisor_action with edit_files, search_code, parallel_tools."""

    def test_edit_files_normalized(self) -> None:
        raw = {
            "action": "edit_files",
            "edits": [
                {"path": "a.py", "old_text": "old", "new_text": "new"},
                {"path": "b.py", "old_text": "x", "new_text": "y"},
            ],
        }
        result = agent_logic_main.normalize_supervisor_action(raw)
        self.assertIsNotNone(result)
        self.assertEqual(result["action"], "edit_files")
        self.assertEqual(len(result["edits"]), 2)

    def test_edit_files_empty_edits_returns_none(self) -> None:
        raw = {"action": "edit_files", "edits": []}
        result = agent_logic_main.normalize_supervisor_action(raw)
        self.assertIsNone(result)

    def test_edit_files_missing_path_filters_out(self) -> None:
        raw = {
            "action": "edit_files",
            "edits": [{"path": "", "old_text": "x", "new_text": "y"}],
        }
        result = agent_logic_main.normalize_supervisor_action(raw)
        self.assertIsNone(result)  # No valid edits

    def test_search_code_normalized(self) -> None:
        raw = {"action": "search_code", "pattern": "TODO", "path": "src/", "max_results": 10}
        result = agent_logic_main.normalize_supervisor_action(raw)
        self.assertIsNotNone(result)
        self.assertEqual(result["action"], "search_code")
        self.assertEqual(result["pattern"], "TODO")
        self.assertEqual(result.get("path"), "src/")
        self.assertEqual(result.get("max_results"), 10)

    def test_search_code_empty_pattern_returns_none(self) -> None:
        raw = {"action": "search_code", "pattern": ""}
        result = agent_logic_main.normalize_supervisor_action(raw)
        self.assertIsNone(result)

    def test_parallel_tools_normalized(self) -> None:
        raw = {
            "action": "parallel_tools",
            "tool_calls": [
                {"action": "local_shell", "command": "ls", "args": ["-la"]},
                {"action": "search_code", "pattern": "test"},
            ],
        }
        result = agent_logic_main.normalize_supervisor_action(raw)
        self.assertIsNotNone(result)
        self.assertEqual(result["action"], "parallel_tools")
        self.assertEqual(len(result["tool_calls"]), 2)

    def test_parallel_tools_filters_unsafe_actions(self) -> None:
        raw = {
            "action": "parallel_tools",
            "tool_calls": [
                {"action": "edit_file", "path": "f", "old_text": "a", "new_text": "b"},
            ],
        }
        result = agent_logic_main.normalize_supervisor_action(raw)
        # edit_file is NOT in the safe set, so all calls filtered -> None
        self.assertIsNone(result)

    def test_parallel_tools_empty_calls_returns_none(self) -> None:
        raw = {"action": "parallel_tools", "tool_calls": []}
        result = agent_logic_main.normalize_supervisor_action(raw)
        self.assertIsNone(result)


class DescribeNewActionsTests(unittest.TestCase):
    """Tests for describe_autonomous_action with new action types."""

    def test_edit_files_description(self) -> None:
        action = {"action": "edit_files", "edits": [{"path": "a"}, {"path": "b"}]}
        desc = agent_logic_main.describe_autonomous_action(action)
        self.assertIn("2 files", desc)

    def test_search_code_description(self) -> None:
        action = {"action": "search_code", "pattern": "TODO"}
        desc = agent_logic_main.describe_autonomous_action(action)
        self.assertIn("TODO", desc)

    def test_parallel_tools_description(self) -> None:
        action = {"action": "parallel_tools", "tool_calls": [{"action": "local_shell"}] * 3}
        desc = agent_logic_main.describe_autonomous_action(action)
        self.assertIn("3 tools", desc)


class UnifiedDiffTests(unittest.TestCase):
    """Tests for unified diff generation in execute_edit_file."""

    def test_diff_field_present_on_success(self) -> None:
        events: list[tuple[str, dict]] = []

        def mock_sandbox(tool: str, args: dict) -> dict:
            if tool == "filesystem.read":
                return {
                    "invoke_status": "completed",
                    "messages": [agent_logic_main.AIMessage(content="old line here")],
                }
            if tool == "filesystem.write":
                return {
                    "invoke_status": "completed",
                    "messages": [agent_logic_main.AIMessage(content="ok")],
                }
            return {"invoke_status": "blocked", "messages": []}

        with patch.object(
            agent_logic_main,
            "publish_runtime_event",
            lambda e, d: events.append((e, d)),
        ):
            result = agent_logic_main.execute_edit_file(
                "test.py",
                "old line",
                "new line",
                mock_sandbox,
            )

        self.assertEqual(result["invoke_status"], "completed")
        self.assertIn("_diff", result)
        self.assertIn("old line", result["_diff"])
        diff_events = [e for e in events if e[0] == "agent.step.diff"]
        self.assertTrue(len(diff_events) >= 1)


class CostModelCoverageTests(unittest.TestCase):
    """Tests for model cost coverage and edge cases."""

    def test_claude_models(self) -> None:
        # Exact match
        cost = agent_logic_main._calculate_cost_usd(1_000_000, 0, "claude-3.5-sonnet")
        self.assertAlmostEqual(cost, 3.0, places=4)

    def test_gpt4_exact(self) -> None:
        cost = agent_logic_main._calculate_cost_usd(0, 1_000_000, "gpt-4")
        self.assertAlmostEqual(cost, 60.0, places=4)

    def test_case_insensitive_prefix(self) -> None:
        # Prefix match is case-insensitive via model_lower
        cost = agent_logic_main._calculate_cost_usd(1_000_000, 0, "GPT-4o-latest")
        # Should match gpt-4o prefix
        self.assertGreater(cost, 0.0)


class ToolPolicyQuickWinTests(unittest.TestCase):
    def test_parse_tool_policy_config_normalizes_runtime_policy(self) -> None:
        parsed = agent_logic_main.parse_tool_policy_config(
            {
                "toolPolicy": {
                    "maxDelegationDepth": 3,
                    "allowedToolPrefixes": ["local.command.", "github/", "github/"],
                    "blockedToolNames": ["local.command.rm"],
                    "requireApprovalFor": ["github/create_issue"],
                }
            }
        )

        self.assertEqual(parsed["maxDelegationDepth"], 3)
        self.assertEqual(parsed["allowedToolPrefixes"], ("local.command.", "github/"))
        self.assertEqual(parsed["blockedToolNames"], frozenset({"local.command.rm"}))
        self.assertEqual(parsed["requireApprovalFor"], frozenset({"github/create_issue"}))

    def test_tool_policy_violation_reason_blocks_disallowed_tool(self) -> None:
        reason = agent_logic_main.tool_policy_violation_reason(
            tool_name="filesystem.read",
            mcp_server="",
            delegation_depth=0,
            policy_spec={"toolPolicy": {"allowedToolPrefixes": ["local.command."]}},
        )

        self.assertIn("not allowed", reason or "")

    def test_tool_policy_violation_reason_blocks_excessive_delegation_depth(self) -> None:
        reason = agent_logic_main.tool_policy_violation_reason(
            tool_name="",
            mcp_server="",
            delegation_depth=2,
            policy_spec={"toolPolicy": {"maxDelegationDepth": 1}},
        )

        self.assertIn("exceeds", reason or "")

    def test_tool_requires_policy_approval_matches_mcp_qualified_name(self) -> None:
        self.assertTrue(
            agent_logic_main.tool_requires_policy_approval(
                tool_name="create_issue",
                mcp_server="github",
                policy_spec={"toolPolicy": {"requireApprovalFor": ["github/create_issue"]}},
            )
        )

    def test_derive_memory_candidates_includes_artifacts_tools_and_summary(self) -> None:
        memory = agent_logic_main.derive_memory_candidates(
            {
                "artifacts": [{"name": "plan.md"}],
                "tool_call_records": [{"tool_name": "filesystem.read"}],
            },
            "Completed the implementation and wrote the plan.",
        )

        self.assertEqual(memory["episodic"][0]["type"], "artifacts")
        self.assertEqual(memory["episodic"][1]["type"], "tools")
        self.assertEqual(memory["procedural"][0]["type"], "response-summary")


if __name__ == "__main__":
    unittest.main()
