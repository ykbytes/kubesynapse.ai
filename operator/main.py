import copy
import logging
import os
import re
import time
import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Callable

from croniter import CroniterBadCronError, croniter  # type: ignore[import-untyped]
from utils import (
    build_eval_run_id,
    build_workflow_run_id,
    merge_goose_config_files,
    now_iso,
    parse_a2a_peer_refs,
    parse_agent_a2a_config,
    parse_agent_skills_config,
    parse_policy_a2a_config,
    parse_goose_config_files,
    parse_runtime_config_files,
    validate_supported_policy_spec,
    validate_workflow_graph,
    workflow_journal_path,
)
from state_store import init_database as init_state_database, safe_record_eval_state, safe_record_workflow_state
import kopf

import kubernetes.client  # type: ignore[import-untyped]
import kubernetes.config  # type: ignore[import-untyped]
from kubernetes.client.rest import ApiException  # type: ignore[import-untyped]

try:
    from pythonjsonlogger import jsonlogger as _jsonlogger  # type: ignore[import-untyped]
except ModuleNotFoundError:  # pragma: no cover
    _jsonlogger = None


def _configure_logging() -> None:
    log_level = os.getenv("OPERATOR_LOG_LEVEL", "INFO").upper()
    handler = logging.StreamHandler()
    if os.getenv("JSON_LOGS", "true").lower() in {"1", "true"} and _jsonlogger is not None:
        handler.setFormatter(_jsonlogger.JsonFormatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    else:
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    logging.basicConfig(level=log_level, handlers=[handler], force=True)


_configure_logging()
logger = logging.getLogger("operator")

ApiTypeError = getattr(kubernetes.client, "ApiTypeError", TypeError)

PERMANENT_API_ERROR_STATUSES = {400, 401, 403, 404, 405, 422}
HIGH_BACKOFF_API_ERROR_STATUSES = {429, 500, 502, 503, 504}
MAX_LOG_FIELD_LENGTH = 400
POD_TEMPLATE_REVISION_ANNOTATION = "sandbox.enterprise.ai/pod-template-revision"
KUBERNETES_RESOURCE_NAME_PATTERN = re.compile(r"^[a-z0-9](?:[-a-z0-9]*[a-z0-9])?$")
STORAGE_QUANTITY_MULTIPLIERS: dict[str, Decimal] = {
    "": Decimal(1),
    "n": Decimal("1e-9"),
    "m": Decimal("1e-3"),
    "k": Decimal(1000),
    "K": Decimal(1000),
    "M": Decimal(1000**2),
    "G": Decimal(1000**3),
    "T": Decimal(1000**4),
    "P": Decimal(1000**5),
    "E": Decimal(1000**6),
    "Ki": Decimal(1024),
    "Mi": Decimal(1024**2),
    "Gi": Decimal(1024**3),
    "Ti": Decimal(1024**4),
    "Pi": Decimal(1024**5),
    "Ei": Decimal(1024**6),
}


def _serialize_log_field(value: Any) -> str:
    try:
        if isinstance(value, str):
            serialized = json.dumps(value)
        else:
            serialized = json.dumps(value, sort_keys=True, default=str)
    except TypeError:
        serialized = json.dumps(str(value))
    if len(serialized) > MAX_LOG_FIELD_LENGTH:
        return f"{serialized[: MAX_LOG_FIELD_LENGTH - 3]}..."
    return serialized


def format_log_fields(fields: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in sorted(fields):
        value = fields[key]
        if value in (None, "", [], {}):
            continue
        parts.append(f"{key}={_serialize_log_field(value)}")
    return " ".join(parts)


def resource_log_fields(
    resource_kind: str | None = None,
    name: str | None = None,
    namespace: str | None = None,
    *,
    meta: dict[str, Any] | None = None,
    generation: int | None = None,
    **extra: Any,
) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    if resource_kind:
        fields["resourceKind"] = resource_kind
    if name:
        fields["name"] = name
    if namespace:
        fields["namespace"] = namespace
    resolved_generation = generation
    if resolved_generation is None and meta is not None:
        resolved_generation = int((meta or {}).get("generation", 0) or 0)
    if resolved_generation:
        fields["generation"] = resolved_generation
    for key, value in extra.items():
        if value in (None, "", [], {}):
            continue
        fields[key] = value
    return fields


def log_operator_event(
    logger: logging.Logger,
    level: int,
    message: str,
    *,
    resource_kind: str | None = None,
    name: str | None = None,
    namespace: str | None = None,
    meta: dict[str, Any] | None = None,
    generation: int | None = None,
    **extra: Any,
) -> None:
    formatted_fields = format_log_fields(
        resource_log_fields(
            resource_kind,
            name,
            namespace,
            meta=meta,
            generation=generation,
            **extra,
        )
    )
    if formatted_fields:
        logger.log(level, "%s %s", message, formatted_fields)
        return
    logger.log(level, message)


def describe_api_exception(exc: ApiException) -> str:
    details: list[str] = []
    status = getattr(exc, "status", None)
    if status is not None:
        details.append(f"status={status}")
    reason = str(getattr(exc, "reason", "") or "").strip()
    if reason:
        details.append(f"reason={reason}")
    body = str(getattr(exc, "body", "") or "").strip()
    if body:
        if len(body) > MAX_LOG_FIELD_LENGTH:
            body = f"{body[: MAX_LOG_FIELD_LENGTH - 3]}..."
        details.append(f"body={body}")
    message = str(exc).strip()
    if message and message not in {reason, body}:
        details.append(f"message={message}")
    return ", ".join(details) or exc.__class__.__name__


def classify_reconcile_error(action: str, exc: Exception, *, default_delay: int = 10) -> Exception:
    if isinstance(exc, (kopf.PermanentError, kopf.TemporaryError)):
        return exc
    if isinstance(exc, ValueError):
        return kopf.PermanentError(str(exc))
    if isinstance(exc, ApiException):
        status = int(getattr(exc, "status", 0) or 0)
        details = describe_api_exception(exc)
        message = f"{action} failed: {details}"
        if status in PERMANENT_API_ERROR_STATUSES:
            return kopf.PermanentError(message)
        delay = max(default_delay, 30) if status in HIGH_BACKOFF_API_ERROR_STATUSES else default_delay
        return kopf.TemporaryError(message, delay=delay)
    return kopf.TemporaryError(f"{action} failed: {exc}", delay=default_delay)


def raise_reconcile_error(
    logger: logging.Logger,
    action: str,
    exc: Exception,
    *,
    resource_kind: str,
    name: str,
    namespace: str | None = None,
    meta: dict[str, Any] | None = None,
    generation: int | None = None,
    default_delay: int = 10,
    **extra: Any,
) -> None:
    resolved_error = classify_reconcile_error(action, exc, default_delay=default_delay)
    message = (
        "Reconcile operation failed permanently."
        if isinstance(resolved_error, kopf.PermanentError)
        else "Reconcile operation failed and will be retried."
    )
    log_details = resource_log_fields(
        resource_kind,
        name,
        namespace,
        meta=meta,
        generation=generation,
        action=action,
        error=str(resolved_error),
        sourceErrorType=type(exc).__name__,
        **extra,
    )
    if isinstance(exc, (kopf.PermanentError, kopf.TemporaryError)):
        logger.log(
            logging.ERROR if isinstance(resolved_error, kopf.PermanentError) else logging.WARNING,
            "%s %s",
            message,
            format_log_fields(log_details),
        )
    else:
        logger.exception("%s %s", message, format_log_fields(log_details))
    raise resolved_error from exc


def execute_reconcile(
    operation: Callable[[], Any],
    *,
    logger: logging.Logger,
    action: str,
    resource_kind: str,
    name: str,
    namespace: str | None = None,
    meta: dict[str, Any] | None = None,
    generation: int | None = None,
    default_delay: int = 10,
    start_message: str | None = None,
    success_message: str | None = None,
    **extra: Any,
) -> Any:
    if start_message:
        log_operator_event(
            logger,
            logging.INFO,
            start_message,
            resource_kind=resource_kind,
            name=name,
            namespace=namespace,
            meta=meta,
            generation=generation,
            action=action,
            **extra,
        )
    try:
        result = operation()
    except Exception as exc:
        raise_reconcile_error(
            logger,
            action,
            exc,
            resource_kind=resource_kind,
            name=name,
            namespace=namespace,
            meta=meta,
            generation=generation,
            default_delay=default_delay,
            **extra,
        )
    if success_message:
        log_operator_event(
            logger,
            logging.INFO,
            success_message,
            resource_kind=resource_kind,
            name=name,
            namespace=namespace,
            meta=meta,
            generation=generation,
            action=action,
            **extra,
        )
    return result


def get_string_env(name: str, default: str) -> str:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip() or default


def get_int_env(name: str, default: int, minimum: int = 0) -> int:
    raw_value = os.getenv(name)
    if raw_value is None:
        return max(default, minimum)
    try:
        return max(int(raw_value.strip()), minimum)
    except ValueError:
        logger.warning("Invalid integer value for %s=%r. Falling back to %s.", name, raw_value, default)
        return max(default, minimum)


def get_float_env(name: str, default: float, minimum: float = 0.0) -> float:
    raw_value = os.getenv(name)
    if raw_value is None:
        return max(default, minimum)
    try:
        return max(float(raw_value.strip()), minimum)
    except ValueError:
        logger.warning("Invalid float value for %s=%r. Falling back to %s.", name, raw_value, default)
        return max(default, minimum)


def get_bool_env(name: str, default: bool) -> bool:
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
    raw_value = os.getenv(name, "")
    return [item.strip() for item in raw_value.split(",") if item.strip()]


def get_json_env(name: str, default: Any) -> Any:
    raw_value = os.getenv(name, "").strip()
    if not raw_value:
        return default
    try:
        return json.loads(raw_value)
    except ValueError:
        logger.warning("Invalid JSON value for %s. Falling back to default.", name)
        return default


def serialize_env_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, (list, dict)):
        return json.dumps(value)
    return str(value)


LITELLM_SVC = os.getenv("LITELLM_SVC_NAME", "ai-agent-sandbox-litellm")
SECRET_NAME = os.getenv("LLM_SECRET_NAME", "ai-agent-sandbox-llm-api-keys")
RUNTIME_IMAGE = os.getenv("AGENT_RUNTIME_IMAGE", "ghcr.io/your-org/ai-agent-runtime:latest")
RUNTIME_IMAGE_PULL_POLICY = get_string_env("AGENT_RUNTIME_IMAGE_PULL_POLICY", "IfNotPresent")
GOOSE_RUNTIME_IMAGE = os.getenv("GOOSE_RUNTIME_IMAGE", "ghcr.io/your-org/ai-goose-runtime:latest")
GOOSE_RUNTIME_IMAGE_PULL_POLICY = get_string_env("GOOSE_RUNTIME_IMAGE_PULL_POLICY", "IfNotPresent")
GOOSE_DEFAULT_PROVIDER = get_string_env("GOOSE_DEFAULT_PROVIDER", "litellm")
CODEX_RUNTIME_IMAGE = os.getenv("CODEX_RUNTIME_IMAGE", "ghcr.io/your-org/ai-codex-runtime:latest")
CODEX_RUNTIME_IMAGE_PULL_POLICY = get_string_env("CODEX_RUNTIME_IMAGE_PULL_POLICY", "IfNotPresent")
CODEX_DEFAULT_PROVIDER = get_string_env("CODEX_DEFAULT_PROVIDER", "litellm")
OPENCODE_RUNTIME_IMAGE = os.getenv("OPENCODE_RUNTIME_IMAGE", "yakdhane/ai-opencode-runtime:latest")
OPENCODE_RUNTIME_IMAGE_PULL_POLICY = get_string_env("OPENCODE_RUNTIME_IMAGE_PULL_POLICY", "IfNotPresent")
OPENCODE_DEFAULT_PROVIDER = get_string_env("OPENCODE_DEFAULT_PROVIDER", "litellm")
RUNTIME_SERVICE_ACCOUNT = os.getenv("RUNTIME_SERVICE_ACCOUNT", "ai-agent-runtime")
RUNTIME_CLUSTER_ROLE = os.getenv("RUNTIME_CLUSTER_ROLE", "ai-agent-runtime-role")
QDRANT_SVC = os.getenv("QDRANT_SVC_NAME", "ai-agent-sandbox-qdrant")
QDRANT_COLLECTION = os.getenv("QDRANT_COLLECTION", "agent-knowledge")
OTEL_ENDPOINT = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip()
DEFAULT_STORAGE_SIZE = os.getenv("AGENT_STORAGE_SIZE", "1Gi")
CLUSTER_SECRET_STORE = os.getenv("CLUSTER_SECRET_STORE", "ai-agent-sandbox-vault-backend")
SECRET_PROVISIONING_MODE = os.getenv("SECRET_PROVISIONING_MODE", "native").strip().lower() or "native"
DEFAULT_LITELLM_MASTER_KEY = os.getenv("DEFAULT_LITELLM_MASTER_KEY", "").strip()
DEFAULT_API_GATEWAY_SHARED_TOKEN = os.getenv("DEFAULT_API_GATEWAY_SHARED_TOKEN", "").strip()
API_GATEWAY_INTERNAL_URL = os.getenv("API_GATEWAY_INTERNAL_URL", "").strip()
API_PORT = 8080
PROTECTED_NAMESPACES = {"default", "kube-system", "kube-public", "kube-node-lease"}
OPERATOR_NAMESPACE = os.getenv("OPERATOR_NAMESPACE", "default").strip() or "default"
OPERATOR_PEERING_NAME = get_string_env("OPERATOR_PEERING_NAME", "ai-agent-sandbox-operator")
WORKER_IMAGE = os.getenv("WORKER_IMAGE", "ghcr.io/your-org/ai-operator:latest")
WORKER_SERVICE_ACCOUNT_NAME = os.getenv("WORKER_SERVICE_ACCOUNT_NAME", "default").strip() or "default"
WORKER_ARTIFACT_SIZE = os.getenv("WORKER_ARTIFACT_SIZE", "2Gi")
WORKER_ARTIFACT_STORAGE_CLASS = os.getenv("WORKER_ARTIFACT_STORAGE_CLASS", "").strip()
WORKER_TTL_SECONDS_AFTER_FINISHED = get_int_env("WORKER_TTL_SECONDS_AFTER_FINISHED", 3600, minimum=0)
WORKER_ACTIVE_DEADLINE_SECONDS = get_int_env("WORKER_ACTIVE_DEADLINE_SECONDS", 1800, minimum=60)
WORKER_IMAGE_PULL_POLICY = os.getenv("WORKER_IMAGE_PULL_POLICY", "IfNotPresent").strip() or "IfNotPresent"
WORKER_CPU_REQUEST = os.getenv("WORKER_CPU_REQUEST", "100m").strip() or "100m"
WORKER_MEMORY_REQUEST = os.getenv("WORKER_MEMORY_REQUEST", "128Mi").strip() or "128Mi"
WORKER_CPU_LIMIT = os.getenv("WORKER_CPU_LIMIT", "500m").strip() or "500m"
WORKER_MEMORY_LIMIT = os.getenv("WORKER_MEMORY_LIMIT", "512Mi").strip() or "512Mi"
AGENT_RUNTIME_TIMEOUT_SECONDS = str(get_float_env("AGENT_RUNTIME_TIMEOUT_SECONDS", 360.0, minimum=1.0))
EVAL_SCHEDULE_POLL_SECONDS = get_int_env("EVAL_SCHEDULE_POLL_SECONDS", 60, minimum=15)
SCHEDULED_EVAL_QUEUE_STALE_SECONDS = get_int_env("SCHEDULED_EVAL_QUEUE_STALE_SECONDS", 600, minimum=60)
WORKFLOW_POLL_SECONDS = get_int_env("WORKFLOW_POLL_SECONDS", 30, minimum=15)
WORKFLOW_QUEUE_STALE_SECONDS = get_int_env("WORKFLOW_QUEUE_STALE_SECONDS", 300, minimum=60)
WORKFLOW_RUNNING_STALE_SECONDS = get_int_env("WORKFLOW_RUNNING_STALE_SECONDS", 900, minimum=60)
ARTIFACT_MOUNT_PATH = "/artifacts"
AGENT_HITL_MODE = os.getenv("AGENT_HITL_MODE", "enforce").strip().lower()
HITL_NOTIFICATION_WEBHOOK_URL = os.getenv("HITL_NOTIFICATION_WEBHOOK_URL", "").strip()
AGENT_CPU_REQUEST = os.getenv("AGENT_CPU_REQUEST", "100m").strip() or "100m"
AGENT_MEMORY_REQUEST = os.getenv("AGENT_MEMORY_REQUEST", "256Mi").strip() or "256Mi"
AGENT_CPU_LIMIT = os.getenv("AGENT_CPU_LIMIT", "1").strip() or "1"
AGENT_MEMORY_LIMIT = os.getenv("AGENT_MEMORY_LIMIT", "1Gi").strip() or "1Gi"
AGENT_ALLOWED_MODELS = get_csv_env("AGENT_ALLOWED_MODELS")
AGENT_MAX_STEPS = str(get_int_env("AGENT_MAX_STEPS", 4, minimum=1))
AGENT_MAX_STEPS_LIMIT = str(get_int_env("AGENT_MAX_STEPS_LIMIT", 12, minimum=1))
AGENT_DOOM_LOOP_THRESHOLD = str(get_int_env("AGENT_DOOM_LOOP_THRESHOLD", 3, minimum=2))
AGENT_SUPERVISOR_HISTORY_LIMIT = str(get_int_env("AGENT_SUPERVISOR_HISTORY_LIMIT", 8, minimum=1))
AGENT_SUPERVISOR_RESPONSE_CHARS = str(get_int_env("AGENT_SUPERVISOR_RESPONSE_CHARS", 12000, minimum=256))
AGENT_AUTONOMY_CONTINUE_ON_ACTION_ERROR = serialize_env_value(
    get_bool_env("AGENT_AUTONOMY_CONTINUE_ON_ACTION_ERROR", True)
)
AGENT_AUTONOMY_ACTION_RETRY_LIMIT = str(get_int_env("AGENT_AUTONOMY_ACTION_RETRY_LIMIT", 2, minimum=0))
AGENT_AUTONOMY_ACTION_RETRY_BACKOFF_SECONDS = str(
    get_float_env("AGENT_AUTONOMY_ACTION_RETRY_BACKOFF_SECONDS", 1.0, minimum=0.0)
)
AGENT_AUTONOMY_FAILURE_HISTORY_LIMIT = str(get_int_env("AGENT_AUTONOMY_FAILURE_HISTORY_LIMIT", 6, minimum=1))
DEFAULT_AGENT_LOCAL_TOOL_ALLOWLIST = "curl,wget,jq,git,rg,tar,unzip,zip"
DEFAULT_AGENT_LOCAL_TOOL_ALLOWED_ROOTS = "/app/state,/workspace"
AGENT_LOCAL_TOOL_MOUNT_WORKSPACE = get_bool_env("AGENT_LOCAL_TOOL_MOUNT_WORKSPACE", True)
AGENT_LOCAL_TOOL_DISCOVERY_ENABLED = serialize_env_value(get_bool_env("AGENT_LOCAL_TOOL_DISCOVERY_ENABLED", True))
AGENT_LOCAL_TOOL_ALLOWLIST = os.getenv("AGENT_LOCAL_TOOL_ALLOWLIST", DEFAULT_AGENT_LOCAL_TOOL_ALLOWLIST).strip()
AGENT_LOCAL_TOOL_TIMEOUT_SECONDS = str(get_float_env("AGENT_LOCAL_TOOL_TIMEOUT_SECONDS", 20.0, minimum=1.0))
AGENT_LOCAL_TOOL_MAX_OUTPUT_CHARS = str(get_int_env("AGENT_LOCAL_TOOL_MAX_OUTPUT_CHARS", 12000, minimum=512))
AGENT_LOCAL_TOOL_MAX_ARGS = str(get_int_env("AGENT_LOCAL_TOOL_MAX_ARGS", 32, minimum=1))
AGENT_LOCAL_TOOL_MAX_ARG_CHARS = str(get_int_env("AGENT_LOCAL_TOOL_MAX_ARG_CHARS", 512, minimum=32))
AGENT_LOCAL_TOOL_ALLOWED_ROOTS = os.getenv("AGENT_LOCAL_TOOL_ALLOWED_ROOTS", DEFAULT_AGENT_LOCAL_TOOL_ALLOWED_ROOTS).strip()
AGENT_LOCAL_TOOL_LIST_LIMIT = str(get_int_env("AGENT_LOCAL_TOOL_LIST_LIMIT", 32, minimum=1))
A2A_DEFAULT_TIMEOUT_SECONDS = get_float_env("A2A_DEFAULT_TIMEOUT_SECONDS", 60.0, minimum=1.0)
IMAGE_PULL_SECRETS = get_csv_env("IMAGE_PULL_SECRETS")
SUPPORTED_RUNTIME_KINDS = {"langgraph", "goose", "codex", "opencode"}
A2A_ALLOWED_CALLERS_ENV = "A2A_ALLOWED_CALLERS_JSON"
A2A_ALLOWED_TARGETS_ENV = "A2A_ALLOWED_TARGETS_JSON"
A2A_REQUIRE_HITL_ENV = "A2A_REQUIRE_HITL"
A2A_MAX_TIMEOUT_SECONDS_ENV = "A2A_MAX_TIMEOUT_SECONDS"
# MCP Hub: namespace where shared enterprise MCP servers run and the auth
# secret that agents must present as a bearer token on every MCP call.
MCP_HUB_NAMESPACE = os.getenv("MCP_HUB_NAMESPACE", "mcp-hub").strip()
MCP_AUTH_SECRET_NAME = os.getenv("MCP_AUTH_SECRET_NAME", "ai-agent-sandbox-mcp-auth").strip()
HELM_RELEASE_NAME = os.getenv("HELM_RELEASE_NAME", "ai-agent-sandbox").strip() or "ai-agent-sandbox"
OPEN_SANDBOX_RUNTIME_ENV: dict[str, str] = {
    "OPEN_SANDBOX_DOMAIN": os.getenv("OPEN_SANDBOX_DOMAIN", "").strip(),
    "OPEN_SANDBOX_PROTOCOL": os.getenv("OPEN_SANDBOX_PROTOCOL", "http").strip() or "http",
    "OPEN_SANDBOX_USE_SERVER_PROXY": os.getenv("OPEN_SANDBOX_USE_SERVER_PROXY", "false").strip() or "false",
    "OPEN_SANDBOX_REQUEST_TIMEOUT_SECONDS": os.getenv("OPEN_SANDBOX_REQUEST_TIMEOUT_SECONDS", "300").strip() or "300",
    "OPEN_SANDBOX_CONNECT_TIMEOUT_SECONDS": os.getenv("OPEN_SANDBOX_CONNECT_TIMEOUT_SECONDS", "30").strip() or "30",
    "OPEN_SANDBOX_DEFAULT_TTL_SECONDS": os.getenv("OPEN_SANDBOX_DEFAULT_TTL_SECONDS", "600").strip() or "600",
    "OPEN_SANDBOX_DEFAULT_IMAGE": os.getenv("OPEN_SANDBOX_DEFAULT_IMAGE", "python:3.11").strip() or "python:3.11",
    "OPEN_SANDBOX_CODE_IMAGE": os.getenv(
        "OPEN_SANDBOX_CODE_IMAGE", "opensandbox/code-interpreter:latest"
    ).strip()
    or "opensandbox/code-interpreter:latest",
    "OPEN_SANDBOX_BROWSER_IMAGE": os.getenv(
        "OPEN_SANDBOX_BROWSER_IMAGE", "opensandbox/chrome:latest"
    ).strip()
    or "opensandbox/chrome:latest",
    "OPEN_SANDBOX_EDITOR_IMAGE": os.getenv(
        "OPEN_SANDBOX_EDITOR_IMAGE", "opensandbox/vscode:latest"
    ).strip()
    or "opensandbox/vscode:latest",
    "OPEN_SANDBOX_PYTHON_VERSION": os.getenv("OPEN_SANDBOX_PYTHON_VERSION", "3.11").strip() or "3.11",
    "OPEN_SANDBOX_JAVA_VERSION": os.getenv("OPEN_SANDBOX_JAVA_VERSION", "17").strip() or "17",
    "OPEN_SANDBOX_NODE_VERSION": os.getenv("OPEN_SANDBOX_NODE_VERSION", "20").strip() or "20",
    "OPEN_SANDBOX_GO_VERSION": os.getenv("OPEN_SANDBOX_GO_VERSION", "1.24").strip() or "1.24",
    "OPEN_SANDBOX_SECURE_RUNTIME_TYPE": os.getenv("OPEN_SANDBOX_SECURE_RUNTIME_TYPE", "").strip(),
}
OPEN_SANDBOX_API_KEY_SECRET_NAME = os.getenv("OPEN_SANDBOX_API_KEY_SECRET_NAME", "").strip()
OPEN_SANDBOX_API_KEY_SECRET_KEY = os.getenv("OPEN_SANDBOX_API_KEY_SECRET_KEY", "api-key").strip() or "api-key"
AGENT_RUNTIME_EXTRA_ENV = get_json_env("AGENT_RUNTIME_EXTRA_ENV_JSON", {})
GOOSE_RUNTIME_EXTRA_ENV = get_json_env("GOOSE_RUNTIME_EXTRA_ENV_JSON", {})
GOOSE_RUNTIME_CONFIG_FILES_ENV = "GOOSE_RUNTIME_CONFIG_FILES_JSON"
CODEX_RUNTIME_EXTRA_ENV = get_json_env("CODEX_RUNTIME_EXTRA_ENV_JSON", {})
CODEX_RUNTIME_CONFIG_FILES_ENV = "CODEX_RUNTIME_CONFIG_FILES_JSON"
CODEX_MCP_SIDECARS_ENV = "CODEX_MCP_SIDECARS_JSON"
OPENCODE_RUNTIME_EXTRA_ENV = get_json_env("OPENCODE_RUNTIME_EXTRA_ENV_JSON", {})
OPENCODE_RUNTIME_CONFIG_FILES_ENV = "OPENCODE_RUNTIME_CONFIG_FILES_JSON"
OPENCODE_MCP_SIDECARS_ENV = "OPENCODE_MCP_SIDECARS_JSON"
AGENT_SKILL_FILES_ENV = "AGENT_SKILL_FILES_JSON"

# Mapping of MCP server names (as referenced in skill frontmatter) to sidecar images.
# The operator auto-injects these sidecars when a skill's allowedMcpServers references them.
MCP_SIDECAR_CATALOG: dict[str, dict[str, Any]] = {}

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


def _extract_skill_mcp_servers(skills_config: dict[str, Any]) -> set[str]:
    """Extract allowedMcpServers from skill file frontmatter."""
    servers: set[str] = set()
    files = skills_config.get("files", {})
    for content in files.values():
        if not isinstance(content, str):
            continue
        # Parse YAML frontmatter between --- delimiters
        if content.startswith("---"):
            parts = content.split("---", 2)
            if len(parts) >= 3:
                try:
                    import yaml
                    fm = yaml.safe_load(parts[1])
                    if isinstance(fm, dict):
                        mcp = fm.get("allowedMcpServers") or fm.get("allowed_mcp_servers") or []
                        if isinstance(mcp, list):
                            servers.update(s for s in mcp if isinstance(s, str))
                except Exception:
                    pass
    return servers


def _auto_inject_mcp_sidecars(
    explicit_sidecars: list[dict[str, Any]],
    skills_config: dict[str, Any],
) -> list[dict[str, Any]]:
    """Merge explicitly declared sidecars with auto-injected ones from skill frontmatter."""
    if not MCP_SIDECAR_CATALOG or not skills_config:
        return explicit_sidecars

    required_servers = _extract_skill_mcp_servers(skills_config)
    if not required_servers:
        return explicit_sidecars

    existing_names = {s.get("name") for s in explicit_sidecars}
    merged = list(explicit_sidecars)
    for server_name in sorted(required_servers):
        if server_name in existing_names:
            continue
        if server_name in MCP_SIDECAR_CATALOG:
            entry = MCP_SIDECAR_CATALOG[server_name]
            merged.append({
                "name": server_name,
                "image": entry.get("image"),
                "port": entry.get("port", 8080),
            })
            logger.info("Auto-injected MCP sidecar '%s' from skill frontmatter", server_name)
    return merged

PLATFORM_MANAGED_GOOSE_ENV = {
    "AGENT_MODEL",
    "AGENT_NAME",
    "AGENT_NAMESPACE",
    "AGENT_SYSTEM_PROMPT",
    "GOOSE_PROVIDER",
    "GOOSE_MODEL",
    "GOOSE_SYSTEM_PROMPT",
    "LITELLM_HOST",
    "LITELLM_BASE_PATH",
    "LITELLM_API_KEY",
    "HOME",
    "XDG_CONFIG_HOME",
    "XDG_DATA_HOME",
    "GOOSE_BIN",
    "GOOSE_WORKDIR",
    A2A_ALLOWED_CALLERS_ENV,
    A2A_ALLOWED_TARGETS_ENV,
    A2A_REQUIRE_HITL_ENV,
    A2A_MAX_TIMEOUT_SECONDS_ENV,
    GOOSE_RUNTIME_CONFIG_FILES_ENV,
}

PLATFORM_MANAGED_CODEX_ENV = {
    "AGENT_MODEL",
    "AGENT_NAME",
    "AGENT_NAMESPACE",
    "AGENT_SYSTEM_PROMPT",
    "CODEX_PROVIDER",
    "CODEX_MODEL",
    "CODEX_SYSTEM_PROMPT",
    "LITELLM_HOST",
    "LITELLM_BASE_PATH",
    "LITELLM_API_KEY",
    "HOME",
    "CODEX_HOME",
    "XDG_CONFIG_HOME",
    "XDG_DATA_HOME",
    "CODEX_BIN",
    "CODEX_WORKDIR",
    A2A_ALLOWED_CALLERS_ENV,
    A2A_ALLOWED_TARGETS_ENV,
    A2A_REQUIRE_HITL_ENV,
    A2A_MAX_TIMEOUT_SECONDS_ENV,
    CODEX_RUNTIME_CONFIG_FILES_ENV,
    CODEX_MCP_SIDECARS_ENV,
}

PLATFORM_MANAGED_OPENCODE_ENV = {
    "AGENT_MODEL",
    "AGENT_NAME",
    "AGENT_NAMESPACE",
    "AGENT_SYSTEM_PROMPT",
    "HELM_RELEASE_NAME",
    "LITELLM_HOST",
    "LITELLM_BASE_PATH",
    "LITELLM_API_KEY",
    "HOME",
    "XDG_CONFIG_HOME",
    "XDG_DATA_HOME",
    "OPENCODE_CONFIG_DIR",
    "OPENCODE_BIN",
    "OPENCODE_WORKDIR",
    "OPENCODE_PROVIDER",
    "OPENCODE_MODEL",
    "OPENCODE_SYSTEM_PROMPT",
    "OPENCODE_DEFAULT_AGENT",
    A2A_ALLOWED_CALLERS_ENV,
    A2A_ALLOWED_TARGETS_ENV,
    A2A_REQUIRE_HITL_ENV,
    A2A_MAX_TIMEOUT_SECONDS_ENV,
    OPENCODE_RUNTIME_CONFIG_FILES_ENV,
    OPENCODE_MCP_SIDECARS_ENV,
    "MCP_SERVERS",
    "MCP_HUB_NAMESPACE",
    "MCP_BEARER_TOKEN",
    "GITHUB_MCP_TOKEN",
} | set(OPEN_SANDBOX_RUNTIME_ENV)

PLATFORM_MANAGED_AGENT_ENV = {
    "AGENT_DEFAULT_MODEL",
    "AGENT_MODEL",
    "AGENT_ALLOWED_MODELS",
    "AGENT_MAX_STEPS",
    "AGENT_MAX_STEPS_LIMIT",
    "AGENT_DOOM_LOOP_THRESHOLD",
    "AGENT_SUPERVISOR_HISTORY_LIMIT",
    "AGENT_SUPERVISOR_RESPONSE_CHARS",
    "AGENT_AUTONOMY_CONTINUE_ON_ACTION_ERROR",
    "AGENT_AUTONOMY_ACTION_RETRY_LIMIT",
    "AGENT_AUTONOMY_ACTION_RETRY_BACKOFF_SECONDS",
    "AGENT_AUTONOMY_FAILURE_HISTORY_LIMIT",
    "AGENT_LOCAL_TOOL_MOUNT_WORKSPACE",
    "AGENT_LOCAL_TOOL_DISCOVERY_ENABLED",
    "AGENT_LOCAL_TOOL_ALLOWLIST",
    "AGENT_LOCAL_TOOL_TIMEOUT_SECONDS",
    "AGENT_LOCAL_TOOL_MAX_OUTPUT_CHARS",
    "AGENT_LOCAL_TOOL_MAX_ARGS",
    "AGENT_LOCAL_TOOL_MAX_ARG_CHARS",
    "AGENT_LOCAL_TOOL_ALLOWED_ROOTS",
    "AGENT_LOCAL_TOOL_LIST_LIMIT",
    "AGENT_NAME",
    "AGENT_NAMESPACE",
    "AGENT_SYSTEM_PROMPT",
    "API_GATEWAY_INTERNAL_URL",
    "API_GATEWAY_SHARED_TOKEN",
    A2A_ALLOWED_CALLERS_ENV,
    A2A_ALLOWED_TARGETS_ENV,
    A2A_REQUIRE_HITL_ENV,
    A2A_MAX_TIMEOUT_SECONDS_ENV,
    AGENT_SKILL_FILES_ENV,
    "LITELLM_API_BASE",
    "MCP_SERVERS",
    "MCP_SIDECARS",
    "QDRANT_URL",
    "QDRANT_COLLECTION",
    "LITELLM_API_KEY",
    "AGENT_POLICY_NAME",
    "OTEL_EXPORTER_OTLP_ENDPOINT",
    "HITL_MODE",
    "HITL_NOTIFICATION_WEBHOOK_URL",
    "MCP_HUB_NAMESPACE",
    "ALLOWED_MCP_SERVERS",
    "MCP_BEARER_TOKEN",
    "GITHUB_MCP_TOKEN",
    "OPEN_SANDBOX_API_KEY",
} | set(OPEN_SANDBOX_RUNTIME_ENV)


def runtime_extra_env_items(
    raw_env: Any,
    *,
    source_env_name: str,
    runtime_name: str,
    platform_managed_names: set[str],
) -> list[dict[str, str]]:
    if not isinstance(raw_env, dict):
        logger.warning("%s must decode to a JSON object. Ignoring it.", source_env_name)
        return []

    items: list[dict[str, str]] = []
    for raw_name, raw_value in sorted(raw_env.items(), key=lambda item: str(item[0])):
        name = str(raw_name).strip()
        if not name or raw_value is None:
            continue
        if name in platform_managed_names:
            logger.warning("Ignoring %s env override for platform-managed variable %s.", runtime_name, name)
            continue
        items.append({"name": name, "value": serialize_env_value(raw_value)})
    return items


def goose_runtime_extra_env_items() -> list[dict[str, str]]:
    return runtime_extra_env_items(
        GOOSE_RUNTIME_EXTRA_ENV,
        source_env_name="GOOSE_RUNTIME_EXTRA_ENV_JSON",
        runtime_name="goose runtime",
        platform_managed_names=PLATFORM_MANAGED_GOOSE_ENV,
    )


def codex_runtime_extra_env_items() -> list[dict[str, str]]:
    return runtime_extra_env_items(
        CODEX_RUNTIME_EXTRA_ENV,
        source_env_name="CODEX_RUNTIME_EXTRA_ENV_JSON",
        runtime_name="codex runtime",
        platform_managed_names=PLATFORM_MANAGED_CODEX_ENV,
    )


def opencode_runtime_extra_env_items() -> list[dict[str, str]]:
    return runtime_extra_env_items(
        OPENCODE_RUNTIME_EXTRA_ENV,
        source_env_name="OPENCODE_RUNTIME_EXTRA_ENV_JSON",
        runtime_name="opencode runtime",
        platform_managed_names=PLATFORM_MANAGED_OPENCODE_ENV,
    )


def agent_runtime_extra_env_items() -> list[dict[str, str]]:
    return runtime_extra_env_items(
        AGENT_RUNTIME_EXTRA_ENV,
        source_env_name="AGENT_RUNTIME_EXTRA_ENV_JSON",
        runtime_name="agent runtime",
        platform_managed_names=PLATFORM_MANAGED_AGENT_ENV,
    )


def merged_goose_runtime_config_files(spec: dict[str, Any]) -> dict[str, Any]:
    runtime_spec = spec.get("runtime") or {}
    goose_spec = runtime_spec.get("goose")
    if goose_spec is None:
        agent_config_files: Any = None
    elif isinstance(goose_spec, dict):
        agent_config_files = goose_spec.get("configFiles")
    else:
        raise kopf.PermanentError("AIAgent.spec.runtime.goose must be an object when provided.")

    try:
        return merge_goose_config_files(
            (
                GOOSE_RUNTIME_EXTRA_ENV.get(GOOSE_RUNTIME_CONFIG_FILES_ENV),
                f"GOOSE_RUNTIME_EXTRA_ENV_JSON.{GOOSE_RUNTIME_CONFIG_FILES_ENV}",
            ),
            (agent_config_files, "AIAgent.spec.runtime.goose.configFiles"),
        )
    except ValueError as exc:
        raise kopf.PermanentError(str(exc)) from exc


def merged_codex_runtime_config_files(spec: dict[str, Any]) -> dict[str, Any]:
    runtime_spec = spec.get("runtime") or {}
    codex_spec = runtime_spec.get("codex")
    if codex_spec is None:
        agent_config_files: Any = None
    elif isinstance(codex_spec, dict):
        agent_config_files = codex_spec.get("configFiles")
    else:
        raise kopf.PermanentError("AIAgent.spec.runtime.codex must be an object when provided.")

    try:
        chart_files = parse_runtime_config_files(
            CODEX_RUNTIME_EXTRA_ENV.get(CODEX_RUNTIME_CONFIG_FILES_ENV),
            source=f"CODEX_RUNTIME_EXTRA_ENV_JSON.{CODEX_RUNTIME_CONFIG_FILES_ENV}",
        )
        agent_files = parse_runtime_config_files(
            agent_config_files,
            source="AIAgent.spec.runtime.codex.configFiles",
        )
    except ValueError as exc:
        raise kopf.PermanentError(str(exc)) from exc

    merged = dict(chart_files)
    merged.update(agent_files)
    return merged


def merged_opencode_runtime_config_files(spec: dict[str, Any]) -> dict[str, Any]:
    runtime_spec = spec.get("runtime") or {}
    opencode_spec = runtime_spec.get("opencode")
    if opencode_spec is None:
        agent_config_files: Any = None
    elif isinstance(opencode_spec, dict):
        agent_config_files = opencode_spec.get("configFiles")
    else:
        raise kopf.PermanentError("AIAgent.spec.runtime.opencode must be an object when provided.")

    try:
        chart_files = parse_runtime_config_files(
            OPENCODE_RUNTIME_EXTRA_ENV.get(OPENCODE_RUNTIME_CONFIG_FILES_ENV),
            source=f"OPENCODE_RUNTIME_EXTRA_ENV_JSON.{OPENCODE_RUNTIME_CONFIG_FILES_ENV}",
        )
        agent_files = parse_runtime_config_files(
            agent_config_files,
            source="AIAgent.spec.runtime.opencode.configFiles",
        )
    except ValueError as exc:
        raise kopf.PermanentError(str(exc)) from exc

    merged = dict(chart_files)
    merged.update(agent_files)
    return merged


@kopf.on.startup()
def configure(settings: kopf.OperatorSettings, **_) -> None:
    """Ensure K8s client is authenticated when the operator starts."""
    settings.persistence.finalizer = "sandbox.enterprise.ai/finalizer"
    settings.peering.name = OPERATOR_PEERING_NAME
    try:
        kubernetes.config.load_incluster_config()
        logger.info("Loaded in-cluster Kubernetes config.")
    except kubernetes.config.ConfigException:
        kubernetes.config.load_kube_config()
        logger.info("Loaded local kubeconfig file.")
    init_state_database()
    log_operator_event(
        logger,
        logging.INFO,
        "Operator startup configuration loaded.",
        action="startup",
        operatorNamespace=OPERATOR_NAMESPACE,
        peering=OPERATOR_PEERING_NAME,
        secretProvisioningMode=SECRET_PROVISIONING_MODE,
        workflowPollSeconds=WORKFLOW_POLL_SECONDS,
        evalSchedulePollSeconds=EVAL_SCHEDULE_POLL_SECONDS,
        workerImage=WORKER_IMAGE,
    )


def sandbox_name(agent_name: str) -> str:
    return f"{agent_name}-sandbox"


def resolved_api_gateway_internal_url() -> str:
    if API_GATEWAY_INTERNAL_URL:
        return API_GATEWAY_INTERNAL_URL.rstrip("/")
    return f"http://ai-agent-sandbox-api-gateway.{OPERATOR_NAMESPACE}.svc.cluster.local:8080"


def slugify_name(value: str, max_length: int = 63) -> str:
    slug = re.sub(r"[^a-z0-9-]+", "-", value.lower()).strip("-") or "resource"
    trimmed = slug[:max_length].rstrip("-")
    return trimmed or "resource"


def hashed_resource_name(prefix: str, namespace: str, name: str, suffix: str = "") -> str:
    digest = hashlib.sha1(f"{prefix}:{namespace}:{name}:{suffix}".encode("utf-8")).hexdigest()[:10]
    base = slugify_name(f"{prefix}-{namespace}-{name}", max_length=max(1, 63 - len(digest) - 1))
    return f"{base}-{digest}"


def worker_artifact_pvc_name(kind: str, namespace: str, name: str) -> str:
    return hashed_resource_name(f"{kind}-artifacts", namespace, name)


def artifact_file_path(kind: str, namespace: str, name: str, generation: int) -> str:
    safe_namespace = slugify_name(namespace, max_length=40)
    safe_name = slugify_name(name, max_length=40)
    return f"{kind}s/{safe_namespace}/{safe_name}/generation-{generation}.json"


def worker_passthrough_env() -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    for name in (
        "STATE_DB_ENABLED",
        "DATABASE_URL",
        "DATABASE_HOST",
        "DATABASE_PORT",
        "DATABASE_NAME",
        "DATABASE_USER",
        "DATABASE_PASSWORD",
        "DATABASE_DRIVER",
        "DATABASE_SQLITE_PATH",
    ):
        value = os.getenv(name, "")
        if value:
            items.append({"name": name, "value": value})
    return items


def build_artifact_ref(
    pvc_name: str,
    path: str,
    generation: int,
    *,
    journal_path: str | None = None,
) -> dict[str, Any]:
    return {
        "namespace": OPERATOR_NAMESPACE,
        "pvcName": pvc_name,
        "path": path,
        "generation": generation,
        "updatedAt": now_iso(),
        **({"journalPath": journal_path} if journal_path else {}),
    }


def parse_iso_datetime(value: str | None) -> datetime | None:
    if value is None or not str(value).strip():
        return None

    normalized = str(value).strip()
    if normalized.endswith("Z"):
        normalized = f"{normalized[:-1]}+00:00"

    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def validate_eval_schedule(schedule: str) -> None:
    try:
        croniter(schedule, datetime.now(timezone.utc))
    except (CroniterBadCronError, ValueError) as exc:
        raise kopf.PermanentError(f"Invalid AgentEval schedule '{schedule}': {exc}") from exc


def scheduled_eval_due(schedule: str, last_run_value: str | None) -> bool:
    last_run = parse_iso_datetime(last_run_value)
    if last_run is None:
        return False

    next_run = croniter(schedule, last_run).get_next(datetime)
    if next_run.tzinfo is None:
        next_run = next_run.replace(tzinfo=timezone.utc)
    else:
        next_run = next_run.astimezone(timezone.utc)
    return datetime.now(timezone.utc) >= next_run


def validate_workflow_spec(spec: dict[str, Any]) -> dict[str, Any]:
    message_bus = str(spec.get("messageBus") or "in-memory").strip() or "in-memory"
    if message_bus != "in-memory":
        raise kopf.PermanentError(
            "AgentWorkflow.spec.messageBus is reserved for future use. Only 'in-memory' is supported today."
        )

    try:
        return validate_workflow_graph(spec.get("steps") or [])
    except ValueError as exc:
        raise kopf.PermanentError(str(exc)) from exc


def build_journal_ref(pvc_name: str, path: str, generation: int) -> dict[str, Any]:
    return {
        "namespace": OPERATOR_NAMESPACE,
        "pvcName": pvc_name,
        "path": path,
        "generation": generation,
        "updatedAt": now_iso(),
    }


def workflow_should_requeue(status: dict[str, Any], job_state: str) -> str | None:
    phase = str(status.get("phase", "") or "")
    if phase not in {"queued", "running"}:
        return None

    summary = status.get("summary", {}) or {}
    now = datetime.now(timezone.utc)

    if phase == "queued":
        queued_at = parse_iso_datetime(str(summary.get("queuedAt") or ""))
        if queued_at is None:
            logger.warning("Workflow stuck in 'queued' with no queuedAt timestamp (job_state=%s)", job_state)
            return f"queued workflow missing queuedAt timestamp with worker job state '{job_state}'"
        queue_age_seconds = (now - queued_at).total_seconds()
        if job_state in {"active", "pending"} and queue_age_seconds < WORKFLOW_QUEUE_STALE_SECONDS:
            return None
        if queue_age_seconds >= WORKFLOW_QUEUE_STALE_SECONDS:
            return f"queued workflow exceeded {WORKFLOW_QUEUE_STALE_SECONDS}s with worker job state '{job_state}'"
        if job_state in {"missing", "failed"}:
            return f"queued workflow lost worker job with state '{job_state}'"
        if job_state == "succeeded":
            return f"queued workflow has succeeded worker job but phase is still 'queued'"
        return None

    updated_at = parse_iso_datetime(str(summary.get("updatedAt") or summary.get("startedAt") or ""))
    if updated_at is None:
        logger.warning("Workflow stuck in '%s' with no updatedAt/startedAt timestamp (job_state=%s)", phase, job_state)
        return f"running workflow missing updatedAt/startedAt timestamp with worker job state '{job_state}'"
    running_age_seconds = (now - updated_at).total_seconds()
    if job_state == "succeeded":
        return f"running workflow has succeeded worker job but phase is still '{phase}'"
    if job_state in {"active", "pending"} and running_age_seconds < WORKFLOW_RUNNING_STALE_SECONDS:
        return None
    if job_state in {"missing", "failed"}:
        return f"running workflow lost worker job with state '{job_state}'"
    if running_age_seconds >= WORKFLOW_RUNNING_STALE_SECONDS:
        return f"running workflow exceeded {WORKFLOW_RUNNING_STALE_SECONDS}s without progress"
    return None


def resolve_agent_policy(namespace: str, policy_ref: str | None) -> tuple[str | None, dict[str, Any]]:
    custom_api = kubernetes.client.CustomObjectsApi()
    if policy_ref:
        try:
            policy = custom_api.get_namespaced_custom_object(
                group="sandbox.enterprise.ai",
                version="v1alpha1",
                namespace=namespace,
                plural="agentpolicies",
                name=policy_ref,
            )
            policy_spec = policy.get("spec", {})
            try:
                validate_supported_policy_spec(policy_spec)
            except ValueError as exc:
                raise kopf.PermanentError(f"AgentPolicy '{policy_ref}' is not supported: {exc}") from exc
            return policy_ref, policy_spec
        except ApiException as exc:
            if exc.status == 404:
                raise kopf.PermanentError(f"AgentPolicy '{policy_ref}' was not found") from exc
            raise

    policies = custom_api.list_namespaced_custom_object(
        group="sandbox.enterprise.ai",
        version="v1alpha1",
        namespace=namespace,
        plural="agentpolicies",
    ).get("items", [])
    policies.sort(key=lambda item: item.get("metadata", {}).get("name", ""))
    if not policies:
        return None, {}
    policy = policies[0]
    policy_name = policy.get("metadata", {}).get("name")
    policy_spec = policy.get("spec", {})
    try:
        validate_supported_policy_spec(policy_spec)
    except ValueError as exc:
        raise kopf.PermanentError(f"AgentPolicy '{policy_name}' is not supported: {exc}") from exc
    return policy_name, policy_spec


def resolve_tenant_for_namespace(namespace: str) -> dict[str, Any] | None:
    custom_api = kubernetes.client.CustomObjectsApi()
    tenants = custom_api.list_cluster_custom_object(
        group="sandbox.enterprise.ai",
        version="v1alpha1",
        plural="agenttenants",
    ).get("items", [])
    for tenant in tenants:
        tenant_spec = tenant.get("spec", {})
        if tenant_spec.get("namespace") == namespace:
            return tenant_spec
    return None


def validate_agent_model(model: str, policy_spec: dict[str, Any], tenant_spec: dict[str, Any] | None) -> None:
    policy_models = set(policy_spec.get("allowedModels", []))
    if policy_models and model not in policy_models:
        raise kopf.PermanentError(
            f"Model '{model}' is not allowed by AgentPolicy. Allowed models: {sorted(policy_models)}"
        )

    tenant_models = set((tenant_spec or {}).get("allowedModels", []))
    if tenant_models and model not in tenant_models:
        raise kopf.PermanentError(
            f"Model '{model}' is not allowed for tenant namespace. Allowed models: {sorted(tenant_models)}"
        )


def resolve_runtime_kind(spec: dict[str, Any]) -> str:
    runtime_spec = spec.get("runtime") or {}
    runtime_kind = "langgraph"
    if isinstance(runtime_spec, dict):
        runtime_kind = str(runtime_spec.get("kind") or "langgraph").strip().lower() or "langgraph"
    if runtime_kind not in SUPPORTED_RUNTIME_KINDS:
        raise kopf.PermanentError(
            f"Unsupported AIAgent.spec.runtime.kind '{runtime_kind}'. Supported values: {sorted(SUPPORTED_RUNTIME_KINDS)}"
        )
    return runtime_kind


def validate_runtime_configuration(runtime_kind: str, spec: dict[str, Any]) -> None:
    runtime_spec = spec.get("runtime") or {}
    goose_spec = runtime_spec.get("goose") if isinstance(runtime_spec, dict) else None
    codex_spec = runtime_spec.get("codex") if isinstance(runtime_spec, dict) else None
    opencode_spec = runtime_spec.get("opencode") if isinstance(runtime_spec, dict) else None
    explicit_sidecars = spec.get("mcpSidecars")
    github_config = spec.get("githubConfig")
    try:
        parse_agent_a2a_config(spec.get("a2a"), source="AIAgent.spec.a2a")
    except ValueError as exc:
        raise kopf.PermanentError(str(exc)) from exc
    try:
        parse_agent_skills_config(spec.get("skills"), source="AIAgent.spec.skills")
    except ValueError as exc:
        raise kopf.PermanentError(str(exc)) from exc
    if explicit_sidecars is not None and not isinstance(explicit_sidecars, list):
        raise kopf.PermanentError("AIAgent.spec.mcpSidecars must be an array when provided.")
    if github_config is not None and not isinstance(github_config, dict):
        raise kopf.PermanentError("AIAgent.spec.githubConfig must be an object when provided.")
    if isinstance(github_config, dict) and github_config:
        credential_secret_ref = str(github_config.get("credentialSecretRef") or "").strip()
        if not credential_secret_ref:
            raise kopf.PermanentError("AIAgent.spec.githubConfig.credentialSecretRef is required when githubConfig is provided.")

    if runtime_kind == "goose":
        if codex_spec is not None:
            raise kopf.PermanentError(
                "AIAgent.spec.runtime.codex is only supported when spec.runtime.kind is 'codex'."
            )
        if opencode_spec is not None:
            raise kopf.PermanentError(
                "AIAgent.spec.runtime.opencode is only supported when spec.runtime.kind is 'opencode'."
            )
        if goose_spec is not None and not isinstance(goose_spec, dict):
            raise kopf.PermanentError("AIAgent.spec.runtime.goose must be an object when provided.")
        try:
            parse_goose_config_files(
                (goose_spec or {}).get("configFiles") if isinstance(goose_spec, dict) else None,
                source="AIAgent.spec.runtime.goose.configFiles",
            )
        except ValueError as exc:
            raise kopf.PermanentError(str(exc)) from exc
        if spec.get("mcpServers"):
            raise kopf.PermanentError(
                "Goose runtime integration does not yet support spec.mcpServers. Use the LangGraph runtime for MCP routing today."
            )
        if spec.get("mcpSidecars"):
            raise kopf.PermanentError(
                "Goose runtime integration does not yet support spec.mcpSidecars. Use the LangGraph runtime for sidecar-based MCP tools today."
            )
        if spec.get("githubConfig"):
            raise kopf.PermanentError(
                "Goose runtime integration does not yet support spec.githubConfig. Use the LangGraph runtime for shared GitHub MCP access today."
            )
    elif runtime_kind == "codex":
        if goose_spec is not None:
            raise kopf.PermanentError(
                "AIAgent.spec.runtime.goose is only supported when spec.runtime.kind is 'goose'."
            )
        if opencode_spec is not None:
            raise kopf.PermanentError(
                "AIAgent.spec.runtime.opencode is only supported when spec.runtime.kind is 'opencode'."
            )
        if codex_spec is not None and not isinstance(codex_spec, dict):
            raise kopf.PermanentError("AIAgent.spec.runtime.codex must be an object when provided.")
        try:
            parse_goose_config_files(
                (codex_spec or {}).get("configFiles") if isinstance(codex_spec, dict) else None,
                source="AIAgent.spec.runtime.codex.configFiles",
            )
        except ValueError as exc:
            raise kopf.PermanentError(str(exc)) from exc
        if spec.get("mcpServers"):
            raise kopf.PermanentError(
                "Codex runtime integration does not yet support spec.mcpServers. Use the LangGraph runtime for MCP routing today."
            )
        if spec.get("githubConfig"):
            raise kopf.PermanentError(
                "Codex runtime integration does not yet support spec.githubConfig. Use the LangGraph runtime for shared GitHub MCP access today."
            )
    elif runtime_kind == "opencode":
        if goose_spec is not None:
            raise kopf.PermanentError(
                "AIAgent.spec.runtime.goose is only supported when spec.runtime.kind is 'goose'."
            )
        if codex_spec is not None:
            raise kopf.PermanentError(
                "AIAgent.spec.runtime.codex is only supported when spec.runtime.kind is 'codex'."
            )
        if opencode_spec is not None and not isinstance(opencode_spec, dict):
            raise kopf.PermanentError("AIAgent.spec.runtime.opencode must be an object when provided.")
        try:
            parse_runtime_config_files(
                (opencode_spec or {}).get("configFiles") if isinstance(opencode_spec, dict) else None,
                source="AIAgent.spec.runtime.opencode.configFiles",
            )
        except ValueError as exc:
            raise kopf.PermanentError(str(exc)) from exc
        if spec.get("githubConfig"):
            raise kopf.PermanentError(
                "OpenCode runtime integration does not yet support spec.githubConfig because the shared GitHub hub service is exposed through an HTTP adapter rather than a native MCP endpoint. Use sidecar-based GitHub MCP or the LangGraph runtime for shared GitHub MCP access today."
            )
    else:
        # langgraph
        if goose_spec is not None:
            raise kopf.PermanentError(
                "AIAgent.spec.runtime.goose is only supported when spec.runtime.kind is 'goose'."
            )
        if codex_spec is not None:
            raise kopf.PermanentError(
                "AIAgent.spec.runtime.codex is only supported when spec.runtime.kind is 'codex'."
            )
        if opencode_spec is not None:
            raise kopf.PermanentError(
                "AIAgent.spec.runtime.opencode is only supported when spec.runtime.kind is 'opencode'."
            )


def ensure_runtime_access(namespace: str) -> None:
    core_api = kubernetes.client.CoreV1Api()
    rbac_api = kubernetes.client.RbacAuthorizationV1Api()

    service_account = kubernetes.client.V1ServiceAccount(
        metadata=kubernetes.client.V1ObjectMeta(name=RUNTIME_SERVICE_ACCOUNT, namespace=namespace),
        image_pull_secrets=[
            kubernetes.client.V1LocalObjectReference(name=secret_name) for secret_name in IMAGE_PULL_SECRETS
        ]
        or None,
    )
    try:
        core_api.create_namespaced_service_account(namespace=namespace, body=service_account)
    except ApiException as exc:
        if exc.status == 409:
            core_api.patch_namespaced_service_account(
                name=RUNTIME_SERVICE_ACCOUNT,
                namespace=namespace,
                body=service_account,
            )
        else:
            raise

    binding = kubernetes.client.V1RoleBinding(
        metadata=kubernetes.client.V1ObjectMeta(
            name=f"{RUNTIME_SERVICE_ACCOUNT}-binding",
            namespace=namespace,
        ),
        role_ref=kubernetes.client.V1RoleRef(
            api_group="rbac.authorization.k8s.io",
            kind="ClusterRole",
            name=RUNTIME_CLUSTER_ROLE,
        ),
        subjects=[
            kubernetes.client.V1Subject(
                kind="ServiceAccount",
                name=RUNTIME_SERVICE_ACCOUNT,
                namespace=namespace,
            )
        ],
    )
    try:
        rbac_api.create_namespaced_role_binding(namespace=namespace, body=binding)
    except ApiException as exc:
        if exc.status == 409:
            rbac_api.patch_namespaced_role_binding(
                name=f"{RUNTIME_SERVICE_ACCOUNT}-binding",
                namespace=namespace,
                body=binding,
            )
        else:
            raise


def build_pvc_spec(storage_size: str, storage_class_name: str | None = None) -> dict[str, Any]:
    pvc_spec: dict[str, Any] = {
        "accessModes": ["ReadWriteOnce"],
        "resources": {"requests": {"storage": storage_size}},
    }
    if storage_class_name:
        pvc_spec["storageClassName"] = storage_class_name
    return pvc_spec


def _build_pod_template_revision(
    spec: dict[str, Any],
    runtime_kind: str,
    policy_name: str | None,
    policy_spec: dict[str, Any] | None,
    mcp_sidecars: list[dict[str, Any]],
) -> str:
    revision_source = {
        "spec": spec,
        "runtimeKind": runtime_kind,
        "policyName": policy_name,
        "policySpec": policy_spec or {},
        "mcpSidecars": mcp_sidecars,
    }
    serialized = json.dumps(revision_source, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:12]


def _sanitize_kube_resource(resource: Any) -> Any:
    if isinstance(resource, (dict, list, str, int, float, bool)) or resource is None:
        return copy.deepcopy(resource)

    api_client_cls = getattr(kubernetes.client, "ApiClient", None)
    if api_client_cls is not None:
        try:
            return api_client_cls().sanitize_for_serialization(resource)
        except Exception:
            pass

    if hasattr(resource, "to_dict"):
        return resource.to_dict()
    return resource


def _extract_statefulset_storage_request(manifest: dict[str, Any], claim_name: str = "state-volume") -> str | None:
    templates = (manifest.get("spec") or {}).get("volumeClaimTemplates") or []
    for template in templates:
        metadata = template.get("metadata") or {}
        if metadata.get("name") != claim_name:
            continue
        requests = ((template.get("spec") or {}).get("resources") or {}).get("requests") or {}
        storage = requests.get("storage")
        if storage:
            return str(storage)
    return None


def _statefulset_template_signature(manifest: dict[str, Any]) -> dict[str, Any]:
    template = ((manifest.get("spec") or {}).get("template") or {})
    template_metadata = template.get("metadata") or {}
    template_spec = template.get("spec") or {}

    def port_signature(port: dict[str, Any]) -> dict[str, Any]:
        return {
            "containerPort": port.get("containerPort"),
            "name": port.get("name"),
            "protocol": port.get("protocol") or "TCP",
        }

    def container_signature(container: dict[str, Any]) -> dict[str, Any]:
        return {
            "name": container.get("name"),
            "image": container.get("image"),
            "ports": [port_signature(port) for port in container.get("ports") or []],
            "env": copy.deepcopy(container.get("env") or []),
        }

    return {
        "revision": (template_metadata.get("annotations") or {}).get(POD_TEMPLATE_REVISION_ANNOTATION),
        "containers": [container_signature(container) for container in template_spec.get("containers") or []],
        "initContainers": [container_signature(container) for container in template_spec.get("initContainers") or []],
    }


def _parse_storage_quantity(value: str) -> Decimal:
    normalized = str(value or "").strip()
    match = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)([KMGTPE]i|[numkKMGTPE])?", normalized)
    if not match:
        raise ValueError(f"Unsupported storage quantity: {value!r}")

    number_text, suffix = match.groups()
    try:
        number = Decimal(number_text)
    except InvalidOperation as exc:
        raise ValueError(f"Unsupported storage quantity: {value!r}") from exc
    return number * STORAGE_QUANTITY_MULTIPLIERS[suffix or ""]


def _validate_mcp_sidecars(sidecars: list[dict[str, Any]]) -> list[dict[str, Any]]:
    # Ports used by the agent runtime container and other system components.
    _RESERVED_PORTS = {8080, 6333}
    normalized_sidecars: list[dict[str, Any]] = []
    seen_names: dict[str, int] = {}
    seen_ports: dict[int, int] = {}

    for index, sidecar in enumerate(sidecars):
        if not isinstance(sidecar, dict):
            raise kopf.PermanentError(
                f"AIAgent.spec.mcpSidecars[{index}] must be an object with name, image, and port fields."
            )

        raw_name = str(sidecar.get("name") or "").strip()
        if not raw_name:
            raise kopf.PermanentError(f"AIAgent.spec.mcpSidecars[{index}].name is required.")
        if len(raw_name) > 59:
            raise kopf.PermanentError(
                f"AIAgent.spec.mcpSidecars[{index}].name '{raw_name}' is too long; keep it to 59 characters or fewer."
            )
        if not KUBERNETES_RESOURCE_NAME_PATTERN.fullmatch(raw_name):
            raise kopf.PermanentError(
                (
                    f"AIAgent.spec.mcpSidecars[{index}].name '{raw_name}' is invalid. "
                    "Use lowercase letters, numbers, and hyphens only."
                )
            )

        raw_image = str(sidecar.get("image") or "").strip()
        if not raw_image:
            raise kopf.PermanentError(
                f"AIAgent.spec.mcpSidecars[{index}].image is required for sidecar '{raw_name}'."
            )
        # Reject images with embedded credentials or shell metacharacters
        if "@" in raw_image.split("/")[0] or any(ch in raw_image for ch in (";", "&", "|", "$", "`", "\n")):
            raise kopf.PermanentError(
                f"AIAgent.spec.mcpSidecars[{index}].image contains invalid characters for sidecar '{raw_name}'."
            )

        raw_port = sidecar.get("port", 8080)
        try:
            port = int(raw_port)
        except (TypeError, ValueError) as exc:
            raise kopf.PermanentError(
                f"AIAgent.spec.mcpSidecars[{index}].port must be an integer for sidecar '{raw_name}'."
            ) from exc
        if port < 1 or port > 65535:
            raise kopf.PermanentError(
                f"AIAgent.spec.mcpSidecars[{index}].port must be between 1 and 65535 for sidecar '{raw_name}'."
            )
        if port in _RESERVED_PORTS:
            raise kopf.PermanentError(
                f"AIAgent.spec.mcpSidecars[{index}].port {port} is reserved for system use (sidecar '{raw_name}')."
            )

        previous_name_index = seen_names.get(raw_name)
        if previous_name_index is not None:
            raise kopf.PermanentError(
                (
                    f"AIAgent.spec.mcpSidecars[{index}].name '{raw_name}' duplicates "
                    f"AIAgent.spec.mcpSidecars[{previous_name_index}].name."
                )
            )
        previous_port_index = seen_ports.get(port)
        if previous_port_index is not None:
            raise kopf.PermanentError(
                (
                    f"AIAgent.spec.mcpSidecars[{index}].port {port} duplicates "
                    f"AIAgent.spec.mcpSidecars[{previous_port_index}].port."
                )
            )

        seen_names[raw_name] = index
        seen_ports[port] = index
        normalized_sidecars.append({"name": raw_name, "image": raw_image, "port": port})

    return normalized_sidecars


def _preserve_statefulset_immutable_fields(
    manifest: dict[str, Any],
    current_statefulset: dict[str, Any],
) -> dict[str, Any]:
    patched_manifest = copy.deepcopy(manifest)
    patched_spec = patched_manifest.setdefault("spec", {})
    current_spec = (current_statefulset.get("spec") or {})

    for field_name in ("volumeClaimTemplates", "selector", "serviceName"):
        current_value = current_spec.get(field_name)
        if current_value is not None:
            patched_spec[field_name] = current_value

    return patched_manifest


def _patch_statefulset_with_merge_patch(
    apps_api: Any,
    namespace: str,
    statefulset_name: str,
    manifest: dict[str, Any],
) -> Any:
    try:
        return apps_api.patch_namespaced_stateful_set(
            name=statefulset_name,
            namespace=namespace,
            body=manifest,
            _content_type="application/merge-patch+json",
        )
    except ApiTypeError:
        api_client = apps_api.api_client
        return api_client.call_api(
            "/apis/apps/v1/namespaces/{namespace}/statefulsets/{name}",
            "PATCH",
            {"name": statefulset_name, "namespace": namespace},
            [],
            {
                "Accept": api_client.select_header_accept(
                    [
                        "application/json",
                        "application/yaml",
                        "application/vnd.kubernetes.protobuf",
                    ]
                ),
                "Content-Type": "application/merge-patch+json",
            },
            body=manifest,
            post_params=[],
            files={},
            response_type="V1StatefulSet",
            auth_settings=["BearerToken"],
            _return_http_data_only=True,
            collection_formats={},
        )


def _resize_statefulset_persistent_volume_claims(
    core_api: Any,
    namespace: str,
    statefulset_name: str,
    current_statefulset: dict[str, Any],
    desired_storage: str | None,
) -> None:
    if not desired_storage:
        return

    desired_quantity = _parse_storage_quantity(desired_storage)
    current_spec = current_statefulset.get("spec") or {}
    replicas = max(int(current_spec.get("replicas") or 1), 1)
    claim_templates = current_spec.get("volumeClaimTemplates") or []

    for template in claim_templates:
        claim_name = str((template.get("metadata") or {}).get("name") or "").strip()
        if claim_name != "state-volume":
            continue

        for ordinal in range(replicas):
            pvc_name = f"{claim_name}-{statefulset_name}-{ordinal}"
            try:
                current_pvc = _sanitize_kube_resource(
                    core_api.read_namespaced_persistent_volume_claim(name=pvc_name, namespace=namespace)
                )
            except ApiException as exc:
                if exc.status == 404:
                    continue
                raise

            current_requests = ((current_pvc.get("spec") or {}).get("resources") or {}).get("requests") or {}
            current_storage = current_requests.get("storage")
            if not current_storage:
                logger.warning(
                    "Skipping PVC resize because '%s' in namespace '%s' has no storage request.",
                    pvc_name,
                    namespace,
                )
                continue

            try:
                current_quantity = _parse_storage_quantity(str(current_storage))
            except ValueError:
                logger.warning(
                    "Skipping PVC resize because '%s' in namespace '%s' has an unsupported storage request %r.",
                    pvc_name,
                    namespace,
                    current_storage,
                )
                continue

            if desired_quantity < current_quantity:
                logger.warning(
                    "Skipping PVC shrink request for '%s' in namespace '%s': current=%s desired=%s.",
                    pvc_name,
                    namespace,
                    current_storage,
                    desired_storage,
                )
                continue
            if desired_quantity == current_quantity:
                continue

            try:
                core_api.patch_namespaced_persistent_volume_claim(
                    name=pvc_name,
                    namespace=namespace,
                    body={"spec": {"resources": {"requests": {"storage": desired_storage}}}},
                )
            except ApiException as exc:
                if exc.status in (403, 422):
                    raise kopf.PermanentError(
                        (
                            f"PVC resize request for '{pvc_name}' in namespace '{namespace}' could not be applied: "
                            f"{describe_api_exception(exc)}"
                        )
                    )
                raise


def create_worker_artifact_pvc_manifest(kind: str, resource_namespace: str, resource_name: str) -> dict[str, Any]:
    return {
        "apiVersion": "v1",
        "kind": "PersistentVolumeClaim",
        "metadata": {
            "name": worker_artifact_pvc_name(kind, resource_namespace, resource_name),
            "namespace": OPERATOR_NAMESPACE,
            "labels": {
                "app": "operator-worker-artifacts",
                "sandbox.enterprise.ai/resource-kind": kind,
                "sandbox.enterprise.ai/resource-name": resource_name,
                "sandbox.enterprise.ai/resource-namespace": resource_namespace,
            },
        },
        "spec": build_pvc_spec(WORKER_ARTIFACT_SIZE, WORKER_ARTIFACT_STORAGE_CLASS or None),
    }


def create_mcp_auth_secret_manifest(namespace: str) -> dict[str, Any]:
    core_api = kubernetes.client.CoreV1Api()
    try:
        source_secret = core_api.read_namespaced_secret(
            name=MCP_AUTH_SECRET_NAME,
            namespace=MCP_HUB_NAMESPACE,
        )
    except ApiException as exc:
        if exc.status == 404:
            raise kopf.TemporaryError(
                f"MCP auth secret '{MCP_AUTH_SECRET_NAME}' was not found in namespace '{MCP_HUB_NAMESPACE}'.",
                delay=15,
            ) from exc
        raise

    bearer_token = (source_secret.data or {}).get("bearer-token")
    if not bearer_token:
        raise kopf.TemporaryError(
            f"MCP auth secret '{MCP_AUTH_SECRET_NAME}' is missing the bearer-token key.",
            delay=15,
        )

    return {
        "apiVersion": "v1",
        "kind": "Secret",
        "metadata": {
            "name": MCP_AUTH_SECRET_NAME,
            "namespace": namespace,
            "labels": {
                "app": "ai-agent",
                "sandbox.enterprise.ai/managed-by": "operator",
                "sandbox.enterprise.ai/secret-purpose": "mcp-auth",
            },
        },
        "type": source_secret.type or "Opaque",
        "data": {"bearer-token": bearer_token},
    }


def create_agent_service_manifest(name: str, namespace: str) -> dict[str, Any]:
    return {
        "apiVersion": "v1",
        "kind": "Service",
        "metadata": {
            "name": sandbox_name(name),
            "namespace": namespace,
            "labels": {"app": "ai-agent", "agent-name": name},
        },
        "spec": {
            "selector": {"app": "ai-agent", "agent-name": name},
            "ports": [{"name": "http", "port": API_PORT, "targetPort": "http"}],
        },
    }


def create_agent_statefulset_manifest(
    name: str,
    namespace: str,
    spec: dict[str, Any],
    policy_name: str | None,
    policy_spec: dict[str, Any] | None = None,
) -> dict[str, Any]:
    runtime_kind = resolve_runtime_kind(spec)
    validate_runtime_configuration(runtime_kind, spec)
    model = spec.get("model", "gpt-4")
    mcp_servers = spec.get("mcpServers") or []
    mcp_sidecars = spec.get("mcpSidecars") or []
    enable_gvisor = spec.get("enableGVisor", False)
    system_prompt = spec.get("systemPrompt", "")
    if len(system_prompt) > 32000:
        raise kopf.PermanentError(
            f"spec.systemPrompt exceeds maximum length (32000 chars, got {len(system_prompt)})"
        )
    skills_config = parse_agent_skills_config(spec.get("skills"), source="AIAgent.spec.skills")
    mcp_sidecars = _auto_inject_mcp_sidecars(mcp_sidecars, skills_config)
    mcp_sidecars = _validate_mcp_sidecars(mcp_sidecars)

    # Git configuration — auto-inject git sidecar and prepare credential env/volumes
    git_config = spec.get("gitConfig") or {}
    github_config = spec.get("githubConfig") or {}
    if github_config and "github" not in mcp_servers:
        mcp_servers = [*mcp_servers, "github"]
    git_sidecar_env: list[dict[str, Any]] = []
    git_volumes: list[dict[str, Any]] = []
    git_volume_mounts: list[dict[str, Any]] = []
    if git_config.get("repoUrl"):
        _repo_url = git_config["repoUrl"]
        from urllib.parse import urlparse as _urlparse
        _parsed_repo = _urlparse(_repo_url)
        _allowed_git_schemes = {"https", "ssh", "git+ssh", "git"}
        if _parsed_repo.scheme and _parsed_repo.scheme.lower() not in _allowed_git_schemes:
            raise kopf.PermanentError(
                f"spec.gitConfig.repoUrl has disallowed scheme '{_parsed_repo.scheme}' "
                f"(allowed: {', '.join(sorted(_allowed_git_schemes))})"
            )
        if not _parsed_repo.scheme and not _repo_url.startswith("git@"):
            raise kopf.PermanentError(
                "spec.gitConfig.repoUrl must use https://, git@, or ssh:// scheme"
            )
        # Auto-inject git sidecar if not already present
        has_git_sidecar = any(s.get("name") == "git" for s in mcp_sidecars)
        if not has_git_sidecar:
            git_catalog_entry = MCP_SIDECAR_CATALOG.get("git", {})
            mcp_sidecars.append({
                "name": "git",
                "image": git_catalog_entry.get("image", "docker.io/yakdhane/mcp-git:latest"),
                "port": git_catalog_entry.get("port", 8095),
            })
            logger.info("Auto-injected git MCP sidecar for agent '%s' (gitConfig present)", name)

        git_sidecar_env = [
            {"name": "GIT_REPO_URL", "value": git_config.get("repoUrl", "")},
            {"name": "GIT_AUTH_METHOD", "value": git_config.get("authMethod", "")},
        ]
        cred_secret = git_config.get("credentialSecretRef", "")
        auth_method = git_config.get("authMethod", "")
        if cred_secret and auth_method == "token":
            git_sidecar_env.append({
                "name": "GIT_TOKEN",
                "valueFrom": {"secretKeyRef": {"name": cred_secret, "key": "token", "optional": True}},
            })
        elif cred_secret and auth_method == "basic":
            git_sidecar_env.extend([
                {"name": "GIT_USERNAME", "valueFrom": {"secretKeyRef": {"name": cred_secret, "key": "username", "optional": True}}},
                {"name": "GIT_PASSWORD", "valueFrom": {"secretKeyRef": {"name": cred_secret, "key": "password", "optional": True}}},
            ])
        elif cred_secret and auth_method == "ssh":
            ssh_vol_name = "git-ssh-key"
            git_volumes.append({
                "name": ssh_vol_name,
                "secret": {"secretName": cred_secret, "items": [{"key": "ssh_private_key", "path": "id_rsa"}], "defaultMode": 0o400},
            })
            git_volume_mounts.append({"name": ssh_vol_name, "mountPath": "/home/mcpuser/.ssh", "readOnly": True})
            git_sidecar_env.append({"name": "GIT_SSH_KEY_PATH", "value": "/home/mcpuser/.ssh/id_rsa"})

    pod_security_context = {
        "runAsNonRoot": True,
        "runAsUser": 1000,
        "runAsGroup": 1000,
        "fsGroup": 1000,
        "fsGroupChangePolicy": "OnRootMismatch",
        "seccompProfile": {"type": "RuntimeDefault"},
    }
    container_security_context = {
        "allowPrivilegeEscalation": False,
        "readOnlyRootFilesystem": True,
        "capabilities": {"drop": ["ALL"]},
    }

    env = [
        {"name": "AGENT_DEFAULT_MODEL", "value": model},
        {"name": "AGENT_MODEL", "value": model},
        {"name": "AGENT_NAME", "value": name},
        {"name": "AGENT_NAMESPACE", "value": namespace},
        {"name": "AGENT_SYSTEM_PROMPT", "value": system_prompt},
        {"name": "HELM_RELEASE_NAME", "value": HELM_RELEASE_NAME},
        {"name": "API_GATEWAY_INTERNAL_URL", "value": resolved_api_gateway_internal_url()},
        {
            "name": "API_GATEWAY_SHARED_TOKEN",
            "valueFrom": {
                "secretKeyRef": {
                    "name": SECRET_NAME,
                    "key": "API_GATEWAY_SHARED_TOKEN",
                    "optional": True,
                }
            },
        },
    ]
    agent_a2a_config = parse_agent_a2a_config(spec.get("a2a"), source="AIAgent.spec.a2a")
    policy_a2a_config = parse_policy_a2a_config(policy_spec or {})
    env.extend(
        [
            {
                "name": A2A_ALLOWED_CALLERS_ENV,
                "value": json.dumps(agent_a2a_config.get("allowedCallers", []), ensure_ascii=False, sort_keys=True),
            },
            {
                "name": A2A_ALLOWED_TARGETS_ENV,
                "value": json.dumps(policy_a2a_config.get("allowedTargets", []), ensure_ascii=False, sort_keys=True),
            },
            {
                "name": A2A_REQUIRE_HITL_ENV,
                "value": serialize_env_value(policy_a2a_config.get("requireHitl", False)),
            },
            {
                "name": A2A_MAX_TIMEOUT_SECONDS_ENV,
                "value": serialize_env_value(policy_a2a_config.get("maxTimeoutSeconds", A2A_DEFAULT_TIMEOUT_SECONDS)),
            },
        ]
    )
    if skills_config:
        env.append(
            {
                "name": AGENT_SKILL_FILES_ENV,
                "value": json.dumps(skills_config.get("files", {}), ensure_ascii=False, sort_keys=True),
            }
        )

    volume_mounts = [
        {"name": "tmp-volume", "mountPath": "/tmp"},
        {"name": "state-volume", "mountPath": "/app/state"},
    ]
    volumes: list[dict[str, Any]] = [{"name": "tmp-volume", "emptyDir": {"sizeLimit": "1Gi"}}]

    agent_image = RUNTIME_IMAGE
    agent_image_pull_policy = RUNTIME_IMAGE_PULL_POLICY

    if runtime_kind == "goose":
        agent_image = GOOSE_RUNTIME_IMAGE
        agent_image_pull_policy = GOOSE_RUNTIME_IMAGE_PULL_POLICY
        goose_config_files = merged_goose_runtime_config_files(spec)
        volume_mounts.append({"name": "workspace-volume", "mountPath": "/workspace"})
        volumes.append({"name": "workspace-volume", "emptyDir": {"sizeLimit": "5Gi"}})
        env.extend(
            [
                {"name": "GOOSE_PROVIDER", "value": GOOSE_DEFAULT_PROVIDER},
                {"name": "GOOSE_MODEL", "value": model},
                {"name": "GOOSE_SYSTEM_PROMPT", "value": system_prompt},
                {"name": "LITELLM_HOST", "value": f"http://{LITELLM_SVC}:4000"},
                {"name": "LITELLM_BASE_PATH", "value": "v1/chat/completions"},
                {
                    "name": "LITELLM_API_KEY",
                    "valueFrom": {
                        "secretKeyRef": {
                            "name": SECRET_NAME,
                            "key": "LITELLM_MASTER_KEY",
                            "optional": True,
                        }
                    },
                },
            ]
        )
        if goose_config_files:
            env.append(
                {
                    "name": GOOSE_RUNTIME_CONFIG_FILES_ENV,
                    "value": json.dumps(goose_config_files, ensure_ascii=False, sort_keys=True),
                }
            )
        env.extend(goose_runtime_extra_env_items())
    elif runtime_kind == "codex":
        agent_image = CODEX_RUNTIME_IMAGE
        agent_image_pull_policy = CODEX_RUNTIME_IMAGE_PULL_POLICY
        codex_config_files = merged_codex_runtime_config_files(spec)
        volume_mounts.append({"name": "workspace-volume", "mountPath": "/workspace"})
        volumes.append({"name": "workspace-volume", "emptyDir": {"sizeLimit": "5Gi"}})
        env.extend(
            [
                {"name": "CODEX_PROVIDER", "value": CODEX_DEFAULT_PROVIDER},
                {"name": "CODEX_MODEL", "value": model},
                {"name": "CODEX_SYSTEM_PROMPT", "value": system_prompt},
                {"name": "LITELLM_HOST", "value": f"http://{LITELLM_SVC}:4000"},
                {"name": "LITELLM_BASE_PATH", "value": "v1/chat/completions"},
                {
                    "name": "LITELLM_API_KEY",
                    "valueFrom": {
                        "secretKeyRef": {
                            "name": SECRET_NAME,
                            "key": "LITELLM_MASTER_KEY",
                            "optional": True,
                        }
                    },
                },
            ]
        )
        if codex_config_files:
            env.append(
                {
                    "name": CODEX_RUNTIME_CONFIG_FILES_ENV,
                    "value": json.dumps(codex_config_files, ensure_ascii=False, sort_keys=True),
                }
            )
        if mcp_sidecars:
            env.append(
                {
                    "name": CODEX_MCP_SIDECARS_ENV,
                    "value": json.dumps(mcp_sidecars, ensure_ascii=False, sort_keys=True),
                }
            )
        env.extend(codex_runtime_extra_env_items())
    elif runtime_kind == "opencode":
        agent_image = OPENCODE_RUNTIME_IMAGE
        agent_image_pull_policy = OPENCODE_RUNTIME_IMAGE_PULL_POLICY
        opencode_config_files = merged_opencode_runtime_config_files(spec)
        volume_mounts.append({"name": "workspace-volume", "mountPath": "/workspace"})
        volumes.append({"name": "workspace-volume", "emptyDir": {"sizeLimit": "5Gi"}})
        env.extend(
            [
                {"name": "OPENCODE_PROVIDER", "value": OPENCODE_DEFAULT_PROVIDER},
                {"name": "OPENCODE_MODEL", "value": model},
                {"name": "OPENCODE_SYSTEM_PROMPT", "value": system_prompt},
                {"name": "OPENCODE_DEFAULT_AGENT", "value": "build"},
                {"name": "LITELLM_HOST", "value": f"http://{LITELLM_SVC}:4000"},
                {"name": "LITELLM_BASE_PATH", "value": "v1/chat/completions"},
                {"name": "MCP_SERVERS", "value": ",".join(mcp_servers)},
                {"name": "MCP_HUB_NAMESPACE", "value": MCP_HUB_NAMESPACE},
                {
                    "name": "LITELLM_API_KEY",
                    "valueFrom": {
                        "secretKeyRef": {
                            "name": SECRET_NAME,
                            "key": "LITELLM_MASTER_KEY",
                            "optional": True,
                        }
                    },
                },
                {
                    "name": "MCP_BEARER_TOKEN",
                    "valueFrom": {
                        "secretKeyRef": {
                            "name": MCP_AUTH_SECRET_NAME,
                            "key": "bearer-token",
                            "optional": not bool(mcp_servers),
                        }
                    },
                },
            ]
        )
        if opencode_config_files:
            env.append(
                {
                    "name": OPENCODE_RUNTIME_CONFIG_FILES_ENV,
                    "value": json.dumps(opencode_config_files, ensure_ascii=False, sort_keys=True),
                }
            )
        if mcp_sidecars:
            env.append(
                {
                    "name": OPENCODE_MCP_SIDECARS_ENV,
                    "value": json.dumps(mcp_sidecars, ensure_ascii=False, sort_keys=True),
                }
            )
        env.extend(opencode_runtime_extra_env_items())
    else:
        if AGENT_LOCAL_TOOL_MOUNT_WORKSPACE:
            volume_mounts.append({"name": "workspace-volume", "mountPath": "/workspace"})
            volumes.append({"name": "workspace-volume", "emptyDir": {"sizeLimit": "5Gi"}})
        env.extend(
            [
                {"name": "LITELLM_API_BASE", "value": f"http://{LITELLM_SVC}:4000"},
                {"name": "AGENT_ALLOWED_MODELS", "value": ",".join(AGENT_ALLOWED_MODELS)},
                {"name": "AGENT_MAX_STEPS", "value": AGENT_MAX_STEPS},
                {"name": "AGENT_MAX_STEPS_LIMIT", "value": AGENT_MAX_STEPS_LIMIT},
                {"name": "AGENT_DOOM_LOOP_THRESHOLD", "value": AGENT_DOOM_LOOP_THRESHOLD},
                {"name": "AGENT_SUPERVISOR_HISTORY_LIMIT", "value": AGENT_SUPERVISOR_HISTORY_LIMIT},
                {"name": "AGENT_SUPERVISOR_RESPONSE_CHARS", "value": AGENT_SUPERVISOR_RESPONSE_CHARS},
                {
                    "name": "AGENT_AUTONOMY_CONTINUE_ON_ACTION_ERROR",
                    "value": AGENT_AUTONOMY_CONTINUE_ON_ACTION_ERROR,
                },
                {
                    "name": "AGENT_AUTONOMY_ACTION_RETRY_LIMIT",
                    "value": AGENT_AUTONOMY_ACTION_RETRY_LIMIT,
                },
                {
                    "name": "AGENT_AUTONOMY_ACTION_RETRY_BACKOFF_SECONDS",
                    "value": AGENT_AUTONOMY_ACTION_RETRY_BACKOFF_SECONDS,
                },
                {
                    "name": "AGENT_AUTONOMY_FAILURE_HISTORY_LIMIT",
                    "value": AGENT_AUTONOMY_FAILURE_HISTORY_LIMIT,
                },
                {
                    "name": "AGENT_LOCAL_TOOL_DISCOVERY_ENABLED",
                    "value": AGENT_LOCAL_TOOL_DISCOVERY_ENABLED,
                },
                {"name": "AGENT_LOCAL_TOOL_ALLOWLIST", "value": AGENT_LOCAL_TOOL_ALLOWLIST},
                {
                    "name": "AGENT_LOCAL_TOOL_TIMEOUT_SECONDS",
                    "value": AGENT_LOCAL_TOOL_TIMEOUT_SECONDS,
                },
                {
                    "name": "AGENT_LOCAL_TOOL_MAX_OUTPUT_CHARS",
                    "value": AGENT_LOCAL_TOOL_MAX_OUTPUT_CHARS,
                },
                {"name": "AGENT_LOCAL_TOOL_MAX_ARGS", "value": AGENT_LOCAL_TOOL_MAX_ARGS},
                {
                    "name": "AGENT_LOCAL_TOOL_MAX_ARG_CHARS",
                    "value": AGENT_LOCAL_TOOL_MAX_ARG_CHARS,
                },
                {
                    "name": "AGENT_LOCAL_TOOL_ALLOWED_ROOTS",
                    "value": AGENT_LOCAL_TOOL_ALLOWED_ROOTS,
                },
                {"name": "AGENT_LOCAL_TOOL_LIST_LIMIT", "value": AGENT_LOCAL_TOOL_LIST_LIMIT},
                {"name": "MCP_SERVERS", "value": ",".join(mcp_servers)},
                {
                    "name": "MCP_SIDECARS",
                    "value": ",".join(f"http://localhost:{item.get('port', 8080)}" for item in mcp_sidecars),
                },
                {"name": "QDRANT_URL", "value": f"http://{QDRANT_SVC}:6333"},
                {"name": "QDRANT_COLLECTION", "value": QDRANT_COLLECTION},
                {
                    "name": "LITELLM_API_KEY",
                    "valueFrom": {
                        "secretKeyRef": {
                            "name": SECRET_NAME,
                            "key": "LITELLM_MASTER_KEY",
                            "optional": True,
                        }
                    },
                },
            ]
        )
        if policy_name:
            env.append({"name": "AGENT_POLICY_NAME", "value": policy_name})
        if OTEL_ENDPOINT:
            env.append({"name": "OTEL_EXPORTER_OTLP_ENDPOINT", "value": OTEL_ENDPOINT})
        if AGENT_HITL_MODE:
            env.append({"name": "HITL_MODE", "value": AGENT_HITL_MODE})
        if HITL_NOTIFICATION_WEBHOOK_URL:
            env.append({"name": "HITL_NOTIFICATION_WEBHOOK_URL", "value": HITL_NOTIFICATION_WEBHOOK_URL})
        env.append({"name": "MCP_HUB_NAMESPACE", "value": MCP_HUB_NAMESPACE})
        allowed_mcp_servers = (policy_spec or {}).get("allowedMcpServers") or []
        require_mcp_bearer_token = bool(allowed_mcp_servers)
        env.append({"name": "ALLOWED_MCP_SERVERS", "value": ",".join(allowed_mcp_servers)})
        env.append({
            "name": "MCP_BEARER_TOKEN",
            "valueFrom": {
                "secretKeyRef": {
                    "name": MCP_AUTH_SECRET_NAME,
                    "key": "bearer-token",
                    "optional": not require_mcp_bearer_token,
                }
            },
        })
        github_credential_secret = str(github_config.get("credentialSecretRef") or "").strip()
        if github_credential_secret:
            env.append(
                {
                    "name": "GITHUB_MCP_TOKEN",
                    "valueFrom": {
                        "secretKeyRef": {
                            "name": github_credential_secret,
                            "key": "token",
                            "optional": True,
                        }
                    },
                }
            )
        for env_name, env_value in OPEN_SANDBOX_RUNTIME_ENV.items():
            if env_value:
                env.append({"name": env_name, "value": env_value})
        if OPEN_SANDBOX_API_KEY_SECRET_NAME:
            env.append({
                "name": "OPEN_SANDBOX_API_KEY",
                "valueFrom": {
                    "secretKeyRef": {
                        "name": OPEN_SANDBOX_API_KEY_SECRET_NAME,
                        "key": OPEN_SANDBOX_API_KEY_SECRET_KEY,
                        "optional": True,
                    }
                },
            })
        env.extend(agent_runtime_extra_env_items())

    init_containers = [
        {
            "name": "init-state-volume",
            "image": agent_image,
            "imagePullPolicy": agent_image_pull_policy,
            "command": [
                "/bin/sh",
                "-c",
                "mkdir -p /app/state/home /app/state/data /app/state/config "
                "&& chown -R 1000:1000 /app/state "
                "&& chmod -R ug+rwX /app/state",
            ],
            "securityContext": {
                "runAsUser": 0,
                "runAsGroup": 0,
                "runAsNonRoot": False,
                "allowPrivilegeEscalation": False,
                "capabilities": {"drop": ["ALL"], "add": ["CHOWN", "FOWNER"]},
                "seccompProfile": {"type": "RuntimeDefault"},
            },
            "volumeMounts": [{"name": "state-volume", "mountPath": "/app/state"}],
        }
    ]

    agent_container = {
        "name": "agent-runtime",
        "image": agent_image,
        "imagePullPolicy": agent_image_pull_policy,
        "securityContext": container_security_context,
        "ports": [{"containerPort": API_PORT, "name": "http", "protocol": "TCP"}],
        "resources": {
            "requests": {"cpu": AGENT_CPU_REQUEST, "memory": AGENT_MEMORY_REQUEST},
            "limits": {"cpu": AGENT_CPU_LIMIT, "memory": AGENT_MEMORY_LIMIT},
        },
        "startupProbe": {
            "httpGet": {"path": "/health", "port": "http"},
            "initialDelaySeconds": 0,
            "periodSeconds": 5,
            "timeoutSeconds": 3,
            "failureThreshold": 60,
        },
        "readinessProbe": {
            "httpGet": {"path": "/ready", "port": "http"},
            "initialDelaySeconds": 5,
            "periodSeconds": 10,
            "timeoutSeconds": 5,
            "failureThreshold": 6,
        },
        "livenessProbe": {
            "httpGet": {"path": "/health", "port": "http"},
            "initialDelaySeconds": 15,
            "periodSeconds": 20,
            "timeoutSeconds": 5,
            "failureThreshold": 6,
        },
        "lifecycle": {
            "preStop": {
                "exec": {"command": ["/bin/sh", "-c", "sleep 15"]},
            },
        },
        "volumeMounts": volume_mounts,
        "env": env,
    }

    containers = [agent_container]
    if runtime_kind in {"langgraph", "codex", "opencode"}:
        for index, sidecar_spec in enumerate(mcp_sidecars):
            sidecar_name = sidecar_spec.get("name", f"tool-{index}")
            sidecar_port = sidecar_spec.get("port", 8080)
            sidecar_env = [{"name": "MCP_LISTEN_PORT", "value": str(sidecar_port)}]
            sidecar_vol_mounts = [{"name": "tmp-volume", "mountPath": "/tmp"}]
            # Inject git-specific env vars and volume mounts
            if sidecar_name == "git" and git_sidecar_env:
                sidecar_env.extend(git_sidecar_env)
                sidecar_vol_mounts.extend(git_volume_mounts)
            containers.append(
                {
                    "name": f"mcp-{sidecar_name}",
                    "image": sidecar_spec["image"],
                    "ports": [{"containerPort": sidecar_port, "protocol": "TCP"}],
                    "env": sidecar_env,
                    "readinessProbe": {
                        "tcpSocket": {"port": sidecar_port},
                        "initialDelaySeconds": 1,
                        "periodSeconds": 5,
                        "timeoutSeconds": 3,
                        "failureThreshold": 6,
                    },
                    "livenessProbe": {
                        "tcpSocket": {"port": sidecar_port},
                        "initialDelaySeconds": 15,
                        "periodSeconds": 20,
                        "timeoutSeconds": 3,
                        "failureThreshold": 3,
                    },
                    "securityContext": container_security_context,
                    "resources": {
                        "requests": {"cpu": "50m", "memory": "64Mi"},
                        "limits": {"cpu": "500m", "memory": "256Mi"},
                    },
                    "volumeMounts": sidecar_vol_mounts,
                }
            )

    pod_spec: dict[str, Any] = {
        "serviceAccountName": RUNTIME_SERVICE_ACCOUNT,
        "automountServiceAccountToken": False,
        "terminationGracePeriodSeconds": 60,
        "securityContext": pod_security_context,
        "initContainers": init_containers,
        "containers": containers,
        "volumes": volumes + git_volumes,
    }
    if IMAGE_PULL_SECRETS:
        pod_spec["imagePullSecrets"] = [{"name": secret_name} for secret_name in IMAGE_PULL_SECRETS]
    if enable_gvisor:
        pod_spec["runtimeClassName"] = "runsc"

    storage_spec = spec.get("storage", {})
    pod_template_revision = _build_pod_template_revision(spec, runtime_kind, policy_name, policy_spec, mcp_sidecars)

    return {
        "apiVersion": "apps/v1",
        "kind": "StatefulSet",
        "metadata": {
            "name": sandbox_name(name),
            "namespace": namespace,
            "labels": {"app": "ai-agent", "agent-name": name, "runtime-kind": runtime_kind},
        },
        "spec": {
            "serviceName": sandbox_name(name),
            "replicas": 1,
            "selector": {"matchLabels": {"app": "ai-agent", "agent-name": name}},
            "updateStrategy": {"type": "RollingUpdate"},
            "persistentVolumeClaimRetentionPolicy": {
                "whenDeleted": "Retain",
                "whenScaled": "Retain",
            },
            "template": {
                "metadata": {
                    "labels": {"app": "ai-agent", "agent-name": name, "runtime-kind": runtime_kind},
                    "annotations": {POD_TEMPLATE_REVISION_ANNOTATION: pod_template_revision},
                },
                "spec": pod_spec,
            },
            "volumeClaimTemplates": [
                {
                    "metadata": {"name": "state-volume"},
                    "spec": build_pvc_spec(
                        storage_spec.get("size", DEFAULT_STORAGE_SIZE),
                        storage_spec.get("storageClassName"),
                    ),
                }
            ],
        },
    }


def ensure_persistent_storage(namespace: str, manifest: dict[str, Any]) -> None:
    core_api = kubernetes.client.CoreV1Api()
    try:
        core_api.create_namespaced_persistent_volume_claim(namespace=namespace, body=manifest)
    except ApiException as exc:
        if exc.status != 409:
            raise


def ensure_service(namespace: str, manifest: dict[str, Any]) -> None:
    core_api = kubernetes.client.CoreV1Api()
    service_name = manifest["metadata"]["name"]
    try:
        core_api.create_namespaced_service(namespace=namespace, body=manifest)
    except ApiException as exc:
        if exc.status == 409:
            core_api.patch_namespaced_service(name=service_name, namespace=namespace, body=manifest)
            return
        raise


def ensure_statefulset(namespace: str, manifest: dict[str, Any]) -> None:
    apps_api = kubernetes.client.AppsV1Api()
    core_api = kubernetes.client.CoreV1Api()
    statefulset_name = manifest["metadata"]["name"]
    try:
        apps_api.create_namespaced_stateful_set(namespace=namespace, body=manifest)
    except ApiException as exc:
        if exc.status == 409:
            current_statefulset = _sanitize_kube_resource(
                apps_api.read_namespaced_stateful_set(name=statefulset_name, namespace=namespace)
            )
            desired_storage = _extract_statefulset_storage_request(manifest)
            patched_manifest = _preserve_statefulset_immutable_fields(manifest, current_statefulset)
            _patch_statefulset_with_merge_patch(apps_api, namespace, statefulset_name, patched_manifest)
            reconciled_statefulset = _sanitize_kube_resource(
                apps_api.read_namespaced_stateful_set(name=statefulset_name, namespace=namespace)
            )
            desired_signature = _statefulset_template_signature(patched_manifest)
            actual_signature = _statefulset_template_signature(reconciled_statefulset)
            if actual_signature != desired_signature:
                raise kopf.TemporaryError(
                    (
                        f"StatefulSet '{statefulset_name}' in namespace '{namespace}' did not converge to the "
                        "desired pod template after patching."
                    ),
                    delay=2,
                )
            _resize_statefulset_persistent_volume_claims(
                core_api,
                namespace,
                statefulset_name,
                reconciled_statefulset,
                desired_storage,
            )
            return
        raise


def ensure_secret(namespace: str, manifest: dict[str, Any]) -> None:
    core_api = kubernetes.client.CoreV1Api()
    secret_name = str(manifest["metadata"]["name"])
    try:
        core_api.create_namespaced_secret(namespace=namespace, body=manifest)
    except ApiException as exc:
        if exc.status == 409:
            core_api.patch_namespaced_secret(name=secret_name, namespace=namespace, body=manifest)
            return
        raise


def ensure_runtime_namespace_secret(namespace: str, owner_name: str, logger: logging.Logger) -> None:
    if SECRET_PROVISIONING_MODE == "external-secrets":
        external_secret = {
            "apiVersion": "external-secrets.io/v1beta1",
            "kind": "ExternalSecret",
            "metadata": {
                "name": SECRET_NAME,
                "namespace": namespace,
                "labels": {
                    "managed-by": "ai-agent-sandbox",
                    "sandbox.enterprise.ai/runtime-secret": "true",
                    "sandbox.enterprise.ai/owner": owner_name,
                },
            },
            "spec": {
                "refreshInterval": "1h",
                "secretStoreRef": {"name": CLUSTER_SECRET_STORE, "kind": "ClusterSecretStore"},
                "target": {"name": SECRET_NAME},
                "data": [
                    {
                        "secretKey": "LITELLM_MASTER_KEY",
                        "remoteRef": {"key": "ai-agent-sandbox/litellm-master-key"},
                    },
                    {
                        "secretKey": "API_GATEWAY_SHARED_TOKEN",
                        "remoteRef": {"key": "ai-agent-sandbox/api-gateway-shared-token"},
                    }
                ],
            },
        }
        custom_api = kubernetes.client.CustomObjectsApi()
        try:
            custom_api.create_namespaced_custom_object(
                group="external-secrets.io",
                version="v1beta1",
                namespace=namespace,
                plural="externalsecrets",
                body=external_secret,
            )
            logger.info("ExternalSecret '%s' provisioned for namespace '%s'", SECRET_NAME, namespace)
        except ApiException as exc:
            if exc.status == 409:
                try:
                    custom_api.patch_namespaced_custom_object(
                        group="external-secrets.io",
                        version="v1beta1",
                        namespace=namespace,
                        plural="externalsecrets",
                        name=SECRET_NAME,
                        body=external_secret,
                    )
                except ApiException as patch_exc:
                    raise kopf.TemporaryError(
                        f"Failed to update ExternalSecret '{SECRET_NAME}' for namespace '{namespace}': {patch_exc}",
                        delay=30,
                    ) from patch_exc
            else:
                raise kopf.TemporaryError(
                    f"Failed to reconcile ExternalSecret '{SECRET_NAME}' for namespace '{namespace}': {exc}",
                    delay=30,
                ) from exc
        return

    string_data: dict[str, str] = {}
    if DEFAULT_LITELLM_MASTER_KEY:
        string_data["LITELLM_MASTER_KEY"] = DEFAULT_LITELLM_MASTER_KEY
    if DEFAULT_API_GATEWAY_SHARED_TOKEN:
        string_data["API_GATEWAY_SHARED_TOKEN"] = DEFAULT_API_GATEWAY_SHARED_TOKEN

    if not string_data:
        logger.warning(
            (
                "Skipping runtime secret provisioning for namespace '%s' because "
                "DEFAULT_LITELLM_MASTER_KEY and DEFAULT_API_GATEWAY_SHARED_TOKEN are empty."
            ),
            namespace,
        )
        return

    secret_manifest = {
        "apiVersion": "v1",
        "kind": "Secret",
        "metadata": {
            "name": SECRET_NAME,
            "namespace": namespace,
            "labels": {
                "managed-by": "ai-agent-sandbox",
                "sandbox.enterprise.ai/runtime-secret": "true",
                "sandbox.enterprise.ai/owner": owner_name,
            },
        },
        "type": "Opaque",
        "stringData": string_data,
    }
    ensure_secret(namespace, secret_manifest)
    logger.info("Secret '%s' provisioned for namespace '%s'", SECRET_NAME, namespace)


def platform_namespace_selector() -> dict[str, dict[str, str]]:
    return {"matchLabels": {"kubernetes.io/metadata.name": OPERATOR_NAMESPACE}}


def agent_baseline_ingress_peers() -> list[dict[str, Any]]:
    return [
        {
            "namespaceSelector": platform_namespace_selector(),
            "podSelector": {"matchLabels": {"app": "api-gateway"}},
        },
        {
            "namespaceSelector": platform_namespace_selector(),
            "podSelector": {"matchLabels": {"app": "operator"}},
        },
        {
            "namespaceSelector": platform_namespace_selector(),
            "podSelector": {"matchLabels": {"app": "operator-worker"}},
        },
    ]


def agent_baseline_egress_rules() -> list[dict[str, Any]]:
    rules: list[dict[str, Any]] = [
        {
            "ports": [
                {"protocol": "UDP", "port": 53},
                {"protocol": "TCP", "port": 53},
            ],
        },
        {
            "to": [
                {
                    "namespaceSelector": platform_namespace_selector(),
                    "podSelector": {"matchLabels": {"app": "api-gateway"}},
                }
            ],
            "ports": [{"protocol": "TCP", "port": API_PORT}],
        },
        {
            "to": [
                {
                    "namespaceSelector": platform_namespace_selector(),
                    "podSelector": {"matchLabels": {"app": "litellm"}},
                }
            ],
            "ports": [{"protocol": "TCP", "port": 4000}],
        },
        {
            "to": [
                {
                    "namespaceSelector": platform_namespace_selector(),
                    "podSelector": {"matchLabels": {"app": "qdrant"}},
                }
            ],
            "ports": [{"protocol": "TCP", "port": 6333}],
        },
        {
            "ports": [{"protocol": "TCP", "port": 443}],
        },
    ]
    if OTEL_ENDPOINT:
        rules.append(
            {
                "to": [
                    {
                        "namespaceSelector": platform_namespace_selector(),
                        "podSelector": {"matchLabels": {"app": "otel-collector"}},
                    }
                ],
                "ports": [{"protocol": "TCP", "port": 4317}],
            }
        )
    return rules


def create_mcp_network_policy_manifest(name: str, namespace: str, allowed_mcp_types: list[str]) -> dict[str, Any]:
    """Create/replace a per-agent NetworkPolicy that restricts MCP egress to
    only the mcp-server pod *types* listed in AgentPolicy.spec.allowedMcpServers.

    Each allowed type generates a separate egress rule using the pod label
    ``mcp.sandbox.enterprise.ai/type=<type>`` ANDed with the mcp-hub namespace
    label ``sandbox.enterprise.ai/mcp-hub=true``.  If allowedMcpServers is
    empty, no MCP egress is allowed at all.
    """
    egress_rules: list[dict[str, Any]] = agent_baseline_egress_rules()
    for mcp_type in allowed_mcp_types:
        egress_rules.append({
            "to": [
                {
                    "namespaceSelector": {
                        "matchLabels": {"sandbox.enterprise.ai/mcp-hub": "true"}
                    },
                    "podSelector": {
                        "matchLabels": {"mcp.sandbox.enterprise.ai/type": mcp_type}
                    },
                }
            ],
            "ports": [{"protocol": "TCP", "port": 8000}],
        })

    manifest: dict[str, Any] = {
        "apiVersion": "networking.k8s.io/v1",
        "kind": "NetworkPolicy",
        "metadata": {
            "name": f"{sandbox_name(name)}-mcp-egress",
            "namespace": namespace,
            "labels": {
                "app": "ai-agent",
                "agent-name": name,
                "sandbox.enterprise.ai/policy-type": "mcp-egress",
            },
        },
        "spec": {
            "podSelector": {"matchLabels": {"app": "ai-agent", "agent-name": name}},
            "policyTypes": ["Egress"],
            "egress": egress_rules,
        },
    }
    return manifest


def create_a2a_egress_network_policy_manifest(
    name: str,
    namespace: str,
    allowed_targets: list[dict[str, str]],
) -> dict[str, Any]:
    egress_rules: list[dict[str, Any]] = []
    for target in allowed_targets:
        egress_rules.append(
            {
                "to": [
                    {
                        "namespaceSelector": {
                            "matchLabels": {"kubernetes.io/metadata.name": target["namespace"]}
                        },
                        "podSelector": {
                            "matchLabels": {"app": "ai-agent", "agent-name": target["name"]}
                        },
                    }
                ],
                "ports": [{"protocol": "TCP", "port": API_PORT}],
            }
        )

    return {
        "apiVersion": "networking.k8s.io/v1",
        "kind": "NetworkPolicy",
        "metadata": {
            "name": f"{sandbox_name(name)}-a2a-egress",
            "namespace": namespace,
            "labels": {
                "app": "ai-agent",
                "agent-name": name,
                "sandbox.enterprise.ai/policy-type": "a2a-egress",
            },
        },
        "spec": {
            "podSelector": {"matchLabels": {"app": "ai-agent", "agent-name": name}},
            "policyTypes": ["Egress"],
            "egress": egress_rules,
        },
    }


def create_a2a_ingress_network_policy_manifest(
    name: str,
    namespace: str,
    allowed_callers: list[dict[str, str]],
) -> dict[str, Any]:
    allowed_sources: list[dict[str, Any]] = agent_baseline_ingress_peers()
    for caller in allowed_callers:
        allowed_sources.append(
            {
                "namespaceSelector": {
                    "matchLabels": {"kubernetes.io/metadata.name": caller["namespace"]}
                },
                "podSelector": {
                    "matchLabels": {"app": "ai-agent", "agent-name": caller["name"]}
                },
            }
        )

    return {
        "apiVersion": "networking.k8s.io/v1",
        "kind": "NetworkPolicy",
        "metadata": {
            "name": f"{sandbox_name(name)}-a2a-ingress",
            "namespace": namespace,
            "labels": {
                "app": "ai-agent",
                "agent-name": name,
                "sandbox.enterprise.ai/policy-type": "a2a-ingress",
            },
        },
        "spec": {
            "podSelector": {"matchLabels": {"app": "ai-agent", "agent-name": name}},
            "policyTypes": ["Ingress"],
            "ingress": [{"from": allowed_sources, "ports": [{"protocol": "TCP", "port": API_PORT}]}],
        },
    }


def ensure_network_policy(namespace: str, manifest: dict[str, Any]) -> None:
    networking_api = kubernetes.client.NetworkingV1Api()
    policy_name = str(manifest["metadata"]["name"])
    try:
        networking_api.create_namespaced_network_policy(namespace=namespace, body=manifest)
    except ApiException as exc:
        if exc.status == 409:
            networking_api.replace_namespaced_network_policy(
                name=policy_name, namespace=namespace, body=manifest
            )
        else:
            raise


def create_agent_resources(spec: dict[str, Any], name: str, namespace: str, logger: logging.Logger) -> None:
    ensure_runtime_access(namespace)
    ensure_runtime_namespace_secret(namespace, name, logger)
    policy_name, policy_spec = resolve_agent_policy(namespace, spec.get("policyRef"))
    tenant_spec = resolve_tenant_for_namespace(namespace)
    validate_agent_model(spec.get("model", "gpt-4"), policy_spec, tenant_spec)
    agent_a2a_config = parse_agent_a2a_config(spec.get("a2a"), source="AIAgent.spec.a2a")
    policy_a2a_config = parse_policy_a2a_config(policy_spec or {})
    allowed_mcp = sorted(
        {
            str(item).strip()
            for item in (policy_spec.get("allowedMcpServers") or [])
            if str(item).strip()
        }
    )

    service_manifest = create_agent_service_manifest(name, namespace)
    statefulset_manifest = create_agent_statefulset_manifest(name, namespace, spec, policy_name, policy_spec)
    network_policy_manifest = create_mcp_network_policy_manifest(name, namespace, allowed_mcp)
    a2a_egress_policy_manifest = create_a2a_egress_network_policy_manifest(
        name,
        namespace,
        parse_a2a_peer_refs(policy_a2a_config.get("allowedTargets"), source="AgentPolicy.spec.a2a.allowedTargets"),
    )
    a2a_ingress_policy_manifest = create_a2a_ingress_network_policy_manifest(
        name,
        namespace,
        parse_a2a_peer_refs(agent_a2a_config.get("allowedCallers"), source="AIAgent.spec.a2a.allowedCallers"),
    )
    mcp_auth_secret_manifest: dict[str, Any] | None = None
    if allowed_mcp:
        mcp_auth_secret_manifest = create_mcp_auth_secret_manifest(namespace)

    log_operator_event(
        logger,
        logging.INFO,
        "Resolved agent resource configuration.",
        resource_kind="AIAgent",
        name=name,
        namespace=namespace,
        policyName=policy_name,
        allowedMcpServers=allowed_mcp,
        hasTenantPolicy=bool(tenant_spec),
        runtimeKind=str((spec.get("runtime") or {}).get("kind") or "langgraph")
        if isinstance(spec.get("runtime") or {}, dict)
        else "langgraph",
    )

    for manifest in (
        service_manifest,
        statefulset_manifest,
        network_policy_manifest,
        a2a_egress_policy_manifest,
        a2a_ingress_policy_manifest,
    ):
        if manifest is None:
            continue
        kopf.adopt(manifest)

    ensure_service(namespace, service_manifest)
    if mcp_auth_secret_manifest is not None:
        ensure_secret(namespace, mcp_auth_secret_manifest)
    try:
        ensure_statefulset(namespace, statefulset_manifest)
    except Exception:
        # Best-effort cleanup of the Service created above before re-raising
        try:
            kubernetes.client.CoreV1Api().delete_namespaced_service(
                name=name + "-sandbox", namespace=namespace
            )
        except Exception:
            pass
        raise
    ensure_network_policy(namespace, network_policy_manifest)
    ensure_network_policy(namespace, a2a_egress_policy_manifest)
    ensure_network_policy(namespace, a2a_ingress_policy_manifest)


@kopf.on.create("sandbox.enterprise.ai", "v1alpha1", "aiagents")  # type: ignore[arg-type]
def create_agent(spec: dict[str, Any], name: str, namespace: str, logger: Any, **kwargs: Any) -> None:
    del kwargs
    execute_reconcile(
        lambda: create_agent_resources(spec, name, namespace, logger),
        logger=logger,
        action="create-agent",
        resource_kind="AIAgent",
        name=name,
        namespace=namespace,
        default_delay=10,
        start_message="Reconciling AIAgent create event.",
        success_message="AIAgent resources reconciled.",
        policyRef=spec.get("policyRef"),
    )


@kopf.on.update("sandbox.enterprise.ai", "v1alpha1", "aiagents")  # type: ignore[arg-type]
def update_agent(spec: dict[str, Any], name: str, namespace: str, logger: logging.Logger, **kwargs: Any) -> None:
    del kwargs
    execute_reconcile(
        lambda: create_agent_resources(spec, name, namespace, logger),
        logger=logger,
        action="update-agent",
        resource_kind="AIAgent",
        name=name,
        namespace=namespace,
        default_delay=5,
        start_message="Reconciling AIAgent update event.",
        success_message="AIAgent update reconciled.",
        policyRef=spec.get("policyRef"),
    )


@kopf.on.resume("sandbox.enterprise.ai", "v1alpha1", "aiagents")  # type: ignore[arg-type]
def resume_agent(spec: dict[str, Any], name: str, namespace: str, logger: logging.Logger, **kwargs: Any) -> None:
    del kwargs
    execute_reconcile(
        lambda: create_agent_resources(spec, name, namespace, logger),
        logger=logger,
        action="resume-agent",
        resource_kind="AIAgent",
        name=name,
        namespace=namespace,
        default_delay=5,
        start_message="Reconciling existing AIAgent on operator startup.",
        success_message="AIAgent resume reconcile completed.",
        policyRef=spec.get("policyRef"),
    )


@kopf.on.delete("sandbox.enterprise.ai", "v1alpha1", "aiagents")  # type: ignore[arg-type]
def delete_agent(spec: dict[str, Any], name: str, namespace: str, logger: logging.Logger, **kwargs: Any) -> None:
    del spec, kwargs
    log_operator_event(
        logger,
        logging.INFO,
        "AIAgent deleted; Kubernetes-owned resources will be garbage-collected while PVCs are retained.",
        resource_kind="AIAgent",
        name=name,
        namespace=namespace,
        action="delete-agent",
    )


@kopf.on.create("sandbox.enterprise.ai", "v1alpha1", "agentpolicies")  # type: ignore[arg-type]
def create_policy(spec: dict[str, Any], name: str, namespace: str, logger: logging.Logger, **kwargs: Any) -> None:
    del kwargs
    execute_reconcile(
        lambda: validate_supported_policy_spec(spec),
        logger=logger,
        action="validate-policy",
        resource_kind="AgentPolicy",
        name=name,
        namespace=namespace,
        start_message="Validating AgentPolicy create event.",
        success_message="AgentPolicy validated.",
    )


@kopf.on.update("sandbox.enterprise.ai", "v1alpha1", "agentpolicies")  # type: ignore[arg-type]
def update_policy(spec: dict[str, Any], name: str, namespace: str, logger: logging.Logger, **kwargs: Any) -> None:
    del kwargs
    execute_reconcile(
        lambda: validate_supported_policy_spec(spec),
        logger=logger,
        action="update-policy",
        resource_kind="AgentPolicy",
        name=name,
        namespace=namespace,
        start_message="Validating AgentPolicy update event.",
        success_message="AgentPolicy update validated.",
    )


@kopf.on.create("sandbox.enterprise.ai", "v1alpha1", "agenttenants")  # type: ignore[arg-type]
def create_tenant(spec: dict[str, Any], name: str, logger: logging.Logger, **kwargs: Any) -> None:
    del kwargs
    tenant_name = spec.get("tenantName", name)
    target_ns = spec.get("namespace", f"agent-tenant-{tenant_name}")
    quota_spec = spec.get("resourceQuota", {})
    admin_users = spec.get("adminUsers", [])

    if target_ns in PROTECTED_NAMESPACES or target_ns == OPERATOR_NAMESPACE:
        log_operator_event(
            logger,
            logging.ERROR,
            "Refusing to provision AgentTenant into a protected namespace.",
            resource_kind="AgentTenant",
            name=name,
            action="create-tenant",
            tenantName=tenant_name,
            targetNamespace=target_ns,
        )
        raise kopf.PermanentError(
            f"Refusing to provision tenant '{tenant_name}' into protected namespace '{target_ns}'."
        )

    log_operator_event(
        logger,
        logging.INFO,
        "Reconciling AgentTenant create event.",
        resource_kind="AgentTenant",
        name=name,
        action="create-tenant",
        tenantName=tenant_name,
        targetNamespace=target_ns,
        adminUserCount=len(admin_users),
    )

    try:
        core_api = kubernetes.client.CoreV1Api()
        rbac_api = kubernetes.client.RbacAuthorizationV1Api()

        namespace_body = kubernetes.client.V1Namespace(
            metadata=kubernetes.client.V1ObjectMeta(
                name=target_ns,
                labels={
                    "managed-by": "ai-agent-sandbox",
                    "tenant": tenant_name,
                    # Required by the mcp-hub NetworkPolicy to allow ingress from
                    # tenant agent pods into the mcp-hub namespace MCP server pods.
                    "sandbox.enterprise.ai/tenant": "true",
                },
            )
        )
        try:
            core_api.create_namespace(body=namespace_body)
            logger.info("Namespace '%s' created", target_ns)
        except ApiException as exc:
            if exc.status == 409:
                core_api.patch_namespace(
                    name=target_ns,
                    body={"metadata": {"labels": namespace_body.metadata.labels}},
                )
                logger.info("Namespace '%s' already exists", target_ns)
            elif exc.status in (400, 422):
                raise kopf.PermanentError(f"Invalid namespace spec: {describe_api_exception(exc)}") from exc
            else:
                raise

        ensure_runtime_access(target_ns)

        hard_limits = {}
        if quota_spec.get("maxCPU"):
            hard_limits["limits.cpu"] = quota_spec["maxCPU"]
        if quota_spec.get("maxMemory"):
            hard_limits["limits.memory"] = quota_spec["maxMemory"]
        if quota_spec.get("maxPods"):
            hard_limits["pods"] = str(quota_spec["maxPods"])
        if quota_spec.get("maxGPU"):
            hard_limits["requests.nvidia.com/gpu"] = quota_spec["maxGPU"]

        if hard_limits:
            quota_body = kubernetes.client.V1ResourceQuota(
                metadata=kubernetes.client.V1ObjectMeta(name=f"{tenant_name}-quota"),
                spec=kubernetes.client.V1ResourceQuotaSpec(hard=hard_limits),
            )
            try:
                core_api.create_namespaced_resource_quota(namespace=target_ns, body=quota_body)
                logger.info("ResourceQuota created for tenant '%s': %s", tenant_name, hard_limits)
            except ApiException as exc:
                if exc.status == 409:
                    core_api.patch_namespaced_resource_quota(
                        name=f"{tenant_name}-quota",
                        namespace=target_ns,
                        body=quota_body,
                    )
                else:
                    raise

        limit_range = kubernetes.client.V1LimitRange(
            metadata=kubernetes.client.V1ObjectMeta(name=f"{tenant_name}-limits"),
            spec=kubernetes.client.V1LimitRangeSpec(
                limits=[
                    kubernetes.client.V1LimitRangeItem(
                        type="Container",
                        default={"cpu": "500m", "memory": "512Mi"},
                        default_request={"cpu": "100m", "memory": "128Mi"},
                    )
                ]
            ),
        )
        try:
            core_api.create_namespaced_limit_range(namespace=target_ns, body=limit_range)
            logger.info("LimitRange created for tenant '%s'", tenant_name)
        except ApiException as exc:
            if exc.status == 409:
                core_api.patch_namespaced_limit_range(
                    name=f"{tenant_name}-limits",
                    namespace=target_ns,
                    body=limit_range,
                )
            else:
                raise

        role = kubernetes.client.V1Role(
            metadata=kubernetes.client.V1ObjectMeta(name=f"{tenant_name}-agent-admin", namespace=target_ns),
            rules=[
                kubernetes.client.V1PolicyRule(
                    api_groups=["sandbox.enterprise.ai"],
                    resources=["aiagents", "agentpolicies", "agentapprovals", "agentworkflows", "agentevals"],
                    verbs=["*"],
                ),
                kubernetes.client.V1PolicyRule(
                    api_groups=[""],
                    resources=["pods", "pods/exec", "pods/portforward", "pods/log", "services"],
                    verbs=["get", "list", "watch", "create"],
                ),
            ],
        )
        try:
            rbac_api.create_namespaced_role(namespace=target_ns, body=role)
        except ApiException as exc:
            if exc.status == 409:
                rbac_api.patch_namespaced_role(
                    name=f"{tenant_name}-agent-admin",
                    namespace=target_ns,
                    body=role,
                )
            else:
                raise

        for user in admin_users:
            safe_user = re.sub(r"[^a-z0-9-]", "-", user.lower().strip()).strip("-")
            if not safe_user:
                logger.warning("Skipping empty or invalid user string: %s", user)
                continue

            binding = kubernetes.client.V1RoleBinding(
                metadata=kubernetes.client.V1ObjectMeta(
                    name=f"{tenant_name}-{safe_user}-binding",
                    namespace=target_ns,
                ),
                role_ref=kubernetes.client.V1RoleRef(
                    api_group="rbac.authorization.k8s.io",
                    kind="Role",
                    name=f"{tenant_name}-agent-admin",
                ),
                subjects=[
                    kubernetes.client.V1Subject(
                        kind="User",
                        name=user,
                        api_group="rbac.authorization.k8s.io",
                    )
                ],
            )
            try:
                rbac_api.create_namespaced_role_binding(namespace=target_ns, body=binding)
                logger.info("RoleBinding created for user '%s' in tenant '%s'", user, tenant_name)
            except ApiException as exc:
                if exc.status == 409:
                    rbac_api.patch_namespaced_role_binding(
                        name=f"{tenant_name}-{safe_user}-binding",
                        namespace=target_ns,
                        body=binding,
                    )
                else:
                    raise

        ensure_runtime_namespace_secret(target_ns, tenant_name, logger)

        log_operator_event(
            logger,
            logging.INFO,
            "AgentTenant resources reconciled.",
            resource_kind="AgentTenant",
            name=name,
            action="create-tenant",
            tenantName=tenant_name,
            targetNamespace=target_ns,
            adminUserCount=len(admin_users),
            quotaConfigured=bool(hard_limits),
        )
    except Exception as exc:
        raise_reconcile_error(
            logger,
            "create-tenant",
            exc,
            resource_kind="AgentTenant",
            name=name,
            default_delay=15,
            tenantName=tenant_name,
            targetNamespace=target_ns,
            adminUserCount=len(admin_users),
        )


@kopf.on.delete("sandbox.enterprise.ai", "v1alpha1", "agenttenants")  # type: ignore[arg-type]
def delete_tenant(spec: dict[str, Any], name: str, logger: logging.Logger, **kwargs: Any) -> None:
    del kwargs
    tenant_name = spec.get("tenantName", name)
    target_ns = spec.get("namespace", f"agent-tenant-{tenant_name}")
    if target_ns in PROTECTED_NAMESPACES or target_ns == OPERATOR_NAMESPACE:
        log_operator_event(
            logger,
            logging.ERROR,
            "Refusing to delete protected namespace via AgentTenant deletion.",
            resource_kind="AgentTenant",
            name=name,
            action="delete-tenant",
            tenantName=tenant_name,
            targetNamespace=target_ns,
        )
        return

    try:
        log_operator_event(
            logger,
            logging.INFO,
            "Deleting tenant namespace.",
            resource_kind="AgentTenant",
            name=name,
            action="delete-tenant",
            tenantName=tenant_name,
            targetNamespace=target_ns,
        )
        kubernetes.client.CoreV1Api().delete_namespace(name=target_ns)
    except ApiException as exc:
        if exc.status != 404:
            raise_reconcile_error(
                logger,
                "delete-tenant",
                exc,
                resource_kind="AgentTenant",
                name=name,
                default_delay=15,
                tenantName=tenant_name,
                targetNamespace=target_ns,
            )
        log_operator_event(
            logger,
            logging.INFO,
            "Tenant namespace already absent during delete.",
            resource_kind="AgentTenant",
            name=name,
            action="delete-tenant",
            tenantName=tenant_name,
            targetNamespace=target_ns,
        )
        return
    log_operator_event(
        logger,
        logging.INFO,
        "Tenant namespace deletion requested.",
        resource_kind="AgentTenant",
        name=name,
        action="delete-tenant",
        tenantName=tenant_name,
        targetNamespace=target_ns,
    )


@kopf.on.update("sandbox.enterprise.ai", "v1alpha1", "agenttenants")  # type: ignore[arg-type]
def update_tenant(spec: dict[str, Any], name: str, logger: logging.Logger, **kwargs: Any) -> None:
    del kwargs
    execute_reconcile(
        lambda: create_tenant(spec, name, logger),
        logger=logger,
        action="update-tenant",
        resource_kind="AgentTenant",
        name=name,
        namespace=spec.get("namespace", f"agent-tenant-{spec.get('tenantName', name)}"),
        default_delay=10,
        start_message="Reconciling AgentTenant update event.",
        success_message="AgentTenant update reconciled.",
    )


@kopf.on.resume("sandbox.enterprise.ai", "v1alpha1", "agenttenants")  # type: ignore[arg-type]
def resume_tenant(spec: dict[str, Any], name: str, logger: logging.Logger, **kwargs: Any) -> None:
    del kwargs
    execute_reconcile(
        lambda: create_tenant(spec, name, logger),
        logger=logger,
        action="resume-tenant",
        resource_kind="AgentTenant",
        name=name,
        namespace=spec.get("namespace", f"agent-tenant-{spec.get('tenantName', name)}"),
        default_delay=10,
        start_message="Reconciling existing AgentTenant on operator startup.",
        success_message="AgentTenant resume reconcile completed.",
    )


def patch_custom_status(plural: str, namespace: str, name: str, status: dict[str, Any]) -> None:
    kubernetes.client.CustomObjectsApi().patch_namespaced_custom_object_status(
        group="sandbox.enterprise.ai",
        version="v1alpha1",
        namespace=namespace,
        plural=plural,
        name=name,
        body={"status": status},
    )


def ensure_worker_artifact_storage(kind: str, resource_namespace: str, resource_name: str) -> str:
    manifest = create_worker_artifact_pvc_manifest(kind, resource_namespace, resource_name)
    ensure_persistent_storage(OPERATOR_NAMESPACE, manifest)
    return str(manifest["metadata"]["name"])


def create_worker_job_manifest(
    kind: str,
    resource_namespace: str,
    resource_name: str,
    generation: int,
    artifact_pvc_name: str,
    artifact_path: str,
    *,
    run_id: str | None = None,
) -> dict[str, Any]:
    timestamp = int(time.time())
    job_name = hashed_resource_name(kind, resource_namespace, resource_name, suffix=f"{generation}-{timestamp}")
    artifact_journal_path = workflow_journal_path(artifact_path)
    pod_security_context = {
        "runAsNonRoot": True,
        "seccompProfile": {"type": "RuntimeDefault"},
    }
    container_security_context = {
        "allowPrivilegeEscalation": False,
        "readOnlyRootFilesystem": True,
        "capabilities": {"drop": ["ALL"]},
    }
    return {
        "apiVersion": "batch/v1",
        "kind": "Job",
        "metadata": {
            "name": job_name,
            "namespace": OPERATOR_NAMESPACE,
            "labels": {
                "app": "operator-worker",
                "sandbox.enterprise.ai/resource-kind": kind,
                "sandbox.enterprise.ai/resource-name": resource_name,
                "sandbox.enterprise.ai/resource-namespace": resource_namespace,
            },
        },
        "spec": {
            "ttlSecondsAfterFinished": WORKER_TTL_SECONDS_AFTER_FINISHED,
            "activeDeadlineSeconds": WORKER_ACTIVE_DEADLINE_SECONDS,
            "backoffLimit": 1,
            "template": {
                "metadata": {
                    "labels": {
                        "app": "operator-worker",
                        "sandbox.enterprise.ai/resource-kind": kind,
                    }
                },
                "spec": {
                    "restartPolicy": "Never",
                    "serviceAccountName": WORKER_SERVICE_ACCOUNT_NAME,
                    "securityContext": pod_security_context,
                    "imagePullSecrets": [{"name": secret_name} for secret_name in IMAGE_PULL_SECRETS],
                    "containers": [
                        {
                            "name": "worker",
                            "image": WORKER_IMAGE,
                            "imagePullPolicy": WORKER_IMAGE_PULL_POLICY,
                            "command": ["python", "/app/worker.py"],
                            "securityContext": container_security_context,
                            "resources": {
                                "requests": {"cpu": WORKER_CPU_REQUEST, "memory": WORKER_MEMORY_REQUEST},
                                "limits": {"cpu": WORKER_CPU_LIMIT, "memory": WORKER_MEMORY_LIMIT},
                            },
                            "env": [
                                {"name": "WORKER_KIND", "value": kind},
                                {"name": "TARGET_NAMESPACE", "value": resource_namespace},
                                {"name": "TARGET_NAME", "value": resource_name},
                                {"name": "OPERATOR_NAMESPACE", "value": OPERATOR_NAMESPACE},
                                {"name": "WORKER_JOB_NAME", "value": job_name},
                                {"name": "ARTIFACT_PATH", "value": artifact_path},
                                {"name": "ARTIFACT_JOURNAL_PATH", "value": artifact_journal_path},
                                {"name": "ARTIFACT_PVC_NAME", "value": artifact_pvc_name},
                                {"name": "AGENT_RUNTIME_TIMEOUT_SECONDS", "value": AGENT_RUNTIME_TIMEOUT_SECONDS},
                                {"name": "WORKFLOW_RUN_ID", "value": run_id or ""},
                                {"name": "EVAL_RUN_ID", "value": run_id or ""},
                                {"name": "PYTHONDONTWRITEBYTECODE", "value": "1"},
                                *worker_passthrough_env(),
                            ],
                            "volumeMounts": [
                                {"name": "artifacts", "mountPath": ARTIFACT_MOUNT_PATH},
                                {"name": "tmp", "mountPath": "/tmp"},
                            ],
                        }
                    ],
                    "volumes": [
                        {
                            "name": "artifacts",
                            "persistentVolumeClaim": {"claimName": artifact_pvc_name},
                        },
                        {"name": "tmp", "emptyDir": {"sizeLimit": "1Gi"}},
                    ],
                },
            },
        },
    }


def enqueue_worker_job(
    kind: str,
    resource_namespace: str,
    resource_name: str,
    generation: int,
    artifact_pvc_name: str,
    artifact_path: str,
    *,
    run_id: str | None = None,
) -> str:
    manifest = create_worker_job_manifest(
        kind,
        resource_namespace,
        resource_name,
        generation,
        artifact_pvc_name,
        artifact_path,
        run_id=run_id,
    )
    batch_api = kubernetes.client.BatchV1Api()
    batch_api.create_namespaced_job(namespace=OPERATOR_NAMESPACE, body=manifest)
    return str(manifest["metadata"]["name"])


def read_job_state(name: str, namespace: str) -> str:
    if not name:
        return "missing"

    batch_api = kubernetes.client.BatchV1Api()
    try:
        job = batch_api.read_namespaced_job(name=name, namespace=namespace)
    except ApiException as exc:
        if exc.status == 404:
            return "missing"
        raise

    status = job.status
    if status is None:
        return "pending"
    if (status.active or 0) > 0:
        return "active"
    if (status.succeeded or 0) > 0:
        return "succeeded"
    if (status.failed or 0) > 0:
        return "failed"
    return "pending"


def cancel_worker_job(name: str, namespace: str) -> bool:
    """Delete a worker Job and its pods. Returns True if a Job was deleted."""
    if not name:
        return False
    batch_api = kubernetes.client.BatchV1Api()
    try:
        batch_api.delete_namespaced_job(
            name=name,
            namespace=namespace,
            body=kubernetes.client.V1DeleteOptions(propagation_policy="Background"),
        )
        return True
    except ApiException as exc:
        if exc.status == 404:
            return False
        raise


def enqueue_eval_job(
    spec: dict[str, Any],
    meta: dict[str, Any],
    name: str,
    namespace: str,
    logger: logging.Logger,
    *,
    scheduled: bool = False,
) -> None:
    test_suite = spec.get("testSuite") or []
    generation = int((meta or {}).get("generation", 1))
    run_id = build_eval_run_id(namespace, name, generation)
    artifact_pvc_name = ensure_worker_artifact_storage("eval", namespace, name)
    artifact_path = artifact_file_path("eval", namespace, name, generation)
    job_name = enqueue_worker_job(
        "eval",
        namespace,
        name,
        generation,
        artifact_pvc_name,
        artifact_path,
        run_id=run_id,
    )
    summary = {
        "queuedAt": now_iso(),
        "caseCount": len(test_suite),
        "completedCases": 0,
        "runId": run_id,
    }
    if scheduled:
        summary["scheduleTriggered"] = True
    status_payload = {
        "phase": "queued",
        "runId": run_id,
        "observedGeneration": generation,
        "artifactRef": build_artifact_ref(artifact_pvc_name, artifact_path, generation),
        "workerJob": {"name": job_name, "namespace": OPERATOR_NAMESPACE},
        "summary": summary,
    }
    patch_custom_status(
        "agentevals",
        namespace,
        name,
        status_payload,
    )
    safe_record_eval_state(
        namespace=namespace,
        resource_name=name,
        generation=generation,
        run_id=run_id,
        phase="queued",
        passed=None,
        spec=spec,
        status=status_payload,
    )
    log_operator_event(
        logger,
        logging.INFO,
        "Queued AgentEval for worker execution.",
        resource_kind="AgentEval",
        name=name,
        namespace=namespace,
        meta=meta,
        generation=generation,
        workerJob=job_name,
        caseCount=len(test_suite),
        scheduled=scheduled,
    )


def enqueue_workflow_job(
    spec: dict[str, Any],
    meta: dict[str, Any],
    name: str,
    namespace: str,
    logger: logging.Logger,
    *,
    current_status: dict[str, Any] | None = None,
    run_id: str | None = None,
    requeue_reason: str | None = None,
) -> str:
    graph = validate_workflow_spec(spec)
    steps = spec.get("steps") or []
    generation = int((meta or {}).get("generation", 1))
    workflow_status = current_status or {}

    # Cancel any stale worker job from a previous run before creating a new one.
    previous_job = workflow_status.get("workerJob", {}) or {}
    previous_job_name = str(previous_job.get("name") or "")
    if previous_job_name:
        cancel_worker_job(previous_job_name, str(previous_job.get("namespace") or OPERATOR_NAMESPACE))

    resolved_run_id = run_id or str(workflow_status.get("runId") or "") or build_workflow_run_id(
        namespace,
        name,
        generation,
    )
    artifact_pvc_name = ensure_worker_artifact_storage("workflow", namespace, name)
    artifact_path = artifact_file_path("workflow", namespace, name, generation)
    journal_path = workflow_journal_path(artifact_path)
    job_name = enqueue_worker_job(
        "workflow",
        namespace,
        name,
        generation,
        artifact_pvc_name,
        artifact_path,
        run_id=resolved_run_id,
    )
    existing_summary = workflow_status.get("summary", {}) or {}
    summary = {
        **existing_summary,
        "queuedAt": now_iso(),
        "updatedAt": now_iso(),
        "completedSteps": int(existing_summary.get("completedSteps", 0) or 0),
        "totalSteps": len(steps),
        "rootSteps": graph.get("roots") or [],
        "runId": resolved_run_id,
    }
    if requeue_reason:
        summary["lastRequeueReason"] = requeue_reason

    patch_custom_status(
        "agentworkflows",
        namespace,
        name,
        {
            "phase": "queued",
            "runId": resolved_run_id,
            "currentStep": str(workflow_status.get("currentStep", "") or ""),
            "observedGeneration": generation,
            "artifactRef": build_artifact_ref(
                artifact_pvc_name,
                artifact_path,
                generation,
                journal_path=journal_path,
            ),
            "journalRef": build_journal_ref(artifact_pvc_name, journal_path, generation),
            "workerJob": {"name": job_name, "namespace": OPERATOR_NAMESPACE},
            "summary": summary,
            "pendingApproval": None,
            "stepStates": workflow_status.get("stepStates", {}) or {},
        },
    )
    safe_record_workflow_state(
        namespace=namespace,
        resource_name=name,
        generation=generation,
        run_id=resolved_run_id,
        phase="queued",
        spec=spec,
        status={
            "phase": "queued",
            "runId": resolved_run_id,
            "currentStep": str(workflow_status.get("currentStep", "") or ""),
            "observedGeneration": generation,
            "artifactRef": build_artifact_ref(
                artifact_pvc_name,
                artifact_path,
                generation,
                journal_path=journal_path,
            ),
            "journalRef": build_journal_ref(artifact_pvc_name, journal_path, generation),
            "workerJob": {"name": job_name, "namespace": OPERATOR_NAMESPACE},
            "summary": summary,
            "pendingApproval": None,
            "stepStates": workflow_status.get("stepStates", {}) or {},
        },
    )
    logger.info(
        "Queued workflow '%s/%s' for background execution in job '%s' with run '%s'.",
        namespace,
        name,
        job_name,
        resolved_run_id,
    )
    log_operator_event(
        logger,
        logging.INFO,
        "Queued AgentWorkflow for worker execution.",
        resource_kind="AgentWorkflow",
        name=name,
        namespace=namespace,
        meta=meta,
        generation=generation,
        workerJob=job_name,
        runId=resolved_run_id,
        requeueReason=requeue_reason,
        stepCount=len(steps),
    )
    return job_name


@kopf.on.create("sandbox.enterprise.ai", "v1alpha1", "agentworkflows")  # type: ignore[arg-type]
@kopf.on.update("sandbox.enterprise.ai", "v1alpha1", "agentworkflows")  # type: ignore[arg-type]
def run_workflow(
    spec: dict[str, Any],
    status: dict[str, Any],
    meta: dict[str, Any],
    name: str,
    namespace: str,
    logger: logging.Logger,
    **kwargs: Any,
) -> None:
    del kwargs
    graph = validate_workflow_spec(spec)
    steps = spec.get("steps") or []

    current_status = status or {}
    generation = int((meta or {}).get("generation", 1))
    observed_generation = int(current_status.get("observedGeneration", 0) or 0)
    phase = str(current_status.get("phase", ""))
    if observed_generation == generation and phase in {"queued", "running", "waiting-approval", "completed", "failed", "cancelled"}:
        log_operator_event(
            logger,
            logging.INFO,
            "Skipping workflow enqueue because the current generation is already reconciled.",
            resource_kind="AgentWorkflow",
            name=name,
            namespace=namespace,
            meta=meta,
            generation=generation,
            action="run-workflow",
            observedGeneration=observed_generation,
            phase=phase,
        )
        return

    execute_reconcile(
        lambda: (
            patch_custom_status(
                "agentworkflows",
                namespace,
                name,
                {
                    **current_status,
                    "summary": {
                        **(current_status.get("summary", {}) or {}),
                        "totalSteps": len(steps),
                        "rootSteps": graph.get("roots") or [],
                        "updatedAt": now_iso(),
                    },
                },
            ),
            enqueue_workflow_job(spec, meta, name, namespace, logger, current_status=current_status),
        ),
        logger=logger,
        action="run-workflow",
        resource_kind="AgentWorkflow",
        name=name,
        namespace=namespace,
        meta=meta,
        generation=generation,
        default_delay=10,
        start_message="Reconciling AgentWorkflow for execution.",
        success_message="AgentWorkflow queued successfully.",
        observedGeneration=observed_generation,
        stepCount=len(steps),
    )


@kopf.on.create("sandbox.enterprise.ai", "v1alpha1", "agentevals")  # type: ignore[arg-type]
@kopf.on.update("sandbox.enterprise.ai", "v1alpha1", "agentevals")  # type: ignore[arg-type]
def run_eval(
    spec: dict[str, Any],
    status: dict[str, Any],
    meta: dict[str, Any],
    name: str,
    namespace: str,
    logger: logging.Logger,
    **kwargs: Any,
) -> None:
    test_suite = spec.get("testSuite") or []
    if not test_suite:
        raise kopf.PermanentError("AgentEval must contain at least one test case")

    schedule = str(spec.get("schedule") or "").strip()
    if schedule:
        validate_eval_schedule(schedule)

    current_status = status or {}
    generation = int((meta or {}).get("generation", 1))
    observed_generation = int(current_status.get("observedGeneration", 0) or 0)
    phase = str(current_status.get("phase", ""))
    if observed_generation == generation and phase in {"queued", "running", "completed", "failed"}:
        log_operator_event(
            logger,
            logging.INFO,
            "Skipping eval enqueue because the current generation is already reconciled.",
            resource_kind="AgentEval",
            name=name,
            namespace=namespace,
            meta=meta,
            generation=generation,
            action="run-eval",
            observedGeneration=observed_generation,
            phase=phase,
        )
        return

    execute_reconcile(
        lambda: enqueue_eval_job(spec, meta, name, namespace, logger),
        logger=logger,
        action="run-eval",
        resource_kind="AgentEval",
        name=name,
        namespace=namespace,
        meta=meta,
        generation=generation,
        default_delay=10,
        start_message="Reconciling AgentEval for execution.",
        success_message="AgentEval queued successfully.",
        observedGeneration=observed_generation,
        caseCount=len(test_suite),
        schedule=schedule,
    )


@kopf.on.resume("sandbox.enterprise.ai", "v1alpha1", "agentevals")  # type: ignore[arg-type]
def resume_eval(
    spec: dict[str, Any],
    status: dict[str, Any],
    meta: dict[str, Any],
    name: str,
    namespace: str,
    logger: logging.Logger,
    **kwargs: Any,
) -> None:
    del kwargs
    current_status = status or {}
    phase = str(current_status.get("phase", "") or "")
    if phase not in {"queued", "running"}:
        return
    worker_job = current_status.get("workerJob", {}) or {}
    job_state = read_job_state(
        str(worker_job.get("name") or ""),
        str(worker_job.get("namespace") or OPERATOR_NAMESPACE),
    )
    if job_state == "active":
        log_operator_event(
            logger,
            logging.INFO,
            "AgentEval resume: worker job still active, skipping re-enqueue.",
            resource_kind="AgentEval",
            name=name,
            namespace=namespace,
            action="resume-eval",
            phase=phase,
            jobState=job_state,
        )
        return
    log_operator_event(
        logger,
        logging.WARNING,
        "AgentEval resume: worker job not active, re-enqueueing.",
        resource_kind="AgentEval",
        name=name,
        namespace=namespace,
        action="resume-eval",
        phase=phase,
        jobState=job_state,
    )
    execute_reconcile(
        lambda: enqueue_eval_job(spec, meta, name, namespace, logger),
        logger=logger,
        action="resume-eval",
        resource_kind="AgentEval",
        name=name,
        namespace=namespace,
        meta=meta,
        default_delay=10,
        start_message="Re-enqueueing AgentEval after operator restart.",
        success_message="AgentEval re-enqueued after operator restart.",
        phase=phase,
        jobState=job_state,
    )


@kopf.on.delete("sandbox.enterprise.ai", "v1alpha1", "agentevals")  # type: ignore[arg-type]
def delete_eval(
    status: dict[str, Any],
    name: str,
    namespace: str,
    logger: logging.Logger,
    **kwargs: Any,
) -> None:
    del kwargs
    current_status = status or {}
    worker_job = current_status.get("workerJob", {}) or {}
    job_name = str(worker_job.get("name") or "")
    job_namespace = str(worker_job.get("namespace") or OPERATOR_NAMESPACE)
    cancelled = cancel_worker_job(job_name, job_namespace)
    log_operator_event(
        logger,
        logging.INFO,
        "AgentEval deleted; worker job cancelled."
        if cancelled
        else "AgentEval deleted; no active worker job to cancel.",
        resource_kind="AgentEval",
        name=name,
        namespace=namespace,
        action="delete-eval",
        workerJobCancelled=cancelled,
        workerJobName=job_name,
    )


@kopf.timer(
    "sandbox.enterprise.ai",
    "v1alpha1",
    "agentworkflows",
    interval=WORKFLOW_POLL_SECONDS,
)  # type: ignore[arg-type]
def run_workflow_watchdog(
    spec: dict[str, Any],
    status: dict[str, Any],
    meta: dict[str, Any],
    name: str,
    namespace: str,
    logger: logging.Logger,
    **kwargs: Any,
) -> None:  # type: ignore[misc]
    del kwargs

    current_status = status or {}
    worker_job = current_status.get("workerJob", {}) or {}
    job_state = read_job_state(
        str(worker_job.get("name") or ""),
        str(worker_job.get("namespace") or OPERATOR_NAMESPACE),
    )
    reason = workflow_should_requeue(current_status, job_state)
    if reason is None:
        return

    logger.warning(
        "Workflow '%s/%s' will be re-enqueued by watchdog: %s",
        namespace,
        name,
        reason,
    )
    execute_reconcile(
        lambda: enqueue_workflow_job(
            spec,
            meta,
            name,
            namespace,
            logger,
            current_status=current_status,
            run_id=str(current_status.get("runId") or "") or None,
            requeue_reason=reason,
        ),
        logger=logger,
        action="watchdog-requeue-workflow",
        resource_kind="AgentWorkflow",
        name=name,
        namespace=namespace,
        meta=meta,
        default_delay=10,
        start_message="Re-enqueueing stale AgentWorkflow from watchdog.",
        success_message="Watchdog re-enqueued AgentWorkflow.",
        reason=reason,
        phase=str(current_status.get("phase", "") or ""),
        workerJob=current_status.get("workerJob", {}) or {},
        jobState=job_state,
    )


@kopf.on.field("sandbox.enterprise.ai", "v1alpha1", "agentworkflows", field="status.phase")  # type: ignore[arg-type]
def on_workflow_phase_cancelled(
    old: str | None,
    new: str | None,
    status: dict[str, Any],
    name: str,
    namespace: str,
    logger: logging.Logger,
    **kwargs: Any,
) -> None:
    """Kill the worker Job when a workflow is cancelled."""
    del kwargs
    if new != "cancelled":
        return
    worker_job = (status or {}).get("workerJob", {}) or {}
    job_name = str(worker_job.get("name") or "")
    job_namespace = str(worker_job.get("namespace") or OPERATOR_NAMESPACE)
    cancelled = cancel_worker_job(job_name, job_namespace)
    log_operator_event(
        logger,
        logging.INFO,
        "Cancelled worker Job %s (deleted=%s)." % (job_name or "<none>", cancelled),
        resource_kind="AgentWorkflow",
        name=name,
        namespace=namespace,
    )


@kopf.on.resume("sandbox.enterprise.ai", "v1alpha1", "agentworkflows")  # type: ignore[arg-type]
def resume_workflow(
    spec: dict[str, Any],
    status: dict[str, Any],
    meta: dict[str, Any],
    name: str,
    namespace: str,
    logger: logging.Logger,
    **kwargs: Any,
) -> None:
    del kwargs
    current_status = status or {}
    phase = str(current_status.get("phase", "") or "")
    if phase not in {"queued", "running", "waiting-approval"}:
        return
    worker_job = current_status.get("workerJob", {}) or {}
    job_state = read_job_state(
        str(worker_job.get("name") or ""),
        str(worker_job.get("namespace") or OPERATOR_NAMESPACE),
    )
    if job_state == "active":
        log_operator_event(
            logger,
            logging.INFO,
            "AgentWorkflow resume: worker job still active, skipping re-enqueue.",
            resource_kind="AgentWorkflow",
            name=name,
            namespace=namespace,
            action="resume-workflow",
            phase=phase,
            jobState=job_state,
        )
        return
    log_operator_event(
        logger,
        logging.INFO,
        "AgentWorkflow resume: re-enqueueing workflow whose worker job is no longer active.",
        resource_kind="AgentWorkflow",
        name=name,
        namespace=namespace,
        action="resume-workflow",
        phase=phase,
        jobState=job_state,
    )
    execute_reconcile(
        lambda: enqueue_workflow_job(
            spec,
            meta,
            name,
            namespace,
            logger,
            current_status=current_status,
            run_id=str(current_status.get("runId") or "") or None,
            requeue_reason=f"operator restart (previous phase: {phase}, job state: {job_state})",
        ),
        logger=logger,
        action="resume-workflow",
        resource_kind="AgentWorkflow",
        name=name,
        namespace=namespace,
        meta=meta,
        default_delay=10,
        start_message="Re-enqueueing AgentWorkflow after operator restart.",
        success_message="AgentWorkflow re-enqueued after operator restart.",
        phase=phase,
        jobState=job_state,
    )


@kopf.on.delete("sandbox.enterprise.ai", "v1alpha1", "agentworkflows")  # type: ignore[arg-type]
def delete_workflow(
    status: dict[str, Any],
    name: str,
    namespace: str,
    logger: logging.Logger,
    **kwargs: Any,
) -> None:
    del kwargs
    current_status = status or {}
    worker_job = current_status.get("workerJob", {}) or {}
    job_name = str(worker_job.get("name") or "")
    job_namespace = str(worker_job.get("namespace") or OPERATOR_NAMESPACE)
    cancelled = cancel_worker_job(job_name, job_namespace)
    log_operator_event(
        logger,
        logging.INFO,
        "AgentWorkflow deleted; worker job cancelled."
        if cancelled
        else "AgentWorkflow deleted; no active worker job to cancel.",
        resource_kind="AgentWorkflow",
        name=name,
        namespace=namespace,
        action="delete-workflow",
        workerJobCancelled=cancelled,
        workerJobName=job_name,
    )


@kopf.timer(
    "sandbox.enterprise.ai",
    "v1alpha1",
    "agentevals",
    interval=EVAL_SCHEDULE_POLL_SECONDS,
)  # type: ignore[arg-type]
def run_scheduled_eval(
    spec: dict[str, Any],
    status: dict[str, Any],
    meta: dict[str, Any],
    name: str,
    namespace: str,
    logger: logging.Logger,
    **kwargs: Any,
) -> None:
    del kwargs

    schedule = str(spec.get("schedule") or "").strip()
    if not schedule:
        return

    validate_eval_schedule(schedule)

    current_status = status or {}
    phase = str(current_status.get("phase", ""))
    if phase == "running":
        return

    retry_stale_queue = False
    if phase == "queued":
        summary = current_status.get("summary", {}) or {}
        queued_at = parse_iso_datetime(str(summary.get("queuedAt") or ""))
        if queued_at is None:
            logger.warning(
                "Scheduled eval '%s/%s' is queued without queuedAt metadata; waiting for the next timer tick.",
                namespace,
                name,
            )
            return

        worker_job = current_status.get("workerJob", {}) or {}
        job_state = read_job_state(
            str(worker_job.get("name") or ""),
            str(worker_job.get("namespace") or OPERATOR_NAMESPACE),
        )
        queue_age_seconds = (datetime.now(timezone.utc) - queued_at).total_seconds()
        if job_state in {"active", "pending"}:
            return
        if queue_age_seconds < SCHEDULED_EVAL_QUEUE_STALE_SECONDS:
            return

        retry_stale_queue = True
        logger.warning(
            "Scheduled eval '%s/%s' is stuck in phase 'queued' with worker job state '%s'; re-enqueueing.",
            namespace,
            name,
            job_state,
        )

    if not retry_stale_queue and not scheduled_eval_due(schedule, str(current_status.get("lastRun") or "")):
        return

    execute_reconcile(
        lambda: enqueue_eval_job(spec, meta, name, namespace, logger, scheduled=True),
        logger=logger,
        action="schedule-eval",
        resource_kind="AgentEval",
        name=name,
        namespace=namespace,
        meta=meta,
        default_delay=10,
        start_message="Enqueuing scheduled AgentEval run.",
        success_message="Scheduled AgentEval queued successfully.",
        schedule=schedule,
        retryStaleQueue=retry_stale_queue,
        phase=phase,
    )


@kopf.on.field("sandbox.enterprise.ai", "v1alpha1", "agentapprovals", field="status.decision")  # type: ignore[arg-type]
def on_approval_decision(old: str, new: str, name: str, namespace: str, logger: logging.Logger, **kwargs: Any) -> None:
    del kwargs
    if old == "pending" and new in ("approved", "denied"):
        log_operator_event(
            logger,
            logging.INFO,
            "Observed AgentApproval decision change.",
            resource_kind="AgentApproval",
            name=name,
            namespace=namespace,
            action="approval-decision",
            previousDecision=old,
            decision=new,
        )
        custom_api = kubernetes.client.CustomObjectsApi()
        try:
            workflows = custom_api.list_namespaced_custom_object(
                group="sandbox.enterprise.ai",
                version="v1alpha1",
                namespace=namespace,
                plural="agentworkflows",
                label_selector=f"sandbox.enterprise.ai/pending-approval={name}",
            ).get("items", [])
        except kubernetes.client.rest.ApiException:
            workflows = custom_api.list_namespaced_custom_object(
                group="sandbox.enterprise.ai",
                version="v1alpha1",
                namespace=namespace,
                plural="agentworkflows",
            ).get("items", [])

        for workflow in workflows:
            workflow_name = workflow.get("metadata", {}).get("name", "")
            workflow_status = workflow.get("status", {}) or {}
            pending_approval = workflow_status.get("pendingApproval", {}) or {}
            if pending_approval.get("name") != name:
                continue
            if workflow_status.get("phase") != "waiting-approval":
                continue

            workflow_meta = workflow.get("metadata", {}) or {}
            workflow_spec = workflow.get("spec", {}) or {}
            generation = int(workflow_status.get("observedGeneration") or workflow_meta.get("generation", 1))
            run_id = str(workflow_status.get("runId") or "") or None

            if new == "approved":
                job_name = execute_reconcile(
                    lambda _ws=workflow_spec, _wm=workflow_meta, _wn=workflow_name, _ws2=workflow_status, _rid=run_id: enqueue_workflow_job(
                        _ws,
                        _wm,
                        _wn,
                        namespace,
                        logger,
                        current_status=_ws2,
                        run_id=_rid,
                        requeue_reason=f"approval '{name}' was approved",
                    ),
                    logger=logger,
                    action="resume-workflow-after-approval",
                    resource_kind="AgentWorkflow",
                    name=workflow_name,
                    namespace=namespace,
                    meta=workflow_meta,
                    generation=generation,
                    default_delay=10,
                    start_message="Resuming workflow after approval.",
                    success_message="Workflow resumed after approval.",
                    approval=name,
                    decision=new,
                )
                log_operator_event(
                    logger,
                    logging.INFO,
                    "Workflow resumed after approval.",
                    resource_kind="AgentWorkflow",
                    name=workflow_name,
                    namespace=namespace,
                    meta=workflow_meta,
                    generation=generation,
                    action="resume-workflow-after-approval",
                    approval=name,
                    decision=new,
                    workerJob=job_name,
                )
            else:
                current_step = str(workflow_status.get("currentStep", "") or "")
                step_states = workflow_status.get("stepStates", {}) or {}
                if current_step:
                    current_step_state = dict(step_states.get(current_step, {}) or {})
                    current_step_state.update(
                        {
                            "status": "denied",
                            "updatedAt": now_iso(),
                            "completedAt": now_iso(),
                            "failureClass": "approval_denied",
                            "error": f"Approval '{name}' was denied",
                        }
                    )
                    step_states[current_step] = current_step_state

                artifact_ref = workflow_status.get("artifactRef", {}) or {}
                journal_path = str(
                    workflow_status.get("journalRef", {}).get("path")
                    or artifact_ref.get("journalPath")
                    or workflow_journal_path(
                        str(artifact_ref.get("path") or artifact_file_path("workflow", namespace, workflow_name, generation))
                    )
                )
                artifact_pvc_name = str(
                    artifact_ref.get("pvcName")
                    or ensure_worker_artifact_storage("workflow", namespace, workflow_name)
                )
                artifact_path = str(
                    artifact_ref.get("path")
                    or artifact_file_path("workflow", namespace, workflow_name, generation)
                )
                denial_status = {
                    "phase": "failed",
                    "runId": workflow_status.get("runId"),
                    "currentStep": current_step,
                    "observedGeneration": generation,
                    "artifactRef": build_artifact_ref(
                        artifact_pvc_name,
                        artifact_path,
                        generation,
                        journal_path=journal_path,
                    ),
                    "journalRef": build_journal_ref(artifact_pvc_name, journal_path, generation),
                    "summary": {
                        **(workflow_status.get("summary", {}) or {}),
                        "failedAt": now_iso(),
                        "error": f"Approval '{name}' was denied",
                        "updatedAt": now_iso(),
                    },
                    "pendingApproval": {
                        "name": name,
                        "namespace": namespace,
                        "decision": new,
                    },
                    "stepStates": step_states,
                }
                execute_reconcile(
                    lambda _wn=workflow_name, _ds=denial_status: patch_custom_status(
                        "agentworkflows",
                        namespace,
                        _wn,
                        _ds,
                    ),
                    logger=logger,
                    action="deny-workflow-after-approval",
                    resource_kind="AgentWorkflow",
                    name=workflow_name,
                    namespace=namespace,
                    meta=workflow_meta,
                    generation=generation,
                    default_delay=10,
                    start_message="Marking workflow as failed after approval denial.",
                    success_message="Workflow marked failed after approval denial.",
                    approval=name,
                    decision=new,
                    currentStep=current_step,
                )
                safe_record_workflow_state(
                    namespace=namespace,
                    resource_name=workflow_name,
                    generation=generation,
                    run_id=str(workflow_status.get("runId") or ""),
                    phase="failed",
                    spec=workflow_spec,
                    status={
                        "phase": "failed",
                        "runId": workflow_status.get("runId"),
                        "currentStep": current_step,
                        "observedGeneration": generation,
                        "artifactRef": build_artifact_ref(
                            artifact_pvc_name,
                            artifact_path,
                            generation,
                            journal_path=journal_path,
                        ),
                        "journalRef": build_journal_ref(artifact_pvc_name, journal_path, generation),
                        "summary": {
                            **(workflow_status.get("summary", {}) or {}),
                            "failedAt": now_iso(),
                            "error": f"Approval '{name}' was denied",
                            "updatedAt": now_iso(),
                        },
                        "pendingApproval": {
                            "name": name,
                            "namespace": namespace,
                            "decision": new,
                        },
                        "stepStates": step_states,
                    },
                )
