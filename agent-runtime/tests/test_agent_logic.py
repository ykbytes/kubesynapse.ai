import importlib.util
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


fastapi_module = types.ModuleType("fastapi")
fastapi_module.FastAPI = _FakeFastAPI
fastapi_module.HTTPException = _HTTPException
fastapi_module.Request = type("Request", (), {})
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


if __name__ == "__main__":
    unittest.main()