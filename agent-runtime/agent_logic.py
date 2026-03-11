import asyncio
import contextlib
from contextvars import ContextVar
import json
import logging
import os
import sqlite3
import threading
import time
import uuid
from datetime import datetime, timezone
from collections.abc import AsyncIterator, Callable, Iterator
from typing import Annotated, Any, TypedDict

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
from kubernetes import client as k8s_client  # type: ignore[import-untyped]
from kubernetes import config as k8s_config  # type: ignore[import-untyped]
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from pydantic import BaseModel, Field, SecretStr, model_validator
from prometheus_fastapi_instrumentator import Instrumentator
from pythonjsonlogger import jsonlogger

from env_utils import get_bool_env, get_float_env, get_int_env
from guardrails import GuardrailsEngine
from hitl import hitl_gate
from opensandbox_tools import (
    SandboxToolError,
    execute_sandbox_tool,
    format_tool_payload,
    is_sandbox_tool,
    sandbox_runtime_metadata,
)


def configure_logging() -> None:
    log_level = os.getenv("AGENT_LOG_LEVEL", "INFO").upper()
    handler = logging.StreamHandler()
    if get_bool_env("AGENT_JSON_LOGS", True):
        handler.setFormatter(jsonlogger.JsonFormatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    else:
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    logging.basicConfig(level=log_level, handlers=[handler], force=True)


configure_logging()
logger = logging.getLogger("agent-runtime")


SERVICE_NAME = os.getenv("AGENT_NAME", "agent-runtime")
SERVICE_NAMESPACE = os.getenv("AGENT_NAMESPACE", "default")
MODEL_NAME = os.getenv("AGENT_MODEL", "gpt-4")
LITELLM_BASE = os.getenv("LITELLM_API_BASE", "http://ai-agent-sandbox-litellm:4000")
LITELLM_API_KEY = os.getenv("LITELLM_API_KEY", "")
LITELLM_PLACEHOLDER_API_KEY = os.getenv("LITELLM_PLACEHOLDER_API_KEY", "local-litelm-placeholder")
SYSTEM_PROMPT = os.getenv("AGENT_SYSTEM_PROMPT", "").strip()
RAG_ENABLED = get_bool_env("RAG_ENABLED", True)
QDRANT_URL = os.getenv("QDRANT_URL", "http://ai-agent-sandbox-qdrant:6333")
QDRANT_COLLECTION = os.getenv("QDRANT_COLLECTION", "").strip()
EMBEDDING_MODEL = os.getenv("AGENT_EMBEDDING_MODEL", "text-embedding-3-small")
RAG_TOP_K = get_int_env("RAG_TOP_K", 3, minimum=1)
POLICY_CACHE_TTL_SECONDS = get_int_env("AGENT_POLICY_CACHE_TTL_SECONDS", 30, minimum=0)
MAX_PROMPT_CHARS = get_int_env("AGENT_MAX_PROMPT_CHARS", 12000, minimum=1)
MAX_CONTEXT_CHARS = get_int_env("AGENT_MAX_CONTEXT_CHARS", 6000, minimum=512)
MAX_THREAD_ID_CHARS = get_int_env("AGENT_MAX_THREAD_ID_CHARS", 128, minimum=16)
# MCP security: bearer token presented on every outbound MCP HTTP call and
# the allow-list of server types the agent is permitted to invoke.  Both are
# injected by the operator from the mcp-auth Secret and AgentPolicy.
MCP_BEARER_TOKEN = os.getenv("MCP_BEARER_TOKEN", "").strip()
MCP_HUB_NAMESPACE = os.getenv("MCP_HUB_NAMESPACE", "mcp-hub").strip()
_raw_allowed = os.getenv("ALLOWED_MCP_SERVERS", "").strip()
ALLOWED_MCP_SERVERS: frozenset[str] = frozenset(s.strip() for s in _raw_allowed.split(",") if s.strip())
MAX_TOOL_ARGS_BYTES = get_int_env("AGENT_MAX_TOOL_ARGS_BYTES", 16384, minimum=512)
MAX_CONCURRENT_REQUESTS = get_int_env("AGENT_MAX_CONCURRENT_REQUESTS", 4, minimum=1)
REQUEST_QUEUE_TIMEOUT_SECONDS = get_float_env("AGENT_REQUEST_QUEUE_TIMEOUT_SECONDS", 5.0, minimum=0.1)
STREAM_EVENT_QUEUE_SIZE = get_int_env("AGENT_STREAM_EVENT_QUEUE_SIZE", 256, minimum=32)
LITELLM_TIMEOUT_SECONDS = get_float_env("AGENT_LITELLM_TIMEOUT_SECONDS", 60.0, minimum=1.0)
EMBEDDING_TIMEOUT_SECONDS = get_float_env("AGENT_EMBEDDING_TIMEOUT_SECONDS", 30.0, minimum=1.0)
RAG_REQUEST_TIMEOUT_SECONDS = get_float_env("AGENT_RAG_TIMEOUT_SECONDS", 10.0, minimum=1.0)
SQLITE_TIMEOUT_SECONDS = get_float_env("AGENT_SQLITE_TIMEOUT_SECONDS", 30.0, minimum=1.0)
BLOCKED_RESPONSE_PREFIX = "Request blocked"
SENSITIVE_STREAM_EVENT_SUFFIXES = (".stdout", ".stderr", ".result")

resource = Resource(attributes={
    "service.name": SERVICE_NAME,
    "service.namespace": SERVICE_NAMESPACE,
})
trace_provider = TracerProvider(resource=resource)
trace.set_tracer_provider(trace_provider)
otlp_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip()
if otlp_endpoint:
    trace_provider.add_span_processor(
        BatchSpanProcessor(
            OTLPSpanExporter(
                endpoint=otlp_endpoint,
                insecure=otlp_endpoint.startswith("http://"),
            )
        )
    )
tracer = trace.get_tracer(__name__)


@contextlib.asynccontextmanager
async def lifespan(_app: FastAPI):
    await asyncio.to_thread(initialize_runtime)
    try:
        yield
    finally:
        _SHUTDOWN.set()
        await asyncio.to_thread(shutdown_runtime)

app = FastAPI(
    title="AI Agent Runtime",
    description="LangGraph-powered runtime for a single sandboxed AI agent",
    version="1.0.0",
    lifespan=lifespan,
)
Instrumentator().instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)

RUNTIME: dict[str, Any] = {}
RUNTIME_LOCK = threading.Lock()
DISCOVERED_QDRANT_COLLECTION = QDRANT_COLLECTION or None
DISCOVERED_QDRANT_LOCK = threading.Lock()
INVOCATION_SLOTS = threading.BoundedSemaphore(MAX_CONCURRENT_REQUESTS)
POLICY_CACHE: dict[str, Any] = {"timestamp": 0.0, "name": None, "spec": {}}
K8S_POLICY_ACCESS = False
_SHUTDOWN = threading.Event()
EVENT_PUBLISHER: ContextVar[Callable[[str, dict[str, Any]], None] | None] = ContextVar(
    "event_publisher",
    default=None,
)
REQUEST_ID: ContextVar[str | None] = ContextVar("request_id", default=None)


@app.middleware("http")
async def bind_request_context(request: Request, call_next):
    request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
    token = REQUEST_ID.set(request_id)
    try:
        response = await call_next(request)
    finally:
        REQUEST_ID.reset(token)
    response.headers["x-request-id"] = request_id
    return response


class State(TypedDict, total=False):
    messages: Annotated[list[Any], add_messages]
    request_prompt: str
    context: str
    invoke_status: str
    policy_name: str
    policy: dict[str, Any]
    system_prompt: str
    tool_name: str
    tool_args: dict[str, Any]
    tool_result: dict[str, Any] | None
    sandbox_session: dict[str, Any] | None
    # MCP tool invocation fields – populated by invoke_graph when the caller
    # sets mcp_server on InvokeRequest.  The mcp_tool graph node reads these.
    mcp_server: str
    mcp_tool_name: str
    mcp_tool_args: dict[str, Any]


class InvokeRequest(BaseModel):
    prompt: str = Field(default="", max_length=MAX_PROMPT_CHARS)
    thread_id: str | None = Field(default=None, max_length=MAX_THREAD_ID_CHARS)
    model: str | None = Field(default=None, max_length=128)
    require_approval: bool = False
    approval_action: str | None = Field(default=None, max_length=512)
    tool_name: str = Field(default="", max_length=128)
    tool_args: dict[str, Any] = Field(default_factory=dict)
    sandbox_session: dict[str, Any] | None = None
    mcp_server: str | None = Field(
        default=None,
        max_length=128,
        description=(
            "MCP server type to call (e.g. 'github', 'prometheus'). "
            "When set, the request is routed to the mcp_tool graph node "
            "instead of the normal chat/RAG path."
        ),
    )

    @model_validator(mode="after")
    def validate_payload_size(self) -> "InvokeRequest":
        self.prompt = self.prompt.strip()
        self.thread_id = self.thread_id.strip() or None if self.thread_id is not None else None
        self.model = self.model.strip() or None if self.model is not None else None
        self.approval_action = self.approval_action.strip() or None if self.approval_action is not None else None
        self.tool_name = self.tool_name.strip()
        self.mcp_server = self.mcp_server.strip() or None if self.mcp_server is not None else None

        prompt = self.prompt
        tool_name = self.tool_name
        mcp_server = self.mcp_server or ""

        if not prompt and not tool_name:
            raise ValueError("prompt must not be blank unless tool_name is provided")

        if mcp_server and not tool_name:
            raise ValueError("tool_name is required when mcp_server is provided")

        if mcp_server and is_sandbox_tool(tool_name):
            raise ValueError("sandbox tools cannot be invoked through mcp_server")

        if not prompt and tool_name and not mcp_server and not is_sandbox_tool(tool_name):
            raise ValueError(f"Unsupported tool_name '{tool_name}'")

        encoded_args = json.dumps(self.tool_args, default=str)
        if len(encoded_args.encode("utf-8")) > MAX_TOOL_ARGS_BYTES:
            raise ValueError(f"tool_args exceeds {MAX_TOOL_ARGS_BYTES} bytes")

        if self.sandbox_session is not None:
            json.dumps(self.sandbox_session, default=str)

        return self


class InvokeResponse(BaseModel):
    thread_id: str
    response: str
    context: str = ""
    model: str
    policy_name: str | None = None
    tool_name: str | None = None
    tool_result: dict[str, Any] | None = None
    sandbox_session: dict[str, Any] | None = None
    status: str = "completed"
    approval_name: str | None = None
    retry_after_seconds: int | None = None
    warnings: list[str] = Field(default_factory=list)


def configure_kubernetes_access() -> None:
    global K8S_POLICY_ACCESS
    try:
        try:
            k8s_config.load_incluster_config()
            logger.info("Loaded in-cluster Kubernetes config for runtime policy lookups.")
        except Exception:
            k8s_config.load_kube_config()
            logger.info("Loaded local kubeconfig for runtime policy lookups.")
        K8S_POLICY_ACCESS = True
    except Exception as exc:
        K8S_POLICY_ACCESS = False
        logger.warning("Kubernetes policy lookups unavailable: %s", exc)


def get_message_content(message: Any) -> str:
    if message is None:
        return ""
    content = getattr(message, "content", message)
    if isinstance(content, list):
        parts = [extract_content_part(item) for item in content]
        return " ".join(part for part in parts if part).strip()
    return str(content)


def extract_content_part(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in ("text", "content", "value"):
            text_value = value.get(key)
            if isinstance(text_value, str) and text_value.strip():
                return text_value
    return str(value)


def current_event_publisher() -> Callable[[str, dict[str, Any]], None] | None:
    return EVENT_PUBLISHER.get()


def publish_runtime_event(event: str, payload: dict[str, Any]) -> None:
    publisher = current_event_publisher()
    if publisher is not None:
        event_payload = dict(payload)
        request_id = REQUEST_ID.get()
        if request_id and "request_id" not in event_payload:
            event_payload["request_id"] = request_id
        publisher(event, event_payload)


@contextlib.contextmanager
def bind_event_publisher(
    publish_event: Callable[[str, dict[str, Any]], None] | None,
) -> Iterator[None]:
    token = EVENT_PUBLISHER.set(publish_event)
    try:
        yield
    finally:
        EVENT_PUBLISHER.reset(token)


def emit_node_event(node_name: str, status: str, **payload: Any) -> None:
    event_payload = {"node": node_name, "status": status}
    event_payload.update({key: value for key, value in payload.items() if value is not None})
    publish_runtime_event("graph.node", event_payload)


def run_graph_node(node_name: str, operation: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    emit_node_event(node_name, "started")
    try:
        result = operation()
    except Exception as exc:
        emit_node_event(node_name, "failed", error=str(exc))
        raise

    emit_node_event(node_name, "completed", invoke_status=result.get("invoke_status"))
    return result


def blocked_response(reason: str) -> str:
    return f"{BLOCKED_RESPONSE_PREFIX}: {reason}"


def is_blocked_response(text: str) -> bool:
    return text.startswith(BLOCKED_RESPONSE_PREFIX)


def build_request_guard_text(
    prompt: str,
    tool_name: str,
    tool_args: dict[str, Any],
    mcp_server: str,
) -> str:
    sections: list[str] = []
    if prompt.strip():
        sections.append(prompt.strip())

    if tool_name.strip():
        tool_payload: dict[str, Any] = {
            "tool_name": tool_name.strip(),
            "tool_args": tool_args,
        }
        if mcp_server.strip():
            tool_payload["mcp_server"] = mcp_server.strip()
        sections.append(json.dumps(tool_payload, ensure_ascii=False, sort_keys=True, default=str))

    return "\n\n".join(section for section in sections if section)


def sanitize_public_payload(value: Any, guardrails: GuardrailsEngine) -> Any:
    if isinstance(value, str):
        return guardrails.sanitize_output(value)
    if isinstance(value, list):
        return [sanitize_public_payload(item, guardrails) for item in value]
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key, item in value.items():
            if key == "headers" and isinstance(item, dict):
                sanitized[key] = {"redacted": True, "count": len(item)}
                continue
            sanitized[key] = sanitize_public_payload(item, guardrails)
        return sanitized
    return value


def get_litellm_headers() -> dict[str, str]:
    if not LITELLM_API_KEY:
        return {}
    return {"Authorization": f"Bearer {LITELLM_API_KEY}"}


def discover_qdrant_collection(client: httpx.Client) -> str:
    global DISCOVERED_QDRANT_COLLECTION

    if DISCOVERED_QDRANT_COLLECTION:
        return DISCOVERED_QDRANT_COLLECTION

    try:
        response = client.get(f"{QDRANT_URL}/collections", timeout=RAG_REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
        collections = response.json().get("result", {}).get("collections", [])
        if collections:
            collection_name = str(collections[0].get("name", "")).strip()
            if collection_name:
                with DISCOVERED_QDRANT_LOCK:
                    DISCOVERED_QDRANT_COLLECTION = collection_name
                return collection_name
    except Exception as exc:
        logger.warning("Failed to discover Qdrant collections: %s", exc)
    return ""


def embed_query(query: str) -> list[float]:
    with httpx.Client(
        headers=get_litellm_headers(),
        timeout=EMBEDDING_TIMEOUT_SECONDS,
        transport=httpx.HTTPTransport(retries=2),
        trust_env=False,
    ) as client:
        response = client.post(
            f"{LITELLM_BASE}/embeddings",
            json={"model": EMBEDDING_MODEL, "input": query},
        )
        response.raise_for_status()
        data = response.json().get("data", [])
        if not data:
            raise ValueError("LiteLLM embedding response contained no vectors")
        embedding = data[0].get("embedding")
        if not isinstance(embedding, list):
            raise ValueError("LiteLLM embedding response was malformed")
        return embedding


def extract_payload_text(payload: Any) -> str:
    if not isinstance(payload, dict):
        return ""

    for key in ("text", "content", "chunk", "document", "page_content", "body"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def retrieve_context(query: str) -> str:
    if not query.strip() or not RAG_ENABLED:
        return ""

    try:
        with httpx.Client(
            timeout=RAG_REQUEST_TIMEOUT_SECONDS,
            transport=httpx.HTTPTransport(retries=2),
            trust_env=False,
        ) as client:
            collection = discover_qdrant_collection(client)
            if not collection:
                logger.info("Skipping RAG retrieval because no Qdrant collection is configured.")
                return ""

            embedding = embed_query(query)
            search_response = client.post(
                f"{QDRANT_URL}/collections/{collection}/points/search",
                json={"vector": embedding, "limit": RAG_TOP_K, "with_payload": True},
            )

            if search_response.status_code == 404:
                search_response = client.post(
                    f"{QDRANT_URL}/collections/{collection}/points/query",
                    json={"query": embedding, "limit": RAG_TOP_K, "with_payload": True},
                )

            search_response.raise_for_status()
            result = search_response.json().get("result", [])
            if isinstance(result, dict):
                result = result.get("points", [])

            snippets: list[str] = []
            seen_snippets: set[str] = set()
            total_chars = 0
            for match in result:
                payload = match.get("payload", {})
                snippet = extract_payload_text(payload)
                if not snippet or snippet in seen_snippets:
                    continue

                remaining = MAX_CONTEXT_CHARS - total_chars
                if remaining <= 0:
                    break

                clipped = snippet[:remaining]
                snippets.append(clipped)
                seen_snippets.add(snippet)
                total_chars += len(clipped) + 2

            return "\n\n".join(snippets)
    except Exception as exc:
        logger.warning("Qdrant retrieval failed, continuing without RAG context: %s", exc)
        return ""


def load_active_policy(force_refresh: bool = False) -> tuple[str | None, dict[str, Any]]:
    now = time.time()
    if not force_refresh and now - POLICY_CACHE["timestamp"] < POLICY_CACHE_TTL_SECONDS:
        return POLICY_CACHE["name"], POLICY_CACHE["spec"]

    if not K8S_POLICY_ACCESS:
        POLICY_CACHE.update({"timestamp": now, "name": None, "spec": {}})
        return None, {}

    policy_name = os.getenv("AGENT_POLICY_NAME", "").strip()
    custom_api = k8s_client.CustomObjectsApi()
    try:
        if policy_name:
            policy = custom_api.get_namespaced_custom_object(
                group="sandbox.enterprise.ai",
                version="v1alpha1",
                namespace=SERVICE_NAMESPACE,
                plural="agentpolicies",
                name=policy_name,
            )
        else:
            policies = custom_api.list_namespaced_custom_object(
                group="sandbox.enterprise.ai",
                version="v1alpha1",
                namespace=SERVICE_NAMESPACE,
                plural="agentpolicies",
            ).get("items", [])
            policies.sort(key=lambda item: item.get("metadata", {}).get("name", ""))
            policy = policies[0] if policies else None

        cached_name = None
        cached_spec: dict[str, Any] = {}
        if policy:
            cached_name = policy.get("metadata", {}).get("name")
            cached_spec = policy.get("spec", {})
            logger.info("Loaded active AgentPolicy '%s'", cached_name)

        POLICY_CACHE.update({"timestamp": now, "name": cached_name, "spec": cached_spec})
        return cached_name, cached_spec
    except Exception as exc:
        logger.warning("Failed to load AgentPolicy, using built-in defaults: %s", exc)
        POLICY_CACHE.update({"timestamp": now, "name": None, "spec": {}})
        return None, {}


def build_guardrails(policy_spec: dict[str, Any]) -> GuardrailsEngine:
    input_cfg = policy_spec.get("inputGuardrails", {})
    output_cfg = policy_spec.get("outputGuardrails", {})
    return GuardrailsEngine(
        block_prompt_injection=input_cfg.get("blockPromptInjection", True),
        mask_pii=output_cfg.get("maskPII", True),
        blocked_input_patterns=input_cfg.get("blockedPatterns", []),
        blocked_output_patterns=output_cfg.get("blockedOutputPatterns", []),
        max_input_tokens=input_cfg.get("maxInputTokens", 4096),
        max_output_tokens=output_cfg.get("maxOutputTokens", 4096),
    )


def route_state(state: State) -> str:
    """Route after input_guard: blocked → END, sandbox → sandbox_tool, MCP → mcp_tool, chat → rag_retrieve."""
    status = state.get("invoke_status", "continue")
    if status == "blocked":
        return "blocked"
    if is_sandbox_tool(state.get("tool_name")):
        return "sandbox_tool"
    if state.get("mcp_server"):
        return "mcp_tool"
    return "continue"


def mcp_call(
    server_type: str,
    tool_name: str,
    tool_args: dict[str, Any],
    *,
    timeout: float = 30.0,
) -> dict[str, Any]:
    """Call a tool on an MCP server with bearer-token auth.

    Security enforcements (both layers must pass):
      1. Runtime allow-list: ``server_type`` must be in ALLOWED_MCP_SERVERS
         (set from the AgentPolicy via the ALLOWED_MCP_SERVERS env var).
         This is a defence-in-depth guard on top of the K8s NetworkPolicy.
      2. Bearer token: every outbound request carries the shared bearer token
         injected from the mcp-auth Secret by the operator.

    MCP tool calls are NOT made directly here – they always flow through
    ``preflight_request_approval()`` → ``hitl_gate()`` in ``invoke_graph()``
    before this function is reached.

    Args:
        server_type: The ``mcp.sandbox.enterprise.ai/type`` label value
            (e.g. "weather", "github", "prometheus").
        tool_name:   Name of the MCP tool to invoke.
        tool_args:   Arguments dict forwarded as JSON body.
        timeout:     HTTP request timeout in seconds.

    Returns:
        The JSON response body from the MCP server.

    Raises:
        PermissionError: If server_type is not in the allow-list.
        httpx.HTTPStatusError: On non-2xx MCP responses.
    """
    if ALLOWED_MCP_SERVERS and server_type not in ALLOWED_MCP_SERVERS:
        raise PermissionError(
            f"MCP server type '{server_type}' is not in the agent's allowed list "
            f"({', '.join(sorted(ALLOWED_MCP_SERVERS))}). "
            "Update AgentPolicy.spec.allowedMcpServers to grant access."
        )

    # Build URL: MCP servers are in the mcp-hub namespace using internal K8s DNS.
    # Pattern: http://<release-fullname>-mcp-<type>.<mcp-hub-ns>.svc.cluster.local:8000
    release_name = os.getenv("HELM_RELEASE_NAME", "ai-agent-sandbox")
    svc = f"{release_name}-mcp-{server_type}.{MCP_HUB_NAMESPACE}.svc.cluster.local"
    url = f"http://{svc}:8000/tools/{tool_name}"

    headers: dict[str, str] = {"Content-Type": "application/json"}
    if not MCP_BEARER_TOKEN:
        raise PermissionError(
            f"MCP_BEARER_TOKEN is not configured; refusing to call MCP server '{server_type}'. "
            "Ensure the MCP auth secret is mounted into the agent runtime."
        )
    headers["Authorization"] = f"Bearer {MCP_BEARER_TOKEN}"

    with httpx.Client(
        timeout=timeout,
        transport=httpx.HTTPTransport(retries=2),
        trust_env=False,
    ) as client:
        response = client.post(url, json=tool_args, headers=headers)
        response.raise_for_status()
        return response.json()  # type: ignore[no-any-return]


def create_agent(llm: ChatOpenAI):
    def input_guard(state: State) -> dict[str, Any]:
        def _run() -> dict[str, Any]:
            with tracer.start_as_current_span("guardrails_input_validation"):
                prompt = state.get("request_prompt", "")
                guard_input = build_request_guard_text(
                    prompt,
                    state.get("tool_name", ""),
                    state.get("tool_args") or {},
                    state.get("mcp_server", ""),
                )
                if not guard_input.strip():
                    return {"context": "", "invoke_status": "continue"}

                guardrails = build_guardrails(state.get("policy", {}))
                is_safe, reason = guardrails.validate_input(guard_input)
                if not is_safe:
                    logger.warning("Input blocked: %s", reason)
                    return {
                        "messages": [AIMessage(content=blocked_response(f"safety policy violation: {reason}"))],
                        "context": "",
                        "invoke_status": "blocked",
                    }
                return {"context": "", "invoke_status": "continue"}

        return run_graph_node("input_guard", _run)

    def rag_retrieve(state: State) -> dict[str, Any]:
        def _run() -> dict[str, Any]:
            with tracer.start_as_current_span("rag_retrieval"):
                prompt = state.get("request_prompt", "")
                if not prompt.strip():
                    return {"context": ""}

                context = retrieve_context(prompt)
                publish_runtime_event(
                    "rag.context",
                    {"chars": len(context), "present": bool(context)},
                )
                return {"context": context}

        return run_graph_node("rag_retrieve", _run)

    def chatbot(state: State) -> dict[str, Any]:
        def _run() -> dict[str, Any]:
            with tracer.start_as_current_span("agent_llm_invocation") as span:
                messages: list[Any] = []
                system_prompt = state.get("system_prompt", "").strip()
                if system_prompt:
                    messages.append(SystemMessage(content=system_prompt))

                context = state.get("context", "")
                if context:
                    messages.append(
                        SystemMessage(content=f"Use the following retrieved context when answering:\n{context}")
                    )

                messages.extend(state.get("messages", []))
                publisher = current_event_publisher()
                response: AIMessage | Any
                if publisher is None:
                    response = llm.invoke(messages)
                else:
                    text_fragments: list[str] = []
                    streamed = False
                    try:
                        for chunk in llm.stream(messages):
                            streamed = True
                            delta = get_message_content(chunk)
                            if delta:
                                text_fragments.append(delta)
                                publish_runtime_event(
                                    "response.delta",
                                    {"delta": delta, "source": "llm"},
                                )
                    except Exception:
                        if streamed:
                            raise
                        logger.warning(
                            "LLM streaming setup failed, falling back to non-streaming invoke.",
                            exc_info=True,
                        )
                        response = llm.invoke(messages)
                    else:
                        response = AIMessage(content="".join(text_fragments))

                span.set_attribute("model", MODEL_NAME)
                span.set_attribute("rag.context_present", bool(context))
                span.set_attribute("llm.streaming", publisher is not None)
                return {"messages": [response], "invoke_status": "completed"}

        return run_graph_node("chatbot", _run)

    def output_guard(state: State) -> dict[str, Any]:
        def _run() -> dict[str, Any]:
            with tracer.start_as_current_span("guardrails_output_sanitization"):
                last_message = state["messages"][-1] if state.get("messages") else None
                content = get_message_content(last_message)
                guardrails = build_guardrails(state.get("policy", {}))
                sanitized = guardrails.sanitize_output(content)
                if sanitized != content:
                    logger.info("Output was sanitized by guardrails")
                    msg_id = getattr(last_message, "id", None)
                    return {"messages": [AIMessage(content=sanitized, id=msg_id)]}
                return {}

        return run_graph_node("output_guard", _run)

    def sandbox_tool(state: State) -> dict[str, Any]:
        def _run() -> dict[str, Any]:
            with tracer.start_as_current_span("sandbox_tool_invocation") as span:
                tool_nm = (state.get("tool_name") or "").strip()
                tool_arguments = state.get("tool_args") or {}
                current_session = state.get("sandbox_session")

                if not is_sandbox_tool(tool_nm):
                    return {
                        "messages": [AIMessage(content=blocked_response("Unsupported sandbox tool invocation"))],
                        "invoke_status": "blocked",
                        "tool_result": None,
                    }

                publish_runtime_event("sandbox.runtime", sandbox_runtime_metadata())

                try:
                    result, next_session = asyncio.run(
                        execute_sandbox_tool(
                            tool_nm,
                            tool_arguments,
                            current_session,
                            publish_runtime_event,
                        )
                    )
                except SandboxToolError as exc:
                    logger.warning("Sandbox tool invocation blocked: %s", exc)
                    return {
                        "messages": [AIMessage(content=blocked_response(str(exc)))],
                        "invoke_status": "blocked",
                        "tool_result": None,
                    }
                except Exception as exc:
                    logger.exception("Sandbox tool invocation failed for %s", tool_nm)
                    return {
                        "messages": [AIMessage(content=blocked_response(f"Sandbox tool failed: {exc}"))],
                        "invoke_status": "blocked",
                        "tool_result": None,
                    }

                result_text = format_tool_payload(result)
                span.set_attribute("sandbox.tool_name", tool_nm)
                if next_session and next_session.get("sandbox_id"):
                    span.set_attribute("sandbox.id", str(next_session["sandbox_id"]))
                return {
                    "messages": [AIMessage(content=result_text)],
                    "invoke_status": "completed",
                    "tool_result": result,
                    "sandbox_session": next_session,
                }

        return run_graph_node("sandbox_tool", _run)

    def mcp_tool(state: State) -> dict[str, Any]:
        """Call a tool on an MCP server and return the result as an AIMessage."""

        def _run() -> dict[str, Any]:
            with tracer.start_as_current_span("mcp_tool_invocation") as span:
                server_type = (state.get("mcp_server") or "").strip()
                tool_nm = (state.get("mcp_tool_name") or "").strip()
                tool_arguments: dict[str, Any] = state.get("mcp_tool_args") or {}

                if not server_type or not tool_nm:
                    return {
                        "messages": [AIMessage(content=blocked_response(
                            "mcp_server and tool_name are required for MCP calls"
                        ))],
                        "invoke_status": "blocked",
                        "tool_result": None,
                    }

                try:
                    result = mcp_call(server_type, tool_nm, tool_arguments)
                    result_text = format_tool_payload(result)
                    span.set_attribute("mcp.server_type", server_type)
                    span.set_attribute("mcp.tool_name", tool_nm)
                    logger.info(
                        "MCP tool '%s/%s' returned %d bytes",
                        server_type, tool_nm, len(result_text),
                    )
                    publish_runtime_event(
                        "mcp.result",
                        {"serverType": server_type, "toolName": tool_nm, "bytes": len(result_text)},
                    )
                    return {
                        "messages": [AIMessage(content=result_text)],
                        "invoke_status": "completed",
                        "tool_result": result,
                    }
                except PermissionError as exc:
                    logger.warning("MCP call blocked by policy allow-list: %s", exc)
                    return {
                        "messages": [AIMessage(content=blocked_response(str(exc)))],
                        "invoke_status": "blocked",
                        "tool_result": None,
                    }
                except httpx.HTTPStatusError as exc:
                    logger.error(
                        "MCP server '%s' returned HTTP %s",
                        server_type, exc.response.status_code,
                    )
                    return {
                        "messages": [AIMessage(content=blocked_response(
                            f"MCP server error: {exc.response.status_code}"
                        ))],
                        "invoke_status": "blocked",
                        "tool_result": None,
                    }
                except Exception as exc:
                    logger.exception("MCP tool invocation failed for %s/%s", server_type, tool_nm)
                    return {
                        "messages": [AIMessage(content=blocked_response(f"MCP call failed: {exc}"))],
                        "invoke_status": "blocked",
                        "tool_result": None,
                    }

        return run_graph_node("mcp_tool", _run)

    graph_builder = StateGraph(State)
    graph_builder.add_node("input_guard", input_guard)
    graph_builder.add_node("rag_retrieve", rag_retrieve)
    graph_builder.add_node("chatbot", chatbot)
    graph_builder.add_node("sandbox_tool", sandbox_tool)
    graph_builder.add_node("mcp_tool", mcp_tool)
    graph_builder.add_node("output_guard", output_guard)

    graph_builder.add_edge(START, "input_guard")
    graph_builder.add_conditional_edges(
        "input_guard",
        route_state,
        {
            "continue": "rag_retrieve",
            "blocked": END,
            "sandbox_tool": "sandbox_tool",
            "mcp_tool": "mcp_tool",
        },
    )
    graph_builder.add_edge("rag_retrieve", "chatbot")
    graph_builder.add_edge("chatbot", "output_guard")
    graph_builder.add_edge("sandbox_tool", "output_guard")
    graph_builder.add_edge("mcp_tool", "output_guard")
    graph_builder.add_edge("output_guard", END)
    return graph_builder


def initialize_runtime() -> None:
    if RUNTIME:
        return

    with RUNTIME_LOCK:
        if RUNTIME:
            return

        configure_kubernetes_access()
        logger.info("Initializing agent runtime for %s in namespace %s.", SERVICE_NAME, SERVICE_NAMESPACE)

        litellm_api_key = LITELLM_API_KEY or LITELLM_PLACEHOLDER_API_KEY
        if not LITELLM_API_KEY:
            logger.warning(
                "LITELLM_API_KEY is not set; using a placeholder client key for base URL %s.",
                LITELLM_BASE,
            )

        llm = ChatOpenAI(
            model=MODEL_NAME,
            base_url=LITELLM_BASE,
            api_key=SecretStr(litellm_api_key),
            timeout=LITELLM_TIMEOUT_SECONDS,
            max_retries=2,
        )

        db_path = "/app/state/checkpoints.sqlite"
        os.makedirs(os.path.dirname(db_path), exist_ok=True)

        connection: sqlite3.Connection | None = None
        try:
            connection = sqlite3.connect(
                db_path,
                check_same_thread=False,
                timeout=SQLITE_TIMEOUT_SECONDS,
            )
            connection.execute("PRAGMA journal_mode=WAL;")
            connection.execute("PRAGMA synchronous=NORMAL;")
            memory = SqliteSaver(connection)
            memory.setup()
            graph = create_agent(llm).compile(checkpointer=memory)
        except Exception:
            if connection is not None:
                connection.close()
            raise

        RUNTIME.update({"llm": llm, "graph": graph, "connection": connection, "memory": memory})
        logger.info("Agent runtime initialized successfully.")


def shutdown_runtime() -> None:
    with RUNTIME_LOCK:
        connection = RUNTIME.get("connection")
        if connection is not None:
            try:
                connection.close()
            except sqlite3.Error as exc:
                logger.warning("Failed to close runtime checkpoint database cleanly: %s", exc)
        RUNTIME.clear()


def get_runtime() -> dict[str, Any]:
    if not RUNTIME:
        initialize_runtime()
    return RUNTIME


def preflight_request_approval(
    request: InvokeRequest,
    thread_id: str,
    policy_name: str | None,
) -> InvokeResponse | None:
    default_action = request.approval_action or (
        f"Invoke tool {request.tool_name} on agent {SERVICE_NAME}"
        if request.tool_name
        else f"Invoke agent {SERVICE_NAME}"
    )

    if not request.require_approval:
        return None

    try:
        approval = hitl_gate(
            action_description=default_action,
            tool_name=request.tool_name,
            tool_args=request.tool_args,
            request_id=thread_id,
        )
    except PermissionError as exc:
        logger.warning("Human approval denied: %s", exc)
        publish_runtime_event(
            "approval.denied",
            {"approvalName": None, "action": default_action, "reason": str(exc)},
        )
        return InvokeResponse(
            thread_id=thread_id,
            response=blocked_response(f"human approval required: {exc}"),
            context="",
            model=MODEL_NAME,
            policy_name=policy_name,
            tool_name=request.tool_name or None,
            status="blocked",
        )

    approval_name = approval.get("approval_name")
    if approval.get("decision") == "pending":
        publish_runtime_event(
            "approval.pending",
            {"approvalName": approval_name, "action": default_action},
        )
        return InvokeResponse(
            thread_id=thread_id,
            response=(
                f"Approval pending for '{default_action}'. "
                "Re-submit this request with the same thread_id after approval is granted."
            ),
            context="",
            model=MODEL_NAME,
            policy_name=policy_name,
            tool_name=request.tool_name or None,
            status="approval_pending",
            approval_name=approval_name,
            retry_after_seconds=5,
        )

    publish_runtime_event(
        "approval.approved",
        {"approvalName": approval_name, "action": default_action},
    )
    return None


def invoke_graph(
    request: InvokeRequest,
    publish_event: Callable[[str, dict[str, Any]], None] | None = None,
) -> InvokeResponse:
    if _SHUTDOWN.is_set():
        raise HTTPException(status_code=503, detail="Runtime is shutting down. Retry on another pod.")

    prompt = request.prompt.strip()
    tool_name = request.tool_name.strip()
    mcp_server = (request.mcp_server or "").strip()
    if request.model and request.model != MODEL_NAME:
        raise HTTPException(
            status_code=400,
            detail=f"Agent '{SERVICE_NAME}' is pinned to model '{MODEL_NAME}', not '{request.model}'",
        )

    if not INVOCATION_SLOTS.acquire(timeout=REQUEST_QUEUE_TIMEOUT_SECONDS):
        raise HTTPException(status_code=503, detail="Agent runtime is busy. Retry shortly.")

    try:
        policy_name, policy_spec = load_active_policy()
        thread_id = request.thread_id or str(uuid.uuid4())
        route_name = "sandbox_tool" if is_sandbox_tool(tool_name) else "mcp_tool" if mcp_server else "chat"

        with bind_event_publisher(publish_event):
            publish_runtime_event(
                "response.started",
                {
                    "thread_id": thread_id,
                    "model": MODEL_NAME,
                    "status": "running",
                    "policy_name": policy_name,
                    "route": route_name,
                    "tool_name": tool_name or None,
                },
            )

            approval_response = preflight_request_approval(request, thread_id, policy_name)
            if approval_response is not None:
                return approval_response

            initial_state: State = {
                "messages": [HumanMessage(content=prompt)] if prompt else [],
                "request_prompt": prompt,
                "context": "",
                "invoke_status": "continue",
                "policy_name": policy_name or "",
                "policy": policy_spec,
                "system_prompt": SYSTEM_PROMPT,
                "tool_name": tool_name,
                "tool_args": request.tool_args,
                "tool_result": None,
                "mcp_server": mcp_server,
                "mcp_tool_name": tool_name,
                "mcp_tool_args": request.tool_args,
            }

            result = get_runtime()["graph"].invoke(
                initial_state,
                config={"configurable": {"thread_id": thread_id}},
            )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Agent invocation failed")
        raise HTTPException(status_code=500, detail=f"Agent invocation failed: {exc}") from exc
    finally:
        INVOCATION_SLOTS.release()

    messages = result.get("messages", [])
    response_text = get_message_content(messages[-1] if messages else None)
    response_status = str(result.get("invoke_status", "completed") or "completed")
    guardrails = build_guardrails(policy_spec)
    sanitized_tool_result = sanitize_public_payload(result.get("tool_result"), guardrails)
    sanitized_sandbox_session = sanitize_public_payload(result.get("sandbox_session"), guardrails)
    warnings: list[str] = []
    if isinstance(sanitized_sandbox_session, dict):
        expires_at_value = sanitized_sandbox_session.get("expires_at")
        if isinstance(expires_at_value, str) and expires_at_value:
            try:
                expires_at = datetime.fromisoformat(expires_at_value)
                remaining_seconds = (expires_at - datetime.now(timezone.utc)).total_seconds()
                if remaining_seconds < 300:
                    warnings.append(
                        "Sandbox expires soon. Use sandbox.session.renew in the same thread_id to extend it."
                    )
            except ValueError:
                logger.debug("Ignoring invalid sandbox expiration timestamp: %s", expires_at_value)

    return InvokeResponse(
        thread_id=thread_id,
        response=response_text,
        context=result.get("context", ""),
        model=MODEL_NAME,
        policy_name=policy_name,
        tool_name=tool_name or None,
        tool_result=sanitized_tool_result,
        sandbox_session=sanitized_sandbox_session,
        status=response_status,
        warnings=warnings,
    )


def chunk_text(text: str, chunk_size: int = 160) -> Iterator[str]:
    if chunk_size <= 0:
        raise ValueError("chunk_size must be greater than 0")

    for index in range(0, len(text), chunk_size):
        yield text[index:index + chunk_size]


def format_sse_event(event: str, payload: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


class StreamEventPublisher:
    def __init__(self, loop: asyncio.AbstractEventLoop, queue: asyncio.Queue[str], thread_id: str):
        self._loop = loop
        self._queue = queue
        self._thread_id = thread_id
        self._closed = threading.Event()
        self.event_counts: dict[str, int] = {}

    def close(self) -> None:
        self._closed.set()

    @staticmethod
    def _sanitize_event_payload(event: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        if event == "response.delta":
            return None

        if event.endswith(SENSITIVE_STREAM_EVENT_SUFFIXES):
            text = str(payload.get("text", ""))
            summary: dict[str, Any] = {
                "timestamp": payload.get("timestamp"),
                "chars": len(text),
            }
            if "extra" in payload and isinstance(payload["extra"], dict):
                summary["extraKeys"] = sorted(str(key) for key in payload["extra"].keys())
            return summary

        if event == "sandbox.endpoint":
            sanitized = dict(payload)
            headers = sanitized.get("headers")
            if headers is not None:
                sanitized["headers"] = {
                    "redacted": True,
                    "count": len(headers) if isinstance(headers, dict) else 0,
                }
            return sanitized

        return dict(payload)

    def _enqueue(self, event: str, payload: dict[str, Any]) -> None:
        if self._closed.is_set():
            return
        try:
            self._queue.put_nowait(format_sse_event(event, payload))
        except asyncio.QueueFull:
            if event in {"response.completed", "response.error"}:
                with contextlib.suppress(asyncio.QueueEmpty):
                    self._queue.get_nowait()
                with contextlib.suppress(asyncio.QueueFull):
                    self._queue.put_nowait(format_sse_event(event, payload))

    def __call__(self, event: str, payload: dict[str, Any]) -> None:
        if self._closed.is_set():
            return

        event_payload = self._sanitize_event_payload(event, payload)
        if event_payload is None:
            return

        event_payload.setdefault("thread_id", self._thread_id)
        self.event_counts[event] = self.event_counts.get(event, 0) + 1
        self._loop.call_soon_threadsafe(
            self._enqueue,
            event,
            event_payload,
        )


@app.get("/health")
async def health() -> dict[str, Any]:
    policy_name, _ = load_active_policy()
    ready = bool(RUNTIME.get("graph") and RUNTIME.get("connection"))
    return {
        "status": "shutting-down" if _SHUTDOWN.is_set() else "healthy" if ready else "starting",
        "ready": ready,
        "shuttingDown": _SHUTDOWN.is_set(),
        "agent": SERVICE_NAME,
        "namespace": SERVICE_NAMESPACE,
        "model": MODEL_NAME,
        "policy": policy_name,
        "ragEnabled": RAG_ENABLED,
        "qdrantCollection": DISCOVERED_QDRANT_COLLECTION,
        "policyAccess": K8S_POLICY_ACCESS,
        "maxConcurrentRequests": MAX_CONCURRENT_REQUESTS,
        "openSandbox": sandbox_runtime_metadata(),
    }


@app.get("/ready")
async def ready() -> dict[str, Any]:
    if _SHUTDOWN.is_set():
        raise HTTPException(status_code=503, detail="Runtime is shutting down")

    runtime_ready = bool(RUNTIME.get("graph") and RUNTIME.get("connection"))
    if not runtime_ready:
        raise HTTPException(status_code=503, detail="Runtime is not ready")

    return {"status": "ready", "agent": SERVICE_NAME, "namespace": SERVICE_NAMESPACE}


@app.post("/invoke", response_model=InvokeResponse)
async def invoke(request: InvokeRequest) -> InvokeResponse:
    if _SHUTDOWN.is_set():
        raise HTTPException(status_code=503, detail="Runtime is shutting down. Retry on another pod.")
    return await asyncio.to_thread(invoke_graph, request)


@app.post("/invoke/stream")
async def invoke_stream(request: InvokeRequest) -> StreamingResponse:
    if _SHUTDOWN.is_set():
        raise HTTPException(status_code=503, detail="Runtime is shutting down. Retry on another pod.")

    async def event_generator() -> AsyncIterator[str]:
        stream_request = request
        if not stream_request.thread_id:
            stream_request = stream_request.model_copy(update={"thread_id": str(uuid.uuid4())})

        queue: asyncio.Queue[str] = asyncio.Queue(maxsize=STREAM_EVENT_QUEUE_SIZE)
        publisher = StreamEventPublisher(
            asyncio.get_running_loop(),
            queue,
            stream_request.thread_id or "",
        )
        invocation_task = asyncio.create_task(asyncio.to_thread(invoke_graph, stream_request, publisher))

        try:
            while True:
                if invocation_task.done() and queue.empty():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=0.25)
                except asyncio.TimeoutError:
                    continue
                yield event

            response = await invocation_task
            if publisher.event_counts.get("response.delta", 0) == 0 and response.response:
                yield format_sse_event(
                    "response.delta",
                    {
                        "delta": response.response,
                        "thread_id": response.thread_id,
                        "request_id": REQUEST_ID.get(),
                    },
                )
            yield format_sse_event(
                "response.completed",
                {
                    "done": True,
                    "thread_id": response.thread_id,
                    "request_id": REQUEST_ID.get(),
                    "policy_name": response.policy_name,
                    "status": response.status,
                    "approval_name": response.approval_name,
                    "retry_after_seconds": response.retry_after_seconds,
                    "tool_name": response.tool_name,
                    "tool_result": response.tool_result,
                    "sandbox_session": response.sandbox_session,
                    "warnings": response.warnings,
                },
            )
        except asyncio.CancelledError:
            publisher.close()
            if not invocation_task.done():
                invocation_task.cancel()
            raise
        except HTTPException as exc:
            detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
            yield format_sse_event("response.error", {"error": detail, "request_id": REQUEST_ID.get()})
        except Exception:
            logger.exception("Streaming invocation failed")
            yield format_sse_event(
                "response.error",
                {"error": "Agent invocation failed", "request_id": REQUEST_ID.get()},
            )
        finally:
            publisher.close()

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def main() -> None:
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8080, proxy_headers=True, forwarded_allow_ips="*")


if __name__ == "__main__":
    main()
