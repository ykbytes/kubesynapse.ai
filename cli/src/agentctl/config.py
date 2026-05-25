"""Configuration management with profiles and token persistence."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from platformdirs import user_config_dir, user_data_dir

APP_NAME = "agentctl"
APP_VERSION = "0.3.0"
DEFAULT_GATEWAY_URL = "http://localhost:8080"
DEFAULT_NAMESPACE = "default"
DEFAULT_TIMEOUT = 60.0

CONFIG_DIR = Path(user_config_dir(APP_NAME, appauthor=False))
DATA_DIR = Path(user_data_dir(APP_NAME, appauthor=False))
CONFIG_FILE = CONFIG_DIR / "config.yaml"
CREDENTIALS_FILE = DATA_DIR / "credentials.yaml"


@dataclass
class Profile:
    """A named connection profile."""

    name: str = "default"
    gateway_url: str = DEFAULT_GATEWAY_URL
    namespace: str = DEFAULT_NAMESPACE
    timeout: float = DEFAULT_TIMEOUT


@dataclass
class Config:
    """Full CLI configuration with multiple profiles."""

    active_profile: str = "default"
    profiles: dict[str, Profile] = field(default_factory=lambda: {"default": Profile()})

    @property
    def current(self) -> Profile:
        return self.profiles.get(self.active_profile, Profile())


@dataclass(frozen=True)
class ResolvedSettings:
    """Final resolved settings for a single command invocation."""

    gateway_url: str
    token: str
    namespace: str
    timeout: float
    output_format: str  # table, json, yaml, wide, name


def load_config() -> Config:
    """Load config from disk, falling back to defaults."""
    if not CONFIG_FILE.exists():
        return Config()
    try:
        raw = yaml.safe_load(CONFIG_FILE.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return Config()

    active = str(raw.get("active_profile", "default"))
    profiles: dict[str, Profile] = {}
    for name, data in (raw.get("profiles") or {"default": {}}).items():
        if not isinstance(data, dict):
            data = {}
        profiles[str(name)] = Profile(
            name=str(name),
            gateway_url=str(data.get("gateway_url", DEFAULT_GATEWAY_URL)),
            namespace=str(data.get("namespace", DEFAULT_NAMESPACE)),
            timeout=float(data.get("timeout", DEFAULT_TIMEOUT)),
        )
    if active not in profiles:
        active = next(iter(profiles), "default")
    return Config(active_profile=active, profiles=profiles)


def save_config(config: Config) -> None:
    """Persist config to disk."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    data: dict[str, Any] = {
        "active_profile": config.active_profile,
        "profiles": {},
    }
    for name, profile in config.profiles.items():
        data["profiles"][name] = {
            "gateway_url": profile.gateway_url,
            "namespace": profile.namespace,
            "timeout": profile.timeout,
        }
    CONFIG_FILE.write_text(yaml.dump(data, default_flow_style=False), encoding="utf-8")


def load_token(profile_name: str = "default") -> str:
    """Load saved token for a profile."""
    if not CREDENTIALS_FILE.exists():
        return ""
    try:
        raw = yaml.safe_load(CREDENTIALS_FILE.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return ""
    tokens = raw.get("tokens") or {}
    return str(tokens.get(profile_name, ""))


def save_token(token: str, profile_name: str = "default") -> None:
    """Persist token securely for a profile."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    try:
        raw = yaml.safe_load(CREDENTIALS_FILE.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        raw = {}

    tokens = raw.get("tokens") or {}
    tokens[profile_name] = token
    raw["tokens"] = tokens
    CREDENTIALS_FILE.write_text(yaml.dump(raw, default_flow_style=False), encoding="utf-8")

    # Restrict permissions on Unix
    try:
        CREDENTIALS_FILE.chmod(0o600)
    except OSError:
        pass


def clear_token(profile_name: str = "default") -> None:
    """Remove saved token for a profile."""
    if not CREDENTIALS_FILE.exists():
        return
    try:
        raw = yaml.safe_load(CREDENTIALS_FILE.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return
    tokens = raw.get("tokens") or {}
    tokens.pop(profile_name, None)
    raw["tokens"] = tokens
    CREDENTIALS_FILE.write_text(yaml.dump(raw, default_flow_style=False), encoding="utf-8")


def resolve_settings(
    *,
    gateway_url: str | None = None,
    token: str | None = None,
    namespace: str | None = None,
    timeout: float | None = None,
    output_format: str = "table",
    profile: str | None = None,
) -> ResolvedSettings:
    """Resolve final settings from config + env + CLI flags (highest priority)."""
    config = load_config()

    # Profile selection: CLI flag > env > config
    active_profile_name = profile or os.environ.get("AGENTCTL_PROFILE") or config.active_profile
    active = config.profiles.get(active_profile_name, Profile())

    # Gateway URL: CLI flag > env > profile
    resolved_url = (
        gateway_url
        or os.environ.get("AGENT_GATEWAY_URL")
        or os.environ.get("AGENTCTL_GATEWAY_URL")
        or active.gateway_url
    )

    # Token: CLI flag > env > saved credentials
    resolved_token = (
        token
        or os.environ.get("AGENT_GATEWAY_TOKEN")
        or os.environ.get("AGENTCTL_TOKEN")
        or load_token(active_profile_name)
    )

    # Namespace: CLI flag > env > profile
    resolved_ns = (
        namespace or os.environ.get("AGENT_NAMESPACE") or os.environ.get("AGENTCTL_NAMESPACE") or active.namespace
    )

    # Timeout: CLI flag > profile
    resolved_timeout = timeout if timeout is not None else active.timeout

    return ResolvedSettings(
        gateway_url=resolved_url,
        token=resolved_token,
        namespace=resolved_ns,
        timeout=resolved_timeout,
        output_format=output_format,
    )
