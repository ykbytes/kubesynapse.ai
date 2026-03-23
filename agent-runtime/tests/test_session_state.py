from __future__ import annotations

import importlib.util
import sys
import tempfile
import types
import unittest
from pathlib import Path


MODULE_ROOT = Path(__file__).resolve().parents[1]
if str(MODULE_ROOT) not in sys.path:
    sys.path.insert(0, str(MODULE_ROOT))

SESSION_STATE_PATH = MODULE_ROOT / "memory" / "session_state.py"
SESSION_STORE_PATH = MODULE_ROOT / "memory" / "session_store.py"
AGENT_LOGIC_PATH = MODULE_ROOT / "agent_logic.py"


def _load_module(name: str, file_path: Path):
    spec = importlib.util.spec_from_file_location(name, file_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module from {file_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


session_state = _load_module("memory.session_state", SESSION_STATE_PATH)
session_store = _load_module("memory.session_store", SESSION_STORE_PATH)


class SessionStateSnapshotTests(unittest.TestCase):
    def test_build_snapshot_tracks_budget_and_messages(self) -> None:
        messages = [
            types.SimpleNamespace(content="system note", role="system"),
            types.SimpleNamespace(content="hello", role="user"),
            types.SimpleNamespace(content="world", role="assistant"),
        ]
        state = {
            "thread_id": "thread-123",
            "messages": messages,
            "scratchpad": ["remember this"],
            "token_usage": {"prompt_tokens": 100, "completion_tokens": 40, "total_tokens": 140},
            "tool_name": "filesystem.read",
            "tool_args": {"path": "/tmp/demo.txt"},
            "tool_result": "file contents",
            "selected_model": "local-model",
            "step_count": 2,
            "invoke_status": "completed",
        }

        snapshot = session_state.build_session_state_snapshot(
            state,
            ttl_seconds=60,
            max_token_budget=1000,
            reserved_tokens=200,
            max_messages=2,
            max_tool_results=4,
        )

        self.assertEqual(snapshot.session_id, "thread-123")
        self.assertEqual(snapshot.thread_id, "thread-123")
        self.assertEqual(snapshot.message_count, 2)
        self.assertEqual(snapshot.current_messages[0].content, "hello")
        self.assertEqual(snapshot.current_messages[1].content, "world")
        self.assertEqual(snapshot.tool_results[0].tool_name, "filesystem.read")
        self.assertEqual(snapshot.remaining_token_budget, 660)
        self.assertEqual(snapshot.scratchpad[0].note, "remember this")


class SqliteSessionStoreTests(unittest.TestCase):
    def test_session_store_lifecycle_create_update_resume(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = session_store.SqliteSessionStore(str(Path(temp_dir) / "sessions.sqlite"))
            first = session_state.build_session_state_snapshot(
                {"thread_id": "session-a", "messages": [types.SimpleNamespace(content="one", role="user")]},
                ttl_seconds=300,
            )
            saved = store.save(first)
            loaded = store.get("session-a")

            self.assertIsNotNone(loaded)
            self.assertEqual(saved.created_at, loaded.created_at)
            self.assertEqual(loaded.current_messages[0].content, "one")

            second = session_state.build_session_state_snapshot(
                {
                    "thread_id": "session-a",
                    "messages": [types.SimpleNamespace(content="two", role="assistant")],
                    "token_usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
                },
                ttl_seconds=300,
            )
            store.save(second)
            resumed = store.get("session-a")

            self.assertIsNotNone(resumed)
            self.assertEqual(resumed.created_at, saved.created_at)
            self.assertEqual(resumed.current_messages[0].content, "two")
            self.assertEqual(resumed.token_usage.total_tokens, 15)
            self.assertEqual(len(store.list_active()), 1)

            store.close()

    def test_session_store_delete_expired_and_allow_new_resume(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = session_store.SqliteSessionStore(str(Path(temp_dir) / "sessions.sqlite"))
            expired = session_state.build_session_state_snapshot({"thread_id": "session-b"}, ttl_seconds=0)
            expired.expires_at = session_state.utc_now()
            store.save(expired)

            deleted = store.delete_expired()
            self.assertEqual(deleted, 1)
            self.assertIsNone(store.get("session-b"))

            resumed = session_state.build_session_state_snapshot(
                {"thread_id": "session-b", "messages": [types.SimpleNamespace(content="back", role="user")]},
                ttl_seconds=300,
            )
            store.save(resumed)
            self.assertIsNotNone(store.get("session-b"))
            store.close()


class AgentRuntimeSessionIntegrationTests(unittest.TestCase):
    def test_persist_session_snapshot_uses_store(self) -> None:
        env_utils_module = types.ModuleType("env_utils")
        env_utils_module.get_bool_env = lambda _name, default, **_kwargs: default
        env_utils_module.get_float_env = lambda _name, default, **_kwargs: default
        env_utils_module.get_int_env = lambda _name, default, **_kwargs: default
        sys.modules.setdefault("env_utils", env_utils_module)

        guardrails_module = types.ModuleType("guardrails")
        guardrails_module.GuardrailsEngine = type("GuardrailsEngine", (), {"__init__": lambda self, **_kwargs: None})
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

        fastapi_module = types.ModuleType("fastapi")
        fastapi_module.FastAPI = type("FastAPI", (), {"__init__": lambda self, *args, **kwargs: None, "middleware": lambda self, *args, **kwargs: (lambda f: f), "get": lambda self, *args, **kwargs: (lambda f: f), "post": lambda self, *args, **kwargs: (lambda f: f)})
        fastapi_module.HTTPException = Exception
        fastapi_module.Request = type("Request", (), {})
        sys.modules.setdefault("fastapi", fastapi_module)
        fastapi_responses_module = types.ModuleType("fastapi.responses")
        fastapi_responses_module.StreamingResponse = type("StreamingResponse", (), {})
        sys.modules.setdefault("fastapi.responses", fastapi_responses_module)

        kubernetes_module = types.ModuleType("kubernetes")
        kubernetes_client_module = types.ModuleType("kubernetes.client")
        kubernetes_config_module = types.ModuleType("kubernetes.config")
        kubernetes_module.client = kubernetes_client_module
        kubernetes_module.config = kubernetes_config_module
        sys.modules.setdefault("kubernetes", kubernetes_module)
        sys.modules.setdefault("kubernetes.client", kubernetes_client_module)
        sys.modules.setdefault("kubernetes.config", kubernetes_config_module)

        langchain_messages_module = types.ModuleType("langchain_core.messages")
        langchain_messages_module.AIMessage = type("AIMessage", (), {"__init__": lambda self, content=None, id=None: setattr(self, "content", content)})
        langchain_messages_module.HumanMessage = type("HumanMessage", (), {"__init__": lambda self, content=None, id=None: setattr(self, "content", content)})
        langchain_messages_module.SystemMessage = type("SystemMessage", (), {"__init__": lambda self, content=None, id=None: setattr(self, "content", content)})
        sys.modules.setdefault("langchain_core.messages", langchain_messages_module)

        for module_name in [
            "langchain_openai",
            "langgraph.checkpoint.sqlite",
            "langgraph.graph",
            "langgraph.graph.message",
            "opentelemetry",
            "opentelemetry.trace",
            "opentelemetry.exporter.otlp.proto.grpc.trace_exporter",
            "opentelemetry.sdk.resources",
            "opentelemetry.sdk.trace",
            "opentelemetry.sdk.trace.export",
            "prometheus_fastapi_instrumentator",
            "pythonjsonlogger",
            "pythonjsonlogger.jsonlogger",
        ]:
            sys.modules.setdefault(module_name, types.ModuleType(module_name))

        sys.modules["langchain_openai"].ChatOpenAI = object
        sys.modules["langgraph.checkpoint.sqlite"].SqliteSaver = object
        sys.modules["langgraph.graph"].END = "END"
        sys.modules["langgraph.graph"].START = "START"
        sys.modules["langgraph.graph"].StateGraph = object
        sys.modules["langgraph.graph.message"].add_messages = lambda value: value
        sys.modules["opentelemetry"].trace = types.SimpleNamespace(
            get_tracer=lambda *_args, **_kwargs: None,
            set_tracer_provider=lambda *_args, **_kwargs: None,
        )
        sys.modules["opentelemetry.exporter.otlp.proto.grpc.trace_exporter"].OTLPSpanExporter = type(
            "OTLPSpanExporter",
            (),
            {"__init__": lambda self, *args, **kwargs: None},
        )
        sys.modules["opentelemetry.sdk.resources"].Resource = type(
            "Resource",
            (),
            {"__init__": lambda self, *args, **kwargs: None},
        )
        sys.modules["opentelemetry.sdk.trace"].TracerProvider = type(
            "TracerProvider",
            (),
            {
                "__init__": lambda self, *args, **kwargs: None,
                "add_span_processor": lambda self, *args, **kwargs: None,
            },
        )
        sys.modules["opentelemetry.sdk.trace.export"].BatchSpanProcessor = type(
            "BatchSpanProcessor",
            (),
            {"__init__": lambda self, *args, **kwargs: None},
        )
        sys.modules["prometheus_fastapi_instrumentator"].Instrumentator = type(
            "Instrumentator",
            (),
            {
                "__init__": lambda self, *args, **kwargs: None,
                "instrument": lambda self, *args, **kwargs: self,
                "expose": lambda self, *args, **kwargs: self,
            },
        )
        sys.modules["pythonjsonlogger.jsonlogger"].JsonFormatter = type(
            "JsonFormatter",
            (),
            {"__init__": lambda self, *args, **kwargs: None},
        )

        agent_logic = _load_module("agent_logic_session_test", AGENT_LOGIC_PATH)
        store = session_store.InMemorySessionStore()

        saved = agent_logic.persist_session_snapshot(
            {"thread_id": "thread-persist", "messages": [types.SimpleNamespace(content="hello", role="user")]},
            session_store=store,
        )

        self.assertIsNotNone(saved)
        self.assertEqual(saved.session_id, "thread-persist")
        self.assertIsNotNone(store.get("thread-persist"))


if __name__ == "__main__":
    unittest.main()