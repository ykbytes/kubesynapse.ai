"""Kubernetes manifest builder functions.

§2.1b of the road-to-prod plan: extract all create_*_manifest functions
and their private helpers from operator/main.py into the builders package.
"""

from __future__ import annotations

import copy
import hashlib
import json
import logging
import time
from typing import Any

import kopf

import kubernetes.client  # type: ignore[import-untyped]
from kubernetes.client.rest import ApiException  # type: ignore[import-untyped]

from config import (
    A2A_ALLOWED_CALLERS_ENV,
    A2A_ALLOWED_TARGETS_ENV,
    A2A_DEFAULT_TIMEOUT_SECONDS,
    A2A_MAX_TIMEOUT_SECONDS_ENV,
    A2A_REQUIRE_HITL_ENV,
    AGENT_ALLOWED_MODELS,
    AGENT_AUTONOMY_ACTION_RETRY_BACKOFF_SECONDS,
    AGENT_AUTONOMY_ACTION_RETRY_LIMIT,
    AGENT_AUTONOMY_CONTINUE_ON_ACTION_ERROR,
    AGENT_AUTONOMY_FAILURE_HISTORY_LIMIT,
    AGENT_CPU_LIMIT,
    AGENT_CPU_REQUEST,
    AGENT_DOOM_LOOP_THRESHOLD,
    AGENT_HITL_MODE,
    AGENT_LOCAL_TOOL_ALLOWED_ROOTS,
    AGENT_LOCAL_TOOL_ALLOWLIST,
    AGENT_LOCAL_TOOL_DISCOVERY_ENABLED,
    AGENT_LOCAL_TOOL_LIST_LIMIT,
    AGENT_LOCAL_TOOL_MAX_ARG_CHARS,
    AGENT_LOCAL_TOOL_MAX_ARGS,
    AGENT_LOCAL_TOOL_MAX_OUTPUT_CHARS,
    AGENT_LOCAL_TOOL_MOUNT_WORKSPACE,
    AGENT_LOCAL_TOOL_TIMEOUT_SECONDS,
    AGENT_MAX_STEPS,
    AGENT_MAX_STEPS_LIMIT,
    AGENT_MEMORY_LIMIT,
    AGENT_MEMORY_REQUEST,
    AGENT_RUNTIME_EXTRA_ENV,
    AGENT_RUNTIME_TIMEOUT_SECONDS,
    AGENT_SKILL_FILES_ENV,
    AGENT_SUPERVISOR_HISTORY_LIMIT,
    AGENT_SUPERVISOR_RESPONSE_CHARS,
    ARTIFACT_MOUNT_PATH,
    CODEX_DEFAULT_PROVIDER,
    CODEX_MCP_SIDECARS_ENV,
    CODEX_RUNTIME_CONFIG_FILES_ENV,
    CODEX_RUNTIME_EXTRA_ENV,
    CODEX_RUNTIME_IMAGE,
    CODEX_RUNTIME_IMAGE_PULL_POLICY,
    DEFAULT_MAX_PARALLEL_STEPS,
    DEFAULT_STORAGE_SIZE,
    GOOSE_DEFAULT_PROVIDER,
    GOOSE_RUNTIME_CONFIG_FILES_ENV,
    GOOSE_RUNTIME_EXTRA_ENV,
    GOOSE_RUNTIME_IMAGE,
    GOOSE_RUNTIME_IMAGE_PULL_POLICY,
    HELM_RELEASE_NAME,
    HITL_NOTIFICATION_WEBHOOK_URL,
    IMAGE_PULL_SECRETS,
    LITELLM_SVC,
    MCP_AUTH_SECRET_NAME,
    MCP_HUB_NAMESPACE,
    MCP_SIDECAR_CATALOG,
    OTEL_ENDPOINT,
    OPEN_SANDBOX_API_KEY_SECRET_KEY,
    OPEN_SANDBOX_API_KEY_SECRET_NAME,
    OPEN_SANDBOX_RUNTIME_ENV,
    OPENCODE_DEFAULT_PROVIDER,
    OPENCODE_MCP_SIDECARS_ENV,
    OPENCODE_RUNTIME_CONFIG_FILES_ENV,
    OPENCODE_RUNTIME_EXTRA_ENV,
    OPENCODE_RUNTIME_IMAGE,
    OPENCODE_RUNTIME_IMAGE_PULL_POLICY,
    OPERATOR_NAMESPACE,
    QDRANT_COLLECTION,
    QDRANT_SVC,
    RUNTIME_IMAGE,
    RUNTIME_IMAGE_PULL_POLICY,
    RUNTIME_SERVICE_ACCOUNT,
    SECRET_NAME,
    SUPPORTED_RUNTIME_KINDS,
    TRUST_BUNDLE_CONFIGMAP_NAME,
    TRUST_BUNDLE_MOUNT_PATH,
    WORKER_ACTIVE_DEADLINE_SECONDS,
    WORKER_CPU_LIMIT,
    WORKER_CPU_REQUEST,
    WORKER_ARTIFACT_SIZE,
    WORKER_ARTIFACT_STORAGE_CLASS,
    WORKER_IMAGE,
    WORKER_IMAGE_PULL_POLICY,
    WORKER_MEMORY_LIMIT,
    WORKER_MEMORY_REQUEST,
    WORKER_SERVICE_ACCOUNT_NAME,
    WORKER_TTL_SECONDS_AFTER_FINISHED,
    serialize_env_value,
)
from utils import (
    merge_goose_config_files,
    parse_agent_a2a_config,
    parse_agent_skills_config,
    parse_goose_config_files,
    parse_policy_a2a_config,
    parse_runtime_config_files,
    workflow_journal_path,
)

from builders.helpers import (
    KUBERNETES_RESOURCE_NAME_PATTERN,
    POD_TEMPLATE_REVISION_ANNOTATION,
    agent_baseline_egress_rules,
    agent_baseline_ingress_peers,
    agent_owner_labels,
    build_pvc_spec,
    hashed_resource_name,
    platform_namespace_selector,
    resolved_api_gateway_internal_url,
    sandbox_name,
    worker_artifact_pvc_name,
    worker_passthrough_env,
)

logger = logging.getLogger("operator.builders")


def trust_bundle_enabled() -> bool:
    """Return True when runtime pods should mount a trust bundle."""
    return bool(TRUST_BUNDLE_CONFIGMAP_NAME and TRUST_BUNDLE_MOUNT_PATH)


def trust_bundle_volume_mount() -> dict[str, Any]:
    """Build the trust bundle file mount used by runtime containers."""
    return {
        "name": "trust-bundle",
        "mountPath": TRUST_BUNDLE_MOUNT_PATH,
        "subPath": "ca-bundle.pem",
        "readOnly": True,
    }


def trust_bundle_volume() -> dict[str, Any]:
    """Build the trust bundle config map volume for runtime pods."""
    return {
        "name": "trust-bundle",
        "configMap": {"name": TRUST_BUNDLE_CONFIGMAP_NAME},
    }


# ---------------------------------------------------------------------------
# Platform-managed env var names (operators inject these; user overrides are
# silently dropped to prevent conflict / privilege escalation).
# ---------------------------------------------------------------------------

PLATFORM_MANAGED_GOOSE_ENV: set[str] = {
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

PLATFORM_MANAGED_CODEX_ENV: set[str] = {
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

PLATFORM_MANAGED_OPENCODE_ENV: set[str] = {
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

PLATFORM_MANAGED_AGENT_ENV: set[str] = {
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


# ---------------------------------------------------------------------------
# Runtime extra env helpers
# ---------------------------------------------------------------------------


def runtime_extra_env_items(
    raw_env: Any,
    *,
    source_env_name: str,
    runtime_name: str,
    platform_managed_names: set[str],
) -> list[dict[str, str]]:
    """Build a filtered list of env vars from user-supplied JSON env overrides."""
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
    """Build extra env items for Goose runtime."""
    return runtime_extra_env_items(
        GOOSE_RUNTIME_EXTRA_ENV,
        source_env_name="GOOSE_RUNTIME_EXTRA_ENV_JSON",
        runtime_name="goose runtime",
        platform_managed_names=PLATFORM_MANAGED_GOOSE_ENV,
    )


def codex_runtime_extra_env_items() -> list[dict[str, str]]:
    """Build extra env items for Codex runtime."""
    return runtime_extra_env_items(
        CODEX_RUNTIME_EXTRA_ENV,
        source_env_name="CODEX_RUNTIME_EXTRA_ENV_JSON",
        runtime_name="codex runtime",
        platform_managed_names=PLATFORM_MANAGED_CODEX_ENV,
    )


def opencode_runtime_extra_env_items() -> list[dict[str, str]]:
    """Build extra env items for OpenCode runtime."""
    return runtime_extra_env_items(
        OPENCODE_RUNTIME_EXTRA_ENV,
        source_env_name="OPENCODE_RUNTIME_EXTRA_ENV_JSON",
        runtime_name="opencode runtime",
        platform_managed_names=PLATFORM_MANAGED_OPENCODE_ENV,
    )


def agent_runtime_extra_env_items() -> list[dict[str, str]]:
    """Build extra env items for LangGraph agent runtime."""
    return runtime_extra_env_items(
        AGENT_RUNTIME_EXTRA_ENV,
        source_env_name="AGENT_RUNTIME_EXTRA_ENV_JSON",
        runtime_name="agent runtime",
        platform_managed_names=PLATFORM_MANAGED_AGENT_ENV,
    )


# ---------------------------------------------------------------------------
# Runtime config file mergers
# ---------------------------------------------------------------------------


def merged_goose_runtime_config_files(spec: dict[str, Any]) -> dict[str, Any]:
    """Merge chart-level and agent-level Goose config files."""
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
    """Merge chart-level and agent-level Codex config files."""
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
    """Merge chart-level and agent-level OpenCode config files."""
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


# ---------------------------------------------------------------------------
# MCP sidecar skill auto-injection
# ---------------------------------------------------------------------------


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
            merged.append(
                {
                    "name": server_name,
                    "image": entry.get("image"),
                    "port": entry.get("port", 8080),
                }
            )
            logger.info("Auto-injected MCP sidecar '%s' from skill frontmatter", server_name)
    return merged


# ---------------------------------------------------------------------------
# Runtime kind resolution & validation
# ---------------------------------------------------------------------------


def resolve_runtime_kind(spec: dict[str, Any]) -> str:
    """Resolve and validate the runtime kind from an AIAgent spec."""
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
    """Validate runtime-specific configuration fields in an AIAgent spec."""
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
            raise kopf.PermanentError(
                "AIAgent.spec.githubConfig.credentialSecretRef is required when githubConfig is provided."
            )

    if runtime_kind == "goose":
        if codex_spec is not None:
            raise kopf.PermanentError("AIAgent.spec.runtime.codex is only supported when spec.runtime.kind is 'codex'.")
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
            raise kopf.PermanentError("AIAgent.spec.runtime.goose is only supported when spec.runtime.kind is 'goose'.")
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
            raise kopf.PermanentError("AIAgent.spec.runtime.goose is only supported when spec.runtime.kind is 'goose'.")
        if codex_spec is not None:
            raise kopf.PermanentError("AIAgent.spec.runtime.codex is only supported when spec.runtime.kind is 'codex'.")
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
        if goose_spec is not None:
            raise kopf.PermanentError("AIAgent.spec.runtime.goose is only supported when spec.runtime.kind is 'goose'.")
        if codex_spec is not None:
            raise kopf.PermanentError("AIAgent.spec.runtime.codex is only supported when spec.runtime.kind is 'codex'.")
        if opencode_spec is not None:
            raise kopf.PermanentError(
                "AIAgent.spec.runtime.opencode is only supported when spec.runtime.kind is 'opencode'."
            )


# ---------------------------------------------------------------------------
# Template revision & signature helpers
# ---------------------------------------------------------------------------


def _build_pod_template_revision(
    spec: dict[str, Any],
    runtime_kind: str,
    policy_name: str | None,
    policy_spec: dict[str, Any] | None,
    mcp_sidecars: list[dict[str, Any]],
) -> str:
    """Compute a deterministic revision hash of the pod template inputs."""
    revision_source = {
        "spec": spec,
        "runtimeKind": runtime_kind,
        "policyName": policy_name,
        "policySpec": policy_spec or {},
        "mcpSidecars": mcp_sidecars,
    }
    serialized = json.dumps(revision_source, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:12]


def _extract_statefulset_storage_request(manifest: dict[str, Any], claim_name: str = "state-volume") -> str | None:
    """Extract the storage size from a StatefulSet's volumeClaimTemplates."""
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
    """Extract a comparable signature from a StatefulSet's pod template."""
    template = (manifest.get("spec") or {}).get("template") or {}
    template_metadata = template.get("metadata") or {}
    template_spec = template.get("spec") or {}

    def port_signature(port: dict[str, Any]) -> dict[str, Any]:
        return {
            "containerPort": port.get("containerPort"),
            "name": port.get("name"),
            "protocol": port.get("protocol") or "TCP",
        }

    def container_signature(container: dict[str, Any]) -> dict[str, Any]:
        # Sort env vars by name to avoid mismatches when K8s reorders them
        env_vars = sorted(
            copy.deepcopy(container.get("env") or []),
            key=lambda e: e.get("name", ""),
        )
        return {
            "name": container.get("name"),
            "image": container.get("image"),
            "ports": [port_signature(port) for port in container.get("ports") or []],
            "env": env_vars,
        }

    return {
        "revision": (template_metadata.get("annotations") or {}).get(POD_TEMPLATE_REVISION_ANNOTATION),
        "containers": [container_signature(container) for container in template_spec.get("containers") or []],
        "initContainers": [container_signature(container) for container in template_spec.get("initContainers") or []],
    }


# ---------------------------------------------------------------------------
# MCP sidecar validation
# ---------------------------------------------------------------------------


def _validate_mcp_sidecars(sidecars: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Validate and normalize an MCP sidecar list from an AIAgent spec."""
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
            raise kopf.PermanentError(f"AIAgent.spec.mcpSidecars[{index}].image is required for sidecar '{raw_name}'.")
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


# ---------------------------------------------------------------------------
# PVC manifests
# ---------------------------------------------------------------------------


def create_worker_artifact_pvc_manifest(kind: str, resource_namespace: str, resource_name: str) -> dict[str, Any]:
    """Build a PVC manifest for worker Job artifacts."""
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


# ---------------------------------------------------------------------------
# Secret manifests
# ---------------------------------------------------------------------------


def create_mcp_auth_secret_manifest(namespace: str) -> dict[str, Any]:
    """Build an MCP auth secret manifest by reading from the hub namespace."""
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

    secret_data: dict[str, str] = source_secret.data or {}  # type: ignore[assignment]
    bearer_token = secret_data.get("bearer-token")
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
        "type": str(getattr(source_secret, "type", None) or "Opaque"),
        "data": {"bearer-token": bearer_token},
    }


# ---------------------------------------------------------------------------
# Service manifests
# ---------------------------------------------------------------------------


def create_agent_service_manifest(name: str, namespace: str) -> dict[str, Any]:
    """Build a ClusterIP Service manifest for an agent."""
    from config import API_PORT

    return {
        "apiVersion": "v1",
        "kind": "Service",
        "metadata": {
            "name": sandbox_name(name),
            "namespace": namespace,
            "labels": {"app": "ai-agent", "agent-name": name, **agent_owner_labels(name)},
        },
        "spec": {
            "selector": {"app": "ai-agent", "agent-name": name},
            "ports": [{"name": "http", "port": API_PORT, "targetPort": "http"}],
        },
    }


# ---------------------------------------------------------------------------
# StatefulSet manifest
# ---------------------------------------------------------------------------


def create_agent_statefulset_manifest(
    name: str,
    namespace: str,
    spec: dict[str, Any],
    policy_name: str | None,
    policy_spec: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a complete StatefulSet manifest for an AIAgent."""
    runtime_kind = resolve_runtime_kind(spec)
    validate_runtime_configuration(runtime_kind, spec)
    model = spec.get("model", "gpt-4")
    mcp_servers = spec.get("mcpServers") or []
    mcp_sidecars = spec.get("mcpSidecars") or []
    enable_gvisor = spec.get("enableGVisor", False)
    system_prompt = spec.get("systemPrompt", "")
    if len(system_prompt) > 32000:
        raise kopf.PermanentError(f"spec.systemPrompt exceeds maximum length (32000 chars, got {len(system_prompt)})")
    skills_config = parse_agent_skills_config(spec.get("skills"), source="AIAgent.spec.skills")
    mcp_sidecars = _auto_inject_mcp_sidecars(mcp_sidecars, skills_config)
    mcp_sidecars = _validate_mcp_sidecars(mcp_sidecars)

    # Git configuration — auto-inject git sidecar and prepare credential env/volumes
    git_config = spec.get("gitConfig") or {}
    github_config = spec.get("githubConfig") or {}
    if github_config and "github" not in mcp_servers:
        mcp_servers = [*mcp_servers, "github"]
    git_agent_env: list[dict[str, Any]] = []
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
            raise kopf.PermanentError("spec.gitConfig.repoUrl must use https://, git@, or ssh:// scheme")
        # Auto-inject git sidecar if not already present
        has_git_sidecar = any(s.get("name") == "git" for s in mcp_sidecars)
        if not has_git_sidecar:
            git_catalog_entry = MCP_SIDECAR_CATALOG.get("git", {})
            mcp_sidecars.append(
                {
                    "name": "git",
                    "image": git_catalog_entry.get("image", "docker.io/yakdhane/mcp-git:latest"),
                    "port": git_catalog_entry.get("port", 8095),
                }
            )
            logger.info("Auto-injected git MCP sidecar for agent '%s' (gitConfig present)", name)

        git_sidecar_env = [
            {"name": "GIT_REPO_URL", "value": git_config.get("repoUrl", "")},
            {"name": "GIT_AUTH_METHOD", "value": git_config.get("authMethod", "")},
        ]
        git_branch = str(git_config.get("branch", "")).strip()
        if git_branch:
            git_sidecar_env.append({"name": "GIT_BRANCH", "value": git_branch})
        cred_secret = git_config.get("credentialSecretRef", "")
        auth_method = git_config.get("authMethod", "")
        if cred_secret and auth_method == "token":
            git_sidecar_env.append(
                {
                    "name": "GIT_TOKEN",
                    "valueFrom": {"secretKeyRef": {"name": cred_secret, "key": "token", "optional": True}},
                }
            )
        elif cred_secret and auth_method == "basic":
            git_sidecar_env.extend(
                [
                    {
                        "name": "GIT_USERNAME",
                        "valueFrom": {"secretKeyRef": {"name": cred_secret, "key": "username", "optional": True}},
                    },
                    {
                        "name": "GIT_PASSWORD",
                        "valueFrom": {"secretKeyRef": {"name": cred_secret, "key": "password", "optional": True}},
                    },
                ]
            )
        elif cred_secret and auth_method == "ssh":
            ssh_vol_name = "git-ssh-key"
            git_volumes.append(
                {
                    "name": ssh_vol_name,
                    "secret": {
                        "secretName": cred_secret,
                        "items": [{"key": "ssh_private_key", "path": "id_rsa"}],
                        "defaultMode": 0o400,
                    },
                }
            )
            git_volume_mounts.append({"name": ssh_vol_name, "mountPath": "/home/mcpuser/.ssh", "readOnly": True})
            git_sidecar_env.append({"name": "GIT_SSH_KEY_PATH", "value": "/home/mcpuser/.ssh/id_rsa"})

        # Also inject git credentials into the main agent container so that
        # bash-based git operations (git push, git pull) work with auth.
        git_agent_env: list[dict[str, Any]] = [
            {"name": "GIT_REPO_URL", "value": git_config.get("repoUrl", "")},
            {"name": "GIT_AUTH_METHOD", "value": git_config.get("authMethod", "")},
        ]
        if git_branch:
            git_agent_env.append({"name": "GIT_BRANCH", "value": git_branch})
        if cred_secret and auth_method == "token":
            git_agent_env.append(
                {
                    "name": "GIT_TOKEN",
                    "valueFrom": {"secretKeyRef": {"name": cred_secret, "key": "token", "optional": True}},
                }
            )
        elif cred_secret and auth_method == "basic":
            git_agent_env.extend(
                [
                    {
                        "name": "GIT_USERNAME",
                        "valueFrom": {"secretKeyRef": {"name": cred_secret, "key": "username", "optional": True}},
                    },
                    {
                        "name": "GIT_PASSWORD",
                        "valueFrom": {"secretKeyRef": {"name": cred_secret, "key": "password", "optional": True}},
                    },
                ]
            )

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
    # Inject git credentials into the main agent container (must happen
    # AFTER the main env list is created above).
    if git_config.get("repoUrl") and git_agent_env:
        env.extend(git_agent_env)

    volume_mounts = [
        {"name": "tmp-volume", "mountPath": "/tmp"},
        {"name": "state-volume", "mountPath": "/app/state"},
    ]
    volumes: list[dict[str, Any]] = [{"name": "tmp-volume", "emptyDir": {"sizeLimit": "1Gi"}}]
    if trust_bundle_enabled():
        volume_mounts.append(trust_bundle_volume_mount())
        volumes.append(trust_bundle_volume())

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
                {"name": "LITELLM_HOST", "value": f"http://{LITELLM_SVC}.{OPERATOR_NAMESPACE}.svc.cluster.local:4000"},
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
                {"name": "LITELLM_HOST", "value": f"http://{LITELLM_SVC}.{OPERATOR_NAMESPACE}.svc.cluster.local:4000"},
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
                {"name": "LITELLM_HOST", "value": f"http://{LITELLM_SVC}.{OPERATOR_NAMESPACE}.svc.cluster.local:4000"},
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
                {
                    "name": "LITELLM_API_BASE",
                    "value": f"http://{LITELLM_SVC}.{OPERATOR_NAMESPACE}.svc.cluster.local:4000",
                },
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
        env.append(
            {
                "name": "MCP_BEARER_TOKEN",
                "valueFrom": {
                    "secretKeyRef": {
                        "name": MCP_AUTH_SECRET_NAME,
                        "key": "bearer-token",
                        "optional": not require_mcp_bearer_token,
                    }
                },
            }
        )
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
            env.append(
                {
                    "name": "OPEN_SANDBOX_API_KEY",
                    "valueFrom": {
                        "secretKeyRef": {
                            "name": OPEN_SANDBOX_API_KEY_SECRET_NAME,
                            "key": OPEN_SANDBOX_API_KEY_SECRET_KEY,
                            "optional": True,
                        }
                    },
                }
            )
        env.extend(agent_runtime_extra_env_items())

    init_volume_mounts = [{"name": "state-volume", "mountPath": "/app/state"}]
    if trust_bundle_enabled():
        init_volume_mounts.append(trust_bundle_volume_mount())

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
            "volumeMounts": init_volume_mounts,
        }
    ]

    from config import API_PORT as _API_PORT

    agent_container = {
        "name": "agent-runtime",
        "image": agent_image,
        "imagePullPolicy": agent_image_pull_policy,
        "securityContext": container_security_context,
        "ports": [{"containerPort": _API_PORT, "name": "http", "protocol": "TCP"}],
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
            # Git sidecar needs access to the workspace so it can clone repos
            # into /workspace and commit/push files the agent created there.
            if sidecar_name == "git":
                sidecar_env.append({"name": "MCP_WORK_DIR", "value": "/workspace"})
                sidecar_vol_mounts.append({"name": "workspace-volume", "mountPath": "/workspace"})
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
            "labels": {"app": "ai-agent", "agent-name": name, "runtime-kind": runtime_kind, **agent_owner_labels(name)},
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
                    "labels": {
                        "app": "ai-agent",
                        "agent-name": name,
                        "runtime-kind": runtime_kind,
                        **agent_owner_labels(name),
                    },
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


# ---------------------------------------------------------------------------
# Network policy manifests
# ---------------------------------------------------------------------------


def create_mcp_network_policy_manifest(name: str, namespace: str, allowed_mcp_types: list[str]) -> dict[str, Any]:
    """Build a NetworkPolicy restricting MCP egress to allowed server types."""
    egress_rules: list[dict[str, Any]] = agent_baseline_egress_rules()
    for mcp_type in allowed_mcp_types:
        egress_rules.append(
            {
                "to": [
                    {
                        "namespaceSelector": {"matchLabels": {"sandbox.enterprise.ai/mcp-hub": "true"}},
                        "podSelector": {"matchLabels": {"mcp.sandbox.enterprise.ai/type": mcp_type}},
                    }
                ],
                "ports": [{"protocol": "TCP", "port": 8000}],
            }
        )

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
                **agent_owner_labels(name),
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
    """Build a NetworkPolicy allowing A2A egress to specific target agents."""
    from config import API_PORT as _API_PORT

    egress_rules: list[dict[str, Any]] = []
    for target in allowed_targets:
        egress_rules.append(
            {
                "to": [
                    {
                        "namespaceSelector": {"matchLabels": {"kubernetes.io/metadata.name": target["namespace"]}},
                        "podSelector": {"matchLabels": {"app": "ai-agent", "agent-name": target["name"]}},
                    }
                ],
                "ports": [{"protocol": "TCP", "port": _API_PORT}],
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
                **agent_owner_labels(name),
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
    """Build a NetworkPolicy allowing A2A ingress from specific caller agents."""
    from config import API_PORT as _API_PORT

    allowed_sources: list[dict[str, Any]] = agent_baseline_ingress_peers()
    for caller in allowed_callers:
        allowed_sources.append(
            {
                "namespaceSelector": {"matchLabels": {"kubernetes.io/metadata.name": caller["namespace"]}},
                "podSelector": {"matchLabels": {"app": "ai-agent", "agent-name": caller["name"]}},
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
                **agent_owner_labels(name),
            },
        },
        "spec": {
            "podSelector": {"matchLabels": {"app": "ai-agent", "agent-name": name}},
            "policyTypes": ["Ingress"],
            "ingress": [{"from": allowed_sources, "ports": [{"protocol": "TCP", "port": _API_PORT}]}],
        },
    }


# ---------------------------------------------------------------------------
# Worker Job manifest
# ---------------------------------------------------------------------------


def _worker_git_env(git_config: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Build env var entries for git config in worker job containers."""
    if not git_config:
        return []
    items: list[dict[str, Any]] = []
    repo_url = str(git_config.get("repoUrl", "") or "").strip()
    if repo_url:
        items.append({"name": "GIT_REPO_URL", "value": repo_url})
    auth_method = str(git_config.get("authMethod", "") or "").strip()
    if auth_method:
        items.append({"name": "GIT_AUTH_METHOD", "value": auth_method})
    branch = str(git_config.get("branch", "") or "").strip()
    if branch:
        items.append({"name": "GIT_BRANCH", "value": branch})
    cred_secret = str(git_config.get("credentialSecretRef", "") or "").strip()
    if cred_secret and auth_method == "token":
        items.append(
            {
                "name": "GIT_TOKEN",
                "valueFrom": {"secretKeyRef": {"name": cred_secret, "key": "token", "optional": True}},
            }
        )
    elif cred_secret and auth_method == "basic":
        items.extend(
            [
                {
                    "name": "GIT_USERNAME",
                    "valueFrom": {"secretKeyRef": {"name": cred_secret, "key": "username", "optional": True}},
                },
                {
                    "name": "GIT_PASSWORD",
                    "valueFrom": {"secretKeyRef": {"name": cred_secret, "key": "password", "optional": True}},
                },
            ]
        )
    return items


def create_worker_job_manifest(
    kind: str,
    resource_namespace: str,
    resource_name: str,
    generation: int,
    artifact_pvc_name: str,
    artifact_path: str,
    *,
    run_id: str | None = None,
    git_config: dict[str, Any] | None = None,
    max_parallel_steps: int | None = None,
) -> dict[str, Any]:
    """Build a Kubernetes Job manifest for a workflow/eval worker."""
    timestamp = int(time.time())
    job_name = hashed_resource_name(kind, resource_namespace, resource_name, suffix=f"{generation}-{timestamp}")
    artifact_journal_path = workflow_journal_path(artifact_path)
    pod_security_context = {
        "runAsUser": 999,
        "runAsGroup": 37,
        "fsGroup": 37,
        "seccompProfile": {"type": "RuntimeDefault"},
    }
    container_security_context = {
        "runAsNonRoot": True,
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
                    "initContainers": [
                        {
                            "name": "init-artifacts",
                            "image": WORKER_IMAGE,
                            "imagePullPolicy": WORKER_IMAGE_PULL_POLICY,
                            "command": ["sh", "-c", "chown -R 999:37 /artifacts && chmod -R 775 /artifacts"],
                            "securityContext": {
                                "runAsUser": 0,
                                "runAsNonRoot": False,
                                "allowPrivilegeEscalation": False,
                                "capabilities": {"drop": ["ALL"], "add": ["CHOWN", "FOWNER"]},
                            },
                            "volumeMounts": [
                                {"name": "artifacts", "mountPath": ARTIFACT_MOUNT_PATH},
                            ],
                        }
                    ],
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
                                {
                                    "name": "MAX_PARALLEL_STEPS",
                                    "value": str(max_parallel_steps or DEFAULT_MAX_PARALLEL_STEPS),
                                },
                                *worker_passthrough_env(),
                                *_worker_git_env(git_config),
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
