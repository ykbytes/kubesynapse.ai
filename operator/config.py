"""Centralised operator configuration loaded from environment variables.

§2.1a of the road-to-prod plan: extract all ~60 os.getenv() calls from
main.py into a single config module with typed helper functions and
module-level constants.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

logger = logging.getLogger("operator.config")

# ---------------------------------------------------------------------------
# Environment helper functions
# ---------------------------------------------------------------------------


def get_string_env(name: str, default: str) -> str:
    """Read a string environment variable with fallback."""
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip() or default


def get_int_env(name: str, default: int, minimum: int = 0) -> int:
    """Read an integer environment variable with bounds checking."""
    raw_value = os.getenv(name)
    if raw_value is None:
        return max(default, minimum)
    try:
        return max(int(raw_value.strip()), minimum)
    except ValueError:
        logger.warning("Invalid integer value for %s=%r. Falling back to %s.", name, raw_value, default)
        return max(default, minimum)


def get_float_env(name: str, default: float, minimum: float = 0.0) -> float:
    """Read a float environment variable with bounds checking."""
    raw_value = os.getenv(name)
    if raw_value is None:
        return max(default, minimum)
    try:
        return max(float(raw_value.strip()), minimum)
    except ValueError:
        logger.warning("Invalid float value for %s=%r. Falling back to %s.", name, raw_value, default)
        return max(default, minimum)


def get_bool_env(name: str, default: bool) -> bool:
    """Read a boolean environment variable (true/false/1/0/yes/no)."""
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    normalized = raw_value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    logger.warning("Invalid boolean value for %s=%r. Falling back to %s.", name, raw_value, default)
    return default


def get_csv_env(name: str) -> list[str]:
    """Read a comma-separated environment variable into a list."""
    raw_value = os.getenv(name, "")
    return [item.strip() for item in raw_value.split(",") if item.strip()]


def get_json_env(name: str, default: Any) -> Any:
    """Read a JSON-encoded environment variable with fallback."""
    raw_value = os.getenv(name, "").strip()
    if not raw_value:
        return default
    try:
        return json.loads(raw_value)
    except ValueError:
        logger.warning("Invalid JSON value for %s. Falling back to default.", name)
        return default


def serialize_env_value(value: Any) -> str:
    """Serialize a Python value for injection into container environment."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, (list, dict)):
        return json.dumps(value)
    return str(value)


# ---------------------------------------------------------------------------
# Service endpoints & images
# ---------------------------------------------------------------------------

LITELLM_SVC: str = os.getenv("LITELLM_SVC_NAME", "kubesynapse-litellm")
SECRET_NAME: str = os.getenv("LLM_SECRET_NAME", "kubesynapse-llm-api-keys")

OPENCODE_RUNTIME_IMAGE: str = os.getenv("OPENCODE_RUNTIME_IMAGE", "docker.io/kubesynapse/kubesynapse-opencode-rt:v1.0.0")
OPENCODE_RUNTIME_IMAGE_PULL_POLICY: str = get_string_env("OPENCODE_RUNTIME_IMAGE_PULL_POLICY", "IfNotPresent")
OPENCODE_DEFAULT_PROVIDER: str = get_string_env("OPENCODE_DEFAULT_PROVIDER", "litellm")

PI_RUNTIME_IMAGE: str = os.getenv("PI_RUNTIME_IMAGE", "kubesynapse-pi-rt:v0.1.0")
PI_RUNTIME_IMAGE_PULL_POLICY: str = get_string_env("PI_RUNTIME_IMAGE_PULL_POLICY", "IfNotPresent")
PI_DEFAULT_PROVIDER: str = get_string_env("PI_DEFAULT_PROVIDER", "")
PI_DEFAULT_MODEL: str = get_string_env("PI_DEFAULT_MODEL", "anthropic/claude-sonnet-4-20250514")
PI_DEFAULT_THINKING_LEVEL: str = get_string_env("PI_DEFAULT_THINKING_LEVEL", "medium")

MISTRAL_VIBE_RUNTIME_IMAGE: str = os.getenv("MISTRAL_VIBE_RUNTIME_IMAGE", "kubesynapse-vibe-rt:v0.1.0")
MISTRAL_VIBE_RUNTIME_IMAGE_PULL_POLICY: str = get_string_env("MISTRAL_VIBE_RUNTIME_IMAGE_PULL_POLICY", "IfNotPresent")

CREDENTIAL_PROXY_IMAGE: str = os.getenv("CREDENTIAL_PROXY_IMAGE", "docker.io/kubesynapse/credential-proxy:v1.0.0")
CREDENTIAL_PROXY_IMAGE_PULL_POLICY: str = get_string_env("CREDENTIAL_PROXY_IMAGE_PULL_POLICY", "IfNotPresent")
CREDENTIAL_PROXY_ENABLED: bool = os.getenv("CREDENTIAL_PROXY_ENABLED", "true").strip().lower() in ("true", "1", "yes")

# When set, overrides the default RUNTIME_AUTH_REQUIRED derivation from CREDENTIAL_PROXY_ENABLED.
# Accepts "true"/"false"/"1"/"0"/"yes"/"no". Empty string means use default.
_RUNTIME_AUTH_REQUIRED_RAW: str = os.getenv("RUNTIME_AUTH_REQUIRED", "").strip().lower()
RUNTIME_AUTH_REQUIRED_OVERRIDE: bool | None = (
    _RUNTIME_AUTH_REQUIRED_RAW in ("true", "1", "yes") if _RUNTIME_AUTH_REQUIRED_RAW else None
)

RUNTIME_SERVICE_ACCOUNT: str = os.getenv("RUNTIME_SERVICE_ACCOUNT", "kubesynapse-agent-runtime")
RUNTIME_CLUSTER_ROLE: str = os.getenv("RUNTIME_CLUSTER_ROLE", "kubesynapse-agent-runtime-role")

# ---------------------------------------------------------------------------
# Infrastructure services
# ---------------------------------------------------------------------------

QDRANT_SVC: str = os.getenv("QDRANT_SVC_NAME", "kubesynapse-qdrant")
OTEL_ENDPOINT: str = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip()

# ---------------------------------------------------------------------------
# Storage & secrets
# ---------------------------------------------------------------------------

DEFAULT_STORAGE_SIZE: str = os.getenv("AGENT_STORAGE_SIZE", "1Gi")
CLUSTER_SECRET_STORE: str = os.getenv("CLUSTER_SECRET_STORE", "kubesynapse-vault-backend")
SECRET_PROVISIONING_MODE: str = os.getenv("SECRET_PROVISIONING_MODE", "native").strip().lower() or "native"
DEFAULT_LITELLM_MASTER_KEY: str = os.getenv("DEFAULT_LITELLM_MASTER_KEY", "").strip()
DEFAULT_API_GATEWAY_SHARED_TOKEN: str = os.getenv("DEFAULT_API_GATEWAY_SHARED_TOKEN", "").strip()
API_GATEWAY_INTERNAL_URL: str = os.getenv("API_GATEWAY_INTERNAL_URL", "").strip()
# §security-R5: optional operator-minted HMAC secret used to bind the
# shared gateway token to a specific agent + namespace. When set, the
# operator uses this secret both to compute the per-agent identity
# digest in the runtime env and as the validation key on the api-gateway
# side. When empty, the api-gateway falls back to its
# RUNTIME_IDENTITY_HMAC_SECRET env var.
RUNTIME_IDENTITY_HMAC_SECRET: str = os.getenv("RUNTIME_IDENTITY_HMAC_SECRET", "").strip()
# ---------------------------------------------------------------------------
# Static constants (not loaded from environment)
# ---------------------------------------------------------------------------

API_PORT: int = 8080
PROTECTED_NAMESPACES: frozenset[str] = frozenset({"default", "kube-system", "kube-public", "kube-node-lease"})
ARTIFACT_MOUNT_PATH: str = "/artifacts"
SUPPORTED_RUNTIME_KINDS: frozenset[str] = frozenset({"opencode", "pi", "mistral-vibe"})

# ---------------------------------------------------------------------------
# Operator & worker settings
# ---------------------------------------------------------------------------

OPERATOR_NAMESPACE: str = os.getenv("OPERATOR_NAMESPACE", "default").strip() or "default"
OPERATOR_PEERING_NAME: str = get_string_env("OPERATOR_PEERING_NAME", "kubesynapse-operator")

WORKER_IMAGE: str = os.getenv("WORKER_IMAGE", "docker.io/kubesynapse/kubesynapse-operator:v1.0.0")
WORKER_SERVICE_ACCOUNT_NAME: str = os.getenv("WORKER_SERVICE_ACCOUNT_NAME", "default").strip() or "default"
TENANT_EXEC_ACCESS: bool = os.getenv("TENANT_EXEC_ACCESS", "").strip().lower() in ("1", "true", "yes")
OPENCODE_IMMUTABLE_CONFIG: bool = os.getenv("OPENCODE_IMMUTABLE_CONFIG", "true").strip().lower() in ("1", "true", "yes")
PI_IMMUTABLE_CONFIG: bool = os.getenv("PI_IMMUTABLE_CONFIG", "true").strip().lower() in ("1", "true", "yes")
WORKER_ARTIFACT_SIZE: str = os.getenv("WORKER_ARTIFACT_SIZE", "2Gi")
WORKER_ARTIFACT_STORAGE_CLASS: str = os.getenv("WORKER_ARTIFACT_STORAGE_CLASS", "").strip()
WORKER_TTL_SECONDS_AFTER_FINISHED: int = get_int_env("WORKER_TTL_SECONDS_AFTER_FINISHED", 3600, minimum=0)
WORKER_ACTIVE_DEADLINE_SECONDS: int = get_int_env("WORKER_ACTIVE_DEADLINE_SECONDS", 14400, minimum=60)
WORKER_IMAGE_PULL_POLICY: str = os.getenv("WORKER_IMAGE_PULL_POLICY", "IfNotPresent").strip() or "IfNotPresent"

# §2.7 — Per-tenant concurrency limit for parallel workflow steps
DEFAULT_MAX_PARALLEL_STEPS: int = get_int_env("DEFAULT_MAX_PARALLEL_STEPS", 4, minimum=1)
WORKER_CPU_REQUEST: str = os.getenv("WORKER_CPU_REQUEST", "100m").strip() or "100m"
WORKER_MEMORY_REQUEST: str = os.getenv("WORKER_MEMORY_REQUEST", "128Mi").strip() or "128Mi"
WORKER_CPU_LIMIT: str = os.getenv("WORKER_CPU_LIMIT", "500m").strip() or "500m"
WORKER_MEMORY_LIMIT: str = os.getenv("WORKER_MEMORY_LIMIT", "512Mi").strip() or "512Mi"

# ---------------------------------------------------------------------------
# Agent runtime tuning
# ---------------------------------------------------------------------------

AGENT_RUNTIME_TIMEOUT_SECONDS: str = str(get_float_env("AGENT_RUNTIME_TIMEOUT_SECONDS", 360.0, minimum=1.0))

WORKFLOW_POLL_SECONDS: int = get_int_env("WORKFLOW_POLL_SECONDS", 30, minimum=15)
WORKFLOW_QUEUE_STALE_SECONDS: int = get_int_env("WORKFLOW_QUEUE_STALE_SECONDS", 300, minimum=60)
WORKFLOW_RUNNING_STALE_SECONDS: int = get_int_env("WORKFLOW_RUNNING_STALE_SECONDS", 900, minimum=60)

# ---------------------------------------------------------------------------
# HITL (Human-in-the-loop)
# ---------------------------------------------------------------------------

AGENT_HITL_MODE: str = os.getenv("AGENT_HITL_MODE", "enforce").strip().lower()
HITL_NOTIFICATION_WEBHOOK_URL: str = os.getenv("HITL_NOTIFICATION_WEBHOOK_URL", "").strip()

# ---------------------------------------------------------------------------
# Agent resource limits
# ---------------------------------------------------------------------------

AGENT_CPU_REQUEST: str = os.getenv("AGENT_CPU_REQUEST", "100m").strip() or "100m"
AGENT_MEMORY_REQUEST: str = os.getenv("AGENT_MEMORY_REQUEST", "256Mi").strip() or "256Mi"
AGENT_CPU_LIMIT: str = os.getenv("AGENT_CPU_LIMIT", "1").strip() or "1"
AGENT_MEMORY_LIMIT: str = os.getenv("AGENT_MEMORY_LIMIT", "1Gi").strip() or "1Gi"

# ---------------------------------------------------------------------------
# A2A (Agent-to-Agent) communication
# ---------------------------------------------------------------------------

A2A_DEFAULT_TIMEOUT_SECONDS: float = get_float_env("A2A_DEFAULT_TIMEOUT_SECONDS", 60.0, minimum=1.0)
IMAGE_PULL_SECRETS: list[str] = get_csv_env("IMAGE_PULL_SECRETS")

# Env var names referenced by handlers when building container env blocks.
A2A_ALLOWED_CALLERS_ENV: str = "A2A_ALLOWED_CALLERS_JSON"
A2A_ALLOWED_TARGETS_ENV: str = "A2A_ALLOWED_TARGETS_JSON"
A2A_REQUIRE_HITL_ENV: str = "A2A_REQUIRE_HITL"
A2A_MAX_TIMEOUT_SECONDS_ENV: str = "A2A_MAX_TIMEOUT_SECONDS"

# ---------------------------------------------------------------------------
# MCP Hub
# ---------------------------------------------------------------------------

MCP_HUB_NAMESPACE: str = os.getenv("MCP_HUB_NAMESPACE", "mcp-hub").strip()
MCP_AUTH_SECRET_NAME: str = os.getenv("MCP_AUTH_SECRET_NAME", "kubesynapse-mcp-auth").strip()
HELM_RELEASE_NAME: str = os.getenv("HELM_RELEASE_NAME", "kubesynapse").strip() or "kubesynapse"
PROVIDER_REGISTRY_CONFIGMAP_NAME: str = os.getenv(
    "PROVIDER_REGISTRY_CONFIGMAP_NAME",
    f"{HELM_RELEASE_NAME}-provider-registry",
).strip()

# ---------------------------------------------------------------------------
# Runtime extra env & config file env-var names
# ---------------------------------------------------------------------------

OPENCODE_RUNTIME_EXTRA_ENV: Any = get_json_env("OPENCODE_RUNTIME_EXTRA_ENV_JSON", {})
OPENCODE_RUNTIME_CONFIG_FILES_ENV: str = "OPENCODE_RUNTIME_CONFIG_FILES_JSON"
OPENCODE_MCP_CONNECTIONS_ENV: str = "OPENCODE_MCP_CONNECTIONS_JSON"
OPENCODE_MCP_SIDECARS_ENV: str = "OPENCODE_MCP_SIDECARS_JSON"
AGENT_SKILL_FILES_ENV: str = "AGENT_SKILL_FILES_JSON"

# ---------------------------------------------------------------------------
# OPA sidecar configuration
# ---------------------------------------------------------------------------
OPA_SIDECAR_IMAGE: str = os.getenv("OPA_SIDECAR_IMAGE", "openpolicyagent/opa:latest-static").strip() or "openpolicyagent/opa:latest-static"
OPA_SIDECAR_PORT: int = get_int_env("OPA_SIDECAR_PORT", 8181, minimum=1)
OPA_SIDECAR_RESOURCES: Any = get_json_env("OPA_SIDECAR_RESOURCES_JSON", {
    "requests": {"cpu": "50m", "memory": "64Mi"},
    "limits": {"cpu": "200m", "memory": "256Mi"},
})

# ---------------------------------------------------------------------------
# MCP sidecar catalog (mutable — populated once at import time)
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Orphan pruning (§kagent-pattern-6)
# ---------------------------------------------------------------------------

ORPHAN_PRUNING_ENABLED: bool = os.getenv("ORPHAN_PRUNING_ENABLED", "true").strip().lower() in ("true", "1", "yes")

# ---------------------------------------------------------------------------
# MCP sidecar catalog (mutable — populated once at import time)
# ---------------------------------------------------------------------------

MCP_SIDECAR_CATALOG: dict[str, dict[str, Any]] = {}


# ---------------------------------------------------------------------------
# Execution Observatory trace client settings
# ---------------------------------------------------------------------------

GATEWAY_URL: str = get_string_env("GATEWAY_URL", "") or get_string_env("API_GATEWAY_INTERNAL_URL", "http://api-gateway:8080")
WORKER_TRACE_ENABLED: bool = get_bool_env("WORKER_TRACE_ENABLED", True)
WORKER_TRACE_BATCH_SIZE: int = get_int_env("WORKER_TRACE_BATCH_SIZE", 50, minimum=1)
WORKER_TRACE_FLUSH_INTERVAL_SEC: int = get_int_env("WORKER_TRACE_FLUSH_INTERVAL_SEC", 5, minimum=1)


def _load_mcp_sidecar_catalog() -> None:
    """Load the MCP sidecar catalog from the MCP_SIDECAR_CATALOG_JSON env var."""
    raw = os.getenv("MCP_SIDECAR_CATALOG_JSON", "").strip()
    if not raw:
        return
    try:
        catalog = json.loads(raw)
        if isinstance(catalog, dict):
            MCP_SIDECAR_CATALOG.update(catalog)
    except (json.JSONDecodeError, TypeError):
        logger.warning("MCP_SIDECAR_CATALOG_JSON is not valid JSON; ignoring.")


_load_mcp_sidecar_catalog()
