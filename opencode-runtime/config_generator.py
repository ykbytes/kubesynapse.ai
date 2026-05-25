"""DEPRECATED — Superseded by skills.py::build_generated_config (2026-05-25).

This module was the original config generation path for the OpenCode runtime.
It has been replaced by the consolidated config generation in skills.py, which:
  - Starts from the immutable security baseline (OPENCODE_CONFIG file)
  - Layers runtime-generated config on top
  - Applies admin env overrides (OPENCODE_ADMIN_*_JSON)
  - Enforces security floors for plugin, permission, and skills keys

The functions in this module (generate_opencode_config, build_config_content)
are NO LONGER CALLED by the live runtime startup path. They are preserved
for reference only and will be removed in a future release.

If you need to add new config generation features, add them to
skills.py::build_generated_config, not here.

Original docstring follows:
---
Generate opencode.json configuration at runtime.

This module builds the opencode.json configuration file that the opencode
server reads on startup. It merges:
1. Base config (model, system prompt, agent settings)
2. Provider-specific config (API keys, base URLs)
3. MCP server definitions
4. Tool permissions
5. Plugin listings
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from providers import ProviderConfig, get_provider

logger = logging.getLogger("opencode-runtime")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

OPENCODE_SUPPORTED_MODELS: dict[str, list[dict]] = {}
OPENCODE_ADMIN_MODEL_OVERRIDE_JSON = os.getenv("OPENCODE_ADMIN_MODEL_OVERRIDE_JSON", "[]")
OPENCODE_ADMIN_PROVIDER_OVERRIDE_JSON = os.getenv("OPENCODE_ADMIN_PROVIDER_OVERRIDE_JSON", "{}")


def _parse_json_env_safe(name: str, default: Any = None) -> Any:
    """Safely parse a JSON-encoded env var."""
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("Failed to parse JSON from env var %s", name)
        return default


def _merge_provider_config(
    base_overrides: dict[str, Any],
    admin_overrides: dict[str, Any],
) -> dict[str, Any]:
    """Merge admin-level provider config overrides into base config overrides."""
    if not admin_overrides:
        return base_overrides
    merged = dict(base_overrides)
    for provider_id, provider_opts in admin_overrides.items():
        if not isinstance(provider_opts, dict):
            continue
        if provider_id not in merged:
            merged[provider_id] = {}
        merged[provider_id].update(provider_opts)
    return merged


def generate_opencode_config(
    provider_id: str,
    model: str,
    system_prompt: str = "",
    mcp_servers: list[dict[str, Any]] | None = None,
    permissions: dict[str, Any] | None = None,
    agent_definitions: dict[str, Any] | None = None,
    disabled_providers: list[str] | None = None,
) -> dict[str, Any]:
    """Generate the opencode.json configuration dict.

    Args:
        provider_id: The provider to use (e.g., "opencode", "copilot", "litellm")
        model: The model name (with or without provider prefix)
        system_prompt: Default system prompt for the build agent
        mcp_servers: List of MCP server definitions
        permissions: Tool permission policies
        agent_definitions: Custom agent definitions
        disabled_providers: List of providers to disable

    Returns:
        Complete opencode.json config dict
    """
    provider = get_provider(provider_id)
    model_ref = provider.build_model_ref(model)

    config: dict[str, Any] = {
        "model": model_ref,
        "disabled_providers": disabled_providers or [],
    }

    # Provider-specific config overrides (e.g., baseURL for opencode-go)
    admin_overrides = _parse_json_env_safe(OPENCODE_ADMIN_PROVIDER_OVERRIDE_JSON, {})
    merged_overrides = _merge_provider_config(dict(provider.config_overrides), admin_overrides)
    if merged_overrides:
        config["provider"] = merged_overrides

    # Small model for lightweight tasks
    small_model = os.getenv("OPENCODE_SMALL_MODEL", "").strip()
    if small_model:
        config["small_model"] = small_model

    # Agent configuration
    agent_config: dict[str, Any] = {}
    if system_prompt:
        if "build" not in agent_config:
            agent_config["build"] = {}
        agent_config["build"]["systemPrompt"] = system_prompt

    if agent_definitions:
        for agent_name, agent_def in agent_definitions.items():
            if agent_name not in agent_config:
                agent_config[agent_name] = {}
            agent_config[agent_name].update(agent_def)

    if agent_config:
        config["agent"] = agent_config

    # MCP servers
    if mcp_servers:
        config["mcp"] = mcp_servers

    # Tool permissions
    if permissions:
        config["permission"] = permissions

    # Server settings
    config["server"] = {
        "hostname": os.getenv("OPENCODE_CONFIG_SERVER_HOSTNAME", "127.0.0.1"),
        "port": int(os.getenv("OPENCODE_CONFIG_SERVER_PORT", "4096")),
    }

    # Share mode
    share_mode = os.getenv("OPENCODE_SHARE_MODE", "disabled").strip()
    if share_mode in ("manual", "auto"):
        config["share"] = share_mode

    # Plugin list from env
    plugins = _parse_json_env_safe("OPENCODE_PLUGIN_LIST_JSON", [])
    if plugins:
        config["plugin"] = plugins

    return config


def build_config_content(
    provider_id: str,
    model: str,
    system_prompt: str = "",
) -> str:
    """Build the OPENCODE_CONFIG_CONTENT JSON string.

    This is the main entry point called by the supervisor before
    launching the opencode subprocess.
    """
    mcp_servers = _parse_json_env_safe("OPENCODE_MCP_CONNECTIONS_JSON")

    config = generate_opencode_config(
        provider_id=provider_id,
        model=model,
        system_prompt=system_prompt,
        mcp_servers=mcp_servers,
    )

    return json.dumps(config, ensure_ascii=False, indent=2)
