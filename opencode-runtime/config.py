"""Environment configuration and constants for the OpenCode runtime."""

from __future__ import annotations

import json
import logging
import logging.config
import os
import re
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Structured logging
# ---------------------------------------------------------------------------
_LOG_CONFIG: dict[str, Any] = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "json": {
            "()": "logging.Formatter",
            "fmt": '{"timestamp":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","message":"%(message)s"}',
            "datefmt": "%Y-%m-%dT%H:%M:%S",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "json",
            "stream": "ext://sys.stderr",
        },
    },
    "root": {"level": os.getenv("LOG_LEVEL", "INFO").upper(), "handlers": ["console"]},
}
logging.config.dictConfig(_LOG_CONFIG)

logger = logging.getLogger("opencode-runtime")


# ---------------------------------------------------------------------------
# Safe env var parsing helpers
# ---------------------------------------------------------------------------


def _safe_int(env_name: str, default: int) -> int:
    """Parse an integer env var, falling back to *default* on bad values."""
    raw = os.getenv(env_name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except (ValueError, TypeError):
        logger.warning("Invalid integer value for %s=%r, using default %d", env_name, raw, default)
        return default


def _safe_float(env_name: str, default: float) -> float:
    """Parse a float env var, falling back to *default* on bad values."""
    raw = os.getenv(env_name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except (ValueError, TypeError):
        logger.warning("Invalid float value for %s=%r, using default %s", env_name, raw, default)
        return default


# ---------------------------------------------------------------------------
# Request / field limits
# ---------------------------------------------------------------------------
MAX_PROMPT_CHARS = max(_safe_int("OPENCODE_MAX_PROMPT_CHARS", 64000), 1024)
MAX_THREAD_ID_CHARS = max(_safe_int("OPENCODE_MAX_THREAD_ID_CHARS", 128), 16)
MAX_MODEL_CHARS = max(_safe_int("OPENCODE_MAX_MODEL_CHARS", 256), 32)
MAX_SYSTEM_PROMPT_CHARS = max(_safe_int("OPENCODE_MAX_SYSTEM_PROMPT_CHARS", 32000), 512)
MAX_TEAM_CONTEXT_CHARS = max(_safe_int("OPENCODE_MAX_TEAM_CONTEXT_CHARS", 16000), 512)
HTTP_TIMEOUT_SECONDS = max(_safe_float("OPENCODE_HTTP_TIMEOUT_SECONDS", 300.0), 1.0)
SERVER_STARTUP_TIMEOUT_SECONDS = max(_safe_float("OPENCODE_STARTUP_TIMEOUT_SECONDS", 60.0), 5.0)
SERVER_POLL_INTERVAL_SECONDS = max(_safe_float("OPENCODE_STARTUP_POLL_SECONDS", 0.5), 0.1)
DEFAULT_AGENT_STEPS = max(_safe_int("OPENCODE_AGENT_STEPS", 128), 1)
MODEL_CONTEXT_LIMIT = max(_safe_int("OPENCODE_MODEL_CONTEXT_LIMIT", 128000), 2048)
MODEL_OUTPUT_LIMIT = max(_safe_int("OPENCODE_MODEL_OUTPUT_LIMIT", 8192), 256)

# ---------------------------------------------------------------------------
# Service identity
# ---------------------------------------------------------------------------
SERVICE_NAME = os.getenv("AGENT_NAME", "opencode-agent").strip() or "opencode-agent"
SERVICE_NAMESPACE = os.getenv("AGENT_NAMESPACE", "default").strip() or "default"

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
HOME_DIR = os.getenv("HOME", "/app/state/home").strip() or "/app/state/home"
XDG_CONFIG_HOME = os.getenv("XDG_CONFIG_HOME", f"{HOME_DIR}/.config").strip() or f"{HOME_DIR}/.config"
XDG_DATA_HOME = os.getenv("XDG_DATA_HOME", f"{HOME_DIR}/.local/share").strip() or f"{HOME_DIR}/.local/share"
OPENCODE_CONFIG_DIR = (
    os.getenv("OPENCODE_CONFIG_DIR", f"{XDG_CONFIG_HOME}/opencode-profile").strip()
    or f"{XDG_CONFIG_HOME}/opencode-profile"
)
OPENCODE_BIN = os.getenv("OPENCODE_BIN", "opencode").strip() or "opencode"
OPENCODE_WORKDIR = os.getenv("OPENCODE_WORKDIR", "/workspace").strip() or "/workspace"
OPENCODE_SERVER_HOST = os.getenv("OPENCODE_SERVER_HOST", "127.0.0.1").strip() or "127.0.0.1"
OPENCODE_SERVER_PORT = max(_safe_int("OPENCODE_SERVER_PORT", 4096), 1024)

# ---------------------------------------------------------------------------
# Model / Provider
# ---------------------------------------------------------------------------
DEFAULT_PROVIDER = os.getenv("OPENCODE_PROVIDER", "litellm").strip() or "litellm"
DEFAULT_MODEL = (os.getenv("OPENCODE_MODEL") or os.getenv("AGENT_MODEL") or "gpt-4").strip() or "gpt-4"
DEFAULT_SYSTEM_PROMPT = (os.getenv("OPENCODE_SYSTEM_PROMPT") or os.getenv("AGENT_SYSTEM_PROMPT") or "").strip()
DEFAULT_AGENT = os.getenv("OPENCODE_DEFAULT_AGENT", "build").strip() or "build"

# ---------------------------------------------------------------------------
# LiteLLM
# ---------------------------------------------------------------------------
LITELLM_HOST = os.getenv("LITELLM_HOST", "http://localhost:4000").strip() or "http://localhost:4000"
LITELLM_BASE_PATH = os.getenv("LITELLM_BASE_PATH", "v1/chat/completions").strip() or "v1/chat/completions"
LITELLM_API_KEY = os.getenv("LITELLM_API_KEY", "").strip()

# ---------------------------------------------------------------------------
# MCP
# ---------------------------------------------------------------------------
MCP_HUB_NAMESPACE = os.getenv("MCP_HUB_NAMESPACE", "mcp-hub").strip() or "mcp-hub"
MCP_BEARER_TOKEN = os.getenv("MCP_BEARER_TOKEN", "").strip()
GITHUB_MCP_TOKEN = os.getenv("GITHUB_MCP_TOKEN", "").strip()
HELM_RELEASE_NAME = os.getenv("HELM_RELEASE_NAME", "kubesynth").strip() or "kubesynth"

# ---------------------------------------------------------------------------
# Autonomy
# ---------------------------------------------------------------------------
AUTONOMOUS_MAX_RETRIES = max(_safe_int("OPENCODE_AUTONOMOUS_MAX_RETRIES", 3), 0)
AUTONOMOUS_MAX_TURNS = max(_safe_int("OPENCODE_AUTONOMOUS_MAX_TURNS", 50), 1)

# ---------------------------------------------------------------------------
# Artifact / Session limits
# ---------------------------------------------------------------------------
ARTIFACT_COLLECTION_MAX_FILES = max(_safe_int("OPENCODE_ARTIFACT_MAX_FILES", 200), 1)
SESSION_IDLE_TIMEOUT_SECONDS = max(_safe_float("OPENCODE_SESSION_IDLE_TIMEOUT_SECONDS", 15.0), 1.0)
SESSION_IDLE_POLL_SECONDS = max(_safe_float("OPENCODE_SESSION_IDLE_POLL_SECONDS", 0.5), 0.1)
STRUCTURED_OUTPUT_RETRY_COUNT = max(_safe_int("OPENCODE_STRUCTURED_OUTPUT_RETRY_COUNT", 2), 0)
COMPACTION_TOKEN_THRESHOLD = min(max(_safe_float("OPENCODE_COMPACTION_TOKEN_THRESHOLD", 0.75), 0.1), 0.99)
COMPACTION_PRUNE_THRESHOLD = min(max(_safe_float("OPENCODE_COMPACTION_PRUNE_THRESHOLD", 0.50), 0.1), 0.99)
COMPACTION_AGGRESSIVE_THRESHOLD = min(max(_safe_float("OPENCODE_COMPACTION_AGGRESSIVE_THRESHOLD", 0.25), 0.01), 0.99)
COMPACTION_PRESERVE_SYSTEM_PROMPTS = os.getenv("OPENCODE_COMPACTION_PRESERVE_SYSTEM", "true").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
COMPACTION_PRESERVE_TODO_PLANS = os.getenv("OPENCODE_COMPACTION_PRESERVE_TODOS", "true").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
SESSION_ABORT_TIMEOUT_SECONDS = max(_safe_float("OPENCODE_ABORT_TIMEOUT_SECONDS", 30.0), 5.0)
PLAN_AGENT_PROMPT_THRESHOLD = max(_safe_int("OPENCODE_PLAN_THRESHOLD_CHARS", 500), 100)
SESSION_MAX_AGE_SECONDS = max(_safe_int("OPENCODE_SESSION_MAX_AGE_SECONDS", 86400), 60)
SESSION_MAX_ENTRIES = max(_safe_int("OPENCODE_SESSION_MAX_ENTRIES", 1000), 10)
MAX_COMPACTION_ATTEMPTS = max(_safe_int("OPENCODE_MAX_COMPACTION_ATTEMPTS", 2), 1)
COMPACTION_MIN_TURN_SPACING = max(_safe_int("OPENCODE_COMPACTION_MIN_TURN_SPACING", 3), 1)
SESSION_INIT_ON_CREATE = os.getenv("OPENCODE_SESSION_INIT_ON_CREATE", "true").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}

# ---------------------------------------------------------------------------
# Memory (cross-session persistence)
# ---------------------------------------------------------------------------
MEMORY_ENABLED = os.getenv("OPENCODE_MEMORY_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}
MEMORY_MAX_THREAD_ENTRIES = max(_safe_int("OPENCODE_MEMORY_MAX_THREAD_ENTRIES", 100), 10)
MEMORY_MAX_WORKSPACE_ENTRIES = max(_safe_int("OPENCODE_MEMORY_MAX_WORKSPACE_ENTRIES", 50), 5)
MEMORY_DIR = Path(os.getenv("OPENCODE_MEMORY_DIR", f"{XDG_DATA_HOME}/opencode-runtime/memory").strip())

# ---------------------------------------------------------------------------
# Workspace awareness
# ---------------------------------------------------------------------------
WORKSPACE_SNAPSHOT_ENABLED = os.getenv("OPENCODE_WORKSPACE_SNAPSHOT_ENABLED", "true").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
WORKSPACE_SNAPSHOT_MAX_AGE_SECONDS = max(_safe_int("OPENCODE_WORKSPACE_SNAPSHOT_MAX_AGE_SECONDS", 300), 30)
WORKSPACE_SNAPSHOT_DIR = Path(
    os.getenv("OPENCODE_WORKSPACE_SNAPSHOT_DIR", f"{XDG_DATA_HOME}/opencode-runtime/workspace-snapshots").strip()
)

# ---------------------------------------------------------------------------
# Agent selection
# ---------------------------------------------------------------------------
AGENT_SELECTION_MODE = os.getenv("OPENCODE_AGENT_SELECTION_MODE", "smart").strip().lower() or "smart"

# ---------------------------------------------------------------------------
# Static data
# ---------------------------------------------------------------------------
DOWNLOADABLE_ARTIFACT_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".pdf",
        ".md",
        ".txt",
        ".json",
        ".yaml",
        ".yml",
        ".csv",
        ".html",
        ".svg",
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".doc",
        ".docx",
    }
)
ARTIFACT_PATH_PATTERN = re.compile(
    r"(?:^|[\s\"'`(])(?P<path>(?:/[A-Za-z0-9._\-/]+|[A-Za-z0-9._-]+(?:/[A-Za-z0-9._-]+)+)"
    r"(?:\.pdf|\.md|\.txt|\.json|\.yaml|\.yml|\.csv|\.html|\.svg|\.png|\.jpg|\.jpeg|\.gif|\.doc|\.docx))(?=$|[\s\"'`),])",
    re.IGNORECASE,
)

NATIVE_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "bash",
        "read",
        "write",
        "edit",
        "glob",
        "grep",
        "webfetch",
        "websearch",
        "codesearch",
        "skill",
        "question",
        "task",
        "todowrite",
    }
)

SKILL_NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")

# ---------------------------------------------------------------------------
# Environment variable names
# ---------------------------------------------------------------------------
A2A_ALLOWED_CALLERS_ENV = "A2A_ALLOWED_CALLERS_JSON"
AGENT_SKILL_FILES_ENV = "AGENT_SKILL_FILES_JSON"
OPENCODE_RUNTIME_CONFIG_FILES_ENV = "OPENCODE_RUNTIME_CONFIG_FILES_JSON"
OPENCODE_MCP_SIDECARS_ENV = "OPENCODE_MCP_SIDECARS_JSON"

# ---------------------------------------------------------------------------
# Derived constants
# ---------------------------------------------------------------------------
SESSION_MAP_PATH = Path(HOME_DIR) / ".local" / "share" / "opencode-runtime" / "session-map.json"

# Task type -> default agent mapping for smart agent selection
TASK_TYPE_AGENT_MAP: dict[str, str] = {
    "exploration": "explore",
    "debugging": DEFAULT_AGENT,
    "feature": "plan" if DEFAULT_AGENT == "build" else DEFAULT_AGENT,
    "edit": DEFAULT_AGENT,
    "review": "general",
    "refactor": DEFAULT_AGENT,
    "deployment": DEFAULT_AGENT,
    "unknown": DEFAULT_AGENT,
}


def _parse_json_env(name: str) -> Any:
    """Parse a JSON-encoded environment variable."""
    raw_value = os.getenv(name, "").strip()
    if not raw_value:
        return None
    try:
        return json.loads(raw_value)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{name} is not valid JSON") from exc


def _parse_allowed_callers() -> set[tuple[str, str]]:
    """Parse the A2A allowed callers environment variable."""
    payload = _parse_json_env(A2A_ALLOWED_CALLERS_ENV)
    allowed: set[tuple[str, str]] = set()
    if not isinstance(payload, list):
        return allowed
    for item in payload:
        if not isinstance(item, dict):
            continue
        namespace = str(item.get("namespace") or "").strip()
        name = str(item.get("name") or "").strip()
        if namespace and name:
            allowed.add((namespace, name))
    return allowed


A2A_ALLOWED_CALLERS = _parse_allowed_callers()


def build_litellm_base_url() -> str:
    """Build the base URL for the LiteLLM proxy."""
    base = LITELLM_HOST.rstrip("/")
    suffix = LITELLM_BASE_PATH.strip("/")
    if not suffix:
        return base
    if suffix.endswith("chat/completions"):
        suffix = suffix[: -len("chat/completions")].rstrip("/")
    if suffix.endswith("responses"):
        suffix = suffix[: -len("responses")].rstrip("/")
    if not suffix:
        return base
    return f"{base}/{suffix}"


def server_base_url() -> str:
    """Return the base URL for the OpenCode server."""
    return f"http://{OPENCODE_SERVER_HOST}:{OPENCODE_SERVER_PORT}"
