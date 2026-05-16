"""Pluggable provider configurations for the OpenCode runtime.

Each provider knows:
- What env vars it needs for the opencode subprocess
- How to map KubeSynapse env vars to opencode env vars
- Default model reference format
- opencode.json config overrides
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("opencode-runtime")


@dataclass(frozen=True)
class EnvMapping:
    """Maps an opencode env var to a KubeSynapse source env var."""

    opencode_env: str
    source_env: str
    required: bool = False


@dataclass(frozen=True)
class ProviderConfig:
    """Configuration for a single LLM provider."""

    id: str
    name: str
    env_mappings: tuple[EnvMapping, ...] = ()
    default_model: str = ""
    config_overrides: dict[str, Any] = field(default_factory=dict)
    description: str = ""

    def resolve_env(self) -> dict[str, str]:
        """Resolve env vars for the opencode subprocess from current environment."""
        result = {}
        for mapping in self.env_mappings:
            value = os.getenv(mapping.source_env, "").strip()
            if not value and mapping.required:
                logger.warning(
                    "Required env var %s (mapped to %s) is not set for provider '%s'",
                    mapping.source_env,
                    mapping.opencode_env,
                    self.id,
                )
            if value:
                result[mapping.opencode_env] = value
        return result

    def build_model_ref(self, model: str) -> str:
        """Build a full model reference like 'provider/model'."""
        if "/" in model:
            return model
        return f"{self.id}/{model}"


# ---------------------------------------------------------------------------
# Provider definitions
# ---------------------------------------------------------------------------

OPENCODE_GO_PROVIDER = ProviderConfig(
    id="opencode",
    name="OpenCode Go",
    env_mappings=(
        EnvMapping(opencode_env="OPENCODE_API_KEY", source_env="OPENCODE_API_KEY", required=True),
    ),
    default_model="gpt-4o",
    description="OpenCode hosted model API (opencode-go provider)",
    config_overrides={
        "provider": {
            "opencode": {
                "baseURL": "https://api.opencode.ai/v1",
            },
        },
    },
)

COPILOT_PROVIDER = ProviderConfig(
    id="copilot",
    name="GitHub Copilot",
    env_mappings=(
        EnvMapping(opencode_env="GITHUB_TOKEN", source_env="GITHUB_TOKEN", required=False),
        EnvMapping(opencode_env="COPILOT_API_KEY", source_env="COPILOT_API_KEY", required=False),
    ),
    default_model="gpt-4o",
    description="GitHub Copilot provider (uses GITHUB_TOKEN or OAuth)",
)

LITELLM_PROVIDER = ProviderConfig(
    id="litellm",
    name="LiteLLM",
    env_mappings=(
        EnvMapping(opencode_env="OPENAI_BASE_URL", source_env="OPENAI_BASE_URL", required=False),
        EnvMapping(opencode_env="OPENAI_API_KEY", source_env="LITELLM_API_KEY", required=True),
    ),
    default_model="gpt-4o-mini",
    description="LiteLLM proxy (OpenAI-compatible API)",
)

OPENAI_COMPATIBLE_PROVIDER = ProviderConfig(
    id="openai-compatible",
    name="OpenAI Compatible",
    env_mappings=(
        EnvMapping(opencode_env="OPENAI_BASE_URL", source_env="OPENAI_BASE_URL", required=True),
        EnvMapping(opencode_env="OPENAI_API_KEY", source_env="OPENAI_API_KEY", required=True),
    ),
    default_model="gpt-4o",
    description="Any OpenAI-compatible API endpoint",
)

ANTHROPIC_PROVIDER = ProviderConfig(
    id="anthropic",
    name="Anthropic",
    env_mappings=(
        EnvMapping(opencode_env="ANTHROPIC_API_KEY", source_env="ANTHROPIC_API_KEY", required=True),
    ),
    default_model="claude-sonnet-4-20250514",
    description="Anthropic Claude API",
)


# ---------------------------------------------------------------------------
# Provider registry
# ---------------------------------------------------------------------------

PROVIDER_REGISTRY: dict[str, ProviderConfig] = {
    "opencode": OPENCODE_GO_PROVIDER,
    "opencode-go": OPENCODE_GO_PROVIDER,
    "copilot": COPILOT_PROVIDER,
    "litellm": LITELLM_PROVIDER,
    "openai-compatible": OPENAI_COMPATIBLE_PROVIDER,
    "anthropic": ANTHROPIC_PROVIDER,
}


def get_provider(provider_id: str) -> ProviderConfig:
    """Get a provider config by ID, falling back to litellm."""
    if provider_id in PROVIDER_REGISTRY:
        return PROVIDER_REGISTRY[provider_id]
    logger.warning("Unknown provider '%s', falling back to 'litellm'", provider_id)
    return PROVIDER_REGISTRY["litellm"]


def list_providers() -> list[str]:
    """List all available provider IDs."""
    return list(PROVIDER_REGISTRY.keys())
