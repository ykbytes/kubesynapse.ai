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
    AGENT_SKILL_FILES_ENV,
    DEFAULT_AGENT,
    DEFAULT_AGENT_STEPS,
    DEFAULT_MODEL,
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


def materialize_skill_files() -> tuple[list[str], list[dict[str, str]], list[str]]:
    """Write operator-injected skill files to the OpenCode skills directory.

    Returns (written_files, skill_meta, warnings) where skill_meta is a list of
    dicts with keys ``name``, ``description``, ``file``, and ``content``.
    """
    payload = _parse_json_env(AGENT_SKILL_FILES_ENV)
    if payload is None:
        return [], [], []
    if not isinstance(payload, dict):
        raise RuntimeError(f"{AGENT_SKILL_FILES_ENV} must be a JSON object")

    written_files: list[str] = []
    skill_meta: list[dict[str, str]] = []
    warnings: list[str] = []
    seen_names: set[str] = set()
    skills_root = Path(OPENCODE_CONFIG_DIR) / "skills"

    for raw_path, raw_content in payload.items():
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


def build_generated_config(
    sidecars: list[dict[str, Any]],
    config_overrides: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """Generate the full OpenCode configuration object."""
    mcp_config, warnings = build_mcp_config(sidecars)
    model_ref = f"{DEFAULT_PROVIDER}/{DEFAULT_MODEL}"
    config: dict[str, Any] = {
        "$schema": "https://opencode.ai/config.json",
        "model": model_ref,
        "small_model": model_ref,
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
        "provider": {
            DEFAULT_PROVIDER: {
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
    if mcp_config:
        config["mcp"] = mcp_config
    if config_overrides:
        config = deep_merge_config(config, config_overrides)
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
        ["git", "config", "--global", "user.email", "agent@kubesynth.local"],
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
