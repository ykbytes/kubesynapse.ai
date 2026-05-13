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
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, model_validator

CURRENT_DIR = Path(__file__).resolve().parent
if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))

MCP_HUB_NAMESPACE = os.getenv("MCP_HUB_NAMESPACE", "mcp-hub").strip() or "mcp-hub"
HELM_RELEASE_NAME = os.getenv("HELM_RELEASE_NAME", "kubesynapse").strip() or "kubesynapse"

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
    count_recent_webhook_invocations,
    count_users,
    create_chat_session,
    create_local_user,
    create_mcp_connection,
    create_session_for_user,
    create_webhook_receiver,
    create_workflow_trigger,
    db_session,
    delete_chat_session,
    delete_mcp_connection,
    delete_memory_record,
    delete_webhook_receiver,
    delete_workflow_trigger,
    ensure_bootstrap_admin,
    get_active_user_context,
    get_chat_session_messages,
    get_mcp_connection,
    get_mcp_connection_rows_by_ids,
    get_user_by_username,
    get_webhook_receiver,
    get_workflow_trigger,
    init_database,
    is_user_locked,
    list_chat_sessions,
    list_mcp_connections,
    list_memory_records,
    list_promoted_memory_records,
    list_trigger_executions,
    list_webhook_invocations,
    list_webhook_receivers,
    list_workflow_runs,
    list_workflow_triggers,
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
    record_trigger_execution,
    record_usage,
    record_webhook_invocation,
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
    update_webhook_invocation_matched_triggers,
    update_webhook_receiver,
    update_workflow_trigger,
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

    # Initialize trace database (runtime_run_events table for Run Intelligence Layer)
    try:
        from trace_store import init_trace_database
        init_trace_database()
        logger.info("Trace database initialized (Run Intelligence Layer).")
    except Exception as exc:
        logger.warning("Trace database init failed (non-critical): %s", exc)
    try:
        try:
            _load_collectors_from_db()
        except NameError:
            pass
        try:
            _load_tasks_from_db()
        except NameError:
            pass
        # Validate shared token is configured
        shared_token = os.environ.get("API_GATEWAY_SHARED_TOKEN", "")
        if not shared_token:
            logger.error("API_GATEWAY_SHARED_TOKEN is empty — authentication is not configured!")
        _scheduler_task = None
        try:
            _scheduler_task = asyncio.create_task(_intelligence_scheduler_loop())
        except NameError:
            pass
        yield
    finally:
        _SHUTDOWN.set()
        if _scheduler_task is not None:
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

NATS_URL = os.getenv("NATS_URL", "nats://kubesynapse-nats:4222")
QDRANT_URL = os.getenv("QDRANT_URL", "http://kubesynapse-qdrant:6333")
# Auth constants (AUTH_MODE, SHARED_TOKEN, etc.) moved to auth_middleware.py — §4.1
AGENT_RUNTIME_TIMEOUT_SECONDS = max(float(os.getenv("AGENT_RUNTIME_TIMEOUT_SECONDS", "360")), 1.0)
LITELLM_INTERNAL_URL = os.getenv("LITELLM_INTERNAL_URL", "").strip() or "http://kubesynapse-litellm:4000"
LITELLM_MASTER_KEY = os.getenv("LITELLM_MASTER_KEY", "").strip()
LLM_SECRET_NAME = os.getenv("LLM_SECRET_NAME", "kubesynapse-llm-api-keys")
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
A2A_PROVIDER_ORGANIZATION = os.getenv("A2A_PROVIDER_ORGANIZATION", "KubeSynapse").strip()
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
FACTORY_AGENT_NAME = "kubesynapse-factory"
FACTORY_WORKFLOW_NAME = "kubesynapse-factory-pipeline"
FACTORY_CONTEXT_NAME = "kubesynapse-factory-context"
DEFAULT_FACTORY_MODE = "governed-bundle"
FACTORY_MODES = frozenset({"lightweight-draft", "governed-bundle", "fully-autonomous"})
FACTORY_MODE_SYSTEM_NOTES = {
    "lightweight-draft": (
        "Factory mode: lightweight-draft. Produce the fastest useful first-pass blueprint that still respects the real kubesynapse CRDs. "
        "Keep the design lean, surface assumptions explicitly, and stop at a draft artifact set without deployment execution."
    ),
    "governed-bundle": (
        "Factory mode: governed-bundle. Produce a review-ready, enterprise-grade bundle with strong prompts, supporting deliverables, and clear approval boundaries. "
        "Optimize for a governed artifact handoff rather than deployment execution."
    ),
    "fully-autonomous": (
        "Factory mode: fully-autonomous. Produce the most capable end-to-end bundle you can, with strong decomposition, rich prompts, verification guidance, and operational realism. "
        "Still respect explicit approval boundaries and current kubesynapse runtime constraints."
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
        "maxInjectedMemories": max(int(raw.get("maxInjectedMemories", 8) or 0), 0),
        "maxInjectedChars": max(int(raw.get("maxInjectedChars", 2400) or 0), 0),
        "allowedMemoryTypes": [str(item).strip() for item in allowed_types if str(item).strip()],
        "autoPromote": bool(raw.get("autoPromote", True)),
    }


def _tokenize_for_memory_ranking(value: str) -> set[str]:
    return {token for token in re.findall(r"[a-zA-Z0-9_./-]{3,}", value.lower()) if token}


def _should_skip_recalled_memory(record: dict[str, Any]) -> bool:
    content = " ".join(str(record.get("content") or "").lower().split())
    if not content:
        return True
    blocked_phrases = (
        "i have no persistent memor",
        "i don't have persistent memory",
        "i do not have persistent memory",
        "i don't have any memories",
        "each session is independent",
        "does not retain data between sessions",
    )
    return any(phrase in content for phrase in blocked_phrases)


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
        if _should_skip_recalled_memory(record):
            continue
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
        "You have persistent memory from prior conversations. Use these as durable context when relevant:",
    ]
    for record in memory_records[:8]:
        topic = str(record.get("topic") or record.get("memory_type") or "memory").strip() or "memory"
        content = str(record.get("content") or "").strip()
        if not content:
            continue
        lines.append(f"- [{topic}] {content[:280]}")
    if len(lines) <= 1:
        return ""
    lines.append("Do not claim you have no memories. The above entries are your recalled memories.")
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
    runtime_kind: str = Field(pattern=r"^(opencode|pi|mistral-vibe)$")
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
    runtime_kind: str | None = Field(default=None, pattern=r"^(opencode|pi|mistral-vibe)$")
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


class WebhookReceiverRequest(BaseModel):
    name: str = Field(min_length=1, max_length=63, pattern=K8S_NAME_PATTERN)
    secret_ref: str = Field(min_length=1, max_length=253)
    ip_allowlist: list[str] = Field(default_factory=list)
    rate_limit: int = Field(default=60, ge=1, le=10000)
    max_payload_bytes: int = Field(default=1048576, ge=1024, le=16777216)
    enabled: bool = True


class WebhookReceiverUpdateRequest(BaseModel):
    secret_ref: str = Field(default="", min_length=1, max_length=253)
    ip_allowlist: list[str] = Field(default_factory=list)
    rate_limit: int = Field(default=60, ge=1, le=10000)
    max_payload_bytes: int = Field(default=1048576, ge=1024, le=16777216)
    enabled: bool = True


class WebhookReceiverInfo(BaseModel):
    name: str
    namespace: str
    secret_ref: str
    ip_allowlist: list[str] = Field(default_factory=list)
    rate_limit: int = 60
    max_payload_bytes: int = 1048576
    enabled: bool = True
    created_at: str | None = None


class WorkflowTriggerRequest(BaseModel):
    name: str = Field(min_length=1, max_length=63, pattern=K8S_NAME_PATTERN)
    source_kind: str = Field(default="WebhookReceiver", pattern=r"^(WebhookReceiver|AgentEvent)$")
    source_name: str = Field(min_length=1, max_length=63)
    event_filter: dict[str, Any] | None = Field(default=None)
    target_workflow_name: str = Field(min_length=1, max_length=63)
    target_workflow_namespace: str = Field(default="default", min_length=1, max_length=63)
    payload_mapping: dict[str, str] = Field(default_factory=dict)
    retry_max_retries: int = Field(default=3, ge=0, le=10)
    retry_backoff_seconds: int = Field(default=60, ge=1, le=3600)
    notifications_on_success: list[str] = Field(default_factory=list)
    notifications_on_failure: list[str] = Field(default_factory=list)
    enabled: bool = True


class WorkflowTriggerUpdateRequest(BaseModel):
    source_kind: str = Field(default="WebhookReceiver", pattern=r"^(WebhookReceiver|AgentEvent)$")
    source_name: str = Field(default="", min_length=1, max_length=63)
    event_filter: dict[str, Any] | None = Field(default=None)
    target_workflow_name: str = Field(default="", min_length=1, max_length=63)
    target_workflow_namespace: str = Field(default="default", min_length=1, max_length=63)
    payload_mapping: dict[str, str] = Field(default_factory=dict)
    retry_max_retries: int = Field(default=3, ge=0, le=10)
    retry_backoff_seconds: int = Field(default=60, ge=1, le=3600)
    notifications_on_success: list[str] = Field(default_factory=list)
    notifications_on_failure: list[str] = Field(default_factory=list)
    enabled: bool = True


class WorkflowTriggerInfo(BaseModel):
    name: str
    namespace: str
    source_kind: str = "WebhookReceiver"
    source_name: str
    event_filter: dict[str, Any] | None = None
    target_workflow_name: str
    target_workflow_namespace: str = "default"
    payload_mapping: dict[str, str] = Field(default_factory=dict)
    retry_max_retries: int = 3
    retry_backoff_seconds: int = 60
    notifications_on_success: list[str] = Field(default_factory=list)
    notifications_on_failure: list[str] = Field(default_factory=list)
    enabled: bool = True
    created_at: str | None = None


class WebhookInvocationInfo(BaseModel):
    id: int
    namespace: str
    webhook_name: str
    event_id: str
    source_ip: str | None = None
    signature_valid: bool
    payload_size: int
    payload_snippet: str | None = None
    matched_triggers: list[str] = Field(default_factory=list)
    error_message: str | None = None
    created_at: str | None = None


class TriggerExecutionInfo(BaseModel):
    id: int
    trigger_namespace: str
    trigger_name: str
    event_id: str
    workflow_name: str
    workflow_namespace: str
    payload_json: dict[str, Any] | None = None
    status: str
    error_message: str | None = None
    attempt_count: int
    created_at: str | None = None
    completed_at: str | None = None


RESOURCE_GROUP = "kubesynapse.ai"
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
    "webhookreceivers": "WebhookReceiver",
    "workflowtriggers": "WorkflowTrigger",
}


def agent_runtime_url(agent_name: str, namespace: str) -> str:
    return f"http://{agent_name}-sandbox.{namespace}.svc.cluster.local:8080"


def normalized_runtime_kind(raw_value: str | None) -> str:
    runtime_kind = str(raw_value or "").strip().lower()
    if not runtime_kind:
        raise ValueError("runtime kind must be explicitly set")
    if runtime_kind not in ("opencode", "pi", "mistral-vibe"):
        raise ValueError(
            f"runtime kind must be 'opencode', 'pi', or 'mistral-vibe'; '{runtime_kind}' is not supported"
        )
    return runtime_kind


def normalized_opencode_runtime_kind(raw_value: str | None, *, field_name: str) -> str:
    runtime_kind = normalized_runtime_kind(raw_value)
    if runtime_kind != "opencode":
        raise ValueError(f"{field_name} must be 'opencode'; '{runtime_kind}' is not supported")
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


def parse_agent_skills_config(config: Any, *, source: str, strict: bool = False, namespace: str | None = None) -> dict[str, Any]:
    if config is None:
        return {}
    if not isinstance(config, dict):
        raise HTTPException(status_code=400, detail=f"{source} must be an object")

    config_map_ref = config.get("config_map_ref") or config.get("configMapRef")
    raw_files = config.get("files")
    merged_files: dict[str, Any] = {}

    if isinstance(raw_files, dict):
        merged_files = dict(raw_files)
    elif raw_files is not None:
        raise HTTPException(status_code=400, detail=f"{source}.files must be an object keyed by Markdown file path")

    if config_map_ref is not None:
        if not isinstance(config_map_ref, str) or not config_map_ref.strip():
            raise HTTPException(status_code=400, detail=f"{source}.config_map_ref must be a non-empty string")
        config_map_ref = config_map_ref.strip()
        if namespace:
            try:
                from kubernetes import client
                from kubernetes.client.rest import ApiException
                client.CoreV1Api().read_namespaced_config_map(name=config_map_ref, namespace=namespace)
            except ApiException as exc:
                if exc.status == 404:
                    raise HTTPException(
                        status_code=400,
                        detail=f"{source}.config_map_ref ConfigMap '{config_map_ref}' not found in namespace '{namespace}'",
                    ) from exc
                raise HTTPException(status_code=502, detail=f"Failed to read skills ConfigMap: {exc}") from exc

    if not merged_files and not config_map_ref:
        return {}

    if len(merged_files) > MAX_AGENT_SKILL_FILES:
        raise HTTPException(
            status_code=400,
            detail=f"{source}.files cannot contain more than {MAX_AGENT_SKILL_FILES} entries",
        )

    normalized_files: dict[str, str] = {}
    total_chars = 0
    for raw_path, raw_content in sorted(merged_files.items(), key=lambda item: str(item[0])):
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

    result: dict[str, Any] = {}
    if normalized_files:
        result["files"] = normalized_files
    if config_map_ref:
        result["configMapRef"] = config_map_ref
    return result


def parse_agent_opa_config(config: Any, *, source: str) -> dict[str, Any]:
    if config is None:
        return {}
    if not isinstance(config, dict):
        raise HTTPException(status_code=400, detail=f"{source} must be an object")

    enabled = bool(config.get("enabled", False))
    policies = config.get("policies")
    config_map_ref = config.get("configMapRef") or config.get("config_map_ref")

    result: dict[str, Any] = {}
    if enabled:
        result["enabled"] = True
    if policies is not None:
        if not isinstance(policies, list):
            raise HTTPException(status_code=400, detail=f"{source}.policies must be a list of strings")
        normalized_policies = [str(p).strip() for p in policies if isinstance(p, str) and str(p).strip()]
        if normalized_policies:
            result["policies"] = normalized_policies
    if config_map_ref is not None:
        if not isinstance(config_map_ref, str) or not config_map_ref.strip():
            raise HTTPException(status_code=400, detail=f"{source}.configMapRef must be a non-empty string")
        result["configMapRef"] = config_map_ref.strip()
    return result


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
    if runtime_kind not in ("opencode", "pi", "mistral-vibe"):
        raise HTTPException(status_code=400, detail=f"Unsupported AIAgent runtime kind '{runtime_kind}'")
    if runtime_kind == "opencode" and spec.get("githubConfig"):
        raise HTTPException(
            status_code=400,
            detail=(
                "OpenCode runtime does not support github_config because the shared GitHub hub service is exposed "
                "through an HTTP adapter rather than a native MCP endpoint. Use sidecar-based GitHub MCP instead."
            ),
        )


def validate_invoke_runtime_compatibility(runtime_kind: str, request: InvokeRequest) -> None:
    if runtime_kind not in ("opencode", "pi", "mistral-vibe"):
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


def _build_mcp_registry_results() -> list[dict[str, Any]]:
    from routers.auth import _build_mcp_registry_results as _auth_build_mcp_registry_results

    return _auth_build_mcp_registry_results()


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
                "app.kubernetes.io/managed-by": "kubesynapse",
                "kubesynapse.ai/mcp-connection-id": connection_id,
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
        return False, "This OAuth-backed MCP entry still needs provider authorization metadata before kubesynapse can drive the sign-in flow."

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
            "organization": A2A_PROVIDER_ORGANIZATION or "KubeSynapse",
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

    passthrough = raw_value.get("KubeSynapseInvoke")
    if passthrough is None:
        return {}
    if not isinstance(passthrough, dict):
        raise A2AJSONRPCError(JSONRPC_INVALID_PARAMS, "metadata.KubeSynapseInvoke must be an object when provided")

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
                "metadata.KubeSynapseInvoke.sandboxSession must be an object when provided",
            )
        parsed["sandbox_session"] = copy.deepcopy(sandbox_session)

    team_context = passthrough.get("teamContext")
    if team_context is not None:
        if not isinstance(team_context, dict):
            raise A2AJSONRPCError(
                JSONRPC_INVALID_PARAMS,
                "metadata.KubeSynapseInvoke.teamContext must be an object when provided",
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
        from routers.agents import invoke_agent

        invoke_response = await invoke_agent(
            agent_name,
            invoke_request,
            raw_request,
            namespace,
            user={"role": "admin", "allowed_namespaces": ["*"]},
        )
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
            from routers.agents import invoke_agent_stream

            upstream_response = await invoke_agent_stream(
                agent_name,
                invoke_request,
                raw_request,
                namespace,
                user={"role": "admin", "allowed_namespaces": ["*"]},
            )
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
        skills_config = parse_agent_skills_config(existing_skills, source="existing spec.skills", strict=False, namespace=namespace)
    else:
        skills_config = parse_agent_skills_config(requested_skills, source="skills", strict=True, namespace=namespace)

    requested_opa = getattr(body, "opa", None)
    if requested_opa is None:
        opa_config = parse_agent_opa_config((existing_spec or {}).get("opa"), source="existing spec.opa")
    else:
        opa_config = parse_agent_opa_config(requested_opa, source="opa")

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
    if opa_config:
        spec["opa"] = opa_config
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
    runtime_label = "Pi" if runtime_kind == "pi" else ("OpenCode" if runtime_kind == "opencode" else (runtime_kind.capitalize() if runtime_kind else "Agent"))
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
                f"- Use method SendMessage. Put the task prompt in params.message.parts[]. For kubesynapse caller continuity, include params.metadata.KubeSynapseInvoke.threadId plus callerAgentName='{agent_name}' and callerAgentNamespace='{namespace}'."
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
            job_namespace = os.getenv("POD_NAMESPACE", "kubesynapse")
            logs, pod_name = _read_workflow_job_logs(str(trace["worker_job_name"]), job_namespace, tail)
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
            group="kubesynapse.ai",
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
                group="kubesynapse.ai",
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

        # Provision OPA policy ConfigMap if inline policies are provided
        opa_config = spec.get("opa") if isinstance(spec, dict) else None
        if isinstance(opa_config, dict):
            ensure_opa_configmap(body.name, namespace, opa_config)

        return created
    except Exception as exc:
        if getattr(exc, "status", None) == 409:
            raise HTTPException(status_code=409, detail=f"Agent '{body.name}' already exists") from exc
        logger.error("Failed to create agent %s: %s", body.name, exc)
        raise HTTPException(status_code=502, detail=f"Failed to create agent '{body.name}'") from exc


def ensure_opa_configmap(agent_name: str, namespace: str, opa_config: dict[str, Any]) -> None:
    """Create or update the OPA policies ConfigMap for an agent.

    When opa.enabled is true and inline policies are present, creates a ConfigMap
    named ``<agent_name>-opa-policies`` containing the Rego policy files. When
    opa.enabled is false or no policies are provided, deletes any existing ConfigMap.
    """
    try:
        from kubernetes import client as k8s_client

        configmap_name = f"{agent_name}-opa-policies"
        core = k8s_client.CoreV1Api()

        enabled = bool(opa_config.get("enabled", False))
        policies = opa_config.get("policies")

        if not enabled:
            try:
                core.delete_namespaced_config_map(name=configmap_name, namespace=namespace)
                logger.info("Deleted OPA ConfigMap %s/%s (opa.enabled=false)", namespace, configmap_name)
            except Exception:
                pass
            return

        if not isinstance(policies, list) or len(policies) == 0:
            return

        # Build ConfigMap data from inline policies
        data: dict[str, str] = {}
        for idx, policy in enumerate(policies):
            if not isinstance(policy, str) or not policy.strip():
                continue
            filename = f"policy-{idx:03d}.rego"
            data[filename] = policy.strip()

        if not data:
            return

        body = k8s_client.V1ConfigMap(
            api_version="v1",
            kind="ConfigMap",
            metadata=k8s_client.V1ObjectMeta(
                name=configmap_name,
                namespace=namespace,
                labels={"app.kubernetes.io/managed-by": "kubesynapse", "agent-name": agent_name},
            ),
            data=data,
        )

        try:
            existing = core.read_namespaced_config_map(name=configmap_name, namespace=namespace)
            existing.data = data
            core.replace_namespaced_config_map(name=configmap_name, namespace=namespace, body=existing)
            logger.info("Updated OPA ConfigMap %s/%s (%d policies)", namespace, configmap_name, len(data))
        except Exception:
            core.create_namespaced_config_map(namespace=namespace, body=body)
            logger.info("Created OPA ConfigMap %s/%s (%d policies)", namespace, configmap_name, len(data))

    except Exception as exc:
        logger.warning("Failed to manage OPA ConfigMap for %s/%s: %s", namespace, agent_name, exc)


def read_approval(approval_name: str, namespace: str) -> dict[str, Any]:
    try:
        from kubernetes import client

        return cast(
            dict[str, Any],
            client.CustomObjectsApi().get_namespaced_custom_object(
                group="kubesynapse.ai",
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

# Export the complete shared gateway surface, including underscore-prefixed
# helpers used by split router modules via ``from _core import *``.
__all__ = [name for name in globals() if not name.startswith("__")]
