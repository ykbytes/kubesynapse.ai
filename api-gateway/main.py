"""REST API Gateway for the AI Agent Sandbox."""

import asyncio
import contextlib
import copy
import hmac
import json
import logging
import os
import re
import threading
import time
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any
from urllib.parse import urlencode

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from jose import jwk, jwt
from jose.utils import base64url_decode
from pydantic import BaseModel, Field, model_validator

logger = logging.getLogger("api-gateway")
K8S_NAME_PATTERN = r"^[a-z0-9]([-a-z0-9]*[a-z0-9])?$"
K8S_NAME_RE = re.compile(K8S_NAME_PATTERN)


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        from kubernetes import config

        try:
            config.load_incluster_config()
            logger.info("Loaded in-cluster Kubernetes config.")
        except Exception:
            config.load_kube_config()
            logger.info("Loaded local kubeconfig file.")
    except Exception as exc:
        logger.warning("Failed to load K8s config on startup (API might fail): %s", exc)
    yield

app = FastAPI(
    title="AI Agent Sandbox API",
    description="Enterprise REST API for interacting with AI Agents",
    version="1.0.0",
    lifespan=lifespan,
)


def cors_origins() -> list[str]:
    raw_origins = os.getenv("API_GATEWAY_CORS_ORIGINS", "").strip()
    if not raw_origins:
        return ["http://localhost:5173", "http://127.0.0.1:5173"]
    return [origin.strip() for origin in raw_origins.split(",") if origin.strip()]


app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins(),
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept", "X-Request-Id"],
)

NATS_URL = os.getenv("NATS_URL", "nats://ai-agent-sandbox-nats:4222")
QDRANT_URL = os.getenv("QDRANT_URL", "http://ai-agent-sandbox-qdrant:6333")
AUTH_MODE = os.getenv("API_GATEWAY_AUTH_MODE", "shared_token").strip().lower()
OIDC_JWKS_URL = os.getenv("OIDC_JWKS_URL", "").strip()
OIDC_ISSUER = os.getenv("OIDC_ISSUER", "").strip()
OIDC_AUDIENCE = os.getenv("OIDC_AUDIENCE", "").strip()
SHARED_TOKEN = os.getenv("API_GATEWAY_SHARED_TOKEN", "").strip()
AGENT_RUNTIME_TIMEOUT_SECONDS = max(float(os.getenv("AGENT_RUNTIME_TIMEOUT_SECONDS", "360")), 1.0)
OIDC_JWKS_TIMEOUT_SECONDS = max(float(os.getenv("OIDC_JWKS_TIMEOUT_SECONDS", "10")), 1.0)
JWKS_CACHE: dict[str, Any] = {"keys": [], "expires_at": 0.0}
STREAM_KEEPALIVE_SECONDS = max(float(os.getenv("API_GATEWAY_STREAM_KEEPALIVE_SECONDS", "15")), 5.0)
A2A_PROTOCOL_VERSION = "1.0"
A2A_TASK_RETENTION_SECONDS = max(int(os.getenv("A2A_TASK_RETENTION_SECONDS", "3600")), 60)
A2A_PUBLIC_BASE_URL = os.getenv("API_GATEWAY_PUBLIC_BASE_URL", "").strip()
A2A_PROVIDER_ORGANIZATION = os.getenv("A2A_PROVIDER_ORGANIZATION", "Kubeminionagents").strip()
A2A_PROVIDER_URL = os.getenv("A2A_PROVIDER_URL", "").strip()
A2A_TERMINAL_STATES = {
    "TASK_STATE_COMPLETED",
    "TASK_STATE_FAILED",
    "TASK_STATE_CANCELED",
    "TASK_STATE_REJECTED",
}
A2A_INTERRUPTED_STATES = {
    "TASK_STATE_INPUT_REQUIRED",
    "TASK_STATE_AUTH_REQUIRED",
}
JSONRPC_PARSE_ERROR = -32700
JSONRPC_INVALID_REQUEST = -32600
JSONRPC_METHOD_NOT_FOUND = -32601
JSONRPC_INVALID_PARAMS = -32602
JSONRPC_INTERNAL_ERROR = -32603
A2A_TASK_NOT_FOUND_ERROR = -32001
A2A_PUSH_NOTIFICATION_NOT_SUPPORTED_ERROR = -32003
A2A_UNSUPPORTED_OPERATION_ERROR = -32004
A2A_CONTENT_TYPE_NOT_SUPPORTED_ERROR = -32005
A2A_VERSION_NOT_SUPPORTED_ERROR = -32009
A2A_TASK_STORE_LOCK = threading.Lock()
A2A_TASK_STORE: dict[tuple[str, str, str], dict[str, Any]] = {}


class InvokeRequest(BaseModel):
    prompt: str = ""
    thread_id: str | None = None
    model: str | None = None
    system: str | None = None
    require_approval: bool = False
    approval_action: str | None = None
    tool_name: str = ""
    tool_args: dict[str, Any] = Field(default_factory=dict)
    sandbox_session: dict[str, Any] | None = None
    mcp_server: str | None = None
    a2a_target_agent: str | None = Field(default=None, max_length=63)
    a2a_target_namespace: str | None = Field(default=None, max_length=63)
    a2a_timeout_seconds: float | None = Field(default=None, ge=1.0)
    debug: bool = False
    no_session: bool = False
    max_turns: int | None = None
    working_directory: str | None = None
    builtin_extensions: list[str] = Field(default_factory=list)
    stdio_extensions: list[str] = Field(default_factory=list)
    streamable_http_extensions: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def normalize_fields(self) -> "InvokeRequest":
        self.prompt = self.prompt.strip()
        self.thread_id = self.thread_id.strip() or None if self.thread_id is not None else None
        self.model = self.model.strip() or None if self.model is not None else None
        self.system = self.system.strip() or None if self.system is not None else None
        self.approval_action = self.approval_action.strip() or None if self.approval_action is not None else None
        self.tool_name = self.tool_name.strip()
        self.mcp_server = self.mcp_server.strip() or None if self.mcp_server is not None else None
        self.a2a_target_agent = self.a2a_target_agent.strip() or None if self.a2a_target_agent is not None else None
        self.a2a_target_namespace = (
            self.a2a_target_namespace.strip() or None if self.a2a_target_namespace is not None else None
        )
        self.working_directory = self.working_directory.strip() or None if self.working_directory is not None else None
        self.builtin_extensions = [str(item).strip() for item in self.builtin_extensions if str(item).strip()]
        self.stdio_extensions = [str(item).strip() for item in self.stdio_extensions if str(item).strip()]
        self.streamable_http_extensions = [str(item).strip() for item in self.streamable_http_extensions if str(item).strip()]
        if self.a2a_target_agent or self.a2a_target_namespace:
            if not self.a2a_target_agent or not self.a2a_target_namespace:
                raise ValueError("a2a_target_agent and a2a_target_namespace must be provided together")
            if not K8S_NAME_RE.fullmatch(self.a2a_target_agent):
                raise ValueError("a2a_target_agent must be a valid lowercase Kubernetes resource name")
            if not K8S_NAME_RE.fullmatch(self.a2a_target_namespace):
                raise ValueError("a2a_target_namespace must be a valid lowercase Kubernetes namespace name")
            if self.tool_name:
                raise ValueError("a2a_target_* cannot be combined with tool_name")
            if self.mcp_server:
                raise ValueError("a2a_target_* cannot be combined with mcp_server")
        return self


class InvokeResponse(BaseModel):
    agent_name: str
    response: str
    thread_id: str
    model: str
    policy_name: str | None = None
    tool_name: str | None = None
    tool_result: dict[str, Any] | None = None
    sandbox_session: dict[str, Any] | None = None
    status: str = "completed"
    approval_name: str | None = None
    retry_after_seconds: int | None = None
    a2a: dict[str, Any] | None = None
    warnings: list[str] = Field(default_factory=list)


class ApprovalInfo(BaseModel):
    name: str
    namespace: str
    decision: str
    agent_name: str
    action: str
    requested_at: str | None = None
    decided_by: str | None = None
    decided_at: str | None = None
    reason: str | None = None


class ApprovalDecisionRequest(BaseModel):
    """Body for PATCH /api/approvals/{name} — records a human decision."""

    decision: str = Field(
        pattern="^(approved|denied)$",
        description="Must be 'approved' or 'denied'",
    )
    reason: str | None = Field(
        default=None,
        max_length=1024,
        description="Optional free-text reason for the decision",
    )


class AgentInfo(BaseModel):
    name: str
    model: str
    namespace: str
    status: str
    runtime_kind: str = "langgraph"


class PolicyInfo(BaseModel):
    name: str
    namespace: str


class AgentDetail(AgentInfo):
    system_prompt: str = ""
    policy_ref: str | None = None
    storage_size: str | None = None
    enable_gvisor: bool = False
    mcp_servers: list[str] = Field(default_factory=list)
    mcp_sidecars: list[dict[str, Any]] = Field(default_factory=list)
    a2a_config: dict[str, Any] = Field(default_factory=dict)
    goose_config_files: dict[str, Any] = Field(default_factory=dict)
    created_at: str | None = None


class AgentDiscoveryPeer(BaseModel):
    name: str
    namespace: str
    exists: bool = False
    model: str | None = None
    status: str | None = None
    runtime_kind: str | None = None
    accepts_caller: bool = False
    reachable: bool = False
    reason: str | None = None


class AgentDiscoveryResponse(BaseModel):
    agent_name: str
    namespace: str
    policy_ref: str | None = None
    peers: list[AgentDiscoveryPeer] = Field(default_factory=list)


class A2AJSONRPCError(Exception):
    def __init__(self, code: int, message: str, data: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data or {}


class CreateAgentRequest(BaseModel):
    name: str = Field(
        min_length=1,
        max_length=63,
        pattern=r"^[a-z0-9]([-a-z0-9]*[a-z0-9])?$",
    )
    model: str = Field(min_length=1, max_length=255)
    system_prompt: str = Field(default="", max_length=4000)
    policy_ref: str | None = Field(default=None, max_length=253)
    storage_size: str | None = Field(default="1Gi", max_length=32)
    runtime_kind: str = Field(default="langgraph", pattern=r"^(langgraph|goose)$")
    enable_gvisor: bool = False
    mcp_servers: list[str] = Field(default_factory=list)
    mcp_sidecars: list[dict[str, Any]] = Field(default_factory=list)
    a2a_config: dict[str, Any] | None = None
    goose_config_files: dict[str, Any] = Field(default_factory=dict)


class UpdateAgentRequest(BaseModel):
    model: str = Field(min_length=1, max_length=255)
    system_prompt: str = Field(default="", max_length=4000)
    policy_ref: str | None = Field(default=None, max_length=253)
    storage_size: str | None = Field(default="1Gi", max_length=32)
    runtime_kind: str | None = Field(default=None, pattern=r"^(langgraph|goose)$")
    enable_gvisor: bool = False
    mcp_servers: list[str] = Field(default_factory=list)
    mcp_sidecars: list[dict[str, Any]] = Field(default_factory=list)
    a2a_config: dict[str, Any] | None = None
    goose_config_files: dict[str, Any] | None = None


class WorkflowStepRequest(BaseModel):
    name: str = Field(min_length=1, max_length=63)
    agent_ref: str = Field(min_length=1, max_length=63)
    prompt: str = Field(default="", max_length=4000)
    depends_on: list[str] = Field(default_factory=list)
    require_approval: bool = False
    execution: dict[str, Any] | None = None


class WorkflowRequest(BaseModel):
    name: str = Field(
        min_length=1,
        max_length=63,
        pattern=r"^[a-z0-9]([-a-z0-9]*[a-z0-9])?$",
    )
    description: str = Field(default="", max_length=4000)
    input: str = Field(default="", max_length=4000)
    message_bus: str = Field(default="in-memory", pattern=r"^(in-memory)$")
    steps: list[WorkflowStepRequest] = Field(default_factory=list)


class WorkflowUpdateRequest(BaseModel):
    description: str = Field(default="", max_length=4000)
    input: str = Field(default="", max_length=4000)
    message_bus: str = Field(default="in-memory", pattern=r"^(in-memory)$")
    steps: list[WorkflowStepRequest] = Field(default_factory=list)


class WorkflowInfo(BaseModel):
    name: str
    namespace: str
    description: str = ""
    input: str = ""
    message_bus: str = "in-memory"
    steps: list[WorkflowStepRequest] = Field(default_factory=list)
    phase: str = "pending"
    current_step: str = ""
    observed_generation: int | None = None
    summary: dict[str, Any] | None = None
    artifact_ref: dict[str, Any] | None = None
    journal_ref: dict[str, Any] | None = None
    pending_approval: dict[str, Any] | None = None
    run_id: str | None = None
    step_states: dict[str, Any] | None = None
    worker_job: dict[str, Any] | None = None
    created_at: str | None = None


class EvalTestCaseRequest(BaseModel):
    input: str = Field(min_length=1, max_length=4000)
    expected_output: str = Field(default="", max_length=4000)
    metrics: list[str] = Field(default_factory=list)


class EvalRequest(BaseModel):
    name: str = Field(
        min_length=1,
        max_length=63,
        pattern=r"^[a-z0-9]([-a-z0-9]*[a-z0-9])?$",
    )
    agent_ref: str = Field(min_length=1, max_length=63)
    schedule: str | None = Field(default=None, max_length=128)
    test_suite: list[EvalTestCaseRequest] = Field(default_factory=list)
    failure_threshold: dict[str, Any] = Field(default_factory=dict)


class EvalUpdateRequest(BaseModel):
    agent_ref: str = Field(min_length=1, max_length=63)
    schedule: str | None = Field(default=None, max_length=128)
    test_suite: list[EvalTestCaseRequest] = Field(default_factory=list)
    failure_threshold: dict[str, Any] = Field(default_factory=dict)


class EvalInfo(BaseModel):
    name: str
    namespace: str
    agent_ref: str
    schedule: str | None = None
    test_suite: list[EvalTestCaseRequest] = Field(default_factory=list)
    failure_threshold: dict[str, Any] = Field(default_factory=dict)
    phase: str = "pending"
    passed: bool | None = None
    last_run: str | None = None
    observed_generation: int | None = None
    summary: dict[str, Any] | None = None
    artifact_ref: dict[str, Any] | None = None
    worker_job: dict[str, Any] | None = None
    created_at: str | None = None


class DeleteResponse(BaseModel):
    status: str
    kind: str
    name: str
    namespace: str


RESOURCE_GROUP = "sandbox.enterprise.ai"
RESOURCE_VERSION = "v1alpha1"
RESOURCE_KIND_BY_PLURAL = {
    "aiagents": "AIAgent",
    "agentworkflows": "AgentWorkflow",
    "agentevals": "AgentEval",
}


def agent_runtime_url(agent_name: str, namespace: str) -> str:
    return f"http://{agent_name}-sandbox.{namespace}.svc.cluster.local:8080"


def normalized_runtime_kind(raw_value: str | None) -> str:
    runtime_kind = (raw_value or "langgraph").strip().lower() or "langgraph"
    if runtime_kind not in {"langgraph", "goose"}:
        raise ValueError(f"Unsupported runtime kind '{runtime_kind}'")
    return runtime_kind


def normalize_goose_config_file_path(raw_path: object) -> str:
    normalized_path = str(raw_path).replace("\\", "/").strip()
    if not normalized_path:
        raise HTTPException(status_code=400, detail="goose_config_files paths must not be blank")
    if normalized_path.startswith("/"):
        raise HTTPException(status_code=400, detail="goose_config_files paths must be relative")

    parts = [part for part in normalized_path.split("/") if part]
    if not parts or any(part in {".", ".."} for part in parts):
        raise HTTPException(status_code=400, detail=f"goose_config_files path '{raw_path}' is invalid")

    candidate = "/".join(parts)
    if candidate == "secrets.yaml":
        raise HTTPException(
            status_code=400,
            detail="goose_config_files cannot preseed secrets.yaml; use Kubernetes secrets and environment variables instead",
        )
    if parts[0] == "permissions":
        raise HTTPException(
            status_code=400,
            detail="goose_config_files cannot preseed permissions/* because Goose manages that path at runtime",
        )
    return candidate


def parse_a2a_peer_ref(raw_value: Any, *, source: str) -> dict[str, str]:
    if not isinstance(raw_value, dict):
        raise HTTPException(status_code=400, detail=f"{source} entries must be objects with name and namespace fields")

    name = str(raw_value.get("name", "")).strip()
    namespace = str(raw_value.get("namespace", "")).strip()
    if not name or not namespace:
        raise HTTPException(status_code=400, detail=f"{source} entries must include non-empty name and namespace values")
    if not K8S_NAME_RE.fullmatch(name):
        raise HTTPException(status_code=400, detail=f"{source}.name must be a valid lowercase Kubernetes resource name")
    if not K8S_NAME_RE.fullmatch(namespace):
        raise HTTPException(status_code=400, detail=f"{source}.namespace must be a valid lowercase Kubernetes namespace name")
    return {"name": name, "namespace": namespace}


def parse_a2a_peer_refs(peer_refs: Any, *, source: str) -> list[dict[str, str]]:
    if peer_refs is None:
        return []
    if not isinstance(peer_refs, list):
        raise HTTPException(status_code=400, detail=f"{source} must be a list of peer reference objects")

    normalized: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for index, raw_value in enumerate(peer_refs):
        peer_ref = parse_a2a_peer_ref(raw_value, source=f"{source}[{index}]")
        identity = (peer_ref["namespace"], peer_ref["name"])
        if identity in seen:
            continue
        seen.add(identity)
        normalized.append(peer_ref)
    return normalized


def parse_a2a_agent_config(config: Any, *, source: str) -> dict[str, Any]:
    if config is None:
        return {}
    if not isinstance(config, dict):
        raise HTTPException(status_code=400, detail=f"{source} must be an object")

    raw_allowed_callers = config.get("allowed_callers")
    if raw_allowed_callers is None:
        raw_allowed_callers = config.get("allowedCallers")

    allowed_callers = parse_a2a_peer_refs(raw_allowed_callers, source=f"{source}.allowed_callers")
    return {"allowedCallers": allowed_callers} if allowed_callers else {}


def parse_a2a_policy_config(config: Any, *, source: str) -> dict[str, Any]:
    if config is None:
        return {}
    if not isinstance(config, dict):
        raise HTTPException(status_code=400, detail=f"{source} must be an object")

    normalized: dict[str, Any] = {}
    raw_allowed_targets = config.get("allowed_targets")
    if raw_allowed_targets is None:
        raw_allowed_targets = config.get("allowedTargets")

    allowed_targets = parse_a2a_peer_refs(raw_allowed_targets, source=f"{source}.allowed_targets")
    if allowed_targets:
        normalized["allowedTargets"] = allowed_targets

    raw_max_timeout_seconds = config.get("max_timeout_seconds")
    if raw_max_timeout_seconds is None:
        raw_max_timeout_seconds = config.get("maxTimeoutSeconds")
    if raw_max_timeout_seconds is not None:
        try:
            normalized["maxTimeoutSeconds"] = max(float(raw_max_timeout_seconds), 1.0)
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=f"{source}.max_timeout_seconds must be a positive number") from exc

    raw_require_hitl = config.get("require_hitl")
    if raw_require_hitl is None:
        raw_require_hitl = config.get("requireHitl")
    if raw_require_hitl is not None:
        if not isinstance(raw_require_hitl, bool):
            raise HTTPException(status_code=400, detail=f"{source}.require_hitl must be a boolean")
        normalized["requireHitl"] = raw_require_hitl

    return normalized


def parse_goose_config_files(config_files: Any, *, source: str) -> dict[str, Any]:
    if config_files is None:
        return {}
    if not isinstance(config_files, dict):
        raise HTTPException(status_code=400, detail=f"{source} must be a JSON object keyed by relative Goose config paths")

    normalized: dict[str, Any] = {}
    for raw_path, raw_content in sorted(config_files.items(), key=lambda item: str(item[0])):
        normalized_path = normalize_goose_config_file_path(raw_path)
        if raw_content is None:
            raise HTTPException(status_code=400, detail=f"{source}.{normalized_path} must not be null")
        normalized[normalized_path] = raw_content
    return normalized


def runtime_kind_from_spec(spec: dict[str, Any] | None) -> str:
    runtime_spec = (spec or {}).get("runtime") or {}
    if isinstance(runtime_spec, dict):
        return normalized_runtime_kind(runtime_spec.get("kind"))
    return "langgraph"


def validate_agent_runtime_compatibility(spec: dict[str, Any]) -> None:
    if runtime_kind_from_spec(spec) != "goose":
        return

    errors: list[str] = []
    if spec.get("mcpServers"):
        errors.append(
            "Goose runtime does not support mcp_servers. Use the LangGraph runtime for MCP routing today."
        )
    if spec.get("mcpSidecars"):
        errors.append(
            "Goose runtime does not support mcp_sidecars. Use the LangGraph runtime for sidecar-based MCP tools today."
        )
    if errors:
        raise HTTPException(status_code=400, detail=" ".join(errors))


def validate_invoke_runtime_compatibility(runtime_kind: str, request: InvokeRequest) -> None:
    if runtime_kind != "goose":
        return

    unsupported_fields: list[str] = []
    if request.require_approval:
        unsupported_fields.append("require_approval")
    if request.tool_name.strip():
        unsupported_fields.append("tool_name")
    if (request.mcp_server or "").strip():
        unsupported_fields.append("mcp_server")
    if request.sandbox_session is not None:
        unsupported_fields.append("sandbox_session")
    if request.a2a_target_agent or request.a2a_target_namespace:
        unsupported_fields.append("a2a_target")
    if request.a2a_timeout_seconds is not None:
        unsupported_fields.append("a2a_timeout_seconds")

    if unsupported_fields:
        joined_fields = ", ".join(unsupported_fields)
        raise HTTPException(
            status_code=400,
            detail=(
                "Goose runtime currently supports chat-style prompt invocation plus Goose-native run controls. "
                f"Unsupported fields for goose agents: {joined_fields}."
            ),
        )


def parse_json_object_response(response: httpx.Response, *, context: str) -> dict[str, Any]:
    try:
        payload = response.json()
    except json.JSONDecodeError as exc:
        response_text = response.text.strip()
        preview = (response_text[:400] + "...") if len(response_text) > 400 else response_text
        raise HTTPException(
            status_code=502,
            detail=f"{context} returned invalid JSON: {preview or 'empty response'}",
        ) from exc

    if not isinstance(payload, dict):
        raise HTTPException(status_code=502, detail=f"{context} returned a non-object JSON payload")
    return payload


def error_payload_from_body(body: bytes, fallback: str) -> dict[str, str]:
    text = body.decode("utf-8", errors="ignore").strip()
    if not text:
        return {"error": fallback}

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return {"error": text}

    if isinstance(parsed, dict):
        for key in ("detail", "error"):
            value = parsed.get(key)
            if isinstance(value, str) and value.strip():
                return {"error": value.strip()}

    return {"error": text}


def sse_event(event: str, payload: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False, default=str)}\n\n"


def sse_keepalive_comment() -> str:
    return ": keepalive\n\n"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def dedupe_text_values(values: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for raw_value in values:
        value = str(raw_value).strip()
        if not value or value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped


def jsonrpc_success_response(request_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def jsonrpc_error_response(
    request_id: Any,
    code: int,
    message: str,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    error_payload: dict[str, Any] = {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {
            "code": code,
            "message": message,
        },
    }
    if data:
        error_payload["error"]["data"] = data
    return error_payload


def jsonrpc_sse_message(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False, default=str)}\n\n"


def canonical_a2a_method(method: str) -> str:
    normalized = method.strip()
    aliases = {
        "SendMessage": "message/send",
        "message/send": "message/send",
        "SendStreamingMessage": "message/stream",
        "message/stream": "message/stream",
        "GetTask": "tasks/get",
        "tasks/get": "tasks/get",
    }
    return aliases.get(normalized, normalized)


def parse_jsonrpc_payload(payload: Any) -> tuple[Any, str, dict[str, Any]]:
    if not isinstance(payload, dict):
        raise A2AJSONRPCError(JSONRPC_INVALID_REQUEST, "JSON-RPC request must be a JSON object")
    if payload.get("jsonrpc") != "2.0":
        raise A2AJSONRPCError(JSONRPC_INVALID_REQUEST, "jsonrpc must be '2.0'")

    method = str(payload.get("method") or "").strip()
    if not method:
        raise A2AJSONRPCError(JSONRPC_INVALID_REQUEST, "method is required")

    params = payload.get("params")
    if params is None:
        params = {}
    if not isinstance(params, dict):
        raise A2AJSONRPCError(JSONRPC_INVALID_PARAMS, "params must be an object")

    return payload.get("id"), canonical_a2a_method(method), params


def validate_a2a_version(request: Request) -> None:
    requested_version = (request.headers.get("A2A-Version") or request.query_params.get("A2A-Version") or "").strip()
    if not requested_version:
        return
    if requested_version != A2A_PROTOCOL_VERSION:
        raise A2AJSONRPCError(
            A2A_VERSION_NOT_SUPPORTED_ERROR,
            f"Requested A2A protocol version {requested_version} is not supported",
            {"requestedVersion": requested_version, "supportedVersions": [A2A_PROTOCOL_VERSION]},
        )


def resolve_a2a_agent_reference(assistant_id: str, namespace: str | None) -> tuple[str, str]:
    raw_assistant_id = assistant_id.strip()
    if not raw_assistant_id:
        raise A2AJSONRPCError(JSONRPC_INVALID_PARAMS, "assistant_id must not be blank")

    if "/" in raw_assistant_id:
        parts = [part.strip() for part in raw_assistant_id.split("/", 1)]
        if len(parts) != 2 or not parts[0] or not parts[1]:
            raise A2AJSONRPCError(JSONRPC_INVALID_PARAMS, "assistant_id must use namespace/name syntax when it contains '/'")
        resolved_namespace, agent_name = parts
        if namespace and namespace.strip() and namespace.strip() != resolved_namespace:
            raise A2AJSONRPCError(JSONRPC_INVALID_PARAMS, "namespace query parameter must match assistant_id namespace")
    else:
        resolved_namespace = (namespace or "default").strip() or "default"
        agent_name = raw_assistant_id

    if not K8S_NAME_RE.fullmatch(agent_name):
        raise A2AJSONRPCError(JSONRPC_INVALID_PARAMS, "assistant_id must resolve to a valid Kubernetes resource name")
    if not K8S_NAME_RE.fullmatch(resolved_namespace):
        raise A2AJSONRPCError(JSONRPC_INVALID_PARAMS, "namespace must be a valid Kubernetes namespace name")

    return agent_name, resolved_namespace


def public_base_url(request: Request) -> str:
    if A2A_PUBLIC_BASE_URL:
        return A2A_PUBLIC_BASE_URL.rstrip("/")
    return str(request.base_url).rstrip("/")


def a2a_interface_url(request: Request, agent_name: str, namespace: str) -> str:
    return f"{public_base_url(request)}/a2a/{agent_name}?{urlencode({'namespace': namespace})}"


def skill_id(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return normalized or "skill"


def summarize_text(value: str, *, fallback: str, max_length: int = 240) -> str:
    text = value.strip() or fallback
    collapsed = re.sub(r"\s+", " ", text).strip()
    if len(collapsed) <= max_length:
        return collapsed
    return collapsed[: max_length - 3].rstrip() + "..."


def build_agent_card_skills(agent: AgentDetail, policy_targets: list[dict[str, str]]) -> list[dict[str, Any]]:
    base_description = summarize_text(
        agent.system_prompt,
        fallback=(
            f"{agent.runtime_kind.capitalize()} assistant backed by model {agent.model}."
        ),
    )
    base_tags = dedupe_text_values(
        [
            "assistant",
            agent.runtime_kind,
            agent.model,
            *agent.mcp_servers,
            *(str(sidecar.get("name") or "") for sidecar in agent.mcp_sidecars if isinstance(sidecar, dict)),
            *( ["a2a", "delegation"] if policy_targets else [] ),
        ]
    )
    skills: list[dict[str, Any]] = [
        {
            "id": skill_id(f"{agent.name}-assistant"),
            "name": f"{agent.name} assistant",
            "description": base_description,
            "tags": base_tags or ["assistant"],
            "inputModes": ["text/plain"],
            "outputModes": ["text/plain"],
        }
    ]

    for server_name in dedupe_text_values(agent.mcp_servers):
        skills.append(
            {
                "id": skill_id(f"mcp-{server_name}"),
                "name": f"{server_name} tool access",
                "description": f"Can use the {server_name} MCP server while working on delegated tasks.",
                "tags": ["mcp", server_name],
                "inputModes": ["text/plain"],
                "outputModes": ["text/plain"],
            }
        )

    sidecar_names = [
        str(sidecar.get("name") or "")
        for sidecar in agent.mcp_sidecars
        if isinstance(sidecar, dict) and str(sidecar.get("name") or "").strip()
    ]
    for sidecar_name in dedupe_text_values(sidecar_names):
        skills.append(
            {
                "id": skill_id(f"sidecar-{sidecar_name}"),
                "name": f"{sidecar_name} sidecar capability",
                "description": f"Uses the {sidecar_name} sidecar capability from inside the agent sandbox.",
                "tags": ["sidecar", sidecar_name],
                "inputModes": ["text/plain"],
                "outputModes": ["text/plain"],
            }
        )

    if policy_targets:
        skills.append(
            {
                "id": "peer-delegation",
                "name": "Peer delegation",
                "description": f"Can delegate subtasks to {len(policy_targets)} explicitly allowed peer agents over A2A.",
                "tags": ["a2a", "delegation"],
                "inputModes": ["text/plain"],
                "outputModes": ["text/plain"],
            }
        )

    return skills


def build_agent_card(agent_name: str, namespace: str, request: Request) -> dict[str, Any]:
    agent_resource = read_agent(agent_name, namespace)
    agent_detail = agent_detail_from_resource(agent_resource)
    policy_targets: list[dict[str, str]] = []
    if agent_detail.policy_ref:
        try:
            policy_targets = policy_a2a_targets_from_resource(
                read_custom_resource("agentpolicies", agent_detail.policy_ref, namespace, "Policy")
            )
        except HTTPException as exc:
            if exc.status_code != 404:
                raise
            logger.warning(
                "Agent %s/%s references missing policy %s while building agent card",
                namespace,
                agent_name,
                agent_detail.policy_ref,
            )

    generation = agent_resource.get("metadata", {}).get("generation")
    version = f"1.0.{generation}" if generation is not None else app.version
    interface_url = a2a_interface_url(request, agent_name, namespace)
    security_requirements = [{"bearerAuth": []}]
    provider_url = A2A_PROVIDER_URL or public_base_url(request)
    card: dict[str, Any] = {
        "name": agent_detail.name,
        "description": summarize_text(
            agent_detail.system_prompt,
            fallback=(
                f"{agent_detail.runtime_kind.capitalize()} agent in namespace {namespace} running model {agent_detail.model}."
            ),
        ),
        "url": interface_url,
        "supportedInterfaces": [
            {
                "url": interface_url,
                "protocolBinding": "JSONRPC",
                "protocolVersion": A2A_PROTOCOL_VERSION,
                "tenant": namespace,
            }
        ],
        "provider": {
            "organization": A2A_PROVIDER_ORGANIZATION or "Kubeminionagents",
            "url": provider_url,
        },
        "version": version,
        "documentationUrl": f"{public_base_url(request)}/docs",
        "capabilities": {
            "streaming": True,
            "pushNotifications": False,
            "extendedAgentCard": False,
        },
        "securitySchemes": {
            "bearerAuth": {
                "httpAuthSecurityScheme": {
                    "scheme": "Bearer",
                    "bearerFormat": "JWT" if AUTH_MODE == "oidc" else "Opaque",
                    "description": "Bearer token required by the API gateway.",
                }
            }
        },
        "securityRequirements": security_requirements,
        "security": security_requirements,
        "defaultInputModes": ["text/plain"],
        "defaultOutputModes": ["text/plain"],
        "skills": build_agent_card_skills(agent_detail, policy_targets),
    }
    return card


def purge_expired_a2a_tasks() -> None:
    cutoff = time.time() - A2A_TASK_RETENTION_SECONDS
    stale_keys = [key for key, record in A2A_TASK_STORE.items() if float(record.get("updatedAt", 0.0)) < cutoff]
    for key in stale_keys:
        A2A_TASK_STORE.pop(key, None)


def a2a_task_store_key(namespace: str, agent_name: str, task_id: str) -> tuple[str, str, str]:
    return namespace, agent_name, task_id


def create_a2a_status_message(text: str, context_id: str, task_id: str) -> dict[str, Any]:
    return {
        "messageId": str(uuid.uuid4()),
        "contextId": context_id,
        "taskId": task_id,
        "role": "ROLE_AGENT",
        "parts": [{"text": text, "mediaType": "text/plain"}],
    }


def create_a2a_history_message(role: str, text: str, context_id: str, task_id: str) -> dict[str, Any]:
    return {
        "messageId": str(uuid.uuid4()),
        "contextId": context_id,
        "taskId": task_id,
        "role": role,
        "parts": [{"text": text, "mediaType": "text/plain"}],
    }


def create_a2a_task_record(agent_name: str, namespace: str, context_id: str, task_id: str, thread_id: str) -> dict[str, Any]:
    return {
        "assistantName": agent_name,
        "namespace": namespace,
        "threadId": thread_id,
        "artifactText": "",
        "updatedAt": time.time(),
        "task": {
            "id": task_id,
            "contextId": context_id,
            "status": {
                "state": "TASK_STATE_SUBMITTED",
                "timestamp": now_iso(),
            },
            "history": [],
            "metadata": {
                "assistantName": agent_name,
                "assistantNamespace": namespace,
                "threadId": thread_id,
            },
        },
    }


def store_a2a_task_record(record: dict[str, Any]) -> None:
    with A2A_TASK_STORE_LOCK:
        purge_expired_a2a_tasks()
        record["updatedAt"] = time.time()
        task_id = str(record.get("task", {}).get("id") or "")
        A2A_TASK_STORE[a2a_task_store_key(record["namespace"], record["assistantName"], task_id)] = record


def get_a2a_task_record(namespace: str, agent_name: str, task_id: str) -> dict[str, Any] | None:
    with A2A_TASK_STORE_LOCK:
        purge_expired_a2a_tasks()
        return A2A_TASK_STORE.get(a2a_task_store_key(namespace, agent_name, task_id))


def append_a2a_task_history(record: dict[str, Any], message: dict[str, Any]) -> None:
    with A2A_TASK_STORE_LOCK:
        history = record.setdefault("task", {}).setdefault("history", [])
        message_id = str(message.get("messageId") or "")
        if message_id and any(str(item.get("messageId") or "") == message_id for item in history):
            return
        history.append(copy.deepcopy(message))
        record["updatedAt"] = time.time()


def set_a2a_task_artifact_text(record: dict[str, Any], text: str) -> None:
    with A2A_TASK_STORE_LOCK:
        record["artifactText"] = text
        task = record.setdefault("task", {})
        if text:
            task["artifacts"] = [
                {
                    "artifactId": f"{task['id']}-response",
                    "name": "response",
                    "description": "Text response emitted by the agent.",
                    "parts": [{"text": text, "mediaType": "text/plain"}],
                }
            ]
        else:
            task.pop("artifacts", None)
        record["updatedAt"] = time.time()


def append_a2a_task_artifact_delta(record: dict[str, Any], delta: str) -> None:
    with A2A_TASK_STORE_LOCK:
        current_text = str(record.get("artifactText") or "") + delta
    set_a2a_task_artifact_text(record, current_text)


def set_a2a_task_status(
    record: dict[str, Any],
    state: str,
    message_text: str | None = None,
    metadata_updates: dict[str, Any] | None = None,
) -> None:
    with A2A_TASK_STORE_LOCK:
        task = record.setdefault("task", {})
        status_payload: dict[str, Any] = {
            "state": state,
            "timestamp": now_iso(),
        }
        if message_text:
            status_payload["message"] = create_a2a_status_message(
                message_text,
                str(task.get("contextId") or ""),
                str(task.get("id") or ""),
            )
        task["status"] = status_payload
        if metadata_updates:
            metadata = task.setdefault("metadata", {})
            metadata.update(metadata_updates)
        record["updatedAt"] = time.time()


def a2a_task_state_from_invoke_status(status: str) -> str:
    normalized = status.strip().lower()
    if normalized == "completed":
        return "TASK_STATE_COMPLETED"
    if normalized == "approval_pending":
        return "TASK_STATE_AUTH_REQUIRED"
    if normalized == "blocked":
        return "TASK_STATE_REJECTED"
    return "TASK_STATE_WORKING"


def parse_history_length(raw_value: Any, *, field_name: str) -> int | None:
    if raw_value is None:
        return None
    try:
        history_length = int(raw_value)
    except (TypeError, ValueError) as exc:
        raise A2AJSONRPCError(JSONRPC_INVALID_PARAMS, f"{field_name} must be a non-negative integer") from exc
    if history_length < 0:
        raise A2AJSONRPCError(JSONRPC_INVALID_PARAMS, f"{field_name} must be a non-negative integer")
    return history_length


def normalize_a2a_parts(parts: Any) -> tuple[list[dict[str, Any]], str]:
    if not isinstance(parts, list) or not parts:
        raise A2AJSONRPCError(JSONRPC_INVALID_PARAMS, "message.parts must be a non-empty array")

    normalized_parts: list[dict[str, Any]] = []
    prompt_parts: list[str] = []
    for index, raw_part in enumerate(parts):
        if not isinstance(raw_part, dict):
            raise A2AJSONRPCError(JSONRPC_INVALID_PARAMS, f"message.parts[{index}] must be an object")

        normalized_part: dict[str, Any]
        if raw_part.get("text") is not None:
            normalized_part = {
                "text": str(raw_part.get("text") or ""),
                "mediaType": str(raw_part.get("mediaType") or "text/plain"),
            }
            prompt_parts.append(normalized_part["text"])
        elif "data" in raw_part:
            normalized_part = {
                "data": raw_part.get("data"),
                "mediaType": str(raw_part.get("mediaType") or "application/json"),
            }
            prompt_parts.append(json.dumps(raw_part.get("data"), ensure_ascii=False, default=str))
        else:
            raise A2AJSONRPCError(
                A2A_CONTENT_TYPE_NOT_SUPPORTED_ERROR,
                "Only text and structured data parts are supported by this A2A facade",
                {"partIndex": index},
            )

        metadata = raw_part.get("metadata")
        if isinstance(metadata, dict) and metadata:
            normalized_part["metadata"] = metadata
        filename = raw_part.get("filename")
        if isinstance(filename, str) and filename.strip():
            normalized_part["filename"] = filename.strip()

        normalized_parts.append(normalized_part)

    prompt = "\n\n".join(part for part in prompt_parts if part.strip()).strip()
    if not prompt:
        raise A2AJSONRPCError(JSONRPC_INVALID_PARAMS, "message.parts must contain at least one non-empty text or data part")

    return normalized_parts, prompt


def parse_reference_task_ids(raw_value: Any) -> list[str]:
    if raw_value is None:
        return []
    if not isinstance(raw_value, list):
        raise A2AJSONRPCError(JSONRPC_INVALID_PARAMS, "message.referenceTaskIds must be an array of strings")

    reference_task_ids: list[str] = []
    for index, item in enumerate(raw_value):
        task_id = str(item or "").strip()
        if not task_id:
            raise A2AJSONRPCError(JSONRPC_INVALID_PARAMS, f"message.referenceTaskIds[{index}] must not be blank")
        reference_task_ids.append(task_id)
    return reference_task_ids


def infer_context_from_reference_tasks(agent_name: str, namespace: str, reference_task_ids: list[str]) -> str | None:
    for task_id in reference_task_ids:
        referenced_record = get_a2a_task_record(namespace, agent_name, task_id)
        if referenced_record is not None:
            return str(referenced_record.get("task", {}).get("contextId") or "").strip() or None
    return None


def prepare_a2a_task_for_message(
    agent_name: str,
    namespace: str,
    params: dict[str, Any],
) -> tuple[dict[str, Any], str, int | None]:
    raw_message = params.get("message")
    if not isinstance(raw_message, dict):
        raise A2AJSONRPCError(JSONRPC_INVALID_PARAMS, "message is required and must be an object")

    role = str(raw_message.get("role") or "").strip().upper()
    if role not in {"ROLE_USER", "USER"}:
        raise A2AJSONRPCError(JSONRPC_INVALID_PARAMS, "message.role must be ROLE_USER")

    message_id = str(raw_message.get("messageId") or "").strip()
    if not message_id:
        raise A2AJSONRPCError(JSONRPC_INVALID_PARAMS, "message.messageId is required")

    normalized_parts, prompt = normalize_a2a_parts(raw_message.get("parts"))
    reference_task_ids = parse_reference_task_ids(raw_message.get("referenceTaskIds"))
    context_id = str(raw_message.get("contextId") or "").strip() or None
    task_id = str(raw_message.get("taskId") or "").strip() or None

    configuration = params.get("configuration") or {}
    if configuration is not None and not isinstance(configuration, dict):
        raise A2AJSONRPCError(JSONRPC_INVALID_PARAMS, "configuration must be an object when provided")
    if configuration.get("taskPushNotificationConfig") is not None:
        raise A2AJSONRPCError(
            A2A_PUSH_NOTIFICATION_NOT_SUPPORTED_ERROR,
            "Push notifications are not supported by this gateway",
        )
    history_length = parse_history_length(configuration.get("historyLength"), field_name="configuration.historyLength")

    if task_id:
        record = get_a2a_task_record(namespace, agent_name, task_id)
        if record is None:
            raise A2AJSONRPCError(
                A2A_TASK_NOT_FOUND_ERROR,
                "Task not found",
                {"taskId": task_id, "timestamp": now_iso()},
            )
        existing_context_id = str(record.get("task", {}).get("contextId") or "").strip()
        if context_id and existing_context_id != context_id:
            raise A2AJSONRPCError(JSONRPC_INVALID_PARAMS, "message.contextId does not match the referenced task")
        existing_state = str(record.get("task", {}).get("status", {}).get("state") or "TASK_STATE_UNSPECIFIED")
        if existing_state in A2A_TERMINAL_STATES:
            raise A2AJSONRPCError(
                A2A_UNSUPPORTED_OPERATION_ERROR,
                "Messages cannot be sent to tasks that are already in a terminal state",
                {"taskId": task_id, "state": existing_state},
            )
        if existing_state in {"TASK_STATE_SUBMITTED", "TASK_STATE_WORKING"}:
            raise A2AJSONRPCError(
                A2A_UNSUPPORTED_OPERATION_ERROR,
                "Messages cannot be sent to tasks that are still actively processing",
                {"taskId": task_id, "state": existing_state},
            )
        context_id = existing_context_id
    else:
        context_id = context_id or infer_context_from_reference_tasks(agent_name, namespace, reference_task_ids) or str(uuid.uuid4())
        task_id = str(uuid.uuid4())
        record = create_a2a_task_record(agent_name, namespace, context_id, task_id, context_id)
        store_a2a_task_record(record)

    normalized_message: dict[str, Any] = {
        "messageId": message_id,
        "contextId": context_id,
        "taskId": task_id,
        "role": "ROLE_USER",
        "parts": normalized_parts,
    }
    metadata = raw_message.get("metadata")
    if isinstance(metadata, dict) and metadata:
        normalized_message["metadata"] = metadata
    if reference_task_ids:
        normalized_message["referenceTaskIds"] = reference_task_ids

    append_a2a_task_history(record, normalized_message)
    return record, prompt, history_length


def public_a2a_task(record: dict[str, Any], history_length: int | None = None) -> dict[str, Any]:
    task = copy.deepcopy(record.get("task", {}))
    history = task.get("history") if isinstance(task.get("history"), list) else []
    if history_length == 0:
        task.pop("history", None)
    elif history:
        if history_length is None:
            task["history"] = history
        else:
            task["history"] = history[-history_length:]
    else:
        task.pop("history", None)

    if not task.get("artifacts"):
        task.pop("artifacts", None)
    if not task.get("metadata"):
        task.pop("metadata", None)
    if not isinstance(task.get("status"), dict):
        task["status"] = {"state": "TASK_STATE_UNSPECIFIED", "timestamp": now_iso()}
    return task


def task_status_update_event(record: dict[str, Any]) -> dict[str, Any]:
    task = record.get("task", {})
    return {
        "taskId": task.get("id"),
        "contextId": task.get("contextId"),
        "status": copy.deepcopy(task.get("status") or {}),
        "metadata": copy.deepcopy(task.get("metadata") or {}),
    }


def task_artifact_update_event(record: dict[str, Any], delta: str, *, append: bool, last_chunk: bool) -> dict[str, Any]:
    task = record.get("task", {})
    return {
        "taskId": task.get("id"),
        "contextId": task.get("contextId"),
        "artifact": {
            "artifactId": f"{task.get('id')}-response",
            "name": "response",
            "parts": [{"text": delta, "mediaType": "text/plain"}],
        },
        "append": append,
        "lastChunk": last_chunk,
        "metadata": copy.deepcopy(task.get("metadata") or {}),
    }


def apply_invoke_response_to_a2a_task(record: dict[str, Any], invoke_response: InvokeResponse) -> None:
    metadata_updates: dict[str, Any] = {
        "threadId": invoke_response.thread_id,
        "model": invoke_response.model,
        "policyName": invoke_response.policy_name,
        "status": invoke_response.status,
    }
    if invoke_response.approval_name:
        metadata_updates["approvalName"] = invoke_response.approval_name
    if invoke_response.retry_after_seconds is not None:
        metadata_updates["retryAfterSeconds"] = invoke_response.retry_after_seconds
    if invoke_response.a2a is not None:
        metadata_updates["a2a"] = invoke_response.a2a
    if invoke_response.warnings:
        metadata_updates["warnings"] = invoke_response.warnings

    task_state = a2a_task_state_from_invoke_status(invoke_response.status)
    response_text = invoke_response.response.strip()
    if response_text:
        append_a2a_task_history(
            record,
            create_a2a_history_message(
                "ROLE_AGENT",
                response_text,
                str(record.get("task", {}).get("contextId") or ""),
                str(record.get("task", {}).get("id") or ""),
            ),
        )

    if task_state == "TASK_STATE_COMPLETED":
        set_a2a_task_artifact_text(record, response_text)
        set_a2a_task_status(record, task_state, None, metadata_updates)
    else:
        set_a2a_task_artifact_text(record, "")
        set_a2a_task_status(record, task_state, response_text or invoke_response.status, metadata_updates)


def mark_a2a_task_failed(record: dict[str, Any], error_message: str) -> None:
    append_a2a_task_history(
        record,
        create_a2a_history_message(
            "ROLE_AGENT",
            error_message,
            str(record.get("task", {}).get("contextId") or ""),
            str(record.get("task", {}).get("id") or ""),
        ),
    )
    set_a2a_task_artifact_text(record, "")
    set_a2a_task_status(
        record,
        "TASK_STATE_FAILED",
        error_message,
        {"status": "failed"},
    )


async def handle_a2a_send_message(
    agent_name: str,
    namespace: str,
    params: dict[str, Any],
    request_id: Any,
    gateway_request_id: str,
) -> dict[str, Any]:
    record, prompt, history_length = prepare_a2a_task_for_message(agent_name, namespace, params)
    set_a2a_task_status(record, "TASK_STATE_WORKING", None, {"status": "working"})
    store_a2a_task_record(record)

    raw_request = SimpleNamespace(headers={"x-request-id": gateway_request_id})
    invoke_request = InvokeRequest(prompt=prompt, thread_id=str(record.get("threadId") or ""))
    try:
        invoke_response = await invoke_agent(agent_name, invoke_request, raw_request, namespace, user={})
    except HTTPException as exc:
        mark_a2a_task_failed(record, str(exc.detail))
    except Exception as exc:
        logger.exception("A2A SendMessage failed for %s/%s", namespace, agent_name)
        mark_a2a_task_failed(record, f"Agent invocation failed: {exc}")
    else:
        apply_invoke_response_to_a2a_task(record, invoke_response)

    store_a2a_task_record(record)
    return jsonrpc_success_response(request_id, {"task": public_a2a_task(record, history_length)})


async def iter_runtime_sse_events(body_iterator: Any) -> Any:
    buffer = ""
    async for chunk in body_iterator:
        if isinstance(chunk, bytes):
            buffer += chunk.decode("utf-8", errors="ignore")
        else:
            buffer += str(chunk)
        while "\n\n" in buffer:
            raw_event, buffer = buffer.split("\n\n", 1)
            event_name = "message"
            data_lines: list[str] = []
            for line in raw_event.splitlines():
                if line.startswith(":"):
                    continue
                if line.startswith("event:"):
                    event_name = line[6:].strip() or "message"
                elif line.startswith("data:"):
                    data_lines.append(line[5:].strip())
            if not data_lines:
                continue
            yield event_name, "\n".join(data_lines)


async def handle_a2a_stream_message(
    agent_name: str,
    namespace: str,
    params: dict[str, Any],
    request_id: Any,
    gateway_request_id: str,
) -> StreamingResponse:
    record, prompt, history_length = prepare_a2a_task_for_message(agent_name, namespace, params)
    set_a2a_task_status(record, "TASK_STATE_WORKING", None, {"status": "working"})
    store_a2a_task_record(record)

    raw_request = SimpleNamespace(headers={"x-request-id": gateway_request_id})
    invoke_request = InvokeRequest(prompt=prompt, thread_id=str(record.get("threadId") or ""))

    async def event_generator() -> Any:
        yielded_artifact = False
        try:
            upstream_response = await invoke_agent_stream(agent_name, invoke_request, raw_request, namespace, user={})
        except HTTPException as exc:
            mark_a2a_task_failed(record, str(exc.detail))
            yield jsonrpc_sse_message(jsonrpc_success_response(request_id, {"task": public_a2a_task(record, history_length)}))
            yield jsonrpc_sse_message(jsonrpc_success_response(request_id, {"statusUpdate": task_status_update_event(record)}))
            return
        except Exception as exc:
            logger.exception("A2A SendStreamingMessage failed to start for %s/%s", namespace, agent_name)
            mark_a2a_task_failed(record, f"Agent invocation failed: {exc}")
            yield jsonrpc_sse_message(jsonrpc_success_response(request_id, {"task": public_a2a_task(record, history_length)}))
            yield jsonrpc_sse_message(jsonrpc_success_response(request_id, {"statusUpdate": task_status_update_event(record)}))
            return

        yield jsonrpc_sse_message(jsonrpc_success_response(request_id, {"task": public_a2a_task(record, history_length)}))

        try:
            async for event_name, raw_data in iter_runtime_sse_events(upstream_response.body_iterator):
                try:
                    payload = json.loads(raw_data)
                except json.JSONDecodeError as exc:
                    mark_a2a_task_failed(record, f"Invalid upstream stream payload: {exc}")
                    yield jsonrpc_sse_message(jsonrpc_success_response(request_id, {"statusUpdate": task_status_update_event(record)}))
                    return

                if event_name == "response.delta":
                    delta = str(payload.get("delta") or "")
                    if not delta:
                        continue
                    append_a2a_task_artifact_delta(record, delta)
                    yielded_artifact = True
                    store_a2a_task_record(record)
                    yield jsonrpc_sse_message(
                        jsonrpc_success_response(
                            request_id,
                            {"artifactUpdate": task_artifact_update_event(record, delta, append=True, last_chunk=False)},
                        )
                    )
                    continue

                if event_name == "response.completed":
                    response_status = str(payload.get("status") or "completed")
                    metadata_updates: dict[str, Any] = {
                        "threadId": str(record.get("threadId") or ""),
                        "status": response_status,
                    }
                    if payload.get("policy_name"):
                        metadata_updates["policyName"] = payload.get("policy_name")
                    if payload.get("approval_name"):
                        metadata_updates["approvalName"] = payload.get("approval_name")
                    if payload.get("retry_after_seconds") is not None:
                        metadata_updates["retryAfterSeconds"] = payload.get("retry_after_seconds")
                    if payload.get("a2a") is not None:
                        metadata_updates["a2a"] = payload.get("a2a")
                    warnings = payload.get("warnings")
                    if isinstance(warnings, list) and warnings:
                        metadata_updates["warnings"] = warnings

                    final_text = str(record.get("artifactText") or "")
                    task_state = a2a_task_state_from_invoke_status(response_status)
                    if final_text:
                        append_a2a_task_history(
                            record,
                            create_a2a_history_message(
                                "ROLE_AGENT",
                                final_text,
                                str(record.get("task", {}).get("contextId") or ""),
                                str(record.get("task", {}).get("id") or ""),
                            ),
                        )

                    if task_state == "TASK_STATE_COMPLETED":
                        set_a2a_task_status(record, task_state, None, metadata_updates)
                    else:
                        set_a2a_task_artifact_text(record, "")
                        set_a2a_task_status(record, task_state, final_text or response_status, metadata_updates)

                    store_a2a_task_record(record)
                    yield jsonrpc_sse_message(jsonrpc_success_response(request_id, {"statusUpdate": task_status_update_event(record)}))
                    return

                if event_name == "response.error":
                    error_message = str(payload.get("error") or "Agent invocation failed")
                    mark_a2a_task_failed(record, error_message)
                    store_a2a_task_record(record)
                    yield jsonrpc_sse_message(jsonrpc_success_response(request_id, {"statusUpdate": task_status_update_event(record)}))
                    return
        except Exception as exc:
            logger.exception("A2A SendStreamingMessage failed while translating the upstream stream")
            mark_a2a_task_failed(record, f"Agent invocation failed: {exc}")
            store_a2a_task_record(record)
            yield jsonrpc_sse_message(jsonrpc_success_response(request_id, {"statusUpdate": task_status_update_event(record)}))

    return StreamingResponse(event_generator(), media_type="text/event-stream")


def handle_a2a_get_task(agent_name: str, namespace: str, params: dict[str, Any], request_id: Any) -> dict[str, Any]:
    task_id = str(params.get("id") or "").strip()
    if not task_id:
        raise A2AJSONRPCError(JSONRPC_INVALID_PARAMS, "params.id is required")
    history_length = parse_history_length(params.get("historyLength"), field_name="historyLength")
    record = get_a2a_task_record(namespace, agent_name, task_id)
    if record is None:
        raise A2AJSONRPCError(
            A2A_TASK_NOT_FOUND_ERROR,
            "Task not found",
            {"taskId": task_id, "timestamp": now_iso()},
        )
    return jsonrpc_success_response(request_id, {"task": public_a2a_task(record, history_length)})


def build_agent_spec(
    body: CreateAgentRequest | UpdateAgentRequest,
    existing_spec: dict[str, Any] | None = None,
) -> dict[str, Any]:
    existing_runtime = (existing_spec or {}).get("runtime") or {}
    existing_runtime_kind = None
    existing_goose_config_files: Any = None
    existing_a2a_config: Any = (existing_spec or {}).get("a2a")
    if isinstance(existing_runtime, dict):
        existing_runtime_kind = existing_runtime.get("kind")
        existing_goose = existing_runtime.get("goose") or {}
        if isinstance(existing_goose, dict):
            existing_goose_config_files = existing_goose.get("configFiles")

    runtime_kind = normalized_runtime_kind(getattr(body, "runtime_kind", None) or existing_runtime_kind)
    requested_goose_config_files = getattr(body, "goose_config_files", None)
    if requested_goose_config_files is None:
        goose_config_files = parse_goose_config_files(
            existing_goose_config_files,
            source="existing runtime.goose.configFiles",
        )
    else:
        goose_config_files = parse_goose_config_files(
            requested_goose_config_files,
            source="goose_config_files",
        )

    requested_a2a_config = getattr(body, "a2a_config", None)
    if requested_a2a_config is None:
        a2a_config = parse_a2a_agent_config(existing_a2a_config, source="existing spec.a2a")
    else:
        a2a_config = parse_a2a_agent_config(requested_a2a_config, source="a2a_config")

    if runtime_kind != "goose" and goose_config_files:
        raise HTTPException(
            status_code=400,
            detail="goose_config_files is only supported when runtime_kind is 'goose'",
        )

    spec: dict[str, Any] = {
        "model": body.model.strip(),
        "systemPrompt": body.system_prompt.strip(),
        "enableGVisor": body.enable_gvisor,
        "storage": {"size": (body.storage_size or "1Gi").strip() or "1Gi"},
        "mcpServers": [server.strip() for server in body.mcp_servers if server.strip()],
        "mcpSidecars": body.mcp_sidecars,
        "runtime": {"kind": runtime_kind},
    }
    if a2a_config:
        spec["a2a"] = a2a_config
    if runtime_kind == "goose" and goose_config_files:
        spec["runtime"]["goose"] = {"configFiles": goose_config_files}
    if body.policy_ref and body.policy_ref.strip():
        spec["policyRef"] = body.policy_ref.strip()
    return spec


def build_workflow_spec(body: WorkflowRequest | WorkflowUpdateRequest) -> dict[str, Any]:
    steps = []
    for step in body.steps:
        step_spec: dict[str, Any] = {
            "name": step.name.strip(),
            "agentRef": step.agent_ref.strip(),
            "prompt": step.prompt,
            "dependsOn": [
                dependency.strip()
                for dependency in step.depends_on
                if dependency.strip()
            ],
            "requireApproval": step.require_approval,
        }
        if isinstance(step.execution, dict) and step.execution:
            step_spec["execution"] = step.execution
        steps.append(step_spec)

    return {
        "description": body.description.strip(),
        "input": body.input.strip(),
        "messageBus": body.message_bus,
        "steps": steps,
    }


def build_eval_spec(body: EvalRequest | EvalUpdateRequest) -> dict[str, Any]:
    spec: dict[str, Any] = {
        "agentRef": body.agent_ref.strip(),
        "testSuite": [
            {
                "input": test_case.input,
                "expectedOutput": test_case.expected_output,
                "metrics": test_case.metrics,
            }
            for test_case in body.test_suite
        ],
        "failureThreshold": body.failure_threshold,
    }
    if body.schedule and body.schedule.strip():
        spec["schedule"] = body.schedule.strip()
    return spec


def list_custom_resources(plural: str, namespace: str) -> list[dict[str, Any]]:
    try:
        from kubernetes import client

        result = client.CustomObjectsApi().list_namespaced_custom_object(
            group=RESOURCE_GROUP,
            version=RESOURCE_VERSION,
            namespace=namespace,
            plural=plural,
        )
        return result.get("items", [])
    except Exception as exc:
        logger.error("Failed to list %s: %s", plural, exc)
        raise HTTPException(status_code=502, detail=f"Failed to list {plural}: {exc}") from exc


def read_custom_resource(plural: str, name: str, namespace: str, label: str) -> dict[str, Any]:
    try:
        from kubernetes import client

        return client.CustomObjectsApi().get_namespaced_custom_object(
            group=RESOURCE_GROUP,
            version=RESOURCE_VERSION,
            namespace=namespace,
            plural=plural,
            name=name,
        )
    except Exception as exc:
        raise HTTPException(status_code=404, detail=f"{label} '{name}' not found: {exc}") from exc


def create_custom_resource(plural: str, namespace: str, name: str, spec: dict[str, Any]) -> dict[str, Any]:
    try:
        from kubernetes import client

        return client.CustomObjectsApi().create_namespaced_custom_object(
            group=RESOURCE_GROUP,
            version=RESOURCE_VERSION,
            namespace=namespace,
            plural=plural,
            body={
                "apiVersion": f"{RESOURCE_GROUP}/{RESOURCE_VERSION}",
                "kind": RESOURCE_KIND_BY_PLURAL[plural],
                "metadata": {
                    "name": name,
                    "namespace": namespace,
                },
                "spec": spec,
            },
        )
    except Exception as exc:
        status = getattr(exc, "status", None)
        if status == 409:
            raise HTTPException(status_code=409, detail=f"Resource '{name}' already exists") from exc
        raise HTTPException(status_code=502, detail=f"Failed to create resource '{name}': {exc}") from exc


def replace_custom_resource_spec(plural: str, name: str, namespace: str, spec: dict[str, Any]) -> dict[str, Any]:
    try:
        from kubernetes import client

        api = client.CustomObjectsApi()
        current = api.get_namespaced_custom_object(
            group=RESOURCE_GROUP,
            version=RESOURCE_VERSION,
            namespace=namespace,
            plural=plural,
            name=name,
        )
        return api.replace_namespaced_custom_object(
            group=RESOURCE_GROUP,
            version=RESOURCE_VERSION,
            namespace=namespace,
            plural=plural,
            name=name,
            body={
                "apiVersion": f"{RESOURCE_GROUP}/{RESOURCE_VERSION}",
                "kind": RESOURCE_KIND_BY_PLURAL[plural],
                "metadata": {
                    "name": name,
                    "namespace": namespace,
                    "resourceVersion": current.get("metadata", {}).get("resourceVersion"),
                },
                "spec": spec,
            },
        )
    except Exception as exc:
        status = getattr(exc, "status", None)
        if status == 404:
            raise HTTPException(status_code=404, detail=f"Resource '{name}' was not found") from exc
        raise HTTPException(status_code=502, detail=f"Failed to update resource '{name}': {exc}") from exc


def delete_custom_resource(plural: str, name: str, namespace: str, label: str) -> None:
    try:
        from kubernetes import client

        client.CustomObjectsApi().delete_namespaced_custom_object(
            group=RESOURCE_GROUP,
            version=RESOURCE_VERSION,
            namespace=namespace,
            plural=plural,
            name=name,
        )
    except Exception as exc:
        status = getattr(exc, "status", None)
        if status == 404:
            raise HTTPException(status_code=404, detail=f"{label} '{name}' not found") from exc
        raise HTTPException(status_code=502, detail=f"Failed to delete {label} '{name}': {exc}") from exc


def policy_info_from_resource(policy: dict[str, Any]) -> PolicyInfo:
    metadata = policy.get("metadata", {})
    return PolicyInfo(
        name=metadata.get("name", ""),
        namespace=metadata.get("namespace", "default"),
    )


def agent_info_from_resource(agent: dict[str, Any]) -> AgentInfo:
    metadata = agent.get("metadata", {})
    spec = agent.get("spec", {})
    runtime_spec = spec.get("runtime") or {}
    runtime_kind = "langgraph"
    if isinstance(runtime_spec, dict):
        runtime_kind = str(runtime_spec.get("kind") or "langgraph")
    namespace = metadata.get("namespace", "default")
    name = metadata.get("name", "")
    return AgentInfo(
        name=name,
        model=spec.get("model", "unknown"),
        namespace=namespace,
        status=get_agent_status(name, namespace),
        runtime_kind=runtime_kind,
    )


def agent_detail_from_resource(agent: dict[str, Any]) -> AgentDetail:
    info = agent_info_from_resource(agent)
    spec = agent.get("spec", {})
    metadata = agent.get("metadata", {})
    storage = spec.get("storage", {}) if isinstance(spec.get("storage"), dict) else {}
    runtime = spec.get("runtime") if isinstance(spec.get("runtime"), dict) else {}
    goose_runtime = runtime.get("goose") if isinstance(runtime.get("goose"), dict) else {}
    return AgentDetail(
        **info.model_dump(),
        system_prompt=spec.get("systemPrompt", "") or "",
        policy_ref=spec.get("policyRef"),
        storage_size=storage.get("size"),
        enable_gvisor=bool(spec.get("enableGVisor", False)),
        mcp_servers=spec.get("mcpServers") or [],
        mcp_sidecars=spec.get("mcpSidecars") or [],
        a2a_config=parse_a2a_agent_config(spec.get("a2a"), source="AIAgent.spec.a2a"),
        goose_config_files=parse_goose_config_files(
            goose_runtime.get("configFiles"),
            source="AIAgent.spec.runtime.goose.configFiles",
        ),
        created_at=metadata.get("creationTimestamp"),
    )


def policy_a2a_targets_from_resource(policy: dict[str, Any]) -> list[dict[str, str]]:
    spec = policy.get("spec") if isinstance(policy.get("spec"), dict) else {}
    config = parse_a2a_policy_config(spec.get("a2a"), source="AgentPolicy.spec.a2a")
    return list(config.get("allowedTargets") or [])


def discover_agent_peers(agent_name: str, namespace: str) -> AgentDiscoveryResponse:
    caller_agent = read_agent(agent_name, namespace)
    caller_spec = caller_agent.get("spec") if isinstance(caller_agent.get("spec"), dict) else {}
    policy_ref = str(caller_spec.get("policyRef") or "").strip() or None
    allowed_targets: list[dict[str, str]] = []
    if policy_ref:
        allowed_targets = policy_a2a_targets_from_resource(
            read_custom_resource("agentpolicies", policy_ref, namespace, "Policy")
        )

    caller_identity = (namespace, agent_name)
    peers: list[AgentDiscoveryPeer] = []
    for target in allowed_targets:
        target_name = target["name"]
        target_namespace = target["namespace"]
        try:
            target_agent = read_agent(target_name, target_namespace)
        except HTTPException as exc:
            if exc.status_code == 404:
                peers.append(
                    AgentDiscoveryPeer(
                        name=target_name,
                        namespace=target_namespace,
                        exists=False,
                        accepts_caller=False,
                        reachable=False,
                        reason="Target agent does not exist.",
                    )
                )
                continue
            raise

        target_info = agent_info_from_resource(target_agent)
        target_spec = target_agent.get("spec") if isinstance(target_agent.get("spec"), dict) else {}
        target_allowed_callers = parse_a2a_agent_config(
            target_spec.get("a2a"),
            source=f"AIAgent[{target_namespace}/{target_name}].spec.a2a",
        ).get("allowedCallers", [])
        allowed_callers = {(item["namespace"], item["name"]) for item in target_allowed_callers}
        accepts_caller = caller_identity in allowed_callers
        reachable = accepts_caller and target_info.status == "running"

        reason: str | None = None
        if not accepts_caller:
            reason = (
                f"Target agent does not list {namespace}/{agent_name} in spec.a2a.allowedCallers."
            )
        elif target_info.status != "running":
            reason = f"Target agent status is '{target_info.status}'."

        peers.append(
            AgentDiscoveryPeer(
                name=target_info.name,
                namespace=target_info.namespace,
                exists=True,
                model=target_info.model,
                status=target_info.status,
                runtime_kind=target_info.runtime_kind,
                accepts_caller=accepts_caller,
                reachable=reachable,
                reason=reason,
            )
        )

    return AgentDiscoveryResponse(
        agent_name=agent_name,
        namespace=namespace,
        policy_ref=policy_ref,
        peers=peers,
    )


def workflow_info_from_resource(workflow: dict[str, Any]) -> WorkflowInfo:
    metadata = workflow.get("metadata", {})
    spec = workflow.get("spec", {})
    status = workflow.get("status", {})
    return WorkflowInfo(
        name=metadata.get("name", ""),
        namespace=metadata.get("namespace", "default"),
        description=spec.get("description", "") or "",
        input=spec.get("input", "") or "",
        message_bus=spec.get("messageBus", "in-memory") or "in-memory",
        steps=[
            WorkflowStepRequest(
                name=step.get("name", ""),
                agent_ref=step.get("agentRef", ""),
                prompt=step.get("prompt", "") or "",
                depends_on=step.get("dependsOn") or [],
                require_approval=bool(step.get("requireApproval", False)),
                execution=step.get("execution") or None,
            )
            for step in spec.get("steps") or []
        ],
        phase=status.get("phase", "pending") or "pending",
        current_step=status.get("currentStep", "") or "",
        observed_generation=status.get("observedGeneration"),
        summary=status.get("summary"),
        artifact_ref=status.get("artifactRef"),
        journal_ref=status.get("journalRef"),
        pending_approval=status.get("pendingApproval"),
        run_id=status.get("runId"),
        step_states=status.get("stepStates"),
        worker_job=status.get("workerJob"),
        created_at=metadata.get("creationTimestamp"),
    )


def eval_info_from_resource(eval_resource: dict[str, Any]) -> EvalInfo:
    metadata = eval_resource.get("metadata", {})
    spec = eval_resource.get("spec", {})
    status = eval_resource.get("status", {})
    return EvalInfo(
        name=metadata.get("name", ""),
        namespace=metadata.get("namespace", "default"),
        agent_ref=spec.get("agentRef", ""),
        schedule=spec.get("schedule"),
        test_suite=[
            EvalTestCaseRequest(
                input=test_case.get("input", ""),
                expected_output=test_case.get("expectedOutput", "") or "",
                metrics=test_case.get("metrics") or [],
            )
            for test_case in spec.get("testSuite") or []
        ],
        failure_threshold=spec.get("failureThreshold") or {},
        phase=status.get("phase", "pending") or "pending",
        passed=status.get("passed"),
        last_run=status.get("lastRun"),
        observed_generation=status.get("observedGeneration"),
        summary=status.get("summary"),
        artifact_ref=status.get("artifactRef"),
        worker_job=status.get("workerJob"),
        created_at=metadata.get("creationTimestamp"),
    )


def get_agents(namespace: str = "default") -> list[dict[str, Any]]:
    try:
        from kubernetes import client

        api = client.CustomObjectsApi()
        result = api.list_namespaced_custom_object(
            group="sandbox.enterprise.ai",
            version="v1alpha1",
            namespace=namespace,
            plural="aiagents",
        )
        return result.get("items", [])
    except Exception as exc:
        logger.error("Failed to list agents: %s", exc)
        return []


def get_policies(namespace: str = "default") -> list[dict[str, Any]]:
    try:
        from kubernetes import client

        result = client.CustomObjectsApi().list_namespaced_custom_object(
            group=RESOURCE_GROUP,
            version=RESOURCE_VERSION,
            namespace=namespace,
            plural="agentpolicies",
        )
        return result.get("items", [])
    except Exception as exc:
        logger.error("Failed to list policies: %s", exc)
        return []


def read_agent(agent_name: str, namespace: str) -> dict[str, Any]:
    try:
        from kubernetes import client

        return client.CustomObjectsApi().get_namespaced_custom_object(
            group="sandbox.enterprise.ai",
            version="v1alpha1",
            namespace=namespace,
            plural="aiagents",
            name=agent_name,
        )
    except Exception as exc:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_name}' not found: {exc}") from exc


def create_agent_resource(body: CreateAgentRequest, namespace: str) -> dict[str, Any]:
    spec = build_agent_spec(body)
    validate_agent_runtime_compatibility(spec)

    try:
        from kubernetes import client

        resource_body: dict[str, Any] = {
            "apiVersion": f"{RESOURCE_GROUP}/{RESOURCE_VERSION}",
            "kind": "AIAgent",
            "metadata": {
                "name": body.name,
                "namespace": namespace,
            },
            "spec": spec,
        }

        return client.CustomObjectsApi().create_namespaced_custom_object(
            group=RESOURCE_GROUP,
            version=RESOURCE_VERSION,
            namespace=namespace,
            plural="aiagents",
            body=resource_body,
        )
    except Exception as exc:
        if getattr(exc, "status", None) == 409:
            raise HTTPException(status_code=409, detail=f"Agent '{body.name}' already exists") from exc
        raise HTTPException(status_code=502, detail=f"Failed to create agent '{body.name}': {exc}") from exc


def read_approval(approval_name: str, namespace: str) -> dict[str, Any]:
    try:
        from kubernetes import client

        return client.CustomObjectsApi().get_namespaced_custom_object(
            group="sandbox.enterprise.ai",
            version="v1alpha1",
            namespace=namespace,
            plural="agentapprovals",
            name=approval_name,
        )
    except Exception as exc:
        raise HTTPException(status_code=404, detail=f"Approval '{approval_name}' not found: {exc}") from exc


def list_agent_pods(agent_name: str, namespace: str) -> list[Any]:
    try:
        from kubernetes import client

        pods = client.CoreV1Api().list_namespaced_pod(
            namespace=namespace,
            label_selector=f"app=ai-agent,agent-name={agent_name}",
        )

        def pod_sort_key(item: Any) -> float:
            metadata = getattr(item, "metadata", None)
            creation_timestamp = getattr(metadata, "creation_timestamp", None)
            if creation_timestamp is None:
                return 0.0
            return creation_timestamp.timestamp()

        return sorted(
            pods.items,
            key=pod_sort_key,
            reverse=True,
        )
    except Exception:
        return []


def get_agent_status(agent_name: str, namespace: str) -> str:
    pods = list_agent_pods(agent_name, namespace)
    if not pods:
        return "unknown"

    pod = pods[0]
    return str(getattr(pod.status, "phase", "Unknown") or "Unknown").lower()


async def load_jwks() -> list[dict[str, Any]]:
    if JWKS_CACHE["expires_at"] > time.time():
        return JWKS_CACHE["keys"]

    if not OIDC_JWKS_URL:
        raise HTTPException(status_code=503, detail="OIDC JWKS URL is not configured")

    async with httpx.AsyncClient(timeout=OIDC_JWKS_TIMEOUT_SECONDS) as client:
        response = await client.get(OIDC_JWKS_URL)
        response.raise_for_status()
        keys = response.json().get("keys", [])

    JWKS_CACHE.update({"keys": keys, "expires_at": time.time() + 300})
    return keys


def validate_claims(claims: dict[str, Any]) -> None:
    now = int(time.time())
    if claims.get("exp") is not None and now >= int(claims["exp"]):
        raise HTTPException(status_code=401, detail="Token has expired")
    if claims.get("nbf") is not None and now < int(claims["nbf"]):
        raise HTTPException(status_code=401, detail="Token is not active yet")
    if OIDC_ISSUER and claims.get("iss") != OIDC_ISSUER:
        raise HTTPException(status_code=401, detail="Token issuer is invalid")
    if OIDC_AUDIENCE:
        audience = claims.get("aud")
        valid = audience == OIDC_AUDIENCE or (
            isinstance(audience, list) and OIDC_AUDIENCE in audience
        )
        if not valid:
            raise HTTPException(status_code=401, detail="Token audience is invalid")


async def verify_oidc_token(token: str) -> dict[str, Any]:
    header = jwt.get_unverified_header(token)
    key_id = header.get("kid")
    keys = await load_jwks()
    key_data = next((item for item in keys if item.get("kid") == key_id), None)
    if key_data is None:
        raise HTTPException(status_code=401, detail="Unable to find a signing key for this token")

    signing_key = jwk.construct(key_data)
    message, encoded_signature = token.rsplit(".", 1)
    decoded_signature = base64url_decode(encoded_signature.encode("utf-8"))
    if not signing_key.verify(message.encode("utf-8"), decoded_signature):
        raise HTTPException(status_code=401, detail="Token signature is invalid")

    claims = jwt.get_unverified_claims(token)
    validate_claims(claims)
    return claims


def verify_shared_token(token: str) -> dict[str, Any]:
    if not SHARED_TOKEN:
        raise HTTPException(status_code=503, detail="Gateway shared token is not configured")
    if not hmac.compare_digest(token, SHARED_TOKEN):
        raise HTTPException(status_code=401, detail="Invalid bearer token")
    return {"sub": "shared-token-user"}


async def verify_token(authorization: str = Header(...)) -> dict[str, Any]:
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid authorization header")

    token = authorization[7:].strip()
    if not token:
        raise HTTPException(status_code=401, detail="Missing token")

    if AUTH_MODE == "oidc":
        return await verify_oidc_token(token)
    if AUTH_MODE == "shared_token":
        return verify_shared_token(token)
    if AUTH_MODE == "auto":
        if "." in token and OIDC_JWKS_URL:
            try:
                return await verify_oidc_token(token)
            except HTTPException as exc:
                logger.warning(
                    "OIDC token verification failed in auto mode; falling back to shared token auth: %s",
                    exc.detail,
                )
            except Exception as exc:
                logger.warning(
                    "OIDC token verification errored in auto mode; falling back to shared token auth: %s",
                    exc,
                )
        return verify_shared_token(token)
    raise HTTPException(status_code=503, detail=f"Unsupported auth mode '{AUTH_MODE}'")


def a2a_card_http_exception(error: A2AJSONRPCError) -> HTTPException:
    detail = error.message
    if error.data:
        detail = f"{detail}: {json.dumps(error.data, ensure_ascii=False, default=str)}"
    return HTTPException(status_code=400, detail=detail)


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {
        "status": "healthy",
        "gateway": "ai-agent-sandbox",
        "auth_mode": AUTH_MODE,
        "nats_url": NATS_URL,
        "qdrant_url": QDRANT_URL,
    }


@app.get("/api/ready")
def ready() -> dict[str, Any]:
    return {"status": "ready", "gateway": "ai-agent-sandbox"}


@app.get("/.well-known/agent-card.json")
async def get_well_known_agent_card(
    request: Request,
    assistant_id: str,
    namespace: str | None = None,
    authorization: str | None = Header(default=None),
):
    if authorization is not None and authorization.strip():
        await verify_token(authorization)

    try:
        agent_name, resolved_namespace = resolve_a2a_agent_reference(assistant_id, namespace)
    except A2AJSONRPCError as exc:
        raise a2a_card_http_exception(exc) from exc

    return JSONResponse(build_agent_card(agent_name, resolved_namespace, request))


@app.post("/a2a/{assistant_id}")
async def a2a_jsonrpc(
    assistant_id: str,
    raw_request: Request,
    namespace: str | None = None,
    user=Depends(verify_token),
):
    del user
    request_id: Any = None
    try:
        validate_a2a_version(raw_request)
        try:
            payload = await raw_request.json()
        except json.JSONDecodeError:
            return JSONResponse(
                jsonrpc_error_response(request_id, JSONRPC_PARSE_ERROR, "Invalid JSON payload"),
                status_code=200,
            )

        request_id, method, params = parse_jsonrpc_payload(payload)
        agent_name, resolved_namespace = resolve_a2a_agent_reference(assistant_id, namespace)
        gateway_request_id = raw_request.headers.get("x-request-id") or str(uuid.uuid4())

        if method == "message/send":
            return JSONResponse(
                await handle_a2a_send_message(
                    agent_name,
                    resolved_namespace,
                    params,
                    request_id,
                    gateway_request_id,
                ),
                status_code=200,
            )

        if method == "message/stream":
            return await handle_a2a_stream_message(
                agent_name,
                resolved_namespace,
                params,
                request_id,
                gateway_request_id,
            )

        if method == "tasks/get":
            return JSONResponse(
                handle_a2a_get_task(agent_name, resolved_namespace, params, request_id),
                status_code=200,
            )

        return JSONResponse(
            jsonrpc_error_response(
                request_id,
                JSONRPC_METHOD_NOT_FOUND,
                "Method not found",
                {"method": method},
            ),
            status_code=200,
        )
    except A2AJSONRPCError as exc:
        return JSONResponse(
            jsonrpc_error_response(request_id, exc.code, exc.message, exc.data),
            status_code=200,
        )
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
        error_code = JSONRPC_INVALID_PARAMS if exc.status_code == 404 else JSONRPC_INTERNAL_ERROR
        return JSONResponse(jsonrpc_error_response(request_id, error_code, detail), status_code=200)
    except Exception as exc:
        logger.exception("Unhandled A2A JSON-RPC error")
        return JSONResponse(
            jsonrpc_error_response(
                request_id,
                JSONRPC_INTERNAL_ERROR,
                "Internal error",
                {"detail": str(exc)},
            ),
            status_code=200,
        )


@app.get("/api/approvals/{approval_name}", response_model=ApprovalInfo)
def get_approval(
    approval_name: str,
    namespace: str = "default",
    user=Depends(verify_token),
):
    approval = read_approval(approval_name, namespace)
    spec = approval.get("spec", {})
    status = approval.get("status", {})
    return ApprovalInfo(
        name=approval.get("metadata", {}).get("name", approval_name),
        namespace=approval.get("metadata", {}).get("namespace", namespace),
        decision=status.get("decision", "pending"),
        agent_name=spec.get("agentName", ""),
        action=spec.get("action", ""),
        requested_at=spec.get("requestedAt"),
        decided_by=status.get("decidedBy"),
        decided_at=status.get("decidedAt"),
        reason=status.get("reason"),
    )


@app.get("/api/policies", response_model=list[PolicyInfo])
def list_policies(namespace: str = "default", user=Depends(verify_token)):
    del user
    return sorted(
        [policy_info_from_resource(policy) for policy in get_policies(namespace)],
        key=lambda item: item.name,
    )


@app.patch("/api/approvals/{approval_name}", response_model=ApprovalInfo)
def decide_approval(
    approval_name: str,
    body: ApprovalDecisionRequest,
    namespace: str = "default",
    user=Depends(verify_token),
):
    """Record an approve/deny decision on a pending AgentApproval.

    Patches the AgentApproval CRD status subresource with the decision,
    the deciding user identity (JWT ``sub`` claim), and a UTC timestamp.
    The agent runtime watches ``status.decision`` and resumes or blocks
    execution once the field is set.
    """
    approval = read_approval(approval_name, namespace)
    spec = approval.get("spec", {})

    decided_by = str(user.get("sub", "unknown"))
    decided_at = datetime.now(timezone.utc).isoformat()

    try:
        from kubernetes import client

        client.CustomObjectsApi().patch_namespaced_custom_object_status(
            group="sandbox.enterprise.ai",
            version="v1alpha1",
            namespace=namespace,
            plural="agentapprovals",
            name=approval_name,
            body={
                "status": {
                    "decision": body.decision,
                    "decidedBy": decided_by,
                    "decidedAt": decided_at,
                    "reason": body.reason or "",
                }
            },
        )
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Failed to record approval decision: {exc}",
        ) from exc

    return ApprovalInfo(
        name=approval_name,
        namespace=namespace,
        decision=body.decision,
        agent_name=spec.get("agentName", ""),
        action=spec.get("action", ""),
        requested_at=spec.get("requestedAt"),
        decided_by=decided_by,
        decided_at=decided_at,
        reason=body.reason,
    )


@app.get("/api/agents", response_model=list[AgentInfo])
def list_agents(namespace: str = "default", user=Depends(verify_token)):
    return sorted([
        agent_info_from_resource(agent)
        for agent in get_agents(namespace)
    ], key=lambda item: item.name)


@app.post("/api/agents", response_model=AgentDetail, status_code=201)
def create_agent(
    body: CreateAgentRequest,
    namespace: str = "default",
    user=Depends(verify_token),
):
    del user
    agent = create_agent_resource(body, namespace)
    return agent_detail_from_resource(agent)


@app.get("/api/agents/{agent_name}", response_model=AgentDetail)
def get_agent(
    agent_name: str,
    namespace: str = "default",
    user=Depends(verify_token),
):
    del user
    return agent_detail_from_resource(read_agent(agent_name, namespace))


@app.get("/api/agents/{agent_name}/discover", response_model=AgentDiscoveryResponse)
def discover_agent_targets(
    agent_name: str,
    namespace: str = "default",
    user=Depends(verify_token),
):
    del user
    return discover_agent_peers(agent_name, namespace)


@app.patch("/api/agents/{agent_name}", response_model=AgentDetail)
def update_agent(
    agent_name: str,
    body: UpdateAgentRequest,
    namespace: str = "default",
    user=Depends(verify_token),
):
    del user
    current_agent = read_agent(agent_name, namespace)
    next_spec = build_agent_spec(body, current_agent.get("spec", {}))
    validate_agent_runtime_compatibility(next_spec)
    updated = replace_custom_resource_spec(
        "aiagents",
        agent_name,
        namespace,
        next_spec,
    )
    return agent_detail_from_resource(updated)


@app.delete("/api/agents/{agent_name}", response_model=DeleteResponse)
def delete_agent(
    agent_name: str,
    namespace: str = "default",
    user=Depends(verify_token),
):
    del user
    delete_custom_resource("aiagents", agent_name, namespace, "Agent")
    return DeleteResponse(status="deleted", kind="agent", name=agent_name, namespace=namespace)


@app.get("/api/workflows", response_model=list[WorkflowInfo])
def list_workflows(namespace: str = "default", user=Depends(verify_token)):
    del user
    return sorted(
        [workflow_info_from_resource(item) for item in list_custom_resources("agentworkflows", namespace)],
        key=lambda item: item.name,
    )


@app.post("/api/workflows", response_model=WorkflowInfo, status_code=201)
def create_workflow(
    body: WorkflowRequest,
    namespace: str = "default",
    user=Depends(verify_token),
):
    del user
    created = create_custom_resource(
        "agentworkflows",
        namespace,
        body.name,
        build_workflow_spec(body),
    )
    return workflow_info_from_resource(created)


@app.get("/api/workflows/{workflow_name}", response_model=WorkflowInfo)
def get_workflow(
    workflow_name: str,
    namespace: str = "default",
    user=Depends(verify_token),
):
    del user
    return workflow_info_from_resource(read_custom_resource("agentworkflows", workflow_name, namespace, "Workflow"))


@app.patch("/api/workflows/{workflow_name}", response_model=WorkflowInfo)
def update_workflow(
    workflow_name: str,
    body: WorkflowUpdateRequest,
    namespace: str = "default",
    user=Depends(verify_token),
):
    del user
    updated = replace_custom_resource_spec("agentworkflows", workflow_name, namespace, build_workflow_spec(body))
    return workflow_info_from_resource(updated)


@app.delete("/api/workflows/{workflow_name}", response_model=DeleteResponse)
def delete_workflow(
    workflow_name: str,
    namespace: str = "default",
    user=Depends(verify_token),
):
    del user
    delete_custom_resource("agentworkflows", workflow_name, namespace, "Workflow")
    return DeleteResponse(status="deleted", kind="workflow", name=workflow_name, namespace=namespace)


@app.get("/api/evals", response_model=list[EvalInfo])
def list_evals(namespace: str = "default", user=Depends(verify_token)):
    del user
    return sorted(
        [eval_info_from_resource(item) for item in list_custom_resources("agentevals", namespace)],
        key=lambda item: item.name,
    )


@app.post("/api/evals", response_model=EvalInfo, status_code=201)
def create_eval(
    body: EvalRequest,
    namespace: str = "default",
    user=Depends(verify_token),
):
    del user
    created = create_custom_resource(
        "agentevals",
        namespace,
        body.name,
        build_eval_spec(body),
    )
    return eval_info_from_resource(created)


@app.get("/api/evals/{eval_name}", response_model=EvalInfo)
def get_eval(
    eval_name: str,
    namespace: str = "default",
    user=Depends(verify_token),
):
    del user
    return eval_info_from_resource(read_custom_resource("agentevals", eval_name, namespace, "Eval"))


@app.patch("/api/evals/{eval_name}", response_model=EvalInfo)
def update_eval(
    eval_name: str,
    body: EvalUpdateRequest,
    namespace: str = "default",
    user=Depends(verify_token),
):
    del user
    updated = replace_custom_resource_spec("agentevals", eval_name, namespace, build_eval_spec(body))
    return eval_info_from_resource(updated)


@app.delete("/api/evals/{eval_name}", response_model=DeleteResponse)
def delete_eval(
    eval_name: str,
    namespace: str = "default",
    user=Depends(verify_token),
):
    del user
    delete_custom_resource("agentevals", eval_name, namespace, "Eval")
    return DeleteResponse(status="deleted", kind="eval", name=eval_name, namespace=namespace)


@app.post("/api/agents/{agent_name}/invoke", response_model=InvokeResponse)
async def invoke_agent(
    agent_name: str,
    request: InvokeRequest,
    raw_request: Request,
    namespace: str = "default",
    user=Depends(verify_token),
):
    agent = await asyncio.to_thread(read_agent, agent_name, namespace)
    validate_invoke_runtime_compatibility(runtime_kind_from_spec(agent.get("spec", {})), request)
    request_payload = request.model_dump()
    request_id = raw_request.headers.get("x-request-id") or str(uuid.uuid4())
    async with httpx.AsyncClient(timeout=AGENT_RUNTIME_TIMEOUT_SECONDS, trust_env=False) as client:
        try:
            response = await client.post(
                f"{agent_runtime_url(agent_name, namespace)}/invoke",
                json=request_payload,
                headers={"x-request-id": request_id},
            )
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Agent invocation failed: {exc}") from exc

    if response.status_code >= 400:
        error_payload = error_payload_from_body(response.content, "Agent invocation failed")
        raise HTTPException(status_code=502, detail=f"Agent invocation failed: {error_payload['error']}")

    data = parse_json_object_response(response, context="Agent runtime /invoke")
    return InvokeResponse(
        agent_name=agent_name,
        response=data.get("response", ""),
        thread_id=data.get("thread_id", ""),
        model=data.get("model") or agent["spec"].get("model", "unknown"),
        policy_name=data.get("policy_name"),
        tool_name=data.get("tool_name"),
        tool_result=data.get("tool_result"),
        sandbox_session=data.get("sandbox_session"),
        status=data.get("status", "completed"),
        approval_name=data.get("approval_name"),
        retry_after_seconds=data.get("retry_after_seconds"),
        a2a=data.get("a2a"),
        warnings=data.get("warnings") or [],
    )


@app.post("/api/agents/{agent_name}/invoke/stream")
async def invoke_agent_stream(
    agent_name: str,
    request: InvokeRequest,
    raw_request: Request,
    namespace: str = "default",
    user=Depends(verify_token),
):
    agent = await asyncio.to_thread(read_agent, agent_name, namespace)
    validate_invoke_runtime_compatibility(runtime_kind_from_spec(agent.get("spec", {})), request)
    request_payload = request.model_dump()
    request_id = raw_request.headers.get("x-request-id") or str(uuid.uuid4())

    async def event_generator():
        try:
            async with httpx.AsyncClient(timeout=None, trust_env=False) as client:
                async with client.stream(
                    "POST",
                    f"{agent_runtime_url(agent_name, namespace)}/invoke/stream",
                    json=request_payload,
                    headers={"x-request-id": request_id},
                ) as response:
                    if response.status_code >= 400:
                        body = await response.aread()
                        yield sse_event(
                            "response.error",
                            error_payload_from_body(body, "Agent invocation failed"),
                        )
                        return
                    stream_iterator = response.aiter_text()
                    next_chunk_task = asyncio.create_task(anext(stream_iterator))
                    try:
                        while True:
                            done, _ = await asyncio.wait({next_chunk_task}, timeout=STREAM_KEEPALIVE_SECONDS)
                            if not done:
                                yield sse_keepalive_comment()
                                continue

                            try:
                                chunk = next_chunk_task.result()
                            except StopAsyncIteration:
                                break

                            if chunk:
                                yield chunk

                            next_chunk_task = asyncio.create_task(anext(stream_iterator))
                    finally:
                        try:
                            if not next_chunk_task.done():
                                next_chunk_task.cancel()
                                with contextlib.suppress(asyncio.CancelledError):
                                    await next_chunk_task
                        except NameError:
                            pass
        except Exception as exc:
            yield sse_event("response.error", {"error": str(exc)})

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.get("/api/agents/{agent_name}/logs")
def get_agent_logs(
    agent_name: str,
    namespace: str = "default",
    user=Depends(verify_token),
):
    read_agent(agent_name, namespace)
    try:
        pods = list_agent_pods(agent_name, namespace)
        if not pods:
            raise HTTPException(status_code=404, detail=f"No runtime pod found for agent '{agent_name}'")

        pod_name = str(getattr(pods[0].metadata, "name", "") or "")
        if not pod_name:
            raise HTTPException(status_code=404, detail=f"No runtime pod found for agent '{agent_name}'")

        from kubernetes import client

        logs = client.CoreV1Api().read_namespaced_pod_log(
            name=pod_name,
            namespace=namespace,
            container="agent-runtime",
            tail_lines=100,
        )
        return {"agent_name": agent_name, "logs": logs}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=404, detail=f"Could not retrieve logs: {exc}") from exc


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8080)
