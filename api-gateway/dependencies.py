"""Shared dependencies, imports, and re-exports for all API gateway routers.

This module centralizes the sprawling import graph so that individual router
files stay concise and depend on a single well-known module.
"""

from __future__ import annotations

# Standard library
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

# Third-party
import certifi
import httpx
from fastapi import Body, Cookie, Depends, FastAPI, Header, HTTPException, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse, StreamingResponse
from pydantic import BaseModel, Field, model_validator

# ---------------------------------------------------------------------------
# Path setup  (must be imported first so relative imports work)
# ---------------------------------------------------------------------------
CURRENT_DIR = Path(__file__).resolve().parent
if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))

# ---------------------------------------------------------------------------
# Auth middleware (extracted module — §4.1)
# ---------------------------------------------------------------------------
from auth_middleware import (  # noqa: E402
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

# ---------------------------------------------------------------------------
# Auth store (database layer)
# ---------------------------------------------------------------------------
from auth_store import (  # noqa: E402
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
    get_workflow_run_trace as load_workflow_run_trace,
    list_users as list_local_users,
)

# ---------------------------------------------------------------------------
# Enterprise auth
# ---------------------------------------------------------------------------
from enterprise_auth import (  # noqa: E402
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

# ---------------------------------------------------------------------------
# JWT utilities
# ---------------------------------------------------------------------------
from jwt_utils import (  # noqa: E402
    JWT_SECRET,
    REFRESH_COOKIE_NAME,
    REFRESH_TOKEN_TTL_SECONDS,
)

# ---------------------------------------------------------------------------
# Optional / conditional imports
# ---------------------------------------------------------------------------
try:
    import yaml
except ModuleNotFoundError:  # pragma: no cover
    yaml = None

try:
    from pythonjsonlogger import jsonlogger as _jsonlogger  # type: ignore[import-untyped]
except ModuleNotFoundError:  # pragma: no cover
    _jsonlogger = None

try:
    from prometheus_fastapi_instrumentator import Instrumentator as _Instrumentator  # type: ignore[import-untyped]
except ModuleNotFoundError:  # pragma: no cover
    _Instrumentator = None

# ---------------------------------------------------------------------------
# Logger
# ---------------------------------------------------------------------------
logger = logging.getLogger("api-gateway")

# ---------------------------------------------------------------------------
# Environment-derived constants
# ---------------------------------------------------------------------------
MCP_HUB_NAMESPACE = os.getenv("MCP_HUB_NAMESPACE", "mcp-hub").strip() or "mcp-hub"
HELM_RELEASE_NAME = os.getenv("HELM_RELEASE_NAME", "kubesynapse").strip() or "kubesynapse"
NATS_URL = os.getenv("NATS_URL", "nats://kubesynapse-nats:4222")
QDRANT_URL = os.getenv("QDRANT_URL", "http://kubesynapse-qdrant:6333")
SHUTDOWN = threading.Event()
K8S_NAME_PATTERN = r"^[a-z0-9]([-a-z0-9]*[a-z0-9])?$"
K8S_NAME_RE = re.compile(K8S_NAME_PATTERN)
GIT_AUTH_METHODS = {"token", "basic", "ssh"}
GIT_PUSH_POLICIES = {"after-each-commit", "end-of-session", "on-approval", "never"}
AGENT_RUNTIME_TIMEOUT_SECONDS = max(float(os.getenv("AGENT_RUNTIME_TIMEOUT_SECONDS", "360")), 1.0)
LITELLM_INTERNAL_URL = os.getenv("LITELLM_INTERNAL_URL", "").strip() or "http://kubesynapse-litellm:4000"
LITELLM_MASTER_KEY = os.getenv("LITELLM_MASTER_KEY", "").strip()
LLM_SECRET_NAME = os.getenv("LLM_SECRET_NAME", "kubesynapse-llm-api-keys")
PROVIDER_REGISTRY_CONFIGMAP_NAME = (
    os.getenv("PROVIDER_REGISTRY_CONFIGMAP_NAME", f"{HELM_RELEASE_NAME}-provider-registry").strip()
    or f"{HELM_RELEASE_NAME}-provider-registry"
)
PROVIDER_AUTH_SECRET_NAME = os.getenv("PROVIDER_AUTH_SECRET_NAME", LLM_SECRET_NAME).strip() or LLM_SECRET_NAME
STREAM_KEEPALIVE_SECONDS = max(float(os.getenv("API_GATEWAY_STREAM_KEEPALIVE_SECONDS", "15")), 5.0)
AGENT_READ_CACHE_TTL_SECONDS = max(float(os.getenv("API_GATEWAY_AGENT_READ_CACHE_TTL_SECONDS", "2.0")), 0.0)
AGENT_READ_CACHE_MAX_ENTRIES = max(int(os.getenv("API_GATEWAY_AGENT_READ_CACHE_MAX_ENTRIES", "256")), 1)
A2A_PROTOCOL_VERSION = "1.0"
A2A_TASK_RETENTION_SECONDS = max(int(os.getenv("A2A_TASK_RETENTION_SECONDS", "3600")), 60)
A2A_PUBLIC_BASE_URL = os.getenv("API_GATEWAY_PUBLIC_BASE_URL", "").strip()
A2A_PROVIDER_ORGANIZATION = os.getenv("A2A_PROVIDER_ORGANIZATION", "KubeSynapseai").strip()
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
AGENT_READ_CACHE_LOCK = threading.Lock()
AGENT_READ_CACHE: dict[tuple[str, str], tuple[float, dict[str, Any]]] = {}
