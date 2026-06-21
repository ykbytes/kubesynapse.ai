"""Kubernetes manifest builder functions.

§2.1b of the road-to-prod plan: extract all create_*_manifest functions
and their private helpers from operator/main.py into the builders package.
"""

from __future__ import annotations

import base64
import copy
import hashlib
import json
import logging
import time
from typing import Any

import kopf
import kubernetes.client  # type: ignore[import-untyped]
from config import (
    A2A_ALLOWED_CALLERS_ENV,
    A2A_ALLOWED_TARGETS_ENV,
    A2A_DEFAULT_TIMEOUT_SECONDS,
    A2A_MAX_TIMEOUT_SECONDS_ENV,
    A2A_REQUIRE_HITL_ENV,
    AGENT_CPU_LIMIT,
    AGENT_CPU_REQUEST,
    AGENT_HITL_MODE,
    AGENT_MEMORY_LIMIT,
    AGENT_MEMORY_REQUEST,
    AGENT_RUNTIME_TIMEOUT_SECONDS,
    AGENT_SKILL_FILES_ENV,
    ARTIFACT_MOUNT_PATH,
    CREDENTIAL_PROXY_ENABLED,
    CREDENTIAL_PROXY_IMAGE,
    CREDENTIAL_PROXY_IMAGE_PULL_POLICY,
    DEFAULT_MAX_PARALLEL_STEPS,
    DEFAULT_STORAGE_SIZE,
    HELM_RELEASE_NAME,
    HITL_NOTIFICATION_WEBHOOK_URL,
    IMAGE_PULL_SECRETS,
    LITELLM_SVC,
    MCP_AUTH_SECRET_NAME,
    MCP_HUB_NAMESPACE,
    MCP_SIDECAR_CATALOG,
    MISTRAL_VIBE_RUNTIME_IMAGE,
    MISTRAL_VIBE_RUNTIME_IMAGE_PULL_POLICY,
    OPA_SIDECAR_IMAGE,
    OPA_SIDECAR_PORT,
    OPA_SIDECAR_RESOURCES,
    OPENCODE_DEFAULT_PROVIDER,
    OPENCODE_IMMUTABLE_CONFIG,
    OPENCODE_MCP_CONNECTIONS_ENV,
    OPENCODE_MCP_SIDECARS_ENV,
    OPENCODE_RUNTIME_CONFIG_FILES_ENV,
    OPENCODE_RUNTIME_EXTRA_ENV,
    OPENCODE_RUNTIME_IMAGE,
    OPENCODE_RUNTIME_IMAGE_PULL_POLICY,
    OPERATOR_NAMESPACE,
    OTEL_ENDPOINT,
    PI_DEFAULT_MODEL,
    PI_DEFAULT_PROVIDER,
    PI_DEFAULT_THINKING_LEVEL,
    PI_IMMUTABLE_CONFIG,
    PI_RUNTIME_IMAGE,
    PI_RUNTIME_IMAGE_PULL_POLICY,
    PROVIDER_REGISTRY_CONFIGMAP_NAME,
    RUNTIME_AUTH_REQUIRED_OVERRIDE,
    RUNTIME_SERVICE_ACCOUNT,
    SECRET_NAME,
    SUPPORTED_RUNTIME_KINDS,
    WORKER_ACTIVE_DEADLINE_SECONDS,
    WORKER_ARTIFACT_SIZE,
    WORKER_ARTIFACT_STORAGE_CLASS,
    WORKER_CPU_LIMIT,
    WORKER_CPU_REQUEST,
    WORKER_IMAGE,
    WORKER_IMAGE_PULL_POLICY,
    WORKER_MEMORY_LIMIT,
    WORKER_MEMORY_REQUEST,
    WORKER_SERVICE_ACCOUNT_NAME,
    WORKER_TTL_SECONDS_AFTER_FINISHED,
    serialize_env_value,
)
from kubernetes.client.rest import ApiException  # type: ignore[import-untyped]

from builders.helpers import (
    KUBERNETES_RESOURCE_NAME_PATTERN,
    POD_TEMPLATE_REVISION_ANNOTATION,
    agent_baseline_egress_rules,
    agent_baseline_ingress_peers,
    agent_owner_labels,
    build_pvc_spec,
    hashed_resource_name,
    resolved_api_gateway_internal_url,
    sandbox_name,
    worker_artifact_pvc_name,
    worker_passthrough_env,
)
from utils import (
    merge_runtime_config_files,
    parse_agent_a2a_config,
    parse_agent_skills_config,
    parse_policy_a2a_config,
    parse_runtime_config_files,
    workflow_journal_path,
)

logger = logging.getLogger("operator.builders")


def _resolve_opencode_model_ref(raw_model: str) -> tuple[str, str]:
    """Split a model reference into (provider_id, model_id).

    Examples:
        "opencode-go/kimi-k2.6" -> ("opencode-go", "kimi-k2.6")
        "gpt-4"                -> (OPENCODE_DEFAULT_PROVIDER, "gpt-4")
    """
    cleaned = str(raw_model or "").strip()
    if not cleaned:
        raise kopf.PermanentError("AIAgent.spec.model must be explicitly set.")
    if "/" in cleaned:
        provider_id, model_id = cleaned.split("/", 1)
        provider_id = provider_id.strip()
        model_id = model_id.strip()
        if not model_id:
            raise kopf.PermanentError("AIAgent.spec.model must include a non-empty model ID.")
        if not provider_id:
            return (OPENCODE_DEFAULT_PROVIDER, model_id)
        return (provider_id, model_id)
    return (OPENCODE_DEFAULT_PROVIDER, cleaned)


def resolve_agent_container_resources(spec: dict[str, Any]) -> dict[str, dict[str, str]]:
    """Resolve per-agent resource overrides with operator defaults as fallback."""

    def resolve_quantity(value: Any, fallback: str) -> str:
        quantity = str(value or "").strip()
        return quantity or fallback

    resources_spec = spec.get("resources") or {}
    if not isinstance(resources_spec, dict):
        resources_spec = {}
    requests_spec = resources_spec.get("requests") or {}
    if not isinstance(requests_spec, dict):
        requests_spec = {}
    limits_spec = resources_spec.get("limits") or {}
    if not isinstance(limits_spec, dict):
        limits_spec = {}

    return {
        "requests": {
            "cpu": resolve_quantity(requests_spec.get("cpu"), AGENT_CPU_REQUEST),
            "memory": resolve_quantity(requests_spec.get("memory"), AGENT_MEMORY_REQUEST),
        },
        "limits": {
            "cpu": resolve_quantity(limits_spec.get("cpu"), AGENT_CPU_LIMIT),
            "memory": resolve_quantity(limits_spec.get("memory"), AGENT_MEMORY_LIMIT),
        },
    }


# ---------------------------------------------------------------------------
# Platform-managed env var names (operators inject these; user overrides are
# silently dropped to prevent conflict / privilege escalation).
# ---------------------------------------------------------------------------

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
    "OPENCODE_MODEL_OUTPUT_LIMIT",
    "OPENCODE_SERVER_PASSWORD",
    "RUNTIME_AUTH_REQUIRED",
    "RUNTIME_BEARER_TOKEN",
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
}


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


def opencode_runtime_extra_env_items() -> list[dict[str, str]]:
    """Build extra env items for OpenCode runtime."""
    return runtime_extra_env_items(
        OPENCODE_RUNTIME_EXTRA_ENV,
        source_env_name="OPENCODE_RUNTIME_EXTRA_ENV_JSON",
        runtime_name="opencode runtime",
        platform_managed_names=PLATFORM_MANAGED_OPENCODE_ENV,
    )


def opencode_runtime_admin_env_items() -> list[dict[str, str]]:
    """Inject admin-controlled OpenCode env vars into the agent pod.

    §security-P1: These vars come from the chart's opencodeRuntime.admin
    section and are applied AFTER user-provided env vars. They are NOT
    filtered by PLATFORM_MANAGED_OPENCODE_ENV — the platform admin
    always has the final word on security-critical runtime behaviour.

    Admin vars include:
      - OPENCODE_DISABLE_DEFAULT_PLUGINS
      - OPENCODE_ADMIN_PROVIDER_OVERRIDE_JSON
      - OPENCODE_ADMIN_MODEL_OVERRIDE_JSON
      - OPENCODE_PLUGIN_LIST_JSON
    """
    from config import get_json_env

    raw = get_json_env("OPENCODE_ADMIN_OVERRIDES_JSON", {})
    if not isinstance(raw, dict):
        return []

    items: list[dict[str, str]] = []
    for name, value in sorted(raw.items(), key=lambda item: str(item[0])):
        name_str = str(name).strip()
        if not name_str or value is None:
            continue
        items.append({"name": name_str, "value": serialize_env_value(value)})
    return items


def _resolve_policy_model_output_limit(policy_spec: dict[str, Any] | None) -> int | None:
    """Return a policy-defined max output token limit when one is configured."""
    output_guardrails = (policy_spec or {}).get("outputGuardrails")
    if not isinstance(output_guardrails, dict):
        return None

    raw_limit = output_guardrails.get("maxOutputTokens", output_guardrails.get("max_output_tokens"))
    if raw_limit in (None, ""):
        return None

    try:
        limit = int(raw_limit)
    except (TypeError, ValueError):
        logger.warning("Ignoring invalid AgentPolicy outputGuardrails.maxOutputTokens=%r", raw_limit)
        return None

    if limit <= 0:
        logger.warning("Ignoring non-positive AgentPolicy outputGuardrails.maxOutputTokens=%r", raw_limit)
        return None

    return limit


# ---------------------------------------------------------------------------
# Admin Tool Ceiling & Policy Attestation
# ---------------------------------------------------------------------------

# Permission strength ordering for ceiling enforcement
_PERMISSION_STRENGTH: dict[str, int] = {"deny": 0, "ask": 1, "allow": 2}
_VALID_TOOL_IDS: frozenset[str] = frozenset({
    "bash", "edit", "write", "read", "glob", "grep", "webfetch", "websearch",
    "task", "todowrite", "skill", "question", "webbrowse", "external_directory",
})


def _resolve_admin_tool_ceiling(policy_spec: dict[str, Any] | None) -> dict[str, str]:
    """Extract and validate the adminToolCeiling from a policy spec.

    Returns a dict mapping tool IDs to their ceiling permission level.
    Only returns entries that are valid (known tool IDs, valid actions).
    """
    if not policy_spec:
        return {}
    tool_policy = policy_spec.get("toolPolicy")
    if not isinstance(tool_policy, dict):
        return {}
    ceiling = tool_policy.get("adminToolCeiling")
    if not isinstance(ceiling, dict):
        return {}

    validated: dict[str, str] = {}
    for tool_id, action in ceiling.items():
        tool_id_str = str(tool_id).strip().lower()
        action_str = str(action).strip().lower()
        if tool_id_str not in _VALID_TOOL_IDS:
            logger.warning(
                "Ignoring unknown tool ID '%s' in adminToolCeiling", tool_id_str
            )
            continue
        if action_str not in _PERMISSION_STRENGTH:
            logger.warning(
                "Ignoring invalid action '%s' for tool '%s' in adminToolCeiling",
                action_str, tool_id_str,
            )
            continue
        validated[tool_id_str] = action_str

    return validated


def _compute_policy_hash(
    policy_name: str | None, policy_spec: dict[str, Any] | None
) -> str:
    """Compute a deterministic hash of the policy spec for runtime attestation.

    The hash is included in the runtime pod's env so that the gateway can
    verify the agent is running with the expected policy configuration.
    """
    import hashlib

    if not policy_name or not policy_spec:
        return ""
    # Create a canonical JSON representation for hashing
    canonical = json.dumps(policy_spec, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha256(f"{policy_name}:{canonical}".encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Runtime config file mergers
# ---------------------------------------------------------------------------


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
        return merge_runtime_config_files(
            (
                OPENCODE_RUNTIME_EXTRA_ENV.get(OPENCODE_RUNTIME_CONFIG_FILES_ENV),
                f"OPENCODE_RUNTIME_EXTRA_ENV_JSON.{OPENCODE_RUNTIME_CONFIG_FILES_ENV}",
            ),
            (agent_config_files, "AIAgent.spec.runtime.opencode.configFiles"),
        )
    except ValueError as exc:
        raise kopf.PermanentError(str(exc)) from exc


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
                except Exception as exc:
                    logger.debug("Failed to parse YAML frontmatter for MCP servers: %s", exc, exc_info=True)
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

    existing_names = {
        str(value).strip()
        for sidecar in explicit_sidecars
        for value in (sidecar.get("name"), sidecar.get("serverId"), sidecar.get("server_id"))
        if str(value or "").strip()
    }
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
                    "port": entry.get("port", 8097),
                }
            )
            logger.info("Auto-injected MCP sidecar '%s' from skill frontmatter", server_name)
    return merged


# ---------------------------------------------------------------------------
# Runtime kind resolution & validation
# ---------------------------------------------------------------------------


def resolve_runtime_kind(spec: dict[str, Any]) -> str:
    """Resolve and validate the runtime kind from an AIAgent spec."""
    runtime_spec = spec.get("runtime")
    if not isinstance(runtime_spec, dict):
        raise kopf.PermanentError(
            "AIAgent.spec.runtime.kind must be explicitly set to 'opencode', 'pi', or 'mistral-vibe'."
        )

    runtime_kind = str(runtime_spec.get("kind") or "").strip().lower()
    if not runtime_kind:
        raise kopf.PermanentError(
            "AIAgent.spec.runtime.kind must be explicitly set to 'opencode', 'pi', or 'mistral-vibe'."
        )
    if runtime_kind not in SUPPORTED_RUNTIME_KINDS:
        raise kopf.PermanentError(
            f"Unsupported AIAgent.spec.runtime.kind '{runtime_kind}'. "
            f"Supported: {', '.join(sorted(SUPPORTED_RUNTIME_KINDS))}"
        )
    return runtime_kind


def validate_runtime_configuration(runtime_kind: str, spec: dict[str, Any]) -> None:
    """Validate runtime-specific configuration fields in an AIAgent spec."""
    runtime_spec = spec.get("runtime") or {}
    goose_spec = runtime_spec.get("goose") if isinstance(runtime_spec, dict) else None
    codex_spec = runtime_spec.get("codex") if isinstance(runtime_spec, dict) else None
    opencode_spec = runtime_spec.get("opencode") if isinstance(runtime_spec, dict) else None
    vibe_spec = runtime_spec.get("mistralVibe") if isinstance(runtime_spec, dict) else None
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
    if runtime_kind not in SUPPORTED_RUNTIME_KINDS:
        raise kopf.PermanentError(
            f"Unsupported AIAgent.spec.runtime.kind '{runtime_kind}'. "
            f"Supported: {', '.join(sorted(SUPPORTED_RUNTIME_KINDS))}"
        )

    if goose_spec is not None:
        raise kopf.PermanentError("AIAgent.spec.runtime.goose is no longer supported. Use spec.runtime.opencode instead.")
    if codex_spec is not None:
        raise kopf.PermanentError("AIAgent.spec.runtime.codex is no longer supported. Use spec.runtime.opencode instead.")
    if opencode_spec is not None and not isinstance(opencode_spec, dict):
        raise kopf.PermanentError("AIAgent.spec.runtime.opencode must be an object when provided.")
    if vibe_spec is not None and not isinstance(vibe_spec, dict):
        raise kopf.PermanentError("AIAgent.spec.runtime.mistralVibe must be an object when provided.")
    try:
        parse_runtime_config_files(
            (opencode_spec or {}).get("configFiles") if isinstance(opencode_spec, dict) else None,
            source="AIAgent.spec.runtime.opencode.configFiles",
        )
    except ValueError as exc:
        raise kopf.PermanentError(str(exc)) from exc
    if runtime_kind == "opencode" and spec.get("githubConfig"):
        raise kopf.PermanentError(
            "OpenCode runtime does not support spec.githubConfig in the OpenCode-only build. Use sidecar-based GitHub MCP credentials instead."
        )

    # §security-P0: Reject dangerous runtime config that could enable RCE.
    # Block !-prefix env values (Pi config RCE via shell execution).
    pi_runtime_spec = (spec.get("runtime") or {}).get("pi") if isinstance(spec.get("runtime"), dict) else None
    if isinstance(pi_runtime_spec, dict):
        pi_env_spec = pi_runtime_spec.get("env")
        if isinstance(pi_env_spec, dict):
            for _ek, _ev in pi_env_spec.items():
                if isinstance(_ev, str) and _ev.startswith("!"):
                    raise kopf.PermanentError(
                        f"AIAgent spec.runtime.pi.env.{_ek} starts with '!' — "
                        f"this enables shell execution in Pi config and is a security risk."
                    )

    # Block plugin arrays in OpenCode configFiles (config-driven RCE).
    opencode_runtime_spec = (spec.get("runtime") or {}).get("opencode") if isinstance(spec.get("runtime"), dict) else None
    if isinstance(opencode_runtime_spec, dict):
        opencode_cf = opencode_runtime_spec.get("configFiles")
        if isinstance(opencode_cf, dict):
            for _cf_path, _cf_content in opencode_cf.items():
                if isinstance(_cf_content, str) and '"plugin"' in _cf_content:
                    import re as _re

                    if _re.search(r'"plugin"\s*:\s*\[', _cf_content) or _re.search(r"'plugin'\s*:\s*\[", _cf_content):
                        _has_nonempty = _re.search(r'"plugin"\s*:\s*\[.+\]', _cf_content) or _re.search(
                            r"'plugin'\s*:\s*\[.+\]", _cf_content
                        )
                        if _has_nonempty:
                            raise kopf.PermanentError(
                                f"AIAgent spec.runtime.opencode.configFiles contains non-empty 'plugin' "
                                f"array in '{_cf_path}' — this enables config-driven RCE and is blocked."
                            )

                # §security-P0: Block local/command-based MCP servers in OpenCode
                # configFiles. OpenCode supports `mcp: {name: {type: "local",
                # command: [...]}}` which spawns an arbitrary subprocess — a direct
                # RCE vector. Only remote (HTTP) MCP servers are permitted; those
                # are provisioned by the operator via MCPConnection resources.
                _cf_obj: Any = None
                if isinstance(_cf_content, dict):
                    _cf_obj = _cf_content
                elif isinstance(_cf_content, str) and '"mcp"' in _cf_content:
                    try:
                        _cf_obj = json.loads(_cf_content)
                    except (json.JSONDecodeError, ValueError):
                        _cf_obj = None
                if isinstance(_cf_obj, dict):
                    _mcp_block = _cf_obj.get("mcp")
                    if isinstance(_mcp_block, dict):
                        for _srv_name, _srv in _mcp_block.items():
                            if not isinstance(_srv, dict):
                                continue
                            _srv_type = str(_srv.get("type") or "").strip().lower()
                            if _srv_type == "local" or "command" in _srv or "args" in _srv:
                                raise kopf.PermanentError(
                                    f"AIAgent spec.runtime.opencode.configFiles defines a local/command-based "
                                    f"MCP server '{_srv_name}' in '{_cf_path}' — this enables config-driven RCE "
                                    f"and is blocked. Use an MCPConnection (remote HTTP) instead."
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


def _build_pi_pod_template_revision(
    spec: dict[str, Any],
    policy_name: str | None,
    policy_spec: dict[str, Any] | None,
    mcp_sidecars: list[dict[str, Any]],
) -> str:
    """Compute a deterministic revision hash for pi runtime pods.

    Excludes model, provider, and thinkingLevel from the hash so that
    changes to these fields do not trigger a pod restart.  The bridge
    handles dynamic model switching at invoke time.
    """
    # Deep-copy spec so we can strip model-related fields without mutating.
    # Convert to plain dicts recursively since kopf Spec/Body objects don't
    # support .pop().  json round-trip guarantees all nested objects are plain.
    import json
    stripped = json.loads(json.dumps(dict(spec)))

    # Remove top-level model (used as fallback by the operator)
    stripped.pop("model", None)

    # Remove pi-specific model/provider/thinkingLevel
    runtime = stripped.get("runtime") or {}
    pi_spec = runtime.get("pi") or {}
    pi_spec.pop("model", None)
    pi_spec.pop("provider", None)
    pi_spec.pop("thinkingLevel", None)
    if runtime.get("pi") is not None:
        runtime["pi"] = pi_spec
    if stripped.get("runtime") is not None:
        stripped["runtime"] = runtime

    revision_source = {
        "spec": stripped,
        "runtimeKind": "pi",
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

                    f"AIAgent.spec.mcpSidecars[{index}].name '{raw_name}' is invalid. "
                    "Use lowercase letters, numbers, and hyphens only."

            )

        raw_image = str(sidecar.get("image") or "").strip()
        if not raw_image:
            raise kopf.PermanentError(f"AIAgent.spec.mcpSidecars[{index}].image is required for sidecar '{raw_name}'.")
        # Reject images with embedded credentials or shell metacharacters
        if "@" in raw_image.split("/")[0] or any(ch in raw_image for ch in (";", "&", "|", "$", "`", "\n")):
            raise kopf.PermanentError(
                f"AIAgent.spec.mcpSidecars[{index}].image contains invalid characters for sidecar '{raw_name}'."
            )

        raw_port = sidecar.get("port", 8097)
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

                    f"AIAgent.spec.mcpSidecars[{index}].name '{raw_name}' duplicates "
                    f"AIAgent.spec.mcpSidecars[{previous_name_index}].name."

            )
        previous_port_index = seen_ports.get(port)
        if previous_port_index is not None:
            raise kopf.PermanentError(

                    f"AIAgent.spec.mcpSidecars[{index}].port {port} duplicates "
                    f"AIAgent.spec.mcpSidecars[{previous_port_index}].port."

            )

        normalized_sidecar: dict[str, Any] = {"name": raw_name, "image": raw_image, "port": port}
        extra_env = sidecar.get("env")
        if isinstance(extra_env, list):
            normalized_sidecar["env"] = copy.deepcopy(extra_env)
        endpoint_path = str(sidecar.get("endpointPath") or sidecar.get("endpoint_path") or "").strip()
        if endpoint_path:
            normalized_sidecar["endpointPath"] = endpoint_path
        server_id = str(sidecar.get("serverId") or sidecar.get("server_id") or "").strip()
        if server_id:
            normalized_sidecar["serverId"] = server_id

        seen_names[raw_name] = index
        seen_ports[port] = index
        normalized_sidecars.append(normalized_sidecar)

    return normalized_sidecars


def _extract_structured_mcp_sidecars(mcp_connections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sidecars: list[dict[str, Any]] = []
    for connection in mcp_connections:
        if not isinstance(connection, dict):
            continue
        runtime = connection.get("runtime") if isinstance(connection.get("runtime"), dict) else {}
        sidecar = runtime.get("sidecar") if isinstance(runtime.get("sidecar"), dict) else None
        if not sidecar:
            continue
        spec = {
            "name": str(sidecar.get("name") or connection.get("slug") or connection.get("name") or "sidecar").strip(),
            "image": str(sidecar.get("image") or "").strip(),
            "port": sidecar.get("port", 8097),
            "env": copy.deepcopy(sidecar.get("env") or []),
            "endpointPath": str(sidecar.get("endpointPath") or "/mcp").strip() or "/mcp",
            "serverId": str(connection.get("serverId") or "").strip(),
        }
        sidecars.append(spec)
    return sidecars


def _build_mcp_runtime_secret_env_bindings(mcp_connections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    env_by_name: dict[str, dict[str, Any]] = {}
    for connection in mcp_connections:
        if not isinstance(connection, dict):
            continue
        runtime = connection.get("runtime") if isinstance(connection.get("runtime"), dict) else {}
        for header in runtime.get("headers") or []:
            if not isinstance(header, dict):
                continue
            env_var = str(header.get("envVar") or "").strip()
            secret_key_ref = header.get("secretKeyRef") if isinstance(header.get("secretKeyRef"), dict) else None
            if not env_var or secret_key_ref is None or env_var in env_by_name:
                continue
            env_by_name[env_var] = {"name": env_var, "valueFrom": {"secretKeyRef": copy.deepcopy(secret_key_ref)}}
    return list(env_by_name.values())


def _build_sidecar_env_items(sidecar_spec: dict[str, Any]) -> list[dict[str, Any]]:
    env_items: list[dict[str, Any]] = [{"name": "MCP_LISTEN_PORT", "value": str(sidecar_spec.get("port", 8080))}]
    for item in sidecar_spec.get("env") or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        secret_key_ref = item.get("secretKeyRef") if isinstance(item.get("secretKeyRef"), dict) else None
        if secret_key_ref is not None:
            env_items.append({"name": name, "valueFrom": {"secretKeyRef": copy.deepcopy(secret_key_ref)}})
            continue
        if item.get("value") is not None:
            env_items.append({"name": name, "value": str(item.get("value"))})
    # Inject egress allowlists from sidecar spec capabilities
    egress = sidecar_spec.get("networkEgress") or {}
    if isinstance(egress, dict):
        domains = egress.get("domains")
        if isinstance(domains, list):
            env_items.append({"name": "MCP_EGRESS_DOMAINS", "value": ",".join(str(d) for d in domains)})
        cidrs = egress.get("ips")
        if isinstance(cidrs, list):
            env_items.append({"name": "MCP_EGRESS_CIDRS", "value": ",".join(str(c) for c in cidrs)})
    return env_items


def _resolve_sidecar_resources(sidecar_spec: dict[str, Any]) -> dict[str, dict[str, str]]:
    """Resolve per-sidecar resource overrides with safe defaults."""
    resources = sidecar_spec.get("resources") or {}
    if not isinstance(resources, dict):
        resources = {}
    requests_spec = resources.get("requests") or {}
    limits_spec = resources.get("limits") or {}
    return {
        "requests": {
            "cpu": str(requests_spec.get("cpu", "50m")),
            "memory": str(requests_spec.get("memory", "64Mi")),
        },
        "limits": {
            "cpu": str(limits_spec.get("cpu", "500m")),
            "memory": str(limits_spec.get("memory", "256Mi")),
        },
    }


def _build_sidecar_egress_init_container(allowed_cidrs: list[str]) -> dict[str, Any]:
    """Build an init container that restricts pod egress via iptables."""
    rules = [
        "iptables -P OUTPUT DROP",
        "iptables -A OUTPUT -o lo -j ACCEPT",
        "iptables -A OUTPUT -p udp --dport 53 -j ACCEPT",
        "iptables -A OUTPUT -p tcp --dport 53 -j ACCEPT",
        "iptables -A OUTPUT -m state --state ESTABLISHED,RELATED -j ACCEPT",
    ]
    for cidr in allowed_cidrs:
        rules.append(f"iptables -A OUTPUT -d {cidr} -j ACCEPT")
    return {
        "name": "sidecar-egress-init",
        "image": "alpine:3.19",
        "command": ["sh", "-c", f"apk add -U --no-cache iptables && {' && '.join(rules)}"],
        "securityContext": {
            "runAsUser": 0,
            "runAsNonRoot": False,
            "allowPrivilegeEscalation": False,
            "capabilities": {"add": ["NET_ADMIN", "NET_RAW"], "drop": ["ALL"]},
            "seccompProfile": {"type": "RuntimeDefault"},
        },
    }


# ---------------------------------------------------------------------------
# Credential proxy sidecar
# ---------------------------------------------------------------------------

CREDENTIAL_PROXY_LITELLM_PORT: int = 4001
CREDENTIAL_PROXY_MCP_HUB_PORT: int = 4010
CREDENTIAL_PROXY_PROVIDER_PORT: int = 4003
CREDENTIAL_PROXY_INBOUND_PORT: int = 8080
CREDENTIAL_PROXY_HEALTH_PORT: int = 9090
AGENT_INTERNAL_PORT: int = 8081

_PROVIDER_PROXY_CONFIG: dict[str, dict[str, str]] = {
    "opencode": {
        "target": "https://opencode.ai/zen/v1",
        "secret_env": "OPENCODE_API_KEY",
        "header_name": "Authorization",
        "header_prefix": "Bearer ",
    },
    "opencode-go": {
        "target": "https://opencode.ai/zen/go/v1",
        "secret_env": "OPENCODE_GO_API_KEY",
        "header_name": "Authorization",
        "header_prefix": "Bearer ",
    },
    "github-copilot": {
        "target": "https://api.githubcopilot.com",
        "secret_env": "GITHUB_COPILOT_TOKEN",
        "header_name": "Authorization",
        "header_prefix": "Bearer ",
    },
}


def _build_credential_proxy_routes(
    mcp_connections: list[dict[str, Any]],
    mcp_servers: list[str],
    selected_provider_id: str,
) -> list[dict[str, str]]:
    """Build the PROXY_ROUTES JSON for the credential-proxy sidecar."""
    routes: list[dict[str, str]] = []

    routes.append({
        "listen": f":{CREDENTIAL_PROXY_LITELLM_PORT}",
        "target": f"http://{LITELLM_SVC}.{OPERATOR_NAMESPACE}.svc.cluster.local:4000",
        "auth": "bearer",
        "secret_env": "LITELLM_MASTER_KEY",
    })

    provider_proxy = _PROVIDER_PROXY_CONFIG.get(selected_provider_id)
    if provider_proxy is not None:
        routes.append(
            {
                "listen": f":{CREDENTIAL_PROXY_PROVIDER_PORT}",
                "target": provider_proxy["target"],
                "auth": "header",
                "secret_env": provider_proxy["secret_env"],
                "header_name": provider_proxy["header_name"],
                "header_prefix": provider_proxy["header_prefix"],
            }
        )

    needs_mcp_bearer = mcp_connections_require_shared_bearer_token(mcp_connections, mcp_servers)
    if needs_mcp_bearer:
        routes.append({
            "listen": f":{CREDENTIAL_PROXY_MCP_HUB_PORT}",
            "target": f"http://{HELM_RELEASE_NAME}-mcp-github.{MCP_HUB_NAMESPACE}.svc.cluster.local:8000",
            "auth": "bearer",
            "secret_env": "MCP_BEARER_TOKEN",
        })

    # Per-connection remote MCP credentials are also isolated in the proxy.
    # The runtime connects to the original target URL without auth headers.
    # The proxy injects those headers server-side using the env-bound secrets.
    for index, connection in enumerate(mcp_connections, start=1):
        if not isinstance(connection, dict):
            continue
        runtime = connection.get("runtime") if isinstance(connection.get("runtime"), dict) else {}
        if str(runtime.get("kind") or "remote").strip().lower() != "remote":
            continue
        runtime_url = str(runtime.get("url") or "").strip()
        if not runtime_url:
            continue
        for header in runtime.get("headers") or []:
            if not isinstance(header, dict):
                continue
            env_var = str(header.get("envVar") or "").strip()
            if not env_var:
                continue
            header_name = str(header.get("name") or "Authorization").strip() or "Authorization"
            prefix = str(header.get("prefix") or "")
            listen_port = CREDENTIAL_PROXY_MCP_HUB_PORT + index
            route: dict[str, str] = {
                "listen": f":{listen_port}",
                "target": runtime_url,
                "auth": "header",
                "secret_env": env_var,
                "header_name": header_name,
            }
            if prefix:
                route["header_prefix"] = prefix
            routes.append(route)
            break

    routes.append({
        "listen": f":{CREDENTIAL_PROXY_INBOUND_PORT}",
        "target": f"http://localhost:{AGENT_INTERNAL_PORT}",
        "auth": "validate",
        "secret_env": "RUNTIME_BEARER_TOKEN",
    })

    return routes


def _build_credential_proxy_container(
    mcp_connections: list[dict[str, Any]],
    mcp_servers: list[str],
    selected_provider_id: str,
    needs_shared_mcp_bearer: bool,
    provider_bootstrap_secret_name: str,
) -> dict[str, Any]:
    """Build the credential-proxy sidecar container spec."""
    routes = _build_credential_proxy_routes(mcp_connections, mcp_servers, selected_provider_id)

    env: list[dict[str, Any]] = [
        {"name": "PROXY_ROUTES", "value": json.dumps(routes, ensure_ascii=False)},
        {
            "name": "LITELLM_MASTER_KEY",
            "valueFrom": {
                "secretKeyRef": {
                    "name": SECRET_NAME,
                    "key": "LITELLM_MASTER_KEY",
                    "optional": False,
                }
            },
        },
        {
            "name": "OPENCODE_SERVER_PASSWORD",
            "valueFrom": {
                "secretKeyRef": {
                    "name": SECRET_NAME,
                    "key": "OPENCODE_SERVER_PASSWORD",
                    "optional": True,
                }
            },
        },
        {
            "name": "RUNTIME_BEARER_TOKEN",
            "valueFrom": {
                "secretKeyRef": {
                    "name": SECRET_NAME,
                    "key": "RUNTIME_BEARER_TOKEN",
                    "optional": True,
                }
            },
        },
    ]

    if needs_shared_mcp_bearer:
        env.append({
            "name": "MCP_BEARER_TOKEN",
            "valueFrom": {
                "secretKeyRef": {
                    "name": MCP_AUTH_SECRET_NAME,
                    "key": "bearer-token",
                    "optional": True,
                }
            },
        })

    provider_proxy = _PROVIDER_PROXY_CONFIG.get(selected_provider_id)
    if provider_proxy is not None:
        env.append(
            {
                "name": provider_proxy["secret_env"],
                "valueFrom": {
                    "secretKeyRef": {
                        "name": SECRET_NAME,
                        "key": provider_proxy["secret_env"],
                        "optional": True,
                    }
                },
            }
        )

    for secret_binding in _build_mcp_runtime_secret_env_bindings(mcp_connections):
        env.append(secret_binding)

    env.append(
        {
            "name": "API_GATEWAY_SHARED_TOKEN",
            "valueFrom": {
                "secretKeyRef": {
                    "name": SECRET_NAME,
                    "key": "API_GATEWAY_SHARED_TOKEN",
                    "optional": False,
                }
            },
        }
    )
    # §security-R5: per-namespace HMAC secret used to bind the shared
    # api-gateway token to this runtime's agent + namespace. The
    # api-gateway reads the same secret (or the operator's
    # RUNTIME_IDENTITY_HMAC_SECRET) to validate the X-Runtime-Identity
    # header. Optional so missing secrets don't fail the pod.
    env.append(
        {
            "name": "RUNTIME_IDENTITY_HMAC_SECRET",
            "valueFrom": {
                "secretKeyRef": {
                    "name": SECRET_NAME,
                    "key": "RUNTIME_IDENTITY_HMAC_SECRET",
                    "optional": True,
                }
            },
        }
    )

    if selected_provider_id not in ("litellm",):
        env.append({
            "name": "OPENCODE_AUTH_CONTENT",
            "valueFrom": {
                "secretKeyRef": {
                    "name": provider_bootstrap_secret_name,
                    "key": "OPENCODE_AUTH_CONTENT",
                    "optional": True,
                }
            },
        })

    return {
        "name": "credential-proxy",
        "image": CREDENTIAL_PROXY_IMAGE,
        "imagePullPolicy": CREDENTIAL_PROXY_IMAGE_PULL_POLICY,
        "ports": [
            {"containerPort": CREDENTIAL_PROXY_LITELLM_PORT, "name": "litellm-proxy", "protocol": "TCP"},
            {"containerPort": CREDENTIAL_PROXY_PROVIDER_PORT, "name": "provider-proxy", "protocol": "TCP"},
            {"containerPort": CREDENTIAL_PROXY_INBOUND_PORT, "name": "proxy-http", "protocol": "TCP"},
            {"containerPort": CREDENTIAL_PROXY_HEALTH_PORT, "name": "health", "protocol": "TCP"},
        ],
        "env": env,
        "resources": {
            "requests": {"cpu": "10m", "memory": "16Mi"},
            "limits": {"cpu": "100m", "memory": "64Mi"},
        },
        "securityContext": {
            "allowPrivilegeEscalation": False,
            "readOnlyRootFilesystem": True,
            "runAsNonRoot": True,
            "runAsUser": 1000,
            "runAsGroup": 1000,
            "capabilities": {"drop": ["ALL"]},
            "seccompProfile": {"type": "RuntimeDefault"},
        },
        "readinessProbe": {
            "httpGet": {"path": "/healthz", "port": CREDENTIAL_PROXY_HEALTH_PORT},
            "initialDelaySeconds": 1,
            "periodSeconds": 5,
            "timeoutSeconds": 2,
            "failureThreshold": 3,
        },
        "livenessProbe": {
            "httpGet": {"path": "/healthz", "port": CREDENTIAL_PROXY_HEALTH_PORT},
            "initialDelaySeconds": 3,
            "periodSeconds": 10,
            "timeoutSeconds": 2,
            "failureThreshold": 3,
        },
        "volumeMounts": [
            {"name": "credential-proxy-tmp", "mountPath": "/tmp"},  # noqa: S108 — standard container tmp mount
        ],
    }


# ---------------------------------------------------------------------------
# PVC manifests
# ---------------------------------------------------------------------------


def create_worker_artifact_pvc_manifest(
    kind: str, resource_namespace: str, resource_name: str,
    owner_references: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a PVC manifest for worker Job artifacts."""
    manifest: dict[str, Any] = {
        "apiVersion": "v1",
        "kind": "PersistentVolumeClaim",
        "metadata": {
            "name": worker_artifact_pvc_name(kind, resource_namespace, resource_name),
            "namespace": OPERATOR_NAMESPACE,
            "labels": {
                "app": "operator-worker-artifacts",
                "kubesynapse.ai/resource-kind": kind,
                "kubesynapse.ai/resource-name": resource_name,
                "kubesynapse.ai/resource-namespace": resource_namespace,
            },
        },
        "spec": build_pvc_spec(WORKER_ARTIFACT_SIZE, WORKER_ARTIFACT_STORAGE_CLASS or None),
    }
    if owner_references:
        if resource_namespace == OPERATOR_NAMESPACE:
            manifest["metadata"]["ownerReferences"] = owner_references
        else:
            logger.warning(
                "Skipping ownerReferences for worker artifact PVC '%s' because the owning %s '%s/%s' "
                "lives outside operator namespace '%s'.",
                manifest["metadata"]["name"],
                kind,
                resource_namespace,
                resource_name,
                OPERATOR_NAMESPACE,
            )
    return manifest


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

    logger.info(
        "MCP auth token copied from '%s/%s' → '%s/%s' (agent secret provisioning).",
        MCP_HUB_NAMESPACE,
        MCP_AUTH_SECRET_NAME,
        namespace,
        MCP_AUTH_SECRET_NAME,
    )

    return {
        "apiVersion": "v1",
        "kind": "Secret",
        "metadata": {
            "name": MCP_AUTH_SECRET_NAME,
            "namespace": namespace,
            "labels": {
                "app": "ai-agent",
                "kubesynapse.ai/managed-by": "operator",
                "kubesynapse.ai/secret-purpose": "mcp-auth",
            },
        },
        "type": str(getattr(source_secret, "type", None) or "Opaque"),
        "data": {"bearer-token": bearer_token},
    }


def mcp_connections_require_shared_bearer_token(mcp_connections: list[dict[str, Any]], mcp_servers: list[str]) -> bool:
    """Return True when an agent still needs the shared MCP hub bearer token.

    Structured saved MCP connections can be fully self-contained remote endpoints.
    Those should not force the operator to mirror the hub auth secret just because
    legacy mcpServers was backfilled for compatibility.
    """
    if not mcp_connections:
        return bool(mcp_servers)

    for connection in mcp_connections:
        if not isinstance(connection, dict):
            continue
        transport = str(connection.get("transport") or "").strip().lower()
        if transport == "hub":
            return True
        runtime = connection.get("runtime") if isinstance(connection.get("runtime"), dict) else {}
        headers = runtime.get("headers") if isinstance(runtime.get("headers"), list) else []
        for header in headers:
            if not isinstance(header, dict):
                continue
            if str(header.get("envVar") or "").strip() == "MCP_BEARER_TOKEN":
                return True
    return False


# Built-in provider ID -> secret key mapping
_BUILTIN_PROVIDER_SECRET_KEYS: dict[str, str] = {
    "opencode": "OPENCODE_API_KEY",
    "opencode-go": "OPENCODE_GO_API_KEY",
    "github-copilot": "GITHUB_COPILOT_TOKEN",
}

_PI_PROVIDER_SECRET_KEYS: dict[str, tuple[str, ...]] = {
    "anthropic": ("ANTHROPIC_API_KEY",),
    "azure-openai-responses": ("AZURE_OPENAI_API_KEY",),
    "openai": ("OPENAI_API_KEY",),
    "deepseek": ("DEEPSEEK_API_KEY",),
    "google": ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
    "mistral": ("MISTRAL_API_KEY",),
    "groq": ("GROQ_API_KEY",),
    "cerebras": ("CEREBRAS_API_KEY",),
    "cloudflare-workers-ai": ("CLOUDFLARE_API_KEY",),
    "xai": ("XAI_API_KEY",),
    "openrouter": ("OPENROUTER_API_KEY",),
    "vercel-ai-gateway": ("AI_GATEWAY_API_KEY",),
    "zai": ("ZAI_API_KEY",),
    "opencode": ("OPENCODE_API_KEY",),
    "opencode-go": ("OPENCODE_API_KEY", "OPENCODE_GO_API_KEY"),
    "huggingface": ("HF_TOKEN",),
    "fireworks": ("FIREWORKS_API_KEY",),
    "kimi-coding": ("KIMI_API_KEY",),
    "minimax": ("MINIMAX_API_KEY",),
    "minimax-cn": ("MINIMAX_CN_API_KEY",),
}


def _decode_secret_value(raw_value: str | None) -> str:
    value = str(raw_value or "").strip()
    if not value:
        return ""
    try:
        return base64.b64decode(value).decode("utf-8").strip()
    except Exception:
        return value


def _resolve_first_secret_value(auth_data: dict[str, str], secret_keys: tuple[str, ...]) -> str:
    for secret_key in secret_keys:
        decoded = _decode_secret_value(auth_data.get(secret_key))
        if decoded:
            return decoded
    return ""


def _build_provider_auth_content(auth_data: dict[str, str]) -> str:
    vals: dict[str, dict[str, str]] = {}
    for provider_id, secret_key in _BUILTIN_PROVIDER_SECRET_KEYS.items():
        value = auth_data.get(secret_key)
        if not value:
            continue
        try:
            decoded = base64.b64decode(value).decode("utf-8").strip()
        except Exception:
            decoded = value.strip()
        if decoded:
            if provider_id == "github-copilot":
                vals[provider_id] = {
                    "type": "oauth",
                    "refresh": decoded,
                    "access": decoded,
                }
            else:
                vals[provider_id] = {"type": "api", "key": decoded}
    return json.dumps(vals, ensure_ascii=False)


def _build_pi_provider_auth_content(auth_data: dict[str, str]) -> str:
    vals: dict[str, dict[str, str]] = {}
    for provider_id, secret_keys in _PI_PROVIDER_SECRET_KEYS.items():
        decoded = _resolve_first_secret_value(auth_data, secret_keys)
        if decoded:
            vals[provider_id] = {"type": "api_key", "key": decoded}
    return json.dumps(vals, ensure_ascii=False)


def _build_selected_provider_json(
    selected_provider_id: str,
    registry_state: dict[str, Any],
) -> str | None:
    custom_providers: dict[str, dict[str, Any]] = registry_state.get("custom_providers") or {}
    entry = custom_providers.get(selected_provider_id)
    if not isinstance(entry, dict):
        return None
    return json.dumps(
        {
            "id": selected_provider_id,
            "name": str(entry.get("name") or selected_provider_id),
            "base_url": str(entry.get("base_url") or "").strip() or None,
            "headers": {str(k): str(v) for k, v in (entry.get("headers") or {}).items()},
            "models": [str(m).strip() for m in (entry.get("models") or []) if str(m).strip()],
        },
        ensure_ascii=False,
    )


def create_opencode_provider_bootstrap_secret(
    agent_name: str,
    namespace: str,
    spec: dict[str, Any],
) -> dict[str, Any] | None:
    model = str(spec.get("model") or "").strip()
    selected_provider_id, _selected_model_id = _resolve_opencode_model_ref(model)

    if selected_provider_id == "litellm":
        return None

    core_api = kubernetes.client.CoreV1Api()
    try:
        source_secret = core_api.read_namespaced_secret(name=SECRET_NAME, namespace=OPERATOR_NAMESPACE)
    except ApiException as exc:
        if exc.status == 404:
            logger.warning("Provider auth secret '%s/%s' not found; skipping bootstrap secret.", OPERATOR_NAMESPACE, SECRET_NAME)
            return None
        raise
    auth_data: dict[str, str] = getattr(source_secret, "data", None) or {}

    auth_content = _build_provider_auth_content(auth_data)
    if not auth_content or auth_content == "{}":
        logger.warning("No connected provider auth keys found; skipping bootstrap secret.")
        return None

    string_data: dict[str, str] = {"OPENCODE_AUTH_CONTENT": auth_content}

    try:
        configmap = core_api.read_namespaced_config_map(
            name=PROVIDER_REGISTRY_CONFIGMAP_NAME,
            namespace=OPERATOR_NAMESPACE,
        )
    except ApiException as exc:
        logger.debug("Provider registry configmap not found (%s); custom provider config unavailable.", exc)
        configmap_data: dict[str, str] = {}
    else:
        configmap_data = getattr(configmap, "data", None) or {}

    registry_state: dict[str, Any] = {}
    raw_registry = str(configmap_data.get("providers.json") or "").strip()
    if raw_registry:
        try:
            registry_state = json.loads(raw_registry)
        except ValueError:
            logger.warning("Provider registry configmap contains invalid JSON; custom provider config unavailable.")

    selected_provider_json = _build_selected_provider_json(selected_provider_id, registry_state)
    if selected_provider_json:
        string_data["OPENCODE_SELECTED_PROVIDER_JSON"] = selected_provider_json

    secret_name = f"{sandbox_name(agent_name)}-opencode-provider"
    return {
        "apiVersion": "v1",
        "kind": "Secret",
        "metadata": {
            "name": secret_name,
            "namespace": namespace,
            "labels": {
                "app": "ai-agent",
                "kubesynapse.ai/managed-by": "operator",
                "kubesynapse.ai/agent-name": agent_name,
                "kubesynapse.ai/secret-purpose": "opencode-provider",
            },
        },
        "type": "Opaque",
        "stringData": string_data,
    }


def create_pi_provider_bootstrap_secret(
    agent_name: str,
    namespace: str,
) -> dict[str, Any] | None:
    core_api = kubernetes.client.CoreV1Api()
    try:
        source_secret = core_api.read_namespaced_secret(name=SECRET_NAME, namespace=OPERATOR_NAMESPACE)
    except ApiException as exc:
        if exc.status == 404:
            logger.warning("Provider auth secret '%s/%s' not found; skipping pi bootstrap secret.", OPERATOR_NAMESPACE, SECRET_NAME)
            return None
        raise

    auth_data: dict[str, str] = getattr(source_secret, "data", None) or {}
    auth_content = _build_pi_provider_auth_content(auth_data)
    if not auth_content or auth_content == "{}":
        logger.warning("No connected pi provider auth keys found; skipping pi bootstrap secret.")
        return None

    secret_name = f"{sandbox_name(agent_name)}-pi-provider"
    return {
        "apiVersion": "v1",
        "kind": "Secret",
        "metadata": {
            "name": secret_name,
            "namespace": namespace,
            "labels": {
                "app": "ai-agent",
                "kubesynapse.ai/managed-by": "operator",
                "kubesynapse.ai/agent-name": agent_name,
                "kubesynapse.ai/secret-purpose": "pi-provider",
            },
        },
        "type": "Opaque",
        "stringData": {"PI_AUTH_JSON": auth_content},
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
            # Keep the Service pinned to the pod's public ingress port.
            # In credential-proxy mode, 8080 belongs to the proxy sidecar while
            # the agent container itself moves to 8081. Routing via the
            # container port name would bypass the proxy.
            "ports": [{"name": "http", "port": API_PORT, "targetPort": API_PORT}],
        },
    }


# ---------------------------------------------------------------------------
# StatefulSet manifest
# ---------------------------------------------------------------------------


def _create_pi_statefulset_spec(
    *,
    name: str,
    namespace: str,
    spec: dict[str, Any],
    system_prompt: str,
    model: str,
    mcp_connections: list[dict[str, Any]],
    mcp_servers: list[str],
    mcp_sidecars: list[dict[str, Any]],
    enable_gvisor: bool,
    agent_resources: dict[str, Any],
    env: list[dict[str, Any]],
    volume_mounts: list[dict[str, Any]],
    volumes: list[dict[str, Any]],
    init_volume_mounts: list[dict[str, Any]],
    container_security_context: dict[str, Any],
    pod_security_context: dict[str, Any],
    git_sidecar_env: list[dict[str, Any]],
    git_volumes: list[dict[str, Any]],
    git_volume_mounts: list[dict[str, Any]],
    init_containers: list[dict[str, Any]],
    skills_config: dict[str, Any],
) -> dict[str, Any]:
    """Build a StatefulSet manifest for the pi runtime."""

    runtime_spec = spec.get("runtime") or {}
    pi_spec = (runtime_spec.get("pi") or {}) if isinstance(runtime_spec, dict) else {}
    needs_shared_mcp_bearer = mcp_connections_require_shared_bearer_token(mcp_connections, mcp_servers)

    agent_image = PI_RUNTIME_IMAGE
    agent_image_pull_policy = PI_RUNTIME_IMAGE_PULL_POLICY

    # Resolve pi model configuration
    pi_provider = str(pi_spec.get("provider") or PI_DEFAULT_PROVIDER or "").strip()
    pi_model = str(pi_spec.get("model") or spec.get("model") or PI_DEFAULT_MODEL).strip()
    pi_thinking_level = str(
        pi_spec.get("thinkingLevel") or PI_DEFAULT_THINKING_LEVEL or "medium"
    ).strip()
    pi_tools = pi_spec.get("tools")
    pi_no_tools = bool(pi_spec.get("noTools", False))
    pi_no_session = bool(pi_spec.get("noSession", False))

    # Workspace volume
    volume_mounts = list(volume_mounts)
    volume_mounts.append({"name": "workspace-volume", "mountPath": "/workspace"})
    # State volume for pi session persistence
    volume_mounts.append({"name": "state-volume", "mountPath": "/home/piuser/.pi/agent"})
    volumes = list(volumes)
    volumes.append({"name": "workspace-volume", "emptyDir": {"sizeLimit": "5Gi"}})

    # §security-P0: Mount hardened immutable config read-only
    if PI_IMMUTABLE_CONFIG:
        release_prefix = HELM_RELEASE_NAME or "kubesynapse"
        pi_cfg_cm_name = f"{release_prefix}-pi-safe-config"
        volume_mounts.append(
            {"name": "pi-immutable-config", "mountPath": "/etc/kubesynapse/pi-config/pi-config.json", "subPath": "pi-config.json", "readOnly": True}
        )
        volumes.append(
            {"name": "pi-immutable-config", "configMap": {"name": pi_cfg_cm_name}}
        )
        # Mount empty read-only dirs to block extension/skill discovery
        volume_mounts.append({"name": "pi-ext-block", "mountPath": "/home/piuser/.pi/agent/extensions", "readOnly": True})
        volumes.append({"name": "pi-ext-block", "emptyDir": {}})
        volume_mounts.append({"name": "pi-skills-block", "mountPath": "/home/piuser/.pi/agent/skills", "readOnly": True})
        volumes.append({"name": "pi-skills-block", "emptyDir": {}})

    # Pi-specific environment variables
    pi_env = list(env)
    pi_env.extend(
        [
            {"name": "KUBESYNAPSE_AGENT_NAME", "value": name},
            {"name": "KUBESYNAPSE_NAMESPACE", "value": namespace},
            {"name": "PI_PROVIDER", "value": pi_provider},
            {"name": "PI_MODEL", "value": pi_model},
            {"name": "PI_THINKING_LEVEL", "value": pi_thinking_level},
            {"name": "PI_NO_SESSION", "value": "true" if pi_no_session else "false"},
            {"name": "PI_SYSTEM_PROMPT", "value": system_prompt},
        ]
    )
    if PI_IMMUTABLE_CONFIG:
        pi_env.append({"name": "PI_CONFIG_DIR", "value": "/etc/kubesynapse/pi-config"})
    pi_env.extend(
        [
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
                        "optional": not needs_shared_mcp_bearer,
                    }
                },
            },
        ]
    )

    # Inject pi-compatible MCP connections
    if mcp_connections:
        pi_env.append(
            {
                "name": OPENCODE_MCP_CONNECTIONS_ENV,  # Same env var, pi extension reads it
                "value": json.dumps(mcp_connections, ensure_ascii=False, sort_keys=True),
            }
        )

    # Inject MCP sidecars
    if mcp_sidecars:
        pi_env.append(
            {
                "name": OPENCODE_MCP_SIDECARS_ENV,
                "value": json.dumps(mcp_sidecars, ensure_ascii=False, sort_keys=True),
            }
        )

    # Tools configuration
    if pi_no_tools:
        pi_env.append({"name": "PI_NO_TOOLS", "value": "true"})
    elif pi_tools:
        if isinstance(pi_tools, list):
            pi_env.append({"name": "PI_TOOLS", "value": ",".join(str(t) for t in pi_tools)})
        else:
            pi_env.append({"name": "PI_TOOLS", "value": str(pi_tools)})

    # Permission level from spec
    permission_level = str(pi_spec.get("permissionLevel") or "permissive").strip()
    pi_env.append({"name": "KS_PERMISSION_LEVEL", "value": permission_level})

    # §security-P0: Provider-scoped API key injection.
    # When pi_provider is set, only that provider's keys are injected into the
    # runtime pod.  When empty (auto-detect mode), all keys are injected with a
    # WARNING logged.  This prevents a compromised runtime from exfiltrating
    # keys for providers it was never configured to use.
    _ALL_PI_SECRET_KEYS: list[str] = [
        "ANTHROPIC_API_KEY",
        "AZURE_OPENAI_API_KEY",
        "OPENAI_API_KEY",
        "DEEPSEEK_API_KEY",
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "MISTRAL_API_KEY",
        "GROQ_API_KEY",
        "CEREBRAS_API_KEY",
        "CLOUDFLARE_API_KEY",
        "XAI_API_KEY",
        "OPENROUTER_API_KEY",
        "AI_GATEWAY_API_KEY",
        "OPENCODE_API_KEY",
        "OPENCODE_GO_API_KEY",
        "HF_TOKEN",
        "FIREWORKS_API_KEY",
        "KIMI_API_KEY",
        "MINIMAX_API_KEY",
        "MINIMAX_CN_API_KEY",
        "COHERE_API_KEY",
    ]
    if pi_provider and pi_provider in _PI_PROVIDER_SECRET_KEYS:
        provider_keys = list(_PI_PROVIDER_SECRET_KEYS[pi_provider])
        for key in provider_keys:
            pi_env.append(
                {
                    "name": key,
                    "valueFrom": {
                        "secretKeyRef": {
                            "name": SECRET_NAME,
                            "key": key,
                            "optional": True,
                        }
                    },
                }
            )
    else:
        if not pi_provider:
            logger.warning(
                "Pi runtime for agent %s has no explicit provider "
                "(PI_DEFAULT_PROVIDER is empty); all %d API keys will be "
                "injected. Set pi.provider or PI_DEFAULT_PROVIDER to scope "
                "key exposure.",
                name,
                len(_ALL_PI_SECRET_KEYS),
            )
        for key in _ALL_PI_SECRET_KEYS:
            pi_env.append(
                {
                    "name": key,
                    "valueFrom": {
                        "secretKeyRef": {
                            "name": SECRET_NAME,
                            "key": key,
                            "optional": True,
                        }
                    },
                }
            )

    # Provider-specific auth from provider registry (same pattern as OpenCode)
    provider_bootstrap_secret_name = f"{sandbox_name(name)}-pi-provider"
    pi_env.append(
        {
            "name": "PI_AUTH_JSON",
            "valueFrom": {
                "secretKeyRef": {
                    "name": provider_bootstrap_secret_name,
                    "key": "PI_AUTH_JSON",
                    "optional": True,
                }
            },
        }
    )

    if OTEL_ENDPOINT:
        pi_env.append({"name": "OTEL_EXPORTER_OTLP_ENDPOINT", "value": OTEL_ENDPOINT})

    # Init containers (same pattern as OpenCode)
    init_containers = list(init_containers)
    init_containers.append(
        {
            "name": "init-state-volume",
            "image": agent_image,
            "imagePullPolicy": agent_image_pull_policy,
            "command": [
                "/bin/sh",
                "-c",
                "set -e; "
                "mkdir -p /home/piuser/.pi/agent/sessions /workspace; "
                "chown -R 2000:2000 /home/piuser/.pi /workspace || true; "
                "chmod -R ug+rwX /home/piuser/.pi /workspace || true",
            ],
            "securityContext": {
                "runAsUser": 0,
                "runAsGroup": 0,
                "runAsNonRoot": False,
                "allowPrivilegeEscalation": False,
                "capabilities": {"drop": ["ALL"], "add": ["CHOWN", "FOWNER"]},
                "seccompProfile": {"type": "RuntimeDefault"},
            },
            "volumeMounts": list(init_volume_mounts),
        }
    )

    # Pi-bridge exposes HTTP endpoints for health checks and prompt forwarding.
    pi_agent_container = {
        "name": "agent-runtime",
        "image": agent_image,
        "imagePullPolicy": agent_image_pull_policy,
        "securityContext": container_security_context,
        "resources": agent_resources,
        "ports": [{"containerPort": 8080, "name": "http", "protocol": "TCP"}],
        "startupProbe": {
            "httpGet": {"path": "/health", "port": 8080},
            "initialDelaySeconds": 5,
            "periodSeconds": 5,
            "timeoutSeconds": 3,
            "failureThreshold": 30,
        },
        "readinessProbe": {
            "httpGet": {"path": "/ready", "port": 8080},
            "initialDelaySeconds": 10,
            "periodSeconds": 10,
            "timeoutSeconds": 5,
            "failureThreshold": 3,
        },
        "livenessProbe": {
            "httpGet": {"path": "/health", "port": 8080},
            "initialDelaySeconds": 15,
            "periodSeconds": 20,
            "timeoutSeconds": 5,
            "failureThreshold": 3,
        },
        "lifecycle": {
            "preStop": {
                "exec": {
                    "command": [
                        "/bin/sh",
                        "-c",
                        "echo '{\"type\":\"abort\"}' | timeout 5 pi --mode rpc --no-session 2>/dev/null; sleep 10",
                    ]
                },
            },
        },
        "volumeMounts": volume_mounts,
        "env": pi_env,
    }

    containers = [pi_agent_container]

    # Add MCP sidecar containers (same pattern as OpenCode)
    if mcp_sidecars:
        for index, sidecar_spec in enumerate(mcp_sidecars):
            sidecar_name = sidecar_spec.get("name", f"tool-{index}")
            sidecar_port = sidecar_spec.get("port", 8080)
            sidecar_env_list = _build_sidecar_env_items(sidecar_spec)
            sidecar_vol_mounts = [
                {"name": "tmp-volume", "mountPath": "/tmp"}  # noqa: S108
            ]
            if sidecar_name == "git" and git_sidecar_env:
                sidecar_env_list.extend(git_sidecar_env)
                sidecar_vol_mounts.extend(git_volume_mounts)
            if sidecar_name == "git":
                sidecar_env_list.append({"name": "MCP_WORK_DIR", "value": "/workspace"})
                sidecar_vol_mounts.append({"name": "workspace-volume", "mountPath": "/workspace"})
            container_name = (
                sidecar_name if str(sidecar_name).startswith("mcp-") else f"mcp-{sidecar_name}"
            )
            containers.append(
                {
                    "name": container_name,
                    "image": sidecar_spec["image"],
                    "imagePullPolicy": sidecar_spec.get("imagePullPolicy", "IfNotPresent"),
                    "ports": [{"containerPort": sidecar_port, "protocol": "TCP"}],
                    "resources": sidecar_spec.get("resources", {}),
                    "env": sidecar_env_list,
                    "volumeMounts": sidecar_vol_mounts,
                }
            )

    # Add git volumes
    all_volumes = list(volumes)
    if git_volumes:
        all_volumes.extend(git_volumes)

    # Build StatefulSet
    statefulset_name = sandbox_name(name)
    pod_labels = {"app": "ai-agent", "agent-name": name, "runtime": "pi"}

    manifest: dict[str, Any] = {
        "apiVersion": "apps/v1",
        "kind": "StatefulSet",
        "metadata": {
            "name": statefulset_name,
            "namespace": namespace,
            "labels": pod_labels,
            "annotations": {
                "kubesynapse.ai/agent-name": name,
                "kubesynapse.ai/runtime": "pi",
            },
        },
        "spec": {
            "serviceName": statefulset_name,
            "replicas": 1,
            "selector": {"matchLabels": pod_labels},
            "template": {
                "metadata": {
                    "labels": pod_labels,
                    "annotations": {
                        POD_TEMPLATE_REVISION_ANNOTATION: _build_pi_pod_template_revision(
                            spec=spec,
                            policy_name=None,
                            policy_spec=None,
                            mcp_sidecars=mcp_sidecars,
                        ),
                    },
                },
                "spec": {
                    "serviceAccountName": RUNTIME_SERVICE_ACCOUNT,
                    "securityContext": {
                        "runAsNonRoot": True,
                        "runAsUser": 2000,
                        "runAsGroup": 2000,
                        "fsGroup": 2000,
                        "fsGroupChangePolicy": "OnRootMismatch",
                        "seccompProfile": {"type": "RuntimeDefault"},
                        # §security-R5: explicitly disable host namespace
                        # access. Defaults are already False in K8s 1.25+,
                        # but defense-in-depth: a compromised runtime cannot
                        # sniff the host's network namespace, observe
                        # host processes, or share IPC with host processes.
                        "hostNetwork": False,
                        "hostPID": False,
                        "hostIPC": False,
                    },
                    "initContainers": init_containers,
                    "containers": containers,
                    "volumes": all_volumes,
                    "terminationGracePeriodSeconds": 60,
                },
            },
            "volumeClaimTemplates": [
                {
                    "metadata": {"name": "state-volume"},
                    "spec": build_pvc_spec(
                        (spec.get("storage") or {}).get("size", DEFAULT_STORAGE_SIZE),
                        (spec.get("storage") or {}).get("storageClassName"),
                    ),
                }
            ],
        },
    }

    if enable_gvisor:
        manifest["spec"]["template"]["spec"]["runtimeClassName"] = "gvisor"

    return manifest


def _create_mistral_vibe_statefulset_spec(
    *,
    name: str,
    namespace: str,
    spec: dict[str, Any],
    system_prompt: str,
    model: str,
    enable_gvisor: bool,
    agent_resources: dict[str, Any],
    env: list[dict[str, Any]],
    volume_mounts: list[dict[str, Any]],
    volumes: list[dict[str, Any]],
    init_volume_mounts: list[dict[str, Any]],
    init_containers: list[dict[str, Any]],
) -> dict[str, Any]:
    runtime_spec = spec.get("runtime") or {}
    vibe_spec = (runtime_spec.get("mistralVibe") or {}) if isinstance(runtime_spec, dict) else {}

    agent_image = MISTRAL_VIBE_RUNTIME_IMAGE
    agent_image_pull_policy = MISTRAL_VIBE_RUNTIME_IMAGE_PULL_POLICY
    vibe_model = str(vibe_spec.get("model") or spec.get("model") or "devstral-small").strip() or "devstral-small"
    vibe_no_session = bool(vibe_spec.get("noSession", False))

    volume_mounts = list(volume_mounts)
    volume_mounts.append({"name": "workspace-volume", "mountPath": "/workspace"})
    volumes = list(volumes)
    volumes.append({"name": "workspace-volume", "emptyDir": {"sizeLimit": "5Gi"}})

    vibe_env = list(env)
    vibe_env.extend(
        [
            {"name": "KUBESYNAPSE_AGENT_NAME", "value": name},
            {"name": "KUBESYNAPSE_NAMESPACE", "value": namespace},
            {"name": "VIBE_ACTIVE_MODEL", "value": vibe_model},
            {"name": "VIBE_SYSTEM_PROMPT", "value": system_prompt},
            {"name": "VIBE_NO_SESSION", "value": "true" if vibe_no_session else "false"},
            {
                "name": "MISTRAL_API_KEY",
                "valueFrom": {
                    "secretKeyRef": {
                        "name": SECRET_NAME,
                        "key": "MISTRAL_API_KEY",
                        "optional": True,
                    }
                },
            },
        ]
    )
    if OTEL_ENDPOINT:
        vibe_env.append({"name": "OTEL_EXPORTER_OTLP_ENDPOINT", "value": OTEL_ENDPOINT})

    init_containers = list(init_containers)
    init_containers.append(
        {
            "name": "init-state-volume",
            "image": agent_image,
            "imagePullPolicy": agent_image_pull_policy,
            "command": [
                "/bin/sh",
                "-c",
                "set -e; mkdir -p /app/state/home/.vibe /workspace; chown -R 1000:1000 /app/state /workspace || true; chmod -R ug+rwX /app/state /workspace || true",
            ],
            "securityContext": {
                "runAsUser": 0,
                "runAsGroup": 0,
                "runAsNonRoot": False,
                "allowPrivilegeEscalation": False,
                "capabilities": {"drop": ["ALL"], "add": ["CHOWN", "FOWNER"]},
                "seccompProfile": {"type": "RuntimeDefault"},
            },
            "volumeMounts": list(init_volume_mounts),
        }
    )

    statefulset_name = sandbox_name(name)
    pod_labels = {"app": "ai-agent", "agent-name": name, "runtime": "mistral-vibe"}
    manifest: dict[str, Any] = {
        "apiVersion": "apps/v1",
        "kind": "StatefulSet",
        "metadata": {
            "name": statefulset_name,
            "namespace": namespace,
            "labels": pod_labels,
            "annotations": {
                "kubesynapse.ai/agent-name": name,
                "kubesynapse.ai/runtime": "mistral-vibe",
            },
        },
        "spec": {
            "serviceName": statefulset_name,
            "replicas": 1,
            "selector": {"matchLabels": pod_labels},
            "template": {
                "metadata": {
                    "labels": pod_labels,
                    "annotations": {
                        POD_TEMPLATE_REVISION_ANNOTATION: _build_pod_template_revision(
                            spec=spec,
                            runtime_kind="mistral-vibe",
                            policy_name=None,
                            policy_spec=None,
                            mcp_sidecars=[],
                        ),
                    },
                },
                "spec": {
                    "serviceAccountName": RUNTIME_SERVICE_ACCOUNT,
                    "securityContext": {
                        "runAsNonRoot": True,
                        "runAsUser": 1000,
                        "runAsGroup": 1000,
                        "fsGroup": 1000,
                        "fsGroupChangePolicy": "OnRootMismatch",
                        "seccompProfile": {"type": "RuntimeDefault"},
                        # §security-R5: explicit host namespace isolation
                        "hostNetwork": False,
                        "hostPID": False,
                        "hostIPC": False,
                    },
                    "initContainers": init_containers,
                    "containers": [
                        {
                            "name": "agent-runtime",
                            "image": agent_image,
                            "imagePullPolicy": agent_image_pull_policy,
                            "securityContext": {
                                "allowPrivilegeEscalation": False,
                                "readOnlyRootFilesystem": True,
                                "capabilities": {"drop": ["ALL"]},
                            },
                            "resources": agent_resources,
                            "ports": [{"containerPort": 8080, "name": "http", "protocol": "TCP"}],
                            "startupProbe": {
                                "httpGet": {"path": "/health", "port": 8080},
                                "initialDelaySeconds": 5,
                                "periodSeconds": 5,
                                "timeoutSeconds": 3,
                                "failureThreshold": 30,
                            },
                            "readinessProbe": {
                                "httpGet": {"path": "/ready", "port": 8080},
                                "initialDelaySeconds": 10,
                                "periodSeconds": 10,
                                "timeoutSeconds": 5,
                                "failureThreshold": 3,
                            },
                            "livenessProbe": {
                                "httpGet": {"path": "/health", "port": 8080},
                                "initialDelaySeconds": 15,
                                "periodSeconds": 20,
                                "timeoutSeconds": 5,
                                "failureThreshold": 3,
                            },
                            "volumeMounts": volume_mounts,
                            "env": vibe_env,
                        }
                    ],
                    "volumes": volumes,
                    "terminationGracePeriodSeconds": 60,
                },
            },
            "volumeClaimTemplates": [
                {
                    "metadata": {"name": "state-volume"},
                    "spec": build_pvc_spec(
                        (spec.get("storage") or {}).get("size", DEFAULT_STORAGE_SIZE),
                        (spec.get("storage") or {}).get("storageClassName"),
                    ),
                }
            ],
        },
    }
    if enable_gvisor:
        manifest["spec"]["template"]["spec"]["runtimeClassName"] = "gvisor"
    return manifest


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
    model = str(spec.get("model") or "").strip()
    if not model:
        raise kopf.PermanentError("AIAgent.spec.model must be explicitly set.")
    mcp_connections = spec.get("mcpConnections") if isinstance(spec.get("mcpConnections"), list) else []
    mcp_servers = spec.get("mcpServers") or []
    mcp_sidecars = _extract_structured_mcp_sidecars(mcp_connections) or (spec.get("mcpSidecars") or [])
    needs_shared_mcp_bearer = mcp_connections_require_shared_bearer_token(mcp_connections, mcp_servers)
    enable_gvisor = spec.get("enableGVisor", False)
    system_prompt = spec.get("systemPrompt", "")
    agent_resources = resolve_agent_container_resources(spec)
    if len(system_prompt) > 32000:
        raise kopf.PermanentError(f"spec.systemPrompt exceeds maximum length (32000 chars, got {len(system_prompt)})")
    skills_config = parse_agent_skills_config(spec.get("skills"), source="AIAgent.spec.skills", namespace=namespace)
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
                    "image": git_catalog_entry.get("image", "docker.io/kubesynapse/mcp-git:latest"),
                    "port": git_catalog_entry.get("port", 8095),
                }
            )
            logger.info("Auto-injected git MCP sidecar for agent '%s' (gitConfig present)", name)

        git_sidecar_env = [
            {"name": "GIT_REPO_URL", "value": git_config.get("repoUrl", "")},
            {"name": "GIT_AUTH_METHOD", "value": git_config.get("authMethod", "")},
        ]
        # D10: derive ``GIT_ALLOWED_HOSTS`` from the parsed host so the
        # runtime rejects credential sends to hosts that aren't in the
        # configured repo URL. The runtime now defaults to deny-all
        # when this env var is missing, so we must set it here.
        if _parsed_repo.hostname:
            git_sidecar_env.append(
                {"name": "GIT_ALLOWED_HOSTS", "value": _parsed_repo.hostname.strip().lower()}
            )
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
        # D10: mirror GIT_ALLOWED_HOSTS into the main agent container
        # so the runtime's deny-all default doesn't break
        # credential-helper-driven git operations.
        if _parsed_repo.hostname:
            git_agent_env.append(
                {"name": "GIT_ALLOWED_HOSTS", "value": _parsed_repo.hostname.strip().lower()}
            )
        if git_branch:
            git_agent_env.append({"name": "GIT_BRANCH", "value": git_branch})
        if cred_secret and auth_method == "token":
            git_agent_env.append(
                {
                    "name": "GIT_TOKEN",
                    "valueFrom": {"secretKeyRef": {"name": cred_secret, "key": "token", "optional": True}},
                }
            )
            # Configure git credential helper so CLI `git push/pull` can
            # authenticate using the injected token automatically.
            _repo_url_for_cred = git_config.get("repoUrl", "")
            _parsed = _urlparse(_repo_url_for_cred)
            _host = _parsed.hostname or ""
            if _host:
                git_agent_env.extend(
                    [
                        {
                            "name": "GIT_CONFIG_COUNT",
                            "value": "2",
                        },
                        {
                            "name": "GIT_CONFIG_KEY_0",
                            "value": f"credential.https://{_host}.username",
                        },
                        {
                            "name": "GIT_CONFIG_VALUE_0",
                            "value": "x-access-token",
                        },
                        {
                            "name": "GIT_CONFIG_KEY_1",
                            "value": f"credential.https://{_host}.helper",
                        },
                        {
                            "name": "GIT_CONFIG_VALUE_1",
                            "value": "!f() { echo \"password=$GIT_TOKEN\"; }; f",
                        },
                    ]
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
            # Configure git credential helper for basic auth so CLI
            # `git push/pull` uses the injected username/password.
            _repo_url_for_cred = git_config.get("repoUrl", "")
            _parsed = _urlparse(_repo_url_for_cred)
            _host = _parsed.hostname or ""
            if _host:
                git_agent_env.extend(
                    [
                        {
                            "name": "GIT_CONFIG_COUNT",
                            "value": "1",
                        },
                        {
                            "name": "GIT_CONFIG_KEY_0",
                            "value": f"credential.https://{_host}.helper",
                        },
                        {
                            "name": "GIT_CONFIG_VALUE_0",
                            "value": "!f() { echo \"username=$GIT_USERNAME\"; echo \"password=$GIT_PASSWORD\"; }; f",
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
        if skills_config.get("configMapRef"):
            env.append({"name": "AGENT_SKILL_CONFIGMAP_PATH", "value": "/app/state/skills-configmap/"})
    # Inject git credentials into the main agent container (must happen
    # AFTER the main env list is created above).
    if git_config.get("repoUrl") and git_agent_env:
        env.extend(git_agent_env)
    if not CREDENTIAL_PROXY_ENABLED:
        env.extend(_build_mcp_runtime_secret_env_bindings(mcp_connections))

    volume_mounts = [
        {"name": "tmp-volume", "mountPath": "/tmp"},  # noqa: S108 — standard container tmp mount
        {"name": "state-volume", "mountPath": "/app/state"},
    ]
    volumes: list[dict[str, Any]] = [{"name": "tmp-volume", "emptyDir": {"sizeLimit": "1Gi"}}]
    if skills_config.get("configMapRef"):
        volume_mounts.append({"name": "skills-configmap", "mountPath": "/app/state/skills-configmap/", "readOnly": True})
        volumes.append({"name": "skills-configmap", "configMap": {"name": skills_config["configMapRef"]}})

    # Shared init volume mounts (used by both opencode and pi)
    init_volume_mounts = [{"name": "state-volume", "mountPath": "/app/state"}]
    # Shared init_containers placeholder (pi builds its own, opencode reassigns)
    init_containers: list[dict[str, Any]] = []

    if runtime_kind == "pi":
        # Pi runtime mounts state at /home/piuser/.pi/agent/ for session persistence
        return _create_pi_statefulset_spec(
            name=name,
            namespace=namespace,
            spec=spec,
            system_prompt=system_prompt,
            model=model,
            mcp_connections=mcp_connections,
            mcp_servers=mcp_servers,
            mcp_sidecars=mcp_sidecars,
            enable_gvisor=enable_gvisor,
            agent_resources=agent_resources,
            env=env,
            volume_mounts=volume_mounts,
            volumes=volumes,
            init_volume_mounts=[
                {"name": "state-volume", "mountPath": "/home/piuser/.pi/agent"},
            ],
            container_security_context=container_security_context,
            pod_security_context=pod_security_context,
            git_sidecar_env=git_sidecar_env,
            git_volumes=git_volumes,
            git_volume_mounts=git_volume_mounts,
            init_containers=init_containers,
            skills_config=skills_config,
        )

    if runtime_kind == "mistral-vibe":
        return _create_mistral_vibe_statefulset_spec(
            name=name,
            namespace=namespace,
            spec=spec,
            system_prompt=system_prompt,
            model=model,
            enable_gvisor=enable_gvisor,
            agent_resources=agent_resources,
            env=env,
            volume_mounts=volume_mounts,
            volumes=volumes,
            init_volume_mounts=[{"name": "state-volume", "mountPath": "/app/state"}],
            init_containers=init_containers,
        )

    if runtime_kind != "opencode":
        raise kopf.PermanentError(f"AIAgent.spec.runtime.kind '{runtime_kind}' is not implemented.")

    agent_image = OPENCODE_RUNTIME_IMAGE
    agent_image_pull_policy = OPENCODE_RUNTIME_IMAGE_PULL_POLICY
    # Resolve the selected provider/model from spec.model (supports slash-form refs)
    selected_provider_id, selected_model_id = _resolve_opencode_model_ref(model)
    opencode_config_files = merged_opencode_runtime_config_files(spec)
    volume_mounts.append({"name": "workspace-volume", "mountPath": "/workspace"})
    volumes.append({"name": "workspace-volume", "emptyDir": {"sizeLimit": "5Gi"}})

    # §security-P0: Mount hardened immutable config read-only
    if OPENCODE_IMMUTABLE_CONFIG:
        release_prefix = HELM_RELEASE_NAME or "kubesynapse"
        cfg_cm_name = f"{release_prefix}-opencode-safe-config"
        volume_mounts.append(
            {"name": "opencode-immutable-config", "mountPath": "/etc/kubesynapse/opencode.json", "subPath": "opencode.json", "readOnly": True}
        )
        volumes.append(
            {"name": "opencode-immutable-config", "configMap": {"name": cfg_cm_name}}
        )
        env.append({"name": "OPENCODE_CONFIG", "value": "/etc/kubesynapse/opencode.json"})
        # §security-P0: Signal that the immutable config is mandatory so the
        # runtime fails CLOSED (restrictive permission baseline) if the mount
        # is missing or tampered with, instead of running wide open.
        env.append({"name": "OPENCODE_REQUIRE_IMMUTABLE_CONFIG", "value": "true"})

    # Build a deterministic per-agent secret name for provider bootstrap data
    provider_bootstrap_secret_name = f"{sandbox_name(name)}-opencode-provider"

    from config import API_PORT as _API_PORT

    # When credential-proxy is enabled, secrets are held in the proxy sidecar.
    # The agent container connects to localhost:4001 (LiteLLM proxy) and
    # localhost:4010 (MCP Hub proxy) without needing any auth tokens.
    if CREDENTIAL_PROXY_ENABLED:
        litellm_host = f"http://localhost:{CREDENTIAL_PROXY_LITELLM_PORT}"
    else:
        litellm_host = f"http://{LITELLM_SVC}.{OPERATOR_NAMESPACE}.svc.cluster.local:4000"

    env.extend(
        [
            {"name": "OPENCODE_PROVIDER", "value": selected_provider_id},
            {"name": "OPENCODE_MODEL", "value": selected_model_id},
            {"name": "OPENCODE_SYSTEM_PROMPT", "value": system_prompt},
            {"name": "OPENCODE_DEFAULT_AGENT", "value": "build"},
            {"name": "LITELLM_HOST", "value": litellm_host},
            {"name": "LITELLM_BASE_PATH", "value": "v1/chat/completions"},
            {"name": "MCP_SERVERS", "value": ",".join(mcp_servers)},
            {"name": "MCP_HUB_NAMESPACE", "value": MCP_HUB_NAMESPACE},
            {"name": "CREDENTIAL_PROXY_ENABLED", "value": "true" if CREDENTIAL_PROXY_ENABLED else "false"},
            {"name": "CREDENTIAL_PROXY_MCP_HUB_PORT", "value": str(CREDENTIAL_PROXY_MCP_HUB_PORT)},
            # The credential proxy validates inbound bearer auth on port 8080
            # and forwards to the inner runtime on 8081 after stripping it.
            {"name": "RUNTIME_AUTH_REQUIRED", "value": str(RUNTIME_AUTH_REQUIRED_OVERRIDE).lower() if RUNTIME_AUTH_REQUIRED_OVERRIDE is not None else ("false" if CREDENTIAL_PROXY_ENABLED else "true")},
            {
                "name": "RUNTIME_BEARER_TOKEN",
                "valueFrom": {
                    "secretKeyRef": {
                        "name": SECRET_NAME,
                        "key": "RUNTIME_BEARER_TOKEN",
                        "optional": True,
                    }
                },
            },
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
            {
                "name": "OPENCODE_SERVER_PASSWORD",
                "valueFrom": {
                    "secretKeyRef": {
                        "name": SECRET_NAME,
                        "key": "OPENCODE_SERVER_PASSWORD",
                        "optional": True,
                    }
                },
            },
        ]
    )

    # Only inject secrets into the agent container when credential-proxy is disabled.
    # When enabled, secrets are held exclusively in the credential-proxy sidecar.
    if not CREDENTIAL_PROXY_ENABLED:
        env.extend(
            [
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
                            "optional": not needs_shared_mcp_bearer,
                        }
                    },
                },
                {
                    "name": "OPENCODE_AUTH_CONTENT",
                    "valueFrom": {
                        "secretKeyRef": {
                            "name": provider_bootstrap_secret_name,
                            "key": "OPENCODE_AUTH_CONTENT",
                            "optional": True,
                        }
                    },
                },
            ]
        )
    # Inject selected-provider non-secret config for custom providers
    if selected_provider_id not in ("opencode", "opencode-go", "github-copilot", "litellm"):
        env.append(
            {
                "name": "OPENCODE_SELECTED_PROVIDER_JSON",
                "valueFrom": {
                    "secretKeyRef": {
                        "name": provider_bootstrap_secret_name,
                        "key": "OPENCODE_SELECTED_PROVIDER_JSON",
                        "optional": True,
                    }
                },
            }
        )
    if opencode_config_files:
        env.append(
            {
                "name": OPENCODE_RUNTIME_CONFIG_FILES_ENV,
                "value": json.dumps(opencode_config_files, ensure_ascii=False, sort_keys=True),
            }
        )
    if mcp_connections:
        env.append(
            {
                "name": OPENCODE_MCP_CONNECTIONS_ENV,
                "value": json.dumps(mcp_connections, ensure_ascii=False, sort_keys=True),
            }
        )
    if mcp_sidecars:
        env.append(
            {
                "name": OPENCODE_MCP_SIDECARS_ENV,
                "value": json.dumps(mcp_sidecars, ensure_ascii=False, sort_keys=True),
            }
        )
    if OTEL_ENDPOINT:
        env.append({"name": "OTEL_EXPORTER_OTLP_ENDPOINT", "value": OTEL_ENDPOINT})
    if AGENT_HITL_MODE:
        env.append({"name": "HITL_MODE", "value": AGENT_HITL_MODE})
    if HITL_NOTIFICATION_WEBHOOK_URL:
        env.append({"name": "HITL_NOTIFICATION_WEBHOOK_URL", "value": HITL_NOTIFICATION_WEBHOOK_URL})
    runtime_extra_env = opencode_runtime_extra_env_items()
    policy_model_output_limit = _resolve_policy_model_output_limit(policy_spec)
    if policy_model_output_limit is not None:
        runtime_extra_env = [
            item for item in runtime_extra_env if item.get("name") != "OPENCODE_MODEL_OUTPUT_LIMIT"
        ]
        runtime_extra_env.append(
            {
                "name": "OPENCODE_MODEL_OUTPUT_LIMIT",
                "value": str(policy_model_output_limit),
            }
        )
    env.extend(runtime_extra_env)

    # §security-P1: Inject policy-defined admin tool ceiling.
    # The ceiling caps the maximum permission level an agent can exercise
    # for each tool, regardless of what the immutable config allows.
    # Applied as a JSON env var that the runtime reads at startup.
    admin_tool_ceiling = _resolve_admin_tool_ceiling(policy_spec)
    if admin_tool_ceiling:
        env.append(
            {
                "name": "OPENCODE_ADMIN_PERMISSION_CEILING_JSON",
                "value": json.dumps(admin_tool_ceiling, ensure_ascii=False, sort_keys=True),
            }
        )

    # §security-P1: Inject sealed policy hash for runtime attestation.
    # The runtime can include this in healthz responses for gateway verification.
    policy_hash = _compute_policy_hash(policy_name, policy_spec)
    if policy_hash:
        env.append({"name": "KUBESYNAPSE_POLICY_HASH", "value": policy_hash})
        env.append({"name": "KUBESYNAPSE_POLICY_NAME", "value": policy_name or ""})

    # §security-P1: Inject admin-controlled env vars last so they always win
    # over user-provided overrides for security-critical runtime behaviour.
    env.extend(opencode_runtime_admin_env_items())

    init_volume_mounts = [{"name": "state-volume", "mountPath": "/app/state"}]

    init_containers = [
        {
            "name": "init-state-volume",
            "image": agent_image,
            "imagePullPolicy": agent_image_pull_policy,
            "command": [
                "/bin/sh",
                "-c",
                "set -e; "
                "mkdir -p /app/state/home /app/state/data /app/state/config; "
                "chown -R 1000:1000 /app/state || true; "
                "chmod -R ug+rwX /app/state || true",
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

    # When credential-proxy is enabled, the agent listens on an internal port (8081)
    # and the credential-proxy listens on the external port (8080) to validate auth.
    agent_listen_port = AGENT_INTERNAL_PORT if CREDENTIAL_PROXY_ENABLED else _API_PORT

    agent_container = {
        "name": "agent-runtime",
        "image": agent_image,
        "imagePullPolicy": agent_image_pull_policy,
        "securityContext": container_security_context,
        "ports": [{"containerPort": agent_listen_port, "name": "http", "protocol": "TCP"}],
        "resources": agent_resources,
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

    # Add credential-proxy sidecar when enabled.
    # This container holds all secrets and injects auth headers for outbound requests.
    # The agent container never sees API keys, bearer tokens, or passwords.
    if CREDENTIAL_PROXY_ENABLED:
        credential_proxy_container = _build_credential_proxy_container(
            mcp_connections=mcp_connections,
            mcp_servers=mcp_servers,
            selected_provider_id=selected_provider_id,
            needs_shared_mcp_bearer=needs_shared_mcp_bearer,
            provider_bootstrap_secret_name=provider_bootstrap_secret_name,
        )
        containers.append(credential_proxy_container)
        volumes.append({"name": "credential-proxy-tmp", "emptyDir": {"sizeLimit": "64Mi"}})
        logger.info(
            "Injected credential-proxy sidecar for agent '%s' (secrets isolated from agent container)",
            name,
        )

    if mcp_sidecars:
        for index, sidecar_spec in enumerate(mcp_sidecars):
            sidecar_name = sidecar_spec.get("name", f"tool-{index}")
            sidecar_port = sidecar_spec.get("port", 8080)
            sidecar_env = _build_sidecar_env_items(sidecar_spec)
            sidecar_vol_mounts = [{"name": "tmp-volume", "mountPath": "/tmp"}]  # noqa: S108 — standard container tmp mount
            # Add egress init container if network restrictions are declared
            egress_cidrs = sidecar_spec.get("networkEgress", {}).get("ips", [])
            if egress_cidrs:
                init_containers.append(_build_sidecar_egress_init_container(egress_cidrs))
            # Inject git-specific env vars and volume mounts
            if sidecar_name == "git" and git_sidecar_env:
                sidecar_env.extend(git_sidecar_env)
                sidecar_vol_mounts.extend(git_volume_mounts)
            # Git sidecar needs access to the workspace so it can clone repos
            # into /workspace and commit/push files the agent created there.
            if sidecar_name == "git":
                sidecar_env.append({"name": "MCP_WORK_DIR", "value": "/workspace"})
                sidecar_vol_mounts.append({"name": "workspace-volume", "mountPath": "/workspace"})
            container_name = sidecar_name if str(sidecar_name).startswith("mcp-") else f"mcp-{sidecar_name}"
            containers.append(
                {
                    "name": container_name,
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
                    "resources": _resolve_sidecar_resources(sidecar_spec),
                    "volumeMounts": sidecar_vol_mounts,
                }
            )

    # OPA sidecar injection
    opa_spec = spec.get("opa") or {}
    if opa_spec.get("enabled"):
        opa_policy_cm = str(opa_spec.get("configMapRef") or "").strip() or f"{name}-opa-policies"
        volumes.append({"name": "opa-policies", "configMap": {"name": opa_policy_cm}})
        containers.append(
            {
                "name": "opa",
                "image": OPA_SIDECAR_IMAGE,
                "ports": [{"containerPort": OPA_SIDECAR_PORT, "protocol": "TCP"}],
                "args": [
                    "run",
                    "--server",
                    "--addr",
                    f"0.0.0.0:{OPA_SIDECAR_PORT}",
                    "/opa/policies",
                ],
                "volumeMounts": [
                    {"name": "opa-policies", "mountPath": "/opa/policies", "readOnly": True}
                ],
                "livenessProbe": {
                    "httpGet": {"path": "/health", "port": OPA_SIDECAR_PORT},
                    "initialDelaySeconds": 5,
                    "periodSeconds": 10,
                    "timeoutSeconds": 3,
                    "failureThreshold": 3,
                },
                "readinessProbe": {
                    "httpGet": {"path": "/health", "port": OPA_SIDECAR_PORT},
                    "initialDelaySeconds": 2,
                    "periodSeconds": 5,
                    "timeoutSeconds": 3,
                    "failureThreshold": 3,
                },
                "securityContext": container_security_context,
                "resources": OPA_SIDECAR_RESOURCES,
            }
        )
        logger.info("Injected OPA sidecar for agent '%s' (policies from ConfigMap '%s')", name, opa_policy_cm)

    # Only mount the service account token when the kubernetes MCP sidecar
    # is present (needs in-cluster API access for kubectl / K8s operations).
    has_k8s_sidecar = any(
        s.get("name") == "kubernetes" or s.get("serverId") == "kubernetes-mcp" for s in mcp_sidecars
    )
    pod_spec: dict[str, Any] = {
        "serviceAccountName": RUNTIME_SERVICE_ACCOUNT,
        "automountServiceAccountToken": has_k8s_sidecar,
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

    # Build pod template annotations including policy attestation
    pod_annotations: dict[str, str] = {POD_TEMPLATE_REVISION_ANNOTATION: pod_template_revision}
    if policy_hash:
        pod_annotations["kubesynapse.ai/policy-hash"] = policy_hash
    if policy_name:
        pod_annotations["kubesynapse.ai/policy-name"] = policy_name
    if policy_spec and policy_spec.get("sealed"):
        pod_annotations["kubesynapse.ai/policy-sealed"] = "true"

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
                "whenDeleted": "Delete",
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
                    "annotations": pod_annotations,
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
                        "namespaceSelector": {"matchLabels": {"kubesynapse.ai/mcp-hub": "true"}},
                        "podSelector": {"matchLabels": {"mcp.kubesynapse.ai/type": mcp_type}},
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
                "kubesynapse.ai/policy-type": "mcp-egress",
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

    egress_rules: list[dict[str, Any]] = agent_baseline_egress_rules()
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
                "kubesynapse.ai/policy-type": "a2a-egress",
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
                "kubesynapse.ai/policy-type": "a2a-ingress",
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
    resource_uid: str | None = None,
) -> dict[str, Any]:
    """Build a Kubernetes Job manifest for a workflow worker."""
    # §reliability-P2: Deterministic job naming from run_id makes concurrent
    # enqueue attempts idempotent — the same run_id always produces the same
    # job name, allowing enqueue_worker_job to detect and return existing jobs.
    run_id_suffix = run_id.strip() if run_id else str(int(time.time()))
    job_name = hashed_resource_name(kind, resource_namespace, resource_name, suffix=f"{generation}-{run_id_suffix}")
    artifact_journal_path = workflow_journal_path(artifact_path)
    pod_security_context = {
        "runAsNonRoot": True,
        "runAsUser": 999,
        "runAsGroup": 37,
        "fsGroup": 37,
        "seccompProfile": {"type": "RuntimeDefault"},
        # §security-R5: explicit host namespace isolation for workers
        "hostNetwork": False,
        "hostPID": False,
        "hostIPC": False,
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
                "kubesynapse.ai/resource-kind": kind,
                "kubesynapse.ai/resource-name": resource_name,
                "kubesynapse.ai/resource-namespace": resource_namespace,
                "kubesynapse.ai/resource-uid": (resource_uid or "")[:63],
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
                        "kubesynapse.ai/resource-kind": kind,
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
                                {
                                    "name": "RUNTIME_BEARER_TOKEN",
                                    "valueFrom": {
                                        "secretKeyRef": {
                                            "name": SECRET_NAME,
                                            "key": "RUNTIME_BEARER_TOKEN",
                                            "optional": False,
                                        }
                                    },
                                },
                                {"name": "WORKFLOW_RUN_ID", "value": run_id or ""},
                                {"name": "TARGET_UID", "value": resource_uid or ""},
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
                                {"name": "tmp", "mountPath": "/tmp"},  # noqa: S108 — standard container tmp mount
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
