"""REST API Gateway for the AI Agent Sandbox."""

import asyncio
import base64
import contextlib
import copy
import hashlib
import html
import json
import logging
import os
import re
import sys
import threading
import time
import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from urllib.parse import urlencode

import certifi
import httpx
from fastapi import Body, Cookie, Depends, FastAPI, Header, HTTPException, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse, StreamingResponse
from pydantic import BaseModel, Field, model_validator

CURRENT_DIR = Path(__file__).resolve().parent
if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))

MCP_HUB_NAMESPACE = os.getenv("MCP_HUB_NAMESPACE", "mcp-hub").strip() or "mcp-hub"
HELM_RELEASE_NAME = os.getenv("HELM_RELEASE_NAME", "kubesynth").strip() or "kubesynth"

from auth_middleware import (  # §4.1 — extracted auth middleware
    AUTH_MODE,
    OIDC_TRANSACTION_COOKIE_NAME,
    auth_configuration_payload,
    authenticate_bearer_token,
    browser_auth_enabled,
    clear_oidc_transaction_cookie,
    clear_refresh_cookie,
    ensure_namespace_access,
    ensure_role,
    issue_session_response,
    local_access_enabled,
    principal_from_local_user,
    registration_allowed,
    request_client_ip,
    safe_record_audit,
    set_oidc_transaction_cookie,
    set_refresh_cookie,
    shared_token_enabled,
    verify_token,
    verify_token_or_query,
)

from auth_store import (
    AlertHistoryRow,
    IntelligenceAlertRow,
    IntelligenceCollectorRow,
    IntelligenceScheduleRow,
    IntelligenceTaskRow,
    apply_memory_feedback,
    change_user_password,
    count_users,
    create_chat_session,
    create_local_user,
    create_mcp_connection,
    create_session_for_user,
    db_session,
    delete_chat_session,
    delete_mcp_connection,
    delete_memory_record,
    ensure_bootstrap_admin,
    get_active_user_context,
    get_chat_session_messages,
    get_mcp_connection,
    get_mcp_connection_rows_by_ids,
    get_user_by_username,
    init_database,
    is_user_locked,
    list_chat_sessions,
    list_mcp_connections,
    list_memory_records,
    list_promoted_memory_records,
    list_workflow_runs,
    login_rate_limit_key,
    login_rate_limited,
    note_login_attempt,
    purge_old_audit_logs,
    query_audit_logs,
    query_usage_detail,
    query_usage_summary,
    record_audit_log,
    record_eval_outcome_memory,
    record_failed_login,
    record_runtime_memory,
    record_usage,
    record_workflow_outcome_memory,
    record_workflow_run,
    record_workflow_run_log_archive,
    reset_failed_logins,
    revoke_refresh_token,
    rotate_refresh_session,
    save_chat_messages,
    serialize_user,
    slugify_mcp_connection_name,
    update_chat_session_title,
    update_mcp_connection,
    update_memory_record,
    update_user_fields,
    upsert_external_user,
    validate_email,
    verify_password,
)
from auth_store import (
    get_workflow_run_trace as load_workflow_run_trace,
)
from auth_store import (
    list_users as list_local_users,
)
from enterprise_auth import (
    authenticate_ldap_user,
    build_oidc_authorization_request,
    build_saml_authorization_request,
    exchange_oidc_code,
    exchange_saml_response,
    get_oidc_provider,
    get_saml_provider,
    ldap_enabled,
    saml_metadata_xml,
    sanitize_redirect_path,
)
from jwt_utils import (
    JWT_SECRET,
    REFRESH_COOKIE_NAME,
    REFRESH_TOKEN_TTL_SECONDS,
)

try:
    import yaml
except ModuleNotFoundError:  # pragma: no cover - covered by runtime packaging
    yaml = None

try:
    from pythonjsonlogger import jsonlogger as _jsonlogger  # type: ignore[import-untyped]
except ModuleNotFoundError:  # pragma: no cover
    _jsonlogger = None

try:
    from prometheus_fastapi_instrumentator import Instrumentator as _Instrumentator  # type: ignore[import-untyped]
except ModuleNotFoundError:  # pragma: no cover
    _Instrumentator = None


def _configure_logging() -> None:
    log_level = os.getenv("API_GATEWAY_LOG_LEVEL", "INFO").upper()
    handler = logging.StreamHandler()
    if os.getenv("JSON_LOGS", "true").lower() in {"1", "true"} and _jsonlogger is not None:
        handler.setFormatter(_jsonlogger.JsonFormatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    else:
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    logging.basicConfig(level=log_level, handlers=[handler], force=True)


_configure_logging()
logger = logging.getLogger("api-gateway")
_SHUTDOWN = threading.Event()
K8S_NAME_PATTERN = r"^[a-z0-9]([-a-z0-9]*[a-z0-9])?$"
K8S_NAME_RE = re.compile(K8S_NAME_PATTERN)
GIT_AUTH_METHODS = {"token", "basic", "ssh"}
GIT_PUSH_POLICIES = {"after-each-commit", "end-of-session", "on-approval", "never"}


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

    max_db_retries = int(os.getenv("DATABASE_INIT_RETRIES", "10"))
    for attempt in range(1, max_db_retries + 1):
        try:
            init_database()
            ensure_bootstrap_admin()
            logger.info("Auth database initialized successfully.")
            break
        except Exception as exc:
            if attempt < max_db_retries:
                logger.warning(
                    "Database init attempt %d/%d failed (%s), retrying in %ds...",
                    attempt,
                    max_db_retries,
                    exc,
                    attempt * 2,
                )
                await asyncio.sleep(attempt * 2)
            else:
                logger.exception("Failed to initialize auth database after %d attempts: %s", max_db_retries, exc)
                raise RuntimeError("Auth database initialization failed") from exc
    try:
        _load_collectors_from_db()
        _load_tasks_from_db()
        # Validate shared token is configured
        shared_token = os.environ.get("API_GATEWAY_SHARED_TOKEN", "")
        if not shared_token:
            logger.error("API_GATEWAY_SHARED_TOKEN is empty — authentication is not configured!")
        _scheduler_task = asyncio.create_task(_intelligence_scheduler_loop())
        yield
    finally:
        _SHUTDOWN.set()
        _scheduler_task.cancel()
        logger.info("API gateway shutting down.")


app = FastAPI(
    title="AI Agent Sandbox API",
    description="Enterprise REST API for interacting with AI Agents",
    version="1.0.0",
    lifespan=lifespan,
)

if _Instrumentator is not None:
    _Instrumentator().instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)


def cors_origins() -> list[str]:
    raw_origins = os.getenv("API_GATEWAY_CORS_ORIGINS", "").strip()
    if not raw_origins:
        return ["http://localhost:5173", "http://127.0.0.1:5173"]
    return [origin.strip() for origin in raw_origins.split(",") if origin.strip()]


app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins(),
    allow_credentials=True,
    allow_methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept", "X-Request-Id"],
)

NATS_URL = os.getenv("NATS_URL", "nats://kubesynth-nats:4222")
QDRANT_URL = os.getenv("QDRANT_URL", "http://kubesynth-qdrant:6333")
# Auth constants (AUTH_MODE, SHARED_TOKEN, etc.) moved to auth_middleware.py — §4.1
AGENT_RUNTIME_TIMEOUT_SECONDS = max(float(os.getenv("AGENT_RUNTIME_TIMEOUT_SECONDS", "360")), 1.0)
LITELLM_INTERNAL_URL = os.getenv("LITELLM_INTERNAL_URL", "").strip() or "http://kubesynth-litellm:4000"
LITELLM_MASTER_KEY = os.getenv("LITELLM_MASTER_KEY", "").strip()
LLM_SECRET_NAME = os.getenv("LLM_SECRET_NAME", "kubesynth-llm-api-keys")
PROVIDER_REGISTRY_CONFIGMAP_NAME = (
    os.getenv("PROVIDER_REGISTRY_CONFIGMAP_NAME", f"{HELM_RELEASE_NAME}-provider-registry").strip()
    or f"{HELM_RELEASE_NAME}-provider-registry"
)
PROVIDER_AUTH_SECRET_NAME = (
    os.getenv("PROVIDER_AUTH_SECRET_NAME", LLM_SECRET_NAME).strip()
    or LLM_SECRET_NAME
)
STREAM_KEEPALIVE_SECONDS = max(float(os.getenv("API_GATEWAY_STREAM_KEEPALIVE_SECONDS", "15")), 5.0)
AGENT_READ_CACHE_TTL_SECONDS = max(float(os.getenv("API_GATEWAY_AGENT_READ_CACHE_TTL_SECONDS", "2.0")), 0.0)
AGENT_READ_CACHE_MAX_ENTRIES = max(int(os.getenv("API_GATEWAY_AGENT_READ_CACHE_MAX_ENTRIES", "256")), 1)
A2A_PROTOCOL_VERSION = "1.0"
A2A_TASK_RETENTION_SECONDS = max(int(os.getenv("A2A_TASK_RETENTION_SECONDS", "3600")), 60)
A2A_PUBLIC_BASE_URL = os.getenv("API_GATEWAY_PUBLIC_BASE_URL", "").strip()
A2A_PROVIDER_ORGANIZATION = os.getenv("A2A_PROVIDER_ORGANIZATION", "kubesynthai").strip()
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
_AGENT_READ_CACHE_LOCK = threading.Lock()
_AGENT_READ_CACHE: dict[tuple[str, str], tuple[float, dict[str, Any]]] = {}
A2A_TASK_STORE: dict[tuple[str, str, str], dict[str, Any]] = {}
TEAM_CONTEXT_MAX_CHARS = max(int(os.getenv("A2A_TEAM_CONTEXT_MAX_CHARS", "4096")), 256)
MAX_SUBAGENT_FILE_CHARS = max(int(os.getenv("AGENT_MAX_SUBAGENT_FILE_CHARS", "4000")), 256)
MAX_SUBAGENT_METADATA_CHARS = max(int(os.getenv("AGENT_MAX_SUBAGENT_METADATA_CHARS", "2048")), 256)
MAX_SUBAGENTS = max(int(os.getenv("AGENT_MAX_SUBAGENTS", "6")), 1)
SUBAGENT_STRATEGIES = frozenset({"sequential", "parallel"})
MAX_AGENT_SKILL_FILES = max(int(os.getenv("AGENT_MAX_SKILL_FILES", "24")), 1)
MAX_AGENT_SKILL_FILE_PATH_CHARS = max(int(os.getenv("AGENT_MAX_SKILL_FILE_PATH_CHARS", "256")), 32)
MAX_AGENT_SKILL_FILE_CONTENT_CHARS = max(int(os.getenv("AGENT_MAX_SKILL_FILE_CONTENT_CHARS", "16000")), 512)
MAX_AGENT_SKILL_TOTAL_CHARS = max(int(os.getenv("AGENT_MAX_SKILL_TOTAL_CHARS", "64000")), 4096)
FACTORY_AGENT_NAME = "kubesynth-factory"
FACTORY_WORKFLOW_NAME = "kubesynth-factory-pipeline"
FACTORY_CONTEXT_NAME = "kubesynth-factory-context"
DEFAULT_FACTORY_MODE = "governed-bundle"
FACTORY_MODES = frozenset({"lightweight-draft", "governed-bundle", "fully-autonomous"})
FACTORY_MODE_SYSTEM_NOTES = {
    "lightweight-draft": (
        "Factory mode: lightweight-draft. Produce the fastest useful first-pass blueprint that still respects the real KubeSynth CRDs. "
        "Keep the design lean, surface assumptions explicitly, and stop at a draft artifact set without deployment execution."
    ),
    "governed-bundle": (
        "Factory mode: governed-bundle. Produce a review-ready, enterprise-grade bundle with strong prompts, supporting deliverables, and clear approval boundaries. "
        "Optimize for a governed artifact handoff rather than deployment execution."
    ),
    "fully-autonomous": (
        "Factory mode: fully-autonomous. Produce the most capable end-to-end bundle you can, with strong decomposition, rich prompts, verification guidance, and operational realism. "
        "Still respect explicit approval boundaries and current KubeSynth runtime constraints."
    ),
}
FACTORY_WORKFLOW_INPUT_RE = re.compile(
    r"^\s*\[Factory Mode\]\s*\r?\n(?P<mode>[^\r\n]+)\s*(?:\r?\n)+\[User Request\]\s*\r?\n(?P<request>[\s\S]*?)\s*$",
    re.IGNORECASE,
)


def normalize_json_object(value: Any, *, field_name: str, max_chars: int) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError(f"{field_name} must be an object when provided")

    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    if len(encoded) > max_chars:
        raise ValueError(f"{field_name} exceeds {max_chars} characters once serialized")

    normalized = json.loads(encoded)
    if not isinstance(normalized, dict):
        raise ValueError(f"{field_name} must serialize to an object")
    return normalized


def normalize_subagent_strategy(value: Any) -> str:
    strategy = str(value or "sequential").strip().lower() or "sequential"
    if strategy not in SUBAGENT_STRATEGIES:
        raise ValueError(f"subagent_strategy must be one of {', '.join(sorted(SUBAGENT_STRATEGIES))}")
    return strategy


def normalize_path_text(value: Any, *, source: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{source} must not be blank")
    if len(text) > 512:
        raise ValueError(f"{source} must not exceed 512 characters")
    return text


def normalize_factory_mode(value: Any) -> str | None:
    normalized = str(value or "").strip().lower()
    if not normalized:
        return None
    if normalized not in FACTORY_MODES:
        raise ValueError(f"factory_mode must be one of {', '.join(sorted(FACTORY_MODES))}")
    return normalized


def is_factory_agent_resource(agent_name: str, agent: dict[str, Any] | None = None) -> bool:
    if agent_name == FACTORY_AGENT_NAME:
        return True
    spec = (agent or {}).get("spec") or {}
    return str(spec.get("contextRef") or "").strip() == FACTORY_CONTEXT_NAME


def is_factory_workflow_resource(workflow_name: str, workflow_spec: dict[str, Any] | None = None) -> bool:
    if workflow_name == FACTORY_WORKFLOW_NAME:
        return True
    spec = workflow_spec or {}
    return str(spec.get("contextRef") or "").strip() == FACTORY_CONTEXT_NAME


def append_system_note(request_payload: dict[str, Any], note: str | None) -> None:
    note_text = str(note or "").strip()
    if not note_text:
        return
    existing_system = str(request_payload.get("system") or "").strip()
    request_payload["system"] = f"{existing_system}\n\n{note_text}" if existing_system else note_text


def unwrap_factory_workflow_input(raw_input: str) -> tuple[str | None, str]:
    match = FACTORY_WORKFLOW_INPUT_RE.match(raw_input or "")
    if not match:
        return None, str(raw_input or "").strip()
    try:
        mode = normalize_factory_mode(match.group("mode"))
    except ValueError:
        return None, str(raw_input or "").strip()
    request_text = str(match.group("request") or "").strip()
    return mode, request_text


def build_factory_workflow_input(user_request: str, factory_mode: str) -> str:
    return f"[Factory Mode]\n{factory_mode}\n\n[User Request]\n{user_request.strip()}"


class SubagentFileRef(BaseModel):
    path: str = Field(max_length=512)
    purpose: str | None = Field(default=None, max_length=256)
    include_content: bool = True
    max_chars: int = Field(default=MAX_SUBAGENT_FILE_CHARS, ge=128, le=MAX_SUBAGENT_FILE_CHARS)

    @model_validator(mode="after")
    def normalize_fields(self) -> "SubagentFileRef":
        self.path = normalize_path_text(self.path, source="subagents[].input_files[].path")
        self.purpose = self.purpose.strip() or None if self.purpose is not None else None
        return self


class SubagentRequest(BaseModel):
    name: str = Field(max_length=63)
    namespace: str = Field(max_length=63)
    role: str | None = Field(default=None, max_length=128)
    task: str | None = Field(default=None, max_length=12000)
    input_files: list[SubagentFileRef] = Field(default_factory=list)
    result_file_path: str | None = Field(default=None, max_length=512)
    share_sandbox_session: bool = True
    metadata: dict[str, Any] | None = None
    timeout_seconds: float | None = Field(default=None, ge=1.0)

    @model_validator(mode="after")
    def normalize_fields(self) -> "SubagentRequest":
        self.name = self.name.strip()
        self.namespace = self.namespace.strip()
        if not K8S_NAME_RE.fullmatch(self.name):
            raise ValueError("subagents[].name must be a valid lowercase Kubernetes resource name")
        if not K8S_NAME_RE.fullmatch(self.namespace):
            raise ValueError("subagents[].namespace must be a valid lowercase Kubernetes namespace name")
        self.role = self.role.strip() or None if self.role is not None else None
        self.task = self.task.strip() or None if self.task is not None else None
        self.result_file_path = (
            normalize_path_text(self.result_file_path, source="subagents[].result_file_path")
            if self.result_file_path is not None
            else None
        )
        self.metadata = normalize_json_object(
            self.metadata,
            field_name="subagents[].metadata",
            max_chars=MAX_SUBAGENT_METADATA_CHARS,
        )
        return self


class InvokeRequest(BaseModel):
    prompt: str = ""
    thread_id: str | None = None
    model: str | None = None
    system: str | None = None
    factory_mode: str | None = Field(default=None, max_length=32)
    require_approval: bool = False
    approval_action: str | None = None
    tool_name: str = ""
    tool_args: dict[str, Any] = Field(default_factory=dict)
    sandbox_session: dict[str, Any] | None = None
    mcp_server: str | None = None
    a2a_target_agent: str | None = Field(default=None, max_length=63)
    a2a_target_namespace: str | None = Field(default=None, max_length=63)
    a2a_timeout_seconds: float | None = Field(default=None, ge=1.0)
    caller_agent_name: str | None = Field(default=None, max_length=63)
    caller_agent_namespace: str | None = Field(default=None, max_length=63)
    parent_thread_id: str | None = Field(default=None, max_length=128)
    caller_request_id: str | None = Field(default=None, max_length=128)
    team_context: dict[str, Any] | None = None
    subagents: list[SubagentRequest] = Field(default_factory=list)
    subagent_strategy: str = Field(default="sequential", max_length=16)
    debug: bool = False
    no_session: bool = False
    max_turns: int | None = None
    working_directory: str | None = None
    output_format: str | None = Field(default=None, max_length=32)
    output_schema: dict[str, Any] | None = None
    max_retries: int | None = Field(default=None)
    structured_output_retry_count: int | None = Field(default=None)
    autonomous: bool = True
    builtin_extensions: list[str] = Field(default_factory=list)
    stdio_extensions: list[str] = Field(default_factory=list)
    streamable_http_extensions: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def normalize_fields(self) -> "InvokeRequest":
        self.prompt = self.prompt.strip()
        self.thread_id = self.thread_id.strip() or None if self.thread_id is not None else None
        self.model = self.model.strip() or None if self.model is not None else None
        self.system = self.system.strip() or None if self.system is not None else None
        self.factory_mode = normalize_factory_mode(self.factory_mode)
        self.approval_action = self.approval_action.strip() or None if self.approval_action is not None else None
        self.tool_name = self.tool_name.strip()
        self.mcp_server = self.mcp_server.strip() or None if self.mcp_server is not None else None
        self.a2a_target_agent = self.a2a_target_agent.strip() or None if self.a2a_target_agent is not None else None
        self.a2a_target_namespace = (
            self.a2a_target_namespace.strip() or None if self.a2a_target_namespace is not None else None
        )
        self.caller_agent_name = self.caller_agent_name.strip() or None if self.caller_agent_name is not None else None
        self.caller_agent_namespace = (
            self.caller_agent_namespace.strip() or None if self.caller_agent_namespace is not None else None
        )
        self.parent_thread_id = self.parent_thread_id.strip() or None if self.parent_thread_id is not None else None
        self.caller_request_id = self.caller_request_id.strip() or None if self.caller_request_id is not None else None
        self.working_directory = self.working_directory.strip() or None if self.working_directory is not None else None
        self.output_format = self.output_format.strip().lower() or None if self.output_format is not None else None
        if self.output_schema is not None and not isinstance(self.output_schema, dict):
            raise ValueError("output_schema must be a JSON object")
        self.builtin_extensions = [str(item).strip() for item in self.builtin_extensions if str(item).strip()]
        self.stdio_extensions = [str(item).strip() for item in self.stdio_extensions if str(item).strip()]
        self.streamable_http_extensions = [
            str(item).strip() for item in self.streamable_http_extensions if str(item).strip()
        ]
        self.subagent_strategy = normalize_subagent_strategy(self.subagent_strategy)
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
        if self.subagents:
            if len(self.subagents) > MAX_SUBAGENTS:
                raise ValueError(f"subagents cannot exceed {MAX_SUBAGENTS} entries")
            if self.tool_name:
                raise ValueError("subagents cannot be combined with tool_name")
            if self.mcp_server:
                raise ValueError("subagents cannot be combined with mcp_server")
            if self.a2a_target_agent or self.a2a_target_namespace:
                raise ValueError("subagents cannot be combined with a2a_target_*")
            if not self.prompt and not any(item.task for item in self.subagents):
                raise ValueError("prompt must not be blank when subagents do not provide explicit tasks")
        if self.caller_agent_name or self.caller_agent_namespace:
            if not self.caller_agent_name or not self.caller_agent_namespace:
                raise ValueError("caller_agent_name and caller_agent_namespace must be provided together")
            if not K8S_NAME_RE.fullmatch(self.caller_agent_name):
                raise ValueError("caller_agent_name must be a valid lowercase Kubernetes resource name")
            if not K8S_NAME_RE.fullmatch(self.caller_agent_namespace):
                raise ValueError("caller_agent_namespace must be a valid lowercase Kubernetes namespace name")
        self.team_context = normalize_json_object(
            self.team_context,
            field_name="team_context",
            max_chars=TEAM_CONTEXT_MAX_CHARS,
        )
        return self


class InvokeResponse(BaseModel):
    agent_name: str
    response: str
    thread_id: str
    model: str
    policy_name: str | None = None
    tool_name: str | None = None
    tool_result: Any = None
    sandbox_session: dict[str, Any] | None = None
    status: str = "completed"
    approval_name: str | None = None
    retry_after_seconds: int | None = None
    a2a: dict[str, Any] | None = None
    subagents: dict[str, Any] | None = None
    warnings: list[str] = Field(default_factory=list)
    artifacts: list[dict[str, Any]] = Field(default_factory=list)
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] | None = None


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
    runtime_kind: str = "unknown"


class PolicyInfo(BaseModel):
    name: str
    namespace: str
    input_guardrails: dict[str, Any] = Field(default_factory=dict)
    output_guardrails: dict[str, Any] = Field(default_factory=dict)
    allowed_models: list[str] = Field(default_factory=list)
    allowed_mcp_servers: list[str] = Field(default_factory=list)
    mcp_require_hitl: bool = True
    tool_policy: dict[str, Any] = Field(default_factory=dict)
    memory_policy: dict[str, Any] = Field(default_factory=dict)


class MemoryRecordInfo(BaseModel):
    id: int
    namespace: str
    agent_name: str
    session_id: str | None = None
    memory_type: str
    topic: str | None = None
    promoted: bool = False
    score: float = 0.0
    promote_reason: str | None = None
    content: str
    detail_json: dict[str, Any] | None = None
    username: str | None = None
    created_at: str | None = None


class MemoryRecordUpdateRequest(BaseModel):
    promoted: bool | None = None
    topic: str | None = None
    content: str | None = None


def _normalize_memory_policy(memory_policy: dict[str, Any] | None) -> dict[str, Any]:
    raw = memory_policy or {}
    allowed_types = raw.get("allowedMemoryTypes") if isinstance(raw.get("allowedMemoryTypes"), list) else []
    return {
        "maxInjectedMemories": max(int(raw.get("maxInjectedMemories", 5) or 0), 0),
        "maxInjectedChars": max(int(raw.get("maxInjectedChars", 1200) or 0), 0),
        "allowedMemoryTypes": [str(item).strip() for item in allowed_types if str(item).strip()],
        "autoPromote": bool(raw.get("autoPromote", False)),
    }


def _tokenize_for_memory_ranking(value: str) -> set[str]:
    return {token for token in re.findall(r"[a-zA-Z0-9_./-]{3,}", value.lower()) if token}


def rank_promoted_memory_records(
    prompt: str,
    memory_records: list[dict[str, Any]],
    *,
    memory_policy: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    policy = _normalize_memory_policy(memory_policy)
    if policy["maxInjectedMemories"] == 0 or policy["maxInjectedChars"] == 0:
        return []

    prompt_tokens = _tokenize_for_memory_ranking(prompt)
    allowed_types = set(policy["allowedMemoryTypes"])
    ranked: list[tuple[float, dict[str, Any]]] = []
    now_ts = time.time()
    for record in memory_records:
        topic = str(record.get("topic") or record.get("memory_type") or "memory").strip()
        content = str(record.get("content") or "").strip()
        if not content:
            continue
        if allowed_types and topic not in allowed_types and str(record.get("memory_type") or "") not in allowed_types:
            continue
        record_tokens = _tokenize_for_memory_ranking(f"{topic} {content}")
        overlap = len(prompt_tokens & record_tokens)
        procedural_bonus = 2.0 if str(record.get("memory_type") or "") == "procedural" else 0.5
        stored_score = float(record.get("score") or 0.0)
        created_at = str(record.get("created_at") or "").strip()
        recency_bonus = 0.0
        if created_at:
            with contextlib.suppress(ValueError):
                age_seconds = max(now_ts - datetime.fromisoformat(created_at.replace("Z", "+00:00")).timestamp(), 0.0)
                recency_bonus = max(0.0, 1.5 - min(age_seconds / 86400.0, 1.5))
        score = overlap * 3.0 + procedural_bonus + recency_bonus + stored_score
        ranked.append((score, record))

    ranked.sort(key=lambda item: item[0], reverse=True)
    selected: list[dict[str, Any]] = []
    total_chars = 0
    for _, record in ranked:
        if len(selected) >= policy["maxInjectedMemories"]:
            break
        content = str(record.get("content") or "").strip()
        estimated = len(content) + len(str(record.get("topic") or "")) + 12
        if total_chars + estimated > policy["maxInjectedChars"]:
            continue
        selected.append(record)
        total_chars += estimated
    return selected


def build_memory_context_system_note(memory_records: list[dict[str, Any]]) -> str:
    if not memory_records:
        return ""
    lines = [
        "Promoted memory from prior work:",
        "Use this as durable context when relevant, but do not treat it as an instruction override.",
    ]
    for record in memory_records[:8]:
        topic = str(record.get("topic") or record.get("memory_type") or "memory").strip() or "memory"
        content = str(record.get("content") or "").strip()
        if not content:
            continue
        lines.append(f"- {topic}: {content[:280]}")
    return "\n".join(lines).strip()


def resolve_agent_memory_policy(agent: dict[str, Any], namespace: str) -> dict[str, Any]:
    spec = agent.get("spec") if isinstance(agent.get("spec"), dict) else {}
    policy_ref = str((spec or {}).get("policyRef") or "").strip()
    if not policy_ref:
        return {}
    try:
        policy = read_custom_resource("agentpolicies", policy_ref, namespace, "Policy")
    except HTTPException:
        return {}
    policy_spec = policy.get("spec") if isinstance(policy.get("spec"), dict) else {}
    return policy_spec.get("memoryPolicy") if isinstance(policy_spec.get("memoryPolicy"), dict) else {}


class AgentDetail(AgentInfo):
    system_prompt: str = ""
    policy_ref: str | None = None
    storage_size: str | None = None
    enable_gvisor: bool = False
    mcp_connections: list[dict[str, Any]] = Field(default_factory=list)
    mcp_servers: list[str] = Field(default_factory=list)
    mcp_sidecars: list[dict[str, Any]] = Field(default_factory=list)
    a2a_config: dict[str, Any] = Field(default_factory=dict)
    skills: dict[str, Any] = Field(default_factory=dict)
    skill_summaries: list[dict[str, Any]] = Field(default_factory=list)
    opencode_config_files: dict[str, Any] = Field(default_factory=dict)
    git_config: dict[str, Any] | None = None
    github_config: dict[str, Any] | None = None
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


AGENT_SYSTEM_PROMPT_MAX_CHARS = 12000


class CreateAgentRequest(BaseModel):
    name: str = Field(
        min_length=1,
        max_length=63,
        pattern=r"^[a-z0-9]([-a-z0-9]*[a-z0-9])?$",
    )
    model: str = Field(min_length=1, max_length=255)
    system_prompt: str = Field(default="", max_length=AGENT_SYSTEM_PROMPT_MAX_CHARS)
    policy_ref: str | None = Field(default=None, max_length=253)
    storage_size: str | None = Field(default="1Gi", max_length=32)
    runtime_kind: str = Field(pattern=r"^opencode$")
    enable_gvisor: bool = False
    mcp_connection_ids: list[str] = Field(default_factory=list)
    mcp_servers: list[str] = Field(default_factory=list)
    mcp_sidecars: list[dict[str, Any]] = Field(default_factory=list)
    a2a_config: dict[str, Any] | None = None
    skills: dict[str, Any] | None = None
    opencode_config_files: dict[str, Any] = Field(default_factory=dict)
    git_config: dict[str, Any] | None = Field(default=None, description="Git repo config for dev-loop workflows")
    github_config: dict[str, Any] | None = Field(
        default=None, description="Shared GitHub MCP credentials for this agent"
    )


class UpdateAgentRequest(BaseModel):
    model: str = Field(min_length=1, max_length=255)
    system_prompt: str = Field(default="", max_length=AGENT_SYSTEM_PROMPT_MAX_CHARS)
    policy_ref: str | None = Field(default=None, max_length=253)
    storage_size: str | None = Field(default="1Gi", max_length=32)
    runtime_kind: str | None = Field(default=None, pattern=r"^opencode$")
    enable_gvisor: bool = False
    mcp_connection_ids: list[str] | None = None
    mcp_servers: list[str] = Field(default_factory=list)
    mcp_sidecars: list[dict[str, Any]] = Field(default_factory=list)
    a2a_config: dict[str, Any] | None = None
    skills: dict[str, Any] | None = None
    opencode_config_files: dict[str, Any] | None = None
    git_config: dict[str, Any] | None = Field(default=None, description="Git repo config for dev-loop workflows")
    github_config: dict[str, Any] | None = Field(
        default=None, description="Shared GitHub MCP credentials for this agent"
    )


class McpConnectionRequest(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    server_id: str = Field(min_length=1, max_length=128)
    config: dict[str, Any] = Field(default_factory=dict)
    credentials: dict[str, str] = Field(default_factory=dict)
    validate_on_save: bool = False


class McpConnectionUpdateRequest(BaseModel):
    name: str | None = Field(default=None, max_length=128)
    server_id: str | None = Field(default=None, max_length=128)
    config: dict[str, Any] | None = None
    credentials: dict[str, str] | None = None
    validate_on_save: bool = False


class GitCredentialRequest(BaseModel):
    """Request body for creating git credentials as a K8s Secret."""

    auth_method: str = Field(pattern=r"^(token|basic|ssh)$")
    token: str | None = Field(default=None, max_length=1024)
    username: str | None = Field(default=None, max_length=255)
    password: str | None = Field(default=None, max_length=1024)
    ssh_private_key: str | None = Field(default=None, max_length=16384)

    @model_validator(mode="after")
    def validate_credentials(self) -> "GitCredentialRequest":
        if self.auth_method == "token" and not self.token:
            raise ValueError("token is required when auth_method is 'token'")
        if self.auth_method == "basic" and (not self.username or not self.password):
            raise ValueError("username and password are required when auth_method is 'basic'")
        if self.auth_method == "ssh" and not self.ssh_private_key:
            raise ValueError("ssh_private_key is required when auth_method is 'ssh'")
        return self


class GitHubCredentialRequest(BaseModel):
    """Request body for creating GitHub MCP credentials as a K8s Secret."""

    token: str = Field(min_length=1, max_length=4096)


class WorkflowStepRequest(BaseModel):
    name: str = Field(min_length=1, max_length=63)
    agent_ref: str = Field(min_length=1, max_length=63)
    prompt: str = Field(default="", max_length=16000)
    depends_on: list[str] = Field(default_factory=list)
    require_approval: bool = False
    execution: dict[str, Any] | None = None
    step_type: str = Field(default="agent", pattern=r"^(agent|loop|conditional|review)$")
    loop_config: dict[str, Any] | None = Field(default=None, description="Config for loop-type steps")
    condition_expr: str | None = Field(
        default=None, max_length=2000, description="Condition expression for conditional steps"
    )
    then_steps: list[str] | None = Field(default=None, description="Steps to activate when condition is true")
    else_steps: list[str] | None = Field(default=None, description="Steps to activate when condition is false")
    verify: str | None = Field(default=None, max_length=4000)
    review_criteria: str | None = Field(default=None, max_length=4000)


class WorkflowRequest(BaseModel):
    name: str = Field(
        min_length=1,
        max_length=63,
        pattern=r"^[a-z0-9]([-a-z0-9]*[a-z0-9])?$",
    )
    description: str = Field(default="", max_length=4000)
    input: str = Field(default="", max_length=4000)
    context_ref: str | None = Field(default=None, max_length=253)
    message_bus: str = Field(default="in-memory", pattern=r"^(in-memory)$")
    steps: list[WorkflowStepRequest] = Field(default_factory=list)


class WorkflowUpdateRequest(BaseModel):
    description: str = Field(default="", max_length=4000)
    input: str = Field(default="", max_length=4000)
    context_ref: str | None = Field(default=None, max_length=253)
    message_bus: str = Field(default="in-memory", pattern=r"^(in-memory)$")
    steps: list[WorkflowStepRequest] = Field(default_factory=list)


class WorkflowInfo(BaseModel):
    name: str
    namespace: str
    description: str = ""
    input: str = ""
    context_ref: str | None = None
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
    cases: list[dict[str, Any]] | None = None
    created_at: str | None = None


class DeleteResponse(BaseModel):
    status: str
    kind: str
    name: str
    namespace: str


class AuthRegisterRequest(BaseModel):
    username: str = Field(min_length=3, max_length=128, pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._-]*$")
    password: str = Field(min_length=8, max_length=256)
    email: str | None = Field(default=None, max_length=320)
    display_name: str | None = Field(default=None, max_length=255)


class AuthLoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=256)
    password: str = Field(min_length=1, max_length=256)
    provider: str = Field(default="local", max_length=64)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=8, max_length=256)


class CreateUserRequest(BaseModel):
    username: str = Field(min_length=3, max_length=128, pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._-]*$")
    password: str = Field(min_length=8, max_length=256)
    email: str | None = Field(default=None, max_length=320)
    display_name: str | None = Field(default=None, max_length=255)
    role: str = Field(default="viewer", pattern=r"^(viewer|operator|admin)$")
    allowed_namespaces: list[str] = Field(default_factory=list)


class UpdateUserRequest(BaseModel):
    display_name: str | None = Field(default=None, max_length=255)
    role: str | None = Field(default=None, pattern=r"^(viewer|operator|admin)$")
    is_active: bool | None = None
    allowed_namespaces: list[str] | None = None


RESOURCE_GROUP = "kubesynth.ai"
RESOURCE_VERSION = "v1alpha1"
RESOURCE_KIND_BY_PLURAL = {
    "aiagents": "AIAgent",
    "agentpolicies": "AgentPolicy",
    "agentworkflows": "AgentWorkflow",
    "agentevals": "AgentEval",
    "observationtargets": "ObservationTarget",
    "observationpolicies": "ObservationPolicy",
    "observationreports": "ObservationReport",
    "connectorplugins": "ConnectorPlugin",
}


def agent_runtime_url(agent_name: str, namespace: str) -> str:
    return f"http://{agent_name}-sandbox.{namespace}.svc.cluster.local:8080"


def normalized_runtime_kind(raw_value: str | None) -> str:
    runtime_kind = str(raw_value or "").strip().lower()
    if not runtime_kind:
        raise ValueError("runtime kind must be explicitly set")
    if runtime_kind != "opencode":
        raise ValueError(f"runtime kind must be 'opencode'; '{runtime_kind}' is no longer supported")
    return runtime_kind


def normalized_opencode_runtime_kind(raw_value: str | None, *, field_name: str) -> str:
    runtime_kind = normalized_runtime_kind(raw_value)
    if runtime_kind != "opencode":
        raise ValueError(f"{field_name} must be 'opencode'; '{runtime_kind}' is no longer supported")
    return runtime_kind


def normalize_runtime_config_file_path(raw_path: object, *, source: str) -> str:
    normalized_path = str(raw_path).replace("\\", "/").strip()
    if not normalized_path:
        raise HTTPException(status_code=400, detail=f"{source} paths must not be blank")
    if normalized_path.startswith("/"):
        raise HTTPException(status_code=400, detail=f"{source} paths must be relative")

    parts = [part for part in normalized_path.split("/") if part]
    if not parts or any(part in {".", ".."} for part in parts):
        raise HTTPException(status_code=400, detail=f"{source} path '{raw_path}' is invalid")
    return "/".join(parts)


def normalize_skill_file_path(raw_path: object) -> str:
    normalized_path = str(raw_path).replace("\\", "/").strip()
    if not normalized_path:
        raise HTTPException(status_code=400, detail="skills.files paths must not be blank")
    if len(normalized_path) > MAX_AGENT_SKILL_FILE_PATH_CHARS:
        raise HTTPException(
            status_code=400,
            detail=(f"skills.files paths must be {MAX_AGENT_SKILL_FILE_PATH_CHARS} characters or fewer"),
        )
    if normalized_path.startswith("/"):
        raise HTTPException(status_code=400, detail="skills.files paths must be relative")

    parts = [part for part in normalized_path.split("/") if part]
    if not parts or any(part in {".", ".."} for part in parts):
        raise HTTPException(status_code=400, detail=f"skills.files path '{raw_path}' is invalid")

    candidate = "/".join(parts)
    if not candidate.lower().endswith(".md"):
        raise HTTPException(
            status_code=400,
            detail=f"skills.files path '{candidate}' must point to a Markdown file ending in .md",
        )
    return candidate


def split_skill_frontmatter(content: str) -> tuple[str | None, str, str | None]:
    normalized = str(content or "").replace("\r\n", "\n")
    if not normalized.startswith("---\n"):
        return None, normalized, None

    lines = normalized.split("\n")
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            frontmatter = "\n".join(lines[1:index])
            body = "\n".join(lines[index + 1 :])
            return frontmatter, body, None
    return None, normalized, "Skill frontmatter must end with a closing '---' line"


def parse_skill_frontmatter(frontmatter: str, *, source: str, strict: bool) -> tuple[dict[str, Any], list[str]]:
    warnings: list[str] = []
    if not frontmatter.strip():
        return {}, warnings

    try:
        parsed = yaml.safe_load(frontmatter) if yaml is not None else json.loads(frontmatter)
    except Exception as exc:
        message = f"{source} frontmatter is invalid: {exc}"
        if strict:
            raise HTTPException(status_code=400, detail=message) from exc
        warnings.append(message)
        return {}, warnings

    if parsed is None:
        return {}, warnings
    if not isinstance(parsed, dict):
        message = f"{source} frontmatter must be a YAML or JSON object"
        if strict:
            raise HTTPException(status_code=400, detail=message)
        warnings.append(message)
        return {}, warnings
    return parsed, warnings


def skill_metadata_string_list(
    metadata: dict[str, Any],
    *keys: str,
    strict: bool,
    source: str,
    warnings: list[str],
) -> list[str]:
    raw_value: Any = None
    for key in keys:
        if key in metadata:
            raw_value = metadata.get(key)
            break

    if raw_value is None:
        return []
    if not isinstance(raw_value, list):
        message = f"{source} must be a list of strings"
        if strict:
            raise HTTPException(status_code=400, detail=message)
        warnings.append(message)
        return []

    normalized: list[str] = []
    seen: set[str] = set()
    for index, item in enumerate(raw_value):
        value = str(item or "").strip()
        if not value:
            continue
        if len(value) > 512:
            message = f"{source}[{index}] must be 512 characters or fewer"
            if strict:
                raise HTTPException(status_code=400, detail=message)
            warnings.append(message)
            continue
        if value in seen:
            continue
        seen.add(value)
        normalized.append(value)
    return normalized


def skill_metadata_bool(
    metadata: dict[str, Any],
    *keys: str,
    strict: bool,
    source: str,
    warnings: list[str],
) -> bool:
    for key in keys:
        if key not in metadata:
            continue
        value = metadata.get(key)
        if isinstance(value, bool):
            return value
        message = f"{source} must be a boolean"
        if strict:
            raise HTTPException(status_code=400, detail=message)
        warnings.append(message)
        return False
    return False


def infer_skill_name(path: str) -> str:
    parts = [part for part in path.split("/") if part]
    if len(parts) >= 2 and parts[-1].lower() == "skill.md":
        return parts[-2].replace("-", " ").strip() or "skill"
    stem = parts[-1].rsplit(".", 1)[0] if parts else "skill"
    return stem.replace("-", " ").strip() or "skill"


def parse_skill_summary(path: str, content: str, *, strict: bool) -> dict[str, Any]:
    warnings: list[str] = []
    frontmatter, body, frontmatter_warning = split_skill_frontmatter(content)
    if frontmatter_warning:
        if strict:
            raise HTTPException(
                status_code=400,
                detail=f"skills.files.{path}: {frontmatter_warning}",
            )
        warnings.append(f"skills.files.{path}: {frontmatter_warning}")
    metadata, metadata_warnings = parse_skill_frontmatter(
        frontmatter or "",
        source=f"skills.files.{path}",
        strict=strict,
    )
    warnings.extend(metadata_warnings)

    raw_name = metadata.get("name")
    if raw_name is not None and not isinstance(raw_name, str):
        message = f"skills.files.{path}.name must be a string"
        if strict:
            raise HTTPException(status_code=400, detail=message)
        warnings.append(message)
        raw_name = None
    raw_description = metadata.get("description")
    if raw_description is not None and not isinstance(raw_description, str):
        message = f"skills.files.{path}.description must be a string"
        if strict:
            raise HTTPException(status_code=400, detail=message)
        warnings.append(message)
        raw_description = None

    name = str(raw_name or infer_skill_name(path)).strip() or infer_skill_name(path)
    description = str(raw_description or "").strip() or None
    instructions_preview = summarize_text(body, fallback=description or name, max_length=320)
    raw_allowed_a2a_targets = metadata.get("allowedA2ATargets", metadata.get("allowed_a2a_targets"))
    if raw_allowed_a2a_targets is None:
        allowed_a2a_targets: list[dict[str, str]] = []
    else:
        try:
            allowed_a2a_targets = parse_a2a_peer_refs(
                raw_allowed_a2a_targets,
                source=f"skills.files.{path}.allowed_a2a_targets",
            )
        except HTTPException as exc:
            if strict:
                raise
            warnings.append(str(exc.detail))
            allowed_a2a_targets = []

    return {
        "path": path,
        "name": name,
        "description": description,
        "instructions_preview": instructions_preview,
        "allowed_sandbox_tools": skill_metadata_string_list(
            metadata,
            "allowedSandboxTools",
            "allowed_sandbox_tools",
            strict=strict,
            source=f"skills.files.{path}.allowed_sandbox_tools",
            warnings=warnings,
        ),
        "allowed_mcp_servers": skill_metadata_string_list(
            metadata,
            "allowedMcpServers",
            "allowed_mcp_servers",
            strict=strict,
            source=f"skills.files.{path}.allowed_mcp_servers",
            warnings=warnings,
        ),
        "allowed_a2a_targets": allowed_a2a_targets,
        "allow_subagents": skill_metadata_bool(
            metadata,
            "allowSubagents",
            "allow_subagents",
            strict=strict,
            source=f"skills.files.{path}.allow_subagents",
            warnings=warnings,
        ),
        "valid": not bool(warnings),
        "warnings": warnings,
    }


def parse_agent_skills_config(config: Any, *, source: str, strict: bool = False) -> dict[str, Any]:
    if config is None:
        return {}
    if not isinstance(config, dict):
        raise HTTPException(status_code=400, detail=f"{source} must be an object")

    raw_files = config.get("files")
    if raw_files is None:
        if config:
            raise HTTPException(status_code=400, detail=f"{source}.files is required when skills are provided")
        return {}
    if not isinstance(raw_files, dict):
        raise HTTPException(status_code=400, detail=f"{source}.files must be an object keyed by Markdown file path")
    if len(raw_files) > MAX_AGENT_SKILL_FILES:
        raise HTTPException(
            status_code=400,
            detail=f"{source}.files cannot contain more than {MAX_AGENT_SKILL_FILES} entries",
        )

    normalized_files: dict[str, str] = {}
    total_chars = 0
    for raw_path, raw_content in sorted(raw_files.items(), key=lambda item: str(item[0])):
        path = normalize_skill_file_path(raw_path)
        if not isinstance(raw_content, str):
            raise HTTPException(status_code=400, detail=f"{source}.files.{path} must be a Markdown string")
        if not raw_content.strip():
            raise HTTPException(status_code=400, detail=f"{source}.files.{path} must not be blank")
        if len(raw_content) > MAX_AGENT_SKILL_FILE_CONTENT_CHARS:
            raise HTTPException(
                status_code=400,
                detail=(f"{source}.files.{path} exceeds {MAX_AGENT_SKILL_FILE_CONTENT_CHARS} characters"),
            )
        total_chars += len(raw_content)
        if total_chars > MAX_AGENT_SKILL_TOTAL_CHARS:
            raise HTTPException(
                status_code=400,
                detail=f"{source}.files exceeds the total limit of {MAX_AGENT_SKILL_TOTAL_CHARS} characters",
            )
        normalized_files[path] = raw_content.replace("\r\n", "\n")
        if strict:
            parse_skill_summary(path, normalized_files[path], strict=True)

    return {"files": normalized_files} if normalized_files else {}


def parse_agent_skill_summaries(config: Any) -> list[dict[str, Any]]:
    if not isinstance(config, dict):
        return []
    raw_files = config.get("files")
    if not isinstance(raw_files, dict):
        return []

    summaries: list[dict[str, Any]] = []
    for raw_path, raw_content in sorted(raw_files.items(), key=lambda item: str(item[0])):
        try:
            path = normalize_skill_file_path(raw_path)
        except HTTPException as exc:
            summaries.append(
                {
                    "path": str(raw_path),
                    "name": infer_skill_name(str(raw_path)),
                    "description": None,
                    "instructions_preview": None,
                    "allowed_sandbox_tools": [],
                    "allowed_mcp_servers": [],
                    "allowed_a2a_targets": [],
                    "allow_subagents": False,
                    "valid": False,
                    "warnings": [str(exc.detail)],
                }
            )
            continue
        if not isinstance(raw_content, str):
            summaries.append(
                {
                    "path": path,
                    "name": infer_skill_name(path),
                    "description": None,
                    "instructions_preview": None,
                    "allowed_sandbox_tools": [],
                    "allowed_mcp_servers": [],
                    "allowed_a2a_targets": [],
                    "allow_subagents": False,
                    "valid": False,
                    "warnings": [f"skills.files.{path} must be a Markdown string"],
                }
            )
            continue
        summaries.append(parse_skill_summary(path, raw_content, strict=False))
    return summaries


def parse_a2a_peer_ref(raw_value: Any, *, source: str) -> dict[str, str]:
    if not isinstance(raw_value, dict):
        raise HTTPException(status_code=400, detail=f"{source} entries must be objects with name and namespace fields")

    name = str(raw_value.get("name", "")).strip()
    namespace = str(raw_value.get("namespace", "")).strip()
    if not name or not namespace:
        raise HTTPException(
            status_code=400, detail=f"{source} entries must include non-empty name and namespace values"
        )
    if not K8S_NAME_RE.fullmatch(name):
        raise HTTPException(status_code=400, detail=f"{source}.name must be a valid lowercase Kubernetes resource name")
    if not K8S_NAME_RE.fullmatch(namespace):
        raise HTTPException(
            status_code=400, detail=f"{source}.namespace must be a valid lowercase Kubernetes namespace name"
        )
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
            raise HTTPException(
                status_code=400, detail=f"{source}.max_timeout_seconds must be a positive number"
            ) from exc

    raw_require_hitl = config.get("require_hitl")
    if raw_require_hitl is None:
        raw_require_hitl = config.get("requireHitl")
    if raw_require_hitl is not None:
        if not isinstance(raw_require_hitl, bool):
            raise HTTPException(status_code=400, detail=f"{source}.require_hitl must be a boolean")
        normalized["requireHitl"] = raw_require_hitl

    return normalized


def parse_opencode_config_files(config_files: Any, *, source: str) -> dict[str, Any]:
    if config_files is None:
        return {}
    if not isinstance(config_files, dict):
        raise HTTPException(
            status_code=400, detail=f"{source} must be a JSON object keyed by relative OpenCode config paths"
        )

    normalized: dict[str, Any] = {}
    for raw_path, raw_content in sorted(config_files.items(), key=lambda item: str(item[0])):
        normalized_path = normalize_runtime_config_file_path(raw_path, source=source)
        if raw_content is None:
            raise HTTPException(status_code=400, detail=f"{source}.{normalized_path} must not be null")
        normalized[normalized_path] = raw_content
    return normalized


def runtime_kind_from_spec(spec: dict[str, Any] | None) -> str:
    runtime_spec = (spec or {}).get("runtime")
    if not isinstance(runtime_spec, dict):
        raise HTTPException(status_code=400, detail="AIAgent.spec.runtime.kind must be explicitly set")
    try:
        return normalized_runtime_kind(runtime_spec.get("kind"))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid AIAgent runtime configuration: {exc}") from exc


def validate_agent_runtime_compatibility(spec: dict[str, Any]) -> None:
    runtime_kind = runtime_kind_from_spec(spec)
    if runtime_kind != "opencode":
        raise HTTPException(status_code=400, detail=f"Unsupported AIAgent runtime kind '{runtime_kind}'")
    if spec.get("githubConfig"):
        raise HTTPException(
            status_code=400,
            detail=(
                "OpenCode runtime does not support github_config because the shared GitHub hub service is exposed "
                "through an HTTP adapter rather than a native MCP endpoint. Use sidecar-based GitHub MCP instead."
            ),
        )


def validate_invoke_runtime_compatibility(runtime_kind: str, request: InvokeRequest) -> None:
    if runtime_kind != "opencode":
        raise HTTPException(status_code=400, detail=f"Unsupported AIAgent runtime kind '{runtime_kind}'")

    unsupported_fields: list[str] = []
    if request.tool_name.strip():
        unsupported_fields.append("tool_name")
    if (request.mcp_server or "").strip():
        unsupported_fields.append("mcp_server")
    if request.sandbox_session is not None:
        unsupported_fields.append("sandbox_session")
    if request.subagents:
        unsupported_fields.append("subagents")

    if unsupported_fields:
        joined_fields = ", ".join(unsupported_fields)
        raise HTTPException(
            status_code=400,
            detail=(
                "OpenCode runtime currently supports chat-style prompt invocation and explicit outbound A2A "
                f"invocation. Unsupported fields for opencode agents: {joined_fields}."
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

    def _normalize_error_text(value: str) -> str:
        return re.sub(r"\s+", " ", value).strip()

    def _truncate_error_text(value: str) -> str:
        normalized = _normalize_error_text(value)
        if len(normalized) <= 400:
            return normalized
        return f"{normalized[:397]}..."

    def _sanitize_error_text(value: str) -> str:
        trimmed = value.strip()
        if not trimmed:
            return fallback

        if re.search(r"<(?:!doctype\s+html|html|body|title|h1)\b", trimmed, re.IGNORECASE):
            headline = None
            for pattern in (
                re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL),
                re.compile(r"<h1[^>]*>(.*?)</h1>", re.IGNORECASE | re.DOTALL),
            ):
                match = pattern.search(trimmed)
                if match and match.group(1).strip():
                    headline = _normalize_error_text(html.unescape(re.sub(r"<[^>]+>", " ", match.group(1))))
                    if headline:
                        break

            if headline:
                return _truncate_error_text(f"Upstream service error: {headline}")

            plain_text = _normalize_error_text(html.unescape(re.sub(r"<[^>]+>", " ", trimmed)))
            if plain_text:
                return _truncate_error_text(f"Upstream service error: {plain_text}")
            return fallback

        return _truncate_error_text(trimmed)

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return {"error": _sanitize_error_text(text)}

    if isinstance(parsed, dict):
        for key in ("detail", "error"):
            value = parsed.get(key)
            if isinstance(value, str) and value.strip():
                return {"error": _sanitize_error_text(value)}

    return {"error": _sanitize_error_text(text)}


def sse_event(event: str, payload: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False, default=str)}\n\n"


def sse_keepalive_comment() -> str:
    return ": keepalive\n\n"


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def build_retry_workflow_run_id(namespace: str, workflow_name: str, generation: int) -> str:
    epoch_ms = int(time.time() * 1000)
    return f"wf-run-{namespace}-{workflow_name}-{generation}-{epoch_ms}-{uuid.uuid4().hex[:8]}"


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


def first_present(config: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in config:
            return config.get(key)
    return None


def parse_agent_git_config(config: Any, *, source: str) -> dict[str, Any]:
    if config is None:
        return {}
    if not isinstance(config, dict):
        raise HTTPException(status_code=400, detail=f"{source} must be an object")
    if not config:
        return {}

    repo_url = str(first_present(config, "repoUrl", "repo_url") or "").strip()
    default_branch = str(first_present(config, "defaultBranch", "default_branch") or "").strip()
    branch = str(first_present(config, "branch") or "").strip()
    push_policy = str(first_present(config, "pushPolicy", "push_policy") or "").strip()
    auth_method = str(first_present(config, "authMethod", "auth_method") or "").strip()
    credential_secret_ref = str(first_present(config, "credentialSecretRef", "credential_secret_ref") or "").strip()

    if auth_method and auth_method not in GIT_AUTH_METHODS:
        raise HTTPException(
            status_code=400,
            detail=f"{source}.auth_method must be one of {', '.join(sorted(GIT_AUTH_METHODS))}",
        )
    if push_policy and push_policy not in GIT_PUSH_POLICIES:
        raise HTTPException(
            status_code=400,
            detail=f"{source}.push_policy must be one of {', '.join(sorted(GIT_PUSH_POLICIES))}",
        )

    normalized: dict[str, Any] = {}
    if repo_url:
        normalized["repoUrl"] = repo_url
    if default_branch:
        normalized["defaultBranch"] = default_branch
    if branch:
        normalized["branch"] = branch
    if push_policy:
        normalized["pushPolicy"] = push_policy
    if auth_method:
        normalized["authMethod"] = auth_method
    if credential_secret_ref:
        normalized["credentialSecretRef"] = credential_secret_ref
    return normalized


def serialize_agent_git_config(config: Any) -> dict[str, Any] | None:
    normalized = parse_agent_git_config(config, source="git_config")
    if not normalized:
        return None
    serialized: dict[str, Any] = {}
    if normalized.get("repoUrl"):
        serialized["repo_url"] = normalized["repoUrl"]
    if normalized.get("defaultBranch"):
        serialized["default_branch"] = normalized["defaultBranch"]
    if normalized.get("branch"):
        serialized["branch"] = normalized["branch"]
    if normalized.get("pushPolicy"):
        serialized["push_policy"] = normalized["pushPolicy"]
    if normalized.get("authMethod"):
        serialized["auth_method"] = normalized["authMethod"]
    if normalized.get("credentialSecretRef"):
        serialized["credential_secret_ref"] = normalized["credentialSecretRef"]
    return serialized or None


def parse_agent_github_config(config: Any, *, source: str) -> dict[str, Any]:
    if config is None:
        return {}
    if not isinstance(config, dict):
        raise HTTPException(status_code=400, detail=f"{source} must be an object")
    if not config:
        return {}

    credential_secret_ref = str(first_present(config, "credentialSecretRef", "credential_secret_ref") or "").strip()
    if not credential_secret_ref:
        raise HTTPException(status_code=400, detail=f"{source}.credential_secret_ref is required")
    return {"credentialSecretRef": credential_secret_ref}


def serialize_agent_github_config(config: Any) -> dict[str, Any] | None:
    normalized = parse_agent_github_config(config, source="github_config")
    if not normalized:
        return None
    return {"credential_secret_ref": normalized["credentialSecretRef"]}


MCP_CONNECTION_VALIDATION_STATES = {"draft", "valid", "warning", "invalid"}


def _mcp_registry_index() -> dict[str, dict[str, Any]]:
    return {entry["id"]: entry for entry in _build_mcp_registry_results()}


def _lookup_mcp_registry_entry(server_id: str, *, required: bool = True) -> dict[str, Any] | None:
    normalized_server_id = str(server_id or "").strip()
    if not normalized_server_id:
        if required:
            raise HTTPException(status_code=400, detail="server_id is required")
        return None
    entry = _mcp_registry_index().get(normalized_server_id)
    if entry is None and required:
        raise HTTPException(status_code=404, detail=f"MCP server '{normalized_server_id}' was not found in the registry.")
    return entry


def _mcp_connection_secret_name(connection_id: str) -> str:
    normalized = re.sub(r"[^a-z0-9-]+", "-", str(connection_id or "").strip().lower()).strip("-") or "connection"
    return f"mcp-conn-{normalized}"[:63].rstrip("-")


def _mcp_connection_secret_env_var(connection_id: str, key: str) -> str:
    normalized_connection = re.sub(r"[^A-Za-z0-9]+", "_", str(connection_id or "")).upper().strip("_") or "CONNECTION"
    normalized_key = re.sub(r"[^A-Za-z0-9]+", "_", str(key or "")).upper().strip("_") or "VALUE"
    return f"MCP_CONNECTION_{normalized_connection}_{normalized_key}"[:180]


def _sidecar_config_env_name(server_id: str, key: str) -> str:
    prefix = re.sub(r"[^A-Za-z0-9]+", "_", str(server_id or "").replace("-sidecar", "")).upper().strip("_") or "MCP"
    suffix = re.sub(r"[^A-Za-z0-9]+", "_", str(key or "")).upper().strip("_") or "VALUE"
    return f"{prefix}_{suffix}"[:120]


def _configured_credential_keys(credential_metadata: Any) -> set[str]:
    if not isinstance(credential_metadata, list):
        return set()
    configured: set[str] = set()
    for item in credential_metadata:
        if not isinstance(item, dict):
            continue
        key = str(item.get("key") or "").strip()
        if key and bool(item.get("configured")):
            configured.add(key)
    return configured


def _credential_fields_for_entry(entry: dict[str, Any]) -> list[dict[str, Any]]:
    fields = entry.get("config_schema") if isinstance(entry.get("config_schema"), list) else []
    return [field for field in fields if isinstance(field, dict) and bool(field.get("is_credential"))]


def _non_credential_fields_for_entry(entry: dict[str, Any]) -> list[dict[str, Any]]:
    fields = entry.get("config_schema") if isinstance(entry.get("config_schema"), list) else []
    return [field for field in fields if isinstance(field, dict) and not bool(field.get("is_credential"))]


def _trimmed_json_mapping(value: Any, *, source: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise HTTPException(status_code=400, detail=f"{source} must be an object")
    normalized: dict[str, Any] = {}
    for raw_key, raw_value in value.items():
        key = str(raw_key or "").strip()
        if not key:
            continue
        if isinstance(raw_value, str):
            trimmed = raw_value.strip()
            if trimmed:
                normalized[key] = trimmed
            continue
        if raw_value is None:
            continue
        normalized[key] = raw_value
    return normalized


def _normalize_mcp_connection_config(entry: dict[str, Any], value: Any, *, source: str) -> dict[str, Any]:
    normalized = _trimmed_json_mapping(value, source=f"{source}.config")
    transport = str(entry.get("transport") or "").strip().lower()

    for field in _non_credential_fields_for_entry(entry):
        key = str(field.get("key") or "").strip()
        if key and bool(field.get("required")) and key not in normalized:
            raise HTTPException(status_code=400, detail=f"{source}.config.{key} is required")

    if transport == "remote":
        default_endpoint = str(entry.get("endpoint") or "").strip()
        endpoint_url = str(normalized.get("endpoint_url") or default_endpoint).strip()
        if endpoint_url:
            normalized["endpoint_url"] = endpoint_url
        if bool(entry.get("attachable")) and not endpoint_url:
            raise HTTPException(status_code=400, detail=f"{source}.config.endpoint_url is required for remote MCP connections")
    elif transport == "hub":
        normalized["endpoint_url"] = _build_hub_mcp_url(entry)
    elif transport == "sidecar":
        if not normalized.get("sidecar_image") and entry.get("sidecar_image"):
            normalized["sidecar_image"] = entry.get("sidecar_image")
        if "sidecar_port" not in normalized and entry.get("sidecar_port") is not None:
            normalized["sidecar_port"] = entry.get("sidecar_port")
        normalized["endpoint_path"] = str(normalized.get("endpoint_path") or "/mcp").strip() or "/mcp"
        if "sidecar_port" in normalized:
            try:
                normalized["sidecar_port"] = int(normalized["sidecar_port"])
            except (TypeError, ValueError) as exc:
                raise HTTPException(status_code=400, detail=f"{source}.config.sidecar_port must be an integer") from exc

    return normalized


def _normalize_mcp_connection_credentials(entry: dict[str, Any], value: Any, *, source: str) -> dict[str, str]:
    normalized = _trimmed_json_mapping(value, source=f"{source}.credentials")
    allowed_keys = {str(field.get("key") or "").strip() for field in _credential_fields_for_entry(entry)}
    return {
        key: str(item_value)
        for key, item_value in normalized.items()
        if key in allowed_keys and str(item_value).strip()
    }


def _build_mcp_connection_credential_metadata(
    entry: dict[str, Any],
    *,
    configured_keys: set[str],
) -> list[dict[str, Any]]:
    metadata: list[dict[str, Any]] = []
    for field in _credential_fields_for_entry(entry):
        key = str(field.get("key") or "").strip()
        if not key:
            continue
        metadata.append(
            {
                "key": key,
                "label": str(field.get("label") or key),
                "type": str(field.get("type") or "text"),
                "group": str(field.get("group") or "credentials"),
                "required": bool(field.get("required")),
                "configured": key in configured_keys,
            }
        )
    return metadata


def _build_hub_mcp_url(entry: dict[str, Any]) -> str:
    hub_server_name = str(entry.get("hub_server_name") or entry.get("id") or "").strip()
    return f"http://{HELM_RELEASE_NAME}-mcp-{hub_server_name}.{MCP_HUB_NAMESPACE}.svc.cluster.local:8000/mcp"


def _first_configured_key(configured_keys: set[str], *candidates: str) -> str | None:
    for candidate in candidates:
        if candidate in configured_keys:
            return candidate
    return None


def _build_runtime_header_bindings(
    connection_id: str,
    entry: dict[str, Any],
    *,
    secret_name: str | None,
    configured_keys: set[str],
) -> list[dict[str, Any]]:
    if not secret_name:
        return []

    server_id = str(entry.get("id") or "").strip()
    auth_type = str(entry.get("auth_type") or "none").strip().lower()
    custom_header_name = str(entry.get("auth_header_name") or "").strip() or None
    custom_header_prefix_raw = entry.get("auth_header_prefix")
    custom_header_prefix = None if custom_header_prefix_raw is None else str(custom_header_prefix_raw)
    bindings: list[dict[str, Any]] = []

    def append_header(header_name: str, key: str, *, prefix: str | None = None) -> None:
        bindings.append(
            {
                "name": header_name,
                "envVar": _mcp_connection_secret_env_var(connection_id, key),
                "secretKeyRef": {"name": secret_name, "key": key, "optional": False},
                "prefix": prefix,
            }
        )

    if server_id == "datadog":
        api_key = _first_configured_key(configured_keys, "api_key")
        app_key = _first_configured_key(configured_keys, "app_key")
        if api_key:
            append_header("DD-API-KEY", api_key)
        if app_key:
            append_header("DD-APPLICATION-KEY", app_key)
        return bindings

    if auth_type == "bearer":
        token_key = _first_configured_key(configured_keys, "token", "access_token", "bearer_token", "api_key")
        if token_key:
            append_header(custom_header_name or "Authorization", token_key, prefix="Bearer " if custom_header_prefix is None else custom_header_prefix)
        return bindings

    if auth_type == "oauth":
        token_key = _first_configured_key(configured_keys, "access_token", "token", "bearer_token")
        if token_key:
            append_header(
                custom_header_name or "Authorization",
                token_key,
                prefix="Bearer " if custom_header_prefix is None else custom_header_prefix,
            )
        return bindings

    if auth_type == "api_key":
        api_key = _first_configured_key(configured_keys, "api_key", "token", "key")
        if api_key:
            append_header(custom_header_name or "X-API-Key", api_key, prefix=custom_header_prefix)
        return bindings

    if auth_type == "connection_string":
        connection_string_key = _first_configured_key(configured_keys, "connection_string")
        if connection_string_key:
            append_header("X-Connection-String", connection_string_key)
        return bindings

    return bindings


def _build_mcp_connection_runtime_payload(connection_record: dict[str, Any], entry: dict[str, Any]) -> dict[str, Any]:
    connection_id = str(connection_record.get("id") or "").strip()
    slug = str(connection_record.get("slug") or slugify_mcp_connection_name(connection_record.get("name") or connection_id))
    config = connection_record.get("config") if isinstance(connection_record.get("config"), dict) else {}
    secret_name = str(connection_record.get("secret_name") or "").strip() or None
    secret_values = _mcp_connection_secret_values_for_record(connection_record)
    configured_keys = _configured_credential_keys(connection_record.get("credential_metadata")) | set(secret_values)
    transport = str(entry.get("transport") or connection_record.get("transport") or "remote").strip().lower() or "remote"

    if transport == "sidecar":
        image = str(config.get("sidecar_image") or entry.get("sidecar_image") or "").strip()
        raw_port = config.get("sidecar_port", entry.get("sidecar_port") or 8097)
        try:
            port = int(raw_port)
        except (TypeError, ValueError):
            port = int(entry.get("sidecar_port") or 8097)
        env_items: list[dict[str, Any]] = []
        for field in entry.get("config_schema") or []:
            if not isinstance(field, dict):
                continue
            key = str(field.get("key") or "").strip()
            if not key:
                continue
            env_name = _sidecar_config_env_name(str(entry.get("id") or slug), key)
            if bool(field.get("is_credential")):
                if secret_name and key in configured_keys:
                    env_items.append(
                        {
                            "name": env_name,
                            "envVar": _mcp_connection_secret_env_var(connection_id, key),
                            "secretKeyRef": {"name": secret_name, "key": key, "optional": False},
                        }
                    )
                continue
            value = config.get(key)
            if value is None or str(value).strip() == "":
                continue
            env_items.append({"name": env_name, "value": str(value)})
        sidecar_name = f"mcp-{slug}"[:59].rstrip("-") or f"mcp-{connection_id[:8]}"
        return {
            "kind": "sidecar",
            "configKey": slug,
            "sidecar": {
                "name": sidecar_name,
                "image": image,
                "port": port,
                "endpointPath": str(config.get("endpoint_path") or "/mcp").strip() or "/mcp",
                "env": env_items,
            },
        }

    url = str(config.get("endpoint_url") or entry.get("endpoint") or "").strip()
    if transport == "hub":
        url = _build_hub_mcp_url(entry)

    return {
        "kind": "remote",
        "configKey": slug,
        "url": url,
        "headers": _build_runtime_header_bindings(connection_id, entry, secret_name=secret_name, configured_keys=configured_keys),
    }


def _serialize_saved_mcp_connection_record(
    connection_record: dict[str, Any],
    *,
    binding_count: int = 0,
) -> dict[str, Any]:
    entry = _lookup_mcp_registry_entry(str(connection_record.get("server_id") or ""), required=False)
    if entry is None:
        return {
            **connection_record,
            "server_name": str(connection_record.get("server_id") or "unknown"),
            "support_level": "planned",
            "attachable": False,
            "status_reason": "The backing registry entry is no longer present.",
            "runtime_preview": None,
            "oauth": None,
            "binding_count": binding_count,
        }
    return {
        **connection_record,
        "server_name": entry.get("name"),
        "support_level": entry.get("support_level", "planned"),
        "attachable": bool(entry.get("attachable")),
        "status_reason": entry.get("status_reason"),
        "runtime_preview": _build_mcp_connection_runtime_payload(connection_record, entry),
        "oauth": _build_mcp_connection_oauth_status(connection_record, entry),
        "binding_count": binding_count,
    }


def _required_mcp_fields_missing(entry: dict[str, Any], config: dict[str, Any], credential_metadata: list[dict[str, Any]]) -> list[str]:
    missing: list[str] = []
    configured_keys = _configured_credential_keys(credential_metadata)
    for field in _non_credential_fields_for_entry(entry):
        key = str(field.get("key") or "").strip()
        if key and bool(field.get("required")) and key not in config:
            missing.append(key)
    for field in _credential_fields_for_entry(entry):
        key = str(field.get("key") or "").strip()
        if key and bool(field.get("required")) and key not in configured_keys:
            missing.append(key)
    if str(entry.get("transport") or "") == "remote" and bool(entry.get("attachable")):
        endpoint_url = str(config.get("endpoint_url") or "").strip()
        if not endpoint_url:
            missing.append("endpoint_url")
    return dedupe_text_values(missing)


def _validate_saved_mcp_connection_record(connection_record: dict[str, Any]) -> tuple[str, str, dict[str, Any]]:
    entry = _lookup_mcp_registry_entry(str(connection_record.get("server_id") or ""), required=False)
    if entry is None:
        return (
            "invalid",
            "The backing registry entry no longer exists.",
            {"reason": "registry_entry_missing"},
        )

    config = connection_record.get("config") if isinstance(connection_record.get("config"), dict) else {}
    credential_metadata = (
        connection_record.get("credential_metadata") if isinstance(connection_record.get("credential_metadata"), list) else []
    )
    missing_fields = _required_mcp_fields_missing(entry, config, credential_metadata)
    if missing_fields:
        return (
            "invalid",
            f"Missing required fields: {', '.join(missing_fields)}.",
            {"missing_fields": missing_fields},
        )

    if not bool(entry.get("attachable")):
        return (
            "warning",
            str(entry.get("status_reason") or "This MCP server is not attachable yet."),
            {"reason": "registry_not_attachable"},
        )

    transport = str(entry.get("transport") or "").strip().lower()
    if transport == "sidecar":
        return (
            "valid",
            "Sidecar settings were captured successfully. Runtime validation completes when an agent pod starts.",
            {"transport": "sidecar"},
        )

    secret_values = _mcp_connection_secret_values_for_record(connection_record)
    auth_type = str(entry.get("auth_type") or "none").strip().lower()
    if auth_type == "oauth":
        secret_values = _ensure_mcp_connection_oauth_access_token(connection_record, entry)
        oauth_status = _build_mcp_connection_oauth_status(connection_record, entry, secret_values=secret_values)
        oauth_state = str((oauth_status or {}).get("state") or "required")
        if oauth_state != "connected":
            return (
                "warning",
                "Refresh or reconnect the OAuth session before validating this connection."
                if oauth_state == "expired"
                else "Complete the browser OAuth sign-in before validating this connection.",
                {"reason": f"oauth_{oauth_state}", "oauth": oauth_status},
            )

    endpoint_url = str(config.get("endpoint_url") or entry.get("endpoint") or "").strip()
    if transport == "hub":
        endpoint_url = _build_hub_mcp_url(entry)
    if not endpoint_url:
        return (
            "invalid",
            "No MCP endpoint URL is configured for this connection.",
            {"reason": "endpoint_missing"},
        )

    try:
        parsed = httpx.URL(endpoint_url)
    except Exception as exc:
        return (
            "invalid",
            f"Endpoint URL is invalid: {exc}",
            {"reason": "invalid_url", "url": endpoint_url},
        )

    if parsed.scheme not in {"http", "https"}:
        return (
            "invalid",
            "Endpoint URL must use http or https.",
            {"reason": "invalid_scheme", "url": endpoint_url},
        )

    try:
        with httpx.Client(timeout=5.0, follow_redirects=True, verify=certifi.where()) as client:
            response = client.get(
                endpoint_url,
                headers=_resolved_mcp_connection_request_headers(connection_record, entry, secret_values=secret_values),
            )
    except Exception as exc:
        return (
            "warning",
            f"Endpoint could not be reached from the gateway: {exc}",
            {"reason": "unreachable", "url": endpoint_url},
        )

    if response.status_code == 404:
        return (
            "invalid",
            "Endpoint responded with 404. Verify the MCP path and vendor URL.",
            {"reason": "not_found", "url": endpoint_url, "status_code": response.status_code},
        )
    if response.status_code >= 500:
        return (
            "warning",
            f"Endpoint responded with server error {response.status_code}.",
            {"reason": "server_error", "url": endpoint_url, "status_code": response.status_code},
        )

    return (
        "valid",
        f"Endpoint responded with HTTP {response.status_code}. Reachability is confirmed; vendor-specific auth was not deeply verified.",
        {"url": endpoint_url, "status_code": response.status_code, "auth_type": auth_type},
    )


def _upsert_mcp_connection_secret(namespace: str, connection_id: str, credentials: dict[str, str]) -> str | None:
    trimmed_credentials = {key: value for key, value in credentials.items() if str(value or "").strip()}
    if not trimmed_credentials:
        return None

    from kubernetes import client
    from kubernetes.client.rest import ApiException

    secret_name = _mcp_connection_secret_name(connection_id)
    secret = client.V1Secret(
        metadata=client.V1ObjectMeta(
            name=secret_name,
            namespace=namespace,
            labels={
                "app.kubernetes.io/managed-by": "kubesynth",
                "kubesynth.ai/mcp-connection-id": connection_id,
            },
        ),
        type="Opaque",
        string_data=trimmed_credentials,
    )
    try:
        client.CoreV1Api().create_namespaced_secret(namespace=namespace, body=secret)
    except ApiException as exc:
        if exc.status == 409:
            client.CoreV1Api().replace_namespaced_secret(name=secret_name, namespace=namespace, body=secret)
        else:
            raise HTTPException(status_code=502, detail=f"Failed to store MCP connection credentials: {exc}") from exc
    return secret_name


def _delete_mcp_connection_secret(namespace: str, secret_name: str | None) -> None:
    trimmed_secret_name = str(secret_name or "").strip()
    if not trimmed_secret_name:
        return
    from kubernetes import client
    from kubernetes.client.rest import ApiException

    try:
        client.CoreV1Api().delete_namespaced_secret(name=trimmed_secret_name, namespace=namespace)
    except ApiException as exc:
        if exc.status != 404:
            raise HTTPException(status_code=502, detail=f"Failed to delete MCP connection credentials: {exc}") from exc


_MCP_OAUTH_PENDING_FLOWS: dict[str, dict[str, Any]] = {}
_MCP_OAUTH_FLOW_TTL_SECONDS = 900
_MCP_OAUTH_EXPIRY_SKEW_SECONDS = 60
_MCP_OAUTH_SESSION_KEYS = {"access_token", "refresh_token", "token_type", "expires_at", "scope"}


def _trimmed_string_mapping(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    normalized: dict[str, str] = {}
    for raw_key, raw_value in value.items():
        key = str(raw_key or "").strip()
        item_value = str(raw_value or "").strip()
        if key and item_value:
            normalized[key] = item_value
    return normalized


def _read_mcp_connection_secret_values(namespace: str, secret_name: str | None) -> dict[str, str]:
    trimmed_secret_name = str(secret_name or "").strip()
    if not trimmed_secret_name:
        return {}

    from kubernetes import client
    from kubernetes.client.rest import ApiException

    try:
        secret = client.CoreV1Api().read_namespaced_secret(name=trimmed_secret_name, namespace=namespace)
    except ApiException as exc:
        if exc.status == 404:
            return {}
        raise HTTPException(status_code=502, detail=f"Failed to read MCP connection credentials: {exc}") from exc

    raw_data = getattr(secret, "data", None) or {}
    decoded: dict[str, str] = {}
    for raw_key, raw_value in raw_data.items():
        key = str(raw_key or "").strip()
        encoded = str(raw_value or "").strip()
        if not key or not encoded:
            continue
        try:
            decoded[key] = base64.b64decode(encoded).decode("utf-8")
        except Exception:
            logger.warning("Failed to decode MCP connection secret field '%s' from %s/%s", key, namespace, trimmed_secret_name)
    return decoded


def _mcp_connection_secret_values_for_record(connection_record: dict[str, Any]) -> dict[str, str]:
    namespace = str(connection_record.get("namespace") or "default").strip() or "default"
    secret_name = str(connection_record.get("secret_name") or "").strip() or None
    return _read_mcp_connection_secret_values(namespace, secret_name)


def _clear_mcp_oauth_session_values(secret_values: dict[str, str]) -> dict[str, str]:
    return {key: value for key, value in secret_values.items() if key not in _MCP_OAUTH_SESSION_KEYS}


def _parse_iso_datetime(value: Any) -> datetime | None:
    raw_value = str(value or "").strip()
    if not raw_value:
        return None
    with contextlib.suppress(ValueError):
        return datetime.fromisoformat(raw_value.replace("Z", "+00:00")).astimezone(UTC)
    return None


def _mcp_oauth_entry_metadata(entry: dict[str, Any]) -> dict[str, Any]:
    authorization_url = str(entry.get("oauth_authorization_url") or "").strip()
    token_url = str(entry.get("oauth_token_url") or "").strip()
    token_auth_method = str(entry.get("oauth_token_auth_method") or "client_secret_post").strip().lower() or "client_secret_post"
    if token_auth_method not in {"client_secret_post", "client_secret_basic", "none"}:
        token_auth_method = "client_secret_post"
    scopes = [str(scope).strip() for scope in (entry.get("oauth_scopes") or []) if str(scope).strip()]
    return {
        "authorization_url": authorization_url,
        "token_url": token_url,
        "token_auth_method": token_auth_method,
        "scopes": scopes,
        "authorize_params": _trimmed_string_mapping(entry.get("oauth_extra_authorize_params")),
        "token_params": _trimmed_string_mapping(entry.get("oauth_extra_token_params")),
        "pkce": bool(entry.get("oauth_pkce", True)),
    }


def _saved_oauth_support(entry: dict[str, Any]) -> tuple[bool, str | None]:
    metadata = _mcp_oauth_entry_metadata(entry)
    if not metadata["authorization_url"] or not metadata["token_url"]:
        return False, "This OAuth-backed MCP entry still needs provider authorization metadata before KubeSynth can drive the sign-in flow."

    config_keys = {str(field.get("key") or "").strip() for field in _non_credential_fields_for_entry(entry)}
    credential_keys = {str(field.get("key") or "").strip() for field in _credential_fields_for_entry(entry)}
    has_client_id = bool(str(entry.get("oauth_client_id") or "").strip()) or "client_id" in config_keys or "client_id" in credential_keys
    if not has_client_id:
        return False, "This OAuth entry does not expose a client_id field or managed client registration yet."

    if metadata["token_auth_method"] != "none":
        has_client_secret = bool(str(entry.get("oauth_client_secret") or "").strip()) or "client_secret" in credential_keys
        if not has_client_secret:
            return False, "This OAuth entry does not expose a client_secret field or managed client secret yet."

    return True, None


def _mcp_oauth_client_id(connection_record: dict[str, Any], entry: dict[str, Any], secret_values: dict[str, str]) -> str:
    config = connection_record.get("config") if isinstance(connection_record.get("config"), dict) else {}
    client_id = str(config.get("client_id") or secret_values.get("client_id") or entry.get("oauth_client_id") or "").strip()
    if not client_id:
        raise HTTPException(status_code=400, detail="OAuth client_id is required before starting this MCP connection sign-in.")
    return client_id


def _mcp_oauth_client_secret(connection_record: dict[str, Any], entry: dict[str, Any], secret_values: dict[str, str]) -> str:
    del connection_record
    return str(secret_values.get("client_secret") or entry.get("oauth_client_secret") or "").strip()


def _mcp_oauth_redirect_uri(request: Request, connection_id: str) -> str:
    return f"{public_base_url(request)}/api/mcp/connections/{connection_id}/oauth/callback"


def _mcp_oauth_code_verifier() -> str:
    return base64.urlsafe_b64encode(os.urandom(48)).decode("ascii").rstrip("=")


def _mcp_oauth_code_challenge(code_verifier: str) -> str:
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def _build_mcp_oauth_token_request(
    entry: dict[str, Any],
    connection_record: dict[str, Any],
    *,
    grant_type: str,
    secret_values: dict[str, str],
    code: str | None = None,
    refresh_token: str | None = None,
    redirect_uri: str | None = None,
    code_verifier: str | None = None,
) -> tuple[str, dict[str, str], dict[str, str]]:
    metadata = _mcp_oauth_entry_metadata(entry)
    token_url = str(metadata["token_url"] or "").strip()
    if not token_url:
        raise HTTPException(status_code=400, detail="OAuth token exchange is not configured for this MCP registry entry.")

    client_id = _mcp_oauth_client_id(connection_record, entry, secret_values)
    client_secret = _mcp_oauth_client_secret(connection_record, entry, secret_values)
    headers = {"Accept": "application/json"}
    data = dict(metadata["token_params"])
    data["grant_type"] = grant_type

    if grant_type == "authorization_code":
        auth_code = str(code or "").strip()
        if not auth_code:
            raise HTTPException(status_code=400, detail="OAuth callback did not include an authorization code.")
        data["code"] = auth_code
        if redirect_uri:
            data["redirect_uri"] = redirect_uri
        if code_verifier:
            data["code_verifier"] = code_verifier
    elif grant_type == "refresh_token":
        refresh_value = str(refresh_token or secret_values.get("refresh_token") or "").strip()
        if not refresh_value:
            raise HTTPException(status_code=400, detail="No refresh token is stored for this MCP connection.")
        data["refresh_token"] = refresh_value
    else:
        raise HTTPException(status_code=400, detail=f"Unsupported OAuth grant type '{grant_type}'.")

    token_auth_method = str(metadata["token_auth_method"] or "client_secret_post")
    if token_auth_method == "client_secret_basic":
        if not client_secret:
            raise HTTPException(status_code=400, detail="OAuth client_secret is required before completing this MCP sign-in.")
        basic_token = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode("ascii")
        headers["Authorization"] = f"Basic {basic_token}"
    else:
        data["client_id"] = client_id
        if token_auth_method == "client_secret_post":
            if not client_secret:
                raise HTTPException(status_code=400, detail="OAuth client_secret is required before completing this MCP sign-in.")
            data["client_secret"] = client_secret

    return token_url, headers, data


def _extract_mcp_oauth_token_bundle(token_payload: Any, existing_secret_values: dict[str, str]) -> dict[str, str]:
    if not isinstance(token_payload, dict):
        raise HTTPException(status_code=502, detail="OAuth provider returned an unexpected token response.")

    access_token = str(token_payload.get("access_token") or "").strip()
    if not access_token:
        error_description = str(token_payload.get("error_description") or token_payload.get("error") or "").strip()
        raise HTTPException(
            status_code=502,
            detail=error_description or "OAuth provider did not return an access token.",
        )

    bundle = {
        "access_token": access_token,
        "token_type": str(token_payload.get("token_type") or existing_secret_values.get("token_type") or "Bearer").strip() or "Bearer",
    }

    refresh_token = str(token_payload.get("refresh_token") or existing_secret_values.get("refresh_token") or "").strip()
    if refresh_token:
        bundle["refresh_token"] = refresh_token

    raw_scope = str(token_payload.get("scope") or existing_secret_values.get("scope") or "").strip()
    if raw_scope:
        bundle["scope"] = raw_scope

    expires_in = token_payload.get("expires_in")
    if expires_in is not None:
        with contextlib.suppress(TypeError, ValueError):
            ttl_seconds = int(float(expires_in))
            if ttl_seconds > 0:
                bundle["expires_at"] = (datetime.now(UTC) + timedelta(seconds=ttl_seconds)).isoformat()

    return bundle


def _store_mcp_oauth_token_bundle(
    namespace: str,
    connection_id: str,
    existing_secret_values: dict[str, str],
    token_bundle: dict[str, str],
) -> tuple[str | None, dict[str, str]]:
    merged_secret_values = dict(existing_secret_values)
    merged_secret_values.update(token_bundle)
    if "expires_at" not in token_bundle:
        merged_secret_values.pop("expires_at", None)
    secret_name = _upsert_mcp_connection_secret(namespace, connection_id, merged_secret_values)
    return secret_name, merged_secret_values


def _build_mcp_connection_oauth_status(
    connection_record: dict[str, Any],
    entry: dict[str, Any],
    *,
    secret_values: dict[str, str] | None = None,
) -> dict[str, Any] | None:
    if str(entry.get("auth_type") or "none").strip().lower() != "oauth":
        return None

    resolved_secret_values = secret_values if secret_values is not None else _mcp_connection_secret_values_for_record(connection_record)
    access_token = str(resolved_secret_values.get("access_token") or "").strip()
    refresh_token = str(resolved_secret_values.get("refresh_token") or "").strip()
    expires_at = _parse_iso_datetime(resolved_secret_values.get("expires_at"))
    expiry_cutoff = datetime.now(UTC) + timedelta(seconds=_MCP_OAUTH_EXPIRY_SKEW_SECONDS)
    if access_token and (expires_at is None or expires_at > expiry_cutoff):
        state = "connected"
    elif access_token or refresh_token:
        state = "expired"
    else:
        state = "required"

    scope_value = str(resolved_secret_values.get("scope") or "").strip()
    scopes = [item for item in scope_value.split() if item] if scope_value else list(_mcp_oauth_entry_metadata(entry)["scopes"])
    return {
        "connected": state == "connected",
        "state": state,
        "expires_at": expires_at.isoformat() if expires_at else None,
        "refresh_available": bool(refresh_token),
        "scope": scopes,
    }


def _refresh_mcp_connection_oauth_access_token_sync(
    connection_record: dict[str, Any],
    entry: dict[str, Any],
    *,
    secret_values: dict[str, str] | None = None,
) -> dict[str, str]:
    resolved_secret_values = secret_values if secret_values is not None else _mcp_connection_secret_values_for_record(connection_record)
    token_url, headers, data = _build_mcp_oauth_token_request(
        entry,
        connection_record,
        grant_type="refresh_token",
        secret_values=resolved_secret_values,
    )
    try:
        with httpx.Client(timeout=15.0, follow_redirects=True, verify=certifi.where()) as client:
            response = client.post(token_url, data=data, headers=headers)
            response.raise_for_status()
            token_payload = response.json()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Failed to refresh MCP OAuth token: {exc}") from exc

    token_bundle = _extract_mcp_oauth_token_bundle(token_payload, resolved_secret_values)
    namespace = str(connection_record.get("namespace") or "default").strip() or "default"
    connection_id = str(connection_record.get("id") or "").strip()
    secret_name, merged_secret_values = _store_mcp_oauth_token_bundle(namespace, connection_id, resolved_secret_values, token_bundle)
    if secret_name and secret_name != connection_record.get("secret_name"):
        update_mcp_connection(namespace, connection_id, secret_name=secret_name)
    return merged_secret_values


def _ensure_mcp_connection_oauth_access_token(connection_record: dict[str, Any], entry: dict[str, Any]) -> dict[str, str]:
    if str(entry.get("auth_type") or "none").strip().lower() != "oauth":
        return _mcp_connection_secret_values_for_record(connection_record)

    secret_values = _mcp_connection_secret_values_for_record(connection_record)
    oauth_status = _build_mcp_connection_oauth_status(connection_record, entry, secret_values=secret_values)
    if oauth_status is None or str(oauth_status.get("state") or "required") == "connected":
        return secret_values
    if not bool(oauth_status.get("refresh_available")):
        return secret_values

    try:
        return _refresh_mcp_connection_oauth_access_token_sync(connection_record, entry, secret_values=secret_values)
    except HTTPException as exc:
        logger.warning(
            "Failed to refresh OAuth session for MCP connection %s/%s: %s",
            connection_record.get("namespace"),
            connection_record.get("id"),
            exc.detail,
        )
        return secret_values


def _resolved_mcp_connection_request_headers(
    connection_record: dict[str, Any],
    entry: dict[str, Any],
    *,
    secret_values: dict[str, str] | None = None,
) -> dict[str, str]:
    resolved_secret_values = secret_values if secret_values is not None else _mcp_connection_secret_values_for_record(connection_record)
    if not resolved_secret_values:
        return {}

    connection_id = str(connection_record.get("id") or "").strip()
    secret_name = str(connection_record.get("secret_name") or "").strip() or "mcp-connection-secret"
    configured_keys = _configured_credential_keys(connection_record.get("credential_metadata")) | set(resolved_secret_values)
    headers: dict[str, str] = {}
    for binding in _build_runtime_header_bindings(connection_id, entry, secret_name=secret_name, configured_keys=configured_keys):
        if not isinstance(binding, dict):
            continue
        secret_key_ref = binding.get("secretKeyRef") if isinstance(binding.get("secretKeyRef"), dict) else {}
        secret_key = str(secret_key_ref.get("key") or "").strip()
        header_name = str(binding.get("name") or "").strip()
        raw_value = str(resolved_secret_values.get(secret_key) or "").strip()
        if not header_name or not raw_value:
            continue
        prefix = str(binding.get("prefix") or "")
        headers[header_name] = f"{prefix}{raw_value}"
    return headers


def _restart_bound_agents_for_mcp_connection(namespace: str, connection_id: str) -> list[str]:
    bindings = _list_mcp_connection_bindings(namespace).get(connection_id, [])
    agent_names = sorted({str(item.get("agent_name") or "").strip() for item in bindings if item.get("agent_name")})
    if not agent_names:
        return []

    from kubernetes import client
    from kubernetes.client.rest import ApiException

    api = client.CoreV1Api()
    restarted: list[str] = []
    for agent_name in agent_names:
        pods = list_agent_pods(agent_name, namespace)
        for pod in pods:
            pod_name = str(getattr(getattr(pod, "metadata", None), "name", "") or "").strip()
            if not pod_name:
                continue
            try:
                api.delete_namespaced_pod(name=pod_name, namespace=namespace)
            except ApiException as exc:
                if exc.status != 404:
                    logger.warning("Failed to restart pod %s for MCP OAuth refresh: %s", pod_name, exc)
        restarted.append(agent_name)
    return restarted


def _build_saved_agent_mcp_connections(namespace: str, connection_ids: list[str]) -> list[dict[str, Any]]:
    normalized_ids = dedupe_text_values(connection_ids)
    if not normalized_ids:
        return []
    stored_connections = get_mcp_connection_rows_by_ids(namespace, normalized_ids)
    if len(stored_connections) != len(normalized_ids):
        found_ids = {row.id for row in stored_connections}
        missing_ids = [item_id for item_id in normalized_ids if item_id not in found_ids]
        raise HTTPException(status_code=400, detail=f"Unknown MCP connection ids: {', '.join(missing_ids)}")

    snapshots: list[dict[str, Any]] = []
    used_ports: set[int] = set()
    for row in stored_connections:
        stored = {
            "id": row.id,
            "namespace": row.namespace,
            "name": row.name,
            "slug": row.slug,
            "server_id": row.server_id,
            "transport": row.transport,
            "auth_type": row.auth_type,
            "config": copy.deepcopy(row.config_json) if isinstance(row.config_json, dict) else {},
            "credential_metadata": copy.deepcopy(row.credential_metadata_json)
            if isinstance(row.credential_metadata_json, list)
            else [],
            "secret_name": row.secret_name,
            "validation": {
                "status": row.validation_status,
                "message": row.validation_message,
                "detail": copy.deepcopy(row.validation_detail_json) if isinstance(row.validation_detail_json, dict) else None,
                "last_validated_at": row.last_validated_at.isoformat() if row.last_validated_at else None,
            },
        }
        entry = _lookup_mcp_registry_entry(row.server_id)
        if str(entry.get("auth_type") or "none").strip().lower() == "oauth":
            secret_values = _ensure_mcp_connection_oauth_access_token(stored, entry)
            oauth_status = _build_mcp_connection_oauth_status(stored, entry, secret_values=secret_values)
            if str((oauth_status or {}).get("state") or "required") != "connected":
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"MCP connection '{row.name}' needs a fresh OAuth session before it can be attached to an agent. "
                        "Reconnect or refresh it from the MCP page first."
                    ),
                )
        runtime_payload = _build_mcp_connection_runtime_payload(stored, entry)
        if runtime_payload.get("kind") == "sidecar":
            raw_port = ((runtime_payload.get("sidecar") or {}).get("port"))
            if isinstance(raw_port, int):
                if raw_port in used_ports:
                    raise HTTPException(status_code=400, detail=f"Duplicate MCP sidecar port detected: {raw_port}")
                used_ports.add(raw_port)
        snapshots.append(
            {
                "connectionId": row.id,
                "name": row.name,
                "slug": row.slug,
                "serverId": row.server_id,
                "serverName": entry.get("name"),
                "transport": entry.get("transport"),
                "supportLevel": entry.get("support_level", "planned"),
                "attachable": bool(entry.get("attachable")),
                "statusReason": entry.get("status_reason"),
                "source": "saved",
                "config": stored["config"],
                "credentialMetadata": stored["credential_metadata"],
                "validation": stored["validation"],
                "runtime": runtime_payload,
            }
        )
    return snapshots


def _build_legacy_agent_mcp_connections(mcp_servers: list[str], mcp_sidecars: list[dict[str, Any]]) -> list[dict[str, Any]]:
    registry_by_id = _mcp_registry_index()
    snapshots: list[dict[str, Any]] = []

    for server_name in dedupe_text_values(mcp_servers):
        entry = registry_by_id.get(server_name)
        if entry is None:
            for candidate in registry_by_id.values():
                if str(candidate.get("hub_server_name") or "").strip() == server_name:
                    entry = candidate
                    break
        if entry is None:
            url = f"http://{HELM_RELEASE_NAME}-mcp-{server_name}.{MCP_HUB_NAMESPACE}.svc.cluster.local:8000/mcp"
            snapshots.append(
                {
                    "connectionId": None,
                    "name": server_name,
                    "slug": slugify_mcp_connection_name(server_name),
                    "serverId": server_name,
                    "serverName": server_name,
                    "transport": "hub",
                    "supportLevel": "limited",
                    "attachable": True,
                    "statusReason": "Legacy shared MCP server reference.",
                    "source": "legacy",
                    "config": {"endpoint_url": url},
                    "credentialMetadata": [],
                    "validation": {"status": "draft", "message": None, "detail": None, "last_validated_at": None},
                    "runtime": {
                        "kind": "remote",
                        "configKey": slugify_mcp_connection_name(server_name),
                        "url": url,
                        "headers": [{"name": "Authorization", "envVar": "MCP_BEARER_TOKEN", "prefix": "Bearer "}],
                    },
                }
            )
            continue

        endpoint_url = str(entry.get("endpoint") or "").strip()
        if str(entry.get("transport") or "") == "hub":
            endpoint_url = _build_hub_mcp_url(entry)
        snapshots.append(
            {
                "connectionId": None,
                "name": entry.get("name"),
                "slug": slugify_mcp_connection_name(entry.get("name") or server_name),
                "serverId": entry.get("id"),
                "serverName": entry.get("name"),
                "transport": entry.get("transport"),
                "supportLevel": entry.get("support_level", "planned"),
                "attachable": bool(entry.get("attachable")),
                "statusReason": entry.get("status_reason"),
                "source": "legacy",
                "config": {"endpoint_url": endpoint_url} if endpoint_url else {},
                "credentialMetadata": [],
                "validation": {"status": "draft", "message": None, "detail": None, "last_validated_at": None},
                "runtime": {
                    "kind": "remote",
                    "configKey": slugify_mcp_connection_name(entry.get("name") or server_name),
                    "url": endpoint_url,
                    "headers": (
                        [{"name": "Authorization", "envVar": "MCP_BEARER_TOKEN", "prefix": "Bearer "}]
                        if str(entry.get("transport") or "") == "hub"
                        else []
                    ),
                },
            }
        )

    for index, sidecar in enumerate(mcp_sidecars):
        if not isinstance(sidecar, dict):
            continue
        raw_name = str(sidecar.get("name") or f"sidecar-{index}").strip() or f"sidecar-{index}"
        raw_image = str(sidecar.get("image") or "").strip()
        try:
            port = int(sidecar.get("port", 8097))
        except (TypeError, ValueError):
            port = 8097
        snapshots.append(
            {
                "connectionId": None,
                "name": raw_name,
                "slug": slugify_mcp_connection_name(raw_name),
                "serverId": raw_name,
                "serverName": raw_name,
                "transport": "sidecar",
                "supportLevel": "limited",
                "attachable": True,
                "statusReason": "Legacy sidecar MCP definition.",
                "source": "legacy",
                "config": {"sidecar_image": raw_image, "sidecar_port": port, "endpoint_path": "/mcp"},
                "credentialMetadata": [],
                "validation": {"status": "draft", "message": None, "detail": None, "last_validated_at": None},
                "runtime": {
                    "kind": "sidecar",
                    "configKey": slugify_mcp_connection_name(raw_name),
                    "sidecar": {
                        "name": raw_name,
                        "image": raw_image,
                        "port": port,
                        "endpointPath": "/mcp",
                        "env": [],
                    },
                },
            }
        )
    return snapshots


def _derive_legacy_mcp_fields_from_connections(mcp_connections: list[dict[str, Any]]) -> tuple[list[str], list[dict[str, Any]]]:
    servers: list[str] = []
    sidecars: list[dict[str, Any]] = []
    registry_by_id = _mcp_registry_index()
    for connection in mcp_connections:
        if not isinstance(connection, dict):
            continue
        transport = str(connection.get("transport") or "").strip().lower()
        server_id = str(connection.get("serverId") or "").strip()
        if transport in {"hub", "remote"} and server_id:
            entry = registry_by_id.get(server_id)
            if entry is not None and str(entry.get("transport") or "") == "hub":
                servers.append(str(entry.get("hub_server_name") or server_id).strip() or server_id)
            else:
                servers.append(server_id)
            continue
        sidecar = ((connection.get("runtime") or {}).get("sidecar")) if isinstance(connection.get("runtime"), dict) else None
        if isinstance(sidecar, dict):
            try:
                port = int(sidecar.get("port", 8097))
            except (TypeError, ValueError):
                port = 8097
            sidecars.append(
                {
                    "name": str(sidecar.get("name") or server_id or connection.get("slug") or "sidecar").strip() or "sidecar",
                    "image": str(sidecar.get("image") or "").strip(),
                    "port": port,
                }
            )
    return dedupe_text_values(servers), sidecars


def _resolve_agent_mcp_connections(
    body: CreateAgentRequest | UpdateAgentRequest,
    *,
    namespace: str,
    existing_spec: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    requested_connection_ids = getattr(body, "mcp_connection_ids", None)
    legacy_servers = dedupe_text_values([server.strip() for server in getattr(body, "mcp_servers", []) if server.strip()])
    legacy_sidecars = getattr(body, "mcp_sidecars", []) or []

    if requested_connection_ids:
        return _build_saved_agent_mcp_connections(namespace, requested_connection_ids)

    if requested_connection_ids == [] and (legacy_servers or legacy_sidecars):
        return _build_legacy_agent_mcp_connections(legacy_servers, legacy_sidecars)

    existing_connections = (existing_spec or {}).get("mcpConnections") if isinstance((existing_spec or {}).get("mcpConnections"), list) else []
    if requested_connection_ids is None and existing_connections:
        return copy.deepcopy(existing_connections)

    if legacy_servers or legacy_sidecars:
        return _build_legacy_agent_mcp_connections(legacy_servers, legacy_sidecars)

    return []


def _list_mcp_connection_bindings(namespace: str) -> dict[str, list[dict[str, Any]]]:
    bindings: dict[str, list[dict[str, Any]]] = {}
    for agent in get_agents(namespace):
        metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
        spec = agent.get("spec") if isinstance(agent.get("spec"), dict) else {}
        raw_connections = spec.get("mcpConnections") if isinstance(spec.get("mcpConnections"), list) else []
        if not raw_connections:
            raw_connections = _build_legacy_agent_mcp_connections(spec.get("mcpServers") or [], spec.get("mcpSidecars") or [])
        for connection in raw_connections:
            if not isinstance(connection, dict):
                continue
            connection_id = str(connection.get("connectionId") or "").strip()
            if not connection_id:
                continue
            bindings.setdefault(connection_id, []).append(
                {
                    "agent_name": str(metadata.get("name") or "").strip(),
                    "namespace": str(metadata.get("namespace") or namespace).strip() or namespace,
                    "connection_id": connection_id,
                    "connection_name": str(connection.get("name") or connection.get("slug") or connection_id).strip(),
                    "server_id": str(connection.get("serverId") or "").strip(),
                    "transport": str(connection.get("transport") or "").strip() or "unknown",
                }
            )
    return bindings


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
            raise A2AJSONRPCError(
                JSONRPC_INVALID_PARAMS, "assistant_id must use namespace/name syntax when it contains '/'"
            )
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
        fallback=(f"{agent.runtime_kind.capitalize()} assistant backed by model {agent.model}."),
    )
    base_tags = dedupe_text_values(
        [
            "assistant",
            agent.runtime_kind,
            agent.model,
            *agent.mcp_servers,
            *(str(sidecar.get("name") or "") for sidecar in agent.mcp_sidecars if isinstance(sidecar, dict)),
            *(["a2a", "delegation"] if policy_targets else []),
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

    if agent.skill_summaries:
        for summary in agent.skill_summaries:
            summary_name = str(summary.get("name") or "skill").strip() or "skill"
            summary_description = summarize_text(
                str(summary.get("description") or summary.get("instructions_preview") or "").strip(),
                fallback=f"Skill file {summary.get('path') or summary_name}",
            )
            tags = dedupe_text_values(
                [
                    "skill",
                    *(summary.get("allowed_mcp_servers") or []),
                    *(["sandbox"] if summary.get("allowed_sandbox_tools") else []),
                    *(["a2a"] if summary.get("allowed_a2a_targets") else []),
                    *(["subagents"] if summary.get("allow_subagents") else []),
                ]
            )
            skills.append(
                {
                    "id": skill_id(f"{agent.name}-{summary_name}"),
                    "name": summary_name,
                    "description": summary_description,
                    "tags": tags or ["skill"],
                    "inputModes": ["text/plain"],
                    "outputModes": ["text/plain"],
                }
            )
        return skills

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
        "supportedInterfaces": [
            {
                "url": interface_url,
                "protocolBinding": "JSONRPC",
                "protocolVersion": A2A_PROTOCOL_VERSION,
                "tenant": namespace,
            }
        ],
        "provider": {
            "organization": A2A_PROVIDER_ORGANIZATION or "kubesynthai",
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
                    "bearerFormat": "JWT"
                    if AUTH_MODE in {"oidc", "local", "hybrid", "enterprise", "auto"}
                    else "Opaque",
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


def create_a2a_task_record(
    agent_name: str, namespace: str, context_id: str, task_id: str, thread_id: str
) -> dict[str, Any]:
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
        raise A2AJSONRPCError(
            JSONRPC_INVALID_PARAMS, "message.parts must contain at least one non-empty text or data part"
        )

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


def parse_a2a_passthrough_metadata(raw_value: Any) -> dict[str, Any]:
    if raw_value is None:
        return {}
    if not isinstance(raw_value, dict):
        raise A2AJSONRPCError(JSONRPC_INVALID_PARAMS, "metadata must be an object when provided")

    passthrough = raw_value.get("kubesynthInvoke")
    if passthrough is None:
        return {}
    if not isinstance(passthrough, dict):
        raise A2AJSONRPCError(JSONRPC_INVALID_PARAMS, "metadata.kubesynthInvoke must be an object when provided")

    parsed: dict[str, Any] = {}
    thread_id = str(passthrough.get("threadId") or "").strip()
    if thread_id:
        parsed["thread_id"] = thread_id

    system = str(passthrough.get("system") or "").strip()
    if system:
        parsed["system"] = system

    model = str(passthrough.get("model") or "").strip()
    if model:
        parsed["model"] = model

    caller_agent_name = str(passthrough.get("callerAgentName") or "").strip()
    if caller_agent_name:
        parsed["caller_agent_name"] = caller_agent_name

    caller_agent_namespace = str(passthrough.get("callerAgentNamespace") or "").strip()
    if caller_agent_namespace:
        parsed["caller_agent_namespace"] = caller_agent_namespace

    parent_thread_id = str(passthrough.get("parentThreadId") or "").strip()
    if parent_thread_id:
        parsed["parent_thread_id"] = parent_thread_id

    caller_request_id = str(passthrough.get("callerRequestId") or "").strip()
    if caller_request_id:
        parsed["caller_request_id"] = caller_request_id

    sandbox_session = passthrough.get("sandboxSession")
    if sandbox_session is not None:
        if not isinstance(sandbox_session, dict):
            raise A2AJSONRPCError(
                JSONRPC_INVALID_PARAMS,
                "metadata.kubesynthInvoke.sandboxSession must be an object when provided",
            )
        parsed["sandbox_session"] = copy.deepcopy(sandbox_session)

    team_context = passthrough.get("teamContext")
    if team_context is not None:
        if not isinstance(team_context, dict):
            raise A2AJSONRPCError(
                JSONRPC_INVALID_PARAMS,
                "metadata.kubesynthInvoke.teamContext must be an object when provided",
            )
        parsed["team_context"] = copy.deepcopy(team_context)

    return parsed


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
) -> tuple[dict[str, Any], str, int | None, dict[str, Any]]:
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
    passthrough_metadata = parse_a2a_passthrough_metadata(params.get("metadata"))
    requested_thread_id = str(passthrough_metadata.get("thread_id") or "").strip() or None

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
        context_id = (
            context_id
            or infer_context_from_reference_tasks(agent_name, namespace, reference_task_ids)
            or str(uuid.uuid4())
        )
        task_id = str(uuid.uuid4())
        record = create_a2a_task_record(
            agent_name,
            namespace,
            context_id,
            task_id,
            requested_thread_id or context_id,
        )
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
    team_context = passthrough_metadata.get("team_context")
    team_context = copy.deepcopy(team_context) if isinstance(team_context, dict) else {}
    team_context.update({
        "mode": "a2a-jsonrpc",
        "contextId": context_id,
        "taskId": task_id,
        "messageId": message_id,
        "workingAgreement": [
            "Treat this as one step in an A2A collaboration.",
            "Return concrete results that another agent can reuse.",
            "Mention blockers or missing information explicitly.",
        ],
    })
    if reference_task_ids:
        team_context["referenceTaskIds"] = reference_task_ids
    if isinstance(metadata, dict) and metadata:
        team_context["messageMetadata"] = metadata

    invoke_options: dict[str, Any] = {
        "thread_id": str(record.get("threadId") or "").strip() or context_id,
        "team_context": team_context,
    }
    for key in (
        "system",
        "model",
        "caller_agent_name",
        "caller_agent_namespace",
        "parent_thread_id",
        "caller_request_id",
        "sandbox_session",
    ):
        value = passthrough_metadata.get(key)
        if value:
            invoke_options[key] = value
    return record, prompt, history_length, invoke_options


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
    record, prompt, history_length, invoke_options = prepare_a2a_task_for_message(agent_name, namespace, params)
    set_a2a_task_status(record, "TASK_STATE_WORKING", None, {"status": "working"})
    store_a2a_task_record(record)

    raw_request = cast(Request, SimpleNamespace(headers={"x-request-id": gateway_request_id}))
    invoke_request = InvokeRequest(
        prompt=prompt,
        thread_id=str(invoke_options.get("thread_id") or ""),
        team_context=invoke_options.get("team_context"),
        system=invoke_options.get("system"),
        model=invoke_options.get("model"),
        caller_agent_name=invoke_options.get("caller_agent_name"),
        caller_agent_namespace=invoke_options.get("caller_agent_namespace"),
        parent_thread_id=invoke_options.get("parent_thread_id"),
        caller_request_id=invoke_options.get("caller_request_id"),
        sandbox_session=invoke_options.get("sandbox_session"),
    )
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


async def iter_runtime_sse_events(body_iterator: Any) -> AsyncGenerator[tuple[str, str], None]:
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
    record, prompt, history_length, invoke_options = prepare_a2a_task_for_message(agent_name, namespace, params)
    set_a2a_task_status(record, "TASK_STATE_WORKING", None, {"status": "working"})
    store_a2a_task_record(record)

    raw_request = cast(Request, SimpleNamespace(headers={"x-request-id": gateway_request_id}))
    invoke_request = InvokeRequest(
        prompt=prompt,
        thread_id=str(invoke_options.get("thread_id") or ""),
        team_context=invoke_options.get("team_context"),
        system=invoke_options.get("system"),
        model=invoke_options.get("model"),
        caller_agent_name=invoke_options.get("caller_agent_name"),
        caller_agent_namespace=invoke_options.get("caller_agent_namespace"),
        parent_thread_id=invoke_options.get("parent_thread_id"),
        caller_request_id=invoke_options.get("caller_request_id"),
        sandbox_session=invoke_options.get("sandbox_session"),
    )

    async def event_generator() -> AsyncGenerator[str, None]:
        try:
            upstream_response = await invoke_agent_stream(agent_name, invoke_request, raw_request, namespace, user={})
        except HTTPException as exc:
            mark_a2a_task_failed(record, str(exc.detail))
            yield jsonrpc_sse_message(
                jsonrpc_success_response(request_id, {"task": public_a2a_task(record, history_length)})
            )
            yield jsonrpc_sse_message(
                jsonrpc_success_response(request_id, {"statusUpdate": task_status_update_event(record)})
            )
            return
        except Exception as exc:
            logger.exception("A2A SendStreamingMessage failed to start for %s/%s", namespace, agent_name)
            mark_a2a_task_failed(record, f"Agent invocation failed: {exc}")
            yield jsonrpc_sse_message(
                jsonrpc_success_response(request_id, {"task": public_a2a_task(record, history_length)})
            )
            yield jsonrpc_sse_message(
                jsonrpc_success_response(request_id, {"statusUpdate": task_status_update_event(record)})
            )
            return

        yield jsonrpc_sse_message(
            jsonrpc_success_response(request_id, {"task": public_a2a_task(record, history_length)})
        )

        try:
            async for event_name, raw_data in iter_runtime_sse_events(upstream_response.body_iterator):
                try:
                    payload = json.loads(raw_data)
                except json.JSONDecodeError as exc:
                    mark_a2a_task_failed(record, f"Invalid upstream stream payload: {exc}")
                    yield jsonrpc_sse_message(
                        jsonrpc_success_response(request_id, {"statusUpdate": task_status_update_event(record)})
                    )
                    return

                if event_name == "response.delta":
                    delta = str(payload.get("delta") or "")
                    if not delta:
                        continue
                    append_a2a_task_artifact_delta(record, delta)
                    store_a2a_task_record(record)
                    yield jsonrpc_sse_message(
                        jsonrpc_success_response(
                            request_id,
                            {
                                "artifactUpdate": task_artifact_update_event(
                                    record, delta, append=True, last_chunk=False
                                )
                            },
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
                    if payload.get("artifacts"):
                        metadata_updates["artifacts"] = payload.get("artifacts")
                    if payload.get("tool_calls"):
                        metadata_updates["toolCalls"] = payload.get("tool_calls")
                    if payload.get("metadata") is not None:
                        metadata_updates["metadata"] = payload.get("metadata")

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
                    yield jsonrpc_sse_message(
                        jsonrpc_success_response(request_id, {"statusUpdate": task_status_update_event(record)})
                    )
                    return

                if event_name == "response.error":
                    error_message = str(payload.get("error") or "Agent invocation failed")
                    mark_a2a_task_failed(record, error_message)
                    store_a2a_task_record(record)
                    yield jsonrpc_sse_message(
                        jsonrpc_success_response(request_id, {"statusUpdate": task_status_update_event(record)})
                    )
                    return
        except Exception as exc:
            logger.exception("A2A SendStreamingMessage failed while translating the upstream stream")
            mark_a2a_task_failed(record, f"Agent invocation failed: {exc}")
            store_a2a_task_record(record)
            yield jsonrpc_sse_message(
                jsonrpc_success_response(request_id, {"statusUpdate": task_status_update_event(record)})
            )
        finally:
            if hasattr(upstream_response.body_iterator, "aclose"):
                await upstream_response.body_iterator.aclose()  # type: ignore[union-attr]

    return StreamingResponse(event_generator(), media_type="text/event-stream")


def handle_a2a_get_task(agent_name: str, namespace: str, params: dict[str, Any], request_id: Any) -> dict[str, Any]:
    task_id = str(params.get("id") or "").strip()
    if not task_id:
        raise A2AJSONRPCError(JSONRPC_INVALID_PARAMS, "params.id is required")
    purge_expired_a2a_tasks()
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
    *,
    namespace: str = "default",
) -> dict[str, Any]:
    def _parse_namespaced_ref(raw_ref: str | None) -> tuple[str | None, str | None]:
        value = str(raw_ref or "").strip()
        if not value:
            return None, None
        if "/" not in value:
            return None, value
        ref_namespace, ref_name = value.split("/", 1)
        return ref_namespace.strip() or None, ref_name.strip() or None

    existing_runtime = (existing_spec or {}).get("runtime") or {}
    existing_runtime_kind = None
    existing_opencode_config_files: Any = None
    existing_a2a_config: Any = (existing_spec or {}).get("a2a")
    existing_skills: Any = (existing_spec or {}).get("skills")
    if isinstance(existing_runtime, dict):
        existing_runtime_kind = existing_runtime.get("kind")
        existing_opencode = existing_runtime.get("opencode") or {}
        if isinstance(existing_opencode, dict):
            existing_opencode_config_files = existing_opencode.get("configFiles")

    try:
        runtime_kind = normalized_opencode_runtime_kind(
            getattr(body, "runtime_kind", None) or existing_runtime_kind,
            field_name="runtime_kind",
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    requested_opencode_config_files = getattr(body, "opencode_config_files", None)
    if requested_opencode_config_files is None:
        opencode_config_files = parse_opencode_config_files(
            existing_opencode_config_files,
            source="existing runtime.opencode.configFiles",
        )
    else:
        opencode_config_files = parse_opencode_config_files(
            requested_opencode_config_files,
            source="opencode_config_files",
        )

    requested_a2a_config = getattr(body, "a2a_config", None)
    if requested_a2a_config is None:
        a2a_config = parse_a2a_agent_config(existing_a2a_config, source="existing spec.a2a")
    else:
        a2a_config = parse_a2a_agent_config(requested_a2a_config, source="a2a_config")

    requested_skills = getattr(body, "skills", None)
    if requested_skills is None:
        skills_config = parse_agent_skills_config(existing_skills, source="existing spec.skills", strict=False)
    else:
        skills_config = parse_agent_skills_config(requested_skills, source="skills", strict=True)

    if runtime_kind != "opencode" and opencode_config_files:
        raise HTTPException(
            status_code=400,
            detail="opencode_config_files is only supported when runtime_kind is 'opencode'",
        )

    policy_ref = str(getattr(body, "policy_ref", None) or "").strip() or None
    if policy_ref:
        policy_namespace, policy_name = _parse_namespaced_ref(policy_ref)
        resolved_policy_namespace = policy_namespace or namespace
        if not policy_name:
            raise HTTPException(status_code=400, detail="policy_ref must not be blank")
        read_custom_resource("agentpolicies", policy_name, resolved_policy_namespace, "Policy")

    requested_git_config = getattr(body, "git_config", None)
    if requested_git_config is None:
        git_config = parse_agent_git_config((existing_spec or {}).get("gitConfig"), source="existing spec.gitConfig")
    else:
        git_config = parse_agent_git_config(requested_git_config, source="git_config")

    requested_github_config = getattr(body, "github_config", None)
    if requested_github_config is None:
        github_config = parse_agent_github_config(
            (existing_spec or {}).get("githubConfig"), source="existing spec.githubConfig"
        )
    else:
        github_config = parse_agent_github_config(requested_github_config, source="github_config")

    mcp_connections = _resolve_agent_mcp_connections(body, namespace=namespace, existing_spec=existing_spec)
    mcp_servers, mcp_sidecars = _derive_legacy_mcp_fields_from_connections(mcp_connections)
    if github_config and "github" not in mcp_servers:
        mcp_servers.append("github")

    spec: dict[str, Any] = {
        "model": body.model.strip(),
        "systemPrompt": body.system_prompt.strip(),
        "enableGVisor": body.enable_gvisor,
        "storage": {"size": (body.storage_size or "1Gi").strip() or "1Gi"},
        "mcpConnections": mcp_connections,
        "mcpServers": mcp_servers,
        "mcpSidecars": mcp_sidecars,
        "runtime": {"kind": runtime_kind},
    }
    if a2a_config:
        spec["a2a"] = a2a_config
    if skills_config:
        spec["skills"] = skills_config
    if runtime_kind == "opencode" and opencode_config_files:
        spec["runtime"]["opencode"] = {"configFiles": opencode_config_files}
    if policy_ref:
        spec["policyRef"] = policy_ref
    if git_config:
        spec["gitConfig"] = git_config
    if github_config:
        spec["githubConfig"] = github_config

    return spec


def build_workflow_spec(body: WorkflowRequest | WorkflowUpdateRequest) -> dict[str, Any]:
    steps = []
    step_names: set[str] = set()
    for step in body.steps:
        trimmed_name = step.name.strip()
        if not trimmed_name:
            raise HTTPException(status_code=400, detail="All workflow steps must have a non-empty name.")
        if trimmed_name in step_names:
            raise HTTPException(status_code=400, detail=f"Duplicate step name: '{trimmed_name}'")
        step_names.add(trimmed_name)
        step_spec: dict[str, Any] = {
            "name": trimmed_name,
            "agentRef": step.agent_ref.strip(),
            "prompt": step.prompt,
            "dependsOn": [dependency.strip() for dependency in step.depends_on if dependency.strip()],
            "requireApproval": step.require_approval,
        }
        if step.step_type == "loop":
            step_spec["type"] = "loop"
            if isinstance(step.loop_config, dict) and step.loop_config:
                step_spec["loopConfig"] = step.loop_config
        if step.step_type == "conditional":
            step_spec["type"] = "conditional"
            if step.condition_expr:
                step_spec["conditionExpr"] = step.condition_expr.strip()
            if step.then_steps:
                step_spec["thenSteps"] = [s.strip() for s in step.then_steps if s.strip()]
            if step.else_steps:
                step_spec["elseSteps"] = [s.strip() for s in step.else_steps if s.strip()]
        if step.step_type == "review":
            step_spec["type"] = "review"
            if step.review_criteria and step.review_criteria.strip():
                step_spec["reviewCriteria"] = step.review_criteria.strip()
        if step.verify and step.verify.strip():
            step_spec["verify"] = step.verify.strip()
        if isinstance(step.execution, dict) and step.execution:
            step_spec["execution"] = step.execution
        steps.append(step_spec)

    # Validate dependency references and detect cycles
    for step_spec in steps:
        for dep in step_spec.get("dependsOn", []):
            if dep not in step_names:
                raise HTTPException(
                    status_code=400, detail=f"Step '{step_spec['name']}' depends on unknown step '{dep}'"
                )
    _detect_workflow_cycles(steps)

    workflow_spec = {
        "description": body.description.strip(),
        "input": body.input.strip(),
        "messageBus": body.message_bus,
        "steps": steps,
    }
    if getattr(body, "context_ref", None) and str(body.context_ref).strip():
        workflow_spec["contextRef"] = str(body.context_ref).strip()
    return workflow_spec


def _detect_workflow_cycles(steps: list[dict[str, Any]]) -> None:
    """Detect dependency cycles in workflow steps using Kahn's algorithm."""
    adj: dict[str, list[str]] = {s["name"]: list(s.get("dependsOn") or []) for s in steps}
    in_degree: dict[str, int] = dict.fromkeys(adj, 0)
    for deps in adj.values():
        for dep in deps:
            if dep in in_degree:
                in_degree[dep] += 1
    queue = [name for name, degree in in_degree.items() if degree == 0]
    visited = 0
    while queue:
        node = queue.pop(0)
        visited += 1
        for dep in adj.get(node, []):
            if dep in in_degree:
                in_degree[dep] -= 1
                if in_degree[dep] == 0:
                    queue.append(dep)
    if visited != len(adj):
        raise HTTPException(status_code=400, detail="Workflow steps contain a dependency cycle.")


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
        raise HTTPException(status_code=502, detail=f"Failed to list {plural}") from exc


def read_custom_resource(plural: str, name: str, namespace: str, label: str) -> dict[str, Any]:
    try:
        from kubernetes import client

        return cast(
            dict[str, Any],
            client.CustomObjectsApi().get_namespaced_custom_object(
                group=RESOURCE_GROUP,
                version=RESOURCE_VERSION,
                namespace=namespace,
                plural=plural,
                name=name,
            ),
        )
    except Exception as exc:
        logger.warning("Resource read failed (%s/%s): %s", plural, name, exc)
        raise HTTPException(status_code=404, detail=f"{label} '{name}' not found") from exc


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
        logger.error("Failed to create resource %s: %s", name, exc)
        raise HTTPException(status_code=502, detail=f"Failed to create resource '{name}'") from exc


def replace_custom_resource_spec(plural: str, name: str, namespace: str, spec: dict[str, Any]) -> dict[str, Any]:
    try:
        from kubernetes import client

        api = client.CustomObjectsApi()
        current = cast(
            dict[str, Any],
            api.get_namespaced_custom_object(
                group=RESOURCE_GROUP,
                version=RESOURCE_VERSION,
                namespace=namespace,
                plural=plural,
                name=name,
            ),
        )
        updated = api.replace_namespaced_custom_object(
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
        if plural == "aiagents":
            invalidate_agent_read_cache(agent_name=name, namespace=namespace)
        return updated
    except Exception as exc:
        status = getattr(exc, "status", None)
        if status == 404:
            raise HTTPException(status_code=404, detail=f"Resource '{name}' was not found") from exc
        logger.error("Failed to update resource %s: %s", name, exc)
        raise HTTPException(status_code=502, detail=f"Failed to update resource '{name}'") from exc


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
        if plural == "aiagents":
            invalidate_agent_read_cache(agent_name=name, namespace=namespace)
    except Exception as exc:
        status = getattr(exc, "status", None)
        if status == 404:
            raise HTTPException(status_code=404, detail=f"{label} '{name}' not found") from exc
        logger.error("Failed to delete %s %s: %s", label, name, exc)
        raise HTTPException(status_code=502, detail=f"Failed to delete {label} '{name}'") from exc


def policy_info_from_resource(policy: dict[str, Any]) -> PolicyInfo:
    metadata = policy.get("metadata", {})
    spec = policy.get("spec", {})
    return PolicyInfo(
        name=metadata.get("name", ""),
        namespace=metadata.get("namespace", "default"),
        input_guardrails=spec.get("inputGuardrails") or {},
        output_guardrails=spec.get("outputGuardrails") or {},
        allowed_models=spec.get("allowedModels") or [],
        allowed_mcp_servers=spec.get("allowedMcpServers") or [],
        mcp_require_hitl=spec.get("mcpRequireHitl", True),
        tool_policy=spec.get("toolPolicy") or {},
        memory_policy=spec.get("memoryPolicy") or {},
    )


def agent_info_from_resource(agent: dict[str, Any]) -> AgentInfo:
    metadata = agent.get("metadata", {})
    spec = agent.get("spec", {})
    runtime_spec = spec.get("runtime") or {}
    runtime_kind = "unknown"
    if isinstance(runtime_spec, dict):
        runtime_kind = str(runtime_spec.get("kind") or "").strip().lower() or "unknown"
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
    _opencode = runtime.get("opencode")
    opencode_runtime: dict[str, Any] = _opencode if isinstance(_opencode, dict) else {}
    try:
        skills_config = parse_agent_skills_config(spec.get("skills"), source="AIAgent.spec.skills", strict=False)
    except HTTPException as exc:
        logger.warning("Ignoring invalid skills config for agent %s/%s: %s", info.namespace, info.name, exc.detail)
        skills_config = {}
    raw_mcp_connections = spec.get("mcpConnections") if isinstance(spec.get("mcpConnections"), list) else None
    mcp_connections = copy.deepcopy(raw_mcp_connections) if raw_mcp_connections is not None else _build_legacy_agent_mcp_connections(
        spec.get("mcpServers") or [],
        spec.get("mcpSidecars") or [],
    )
    mcp_servers = spec.get("mcpServers") if isinstance(spec.get("mcpServers"), list) else []
    mcp_sidecars = spec.get("mcpSidecars") if isinstance(spec.get("mcpSidecars"), list) else []
    if (not mcp_servers and not mcp_sidecars) and mcp_connections:
        mcp_servers, mcp_sidecars = _derive_legacy_mcp_fields_from_connections(mcp_connections)
    return AgentDetail(
        **info.model_dump(),
        system_prompt=spec.get("systemPrompt", "") or "",
        policy_ref=spec.get("policyRef"),
        storage_size=storage.get("size"),
        enable_gvisor=bool(spec.get("enableGVisor", False)),
        mcp_connections=mcp_connections,
        mcp_servers=mcp_servers,
        mcp_sidecars=mcp_sidecars,
        a2a_config=parse_a2a_agent_config(spec.get("a2a"), source="AIAgent.spec.a2a"),
        skills=skills_config,
        skill_summaries=parse_agent_skill_summaries(skills_config),
        opencode_config_files=parse_opencode_config_files(
            opencode_runtime.get("configFiles"),
            source="AIAgent.spec.runtime.opencode.configFiles",
        ),
        git_config=serialize_agent_git_config(spec.get("gitConfig")),
        github_config=serialize_agent_github_config(spec.get("githubConfig")),
        created_at=metadata.get("creationTimestamp"),
    )


def policy_a2a_targets_from_resource(policy: dict[str, Any]) -> list[dict[str, str]]:
    _spec = policy.get("spec")
    spec: dict[str, Any] = _spec if isinstance(_spec, dict) else {}
    config = parse_a2a_policy_config(spec.get("a2a"), source="AgentPolicy.spec.a2a")
    return list(config.get("allowedTargets") or [])


def runtime_supports_direct_chat_delegation(runtime_kind: str) -> bool:
    return False


def format_a2a_peer_ref_list(peer_refs: list[dict[str, str]], *, max_items: int = 6) -> str:
    labels = [f"{item['namespace']}/{item['name']}" for item in peer_refs if item.get("namespace") and item.get("name")]
    if not labels:
        return "none"
    if len(labels) <= max_items:
        return ", ".join(labels)
    remainder = len(labels) - max_items
    return f"{', '.join(labels[:max_items])}, +{remainder} more"


def build_agent_collaboration_system_note(agent_name: str, namespace: str, agent: dict[str, Any]) -> str | None:
    _spec = agent.get("spec")
    spec: dict[str, Any] = _spec if isinstance(_spec, dict) else {}
    runtime_kind = runtime_kind_from_spec(spec)
    runtime_label = "OpenCode" if runtime_kind == "opencode" else (runtime_kind.capitalize() if runtime_kind else "Agent")
    inbound_callers = parse_a2a_agent_config(
        spec.get("a2a"),
        source=f"AIAgent[{namespace}/{agent_name}].spec.a2a",
    ).get("allowedCallers", [])
    policy_ref = str(spec.get("policyRef") or "").strip() or None

    outbound_targets: list[dict[str, str]] = []
    if policy_ref:
        try:
            outbound_targets = policy_a2a_targets_from_resource(
                read_custom_resource("agentpolicies", policy_ref, namespace, "Policy")
            )
        except HTTPException as exc:
            if exc.status_code != 404:
                raise
            logger.warning(
                "Agent %s/%s references missing policy %s while building collaboration note",
                namespace,
                agent_name,
                policy_ref,
            )

    discovery: AgentDiscoveryResponse | None = None
    if policy_ref:
        try:
            discovery = discover_agent_peers(agent_name, namespace)
        except HTTPException:
            logger.warning(
                "Failed to discover peer agents for %s/%s while building collaboration note",
                namespace,
                agent_name,
                exc_info=True,
            )

    if not inbound_callers and not policy_ref and not outbound_targets and not (discovery and discovery.peers):
        return None

    lines = ["COLLABORATION CONTEXT:"]
    lines.append(f"- Agents allowed to call you (inbound A2A): {format_a2a_peer_ref_list(inbound_callers)}")
    if policy_ref:
        lines.append(f"- Outbound delegation policy: {policy_ref}")
    else:
        lines.append("- Outbound delegation policy: none configured")
    lines.append(
        f"- Agents you are configured to call (outbound policy targets): {format_a2a_peer_ref_list(outbound_targets)}"
    )

    peers = list((discovery.peers if discovery else []) or [])
    reachable: list[dict[str, str]] = []
    if peers:
        reachable = [
            {"namespace": peer.namespace, "name": peer.name}
            for peer in peers
            if peer.reachable
        ]
        blocked = [peer for peer in peers if not peer.reachable]
        if reachable:
            lines.append(f"- Currently reachable outbound peers: {format_a2a_peer_ref_list(reachable)}")
        if blocked:
            blocked_descriptions = []
            for peer in blocked[:6]:
                reason = (peer.reason or peer.status or "unavailable").strip()
                blocked_descriptions.append(f"{peer.namespace}/{peer.name} ({reason})")
            if len(blocked) > 6:
                blocked_descriptions.append(f"+{len(blocked) - 6} more")
            lines.append(f"- Outbound peers currently blocked or unavailable: {', '.join(blocked_descriptions)}")

    if not runtime_supports_direct_chat_delegation(runtime_kind):
        if runtime_kind == "opencode":
            example_peer = reachable[0] if reachable else (outbound_targets[0] if outbound_targets else None)
            example_peer_namespace = (example_peer or {}).get("namespace") or namespace
            example_peer_name = (example_peer or {}).get("name") or "peer-agent"
            lines.append(
                "- Runtime note: OpenCode supports explicit outbound A2A through the internal API gateway when the target agent is allowed by policy."
            )
            lines.append(
                f"- To actually query a peer from standard chat, use the bash tool to POST JSON-RPC 2.0 to $API_GATEWAY_INTERNAL_URL/a2a/<agent>?namespace=<namespace> with Authorization: Bearer $API_GATEWAY_SHARED_TOKEN and A2A-Version: {A2A_PROTOCOL_VERSION}."
            )
            lines.append(
                f"- Use method SendMessage. Put the task prompt in params.message.parts[]. For KubeSynth caller continuity, include params.metadata.kubesynthInvoke.threadId plus callerAgentName='{agent_name}' and callerAgentNamespace='{namespace}'."
            )
            lines.append(
                f"- URL rule: if a peer is shown as namespace/name, put only the agent name in the /a2a/<agent> path and keep the namespace in the ?namespace= query parameter. Example: peer {example_peer_namespace}/{example_peer_name} maps to $API_GATEWAY_INTERNAL_URL/a2a/{example_peer_name}?namespace={example_peer_namespace}."
            )
            lines.append(
                "- Delegation rule: do not mark a delegation step complete, summarize delegated work as done, or move past a delegated research/review task until the peer actually returns a concrete result or an explicit failure."
            )
            lines.append(
                "- If a peer call is slow, blocked, or fails, report that explicitly, keep that task incomplete in your todo plan, and either retry or revise the plan before continuing."
            )
        else:
            lines.append(
                f"- Runtime limitation: {runtime_label} agents do not support direct outbound A2A or specialist-team delegation from standard chat requests in this build."
            )

    lines.append(
        "- When asked about collaboration, distinguish inbound callers from outbound delegates and only claim peer results after you actually invoke the peer through the configured platform route."
    )
    return "\n".join(lines)


def discover_agent_peers(agent_name: str, namespace: str) -> AgentDiscoveryResponse:
    caller_agent = read_agent(agent_name, namespace)
    _caller_spec = caller_agent.get("spec")
    caller_spec: dict[str, Any] = _caller_spec if isinstance(_caller_spec, dict) else {}
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
        _target_spec = target_agent.get("spec")
        target_spec: dict[str, Any] = _target_spec if isinstance(_target_spec, dict) else {}
        target_allowed_callers = parse_a2a_agent_config(
            target_spec.get("a2a"),
            source=f"AIAgent[{target_namespace}/{target_name}].spec.a2a",
        ).get("allowedCallers", [])
        allowed_callers = {(item["namespace"], item["name"]) for item in target_allowed_callers}
        accepts_caller = caller_identity in allowed_callers
        reachable = accepts_caller and target_info.status == "running"

        reason: str | None = None
        if not accepts_caller:
            reason = f"Target agent does not list {namespace}/{agent_name} in spec.a2a.allowedCallers."
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


def resolve_invoke_agent_reference(agent_name: str, namespace: str | None, *, path_namespace: str | None = None) -> tuple[str, str]:
    resolved_agent_name = (agent_name or "").strip()
    if not K8S_NAME_RE.fullmatch(resolved_agent_name):
        raise HTTPException(status_code=400, detail="agent_name must be a valid Kubernetes resource name")

    resolved_namespace = (path_namespace or namespace or "default").strip() or "default"
    if namespace and namespace.strip() and path_namespace and namespace.strip() != resolved_namespace:
        raise HTTPException(
            status_code=400,
            detail="namespace query parameter must match the namespace segment in the agent invoke path",
        )
    if not K8S_NAME_RE.fullmatch(resolved_namespace):
        raise HTTPException(status_code=400, detail="namespace must be a valid Kubernetes namespace name")

    return resolved_agent_name, resolved_namespace


def workflow_info_from_resource(workflow: dict[str, Any]) -> WorkflowInfo:
    metadata = workflow.get("metadata", {})
    spec = workflow.get("spec", {})
    status = workflow.get("status", {})
    return WorkflowInfo(
        name=metadata.get("name", ""),
        namespace=metadata.get("namespace", "default"),
        description=spec.get("description", "") or "",
        input=spec.get("input", "") or "",
        context_ref=spec.get("contextRef"),
        message_bus=spec.get("messageBus", "in-memory") or "in-memory",
        steps=[
            WorkflowStepRequest(
                name=step.get("name", ""),
                agent_ref=step.get("agentRef", ""),
                prompt=step.get("prompt", "") or "",
                depends_on=step.get("dependsOn") or [],
                require_approval=bool(step.get("requireApproval", False)),
                execution=step.get("execution") or None,
                step_type=step.get("type", "agent") or "agent",
                loop_config=step.get("loopConfig") or None,
                condition_expr=step.get("conditionExpr") or None,
                then_steps=step.get("thenSteps") or None,
                else_steps=step.get("elseSteps") or None,
                verify=step.get("verify") or None,
                review_criteria=step.get("reviewCriteria") or None,
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


def _workflow_resource_from_trace(trace: dict[str, Any]) -> dict[str, Any]:
    spec = trace.get("spec") if isinstance(trace.get("spec"), dict) else {}
    status = trace.get("status") if isinstance(trace.get("status"), dict) else {}

    normalized_spec = dict(spec)
    if not normalized_spec.get("input") and trace.get("input_text"):
        normalized_spec["input"] = trace["input_text"]

    normalized_status = dict(status)
    if not normalized_status.get("phase") and trace.get("phase"):
        normalized_status["phase"] = trace["phase"]
    if not normalized_status.get("summary") and isinstance(trace.get("summary"), dict):
        normalized_status["summary"] = trace["summary"]
    if not normalized_status.get("stepStates") and isinstance(trace.get("step_states"), dict):
        normalized_status["stepStates"] = trace["step_states"]
    if not normalized_status.get("runId") and trace.get("run_id"):
        normalized_status["runId"] = trace["run_id"]
    if not normalized_status.get("workerJob") and trace.get("worker_job_name"):
        normalized_status["workerJob"] = {
            "name": trace["worker_job_name"],
            "namespace": trace.get("namespace") or "default",
        }
    if not normalized_status.get("journalRef") and trace.get("journal_path"):
        normalized_status["journalRef"] = {"path": trace["journal_path"]}
    if not normalized_status.get("pendingApproval") and trace.get("pending_approval_name"):
        normalized_status["pendingApproval"] = {"name": trace["pending_approval_name"]}

    metadata: dict[str, Any] = {
        "name": trace.get("workflow_name") or "",
        "namespace": trace.get("namespace") or "default",
    }
    if trace.get("created_at"):
        metadata["creationTimestamp"] = trace["created_at"]
    if trace.get("generation") is not None:
        metadata["generation"] = trace["generation"]

    return {
        "metadata": metadata,
        "spec": normalized_spec,
        "status": normalized_status,
    }


def _tail_log_text(log_text: str, tail_lines: int | None) -> str:
    if tail_lines is None or tail_lines <= 0 or not log_text:
        return log_text
    lines = log_text.splitlines()
    if len(lines) <= tail_lines:
        return log_text
    return "\n".join(lines[-tail_lines:])


def _read_workflow_job_logs(job_name: str, namespace: str, tail_lines: int | None = None) -> tuple[str, str]:
    pods = list_job_pods(job_name, namespace)
    if not pods:
        raise HTTPException(status_code=404, detail=f"No worker pod found for workflow job '{job_name}'")

    pod_name = str(getattr(pods[0].metadata, "name", "") or "")
    if not pod_name:
        raise HTTPException(status_code=404, detail=f"No worker pod found for workflow job '{job_name}'")

    try:
        from kubernetes import client

        kwargs: dict[str, Any] = {
            "name": pod_name,
            "namespace": namespace,
            "container": "worker",
            "timestamps": True,
        }
        if tail_lines is not None:
            kwargs["tail_lines"] = tail_lines
        logs = client.CoreV1Api().read_namespaced_pod_log(**kwargs)
        return str(logs or ""), pod_name
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("Could not retrieve workflow logs for job %s/%s: %s", namespace, job_name, exc)
        raise HTTPException(status_code=404, detail="Could not retrieve workflow logs") from exc


def _resolve_workflow_run_trace_payload(
    workflow_name: str,
    namespace: str,
    run_id: str,
    *,
    tail: int | None = None,
    persist_live_fallback: bool = False,
) -> dict[str, Any]:
    trace = load_workflow_run_trace(workflow_name, namespace, run_id, include_logs=True)
    if trace is None:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found for workflow '{workflow_name}'")

    archived_logs = trace.get("logs") if isinstance(trace.get("logs"), str) else ""
    logs = archived_logs
    source = "archived" if archived_logs else "unavailable"
    pod_name: str | None = None
    live_log_error: str | None = None

    if not logs and trace.get("worker_job_name"):
        try:
            logs, pod_name = _read_workflow_job_logs(str(trace["worker_job_name"]), namespace, tail)
            source = "live-worker"
            if logs and persist_live_fallback:
                with contextlib.suppress(Exception):
                    record_workflow_run_log_archive(
                        workflow_name=workflow_name,
                        namespace=namespace,
                        run_id=run_id,
                        log_text=logs,
                        source="gateway-live-fallback",
                    )
        except HTTPException as exc:
            live_log_error = str(exc.detail)
        except Exception as exc:
            live_log_error = str(exc)
    elif logs:
        logs = _tail_log_text(logs, tail)

    workflow_snapshot = workflow_info_from_resource(_workflow_resource_from_trace(trace)).model_dump(mode="json")
    return {
        "workflow_name": workflow_name,
        "namespace": namespace,
        "history_id": trace.get("history_id"),
        "run_id": run_id,
        "phase": trace.get("phase"),
        "source": source,
        "logs": logs or "",
        "pod_name": pod_name,
        "worker_job_name": trace.get("worker_job_name"),
        "workflow": workflow_snapshot,
        "summary": trace.get("summary"),
        "step_states": trace.get("step_states"),
        "triggered_by": trace.get("triggered_by"),
        "input_text": trace.get("input_text"),
        "artifact_path": trace.get("artifact_path"),
        "journal_path": trace.get("journal_path"),
        "created_at": trace.get("created_at"),
        "updated_at": trace.get("updated_at"),
        "completed_at": trace.get("completed_at"),
        "archived_log_available": bool(trace.get("archived_log_available")) or source == "live-worker",
        "archived_log_source": trace.get("archived_log_source"),
        "archived_log_truncated": bool(trace.get("archived_log_truncated")),
        "archived_log_captured_at": trace.get("archived_log_captured_at"),
        "live_log_error": live_log_error,
    }


def _workflow_logs_response_from_trace(trace_payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "workflow_name": trace_payload.get("workflow_name"),
        "run_id": trace_payload.get("run_id"),
        "job_name": trace_payload.get("worker_job_name"),
        "pod_name": trace_payload.get("pod_name"),
        "source": trace_payload.get("source"),
        "archived_log_available": trace_payload.get("archived_log_available"),
        "archived_log_source": trace_payload.get("archived_log_source"),
        "archived_log_truncated": trace_payload.get("archived_log_truncated"),
        "archived_log_captured_at": trace_payload.get("archived_log_captured_at"),
        "logs": trace_payload.get("logs") or "",
    }


def _fallback_workflow_logs_from_run(
    workflow_name: str,
    namespace: str,
    run_id: str | None,
    *,
    tail: int,
) -> dict[str, Any] | None:
    if not run_id:
        return None
    try:
        trace_payload = _resolve_workflow_run_trace_payload(
            workflow_name,
            namespace,
            run_id,
            tail=tail,
            persist_live_fallback=True,
        )
    except HTTPException:
        return None

    if not trace_payload.get("logs"):
        return None
    return _workflow_logs_response_from_trace(trace_payload)


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
        cases=status.get("cases"),
        created_at=metadata.get("creationTimestamp"),
    )


def get_agents(namespace: str = "default") -> list[dict[str, Any]]:
    try:
        from kubernetes import client

        api = client.CustomObjectsApi()
        result = api.list_namespaced_custom_object(
            group="kubesynth.ai",
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

        return cast(
            dict[str, Any],
            client.CustomObjectsApi().get_namespaced_custom_object(
                group="kubesynth.ai",
                version="v1alpha1",
                namespace=namespace,
                plural="aiagents",
                name=agent_name,
            ),
        )
    except Exception as exc:
        logger.warning("Agent read failed (%s): %s", agent_name, exc)
        raise HTTPException(status_code=404, detail=f"Agent '{agent_name}' not found") from exc


def _prune_agent_read_cache(now: float) -> None:
    expired_keys = [key for key, (expires_at, _) in _AGENT_READ_CACHE.items() if expires_at <= now]
    for key in expired_keys:
        _AGENT_READ_CACHE.pop(key, None)
    while len(_AGENT_READ_CACHE) > AGENT_READ_CACHE_MAX_ENTRIES:
        oldest_key = min(_AGENT_READ_CACHE.items(), key=lambda item: item[1][0])[0]
        _AGENT_READ_CACHE.pop(oldest_key, None)


def invalidate_agent_read_cache(agent_name: str | None = None, namespace: str | None = None) -> None:
    with _AGENT_READ_CACHE_LOCK:
        if agent_name is None and namespace is None:
            _AGENT_READ_CACHE.clear()
            return
        matching_keys = [
            key
            for key in _AGENT_READ_CACHE
            if (agent_name is None or key[1] == agent_name) and (namespace is None or key[0] == namespace)
        ]
        for key in matching_keys:
            _AGENT_READ_CACHE.pop(key, None)


def read_agent_cached(agent_name: str, namespace: str) -> dict[str, Any]:
    if AGENT_READ_CACHE_TTL_SECONDS <= 0:
        return read_agent(agent_name, namespace)

    cache_key = (namespace, agent_name)
    now = time.monotonic()
    with _AGENT_READ_CACHE_LOCK:
        cached_entry = _AGENT_READ_CACHE.get(cache_key)
        if cached_entry is not None:
            expires_at, cached_agent = cached_entry
            if expires_at > now:
                return copy.deepcopy(cached_agent)
            _AGENT_READ_CACHE.pop(cache_key, None)

    agent = read_agent(agent_name, namespace)
    with _AGENT_READ_CACHE_LOCK:
        cache_time = time.monotonic()
        _AGENT_READ_CACHE[cache_key] = (cache_time + AGENT_READ_CACHE_TTL_SECONDS, copy.deepcopy(agent))
        _prune_agent_read_cache(cache_time)
    return agent


def create_agent_resource(body: CreateAgentRequest, namespace: str) -> dict[str, Any]:
    spec = build_agent_spec(body, namespace=namespace)
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

        created = client.CustomObjectsApi().create_namespaced_custom_object(
            group=RESOURCE_GROUP,
            version=RESOURCE_VERSION,
            namespace=namespace,
            plural="aiagents",
            body=resource_body,
        )
        invalidate_agent_read_cache(agent_name=body.name, namespace=namespace)
        return created
    except Exception as exc:
        if getattr(exc, "status", None) == 409:
            raise HTTPException(status_code=409, detail=f"Agent '{body.name}' already exists") from exc
        logger.error("Failed to create agent %s: %s", body.name, exc)
        raise HTTPException(status_code=502, detail=f"Failed to create agent '{body.name}'") from exc


def read_approval(approval_name: str, namespace: str) -> dict[str, Any]:
    try:
        from kubernetes import client

        return cast(
            dict[str, Any],
            client.CustomObjectsApi().get_namespaced_custom_object(
                group="kubesynth.ai",
                version="v1alpha1",
                namespace=namespace,
                plural="agentapprovals",
                name=approval_name,
            ),
        )
    except Exception as exc:
        logger.warning("Approval read failed (%s): %s", approval_name, exc)
        raise HTTPException(status_code=404, detail=f"Approval '{approval_name}' not found") from exc


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


def list_job_pods(job_name: str, namespace: str) -> list[Any]:
    try:
        from kubernetes import client

        pods = client.CoreV1Api().list_namespaced_pod(
            namespace=namespace,
            label_selector=f"job-name={job_name}",
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


# Auth middleware (load_jwks … verify_token_or_query) extracted to auth_middleware.py — §4.1


def a2a_card_http_exception(error: A2AJSONRPCError) -> HTTPException:
    detail = error.message
    if error.data:
        detail = f"{detail}: {json.dumps(error.data, ensure_ascii=False, default=str)}"
    return HTTPException(status_code=400, detail=detail)


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------


@app.get("/api/auth/config")
def get_auth_config() -> dict[str, Any]:
    return auth_configuration_payload()


@app.post("/api/auth/register")
def register_local_user(body: AuthRegisterRequest, raw_request: Request):
    if not local_access_enabled():
        raise HTTPException(status_code=503, detail="Local authentication is not enabled")
    if not registration_allowed():
        raise HTTPException(status_code=403, detail="Self-registration is disabled")

    # Rate-limit registration using the same mechanism as login
    rate_limit_key = login_rate_limit_key(request_client_ip(raw_request), body.username.strip().lower())
    if login_rate_limited(rate_limit_key):
        raise HTTPException(status_code=429, detail="Too many registration attempts. Try again shortly.")

    # Validate email early before DB operations
    try:
        validated_email = validate_email(body.email)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # Atomic first-user check: count once and use that value
    user_count = count_users()
    is_first_user = user_count == 0
    role = "admin" if is_first_user else "operator"
    namespaces = ["*"] if is_first_user else ["default"]
    try:
        user = create_local_user(
            username=body.username,
            password=body.password,
            email=validated_email,
            display_name=body.display_name,
            role=role,
            allowed_namespaces=namespaces,
        )
    except ValueError as exc:
        note_login_attempt(rate_limit_key, success=False)
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    session_record, refresh_token = create_session_for_user(
        int(user["id"]),
        auth_provider=str(user.get("auth_provider") or "local"),
        ip_address=request_client_ip(raw_request),
        user_agent=raw_request.headers.get("user-agent"),
        ttl_seconds=REFRESH_TOKEN_TTL_SECONDS,
    )
    principal = principal_from_local_user(user, str(session_record["id"]))
    safe_record_audit(
        action="auth.register",
        principal=principal,
        detail={"role": role},
        ip_address=request_client_ip(raw_request),
    )
    note_login_attempt(rate_limit_key, success=True)
    return issue_session_response(user, session_record, refresh_token, status_code=201)


@app.post("/api/auth/login")
def login(body: AuthLoginRequest, raw_request: Request):
    provider = body.provider.strip().lower() or "local"
    username = body.username.strip().lower()
    rate_limit_key = login_rate_limit_key(request_client_ip(raw_request), username)
    if login_rate_limited(rate_limit_key):
        raise HTTPException(status_code=429, detail="Too many login attempts. Try again shortly.")

    user: dict[str, Any]
    if provider == "local":
        if not local_access_enabled():
            raise HTTPException(status_code=503, detail="Local authentication is not enabled")
        db_user = get_user_by_username(username)
        if db_user is None or not verify_password(body.password, cast(str, db_user.password_hash)):
            note_login_attempt(rate_limit_key, success=False)
            record_failed_login(username)
            raise HTTPException(status_code=401, detail="Invalid username or password")
        if not bool(db_user.is_active):
            raise HTTPException(status_code=403, detail="User account is inactive")
        if is_user_locked(db_user):
            raise HTTPException(status_code=423, detail="User account is temporarily locked")
        reset_failed_logins(cast(int, db_user.id))
        user = get_active_user_context(cast(int, db_user.id)) or serialize_user(db_user)
    elif provider == "ldap":
        if not ldap_enabled():
            raise HTTPException(status_code=503, detail="LDAP authentication is not enabled")
        try:
            ldap_identity = authenticate_ldap_user(username, body.password)
            user = upsert_external_user(
                username=str(ldap_identity["username"]),
                email=ldap_identity.get("email"),
                display_name=ldap_identity.get("display_name"),
                auth_provider=str(ldap_identity.get("auth_provider") or "ldap"),
                external_id=str(ldap_identity["external_id"]),
                role=str(ldap_identity.get("role") or "viewer"),
                allowed_namespaces=ldap_identity.get("allowed_namespaces"),
            )
        except ValueError as exc:
            note_login_attempt(rate_limit_key, success=False)
            raise HTTPException(status_code=401, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
    else:
        raise HTTPException(status_code=400, detail=f"Unsupported auth provider '{provider}'")

    note_login_attempt(rate_limit_key, success=True)
    session_record, refresh_token = create_session_for_user(
        int(user["id"]),
        auth_provider=str(user.get("auth_provider") or provider),
        ip_address=request_client_ip(raw_request),
        user_agent=raw_request.headers.get("user-agent"),
        ttl_seconds=REFRESH_TOKEN_TTL_SECONDS,
    )
    principal = principal_from_local_user(user, str(session_record["id"]))
    safe_record_audit(
        action="auth.login",
        principal=principal,
        detail={"provider": provider},
        ip_address=request_client_ip(raw_request),
    )
    return issue_session_response(user, session_record, refresh_token)


@app.post("/api/auth/refresh")
def refresh_session(
    raw_request: Request,
    refresh_token: str | None = Cookie(default=None, alias=REFRESH_COOKIE_NAME),
):
    if not refresh_token:
        raise HTTPException(status_code=401, detail="Refresh token cookie is missing")
    try:
        user, session_record, new_refresh_token = rotate_refresh_session(
            refresh_token,
            ip_address=request_client_ip(raw_request),
            user_agent=raw_request.headers.get("user-agent"),
            ttl_seconds=REFRESH_TOKEN_TTL_SECONDS,
        )
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc

    principal = principal_from_local_user(user, str(session_record["id"]))
    safe_record_audit(
        action="auth.refresh",
        principal=principal,
        ip_address=request_client_ip(raw_request),
    )
    return issue_session_response(user, session_record, new_refresh_token)


@app.post("/api/auth/logout")
async def logout(
    raw_request: Request,
    authorization: str | None = Header(default=None),
    refresh_token: str | None = Cookie(default=None, alias=REFRESH_COOKIE_NAME),
):
    principal: dict[str, Any] | None = None
    if authorization and authorization.startswith("Bearer "):
        with contextlib.suppress(HTTPException):
            principal = await authenticate_bearer_token(authorization[7:].strip())

    if refresh_token:
        revoke_refresh_token(refresh_token)

    response = JSONResponse({"status": "logged_out"})
    clear_refresh_cookie(response)
    clear_oidc_transaction_cookie(response)
    safe_record_audit(
        action="auth.logout",
        principal=principal,
        ip_address=request_client_ip(raw_request),
    )
    return response


@app.get("/api/auth/me")
def get_current_user(user=Depends(verify_token)) -> dict[str, Any]:
    return {"user": user, "auth_mode": AUTH_MODE}


@app.post("/api/auth/change-password")
def change_password_endpoint(
    body: ChangePasswordRequest,
    raw_request: Request,
    user=Depends(verify_token),
) -> dict[str, Any]:
    if str(user.get("auth_provider") or "") != "local":
        raise HTTPException(status_code=400, detail="Password changes are only supported for local users")
    try:
        updated_user = change_user_password(int(str(user.get("sub") or "0")), body.current_password, body.new_password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    principal = principal_from_local_user(updated_user, str(user.get("session_id") or ""))
    safe_record_audit(
        action="auth.change-password",
        principal=principal,
        ip_address=request_client_ip(raw_request),
    )
    return {"status": "updated", "user": principal}


@app.get("/api/admin/users")
def admin_list_users(user=Depends(verify_token)) -> list[dict[str, Any]]:
    ensure_role(user, "admin")
    return list_local_users()


@app.post("/api/admin/users", status_code=201)
def admin_create_user(
    body: CreateUserRequest,
    raw_request: Request,
    user=Depends(verify_token),
) -> dict[str, Any]:
    ensure_role(user, "admin")
    try:
        created = create_local_user(
            username=body.username,
            password=body.password,
            email=body.email,
            display_name=body.display_name,
            role=body.role,
            allowed_namespaces=body.allowed_namespaces or ["default"],
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    safe_record_audit(
        action="admin.create-user",
        principal=user,
        resource_kind="user",
        resource_name=str(created.get("username") or body.username),
        detail={"role": created.get("role")},
        ip_address=request_client_ip(raw_request),
    )
    return created


@app.patch("/api/admin/users/{user_id}")
def admin_update_user(
    user_id: int,
    body: UpdateUserRequest,
    raw_request: Request,
    user=Depends(verify_token),
) -> dict[str, Any]:
    ensure_role(user, "admin")

    # Prevent admin from demoting themselves
    acting_user_id = int(str(user.get("sub") or "0"))
    if acting_user_id == user_id and body.role is not None and body.role != "admin":
        raise HTTPException(status_code=400, detail="Cannot change your own admin role")
    if acting_user_id == user_id and body.is_active is False:
        raise HTTPException(status_code=400, detail="Cannot deactivate your own account")

    try:
        updated = update_user_fields(
            user_id,
            display_name=body.display_name,
            role=body.role,
            is_active=body.is_active,
            allowed_namespaces=body.allowed_namespaces,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    safe_record_audit(
        action="admin.update-user",
        principal=user,
        resource_kind="user",
        resource_name=str(updated.get("username") or user_id),
        detail={
            "role": updated.get("role"),
            "is_active": updated.get("is_active"),
            "allowed_namespaces": updated.get("allowed_namespaces"),
        },
        ip_address=request_client_ip(raw_request),
    )
    return updated


@app.get("/api/admin/audit")
def get_audit_logs(
    raw_request: Request,
    actor: str | None = None,
    actor_type: str | None = None,
    action: str | None = None,
    resource_kind: str | None = None,
    resource_name: str | None = None,
    namespace: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
    limit: int = 100,
    offset: int = 0,
    user=Depends(verify_token),
):
    ensure_role(user, "admin")
    from_dt = None
    to_dt = None
    if from_date:
        try:
            from_dt = datetime.fromisoformat(from_date)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid from_date format") from None
    if to_date:
        try:
            to_dt = datetime.fromisoformat(to_date)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid to_date format") from None
    return query_audit_logs(
        actor=actor,
        actor_type=actor_type,
        action=action,
        resource_kind=resource_kind,
        resource_name=resource_name,
        namespace=namespace,
        from_date=from_dt,
        to_date=to_dt,
        limit=limit,
        offset=offset,
    )


@app.delete("/api/admin/audit/purge")
def purge_audit_logs(
    raw_request: Request,
    user=Depends(verify_token),
):
    ensure_role(user, "admin")
    deleted = purge_old_audit_logs()
    record_audit_log(
        action="purged",
        actor_sub=user.get("sub"),
        actor_username=user.get("username"),
        actor_type="user",
        auth_provider=user.get("auth_provider"),
        resource_kind="audit",
        detail={"deleted_count": deleted},
        ip_address=request_client_ip(raw_request),
    )
    return {"deleted": deleted}


# ── Token Usage & Cost Endpoints ──


@app.get("/api/usage/summary")
def usage_summary(
    user=Depends(verify_token),
    namespace: str | None = None,
    group_by: str = "agent",
    from_date: str | None = None,
    to_date: str | None = None,
):
    from datetime import datetime as _dt

    parsed_from = _dt.fromisoformat(from_date) if from_date else None
    parsed_to = _dt.fromisoformat(to_date) if to_date else None
    rows = query_usage_summary(
        namespace=namespace,
        from_date=parsed_from,
        to_date=parsed_to,
        group_by=group_by,
    )
    return {"items": rows}


@app.get("/api/usage/detail")
def usage_detail(
    user=Depends(verify_token),
    namespace: str | None = None,
    agent_name: str | None = None,
    model: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
    limit: int = 100,
    offset: int = 0,
):
    from datetime import datetime as _dt

    parsed_from = _dt.fromisoformat(from_date) if from_date else None
    parsed_to = _dt.fromisoformat(to_date) if to_date else None
    return query_usage_detail(
        namespace=namespace,
        agent_name=agent_name,
        model=model,
        from_date=parsed_from,
        to_date=parsed_to,
        limit=limit,
        offset=offset,
    )


@app.get("/api/auth/oidc/start/{provider_id}")
def start_oidc_login(provider_id: str, raw_request: Request, next: str = "/"):
    if get_oidc_provider(provider_id=provider_id) is None:
        raise HTTPException(status_code=404, detail=f"OIDC provider '{provider_id}' is not configured")
    try:
        auth_request = build_oidc_authorization_request(provider_id, public_base_url(raw_request), next)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    response = RedirectResponse(url=auth_request["authorization_url"], status_code=status.HTTP_302_FOUND)
    set_oidc_transaction_cookie(response, auth_request["cookie_value"])
    return response


@app.get("/api/auth/oidc/callback/{provider_id}")
def finish_oidc_login(
    provider_id: str,
    raw_request: Request,
    code: str,
    state: str,
    oidc_transaction: str | None = Cookie(default=None, alias=OIDC_TRANSACTION_COOKIE_NAME),
):
    if not oidc_transaction:
        raise HTTPException(status_code=400, detail="OIDC login transaction cookie is missing")

    try:
        identity = exchange_oidc_code(
            provider_id,
            code,
            state,
            oidc_transaction,
            public_base_url(raw_request),
        )
        user = upsert_external_user(
            username=str(identity["username"]),
            email=identity.get("email"),
            display_name=identity.get("display_name"),
            auth_provider=str(identity.get("auth_provider") or f"oidc:{provider_id}"),
            external_id=str(identity["external_id"]),
            role=str(identity.get("role") or "viewer"),
            allowed_namespaces=identity.get("allowed_namespaces"),
        )
        session_record, refresh_token = create_session_for_user(
            int(user["id"]),
            auth_provider=str(user.get("auth_provider") or f"oidc:{provider_id}"),
            ip_address=request_client_ip(raw_request),
            user_agent=raw_request.headers.get("user-agent"),
            ttl_seconds=REFRESH_TOKEN_TTL_SECONDS,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    redirect_path = sanitize_redirect_path(str(identity.get("next") or "/"))
    separator = "&" if "?" in redirect_path else "?"
    response = RedirectResponse(
        url=f"{redirect_path}{separator}auth=success&provider={provider_id}",
        status_code=status.HTTP_302_FOUND,
    )
    set_refresh_cookie(response, refresh_token)
    clear_oidc_transaction_cookie(response)
    response.headers["Cache-Control"] = "no-store"
    principal = principal_from_local_user(user, str(session_record["id"]))
    safe_record_audit(
        action="auth.oidc-login",
        principal=principal,
        detail={"provider": provider_id},
        ip_address=request_client_ip(raw_request),
    )
    return response


@app.get("/api/auth/saml/start/{provider_id}")
def start_saml_login(provider_id: str, raw_request: Request, next: str = "/"):
    if get_saml_provider(provider_id=provider_id) is None:
        raise HTTPException(status_code=404, detail=f"SAML provider '{provider_id}' is not configured")
    try:
        auth_request = build_saml_authorization_request(provider_id, public_base_url(raw_request), next)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    response = RedirectResponse(url=auth_request["authorization_url"], status_code=status.HTTP_302_FOUND)
    set_oidc_transaction_cookie(response, auth_request["cookie_value"])
    return response


@app.api_route("/api/auth/saml/callback/{provider_id}", methods=["POST"])
async def finish_saml_login(
    provider_id: str,
    raw_request: Request,
    oidc_transaction: str | None = Cookie(default=None, alias=OIDC_TRANSACTION_COOKIE_NAME),
):
    if not oidc_transaction:
        raise HTTPException(status_code=400, detail="SAML login transaction cookie is missing")

    query_data = dict(raw_request.query_params.multi_items())
    form_data = await raw_request.form()
    post_data = {str(key): str(value) for key, value in form_data.multi_items()}

    saml_response = str(post_data.get("SAMLResponse") or "").strip()
    relay_state = str(post_data.get("RelayState") or "").strip() or None

    try:
        identity = exchange_saml_response(
            provider_id,
            saml_response=saml_response,
            relay_state=relay_state,
            cookie_value=oidc_transaction,
            base_url=public_base_url(raw_request),
            request_path=raw_request.url.path,
            query_data=query_data,
            post_data=post_data,
        )
        user = upsert_external_user(
            username=str(identity["username"]),
            email=identity.get("email"),
            display_name=identity.get("display_name"),
            auth_provider=str(identity.get("auth_provider") or f"saml:{provider_id}"),
            external_id=str(identity["external_id"]),
            role=str(identity.get("role") or "viewer"),
            allowed_namespaces=identity.get("allowed_namespaces"),
        )
        session_record, refresh_token = create_session_for_user(
            int(user["id"]),
            auth_provider=str(user.get("auth_provider") or f"saml:{provider_id}"),
            ip_address=request_client_ip(raw_request),
            user_agent=raw_request.headers.get("user-agent"),
            ttl_seconds=REFRESH_TOKEN_TTL_SECONDS,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    redirect_path = sanitize_redirect_path(str(identity.get("next") or "/"))
    separator = "&" if "?" in redirect_path else "?"
    response = RedirectResponse(
        url=f"{redirect_path}{separator}auth=success&provider={provider_id}",
        status_code=status.HTTP_302_FOUND,
    )
    set_refresh_cookie(response, refresh_token)
    clear_oidc_transaction_cookie(response)
    response.headers["Cache-Control"] = "no-store"
    principal = principal_from_local_user(user, str(session_record["id"]))
    safe_record_audit(
        action="auth.saml-login",
        principal=principal,
        detail={"provider": provider_id},
        ip_address=request_client_ip(raw_request),
    )
    return response


@app.get("/api/auth/saml/metadata/{provider_id}")
def get_saml_metadata(provider_id: str, raw_request: Request) -> Response:
    if get_saml_provider(provider_id=provider_id) is None:
        raise HTTPException(status_code=404, detail=f"SAML provider '{provider_id}' is not configured")
    try:
        metadata_xml = saml_metadata_xml(provider_id, public_base_url(raw_request))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return Response(content=metadata_xml, media_type="application/xml")


# ---------------------------------------------------------------------------
# Skills Catalog
# ---------------------------------------------------------------------------

SKILLS_CATALOG_PATH = os.getenv("SKILLS_CATALOG_PATH", "/data/skills-catalog.json")
_SKILLS_CATALOG_CACHE: list[dict[str, Any]] | None = None
_MCP_SIDECAR_CATALOG_CACHE: dict[str, dict[str, Any]] | None = None

MCP_TOOL_CATEGORY_KEY_MAP: dict[str, str] = {
    "code-exec": "codeExec",
    "web-search": "webSearch",
    "documents": "documents",
    "browser": "browser",
    "database": "database",
    "git": "git",
    "kubernetes": "kubernetes",
    "messaging": "messaging",
    "rag": "rag",
}


def _load_skills_catalog() -> list[dict[str, Any]]:
    global _SKILLS_CATALOG_CACHE
    if _SKILLS_CATALOG_CACHE is not None:
        return _SKILLS_CATALOG_CACHE

    env_json = os.getenv("SKILLS_CATALOG_JSON", "").strip()
    if env_json:
        try:
            data = json.loads(env_json)
            if isinstance(data, list):
                _SKILLS_CATALOG_CACHE = data
                logger.info("Loaded skills catalog from SKILLS_CATALOG_JSON env (%d skills)", len(data))
                return _SKILLS_CATALOG_CACHE
        except json.JSONDecodeError:
            logger.warning("SKILLS_CATALOG_JSON env is not valid JSON; falling back to file.")

    if os.path.isfile(SKILLS_CATALOG_PATH):
        with open(SKILLS_CATALOG_PATH, encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, list):
            _SKILLS_CATALOG_CACHE = data
            logger.info("Loaded skills catalog from %s (%d skills)", SKILLS_CATALOG_PATH, len(data))
            return _SKILLS_CATALOG_CACHE

    _SKILLS_CATALOG_CACHE = []
    logger.info("No skills catalog found; catalog endpoints will return empty results.")
    return _SKILLS_CATALOG_CACHE


def _load_mcp_sidecar_catalog() -> dict[str, dict[str, Any]]:
    global _MCP_SIDECAR_CATALOG_CACHE
    if _MCP_SIDECAR_CATALOG_CACHE is not None:
        return _MCP_SIDECAR_CATALOG_CACHE

    raw = os.getenv("MCP_SIDECAR_CATALOG_JSON", "").strip()
    if not raw:
        _MCP_SIDECAR_CATALOG_CACHE = {}
        return _MCP_SIDECAR_CATALOG_CACHE

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("MCP_SIDECAR_CATALOG_JSON env is not valid JSON; tool image metadata will be unavailable.")
        _MCP_SIDECAR_CATALOG_CACHE = {}
        return _MCP_SIDECAR_CATALOG_CACHE

    if not isinstance(data, dict):
        logger.warning("MCP_SIDECAR_CATALOG_JSON env is not a JSON object; tool image metadata will be unavailable.")
        _MCP_SIDECAR_CATALOG_CACHE = {}
        return _MCP_SIDECAR_CATALOG_CACHE

    normalized: dict[str, dict[str, Any]] = {}
    for key, value in data.items():
        if isinstance(key, str) and isinstance(value, dict):
            normalized[key] = value
    _MCP_SIDECAR_CATALOG_CACHE = normalized
    return _MCP_SIDECAR_CATALOG_CACHE


def _resolve_sidecar_catalog_entry(tool_id: str) -> dict[str, Any] | None:
    catalog = _load_mcp_sidecar_catalog()
    entry = catalog.get(tool_id)
    if not isinstance(entry, dict):
        mapped_key = MCP_TOOL_CATEGORY_KEY_MAP.get(tool_id, tool_id)
        entry = catalog.get(mapped_key)
    return entry if isinstance(entry, dict) else None


def _resolve_sidecar_image(tool_id: str) -> str | None:
    entry = _resolve_sidecar_catalog_entry(tool_id)
    if entry is None:
        return None
    image = entry.get("image")
    return image if isinstance(image, str) and image.strip() else None


def _resolve_sidecar_port(tool_id: str, fallback_port: int) -> int:
    entry = _resolve_sidecar_catalog_entry(tool_id)
    if entry is None:
        return fallback_port

    port = entry.get("port")
    if isinstance(port, bool):
        return fallback_port
    if isinstance(port, int) and 1 <= port <= 65535:
        return port
    if isinstance(port, str):
        port_text = port.strip()
        if port_text.isdigit():
            normalized_port = int(port_text)
            if 1 <= normalized_port <= 65535:
                return normalized_port
    return fallback_port


MCP_TOOL_CATEGORIES: list[dict[str, Any]] = [
    {
        "id": "code-exec",
        "name": "Code Execution",
        "description": "Run Python, Bash, and Node.js code in a sandboxed environment.",
        "icon": "terminal",
        "default_port": 8090,
        "config_schema": [],
        "credential_type": None,
    },
    {
        "id": "web-search",
        "name": "Web Search",
        "description": "Search the web, fetch URLs, and extract text content.",
        "icon": "globe",
        "default_port": 8091,
        "config_schema": [],
        "credential_type": None,
    },
    {
        "id": "documents",
        "name": "PDF & Office",
        "description": "Read, create, and manipulate PDF, DOCX, XLSX, and PPTX files.",
        "icon": "file-text",
        "default_port": 8092,
        "config_schema": [],
        "credential_type": None,
    },
    {
        "id": "browser",
        "name": "Browser Automation",
        "description": "Browse pages, take screenshots, click elements, and fill forms.",
        "icon": "monitor",
        "default_port": 8093,
        "config_schema": [],
        "credential_type": None,
    },
    {
        "id": "database",
        "name": "Database",
        "description": "Query SQL databases, list tables, and describe schemas.",
        "icon": "database",
        "default_port": 8094,
        "config_schema": [],
        "credential_type": None,
    },
    {
        "id": "git",
        "name": "Git & GitHub",
        "description": "Clone repos, view diffs, create commits, and interact with GitHub API.",
        "icon": "git-branch",
        "default_port": 8095,
        "credential_type": "git",
        "config_schema": [
            {
                "key": "repo_url",
                "label": "Repository URL",
                "type": "text",
                "placeholder": "https://github.com/org/repo.git",
                "required": True,
                "group": "repository",
                "help": "HTTPS or SSH URL of the Git repository to clone into the sandbox",
            },
            {
                "key": "default_branch",
                "label": "Default Branch",
                "type": "text",
                "placeholder": "main",
                "group": "repository",
            },
            {
                "key": "push_policy",
                "label": "Push Policy",
                "type": "select",
                "options": [
                    {"value": "after-each-commit", "label": "After Each Commit"},
                    {"value": "end-of-session", "label": "End of Session"},
                    {"value": "on-approval", "label": "On Approval"},
                    {"value": "never", "label": "Never"},
                ],
                "default": "end-of-session",
                "group": "repository",
            },
            {
                "key": "auth_method",
                "label": "Authentication Method",
                "type": "select",
                "options": [
                    {"value": "token", "label": "Personal Access Token"},
                    {"value": "basic", "label": "Username & Password"},
                    {"value": "ssh", "label": "SSH Key"},
                ],
                "default": "token",
                "group": "credentials",
            },
            {
                "key": "token",
                "label": "Access Token",
                "type": "password",
                "placeholder": "ghp_...",
                "group": "credentials",
                "is_credential": True,
                "visible_when": {"field": "auth_method", "values": ["token"]},
            },
            {
                "key": "username",
                "label": "Username",
                "type": "text",
                "group": "credentials",
                "is_credential": True,
                "visible_when": {"field": "auth_method", "values": ["basic"]},
            },
            {
                "key": "password",
                "label": "Password",
                "type": "password",
                "group": "credentials",
                "is_credential": True,
                "visible_when": {"field": "auth_method", "values": ["basic"]},
            },
            {
                "key": "ssh_private_key",
                "label": "SSH Private Key",
                "type": "textarea",
                "placeholder": "-----BEGIN OPENSSH PRIVATE KEY-----",
                "group": "credentials",
                "is_credential": True,
                "visible_when": {"field": "auth_method", "values": ["ssh"]},
            },
        ],
    },
    {
        "id": "kubernetes",
        "name": "Kubernetes & Cloud",
        "description": "List pods, get logs, apply manifests, and manage cluster resources.",
        "icon": "server",
        "default_port": 8096,
        "config_schema": [],
        "credential_type": None,
    },
    {
        "id": "messaging",
        "name": "Email & Messaging",
        "description": "Send emails and Slack messages, list conversations.",
        "icon": "mail",
        "default_port": 8097,
        "config_schema": [],
        "credential_type": None,
    },
    {
        "id": "rag",
        "name": "RAG & Vector Search",
        "description": "Index documents, perform semantic search, and retrieve context.",
        "icon": "search",
        "default_port": 8098,
        "config_schema": [],
        "credential_type": None,
    },
]

MCP_HUB_SERVERS: list[dict[str, Any]] = [
    {
        "id": "github",
        "name": "GitHub",
        "description": "Shared GitHub API access via the platform MCP hub.",
        "icon": "git-branch",
        "credential_type": "github",
        "config_schema": [
            {
                "key": "token",
                "label": "GitHub Personal Access Token",
                "type": "password",
                "placeholder": "ghp_...",
                "required": True,
                "group": "credentials",
                "is_credential": True,
                "help": "A GitHub PAT with appropriate scopes for the repositories you want to access.",
            },
        ],
    },
]

# ── MCP Registry ── comprehensive catalog of all known MCP servers ──

MCP_REGISTRY: list[dict[str, Any]] = [
    # ── Remote-native servers (vendor-hosted, zero containers) ──
    {
        "id": "github-remote",
        "name": "GitHub MCP",
        "description": "Access GitHub repos, issues, PRs, code search, and actions via GitHub's hosted MCP endpoint.",
        "icon": "git-branch",
        "category": "developer",
        "transport": "remote",
        "endpoint": "https://api.githubcopilot.com/mcp/",
        "auth_type": "bearer",
        "enabled": True,
        "tags": ["git", "code", "issues", "pull-requests"],
        "tools_count": 35,
        "docs_url": "https://github.com/github/github-mcp-server/blob/main/docs/remote-server.md",
        "repository_url": "https://github.com/github/github-mcp-server",
        "protocol_label": "Streamable HTTP",
        "deployment_model": "GitHub-hosted remote",
        "connection_notes": "The hosted GitHub endpoint works with PAT auth today. GitHub Enterprise Cloud with data residency uses a different copilot-api.<subdomain>.ghe.com endpoint.",
        "config_schema": [
            {"key": "token", "label": "GitHub PAT", "type": "password", "placeholder": "ghp_...", "required": True, "group": "credentials", "is_credential": True},
        ],
    },
    {
        "id": "context7",
        "name": "Context7",
        "description": "Up-to-date documentation and code examples for any library, pulled from source. Prevents hallucinated APIs.",
        "icon": "book-open",
        "category": "developer",
        "transport": "remote",
        "endpoint": "https://mcp.context7.com/mcp",
        "auth_type": "api_key",
        "enabled": True,
        "tags": ["documentation", "libraries", "code-examples"],
        "tools_count": 2,
        "docs_url": "https://context7.com/docs/resources/all-clients",
        "repository_url": "https://github.com/upstash/context7",
        "protocol_label": "Streamable HTTP",
        "deployment_model": "Vendor-hosted remote",
        "connection_notes": "Context7 works without auth, but the vendor recommends an API key for higher rate limits in supported clients.",
        "auth_header_name": "CONTEXT7_API_KEY",
        "config_schema": [
            {"key": "api_key", "label": "Context7 API Key", "type": "password", "required": False, "group": "credentials", "is_credential": True},
        ],
    },
    {
        "id": "microsoft-learn",
        "name": "Microsoft Learn",
        "description": "Trusted Microsoft documentation and code samples from the official Learn MCP endpoint.",
        "icon": "book-open",
        "category": "developer",
        "transport": "remote",
        "endpoint": "https://learn.microsoft.com/api/mcp",
        "auth_type": "none",
        "enabled": True,
        "tags": ["documentation", "microsoft", "azure", "code-samples"],
        "tools_count": 3,
        "tool_names": ["microsoft_docs_search", "microsoft_docs_fetch", "microsoft_code_sample_search"],
        "docs_url": "https://learn.microsoft.com/en-us/training/support/mcp",
        "repository_url": "https://github.com/MicrosoftDocs/mcp",
        "protocol_label": "Streamable HTTP",
        "deployment_model": "Vendor-hosted remote",
        "connection_notes": "The Learn endpoint is public. A plain browser-style GET may return 405 even though the MCP server is healthy; connect with a real MCP client over Streamable HTTP.",
        "config_schema": [],
    },
    {
        "id": "brave-search",
        "name": "Brave Search",
        "description": "Web and local search using Brave's Search API with privacy-focused results.",
        "icon": "globe",
        "category": "search",
        "transport": "remote",
        "endpoint": None,
        "auth_type": "api_key",
        "enabled": True,
        "tags": ["web-search", "local-search", "news"],
        "tools_count": 2,
        "config_schema": [
            {"key": "api_key", "label": "Brave API Key", "type": "password", "required": True, "group": "credentials", "is_credential": True},
        ],
    },
    {
        "id": "firecrawl",
        "name": "Firecrawl",
        "description": "Web scraping, crawling, and content extraction. Convert any website to clean markdown or structured data.",
        "icon": "globe",
        "category": "search",
        "transport": "remote",
        "endpoint": None,
        "auth_type": "api_key",
        "enabled": True,
        "tags": ["web-scraping", "crawling", "extraction"],
        "tools_count": 14,
        "tool_names": [
            "firecrawl_scrape",
            "firecrawl_batch_scrape",
            "firecrawl_check_batch_status",
            "firecrawl_map",
            "firecrawl_search",
            "firecrawl_crawl",
            "firecrawl_check_crawl_status",
            "firecrawl_extract",
            "firecrawl_agent",
            "firecrawl_agent_status",
            "firecrawl_browser_create",
            "firecrawl_browser_execute",
            "firecrawl_browser_list",
            "firecrawl_browser_delete",
        ],
        "docs_url": "https://github.com/firecrawl/firecrawl-mcp-server",
        "repository_url": "https://github.com/firecrawl/firecrawl-mcp-server",
        "protocol_label": "stdio or self-hosted Streamable HTTP",
        "deployment_model": "Self-hosted or local bridge",
        "suggested_endpoint": "http://localhost:3000/mcp",
        "connection_notes": "The official package runs over stdio by default and can expose a local Streamable HTTP endpoint at http://localhost:3000/mcp. No vendor-hosted default MCP endpoint is published in the docs.",
        "config_schema": [
            {"key": "api_key", "label": "Firecrawl API Key", "type": "password", "required": True, "group": "credentials", "is_credential": True},
        ],
    },
    {
        "id": "sentry",
        "name": "Sentry (Self-hosted / local)",
        "description": "Run Sentry's MCP server locally or against self-hosted Sentry with token-based auth.",
        "icon": "alert-triangle",
        "category": "observability",
        "transport": "remote",
        "endpoint": None,
        "auth_type": "bearer",
        "enabled": True,
        "tags": ["errors", "monitoring", "debugging", "stack-traces"],
        "tools_count": 8,
        "docs_url": "https://docs.sentry.io/product/sentry-mcp/",
        "repository_url": "https://github.com/getsentry/sentry-mcp",
        "protocol_label": "Local stdio or self-hosted HTTP",
        "deployment_model": "Self-hosted or local bridge",
        "connection_notes": "Use this entry when you run the open-source MCP server yourself for self-hosted Sentry or local stdio workflows. The official sentry.io hosted endpoint is listed separately.",
        "config_schema": [
            {"key": "token", "label": "Sentry Auth Token", "type": "password", "required": True, "group": "credentials", "is_credential": True},
            {"key": "organization", "label": "Organization Slug", "type": "text", "required": True, "group": "connection"},
        ],
    },
    {
        "id": "sentry-remote",
        "name": "Sentry Cloud",
        "description": "Official Sentry-hosted MCP endpoint for sentry.io with OAuth login and optional org/project scoping.",
        "icon": "alert-triangle",
        "category": "observability",
        "transport": "remote",
        "endpoint": "https://mcp.sentry.dev/mcp",
        "auth_type": "oauth",
        "enabled": True,
        "tags": ["errors", "monitoring", "debugging", "stack-traces", "oauth"],
        "tools_count": 8,
        "docs_url": "https://docs.sentry.io/product/sentry-mcp/",
        "repository_url": "https://github.com/getsentry/sentry-mcp",
        "protocol_label": "Streamable HTTP",
        "deployment_model": "Vendor-hosted remote",
        "connection_notes": "The hosted sentry.io endpoint uses OAuth and supports scoped URLs like /mcp/<org>/<project>. Self-hosted Sentry still requires the local stdio server.",
        "config_schema": [],
    },
    {
        "id": "linear",
        "name": "Linear",
        "description": "Manage issues, projects, and cycles in Linear. Create, update, search, and comment on issues.",
        "icon": "layout-list",
        "category": "project-management",
        "transport": "remote",
        "endpoint": None,
        "auth_type": "api_key",
        "enabled": True,
        "tags": ["issues", "project-management", "agile", "tracking"],
        "tools_count": 12,
        "config_schema": [
            {"key": "api_key", "label": "Linear API Key", "type": "password", "required": True, "group": "credentials", "is_credential": True},
        ],
    },
    {
        "id": "atlassian-rovo",
        "name": "Atlassian Rovo",
        "description": "Official Atlassian-hosted MCP endpoint for Jira, Confluence, Bitbucket, and Compass workflows.",
        "icon": "layout-list",
        "category": "project-management",
        "transport": "remote",
        "endpoint": "https://mcp.atlassian.com/v1/mcp",
        "auth_type": "bearer",
        "enabled": True,
        "tags": ["jira", "confluence", "bitbucket", "compass", "project-management"],
        "tools_count": 20,
        "protocol_label": "Streamable HTTP",
        "deployment_model": "Vendor-hosted remote",
        "connection_notes": "Atlassian's hosted MCP endpoint supports Jira, Confluence, Bitbucket, and Compass. OAuth is the default interactive path, while service-account style bearer tokens are suitable for headless saved connections.",
        "config_schema": [
            {"key": "token", "label": "Atlassian Access Token", "type": "password", "required": True, "group": "credentials", "is_credential": True},
        ],
    },
    {
        "id": "slack",
        "name": "Slack",
        "description": "Read and send messages, manage channels, search history, and interact with Slack workspaces.",
        "icon": "message-square",
        "category": "communication",
        "transport": "remote",
        "endpoint": None,
        "auth_type": "bearer",
        "enabled": True,
        "tags": ["messaging", "channels", "team-communication"],
        "tools_count": 10,
        "config_schema": [
            {"key": "token", "label": "Slack Bot Token", "type": "password", "placeholder": "xoxb-...", "required": True, "group": "credentials", "is_credential": True},
        ],
    },
    {
        "id": "notion",
        "name": "Notion (Self-hosted)",
        "description": "Open-source Notion API MCP server for self-hosted stdio or Streamable HTTP deployments.",
        "icon": "file-text",
        "category": "productivity",
        "transport": "remote",
        "endpoint": None,
        "auth_type": "bearer",
        "enabled": True,
        "tags": ["wiki", "documents", "databases", "knowledge-base"],
        "tools_count": 22,
        "docs_url": "https://github.com/makenotion/notion-mcp-server",
        "repository_url": "https://github.com/makenotion/notion-mcp-server",
        "protocol_label": "stdio or self-hosted Streamable HTTP",
        "deployment_model": "Self-hosted or local bridge",
        "connection_notes": "This entry is for the open-source Notion server that you run yourself. The official hosted Notion MCP endpoint is listed separately below.",
        "config_schema": [
            {"key": "token", "label": "Notion Integration Token", "type": "password", "placeholder": "ntn_...", "required": True, "group": "credentials", "is_credential": True},
        ],
    },
    {
        "id": "notion-remote",
        "name": "Notion Cloud",
        "description": "Official Notion-hosted MCP endpoint for workspace search, content fetch, comments, views, and page operations.",
        "icon": "file-text",
        "category": "productivity",
        "transport": "remote",
        "endpoint": "https://mcp.notion.com/mcp",
        "auth_type": "oauth",
        "enabled": True,
        "tags": ["wiki", "documents", "databases", "knowledge-base", "oauth"],
        "tools_count": 18,
        "tool_names": [
            "search",
            "fetch",
            "create-page",
            "update-page",
            "move-page",
            "duplicate-page",
            "create-database",
            "update-data-source",
            "create-view",
            "update-view",
            "query-data-sources",
            "query-database-view",
            "add-comment",
            "get-comments",
            "get-teams",
            "list-users",
            "get-current-user",
            "get-bot-info",
        ],
        "docs_url": "https://developers.notion.com/guides/mcp/get-started-with-mcp",
        "repository_url": "https://github.com/makenotion/notion-mcp-server",
        "protocol_label": "Streamable HTTP or SSE",
        "deployment_model": "Vendor-hosted remote",
        "connection_notes": "Official hosted Notion MCP uses OAuth and also exposes a legacy SSE endpoint for older clients. Save the connection once, supply your Notion OAuth app credentials, and complete the browser sign-in from the MCP page.",
        "oauth_authorization_url": "https://api.notion.com/v1/oauth/authorize",
        "oauth_token_url": "https://api.notion.com/v1/oauth/token",
        "oauth_token_auth_method": "client_secret_basic",
        "oauth_extra_authorize_params": {"owner": "user"},
        "config_schema": [
            {"key": "client_id", "label": "OAuth Client ID", "type": "text", "required": True, "group": "connection"},
            {"key": "client_secret", "label": "OAuth Client Secret", "type": "password", "required": True, "group": "credentials", "is_credential": True},
        ],
    },
    # ── Shared Hub servers (deployed centrally in mcp-hub namespace) ──
    {
        "id": "github-hub",
        "name": "GitHub (Hub)",
        "description": "Shared GitHub API access deployed in the platform MCP hub namespace. Central management for all agents.",
        "icon": "git-branch",
        "category": "developer",
        "transport": "hub",
        "hub_server_name": "github",
        "auth_type": "bearer",
        "enabled": True,
        "tags": ["git", "code", "issues", "pull-requests"],
        "tools_count": 35,
        "config_schema": [
            {"key": "token", "label": "GitHub PAT", "type": "password", "placeholder": "ghp_...", "required": True, "group": "credentials", "is_credential": True},
        ],
    },
    {
        "id": "postgres-hub",
        "name": "PostgreSQL (Hub)",
        "description": "Shared read-only PostgreSQL access deployed in the MCP hub. Query tables, list schemas, describe databases.",
        "icon": "database",
        "category": "data",
        "transport": "hub",
        "hub_server_name": "postgres-readonly",
        "auth_type": "connection_string",
        "enabled": True,
        "tags": ["sql", "database", "postgres", "read-only"],
        "tools_count": 5,
        "config_schema": [
            {"key": "connection_string", "label": "PostgreSQL Connection String", "type": "password", "placeholder": "postgresql://user:pass@host:5432/db", "required": True, "group": "connection", "is_credential": True},
        ],
    },
    # ── Sidecar servers (run as containers in the agent pod) ──
    {
        "id": "playwright-sidecar",
        "name": "Playwright Browser",
        "description": "Full browser automation with Playwright. Navigate pages, take screenshots, click elements, fill forms, and extract content.",
        "icon": "monitor",
        "category": "browser",
        "transport": "sidecar",
        "auth_type": "none",
        "enabled": True,
        "tags": ["browser", "automation", "screenshots", "testing"],
        "tools_count": 18,
        "config_schema": [],
    },
    {
        "id": "filesystem-sidecar",
        "name": "Filesystem",
        "description": "Safe file system operations within a sandboxed workspace. Read, write, search, and manage files.",
        "icon": "folder",
        "category": "developer",
        "transport": "sidecar",
        "auth_type": "none",
        "enabled": True,
        "tags": ["files", "filesystem", "workspace"],
        "tools_count": 11,
        "config_schema": [],
    },
    {
        "id": "memory-sidecar",
        "name": "Memory & Knowledge Graph",
        "description": "Persistent memory with a knowledge graph backend. Store entities, relations, and retrieve context across sessions.",
        "icon": "brain",
        "category": "ai",
        "transport": "sidecar",
        "auth_type": "none",
        "enabled": True,
        "tags": ["memory", "knowledge-graph", "persistence", "context"],
        "tools_count": 7,
        "config_schema": [],
    },
    {
        "id": "puppeteer-sidecar",
        "name": "Puppeteer",
        "description": "Headless Chrome automation for web scraping, screenshot capture, and page interaction.",
        "icon": "monitor",
        "category": "browser",
        "transport": "sidecar",
        "auth_type": "none",
        "enabled": True,
        "tags": ["browser", "headless", "chrome", "scraping"],
        "tools_count": 9,
        "config_schema": [],
    },
    # ── Cloud & Infrastructure ──
    {
        "id": "azure-mcp",
        "name": "Azure MCP Server",
        "description": "276 tools across 57 Azure services including Compute, Storage, AI, DevOps, Networking, and more.",
        "icon": "cloud",
        "category": "cloud",
        "transport": "remote",
        "endpoint": None,
        "auth_type": "oauth",
        "enabled": True,
        "tags": ["azure", "cloud", "infrastructure", "devops"],
        "tools_count": 276,
        "docs_url": "https://learn.microsoft.com/azure/developer/azure-mcp-server/",
        "repository_url": "https://github.com/microsoft/mcp",
        "protocol_label": "stdio or self-hosted Streamable HTTP",
        "deployment_model": "Self-hosted remote preview",
        "connection_notes": "Azure publishes packages, IDE integrations, and a self-hosted remote preview for platforms like Foundry and Copilot Studio, but no shared vendor-hosted MCP endpoint is documented.",
        "config_schema": [
            {"key": "tenant_id", "label": "Azure Tenant ID", "type": "text", "required": True, "group": "connection"},
            {"key": "client_id", "label": "Client ID", "type": "text", "required": True, "group": "credentials"},
            {"key": "client_secret", "label": "Client Secret", "type": "password", "required": True, "group": "credentials", "is_credential": True},
        ],
    },
    {
        "id": "aws-kb-retrieval",
        "name": "AWS Knowledge Base",
        "description": "Retrieve information from AWS Knowledge Bases using Amazon Bedrock Agent Runtime.",
        "icon": "cloud",
        "category": "cloud",
        "transport": "remote",
        "endpoint": None,
        "auth_type": "api_key",
        "enabled": True,
        "tags": ["aws", "knowledge-base", "bedrock", "rag"],
        "tools_count": 1,
        "config_schema": [
            {"key": "access_key", "label": "AWS Access Key", "type": "text", "required": True, "group": "credentials"},
            {"key": "secret_key", "label": "AWS Secret Key", "type": "password", "required": True, "group": "credentials", "is_credential": True},
            {"key": "region", "label": "AWS Region", "type": "text", "placeholder": "us-east-1", "required": True, "group": "connection"},
        ],
    },
    # ── Data & Analytics ──
    {
        "id": "qdrant",
        "name": "Qdrant Vector Search",
        "description": "Semantic vector search operations. Create collections, upsert points, and query with filters.",
        "icon": "search",
        "category": "data",
        "transport": "sidecar",
        "auth_type": "api_key",
        "enabled": True,
        "tags": ["vector-search", "embeddings", "semantic", "rag"],
        "tools_count": 6,
        "config_schema": [
            {"key": "url", "label": "Qdrant URL", "type": "text", "placeholder": "http://qdrant:6333", "required": True, "group": "connection"},
            {"key": "api_key", "label": "Qdrant API Key", "type": "password", "group": "credentials", "is_credential": True},
        ],
    },
    {
        "id": "sqlite",
        "name": "SQLite",
        "description": "Interact with SQLite databases. Run queries, describe schemas, and manage tables.",
        "icon": "database",
        "category": "data",
        "transport": "sidecar",
        "auth_type": "none",
        "enabled": True,
        "tags": ["sql", "database", "sqlite", "local"],
        "tools_count": 6,
        "config_schema": [
            {"key": "db_path", "label": "Database Path", "type": "text", "placeholder": "/data/mydb.sqlite", "required": True, "group": "connection"},
        ],
    },
    # ── DevOps & CI/CD ──
    {
        "id": "docker",
        "name": "Docker",
        "description": "Manage Docker containers, images, volumes and networks. Build, run, and inspect containers.",
        "icon": "box",
        "category": "devops",
        "transport": "sidecar",
        "auth_type": "none",
        "enabled": True,
        "tags": ["docker", "containers", "images", "devops"],
        "tools_count": 15,
        "config_schema": [],
    },
    {
        "id": "kubernetes-mcp",
        "name": "Kubernetes",
        "description": "Full Kubernetes cluster operations. Get pods, logs, apply manifests, scale deployments, and manage resources.",
        "icon": "server",
        "category": "devops",
        "transport": "sidecar",
        "auth_type": "kubeconfig",
        "enabled": True,
        "tags": ["kubernetes", "k8s", "cluster", "pods", "deployments"],
        "tools_count": 20,
        "config_schema": [],
    },
    # ── Communication ──
    {
        "id": "gmail",
        "name": "Gmail",
        "description": "Read, send, search, and manage emails via Gmail API with OAuth2 authentication.",
        "icon": "mail",
        "category": "communication",
        "transport": "remote",
        "endpoint": None,
        "auth_type": "oauth",
        "enabled": True,
        "tags": ["email", "gmail", "google"],
        "tools_count": 8,
        "docs_url": "https://developers.google.com/gmail/api/guides",
        "connection_notes": "Use this entry with your own Gmail MCP deployment endpoint. Save the endpoint URL, register a Google OAuth app with this gateway as the redirect target, and complete the browser sign-in from the MCP page.",
        "oauth_authorization_url": "https://accounts.google.com/o/oauth2/v2/auth",
        "oauth_token_url": "https://oauth2.googleapis.com/token",
        "oauth_scopes": [
            "openid",
            "email",
            "profile",
            "https://www.googleapis.com/auth/gmail.modify",
            "https://www.googleapis.com/auth/gmail.send",
        ],
        "oauth_extra_authorize_params": {
            "access_type": "offline",
            "include_granted_scopes": "true",
            "prompt": "consent"
        },
        "config_schema": [
            {"key": "client_id", "label": "OAuth Client ID", "type": "text", "required": True, "group": "credentials"},
            {"key": "client_secret", "label": "OAuth Client Secret", "type": "password", "required": True, "group": "credentials", "is_credential": True},
        ],
    },
    {
        "id": "discord",
        "name": "Discord",
        "description": "Interact with Discord servers. Read messages, send messages, manage channels, and respond to events.",
        "icon": "message-square",
        "category": "communication",
        "transport": "remote",
        "endpoint": None,
        "auth_type": "bearer",
        "enabled": True,
        "tags": ["messaging", "discord", "community"],
        "tools_count": 7,
        "config_schema": [
            {"key": "token", "label": "Discord Bot Token", "type": "password", "required": True, "group": "credentials", "is_credential": True},
        ],
    },
    # ── Design & Content ──
    {
        "id": "figma",
        "name": "Figma",
        "description": "Official Figma-hosted MCP server for design context, screenshots, Code Connect, and write-to-canvas workflows.",
        "icon": "palette",
        "category": "design",
        "transport": "remote",
        "endpoint": "https://mcp.figma.com/mcp",
        "auth_type": "oauth",
        "enabled": True,
        "tags": ["design", "figma", "ui", "components", "design-systems"],
        "tools_count": 16,
        "tool_names": [
            "get_design_context",
            "generate_figma_design",
            "get_variable_defs",
            "get_code_connect_map",
            "add_code_connect_map",
            "get_code_connect_suggestions",
            "send_code_connect_mappings",
            "get_screenshot",
            "create_design_system_rules",
            "get_metadata",
            "get_figjam",
            "generate_diagram",
            "whoami",
            "use_figma",
            "search_design_system",
            "create_new_file",
        ],
        "docs_url": "https://developers.figma.com/docs/figma-mcp-server/remote-server-installation/",
        "repository_url": "https://github.com/figma/mcp-server-guide",
        "protocol_label": "Streamable HTTP",
        "deployment_model": "Vendor-hosted remote",
        "connection_notes": "Figma only allows approved MCP clients to connect to the hosted endpoint. Interactive OAuth is required, and some write-to-canvas tools are available only in supported clients.",
        "config_schema": [],
    },
    # ── AI & ML ──
    {
        "id": "exa",
        "name": "Exa Search",
        "description": "AI-powered web search that understands meaning. Find similar content, get clean page extracts.",
        "icon": "sparkles",
        "category": "ai",
        "transport": "remote",
        "endpoint": None,
        "auth_type": "api_key",
        "enabled": True,
        "tags": ["search", "ai-search", "semantic", "content"],
        "tools_count": 3,
        "config_schema": [
            {"key": "api_key", "label": "Exa API Key", "type": "password", "required": True, "group": "credentials", "is_credential": True},
        ],
    },
    {
        "id": "tavily",
        "name": "Tavily Search",
        "description": "AI-optimized Tavily remote MCP endpoint for search, extract, map, and crawl workflows.",
        "icon": "globe",
        "category": "search",
        "transport": "remote",
        "endpoint": "https://mcp.tavily.com/mcp",
        "auth_type": "api_key",
        "enabled": True,
        "tags": ["search", "ai-search", "research"],
        "tools_count": 4,
        "tool_names": ["tavily-search", "tavily-extract", "tavily-map", "tavily-crawl"],
        "docs_url": "https://github.com/tavily-ai/tavily-mcp",
        "repository_url": "https://github.com/tavily-ai/tavily-mcp",
        "protocol_label": "Streamable HTTP",
        "deployment_model": "Vendor-hosted remote",
        "connection_notes": "Tavily supports either OAuth or API-key auth. KubeSynth uses Bearer-token API-key auth for headless saved connections.",
        "auth_header_name": "Authorization",
        "auth_header_prefix": "Bearer ",
        "config_schema": [
            {"key": "api_key", "label": "Tavily API Key", "type": "password", "required": True, "group": "credentials", "is_credential": True},
        ],
    },
    # ── Monitoring & Observability ──
    {
        "id": "grafana",
        "name": "Grafana",
        "description": "Query dashboards, explore metrics, search logs, and manage alerts from Grafana.",
        "icon": "activity",
        "category": "observability",
        "transport": "remote",
        "endpoint": None,
        "auth_type": "api_key",
        "enabled": True,
        "tags": ["monitoring", "metrics", "dashboards", "alerts"],
        "tools_count": 8,
        "config_schema": [
            {"key": "url", "label": "Grafana URL", "type": "text", "placeholder": "https://grafana.example.com", "required": True, "group": "connection"},
            {"key": "api_key", "label": "Grafana API Key", "type": "password", "required": True, "group": "credentials", "is_credential": True},
        ],
    },
    {
        "id": "datadog",
        "name": "Datadog",
        "description": "Query metrics, search logs, manage monitors, and explore traces from Datadog.",
        "icon": "activity",
        "category": "observability",
        "transport": "remote",
        "endpoint": None,
        "auth_type": "api_key",
        "enabled": True,
        "tags": ["monitoring", "apm", "logs", "infrastructure"],
        "tools_count": 10,
        "config_schema": [
            {"key": "api_key", "label": "Datadog API Key", "type": "password", "required": True, "group": "credentials", "is_credential": True},
            {"key": "app_key", "label": "Datadog App Key", "type": "password", "required": True, "group": "credentials", "is_credential": True},
            {"key": "site", "label": "Datadog Site", "type": "text", "placeholder": "datadoghq.com", "group": "connection"},
        ],
    },
    {
        "id": "netdata-cloud",
        "name": "Netdata Cloud",
        "description": "Official Netdata-hosted MCP endpoint for infrastructure troubleshooting and observability workflows.",
        "icon": "activity",
        "category": "observability",
        "transport": "remote",
        "endpoint": "https://app.netdata.cloud/api/v1/mcp",
        "auth_type": "bearer",
        "enabled": True,
        "tags": ["observability", "metrics", "infrastructure", "troubleshooting"],
        "tools_count": 6,
        "protocol_label": "Streamable HTTP",
        "deployment_model": "Vendor-hosted remote",
        "connection_notes": "Netdata Cloud uses bearer-token authentication against the hosted MCP endpoint. Use this entry for hosted Netdata Cloud troubleshooting rather than self-hosted collectors.",
        "config_schema": [
            {"key": "token", "label": "Netdata Cloud Token", "type": "password", "required": True, "group": "credentials", "is_credential": True},
        ],
    },
]

# ── MCP Profiles ── curated presets for common use cases ──

MCP_PROFILES: list[dict[str, Any]] = [
    {
        "id": "developer-essentials",
        "name": "Developer Essentials",
        "description": "Core toolkit for software development: GitHub access, code documentation, browser testing, and filesystem operations.",
        "icon": "code",
        "color": "sky",
        "servers": ["github-remote", "context7", "playwright-sidecar", "filesystem-sidecar"],
        "tags": ["development", "recommended"],
    },
    {
        "id": "cloud-ops",
        "name": "Cloud Operations",
        "description": "Full-stack infrastructure management with Azure, Kubernetes, Docker, and observability tools.",
        "icon": "cloud",
        "color": "violet",
        "servers": ["azure-mcp", "kubernetes-mcp", "docker", "grafana", "netdata-cloud", "sentry"],
        "tags": ["infrastructure", "devops", "monitoring"],
    },
    {
        "id": "data-science",
        "name": "Data & Analytics",
        "description": "Database access, vector search, and knowledge retrieval for data-intensive workflows.",
        "icon": "database",
        "color": "emerald",
        "servers": ["postgres-hub", "sqlite", "qdrant", "exa"],
        "tags": ["data", "analytics", "ml"],
    },
    {
        "id": "research-writer",
        "name": "Research & Writing",
        "description": "Web research, content retrieval, documentation lookup, and AI-powered search for writing and analysis tasks.",
        "icon": "book-open",
        "color": "amber",
        "servers": ["brave-search", "tavily", "context7", "firecrawl", "notion"],
        "tags": ["research", "writing", "content"],
    },
    {
        "id": "team-collaboration",
        "name": "Team Collaboration",
        "description": "Connect with your team through Slack, Linear, email, and knowledge bases like Notion.",
        "icon": "users",
        "color": "rose",
        "servers": ["slack", "linear", "atlassian-rovo", "notion", "gmail"],
        "tags": ["communication", "project-management", "team"],
    },
    {
        "id": "full-stack",
        "name": "Full Stack",
        "description": "Everything included: development, cloud, data, communication, and research tools for maximum capability.",
        "icon": "layers",
        "color": "fuchsia",
        "servers": ["github-remote", "context7", "playwright-sidecar", "filesystem-sidecar", "azure-mcp", "kubernetes-mcp", "postgres-hub", "brave-search", "slack", "grafana"],
        "tags": ["everything", "maximum-capability"],
    },
]

MCP_REGISTRY_TOOL_NAMES: dict[str, list[str]] = {
    "github-remote": [
        "Search repositories",
        "Search code",
        "Read issues",
        "Create issues",
        "Read pull requests",
        "Create pull requests",
        "Review pull request files",
        "Trigger Actions workflows",
    ],
    "context7": [
        "Resolve library IDs",
        "Fetch library docs",
    ],
    "brave-search": [
        "Web search",
        "Local search",
    ],
    "firecrawl": [
        "Scrape page",
        "Crawl site",
        "Map site",
        "Extract structured data",
        "Search indexed pages",
        "Deep research",
    ],
    "sentry": [
        "Find issues",
        "Inspect issue details",
        "Read stack traces",
        "Query traces",
        "Search releases",
        "List projects",
        "Comment on issues",
        "Assign issues",
    ],
    "linear": [
        "Search issues",
        "Create issue",
        "Update issue",
        "Comment on issue",
        "List projects",
        "List cycles",
        "Search teams",
        "Create project",
    ],
    "slack": [
        "Search messages",
        "Read channel history",
        "Post message",
        "Reply in thread",
        "List channels",
        "Read channel info",
        "Lookup users",
        "Open direct message",
    ],
    "notion": [
        "Search pages",
        "Read page",
        "Create page",
        "Update page",
        "Search databases",
        "Query database",
        "Create database row",
        "Update database row",
    ],
    "github-hub": [
        "Search repositories",
        "Search code",
        "Read issues",
        "Create issues",
        "Read pull requests",
        "Create pull requests",
        "Review pull request files",
        "Trigger Actions workflows",
    ],
    "postgres-hub": [
        "List schemas",
        "List tables",
        "Describe table",
        "Run read-only query",
        "Explain query",
    ],
    "playwright-sidecar": [
        "Open page",
        "Click element",
        "Fill form",
        "Take screenshot",
        "Evaluate script",
        "Wait for selector",
        "Extract text",
        "Manage tabs",
    ],
    "filesystem-sidecar": [
        "List directory",
        "Read file",
        "Write file",
        "Edit file",
        "Create directory",
        "Move file",
        "Delete file",
        "Search workspace",
    ],
    "memory-sidecar": [
        "Store memory",
        "Search memories",
        "Read entities",
        "Write entities",
        "Link related facts",
        "Summarize context",
        "Pin memory",
    ],
    "puppeteer-sidecar": [
        "Open page",
        "Click element",
        "Fill form",
        "Take screenshot",
        "Evaluate script",
        "Extract text",
        "Generate PDF",
        "Manage tabs",
    ],
    "azure-mcp": [
        "List subscriptions",
        "Manage resource groups",
        "Inspect virtual machines",
        "Query storage accounts",
        "Deploy templates",
        "Manage Container Apps",
        "Read Azure Monitor metrics",
        "Work with Azure OpenAI resources",
    ],
    "aws-kb-retrieval": [
        "Retrieve knowledge base context",
    ],
    "qdrant": [
        "Create collection",
        "List collections",
        "Upsert points",
        "Query points",
        "Delete points",
        "Inspect collection",
    ],
    "sqlite": [
        "Open database",
        "List tables",
        "Describe table",
        "Run query",
        "Insert row",
        "Update row",
    ],
    "docker": [
        "List containers",
        "Inspect container",
        "View logs",
        "Build image",
        "Run container",
        "Stop container",
        "List images",
        "Manage networks",
    ],
    "kubernetes-mcp": [
        "List resources",
        "Read logs",
        "Describe resource",
        "Apply manifest",
        "Delete resource",
        "Scale workload",
        "Restart workload",
        "Inspect events",
    ],
    "gmail": [
        "Search mail",
        "Read message",
        "Send message",
        "Draft reply",
        "List threads",
        "Read attachments",
        "Label message",
        "Archive message",
    ],
    "discord": [
        "List guilds",
        "List channels",
        "Read messages",
        "Send message",
        "Reply in thread",
        "Manage channels",
        "Lookup members",
    ],
    "figma": [
        "Read file",
        "Inspect components",
        "Read design tokens",
        "Read frames",
        "Inspect styles",
    ],
    "exa": [
        "Search web",
        "Find similar pages",
        "Answer with citations",
    ],
    "tavily": [
        "Search web",
        "Deep research",
    ],
    "grafana": [
        "List dashboards",
        "Read dashboard",
        "Query metrics",
        "Search logs",
        "Inspect traces",
        "List alerts",
        "Read alert rule",
        "Explore datasources",
    ],
    "datadog": [
        "Query metrics",
        "Search logs",
        "Inspect traces",
        "List monitors",
        "Read monitor",
        "Manage downtime",
        "Query events",
        "Read dashboards",
    ],
}


def _build_mcp_registry_entry(entry: dict[str, Any]) -> dict[str, Any]:
    result = dict(entry)
    tool_names = result.get("tool_names")
    if not isinstance(tool_names, list):
        tool_names = MCP_REGISTRY_TOOL_NAMES.get(str(result.get("id") or ""), [])
    result["tool_names"] = [str(name).strip() for name in tool_names if str(name).strip()]

    if result.get("transport") == "sidecar":
        tid = str(result.get("id", "")).replace("-sidecar", "")
        image = _resolve_sidecar_image(tid)
        if image:
            result["sidecar_image"] = image
        port = _resolve_sidecar_port(tid, 0)
        if port:
            result["sidecar_port"] = port

    transport = str(result.get("transport") or "").strip().lower()
    auth_type = str(result.get("auth_type") or "none").strip().lower()
    registry_endpoint = str(result.get("endpoint") or "").strip()
    config_schema = result.get("config_schema") if isinstance(result.get("config_schema"), list) else []

    for metadata_key in (
        "docs_url",
        "repository_url",
        "connection_notes",
        "auth_header_name",
        "suggested_endpoint",
        "oauth_authorization_url",
        "oauth_token_url",
    ):
        cleaned_value = str(result.get(metadata_key) or "").strip()
        if cleaned_value:
            result[metadata_key] = cleaned_value
        else:
            result.pop(metadata_key, None)
    if result.get("auth_header_prefix") is not None:
        result["auth_header_prefix"] = str(result.get("auth_header_prefix"))
    oauth_scopes = result.get("oauth_scopes") if isinstance(result.get("oauth_scopes"), list) else []
    cleaned_oauth_scopes = [str(scope).strip() for scope in oauth_scopes if str(scope).strip()]
    if cleaned_oauth_scopes:
        result["oauth_scopes"] = cleaned_oauth_scopes
    else:
        result.pop("oauth_scopes", None)
    oauth_extra_authorize_params = _trimmed_string_mapping(result.get("oauth_extra_authorize_params"))
    if oauth_extra_authorize_params:
        result["oauth_extra_authorize_params"] = oauth_extra_authorize_params
    else:
        result.pop("oauth_extra_authorize_params", None)
    oauth_extra_token_params = _trimmed_string_mapping(result.get("oauth_extra_token_params"))
    if oauth_extra_token_params:
        result["oauth_extra_token_params"] = oauth_extra_token_params
    else:
        result.pop("oauth_extra_token_params", None)
    oauth_token_auth_method = str(result.get("oauth_token_auth_method") or "").strip().lower()
    if oauth_token_auth_method in {"client_secret_post", "client_secret_basic", "none"}:
        result["oauth_token_auth_method"] = oauth_token_auth_method
    else:
        result.pop("oauth_token_auth_method", None)
    if "oauth_pkce" in result:
        result["oauth_pkce"] = bool(result.get("oauth_pkce"))

    protocol_label = str(result.get("protocol_label") or "").strip()
    if not protocol_label:
        if transport == "remote":
            protocol_label = "Streamable HTTP"
        elif transport == "hub":
            protocol_label = "Cluster service HTTP"
        elif transport == "sidecar":
            protocol_label = "Pod-local HTTP"
    if protocol_label:
        result["protocol_label"] = protocol_label

    deployment_model = str(result.get("deployment_model") or "").strip()
    if not deployment_model:
        if transport == "remote":
            deployment_model = "Vendor-hosted remote" if registry_endpoint else "Self-hosted remote"
        elif transport == "hub":
            deployment_model = "Shared hub service"
        elif transport == "sidecar":
            deployment_model = "Per-agent sidecar"
    if deployment_model:
        result["deployment_model"] = deployment_model

    if transport == "remote":
        if auth_type == "oauth":
            oauth_supported, oauth_reason = _saved_oauth_support(result)
            if not oauth_supported:
                result.update(
                    {
                        "support_level": "planned",
                        "attachable": False,
                        "status_reason": oauth_reason
                        or "This OAuth-backed MCP entry still needs provider metadata before KubeSynth can drive the sign-in flow.",
                    }
                )
                return result
            result.update(
                {
                    "support_level": "ready" if registry_endpoint else "limited",
                    "attachable": True,
                    "status_reason": (
                        "Attachable after you save the connection and complete browser-based OAuth once from the MCP page. KubeSynth stores the resulting token on the saved connection and reuses it for runtime headers."
                        if registry_endpoint
                        else "Attachable after you save the connection, provide the endpoint URL for your own deployment, and complete browser-based OAuth once from the MCP page."
                    ),
                }
            )
            return result
        if auth_type == "kubeconfig":
            result.update(
                {
                    "support_level": "planned",
                    "attachable": False,
                    "status_reason": "Kubeconfig-backed remote MCP flows still need runtime-specific credential mounting before they can be attached to agents.",
                }
            )
            return result
        if registry_endpoint:
            result.update(
                {
                    "support_level": "ready",
                    "attachable": True,
                    "status_reason": "Attachable with a saved namespace-scoped connection. The published remote MCP endpoint is prefilled from the registry; add credentials or optional overrides only when needed.",
                }
            )
            return result
        result.update(
            {
                "support_level": "limited",
                "attachable": True,
                "status_reason": "No default endpoint is published for this MCP. Use it only when you run your own remote MCP deployment and can provide its endpoint URL and credentials.",
            }
        )
        return result

    if transport == "hub":
        support_level = "ready" if auth_type in {"none", "bearer", "api_key"} else "limited"
        result.update(
            {
                "support_level": support_level,
                "attachable": True,
                "status_reason": (
                    "Attachable through the shared MCP hub with saved namespace-scoped connection metadata and credentials."
                    if support_level == "ready"
                    else "Attachable through the shared MCP hub, but non-standard credential flows may still need adapter-specific follow-up."
                ),
            }
        )
        return result

    if transport == "sidecar":
        if not result.get("sidecar_image"):
            result.update(
                {
                    "support_level": "planned",
                    "attachable": False,
                    "status_reason": "This sidecar is listed in the registry, but no managed sidecar image is registered for it yet.",
                }
            )
            return result
        result.update(
            {
                "support_level": "ready",
                "attachable": True,
                "status_reason": (
                    "Attachable today as a managed per-agent sidecar. Saved connections preserve image, port, and per-sidecar configuration."
                    if config_schema
                    else "Attachable today as a managed per-agent sidecar."
                ),
            }
        )
        return result

    result.update(
        {
            "support_level": "planned",
            "attachable": False,
            "status_reason": "This MCP server has an unknown transport and is not attachable yet.",
        }
    )
    return result


def _build_mcp_registry_results() -> list[dict[str, Any]]:
    return [_build_mcp_registry_entry(entry) for entry in MCP_REGISTRY]


@app.get("/api/skills/catalog")
def get_skills_catalog(
    category: str | None = None,
    search: str | None = None,
    user=Depends(verify_token),
) -> list[dict[str, Any]]:
    del user
    catalog = _load_skills_catalog()
    results = catalog

    if category:
        category_lower = category.strip().lower()
        results = [s for s in results if s.get("category", "").lower() == category_lower]

    if search:
        search_lower = search.strip().lower()
        results = [
            s
            for s in results
            if search_lower in s.get("name", "").lower()
            or search_lower in s.get("description", "").lower()
            or search_lower in s.get("id", "").lower()
        ]

    return [
        {
            "id": s.get("id"),
            "name": s.get("name"),
            "description": s.get("description"),
            "category": s.get("category"),
            "source": s.get("source"),
            "license": s.get("license"),
            "instructions_preview": s.get("instructions_preview"),
            "allowed_mcp_servers": s.get("allowed_mcp_servers", []),
            "allowed_sandbox_tools": s.get("allowed_sandbox_tools", []),
            "bundled_assets": s.get("bundled_assets", []),
            "files": dict.fromkeys(s.get("files", {}).keys(), "") if isinstance(s.get("files"), dict) else {},
        }
        for s in results
    ]


@app.post("/api/skills/catalog/refresh")
def refresh_skills_catalog(
    user=Depends(verify_token),
) -> dict[str, Any]:
    """Invalidate the in-memory skills catalog cache so the next read reloads from disk."""
    del user
    global _SKILLS_CATALOG_CACHE
    _SKILLS_CATALOG_CACHE = None
    reloaded = _load_skills_catalog()
    return {"refreshed": True, "count": len(reloaded)}


@app.get("/api/skills/catalog/{skill_id}")
def get_skill_detail(
    skill_id: str,
    user=Depends(verify_token),
) -> dict[str, Any]:
    del user
    catalog = _load_skills_catalog()
    for s in catalog:
        if s.get("id") == skill_id:
            return s
    raise HTTPException(status_code=404, detail=f"Skill '{skill_id}' not found in catalog")


@app.get("/api/skills/tools")
def get_tool_categories(
    user=Depends(verify_token),
) -> list[dict[str, Any]]:
    del user
    return [
        {
            **tool,
            "default_port": _resolve_sidecar_port(str(tool.get("id", "")), int(tool.get("default_port", 0))),
            "sidecar_image": _resolve_sidecar_image(str(tool.get("id", ""))),
        }
        for tool in MCP_TOOL_CATEGORIES
    ]


@app.get("/api/mcp-hub/servers")
def get_mcp_hub_servers(
    user=Depends(verify_token),
) -> list[dict[str, Any]]:
    """Return metadata about shared MCP hub servers available for agents."""
    del user
    return MCP_HUB_SERVERS


# ── MCP Registry & Management API ──


@app.get("/api/mcp/registry")
def get_mcp_registry(
    category: str | None = None,
    transport: str | None = None,
    search: str | None = None,
    user=Depends(verify_token),
) -> list[dict[str, Any]]:
    """Return the full MCP server registry with optional filtering."""
    del user
    results = _build_mcp_registry_results()

    if category:
        cat_lower = category.strip().lower()
        results = [s for s in results if s.get("category", "").lower() == cat_lower]

    if transport:
        t_lower = transport.strip().lower()
        results = [s for s in results if s.get("transport", "").lower() == t_lower]

    if search:
        search_lower = search.strip().lower()
        results = [
            s
            for s in results
            if search_lower in s.get("name", "").lower()
            or search_lower in s.get("description", "").lower()
            or search_lower in s.get("id", "").lower()
            or any(search_lower in tag for tag in s.get("tags", []))
        ]

    return results


@app.get("/api/mcp/profiles")
def get_mcp_profiles(
    user=Depends(verify_token),
) -> list[dict[str, Any]]:
    """Return curated MCP profiles (presets)."""
    del user
    registry_index = {s["id"]: s for s in _build_mcp_registry_results()}
    enriched = []
    for profile in MCP_PROFILES:
        resolved_servers = []
        attachable_servers = []
        blocked_servers = []
        total_tools = 0
        for sid in profile.get("servers", []):
            entry = registry_index.get(sid)
            if entry:
                resolved_entry = {
                    "id": sid,
                    "name": entry["name"],
                    "transport": entry["transport"],
                    "support_level": entry.get("support_level", "planned"),
                    "attachable": bool(entry.get("attachable")),
                    "status_reason": entry.get("status_reason"),
                }
                resolved_servers.append(resolved_entry)
                if resolved_entry["attachable"]:
                    attachable_servers.append(resolved_entry)
                else:
                    blocked_servers.append(resolved_entry)
                total_tools += entry.get("tools_count", 0)
        support_level = "planned"
        if attachable_servers and not blocked_servers:
            support_level = "ready"
        elif attachable_servers:
            support_level = "limited"
        enriched.append(
            {
                **profile,
                "resolved_servers": resolved_servers,
                "attachable_servers": attachable_servers,
                "blocked_servers": blocked_servers,
                "can_apply": bool(attachable_servers),
                "support_level": support_level,
                "total_tools": total_tools,
            }
        )
    return enriched


@app.get("/api/mcp/registry/{server_id}")
def get_mcp_server_detail(
    server_id: str,
    user=Depends(verify_token),
) -> dict[str, Any]:
    """Return full detail for a single MCP registry entry."""
    del user
    for entry in MCP_REGISTRY:
        if entry["id"] == server_id:
            return _build_mcp_registry_entry(entry)
    raise HTTPException(status_code=404, detail=f"MCP server '{server_id}' not found in registry.")


@app.get("/api/mcp/categories")
def get_mcp_categories(
    user=Depends(verify_token),
) -> list[dict[str, Any]]:
    """Return all unique MCP categories with counts."""
    del user
    category_counts: dict[str, int] = {}
    for entry in MCP_REGISTRY:
        cat = entry.get("category", "other")
        category_counts[cat] = category_counts.get(cat, 0) + 1
    return [{"id": cat, "name": cat.replace("-", " ").title(), "count": count} for cat, count in sorted(category_counts.items())]


@app.get("/api/mcp/stats")
def get_mcp_stats(
    user=Depends(verify_token),
) -> dict[str, Any]:
    """Return aggregate MCP registry statistics."""
    del user
    transport_counts: dict[str, int] = {}
    total_tools = 0
    for entry in MCP_REGISTRY:
        t = entry.get("transport", "unknown")
        transport_counts[t] = transport_counts.get(t, 0) + 1
        total_tools += entry.get("tools_count", 0)
    return {
        "total_servers": len(MCP_REGISTRY),
        "total_tools": total_tools,
        "total_profiles": len(MCP_PROFILES),
        "by_transport": transport_counts,
        "categories": len({e.get("category", "other") for e in MCP_REGISTRY}),
    }


@app.get("/api/mcp/connections")
def get_mcp_connections(
    namespace: str = "default",
    user=Depends(verify_token),
) -> list[dict[str, Any]]:
    ensure_namespace_access(user, namespace)
    bindings_by_id = _list_mcp_connection_bindings(namespace)
    return [
        _serialize_saved_mcp_connection_record(record, binding_count=len(bindings_by_id.get(record["id"], [])))
        for record in list_mcp_connections(namespace)
    ]


@app.post("/api/mcp/connections", status_code=201)
def create_saved_mcp_connection(
    body: McpConnectionRequest,
    namespace: str = "default",
    user=Depends(verify_token),
) -> dict[str, Any]:
    ensure_namespace_access(user, namespace, "operator")
    entry = _lookup_mcp_registry_entry(body.server_id)
    config = _normalize_mcp_connection_config(entry, body.config, source="body")
    credentials = _normalize_mcp_connection_credentials(entry, body.credentials, source="body")
    credential_metadata = _build_mcp_connection_credential_metadata(entry, configured_keys=set(credentials))
    created = create_mcp_connection(
        namespace=namespace,
        name=body.name,
        server_id=str(entry.get("id") or body.server_id),
        transport=str(entry.get("transport") or "remote"),
        auth_type=str(entry.get("auth_type") or "none"),
        config=config,
        credential_metadata=credential_metadata,
        validation_status="draft",
        validation_message="Saved but not validated yet.",
    )
    try:
        secret_name = _upsert_mcp_connection_secret(namespace, created["id"], credentials)
        validation_status = "draft"
        validation_message = "Saved but not validated yet."
        validation_detail: dict[str, Any] | None = None
        validated_at: datetime | None = None
        if body.validate_on_save:
            validation_status, validation_message, validation_detail = _validate_saved_mcp_connection_record(
                {**created, "secret_name": secret_name, "credential_metadata": credential_metadata}
            )
            validated_at = datetime.now(UTC)
        updated = update_mcp_connection(
            namespace,
            created["id"],
            transport=str(entry.get("transport") or "remote"),
            auth_type=str(entry.get("auth_type") or "none"),
            config=config,
            credential_metadata=credential_metadata,
            secret_name=secret_name,
            validation_status=validation_status,
            validation_message=validation_message,
            validation_detail=validation_detail,
            last_validated_at=validated_at,
        )
    except Exception:
        delete_mcp_connection(namespace, created["id"])
        raise
    return _serialize_saved_mcp_connection_record(updated)


@app.get("/api/mcp/connections/{connection_id}")
def get_saved_mcp_connection(
    connection_id: str,
    namespace: str = "default",
    user=Depends(verify_token),
) -> dict[str, Any]:
    ensure_namespace_access(user, namespace)
    record = get_mcp_connection(namespace, connection_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"MCP connection '{connection_id}' was not found.")
    bindings = _list_mcp_connection_bindings(namespace).get(connection_id, [])
    return _serialize_saved_mcp_connection_record(record, binding_count=len(bindings))


@app.patch("/api/mcp/connections/{connection_id}")
def update_saved_mcp_connection(
    connection_id: str,
    body: McpConnectionUpdateRequest,
    namespace: str = "default",
    user=Depends(verify_token),
) -> dict[str, Any]:
    ensure_namespace_access(user, namespace, "operator")
    existing = get_mcp_connection(namespace, connection_id)
    if existing is None:
        raise HTTPException(status_code=404, detail=f"MCP connection '{connection_id}' was not found.")

    next_server_id = str(body.server_id or existing["server_id"]).strip()
    entry = _lookup_mcp_registry_entry(next_server_id)
    server_changed = next_server_id != str(existing.get("server_id") or "")

    config_source = body.config if body.config is not None else ({} if server_changed else existing.get("config") or {})
    config = _normalize_mcp_connection_config(entry, config_source, source="body")

    existing_configured_keys = set() if server_changed else _configured_credential_keys(existing.get("credential_metadata"))
    credentials = _normalize_mcp_connection_credentials(entry, body.credentials, source="body") if body.credentials is not None else {}
    configured_keys = existing_configured_keys | set(credentials)
    credential_metadata = _build_mcp_connection_credential_metadata(entry, configured_keys=configured_keys)

    existing_secret_name = str(existing.get("secret_name") or "").strip() or None
    existing_secret_values = {} if server_changed else _read_mcp_connection_secret_values(namespace, existing_secret_name)
    secret_name = existing_secret_name
    next_secret_values = dict(existing_secret_values)
    if server_changed and existing_secret_name:
        _delete_mcp_connection_secret(namespace, existing_secret_name)
        secret_name = None
        next_secret_values = {}
    if credentials:
        next_secret_values.update(credentials)

    should_reset_oauth_session = str(entry.get("auth_type") or "none").strip().lower() == "oauth" and (
        server_changed or body.config is not None or body.credentials is not None
    )
    if should_reset_oauth_session:
        next_secret_values = _clear_mcp_oauth_session_values(next_secret_values)

    if body.credentials is not None or should_reset_oauth_session:
        if next_secret_values:
            secret_name = _upsert_mcp_connection_secret(namespace, connection_id, next_secret_values)
        else:
            if existing_secret_name and not server_changed:
                _delete_mcp_connection_secret(namespace, existing_secret_name)
            secret_name = None

    validation_status = str((existing.get("validation") or {}).get("status") or "draft")
    validation_message = str((existing.get("validation") or {}).get("message") or "Saved but not validated yet.")
    validation_detail = (existing.get("validation") or {}).get("detail")
    validated_at_raw = (existing.get("validation") or {}).get("last_validated_at")
    validated_at: datetime | None = None
    if isinstance(validated_at_raw, str) and validated_at_raw:
        with contextlib.suppress(ValueError):
            validated_at = datetime.fromisoformat(validated_at_raw.replace("Z", "+00:00"))

    if server_changed or body.config is not None or body.credentials is not None:
        validation_status = "draft"
        validation_message = "Saved but not validated yet."
        validation_detail = None
        validated_at = None
    if body.validate_on_save:
        validation_status, validation_message, validation_detail = _validate_saved_mcp_connection_record(
            {
                **existing,
                "id": connection_id,
                "name": body.name or existing.get("name"),
                "server_id": next_server_id,
                "transport": entry.get("transport"),
                "auth_type": entry.get("auth_type"),
                "config": config,
                "credential_metadata": credential_metadata,
                "secret_name": secret_name,
            }
        )
        validated_at = datetime.now(UTC)

    updated = update_mcp_connection(
        namespace,
        connection_id,
        name=body.name,
        transport=str(entry.get("transport") or "remote"),
        auth_type=str(entry.get("auth_type") or "none"),
        config=config,
        credential_metadata=credential_metadata,
        secret_name=secret_name,
        validation_status=validation_status,
        validation_message=validation_message,
        validation_detail=validation_detail if isinstance(validation_detail, dict) else None,
        last_validated_at=validated_at,
    )
    bindings = _list_mcp_connection_bindings(namespace).get(connection_id, [])
    return _serialize_saved_mcp_connection_record(updated, binding_count=len(bindings))


@app.post("/api/mcp/connections/{connection_id}/validate")
def validate_saved_mcp_connection(
    connection_id: str,
    namespace: str = "default",
    user=Depends(verify_token),
) -> dict[str, Any]:
    ensure_namespace_access(user, namespace, "operator")
    existing = get_mcp_connection(namespace, connection_id)
    if existing is None:
        raise HTTPException(status_code=404, detail=f"MCP connection '{connection_id}' was not found.")

    validation_status, validation_message, validation_detail = _validate_saved_mcp_connection_record(existing)
    updated = update_mcp_connection(
        namespace,
        connection_id,
        validation_status=validation_status,
        validation_message=validation_message,
        validation_detail=validation_detail,
        last_validated_at=datetime.now(UTC),
    )
    bindings = _list_mcp_connection_bindings(namespace).get(connection_id, [])
    return _serialize_saved_mcp_connection_record(updated, binding_count=len(bindings))


def _clean_expired_mcp_oauth_flows() -> None:
    now = datetime.now(UTC)
    expired_states = [
        state
        for state, flow in _MCP_OAUTH_PENDING_FLOWS.items()
        if _parse_iso_datetime(flow.get("expires_at")) and cast(datetime, _parse_iso_datetime(flow.get("expires_at"))) <= now
    ]
    for state in expired_states:
        _MCP_OAUTH_PENDING_FLOWS.pop(state, None)


def _mcp_oauth_callback_response(
    connection_id: str,
    *,
    status_value: str,
    message: str,
    restarted_agents: list[str] | None = None,
) -> Response:
    payload = json.dumps(
        {
            "type": "kubesynth-mcp-oauth-result",
            "connectionId": connection_id,
            "status": status_value,
            "message": message,
            "restartedAgents": restarted_agents or [],
        }
    )
    title = "MCP OAuth connected" if status_value == "success" else "MCP OAuth failed"
    safe_title = html.escape(title)
    safe_message = html.escape(message)
    html_body = f"""<!doctype html>
<html lang=\"en\">
  <head>
    <meta charset=\"utf-8\" />
    <title>{safe_title}</title>
    <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
    <style>
      body {{ font-family: ui-sans-serif, system-ui, sans-serif; background: #0c1117; color: #f5f7fa; margin: 0; }}
      main {{ max-width: 32rem; margin: 12vh auto; padding: 2rem; border-radius: 1rem; border: 1px solid rgba(255,255,255,0.08); background: rgba(255,255,255,0.04); }}
      h1 {{ margin: 0 0 0.75rem; font-size: 1.125rem; }}
      p {{ margin: 0; line-height: 1.6; color: rgba(245,247,250,0.82); }}
    </style>
  </head>
  <body>
    <main>
      <h1>{safe_title}</h1>
      <p>{safe_message}</p>
    </main>
    <script>
      (function() {{
        const payload = {payload};
        try {{
          if (window.opener && !window.opener.closed) {{
            window.opener.postMessage(payload, "*");
          }}
        }} catch (_error) {{}}
        try {{
          window.close();
        }} catch (_error) {{}}
      }})();
    </script>
  </body>
</html>"""
    return Response(content=html_body, media_type="text/html")


@app.post("/api/mcp/connections/{connection_id}/oauth/start")
def start_saved_mcp_connection_oauth(
    connection_id: str,
    raw_request: Request,
    namespace: str = "default",
    user=Depends(verify_token),
) -> dict[str, Any]:
    ensure_namespace_access(user, namespace, "operator")
    record = get_mcp_connection(namespace, connection_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"MCP connection '{connection_id}' was not found.")

    entry = _lookup_mcp_registry_entry(str(record.get("server_id") or ""))
    if str(entry.get("auth_type") or "none").strip().lower() != "oauth":
        raise HTTPException(status_code=400, detail="This MCP connection does not use OAuth.")
    supported, support_reason = _saved_oauth_support(entry)
    if not supported:
        raise HTTPException(status_code=400, detail=support_reason or "OAuth is not configured for this MCP entry yet.")

    secret_values = _mcp_connection_secret_values_for_record(record)
    metadata = _mcp_oauth_entry_metadata(entry)
    redirect_uri = _mcp_oauth_redirect_uri(raw_request, connection_id)
    code_verifier = _mcp_oauth_code_verifier()
    state = uuid.uuid4().hex
    params = {
        "response_type": "code",
        "client_id": _mcp_oauth_client_id(record, entry, secret_values),
        "redirect_uri": redirect_uri,
        "state": state,
    }
    if metadata["scopes"]:
        params["scope"] = " ".join(metadata["scopes"])
    if bool(metadata["pkce"]):
        params["code_challenge"] = _mcp_oauth_code_challenge(code_verifier)
        params["code_challenge_method"] = "S256"
    params.update(metadata["authorize_params"])

    _clean_expired_mcp_oauth_flows()
    expires_at = datetime.now(UTC) + timedelta(seconds=_MCP_OAUTH_FLOW_TTL_SECONDS)
    _MCP_OAUTH_PENDING_FLOWS[state] = {
        "connection_id": connection_id,
        "namespace": namespace,
        "user_sub": str(user.get("sub") or "").strip(),
        "code_verifier": code_verifier,
        "expires_at": expires_at.isoformat(),
    }
    return {
        "authorization_url": f"{metadata['authorization_url']}?{urlencode(params)}",
        "expires_at": expires_at.isoformat(),
    }


@app.get("/api/mcp/connections/{connection_id}/oauth/callback")
async def complete_saved_mcp_connection_oauth(
    connection_id: str,
    raw_request: Request,
    state: str = "",
    code: str | None = None,
    error: str | None = None,
    error_description: str | None = None,
) -> Response:
    _clean_expired_mcp_oauth_flows()
    flow = _MCP_OAUTH_PENDING_FLOWS.get(state)
    if flow is None or str(flow.get("connection_id") or "") != connection_id:
        return _mcp_oauth_callback_response(
            connection_id,
            status_value="error",
            message="This OAuth sign-in session expired or no longer matches the saved connection.",
        )

    namespace = str(flow.get("namespace") or "default").strip() or "default"
    _MCP_OAUTH_PENDING_FLOWS.pop(state, None)
    if error:
        message = str(error_description or error).strip() or "OAuth provider rejected the sign-in request."
        return _mcp_oauth_callback_response(connection_id, status_value="error", message=message)

    record = get_mcp_connection(namespace, connection_id)
    if record is None:
        return _mcp_oauth_callback_response(
            connection_id,
            status_value="error",
            message="The saved MCP connection was deleted before OAuth completed.",
        )

    entry = _lookup_mcp_registry_entry(str(record.get("server_id") or ""))
    secret_values = _mcp_connection_secret_values_for_record(record)
    try:
        token_url, headers, data = _build_mcp_oauth_token_request(
            entry,
            record,
            grant_type="authorization_code",
            secret_values=secret_values,
            code=code,
            redirect_uri=_mcp_oauth_redirect_uri(raw_request, connection_id),
            code_verifier=str(flow.get("code_verifier") or "").strip() or None,
        )
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True, verify=certifi.where()) as client:
            response = await client.post(token_url, data=data, headers=headers)
            response.raise_for_status()
            token_payload = response.json()
        token_bundle = _extract_mcp_oauth_token_bundle(token_payload, secret_values)
        secret_name, _merged_secret_values = _store_mcp_oauth_token_bundle(namespace, connection_id, secret_values, token_bundle)
        validation_status, validation_message, validation_detail = _validate_saved_mcp_connection_record(
            {
                **record,
                "secret_name": secret_name,
            }
        )
        updated = update_mcp_connection(
            namespace,
            connection_id,
            secret_name=secret_name,
            validation_status=validation_status,
            validation_message=validation_message,
            validation_detail=validation_detail if isinstance(validation_detail, dict) else None,
            last_validated_at=datetime.now(UTC),
        )
        restarted_agents = _restart_bound_agents_for_mcp_connection(namespace, connection_id)
    except HTTPException as exc:
        return _mcp_oauth_callback_response(connection_id, status_value="error", message=str(exc.detail))
    except Exception as exc:
        logger.exception("Failed to complete MCP OAuth callback for %s/%s", namespace, connection_id)
        return _mcp_oauth_callback_response(
            connection_id,
            status_value="error",
            message=f"Failed to complete OAuth sign-in: {exc}",
        )

    message = "OAuth sign-in completed and the saved MCP connection is ready to use."
    if restarted_agents:
        message = f"OAuth sign-in completed. Restarted {len(restarted_agents)} bound agent(s) so they pick up the refreshed token."
    del updated
    return _mcp_oauth_callback_response(
        connection_id,
        status_value="success",
        message=message,
        restarted_agents=restarted_agents,
    )


@app.post("/api/mcp/connections/{connection_id}/oauth/refresh")
def refresh_saved_mcp_connection_oauth(
    connection_id: str,
    namespace: str = "default",
    user=Depends(verify_token),
) -> dict[str, Any]:
    ensure_namespace_access(user, namespace, "operator")
    record = get_mcp_connection(namespace, connection_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"MCP connection '{connection_id}' was not found.")

    entry = _lookup_mcp_registry_entry(str(record.get("server_id") or ""))
    if str(entry.get("auth_type") or "none").strip().lower() != "oauth":
        raise HTTPException(status_code=400, detail="This MCP connection does not use OAuth.")

    _refresh_mcp_connection_oauth_access_token_sync(record, entry)
    refreshed_record = get_mcp_connection(namespace, connection_id) or record
    validation_status, validation_message, validation_detail = _validate_saved_mcp_connection_record(refreshed_record)
    updated = update_mcp_connection(
        namespace,
        connection_id,
        secret_name=str(refreshed_record.get("secret_name") or "").strip() or None,
        validation_status=validation_status,
        validation_message=validation_message,
        validation_detail=validation_detail if isinstance(validation_detail, dict) else None,
        last_validated_at=datetime.now(UTC),
    )
    _restart_bound_agents_for_mcp_connection(namespace, connection_id)
    bindings = _list_mcp_connection_bindings(namespace).get(connection_id, [])
    return _serialize_saved_mcp_connection_record(updated, binding_count=len(bindings))


@app.get("/api/mcp/connections/{connection_id}/bindings")
def get_saved_mcp_connection_bindings(
    connection_id: str,
    namespace: str = "default",
    user=Depends(verify_token),
) -> list[dict[str, Any]]:
    ensure_namespace_access(user, namespace)
    if get_mcp_connection(namespace, connection_id) is None:
        raise HTTPException(status_code=404, detail=f"MCP connection '{connection_id}' was not found.")
    bindings = _list_mcp_connection_bindings(namespace).get(connection_id, [])
    return sorted(bindings, key=lambda item: (item.get("namespace", ""), item.get("agent_name", "")))


@app.delete("/api/mcp/connections/{connection_id}", response_model=DeleteResponse)
def delete_saved_mcp_connection(
    connection_id: str,
    namespace: str = "default",
    user=Depends(verify_token),
) -> DeleteResponse:
    ensure_namespace_access(user, namespace, "operator")
    record = get_mcp_connection(namespace, connection_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"MCP connection '{connection_id}' was not found.")
    bindings = _list_mcp_connection_bindings(namespace).get(connection_id, [])
    if bindings:
        bound_agents = ", ".join(sorted({str(item.get("agent_name") or "") for item in bindings if item.get("agent_name")}))
        raise HTTPException(
            status_code=409,
            detail=(
                f"MCP connection '{record['name']}' is still bound to {len(bindings)} agent(s): {bound_agents or 'unknown'}"
            ),
        )

    _delete_mcp_connection_secret(namespace, record.get("secret_name"))
    delete_mcp_connection(namespace, connection_id)
    return DeleteResponse(status="deleted", kind="mcp_connection", name=record["name"], namespace=namespace)


@app.get("/api/namespaces")
async def list_namespaces(user=Depends(verify_token)):
    """Return Kubernetes namespaces the caller is permitted to access."""
    ensure_role(user, "viewer")
    allowed = user.get("allowed_namespaces") or []
    try:
        from kubernetes import client

        ns_list = client.CoreV1Api().list_namespace()
        all_ns = sorted(ns.metadata.name for ns in ns_list.items if ns.metadata and ns.metadata.name)
    except Exception as exc:
        logger.warning("Could not list K8s namespaces: %s", exc)
        # Fall back to what the user's token says they can access
        if "*" in allowed:
            return {"namespaces": ["default"]}
        return {"namespaces": sorted(set(allowed)) if allowed else ["default"]}

    if "*" in allowed:
        return {"namespaces": all_ns}
    return {"namespaces": [ns for ns in all_ns if ns in allowed]}


@app.get("/api/health")
def health() -> dict[str, Any]:
    if _SHUTDOWN.is_set():
        return {"status": "shutting-down", "gateway": "kubesynth"}
    return {
        "status": "healthy",
        "gateway": "kubesynth",
        "auth_mode": AUTH_MODE,
        "browser_auth_enabled": browser_auth_enabled(),
        "local_auth_enabled": local_access_enabled(),
        "shared_token_enabled": shared_token_enabled(),
        "nats_url": NATS_URL,
        "qdrant_url": QDRANT_URL,
    }


@app.get("/api/ready")
def ready(response: Response) -> dict[str, Any]:
    if _SHUTDOWN.is_set():
        response.status_code = 503
        return {"status": "shutting-down", "gateway": "kubesynth"}
    checks: dict[str, str] = {}
    try:
        from sqlalchemy import text as _sa_text

        from auth_store import ENGINE

        with ENGINE.connect() as conn:
            conn.execute(_sa_text("select 1"))
        checks["database"] = "ok"
    except Exception:
        checks["database"] = "error"
    all_ok = all(v == "ok" for v in checks.values())
    if not all_ok:
        response.status_code = 503
    return {"status": "ready" if all_ok else "degraded", "gateway": "kubesynth", "checks": checks}


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
        ensure_namespace_access(user, resolved_namespace)
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
    ensure_namespace_access(user, namespace)
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
    ensure_namespace_access(user, namespace)
    return sorted(
        [policy_info_from_resource(policy) for policy in get_policies(namespace)],
        key=lambda item: item.name,
    )


class PolicyRequest(BaseModel):
    name: str = Field(min_length=1, max_length=253, pattern=r"^[a-z0-9][a-z0-9\-]*[a-z0-9]$")
    input_guardrails: dict[str, Any] = Field(default_factory=dict)
    output_guardrails: dict[str, Any] = Field(default_factory=dict)
    allowed_models: list[str] = Field(default_factory=list)
    allowed_mcp_servers: list[str] = Field(default_factory=list)
    mcp_require_hitl: bool = True
    tool_policy: dict[str, Any] = Field(default_factory=dict)
    memory_policy: dict[str, Any] = Field(default_factory=dict)


class PolicyUpdateRequest(BaseModel):
    input_guardrails: dict[str, Any] | None = None
    output_guardrails: dict[str, Any] | None = None
    allowed_models: list[str] | None = None
    allowed_mcp_servers: list[str] | None = None
    mcp_require_hitl: bool | None = None
    tool_policy: dict[str, Any] | None = None
    memory_policy: dict[str, Any] | None = None


def build_policy_spec(
    body: PolicyRequest | PolicyUpdateRequest, existing_spec: dict[str, Any] | None = None
) -> dict[str, Any]:
    spec: dict[str, Any] = dict(existing_spec) if existing_spec else {}
    if isinstance(body, PolicyRequest) or body.input_guardrails is not None:
        ig = body.input_guardrails or {}
        spec["inputGuardrails"] = {
            "blockPromptInjection": ig.get("block_prompt_injection", ig.get("blockPromptInjection", False)),
            "blockedPatterns": ig.get("blocked_patterns", ig.get("blockedPatterns", [])),
            "maxInputTokens": ig.get("max_input_tokens", ig.get("maxInputTokens", 4096)),
        }
    if isinstance(body, PolicyRequest) or body.output_guardrails is not None:
        og = body.output_guardrails or {}
        spec["outputGuardrails"] = {
            "maskPII": og.get("mask_pii", og.get("maskPII", False)),
            "blockedOutputPatterns": og.get("blocked_output_patterns", og.get("blockedOutputPatterns", [])),
            "maxOutputTokens": og.get("max_output_tokens", og.get("maxOutputTokens", 4096)),
        }
    if isinstance(body, PolicyRequest) or body.allowed_models is not None:
        spec["allowedModels"] = body.allowed_models or []
    if isinstance(body, PolicyRequest) or body.allowed_mcp_servers is not None:
        spec["allowedMcpServers"] = body.allowed_mcp_servers or []
    if isinstance(body, PolicyRequest) or body.mcp_require_hitl is not None:
        spec["mcpRequireHitl"] = body.mcp_require_hitl if body.mcp_require_hitl is not None else True
    if isinstance(body, PolicyRequest) or body.tool_policy is not None:
        spec["toolPolicy"] = body.tool_policy or {}
    if isinstance(body, PolicyRequest) or body.memory_policy is not None:
        spec["memoryPolicy"] = body.memory_policy or {}
    return spec


@app.post("/api/policies", response_model=PolicyInfo, status_code=201)
def create_policy(
    body: PolicyRequest,
    namespace: str = "default",
    user=Depends(verify_token),
):
    ensure_namespace_access(user, namespace, "operator")
    spec = build_policy_spec(body)
    created = create_custom_resource("agentpolicies", namespace, body.name, spec)
    return policy_info_from_resource(created)


@app.get("/api/policies/{policy_name}", response_model=PolicyInfo)
def get_policy(policy_name: str, namespace: str = "default", user=Depends(verify_token)):
    ensure_namespace_access(user, namespace)
    resource = read_custom_resource("agentpolicies", policy_name, namespace, "Policy")
    return policy_info_from_resource(resource)


@app.patch("/api/policies/{policy_name}", response_model=PolicyInfo)
def update_policy(
    policy_name: str,
    body: PolicyUpdateRequest,
    namespace: str = "default",
    user=Depends(verify_token),
):
    ensure_namespace_access(user, namespace, "operator")
    existing = read_custom_resource("agentpolicies", policy_name, namespace, "Policy")
    existing_spec = existing.get("spec", {})
    updated_spec = build_policy_spec(body, existing_spec)
    try:
        from kubernetes import client

        updated = client.CustomObjectsApi().patch_namespaced_custom_object(
            group=RESOURCE_GROUP,
            version=RESOURCE_VERSION,
            namespace=namespace,
            plural="agentpolicies",
            name=policy_name,
            body={"spec": updated_spec},
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Failed to update policy") from exc
    return policy_info_from_resource(updated)


@app.delete("/api/policies/{policy_name}", response_model=DeleteResponse)
def delete_policy(
    policy_name: str,
    namespace: str = "default",
    user=Depends(verify_token),
):
    ensure_namespace_access(user, namespace, "operator")
    delete_custom_resource("agentpolicies", policy_name, namespace, "Policy")
    return DeleteResponse(status="deleted", kind="policy", name=policy_name, namespace=namespace)


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
    ensure_namespace_access(user, namespace, "operator")
    approval = read_approval(approval_name, namespace)
    spec = approval.get("spec", {})

    decided_by = str(user.get("sub", "unknown"))
    decided_at = datetime.now(UTC).isoformat()

    try:
        from kubernetes import client

        client.CustomObjectsApi().patch_namespaced_custom_object_status(
            group="kubesynth.ai",
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
            detail="Failed to record approval decision",
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
    ensure_namespace_access(user, namespace)
    return sorted([agent_info_from_resource(agent) for agent in get_agents(namespace)], key=lambda item: item.name)


@app.post("/api/agents", response_model=AgentDetail, status_code=201)
def create_agent(
    body: CreateAgentRequest,
    namespace: str = "default",
    user=Depends(verify_token),
):
    ensure_namespace_access(user, namespace, "operator")
    agent = create_agent_resource(body, namespace)
    return agent_detail_from_resource(agent)


@app.get("/api/agents/{agent_name}", response_model=AgentDetail)
def get_agent(
    agent_name: str,
    namespace: str = "default",
    user=Depends(verify_token),
):
    ensure_namespace_access(user, namespace)
    return agent_detail_from_resource(read_agent(agent_name, namespace))


@app.get("/api/agents/{agent_name}/discover", response_model=AgentDiscoveryResponse)
def discover_agent_targets(
    agent_name: str,
    namespace: str = "default",
    user=Depends(verify_token),
):
    ensure_namespace_access(user, namespace)
    return discover_agent_peers(agent_name, namespace)


@app.patch("/api/agents/{agent_name}", response_model=AgentDetail)
def update_agent(
    agent_name: str,
    body: UpdateAgentRequest,
    namespace: str = "default",
    user=Depends(verify_token),
):
    ensure_namespace_access(user, namespace, "operator")
    current_agent = read_agent(agent_name, namespace)
    next_spec = build_agent_spec(body, current_agent.get("spec", {}), namespace=namespace)
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
    ensure_namespace_access(user, namespace, "operator")
    delete_custom_resource("aiagents", agent_name, namespace, "Agent")
    return DeleteResponse(status="deleted", kind="agent", name=agent_name, namespace=namespace)


@app.post("/api/agents/{agent_name}/clone", response_model=AgentDetail, status_code=201)
def clone_agent(
    agent_name: str,
    namespace: str = "default",
    new_name: str | None = None,
    user=Depends(verify_token),
):
    """Clone an existing agent CRD into a new resource."""
    ensure_namespace_access(user, namespace, "operator")
    source = read_agent(agent_name, namespace)

    # Determine clone name
    clone_name = new_name or f"{agent_name}-copy"
    # Sanitize to DNS-1123 label (max 63 chars, lowercase alphanumeric and hyphens)
    import re as _re

    clone_name = _re.sub(r"[^a-z0-9-]", "-", clone_name.lower()).strip("-")[:63]

    spec = dict(source.get("spec", {}))

    try:
        from kubernetes import client

        resource_body: dict[str, Any] = {
            "apiVersion": f"{RESOURCE_GROUP}/{RESOURCE_VERSION}",
            "kind": "AIAgent",
            "metadata": {
                "name": clone_name,
                "namespace": namespace,
                "labels": {"cloned-from": agent_name},
            },
            "spec": spec,
        }

        created = client.CustomObjectsApi().create_namespaced_custom_object(
            group=RESOURCE_GROUP,
            version=RESOURCE_VERSION,
            namespace=namespace,
            plural="aiagents",
            body=resource_body,
        )
        invalidate_agent_read_cache(agent_name=clone_name, namespace=namespace)
        return agent_detail_from_resource(created)
    except Exception as exc:
        if getattr(exc, "status", None) == 409:
            raise HTTPException(status_code=409, detail=f"Agent '{clone_name}' already exists") from exc
        logger.error("Failed to clone agent %s → %s: %s", agent_name, clone_name, exc)
        raise HTTPException(status_code=502, detail=f"Failed to clone agent: {exc}") from exc


# ---- Git credential management ----


def _git_secret_name(agent_name: str) -> str:
    return f"{agent_name}-git-credentials"


def _github_secret_name(agent_name: str) -> str:
    return f"{agent_name}-github-credentials"


@app.post("/api/agents/{agent_name}/git-credentials", status_code=201)
def create_git_credentials(
    agent_name: str,
    body: GitCredentialRequest,
    namespace: str = "default",
    user=Depends(verify_token),
):
    """Create a K8s Secret with git credentials for an agent."""
    ensure_namespace_access(user, namespace, "operator")
    from kubernetes import client
    from kubernetes.client.rest import ApiException

    secret_name = _git_secret_name(agent_name)
    string_data: dict[str, str] = {"auth_method": body.auth_method}
    if body.auth_method == "token":
        string_data["token"] = body.token or ""
    elif body.auth_method == "basic":
        string_data["username"] = body.username or ""
        string_data["password"] = body.password or ""
    elif body.auth_method == "ssh":
        string_data["ssh_private_key"] = body.ssh_private_key or ""

    secret = client.V1Secret(
        metadata=client.V1ObjectMeta(
            name=secret_name,
            namespace=namespace,
            labels={"app.kubernetes.io/managed-by": "kubesynth", "agent": agent_name},
        ),
        type="Opaque",
        string_data=string_data,
    )
    try:
        client.CoreV1Api().create_namespaced_secret(namespace=namespace, body=secret)
    except ApiException as e:
        if e.status == 409:
            client.CoreV1Api().replace_namespaced_secret(name=secret_name, namespace=namespace, body=secret)
        else:
            raise HTTPException(status_code=502, detail=f"Failed to create git credential secret: {e}") from e
    return {"status": "created", "secret_name": secret_name, "auth_method": body.auth_method}


@app.get("/api/agents/{agent_name}/git-credentials")
def get_git_credentials(
    agent_name: str,
    namespace: str = "default",
    user=Depends(verify_token),
):
    """Get git credential metadata (auth method only, never exposes secrets)."""
    ensure_namespace_access(user, namespace)
    from kubernetes import client
    from kubernetes.client.rest import ApiException

    secret_name = _git_secret_name(agent_name)
    try:
        secret_result = client.CoreV1Api().read_namespaced_secret(name=secret_name, namespace=namespace)
        data: dict[str, str] = getattr(secret_result, "data", None) or {}
        # Only return auth_method, never actual credentials
        import base64

        auth_method = base64.b64decode(data.get("auth_method", "")).decode() if data.get("auth_method") else "unknown"
        return {"exists": True, "secret_name": secret_name, "auth_method": auth_method}
    except ApiException as e:
        if e.status == 404:
            return {"exists": False, "secret_name": secret_name}
        raise HTTPException(status_code=502, detail=f"Failed to read git credential secret: {e}") from e


@app.delete("/api/agents/{agent_name}/git-credentials")
def delete_git_credentials(
    agent_name: str,
    namespace: str = "default",
    user=Depends(verify_token),
):
    """Delete git credential secret for an agent."""
    ensure_namespace_access(user, namespace, "operator")
    from kubernetes import client
    from kubernetes.client.rest import ApiException

    secret_name = _git_secret_name(agent_name)
    try:
        client.CoreV1Api().delete_namespaced_secret(name=secret_name, namespace=namespace)
        return {"status": "deleted", "secret_name": secret_name}
    except ApiException as e:
        if e.status == 404:
            raise HTTPException(status_code=404, detail=f"Git credentials not found for agent '{agent_name}'") from e
        raise HTTPException(status_code=502, detail=f"Failed to delete git credential secret: {e}") from e


@app.post("/api/agents/{agent_name}/github-credentials", status_code=201)
def create_github_credentials(
    agent_name: str,
    body: GitHubCredentialRequest,
    namespace: str = "default",
    user=Depends(verify_token),
):
    """Create a K8s Secret with GitHub MCP credentials for an agent."""
    ensure_namespace_access(user, namespace, "operator")
    from kubernetes import client
    from kubernetes.client.rest import ApiException

    secret_name = _github_secret_name(agent_name)
    secret = client.V1Secret(
        metadata=client.V1ObjectMeta(
            name=secret_name,
            namespace=namespace,
            labels={"app.kubernetes.io/managed-by": "kubesynth", "agent": agent_name},
        ),
        type="Opaque",
        string_data={"token": body.token},
    )
    try:
        client.CoreV1Api().create_namespaced_secret(namespace=namespace, body=secret)
    except ApiException as e:
        if e.status == 409:
            client.CoreV1Api().replace_namespaced_secret(name=secret_name, namespace=namespace, body=secret)
        else:
            raise HTTPException(status_code=502, detail=f"Failed to create GitHub credential secret: {e}") from e
    return {"status": "created", "secret_name": secret_name}


@app.get("/api/agents/{agent_name}/github-credentials")
def get_github_credentials(
    agent_name: str,
    namespace: str = "default",
    user=Depends(verify_token),
):
    """Get GitHub credential metadata without exposing secrets."""
    ensure_namespace_access(user, namespace)
    from kubernetes import client
    from kubernetes.client.rest import ApiException

    secret_name = _github_secret_name(agent_name)
    try:
        client.CoreV1Api().read_namespaced_secret(name=secret_name, namespace=namespace)
        return {"exists": True, "secret_name": secret_name}
    except ApiException as e:
        if e.status == 404:
            return {"exists": False, "secret_name": secret_name}
        raise HTTPException(status_code=502, detail=f"Failed to read GitHub credential secret: {e}") from e


@app.delete("/api/agents/{agent_name}/github-credentials")
def delete_github_credentials(
    agent_name: str,
    namespace: str = "default",
    user=Depends(verify_token),
):
    """Delete GitHub credential secret for an agent."""
    ensure_namespace_access(user, namespace, "operator")
    from kubernetes import client
    from kubernetes.client.rest import ApiException

    secret_name = _github_secret_name(agent_name)
    try:
        client.CoreV1Api().delete_namespaced_secret(name=secret_name, namespace=namespace)
        return {"status": "deleted", "secret_name": secret_name}
    except ApiException as e:
        if e.status == 404:
            raise HTTPException(status_code=404, detail=f"GitHub credentials not found for agent '{agent_name}'") from e
        raise HTTPException(status_code=502, detail=f"Failed to delete GitHub credential secret: {e}") from e


@app.get("/api/workflows", response_model=list[WorkflowInfo])
def list_workflows(namespace: str = "default", user=Depends(verify_token)):
    ensure_namespace_access(user, namespace)
    workflows = sorted(
        [workflow_info_from_resource(item) for item in list_custom_resources("agentworkflows", namespace)],
        key=lambda item: item.name,
    )
    for wf in workflows:
        _sync_workflow_run_history(wf)
    return workflows


@app.post("/api/workflows", response_model=WorkflowInfo, status_code=201)
def create_workflow(
    body: WorkflowRequest,
    namespace: str = "default",
    user=Depends(verify_token),
):
    ensure_namespace_access(user, namespace, "operator")
    created = create_custom_resource(
        "agentworkflows",
        namespace,
        body.name,
        build_workflow_spec(body),
    )
    return workflow_info_from_resource(created)


def _sync_workflow_run_history(info: WorkflowInfo) -> None:
    """Best-effort upsert of workflow run into run history based on current K8s state.

    Called on every status fetch so that runs appear in history regardless of
    whether the workflow was triggered via the API gateway or kubectl apply.
    """
    if not info.run_id or info.phase == "pending":
        return
    try:
        summary = info.summary or {}
        started_at = None
        completed_at = None
        if isinstance(summary.get("startedAt"), str):
            with contextlib.suppress(ValueError, TypeError):
                started_at = datetime.fromisoformat(summary["startedAt"].replace("Z", "+00:00"))
        terminal = info.phase in {"completed", "failed", "cancelled"}
        if terminal and isinstance(summary.get("completedAt"), str):
            with contextlib.suppress(ValueError, TypeError):
                completed_at = datetime.fromisoformat(summary["completedAt"].replace("Z", "+00:00"))

        record_workflow_run(
            workflow_name=info.name,
            namespace=info.namespace,
            run_id=info.run_id,
            phase=info.phase,
            total_steps=summary.get("totalSteps"),
            completed_steps=summary.get("completedSteps"),
            failed_steps=summary.get("failedSteps"),
            started_at=started_at,
            completed_at=completed_at,
        )
        if info.phase in {"completed", "failed"}:
            primary_agent = info.steps[0].agent_ref if info.steps else None
            if primary_agent:
                record_workflow_outcome_memory(
                    info.namespace,
                    primary_agent,
                    info.name,
                    run_id=info.run_id,
                    phase=info.phase,
                    summary=summary,
                )
                apply_memory_feedback(
                    info.namespace,
                    primary_agent,
                    session_id=info.run_id,
                    success=(info.phase == "completed"),
                )
    except Exception as exc:
        logger.debug("Failed to sync workflow run history for %s: %s", info.name, exc)


def _sync_eval_memory(info: EvalInfo) -> None:
    if info.phase == "pending":
        return
    try:
        summary = info.summary or {}
        record_eval_outcome_memory(
            info.namespace,
            info.agent_ref,
            info.name,
            phase=info.phase,
            passed=info.passed,
            summary=summary if isinstance(summary, dict) else None,
        )
        if info.passed is not None:
            apply_memory_feedback(
                info.namespace,
                info.agent_ref,
                session_id=info.name,
                success=bool(info.passed),
            )
    except Exception as exc:
        logger.debug("Failed to sync eval memory for %s: %s", info.name, exc)


@app.get("/api/workflows/{workflow_name}", response_model=WorkflowInfo)
def get_workflow(
    workflow_name: str,
    namespace: str = "default",
    user=Depends(verify_token),
):
    ensure_namespace_access(user, namespace)
    info = workflow_info_from_resource(read_custom_resource("agentworkflows", workflow_name, namespace, "Workflow"))
    _sync_workflow_run_history(info)
    return info


@app.patch("/api/workflows/{workflow_name}", response_model=WorkflowInfo)
def update_workflow(
    workflow_name: str,
    body: WorkflowUpdateRequest,
    namespace: str = "default",
    user=Depends(verify_token),
):
    ensure_namespace_access(user, namespace, "operator")
    updated = replace_custom_resource_spec("agentworkflows", workflow_name, namespace, build_workflow_spec(body))
    return workflow_info_from_resource(updated)


@app.delete("/api/workflows/{workflow_name}", response_model=DeleteResponse)
def delete_workflow(
    workflow_name: str,
    namespace: str = "default",
    user=Depends(verify_token),
):
    ensure_namespace_access(user, namespace, "operator")
    delete_custom_resource("agentworkflows", workflow_name, namespace, "Workflow")
    return DeleteResponse(status="deleted", kind="workflow", name=workflow_name, namespace=namespace)


class WorkflowTriggerRequest(BaseModel):
    input: str = Field(default="", max_length=4000)
    factory_mode: str | None = Field(default=None, max_length=32)

    @model_validator(mode="after")
    def normalize_fields(self) -> "WorkflowTriggerRequest":
        self.input = self.input.strip()
        self.factory_mode = normalize_factory_mode(self.factory_mode)
        return self


@app.post("/api/workflows/{workflow_name}/trigger", response_model=WorkflowInfo)
def trigger_workflow(
    workflow_name: str,
    body: WorkflowTriggerRequest | None = None,
    namespace: str = "default",
    user=Depends(verify_token),
):
    """Trigger a workflow run by updating only spec.input, preserving all other spec fields.

    This bumps the resource generation, which causes the operator to re-reconcile.
    """
    ensure_namespace_access(user, namespace, "operator")
    try:
        from kubernetes import client

        api = client.CustomObjectsApi()
        current = cast(
            dict[str, Any],
            api.get_namespaced_custom_object(
                group=RESOURCE_GROUP,
                version=RESOURCE_VERSION,
                namespace=namespace,
                plural="agentworkflows",
                name=workflow_name,
            ),
        )
    except Exception as exc:
        status = getattr(exc, "status", None)
        if status == 404:
            raise HTTPException(status_code=404, detail=f"Workflow '{workflow_name}' not found") from exc
        raise HTTPException(status_code=502, detail=f"Failed to read workflow: {exc}") from exc

    existing_spec = current.get("spec", {}) or {}
    if body and body.factory_mode and not is_factory_workflow_resource(workflow_name, existing_spec):
        raise HTTPException(status_code=400, detail="factory_mode is only supported for the KubeSynth factory workflow.")

    existing_input = str(existing_spec.get("input", "") or "")
    _, unwrapped_existing_request = unwrap_factory_workflow_input(existing_input)
    base_input = body.input if body and body.input else (unwrapped_existing_request or existing_input)
    if body and body.factory_mode:
        new_input = build_factory_workflow_input(base_input, body.factory_mode)
    else:
        new_input = base_input
    updated_spec = {**existing_spec, "input": new_input}

    try:
        from kubernetes import client as k8s_client

        updated = cast(
            dict[str, Any],
            k8s_client.CustomObjectsApi().replace_namespaced_custom_object(
                group=RESOURCE_GROUP,
                version=RESOURCE_VERSION,
                namespace=namespace,
                plural="agentworkflows",
                name=workflow_name,
                body={
                    "apiVersion": f"{RESOURCE_GROUP}/{RESOURCE_VERSION}",
                    "kind": RESOURCE_KIND_BY_PLURAL["agentworkflows"],
                    "metadata": {
                        "name": workflow_name,
                        "namespace": namespace,
                        "resourceVersion": current.get("metadata", {}).get("resourceVersion"),
                    },
                    "spec": updated_spec,
                },
            ),
        )
    except Exception as exc:
        status = getattr(exc, "status", None)
        if status == 409:
            raise HTTPException(status_code=409, detail="Workflow was modified concurrently. Retry.") from exc
        logger.error("Failed to trigger workflow: %s", exc)
        raise HTTPException(status_code=502, detail="Failed to trigger workflow") from exc

    # Reset status so the operator re-reconciles even when the spec
    # (and therefore metadata.generation) did not change.
    try:
        from kubernetes import client as k8s_reset

        k8s_reset.CustomObjectsApi().patch_namespaced_custom_object_status(
            group=RESOURCE_GROUP,
            version=RESOURCE_VERSION,
            namespace=namespace,
            plural="agentworkflows",
            name=workflow_name,
            body={
                "status": {
                    "phase": "pending",
                    "observedGeneration": None,
                    "pendingApproval": None,
                }
            },
        )
        # Re-read to return the freshest state
        updated = cast(
            dict[str, Any],
            k8s_client.CustomObjectsApi().get_namespaced_custom_object(
                group=RESOURCE_GROUP,
                version=RESOURCE_VERSION,
                namespace=namespace,
                plural="agentworkflows",
                name=workflow_name,
            ),
        )
    except Exception:
        logger.warning("Workflow status reset failed after spec replace (best-effort)", exc_info=True)

    result = workflow_info_from_resource(updated)

    # Record in run history
    try:
        record_workflow_run(
            workflow_name=workflow_name,
            namespace=namespace,
            run_id=result.run_id,
            phase=result.phase,
            total_steps=result.summary.get("totalSteps") if isinstance(result.summary, dict) else None,
            triggered_by=str(user.get("sub", "unknown")),
            input_text=new_input[:2000] if new_input else None,
        )
    except Exception as exc:
        logger.warning("Failed to record workflow run history: %s", exc)

    return result


@app.post("/api/workflows/{workflow_name}/retry-failed", response_model=WorkflowInfo)
def retry_failed_workflow_steps(
    workflow_name: str,
    namespace: str = "default",
    user=Depends(verify_token),
):
    """Retry only the failed steps of a workflow.

    Resets failed step states back to 'pending' while preserving completed
    steps, preserves the current artifact generation, and assigns a fresh
    runId so session-aware runtimes perform a new failed-step attempt.
    """
    ensure_namespace_access(user, namespace, "operator")
    try:
        from kubernetes import client

        api = client.CustomObjectsApi()
        current = cast(
            dict[str, Any],
            api.get_namespaced_custom_object(
                group=RESOURCE_GROUP,
                version=RESOURCE_VERSION,
                namespace=namespace,
                plural="agentworkflows",
                name=workflow_name,
            ),
        )
    except Exception as exc:
        status_code = getattr(exc, "status", None)
        if status_code == 404:
            raise HTTPException(status_code=404, detail=f"Workflow '{workflow_name}' not found") from exc
        raise HTTPException(status_code=502, detail=f"Failed to read workflow: {exc}") from exc

    current_status = current.get("status") or {}
    current_phase = str(current_status.get("phase", "pending") or "pending")
    if current_phase != "failed":
        raise HTTPException(
            status_code=409,
            detail=f"Workflow is in '{current_phase}' phase. Only failed workflows can retry failed steps.",
        )

    step_states = current_status.get("stepStates") or {}
    failed_step_names: list[str] = []
    patched_step_states: dict[str, Any] = {}
    for step_name, state in step_states.items():
        if not isinstance(state, dict):
            patched_step_states[step_name] = state
            continue
        step_status = str(state.get("status", "") or "")
        if step_status == "failed":
            failed_step_names.append(step_name)
            patched_step_states[step_name] = {
                "status": "pending",
                "error": None,
                "failureClass": None,
                "startedAt": None,
                "completedAt": None,
                "iterationFailures": None,
            }
        else:
            patched_step_states[step_name] = state

    if not failed_step_names:
        raise HTTPException(status_code=409, detail="No failed steps found to retry.")

    current_generation = int((current.get("metadata") or {}).get("generation") or 1)
    retry_run_id = build_retry_workflow_run_id(namespace, workflow_name, current_generation)

    # Patch status only. Keeping the current generation preserves the existing
    # artifact path so dependent downstream steps can still read the completed
    # step outputs they rely on. A fresh runId forces session-aware runtimes
    # such as OpenCode to use a new thread instead of replaying the previous
    # failed step session.
    try:
        from kubernetes import client as k8s_client

        k8s_client.CustomObjectsApi().patch_namespaced_custom_object_status(
            group=RESOURCE_GROUP,
            version=RESOURCE_VERSION,
            namespace=namespace,
            plural="agentworkflows",
            name=workflow_name,
            body={
                "status": {
                    "phase": "pending",
                    "runId": retry_run_id,
                    "observedGeneration": None,
                    "pendingApproval": None,
                    "stepStates": patched_step_states,
                    "workerJob": None,
                    "summary": {
                        **(current_status.get("summary") or {}),
                        "runId": retry_run_id,
                        "failedSteps": 0,
                        "waitingApprovalSteps": 0,
                        "error": None,
                        "updatedAt": now_iso(),
                    },
                }
            },
        )
    except Exception as exc:
        logger.error("Failed to patch workflow status for retry-failed: %s", exc)
        raise HTTPException(status_code=502, detail="Failed to reset failed steps") from exc

    # Re-read and return freshest state.
    try:
        updated = cast(
            dict[str, Any],
            api.get_namespaced_custom_object(
                group=RESOURCE_GROUP,
                version=RESOURCE_VERSION,
                namespace=namespace,
                plural="agentworkflows",
                name=workflow_name,
            ),
        )
    except Exception:
        current["status"] = {
            **current_status,
            "phase": "pending",
            "runId": retry_run_id,
            "observedGeneration": None,
            "pendingApproval": None,
            "workerJob": None,
            "stepStates": patched_step_states,
            "summary": {
                **(current_status.get("summary") or {}),
                "runId": retry_run_id,
                "failedSteps": 0,
                "waitingApprovalSteps": 0,
                "error": None,
                "updatedAt": now_iso(),
            },
        }
        return workflow_info_from_resource(current)

    result = workflow_info_from_resource(updated)

    try:
        record_workflow_run(
            workflow_name=workflow_name,
            namespace=namespace,
            run_id=result.run_id,
            phase=result.phase,
            total_steps=result.summary.get("totalSteps") if isinstance(result.summary, dict) else None,
            triggered_by=str(user.get("sub", "unknown")),
        )
    except Exception as exc:
        logger.warning("Failed to record workflow retry-failed run history: %s", exc)

    logger.info(
        "Retrying failed steps %s for workflow '%s/%s'",
        failed_step_names,
        namespace,
        workflow_name,
    )
    return result


@app.post("/api/workflows/{workflow_name}/cancel", response_model=WorkflowInfo)
def cancel_workflow(
    workflow_name: str,
    namespace: str = "default",
    user=Depends(verify_token),
):
    """Cancel a running, queued, or waiting-approval workflow by patching its status phase."""
    ensure_namespace_access(user, namespace, "operator")
    try:
        from kubernetes import client

        api = client.CustomObjectsApi()
        current = cast(
            dict[str, Any],
            api.get_namespaced_custom_object(
                group=RESOURCE_GROUP,
                version=RESOURCE_VERSION,
                namespace=namespace,
                plural="agentworkflows",
                name=workflow_name,
            ),
        )
    except Exception as exc:
        status_code = getattr(exc, "status", None)
        if status_code == 404:
            raise HTTPException(status_code=404, detail=f"Workflow '{workflow_name}' not found") from exc
        logger.error("Failed to read workflow %s for cancel: %s", workflow_name, exc)
        raise HTTPException(status_code=502, detail="Failed to read workflow") from exc

    current_phase = (current.get("status") or {}).get("phase", "pending")
    if current_phase not in ("queued", "running", "waiting-approval"):
        raise HTTPException(
            status_code=409,
            detail=f"Workflow is in '{current_phase}' phase and cannot be cancelled",
        )

    try:
        from kubernetes import client as k8s_client

        k8s_client.CustomObjectsApi().patch_namespaced_custom_object_status(
            group=RESOURCE_GROUP,
            version=RESOURCE_VERSION,
            namespace=namespace,
            plural="agentworkflows",
            name=workflow_name,
            body={
                "status": {
                    "phase": "cancelled",
                    "pendingApproval": None,
                }
            },
        )
    except Exception as exc:
        logger.error("Failed to cancel workflow: %s", exc)
        raise HTTPException(status_code=502, detail="Failed to cancel workflow") from exc

    try:
        updated = cast(
            dict[str, Any],
            api.get_namespaced_custom_object(
                group=RESOURCE_GROUP,
                version=RESOURCE_VERSION,
                namespace=namespace,
                plural="agentworkflows",
                name=workflow_name,
            ),
        )
    except Exception:
        # Status was already patched successfully — return a minimal response
        # rather than failing the entire cancel operation.
        current["status"] = {**(current.get("status") or {}), "phase": "cancelled", "pendingApproval": None}
        return workflow_info_from_resource(current)
    return workflow_info_from_resource(updated)


@app.get("/api/workflows/{workflow_name}/status/stream")
def stream_workflow_status(
    workflow_name: str,
    namespace: str = "default",
    user=Depends(verify_token),
):
    """SSE stream that pushes workflow status updates until the workflow reaches a terminal phase."""
    ensure_namespace_access(user, namespace)
    import asyncio

    async def event_generator():
        terminal_phases = {"completed", "failed", "cancelled"}
        prev_hash = ""
        try:
            while True:
                try:
                    from kubernetes import client as k8s_client

                    resource = cast(
                        dict[str, Any],
                        k8s_client.CustomObjectsApi().get_namespaced_custom_object(
                            group=RESOURCE_GROUP,
                            version=RESOURCE_VERSION,
                            namespace=namespace,
                            plural="agentworkflows",
                            name=workflow_name,
                        ),
                    )
                    info = workflow_info_from_resource(resource)
                    _sync_workflow_run_history(info)
                    info_dict = info.model_dump(mode="json")
                    current_hash = json.dumps(info_dict, sort_keys=True, default=str)
                    if current_hash != prev_hash:
                        prev_hash = current_hash
                        yield sse_event("status", info_dict)
                    if info.phase in terminal_phases:
                        yield sse_event("done", {"phase": info.phase})
                        return
                except Exception as exc:
                    yield sse_event("error", {"error": str(exc)})
                    return
                await asyncio.sleep(2)
        except asyncio.CancelledError:
            return

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/workflows/{workflow_name}/runs")
def get_workflow_runs(
    workflow_name: str,
    namespace: str = "default",
    limit: int = 20,
    user=Depends(verify_token),
):
    """Return the recent run history for a workflow."""
    ensure_namespace_access(user, namespace)
    return list_workflow_runs(workflow_name, namespace, limit=limit)


@app.get("/api/workflows/{workflow_name}/runs/{run_id}/trace")
def get_workflow_run_trace_endpoint(
    workflow_name: str,
    run_id: str,
    namespace: str = "default",
    tail: int = 4000,
    user=Depends(verify_token),
):
    ensure_namespace_access(user, namespace)
    tail = max(1, min(tail, 20000))
    return _resolve_workflow_run_trace_payload(
        workflow_name,
        namespace,
        run_id,
        tail=tail,
        persist_live_fallback=True,
    )


@app.get("/api/workflows/{workflow_name}/runs/{run_id}/export")
def export_workflow_run_trace(
    workflow_name: str,
    run_id: str,
    namespace: str = "default",
    user=Depends(verify_token),
):
    ensure_namespace_access(user, namespace)
    payload = _resolve_workflow_run_trace_payload(
        workflow_name,
        namespace,
        run_id,
        tail=None,
        persist_live_fallback=True,
    )
    response = JSONResponse(payload)
    response.headers["Content-Disposition"] = f'attachment; filename="{workflow_name}-{run_id}-trace.json"'
    return response


@app.get("/api/workflows/{workflow_name}/logs")
def get_workflow_logs(
    workflow_name: str,
    namespace: str = "default",
    tail: int = 200,
    user=Depends(verify_token),
):
    ensure_namespace_access(user, namespace)
    tail = max(1, min(tail, 5000))
    resource = read_custom_resource("agentworkflows", workflow_name, namespace, "Workflow")
    status = (resource.get("status") or {}) if isinstance(resource, dict) else {}
    run_id = str(status.get("runId") or "") or None
    worker_job = status.get("workerJob") or {}
    job_name = str(worker_job.get("name") or "")
    job_namespace = str(worker_job.get("namespace") or namespace)
    if not job_name:
        archived_logs = _fallback_workflow_logs_from_run(workflow_name, namespace, run_id, tail=tail)
        if archived_logs is not None:
            return archived_logs
        raise HTTPException(status_code=404, detail=f"No worker job found for workflow '{workflow_name}'")

    try:
        logs, pod_name = _read_workflow_job_logs(job_name, job_namespace, tail)
        return {
            "workflow_name": workflow_name,
            "run_id": run_id,
            "job_name": job_name,
            "pod_name": pod_name,
            "source": "live-worker",
            "archived_log_available": False,
            "logs": logs,
        }
    except HTTPException:
        archived_logs = _fallback_workflow_logs_from_run(workflow_name, namespace, run_id, tail=tail)
        if archived_logs is not None:
            return archived_logs
        raise
    except Exception as exc:
        logger.warning("Could not retrieve workflow logs for %s: %s", workflow_name, exc)
        archived_logs = _fallback_workflow_logs_from_run(workflow_name, namespace, run_id, tail=tail)
        if archived_logs is not None:
            return archived_logs
        raise HTTPException(status_code=404, detail="Could not retrieve workflow logs") from exc


@app.get("/api/workflows/{workflow_name}/logs/stream")
async def stream_workflow_logs(
    workflow_name: str,
    request: Request,
    namespace: str = "default",
    tail: int = 50,
    user=Depends(verify_token),
):
    ensure_namespace_access(user, namespace)
    tail = max(1, min(tail, 5000))
    resource = read_custom_resource("agentworkflows", workflow_name, namespace, "Workflow")
    status = (resource.get("status") or {}) if isinstance(resource, dict) else {}
    worker_job = status.get("workerJob") or {}
    job_name = str(worker_job.get("name") or "")
    job_namespace = str(worker_job.get("namespace") or namespace)
    if not job_name:
        raise HTTPException(status_code=404, detail=f"No worker job found for workflow '{workflow_name}'")

    pods = list_job_pods(job_name, job_namespace)
    if not pods:
        raise HTTPException(status_code=404, detail=f"No worker pod found for workflow '{workflow_name}'")

    pod_name = str(getattr(pods[0].metadata, "name", "") or "")
    if not pod_name:
        raise HTTPException(status_code=404, detail=f"No worker pod found for workflow '{workflow_name}'")

    async def log_event_generator():
        import time

        from kubernetes import client as k8s_client
        from kubernetes import watch as k8s_watch

        yield sse_event("log.started", {"workflow_name": workflow_name, "job_name": job_name, "pod_name": pod_name})

        w = k8s_watch.Watch()
        try:
            log_stream = w.stream(
                k8s_client.CoreV1Api().read_namespaced_pod_log,
                name=pod_name,
                namespace=job_namespace,
                container="worker",
                follow=True,
                tail_lines=tail,
                timestamps=True,
                _request_timeout=0,
            )
            last_event_time = time.monotonic()
            for line in log_stream:
                if await request.is_disconnected():
                    break
                yield sse_event("log.line", {"line": line})
                last_event_time = time.monotonic()
                await asyncio.sleep(0)
                if time.monotonic() - last_event_time > STREAM_KEEPALIVE_SECONDS:
                    yield sse_keepalive_comment()
                    last_event_time = time.monotonic()
        except Exception as exc:
            yield sse_event("log.error", {"error": str(exc)})
        finally:
            w.stop()
            yield sse_event("log.stopped", {"workflow_name": workflow_name, "job_name": job_name})

    return StreamingResponse(log_event_generator(), media_type="text/event-stream")


@app.get("/api/workflows/{workflow_name}/next-action")
def get_workflow_next_action(
    workflow_name: str,
    namespace: str = "default",
    user=Depends(verify_token),
):
    """Return a suggested next action based on the workflow's current state."""
    ensure_namespace_access(user, namespace)
    try:
        resource = read_custom_resource("agentworkflows", workflow_name, namespace, "Workflow")
    except Exception:
        return {"action": "Create a workflow", "reason": "Workflow not found."}

    status = (resource.get("status") or {}) if isinstance(resource, dict) else {}
    phase = str(status.get("phase", "") or "").strip()
    step_states = status.get("stepStates") or {}

    # Determine failed steps
    failed_steps = [
        name
        for name, state in step_states.items()
        if isinstance(state, dict) and str(state.get("status", "")).strip() == "failed"
    ]
    # Determine review results
    rejected_reviews = [
        name
        for name, state in step_states.items()
        if isinstance(state, dict)
        and isinstance(state.get("reviewResult"), dict)
        and not state["reviewResult"].get("approved", True)
    ]
    # Determine verification failures
    verify_failures = [
        name
        for name, state in step_states.items()
        if isinstance(state, dict)
        and isinstance(state.get("verificationResult"), dict)
        and not state["verificationResult"].get("passed", True)
    ]

    if phase == "failed":
        if failed_steps:
            return {
                "action": "Retry failed steps",
                "reason": f"Workflow failed at step(s): {', '.join(failed_steps)}. Use retry-failed to re-run only the failed steps while preserving completed work.",
                "failedSteps": failed_steps,
                "retryAvailable": True,
            }
        return {"action": "Inspect workflow failure and retry", "reason": "Workflow is in failed state."}

    if phase == "waiting-approval":
        pending = status.get("pendingApproval") or {}
        step_name = pending.get("stepName", "unknown")
        return {
            "action": f"Approve or reject step '{step_name}'",
            "reason": "Workflow is waiting for human approval.",
        }

    if phase == "completed":
        if rejected_reviews:
            return {
                "action": f"Address review findings in step(s): {', '.join(rejected_reviews)}",
                "reason": "One or more review steps were rejected.",
                "rejectedReviews": rejected_reviews,
            }
        if verify_failures:
            return {
                "action": f"Fix verification failures in step(s): {', '.join(verify_failures)}",
                "reason": "One or more steps failed verification.",
                "verifyFailures": verify_failures,
            }
        # Check if there's a matching eval
        try:
            evals = list_custom_resources("agentevals", namespace)
            matching_evals = [
                e
                for e in evals
                if isinstance(e, dict) and str((e.get("spec") or {}).get("workflowRef", "")) == workflow_name
            ]
            if not matching_evals:
                return {"action": "Run evaluation", "reason": "Workflow completed successfully but has no evaluation."}
            # Check eval status
            for ev in matching_evals:
                ev_status = ev.get("status") or {}
                ev_phase = str(ev_status.get("phase", "")).strip()
                if ev_phase == "failed":
                    return {
                        "action": "Check failing eval test cases",
                        "reason": f"Eval '{ev.get('metadata', {}).get('name', '')}' has failures.",
                    }
        except Exception:
            logger.warning("Eval status check failed (best-effort)", exc_info=True)
        return {"action": "Deploy or promote", "reason": "All steps completed and verified successfully."}

    if phase == "running":
        current = str(status.get("currentStep", "") or "")
        return {"action": "Wait for completion", "reason": f"Workflow is running (current: {current})."}

    return {"action": "Trigger workflow", "reason": "Workflow has not been started."}


@app.get("/api/evals", response_model=list[EvalInfo])
def list_evals(namespace: str = "default", user=Depends(verify_token)):
    ensure_namespace_access(user, namespace)
    evals = sorted(
        [eval_info_from_resource(item) for item in list_custom_resources("agentevals", namespace)],
        key=lambda item: item.name,
    )
    for item in evals:
        _sync_eval_memory(item)
    return evals


@app.post("/api/evals", response_model=EvalInfo, status_code=201)
def create_eval(
    body: EvalRequest,
    namespace: str = "default",
    user=Depends(verify_token),
):
    ensure_namespace_access(user, namespace, "operator")
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
    ensure_namespace_access(user, namespace)
    info = eval_info_from_resource(read_custom_resource("agentevals", eval_name, namespace, "Eval"))
    _sync_eval_memory(info)
    return info


@app.patch("/api/evals/{eval_name}", response_model=EvalInfo)
def update_eval(
    eval_name: str,
    body: EvalUpdateRequest,
    namespace: str = "default",
    user=Depends(verify_token),
):
    ensure_namespace_access(user, namespace, "operator")
    updated = replace_custom_resource_spec("agentevals", eval_name, namespace, build_eval_spec(body))
    return eval_info_from_resource(updated)


@app.delete("/api/evals/{eval_name}", response_model=DeleteResponse)
def delete_eval(
    eval_name: str,
    namespace: str = "default",
    user=Depends(verify_token),
):
    ensure_namespace_access(user, namespace, "operator")
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
    invoke_started_at = time.perf_counter()

    def _log_invoke_step(step: str) -> None:
        logger.info(
            "Invoke step agent=%s namespace=%s step=%s elapsed_ms=%.1f",
            agent_name,
            namespace,
            step,
            (time.perf_counter() - invoke_started_at) * 1000.0,
        )

    agent_name, namespace = resolve_invoke_agent_reference(agent_name, namespace)
    _log_invoke_step("resolved_reference")
    ensure_namespace_access(user, namespace)
    _log_invoke_step("namespace_access_checked")
    agent = await asyncio.to_thread(read_agent_cached, agent_name, namespace)
    _log_invoke_step("agent_loaded")
    validate_invoke_runtime_compatibility(runtime_kind_from_spec(agent.get("spec", {})), request)
    _log_invoke_step("runtime_validated")
    if request.factory_mode and not is_factory_agent_resource(agent_name, agent):
        raise HTTPException(status_code=400, detail="factory_mode is only supported for the KubeSynth factory agent.")
    request_payload = request.model_dump(exclude={"factory_mode"})
    policy_memory = resolve_agent_memory_policy(agent, namespace)
    _log_invoke_step("memory_policy_resolved")
    normalized_memory_policy = _normalize_memory_policy(policy_memory)
    promoted_memory = list_promoted_memory_records(
        namespace,
        agent_name,
        username=str(user.get("sub") or user.get("username") or "").strip() or None,
    )
    _log_invoke_step("promoted_memory_loaded")
    ranked_memory = rank_promoted_memory_records(
        request.prompt, promoted_memory, memory_policy=normalized_memory_policy
    )
    _log_invoke_step("promoted_memory_ranked")
    memory_note = build_memory_context_system_note(ranked_memory)
    if memory_note:
        existing_system = str(request_payload.get("system") or "").strip()
        request_payload["system"] = f"{memory_note}\n\n{existing_system}" if existing_system else memory_note
    append_system_note(request_payload, build_agent_collaboration_system_note(agent_name, namespace, agent))
    _log_invoke_step("collaboration_note_appended")
    # Auto-inject intelligence context for intelligence-aware agents
    if _agent_wants_intelligence(agent):
        intel_ctx = _build_auto_intelligence_context(namespace)
        if intel_ctx:
            existing_system = str(request_payload.get("system") or "").strip()
            request_payload["system"] = f"{existing_system}\n\n{intel_ctx}" if existing_system else intel_ctx
        _log_invoke_step("intelligence_context_processed")
    if request.factory_mode:
        append_system_note(request_payload, FACTORY_MODE_SYSTEM_NOTES.get(request.factory_mode))
    request_id = raw_request.headers.get("x-request-id") or str(uuid.uuid4())
    async with httpx.AsyncClient(timeout=AGENT_RUNTIME_TIMEOUT_SECONDS, trust_env=False) as client:
        try:
            _log_invoke_step("runtime_request_start")
            response = await client.post(
                f"{agent_runtime_url(agent_name, namespace)}/invoke",
                json=request_payload,
                headers={"x-request-id": request_id},
            )
            _log_invoke_step("runtime_request_complete")
        except Exception as exc:
            logger.error("Agent invocation failed (%s): %s", agent_name, exc)
            raise HTTPException(status_code=502, detail="Agent invocation failed") from exc

    if response.status_code >= 400:
        error_payload = error_payload_from_body(response.content, "Agent invocation failed")
        raise HTTPException(status_code=502, detail=f"Agent invocation failed: {error_payload['error']}")

    data = parse_json_object_response(response, context="Agent runtime /invoke")
    _log_invoke_step("runtime_response_parsed")
    # Record token usage if present
    _usage = data.get("usage") or {}
    if _usage or data.get("model"):
        try:
            record_usage(
                agent_name=agent_name,
                namespace=namespace,
                user_id=user.get("sub"),
                model=data.get("model") or agent["spec"].get("model"),
                prompt_tokens=int(_usage.get("prompt_tokens", 0)),
                completion_tokens=int(_usage.get("completion_tokens", 0)),
                total_tokens=int(_usage.get("total_tokens", 0)),
                session_id=data.get("thread_id"),
                request_id=request_id,
            )
        except Exception:
            logger.warning("Failed to record usage for %s", agent_name, exc_info=True)
    try:
        record_runtime_memory(
            namespace,
            agent_name,
            session_id=str(data.get("thread_id") or "").strip() or None,
            username=str(user.get("sub") or user.get("username") or "").strip() or None,
            metadata=data.get("metadata") if isinstance(data.get("metadata"), dict) else None,
            auto_promote=bool(normalized_memory_policy.get("autoPromote", False)),
        )
    except Exception:
        logger.warning("Failed to record runtime memory for %s", agent_name, exc_info=True)
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
        subagents=data.get("subagents"),
        warnings=data.get("warnings") or [],
        artifacts=data.get("artifacts") or [],
        tool_calls=data.get("tool_calls") or [],
        metadata=data.get("metadata"),
    )


@app.post("/api/agents/{agent_namespace}/{agent_name}/invoke", response_model=InvokeResponse)
async def invoke_agent_with_namespace_path(
    agent_namespace: str,
    agent_name: str,
    request: InvokeRequest,
    raw_request: Request,
    namespace: str | None = None,
    user=Depends(verify_token),
):
    resolved_agent_name, resolved_namespace = resolve_invoke_agent_reference(
        agent_name,
        namespace,
        path_namespace=agent_namespace,
    )
    return await invoke_agent(resolved_agent_name, request, raw_request, resolved_namespace, user)


@app.post("/api/agents/{agent_name}/invoke/stream")
async def invoke_agent_stream(
    agent_name: str,
    request: InvokeRequest,
    raw_request: Request,
    namespace: str = "default",
    user=Depends(verify_token),
):
    agent_name, namespace = resolve_invoke_agent_reference(agent_name, namespace)
    ensure_namespace_access(user, namespace)
    agent = await asyncio.to_thread(read_agent_cached, agent_name, namespace)
    validate_invoke_runtime_compatibility(runtime_kind_from_spec(agent.get("spec", {})), request)
    if request.factory_mode and not is_factory_agent_resource(agent_name, agent):
        raise HTTPException(status_code=400, detail="factory_mode is only supported for the KubeSynth factory agent.")
    request_payload = request.model_dump(exclude={"factory_mode"})
    append_system_note(request_payload, build_agent_collaboration_system_note(agent_name, namespace, agent))
    # Auto-inject intelligence context for intelligence-aware agents
    if _agent_wants_intelligence(agent):
        intel_ctx = _build_auto_intelligence_context(namespace)
        if intel_ctx:
            existing_system = str(request_payload.get("system") or "").strip()
            request_payload["system"] = f"{existing_system}\n\n{intel_ctx}" if existing_system else intel_ctx
    if request.factory_mode:
        append_system_note(request_payload, FACTORY_MODE_SYSTEM_NOTES.get(request.factory_mode))
    request_id = raw_request.headers.get("x-request-id") or str(uuid.uuid4())

    async def event_generator():
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=10.0), trust_env=False) as client:  # noqa: SIM117
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

                    async def _next_chunk() -> str:
                        return await anext(stream_iterator)

                    next_chunk_task = asyncio.create_task(_next_chunk())
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

                            next_chunk_task = asyncio.create_task(_next_chunk())
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


@app.post("/api/agents/{agent_namespace}/{agent_name}/invoke/stream")
async def invoke_agent_stream_with_namespace_path(
    agent_namespace: str,
    agent_name: str,
    request: InvokeRequest,
    raw_request: Request,
    namespace: str | None = None,
    user=Depends(verify_token),
):
    resolved_agent_name, resolved_namespace = resolve_invoke_agent_reference(
        agent_name,
        namespace,
        path_namespace=agent_namespace,
    )
    return await invoke_agent_stream(resolved_agent_name, request, raw_request, resolved_namespace, user)


@app.get("/api/agents/{agent_name}/todo")
async def get_agent_todos(
    agent_name: str,
    thread_id: str,
    request: Request,
    namespace: str = "default",
    user=Depends(verify_token),
):
    ensure_namespace_access(user, namespace)
    await asyncio.to_thread(read_agent, agent_name, namespace)
    # Forward If-None-Match from client for ETag-based conditional polling
    upstream_headers: dict[str, str] = {}
    if_none_match = request.headers.get("if-none-match")
    if if_none_match:
        upstream_headers["If-None-Match"] = if_none_match
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0), trust_env=False) as client:
            response = await client.get(
                f"{agent_runtime_url(agent_name, namespace)}/todo",
                params={"thread_id": thread_id},
                headers=upstream_headers,
            )
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Failed to fetch agent todos: {exc}") from exc

    if response.status_code == 304:
        return Response(status_code=304, headers={"ETag": response.headers.get("etag", "")})
    if response.status_code == 404:
        raise HTTPException(status_code=404, detail="Agent thread not found")
    if response.status_code >= 400:
        detail = error_payload_from_body(await response.aread(), "Agent todo request failed")
        raise HTTPException(status_code=response.status_code, detail=detail.get("error") or "Agent todo request failed")
    resp_headers: dict[str, str] = {}
    if etag := response.headers.get("etag"):
        resp_headers["ETag"] = etag
    return JSONResponse(content=response.json(), headers=resp_headers)


@app.get("/api/agents/{agent_name}/diff")
async def get_agent_diff(
    agent_name: str,
    thread_id: str,
    namespace: str = "default",
    user=Depends(verify_token),
):
    """Return the unified diff of file changes for the given agent thread."""
    ensure_namespace_access(user, namespace)
    await asyncio.to_thread(read_agent, agent_name, namespace)
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0), trust_env=False) as client:
            response = await client.get(
                f"{agent_runtime_url(agent_name, namespace)}/diff",
                params={"thread_id": thread_id},
            )
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Failed to fetch session diff: {exc}") from exc
    if response.status_code == 404:
        raise HTTPException(status_code=404, detail="Agent thread not found")
    if response.status_code >= 400:
        detail = error_payload_from_body(await response.aread(), "Agent diff request failed")
        raise HTTPException(status_code=response.status_code, detail=detail.get("error") or "Agent diff request failed")
    return JSONResponse(content=response.json())


@app.get("/api/agents/{agent_name}/question")
async def get_agent_questions(
    agent_name: str,
    namespace: str = "default",
    user=Depends(verify_token),
):
    """List pending question requests for an agent."""
    ensure_namespace_access(user, namespace)
    await asyncio.to_thread(read_agent, agent_name, namespace)
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0), trust_env=False) as client:
            response = await client.get(
                f"{agent_runtime_url(agent_name, namespace)}/question",
            )
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Failed to fetch agent questions: {exc}") from exc
    if response.status_code >= 400:
        detail = error_payload_from_body(await response.aread(), "Agent question request failed")
        raise HTTPException(status_code=response.status_code, detail=detail.get("error") or "Agent question request failed")
    return JSONResponse(content=response.json())


@app.post("/api/agents/{agent_name}/question/{request_id}/reply")
async def reply_agent_question(
    agent_name: str,
    request_id: str,
    request: Request,
    namespace: str = "default",
    user=Depends(verify_token),
):
    """Reply to a pending question request."""
    ensure_namespace_access(user, namespace)
    await asyncio.to_thread(read_agent, agent_name, namespace)
    body = await request.json()
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0), trust_env=False) as client:
            response = await client.post(
                f"{agent_runtime_url(agent_name, namespace)}/question/{request_id}/reply",
                json=body,
            )
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Failed to reply to question: {exc}") from exc
    if response.status_code >= 400:
        detail = error_payload_from_body(await response.aread(), "Question reply failed")
        raise HTTPException(status_code=response.status_code, detail=detail.get("error") or "Question reply failed")
    return JSONResponse(content=response.json())


@app.post("/api/agents/{agent_name}/question/{request_id}/reject")
async def reject_agent_question(
    agent_name: str,
    request_id: str,
    namespace: str = "default",
    user=Depends(verify_token),
):
    """Reject a pending question request."""
    ensure_namespace_access(user, namespace)
    await asyncio.to_thread(read_agent, agent_name, namespace)
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0), trust_env=False) as client:
            response = await client.post(
                f"{agent_runtime_url(agent_name, namespace)}/question/{request_id}/reject",
            )
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Failed to reject question: {exc}") from exc
    if response.status_code >= 400:
        detail = error_payload_from_body(await response.aread(), "Question reject failed")
        raise HTTPException(status_code=response.status_code, detail=detail.get("error") or "Question reject failed")
    return JSONResponse(content=response.json())


@app.get("/api/agents/{agent_name}/artifacts/download")
async def download_agent_artifact(
    agent_name: str,
    path: str,
    namespace: str = "default",
    user=Depends(verify_token),
):
    ensure_namespace_access(user, namespace)
    await asyncio.to_thread(read_agent, agent_name, namespace)

    async with httpx.AsyncClient(timeout=AGENT_RUNTIME_TIMEOUT_SECONDS, trust_env=False) as client:
        try:
            response = await client.get(
                f"{agent_runtime_url(agent_name, namespace)}/artifacts/download",
                params={"path": path},
            )
        except Exception as exc:
            logger.error("Artifact download failed (%s/%s): %s", namespace, agent_name, exc)
            raise HTTPException(status_code=502, detail="Artifact download failed") from exc

    if response.status_code >= 400:
        error_payload = error_payload_from_body(response.content, "Artifact download failed")
        status_code = response.status_code if response.status_code in {400, 404} else 502
        raise HTTPException(status_code=status_code, detail=error_payload["error"])

    passthrough_headers = {}
    content_disposition = response.headers.get("content-disposition")
    if content_disposition:
        passthrough_headers["content-disposition"] = content_disposition
    content_length = response.headers.get("content-length")
    if content_length:
        passthrough_headers["content-length"] = content_length

    return Response(
        content=response.content,
        media_type=response.headers.get("content-type") or "application/octet-stream",
        headers=passthrough_headers,
    )


@app.get("/api/agents/{agent_name}/artifacts/zip")
async def download_agent_artifacts_zip(
    agent_name: str,
    namespace: str = "default",
    root: str = "",
    user=Depends(verify_token),
):
    """Download a ZIP archive of all workspace files from an agent runtime."""
    ensure_namespace_access(user, namespace)
    await asyncio.to_thread(read_agent, agent_name, namespace)

    params: dict[str, str] = {}
    if root:
        params["root"] = root

    async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=10.0), trust_env=False) as client:
        try:
            response = await client.get(
                f"{agent_runtime_url(agent_name, namespace)}/artifacts/zip",
                params=params,
            )
        except Exception as exc:
            logger.error("Artifact zip download failed (%s/%s): %s", namespace, agent_name, exc)
            raise HTTPException(status_code=502, detail="Artifact zip download failed") from exc

    if response.status_code >= 400:
        error_payload = error_payload_from_body(response.content, "Artifact zip download failed")
        status_code = response.status_code if response.status_code in {400, 404} else 502
        raise HTTPException(status_code=status_code, detail=error_payload["error"])

    passthrough_headers = {}
    content_disposition = response.headers.get("content-disposition")
    if content_disposition:
        passthrough_headers["content-disposition"] = content_disposition
    content_length = response.headers.get("content-length")
    if content_length:
        passthrough_headers["content-length"] = content_length

    return Response(
        content=response.content,
        media_type=response.headers.get("content-type") or "application/zip",
        headers=passthrough_headers,
    )


@app.get("/api/agents/{agent_name}/artifacts/list")
async def list_agent_artifacts(
    agent_name: str,
    namespace: str = "default",
    root: str = "",
    user=Depends(verify_token),
):
    ensure_namespace_access(user, namespace)
    await asyncio.to_thread(read_agent, agent_name, namespace)

    params: dict[str, str] = {}
    if root:
        params["root"] = root

    async with httpx.AsyncClient(timeout=AGENT_RUNTIME_TIMEOUT_SECONDS, trust_env=False) as client:
        try:
            response = await client.get(
                f"{agent_runtime_url(agent_name, namespace)}/artifacts/list",
                params=params,
            )
        except Exception as exc:
            logger.error("Artifact list failed (%s/%s): %s", namespace, agent_name, exc)
            raise HTTPException(status_code=502, detail="Artifact listing failed") from exc

    if response.status_code >= 400:
        error_payload = error_payload_from_body(response.content, "Artifact listing failed")
        status_code = response.status_code if response.status_code in {400, 404} else 502
        raise HTTPException(status_code=status_code, detail=error_payload["error"])

    return response.json()


@app.get("/api/agents/{agent_name}/logs")
def get_agent_logs(
    agent_name: str,
    namespace: str = "default",
    tail: int = 200,
    user=Depends(verify_token),
):
    ensure_namespace_access(user, namespace)
    read_agent(agent_name, namespace)
    tail = max(1, min(tail, 5000))
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
            tail_lines=tail,
            timestamps=True,
        )
        return {"agent_name": agent_name, "pod_name": pod_name, "logs": logs}
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("Could not retrieve logs for %s: %s", agent_name, exc)
        raise HTTPException(status_code=404, detail="Could not retrieve logs") from exc


@app.get("/api/agents/{agent_name}/logs/stream")
async def stream_agent_logs(
    agent_name: str,
    request: Request,
    namespace: str = "default",
    tail: int = 50,
    user=Depends(verify_token),
):
    """Stream pod logs via SSE using Kubernetes follow=True."""
    ensure_namespace_access(user, namespace)
    read_agent(agent_name, namespace)
    tail = max(1, min(tail, 5000))

    pods = list_agent_pods(agent_name, namespace)
    if not pods:
        raise HTTPException(status_code=404, detail=f"No runtime pod found for agent '{agent_name}'")

    pod_name = str(getattr(pods[0].metadata, "name", "") or "")
    if not pod_name:
        raise HTTPException(status_code=404, detail=f"No runtime pod found for agent '{agent_name}'")

    async def log_event_generator():
        import time

        from kubernetes import client as k8s_client
        from kubernetes import watch as k8s_watch

        yield sse_event("log.started", {"agent_name": agent_name, "pod_name": pod_name})

        w = k8s_watch.Watch()
        try:
            log_stream = w.stream(
                k8s_client.CoreV1Api().read_namespaced_pod_log,
                name=pod_name,
                namespace=namespace,
                container="agent-runtime",
                follow=True,
                tail_lines=tail,
                timestamps=True,
                _request_timeout=0,
            )
            last_event_time = time.monotonic()
            for line in log_stream:
                if await request.is_disconnected():
                    break
                yield sse_event("log.line", {"line": line})
                last_event_time = time.monotonic()
                await asyncio.sleep(0)  # yield control so disconnect check works
                # Send keepalive if idle for too long (prevents proxy timeouts)
                if time.monotonic() - last_event_time > STREAM_KEEPALIVE_SECONDS:
                    yield sse_keepalive_comment()
                    last_event_time = time.monotonic()
        except Exception as exc:
            yield sse_event("log.error", {"error": str(exc)})
        finally:
            w.stop()
            yield sse_event("log.stopped", {"agent_name": agent_name})

    return StreamingResponse(log_event_generator(), media_type="text/event-stream")


# ─────────────────────────────────────────────────────────────
# Chat Session Persistence
# ─────────────────────────────────────────────────────────────


class ChatSessionCreate(BaseModel):
    agent_name: str = Field(..., min_length=1, max_length=128)
    title: str = Field("Untitled", max_length=256)


class ChatSessionUpdate(BaseModel):
    title: str = Field(..., min_length=1, max_length=256)


class ChatMessagePayload(BaseModel):
    message_id: str = Field(..., min_length=1, max_length=128)
    role: str = Field(..., min_length=1, max_length=32)
    content: str = ""
    status: str = "complete"
    toolName: str | None = None
    toolNode: str | None = None


class ChatMessagesSave(BaseModel):
    messages: list[ChatMessagePayload]


@app.get("/api/chat-sessions")
async def api_list_chat_sessions(
    agent_name: str,
    namespace: str = "default",
    user=Depends(verify_token),
):
    """List chat sessions for the given agent in the given namespace."""
    ensure_namespace_access(user, namespace)
    username = user.get("sub") or user.get("username")
    return list_chat_sessions(namespace, agent_name, username=username)


@app.post("/api/chat-sessions", status_code=201)
async def api_create_chat_session(
    body: ChatSessionCreate,
    namespace: str = "default",
    user=Depends(verify_token),
):
    """Create a new chat session."""
    ensure_namespace_access(user, namespace)
    username = user.get("sub") or user.get("username")
    session_id = str(uuid.uuid4())
    return create_chat_session(namespace, body.agent_name, session_id, body.title, username=username)


@app.get("/api/chat-sessions/{session_id}/messages")
async def api_get_chat_messages(
    session_id: str,
    user=Depends(verify_token),
):
    """Get all messages for a chat session."""
    return get_chat_session_messages(session_id)


@app.put("/api/chat-sessions/{session_id}/messages")
async def api_save_chat_messages(
    session_id: str,
    body: ChatMessagesSave,
    user=Depends(verify_token),
):
    """Save (replace) all messages for a chat session."""
    save_chat_messages(session_id, [m.model_dump() for m in body.messages])
    return {"status": "ok"}


@app.patch("/api/chat-sessions/{session_id}")
async def api_update_chat_session(
    session_id: str,
    body: ChatSessionUpdate,
    user=Depends(verify_token),
):
    """Update a chat session title."""
    result = update_chat_session_title(session_id, body.title)
    if result is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return result


@app.delete("/api/chat-sessions/{session_id}")
async def api_delete_chat_session(
    session_id: str,
    user=Depends(verify_token),
):
    """Delete a chat session and all its messages."""
    deleted = delete_chat_session(session_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"status": "deleted"}


@app.get("/api/agents/{agent_name}/memory", response_model=list[MemoryRecordInfo])
async def api_list_agent_memory(
    agent_name: str,
    namespace: str = "default",
    session_id: str | None = None,
    limit: int = 50,
    user=Depends(verify_token),
):
    """List persisted memory records for an agent, optionally scoped to a session."""
    ensure_namespace_access(user, namespace)
    username = user.get("sub") or user.get("username")
    return [
        MemoryRecordInfo(**item)
        for item in list_memory_records(
            namespace,
            agent_name,
            username=username,
            session_id=session_id,
            limit=limit,
        )
    ]


@app.patch("/api/memory/{record_id}", response_model=MemoryRecordInfo)
async def api_update_memory_record(
    record_id: int,
    body: MemoryRecordUpdateRequest,
    user=Depends(verify_token),
):
    username = user.get("sub") or user.get("username")
    updated = update_memory_record(
        record_id,
        promoted=body.promoted,
        topic=body.topic,
        content=body.content,
        username=username,
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="Memory record not found")
    return MemoryRecordInfo(**updated)


@app.delete("/api/memory/{record_id}")
async def api_delete_memory_record(
    record_id: int,
    user=Depends(verify_token),
):
    username = user.get("sub") or user.get("username")
    deleted = delete_memory_record(record_id, username=username)
    if not deleted:
        raise HTTPException(status_code=404, detail="Memory record not found")
    return {"status": "deleted", "id": record_id}


# ─────────────────────────────────────────────────────────────
# LLM / Provider management (proxied to the LiteLLM sidecar)
# ─────────────────────────────────────────────────────────────

_LLM_PROXY_TIMEOUT = httpx.Timeout(15.0, connect=5.0)
_OPENROUTER_API_TIMEOUT = httpx.Timeout(20.0, connect=10.0)

# -- OpenRouter model cache (TTL-based in-memory)
_openrouter_model_cache: list[dict[str, str]] = []
_openrouter_cache_ts: float = 0.0
_OPENROUTER_CACHE_TTL = 600  # 10 minutes

# -- Copilot model cache --
_copilot_model_cache: list[dict[str, str]] = []
_copilot_cache_ts: float = 0.0
_COPILOT_CACHE_TTL = 600  # 10 minutes


async def _fetch_copilot_models(copilot_token: str) -> list[dict[str, str]]:
    """Fetch available models from GitHub Copilot API with caching."""
    global _copilot_model_cache, _copilot_cache_ts

    now = time.monotonic()
    if _copilot_model_cache and (now - _copilot_cache_ts) < _COPILOT_CACHE_TTL:
        return _copilot_model_cache

    try:
        # Try exchanging for a Copilot session token; fall back to using the
        # OAuth token directly (works for personal GitHub tokens with Copilot).
        session_token = copilot_token
        models_url = "https://api.githubcopilot.com/models"
        try:
            exchanged, api_endpoint = await _exchange_copilot_session_token(copilot_token)
            session_token = exchanged
            if api_endpoint:
                models_url = f"{api_endpoint.rstrip('/')}/models"
        except Exception as exc:
            logger.info("Copilot token exchange failed, using OAuth token directly: %s", exc)
        data = await _copilot_get_json(
            models_url,
            {
                "Authorization": f"Bearer {session_token}",
                "Accept": "application/json",
                "User-Agent": "GitHubCopilotChat/0.25.2024",
                "Editor-Version": "vscode/1.96.2",
                "Editor-Plugin-Version": "copilot-chat/0.25.2024",
                "Copilot-Integration-Id": "vscode-chat",
                "Openai-Intent": "conversation-edits",
            },
        )
        models_raw = data if isinstance(data, list) else data.get("data", data.get("models", []))
        result: list[dict[str, str]] = []
        for m in models_raw:
            model_id = m.get("id", "") if isinstance(m, dict) else str(m)
            if not model_id:
                continue
            name = m.get("name", model_id) if isinstance(m, dict) else model_id
            caps = m.get("capabilities", {}) if isinstance(m, dict) else {}
            family = m.get("model_picker_label", m.get("family", "")) if isinstance(m, dict) else ""
            desc_parts: list[str] = []
            if family:
                desc_parts.append(family)
            if caps.get("type"):
                desc_parts.append(caps["type"])
            result.append(
                {
                    "model_id": model_id,
                    "display_name": name,
                    "description": " · ".join(desc_parts) if desc_parts else "Copilot model",
                }
            )
        _copilot_model_cache = result
        _copilot_cache_ts = now
        logger.info("Fetched %d models from GitHub Copilot API", len(result))
        return result
    except Exception as exc:
        logger.warning("Failed to fetch Copilot models: %s", exc)
        return _copilot_model_cache  # return stale cache on error


async def _fetch_openrouter_models(api_key: str | None = None) -> list[dict[str, str]]:
    """Fetch models from OpenRouter API with in-memory caching."""
    import time

    global _openrouter_model_cache, _openrouter_cache_ts

    now = time.monotonic()
    if _openrouter_model_cache and (now - _openrouter_cache_ts) < _OPENROUTER_CACHE_TTL:
        return _openrouter_model_cache

    headers: dict[str, str] = {"Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        async with httpx.AsyncClient(timeout=_OPENROUTER_API_TIMEOUT, trust_env=False) as client:
            resp = await client.get("https://openrouter.ai/api/v1/models", headers=headers)
            resp.raise_for_status()
            data = resp.json()
            models_raw = data.get("data", [])
            result: list[dict[str, str]] = []
            for m in models_raw:
                model_id = m.get("id", "")
                name = m.get("name", model_id)
                desc_parts: list[str] = []
                pricing = m.get("pricing", {})
                if pricing:
                    prompt_price = pricing.get("prompt")
                    if prompt_price is not None:
                        try:
                            p = float(prompt_price) * 1_000_000
                            desc_parts.append(f"${p:.2f}/M input")
                        except (ValueError, TypeError):
                            pass
                ctx = m.get("context_length")
                if ctx:
                    with contextlib.suppress(ValueError, TypeError):
                        desc_parts.append(f"{int(ctx) // 1000}k ctx")
                description = " · ".join(desc_parts) if desc_parts else ""
                if model_id:
                    result.append(
                        {
                            "model_id": model_id,
                            "display_name": name,
                            "description": description,
                        }
                    )
            _openrouter_model_cache = result
            _openrouter_cache_ts = now
            logger.info("Fetched %d models from OpenRouter API", len(result))
            return result
    except Exception as exc:
        logger.warning("Failed to fetch OpenRouter models: %s", exc)
        return _openrouter_model_cache  # return stale cache on error


# -- well-known provider keys accepted by the platform
_ALLOWED_SECRET_KEYS = frozenset(
    {
        "OPENAI_API_KEY",
        "OPENROUTER_API_KEY",
        "ANTHROPIC_API_KEY",
        "AZURE_API_KEY",
        "GOOGLE_API_KEY",
        "MISTRAL_API_KEY",
        "COHERE_API_KEY",
        "GROQ_API_KEY",
        "DEEPSEEK_API_KEY",
        "TOGETHER_API_KEY",
        "FIREWORKS_API_KEY",
        "GITHUB_COPILOT_TOKEN",
    }
)

# -- Provider metadata: key_name → {label, prefix for litellm, env reference}
_PROVIDER_META: dict[str, dict[str, str]] = {
    "OPENAI_API_KEY": {"label": "OpenAI", "prefix": "openai/", "placeholder": "sk-..."},
    "OPENROUTER_API_KEY": {"label": "OpenRouter", "prefix": "openrouter/", "placeholder": "sk-or-..."},
    "ANTHROPIC_API_KEY": {"label": "Anthropic", "prefix": "anthropic/", "placeholder": "sk-ant-..."},
    "AZURE_API_KEY": {"label": "Azure OpenAI", "prefix": "azure/", "placeholder": "..."},
    "GOOGLE_API_KEY": {"label": "Google AI", "prefix": "gemini/", "placeholder": "AIza..."},
    "MISTRAL_API_KEY": {"label": "Mistral", "prefix": "mistral/", "placeholder": "..."},
    "COHERE_API_KEY": {"label": "Cohere", "prefix": "cohere/", "placeholder": "..."},
    "GROQ_API_KEY": {"label": "Groq", "prefix": "groq/", "placeholder": "gsk_..."},
    "DEEPSEEK_API_KEY": {"label": "DeepSeek", "prefix": "deepseek/", "placeholder": "sk-..."},
    "TOGETHER_API_KEY": {"label": "Together AI", "prefix": "together_ai/", "placeholder": "..."},
    "FIREWORKS_API_KEY": {"label": "Fireworks", "prefix": "fireworks_ai/", "placeholder": "..."},
    "GITHUB_COPILOT_TOKEN": {
        "label": "GitHub Copilot",
        "prefix": "openai/",
        "placeholder": "Authenticated via GitHub",
        "api_base": "https://api.githubcopilot.com",
        "extra_headers": '{"Copilot-Integration-Id": "vscode-chat"}',
    },
}

# -- Popular models per provider (static, curated)
_PROVIDER_POPULAR_MODELS: dict[str, list[dict[str, str]]] = {
    "OPENAI_API_KEY": [
        {"model_id": "gpt-4o", "display_name": "GPT-4o", "description": "Most capable, multimodal"},
        {"model_id": "gpt-4o-mini", "display_name": "GPT-4o Mini", "description": "Fast and affordable"},
        {"model_id": "gpt-4-turbo", "display_name": "GPT-4 Turbo", "description": "High capability, 128k context"},
        {"model_id": "gpt-3.5-turbo", "display_name": "GPT-3.5 Turbo", "description": "Budget option"},
        {"model_id": "o1", "display_name": "o1", "description": "Reasoning model"},
        {"model_id": "o1-mini", "display_name": "o1 Mini", "description": "Fast reasoning"},
        {"model_id": "o3-mini", "display_name": "o3 Mini", "description": "Latest reasoning, cost-effective"},
    ],
    "OPENROUTER_API_KEY": [],
    "ANTHROPIC_API_KEY": [
        {
            "model_id": "claude-sonnet-4-20250514",
            "display_name": "Claude Sonnet 4",
            "description": "Latest, most capable",
        },
        {
            "model_id": "claude-3-5-sonnet-20241022",
            "display_name": "Claude 3.5 Sonnet",
            "description": "Fast and intelligent",
        },
        {
            "model_id": "claude-3-5-haiku-20241022",
            "display_name": "Claude 3.5 Haiku",
            "description": "Fastest, most compact",
        },
        {"model_id": "claude-3-opus-20240229", "display_name": "Claude 3 Opus", "description": "Most capable (legacy)"},
    ],
    "AZURE_API_KEY": [
        {"model_id": "gpt-4o", "display_name": "GPT-4o", "description": "Azure-hosted GPT-4o"},
        {"model_id": "gpt-4o-mini", "display_name": "GPT-4o Mini", "description": "Azure-hosted GPT-4o Mini"},
        {"model_id": "gpt-4", "display_name": "GPT-4", "description": "Azure-hosted GPT-4"},
    ],
    "GOOGLE_API_KEY": [
        {"model_id": "gemini-2.0-flash", "display_name": "Gemini 2.0 Flash", "description": "Fast multimodal"},
        {"model_id": "gemini-1.5-pro", "display_name": "Gemini 1.5 Pro", "description": "1M context window"},
        {"model_id": "gemini-1.5-flash", "display_name": "Gemini 1.5 Flash", "description": "Fast, 1M context"},
    ],
    "MISTRAL_API_KEY": [
        {"model_id": "mistral-large-latest", "display_name": "Mistral Large", "description": "Top-tier reasoning"},
        {"model_id": "mistral-medium-latest", "display_name": "Mistral Medium", "description": "Balanced"},
        {"model_id": "mistral-small-latest", "display_name": "Mistral Small", "description": "Fast and affordable"},
        {"model_id": "codestral-latest", "display_name": "Codestral", "description": "Code-specialized"},
    ],
    "COHERE_API_KEY": [
        {"model_id": "command-r-plus", "display_name": "Command R+", "description": "Most capable"},
        {"model_id": "command-r", "display_name": "Command R", "description": "Balanced"},
    ],
    "GROQ_API_KEY": [
        {"model_id": "llama-3.1-70b-versatile", "display_name": "Llama 3.1 70B", "description": "Fast inference"},
        {"model_id": "llama-3.1-8b-instant", "display_name": "Llama 3.1 8B", "description": "Ultra-fast"},
        {"model_id": "mixtral-8x7b-32768", "display_name": "Mixtral 8x7B", "description": "MoE, 32K context"},
    ],
    "DEEPSEEK_API_KEY": [
        {"model_id": "deepseek-chat", "display_name": "DeepSeek Chat", "description": "General purpose"},
        {"model_id": "deepseek-coder", "display_name": "DeepSeek Coder", "description": "Code-specialized"},
        {"model_id": "deepseek-reasoner", "display_name": "DeepSeek Reasoner", "description": "Reasoning model"},
    ],
    "TOGETHER_API_KEY": [
        {
            "model_id": "meta-llama/Llama-3.1-70B-Instruct-Turbo",
            "display_name": "Llama 3.1 70B Turbo",
            "description": "Fast Llama",
        },
        {
            "model_id": "meta-llama/Llama-3.1-8B-Instruct-Turbo",
            "display_name": "Llama 3.1 8B Turbo",
            "description": "Ultra-fast Llama",
        },
        {"model_id": "Qwen/Qwen2.5-72B-Instruct-Turbo", "display_name": "Qwen 2.5 72B", "description": "Top-tier open"},
    ],
    "FIREWORKS_API_KEY": [
        {
            "model_id": "accounts/fireworks/models/llama-v3p1-70b-instruct",
            "display_name": "Llama 3.1 70B",
            "description": "Fast inference",
        },
        {
            "model_id": "accounts/fireworks/models/llama-v3p1-8b-instruct",
            "display_name": "Llama 3.1 8B",
            "description": "Low latency",
        },
    ],
    "GITHUB_COPILOT_TOKEN": [
        {"model_id": "gpt-4o", "display_name": "GPT-4o", "description": "Most capable, multimodal"},
        {"model_id": "gpt-4.1", "display_name": "GPT-4.1", "description": "Latest GPT model"},
        {"model_id": "o3-mini", "display_name": "o3 Mini", "description": "Fast reasoning"},
        {"model_id": "o4-mini", "display_name": "o4 Mini", "description": "Latest reasoning, cost-effective"},
        {"model_id": "claude-sonnet-4", "display_name": "Claude Sonnet 4", "description": "Anthropic via Copilot"},
        {
            "model_id": "claude-3.5-sonnet",
            "display_name": "Claude 3.5 Sonnet",
            "description": "Fast Anthropic via Copilot",
        },
        {"model_id": "gemini-2.0-flash", "display_name": "Gemini 2.0 Flash", "description": "Google via Copilot"},
    ],
}

_PROVIDER_REGISTRY_DATA_KEY = "providers.json"
_PROVIDER_REGISTRY_VERSION = 1
_PROVIDER_ID_RE = re.compile(r"^[a-z0-9](?:[-a-z0-9]{0,62})$")
_OPENCODE_ZEN_MODELS_URL = "https://opencode.ai/zen/v1/models"
_OPENCODE_ZEN_BASE_URL = "https://opencode.ai/zen/v1"
_PROVIDER_AUTH_PLACEHOLDERS: dict[str, str] = {
    "opencode": "sk-...",
    "opencode-go": "sk-...",
    "github-copilot": "Authenticated via GitHub",
}
_PROVIDER_REGISTRY_META: dict[str, dict[str, Any]] = {
    "opencode": {
        "label": "OpenCode Zen",
        "description": "Recommended OpenCode-native provider with curated models from the OpenCode team.",
        "auth_type": "apiKey",
        "secret_key": "OPENCODE_API_KEY",
        "base_url": _OPENCODE_ZEN_BASE_URL,
        "docs_url": "https://opencode.ai/docs/providers/#opencode-zen",
    },
    "opencode-go": {
        "label": "OpenCode Go",
        "description": "Low-cost OpenCode provider tuned for reliable coding workloads.",
        "auth_type": "apiKey",
        "secret_key": "OPENCODE_GO_API_KEY",
        "base_url": None,
        "docs_url": "https://opencode.ai/docs/providers/#opencode-go",
    },
    "github-copilot": {
        "label": "GitHub Copilot",
        "description": "Connect a GitHub Copilot subscription through the device authorization flow.",
        "auth_type": "oauth",
        "secret_key": "GITHUB_COPILOT_TOKEN",
        "base_url": "https://api.githubcopilot.com",
        "docs_url": "https://opencode.ai/docs/providers/#github-copilot",
    },
}
_OPENCODE_GO_FALLBACK_MODELS: list[dict[str, str]] = [
    {
        "model_id": "kimi-k2.6",
        "display_name": "kimi-k2.6",
        "description": "Current KubeSynth default for bundled OpenCode agents.",
    }
]


def _provider_namespace() -> str:
    return os.getenv("POD_NAMESPACE", "ai-platform")


def _empty_provider_registry_state() -> dict[str, Any]:
    return {"version": _PROVIDER_REGISTRY_VERSION, "custom_providers": {}}


def _normalize_provider_id(raw_value: str) -> str:
    provider_id = str(raw_value or "").strip().lower()
    if not _PROVIDER_ID_RE.fullmatch(provider_id):
        raise HTTPException(
            status_code=400,
            detail="provider_id must use lowercase letters, numbers, and hyphens only.",
        )
    return provider_id


def _custom_provider_secret_key(provider_id: str) -> str:
    normalized = re.sub(r"[^A-Z0-9]+", "_", provider_id.upper()).strip("_")
    return f"CUSTOM_PROVIDER_{normalized}_API_KEY"


def _decode_secret_value(raw_value: str) -> str | None:
    if not raw_value:
        return None
    try:
        return base64.b64decode(raw_value).decode("utf-8").strip() or None
    except Exception:
        return None


def _read_or_create_provider_registry_configmap() -> tuple[Any, Any, dict[str, Any]]:
    from kubernetes import client as k8s_client
    from kubernetes.client.rest import ApiException

    namespace = _provider_namespace()
    api = k8s_client.CoreV1Api()
    try:
        configmap = api.read_namespaced_config_map(name=PROVIDER_REGISTRY_CONFIGMAP_NAME, namespace=namespace)
    except ApiException as exc:
        if exc.status != 404:
            raise
        body = {
            "apiVersion": "v1",
            "kind": "ConfigMap",
            "metadata": {"name": PROVIDER_REGISTRY_CONFIGMAP_NAME, "namespace": namespace},
            "data": {
                _PROVIDER_REGISTRY_DATA_KEY: json.dumps(_empty_provider_registry_state(), ensure_ascii=False, sort_keys=True)
            },
        }
        api.create_namespaced_config_map(namespace=namespace, body=body)
        configmap = api.read_namespaced_config_map(name=PROVIDER_REGISTRY_CONFIGMAP_NAME, namespace=namespace)

    data = getattr(configmap, "data", None) or {}
    raw_payload = str(data.get(_PROVIDER_REGISTRY_DATA_KEY) or "").strip()
    if not raw_payload:
        return api, configmap, _empty_provider_registry_state()
    try:
        payload = json.loads(raw_payload)
    except ValueError as exc:
        raise HTTPException(status_code=500, detail="Provider registry ConfigMap contains invalid JSON") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=500, detail="Provider registry ConfigMap must decode to an object")
    custom_providers = payload.get("custom_providers")
    if custom_providers is None:
        payload["custom_providers"] = {}
    elif not isinstance(custom_providers, dict):
        raise HTTPException(status_code=500, detail="Provider registry custom_providers must decode to an object")
    return api, configmap, payload


def _save_provider_registry_state(api: Any, configmap: Any, state: dict[str, Any]) -> None:
    data = getattr(configmap, "data", None) or {}
    data[_PROVIDER_REGISTRY_DATA_KEY] = json.dumps(state, ensure_ascii=False, sort_keys=True)
    configmap.data = data  # type: ignore[union-attr]
    api.replace_namespaced_config_map(
        name=PROVIDER_REGISTRY_CONFIGMAP_NAME,
        namespace=_provider_namespace(),
        body=configmap,
    )


def _read_or_create_provider_auth_secret() -> tuple[Any, Any, dict[str, str]]:
    from kubernetes import client as k8s_client
    from kubernetes.client.rest import ApiException

    namespace = _provider_namespace()
    api = k8s_client.CoreV1Api()
    try:
        secret = api.read_namespaced_secret(name=PROVIDER_AUTH_SECRET_NAME, namespace=namespace)
    except ApiException as exc:
        if exc.status != 404:
            raise
        body = {
            "apiVersion": "v1",
            "kind": "Secret",
            "metadata": {"name": PROVIDER_AUTH_SECRET_NAME, "namespace": namespace},
            "type": "Opaque",
            "data": {},
        }
        api.create_namespaced_secret(namespace=namespace, body=body)
        secret = api.read_namespaced_secret(name=PROVIDER_AUTH_SECRET_NAME, namespace=namespace)
    data = getattr(secret, "data", None) or {}
    return api, secret, cast(dict[str, str], data)


def _update_provider_auth_secret(*, values: dict[str, str] | None = None, remove_keys: set[str] | None = None) -> None:
    api, secret, existing_data = _read_or_create_provider_auth_secret()
    next_data = dict(existing_data)
    for key_name in remove_keys or set():
        next_data.pop(key_name, None)
    for key_name, value in (values or {}).items():
        next_data[key_name] = base64.b64encode(value.encode("utf-8")).decode("ascii")
    secret.data = next_data  # type: ignore[union-attr]
    api.replace_namespaced_secret(name=PROVIDER_AUTH_SECRET_NAME, namespace=_provider_namespace(), body=secret)


def _provider_registry_model_entries(raw_models: list[dict[str, str]]) -> list[dict[str, str | None]]:
    return [
        {
            "id": str(item.get("model_id") or "").strip(),
            "name": str(item.get("display_name") or item.get("model_id") or "").strip(),
            "description": str(item.get("description") or "").strip() or None,
        }
        for item in raw_models
        if str(item.get("model_id") or "").strip()
    ]


async def _fetch_opencode_zen_models() -> list[dict[str, str]]:
    try:
        async with httpx.AsyncClient(timeout=15.0, trust_env=False) as client:
            response = await client.get(_OPENCODE_ZEN_MODELS_URL, headers={"Accept": "application/json"})
            response.raise_for_status()
            payload = response.json()
        data = payload.get("data") if isinstance(payload, dict) else []
        if not isinstance(data, list):
            return []
        result: list[dict[str, str]] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            model_id = str(item.get("id") or "").strip()
            if not model_id:
                continue
            result.append({"model_id": model_id, "display_name": model_id, "description": "Live model catalog"})
        return result
    except Exception as exc:
        logger.warning("Failed to fetch OpenCode Zen models: %s", exc)
        return [
            {"model_id": "kimi-k2.6", "display_name": "kimi-k2.6", "description": "KubeSynth default"},
            {"model_id": "gpt-5.4", "display_name": "gpt-5.4", "description": "Latest GPT family"},
            {"model_id": "claude-sonnet-4", "display_name": "claude-sonnet-4", "description": "Claude Sonnet"},
        ]


async def _fetch_opencode_go_models() -> list[dict[str, str]]:
    try:
        async with httpx.AsyncClient(timeout=20.0, trust_env=False) as client:
            response = await client.get(
                "https://models.dev/api.json",
                headers={"Accept": "application/json", "User-Agent": "kubesynth-api-gateway/1.0"},
            )
            response.raise_for_status()
            data = response.json()
        go_data = data.get("opencode-go") if isinstance(data, dict) else None
        if not isinstance(go_data, dict):
            return _OPENCODE_GO_FALLBACK_MODELS
        models_raw = go_data.get("models") or {}
        if not isinstance(models_raw, dict):
            return _OPENCODE_GO_FALLBACK_MODELS
        result: list[dict[str, str]] = []
        for model_id in sorted(models_raw.keys()):
            model_id = str(model_id).strip()
            if not model_id:
                continue
            result.append({"model_id": model_id, "display_name": model_id, "description": "Live model catalog"})
        return result if result else _OPENCODE_GO_FALLBACK_MODELS
    except Exception as exc:
        logger.warning("Failed to fetch opencode-go models from models.dev: %s", exc)
        return _OPENCODE_GO_FALLBACK_MODELS


async def _provider_registry_models_for_builtin(provider_id: str, auth_data: dict[str, str]) -> list[dict[str, str | None]]:
    if provider_id == "opencode":
        return _provider_registry_model_entries(await _fetch_opencode_zen_models())
    if provider_id == "opencode-go":
        return _provider_registry_model_entries(await _fetch_opencode_go_models())
    if provider_id == "github-copilot":
        copilot_token = _decode_secret_value(auth_data.get("GITHUB_COPILOT_TOKEN", ""))
        if copilot_token:
            live_models = await _fetch_copilot_models(copilot_token)
            if live_models:
                return _provider_registry_model_entries(live_models)
        return _provider_registry_model_entries(_PROVIDER_POPULAR_MODELS.get("GITHUB_COPILOT_TOKEN", []))
    return []


async def _provider_registry_response() -> dict[str, Any]:
    _, _, registry_state = _read_or_create_provider_registry_configmap()
    _, _, auth_data = _read_or_create_provider_auth_secret()

    providers: list[dict[str, Any]] = []
    for provider_id, meta in _PROVIDER_REGISTRY_META.items():
        secret_key = str(meta.get("secret_key") or "")
        providers.append(
            {
                "id": provider_id,
                "label": meta["label"],
                "kind": "builtin",
                "description": meta["description"],
                "auth_type": meta["auth_type"],
                "connected": bool(auth_data.get(secret_key)),
                "docs_url": meta.get("docs_url"),
                "base_url": meta.get("base_url"),
                "key_placeholder": _PROVIDER_AUTH_PLACEHOLDERS.get(provider_id),
                "editable": False,
                "headers": {},
                "models": await _provider_registry_models_for_builtin(provider_id, auth_data),
            }
        )

    custom_providers = cast(dict[str, dict[str, Any]], registry_state.get("custom_providers") or {})
    for provider_id, entry in sorted(custom_providers.items()):
        secret_key = str(entry.get("secret_key_name") or _custom_provider_secret_key(provider_id))
        model_ids = [
            str(raw_model).strip()
            for raw_model in cast(list[Any], entry.get("models") or [])
            if str(raw_model).strip()
        ]
        providers.append(
            {
                "id": provider_id,
                "label": str(entry.get("name") or provider_id),
                "kind": "custom",
                "description": str(entry.get("description") or "OpenAI-compatible custom provider.").strip(),
                "auth_type": "apiKey",
                "connected": bool(auth_data.get(secret_key)),
                "docs_url": None,
                "base_url": str(entry.get("base_url") or "").strip() or None,
                "key_placeholder": "sk-...",
                "editable": True,
                "headers": cast(dict[str, str], entry.get("headers") or {}),
                "models": [
                    {"id": model_id, "name": model_id, "description": None}
                    for model_id in model_ids
                ],
            }
        )

    return {"providers": providers}


def _litellm_headers() -> dict[str, str]:
    key = LITELLM_MASTER_KEY
    if not key:
        # fall back to env injected from K8s secret
        key = os.getenv("LITELLM_MASTER_KEY", "") or ""
    hdrs: dict[str, str] = {"Accept": "application/json"}
    if key:
        hdrs["Authorization"] = f"Bearer {key}"
    return hdrs


class LLMModelEntry(BaseModel):
    model_name: str = Field(..., min_length=1, max_length=200)
    litellm_params: dict[str, Any] = Field(default_factory=dict)


class LLMModelDeleteRequest(BaseModel):
    id: str = Field(..., min_length=1, max_length=200)


class LLMKeyUpdate(BaseModel):
    keys: dict[str, str] = Field(default_factory=dict, description="Map of KEY_NAME -> value")


class ProviderCredentialUpdate(BaseModel):
    api_key: str = Field(..., min_length=1, max_length=500)


class ProviderCatalogModel(BaseModel):
    model_id: str = Field(..., min_length=1, max_length=300)


class CustomProviderRequest(BaseModel):
    provider_id: str = Field(..., min_length=1, max_length=63)
    name: str = Field(..., min_length=1, max_length=120)
    base_url: str = Field(..., min_length=1, max_length=500)
    description: str | None = Field(default=None, max_length=240)
    api_key: str | None = Field(default=None, max_length=500)
    headers: dict[str, str] = Field(default_factory=dict)
    models: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_custom_provider_fields(self) -> "CustomProviderRequest":
        normalized_headers: dict[str, str] = {}
        for raw_name, raw_value in self.headers.items():
            name = str(raw_name).strip()
            value = str(raw_value).strip()
            if not name:
                raise ValueError("Custom provider headers must use non-empty names")
            if not value:
                raise ValueError(f"Custom provider header '{name}' must not be blank")
            normalized_headers[name] = value
        self.headers = normalized_headers
        self.models = [str(model).strip() for model in self.models if str(model).strip()]
        return self


@app.get("/api/providers")
async def provider_registry_list(user=Depends(verify_token)):
    """List built-in and custom providers for the OpenCode-style settings UX."""
    ensure_role(user, "viewer")
    return await _provider_registry_response()


@app.get("/api/providers/catalog")
async def provider_registry_catalog(user=Depends(verify_token)):
    """Return a flattened model catalog for runtime-compatible provider/model picks."""
    ensure_role(user, "viewer")
    payload = await _provider_registry_response()
    catalog: list[dict[str, Any]] = []
    for provider in cast(list[dict[str, Any]], payload.get("providers") or []):
        provider_id = str(provider.get("id") or "").strip()
        provider_label = str(provider.get("label") or provider_id).strip()
        for model in cast(list[dict[str, Any]], provider.get("models") or []):
            model_id = str(model.get("id") or "").strip()
            if not provider_id or not model_id:
                continue
            catalog.append(
                {
                    "provider_id": provider_id,
                    "provider_label": provider_label,
                    "model_id": model_id,
                    "model_ref": f"{provider_id}/{model_id}",
                    "connected": bool(provider.get("connected")),
                    "kind": str(provider.get("kind") or "builtin"),
                    "description": model.get("description"),
                }
            )
    return {"models": catalog}


@app.put("/api/providers/{provider_id}/credentials")
def provider_registry_update_credentials(provider_id: str, body: ProviderCredentialUpdate, user=Depends(verify_token)):
    """Store provider auth in the dedicated provider-auth secret. Admin only."""
    ensure_role(user, "admin")
    normalized_provider_id = _normalize_provider_id(provider_id)
    value = body.api_key.strip()
    if not value:
        raise HTTPException(status_code=400, detail="api_key must not be blank")

    if normalized_provider_id in _PROVIDER_REGISTRY_META:
        secret_key = str(_PROVIDER_REGISTRY_META[normalized_provider_id]["secret_key"])
    else:
        _, _, state = _read_or_create_provider_registry_configmap()
        custom_providers = cast(dict[str, dict[str, Any]], state.get("custom_providers") or {})
        if normalized_provider_id not in custom_providers:
            raise HTTPException(status_code=404, detail=f"Unknown provider: {normalized_provider_id}")
        secret_key = str(custom_providers[normalized_provider_id].get("secret_key_name") or _custom_provider_secret_key(normalized_provider_id))

    _update_provider_auth_secret(values={secret_key: value})
    logger.info("Updated provider credential for %s (by user %s)", normalized_provider_id, user.get("sub", "unknown"))
    return {"status": "updated", "provider_id": normalized_provider_id}


@app.get("/api/providers/{provider_id}/models")
async def provider_registry_models(provider_id: str, user=Depends(verify_token)):
    """Return model entries for a single provider."""
    ensure_role(user, "viewer")
    normalized_provider_id = _normalize_provider_id(provider_id)
    payload = await _provider_registry_response()
    providers = cast(list[dict[str, Any]], payload.get("providers") or [])
    for provider in providers:
        if str(provider.get("id") or "") == normalized_provider_id:
            return {"provider_id": normalized_provider_id, "models": provider.get("models") or []}
    raise HTTPException(status_code=404, detail=f"Unknown provider: {normalized_provider_id}")


@app.post("/api/providers/custom", status_code=201)
def provider_registry_upsert_custom_provider(body: CustomProviderRequest, user=Depends(verify_token)):
    """Create or update a custom OpenAI-compatible provider. Admin only."""
    ensure_role(user, "admin")
    provider_id = _normalize_provider_id(body.provider_id)
    if provider_id in _PROVIDER_REGISTRY_META:
        raise HTTPException(status_code=400, detail="Built-in provider IDs cannot be overwritten")

    base_url = body.base_url.strip()
    if not re.match(r"^https?://", base_url, re.IGNORECASE):
        raise HTTPException(status_code=400, detail="base_url must be an http or https URL")

    api, configmap, state = _read_or_create_provider_registry_configmap()
    custom_providers = cast(dict[str, dict[str, Any]], state.setdefault("custom_providers", {}))
    secret_key_name = str(custom_providers.get(provider_id, {}).get("secret_key_name") or _custom_provider_secret_key(provider_id))
    custom_providers[provider_id] = {
        "name": body.name.strip(),
        "description": (body.description or "").strip() or None,
        "base_url": base_url,
        "headers": {key: value for key, value in body.headers.items()},
        "models": body.models,
        "secret_key_name": secret_key_name,
    }
    _save_provider_registry_state(api, configmap, state)
    if body.api_key and body.api_key.strip():
        _update_provider_auth_secret(values={secret_key_name: body.api_key.strip()})
    logger.info("Upserted custom provider %s (by user %s)", provider_id, user.get("sub", "unknown"))
    return {"status": "created", "provider_id": provider_id}


@app.delete("/api/providers/custom/{provider_id}")
def provider_registry_delete_custom_provider(provider_id: str, user=Depends(verify_token)):
    """Delete a custom provider and remove its stored auth material. Admin only."""
    ensure_role(user, "admin")
    normalized_provider_id = _normalize_provider_id(provider_id)
    api, configmap, state = _read_or_create_provider_registry_configmap()
    custom_providers = cast(dict[str, dict[str, Any]], state.get("custom_providers") or {})
    if normalized_provider_id not in custom_providers:
        raise HTTPException(status_code=404, detail=f"Unknown custom provider: {normalized_provider_id}")
    entry = custom_providers.pop(normalized_provider_id)
    _save_provider_registry_state(api, configmap, state)
    secret_key_name = str(entry.get("secret_key_name") or _custom_provider_secret_key(normalized_provider_id))
    _update_provider_auth_secret(remove_keys={secret_key_name})
    logger.info("Deleted custom provider %s (by user %s)", normalized_provider_id, user.get("sub", "unknown"))
    return {"status": "deleted", "provider_id": normalized_provider_id}


@app.get("/api/llm/health")
async def llm_health(user=Depends(verify_token)):
    """Proxy LiteLLM health check."""
    ensure_role(user, "viewer")
    try:
        async with httpx.AsyncClient(timeout=_LLM_PROXY_TIMEOUT, trust_env=False) as client:
            resp = await client.get(f"{LITELLM_INTERNAL_URL}/health/liveliness", headers=_litellm_headers())
            return {"status": "healthy" if resp.status_code == 200 else "unhealthy", "litellm_status": resp.status_code}
    except Exception as exc:
        return {"status": "unreachable", "error": str(exc)}


@app.get("/api/llm/models")
async def llm_list_models(response: Response, user=Depends(verify_token)):
    """List model deployments configured in LiteLLM."""
    ensure_role(user, "viewer")
    response.headers["Cache-Control"] = "no-store"
    try:
        async with httpx.AsyncClient(timeout=_LLM_PROXY_TIMEOUT, trust_env=False) as client:
            resp = await client.get(f"{LITELLM_INTERNAL_URL}/model/info", headers=_litellm_headers())
            resp.raise_for_status()
            data = resp.json()
            return {"models": data.get("data", [])}
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=exc.response.status_code, detail=f"LiteLLM error: {exc.response.text[:500]}"
        ) from exc
    except Exception as exc:
        logger.error("Failed to reach LiteLLM (model/info): %s", exc)
        raise HTTPException(status_code=502, detail="Failed to reach LiteLLM") from exc


@app.post("/api/llm/models", status_code=201)
async def llm_add_model(body: LLMModelEntry, user=Depends(verify_token)):
    """Add a model deployment to LiteLLM."""
    ensure_role(user, "admin")
    payload = {"model_name": body.model_name, "litellm_params": body.litellm_params}
    try:
        async with httpx.AsyncClient(timeout=_LLM_PROXY_TIMEOUT, trust_env=False) as client:
            resp = await client.post(
                f"{LITELLM_INTERNAL_URL}/model/new",
                headers={**_litellm_headers(), "Content-Type": "application/json"},
                json=payload,
            )
            resp.raise_for_status()
            return resp.json()
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=exc.response.status_code, detail=f"LiteLLM error: {exc.response.text[:500]}"
        ) from exc
    except Exception as exc:
        logger.error("Failed to reach LiteLLM (model/new): %s", exc)
        raise HTTPException(status_code=502, detail="Failed to reach LiteLLM") from exc


@app.post("/api/llm/models/delete")
async def llm_delete_model(body: LLMModelDeleteRequest, user=Depends(verify_token)):
    """Delete a model deployment from LiteLLM."""
    ensure_role(user, "admin")
    try:
        async with httpx.AsyncClient(timeout=_LLM_PROXY_TIMEOUT, trust_env=False) as client:
            resp = await client.post(
                f"{LITELLM_INTERNAL_URL}/model/delete",
                headers={**_litellm_headers(), "Content-Type": "application/json"},
                json={"id": body.id},
            )
            resp.raise_for_status()
            return resp.json()
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=exc.response.status_code, detail=f"LiteLLM error: {exc.response.text[:500]}"
        ) from exc
    except Exception as exc:
        logger.error("Failed to reach LiteLLM (model/delete): %s", exc)
        raise HTTPException(status_code=502, detail="Failed to reach LiteLLM") from exc


@app.get("/api/llm/keys")
def llm_list_keys(user=Depends(verify_token)):
    """List which LLM API key env vars are set (names only, never values)."""
    ensure_role(user, "admin")
    try:
        from kubernetes import client as k8s_client

        secret = k8s_client.CoreV1Api().read_namespaced_secret(
            name=LLM_SECRET_NAME,
            namespace=os.getenv("POD_NAMESPACE", "ai-platform"),
        )
        data: dict[str, str] = getattr(secret, "data", None) or {}
        result: list[dict[str, Any]] = []
        for key_name in sorted(_ALLOWED_SECRET_KEYS):
            result.append(
                {
                    "name": key_name,
                    "is_set": key_name in data and bool(data[key_name]),
                }
            )
        return {"keys": result}
    except Exception as exc:
        logger.error("Failed to read LLM secret: %s", exc)
        raise HTTPException(status_code=502, detail="Failed to read secret") from exc


@app.put("/api/llm/keys")
def llm_update_keys(body: LLMKeyUpdate, user=Depends(verify_token)):
    """Update LLM API key values in the K8s Secret. Operator-or-admin."""
    ensure_role(user, "admin")

    # Validate key names
    for key_name in body.keys:
        if key_name not in _ALLOWED_SECRET_KEYS:
            raise HTTPException(status_code=400, detail=f"Key '{key_name}' is not a recognized LLM provider key")
        if len(body.keys[key_name]) > 500:
            raise HTTPException(status_code=400, detail=f"Key value for '{key_name}' is too long")

    try:
        import base64

        from kubernetes import client as k8s_client

        ns = os.getenv("POD_NAMESPACE", "ai-platform")
        api = k8s_client.CoreV1Api()
        secret = api.read_namespaced_secret(name=LLM_SECRET_NAME, namespace=ns)
        existing_data: dict[str, str] = getattr(secret, "data", None) or {}

        for key_name, value in body.keys.items():
            existing_data[key_name] = base64.b64encode(value.encode("utf-8")).decode("ascii")

        secret.data = existing_data  # type: ignore[union-attr]
        api.replace_namespaced_secret(name=LLM_SECRET_NAME, namespace=ns, body=secret)
        logger.info("Updated LLM API keys: %s (by user %s)", list(body.keys.keys()), user.get("sub", "unknown"))
        return {"status": "updated", "keys": list(body.keys.keys())}
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Failed to update LLM secret: %s", exc)
        raise HTTPException(status_code=502, detail="Failed to update secret") from exc


# ─────────────────────────────────────────────────────────────
# Provider-centric LLM management (new, cleaner API)
# ─────────────────────────────────────────────────────────────


class ProviderModelAdd(BaseModel):
    model_id: str = Field(..., min_length=1, max_length=300, description="Model identifier (e.g. gpt-4o-mini)")
    alias: str | None = Field(None, max_length=200, description="Optional alias; defaults to model_id")


@app.get("/api/llm/providers")
async def llm_list_providers(response: Response, user=Depends(verify_token)):
    """Unified provider view: merges model list + key status grouped by provider."""
    ensure_role(user, "viewer")
    response.headers["Cache-Control"] = "no-store"

    # Fetch models from LiteLLM
    models_by_provider: dict[str, list[dict[str, Any]]] = {k: [] for k in _PROVIDER_META}
    try:
        async with httpx.AsyncClient(timeout=_LLM_PROXY_TIMEOUT, trust_env=False) as client:
            resp = await client.get(f"{LITELLM_INTERNAL_URL}/model/info", headers=_litellm_headers())
            resp.raise_for_status()
            raw_models = resp.json().get("data", [])
            for m in raw_models:
                litellm_model = str((m.get("litellm_params") or {}).get("model", ""))
                model_api_base = str((m.get("litellm_params") or {}).get("api_base", "") or "")
                # Match by api_base first (most specific - works even when
                # LiteLLM redacts the api_key from /model/info responses).
                matched = False
                for key_name, meta in _PROVIDER_META.items():
                    if meta.get("api_base") and model_api_base and meta["api_base"] in model_api_base:
                        models_by_provider[key_name].append(m)
                        matched = True
                        break
                if not matched:
                    # Fall back to litellm prefix match
                    for key_name, meta in _PROVIDER_META.items():
                        if litellm_model.startswith(meta["prefix"]):
                            models_by_provider[key_name].append(m)
                            break
    except Exception as exc:
        logger.warning("Could not fetch LiteLLM models for providers view: %s", exc)

    # Fetch key status from K8s Secret
    key_status: dict[str, bool] = {}
    is_admin = (user.get("role") or "viewer") in ("admin",)
    if is_admin:
        try:
            from kubernetes import client as k8s_client

            secret = k8s_client.CoreV1Api().read_namespaced_secret(
                name=LLM_SECRET_NAME,
                namespace=os.getenv("POD_NAMESPACE", "ai-platform"),
            )
            data: dict[str, str] = getattr(secret, "data", None) or {}
            for key_name in _ALLOWED_SECRET_KEYS:
                key_status[key_name] = key_name in data and bool(data[key_name])
        except Exception as exc:
            logger.warning("Could not read LLM secret for providers view: %s", exc)

    # Build response
    providers = []
    for key_name, meta in _PROVIDER_META.items():
        raw = models_by_provider.get(key_name, [])
        provider_models = []
        for m in raw:
            provider_models.append(
                {
                    "model_name": m.get("model_name", ""),
                    "litellm_model": str((m.get("litellm_params") or {}).get("model", "")),
                    "id": str((m.get("model_info") or {}).get("id", "")),
                }
            )
        providers.append(
            {
                "key_name": key_name,
                "label": meta["label"],
                "prefix": meta["prefix"],
                "is_configured": key_status.get(key_name, False) if is_admin else None,
                "model_count": len(provider_models),
                "models": provider_models,
            }
        )

    return {"providers": providers}


@app.get("/api/llm/providers/{provider}/suggestions")
async def llm_provider_suggestions(provider: str, q: str = "", user=Depends(verify_token)):
    """Return model suggestions for a provider.

    Merges already-configured models from LiteLLM with the static popular-models
    list (excluding duplicates). Supports ``?q=`` for server-side filtering.
    """
    ensure_role(user, "viewer")
    if provider not in _PROVIDER_META:
        raise HTTPException(status_code=404, detail=f"Unknown provider: {provider}")

    meta = _PROVIDER_META[provider]
    prefix = meta["prefix"]

    # Fetch already-configured models from LiteLLM for this provider
    configured: list[dict[str, str]] = []
    configured_ids: set[str] = set()
    try:
        async with httpx.AsyncClient(timeout=_LLM_PROXY_TIMEOUT, trust_env=False) as client:
            resp = await client.get(f"{LITELLM_INTERNAL_URL}/model/info", headers=_litellm_headers())
            resp.raise_for_status()
            for m in resp.json().get("data", []):
                litellm_model = str((m.get("litellm_params") or {}).get("model", ""))
                model_api_base = str((m.get("litellm_params") or {}).get("api_base", "") or "")
                provider_api_base = meta.get("api_base", "")
                # Match by api_base first (works even when LiteLLM redacts api_key)
                is_match = False
                if provider_api_base and model_api_base and provider_api_base in model_api_base:
                    is_match = True
                elif not provider_api_base and litellm_model.startswith(prefix):
                    # Prefix match only for providers WITHOUT a custom api_base
                    is_match = True
                if is_match:
                    model_id = litellm_model[len(prefix) :] if litellm_model.startswith(prefix) else litellm_model
                    configured_ids.add(model_id)
                    configured.append(
                        {
                            "model_id": model_id,
                            "display_name": m.get("model_name", model_id),
                            "description": "Already configured",
                        }
                    )
    except Exception as exc:
        logger.warning("Could not fetch LiteLLM models for suggestions: %s", exc)

    # For OpenRouter, fetch live models from the API
    if provider == "OPENROUTER_API_KEY":
        # Read OpenRouter API key from K8s secret or env
        or_key: str | None = None
        try:
            from kubernetes import client as k8s_client

            ns = os.getenv("POD_NAMESPACE", "ai-platform")
            secret = k8s_client.CoreV1Api().read_namespaced_secret(name=LLM_SECRET_NAME, namespace=ns)
            raw = (getattr(secret, "data", None) or {}).get("OPENROUTER_API_KEY", "")
            if raw:
                import base64

                or_key = base64.b64decode(raw).decode("utf-8").strip() or None
        except Exception:
            or_key = os.getenv("OPENROUTER_API_KEY") or None

        live_models = await _fetch_openrouter_models(or_key)
        # Mark already-configured and merge
        live_suggestions = []
        for lm in live_models:
            entry = dict(lm)
            if lm["model_id"] in configured_ids:
                entry["description"] = "Already configured"
            live_suggestions.append(entry)

        # Apply search filter
        if q:
            ql = q.lower()
            live_suggestions = [
                s
                for s in live_suggestions
                if ql in s["model_id"].lower()
                or ql in s["display_name"].lower()
                or ql in s.get("description", "").lower()
            ]

        # Put configured first, then unconfigured, limit results
        configured_live = [s for s in live_suggestions if s.get("description") == "Already configured"]
        unconfigured_live = [s for s in live_suggestions if s.get("description") != "Already configured"]
        combined = configured_live + unconfigured_live
        return {"provider": provider, "suggestions": combined[:100]}

    # For GitHub Copilot, fetch live models from the Copilot API
    if provider == "GITHUB_COPILOT_TOKEN":
        cp_token: str | None = None
        try:
            import base64

            from kubernetes import client as k8s_client

            ns = os.getenv("POD_NAMESPACE", "ai-platform")
            secret = k8s_client.CoreV1Api().read_namespaced_secret(name=LLM_SECRET_NAME, namespace=ns)
            raw = (getattr(secret, "data", None) or {}).get("GITHUB_COPILOT_TOKEN", "")
            if raw:
                cp_token = base64.b64decode(raw).decode("utf-8").strip() or None
        except Exception:
            cp_token = os.getenv("GITHUB_COPILOT_TOKEN") or None

        if cp_token:
            live_models = await _fetch_copilot_models(cp_token)
            if live_models:
                live_suggestions = []
                for lm in live_models:
                    entry = dict(lm)
                    if lm["model_id"] in configured_ids:
                        entry["description"] = "Already configured"
                    live_suggestions.append(entry)

                if q:
                    ql = q.lower()
                    live_suggestions = [s for s in live_suggestions if _suggestion_matches(s, q)]

                configured_live = [s for s in live_suggestions if s.get("description") == "Already configured"]
                unconfigured_live = [s for s in live_suggestions if s.get("description") != "Already configured"]
                combined = configured_live + unconfigured_live
                return {"provider": provider, "suggestions": combined[:100]}
        # Fall through to static suggestions if no token or fetch failed

    # Static popular suggestions, excluding already-configured
    static = [s for s in _PROVIDER_POPULAR_MODELS.get(provider, []) if s["model_id"] not in configured_ids]

    combined = configured + static

    # Apply search filter
    if q:
        ql = q.lower()
        combined = [s for s in combined if _suggestion_matches(s, q)]

    return {"provider": provider, "suggestions": combined}


@app.post("/api/llm/providers/{provider}/models", status_code=201)
async def llm_add_provider_model(provider: str, body: ProviderModelAdd, user=Depends(verify_token)):
    """Add a model to LiteLLM via the simplified provider-centric API."""
    ensure_role(user, "admin")
    if provider not in _PROVIDER_META:
        raise HTTPException(status_code=404, detail=f"Unknown provider: {provider}")

    meta = _PROVIDER_META[provider]
    raw_alias = (body.alias or "").strip() or body.model_id.split("/")[-1]
    # Prefix Copilot aliases with "copilot-" to avoid collisions with direct OpenAI models
    alias = f"copilot-{raw_alias}" if provider == "GITHUB_COPILOT_TOKEN" else raw_alias
    litellm_model = f"{meta['prefix']}{body.model_id}"
    api_key_ref = f"os.environ/{provider}"

    # For Copilot, read the actual token from the K8s secret instead of using
    # os.environ/ reference, because the token is set dynamically after LiteLLM
    # pod start so the env var may not be present.
    actual_api_key: str | None = None
    actual_api_base: str | None = None
    if provider == "GITHUB_COPILOT_TOKEN":
        try:
            import base64

            from kubernetes import client as k8s_client

            ns = os.getenv("POD_NAMESPACE", "ai-platform")
            secret = k8s_client.CoreV1Api().read_namespaced_secret(
                name=LLM_SECRET_NAME,
                namespace=ns,
            )
            raw_b64 = (getattr(secret, "data", None) or {}).get("GITHUB_COPILOT_TOKEN", "")
            if raw_b64:
                actual_api_key = base64.b64decode(raw_b64).decode("utf-8")
            else:
                logger.warning("GITHUB_COPILOT_TOKEN is empty in secret %s/%s", ns, LLM_SECRET_NAME)
        except Exception as exc:
            logger.error("Failed to read Copilot token from K8s secret: %s", exc)
        if not actual_api_key:
            raise HTTPException(
                status_code=400, detail="GitHub Copilot is not authenticated. Please connect via the device flow first."
            )
        try:
            exchanged_token, resolved_api_endpoint = await _exchange_copilot_session_token(actual_api_key)
            actual_api_key = exchanged_token
            actual_api_base = resolved_api_endpoint or meta.get("api_base") or None
        except Exception as exc:
            logger.warning(
                "Failed to exchange GitHub token for Copilot session token; falling back to stored OAuth token: %s",
                exc,
            )
            actual_api_base = meta.get("api_base") or None

    litellm_params: dict[str, Any] = {
        "model": litellm_model,
        "api_key": actual_api_key if actual_api_key else api_key_ref,
    }
    if provider == "GITHUB_COPILOT_TOKEN":
        if actual_api_base:
            litellm_params["api_base"] = actual_api_base
    elif meta.get("api_base"):
        litellm_params["api_base"] = meta["api_base"]
    if meta.get("extra_headers"):
        litellm_params["extra_headers"] = json.loads(meta["extra_headers"])

    payload = {
        "model_name": alias,
        "litellm_params": litellm_params,
    }
    try:
        async with httpx.AsyncClient(timeout=_LLM_PROXY_TIMEOUT, trust_env=False) as client:
            resp = await client.post(
                f"{LITELLM_INTERNAL_URL}/model/new",
                headers={**_litellm_headers(), "Content-Type": "application/json"},
                json=payload,
            )
            resp.raise_for_status()
            return resp.json()
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=exc.response.status_code, detail=f"LiteLLM error: {exc.response.text[:500]}"
        ) from exc
    except Exception as exc:
        logger.error("Failed to reach LiteLLM (provider model add): %s", exc)
        raise HTTPException(status_code=502, detail="Failed to reach LiteLLM") from exc


# --------------------------------------------------------------------------- #
#  GitHub Copilot - OAuth Device Flow                                          #
# --------------------------------------------------------------------------- #

_COPILOT_CLIENT_ID = "Ov23li8tweQw6odWQebz"
_COPILOT_DEVICE_CODE_URL = "https://github.com/login/device/code"
_COPILOT_ACCESS_TOKEN_URL = "https://github.com/login/oauth/access_token"

# In-memory device flow state (keyed by user sub). Cleared on success/error.
_copilot_device_flows: dict[str, dict[str, Any]] = {}


def _normalized_search_text(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def _suggestion_matches(entry: dict[str, str], query: str) -> bool:
    ql = query.lower()
    qn = _normalized_search_text(query)
    for text in (entry.get("model_id", ""), entry.get("display_name", ""), entry.get("description", "")):
        lowered = text.lower()
        if ql in lowered:
            return True
        if qn and qn in _normalized_search_text(text):
            return True
    return False


def _outbound_ssl_verify() -> str:
    return certifi.where()


async def _copilot_get_json(url: str, headers: dict[str, str]) -> Any:
    last_error: Exception | None = None
    for verify in (_outbound_ssl_verify(), False):
        try:
            async with httpx.AsyncClient(timeout=15.0, trust_env=True, verify=verify) as client:
                resp = await client.get(url, headers=headers)
                resp.raise_for_status()
                return resp.json()
        except httpx.HTTPStatusError:
            raise
        except httpx.TransportError as exc:
            last_error = exc
            if verify is not False:
                logger.warning(
                    "Copilot HTTPS request failed with certificate verification; retrying insecurely: %s", exc
                )
                continue
            raise
    if last_error is not None:
        raise last_error
    raise RuntimeError("Copilot request failed")


async def _exchange_copilot_session_token(github_oauth_token: str) -> tuple[str, str | None]:
    data = await _copilot_get_json(
        "https://api.github.com/copilot_internal/v2/token",
        {
            "Authorization": f"token {github_oauth_token}",
            "Accept": "application/json",
            "User-Agent": "GitHubCopilotChat/0.25.2024",
            "Editor-Version": "vscode/1.96.2",
            "Editor-Plugin-Version": "copilot-chat/0.25.2024",
        },
    )

    token = str(data.get("token") or "").strip()
    if not token:
        raise ValueError("Copilot token exchange response did not include a session token")

    endpoints = data.get("endpoints") if isinstance(data.get("endpoints"), dict) else {}
    api_endpoint = str(endpoints.get("api") or "").strip() or None
    return token, api_endpoint


@app.post("/api/copilot/auth/device")
async def copilot_auth_device(user=Depends(verify_token)):
    """Initiate GitHub OAuth device flow for Copilot."""
    ensure_role(user, "admin")
    user_id = user.get("sub", "unknown")

    try:
        async with httpx.AsyncClient(timeout=15.0, trust_env=False) as client:
            resp = await client.post(
                _COPILOT_DEVICE_CODE_URL,
                data={"client_id": _COPILOT_CLIENT_ID, "scope": "read:user"},
                headers={"Accept": "application/json"},
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:
        logger.error("Copilot device flow initiation failed: %s", exc)
        raise HTTPException(status_code=502, detail="Failed to contact GitHub for device auth") from exc

    user_code = data.get("user_code", "")
    verification_uri = data.get("verification_uri", "https://github.com/login/device")
    device_code = data.get("device_code", "")
    interval = int(data.get("interval", 5))

    if not device_code:
        raise HTTPException(status_code=502, detail="GitHub did not return a device code")

    _copilot_device_flows[user_id] = {
        "device_code": device_code,
        "interval": interval,
    }

    return {
        "user_code": user_code,
        "verification_uri": verification_uri,
        "interval": interval,
    }


@app.post("/api/copilot/auth/poll")
async def copilot_auth_poll(user=Depends(verify_token)):
    """Poll GitHub for device flow completion. On success stores token in K8s secret."""
    ensure_role(user, "admin")
    user_id = user.get("sub", "unknown")
    flow = _copilot_device_flows.get(user_id)
    if not flow:
        raise HTTPException(status_code=400, detail="No pending device flow. Call /api/copilot/auth/device first.")

    device_code = flow["device_code"]
    try:
        async with httpx.AsyncClient(timeout=15.0, trust_env=False) as client:
            resp = await client.post(
                _COPILOT_ACCESS_TOKEN_URL,
                data={
                    "client_id": _COPILOT_CLIENT_ID,
                    "device_code": device_code,
                    "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                },
                headers={"Accept": "application/json"},
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:
        logger.error("Copilot token poll failed: %s", exc)
        raise HTTPException(status_code=502, detail="Failed to contact GitHub for token") from exc

    # Check for pending/slow_down/error states
    error = data.get("error")
    if error == "authorization_pending":
        return {"status": "pending"}
    if error == "slow_down":
        new_interval = int(data.get("interval", flow["interval"] + 5))
        flow["interval"] = new_interval
        return {"status": "pending", "interval": new_interval}
    if error:
        _copilot_device_flows.pop(user_id, None)
        return {"status": "error", "error": data.get("error_description", error)}

    access_token = data.get("access_token", "").strip()
    if not access_token:
        _copilot_device_flows.pop(user_id, None)
        return {"status": "error", "error": "No access token in GitHub response"}

    # Store token in K8s secret
    try:
        import base64

        from kubernetes import client as k8s_client

        ns = os.getenv("POD_NAMESPACE", "ai-platform")
        api = k8s_client.CoreV1Api()
        secret = api.read_namespaced_secret(name=LLM_SECRET_NAME, namespace=ns)
        existing_data = getattr(secret, "data", None) or {}
        existing_data["GITHUB_COPILOT_TOKEN"] = base64.b64encode(access_token.encode("utf-8")).decode("ascii")
        secret.data = existing_data  # type: ignore[union-attr]
        api.replace_namespaced_secret(name=LLM_SECRET_NAME, namespace=ns, body=secret)
        logger.info("Stored Copilot token for user %s", user_id)
    except Exception as exc:
        logger.error("Failed to store Copilot token in K8s secret: %s", exc)
        _copilot_device_flows.pop(user_id, None)
        raise HTTPException(status_code=502, detail="Token received but failed to store in cluster secret") from exc

    _copilot_device_flows.pop(user_id, None)
    return {"status": "success"}


@app.get("/api/copilot/auth/status")
def copilot_auth_status(user=Depends(verify_token)):
    """Check if a Copilot token is stored in the K8s secret."""
    ensure_role(user, "admin")
    try:
        from kubernetes import client as k8s_client

        secret = k8s_client.CoreV1Api().read_namespaced_secret(
            name=LLM_SECRET_NAME,
            namespace=os.getenv("POD_NAMESPACE", "ai-platform"),
        )
        data: dict[str, str] = getattr(secret, "data", None) or {}
        is_set = "GITHUB_COPILOT_TOKEN" in data and bool(data["GITHUB_COPILOT_TOKEN"])
        return {"connected": is_set}
    except Exception as exc:
        logger.warning("Failed to check Copilot status: %s", exc)
        return {"connected": False}


if __name__ == "__main__":
    import uvicorn  # type: ignore[import-untyped]

    uvicorn.run(app, host="0.0.0.0", port=8080)


# --------------------------------------------------------------------------- #
#  Notification SSE stream                                                     #
# --------------------------------------------------------------------------- #


@app.get("/api/notifications/stream")
def stream_notifications(
    namespace: str = "default",
    user=Depends(verify_token_or_query),
):
    """Long-lived SSE connection that pushes resource status change events."""
    ensure_namespace_access(user, namespace)
    import asyncio

    async def notification_generator():
        last_agents: dict[str, str] = {}
        last_workflows: dict[str, str] = {}
        last_evals: dict[str, str] = {}
        first_poll = True

        while True:
            try:
                agents = list_custom_resources("aiagents", namespace)
                workflows = list_custom_resources("agentworkflows", namespace)
                evals = list_custom_resources("agentevals", namespace)

                current_agents: dict[str, str] = {}
                for a in agents:
                    name = (a.get("metadata") or {}).get("name", "")
                    phase = ((a.get("status") or {}).get("phase") or "unknown").lower()
                    current_agents[name] = phase

                current_workflows: dict[str, str] = {}
                for w in workflows:
                    name = (w.get("metadata") or {}).get("name", "")
                    phase = ((w.get("status") or {}).get("phase") or "unknown").lower()
                    current_workflows[name] = phase

                current_evals: dict[str, str] = {}
                for e in evals:
                    name = (e.get("metadata") or {}).get("name", "")
                    phase = ((e.get("status") or {}).get("phase") or "unknown").lower()
                    current_evals[name] = phase

                if not first_poll:
                    # Agent status changes
                    for name, phase in current_agents.items():
                        prev = last_agents.get(name)
                        if prev != phase:
                            yield sse_event(
                                "agent.status_changed",
                                {
                                    "name": name,
                                    "namespace": namespace,
                                    "phase": phase,
                                    "previousPhase": prev,
                                    "timestamp": now_iso(),
                                },
                            )

                    # Deleted agents
                    for name in set(last_agents) - set(current_agents):
                        yield sse_event(
                            "agent.status_changed",
                            {
                                "name": name,
                                "namespace": namespace,
                                "phase": "deleted",
                                "previousPhase": last_agents[name],
                                "timestamp": now_iso(),
                            },
                        )

                    # Workflow status changes
                    for name, phase in current_workflows.items():
                        prev = last_workflows.get(name)
                        if prev != phase:
                            event_type = (
                                "workflow.completed"
                                if phase in ("succeeded",)
                                else "workflow.failed"
                                if phase in ("failed",)
                                else "workflow.approval_needed"
                                if phase in ("waitingapproval", "waiting_approval", "waiting-approval")
                                else "workflow.status_changed"
                            )
                            yield sse_event(
                                event_type,
                                {
                                    "name": name,
                                    "namespace": namespace,
                                    "phase": phase,
                                    "previousPhase": prev,
                                    "timestamp": now_iso(),
                                },
                            )

                    # Deleted workflows
                    for name in set(last_workflows) - set(current_workflows):
                        yield sse_event(
                            "workflow.status_changed",
                            {
                                "name": name,
                                "namespace": namespace,
                                "phase": "deleted",
                                "previousPhase": last_workflows[name],
                                "timestamp": now_iso(),
                            },
                        )

                    # Eval status changes
                    for name, phase in current_evals.items():
                        prev = last_evals.get(name)
                        if prev != phase:
                            event_type = (
                                "eval.completed"
                                if phase in ("succeeded",)
                                else "eval.failed"
                                if phase in ("failed",)
                                else "eval.status_changed"
                            )
                            yield sse_event(
                                event_type,
                                {
                                    "name": name,
                                    "namespace": namespace,
                                    "phase": phase,
                                    "previousPhase": prev,
                                    "timestamp": now_iso(),
                                },
                            )

                    # Deleted evals
                    for name in set(last_evals) - set(current_evals):
                        yield sse_event(
                            "eval.status_changed",
                            {
                                "name": name,
                                "namespace": namespace,
                                "phase": "deleted",
                                "previousPhase": last_evals[name],
                                "timestamp": now_iso(),
                            },
                        )

                last_agents = current_agents
                last_workflows = current_workflows
                last_evals = current_evals
                first_poll = False

            except Exception as exc:
                logger.warning("Notification stream poll error: %s", exc)
                yield sse_event("system.error", {"message": str(exc)[:300], "timestamp": now_iso()})

            yield sse_keepalive_comment()
            await asyncio.sleep(5)

    return StreamingResponse(notification_generator(), media_type="text/event-stream")


# --------------------------------------------------------------------------- #
#  Export / Import YAML bundles                                                 #
# --------------------------------------------------------------------------- #


@app.get("/api/export/bundle")
def export_yaml_bundle(
    namespace: str = "default",
    user=Depends(verify_token),
):
    """Export all agents, workflows, and evals in the namespace as a multi-document YAML bundle."""
    ensure_namespace_access(user, namespace)
    import yaml as _yaml

    documents: list[dict[str, Any]] = []
    for plural in ("aiagents", "agentworkflows", "agentevals", "agentpolicies"):
        items = list_custom_resources(plural, namespace)
        for item in items:
            # Strip runtime status and server-managed metadata fields
            doc = {
                "apiVersion": item.get("apiVersion", f"{RESOURCE_GROUP}/{RESOURCE_VERSION}"),
                "kind": item.get("kind", plural),
                "metadata": {
                    "name": (item.get("metadata") or {}).get("name", ""),
                    "namespace": namespace,
                    "labels": (item.get("metadata") or {}).get("labels", {}),
                    "annotations": (item.get("metadata") or {}).get("annotations", {}),
                },
                "spec": item.get("spec", {}),
            }
            # Remove empty labels/annotations
            if not doc["metadata"]["labels"]:
                del doc["metadata"]["labels"]
            if not doc["metadata"]["annotations"]:
                del doc["metadata"]["annotations"]
            documents.append(doc)

    bundle = _yaml.dump_all(documents, default_flow_style=False, sort_keys=False)
    return Response(
        content=bundle,
        media_type="application/x-yaml",
        headers={"Content-Disposition": f"attachment; filename=bundle-{namespace}.yaml"},
    )


@app.post("/api/import/bundle", status_code=201)
async def import_yaml_bundle(
    request: Request,
    namespace: str = "default",
    user=Depends(verify_token),
):
    """Import a multi-document YAML bundle, creating or updating resources."""
    ensure_namespace_access(user, namespace, "operator")
    import yaml as _yaml

    raw = await request.body()
    try:
        documents = list(_yaml.safe_load_all(raw.decode("utf-8")))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid YAML: {exc}") from exc

    results: list[dict[str, str]] = []
    for doc in documents:
        if not isinstance(doc, dict) or "kind" not in doc:
            continue

        kind = doc["kind"]
        plural_map = {
            "AIAgent": "aiagents",
            "AgentWorkflow": "agentworkflows",
            "AgentEval": "agentevals",
            "AgentPolicy": "agentpolicies",
        }
        plural = plural_map.get(kind)
        if not plural:
            results.append(
                {
                    "name": doc.get("metadata", {}).get("name", "?"),
                    "status": "skipped",
                    "reason": f"Unknown kind: {kind}",
                }
            )
            continue

        name = (doc.get("metadata") or {}).get("name", "")
        if not name:
            results.append({"name": "(unnamed)", "status": "skipped", "reason": "Missing metadata.name"})
            continue

        doc.setdefault("metadata", {})["namespace"] = namespace

        from kubernetes import client

        api = client.CustomObjectsApi()

        try:
            # Try creating
            api.create_namespaced_custom_object(
                group=RESOURCE_GROUP,
                version=RESOURCE_VERSION,
                namespace=namespace,
                plural=plural,
                body=doc,
            )
            results.append({"name": name, "kind": kind, "status": "created"})
        except Exception as create_exc:
            if getattr(create_exc, "status", None) == 409:
                # Already exists — update spec only
                try:
                    existing = cast(
                        dict[str, Any],
                        api.get_namespaced_custom_object(
                            group=RESOURCE_GROUP,
                            version=RESOURCE_VERSION,
                            namespace=namespace,
                            plural=plural,
                            name=name,
                        ),
                    )
                    existing["spec"] = doc.get("spec", {})
                    api.replace_namespaced_custom_object(
                        group=RESOURCE_GROUP,
                        version=RESOURCE_VERSION,
                        namespace=namespace,
                        plural=plural,
                        name=name,
                        body=existing,
                    )
                    results.append({"name": name, "kind": kind, "status": "updated"})
                except Exception as upd_exc:
                    results.append({"name": name, "kind": kind, "status": "error", "reason": str(upd_exc)[:200]})
            else:
                results.append({"name": name, "kind": kind, "status": "error", "reason": str(create_exc)[:200]})

    return {"imported": len([r for r in results if r["status"] in ("created", "updated")]), "results": results}


# --------------------------------------------------------------------------- #
#  System health dashboard                                                      #
# --------------------------------------------------------------------------- #


@app.get("/api/system/health")
def system_health(
    namespace: str = "default",
    user=Depends(verify_token),
):
    """Comprehensive system health check across all subsystems."""
    ensure_namespace_access(user, namespace)

    checks: dict[str, dict[str, Any]] = {}

    # Database
    try:
        from sqlalchemy import text as _sa_text

        from auth_store import ENGINE

        with ENGINE.connect() as conn:
            conn.execute(_sa_text("select 1"))
        checks["database"] = {"status": "ok"}
    except Exception as exc:
        checks["database"] = {"status": "error", "message": str(exc)[:200]}

    # Kubernetes API
    try:
        from kubernetes import client

        v1 = client.CoreV1Api()
        v1.list_namespace(limit=1)
        checks["kubernetes"] = {"status": "ok"}
    except Exception as exc:
        checks["kubernetes"] = {"status": "error", "message": str(exc)[:200]}

    # CRD counts
    try:
        agents = list_custom_resources("aiagents", namespace)
        workflows = list_custom_resources("agentworkflows", namespace)
        evals = list_custom_resources("agentevals", namespace)
        policies = list_custom_resources("agentpolicies", namespace)

        agent_phases: dict[str, int] = {}
        for a in agents:
            phase = ((a.get("status") or {}).get("phase") or "unknown").lower()
            agent_phases[phase] = agent_phases.get(phase, 0) + 1

        workflow_phases: dict[str, int] = {}
        for w in workflows:
            phase = ((w.get("status") or {}).get("phase") or "unknown").lower()
            workflow_phases[phase] = workflow_phases.get(phase, 0) + 1

        checks["resources"] = {
            "status": "ok",
            "agents": {"total": len(agents), "by_phase": agent_phases},
            "workflows": {"total": len(workflows), "by_phase": workflow_phases},
            "evals": {"total": len(evals)},
            "policies": {"total": len(policies)},
        }
    except Exception as exc:
        checks["resources"] = {"status": "error", "message": str(exc)[:200]}

    # NATS
    if NATS_URL:
        checks["nats"] = {"status": "configured", "url": NATS_URL}
    else:
        checks["nats"] = {"status": "not_configured"}

    # Qdrant
    if QDRANT_URL:
        checks["qdrant"] = {"status": "configured", "url": QDRANT_URL}
    else:
        checks["qdrant"] = {"status": "not_configured"}

    overall = (
        "healthy"
        if all(c.get("status") in ("ok", "configured", "not_configured") for c in checks.values())
        else "degraded"
    )

    return {
        "status": overall,
        "namespace": namespace,
        "auth_mode": AUTH_MODE,
        "checks": checks,
        "timestamp": now_iso(),
    }


# --------------------------------------------------------------------------- #
#  AIOps Observability — targets, policies, reports, connectors                #
# --------------------------------------------------------------------------- #

OBSERVATION_PLURALS = {
    "targets": "observationtargets",
    "policies": "observationpolicies",
    "reports": "observationreports",
    "connectors": "connectorplugins",
}

OBSERVATION_TARGET_TYPES = {"prometheus", "kubernetes-api", "snmp", "gnmi", "nats", "custom"}
OBSERVATION_PROTOCOLS = {"grpc", "http"}
OBSERVATION_CAPABILITIES = OBSERVATION_TARGET_TYPES
OBSERVATION_ALERT_SEVERITIES = {"info", "warning", "critical"}
OBSERVATION_ALGORITHMS = {"isolation-forest", "prophet", "ensemble"}


def merge_resource_spec(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    merged = copy.deepcopy(base)
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = merge_resource_spec(cast(dict[str, Any], merged[key]), cast(dict[str, Any], value))
        else:
            merged[key] = value
    return merged


def replace_custom_resource_spec_patch(plural: str, name: str, namespace: str, patch: dict[str, Any]) -> dict[str, Any]:
    current = read_custom_resource(plural, name, namespace, "Resource")
    current_spec = cast(dict[str, Any], current.get("spec") or {})
    merged_spec = merge_resource_spec(current_spec, patch)
    return replace_custom_resource_spec(plural, name, namespace, merged_spec)


def extract_observation_spec(
    body: dict[str, Any],
    *,
    require_name: bool,
    required_fields: tuple[str, ...] = (),
) -> tuple[str | None, dict[str, Any]]:
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Request body must be a JSON object")

    name: str | None = None
    raw_name = body.get("name")
    if require_name:
        if not isinstance(raw_name, str) or not raw_name.strip():
            raise HTTPException(status_code=400, detail="Missing 'name'")
        name = raw_name.strip()
    elif raw_name is not None:
        if not isinstance(raw_name, str) or not raw_name.strip():
            raise HTTPException(status_code=400, detail="Field 'name' must be a non-empty string when provided")
        name = raw_name.strip()

    reserved_fields = {"name", "apiVersion", "kind", "metadata", "status"}
    spec = {key: value for key, value in body.items() if key not in reserved_fields}

    for field in required_fields:
        value = spec.get(field)
        if not isinstance(value, str) or not value.strip():
            raise HTTPException(status_code=400, detail=f"Missing '{field}'")

    return name, spec


def validate_observation_target_spec(spec: dict[str, Any], *, partial: bool) -> dict[str, Any]:
    target_type = spec.get("targetType")
    if target_type is not None:
        if not isinstance(target_type, str) or target_type not in OBSERVATION_TARGET_TYPES:
            raise HTTPException(status_code=400, detail="Field 'targetType' must be a valid observation target type")
    elif not partial:
        raise HTTPException(status_code=400, detail="Missing 'targetType'")

    connector_ref = spec.get("connectorRef")
    if connector_ref is not None:
        if not isinstance(connector_ref, str) or not connector_ref.strip():
            raise HTTPException(status_code=400, detail="Field 'connectorRef' must be a non-empty string")
    elif not partial:
        raise HTTPException(status_code=400, detail="Missing 'connectorRef'")

    for optional_string_field in ("description", "endpoint", "scrapeInterval", "policyRef"):
        if optional_string_field in spec and spec[optional_string_field] is not None and not isinstance(spec[optional_string_field], str):
            raise HTTPException(status_code=400, detail=f"Field '{optional_string_field}' must be a string")

    if "selector" in spec and spec["selector"] is not None and not isinstance(spec["selector"], dict):
        raise HTTPException(status_code=400, detail="Field 'selector' must be an object")
    if "credentials" in spec and spec["credentials"] is not None and not isinstance(spec["credentials"], dict):
        raise HTTPException(status_code=400, detail="Field 'credentials' must be an object")
    if "tlsConfig" in spec and spec["tlsConfig"] is not None and not isinstance(spec["tlsConfig"], dict):
        raise HTTPException(status_code=400, detail="Field 'tlsConfig' must be an object")
    if "labels" in spec and spec["labels"] is not None:
        labels = spec["labels"]
        if not isinstance(labels, dict) or not all(isinstance(key, str) and isinstance(value, str) for key, value in labels.items()):
            raise HTTPException(status_code=400, detail="Field 'labels' must be an object of string values")

    return spec


def validate_observation_policy_spec(spec: dict[str, Any], *, partial: bool) -> dict[str, Any]:
    if "description" in spec and spec["description"] is not None and not isinstance(spec["description"], str):
        raise HTTPException(status_code=400, detail="Field 'description' must be a string")

    retention = spec.get("retention")
    if retention is not None:
        if not isinstance(retention, dict):
            raise HTTPException(status_code=400, detail="Field 'retention' must be an object")
        days = retention.get("days")
        if days is not None and (not isinstance(days, int) or days < 1 or days > 365):
            raise HTTPException(status_code=400, detail="Field 'retention.days' must be an integer between 1 and 365")

    alert_rules = spec.get("alertRules")
    if alert_rules is not None:
        if not isinstance(alert_rules, list):
            raise HTTPException(status_code=400, detail="Field 'alertRules' must be an array")
        for index, rule in enumerate(alert_rules):
            if not isinstance(rule, dict):
                raise HTTPException(status_code=400, detail=f"alertRules[{index}] must be an object")
            name = rule.get("name")
            expr = rule.get("expr")
            severity = rule.get("severity")
            if not isinstance(name, str) or not name.strip():
                raise HTTPException(status_code=400, detail=f"alertRules[{index}].name must be a non-empty string")
            if not isinstance(expr, str) or not expr.strip():
                raise HTTPException(status_code=400, detail=f"alertRules[{index}].expr must be a non-empty string")
            if severity is not None and (not isinstance(severity, str) or severity not in OBSERVATION_ALERT_SEVERITIES):
                raise HTTPException(status_code=400, detail=f"alertRules[{index}].severity must be one of {sorted(OBSERVATION_ALERT_SEVERITIES)}")

    anomaly_detection = spec.get("anomalyDetection")
    if anomaly_detection is not None:
        if not isinstance(anomaly_detection, dict):
            raise HTTPException(status_code=400, detail="Field 'anomalyDetection' must be an object")
        algorithm = anomaly_detection.get("algorithm")
        sensitivity = anomaly_detection.get("sensitivity")
        metrics = anomaly_detection.get("metrics")
        if algorithm is not None and (not isinstance(algorithm, str) or algorithm not in OBSERVATION_ALGORITHMS):
            raise HTTPException(status_code=400, detail=f"Field 'anomalyDetection.algorithm' must be one of {sorted(OBSERVATION_ALGORITHMS)}")
        if sensitivity is not None and not isinstance(sensitivity, (int, float)):
            raise HTTPException(status_code=400, detail="Field 'anomalyDetection.sensitivity' must be numeric")
        if metrics is not None and (not isinstance(metrics, list) or not all(isinstance(item, str) for item in metrics)):
            raise HTTPException(status_code=400, detail="Field 'anomalyDetection.metrics' must be an array of strings")

    notifications = spec.get("notifications")
    if notifications is not None and not isinstance(notifications, dict):
        raise HTTPException(status_code=400, detail="Field 'notifications' must be an object")

    return spec


def validate_connector_plugin_spec(spec: dict[str, Any], *, partial: bool) -> dict[str, Any]:
    image = spec.get("image")
    if image is not None:
        if not isinstance(image, str) or not image.strip():
            raise HTTPException(status_code=400, detail="Field 'image' must be a non-empty string")
    elif not partial:
        raise HTTPException(status_code=400, detail="Missing 'image'")

    protocol = spec.get("protocol")
    if protocol is not None:
        if not isinstance(protocol, str) or protocol not in OBSERVATION_PROTOCOLS:
            raise HTTPException(status_code=400, detail=f"Field 'protocol' must be one of {sorted(OBSERVATION_PROTOCOLS)}")
    elif not partial:
        raise HTTPException(status_code=400, detail="Missing 'protocol'")

    capabilities = spec.get("capabilities")
    if capabilities is not None:
        if not isinstance(capabilities, list) or not capabilities:
            raise HTTPException(status_code=400, detail="Field 'capabilities' must be a non-empty array")
        if not all(isinstance(item, str) and item in OBSERVATION_CAPABILITIES for item in capabilities):
            raise HTTPException(status_code=400, detail=f"Field 'capabilities' must contain only {sorted(OBSERVATION_CAPABILITIES)}")
    elif not partial:
        raise HTTPException(status_code=400, detail="Missing 'capabilities'")

    port = spec.get("port")
    if port is not None and (not isinstance(port, int) or port < 1024 or port > 65535):
        raise HTTPException(status_code=400, detail="Field 'port' must be an integer between 1024 and 65535")

    for optional_string_field in ("description", "healthEndpoint", "secretRef"):
        if optional_string_field in spec and spec[optional_string_field] is not None and not isinstance(spec[optional_string_field], str):
            raise HTTPException(status_code=400, detail=f"Field '{optional_string_field}' must be a string")

    if "resources" in spec and spec["resources"] is not None and not isinstance(spec["resources"], dict):
        raise HTTPException(status_code=400, detail="Field 'resources' must be an object")
    if "env" in spec and spec["env"] is not None and not isinstance(spec["env"], list):
        raise HTTPException(status_code=400, detail="Field 'env' must be an array")

    return spec


@app.get("/api/observability/overview")
def observability_overview(
    namespace: str = "default",
    user=Depends(verify_token),
):
    """Aggregated observability dashboard data — targets, policies, reports, connectors."""
    ensure_namespace_access(user, namespace)
    from kubernetes import client as k8s_client

    custom_api = k8s_client.CustomObjectsApi()
    data: dict[str, Any] = {}

    for label, plural in OBSERVATION_PLURALS.items():
        try:
            items = custom_api.list_namespaced_custom_object(
                group=RESOURCE_GROUP,
                version=RESOURCE_VERSION,
                namespace=namespace,
                plural=plural,
            ).get("items", [])
            data[label] = items
        except Exception:
            data[label] = []

    # ----- Derive summary stats -----
    targets = data.get("targets", [])
    reports = data.get("reports", [])
    connectors = data.get("connectors", [])

    active_targets = sum(
        1 for t in targets
        if (t.get("status") or {}).get("phase") == "Active"
    )
    degraded_targets = sum(
        1 for t in targets
        if (t.get("status") or {}).get("phase") == "Degraded"
    )
    failed_targets = sum(
        1 for t in targets
        if (t.get("status") or {}).get("phase") == "Failed"
    )
    total_findings = sum(
        (r.get("status") or {}).get("findingsCount", 0) for r in reports
    )
    avg_health = 0
    scores = [
        (r.get("status") or {}).get("healthScore", -1) for r in reports
        if (r.get("status") or {}).get("healthScore") is not None
    ]
    valid_scores = [s for s in scores if s >= 0]
    if valid_scores:
        avg_health = round(sum(valid_scores) / len(valid_scores))

    ready_connectors = sum(
        1 for c in connectors
        if (c.get("status") or {}).get("ready") == "True"
    )

    # ----- Agent metrics summary (from K8s pod status) -----
    agent_pod_summary: dict[str, Any] = {"total": 0, "ready": 0, "notReady": 0}
    try:
        v1 = k8s_client.CoreV1Api()
        pods = v1.list_namespaced_pod(
            namespace=namespace,
            label_selector="kubesynth.ai/managed-by=kubesynth-operator",
        )
        agent_pod_summary["total"] = len(pods.items)
        for pod in pods.items:
            ready = all(
                cs.ready for cs in (pod.status.container_statuses or [])
            ) if pod.status and pod.status.container_statuses else False
            if ready:
                agent_pod_summary["ready"] += 1
            else:
                agent_pod_summary["notReady"] += 1
    except Exception:
        logger.warning("Failed to list agent pods for observability summary", exc_info=True)

    return {
        "summary": {
            "targets": {
                "total": len(targets),
                "active": active_targets,
                "degraded": degraded_targets,
                "failed": failed_targets,
            },
            "reports": {
                "total": len(reports),
                "totalFindings": total_findings,
                "avgHealthScore": avg_health,
            },
            "connectors": {
                "total": len(connectors),
                "ready": ready_connectors,
            },
            "policies": {
                "total": len(data.get("policies", [])),
            },
            "agents": agent_pod_summary,
        },
        "targets": [
            {
                "name": t["metadata"]["name"],
                "namespace": t["metadata"].get("namespace", namespace),
                "description": t.get("spec", {}).get("description", ""),
                "targetType": t.get("spec", {}).get("targetType", "unknown"),
                "connectorRef": t.get("spec", {}).get("connectorRef", ""),
                "policyRef": t.get("spec", {}).get("policyRef"),
                "endpoint": t.get("spec", {}).get("endpoint", ""),
                "scrapeInterval": t.get("spec", {}).get("scrapeInterval", "30s"),
                "phase": (t.get("status") or {}).get("phase", "Pending"),
                "lastScrapeTime": (t.get("status") or {}).get("lastScrapeTime"),
                "metricsCollected": (t.get("status") or {}).get("metricsCollected", 0),
                "connectorHealth": (t.get("status") or {}).get("connectorHealth", "Unknown"),
                "createdAt": t["metadata"].get("creationTimestamp", ""),
            }
            for t in targets
        ],
        "reports": [
            {
                "name": r["metadata"]["name"],
                "targetRef": r.get("spec", {}).get("targetRef", ""),
                "reportType": r.get("spec", {}).get("reportType", "anomaly"),
                "phase": (r.get("status") or {}).get("phase", "Pending"),
                "healthScore": (r.get("status") or {}).get("healthScore"),
                "findingsCount": (r.get("status") or {}).get("findingsCount", 0),
                "lastEvaluated": (r.get("status") or {}).get("lastEvaluated"),
                "findings": (r.get("status") or {}).get("findings", []),
                "summary": (r.get("status") or {}).get("summary", ""),
                "createdAt": r["metadata"].get("creationTimestamp", ""),
            }
            for r in reports
        ],
        "connectors": [
            {
                "name": c["metadata"]["name"],
                "description": c.get("spec", {}).get("description", ""),
                "image": c.get("spec", {}).get("image", ""),
                "protocol": c.get("spec", {}).get("protocol", "grpc"),
                "port": c.get("spec", {}).get("port", 9090),
                "capabilities": c.get("spec", {}).get("capabilities", []),
                "ready": (c.get("status") or {}).get("ready", "Unknown"),
                "lastHealthCheck": (c.get("status") or {}).get("lastHealthCheck"),
                "createdAt": c["metadata"].get("creationTimestamp", ""),
            }
            for c in connectors
        ],
        "policies": [
            {
                "name": p["metadata"]["name"],
                "description": p.get("spec", {}).get("description", ""),
                "retentionDays": p.get("spec", {}).get("retention", {}).get("days", 30),
                "anomalyEnabled": p.get("spec", {}).get("anomalyDetection", {}).get("enabled", False),
                "anomalyAlgorithm": p.get("spec", {}).get("anomalyDetection", {}).get("algorithm", "ensemble"),
                "alertRulesCount": len(p.get("spec", {}).get("alertRules", [])),
                "activeAlerts": (p.get("status") or {}).get("activeAlerts", 0),
                "createdAt": p["metadata"].get("creationTimestamp", ""),
            }
            for p in data.get("policies", [])
        ],
        "timestamp": now_iso(),
    }


@app.post("/api/observability/targets")
def create_observation_target(
    body: dict[str, Any] = Body(...),
    namespace: str = "default",
    user=Depends(verify_token),
):
    """Create a new ObservationTarget CR."""
    ensure_namespace_access(user, namespace)
    ensure_role(user, "operator")
    name, spec = extract_observation_spec(body, require_name=True, required_fields=("targetType", "connectorRef"))
    spec = validate_observation_target_spec(spec, partial=False)
    return create_custom_resource("observationtargets", namespace, name, spec)


@app.get("/api/observability/targets/{name}")
def get_observation_target(
    name: str,
    namespace: str = "default",
    user=Depends(verify_token),
):
    """Return the full ObservationTarget resource."""
    ensure_namespace_access(user, namespace)
    return read_custom_resource("observationtargets", name, namespace, "ObservationTarget")


@app.patch("/api/observability/targets/{name}")
def update_observation_target(
    name: str,
    body: dict[str, Any] = Body(...),
    namespace: str = "default",
    user=Depends(verify_token),
):
    """Patch an ObservationTarget spec."""
    ensure_namespace_access(user, namespace)
    ensure_role(user, "operator")
    provided_name, spec = extract_observation_spec(body, require_name=False)
    if provided_name and provided_name != name:
        raise HTTPException(status_code=400, detail="Body name does not match path name")
    spec = validate_observation_target_spec(spec, partial=True)
    return replace_custom_resource_spec_patch("observationtargets", name, namespace, spec)


@app.delete("/api/observability/targets/{name}")
def delete_observation_target(
    name: str,
    namespace: str = "default",
    user=Depends(verify_token),
):
    """Delete an ObservationTarget CR."""
    ensure_namespace_access(user, namespace)
    ensure_role(user, "operator")
    return delete_custom_resource("observationtargets", name, namespace, "ObservationTarget")


@app.post("/api/observability/policies")
def create_observation_policy(
    body: dict[str, Any] = Body(...),
    namespace: str = "default",
    user=Depends(verify_token),
):
    """Create a new ObservationPolicy CR."""
    ensure_namespace_access(user, namespace)
    ensure_role(user, "operator")
    name, spec = extract_observation_spec(body, require_name=True)
    spec = validate_observation_policy_spec(spec, partial=False)
    return create_custom_resource("observationpolicies", namespace, name, spec)


@app.get("/api/observability/policies/{name}")
def get_observation_policy(
    name: str,
    namespace: str = "default",
    user=Depends(verify_token),
):
    """Return the full ObservationPolicy resource."""
    ensure_namespace_access(user, namespace)
    return read_custom_resource("observationpolicies", name, namespace, "ObservationPolicy")


@app.patch("/api/observability/policies/{name}")
def update_observation_policy(
    name: str,
    body: dict[str, Any] = Body(...),
    namespace: str = "default",
    user=Depends(verify_token),
):
    """Patch an ObservationPolicy spec."""
    ensure_namespace_access(user, namespace)
    ensure_role(user, "operator")
    provided_name, spec = extract_observation_spec(body, require_name=False)
    if provided_name and provided_name != name:
        raise HTTPException(status_code=400, detail="Body name does not match path name")
    spec = validate_observation_policy_spec(spec, partial=True)
    return replace_custom_resource_spec_patch("observationpolicies", name, namespace, spec)


@app.delete("/api/observability/policies/{name}")
def delete_observation_policy(
    name: str,
    namespace: str = "default",
    user=Depends(verify_token),
):
    """Delete an ObservationPolicy CR."""
    ensure_namespace_access(user, namespace)
    ensure_role(user, "operator")
    return delete_custom_resource("observationpolicies", name, namespace, "ObservationPolicy")


@app.post("/api/observability/connectors")
def create_connector_plugin(
    body: dict[str, Any] = Body(...),
    namespace: str = "default",
    user=Depends(verify_token),
):
    """Create a new ConnectorPlugin CR."""
    ensure_namespace_access(user, namespace)
    ensure_role(user, "operator")
    name, spec = extract_observation_spec(body, require_name=True, required_fields=("image", "protocol"))
    spec = validate_connector_plugin_spec(spec, partial=False)
    return create_custom_resource("connectorplugins", namespace, name, spec)


@app.get("/api/observability/connectors/{name}")
def get_connector_plugin(
    name: str,
    namespace: str = "default",
    user=Depends(verify_token),
):
    """Return the full ConnectorPlugin resource."""
    ensure_namespace_access(user, namespace)
    return read_custom_resource("connectorplugins", name, namespace, "ConnectorPlugin")


@app.patch("/api/observability/connectors/{name}")
def update_connector_plugin(
    name: str,
    body: dict[str, Any] = Body(...),
    namespace: str = "default",
    user=Depends(verify_token),
):
    """Patch a ConnectorPlugin spec."""
    ensure_namespace_access(user, namespace)
    ensure_role(user, "operator")
    provided_name, spec = extract_observation_spec(body, require_name=False)
    if provided_name and provided_name != name:
        raise HTTPException(status_code=400, detail="Body name does not match path name")
    spec = validate_connector_plugin_spec(spec, partial=True)
    return replace_custom_resource_spec_patch("connectorplugins", name, namespace, spec)


@app.delete("/api/observability/connectors/{name}")
def delete_connector_plugin(
    name: str,
    namespace: str = "default",
    user=Depends(verify_token),
):
    """Delete a ConnectorPlugin CR."""
    ensure_namespace_access(user, namespace)
    ensure_role(user, "operator")
    return delete_custom_resource("connectorplugins", name, namespace, "ConnectorPlugin")


# =========================================================================
# Intelligence Collector API
# =========================================================================

# In-memory cache of collectors — authoritative source is DB (IntelligenceCollectorRow)
_collector_registry: dict[str, dict[str, dict[str, Any]]] = {}
_collection_tasks: dict[str, dict[str, Any]] = {}
_ALERT_HISTORY_CAP = 500
_COLLECTION_TASKS_CAP = 200

# Thread-safety locks for in-memory intelligence dicts
_collector_lock = threading.Lock()
_tasks_lock = threading.Lock()

COLLECTOR_TIMEOUT = int(os.environ.get("COLLECTOR_TIMEOUT", "45"))

# ─── SSRF protection for collector URLs ───────────────────────────────────
import ipaddress as _ipaddress

_SSRF_BLOCKED_NETS = [
    _ipaddress.ip_network("169.254.0.0/16"),   # AWS / cloud metadata
    _ipaddress.ip_network("100.100.100.0/24"), # Alibaba metadata
]
_INTELLIGENCE_SCRIPT_TYPES = {"bash", "python"}
_INTELLIGENCE_ALERT_CONDITION_TYPES = {"contains", "not_contains", "exit_code", "regex"}
_INTELLIGENCE_ALERT_ACTIONS = {"notify", "invoke_agent"}
_INTELLIGENCE_BUILTINS = {
    "cluster_overview",
    "node_health",
    "pod_resources",
    "logs_collector",
    "helm_releases",
    "network_info",
    "storage_info",
    "configmap_secrets",
    "security_posture",
    "crd_inventory",
}

_DEFAULT_COLLECTOR_TOKEN = os.environ.get("KUBESYNTH_COLLECTOR_TOKEN", "")
_DEFAULT_COLLECTOR_TOKEN_HASH = (
    hashlib.sha256(_DEFAULT_COLLECTOR_TOKEN.encode("utf-8")).hexdigest() if _DEFAULT_COLLECTOR_TOKEN else ""
)
_COLLECTOR_TOKEN_MISSING_ERROR = "Collector token is unavailable in the gateway. Re-register this collector with a valid token."
_collector_secret_warning_emitted = False


def _collector_token_secret() -> str:
    global _collector_secret_warning_emitted

    explicit_secret = os.getenv("INTELLIGENCE_COLLECTOR_TOKEN_KEY", "").strip()
    if explicit_secret:
        return explicit_secret

    explicit_secret = os.getenv("JWT_SECRET", "").strip() or os.getenv("API_GATEWAY_SHARED_TOKEN", "").strip()
    if explicit_secret:
        return explicit_secret

    if not _collector_secret_warning_emitted:
        logger.warning(
            "INTELLIGENCE_COLLECTOR_TOKEN_KEY, JWT_SECRET, and API_GATEWAY_SHARED_TOKEN are unset. "
            "Collector tokens are encrypted with an ephemeral process secret and will not survive gateway restarts."
        )
        _collector_secret_warning_emitted = True
    return JWT_SECRET


def _collector_fernet():
    from cryptography.fernet import Fernet

    digest = hashlib.sha256(_collector_token_secret().encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def _encrypt_collector_token(token: str) -> str:
    normalized = str(token or "").strip()
    if not normalized:
        raise ValueError("Collector token cannot be empty")
    return _collector_fernet().encrypt(normalized.encode("utf-8")).decode("utf-8")


def _decrypt_collector_token(encrypted_token: str | None) -> str | None:
    if not encrypted_token:
        return None
    try:
        from cryptography.fernet import InvalidToken

        return _collector_fernet().decrypt(encrypted_token.encode("utf-8")).decode("utf-8")
    except InvalidToken:
        logger.warning("Failed to decrypt a persisted collector token. Re-register the collector to restore task execution.")
    except Exception:
        logger.exception("Unexpected error while decrypting a persisted collector token.")
    return None


def _recover_collector_token(row: IntelligenceCollectorRow) -> str | None:
    decrypted = _decrypt_collector_token(getattr(row, "encrypted_token", None))
    if decrypted:
        return decrypted
    if getattr(row, "token_hash", None) == _DEFAULT_COLLECTOR_TOKEN_HASH:
        return _DEFAULT_COLLECTOR_TOKEN
    return None


def _collector_auth_headers(token: str | None) -> dict[str, str]:
    normalized = str(token or "").strip()
    if not normalized:
        return {}
    return {"Authorization": f"Bearer {normalized}"}

def _validate_collector_url(url: str) -> str:
    """Validate a collector URL: must be http/https, no cloud-metadata IPs."""
    from urllib.parse import urlparse
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise HTTPException(status_code=400, detail="Collector URL must use http or https scheme")
    hostname = parsed.hostname or ""
    try:
        addr = _ipaddress.ip_address(hostname)
        for net in _SSRF_BLOCKED_NETS:
            if addr in net:
                raise HTTPException(status_code=400, detail=f"Collector URL targets a blocked IP range ({net})")
    except ValueError:
        pass  # hostname is a DNS name, not a raw IP — allowed
    return url.rstrip("/")


def _normalize_intelligence_namespace(namespace: str | None) -> str:
    normalized = str(namespace or "default").strip()
    return normalized or "default"


def _slugify_identifier(value: str, fallback: str = "item") -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or fallback


def _build_namespace_scoped_collector_id(namespace: str, name: str) -> str:
    namespace_slug = _slugify_identifier(namespace, "default")
    collector_slug = _slugify_identifier(name, "collector")
    candidate = f"{namespace_slug}-{collector_slug}"
    if len(candidate) <= 128:
        return candidate
    digest = hashlib.sha256(f"{namespace}:{name}".encode()).hexdigest()[:8]
    head = max(1, 128 - len(namespace_slug) - len(digest) - 2)
    trimmed_slug = collector_slug[:head].rstrip("-") or "collector"
    return f"{namespace_slug}-{trimmed_slug}-{digest}"


def _get_namespaced_collectors(namespace: str) -> dict[str, dict[str, Any]]:
    normalized = _normalize_intelligence_namespace(namespace)
    with _collector_lock:
        return {
            collector_id: copy.deepcopy(info)
            for collector_id, info in _collector_registry.get(normalized, {}).items()
        }


def _set_namespaced_collector(namespace: str, collector_id: str, info: dict[str, Any]) -> None:
    normalized = _normalize_intelligence_namespace(namespace)
    with _collector_lock:
        bucket = _collector_registry.setdefault(normalized, {})
        bucket[collector_id] = {**copy.deepcopy(info), "namespace": normalized}


def _remove_namespaced_collector(namespace: str, collector_id: str) -> None:
    normalized = _normalize_intelligence_namespace(namespace)
    with _collector_lock:
        bucket = _collector_registry.get(normalized, {})
        bucket.pop(collector_id, None)
        if not bucket and normalized in _collector_registry:
            del _collector_registry[normalized]


def _list_namespaced_tasks(namespace: str) -> list[dict[str, Any]]:
    normalized = _normalize_intelligence_namespace(namespace)
    with _tasks_lock:
        tasks = [
            copy.deepcopy(task)
            for task in _collection_tasks.values()
            if _normalize_intelligence_namespace(task.get("namespace")) == normalized
        ]
    return sorted(tasks, key=lambda task: task.get("submitted_at", ""), reverse=True)


def _validate_intelligence_builtin(builtin: Any) -> str:
    normalized = str(builtin or "").strip()
    if normalized not in _INTELLIGENCE_BUILTINS:
        allowed = ", ".join(sorted(_INTELLIGENCE_BUILTINS))
        raise HTTPException(status_code=400, detail=f"Unknown built-in script '{normalized}'. Allowed values: {allowed}")
    return normalized


def _normalize_intelligence_timeout(value: Any, default: int = 30) -> int:
    try:
        timeout = int(default if value is None else value)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="Timeout must be an integer between 1 and 60 seconds") from exc
    return max(1, min(timeout, 60))


def _normalize_intelligence_script_type(value: Any) -> str:
    normalized = str(value or "bash").strip().lower() or "bash"
    if normalized not in _INTELLIGENCE_SCRIPT_TYPES:
        raise HTTPException(status_code=400, detail="Script type must be 'bash' or 'python'")
    return normalized


def _normalize_collection_payload(body: dict[str, Any], *, require_execution: bool = True) -> dict[str, Any]:
    builtin = str(body.get("builtin") or "").strip()
    script = str(body.get("script") or "").strip()
    if builtin and script:
        raise HTTPException(status_code=400, detail="Specify either 'builtin' or 'script', not both")
    if require_execution and not builtin and not script:
        raise HTTPException(status_code=400, detail="'builtin' or 'script' required")

    payload: dict[str, Any] = {"timeout": _normalize_intelligence_timeout(body.get("timeout"), 30)}
    if builtin:
        payload["builtin"] = _validate_intelligence_builtin(builtin)
        return payload
    if script:
        if len(script) > 10000:
            raise HTTPException(status_code=400, detail="Script too large (max 10000 chars)")
        payload["script"] = script
        payload["type"] = _normalize_intelligence_script_type(body.get("type") or body.get("script_type"))
    return payload


def _resolve_collection_targets(namespace: str, collector_id: str) -> dict[str, dict[str, Any]]:
    collectors = _get_namespaced_collectors(namespace)
    if collector_id == "all":
        if not collectors:
            raise HTTPException(status_code=404, detail=f"No collectors registered in namespace '{namespace}'")
        return collectors
    if collector_id not in collectors:
        raise HTTPException(status_code=404, detail=f"Collector '{collector_id}' not found in namespace '{namespace}'")
    return {collector_id: collectors[collector_id]}


def _ensure_intelligence_agent_exists(agent_name: Any, namespace: str) -> str | None:
    normalized = str(agent_name or "").strip() or None
    if normalized:
        read_agent(normalized, namespace)
    return normalized


def _task_matches_request(task: dict[str, Any], collector_id: str, payload: dict[str, Any]) -> bool:
    if collector_id != "all" and task.get("collector_id") != collector_id:
        return False
    task_payload = task.get("payload") or {}
    builtin = payload.get("builtin")
    if builtin:
        return task_payload.get("builtin") == builtin
    return (
        task_payload.get("script") == payload.get("script")
        and str(task_payload.get("type") or "bash") == str(payload.get("type") or "bash")
    )


def _build_intelligence_task_record(
    namespace: str,
    *,
    task_id: str,
    collector_id: str,
    payload: dict[str, Any],
    results: dict[str, Any],
    submitted_by: str,
) -> dict[str, Any]:
    return {
        "task_id": task_id,
        "namespace": _normalize_intelligence_namespace(namespace),
        "collector_id": collector_id,
        "payload": payload,
        "results": results,
        "submitted_by": submitted_by,
        "submitted_at": datetime.now(UTC).isoformat(),
        "total": len(results),
        "completed": sum(1 for result in results.values() if result.get("status") == "completed"),
    }


def _load_collectors_from_db() -> None:
    """Populate the in-memory collector cache from the database at startup."""
    with db_session() as ses:
        rows = ses.query(IntelligenceCollectorRow).all()
        for row in rows:
            recovered_token = _recover_collector_token(row)
            _set_namespaced_collector(
                row.namespace,
                row.id,
                {
                    "id": row.id,
                    "name": row.name,
                    "url": row.url,
                    "token": recovered_token,
                    "cluster": row.cluster,
                    "registered_at": row.registered_at.isoformat() if row.registered_at else None,
                    "tags": row.tags or [],
                },
            )
    logger.info("Loaded %d collectors from database.", len(_collector_registry))


def _load_tasks_from_db() -> None:
    """Populate the in-memory task cache from the database at startup."""
    with db_session() as ses:
        rows = (
            ses.query(IntelligenceTaskRow)
            .order_by(IntelligenceTaskRow.submitted_at.desc())
            .limit(_COLLECTION_TASKS_CAP)
            .all()
        )
        for row in rows:
            _collection_tasks[row.task_id] = {
                "task_id": row.task_id,
                "namespace": row.namespace,
                "collector_id": row.collector_id,
                "payload": row.payload or {},
                "results": row.results or {},
                "submitted_by": row.submitted_by,
                "submitted_at": row.submitted_at.isoformat() if row.submitted_at else None,
                "total": row.total or 0,
                "completed": row.completed or 0,
            }
    logger.info("Loaded %d tasks from database.", len(_collection_tasks))


def _persist_task(task_record: dict[str, Any]) -> None:
    """Write a task record to the database."""
    with db_session() as ses:
        ses.add(IntelligenceTaskRow(
            task_id=task_record["task_id"],
            namespace=_normalize_intelligence_namespace(task_record.get("namespace")),
            collector_id=task_record.get("collector_id"),
            payload=task_record.get("payload"),
            results=task_record.get("results"),
            submitted_by=task_record.get("submitted_by"),
            submitted_at=datetime.fromisoformat(task_record["submitted_at"]) if task_record.get("submitted_at") else datetime.now(UTC),
            total=task_record.get("total", 0),
            completed=task_record.get("completed", 0),
        ))


def _enforce_collection_tasks_cap() -> None:
    """Evict oldest tasks when the in-memory dict exceeds _COLLECTION_TASKS_CAP."""
    if len(_collection_tasks) <= _COLLECTION_TASKS_CAP:
        return
    sorted_ids = sorted(
        _collection_tasks,
        key=lambda tid: _collection_tasks[tid].get("submitted_at", ""),
    )
    to_remove = len(_collection_tasks) - _COLLECTION_TASKS_CAP
    for tid in sorted_ids[:to_remove]:
        del _collection_tasks[tid]
    # Also trim the DB
    with db_session() as ses:
        total = ses.query(IntelligenceTaskRow).count()
        if total > _COLLECTION_TASKS_CAP:
            oldest = (
                ses.query(IntelligenceTaskRow)
                .order_by(IntelligenceTaskRow.submitted_at.asc())
                .limit(total - _COLLECTION_TASKS_CAP)
                .all()
            )
            for old in oldest:
                ses.delete(old)


def _delete_collection_tasks(namespace: str, task_ids: list[Any]) -> tuple[list[str], list[str]]:
    normalized = _normalize_intelligence_namespace(namespace)
    requested: list[str] = []
    seen: set[str] = set()
    for value in task_ids:
        task_id = str(value or "").strip()
        if task_id and task_id not in seen:
            requested.append(task_id)
            seen.add(task_id)
    if not requested:
        raise HTTPException(status_code=400, detail="'task_ids' must contain at least one task id")

    deleted: set[str] = set()
    with db_session() as ses:
        rows = (
            ses.query(IntelligenceTaskRow)
            .filter(
                IntelligenceTaskRow.namespace == normalized,
                IntelligenceTaskRow.task_id.in_(requested),
            )
            .all()
        )
        for row in rows:
            deleted.add(row.task_id)
            ses.delete(row)

    with _tasks_lock:
        for task_id in requested:
            task = _collection_tasks.get(task_id)
            if task and _normalize_intelligence_namespace(task.get("namespace")) == normalized:
                deleted.add(task_id)
                _collection_tasks.pop(task_id, None)

    deleted_ids = [task_id for task_id in requested if task_id in deleted]
    missing_ids = [task_id for task_id in requested if task_id not in deleted]
    return deleted_ids, missing_ids

# ─── Auto-inject intelligence context into agent invocations ─────────────

_INTELLIGENCE_SYSTEM_KEYWORDS = {"cluster intelligence", "intelligence data", "sre assistant", "cluster intel"}

def _agent_wants_intelligence(agent: dict[str, Any]) -> bool:
    """Return True if the agent's system prompt indicates it uses intelligence."""
    sys_prompt = (agent.get("spec", {}).get("systemPrompt") or "").lower()
    return any(kw in sys_prompt for kw in _INTELLIGENCE_SYSTEM_KEYWORDS)


def _build_auto_intelligence_context(
    namespace: str,
    max_scripts: int = 5,
    max_chars: int = 6000,
    max_age_minutes: int = 30,
) -> str:
    """Build a condensed intelligence context from recent collection tasks.
    Skips tasks older than max_age_minutes to avoid injecting stale data."""
    recent_tasks = _list_namespaced_tasks(namespace)
    if not recent_tasks:
        return ""
    cutoff = datetime.now(UTC) - timedelta(minutes=max_age_minutes)
    # Group by builtin script, keep most recent per script
    latest_by_script: dict[str, dict[str, Any]] = {}
    for task in recent_tasks:
        # Staleness check
        submitted_str = task.get("submitted_at", "")
        if submitted_str:
            try:
                submitted = datetime.fromisoformat(submitted_str)
                if submitted.tzinfo is None:
                    submitted = submitted.replace(tzinfo=UTC)
                if submitted < cutoff:
                    continue
            except (ValueError, TypeError):
                pass
        builtin = task.get("payload", {}).get("builtin", "")
        if not builtin or builtin in latest_by_script:
            continue
        latest_by_script[builtin] = task
        if len(latest_by_script) >= max_scripts:
            break
    if not latest_by_script:
        return ""
    parts = ["## Auto-injected Cluster Intelligence Summary", ""]
    total_len = 0
    for builtin, task in latest_by_script.items():
        section = [f"### {builtin} (collected {task.get('submitted_at', 'unknown')})"]
        for _cid, result in task.get("results", {}).items():
            if result.get("status") == "completed":
                stdout = (result.get("stdout") or "").strip()
                if stdout:
                    remaining = max_chars - total_len
                    if remaining <= 200:
                        break
                    snippet = stdout[:remaining]
                    section.append(f"```\n{snippet}\n```")
                    total_len += len(snippet)
        parts.extend(section)
        parts.append("")
        if total_len >= max_chars:
            break
    return "\n".join(parts)


@app.get("/api/intelligence/collectors")
async def list_intelligence_collectors(namespace: str = "default", user=Depends(verify_token)):
    """List all registered collector agents and their status (tokens redacted)."""
    namespace = _normalize_intelligence_namespace(namespace)
    ensure_namespace_access(user, namespace)
    collectors = []
    async with httpx.AsyncClient(timeout=10, trust_env=False) as client:
        for cid, info in _get_namespaced_collectors(namespace).items():
            entry = {
                "id": cid,
                "namespace": namespace,
                "name": info.get("name", cid),
                "url": info.get("url", ""),
                "token": "***",
                "cluster": info.get("cluster", "unknown"),
                "registered_at": info.get("registered_at"),
                "tags": info.get("tags", []),
            }
            try:
                health = await client.get(f"{info['url']}/healthz")
                if health.status_code != 200:
                    entry["status"] = "degraded"
                    entry["error"] = f"Health check returned {health.status_code}"
                    collectors.append(entry)
                    continue

                token = str(info.get("token") or "").strip()
                if not token:
                    entry["status"] = "degraded"
                    entry["error"] = _COLLECTOR_TOKEN_MISSING_ERROR
                    collectors.append(entry)
                    continue

                try:
                    metadata = await client.get(
                        f"{info['url']}/info",
                        headers=_collector_auth_headers(token),
                    )
                    metadata.raise_for_status()
                    payload = metadata.json()
                    metadata_payload = payload if isinstance(payload, dict) else {}
                    entry["status"] = "online"
                    for field in ("node", "version", "capabilities", "builtin_scripts", "max_timeout", "cluster"):
                        value = metadata_payload.get(field)
                        if value not in (None, ""):
                            entry[field] = value
                except Exception as exc:
                    entry["status"] = "degraded"
                    entry["error"] = str(exc)
            except Exception as exc:
                entry["status"] = "offline"
                entry["error"] = str(exc)
            collectors.append(entry)
    return {"collectors": collectors, "total": len(collectors)}


@app.post("/api/intelligence/collectors")
def register_intelligence_collector(
    body: dict[str, Any] = Body(...),
    namespace: str = "default",
    user=Depends(verify_token),
):
    """Register a new collector agent (persisted to DB, cached in memory)."""
    namespace = _normalize_intelligence_namespace(namespace)
    ensure_namespace_access(user, namespace, "operator")
    name = body.get("name")
    url = body.get("url")
    if not name or not url:
        raise HTTPException(status_code=400, detail="'name' and 'url' required")
    validated_url = _validate_collector_url(url)
    token = str(body.get("token", "")).strip()
    if not token:
        raise HTTPException(status_code=400, detail="'token' is required")
    expected_id = _build_namespace_scoped_collector_id(namespace, name)
    now = datetime.now(UTC)
    # Persist to DB (hash the token)
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    encrypted_token = _encrypt_collector_token(token)
    with db_session() as ses:
        existing = ses.query(IntelligenceCollectorRow).filter_by(namespace=namespace, id=expected_id).first()
        if existing is None:
            existing = ses.query(IntelligenceCollectorRow).filter_by(namespace=namespace, name=name).first()
        if existing:
            cid = existing.id
            existing.name = name
            existing.namespace = namespace
            existing.url = validated_url
            existing.token_hash = token_hash
            existing.encrypted_token = encrypted_token
            existing.cluster = body.get("cluster", "unknown")
            existing.tags = body.get("tags", [])
            existing.registered_by = user.get("sub", "unknown") if isinstance(user, dict) else "unknown"
        else:
            cid = expected_id
            if ses.query(IntelligenceCollectorRow).filter_by(id=cid).first():
                raise HTTPException(status_code=409, detail="Collector identifier collision. Rename the collector and try again.")
            ses.add(IntelligenceCollectorRow(
                id=cid, namespace=namespace, name=name, url=validated_url, token_hash=token_hash, encrypted_token=encrypted_token,
                cluster=body.get("cluster", "unknown"), tags=body.get("tags", []),
                registered_at=now,
                registered_by=user.get("sub", "unknown") if isinstance(user, dict) else "unknown",
            ))
    # Update in-memory cache (plaintext token kept for outbound requests)
    _set_namespaced_collector(namespace, cid, {
        "id": cid,
        "name": name,
        "url": validated_url,
        "token": token,
        "cluster": body.get("cluster", "unknown"),
        "registered_at": now.isoformat(),
        "tags": body.get("tags", []),
    })
    safe_record_audit(
        action="intelligence.collector.register",
        principal=user,
        resource_kind="intelligence-collector",
        resource_name=cid,
        resource_namespace=namespace,
        detail={"collector_name": name, "cluster": body.get("cluster", "unknown")},
    )
    return {"id": cid, "namespace": namespace, "status": "registered", "name": name, "url": validated_url, "token": "***"}


@app.delete("/api/intelligence/collectors/{collector_id}")
def unregister_intelligence_collector(
    collector_id: str,
    namespace: str = "default",
    user=Depends(verify_token),
):
    """Unregister a collector agent (removes from DB and cache)."""
    namespace = _normalize_intelligence_namespace(namespace)
    ensure_namespace_access(user, namespace, "operator")
    collectors = _get_namespaced_collectors(namespace)
    if collector_id not in collectors:
        raise HTTPException(status_code=404, detail="Collector not found")
    # Remove from DB
    with db_session() as ses:
        row = ses.query(IntelligenceCollectorRow).filter_by(id=collector_id, namespace=namespace).first()
        if row:
            ses.delete(row)
    # Remove from cache
    _remove_namespaced_collector(namespace, collector_id)
    safe_record_audit(
        action="intelligence.collector.unregister",
        principal=user,
        resource_kind="intelligence-collector",
        resource_name=collector_id,
        resource_namespace=namespace,
    )
    return {"status": "unregistered", "id": collector_id, "namespace": namespace}


@app.post("/api/intelligence/collect")
async def submit_collection_task(
    body: dict[str, Any] = Body(...),
    namespace: str = "default",
    user=Depends(verify_token),
):
    """
    Submit a collection task to one or more collectors.

    Body:
    {
        "collector_id": "my-cluster",      # or "all" for fan-out
        "script": "kubectl get pods -A",   # custom script
        "builtin": "cluster_overview",     # OR use a built-in script
        "type": "bash",                    # bash or python
        "timeout": 30
    }
    """
    namespace = _normalize_intelligence_namespace(namespace)
    ensure_namespace_access(user, namespace, "operator")

    collector_id = str(body.get("collector_id") or "").strip()
    if not collector_id:
        raise HTTPException(status_code=400, detail="'collector_id' required")
    task_id = str(uuid.uuid4())[:8]
    payload = _normalize_collection_payload(body)

    # Determine targets
    targets = _resolve_collection_targets(namespace, collector_id)

    # Execute
    results = {}
    async with httpx.AsyncClient(timeout=COLLECTOR_TIMEOUT, trust_env=False) as client:
        for cid, info in targets.items():
            token = str(info.get("token") or "").strip()
            if not token:
                results[cid] = {"status": "error", "error": _COLLECTOR_TOKEN_MISSING_ERROR}
                continue
            try:
                resp = await client.post(
                    f"{info['url']}/collect",
                    headers=_collector_auth_headers(token),
                    json=payload,
                )
                resp.raise_for_status()
                results[cid] = resp.json()
            except Exception as e:
                results[cid] = {"status": "error", "error": str(e)}

    task_record = _build_intelligence_task_record(
        namespace,
        task_id=task_id,
        collector_id=collector_id,
        payload=payload,
        results=results,
        submitted_by=user.get("sub", "unknown") if isinstance(user, dict) else "unknown",
    )
    with _tasks_lock:
        _collection_tasks[task_id] = task_record
    _enforce_collection_tasks_cap()
    _persist_task(task_record)
    safe_record_audit(
        action="intelligence.task.submit",
        principal=user,
        resource_kind="intelligence-task",
        resource_name=task_id,
        resource_namespace=namespace,
        detail={"collector_id": collector_id, "builtin": payload.get("builtin")},
    )
    return task_record


@app.get("/api/intelligence/tasks")
def list_collection_tasks(
    limit: int = 50,
    namespace: str = "default",
    user=Depends(verify_token),
):
    """List recent collection tasks."""
    namespace = _normalize_intelligence_namespace(namespace)
    ensure_namespace_access(user, namespace)
    with db_session() as ses:
        rows = (
            ses.query(IntelligenceTaskRow)
            .filter_by(namespace=namespace)
            .order_by(IntelligenceTaskRow.submitted_at.desc())
            .limit(limit)
            .all()
        )
        tasks = [row.to_dict() for row in rows]
        total = ses.query(IntelligenceTaskRow).filter_by(namespace=namespace).count()
    return {"tasks": tasks, "total": total}


@app.get("/api/intelligence/tasks/{task_id}")
def get_collection_task(
    task_id: str,
    namespace: str = "default",
    user=Depends(verify_token),
):
    """Get a specific collection task and its results."""
    namespace = _normalize_intelligence_namespace(namespace)
    ensure_namespace_access(user, namespace)
    with db_session() as ses:
        row = ses.query(IntelligenceTaskRow).filter_by(task_id=task_id, namespace=namespace).first()
    if not row:
        raise HTTPException(status_code=404, detail="Task not found")
    return row.to_dict()


@app.delete("/api/intelligence/tasks/{task_id}", response_model=DeleteResponse)
def delete_collection_task(
    task_id: str,
    namespace: str = "default",
    user=Depends(verify_token),
):
    """Delete a specific collection task and remove it from intelligence context caches."""
    namespace = _normalize_intelligence_namespace(namespace)
    ensure_namespace_access(user, namespace, "operator")
    deleted_ids, _missing_ids = _delete_collection_tasks(namespace, [task_id])
    if not deleted_ids:
        raise HTTPException(status_code=404, detail="Task not found")
    safe_record_audit(
        action="intelligence.task.delete",
        principal=user,
        resource_kind="intelligence-task",
        resource_name=task_id,
        resource_namespace=namespace,
    )
    return {"status": "deleted", "kind": "intelligence-task", "name": task_id, "namespace": namespace}


@app.post("/api/intelligence/tasks/delete")
def bulk_delete_collection_tasks(
    body: dict[str, Any] = Body(...),
    namespace: str = "default",
    user=Depends(verify_token),
):
    """Delete multiple collection tasks in one request."""
    namespace = _normalize_intelligence_namespace(namespace)
    ensure_namespace_access(user, namespace, "operator")
    task_ids = body.get("task_ids")
    if not isinstance(task_ids, list):
        raise HTTPException(status_code=400, detail="'task_ids' must be a list")
    deleted_ids, missing_ids = _delete_collection_tasks(namespace, task_ids)
    if not deleted_ids:
        raise HTTPException(status_code=404, detail="No matching tasks found")
    safe_record_audit(
        action="intelligence.task.delete.bulk",
        principal=user,
        resource_kind="intelligence-task",
        resource_name="bulk",
        resource_namespace=namespace,
        detail={"deleted_ids": deleted_ids[:20], "missing_ids": missing_ids[:20], "deleted": len(deleted_ids)},
    )
    return {
        "status": "deleted",
        "kind": "intelligence-task",
        "namespace": namespace,
        "deleted": len(deleted_ids),
        "requested": len(deleted_ids) + len(missing_ids),
        "deleted_ids": deleted_ids,
        "missing_ids": missing_ids,
    }


# =========================================================================
# Intelligence Schedules & Alerts API  (PostgreSQL-backed)
# =========================================================================


def _normalize_schedule_configuration(
    body: dict[str, Any],
    *,
    namespace: str,
    current: dict[str, Any] | None = None,
) -> dict[str, Any]:
    merged: dict[str, Any] = dict(current or {})
    merged.update(body)

    name = str(merged.get("name") or "").strip()
    cron_expr = str(merged.get("cron") or "").strip()
    if not name or not cron_expr:
        raise HTTPException(status_code=400, detail="'name' and 'cron' required")
    try:
        from croniter import croniter

        croniter(cron_expr)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid cron expression: {exc}") from exc

    payload = _normalize_collection_payload(merged)
    collector_id = str(merged.get("collector_id") or "all").strip() or "all"
    if collector_id != "all":
        _resolve_collection_targets(namespace, collector_id)
    agent_name = _ensure_intelligence_agent_exists(merged.get("agent_name"), namespace)
    return {
        "name": name,
        "cron": cron_expr,
        "collector_id": collector_id,
        "builtin": payload.get("builtin"),
        "script": payload.get("script"),
        "script_type": payload.get("type", "bash"),
        "timeout": payload.get("timeout", 30),
        "agent_name": agent_name,
        "enabled": bool(merged.get("enabled", True)),
    }


def _normalize_alert_configuration(
    body: dict[str, Any],
    *,
    namespace: str,
    current: dict[str, Any] | None = None,
) -> dict[str, Any]:
    merged: dict[str, Any] = dict(current or {})
    merged.update(body)

    name = str(merged.get("name") or "").strip()
    condition_type = str(merged.get("condition_type") or "").strip()
    if not name or condition_type not in _INTELLIGENCE_ALERT_CONDITION_TYPES:
        raise HTTPException(status_code=400, detail="'name' and valid 'condition_type' required")

    condition_value = str(merged.get("condition_value") or "")
    if condition_type == "regex":
        try:
            re.compile(condition_value)
        except re.error as exc:
            raise HTTPException(status_code=400, detail=f"Invalid regex: {exc}") from exc

    action = str(merged.get("action") or "notify").strip() or "notify"
    if action not in _INTELLIGENCE_ALERT_ACTIONS:
        raise HTTPException(status_code=400, detail="Action must be 'notify' or 'invoke_agent'")

    schedule_id = str(merged.get("schedule_id") or "").strip() or None
    if schedule_id:
        with db_session() as ses:
            linked_schedule = ses.query(IntelligenceScheduleRow).filter_by(id=schedule_id, namespace=namespace).first()
        if linked_schedule is None:
            raise HTTPException(status_code=400, detail=f"Schedule '{schedule_id}' was not found in namespace '{namespace}'")

    agent_name = _ensure_intelligence_agent_exists(merged.get("agent_name"), namespace)
    if action == "invoke_agent" and not agent_name:
        raise HTTPException(status_code=400, detail="'agent_name' is required when action is 'invoke_agent'")

    prompt_template = str(merged.get("prompt_template") or "").strip() or None
    if action == "invoke_agent" and not prompt_template:
        prompt_template = "Intelligence alert:\n\n{{output}}"

    return {
        "name": name,
        "schedule_id": schedule_id,
        "condition_type": condition_type,
        "condition_value": condition_value,
        "action": action,
        "agent_name": agent_name,
        "prompt_template": prompt_template if action == "invoke_agent" else None,
        "enabled": bool(merged.get("enabled", True)),
    }

@app.get("/api/intelligence/schedules")
def list_intelligence_schedules(namespace: str = "default", user=Depends(verify_token)):
    """List all collection schedules."""
    namespace = _normalize_intelligence_namespace(namespace)
    ensure_namespace_access(user, namespace)
    with db_session() as ses:
        rows = (
            ses.query(IntelligenceScheduleRow)
            .filter_by(namespace=namespace)
            .order_by(IntelligenceScheduleRow.created_at.desc())
            .all()
        )
        items = [r.to_dict() for r in rows]
    return {"schedules": items, "total": len(items)}


@app.post("/api/intelligence/schedules")
def create_intelligence_schedule(body: dict[str, Any] = Body(...), namespace: str = "default", user=Depends(verify_token)):
    """Create a recurring collection schedule."""
    namespace = _normalize_intelligence_namespace(namespace)
    ensure_namespace_access(user, namespace, "operator")
    config = _normalize_schedule_configuration(body, namespace=namespace)
    sid = str(uuid.uuid4())[:8]
    from croniter import croniter as _croniter
    nxt = _croniter(config["cron"], datetime.now(UTC)).get_next(datetime)
    row = IntelligenceScheduleRow(
        id=sid,
        namespace=namespace,
        name=config["name"],
        cron=config["cron"],
        collector_id=config["collector_id"],
        builtin=config["builtin"],
        script=config["script"],
        script_type=config["script_type"],
        timeout=config["timeout"],
        agent_name=config["agent_name"],
        enabled=config["enabled"],
        created_by=user.get("sub", "unknown") if isinstance(user, dict) else "unknown",
        next_run=nxt,
    )
    with db_session() as ses:
        ses.add(row)
        ses.flush()
        result = row.to_dict()
    safe_record_audit(
        action="intelligence.schedule.create",
        principal=user,
        resource_kind="intelligence-schedule",
        resource_name=sid,
        resource_namespace=namespace,
        detail={"collector_id": config["collector_id"], "builtin": config["builtin"]},
    )
    return result


@app.put("/api/intelligence/schedules/{schedule_id}")
def update_intelligence_schedule(
    schedule_id: str,
    body: dict[str, Any] = Body(...),
    namespace: str = "default",
    user=Depends(verify_token),
):
    """Update a collection schedule."""
    namespace = _normalize_intelligence_namespace(namespace)
    ensure_namespace_access(user, namespace, "operator")
    with db_session() as ses:
        row = ses.query(IntelligenceScheduleRow).filter_by(id=schedule_id, namespace=namespace).first()
        if not row:
            raise HTTPException(status_code=404, detail="Schedule not found")
        config = _normalize_schedule_configuration(body, namespace=namespace, current=row.to_dict())
        row.name = config["name"]
        row.cron = config["cron"]
        row.collector_id = config["collector_id"]
        row.builtin = config["builtin"]
        row.script = config["script"]
        row.script_type = config["script_type"]
        row.timeout = config["timeout"]
        row.agent_name = config["agent_name"]
        row.enabled = config["enabled"]
        try:
            from croniter import croniter

            row.next_run = croniter(config["cron"], datetime.now(UTC)).get_next(datetime)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Invalid cron expression: {exc}") from exc
        result = row.to_dict()
    safe_record_audit(
        action="intelligence.schedule.update",
        principal=user,
        resource_kind="intelligence-schedule",
        resource_name=schedule_id,
        resource_namespace=namespace,
        detail={"collector_id": result.get("collector_id"), "builtin": result.get("builtin")},
    )
    return result


@app.delete("/api/intelligence/schedules/{schedule_id}")
def delete_intelligence_schedule(schedule_id: str, namespace: str = "default", user=Depends(verify_token)):
    """Delete a collection schedule."""
    namespace = _normalize_intelligence_namespace(namespace)
    ensure_namespace_access(user, namespace, "operator")
    with db_session() as ses:
        row = ses.query(IntelligenceScheduleRow).filter_by(id=schedule_id, namespace=namespace).first()
        if not row:
            raise HTTPException(status_code=404, detail="Schedule not found")
        ses.delete(row)
    safe_record_audit(
        action="intelligence.schedule.delete",
        principal=user,
        resource_kind="intelligence-schedule",
        resource_name=schedule_id,
        resource_namespace=namespace,
    )
    return {"status": "deleted", "id": schedule_id, "namespace": namespace}


@app.get("/api/intelligence/alerts")
def list_intelligence_alerts(agent_name: str | None = None, namespace: str = "default", user=Depends(verify_token)):
    """List alert rules, optionally filtered by agent_name."""
    namespace = _normalize_intelligence_namespace(namespace)
    ensure_namespace_access(user, namespace)
    with db_session() as ses:
        q = ses.query(IntelligenceAlertRow).filter_by(namespace=namespace)
        if agent_name:
            q = q.filter_by(agent_name=agent_name)
        rows = q.order_by(IntelligenceAlertRow.created_at.desc()).all()
        items = [r.to_dict() for r in rows]
    return {"alerts": items, "total": len(items)}


@app.post("/api/intelligence/alerts")
def create_intelligence_alert(body: dict[str, Any] = Body(...), namespace: str = "default", user=Depends(verify_token)):
    """Create an alert rule on collection output."""
    namespace = _normalize_intelligence_namespace(namespace)
    ensure_namespace_access(user, namespace, "operator")
    config = _normalize_alert_configuration(body, namespace=namespace)
    aid = str(uuid.uuid4())[:8]
    row = IntelligenceAlertRow(
        id=aid,
        namespace=namespace,
        name=config["name"],
        schedule_id=config["schedule_id"],
        condition_type=config["condition_type"],
        condition_value=config["condition_value"],
        action=config["action"],
        agent_name=config["agent_name"],
        prompt_template=config["prompt_template"],
        enabled=config["enabled"],
        created_by=user.get("sub", "unknown") if isinstance(user, dict) else "unknown",
    )
    with db_session() as ses:
        ses.add(row)
        ses.flush()
        result = row.to_dict()
    safe_record_audit(
        action="intelligence.alert.create",
        principal=user,
        resource_kind="intelligence-alert",
        resource_name=aid,
        resource_namespace=namespace,
        detail={"schedule_id": config["schedule_id"], "action": config["action"]},
    )
    return result


@app.put("/api/intelligence/alerts/{alert_id}")
def update_intelligence_alert(
    alert_id: str,
    body: dict[str, Any] = Body(...),
    namespace: str = "default",
    user=Depends(verify_token),
):
    """Update an alert rule."""
    namespace = _normalize_intelligence_namespace(namespace)
    ensure_namespace_access(user, namespace, "operator")
    with db_session() as ses:
        row = ses.query(IntelligenceAlertRow).filter_by(id=alert_id, namespace=namespace).first()
        if not row:
            raise HTTPException(status_code=404, detail="Alert not found")
        config = _normalize_alert_configuration(body, namespace=namespace, current=row.to_dict())
        row.name = config["name"]
        row.schedule_id = config["schedule_id"]
        row.condition_type = config["condition_type"]
        row.condition_value = config["condition_value"]
        row.action = config["action"]
        row.agent_name = config["agent_name"]
        row.prompt_template = config["prompt_template"]
        row.enabled = config["enabled"]
        result = row.to_dict()
    safe_record_audit(
        action="intelligence.alert.update",
        principal=user,
        resource_kind="intelligence-alert",
        resource_name=alert_id,
        resource_namespace=namespace,
        detail={"schedule_id": result.get("schedule_id"), "action": result.get("action")},
    )
    return result


@app.delete("/api/intelligence/alerts/{alert_id}")
def delete_intelligence_alert(alert_id: str, namespace: str = "default", user=Depends(verify_token)):
    """Delete an alert rule."""
    namespace = _normalize_intelligence_namespace(namespace)
    ensure_namespace_access(user, namespace, "operator")
    with db_session() as ses:
        row = ses.query(IntelligenceAlertRow).filter_by(id=alert_id, namespace=namespace).first()
        if not row:
            raise HTTPException(status_code=404, detail="Alert not found")
        ses.delete(row)
    safe_record_audit(
        action="intelligence.alert.delete",
        principal=user,
        resource_kind="intelligence-alert",
        resource_name=alert_id,
        resource_namespace=namespace,
    )
    return {"status": "deleted", "id": alert_id, "namespace": namespace}


@app.get("/api/intelligence/alerts/history")
def list_alert_history(limit: int = 50, namespace: str = "default", user=Depends(verify_token)):
    """Get recent alert trigger history."""
    namespace = _normalize_intelligence_namespace(namespace)
    ensure_namespace_access(user, namespace)
    with db_session() as ses:
        rows = (
            ses.query(AlertHistoryRow)
            .filter_by(namespace=namespace)
            .order_by(AlertHistoryRow.triggered_at.desc())
            .limit(min(limit, 500))
            .all()
        )
        items = [r.to_dict() for r in rows]
    return {"history": items, "total": len(items)}


@app.post("/api/intelligence/prompt-context")
async def get_intelligence_prompt_context(
    body: dict[str, Any] = Body(...),
    namespace: str = "default",
    user=Depends(verify_token),
):
    """
    Fetch the latest intelligence output formatted as a prompt context string.
    Optionally runs a fresh collection if no recent tasks exist.
    """
    namespace = _normalize_intelligence_namespace(namespace)
    ensure_namespace_access(user, namespace, "operator")
    collector_id = str(body.get("collector_id") or "all").strip() or "all"
    payload = _normalize_collection_payload(body)
    # Try to find a recent matching task
    matching = [
        task
        for task in _list_namespaced_tasks(namespace)
        if _task_matches_request(task, collector_id, payload)
    ][:1]
    if matching:
        task = matching[0]
    else:
        # Run a fresh collection
        targets = _resolve_collection_targets(namespace, collector_id)
        results: dict[str, Any] = {}
        async with httpx.AsyncClient(timeout=COLLECTOR_TIMEOUT, trust_env=False) as client:
            for cid, info in targets.items():
                try:
                    resp = await client.post(
                        f"{info['url']}/collect",
                        headers={"Authorization": f"Bearer {info.get('token', '')}"},
                        json=payload,
                    )
                    resp.raise_for_status()
                    results[cid] = resp.json()
                except Exception as e:
                    results[cid] = {"status": "error", "error": str(e)}
        tid = str(uuid.uuid4())[:8]
        task = _build_intelligence_task_record(
            namespace,
            task_id=tid,
            collector_id=collector_id,
            payload=payload,
            results=results,
            submitted_by=str(user.get("sub") or "prompt-context") if isinstance(user, dict) else "prompt-context",
        )
        with _tasks_lock:
            _collection_tasks[tid] = task
        _enforce_collection_tasks_cap()
        _persist_task(task)
        safe_record_audit(
            action="intelligence.prompt-context.collect",
            principal=user,
            resource_kind="intelligence-task",
            resource_name=tid,
            resource_namespace=namespace,
            detail={"collector_id": collector_id, "builtin": payload.get("builtin")},
        )
    # Format as prompt context
    parts = [f"## Cluster Intelligence ({payload.get('builtin') or 'custom script'})"]
    parts.append(f"Collected at: {task.get('submitted_at', 'unknown')}")
    parts.append("")
    for cid, result in task.get("results", {}).items():
        parts.append(f"### Collector: {cid}")
        if result.get("status") == "completed":
            stdout = result.get("stdout", "").strip()
            if stdout:
                parts.append(f"```\n{stdout[:8000]}\n```")
            else:
                parts.append("*(no output)*")
        else:
            parts.append(f"Status: {result.get('status', 'unknown')}")
            if result.get("error"):
                parts.append(f"Error: {result['error']}")
        parts.append("")
    return {
        "context": "\n".join(parts),
        "task_id": task.get("task_id"),
        "collector_id": collector_id,
        "namespace": namespace,
    }


# ─── Background intelligence scheduler ───────────────────────────────────

def _evaluate_alert_condition(alert: dict[str, Any], result: dict[str, Any]) -> bool:
    """Check whether a collection result triggers the alert condition."""
    ctype = alert.get("condition_type", "")
    cvalue = str(alert.get("condition_value", ""))
    stdout = result.get("stdout", "")
    if ctype == "contains":
        return cvalue in stdout
    if ctype == "not_contains":
        return cvalue not in stdout
    if ctype == "exit_code":
        try:
            return result.get("exit_code") == int(cvalue)
        except (ValueError, TypeError):
            return False
    if ctype == "regex":
        try:
            return bool(re.search(cvalue, stdout))
        except re.error:
            return False
    return False


async def _run_scheduled_collection(schedule: dict[str, Any]) -> dict[str, Any] | None:
    """Execute a collection for a schedule entry and return the task record."""
    namespace = _normalize_intelligence_namespace(schedule.get("namespace"))
    collector_id = schedule.get("collector_id", "all")
    payload: dict[str, Any] = {"timeout": schedule.get("timeout", 30)}
    if schedule.get("builtin"):
        payload["builtin"] = schedule["builtin"]
    elif schedule.get("script"):
        payload["script"] = schedule["script"]
        payload["type"] = schedule.get("script_type", "bash")
    else:
        return None
    try:
        targets = _resolve_collection_targets(namespace, collector_id)
    except HTTPException:
        return None
    results: dict[str, Any] = {}
    async with httpx.AsyncClient(timeout=COLLECTOR_TIMEOUT, trust_env=False) as client:
        for cid, info in targets.items():
            try:
                resp = await client.post(
                    f"{info['url']}/collect",
                    headers={"Authorization": f"Bearer {info.get('token', '')}"},
                    json=payload,
                )
                resp.raise_for_status()
                results[cid] = resp.json()
            except Exception as e:
                results[cid] = {"status": "error", "error": str(e)}
    tid = str(uuid.uuid4())[:8]
    task = _build_intelligence_task_record(
        namespace,
        task_id=tid,
        collector_id=collector_id,
        payload=payload,
        results=results,
        submitted_by=f"schedule:{schedule.get('id', 'unknown')}",
    )
    with _tasks_lock:
        _collection_tasks[tid] = task
    _enforce_collection_tasks_cap()
    _persist_task(task)
    return task


async def _fire_alert(alert_dict: dict[str, Any], task: dict[str, Any], matching_output: str):
    """Process a fired alert — log to history (DB) and optionally invoke an agent."""
    namespace = _normalize_intelligence_namespace(alert_dict.get("namespace"))
    now = datetime.now(UTC)
    snippet = matching_output[:500] if matching_output else ""
    hid = str(uuid.uuid4())[:8]
    history_entry = AlertHistoryRow(
        id=hid,
        namespace=namespace,
        alert_id=alert_dict["id"],
        alert_name=alert_dict["name"],
        triggered_at=now,
        condition_matched=f"{alert_dict['condition_type']}:{alert_dict['condition_value']}",
        action_taken=alert_dict.get("action", "notify"),
        task_id=task.get("task_id"),
        snippet=snippet,
    )
    if alert_dict.get("action") == "invoke_agent" and alert_dict.get("agent_name"):
        agent_name = alert_dict["agent_name"]
        template = alert_dict.get("prompt_template", "Intelligence alert:\n\n{{output}}")
        prompt = template.replace("{{output}}", matching_output[:4000])
        try:
            # Direct in-process call to agent runtime — avoids HTTP round-trip,
            # hardcoded port, and fake auth token.
            runtime_url = agent_runtime_url(agent_name, namespace)
            request_payload = {"prompt": prompt, "autonomous": True}
            async with httpx.AsyncClient(timeout=60, trust_env=False) as client:
                resp = await client.post(
                    f"{runtime_url}/invoke",
                    json=request_payload,
                    headers={"x-request-id": str(uuid.uuid4())},
                )
                history_entry.agent_invoked = agent_name
                history_entry.invoke_status = resp.status_code
        except Exception as exc:
            history_entry.agent_invoked = agent_name
            history_entry.invoke_error = str(exc)
            logger.warning("Alert auto-invoke failed for agent %s: %s", agent_name, exc)
    with db_session() as ses:
        # Update alert row
        alert_row = ses.query(IntelligenceAlertRow).filter_by(id=alert_dict["id"], namespace=namespace).first()
        if alert_row:
            alert_row.last_triggered = now
            alert_row.trigger_count = (alert_row.trigger_count or 0) + 1
        ses.add(history_entry)
        # Trim old history
        total = ses.query(AlertHistoryRow).filter_by(namespace=namespace).count()
        if total > _ALERT_HISTORY_CAP:
            oldest = (
                ses.query(AlertHistoryRow)
                .filter_by(namespace=namespace)
                .order_by(AlertHistoryRow.triggered_at.asc())
                .limit(total - _ALERT_HISTORY_CAP)
                .all()
            )
            for old in oldest:
                ses.delete(old)
    logger.info("Alert '%s' triggered (task %s)", alert_dict["name"], task.get("task_id"))


async def _intelligence_scheduler_loop():
    """Background loop that polls schedules every 30s and fires due collections."""
    logger.info("Intelligence scheduler started.")
    while not _SHUTDOWN.is_set():
        try:
            await asyncio.sleep(30)
            now = datetime.now(UTC)
            # Load schedules from DB
            with db_session() as ses:
                schedules = ses.query(IntelligenceScheduleRow).filter_by(enabled=True).all()
                sched_dicts = [r.to_dict() for r in schedules]
            for sched in sched_dicts:
                next_run_str = sched.get("next_run")
                if not next_run_str:
                    continue
                try:
                    next_run = datetime.fromisoformat(next_run_str)
                    if next_run.tzinfo is None:
                        next_run = next_run.replace(tzinfo=UTC)
                except (ValueError, TypeError):
                    continue
                if now < next_run:
                    continue
                sid = sched["id"]
                schedule_namespace = _normalize_intelligence_namespace(sched.get("namespace"))
                # Re-check enabled right before execution (may have been toggled since loop start)
                with db_session() as ses:
                    still_enabled = ses.query(IntelligenceScheduleRow).filter_by(
                        id=sid,
                        namespace=schedule_namespace,
                        enabled=True,
                    ).first()
                if not still_enabled:
                    logger.info("Schedule '%s' (id=%s) was disabled since loop start, skipping.", sched.get("name"), sid)
                    continue
                logger.info("Scheduled collection '%s' (id=%s) is due.", sched.get("name"), sid)
                task = await _run_scheduled_collection(sched)
                # Update schedule row in DB
                try:
                    from croniter import croniter
                    nxt = croniter(sched["cron"], now).get_next(datetime)
                except Exception:
                    nxt = None
                with db_session() as ses:
                    row = ses.query(IntelligenceScheduleRow).filter_by(id=sid, namespace=schedule_namespace).first()
                    if row:
                        row.last_run = now
                        row.next_run = nxt
                if not task:
                    continue
                # Load alerts from DB and evaluate
                with db_session() as ses:
                    alerts = ses.query(IntelligenceAlertRow).filter_by(enabled=True, namespace=schedule_namespace).all()
                    alert_dicts = [a.to_dict() for a in alerts]
                for alert in alert_dicts:
                    linked_schedule = alert.get("schedule_id")
                    if linked_schedule and linked_schedule != sid:
                        continue
                    for _cid, result in task.get("results", {}).items():
                        if _evaluate_alert_condition(alert, result):
                            await _fire_alert(alert, task, result.get("stdout", ""))
                            break
        except asyncio.CancelledError:
            break
        except Exception:
            logger.exception("Error in intelligence scheduler loop")
    logger.info("Intelligence scheduler stopped.")
