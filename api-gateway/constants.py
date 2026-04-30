"""Shared constants for the API Gateway."""

import os
import re
import threading

import httpx

# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------
MCP_HUB_NAMESPACE = os.getenv("MCP_HUB_NAMESPACE", "mcp-hub").strip() or "mcp-hub"
HELM_RELEASE_NAME = os.getenv("HELM_RELEASE_NAME", "kubesynapse").strip() or "kubesynapse"

# ---------------------------------------------------------------------------
# Infrastructure endpoints
# ---------------------------------------------------------------------------
NATS_URL = os.getenv("NATS_URL", "nats://kubesynapse-nats:4222")
QDRANT_URL = os.getenv("QDRANT_URL", "http://kubesynapse-qdrant:6333")
LITELLM_INTERNAL_URL = os.getenv("LITELLM_INTERNAL_URL", "").strip() or "http://kubesynapse-litellm:4000"
LITELLM_MASTER_KEY = os.getenv("LITELLM_MASTER_KEY", "").strip()
LLM_SECRET_NAME = os.getenv("LLM_SECRET_NAME", "kubesynapse-llm-api-keys")

# ---------------------------------------------------------------------------
# Runtime / agent limits
# ---------------------------------------------------------------------------
AGENT_RUNTIME_TIMEOUT_SECONDS = max(float(os.getenv("AGENT_RUNTIME_TIMEOUT_SECONDS", "360")), 1.0)
STREAM_KEEPALIVE_SECONDS = max(float(os.getenv("API_GATEWAY_STREAM_KEEPALIVE_SECONDS", "15")), 5.0)
AGENT_READ_CACHE_TTL_SECONDS = max(float(os.getenv("API_GATEWAY_AGENT_READ_CACHE_TTL_SECONDS", "2.0")), 0.0)
AGENT_READ_CACHE_MAX_ENTRIES = max(int(os.getenv("API_GATEWAY_AGENT_READ_CACHE_MAX_ENTRIES", "256")), 1)

# ---------------------------------------------------------------------------
# HTTP client timeouts
# ---------------------------------------------------------------------------
HTTP_DEFAULT_TIMEOUT = 15.0
HTTP_SHORT_TIMEOUT = 10.0
HTTP_COLLECTOR_TIMEOUT = 60.0
HTTP_STREAM_TIMEOUT = httpx.Timeout(300.0, connect=10.0)
HTTP_AGENT_TIMEOUT = httpx.Timeout(30.0, connect=10.0)
HTTP_INVOKE_TIMEOUT = httpx.Timeout(120.0, connect=10.0)

# ---------------------------------------------------------------------------
# A2A protocol constants
# ---------------------------------------------------------------------------
A2A_PROTOCOL_VERSION = "1.0"
A2A_TASK_RETENTION_SECONDS = max(int(os.getenv("A2A_TASK_RETENTION_SECONDS", "3600")), 60)
A2A_PUBLIC_BASE_URL = os.getenv("API_GATEWAY_PUBLIC_BASE_URL", "").strip()
A2A_PROVIDER_ORGANIZATION = os.getenv("A2A_PROVIDER_ORGANIZATION", "KubeSynapse").strip()
A2A_PROVIDER_URL = os.getenv("A2A_PROVIDER_URL", "").strip()
A2A_TERMINAL_STATES: frozenset[str] = frozenset(
    {"TASK_STATE_COMPLETED", "TASK_STATE_FAILED", "TASK_STATE_CANCELED", "TASK_STATE_REJECTED"}
)
A2A_INTERRUPTED_STATES: frozenset[str] = frozenset(
    {"TASK_STATE_INPUT_REQUIRED", "TASK_STATE_AUTH_REQUIRED"}
)

# ---------------------------------------------------------------------------
# JSON-RPC error codes
# ---------------------------------------------------------------------------
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

# ---------------------------------------------------------------------------
# Shared locks
# ---------------------------------------------------------------------------
A2A_TASK_STORE_LOCK = threading.Lock()
_AGENT_READ_CACHE_LOCK = threading.Lock()

# ---------------------------------------------------------------------------
# Agent / subagent / skill limits
# ---------------------------------------------------------------------------
TEAM_CONTEXT_MAX_CHARS = max(int(os.getenv("A2A_TEAM_CONTEXT_MAX_CHARS", "4096")), 256)
MAX_SUBAGENT_FILE_CHARS = max(int(os.getenv("AGENT_MAX_SUBAGENT_FILE_CHARS", "4000")), 256)
MAX_SUBAGENT_METADATA_CHARS = max(int(os.getenv("AGENT_MAX_SUBAGENT_METADATA_CHARS", "2048")), 256)
MAX_SUBAGENTS = max(int(os.getenv("AGENT_MAX_SUBAGENTS", "6")), 1)
AGENT_SYSTEM_PROMPT_MAX_CHARS = 12000
SUBAGENT_STRATEGIES: frozenset[str] = frozenset({"sequential", "parallel"})
MAX_AGENT_SKILL_FILES = max(int(os.getenv("AGENT_MAX_SKILL_FILES", "24")), 1)
MAX_AGENT_SKILL_FILE_PATH_CHARS = max(int(os.getenv("AGENT_MAX_SKILL_FILE_PATH_CHARS", "256")), 32)
MAX_AGENT_SKILL_FILE_CONTENT_CHARS = max(int(os.getenv("AGENT_MAX_SKILL_FILE_CONTENT_CHARS", "16000")), 512)
MAX_AGENT_SKILL_TOTAL_CHARS = max(int(os.getenv("AGENT_MAX_SKILL_TOTAL_CHARS", "64000")), 4096)

# ---------------------------------------------------------------------------
# Factory constants
# ---------------------------------------------------------------------------
FACTORY_AGENT_NAME = "kubesynapse-factory"
FACTORY_WORKFLOW_NAME = "kubesynapse-factory-pipeline"
FACTORY_CONTEXT_NAME = "kubesynapse-factory-context"
DEFAULT_FACTORY_MODE = "governed-bundle"
FACTORY_MODES: frozenset[str] = frozenset({"lightweight-draft", "governed-bundle", "fully-autonomous"})
FACTORY_MODE_SYSTEM_NOTES: dict[str, str] = {
    "lightweight-draft": (
        "You are in lightweight-draft mode. Produce quick, draft-quality outputs "
        "with minimal verification. Focus on speed over completeness."
    ),
    "governed-bundle": (
        "You are in governed-bundle mode. Follow the full factory process: "
        "discover, decompose, design, package, and verify. Produce complete, "
        "production-ready bundles with all required artifacts."
    ),
    "fully-autonomous": (
        "You are in fully-autonomous mode. You have full authority to plan, "
        "execute, and verify work end-to-end without human approval. "
        "Document your reasoning and maintain auditability."
    ),
}

# ---------------------------------------------------------------------------
# Validation patterns
# ---------------------------------------------------------------------------
K8S_NAME_PATTERN = r"^[a-z0-9]([-a-z0-9]*[a-z0-9])?$"
K8S_NAME_RE = re.compile(K8S_NAME_PATTERN)
GIT_AUTH_METHODS: frozenset[str] = frozenset({"token", "basic", "ssh"})
GIT_PUSH_POLICIES: frozenset[str] = frozenset({"after-each-commit", "end-of-session", "on-approval", "never"})
