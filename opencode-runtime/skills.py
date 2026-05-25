"""Skill materialization, MCP config, runtime directory setup, and git credentials."""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
from pathlib import Path
from typing import Any

import yaml
from config import (
    AGENT_SKILL_CONFIGMAP_PATH_ENV,
    AGENT_SKILL_FILES_ENV,
    DEFAULT_AGENT,
    DEFAULT_AGENT_STEPS,
    DEFAULT_MODEL,
    DEFAULT_MODEL_REF,
    DEFAULT_PROVIDER,
    HELM_RELEASE_NAME,
    HOME_DIR,
    LITELLM_API_KEY,
    MCP_BEARER_TOKEN,
    MCP_HUB_NAMESPACE,
    MEMORY_DIR,
    MODEL_CONTEXT_LIMIT,
    MODEL_OUTPUT_LIMIT,
    OPENCODE_CONFIG_DIR,
    OPENCODE_MCP_CONNECTIONS_ENV,
    OPENCODE_MCP_SIDECARS_ENV,
    OPENCODE_RUNTIME_CONFIG_FILES_ENV,
    OPENCODE_SERVER_HOST,
    OPENCODE_SERVER_PORT,
    OPENCODE_WORKDIR,
    SELECTED_PROVIDER_JSON,
    SESSION_MAP_PATH,
    SKILL_NAME_RE,
    WORKSPACE_SNAPSHOT_DIR,
    XDG_CONFIG_HOME,
    XDG_DATA_HOME,
    _parse_json_env,
    build_litellm_base_url,
)

from utils import dedupe_items, normalize_relative_path, serialize_file_content

logger = logging.getLogger("opencode-runtime")

# Mutable runtime config populated during lifespan startup
SKILL_RUNTIME_CONFIG: dict[str, Any] = {
    "skillFiles": [],
    "warnings": [],
    "configFiles": [],
    "mcpSidecars": [],
}

# kubesynapse platform instruction injected into all OpenCode agents
KUBESYNAPSE_INSTRUCTION_CONTENT = (
    "# kubesynapse Platform Context\n\n"
    "You are operating inside the kubesynapse Kubernetes AI platform.\n\n"
    "## Environment\n"
    "- Your pod name, namespace, and identity are in environment variables (KUBESYNAPSE_AGENT_NAME, KUBESYNAPSE_NAMESPACE, etc.).\n"
    "- You have access to A2A (agent-to-agent) communication — use @ mentions to invoke peer agents.\n"
    "- You have access to MCP (Model Context Protocol) servers configured by the platform admin.\n"
    "- The shared repository URL is in GIT_REPO_URL (if configured).\n\n"
    "## Session Continuity\n"
    "- Use the memory tool to save important findings and decisions.\n"
    "- Check memory first when you don't recall previous conversation context.\n"
    "- After completing major milestones, save a summary to memory with type='checkpoint'.\n\n"
    "## Behavior Rules\n"
    "1. Always search the codebase before making changes.\n"
    "2. Verify your work after each change — read files back, run tests.\n"
    "3. Report FULL error messages, not summaries.\n"
    "4. Use MCP servers for external integrations instead of bash hacks when available.\n"
    "5. Only invoke A2A agents that are configured in your outbound targets.\n"
    "6. You are scoped to your namespace — cross-namespace operations require explicit references.\n"
    "7. Clean up temporary files and be efficient with resources.\n"
    "8. When something fails, report the full error and your diagnosis.\n"
)


def ensure_runtime_directories() -> None:
    """Create required runtime directories if they do not exist."""
    for path in [
        Path(HOME_DIR),
        Path(XDG_CONFIG_HOME),
        Path(XDG_DATA_HOME),
        Path(OPENCODE_CONFIG_DIR),
        Path(OPENCODE_WORKDIR),
        SESSION_MAP_PATH.parent,
        Path(MEMORY_DIR),
        Path(WORKSPACE_SNAPSHOT_DIR),
    ]:
        path.mkdir(parents=True, exist_ok=True)


def materialize_KUBESYNAPSE_instructions() -> str | None:
    """Write the kubesynapse platform instruction file to the OpenCode config dir.

    Returns the relative path to the instruction file for use in opencode.json,
    or None if the file could not be written.
    """
    try:
        config_dir = Path(OPENCODE_CONFIG_DIR)
        config_dir.mkdir(parents=True, exist_ok=True)
        target = config_dir / "kubesynapse-platform-context.md"
        target.write_text(KUBESYNAPSE_INSTRUCTION_CONTENT, encoding="utf-8")
        return str(target.relative_to(config_dir).as_posix())
    except OSError as exc:
        logger.warning("Failed to write kubesynapse instruction file: %s", exc)
        return None


def parse_skill_frontmatter(path: str, content: str) -> tuple[str, str, list[str]]:
    """Extract the canonical skill name, description, and warnings from a skill file."""

    def _normalize_skill_name(candidate: str) -> str:
        lowered = candidate.strip().lower()
        cleaned = re.sub(r"[^a-z0-9-]", "-", lowered)
        cleaned = re.sub(r"-+", "-", cleaned).strip("-")
        return cleaned or "skill"

    default_name = _normalize_skill_name(Path(path).parent.name or Path(path).stem or "skill")
    warnings: list[str] = []
    description = ""
    if not content.startswith("---"):
        return default_name, description, warnings
    parts = content.split("---", 2)
    if len(parts) < 3:
        return default_name, description, warnings
    try:
        frontmatter = yaml.safe_load(parts[1]) or {}
    except yaml.YAMLError as exc:
        warnings.append(f"Unable to parse skill frontmatter for '{path}': {exc}")
        return default_name, description, warnings
    description = str(frontmatter.get("description") or "").strip()
    name = _normalize_skill_name(str(frontmatter.get("name") or default_name))
    if not SKILL_NAME_RE.fullmatch(name) or len(name) > 64:
        warnings.append(
            f"Skill '{path}' has invalid frontmatter name '{frontmatter.get('name')}'. Falling back to '{default_name}'."
        )
        name = default_name
    if name != default_name:
        warnings.append(f"Materialized skill '{path}' as '{name}' for OpenCode discovery.")
    return name or default_name, description, warnings


def deep_merge_config(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge *override* into *base* and return a new dict."""
    merged: dict[str, Any] = dict(base.items())
    for key, value in override.items():
        existing = merged.get(key)
        if isinstance(existing, dict) and isinstance(value, dict):
            merged[key] = deep_merge_config(existing, value)
        else:
            merged[key] = value
    return merged


def load_opencode_config_overrides() -> dict[str, Any]:
    """Load any user-provided opencode.json override from the injected config payload."""
    payload = _parse_json_env(OPENCODE_RUNTIME_CONFIG_FILES_ENV)
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise RuntimeError(f"{OPENCODE_RUNTIME_CONFIG_FILES_ENV} must be a JSON object")

    raw_content = payload.get("opencode.json")
    if raw_content is None:
        return {}
    if isinstance(raw_content, dict):
        return raw_content
    if isinstance(raw_content, str):
        parsed = json.loads(raw_content)
        if isinstance(parsed, dict):
            return parsed
    raise RuntimeError("opencode.json must decode to a JSON object")


def materialize_opencode_config_files(base_config: dict[str, Any] | None = None) -> list[str]:
    """Write operator-injected config files to the OpenCode config directory."""
    payload = _parse_json_env(OPENCODE_RUNTIME_CONFIG_FILES_ENV)
    if payload is None:
        payload = {}
    if not isinstance(payload, dict):
        raise RuntimeError(f"{OPENCODE_RUNTIME_CONFIG_FILES_ENV} must be a JSON object")

    merged_base_config = base_config
    if base_config is not None:
        merged_base_config = deep_merge_config(base_config, load_opencode_config_overrides())

    written_files: list[str] = []
    root = Path(OPENCODE_CONFIG_DIR)
    for raw_path, raw_content in payload.items():
        relative_path = normalize_relative_path(str(raw_path), source=OPENCODE_RUNTIME_CONFIG_FILES_ENV)
        if relative_path == "opencode.json" and merged_base_config is not None:
            continue
        target = root / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(f"{serialize_file_content(raw_content).rstrip()}\n", encoding="utf-8")
        written_files.append(relative_path)

    if merged_base_config is not None:
        target = root / "opencode.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(f"{serialize_file_content(merged_base_config).rstrip()}\n", encoding="utf-8")
        written_files.append("opencode.json")

    return sorted(written_files)


def _collect_skill_files_from_env() -> dict[str, str]:
    """Collect skill files from operator-injected env var and ConfigMap mount."""
    files: dict[str, str] = {}

    payload = _parse_json_env(AGENT_SKILL_FILES_ENV)
    if payload is not None:
        if not isinstance(payload, dict):
            raise RuntimeError(f"{AGENT_SKILL_FILES_ENV} must be a JSON object")
        files.update({str(k): str(v) for k, v in payload.items()})

    configmap_path = os.environ.get(AGENT_SKILL_CONFIGMAP_PATH_ENV, "").strip()
    if configmap_path:
        cm_dir = Path(configmap_path)
        if cm_dir.is_dir():
            for entry in sorted(cm_dir.iterdir()):
                if entry.is_file() and entry.name.endswith(".md"):
                    try:
                        content = entry.read_text(encoding="utf-8")
                    except Exception:
                        continue
                    files[entry.name] = content

    return files


def materialize_skill_files() -> tuple[list[str], list[dict[str, str]], list[str]]:
    """Write operator-injected skill files to the OpenCode skills directory.

    Reads from both inline skill files (env var) and mounted ConfigMap directory.
    Returns (written_files, skill_meta, warnings) where skill_meta is a list of
    dicts with keys ``name``, ``description``, ``file``, and ``content``.
    """
    skill_files = _collect_skill_files_from_env()
    if not skill_files:
        return [], [], []

    written_files: list[str] = []
    skill_meta: list[dict[str, str]] = []
    warnings: list[str] = []
    seen_names: set[str] = set()
    skills_root = Path(OPENCODE_CONFIG_DIR) / "skills"

    for raw_path, raw_content in skill_files.items():
        content = str(raw_content)
        skill_name, skill_description, skill_warnings = parse_skill_frontmatter(str(raw_path), content)
        warnings.extend(skill_warnings)
        if skill_name in seen_names:
            warnings.append(f"Skipping duplicate skill '{skill_name}' while materializing OpenCode skills.")
            continue
        seen_names.add(skill_name)
        target = skills_root / skill_name / "SKILL.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(f"{content.rstrip()}\n", encoding="utf-8")
        rel_path = target.relative_to(Path(OPENCODE_CONFIG_DIR)).as_posix()
        written_files.append(rel_path)
        # Strip YAML frontmatter for the content injected into the prompt
        body = content
        if content.startswith("---"):
            parts = content.split("---", 2)
            if len(parts) >= 3:
                body = parts[2].strip()
        skill_meta.append({
            "name": skill_name,
            "description": skill_description,
            "file": str(target),
            "content": body,
        })

    return sorted(written_files), skill_meta, dedupe_items(warnings)


def load_opencode_sidecars() -> list[dict[str, Any]]:
    """Parse the MCP sidecar configuration from environment."""
    payload = _parse_json_env(OPENCODE_MCP_SIDECARS_ENV)
    if payload is None:
        return []
    if not isinstance(payload, list):
        raise RuntimeError(f"{OPENCODE_MCP_SIDECARS_ENV} must decode to a JSON array")

    sidecars: list[dict[str, Any]] = []
    seen: set[tuple[str, int]] = set()
    for item in payload:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        try:
            port = int(item.get("port", 8080))
        except (TypeError, ValueError):
            continue
        key = (name, port)
        if key in seen:
            continue
        seen.add(key)
        sidecars.append({"name": name, "port": port})
    return sidecars


def load_opencode_mcp_connections() -> list[dict[str, Any]]:
    """Load structured MCP connections passed in by the operator."""
    payload = _parse_json_env(OPENCODE_MCP_CONNECTIONS_ENV)
    if payload is None:
        return []
    if not isinstance(payload, list):
        raise RuntimeError(f"{OPENCODE_MCP_CONNECTIONS_ENV} must decode to a JSON array")
    return [item for item in payload if isinstance(item, dict)]


def build_shared_mcp_config() -> tuple[dict[str, Any], list[str]]:
    """Build MCP server entries from the shared MCP hub."""
    entries: dict[str, Any] = {}
    warnings: list[str] = []
    raw_servers = os.getenv("MCP_SERVERS", "").strip()
    if not raw_servers:
        return entries, warnings

    for server_type in [item.strip() for item in raw_servers.split(",") if item.strip()]:
        if server_type == "github":
            warnings.append(
                "Skipping shared GitHub MCP server for OpenCode because the current hub deployment exposes an HTTP adapter rather than a native /mcp endpoint."
            )
            continue
        if not MCP_BEARER_TOKEN:
            warnings.append(f"Skipping shared MCP server '{server_type}' because MCP_BEARER_TOKEN is not configured.")
            continue
        entries[server_type] = {
            "type": "remote",
            "url": f"http://{HELM_RELEASE_NAME}-mcp-{server_type}.{MCP_HUB_NAMESPACE}.svc.cluster.local:8000/mcp",
            "enabled": True,
            "headers": {
                "Authorization": f"Bearer {MCP_BEARER_TOKEN}",
            },
        }
    return entries, warnings


def build_mcp_config(sidecars: list[dict[str, Any]]) -> tuple[dict[str, Any], list[str]]:
    """Merge sidecar and shared MCP configurations."""
    structured_connections = load_opencode_mcp_connections()
    if structured_connections:
        return build_structured_mcp_config(structured_connections)

    config: dict[str, Any] = {}
    warnings: list[str] = []
    for item in sidecars:
        config[item["name"]] = {
            "type": "remote",
            "url": f"http://127.0.0.1:{item['port']}/mcp",
            "enabled": True,
        }
    shared_config, shared_warnings = build_shared_mcp_config()
    config.update(shared_config)
    warnings.extend(shared_warnings)
    return config, dedupe_items(warnings)


def build_structured_mcp_config(connections: list[dict[str, Any]]) -> tuple[dict[str, Any], list[str]]:
    """Build MCP config entries from the structured operator contract."""
    config: dict[str, Any] = {}
    warnings: list[str] = []

    for connection in connections:
        runtime = connection.get("runtime") if isinstance(connection.get("runtime"), dict) else {}
        runtime_kind = str(runtime.get("kind") or "remote").strip().lower() or "remote"
        config_key = str(runtime.get("configKey") or connection.get("slug") or connection.get("name") or connection.get("serverId") or "").strip()
        if not config_key:
            warnings.append("Skipping MCP connection with no config key.")
            continue

        if runtime_kind == "sidecar":
            sidecar = runtime.get("sidecar") if isinstance(runtime.get("sidecar"), dict) else {}
            try:
                port = int(sidecar.get("port", 8080))
            except (TypeError, ValueError):
                warnings.append(f"Skipping MCP sidecar '{config_key}' because its port is invalid.")
                continue
            endpoint_path = str(sidecar.get("endpointPath") or "/mcp").strip() or "/mcp"
            config[config_key] = {
                "type": "remote",
                "url": f"http://127.0.0.1:{port}{endpoint_path}",
                "enabled": True,
            }
            continue

        url = str(runtime.get("url") or "").strip()
        if not url:
            warnings.append(f"Skipping MCP connection '{config_key}' because no runtime URL was provided.")
            continue
        headers: dict[str, str] = {}
        for header in runtime.get("headers") or []:
            if not isinstance(header, dict):
                continue
            header_name = str(header.get("name") or "").strip()
            if not header_name:
                continue
            value = str(header.get("value") or "").strip()
            if not value:
                env_var = str(header.get("envVar") or "").strip()
                if env_var:
                    env_value = os.getenv(env_var, "").strip()
                    prefix = str(header.get("prefix") or "")
                    value = f"{prefix}{env_value}" if env_value else ""
            if value:
                headers[header_name] = value
        config[config_key] = {
            "type": "remote",
            "url": url,
            "enabled": True,
        }
        if headers:
            config[config_key]["headers"] = headers

    return config, dedupe_items(warnings)


# ---------------------------------------------------------------------------
# §security-P1: Immutable config base and admin override helpers
# ---------------------------------------------------------------------------


def _load_immutable_config_base() -> dict[str, Any]:
    """Load the hardened immutable OpenCode config as the security baseline.

    The immutable ConfigMap at /etc/kubesynapse/opencode.json (mounted via
    OPENCODE_CONFIG env var) provides the security FLOOR:
      - plugin: []           — block all plugin auto-loading
      - permission: {...}    — restrictive tool permissions
      - skills: {urls: []}   — block external skill URLs
      - mcp: {}              — empty MCP baseline (runtime adds servers)
      - provider: {}         — empty provider baseline (runtime adds config)

    Returns an empty dict if the file is not found or cannot be parsed.
    """
    import json as _json

    immutable_path = os.getenv("OPENCODE_CONFIG", "/etc/kubesynapse/opencode.json")
    if not immutable_path:
        return {}
    try:
        path = Path(immutable_path)
        if not path.is_file():
            logger.debug("Immutable config not found at %s; skipping security baseline.", immutable_path)
            return {}
        with open(path, encoding="utf-8") as fh:
            return _json.load(fh)
    except (OSError, ValueError) as exc:
        logger.warning("Failed to load immutable config base from %s: %s", immutable_path, exc)
        return {}


def _apply_immutable_security_constraints(
    config: dict[str, Any],
    immutable_base: dict[str, Any],
) -> dict[str, Any]:
    """Re-apply security-critical keys from the immutable config.

    These keys form the security FLOOR. Runtime-generated values and
    user-provided config_overrides cannot relax them. Admin env overrides
    (applied later) CAN selectively override them.
    """
    _SECURITY_FLOOR_KEYS = ("plugin", "skills", "permission")
    for key in _SECURITY_FLOOR_KEYS:
        if key in immutable_base:
            config[key] = immutable_base[key]
    return config


def _apply_admin_provider_overrides(config: dict[str, Any]) -> None:
    """Merge admin-level provider configuration overrides into the config.

    Reads OPENCODE_ADMIN_PROVIDER_OVERRIDE_JSON from the environment.
    Admin can use this to:
      - Force baseURL through a security proxy / LiteLLM
      - Set provider-level timeouts and retry policies
      - Block or redirect specific providers
    """
    raw = os.getenv("OPENCODE_ADMIN_PROVIDER_OVERRIDE_JSON", "").strip()
    if not raw:
        return
    try:
        overrides = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("Failed to parse OPENCODE_ADMIN_PROVIDER_OVERRIDE_JSON; skipping.")
        return
    if not isinstance(overrides, dict):
        return

    provider = config.get("provider")
    if not isinstance(provider, dict):
        provider = {}

    for pid, popts in overrides.items():
        if not isinstance(popts, dict):
            continue
        target = provider.setdefault(pid, {})
        # Deep-merge options dict if both sides have it
        if "options" in popts and "options" in target:
            target_opts = dict(target["options"])
            target_opts.update(popts["options"])
            target["options"] = target_opts
        target.update({k: v for k, v in popts.items() if k != "options"})

    config["provider"] = provider


def _apply_admin_plugin_list(config: dict[str, Any]) -> None:
    """Apply admin-approved plugin allowlist from OPENCODE_PLUGIN_LIST_JSON.

    When the immutable config blocks all plugins (plugin: []), this env var
    is the ONLY way to selectively allow specific admin-vetted plugins.
    An empty list means no plugins; omitting the env var leaves the
    immutable default (typically []) in place.
    """
    raw = os.getenv("OPENCODE_PLUGIN_LIST_JSON", "").strip()
    if not raw:
        return
    try:
        plugins = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("Failed to parse OPENCODE_PLUGIN_LIST_JSON; skipping.")
        return
    if isinstance(plugins, list):
        config["plugin"] = plugins


def _apply_admin_model_override(
    config: dict[str, Any],
    warnings: list[str],
) -> None:
    """Enforce admin-level model allowlist from OPENCODE_ADMIN_MODEL_OVERRIDE_JSON.

    If the currently selected model is not in the admin allowlist, it is
    replaced with the first allowed model. A warning is emitted so
    operators can detect misconfigured agents.
    """
    raw = os.getenv("OPENCODE_ADMIN_MODEL_OVERRIDE_JSON", "").strip()
    if not raw:
        return
    try:
        allowed_models = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("Failed to parse OPENCODE_ADMIN_MODEL_OVERRIDE_JSON; skipping.")
        return
    if not isinstance(allowed_models, list) or not allowed_models:
        return

    allowed_set = {str(m).strip() for m in allowed_models if str(m).strip()}
    if not allowed_set:
        return

    current_model = str(config.get("model", "")).strip()
    if current_model and current_model not in allowed_set:
        fallback = sorted(allowed_set)[0]
        warnings.append(
            f"Model '{current_model}' blocked by OPENCODE_ADMIN_MODEL_OVERRIDE_JSON. "
            f"Falling back to '{fallback}'. Allowed: {sorted(allowed_set)}"
        )
        config["model"] = fallback
        # Also override small_model if it was set to the same blocked model
        if config.get("small_model") == current_model:
            config["small_model"] = fallback


def build_generated_config(
    sidecars: list[dict[str, Any]],
    config_overrides: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """Generate the full OpenCode configuration object."""
    mcp_config, warnings = build_mcp_config(sidecars)
    KUBESYNAPSE_instruction_path = materialize_KUBESYNAPSE_instructions()
    config: dict[str, Any] = {
        "$schema": "https://opencode.ai/config.json",
        "model": DEFAULT_MODEL_REF,
        "small_model": DEFAULT_MODEL_REF,
        "default_agent": DEFAULT_AGENT,
        "permission": "allow",
        "compaction": {
            "auto": True,
            "prune": True,
            "reserved": 10000,
        },
        "server": {
            "hostname": OPENCODE_SERVER_HOST,
            "port": OPENCODE_SERVER_PORT,
        },
        "agent": {
            "build": {
                "steps": DEFAULT_AGENT_STEPS,
            },
            "code": {
                "steps": DEFAULT_AGENT_STEPS,
            },
            "plan": {
                "steps": DEFAULT_AGENT_STEPS,
            },
        },
    }
    if KUBESYNAPSE_instruction_path:
        config["instructions"] = [KUBESYNAPSE_instruction_path]

    provider: dict[str, Any] = {}
    provider_id = DEFAULT_PROVIDER.lower()

    if provider_id == "litellm":
        provider[provider_id] = {
            "npm": "@ai-sdk/openai-compatible",
            "name": DEFAULT_PROVIDER,
            "options": {
                "baseURL": build_litellm_base_url(),
                "apiKey": LITELLM_API_KEY,
            },
            "models": {
                DEFAULT_MODEL: {
                    "name": DEFAULT_MODEL,
                    "limit": {
                        "context": MODEL_CONTEXT_LIMIT,
                        "output": MODEL_OUTPUT_LIMIT,
                    },
                }
            },
        }
    elif provider_id in ("opencode", "opencode-go", "openai-compatible"):
        from providers import get_provider

        prov = get_provider(provider_id)
        provider_block: dict[str, Any] = {
            "npm": "@ai-sdk/openai-compatible",
            "name": provider_id,
        }
        resolved = prov.resolve_env()
        if "OPENAI_BASE_URL" in resolved:
            provider_block.setdefault("options", {})["baseURL"] = resolved["OPENAI_BASE_URL"]
        elif provider_id == "opencode-go":
            provider_block.setdefault("options", {})["baseURL"] = "https://opencode.ai/zen/go/v1"
        elif provider_id == "opencode":
            provider_block.setdefault("options", {})["baseURL"] = "https://opencode.ai/zen/v1"
        # Extract API key from OPENCODE_AUTH_CONTENT if not in env
        api_key = resolved.get("OPENCODE_API_KEY", "")
        if not api_key:
            auth_content = os.getenv("OPENCODE_AUTH_CONTENT", "").strip()
            if auth_content:
                try:
                    auth_data = json.loads(auth_content)
                    for key in (provider_id, provider_id.replace("-go", ""), provider_id.replace("-", "")):
                        entry = auth_data.get(key)
                        if isinstance(entry, dict) and entry.get("type") == "api":
                            api_key = str(entry.get("key", "")).strip()
                            if api_key:
                                break
                except (json.JSONDecodeError, TypeError):
                    pass
        provider_block.setdefault("options", {})["apiKey"] = api_key
        provider_block["models"] = {
            DEFAULT_MODEL: {
                "name": DEFAULT_MODEL,
                "limit": {
                    "context": MODEL_CONTEXT_LIMIT,
                    "output": MODEL_OUTPUT_LIMIT,
                },
            }
        }
        provider[provider_id] = provider_block
    elif provider_id == "copilot":
        from providers import get_provider

        prov = get_provider("copilot")
        provider_block: dict[str, Any] = {
            "npm": "@ai-sdk/openai-compatible",
            "name": "copilot",
        }
        resolved = prov.resolve_env()
        if "GITHUB_TOKEN" in resolved:
            provider_block.setdefault("options", {})["headers"] = {
                "Authorization": f"Bearer {resolved['GITHUB_TOKEN']}"
            }
        provider[provider_id] = provider_block
    elif provider_id == "anthropic":
        from providers import get_provider

        prov = get_provider("anthropic")
        provider_block: dict[str, Any] = {
            "npm": "@ai-sdk/anthropic",
            "name": "anthropic",
        }
        resolved = prov.resolve_env()
        if "ANTHROPIC_API_KEY" in resolved:
            provider_block.setdefault("options", {})["apiKey"] = resolved["ANTHROPIC_API_KEY"]
        provider[provider_id] = provider_block
    elif SELECTED_PROVIDER_JSON:
        try:
            payload = json.loads(SELECTED_PROVIDER_JSON)
            if isinstance(payload, dict):
                provider_id = str(payload.get("id") or DEFAULT_PROVIDER)
                provider_name = str(payload.get("name") or provider_id)
                provider_base_url = str(payload.get("base_url") or "").strip() or None
                provider_headers = payload.get("headers")
                provider_model_list: list[str] = [
                    str(m).strip()
                    for m in (payload.get("models") or [])
                    if str(m).strip()
                ]
                provider_block: dict[str, Any] = {
                    "npm": "@ai-sdk/openai-compatible",
                    "name": provider_name,
                }
                if provider_base_url:
                    provider_block.setdefault("options", {})["baseURL"] = provider_base_url
                if isinstance(provider_headers, dict) and provider_headers:
                    provider_block.setdefault("options", {})["headers"] = {
                        str(k): str(v) for k, v in provider_headers.items()
                    }
                if provider_model_list:
                    provider_block["models"] = {
                        model_id: {
                            "name": model_id,
                            "limit": {
                                "context": MODEL_CONTEXT_LIMIT,
                                "output": MODEL_OUTPUT_LIMIT,
                            },
                        }
                        for model_id in provider_model_list
                    }
                provider[provider_id] = provider_block
        except (json.JSONDecodeError, TypeError, ValueError):
            logger.warning("OPENCODE_SELECTED_PROVIDER_JSON is invalid; skipping custom provider config.")

    if provider:
        config["provider"] = provider
    if mcp_config:
        config["mcp"] = mcp_config
    if config_overrides:
        config = deep_merge_config(config, config_overrides)

    # §security-P1: Layer immutable security constraints on top of runtime
    # config. The immutable ConfigMap provides the security FLOOR — runtime
    # values and user-provided config_overrides cannot relax these.
    immutable_base = _load_immutable_config_base()
    if immutable_base:
        config = _apply_immutable_security_constraints(config, immutable_base)

    # §security-P1: Apply admin env overrides (highest priority). These can
    # override even immutable security constraints for explicit admin-approved
    # exceptions (e.g., allowing a specific vetted plugin).
    _apply_admin_provider_overrides(config)
    _apply_admin_plugin_list(config)
    _apply_admin_model_override(config, warnings)

    return config, warnings


def configure_git_credentials() -> None:
    """Bootstrap git credentials from env vars for bash git operations."""
    auth_method = os.getenv("GIT_AUTH_METHOD", "").strip()
    if not auth_method:
        return

    subprocess.run(
        ["git", "config", "--global", "user.name", "AI Agent"],
        capture_output=True,
        timeout=5,
    )
    subprocess.run(
        ["git", "config", "--global", "user.email", "agent@kubesynapse.local"],
        capture_output=True,
        timeout=5,
    )

    repo_url = os.getenv("GIT_REPO_URL", "").strip()

    if auth_method == "token":
        token = os.getenv("GIT_TOKEN", "").strip()
        if not token:
            logger.warning("GIT_AUTH_METHOD=token but GIT_TOKEN is empty")
            return
        subprocess.run(
            ["git", "config", "--global", "credential.helper", "store"],
            capture_output=True,
            timeout=5,
        )
        cred_path = os.path.expanduser("~/.git-credentials")
        if repo_url and repo_url.startswith("https://"):
            host = repo_url.split("//")[1].split("/")[0]
            cred_line = f"https://oauth2:{token}@{host}\n"
        else:
            cred_line = f"https://oauth2:{token}@github.com\n"
        with open(cred_path, "w") as f:
            f.write(cred_line)
        os.chmod(cred_path, 0o600)
        logger.info("Configured git credential store (token) for bash git operations")

    elif auth_method == "basic":
        username = os.getenv("GIT_USERNAME", "").strip()
        password = os.getenv("GIT_PASSWORD", "").strip()
        if not username or not password:
            logger.warning("GIT_AUTH_METHOD=basic but GIT_USERNAME or GIT_PASSWORD is empty")
            return
        subprocess.run(
            ["git", "config", "--global", "credential.helper", "store"],
            capture_output=True,
            timeout=5,
        )
        cred_path = os.path.expanduser("~/.git-credentials")
        if repo_url and repo_url.startswith("https://"):
            host = repo_url.split("//")[1].split("/")[0]
            cred_line = f"https://{username}:{password}@{host}\n"
        else:
            cred_line = f"https://{username}:{password}@github.com\n"
        with open(cred_path, "w") as f:
            f.write(cred_line)
        os.chmod(cred_path, 0o600)
        logger.info("Configured git credential store (basic) for bash git operations")

    elif auth_method == "ssh":
        ssh_key = os.getenv("GIT_SSH_KEY_PATH", "").strip()
        if ssh_key and os.path.exists(ssh_key):
            subprocess.run(
                [
                    "git",
                    "config",
                    "--global",
                    "core.sshCommand",
                    f"ssh -i {ssh_key} -o StrictHostKeyChecking=accept-new",
                ],
                capture_output=True,
                timeout=5,
            )
            logger.info("Configured git SSH key for bash git operations")
