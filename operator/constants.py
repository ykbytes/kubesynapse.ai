"""§8 — Operator constants and enumerations for production reliability.

Centralizes magic strings, API versions, group names, and validation rules
to reduce bugs from typos and improve maintainability.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Kubernetes API conventions
# ---------------------------------------------------------------------------

API_GROUP = "kubesynapse.ai"
API_VERSION_V1ALPHA1 = "v1alpha1"
API_VERSION_STABLE = "v1"  # Reserved for GA

# Resource plurals  
RESOURCE_AGENTS = "aiagents"
RESOURCE_WORKFLOWS = "agentworkflows"
RESOURCE_POLICIES = "agentpolicies"
RESOURCE_TENANTS = "agenttenants"
RESOURCE_APPROVALS = "approvalrequests"
RESOURCE_INCIDENTS = "incidents"
RESOURCE_MCP_CONNECTIONS = "mcpconnections"
RESOURCE_WEBHOOKS = "webhooks"
RESOURCE_SIGNALS = "signals"
RESOURCE_OBSERVATIONS = "observations"

# Resource kinds
KIND_AGENT = "AIAgent"
KIND_WORKFLOW = "AgentWorkflow"
KIND_POLICY = "AgentPolicy"
KIND_TENANT = "AgentTenant"
KIND_APPROVAL = "ApprovalRequest"
KIND_INCIDENT = "Incident"
KIND_MCP_CONNECTION = "MCPConnection"
KIND_WEBHOOK = "Webhook"
KIND_SIGNAL = "Signal"
KIND_OBSERVATION = "Observation"

# ---------------------------------------------------------------------------
# Labels and annotations
# ---------------------------------------------------------------------------

LABEL_MANAGED_BY = "kubesynapse.ai/managed-by"
LABEL_MANAGED_BY_VALUE = "kubesynapse-operator"
LABEL_OWNER_AGENT = "kubesynapse.ai/owner-agent"
LABEL_OWNER_WORKFLOW = "kubesynapse.ai/owner-workflow"
LABEL_OWNER_TENANT = "kubesynapse.ai/owner-tenant"
LABEL_COMPONENT = "kubesynapse.ai/component"
LABEL_VERSION = "kubesynapse.ai/version"

ANNOTATION_FINALIZER = "kubesynapse.ai/finalizer"
ANNOTATION_SECRET_MANUAL_OVERRIDE = "kubesynapse.ai/secret-manual-override"
ANNOTATION_AUTO_RETRY_FAILED = "kubesynapse.ai/auto-retry-failed"
ANNOTATION_AUTO_RETRY_LIMIT = "kubesynapse.ai/auto-retry-limit"
ANNOTATION_AUTO_RETRY_FAILURE_CLASSES = "kubesynapse.ai/auto-retry-failure-classes"

# ---------------------------------------------------------------------------
# Workflow and execution constants
# ---------------------------------------------------------------------------

WORKFLOW_PHASE_PENDING = "pending"
WORKFLOW_PHASE_QUEUED = "queued"
WORKFLOW_PHASE_RUNNING = "running"
WORKFLOW_PHASE_PAUSED = "paused"
WORKFLOW_PHASE_COMPLETED = "completed"
WORKFLOW_PHASE_FAILED = "failed"
WORKFLOW_PHASE_ABORTED = "aborted"

VALID_WORKFLOW_PHASES = frozenset({
    WORKFLOW_PHASE_PENDING,
    WORKFLOW_PHASE_QUEUED,
    WORKFLOW_PHASE_RUNNING,
    WORKFLOW_PHASE_PAUSED,
    WORKFLOW_PHASE_COMPLETED,
    WORKFLOW_PHASE_FAILED,
    WORKFLOW_PHASE_ABORTED,
})

DEFAULT_AUTO_RETRY_LIMIT = 1
DEFAULT_AUTO_RETRY_FAILURE_CLASSES = frozenset({
    "TimeoutError",
    "ConnectTimeout",
    "ReadTimeout",
    "PoolTimeout",
    "RemoteProtocolError",
    "ConnectError",
    "ReadError",
    "ApiException",
})
NON_RETRYABLE_FAILURE_CLASSES = frozenset({"ReviewRejectedError", "ApprovalDenied"})

# ---------------------------------------------------------------------------
# Agent and session constants
# ---------------------------------------------------------------------------

AGENT_STATUS_INITIALIZING = "initializing"
AGENT_STATUS_READY = "ready"
AGENT_STATUS_ERROR = "error"
AGENT_STATUS_TERMINATING = "terminating"

SESSION_STATUS_ACTIVE = "active"
SESSION_STATUS_COMPLETED = "completed"
SESSION_STATUS_FAILED = "failed"

# ---------------------------------------------------------------------------
# Database constraints
# ---------------------------------------------------------------------------

MAX_WORKFLOW_NAME_LENGTH = 128
MAX_NAMESPACE_LENGTH = 63  # Kubernetes limit
MAX_SECRET_SIZE_BYTES = 1048576  # 1 MiB
MAX_LOG_FIELD_LENGTH = 400
MAX_JSON_DEPTH = 50  # Prevent DoS from deep nesting

# ---------------------------------------------------------------------------
# Retry and backoff constants
# ---------------------------------------------------------------------------

MAX_RECONCILIATION_RETRIES = 10
BACKOFF_JITTER_MAX_SECONDS = 5
BACKOFF_MIN_SECONDS = 5
BACKOFF_MAX_SECONDS = 120

# Kubernetes API specific
TRANSIENT_API_ERROR_CODES = frozenset({429, 500, 502, 503, 504})
PERMANENT_API_ERROR_CODES = frozenset({400, 401, 403, 404, 405, 422})

# Database errors
TRANSIENT_DB_ERROR_KEYWORDS = frozenset({
    "connection refused",
    "connection reset",
    "timeout",
    "deadlock",
    "too many connections",
    "ssl",
    "eof",
    "no route to host",
})

# ---------------------------------------------------------------------------
# Operator configuration constants
# ---------------------------------------------------------------------------

DEFAULT_OPERATOR_NAMESPACE = "kubesynapse"
DEFAULT_OPERATOR_LOG_LEVEL = "INFO"
DEFAULT_OPERATOR_HEALTH_PORT = 8080
DEFAULT_OPERATOR_PEERING_NAME = "kubesynapse-operator"

# Health check settings
HEALTH_CHECK_INTERVAL = 30  # seconds
HEALTH_CHECK_TIMEOUT = 5
HEALTH_CHECK_START_PERIOD = 10
HEALTH_CHECK_RETRIES = 3

# Lease/leadership settings
LEADER_ELECTION_LEASE_DURATION = 30  # seconds
LEADER_ELECTION_STANDBY_DELAY = 15  # seconds

# Circuit breaker settings
CIRCUIT_BREAKER_FAILURE_THRESHOLD = 5
CIRCUIT_BREAKER_RECOVERY_TIMEOUT = 30  # seconds
CIRCUIT_BREAKER_HALF_OPEN_MAX_CALLS = 1

# ---------------------------------------------------------------------------
# Validation patterns and ranges
# ---------------------------------------------------------------------------

# Resource naming (RFC 1123 compatible)
VALID_RESOURCE_NAME_PATTERN = r"^[a-z0-9]([-a-z0-9]*[a-z0-9])?$"

# Cloud provider identifiers
VALID_CLOUD_PROVIDERS = frozenset({
    "aws",
    "gcp",
    "azure",
    "local",
})

# ---------------------------------------------------------------------------
# Feature flags and deprecation markers
# ---------------------------------------------------------------------------

FEATURE_STATE_DB_ENABLED = True  # Can be disabled for dev/test
FEATURE_MCP_HUB_ENABLED = True
FEATURE_WEBHOOK_VALIDATION_ENABLED = True
DEPRECATED_API_VERSIONS = frozenset()  # Future deprecations go here
