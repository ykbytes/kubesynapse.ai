import asyncio
import contextlib
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextvars import ContextVar
import difflib
import functools
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from collections.abc import AsyncIterator, Callable, Iterator
from typing import Annotated, Any, TypedDict

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
from kubernetes import client as k8s_client  # type: ignore[import-untyped]
from kubernetes import config as k8s_config  # type: ignore[import-untyped]
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from pydantic import BaseModel, Field, SecretStr, model_validator
from prometheus_fastapi_instrumentator import Instrumentator
from pythonjsonlogger import jsonlogger

try:
    import yaml
except ModuleNotFoundError:  # pragma: no cover - covered by runtime packaging
    yaml = None

from env_utils import get_bool_env, get_float_env, get_int_env
from guardrails import GuardrailsEngine
from hitl import hitl_gate
from opensandbox_tools import (
    SandboxToolError,
    execute_sandbox_tool,
    format_tool_payload,
    is_sandbox_tool,
    sandbox_runtime_metadata,
)

try:
    from memory.session_state import SessionStateSnapshot, build_session_state_snapshot
    from memory.session_store import SessionStore, create_session_store
except ModuleNotFoundError:
    current_dir = Path(__file__).resolve().parent
    if str(current_dir) not in sys.path:
        sys.path.insert(0, str(current_dir))
    from memory.session_state import SessionStateSnapshot, build_session_state_snapshot
    from memory.session_store import SessionStore, create_session_store


def configure_logging() -> None:
    log_level = os.getenv("AGENT_LOG_LEVEL", "INFO").upper()
    handler = logging.StreamHandler()
    if get_bool_env("AGENT_JSON_LOGS", True):
        handler.setFormatter(jsonlogger.JsonFormatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    else:
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    logging.basicConfig(level=log_level, handlers=[handler], force=True)


configure_logging()
logger = logging.getLogger("agent-runtime")

K8S_NAME_RE = re.compile(r"^[a-z0-9]([-a-z0-9]*[a-z0-9])?$")


def _run_async(coro: Any) -> Any:
    """Run an async coroutine from synchronous code, handling nested event loops."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop is not None and loop.is_running():
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, coro).result()
    return asyncio.run(coro)


def normalize_a2a_identifier(value: Any, *, source: str) -> str:
    text = str(value).strip()
    if not text:
        raise ValueError(f"{source} must not be blank")
    if len(text) > 63 or not K8S_NAME_RE.fullmatch(text):
        raise ValueError(f"{source} must be a valid lowercase Kubernetes resource name")
    return text


def parse_a2a_peer_ref(raw_value: Any, *, source: str) -> dict[str, str]:
    if not isinstance(raw_value, dict):
        raise ValueError(f"{source} entries must be objects with 'name' and 'namespace' fields")
    return {
        "name": normalize_a2a_identifier(raw_value.get("name", ""), source=f"{source}.name"),
        "namespace": normalize_a2a_identifier(raw_value.get("namespace", ""), source=f"{source}.namespace"),
    }


def parse_a2a_peer_refs(peer_refs: Any, *, source: str) -> list[dict[str, str]]:
    if peer_refs is None:
        return []
    if not isinstance(peer_refs, list):
        raise ValueError(f"{source} must be a list of peer reference objects")

    normalized: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for index, raw_value in enumerate(peer_refs):
        peer_ref = parse_a2a_peer_ref(raw_value, source=f"{source}[{index}]")
        identity = (peer_ref["namespace"], peer_ref["name"])
        if identity in seen:
            continue
        seen.add(identity)
        normalized.append(peer_ref)
    return normalized


def parse_a2a_peer_refs_env(name: str) -> frozenset[tuple[str, str]]:
    raw_value = os.getenv(name, "").strip()
    if not raw_value:
        return frozenset()

    try:
        parsed = json.loads(raw_value)
        peer_refs = parse_a2a_peer_refs(parsed, source=name)
    except (ValueError, json.JSONDecodeError) as exc:
        logger.warning("Ignoring invalid %s value: %s", name, exc)
        return frozenset()

    return frozenset((item["namespace"], item["name"]) for item in peer_refs)


def dedupe_text_items(values: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for raw_value in values:
        value = str(raw_value).strip()
        if not value or value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped


SERVICE_NAME = os.getenv("AGENT_NAME", "agent-runtime")
SERVICE_NAMESPACE = os.getenv("AGENT_NAMESPACE", "default")
MODEL_NAME = os.getenv("AGENT_DEFAULT_MODEL", os.getenv("AGENT_MODEL", "gpt-4")).strip() or "gpt-4"
CONFIGURED_ALLOWED_MODELS: frozenset[str] = frozenset(
    item.strip() for item in os.getenv("AGENT_ALLOWED_MODELS", "").split(",") if item.strip()
)
LITELLM_BASE = os.getenv("LITELLM_API_BASE", "http://ai-agent-sandbox-litellm:4000")
LITELLM_API_KEY = os.getenv("LITELLM_API_KEY", "")
LITELLM_PLACEHOLDER_API_KEY = os.getenv("LITELLM_PLACEHOLDER_API_KEY", "local-litelm-placeholder")
SYSTEM_PROMPT = os.getenv("AGENT_SYSTEM_PROMPT", "").strip()
RAG_ENABLED = get_bool_env("RAG_ENABLED", True)
QDRANT_URL = os.getenv("QDRANT_URL", "http://ai-agent-sandbox-qdrant:6333")
QDRANT_COLLECTION = os.getenv("QDRANT_COLLECTION", "").strip()
EMBEDDING_MODEL = os.getenv("AGENT_EMBEDDING_MODEL", "text-embedding-3-small")
RAG_TOP_K = get_int_env("RAG_TOP_K", 3, minimum=1)
POLICY_CACHE_TTL_SECONDS = get_int_env("AGENT_POLICY_CACHE_TTL_SECONDS", 30, minimum=0)
MAX_PROMPT_CHARS = get_int_env("AGENT_MAX_PROMPT_CHARS", 12000, minimum=1)
MAX_CONTEXT_CHARS = get_int_env("AGENT_MAX_CONTEXT_CHARS", 6000, minimum=512)
MAX_THREAD_ID_CHARS = get_int_env("AGENT_MAX_THREAD_ID_CHARS", 128, minimum=16)
# MCP security: bearer token presented on every outbound MCP HTTP call and
# the allow-list of server types the agent is permitted to invoke.  Both are
# injected by the operator from the mcp-auth Secret and AgentPolicy.
MCP_BEARER_TOKEN = os.getenv("MCP_BEARER_TOKEN", "").strip()
GITHUB_MCP_TOKEN = os.getenv("GITHUB_MCP_TOKEN", "").strip()
MCP_HUB_NAMESPACE = os.getenv("MCP_HUB_NAMESPACE", "mcp-hub").strip()
_raw_allowed = os.getenv("ALLOWED_MCP_SERVERS", "").strip()
ALLOWED_MCP_SERVERS: frozenset[str] = frozenset(s.strip() for s in _raw_allowed.split(",") if s.strip())
A2A_ALLOWED_CALLERS = parse_a2a_peer_refs_env("A2A_ALLOWED_CALLERS_JSON")
A2A_ALLOWED_TARGETS_SNAPSHOT = parse_a2a_peer_refs_env("A2A_ALLOWED_TARGETS_JSON")
A2A_REQUIRE_HITL_DEFAULT = get_bool_env("A2A_REQUIRE_HITL", False)
A2A_MAX_TIMEOUT_SECONDS = get_float_env("A2A_MAX_TIMEOUT_SECONDS", 60.0, minimum=1.0)
MAX_DELEGATION_DEPTH = get_int_env("MAX_DELEGATION_DEPTH", 5, minimum=1)
API_GATEWAY_INTERNAL_URL = os.getenv("API_GATEWAY_INTERNAL_URL", "").strip().rstrip("/")
API_GATEWAY_SHARED_TOKEN = os.getenv("API_GATEWAY_SHARED_TOKEN", "").strip()
TEAM_CONTEXT_MAX_CHARS = get_int_env("A2A_TEAM_CONTEXT_MAX_CHARS", 4096, minimum=256)
TEAMWORK_WORKING_AGREEMENT = (
    "Treat this request as one delegated step in a multi-agent workflow.",
    "Do the subtask directly and return concrete findings or next actions.",
    "Call out blockers, uncertainties, or missing inputs explicitly instead of guessing.",
    "Verify your work before returning results — the caller cannot easily re-check your output.",
    "Stay focused on the delegated objective — do not expand scope or pursue tangential tasks.",
)
MAX_SUBAGENTS = get_int_env("AGENT_MAX_SUBAGENTS", 6, minimum=1)
MAX_SUBAGENT_FILE_CHARS = get_int_env("AGENT_MAX_SUBAGENT_FILE_CHARS", 4000, minimum=256)
MAX_SUBAGENT_METADATA_CHARS = get_int_env("AGENT_MAX_SUBAGENT_METADATA_CHARS", 2048, minimum=256)
SUBAGENT_STRATEGIES = frozenset({"sequential", "parallel"})
MAX_TOOL_ARGS_BYTES = get_int_env("AGENT_MAX_TOOL_ARGS_BYTES", 16384, minimum=512)
MAX_CONCURRENT_REQUESTS = get_int_env("AGENT_MAX_CONCURRENT_REQUESTS", 4, minimum=1)
REQUEST_QUEUE_TIMEOUT_SECONDS = get_float_env("AGENT_REQUEST_QUEUE_TIMEOUT_SECONDS", 5.0, minimum=0.1)
STREAM_EVENT_QUEUE_SIZE = get_int_env("AGENT_STREAM_EVENT_QUEUE_SIZE", 256, minimum=32)
LITELLM_TIMEOUT_SECONDS = get_float_env("AGENT_LITELLM_TIMEOUT_SECONDS", 60.0, minimum=1.0)
EMBEDDING_TIMEOUT_SECONDS = get_float_env("AGENT_EMBEDDING_TIMEOUT_SECONDS", 30.0, minimum=1.0)
RAG_REQUEST_TIMEOUT_SECONDS = get_float_env("AGENT_RAG_TIMEOUT_SECONDS", 10.0, minimum=1.0)
SQLITE_TIMEOUT_SECONDS = get_float_env("AGENT_SQLITE_TIMEOUT_SECONDS", 30.0, minimum=1.0)
MAX_AUTONOMY_STEPS_LIMIT = get_int_env("AGENT_MAX_STEPS_LIMIT", 25, minimum=1)
DEFAULT_MAX_AUTONOMY_STEPS = min(
    get_int_env("AGENT_MAX_STEPS", 8, minimum=1),
    MAX_AUTONOMY_STEPS_LIMIT,
)
AUTONOMY_CONTINUE_ON_ACTION_ERROR = get_bool_env("AGENT_AUTONOMY_CONTINUE_ON_ACTION_ERROR", True)
DOOM_LOOP_THRESHOLD = get_int_env("AGENT_DOOM_LOOP_THRESHOLD", 3, minimum=2)
DOOM_LOOP_WINDOW_SIZE = get_int_env("AGENT_DOOM_LOOP_WINDOW_SIZE", 8, minimum=6)
SUPERVISOR_HISTORY_LIMIT = get_int_env("AGENT_SUPERVISOR_HISTORY_LIMIT", 12, minimum=1)
ADAPTIVE_REPLAN_THRESHOLD = get_int_env("AGENT_REPLAN_FAILURE_THRESHOLD", 2, minimum=1)
MAX_REPLAN_COUNT = get_int_env("AGENT_MAX_REPLAN_COUNT", 3, minimum=1)
MAX_SCRATCHPAD_ENTRIES = get_int_env("AGENT_MAX_SCRATCHPAD_ENTRIES", 30, minimum=1)
DESTRUCTIVE_TOOL_PATTERNS: frozenset[str] = frozenset(
    {
        "filesystem.delete",
    }
)
DESTRUCTIVE_SHELL_COMMANDS: frozenset[str] = frozenset(
    {
        "rm",
        "rmdir",
        "git push",
        "git reset",
        "git clean",
    }
)
TOOL_CACHE_MAX_ENTRIES = get_int_env("AGENT_TOOL_CACHE_MAX_ENTRIES", 64, minimum=1)
AUTO_TEST_TIMEOUT_SECONDS = get_float_env("AGENT_AUTO_TEST_TIMEOUT_SECONDS", 20.0, minimum=1.0)
AUTO_TEST_MAX_OUTPUT_CHARS = get_int_env("AGENT_AUTO_TEST_MAX_OUTPUT_CHARS", 2000, minimum=256)
AUTO_TEST_FIX_RETRIES = get_int_env("AGENT_AUTO_TEST_FIX_RETRIES", 3, minimum=0)
DESTRUCTIVE_ACTION_GATE = get_bool_env("AGENT_DESTRUCTIVE_ACTION_GATE", True)
MAX_EDIT_HISTORY = get_int_env("AGENT_MAX_EDIT_HISTORY", 20, minimum=1)
USE_TOOL_CALLING = get_bool_env("AGENT_USE_TOOL_CALLING", True)
MAX_TOKEN_BUDGET = get_int_env("AGENT_MAX_TOKEN_BUDGET", 0, minimum=0)  # 0 = unlimited
SESSION_STATE_ENABLED = get_bool_env("AGENT_SESSION_STATE_ENABLED", True)
SESSION_STATE_TTL_SECONDS = get_int_env("AGENT_SESSION_TTL_SECONDS", 86400, minimum=0)
SESSION_STATE_MAX_MESSAGES = get_int_env("AGENT_SESSION_MAX_MESSAGES", 24, minimum=1)
SESSION_STATE_MAX_TOOL_RESULTS = get_int_env("AGENT_SESSION_MAX_TOOL_RESULTS", 12, minimum=0)
SESSION_RESERVED_TOKENS = get_int_env("AGENT_SESSION_RESERVED_TOKENS", 1500, minimum=0)
SESSION_TOKEN_BUDGET = get_int_env(
    "AGENT_SESSION_TOKEN_BUDGET",
    MAX_TOKEN_BUDGET if MAX_TOKEN_BUDGET > 0 else 0,
    minimum=0,
)
FUZZY_MATCH_THRESHOLD = get_float_env("AGENT_FUZZY_MATCH_THRESHOLD", 0.85, minimum=0.5)

# Cost per million tokens for common models (input_cost, output_cost)
_MODEL_COST_PER_MILLION: dict[str, tuple[float, float]] = {
    "gpt-4": (30.0, 60.0),
    "gpt-4-turbo": (10.0, 30.0),
    "gpt-4o": (2.5, 10.0),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4.1": (2.0, 8.0),
    "gpt-4.1-mini": (0.4, 1.6),
    "gpt-4.1-nano": (0.1, 0.4),
    "gpt-3.5-turbo": (0.50, 1.50),
    "claude-3-opus": (15.0, 75.0),
    "claude-3-sonnet": (3.0, 15.0),
    "claude-3-haiku": (0.25, 1.25),
    "claude-3.5-sonnet": (3.0, 15.0),
    "claude-3.5-haiku": (0.80, 4.0),
    "claude-sonnet-4": (3.0, 15.0),
    "claude-opus-4": (15.0, 75.0),
    "o1": (15.0, 60.0),
    "o1-mini": (1.10, 4.40),
    "o3": (2.0, 8.0),
    "o3-mini": (1.10, 4.40),
    "o4-mini": (1.10, 4.40),
}


def _calculate_cost_usd(prompt_tokens: int, completion_tokens: int, model: str) -> float:
    """Calculate approximate USD cost from token counts and model name."""
    # Try exact match, then prefix match
    costs = _MODEL_COST_PER_MILLION.get(model)
    if not costs:
        model_lower = model.lower()
        for key, val in _MODEL_COST_PER_MILLION.items():
            if model_lower.startswith(key):
                costs = val
                break
    if not costs:
        return 0.0
    input_cost = (prompt_tokens / 1_000_000) * costs[0]
    output_cost = (completion_tokens / 1_000_000) * costs[1]
    return round(input_cost + output_cost, 6)


SUPERVISOR_RESPONSE_CHARS = min(
    get_int_env("AGENT_SUPERVISOR_RESPONSE_CHARS", MAX_PROMPT_CHARS, minimum=256),
    MAX_PROMPT_CHARS,
)
SKILL_FILES_ENV = "AGENT_SKILL_FILES_JSON"
SKILLS_ROOT = os.getenv("AGENT_SKILLS_ROOT", "/app/state/skills").strip() or "/app/state/skills"
MAX_AGENT_SKILL_FILES = get_int_env("AGENT_MAX_SKILL_FILES", 24, minimum=1)
MAX_AGENT_SKILL_FILE_PATH_CHARS = get_int_env("AGENT_MAX_SKILL_FILE_PATH_CHARS", 256, minimum=32)
MAX_AGENT_SKILL_FILE_CONTENT_CHARS = get_int_env("AGENT_MAX_SKILL_FILE_CONTENT_CHARS", 16000, minimum=512)
MAX_AGENT_SKILL_TOTAL_CHARS = get_int_env("AGENT_MAX_SKILL_TOTAL_CHARS", 64000, minimum=4096)
MAX_AGENT_SKILL_PROMPT_CHARS = get_int_env("AGENT_MAX_SKILL_PROMPT_CHARS", 16000, minimum=512)
BLOCKED_RESPONSE_PREFIX = "Request blocked"
SENSITIVE_STREAM_EVENT_SUFFIXES = (".stdout", ".stderr", ".result")
safe_json_dumps: Callable[..., str] = functools.partial(json.dumps, ensure_ascii=False, sort_keys=True, default=str)
RETRYABLE_HTTP_STATUS_CODES = frozenset({408, 409, 425, 429, 500, 502, 503, 504})
LOCAL_RUNTIME_TOOL_NAMES = frozenset({"local.command.list", "local.command.run"})
DEFAULT_LOCAL_COMMAND_ALLOWLIST = (
    "curl",
    "wget",
    "jq",
    "git",
    "rg",
    "python",
    "pip",
    "tar",
    "unzip",
    "zip",
)
LOCAL_TOOL_DISCOVERY_ENABLED = get_bool_env("AGENT_LOCAL_TOOL_DISCOVERY_ENABLED", True)
LOCAL_TOOL_ALLOWLIST: frozenset[str] = frozenset(
    dedupe_text_items(
        [
            item.strip()
            for item in os.getenv("AGENT_LOCAL_TOOL_ALLOWLIST", ",".join(DEFAULT_LOCAL_COMMAND_ALLOWLIST)).split(",")
            if item.strip()
        ]
    )
)
LOCAL_TOOL_TIMEOUT_SECONDS = get_float_env("AGENT_LOCAL_TOOL_TIMEOUT_SECONDS", 20.0, minimum=1.0)
LOCAL_TOOL_MAX_OUTPUT_CHARS = get_int_env("AGENT_LOCAL_TOOL_MAX_OUTPUT_CHARS", 12000, minimum=512)
LOCAL_TOOL_MAX_ARGS = get_int_env("AGENT_LOCAL_TOOL_MAX_ARGS", 32, minimum=1)
LOCAL_TOOL_MAX_ARG_CHARS = get_int_env("AGENT_LOCAL_TOOL_MAX_ARG_CHARS", 512, minimum=32)
LOCAL_TOOL_ALLOWED_ROOTS = tuple(
    dedupe_text_items(
        [
            item.strip()
            for item in os.getenv("AGENT_LOCAL_TOOL_ALLOWED_ROOTS", "/app/state,/workspace").split(",")
            if item.strip()
        ]
    )
)
LOCAL_TOOL_LIST_LIMIT = get_int_env("AGENT_LOCAL_TOOL_LIST_LIMIT", 32, minimum=1)
AUTONOMY_ACTION_RETRY_LIMIT = get_int_env("AGENT_AUTONOMY_ACTION_RETRY_LIMIT", 2, minimum=0)
AUTONOMY_ACTION_RETRY_BACKOFF_SECONDS = get_float_env("AGENT_AUTONOMY_ACTION_RETRY_BACKOFF_SECONDS", 1.0, minimum=0.0)
AUTONOMY_FAILURE_HISTORY_LIMIT = get_int_env("AGENT_AUTONOMY_FAILURE_HISTORY_LIMIT", 6, minimum=1)


def build_thread_id(prefix: str, *parts: object, max_length: int = MAX_THREAD_ID_CHARS) -> str:
    normalized_parts = [
        re.sub(r"[^a-zA-Z0-9_-]+", "-", str(part).strip()).strip("-_") for part in parts if str(part).strip()
    ]
    normalized_parts = [part for part in normalized_parts if part]
    base = "-".join([prefix, *normalized_parts])
    if len(base) <= max_length:
        return base

    digest = hashlib.sha256(base.encode("utf-8")).hexdigest()[:10]
    keep_length = max(max_length - len(digest) - 1, 1)
    truncated = base[:keep_length].rstrip("-_") or prefix
    return f"{truncated}-{digest}"


def truncate_text(value: str, max_chars: int) -> str:
    text = str(value or "").strip()
    if len(text) <= max_chars:
        return text
    if max_chars <= 3:
        return text[:max_chars]
    return f"{text[: max_chars - 3].rstrip()}..."


def configured_local_tool_roots() -> tuple[str, ...]:
    roots = [os.path.abspath(path) for path in LOCAL_TOOL_ALLOWED_ROOTS if str(path).strip()]
    return tuple(roots)


def default_local_tool_cwd() -> str:
    for candidate in configured_local_tool_roots():
        if os.path.isdir(candidate):
            return candidate
    return os.path.abspath(os.getcwd())


def is_local_runtime_tool(tool_name: str | None) -> bool:
    return bool(tool_name and str(tool_name).strip() in LOCAL_RUNTIME_TOOL_NAMES)


def is_runtime_tool(tool_name: str | None) -> bool:
    return is_sandbox_tool(tool_name) or is_local_runtime_tool(tool_name)


def discover_local_tool_inventory(*, refresh: bool = False) -> dict[str, Any]:
    cached = RUNTIME.get("local_tool_inventory")
    if isinstance(cached, dict) and not refresh:
        return cached

    available_commands: list[dict[str, str]] = []
    if LOCAL_TOOL_DISCOVERY_ENABLED:
        for command in sorted(LOCAL_TOOL_ALLOWLIST)[:LOCAL_TOOL_LIST_LIMIT]:
            resolved_path = shutil.which(command)
            if not resolved_path:
                continue
            available_commands.append({"name": command, "path": resolved_path})

    metadata = {
        "configured": LOCAL_TOOL_DISCOVERY_ENABLED,
        "supportedTools": sorted(LOCAL_RUNTIME_TOOL_NAMES),
        "availableCommands": available_commands,
        "allowlist": list(LOCAL_TOOL_ALLOWLIST),
        "allowedRoots": list(configured_local_tool_roots()),
        "defaultCwd": default_local_tool_cwd(),
        "timeoutSeconds": LOCAL_TOOL_TIMEOUT_SECONDS,
    }
    if RUNTIME is not None:
        RUNTIME["local_tool_inventory"] = metadata
    return metadata


def local_runtime_metadata(*, refresh: bool = False) -> dict[str, Any]:
    metadata = discover_local_tool_inventory(refresh=refresh)
    return json.loads(json.dumps(metadata, default=str))


def supervisor_visible_sandbox_tools() -> list[str]:
    supported = [
        str(item).strip() for item in (sandbox_runtime_metadata().get("supportedTools") or []) if str(item).strip()
    ]
    if not SKILL_RUNTIME_CONFIG.get("skills"):
        return sorted(supported)
    allowed_patterns = SKILL_RUNTIME_CONFIG.get("allowedSandboxToolPatterns") or frozenset()
    return sorted(tool_name for tool_name in supported if skill_allows_sandbox_tool(tool_name, allowed_patterns))


def supervisor_visible_local_runtime() -> dict[str, Any]:
    metadata = local_runtime_metadata()
    if not SKILL_RUNTIME_CONFIG.get("skills"):
        return metadata

    allowed_patterns = SKILL_RUNTIME_CONFIG.get("allowedSandboxToolPatterns") or frozenset()
    supported_tools = [
        tool_name for tool_name in LOCAL_RUNTIME_TOOL_NAMES if skill_allows_sandbox_tool(tool_name, allowed_patterns)
    ]
    visible_commands = metadata.get("availableCommands") if "local.command.run" in supported_tools else []
    return {
        **metadata,
        "supportedTools": sorted(supported_tools),
        "availableCommands": visible_commands,
    }


def normalize_json_object(value: Any, *, field_name: str, max_chars: int) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError(f"{field_name} must be an object when provided")

    encoded = safe_json_dumps(value)
    if len(encoded) > max_chars:
        raise ValueError(f"{field_name} exceeds {max_chars} characters once serialized")

    normalized = json.loads(encoded)
    if not isinstance(normalized, dict):
        raise ValueError(f"{field_name} must serialize to an object")
    return normalized


def parse_model_aliases(value: Any) -> frozenset[str]:
    if value is None:
        return frozenset()
    if isinstance(value, str):
        raw_items = value.split(",")
    elif isinstance(value, (list, tuple, set, frozenset)):
        raw_items = list(value)
    else:
        return frozenset()

    return frozenset(str(item).strip() for item in raw_items if str(item).strip())


def effective_allowed_models(policy_spec: dict[str, Any]) -> frozenset[str]:
    policy_models = parse_model_aliases((policy_spec or {}).get("allowedModels"))
    if CONFIGURED_ALLOWED_MODELS and policy_models:
        allowed = frozenset(item for item in CONFIGURED_ALLOWED_MODELS if item in policy_models)
    elif CONFIGURED_ALLOWED_MODELS:
        allowed = CONFIGURED_ALLOWED_MODELS
    elif policy_models:
        allowed = policy_models
    else:
        allowed = frozenset({MODEL_NAME})

    return frozenset({*allowed, MODEL_NAME})


def resolve_requested_model(requested_model: str | None, policy_spec: dict[str, Any]) -> str:
    requested = str(requested_model or "").strip()
    if not requested:
        return MODEL_NAME

    allowed_models = effective_allowed_models(policy_spec)
    if requested not in allowed_models:
        allowed = ", ".join(sorted(allowed_models))
        raise HTTPException(
            status_code=400,
            detail=(f"Agent '{SERVICE_NAME}' allows models [{allowed}], not '{requested}'."),
        )
    return requested


def normalize_subagent_strategy(value: Any) -> str:
    strategy = str(value or "sequential").strip().lower() or "sequential"
    if strategy not in SUBAGENT_STRATEGIES:
        raise ValueError(f"subagent_strategy must be one of {', '.join(sorted(SUBAGENT_STRATEGIES))}")
    return strategy


def normalize_path_text(value: Any, *, source: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{source} must not be blank")
    if len(text) > 512:
        raise ValueError(f"{source} must not exceed 512 characters")
    return text


def normalize_skill_file_path(value: Any, *, source: str) -> str:
    text = str(value or "").replace("\\", "/").strip()
    if not text:
        raise ValueError(f"{source} must not be blank")
    if len(text) > MAX_AGENT_SKILL_FILE_PATH_CHARS:
        raise ValueError(f"{source} must be {MAX_AGENT_SKILL_FILE_PATH_CHARS} characters or fewer")
    if text.startswith("/"):
        raise ValueError(f"{source} must be relative")

    parts = [part for part in text.split("/") if part]
    if not parts or any(part in {".", ".."} for part in parts):
        raise ValueError(f"{source} is invalid")

    normalized = "/".join(parts)
    if not normalized.lower().endswith(".md"):
        raise ValueError(f"{source} must point to a Markdown file ending in .md")
    return normalized


def split_skill_frontmatter(content: str) -> tuple[str | None, str, str | None]:
    normalized = str(content or "").replace("\r\n", "\n")
    if not normalized.startswith("---\n"):
        return None, normalized, None

    lines = normalized.split("\n")
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            return "\n".join(lines[1:index]), "\n".join(lines[index + 1 :]), None
    return None, normalized, "Skill frontmatter must end with a closing '---' line"


def infer_skill_name(path: str) -> str:
    parts = [part for part in path.split("/") if part]
    if len(parts) >= 2 and parts[-1].lower() == "skill.md":
        return parts[-2].replace("-", " ").strip() or "skill"
    stem = parts[-1].rsplit(".", 1)[0] if parts else "skill"
    return stem.replace("-", " ").strip() or "skill"


def parse_skill_frontmatter(frontmatter: str) -> tuple[dict[str, Any], list[str]]:
    warnings: list[str] = []
    if not frontmatter.strip():
        return {}, warnings

    try:
        if yaml is not None:
            parsed = yaml.safe_load(frontmatter)
        else:
            parsed = json.loads(frontmatter)
    except Exception as exc:
        warnings.append(f"Skill frontmatter is invalid: {exc}")
        return {}, warnings

    if parsed is None:
        return {}, warnings
    if not isinstance(parsed, dict):
        warnings.append("Skill frontmatter must be a YAML or JSON object")
        return {}, warnings
    return parsed, warnings


def skill_metadata_string_list(metadata: dict[str, Any], *keys: str) -> tuple[list[str], list[str]]:
    warnings: list[str] = []
    raw_value: Any = None
    field_name = keys[0] if keys else "value"
    for key in keys:
        if key in metadata:
            raw_value = metadata.get(key)
            field_name = key
            break

    if raw_value is None:
        return [], warnings
    if not isinstance(raw_value, list):
        return [], [f"{field_name} must be a list of strings"]

    normalized: list[str] = []
    seen: set[str] = set()
    for index, item in enumerate(raw_value):
        value = str(item or "").strip()
        if not value:
            continue
        if len(value) > 512:
            warnings.append(f"{field_name}[{index}] must be 512 characters or fewer")
            continue
        if value in seen:
            continue
        seen.add(value)
        normalized.append(value)
    return normalized, warnings


def skill_metadata_bool(metadata: dict[str, Any], *keys: str) -> tuple[bool, list[str]]:
    field_name = keys[0] if keys else "value"
    for key in keys:
        if key not in metadata:
            continue
        field_name = key
        value = metadata.get(key)
        if isinstance(value, bool):
            return value, []
        return False, [f"{field_name} must be a boolean"]
    return False, []


def skill_metadata_a2a_targets(metadata: dict[str, Any], *keys: str) -> tuple[list[dict[str, str]], list[str]]:
    for key in keys:
        if key not in metadata:
            continue
        try:
            return parse_a2a_peer_refs(metadata.get(key), source=key), []
        except ValueError as exc:
            return [], [str(exc)]
    return [], []


def summarize_skill_body(value: str, fallback: str) -> str:
    body = str(value or "").strip()
    if not body:
        return fallback
    return truncate_text(body, 320)


def parse_skill_definition(path: str, content: str) -> dict[str, Any]:
    warnings: list[str] = []
    frontmatter, body, split_warning = split_skill_frontmatter(content)
    if split_warning:
        warnings.append(split_warning)
    metadata, metadata_warnings = parse_skill_frontmatter(frontmatter or "")
    warnings.extend(metadata_warnings)

    raw_name = metadata.get("name")
    if raw_name is not None and not isinstance(raw_name, str):
        warnings.append("name must be a string")
        raw_name = None
    raw_description = metadata.get("description")
    if raw_description is not None and not isinstance(raw_description, str):
        warnings.append("description must be a string")
        raw_description = None

    allowed_sandbox_tools, sandbox_warnings = skill_metadata_string_list(
        metadata,
        "allowedSandboxTools",
        "allowed_sandbox_tools",
    )
    allowed_mcp_servers, mcp_warnings = skill_metadata_string_list(
        metadata,
        "allowedMcpServers",
        "allowed_mcp_servers",
    )
    allowed_a2a_targets, a2a_warnings = skill_metadata_a2a_targets(
        metadata,
        "allowedA2ATargets",
        "allowed_a2a_targets",
    )
    allow_subagents, subagent_warnings = skill_metadata_bool(
        metadata,
        "allowSubagents",
        "allow_subagents",
    )
    goose_builtin_extensions, builtin_warnings = skill_metadata_string_list(
        metadata,
        "gooseBuiltinExtensions",
        "goose_builtin_extensions",
    )
    goose_stdio_extensions, stdio_warnings = skill_metadata_string_list(
        metadata,
        "gooseStdioExtensions",
        "goose_stdio_extensions",
    )
    goose_streamable_http_extensions, http_warnings = skill_metadata_string_list(
        metadata,
        "gooseStreamableHttpExtensions",
        "goose_streamable_http_extensions",
    )
    warnings.extend(sandbox_warnings)
    warnings.extend(mcp_warnings)
    warnings.extend(a2a_warnings)
    warnings.extend(subagent_warnings)
    warnings.extend(builtin_warnings)
    warnings.extend(stdio_warnings)
    warnings.extend(http_warnings)
    warnings = dedupe_text_items(warnings)

    name = str(raw_name or infer_skill_name(path)).strip() or infer_skill_name(path)
    description = str(raw_description or "").strip() or None

    return {
        "path": path,
        "name": name,
        "description": description,
        "body": body.strip(),
        "instructionsPreview": summarize_skill_body(body, description or name),
        "allowedSandboxTools": allowed_sandbox_tools,
        "allowedMcpServers": allowed_mcp_servers,
        "allowedA2ATargets": allowed_a2a_targets,
        "allowSubagents": allow_subagents,
        "gooseBuiltinExtensions": goose_builtin_extensions,
        "gooseStdioExtensions": goose_stdio_extensions,
        "gooseStreamableHttpExtensions": goose_streamable_http_extensions,
        "warnings": warnings,
    }


def render_skill_prompt(skills: list[dict[str, Any]]) -> str:
    if not skills:
        return ""

    sections = [
        "The following file-backed skills are available. Use their guidance when relevant and stay within the declared capability grants.",
    ]
    for skill in skills:
        lines = [f"Skill: {skill.get('name')}"]
        if skill.get("description"):
            lines.append(f"Description: {skill.get('description')}")
        grants: list[str] = []
        if skill.get("allowedSandboxTools"):
            grants.append("Sandbox tools: " + ", ".join(skill.get("allowedSandboxTools") or []))
        if skill.get("allowedMcpServers"):
            grants.append("MCP servers: " + ", ".join(skill.get("allowedMcpServers") or []))
        if skill.get("allowedA2ATargets"):
            grants.append(
                "A2A targets: "
                + ", ".join(
                    f"{item['namespace']}/{item['name']}"
                    for item in (skill.get("allowedA2ATargets") or [])
                    if isinstance(item, dict)
                )
            )
        if skill.get("allowSubagents"):
            grants.append("Specialist subagents: allowed")
        if grants:
            lines.append("Capability grants:")
            lines.extend(f"- {item}" for item in grants)
        if skill.get("body"):
            lines.append("Instructions:")
            lines.append(str(skill.get("body") or "").strip())
        sections.append("\n".join(lines).strip())
    return truncate_text("\n\n".join(section for section in sections if section.strip()), MAX_AGENT_SKILL_PROMPT_CHARS)


def load_skill_runtime_config() -> dict[str, Any]:
    raw_value = os.getenv(SKILL_FILES_ENV, "").strip()
    if not raw_value:
        return {
            "files": {},
            "skills": [],
            "prompt": "",
            "warnings": [],
            "allowedSandboxToolPatterns": frozenset(),
            "allowedMcpServers": frozenset(),
            "allowedA2ATargets": frozenset(),
            "allowSubagents": False,
            "skillFiles": [],
        }

    try:
        parsed = json.loads(raw_value)
    except ValueError as exc:
        warning = f"Ignoring invalid {SKILL_FILES_ENV} value: {exc}"
        logger.warning(warning)
        return {
            "files": {},
            "skills": [],
            "prompt": "",
            "warnings": [warning],
            "allowedSandboxToolPatterns": frozenset(),
            "allowedMcpServers": frozenset(),
            "allowedA2ATargets": frozenset(),
            "allowSubagents": False,
            "skillFiles": [],
        }

    if not isinstance(parsed, dict):
        warning = f"Ignoring invalid {SKILL_FILES_ENV} value: expected a JSON object keyed by Markdown paths"
        logger.warning(warning)
        return {
            "files": {},
            "skills": [],
            "prompt": "",
            "warnings": [warning],
            "allowedSandboxToolPatterns": frozenset(),
            "allowedMcpServers": frozenset(),
            "allowedA2ATargets": frozenset(),
            "allowSubagents": False,
            "skillFiles": [],
        }

    files: dict[str, str] = {}
    skills: list[dict[str, Any]] = []
    warnings: list[str] = []
    sandbox_patterns: set[str] = set()
    allowed_mcp_servers: set[str] = set()
    allowed_a2a_targets: set[tuple[str, str]] = set()
    allow_subagents = False
    total_chars = 0

    for raw_path, raw_content in sorted(parsed.items(), key=lambda item: str(item[0])):
        try:
            path = normalize_skill_file_path(raw_path, source=f"{SKILL_FILES_ENV}.{raw_path}")
        except ValueError as exc:
            warnings.append(str(exc))
            continue
        if not isinstance(raw_content, str):
            warnings.append(f"{SKILL_FILES_ENV}.{path} must be a Markdown string")
            continue
        if not raw_content.strip():
            warnings.append(f"{SKILL_FILES_ENV}.{path} must not be blank")
            continue
        if len(raw_content) > MAX_AGENT_SKILL_FILE_CONTENT_CHARS:
            warnings.append(f"{SKILL_FILES_ENV}.{path} exceeds {MAX_AGENT_SKILL_FILE_CONTENT_CHARS} characters")
            continue
        if len(files) >= MAX_AGENT_SKILL_FILES:
            warnings.append(f"Only the first {MAX_AGENT_SKILL_FILES} skill files were loaded")
            break

        total_chars += len(raw_content)
        if total_chars > MAX_AGENT_SKILL_TOTAL_CHARS:
            warnings.append(
                f"Ignoring {path} because total skill content exceeds {MAX_AGENT_SKILL_TOTAL_CHARS} characters"
            )
            break

        normalized_content = raw_content.replace("\r\n", "\n")
        files[path] = normalized_content
        skill = parse_skill_definition(path, normalized_content)
        skills.append(skill)
        warnings.extend(skill.get("warnings") or [])
        sandbox_patterns.update(
            str(item).strip() for item in (skill.get("allowedSandboxTools") or []) if str(item).strip()
        )
        allowed_mcp_servers.update(
            str(item).strip() for item in (skill.get("allowedMcpServers") or []) if str(item).strip()
        )
        allowed_a2a_targets.update(
            (str(item.get("namespace") or "").strip(), str(item.get("name") or "").strip())
            for item in (skill.get("allowedA2ATargets") or [])
            if isinstance(item, dict)
            and str(item.get("namespace") or "").strip()
            and str(item.get("name") or "").strip()
        )
        allow_subagents = allow_subagents or bool(skill.get("allowSubagents"))

    warnings = dedupe_text_items(warnings)
    return {
        "files": files,
        "skills": skills,
        "prompt": render_skill_prompt(skills),
        "warnings": warnings,
        "allowedSandboxToolPatterns": frozenset(sandbox_patterns),
        "allowedMcpServers": frozenset(allowed_mcp_servers),
        "allowedA2ATargets": frozenset(allowed_a2a_targets),
        "allowSubagents": allow_subagents,
        "skillFiles": sorted(files.keys()),
    }


def materialize_skill_files(skill_files: dict[str, str]) -> list[str]:
    if os.path.isdir(SKILLS_ROOT):
        shutil.rmtree(SKILLS_ROOT, ignore_errors=True)
    os.makedirs(SKILLS_ROOT, exist_ok=True)

    written_files: list[str] = []
    for path, content in sorted(skill_files.items()):
        absolute_path = os.path.join(SKILLS_ROOT, *path.split("/"))
        os.makedirs(os.path.dirname(absolute_path), exist_ok=True)
        with open(absolute_path, "w", encoding="utf-8") as handle:
            handle.write(content.rstrip("\n") + "\n")
        written_files.append(path)
    return written_files


def skill_allows_sandbox_tool(tool_name: str, patterns: frozenset[str]) -> bool:
    if not patterns:
        return False
    for pattern in patterns:
        if pattern == "*" or pattern == tool_name:
            return True
        if pattern.endswith("*") and tool_name.startswith(pattern[:-1]):
            return True
    return False


def skill_block_reason(
    *,
    tool_name: str,
    mcp_server: str,
    a2a_target_agent: str,
    a2a_target_namespace: str,
    subagents: list[Any],
) -> str | None:
    if not SKILL_RUNTIME_CONFIG.get("skills"):
        return None

    if is_runtime_tool(tool_name):
        allowed_patterns = SKILL_RUNTIME_CONFIG.get("allowedSandboxToolPatterns") or frozenset()
        if not skill_allows_sandbox_tool(tool_name, allowed_patterns):
            return f"Runtime tool '{tool_name}' is not granted by the agent's skill files"

    if mcp_server:
        allowed_mcp_servers = SKILL_RUNTIME_CONFIG.get("allowedMcpServers") or frozenset()
        if not allowed_mcp_servers or mcp_server not in allowed_mcp_servers:
            return f"MCP server '{mcp_server}' is not granted by the agent's skill files"

    if a2a_target_agent and a2a_target_namespace:
        allowed_targets = SKILL_RUNTIME_CONFIG.get("allowedA2ATargets") or frozenset()
        if not allowed_targets or (a2a_target_namespace, a2a_target_agent) not in allowed_targets:
            return f"A2A target '{a2a_target_namespace}/{a2a_target_agent}' is not granted by the agent's skill files"

    if subagents:
        if not bool(SKILL_RUNTIME_CONFIG.get("allowSubagents")):
            return "Specialist subagent coordination is not granted by the agent's skill files"
        allowed_targets = SKILL_RUNTIME_CONFIG.get("allowedA2ATargets") or frozenset()
        if not allowed_targets:
            return "Skill files allow specialist subagents but do not grant any A2A targets"
        for subagent in subagents:
            if (subagent.namespace, subagent.name) not in allowed_targets:
                return (
                    f"Subagent target '{subagent.namespace}/{subagent.name}' is not granted by the agent's skill files"
                )

    return None


def parse_iso_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None


def merge_sandbox_sessions(
    current_session: dict[str, Any] | None,
    candidate_session: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not isinstance(candidate_session, dict):
        return current_session
    if not isinstance(current_session, dict):
        return candidate_session

    current_expires = parse_iso_datetime(current_session.get("expires_at"))
    candidate_expires = parse_iso_datetime(candidate_session.get("expires_at"))
    if current_expires and candidate_expires and candidate_expires < current_expires:
        return {**candidate_session, **current_session}
    return {**current_session, **candidate_session}


def parent_directory(path: str) -> str:
    normalized = str(path or "").strip().rstrip("/\\")
    if not normalized:
        return ""

    leading_slash = normalized.startswith("/")
    parts = [part for part in re.split(r"[/\\]+", normalized) if part]
    if len(parts) <= 1:
        return ""

    directory = "/".join(parts[:-1])
    return f"/{directory}" if leading_slash else directory


def dedupe_delegation_chain(values: Any) -> list[dict[str, Any]]:
    if not isinstance(values, list):
        return []

    chain: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for item in values:
        if not isinstance(item, dict):
            continue

        name = str(item.get("name") or "").strip()
        namespace = str(item.get("namespace") or "").strip()
        if not name or not namespace:
            continue

        entry: dict[str, Any] = {"name": name, "namespace": namespace}
        thread_id = str(item.get("threadId") or "").strip()
        request_id = str(item.get("requestId") or "").strip()
        if thread_id:
            entry["threadId"] = truncate_text(thread_id, MAX_THREAD_ID_CHARS)
        if request_id:
            entry["requestId"] = truncate_text(request_id, 128)

        identity = (
            entry["namespace"],
            entry["name"],
            str(entry.get("threadId") or ""),
            str(entry.get("requestId") or ""),
        )
        if identity in seen:
            continue
        seen.add(identity)
        chain.append(entry)
    return chain


def build_inbound_team_context(request: "InvokeRequest") -> dict[str, Any] | None:
    team_context = dict(request.team_context or {})
    if request.caller_agent_name and request.caller_agent_namespace:
        caller_entry: dict[str, Any] = {
            "name": request.caller_agent_name,
            "namespace": request.caller_agent_namespace,
        }
        if request.parent_thread_id:
            caller_entry["threadId"] = request.parent_thread_id
        if request.caller_request_id:
            caller_entry["requestId"] = request.caller_request_id

        existing_caller = team_context.get("caller") if isinstance(team_context.get("caller"), dict) else {}
        team_context["caller"] = {**existing_caller, **caller_entry}
        team_context.setdefault("mode", "delegation")
        if request.prompt.strip():
            team_context.setdefault("objective", truncate_text(request.prompt, 1024))

        working_agreement = team_context.get("workingAgreement")
        if not isinstance(working_agreement, list) or not any(str(item).strip() for item in working_agreement):
            team_context["workingAgreement"] = list(TEAMWORK_WORKING_AGREEMENT)

        existing_chain = (
            team_context.get("delegationChain") if isinstance(team_context.get("delegationChain"), list) else []
        )
        delegation_chain = dedupe_delegation_chain([*existing_chain, caller_entry])
        if delegation_chain:
            team_context["delegationChain"] = delegation_chain

    return team_context or None


def build_outbound_team_context(
    state: "State",
    target_agent: str,
    target_namespace: str,
    target_thread_id: str,
) -> dict[str, Any]:
    team_context = dict(state.get("team_context") or {})
    caller_entry: dict[str, Any] = {
        "name": SERVICE_NAME,
        "namespace": SERVICE_NAMESPACE,
    }
    caller_thread_id = str(state.get("thread_id") or "").strip()
    caller_request_id = REQUEST_ID.get() or str(state.get("caller_request_id") or "").strip()
    if caller_thread_id:
        caller_entry["threadId"] = caller_thread_id
    if caller_request_id:
        caller_entry["requestId"] = caller_request_id

    existing_caller = team_context.get("caller") if isinstance(team_context.get("caller"), dict) else {}
    team_context["caller"] = {**existing_caller, **caller_entry}
    team_context["target"] = {
        "name": target_agent,
        "namespace": target_namespace,
        "threadId": target_thread_id,
    }
    team_context.setdefault("mode", "delegation")

    objective = str(team_context.get("objective") or state.get("request_prompt") or "").strip()
    if objective:
        team_context["objective"] = truncate_text(objective, 1024)

    working_agreement = team_context.get("workingAgreement")
    if not isinstance(working_agreement, list) or not any(str(item).strip() for item in working_agreement):
        team_context["workingAgreement"] = list(TEAMWORK_WORKING_AGREEMENT)

    existing_chain = (
        team_context.get("delegationChain") if isinstance(team_context.get("delegationChain"), list) else []
    )
    delegation_chain = dedupe_delegation_chain([*existing_chain, caller_entry])
    if delegation_chain:
        team_context["delegationChain"] = delegation_chain

    try:
        return (
            normalize_json_object(
                team_context,
                field_name="team_context",
                max_chars=TEAM_CONTEXT_MAX_CHARS,
            )
            or {}
        )
    except ValueError:
        return {
            "mode": "delegation",
            "objective": truncate_text(str(state.get("request_prompt") or ""), 1024),
            "caller": caller_entry,
            "target": {
                "name": target_agent,
                "namespace": target_namespace,
                "threadId": target_thread_id,
            },
            "workingAgreement": list(TEAMWORK_WORKING_AGREEMENT),
            "delegationChain": dedupe_delegation_chain([caller_entry]),
        }


def format_team_context_system_message(team_context: dict[str, Any] | None) -> str:
    if not isinstance(team_context, dict) or not team_context:
        return ""

    lines = ["This request is part of a multi-agent collaboration."]
    caller = team_context.get("caller") if isinstance(team_context.get("caller"), dict) else None
    if caller:
        caller_name = str(caller.get("name") or "").strip()
        caller_namespace = str(caller.get("namespace") or "").strip()
        if caller_name and caller_namespace:
            lines.append(f"Caller agent: {caller_name} in namespace {caller_namespace}.")
        caller_thread = str(caller.get("threadId") or "").strip()
        if caller_thread:
            lines.append(f"Caller thread: {caller_thread}.")

    objective = str(team_context.get("objective") or "").strip()
    if objective:
        lines.append(f"Delegated objective: {objective}")

    working_agreement = [
        str(item).strip()
        for item in (
            team_context.get("workingAgreement") if isinstance(team_context.get("workingAgreement"), list) else []
        )
        if str(item).strip()
    ]
    if working_agreement:
        lines.append("Working agreement:")
        lines.extend(f"- {item}" for item in working_agreement[:5])

    delegation_chain = dedupe_delegation_chain(team_context.get("delegationChain"))
    if delegation_chain:
        lines.append("Delegation chain:")
        for entry in delegation_chain[-4:]:
            label = f"- {entry['name']} ({entry['namespace']})"
            if entry.get("threadId"):
                label = f"{label} thread {entry['threadId']}"
            lines.append(label)

    extra = {
        key: value
        for key, value in team_context.items()
        if key not in {"caller", "target", "objective", "workingAgreement", "delegationChain", "mode"}
    }
    if extra:
        lines.append("Additional collaboration context:")
        lines.append(safe_json_dumps(extra))

    return truncate_text("\n".join(lines), TEAM_CONTEXT_MAX_CHARS)


# ---------------------------------------------------------------------------
# Simple per-target circuit breaker for direct A2A calls
# ---------------------------------------------------------------------------
_A2A_CIRCUIT_FAILURES: dict[tuple[str, str], tuple[int, float]] = {}
_A2A_CIRCUIT_LOCK = threading.Lock()
_A2A_CIRCUIT_THRESHOLD = 3  # consecutive failures before skipping direct
_A2A_CIRCUIT_EVICTION_SECONDS = 3600.0  # evict entries older than 1 hour


def _evict_stale_circuit_entries() -> None:
    """Remove circuit breaker entries that haven't been updated recently."""
    cutoff = time.time() - _A2A_CIRCUIT_EVICTION_SECONDS
    stale = [k for k, (_, ts) in _A2A_CIRCUIT_FAILURES.items() if ts < cutoff]
    for k in stale:
        _A2A_CIRCUIT_FAILURES.pop(k, None)


def _record_a2a_direct_failure(target: tuple[str, str]) -> None:
    with _A2A_CIRCUIT_LOCK:
        _evict_stale_circuit_entries()
        count, _ = _A2A_CIRCUIT_FAILURES.get(target, (0, 0.0))
        _A2A_CIRCUIT_FAILURES[target] = (count + 1, time.time())


def _record_a2a_direct_success(target: tuple[str, str]) -> None:
    with _A2A_CIRCUIT_LOCK:
        _A2A_CIRCUIT_FAILURES.pop(target, None)


def _a2a_direct_circuit_open(target: tuple[str, str]) -> bool:
    with _A2A_CIRCUIT_LOCK:
        entry = _A2A_CIRCUIT_FAILURES.get(target)
        if entry is None:
            return False
        count, last_ts = entry
        if time.time() - last_ts > _A2A_CIRCUIT_EVICTION_SECONDS:
            _A2A_CIRCUIT_FAILURES.pop(target, None)
            return False
        return count >= _A2A_CIRCUIT_THRESHOLD


def gateway_fallback_available() -> bool:
    return bool(API_GATEWAY_INTERNAL_URL and API_GATEWAY_SHARED_TOKEN)


def invoke_direct_a2a_target(
    target_agent: str,
    target_namespace: str,
    payload: dict[str, Any],
    request_id: str,
    timeout_seconds: float,
) -> dict[str, Any]:
    with httpx.Client(
        timeout=timeout_seconds,
        transport=httpx.HTTPTransport(retries=2),
        trust_env=False,
    ) as client:
        response = client.post(
            f"{a2a_runtime_url(target_agent, target_namespace)}/invoke",
            json=payload,
            headers={"x-request-id": request_id},
        )
        response.raise_for_status()
        return response.json()  # type: ignore[no-any-return]


def invoke_gateway_a2a_target(
    target_agent: str,
    target_namespace: str,
    payload: dict[str, Any],
    request_id: str,
    timeout_seconds: float,
) -> dict[str, Any]:
    if not gateway_fallback_available():
        raise RuntimeError("API gateway fallback is not configured for agent runtimes")

    with httpx.Client(
        timeout=timeout_seconds,
        transport=httpx.HTTPTransport(retries=2),
        trust_env=False,
    ) as client:
        response = client.post(
            f"{API_GATEWAY_INTERNAL_URL}/api/agents/{target_agent}/invoke",
            params={"namespace": target_namespace},
            json=payload,
            headers={
                "Authorization": f"Bearer {API_GATEWAY_SHARED_TOKEN}",
                "x-request-id": request_id,
            },
        )
        response.raise_for_status()
        return response.json()  # type: ignore[no-any-return]


def invoke_a2a_target_with_fallback(
    target_agent: str,
    target_namespace: str,
    payload: dict[str, Any],
    request_id: str,
    timeout_seconds: float,
) -> tuple[dict[str, Any], str, str | None]:
    target_key = (target_namespace, target_agent)
    direct_failure: str | None = None

    # Skip direct call if circuit breaker is open for this target.
    if _a2a_direct_circuit_open(target_key):
        direct_failure = f"Circuit breaker open for {target_namespace}/{target_agent} (>{_A2A_CIRCUIT_THRESHOLD} consecutive failures)"
    else:
        try:
            result = invoke_direct_a2a_target(target_agent, target_namespace, payload, request_id, timeout_seconds)
            _record_a2a_direct_success(target_key)
            return result, "direct", None
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code < 500:
                raise
            direct_failure = f"Direct A2A target returned HTTP {exc.response.status_code}"
            _record_a2a_direct_failure(target_key)
        except Exception as exc:
            direct_failure = f"Direct A2A transport failed: {exc}"
            _record_a2a_direct_failure(target_key)

    if not gateway_fallback_available():
        raise RuntimeError(direct_failure)

    logger.warning("%s. Retrying %s/%s through the API gateway.", direct_failure, target_namespace, target_agent)
    try:
        result = invoke_gateway_a2a_target(target_agent, target_namespace, payload, request_id, timeout_seconds)
    except httpx.HTTPStatusError as exc:
        raise RuntimeError(f"{direct_failure}; API gateway fallback returned HTTP {exc.response.status_code}") from exc
    except Exception as exc:
        raise RuntimeError(f"{direct_failure}; API gateway fallback failed: {exc}") from exc
    return result, "gateway", direct_failure


resource = Resource(
    attributes={
        "service.name": SERVICE_NAME,
        "service.namespace": SERVICE_NAMESPACE,
    }
)
trace_provider = TracerProvider(resource=resource)
trace.set_tracer_provider(trace_provider)
otlp_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip()
if otlp_endpoint:
    trace_provider.add_span_processor(
        BatchSpanProcessor(
            OTLPSpanExporter(
                endpoint=otlp_endpoint,
                insecure=otlp_endpoint.startswith("http://"),
            )
        )
    )
tracer = trace.get_tracer(__name__)


@contextlib.asynccontextmanager
async def lifespan(_app: FastAPI):
    await asyncio.to_thread(initialize_runtime)
    try:
        yield
    finally:
        _SHUTDOWN.set()
        await asyncio.to_thread(shutdown_runtime)


app = FastAPI(
    title="AI Agent Runtime",
    description="LangGraph-powered runtime for a single sandboxed AI agent",
    version="1.0.0",
    lifespan=lifespan,
)
Instrumentator().instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)

RUNTIME: dict[str, Any] = {}
RUNTIME_LOCK = threading.Lock()
DISCOVERED_QDRANT_COLLECTION = QDRANT_COLLECTION or None
DISCOVERED_QDRANT_LOCK = threading.Lock()
INVOCATION_SLOTS = threading.BoundedSemaphore(MAX_CONCURRENT_REQUESTS)
POLICY_CACHE: dict[str, Any] = {"timestamp": 0.0, "name": None, "spec": {}}
POLICY_CACHE_LOCK = threading.Lock()
K8S_POLICY_ACCESS = False
_SHUTDOWN = threading.Event()
SKILL_RUNTIME_CONFIG: dict[str, Any] = {
    "files": {},
    "skills": [],
    "prompt": "",
    "warnings": [],
    "allowedSandboxToolPatterns": frozenset(),
    "allowedMcpServers": frozenset(),
    "allowedA2ATargets": frozenset(),
    "allowSubagents": False,
    "skillFiles": [],
}
EVENT_PUBLISHER: ContextVar[Callable[[str, dict[str, Any]], None] | None] = ContextVar(
    "event_publisher",
    default=None,
)
REQUEST_ID: ContextVar[str | None] = ContextVar("request_id", default=None)
_WARNED_LITELLM_PLACEHOLDER = False


@app.middleware("http")
async def bind_request_context(request: Request, call_next):
    request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
    token = REQUEST_ID.set(request_id)
    try:
        response = await call_next(request)
    finally:
        REQUEST_ID.reset(token)
    response.headers["x-request-id"] = request_id
    return response


class SubagentFileRef(BaseModel):
    path: str = Field(max_length=512)
    purpose: str | None = Field(default=None, max_length=256)
    include_content: bool = True
    max_chars: int = Field(default=MAX_SUBAGENT_FILE_CHARS, ge=128, le=MAX_SUBAGENT_FILE_CHARS)

    @model_validator(mode="after")
    def normalize_fields(self) -> "SubagentFileRef":
        self.path = normalize_path_text(self.path, source="subagents[].input_files[].path")
        self.purpose = self.purpose.strip() or None if self.purpose is not None else None
        return self


class SubagentRequest(BaseModel):
    name: str = Field(max_length=63)
    namespace: str = Field(max_length=63)
    role: str | None = Field(default=None, max_length=128)
    task: str | None = Field(default=None, max_length=MAX_PROMPT_CHARS)
    input_files: list[SubagentFileRef] = Field(default_factory=list)
    result_file_path: str | None = Field(default=None, max_length=512)
    share_sandbox_session: bool = True
    metadata: dict[str, Any] | None = None
    timeout_seconds: float | None = Field(default=None, ge=1.0)

    @model_validator(mode="after")
    def normalize_fields(self) -> "SubagentRequest":
        self.name = normalize_a2a_identifier(self.name, source="subagents[].name")
        self.namespace = normalize_a2a_identifier(self.namespace, source="subagents[].namespace")
        self.role = self.role.strip() or None if self.role is not None else None
        self.task = self.task.strip() or None if self.task is not None else None
        self.result_file_path = (
            normalize_path_text(self.result_file_path, source="subagents[].result_file_path")
            if self.result_file_path is not None
            else None
        )
        self.metadata = normalize_json_object(
            self.metadata,
            field_name="subagents[].metadata",
            max_chars=MAX_SUBAGENT_METADATA_CHARS,
        )
        return self


class State(TypedDict, total=False):
    thread_id: str
    messages: Annotated[list[Any], add_messages]
    request_prompt: str
    delegated_prompt: str
    context: str
    team_context: dict[str, Any] | None
    subagents: list[dict[str, Any]]
    subagent_strategy: str
    autonomy_enabled: bool
    selected_model: str
    max_steps: int
    step_count: int
    stop_reason: str
    last_action_fingerprint: str
    repeat_action_count: int
    invoke_status: str
    policy_name: str
    policy: dict[str, Any]
    system_prompt: str
    tool_name: str
    tool_args: dict[str, Any]
    tool_result: Any
    available_local_commands: list[dict[str, Any]]
    sandbox_session: dict[str, Any] | None
    approval_name: str | None
    retry_after_seconds: int | None
    warnings: list[str]
    last_step_error: dict[str, Any] | None
    recent_failures: list[dict[str, Any]]
    attempted_actions: list[dict[str, Any]]
    action_fingerprints: list[str]
    doom_loop_warned: bool
    a2a: dict[str, Any] | None
    subagent_results: dict[str, Any] | None
    a2a_target_agent: str
    a2a_target_namespace: str
    a2a_timeout_seconds: float | None
    caller_agent_name: str
    caller_agent_namespace: str
    parent_thread_id: str
    caller_request_id: str
    # Plan tracking — stores the agent's explicit multi-step plan
    active_plan: list[str]
    plan_step_index: int
    # Workspace profile — auto-detected project context for first-step orientation
    workspace_profile: dict[str, Any] | None
    workspace_scanned: bool
    # Files modified during this autonomous session (for change summary)
    files_modified: list[str]
    # Session scratchpad — agent can append notes that persist across steps
    scratchpad: list[str]
    # Adaptive re-planning — tracks how many times the agent has replanned
    replan_count: int
    # Consecutive failures counter (for adaptive re-planning trigger)
    consecutive_failures: int
    # Token usage tracking — accumulated prompt/completion/total tokens
    token_usage: dict[str, int]
    # Edit history for undo/rollback — LIFO stack of {path, content} snapshots
    edit_history: list[dict[str, str]]
    # MCP tool invocation fields – populated by invoke_graph when the caller
    # sets mcp_server on InvokeRequest.  The mcp_tool graph node reads these.
    # Pre-authorized destructive actions (e.g. ['git push']) — bypasses HITL gate
    pre_authorized_actions: list[str]
    mcp_server: str
    mcp_tool_name: str
    mcp_tool_args: dict[str, Any]
    # Artifacts and tool call records collected during invocation
    artifacts: list[dict[str, Any]]
    tool_call_records: list[dict[str, Any]]


class InvokeRequest(BaseModel):
    prompt: str = Field(default="", max_length=MAX_PROMPT_CHARS)
    thread_id: str | None = Field(default=None, max_length=MAX_THREAD_ID_CHARS)
    model: str | None = Field(default=None, max_length=128)
    max_steps: int | None = Field(default=None, ge=1, le=MAX_AUTONOMY_STEPS_LIMIT)
    require_approval: bool = False
    approval_action: str | None = Field(default=None, max_length=512)
    tool_name: str = Field(default="", max_length=128)
    tool_args: dict[str, Any] = Field(default_factory=dict)
    sandbox_session: dict[str, Any] | None = None
    a2a_target_agent: str | None = Field(default=None, max_length=63)
    a2a_target_namespace: str | None = Field(default=None, max_length=63)
    a2a_timeout_seconds: float | None = Field(default=None, ge=1.0)
    caller_agent_name: str | None = Field(default=None, max_length=63)
    caller_agent_namespace: str | None = Field(default=None, max_length=63)
    parent_thread_id: str | None = Field(default=None, max_length=MAX_THREAD_ID_CHARS)
    caller_request_id: str | None = Field(default=None, max_length=128)
    team_context: dict[str, Any] | None = None
    subagents: list[SubagentRequest] = Field(default_factory=list)
    subagent_strategy: str = Field(default="sequential", max_length=16)
    delegation_depth: int = Field(
        default=0, ge=0, le=10, description="Current delegation depth for preventing infinite recursion."
    )
    mcp_server: str | None = Field(
        default=None,
        max_length=128,
        description=(
            "MCP server type to call (e.g. 'github', 'prometheus'). "
            "When set, the request is routed to the mcp_tool graph node "
            "instead of the normal chat/RAG path."
        ),
    )
    pre_authorized_actions: list[str] = Field(
        default_factory=list,
        description=(
            "Shell command prefixes pre-authorized to bypass the destructive "
            "action gate (e.g. ['git push']). Used by workflow orchestrators "
            "to allow specific destructive operations without HITL approval."
        ),
    )

    @model_validator(mode="after")
    def validate_payload_size(self) -> "InvokeRequest":
        self.prompt = self.prompt.strip()
        self.thread_id = self.thread_id.strip() or None if self.thread_id is not None else None
        self.model = self.model.strip() or None if self.model is not None else None
        self.approval_action = self.approval_action.strip() or None if self.approval_action is not None else None
        self.tool_name = self.tool_name.strip()
        self.a2a_target_agent = self.a2a_target_agent.strip() or None if self.a2a_target_agent is not None else None
        self.a2a_target_namespace = (
            self.a2a_target_namespace.strip() or None if self.a2a_target_namespace is not None else None
        )
        self.caller_agent_name = self.caller_agent_name.strip() or None if self.caller_agent_name is not None else None
        self.caller_agent_namespace = (
            self.caller_agent_namespace.strip() or None if self.caller_agent_namespace is not None else None
        )
        self.parent_thread_id = self.parent_thread_id.strip() or None if self.parent_thread_id is not None else None
        self.caller_request_id = self.caller_request_id.strip() or None if self.caller_request_id is not None else None
        self.mcp_server = self.mcp_server.strip() or None if self.mcp_server is not None else None

        prompt = self.prompt
        tool_name = self.tool_name
        mcp_server = self.mcp_server or ""
        a2a_target_agent = self.a2a_target_agent or ""
        a2a_target_namespace = self.a2a_target_namespace or ""
        self.subagent_strategy = normalize_subagent_strategy(self.subagent_strategy)

        if not prompt and not tool_name and not self.subagents:
            raise ValueError("prompt must not be blank unless tool_name or subagents are provided")

        if self.subagents and len(self.subagents) > MAX_SUBAGENTS:
            raise ValueError(f"subagents cannot exceed {MAX_SUBAGENTS} entries")

        if self.subagents and not prompt and not any(item.task for item in self.subagents):
            raise ValueError("prompt must not be blank when subagents do not provide explicit tasks")

        if mcp_server and not tool_name:
            raise ValueError("tool_name is required when mcp_server is provided")

        if mcp_server and is_runtime_tool(tool_name):
            raise ValueError("runtime tools cannot be invoked through mcp_server")

        if a2a_target_agent or a2a_target_namespace:
            if not a2a_target_agent or not a2a_target_namespace:
                raise ValueError("a2a_target_agent and a2a_target_namespace must be provided together")
            normalize_a2a_identifier(a2a_target_agent, source="a2a_target_agent")
            normalize_a2a_identifier(a2a_target_namespace, source="a2a_target_namespace")
            if tool_name:
                raise ValueError("a2a_target_* cannot be combined with tool_name")
            if mcp_server:
                raise ValueError("a2a_target_* cannot be combined with mcp_server")

        if self.subagents:
            if tool_name:
                raise ValueError("subagents cannot be combined with tool_name")
            if mcp_server:
                raise ValueError("subagents cannot be combined with mcp_server")
            if a2a_target_agent or a2a_target_namespace:
                raise ValueError("subagents cannot be combined with a2a_target_*")

        if self.caller_agent_name or self.caller_agent_namespace:
            if not self.caller_agent_name or not self.caller_agent_namespace:
                raise ValueError("caller_agent_name and caller_agent_namespace must be provided together")
            normalize_a2a_identifier(self.caller_agent_name, source="caller_agent_name")
            normalize_a2a_identifier(self.caller_agent_namespace, source="caller_agent_namespace")

        if not prompt and tool_name and not mcp_server and not is_sandbox_tool(tool_name):
            raise ValueError(f"Unsupported tool_name '{tool_name}'")

        encoded_args = json.dumps(self.tool_args, default=str)
        if len(encoded_args.encode("utf-8")) > MAX_TOOL_ARGS_BYTES:
            raise ValueError(f"tool_args exceeds {MAX_TOOL_ARGS_BYTES} bytes")

        if self.sandbox_session is not None:
            json.dumps(self.sandbox_session, default=str)
        self.team_context = normalize_json_object(
            self.team_context,
            field_name="team_context",
            max_chars=TEAM_CONTEXT_MAX_CHARS,
        )

        return self


class InvokeResponse(BaseModel):
    thread_id: str
    response: str
    context: str = ""
    model: str
    step_count: int = 0
    stop_reason: str | None = None
    policy_name: str | None = None
    tool_name: str | None = None
    tool_result: Any = None
    sandbox_session: dict[str, Any] | None = None
    status: str = "completed"
    approval_name: str | None = None
    retry_after_seconds: int | None = None
    a2a: dict[str, Any] | None = None
    subagents: dict[str, Any] | None = None
    warnings: list[str] = Field(default_factory=list)
    artifacts: list[dict[str, Any]] = Field(default_factory=list)
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] | None = None
    token_usage: dict[str, int] | None = None


def persist_session_snapshot(
    agent_state: dict[str, Any], *, session_store: SessionStore | None
) -> SessionStateSnapshot | None:
    if not SESSION_STATE_ENABLED or session_store is None:
        return None
    snapshot = build_session_state_snapshot(
        agent_state,
        session_id=str(agent_state.get("thread_id") or "").strip() or None,
        ttl_seconds=SESSION_STATE_TTL_SECONDS,
        max_token_budget=SESSION_TOKEN_BUDGET,
        reserved_tokens=SESSION_RESERVED_TOKENS,
        max_messages=SESSION_STATE_MAX_MESSAGES,
        max_tool_results=SESSION_STATE_MAX_TOOL_RESULTS,
    )
    saved = session_store.save(snapshot)
    session_store.delete_expired()
    return saved


def configure_kubernetes_access() -> None:
    global K8S_POLICY_ACCESS
    try:
        try:
            k8s_config.load_incluster_config()
            logger.info("Loaded in-cluster Kubernetes config for runtime policy lookups.")
        except Exception:
            k8s_config.load_kube_config()
            logger.info("Loaded local kubeconfig for runtime policy lookups.")
        K8S_POLICY_ACCESS = True
    except Exception as exc:
        K8S_POLICY_ACCESS = False
        logger.warning("Kubernetes policy lookups unavailable: %s", exc)


def get_message_content(message: Any) -> str:
    if message is None:
        return ""
    content = getattr(message, "content", message)
    if isinstance(content, list):
        parts = [extract_content_part(item) for item in content]
        return " ".join(part for part in parts if part).strip()
    return str(content)


def extract_content_part(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in ("text", "content", "value"):
            text_value = value.get(key)
            if isinstance(text_value, str) and text_value.strip():
                return text_value
    return str(value)


def current_event_publisher() -> Callable[[str, dict[str, Any]], None] | None:
    return EVENT_PUBLISHER.get()


def publish_runtime_event(event: str, payload: dict[str, Any]) -> None:
    publisher = current_event_publisher()
    if publisher is not None:
        event_payload = dict(payload)
        request_id = REQUEST_ID.get()
        if request_id and "request_id" not in event_payload:
            event_payload["request_id"] = request_id
        publisher(event, event_payload)


@contextlib.contextmanager
def bind_event_publisher(
    publish_event: Callable[[str, dict[str, Any]], None] | None,
) -> Iterator[None]:
    token = EVENT_PUBLISHER.set(publish_event)
    try:
        yield
    finally:
        EVENT_PUBLISHER.reset(token)


def emit_node_event(node_name: str, status: str, **payload: Any) -> None:
    event_payload = {"node": node_name, "status": status}
    event_payload.update({key: value for key, value in payload.items() if value is not None})
    publish_runtime_event("graph.node", event_payload)


def run_graph_node(node_name: str, operation: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    emit_node_event(node_name, "started")
    try:
        result = operation()
    except Exception as exc:
        emit_node_event(node_name, "failed", error=str(exc))
        raise

    emit_node_event(node_name, "completed", invoke_status=result.get("invoke_status"))
    return result


def build_litellm_client(model_name: str) -> ChatOpenAI:
    global _WARNED_LITELLM_PLACEHOLDER

    litellm_api_key = LITELLM_API_KEY or LITELLM_PLACEHOLDER_API_KEY
    if not LITELLM_API_KEY and not _WARNED_LITELLM_PLACEHOLDER:
        logger.warning(
            "LITELLM_API_KEY is not set; using a placeholder client key for base URL %s.",
            LITELLM_BASE,
        )
        _WARNED_LITELLM_PLACEHOLDER = True

    return ChatOpenAI(
        model=model_name,
        base_url=LITELLM_BASE,
        api_key=SecretStr(litellm_api_key),
        timeout=LITELLM_TIMEOUT_SECONDS,
        max_retries=2,
    )


def get_llm_client(model_name: str) -> ChatOpenAI:
    cached_clients = RUNTIME.get("llm_clients")
    if isinstance(cached_clients, dict) and model_name in cached_clients:
        return cached_clients[model_name]

    with RUNTIME_LOCK:
        cached_clients = RUNTIME.setdefault("llm_clients", {})
        if model_name not in cached_clients:
            cached_clients[model_name] = build_litellm_client(model_name)
        return cached_clients[model_name]


def infer_message_role(message: Any) -> str:
    type_name = type(message).__name__.lower()
    if "human" in type_name:
        return "user"
    if "system" in type_name:
        return "system"
    return "assistant"


def _is_decision_anchor(message: Any) -> bool:
    """Detect messages that represent important decisions/plans worth preserving."""
    content = get_message_content(message)
    if not content:
        return False
    lower = content.lower()
    # Plan messages
    if lower.startswith("plan created with"):
        return True
    # Reflection messages (lessons learned)
    if lower.startswith("reflection:"):
        return True
    # Scratchpad notes
    if lower.startswith("note saved:"):
        return True
    return False


def _estimate_tokens(text: str) -> int:
    """Approximate token count: ~4 chars per token for English text."""
    return max(len(text) // 4, 1)


CONTEXT_WINDOW_TOKEN_LIMIT = get_int_env("AGENT_CONTEXT_WINDOW_TOKENS", 32000, minimum=4096)


def summarize_message_history(
    messages: list[Any],
    limit: int = SUPERVISOR_HISTORY_LIMIT,
    token_budget: int = 0,
) -> list[dict[str, str]]:
    """Keep first message (objective context) and last messages in full; compress middle.

    Decision anchors (plans, reflections, notes) are preserved through compression.
    When token_budget > 0, adaptively compresses to fit within budget.
    """
    raw: list[dict[str, str]] = []
    for message in messages or []:
        content = truncate_text(get_message_content(message), MAX_CONTEXT_CHARS)
        if not content:
            continue
        raw.append({"role": infer_message_role(message), "content": content})

    if len(raw) <= limit:
        # Check token budget even if under message count limit
        if token_budget > 0:
            total_tokens = sum(_estimate_tokens(m["content"]) for m in raw)
            if total_tokens > token_budget:
                # Progressively truncate longest messages
                while total_tokens > token_budget and raw:
                    longest_idx = max(range(1, len(raw)), key=lambda i: len(raw[i]["content"]), default=0)
                    if longest_idx == 0:
                        break
                    old_content = raw[longest_idx]["content"]
                    half = max(len(old_content) // 2, 100)
                    raw[longest_idx]["content"] = old_content[:half] + "\n...[truncated]"
                    total_tokens = sum(_estimate_tokens(m["content"]) for m in raw)
        return raw

    # preserve first message (objective) + last (limit - 2) messages; compress middle
    keep_tail = max(limit - 2, 1)
    first = raw[:1]
    middle = raw[1:-keep_tail] if keep_tail < len(raw) - 1 else []
    tail = raw[-keep_tail:]

    compressed_middle: list[dict[str, str]] = []
    if middle:
        # Separate decision anchors from compressible messages
        anchors: list[dict[str, str]] = []
        summaries: list[str] = []
        for idx, item in enumerate(middle):
            msg = (messages or [])[idx + 1] if idx + 1 < len(messages or []) else None
            if msg is not None and _is_decision_anchor(msg):
                anchors.append(item)
            else:
                line = item["content"]
                if len(line) > 120:
                    line = line[:117] + "..."
                summaries.append(f"[{item['role']}] {line}")

        if summaries:
            compressed_middle.append(
                {
                    "role": "system",
                    "content": f"[{len(summaries)} earlier messages compressed]\n" + "\n".join(summaries),
                }
            )
        # Re-insert decision anchors after the compression summary
        compressed_middle.extend(anchors)

    result = first + compressed_middle + tail

    # Token budget enforcement on the compressed result
    if token_budget > 0:
        total_tokens = sum(_estimate_tokens(m["content"]) for m in result)
        if total_tokens > token_budget:
            # Drop compressed middle first, then truncate tail messages
            if compressed_middle:
                result = first + tail
                total_tokens = sum(_estimate_tokens(m["content"]) for m in result)
            while total_tokens > token_budget and len(result) > 2:
                # Truncate the longest message (not the first)
                longest_idx = max(range(1, len(result)), key=lambda i: len(result[i]["content"]))
                old_content = result[longest_idx]["content"]
                half = max(len(old_content) // 2, 100)
                result[longest_idx]["content"] = old_content[:half] + "\n...[truncated]"
                total_tokens = sum(_estimate_tokens(m["content"]) for m in result)

    return result


def build_progress_summary(attempted_actions: list[dict[str, Any]]) -> str:
    """Auto-generate a step-by-step progress summary from the action trail."""
    if not attempted_actions:
        return ""
    lines: list[str] = []
    for idx, record in enumerate(attempted_actions[-12:], 1):
        label = record.get("label", "action")
        status = record.get("status", "unknown")
        thinking = record.get("thinking", "")
        line = f"Step {idx}: {label} -> {status}"
        if thinking:
            line += f" (reasoning: {thinking[:80]}{'...' if len(thinking) > 80 else ''})"
        lines.append(line)
    return "\n".join(lines)


def format_plan_status(plan_steps: list[str], current_index: int) -> str:
    """Format the active plan with progress markers for the supervisor payload."""
    if not plan_steps:
        return ""
    lines: list[str] = []
    for idx, step in enumerate(plan_steps):
        if idx < current_index:
            marker = "[done]"
        elif idx == current_index:
            marker = "[current]"
        else:
            marker = "[pending]"
        lines.append(f"  {marker} {idx + 1}. {step}")
    return "Active plan:\n" + "\n".join(lines)


def _build_file_tree(execute_sandbox_tool: Callable, max_depth: int = 3) -> str:
    """Build a compact file tree by listing directories up to *max_depth* levels."""
    lines: list[str] = []

    def _ls_dir(path: str, depth: int, prefix: str) -> None:
        if depth > max_depth or len(lines) > 120:
            return
        try:
            ls_result = execute_sandbox_tool("filesystem.ls", {"path": path})
            ls_text = (
                get_message_content((ls_result.get("messages") or [None])[-1]).strip()
                if ls_result.get("messages")
                else ""
            )
        except Exception:
            return
        if not ls_text or ls_text.startswith(BLOCKED_RESPONSE_PREFIX):
            return
        entries = [e.strip() for e in ls_text.replace("\n", ",").split(",") if e.strip()]
        for entry in entries:
            if entry.startswith(".") and entry not in (".gitignore", ".env.example"):
                continue
            if entry in ("node_modules", "__pycache__", ".git", "venv", ".venv", "dist", "build"):
                lines.append(f"{prefix}{entry}/  [skipped]")
                continue
            lines.append(f"{prefix}{entry}")
            if entry.endswith("/") or (depth < max_depth and "/" not in entry):
                child = f"{path.rstrip('/')}/{entry.rstrip('/')}"
                try:
                    child_ls = execute_sandbox_tool("filesystem.ls", {"path": child})
                    child_text = (
                        get_message_content((child_ls.get("messages") or [None])[-1]).strip()
                        if child_ls.get("messages")
                        else ""
                    )
                    if child_text and not child_text.startswith(BLOCKED_RESPONSE_PREFIX):
                        _ls_dir(child, depth + 1, prefix + "  ")
                except Exception:
                    pass

    _ls_dir("/", 1, "")
    return "\n".join(lines[:120])


def _scan_git_status(execute_sandbox_tool: Callable) -> dict[str, Any] | None:
    """Detect git repo status: branch, dirty files, recent log."""
    git_info: dict[str, Any] = {}
    try:
        # Check if .git exists
        git_check = execute_sandbox_tool("filesystem.ls", {"path": "/.git"})
        git_text = (
            get_message_content((git_check.get("messages") or [None])[-1]).strip() if git_check.get("messages") else ""
        )
        if not git_text or git_text.startswith(BLOCKED_RESPONSE_PREFIX):
            return None
        git_info["enabled"] = True
    except Exception:
        return None

    # Try reading HEAD for branch
    try:
        head_result = execute_sandbox_tool("filesystem.read", {"path": "/.git/HEAD"})
        head_text = (
            get_message_content((head_result.get("messages") or [None])[-1]).strip()
            if head_result.get("messages")
            else ""
        )
        if head_text.startswith("ref: refs/heads/"):
            git_info["branch"] = head_text.replace("ref: refs/heads/", "").strip()
        elif head_text:
            git_info["branch"] = head_text[:12]  # detached HEAD
    except Exception:
        pass

    return git_info


def scan_workspace_profile(execute_sandbox_tool: Callable) -> dict[str, Any]:
    """Auto-detect project type, build file tree, and check git status."""
    profile: dict[str, Any] = {}

    try:
        ls_result = execute_sandbox_tool("filesystem.ls", {"path": "/"})
        ls_text = (
            get_message_content((ls_result.get("messages") or [None])[-1]).strip() if ls_result.get("messages") else ""
        )
        if ls_text:
            profile["rootFiles"] = ls_text[:2000]
    except Exception:
        pass

    # Build compact file tree (Aider repo-map pattern)
    try:
        file_tree = _build_file_tree(execute_sandbox_tool, max_depth=2)
        if file_tree:
            profile["fileTree"] = file_tree[:3000]
    except Exception:
        pass

    # Scan git status
    try:
        git_info = _scan_git_status(execute_sandbox_tool)
        if git_info:
            profile["git"] = git_info
    except Exception:
        pass

    config_files = [
        "README.md",
        "package.json",
        "Makefile",
        "pyproject.toml",
        "Cargo.toml",
        "go.mod",
        "pom.xml",
        "build.gradle",
        "requirements.txt",
        "Dockerfile",
        ".gitignore",
    ]
    detected: list[str] = []
    for fname in config_files:
        try:
            read_result = execute_sandbox_tool(
                "filesystem.read",
                {"path": f"/{fname}"},
            )
            content = (
                get_message_content((read_result.get("messages") or [None])[-1]).strip()
                if read_result.get("messages")
                else ""
            )
            if content and not content.startswith(BLOCKED_RESPONSE_PREFIX):
                profile[fname] = truncate_text(content, 1500)
                detected.append(fname)
        except Exception:
            continue

    # Derive project type heuristic
    if "package.json" in detected:
        profile["projectType"] = "node"
    elif "pyproject.toml" in detected or "requirements.txt" in detected:
        profile["projectType"] = "python"
    elif "Cargo.toml" in detected:
        profile["projectType"] = "rust"
    elif "go.mod" in detected:
        profile["projectType"] = "go"
    elif "pom.xml" in detected or "build.gradle" in detected:
        profile["projectType"] = "java"
    elif "Makefile" in detected:
        profile["projectType"] = "make"

    # Derive lint/test commands from project type
    project_type = profile.get("projectType", "")
    if project_type == "python":
        profile["lintCommand"] = "python -c \"import py_compile; py_compile.compile('{path}', doraise=True)\""
        profile["testCommand"] = "python -m pytest --tb=short -q"
    elif project_type == "node":
        profile["lintCommand"] = "npx --yes eslint --no-eslintrc '{path}'"
        profile["testCommand"] = "npm test"
    elif project_type == "go":
        profile["lintCommand"] = "go vet '{path}'"
        profile["testCommand"] = "go test ./..."
    elif project_type == "rust":
        profile["lintCommand"] = "cargo check"
        profile["testCommand"] = "cargo test"

    return profile


_ERROR_TAXONOMY: dict[str, dict[str, str]] = {
    "file_not_found": {
        "pattern": "not found|no such file|does not exist|enoent",
        "hint": "Check the file path — use ls or find to locate the correct file before retrying.",
    },
    "permission_denied": {
        "pattern": "permission denied|access denied|forbidden|eacces",
        "hint": "You may not have write access. Check file permissions or try a different approach.",
    },
    "syntax_error": {
        "pattern": "syntax error|unexpected token|parse error|invalid syntax|indentation",
        "hint": "The code has a syntax issue. Read the file around the error line and fix the specific syntax problem.",
    },
    "test_failure": {
        "pattern": "test.*fail|assert.*error|expected.*got|fail.*test",
        "hint": "A test failed. Read the test output carefully, identify which assertion "
        "failed and why, then fix the code (not the test, unless the test is wrong).",
    },
    "import_error": {
        "pattern": "import error|module not found|no module named|cannot find module",
        "hint": "A module is missing. Check the import path, installed packages, or whether the module file exists.",
    },
    "timeout": {
        "pattern": "timeout|timed out|deadline exceeded",
        "hint": "The operation timed out. Try a more targeted approach with smaller scope.",
    },
    "command_not_found": {
        "pattern": "command not found|not recognized|no such command",
        "hint": "The command is not available. Check local_shell capabilities or use a sandbox_tool alternative.",
    },
    "type_error": {
        "pattern": "type error|typeerror|attributeerror|cannot read propert",
        "hint": "A type/attribute error occurred. Check the variable types, "
        "function signatures, and ensure the right API is being called.",
    },
}


def classify_error(failure_summary: str) -> tuple[str, str]:
    """Classify an error message and return (category, recovery_hint)."""
    lower = failure_summary.lower()
    for category, info in _ERROR_TAXONOMY.items():
        if re.search(info["pattern"], lower):
            return category, info["hint"]
    return "unknown", (
        "Analyze the error message carefully. Consider alternative tools, "
        "different arguments, or breaking the problem into smaller steps."
    )


def execute_git_commit(
    message: str,
    *,
    commit_all: bool = True,
    execute_local_tool: Callable[[str, list[str]], dict[str, Any]],
) -> dict[str, Any]:
    """Execute a git commit with the given message.

    When *commit_all* is True, stages **all** files (including new/untracked)
    via ``git add -A`` before committing.
    """
    steps: list[str] = []
    try:
        # Stage changes — use -A to include new/untracked files, not just modified
        if commit_all:
            add_result = execute_local_tool("git", ["add", "-A"])
            add_status = str(add_result.get("invoke_status") or "")
            if add_status not in ("completed", "continue"):
                return {
                    "messages": [AIMessage(content=blocked_response("git add -A failed"))],
                    "invoke_status": "blocked",
                    "error_type": "git_error",
                    "error": "git add -A failed",
                    "stop_reason": "git_error",
                }
            steps.append("staged modified files")

        # Commit
        commit_result = execute_local_tool("git", ["commit", "-m", message])
        commit_status = str(commit_result.get("invoke_status") or "")
        commit_output = get_message_content((commit_result.get("messages") or [None])[-1]).strip()

        if commit_status not in ("completed", "continue"):
            return {
                "messages": [AIMessage(content=f"git commit failed:\n{commit_output[:500]}")],
                "invoke_status": "blocked",
                "error_type": "git_error",
                "error": commit_output[:500],
                "stop_reason": "git_error",
            }

        steps.append("committed")
        return {
            "messages": [AIMessage(content=f"Git commit successful ({', '.join(steps)}):\n{commit_output[:500]}")],
            "invoke_status": "completed",
            "tool_result": {"commit_message": message},
        }
    except Exception as exc:
        return {
            "messages": [AIMessage(content=blocked_response(f"git commit error: {exc}"))],
            "invoke_status": "blocked",
            "error_type": "git_error",
            "error": str(exc),
            "stop_reason": "git_error",
        }


def execute_edit_file(
    path: str,
    old_text: str,
    new_text: str,
    execute_sandbox_tool: Callable,
) -> dict[str, Any]:
    """Execute an edit_file action: read file, find old_text, replace, write back."""
    read_result = execute_sandbox_tool("filesystem.read", {"path": path})
    read_status = str(read_result.get("invoke_status") or "completed")
    if read_status not in ("completed", "continue"):
        return {
            "messages": [AIMessage(content=blocked_response(f"edit_file: cannot read '{path}': {read_status}"))],
            "invoke_status": "blocked",
            "error_type": "edit_read_failed",
            "error": f"Could not read file '{path}' for editing",
            "stop_reason": "edit_read_failed",
        }

    content = get_message_content((read_result.get("messages") or [None])[-1]).strip()
    if not content or content.startswith(BLOCKED_RESPONSE_PREFIX):
        return {
            "messages": [AIMessage(content=blocked_response(f"edit_file: file '{path}' is empty or unreadable"))],
            "invoke_status": "blocked",
            "error_type": "edit_read_failed",
            "error": f"File '{path}' is empty or unreadable",
            "stop_reason": "edit_read_failed",
        }

    occurrences = content.count(old_text)
    if occurrences == 0:
        # --- Fuzzy matching fallback ---
        # Split content into sliding windows of similar size to old_text and
        # find the best match using SequenceMatcher.
        best_ratio = 0.0
        best_match_text = ""
        best_line = 0
        content_lines = content.splitlines(keepends=True)
        old_lines_count = old_text.count("\n") + 1
        # Slide a window of old_lines_count lines across the file
        for i in range(max(1, len(content_lines) - old_lines_count + 1)):
            window = "".join(content_lines[i : i + old_lines_count])
            ratio = difflib.SequenceMatcher(None, old_text, window).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
                best_match_text = window
                best_line = i + 1

        hint = f"Read the file again to see its current content."
        if best_ratio >= FUZZY_MATCH_THRESHOLD:
            # Show the near-match to help the agent correct its old_text
            preview = best_match_text[:300].rstrip()
            hint = (
                f"A close match ({best_ratio:.0%} similar) was found at line {best_line}:\n"
                f"```\n{preview}\n```\n"
                "Use this exact text as old_text to match correctly."
            )

        return {
            "messages": [AIMessage(content=blocked_response(f"edit_file: old_text not found in '{path}'. {hint}"))],
            "invoke_status": "blocked",
            "error_type": "edit_old_text_not_found",
            "error": f"old_text not found in '{path}'",
            "stop_reason": "edit_old_text_not_found",
            "retryable": True,
        }

    if occurrences > 1:
        return {
            "messages": [
                AIMessage(
                    content=blocked_response(
                        f"edit_file: old_text matches {occurrences} locations in '{path}'. "
                        "Include more surrounding context to make the match unique."
                    )
                )
            ],
            "invoke_status": "blocked",
            "error_type": "edit_ambiguous_match",
            "error": f"old_text matches {occurrences} locations",
            "stop_reason": "edit_ambiguous_match",
            "retryable": True,
        }

    new_content = content.replace(old_text, new_text, 1)
    write_result = execute_sandbox_tool(
        "filesystem.write",
        {"path": path, "content": new_content},
    )
    write_status = str(write_result.get("invoke_status") or "completed")
    if write_status not in ("completed", "continue"):
        return {
            "messages": [AIMessage(content=blocked_response(f"edit_file: failed to write '{path}': {write_status}"))],
            "invoke_status": "blocked",
            "error_type": "edit_write_failed",
            "error": f"Could not write file '{path}'",
            "stop_reason": "edit_write_failed",
        }

    # Count lines changed for summary
    old_lines = old_text.count("\n") + 1
    new_lines = new_text.count("\n") + 1
    summary = f"Successfully edited '{path}': replaced {old_lines} lines with {new_lines} lines (1 occurrence)."

    # Generate unified diff for UI display
    diff_lines = list(
        difflib.unified_diff(
            content.splitlines(keepends=True),
            new_content.splitlines(keepends=True),
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
        )
    )
    diff_text = "".join(diff_lines)
    if diff_text:
        publish_runtime_event("agent.step.diff", {"path": path, "diff": diff_text[:4000]})

    return {
        "messages": [AIMessage(content=summary)],
        "invoke_status": "completed",
        "tool_result": {"path": path, "oldLines": old_lines, "newLines": new_lines},
        "_edit_record": {"path": path, "old_text": new_text, "new_text": old_text},
        "_diff": diff_text,
    }


def execute_undo_edit(
    edit_history: list[dict[str, str]],
    execute_sandbox_tool: Callable,
) -> dict[str, Any]:
    """Pop the last edit from history and reverse it."""
    if not edit_history:
        return {
            "messages": [AIMessage(content=blocked_response("undo_edit: no edits in history to undo"))],
            "invoke_status": "blocked",
            "error_type": "undo_empty_history",
            "error": "No edits to undo",
            "stop_reason": "undo_empty_history",
        }
    record = edit_history.pop()
    # record["old_text"] is the reverse text (what was written), "new_text" is what was there before
    return execute_edit_file(
        record["path"],
        record["old_text"],
        record["new_text"],
        execute_sandbox_tool,
    )


def execute_edit_files(
    edits: list[dict[str, str]],
    execute_sandbox_tool: Callable,
) -> dict[str, Any]:
    """Execute multiple edit_file operations transactionally (all-or-nothing).

    Phase 1: validate all edits (read files, verify old_text exists exactly once).
    Phase 2: apply all edits and collect undo records.
    If any write fails, roll back completed writes using undo records.
    """
    if not edits:
        return {
            "messages": [AIMessage(content=blocked_response("edit_files: no edits provided"))],
            "invoke_status": "blocked",
            "error_type": "edit_files_empty",
            "error": "No edits provided",
            "stop_reason": "edit_files_empty",
        }

    # Phase 1 — validate all files before writing anything
    validated: list[dict[str, Any]] = []
    for idx, entry in enumerate(edits[:8]):
        path = str(entry.get("path") or "").strip()
        old_text = str(entry.get("old_text") or "")
        new_text = str(entry.get("new_text") or "")
        if not path or not old_text:
            return {
                "messages": [
                    AIMessage(content=blocked_response(f"edit_files: edit[{idx}] missing required path or old_text"))
                ],
                "invoke_status": "blocked",
                "error_type": "edit_files_validation",
                "error": f"edit[{idx}] missing path or old_text",
                "stop_reason": "edit_files_validation",
                "retryable": True,
            }
        read_result = execute_sandbox_tool("filesystem.read", {"path": path})
        if str(read_result.get("invoke_status") or "") not in ("completed", "continue"):
            return {
                "messages": [AIMessage(content=blocked_response(f"edit_files: cannot read '{path}' for edit[{idx}]"))],
                "invoke_status": "blocked",
                "error_type": "edit_files_read_failed",
                "error": f"Cannot read '{path}'",
                "stop_reason": "edit_files_read_failed",
            }
        content = get_message_content((read_result.get("messages") or [None])[-1]).strip()
        occurrences = content.count(old_text)
        if occurrences == 0:
            return {
                "messages": [
                    AIMessage(content=blocked_response(f"edit_files: old_text not found in '{path}' (edit[{idx}])"))
                ],
                "invoke_status": "blocked",
                "error_type": "edit_old_text_not_found",
                "error": f"old_text not found in '{path}' for edit[{idx}]",
                "stop_reason": "edit_old_text_not_found",
                "retryable": True,
            }
        if occurrences > 1:
            return {
                "messages": [
                    AIMessage(
                        content=blocked_response(
                            f"edit_files: old_text matches {occurrences} locations in '{path}' (edit[{idx}])"
                        )
                    )
                ],
                "invoke_status": "blocked",
                "error_type": "edit_ambiguous_match",
                "error": f"old_text matches {occurrences} locations in '{path}'",
                "stop_reason": "edit_ambiguous_match",
                "retryable": True,
            }
        new_content = content.replace(old_text, new_text, 1)
        validated.append(
            {
                "path": path,
                "old_text": old_text,
                "new_text": new_text,
                "old_content": content,
                "new_content": new_content,
            }
        )

    # Phase 2 — apply all writes; rollback on failure
    edit_records: list[dict[str, str]] = []
    diffs: list[str] = []
    for idx, v in enumerate(validated):
        write_result = execute_sandbox_tool("filesystem.write", {"path": v["path"], "content": v["new_content"]})
        if str(write_result.get("invoke_status") or "") not in ("completed", "continue"):
            # Rollback completed writes
            for rec in reversed(edit_records):
                execute_sandbox_tool("filesystem.write", {"path": rec["path"], "content": rec["new_text"]})
            return {
                "messages": [
                    AIMessage(
                        content=blocked_response(
                            f"edit_files: write failed for '{v['path']}' (edit[{idx}]); "
                            f"rolled back {len(edit_records)} prior write(s)"
                        )
                    )
                ],
                "invoke_status": "blocked",
                "error_type": "edit_files_write_failed",
                "error": f"Write failed for '{v['path']}'",
                "stop_reason": "edit_files_write_failed",
            }
        edit_records.append({"path": v["path"], "old_text": v["new_text"], "new_text": v["old_text"]})
        dl = list(
            difflib.unified_diff(
                v["old_content"].splitlines(keepends=True),
                v["new_content"].splitlines(keepends=True),
                fromfile=f"a/{v['path']}",
                tofile=f"b/{v['path']}",
            )
        )
        diffs.append("".join(dl))

    summary_parts = [f"- {v['path']}" for v in validated]
    summary = f"Successfully edited {len(validated)} files:\n" + "\n".join(summary_parts)
    combined_diff = "\n".join(d for d in diffs if d)
    if combined_diff:
        publish_runtime_event("agent.step.diff", {"path": "(multi)", "diff": combined_diff[:8000]})

    return {
        "messages": [AIMessage(content=summary)],
        "invoke_status": "completed",
        "tool_result": {"filesEdited": len(validated), "paths": [v["path"] for v in validated]},
        "_edit_records": edit_records,
        "_diff": combined_diff,
    }


def execute_search_code(
    action: dict[str, Any],
    execute_local_tool: Callable[[str, list[str]], dict[str, Any]],
) -> dict[str, Any]:
    """Search code using grep/ripgrep with structured output parsing."""
    pattern = str(action.get("pattern") or "").strip()
    if not pattern:
        return {
            "messages": [AIMessage(content=blocked_response("search_code: no pattern provided"))],
            "invoke_status": "blocked",
            "error_type": "search_code_empty",
            "error": "No search pattern provided",
            "stop_reason": "search_code_empty",
        }
    max_results = min(int(action.get("max_results") or 20), 50)
    search_path = str(action.get("path") or ".").strip() or "."
    include_glob = str(action.get("include") or "").strip()

    # Build grep args — prefer ripgrep if available, fallback to grep
    args = ["-rn", "--color=never"]
    if include_glob:
        args.extend(["--include", include_glob])
    args.extend([pattern, search_path])

    try:
        result = execute_local_tool("grep", args)
    except Exception:
        result = {"invoke_status": "blocked", "messages": []}

    raw_output = get_message_content((result.get("messages") or [None])[-1]).strip() if result.get("messages") else ""

    if not raw_output or str(result.get("invoke_status") or "") == "blocked":
        return {
            "messages": [AIMessage(content=f"search_code: no matches for '{pattern}'")],
            "invoke_status": "completed",
            "tool_result": {"matches": 0, "results": []},
        }

    # Parse grep output into structured results
    matches: list[dict[str, Any]] = []
    for line in raw_output.splitlines():
        if len(matches) >= max_results:
            break
        parts = line.split(":", 2)
        if len(parts) >= 3:
            matches.append(
                {
                    "file": parts[0],
                    "line": parts[1],
                    "text": parts[2].strip()[:200],
                }
            )
        elif len(parts) == 2:
            matches.append({"file": parts[0], "line": parts[1], "text": ""})

    summary_lines = [f"{m['file']}:{m['line']}: {m['text']}" for m in matches[:max_results]]
    summary = f"Found {len(matches)} match(es) for '{pattern}':\n" + "\n".join(summary_lines)

    return {
        "messages": [AIMessage(content=summary)],
        "invoke_status": "completed",
        "tool_result": {"matches": len(matches), "results": matches},
    }


def execute_batch_read(
    reads: list[dict[str, Any]],
    execute_sandbox_tool: Callable,
) -> dict[str, Any]:
    """Execute a batch_read action: read multiple files/ranges in parallel."""

    def _read_one(entry: dict[str, Any]) -> str:
        path = str(entry.get("path") or "").strip()
        if not path:
            return ""
        start_line = entry.get("start_line")
        end_line = entry.get("end_line")
        tool_args: dict[str, Any] = {"path": path}
        if start_line is not None and end_line is not None:
            try:
                tool_args["start_line"] = int(start_line)
                tool_args["end_line"] = int(end_line)
            except (TypeError, ValueError):
                pass
        try:
            read_result = execute_sandbox_tool("filesystem.read", tool_args)
            content = (
                get_message_content((read_result.get("messages") or [None])[-1]).strip()
                if read_result.get("messages")
                else ""
            )
        except Exception as exc:
            content = f"Error reading {path}: {exc}"
        header = f"=== {path}"
        if "start_line" in tool_args and "end_line" in tool_args:
            header += f" (lines {tool_args['start_line']}-{tool_args['end_line']})"
        header += " ==="
        return f"{header}\n{truncate_text(content, 4000)}"

    entries = [e for e in reads[:8] if str(e.get("path") or "").strip()]
    if not entries:
        return {
            "messages": [AIMessage(content=blocked_response("batch_read: no valid paths provided"))],
            "invoke_status": "blocked",
            "error_type": "batch_read_empty",
            "error": "No valid file paths provided",
            "stop_reason": "batch_read_empty",
        }

    # Parallel reads when more than 1 file
    results: list[str] = []
    if len(entries) > 1:
        with ThreadPoolExecutor(max_workers=min(len(entries), 4)) as pool:
            future_map = {pool.submit(_read_one, e): i for i, e in enumerate(entries)}
            ordered: dict[int, str] = {}
            for future in as_completed(future_map):
                idx = future_map[future]
                try:
                    ordered[idx] = future.result()
                except Exception as exc:
                    path = str(entries[idx].get("path") or "?")
                    ordered[idx] = f"=== {path} ===\nError: {exc}"
            results = [ordered[i] for i in sorted(ordered)]
    else:
        results = [_read_one(entries[0])]

    results = [r for r in results if r]
    combined = "\n\n".join(results)
    return {
        "messages": [AIMessage(content=combined)],
        "invoke_status": "completed",
        "tool_result": {"filesRead": len(results)},
    }


_SUPERVISOR_SYSTEM_PROMPT = """\
You are an expert autonomous coding agent — the internal supervisor that plans \
and executes multi-step tasks inside a sandboxed environment. Your goal is to \
fulfill the user's objective completely and correctly using the available tools.

## Core Principles
1. **Think before acting.** Always fill the "thinking" field with your chain-of-thought \
reasoning BEFORE choosing an action. Explain what you know, what you need, and why \
you chose this specific action.
2. **Read before writing.** Before modifying any file, read it first to understand its \
current state. Use filesystem.read, grep/search, or ls to orient yourself.
3. **Verify after changing.** After making edits or executing commands, verify the result \
by reading the output, running tests, or checking file contents.
4. **Search broadly, then narrow.** When looking for something, cast a wide net first \
(search patterns, list directories), then drill into specifics.
5. **One step at a time.** Each action should be a single, well-defined operation. \
Don't try to accomplish everything in one step.
6. **Prefer respond when you have enough information.** If you already know the answer \
or have gathered sufficient context, respond immediately.
7. **Verify before claiming done.** Task completion \u2260 goal achievement. Before your \
final response, verify the actual goal was achieved: re-read modified files, re-run tests, \
or re-check output. Work backwards from the goal \u2014 what must be TRUE, what must EXIST, \
what must be WIRED \u2014 and confirm each condition.
8. **Diagnose before fixing.** When something fails, understand WHY before applying \
any fix. Read the full error message, identify the root cause, and only then act. \
Never apply speculative patches.

## Anti-Patterns (AVOID)
- Repeating the same action with identical arguments — it won't produce different results.
- Guessing file paths without first listing or searching the directory structure.
- Making changes without verifying them afterward.
- Issuing overly broad commands that produce too much output; be specific.
- Skipping error analysis — when something fails, reason about WHY before retrying.
- Claiming completion without fresh verification evidence — always re-read/re-run before responding.
- Applying fixes without understanding root cause — diagnose the failure before patching.

## Response Format
Return exactly ONE JSON object (no markdown fences). Every response MUST include a \
"thinking" field explaining your reasoning.

### Action Schemas

**Respond with final answer:**
{"thinking":"...","action":"respond","response":"<full final answer>"}

**Create or update an explicit plan:**
{"thinking":"...","action":"plan","steps":["step 1 description","step 2 description",...]}

**Run a sandbox tool (filesystem, code execution):**
{"thinking":"...","action":"sandbox_tool","tool_name":"<tool>","tool_args":{...}}

**Edit a file with search-and-replace (preferred for targeted edits):**
{"thinking":"...","action":"edit_file","path":"<file>","old_text":"exact text to find","new_text":"replacement text"}

**Edit multiple files transactionally (all-or-nothing):**
{"thinking":"...","action":"edit_files","edits":[{"path":"file1","old_text":"find","new_text":"replace"},{"path":"file2","old_text":"find","new_text":"replace"}]}

**Read multiple file ranges in one step:**
{"thinking":"...","action":"batch_read","reads":[{"path":"file1","start_line":1,"end_line":50},{"path":"file2"}]}

**Run a local shell command (grep, find, ls, cat, etc.):**
{"thinking":"...","action":"local_shell","command":"<cmd>","args":["arg1","arg2"],"cwd":"/optional/path"}

**Search code with structured results (grep/ripgrep with parsed output):**
{"thinking":"...","action":"search_code","pattern":"<regex or literal>","path":"/optional/scope","include":"*.py","max_results":20}

**Execute multiple independent tool calls in parallel:**
{"thinking":"...","action":"parallel_tools","tool_calls":[{"action":"local_shell","command":"grep","args":["-rn","pattern","src/"]},{"action":"sandbox_tool","tool_name":"filesystem.read","tool_args":{"path":"file.py"}}]}

**Call an MCP tool:**
{"thinking":"...","action":"mcp_tool","mcp_server":"<server>","tool_name":"<tool>","tool_args":{...}}

**Delegate to another agent (A2A):**
{"thinking":"...","action":"a2a_call","a2a_target_namespace":"...","a2a_target_agent":"...","prompt":"...","a2a_timeout_seconds":30}

**Orchestrate a subagent team:**
{"thinking":"...","action":"subagent_team","subagent_strategy":"sequential","subagents":[{"namespace":"...","name":"...","task":"...","role":"..."}]}

**Save a note to your scratchpad (persists across steps, free — no step cost):**
{"thinking":"...","action":"note","note":"Important finding: the auth module uses JWT with RS256"}

**Commit staged or all modified files to git (when git is available):**
{"thinking":"...","action":"git_commit","message":"<commit message>","all":true}

**Undo the last edit_file operation (reverses the most recent edit):**
{"thinking":"...","action":"undo_edit"}

## Tool Usage Recipes

### Exploring a project
1. `local_shell` ls / find to see directory structure
2. `sandbox_tool` filesystem.read on README, package.json, Makefile for project context
3. `local_shell` grep/rg to search for specific patterns
4. `sandbox_tool` filesystem.read on target files

### Modifying code safely
1. `sandbox_tool` filesystem.read — read the target file first
2. `edit_file` — make a targeted search-and-replace edit (NOT full-file rewrite)
3. `sandbox_tool` filesystem.read — verify the edit took effect
4. `local_shell` — run tests or linting to confirm correctness

### Debugging a failure
1. Read the error message / stack trace carefully in your thinking
2. `local_shell` grep for the error keyword or failing function
3. `sandbox_tool` filesystem.read on the relevant source file
4. `edit_file` to apply the fix
5. `local_shell` to re-run and confirm the fix

### Multi-file changes
1. `plan` — create a step-by-step plan before starting
2. For each file: read -> edit -> verify
3. Run tests after all edits
4. `respond` with a summary of changes

## Strategy Heuristics
- For code exploration tasks: ls -> search/grep -> read specific files -> respond
- For code modification: read target file -> edit_file -> verify change -> run tests
- For debugging: read error context -> identify root cause FIRST -> search for relevant code -> analyze -> fix -> verify
- For task completion: re-read the original objective -> verify each requirement is met with evidence -> then respond
- When stuck after a failure: re-read the error, consider alternative approaches, try a different tool
- Use `note` to save important findings, decisions, and context you'll need later — it's free
- When your plan has failed multiple times, issue a new `plan` action to revise your approach
- For destructive operations (file delete, git push): be cautious and verify before acting
- For git operations (clone, commit, push, pull): prefer MCP sidecar tools (git_clone, git_commit, git_push) when available — they have authentication pre-configured. Fall back to local_shell git only if no git MCP tools are present

## Response Formatting
When crafting your final `respond` answer:
- Use **markdown** formatting: headers, bullet points, code blocks with language tags
- For code changes: show key changes as fenced code blocks, not full files
- For debugging: state the **root cause first**, then the fix
- For explanations: brief summary followed by details
- For multi-file changes: list each file with a 1-line description of what changed
- Keep responses **concise** — don't repeat full file contents the user already has
- Use tables for comparisons, lists for steps, code blocks for code

## Re-Planning
- If your current approach has failed multiple times, revise the plan with a new `plan` action
- When re-planning, explain in your thinking what went wrong and why the new approach is different
- Don't persist with a broken strategy — adapt based on error feedback
- Use local_shell for quick operations (grep, find, ls, cat) when sandbox tools are heavier
- Use edit_file instead of filesystem.write for targeted code changes — it's safer and preserves context
- Use batch_read to read multiple files at once when you need broad context
- Use plan at the start of multi-step tasks to organize your work

## Important Rules
- Never choose a capability that is unavailable in the provided payload.
- The "thinking" field is mandatory for every action — responses without it may be rejected.
- When you choose respond, write the COMPLETE final answer in the response field.
- If the step budget is nearly exhausted, prioritize responding with what you have over starting new operations.
- When a plan is active, follow the plan steps in order. Update the plan if you discover the approach needs to change.
- After editing a file, always verify the change was applied correctly.
"""


# ---------------------------------------------------------------------------
# OpenAI function-calling / tool schemas
# ---------------------------------------------------------------------------

_SUPERVISOR_TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "respond",
            "description": "Return the final answer to the user. Use when you have gathered enough information.",
            "parameters": {
                "type": "object",
                "properties": {
                    "thinking": {"type": "string", "description": "Chain-of-thought reasoning."},
                    "response": {"type": "string", "description": "Full final answer in markdown."},
                },
                "required": ["thinking", "response"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "plan",
            "description": "Create or revise a multi-step plan before executing.",
            "parameters": {
                "type": "object",
                "properties": {
                    "thinking": {"type": "string", "description": "Chain-of-thought reasoning."},
                    "steps": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Ordered list of plan steps.",
                    },
                },
                "required": ["thinking", "steps"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "sandbox_tool",
            "description": "Run a sandbox tool (filesystem.read, filesystem.write, filesystem.ls, etc.).",
            "parameters": {
                "type": "object",
                "properties": {
                    "thinking": {"type": "string", "description": "Chain-of-thought reasoning."},
                    "tool_name": {"type": "string", "description": "Sandbox tool name, e.g. filesystem.read"},
                    "tool_args": {"type": "object", "description": "Arguments for the tool."},
                },
                "required": ["thinking", "tool_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit_file",
            "description": "Edit a file with search-and-replace. Finds old_text and replaces with new_text.",
            "parameters": {
                "type": "object",
                "properties": {
                    "thinking": {"type": "string", "description": "Chain-of-thought reasoning."},
                    "path": {"type": "string", "description": "File path to edit."},
                    "old_text": {"type": "string", "description": "Exact text to find in the file."},
                    "new_text": {"type": "string", "description": "Replacement text."},
                },
                "required": ["thinking", "path", "old_text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "batch_read",
            "description": "Read multiple file ranges in a single step.",
            "parameters": {
                "type": "object",
                "properties": {
                    "thinking": {"type": "string", "description": "Chain-of-thought reasoning."},
                    "reads": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "path": {"type": "string"},
                                "start_line": {"type": "integer"},
                                "end_line": {"type": "integer"},
                            },
                            "required": ["path"],
                        },
                        "description": "List of file read specifications.",
                    },
                },
                "required": ["thinking", "reads"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "local_shell",
            "description": "Run a local shell command (grep, find, ls, cat, git, etc.).",
            "parameters": {
                "type": "object",
                "properties": {
                    "thinking": {"type": "string", "description": "Chain-of-thought reasoning."},
                    "command": {"type": "string", "description": "Command name."},
                    "args": {"type": "array", "items": {"type": "string"}, "description": "Command arguments."},
                    "cwd": {"type": "string", "description": "Optional working directory."},
                },
                "required": ["thinking", "command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "mcp_tool",
            "description": "Call a tool on an MCP server.",
            "parameters": {
                "type": "object",
                "properties": {
                    "thinking": {"type": "string", "description": "Chain-of-thought reasoning."},
                    "mcp_server": {"type": "string", "description": "MCP server type."},
                    "tool_name": {"type": "string", "description": "MCP tool name."},
                    "tool_args": {"type": "object", "description": "Tool arguments."},
                },
                "required": ["thinking", "mcp_server", "tool_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "a2a_call",
            "description": "Delegate a task to another agent via A2A protocol.",
            "parameters": {
                "type": "object",
                "properties": {
                    "thinking": {"type": "string", "description": "Chain-of-thought reasoning."},
                    "a2a_target_namespace": {"type": "string", "description": "Target agent namespace."},
                    "a2a_target_agent": {"type": "string", "description": "Target agent name."},
                    "prompt": {"type": "string", "description": "Prompt to send to the target agent."},
                    "a2a_timeout_seconds": {"type": "number", "description": "Optional timeout in seconds."},
                },
                "required": ["thinking", "a2a_target_namespace", "a2a_target_agent", "prompt"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "subagent_team",
            "description": "Orchestrate a team of subagents to work on subtasks.",
            "parameters": {
                "type": "object",
                "properties": {
                    "thinking": {"type": "string", "description": "Chain-of-thought reasoning."},
                    "subagent_strategy": {"type": "string", "enum": ["sequential", "parallel"]},
                    "subagents": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "namespace": {"type": "string"},
                                "name": {"type": "string"},
                                "role": {"type": "string"},
                                "task": {"type": "string"},
                            },
                            "required": ["namespace", "name"],
                        },
                    },
                },
                "required": ["thinking", "subagent_strategy", "subagents"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "note",
            "description": "Save a note to your scratchpad. Persists across steps, free (no step cost).",
            "parameters": {
                "type": "object",
                "properties": {
                    "thinking": {"type": "string", "description": "Chain-of-thought reasoning."},
                    "note": {"type": "string", "description": "Note text to remember."},
                },
                "required": ["thinking", "note"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "git_commit",
            "description": "Commit staged or all modified files to git.",
            "parameters": {
                "type": "object",
                "properties": {
                    "thinking": {"type": "string", "description": "Chain-of-thought reasoning."},
                    "message": {"type": "string", "description": "Commit message."},
                    "all": {
                        "type": "boolean",
                        "description": "Stage all tracked modified files before committing.",
                        "default": True,
                    },
                },
                "required": ["thinking", "message"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "undo_edit",
            "description": "Undo the last file edit, restoring the previous content.",
            "parameters": {
                "type": "object",
                "properties": {
                    "thinking": {"type": "string", "description": "Chain-of-thought reasoning."},
                },
                "required": ["thinking"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit_files",
            "description": "Edit multiple files transactionally (all-or-nothing). All edits are validated before any writes; if any write fails, completed writes are rolled back.",
            "parameters": {
                "type": "object",
                "properties": {
                    "thinking": {"type": "string", "description": "Chain-of-thought reasoning."},
                    "edits": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "path": {"type": "string", "description": "File path to edit."},
                                "old_text": {"type": "string", "description": "Exact text to find."},
                                "new_text": {"type": "string", "description": "Replacement text."},
                            },
                            "required": ["path", "old_text"],
                        },
                        "description": "List of file edit operations.",
                    },
                },
                "required": ["thinking", "edits"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_code",
            "description": "Search code with structured results using grep/ripgrep. Returns matching file paths and line numbers.",
            "parameters": {
                "type": "object",
                "properties": {
                    "thinking": {"type": "string", "description": "Chain-of-thought reasoning."},
                    "pattern": {"type": "string", "description": "Search pattern (regex or literal)."},
                    "path": {"type": "string", "description": "Directory to search in (default: workspace root)."},
                    "include": {"type": "string", "description": "Glob pattern to filter files, e.g. '*.py'."},
                    "max_results": {
                        "type": "integer",
                        "description": "Max results to return (default 20).",
                        "default": 20,
                    },
                },
                "required": ["thinking", "pattern"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "parallel_tools",
            "description": "Execute multiple independent tool calls in parallel. Each call must be a read-only or independent operation (sandbox_tool reads, local_shell, search_code, batch_read). Do NOT include edit_file or other write operations.",
            "parameters": {
                "type": "object",
                "properties": {
                    "thinking": {"type": "string", "description": "Chain-of-thought reasoning."},
                    "tool_calls": {
                        "type": "array",
                        "items": {"type": "object", "description": "Action dict (same schema as individual actions)."},
                        "description": "List of independent tool calls to execute concurrently.",
                        "maxItems": 6,
                    },
                },
                "required": ["thinking", "tool_calls"],
            },
        },
    },
]


def build_tool_schemas(capabilities: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the subset of tool schemas that match the agent's current capabilities."""
    schemas = list(_SUPERVISOR_TOOL_SCHEMAS)
    # Remove a2a_call and subagent_team if no targets
    if not capabilities.get("a2aTargets"):
        schemas = [s for s in schemas if s["function"]["name"] not in ("a2a_call", "subagent_team")]
    if not capabilities.get("allowSubagents"):
        schemas = [s for s in schemas if s["function"]["name"] != "subagent_team"]
    if not capabilities.get("mcpServers"):
        schemas = [s for s in schemas if s["function"]["name"] != "mcp_tool"]
    return schemas


def parse_tool_call_to_action(tool_call: dict[str, Any]) -> dict[str, Any] | None:
    """Convert an OpenAI-style tool_call into our normalized action dict."""
    func_name = str(tool_call.get("name") or "").strip()
    args = tool_call.get("args") or {}
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except (json.JSONDecodeError, ValueError):
            return None
    if not isinstance(args, dict):
        return None
    # Merge function name as "action"
    action_dict = {"action": func_name, **args}
    return normalize_supervisor_action(action_dict)


def build_supervisor_messages(state: State) -> list[Any]:
    capabilities = {
        "sandboxTools": supervisor_visible_sandbox_tools(),
        "localRuntime": supervisor_visible_local_runtime(),
        "mcpServers": sorted(SKILL_RUNTIME_CONFIG.get("allowedMcpServers") or []),
        "a2aTargets": [
            {"namespace": namespace, "name": name}
            for namespace, name in sorted(SKILL_RUNTIME_CONFIG.get("allowedA2ATargets") or [])
        ],
        "allowSubagents": bool(SKILL_RUNTIME_CONFIG.get("allowSubagents")),
    }
    if not SKILL_RUNTIME_CONFIG.get("skills"):
        capabilities["mcpServers"] = sorted(ALLOWED_MCP_SERVERS)
        capabilities["a2aTargets"] = [
            {"namespace": namespace, "name": name} for namespace, name in sorted(A2A_ALLOWED_TARGETS_SNAPSHOT)
        ]
        capabilities["allowSubagents"] = bool(A2A_ALLOWED_TARGETS_SNAPSHOT)

    current_step = int(state.get("step_count") or 0) + 1
    max_steps = int(state.get("max_steps") or DEFAULT_MAX_AUTONOMY_STEPS)
    attempted_actions = state.get("attempted_actions") or []
    progress_summary = build_progress_summary(attempted_actions)

    payload = {
        "objective": state.get("request_prompt", ""),
        "retrievedContext": truncate_text(state.get("context", ""), MAX_CONTEXT_CHARS),
        "history": summarize_message_history(
            state.get("messages") or [],
            token_budget=CONTEXT_WINDOW_TOKEN_LIMIT // 2,
        ),
        "teamContext": state.get("team_context"),
        "step": current_step,
        "maxSteps": max_steps,
        "stepBudgetRemaining": max(max_steps - current_step + 1, 0),
        "capabilities": capabilities,
        "lastStepError": state.get("last_step_error"),
        "recentFailures": state.get("recent_failures") or [],
        "attemptedActions": [
            {"step": record.get("step"), "label": record.get("label"), "status": record.get("status")}
            for record in attempted_actions[-8:]
        ],
        "progressSummary": progress_summary,
    }

    # Include active plan status if one exists
    active_plan = state.get("active_plan") or []
    plan_step_index = int(state.get("plan_step_index") or 0)
    if active_plan:
        payload["planStatus"] = format_plan_status(active_plan, plan_step_index)

    # Include workspace profile if scanned
    workspace_profile = state.get("workspace_profile")
    if isinstance(workspace_profile, dict) and workspace_profile:
        wp: dict[str, Any] = {
            "projectType": workspace_profile.get("projectType", "unknown"),
            "rootFiles": workspace_profile.get("rootFiles", "")[:500],
        }
        file_tree = workspace_profile.get("fileTree", "")
        if file_tree:
            wp["fileTree"] = file_tree[:2000]
        git_info = workspace_profile.get("git")
        if isinstance(git_info, dict) and git_info:
            wp["git"] = git_info
        lint_cmd = workspace_profile.get("lintCommand")
        if lint_cmd:
            wp["lintCommand"] = lint_cmd
        test_cmd = workspace_profile.get("testCommand")
        if test_cmd:
            wp["testCommand"] = test_cmd
        payload["workspaceProfile"] = wp

    # Include files modified so far
    files_modified = state.get("files_modified") or []
    if files_modified:
        payload["filesModified"] = files_modified[-20:]

    # Include git diff stat when files have been modified
    git_diff_stat = str(state.get("git_diff_stat") or "").strip()
    if git_diff_stat:
        payload["gitDiffStat"] = git_diff_stat

    # Include scratchpad notes if any
    scratchpad = state.get("scratchpad") or []
    if scratchpad:
        payload["scratchpad"] = scratchpad[-MAX_SCRATCHPAD_ENTRIES:]
    system_messages: list[Any] = []
    system_prompt = str(state.get("system_prompt") or "").strip()
    if system_prompt:
        system_messages.append(SystemMessage(content=system_prompt))

    skill_prompt = str(SKILL_RUNTIME_CONFIG.get("prompt") or "").strip()
    if skill_prompt:
        system_messages.append(SystemMessage(content=skill_prompt))

    collaboration_context = format_team_context_system_message(state.get("team_context"))
    if collaboration_context:
        system_messages.append(SystemMessage(content=collaboration_context))

    system_messages.append(SystemMessage(content=_SUPERVISOR_SYSTEM_PROMPT))
    system_messages.append(HumanMessage(content=safe_json_dumps(payload)))
    return system_messages


def extract_json_object(text: str) -> dict[str, Any] | None:
    candidate = str(text or "").strip()
    if not candidate:
        return None
    if candidate.startswith("```"):
        match = re.search(r"```(?:json)?\s*(.*?)```", candidate, flags=re.DOTALL | re.IGNORECASE)
        if match is not None:
            candidate = match.group(1).strip()

    start = candidate.find("{")
    end = candidate.rfind("}")
    if start == -1 or end == -1 or end < start:
        return None

    try:
        parsed = json.loads(candidate[start : end + 1])
    except ValueError:
        logger.debug("extract_json_object: JSON parse failed for: %.200s", candidate[start : end + 1])
        return None
    return parsed if isinstance(parsed, dict) else None


def _extract_thinking(value: dict[str, Any]) -> str:
    """Extract optional chain-of-thought thinking field from supervisor JSON."""
    raw = value.get("thinking")
    if not raw or not isinstance(raw, str):
        return ""
    return raw.strip()[:2000]


def normalize_supervisor_action(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None

    thinking = _extract_thinking(value)
    action = str(value.get("action") or "").strip().lower()

    if action == "respond":
        response = truncate_text(str(value.get("response") or "").strip(), SUPERVISOR_RESPONSE_CHARS)
        if not response:
            return None
        return {"action": action, "response": response, "thinking": thinking}

    if action == "plan":
        raw_steps = value.get("steps")
        if not isinstance(raw_steps, list) or not raw_steps:
            return None
        steps = [str(s).strip() for s in raw_steps[:20] if str(s).strip()]
        if not steps:
            return None
        return {"action": action, "steps": steps, "thinking": thinking}

    if action == "note":
        note_text = str(value.get("note") or "").strip()
        if not note_text:
            return None
        return {"action": action, "note": note_text[:500], "thinking": thinking}

    if action == "git_commit":
        message = str(value.get("message") or "").strip()
        if not message:
            return None
        commit_all = bool(value.get("all", True))
        return {"action": action, "message": message[:200], "all": commit_all, "thinking": thinking}

    if action == "undo_edit":
        return {"action": action, "thinking": thinking}

    if action == "edit_files":
        raw_edits = value.get("edits")
        if not isinstance(raw_edits, list) or not raw_edits:
            return None
        edits: list[dict[str, str]] = []
        for entry in raw_edits[:8]:
            if isinstance(entry, dict):
                p = str(entry.get("path") or "").strip()
                ot = str(entry.get("old_text") or "")
                nt = str(entry.get("new_text") or "")
                if p and ot:
                    edits.append({"path": p, "old_text": ot, "new_text": nt})
        if not edits:
            return None
        return {"action": action, "edits": edits, "thinking": thinking}

    if action == "search_code":
        pattern = str(value.get("pattern") or "").strip()
        if not pattern:
            return None
        result: dict[str, Any] = {"action": action, "pattern": pattern, "thinking": thinking}
        search_path = str(value.get("path") or "").strip()
        if search_path:
            result["path"] = search_path
        include = str(value.get("include") or "").strip()
        if include:
            result["include"] = include
        max_results = value.get("max_results")
        if max_results is not None:
            try:
                result["max_results"] = min(int(max_results), 50)
            except (TypeError, ValueError):
                pass
        return result

    if action == "parallel_tools":
        raw_calls = value.get("tool_calls")
        if not isinstance(raw_calls, list) or not raw_calls:
            return None
        # Only allow read-only actions in parallel
        _PARALLEL_SAFE = frozenset({"sandbox_tool", "local_shell", "batch_read", "search_code"})
        calls: list[dict[str, Any]] = []
        for item in raw_calls[:6]:
            normalized = normalize_supervisor_action(item) if isinstance(item, dict) else None
            if normalized and normalized.get("action") in _PARALLEL_SAFE:
                calls.append(normalized)
        if not calls:
            return None
        return {"action": action, "tool_calls": calls, "thinking": thinking}

    if action == "edit_file":
        path = str(value.get("path") or "").strip()
        old_text = str(value.get("old_text") or "")
        new_text = str(value.get("new_text") or "")
        if not path or not old_text:
            return None
        return {
            "action": action,
            "path": path,
            "old_text": old_text,
            "new_text": new_text,
            "thinking": thinking,
        }

    if action == "batch_read":
        raw_reads = value.get("reads")
        if not isinstance(raw_reads, list) or not raw_reads:
            return None
        reads: list[dict[str, Any]] = []
        for entry in raw_reads[:8]:
            if isinstance(entry, dict) and str(entry.get("path") or "").strip():
                reads.append(
                    {
                        "path": str(entry["path"]).strip(),
                        "start_line": entry.get("start_line"),
                        "end_line": entry.get("end_line"),
                    }
                )
        if not reads:
            return None
        return {"action": action, "reads": reads, "thinking": thinking}

    tool_name = str(value.get("tool_name") or "").strip()
    tool_args = value.get("tool_args") if isinstance(value.get("tool_args"), dict) else {}
    encoded_args = json.dumps(tool_args, default=str)
    if len(encoded_args.encode("utf-8")) > MAX_TOOL_ARGS_BYTES:
        return None

    if action == "sandbox_tool":
        if not tool_name:
            return None
        return {"action": action, "tool_name": tool_name, "tool_args": tool_args, "thinking": thinking}

    if action == "local_shell":
        command = str(value.get("command") or "").strip()
        if not command:
            return None
        raw_args = value.get("args") or []
        if not isinstance(raw_args, list):
            raw_args = [str(raw_args)]
        shell_args = [str(item) for item in raw_args]
        cwd = value.get("cwd")
        shell_tool_args: dict[str, Any] = {"command": command, "args": shell_args}
        if cwd is not None:
            shell_tool_args["cwd"] = str(cwd).strip()
        return {
            "action": action,
            "command": command,
            "args": shell_args,
            "tool_args": shell_tool_args,
            "thinking": thinking,
        }

    if action == "mcp_tool":
        mcp_server = str(value.get("mcp_server") or "").strip()
        if not mcp_server or not tool_name:
            return None
        return {
            "action": action,
            "mcp_server": mcp_server,
            "tool_name": tool_name,
            "tool_args": tool_args,
            "thinking": thinking,
        }

    if action == "a2a_call":
        namespace = str(value.get("a2a_target_namespace") or "").strip()
        name = str(value.get("a2a_target_agent") or "").strip()
        if not namespace or not name:
            return None
        try:
            namespace = normalize_a2a_identifier(namespace, source="supervisor.a2a_target_namespace")
            name = normalize_a2a_identifier(name, source="supervisor.a2a_target_agent")
        except ValueError:
            return None
        delegated_prompt = truncate_text(
            str(value.get("prompt") or "").strip(),
            MAX_PROMPT_CHARS,
        )
        timeout_raw = value.get("a2a_timeout_seconds")
        timeout_seconds: float | None = None
        if timeout_raw not in (None, ""):
            try:
                timeout_seconds = max(float(timeout_raw), 1.0)
            except (TypeError, ValueError):
                return None
        return {
            "action": action,
            "a2a_target_namespace": namespace,
            "a2a_target_agent": name,
            "delegated_prompt": delegated_prompt,
            "a2a_timeout_seconds": timeout_seconds,
            "thinking": thinking,
        }

    if action == "subagent_team":
        raw_subagents = value.get("subagents")
        if not isinstance(raw_subagents, list) or not raw_subagents:
            return None
        try:
            strategy = normalize_subagent_strategy(value.get("subagent_strategy") or "sequential")
        except ValueError:
            return None

        subagents: list[dict[str, Any]] = []
        for item in raw_subagents[:MAX_SUBAGENTS]:
            try:
                subagent = SubagentRequest.model_validate(item)
            except Exception:
                continue
            subagents.append(subagent.model_dump())
        if not subagents:
            return None
        return {
            "action": action,
            "subagent_strategy": strategy,
            "subagents": subagents,
            "thinking": thinking,
        }

    return None


def build_reflection_prompt(
    objective: str,
    action_label: str,
    failure_summary: str,
    attempted_actions: list[dict[str, Any]] | None = None,
) -> SystemMessage:
    """Construct a focused reflection message after an action failure with error-specific guidance."""
    error_category, recovery_hint = classify_error(failure_summary)

    tried_text = ""
    if attempted_actions:
        tried_lines = [
            f"- {record.get('label', '?')}: {record.get('status', '?')}" for record in attempted_actions[-5:]
        ]
        tried_text = "\n\nActions attempted so far:\n" + "\n".join(tried_lines)

    return SystemMessage(
        content=(
            f"REFLECTION: The previous action '{action_label}' failed.\n"
            f"Error category: {error_category}\n"
            f"Failure details: {failure_summary}\n"
            f"Recovery hint: {recovery_hint}\n"
            f"Objective: {objective}\n"
            f"{tried_text}\n\n"
            "Before proposing a fix, answer these questions in your thinking:\n"
            "1. What assumption was wrong? What condition did you miss?\n"
            "2. Is this the same root cause as a previous failure, or a new one?\n"
            "3. How will your next attempt differ FUNDAMENTALLY from what already failed?\n\n"
            "Do NOT repeat the same action with the same arguments."
        )
    )


def detect_action_cycle(fingerprints: list[str], window_size: int = DOOM_LOOP_WINDOW_SIZE) -> bool:
    """Detect repeating cycles in the action fingerprint window.

    Checks for cycles of length 1 (AAA), 2 (ABAB), and 3 (ABCABC) in the
    last *window_size* fingerprints.
    """
    if len(fingerprints) < 2:
        return False

    window = fingerprints[-window_size:]

    # Length-1 cycle: same action repeated
    if len(set(window[-DOOM_LOOP_THRESHOLD:])) == 1 and len(window) >= DOOM_LOOP_THRESHOLD:
        return True

    # Length-2 cycle: ABAB pattern
    if len(window) >= 4:
        if window[-1] == window[-3] and window[-2] == window[-4]:
            return True

    # Length-3 cycle: ABCABC pattern
    if len(window) >= 6:
        if window[-1] == window[-4] and window[-2] == window[-5] and window[-3] == window[-6]:
            return True

    return False


def autonomous_action_fingerprint(action: dict[str, Any]) -> str:
    payload = {key: value for key, value in action.items() if key not in ("response", "thinking")}
    encoded = safe_json_dumps(payload)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def merge_autonomous_state(state: State, delta: dict[str, Any]) -> State:
    merged: State = dict(state)
    for key, value in delta.items():
        if key == "messages":
            merged["messages"] = [*(merged.get("messages") or []), *(value or [])]
            continue
        if key == "warnings":
            merged["warnings"] = dedupe_text_items([*(merged.get("warnings") or []), *(value or [])])
            continue
        merged[key] = value
    return merged


def autonomous_result_status(result: dict[str, Any]) -> str:
    return str(result.get("invoke_status") or "completed").strip().lower() or "completed"


def describe_autonomous_action(action: dict[str, Any]) -> str:
    action_name = str(action.get("action") or "action").strip() or "action"
    if action_name == "sandbox_tool":
        return f"Sandbox tool {str(action.get('tool_name') or '').strip() or '?'}"
    if action_name == "local_shell":
        cmd = str(action.get("command") or "").strip() or "?"
        return f"Local shell {cmd}"
    if action_name == "edit_file":
        path = str(action.get("path") or "").strip() or "?"
        return f"Edit file {path}"
    if action_name == "batch_read":
        count = len(action.get("reads") or [])
        return f"Batch read {count} files"
    if action_name == "plan":
        count = len(action.get("steps") or [])
        return f"Plan ({count} steps)"
    if action_name == "note":
        return "Note to scratchpad"
    if action_name == "git_commit":
        msg = str(action.get("message") or "").strip()[:60]
        return f"Git commit: {msg}" if msg else "Git commit"
    if action_name == "undo_edit":
        return "Undo last edit"
    if action_name == "edit_files":
        count = len(action.get("edits") or [])
        return f"Edit {count} files (transactional)"
    if action_name == "search_code":
        pattern = str(action.get("pattern") or "").strip()[:40]
        return f"Search code: {pattern}"
    if action_name == "parallel_tools":
        count = len(action.get("tool_calls") or [])
        return f"Parallel execution ({count} tools)"
    if action_name == "mcp_tool":
        return (
            f"MCP tool {str(action.get('mcp_server') or '').strip() or '?'}"
            f"/{str(action.get('tool_name') or '').strip() or '?'}"
        )
    if action_name == "a2a_call":
        return (
            f"A2A call {str(action.get('a2a_target_namespace') or '').strip() or '?'}"
            f"/{str(action.get('a2a_target_agent') or '').strip() or '?'}"
        )
    if action_name == "subagent_team":
        return "Subagent team"
    return f"Autonomous action {action_name}"


def blocked_tool_state(
    reason: str,
    *,
    tool_result: Any = None,
    error: str | None = None,
    error_type: str = "tool_error",
    retryable: bool = False,
    stop_reason: str | None = None,
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "messages": [AIMessage(content=blocked_response(reason))],
        "invoke_status": "blocked",
        "tool_result": tool_result,
        "error": error or reason,
        "error_type": error_type,
        "retryable": retryable,
        "stop_reason": stop_reason or error_type,
        "warnings": dedupe_text_items(list(warnings or [])),
    }


def resolve_local_tool_cwd(cwd: Any) -> str:
    if cwd in (None, ""):
        return default_local_tool_cwd()

    candidate = os.path.realpath(str(cwd))
    if not os.path.isdir(candidate):
        raise SandboxToolError(f"cwd '{candidate}' does not exist")

    for root in configured_local_tool_roots():
        real_root = os.path.realpath(root)
        with contextlib.suppress(ValueError):
            if os.path.commonpath([candidate, real_root]) == real_root:
                return candidate
    raise SandboxToolError(f"cwd '{candidate}' is outside the allowed local tool roots")


def classify_local_command_failure(command: str, exit_code: int) -> tuple[str, bool]:
    if command == "curl" and exit_code in {5, 6, 7, 18, 28, 35, 47, 52, 56}:
        return "transient_command_failure", True
    if command == "wget" and exit_code == 4:
        return "transient_command_failure", True
    return "command_failed", False


def execute_local_runtime_tool(tool_name: str, tool_args: dict[str, Any]) -> dict[str, Any]:
    metadata = local_runtime_metadata(refresh=bool((tool_args or {}).get("refresh")))
    available_commands = {
        str(item.get("name") or "").strip(): str(item.get("path") or "").strip()
        for item in (metadata.get("availableCommands") or [])
        if str(item.get("name") or "").strip() and str(item.get("path") or "").strip()
    }

    if tool_name == "local.command.list":
        return {
            "messages": [AIMessage(content=format_tool_payload(metadata))],
            "invoke_status": "completed",
            "tool_result": metadata,
            "available_local_commands": metadata.get("availableCommands") or [],
        }

    if tool_name != "local.command.run":
        return blocked_tool_state(
            f"Unsupported local runtime tool '{tool_name}'",
            error_type="unsupported_local_tool",
            stop_reason="unsupported_local_tool",
        )

    command = str((tool_args or {}).get("command") or "").strip()
    if not command:
        return blocked_tool_state(
            "local.command.run requires a non-empty 'command' argument",
            error_type="invalid_local_tool_args",
            stop_reason="invalid_local_tool_args",
        )

    if command not in LOCAL_TOOL_ALLOWLIST:
        return blocked_tool_state(
            f"Local command '{command}' is not on the allowlist",
            error_type="disallowed_local_command",
            stop_reason="disallowed_local_command",
        )

    resolved_path = available_commands.get(command)
    if not resolved_path:
        return blocked_tool_state(
            f"Local command '{command}' is not available in this runtime container",
            tool_result=metadata,
            error_type="missing_local_command",
            stop_reason="missing_local_command",
        )

    raw_args = (tool_args or {}).get("args") or []
    if not isinstance(raw_args, list):
        return blocked_tool_state(
            "local.command.run requires 'args' to be a list of strings",
            error_type="invalid_local_tool_args",
            stop_reason="invalid_local_tool_args",
        )
    if len(raw_args) > LOCAL_TOOL_MAX_ARGS:
        return blocked_tool_state(
            f"local.command.run accepts at most {LOCAL_TOOL_MAX_ARGS} arguments",
            error_type="invalid_local_tool_args",
            stop_reason="invalid_local_tool_args",
        )

    args = [str(item) for item in raw_args]
    if any(len(item) > LOCAL_TOOL_MAX_ARG_CHARS for item in args):
        return blocked_tool_state(
            f"local.command.run arguments must not exceed {LOCAL_TOOL_MAX_ARG_CHARS} characters",
            error_type="invalid_local_tool_args",
            stop_reason="invalid_local_tool_args",
        )

    timeout_seconds = LOCAL_TOOL_TIMEOUT_SECONDS
    if (tool_args or {}).get("timeout_seconds") not in (None, ""):
        try:
            timeout_seconds = max(float((tool_args or {}).get("timeout_seconds")), 1.0)
        except (TypeError, ValueError):
            return blocked_tool_state(
                "local.command.run timeout_seconds must be a positive number",
                error_type="invalid_local_tool_args",
                stop_reason="invalid_local_tool_args",
            )

    try:
        cwd = resolve_local_tool_cwd((tool_args or {}).get("cwd"))
    except SandboxToolError as exc:
        return blocked_tool_state(
            str(exc),
            error_type="invalid_local_tool_cwd",
            stop_reason="invalid_local_tool_cwd",
        )

    started_at = time.monotonic()
    try:
        completed = subprocess.run(
            [resolved_path, *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            shell=False,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return blocked_tool_state(
            f"Local command '{command}' timed out after {timeout_seconds:.1f}s",
            tool_result={
                "command": command,
                "args": args,
                "cwd": cwd,
                "timeoutSeconds": timeout_seconds,
            },
            error=str(exc),
            error_type="local_tool_timeout",
            retryable=True,
            stop_reason="local_tool_timeout",
        )
    except Exception as exc:
        return blocked_tool_state(
            f"Local command '{command}' failed before execution: {exc}",
            error=str(exc),
            error_type="local_tool_runtime_error",
            stop_reason="local_tool_runtime_error",
        )

    duration_seconds = round(time.monotonic() - started_at, 3)
    stdout_text = completed.stdout or ""
    stderr_text = completed.stderr or ""
    result_payload = {
        "command": command,
        "path": resolved_path,
        "args": args,
        "cwd": cwd,
        "timeoutSeconds": timeout_seconds,
        "durationSeconds": duration_seconds,
        "exitCode": completed.returncode,
        "stdout": truncate_text(stdout_text, LOCAL_TOOL_MAX_OUTPUT_CHARS),
        "stderr": truncate_text(stderr_text, LOCAL_TOOL_MAX_OUTPUT_CHARS),
        "stdoutTruncated": len(stdout_text) > LOCAL_TOOL_MAX_OUTPUT_CHARS,
        "stderrTruncated": len(stderr_text) > LOCAL_TOOL_MAX_OUTPUT_CHARS,
    }

    if completed.returncode != 0:
        error_type, retryable = classify_local_command_failure(command, completed.returncode)
        return blocked_tool_state(
            f"Local command '{command}' exited with code {completed.returncode}",
            tool_result=result_payload,
            error_type=error_type,
            retryable=retryable,
            stop_reason=error_type,
        )

    return {
        "messages": [AIMessage(content=format_tool_payload(result_payload))],
        "invoke_status": "completed",
        "tool_result": result_payload,
        "available_local_commands": metadata.get("availableCommands") or [],
    }


def autonomous_action_should_retry(result: dict[str, Any], retry_count: int) -> bool:
    if retry_count >= AUTONOMY_ACTION_RETRY_LIMIT:
        return False
    return autonomous_result_status(result) == "blocked" and bool(result.get("retryable"))


def execute_autonomous_action_with_retries(
    action_label: str,
    executor: Callable[[], dict[str, Any]],
) -> dict[str, Any]:
    retry_count = 0
    warnings: list[str] = []
    result = executor()
    while autonomous_action_should_retry(result, retry_count):
        retry_count += 1
        delay_seconds = AUTONOMY_ACTION_RETRY_BACKOFF_SECONDS * retry_count
        if delay_seconds > 0:
            time.sleep(delay_seconds)
        warnings.append(
            f"{action_label} transient failure; retrying attempt {retry_count + 1} of {AUTONOMY_ACTION_RETRY_LIMIT + 1}."
        )
        result = executor()

    if retry_count or warnings:
        result = {
            **result,
            "retry_count": retry_count,
            "warnings": dedupe_text_items([*(result.get("warnings") or []), *warnings]),
        }
    return result


def action_result_summary_text(result: dict[str, Any]) -> str:
    content = get_message_content((result.get("messages") or [None])[-1]).strip()
    if content:
        if is_blocked_response(content):
            return content.replace(f"{BLOCKED_RESPONSE_PREFIX}: ", "", 1).strip()
        return content
    if result.get("error"):
        return str(result.get("error") or "").strip()
    if result.get("tool_result") is not None:
        return format_tool_payload(result.get("tool_result"))
    return ""


def build_autonomous_failure_record(action_label: str, result: dict[str, Any]) -> dict[str, Any] | None:
    status = autonomous_result_status(result)
    if status in {"completed", "continue"} and not result.get("error"):
        return None

    summary = truncate_text(action_result_summary_text(result), MAX_CONTEXT_CHARS)
    if not summary:
        return None

    return {
        "action": action_label,
        "status": status,
        "errorType": str(result.get("error_type") or "tool_error").strip() or "tool_error",
        "message": summary,
        "retryable": bool(result.get("retryable")),
        "retryCount": int(result.get("retry_count") or 0),
        "stopReason": str(result.get("stop_reason") or "").strip() or None,
    }


def enrich_autonomous_action_result(
    action_label: str,
    prior_state: State,
    result: dict[str, Any],
) -> dict[str, Any]:
    failure_record = build_autonomous_failure_record(action_label, result)
    recent_failures = [item for item in (prior_state.get("recent_failures") or []) if isinstance(item, dict)]
    if failure_record is not None:
        recent_failures = [*recent_failures, failure_record][-AUTONOMY_FAILURE_HISTORY_LIMIT:]
    return {
        **result,
        "last_step_error": failure_record,
        "recent_failures": recent_failures,
    }


def autonomous_terminal_state(state: State, **updates: Any) -> dict[str, Any]:
    terminal = {key: value for key, value in state.items() if key != "messages"}
    terminal.update(updates)
    return terminal


def autonomous_result_requires_stop(result: dict[str, Any]) -> bool:
    status = autonomous_result_status(result)
    if status in {"approval_pending", "pending"}:
        return True

    if result.get("approval_name"):
        return True

    retry_after_seconds = result.get("retry_after_seconds")
    if retry_after_seconds not in (None, "", 0, 0.0):
        return True

    stop_reason = str(result.get("stop_reason") or "").strip().lower()
    return stop_reason in {"approval_pending", "human_approval_required"}


def build_autonomous_action_observation(action_label: str, result: dict[str, Any]) -> AIMessage:
    status = autonomous_result_status(result)
    stop_reason = str(result.get("stop_reason") or "").strip()
    content = get_message_content((result.get("messages") or [None])[-1]).strip()

    if not content and result.get("tool_result") is not None:
        content = format_tool_payload(result.get("tool_result"))
    if not content and result.get("subagent_results") is not None:
        content = format_tool_payload(result.get("subagent_results"))
    if not content and result.get("a2a") is not None:
        content = format_tool_payload(result.get("a2a"))
    if not content:
        content = str(result.get("error") or "").strip()

    warnings = dedupe_text_items([str(item).strip() for item in (result.get("warnings") or []) if str(item).strip()])

    lines = [f"{action_label} result" if status == "completed" else f"{action_label} returned status '{status}'"]
    if stop_reason and stop_reason != "response":
        lines.append(f"Stop reason: {stop_reason}")
    if content:
        lines.append(content)
    if warnings:
        lines.append(f"Warnings: {'; '.join(warnings[:3])}")
    return AIMessage(content="\n".join(lines).strip())


def normalize_autonomous_action_result(action_label: str, result: dict[str, Any]) -> dict[str, Any]:
    status = autonomous_result_status(result)
    publish_runtime_event(
        "agent.step.result",
        {
            "mode": "autonomy",
            "action": action_label,
            "status": status,
            "stopReason": str(result.get("stop_reason") or "").strip() or None,
            "approvalName": result.get("approval_name"),
            "retryAfterSeconds": result.get("retry_after_seconds"),
        },
    )

    if status == "continue":
        return result

    if status == "completed" or (AUTONOMY_CONTINUE_ON_ACTION_ERROR and not autonomous_result_requires_stop(result)):
        return {
            **result,
            "messages": [build_autonomous_action_observation(action_label, result)],
            "invoke_status": "continue",
            "stop_reason": "",
        }

    return result


def _is_destructive_action(decision: dict[str, Any]) -> bool:
    """Check if an action is destructive (deletes files, force-pushes, etc.)."""
    action_name = str(decision.get("action") or "")
    if action_name == "sandbox_tool":
        tool = str(decision.get("tool_name") or "")
        if tool in DESTRUCTIVE_TOOL_PATTERNS:
            return True
    if action_name == "local_shell":
        cmd = str(decision.get("command") or "").strip()
        args = decision.get("args") or []
        full_cmd = f"{cmd} {' '.join(str(a) for a in args)}".strip()
        for pattern in DESTRUCTIVE_SHELL_COMMANDS:
            if full_cmd.startswith(pattern):
                return True
    return False


def _auto_lint_command(path: str, workspace_profile: dict[str, Any] | None) -> tuple[str, list[str]] | None:
    """Return (command, args) for a lint check based on project type and file extension."""
    if not isinstance(workspace_profile, dict):
        return None
    project_type = workspace_profile.get("projectType", "")
    ext = path.rsplit(".", 1)[-1].lower() if "." in path else ""

    if ext == "py" or (project_type == "python" and not ext):
        return ("python", ["-c", f"import py_compile; py_compile.compile('{path}', doraise=True)"])
    if ext in ("go",) or project_type == "go":
        return ("go", ["vet", path])
    return None


def _auto_test_command(workspace_profile: dict[str, Any] | None) -> tuple[str, list[str]] | None:
    """Return (command, args) for auto-test based on workspace profile testCommand."""
    if not isinstance(workspace_profile, dict):
        return None
    test_cmd = str(workspace_profile.get("testCommand") or "").strip()
    if not test_cmd:
        return None
    parts = test_cmd.split()
    return (parts[0], parts[1:]) if parts else None


def run_autonomous_session(
    state: State,
    *,
    plan_invoke: Callable[[list[Any]], Any],
    execute_action: Callable[[dict[str, Any], State], dict[str, Any]],
) -> dict[str, Any]:
    local_state: State = dict(state)
    step_count = int(local_state.get("step_count") or 0)
    attempted_actions: list[dict[str, Any]] = list(local_state.get("attempted_actions") or [])
    action_fingerprints: list[str] = list(local_state.get("action_fingerprints") or [])
    doom_loop_warned = bool(local_state.get("doom_loop_warned"))
    objective = str(local_state.get("request_prompt") or "").strip()
    files_modified: list[str] = list(local_state.get("files_modified") or [])
    active_plan: list[str] = list(local_state.get("active_plan") or [])
    plan_step_index: int = int(local_state.get("plan_step_index") or 0)
    scratchpad: list[str] = list(local_state.get("scratchpad") or [])
    consecutive_failures: int = int(local_state.get("consecutive_failures") or 0)
    replan_count: int = int(local_state.get("replan_count") or 0)
    edit_history: list[dict[str, str]] = list(local_state.get("edit_history") or [])

    # Per-session tool result cache for idempotent reads
    _CACHEABLE_TOOLS = frozenset({"filesystem.read", "filesystem.ls", "filesystem.list"})
    _CACHE_BUSTING_TOOLS = frozenset({"filesystem.write", "filesystem.delete"})
    _tool_cache: dict[str, Any] = {}

    def _cached_execute(action: dict[str, Any], loop_state: State) -> dict[str, Any]:
        action_name = action.get("action", "")
        tool_name = str(action.get("tool_name", ""))
        # Invalidate on writes
        if action_name == "edit_file" or (action_name == "sandbox_tool" and tool_name in _CACHE_BUSTING_TOOLS):
            _tool_cache.clear()
        # Cache idempotent reads
        if action_name == "sandbox_tool" and tool_name in _CACHEABLE_TOOLS:
            cache_key = safe_json_dumps({"tool": tool_name, "args": action.get("tool_args", {})})
            cached = _tool_cache.get(cache_key)
            if cached is not None:
                return cached
            result = execute_action(action, loop_state)
            if str(result.get("invoke_status", "")) in ("completed", "continue"):
                if len(_tool_cache) < TOOL_CACHE_MAX_ENTRIES:
                    _tool_cache[cache_key] = result
            return result
        return execute_action(action, loop_state)

    # Workspace scanning on first step — auto-detect project context
    if not local_state.get("workspace_scanned"):
        local_state["workspace_scanned"] = True
        try:

            def _scan_tool(tool_name: str, tool_args: dict) -> dict:
                return execute_action(
                    {"action": "sandbox_tool", "tool_name": tool_name, "tool_args": tool_args},
                    local_state,
                )

            profile = scan_workspace_profile(_scan_tool)
            if profile:
                local_state["workspace_profile"] = profile
                publish_runtime_event(
                    "agent.workspace_scan",
                    {"projectType": profile.get("projectType", "unknown")},
                )
        except Exception as exc:
            logger.debug("Workspace scan failed (non-fatal): %s", exc)

    while True:
        max_steps = int(local_state.get("max_steps") or DEFAULT_MAX_AUTONOMY_STEPS)
        if step_count >= max_steps:
            return autonomous_terminal_state(
                local_state,
                messages=[
                    AIMessage(
                        content=blocked_response(
                            f"autonomy step budget of {max_steps} was exhausted before a final answer was produced"
                        )
                    )
                ],
                invoke_status="blocked",
                step_count=step_count,
                stop_reason="max_steps_exceeded",
            )

        # Update state with tracking fields before building supervisor messages
        local_state["attempted_actions"] = attempted_actions
        local_state["action_fingerprints"] = action_fingerprints
        local_state["files_modified"] = files_modified
        local_state["active_plan"] = active_plan
        local_state["plan_step_index"] = plan_step_index
        local_state["scratchpad"] = scratchpad
        local_state["consecutive_failures"] = consecutive_failures
        local_state["replan_count"] = replan_count
        local_state["edit_history"] = edit_history

        llm_response = plan_invoke(build_supervisor_messages(local_state))
        raw_decision = get_message_content(llm_response).strip()

        # Accumulate token usage from LLM response
        _usage = getattr(llm_response, "usage_metadata", None) or {}
        if _usage:
            _tu = local_state.get("token_usage") or {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
            }
            _tu["prompt_tokens"] = _tu.get("prompt_tokens", 0) + int(_usage.get("input_tokens", 0))
            _tu["completion_tokens"] = _tu.get("completion_tokens", 0) + int(_usage.get("output_tokens", 0))
            _tu["total_tokens"] = _tu["prompt_tokens"] + _tu["completion_tokens"]
            _tu["cost_usd"] = _calculate_cost_usd(
                _tu["prompt_tokens"],
                _tu["completion_tokens"],
                str(local_state.get("selected_model") or MODEL_NAME),
            )
            local_state["token_usage"] = _tu
            publish_runtime_event("agent.tokens", _tu)

            # Token budget enforcement
            if MAX_TOKEN_BUDGET > 0 and _tu["total_tokens"] >= MAX_TOKEN_BUDGET:
                return autonomous_terminal_state(
                    local_state,
                    messages=[
                        AIMessage(
                            content=blocked_response(
                                f"token budget of {MAX_TOKEN_BUDGET} was exhausted (used {_tu['total_tokens']} tokens)"
                            )
                        )
                    ],
                    invoke_status="blocked",
                    step_count=step_count,
                    stop_reason="token_budget_exceeded",
                )

        # Native tool calling: parse tool_calls from response if available
        _tool_calls = getattr(llm_response, "tool_calls", None) or []
        decision = None
        if _tool_calls and isinstance(_tool_calls, list):
            try:
                decision = parse_tool_call_to_action(_tool_calls[0])
            except Exception as exc:
                logger.debug("Failed to parse tool_call, falling back to text: %s", exc)

        # Fall back to text JSON parsing
        if decision is None:
            if not raw_decision:
                return autonomous_terminal_state(
                    local_state,
                    messages=[AIMessage(content=blocked_response("autonomy supervisor returned an empty decision"))],
                    invoke_status="blocked",
                    step_count=step_count,
                    stop_reason="empty_decision",
                )

            decision = normalize_supervisor_action(extract_json_object(raw_decision))
            if decision is None:
                publish_runtime_event(
                    "agent.step",
                    {"mode": "autonomy", "step": step_count + 1, "action": "respond", "fallback": True},
                )
                return autonomous_terminal_state(
                    local_state,
                    messages=[AIMessage(content=raw_decision)],
                    invoke_status="completed",
                    step_count=step_count,
                    stop_reason="fallback_response",
                )

        # Log chain-of-thought thinking
        thinking = decision.get("thinking", "")
        if thinking:
            publish_runtime_event(
                "agent.step.thinking",
                {"mode": "autonomy", "step": step_count + 1, "thinking": thinking},
            )

        publish_runtime_event(
            "agent.step",
            {"mode": "autonomy", "step": step_count + 1, "action": decision["action"]},
        )

        # Handle plan action inline — updates state without consuming a step
        if decision["action"] == "plan":
            # Track re-planning
            if active_plan:
                replan_count += 1
                local_state["replan_count"] = replan_count
            active_plan = decision["steps"]
            plan_step_index = 0
            consecutive_failures = 0  # Reset failure counter on replan
            local_state["active_plan"] = active_plan
            local_state["plan_step_index"] = plan_step_index
            plan_msg = f"Plan created with {len(active_plan)} steps:\n"
            plan_msg += "\n".join(f"  {i + 1}. {s}" for i, s in enumerate(active_plan))
            local_state["messages"] = [
                *(local_state.get("messages") or []),
                AIMessage(content=plan_msg),
            ]
            publish_runtime_event(
                "agent.plan",
                {"steps": active_plan, "stepCount": len(active_plan)},
            )
            attempted_actions.append(
                {
                    "step": step_count,
                    "label": describe_autonomous_action(decision),
                    "status": "completed",
                    "thinking": thinking[:120] if thinking else "",
                }
            )
            continue

        # Handle note action inline — saves to scratchpad without consuming a step
        if decision["action"] == "note":
            note_text = decision["note"]
            scratchpad.append(note_text)
            if len(scratchpad) > MAX_SCRATCHPAD_ENTRIES:
                scratchpad = scratchpad[-MAX_SCRATCHPAD_ENTRIES:]
            local_state["scratchpad"] = scratchpad
            local_state["messages"] = [
                *(local_state.get("messages") or []),
                AIMessage(content=f"Note saved: {note_text}"),
            ]
            attempted_actions.append(
                {
                    "step": step_count,
                    "label": "Note to scratchpad",
                    "status": "completed",
                    "thinking": thinking[:120] if thinking else "",
                }
            )
            continue

        if decision["action"] == "respond":
            response_text = decision["response"]
            # Append change summary if files were modified
            if files_modified:
                unique_files = list(dict.fromkeys(files_modified))
                summary = "\n\n---\n**Changes made:**\n"
                summary += "\n".join(f"- {f}" for f in unique_files)
                response_text = response_text + summary
            return autonomous_terminal_state(
                local_state,
                messages=[AIMessage(content=response_text)],
                invoke_status="completed",
                step_count=step_count,
                stop_reason="response",
            )

        # Sliding-window doom loop detection
        fingerprint = autonomous_action_fingerprint(decision)
        action_fingerprints.append(fingerprint)
        cycle_detected = detect_action_cycle(action_fingerprints)

        if cycle_detected:
            if doom_loop_warned:
                # Second detection — hard stop
                return autonomous_terminal_state(
                    local_state,
                    messages=[
                        AIMessage(
                            content=blocked_response(
                                "autonomy loop stopped: repeated action cycle detected after warning"
                            )
                        )
                    ],
                    invoke_status="blocked",
                    step_count=step_count,
                    stop_reason="doom_loop_detected",
                )
            else:
                # First detection — inject warning and give one more chance
                doom_loop_warned = True
                local_state["doom_loop_warned"] = True
                action_label = describe_autonomous_action(decision)
                reflection = build_reflection_prompt(
                    objective,
                    action_label,
                    "You are repeating the same sequence of actions. This is not making progress. "
                    "STOP and reconsider: (1) Is the goal achievable with your current tools? "
                    "(2) Is there a prerequisite you missed? (3) Try a completely different approach "
                    "rather than variations of the same strategy.",
                    attempted_actions,
                )
                local_state["messages"] = [*(local_state.get("messages") or []), reflection]
                logger.warning("Doom loop warning injected at step %d", step_count + 1)
                continue

        step_count += 1
        local_state["step_count"] = step_count
        action_label = describe_autonomous_action(decision)

        # Destructive operation gate — block or require approval for dangerous actions
        if _is_destructive_action(decision):
            publish_runtime_event(
                "agent.step.destructive",
                {"mode": "autonomy", "step": step_count, "action": action_label},
            )
            # Check if this action is pre-authorized (e.g. by a workflow orchestrator)
            _pre_auth = list(local_state.get("pre_authorized_actions") or [])
            _action_pre_authorized = False
            if _pre_auth:
                cmd = str(decision.get("command") or "").strip()
                args = decision.get("args") or []
                full_cmd = f"{cmd} {' '.join(str(a) for a in args)}".strip()
                for allowed in _pre_auth:
                    if full_cmd.startswith(allowed):
                        _action_pre_authorized = True
                        break
            if DESTRUCTIVE_ACTION_GATE and not _action_pre_authorized:
                # Check if we have HITL approval flow available
                require_approval = bool(local_state.get("require_approval"))
                if require_approval:
                    try:
                        approval = hitl_gate(
                            action_description=f"Destructive action: {action_label}",
                            tool_name=decision.get("tool_name") or decision.get("command") or decision["action"],
                            tool_args=decision.get("tool_args") or {},
                            request_id=str(local_state.get("thread_id") or "autonomous"),
                        )
                        if approval.get("decision") != "approved":
                            result_messages = [
                                AIMessage(
                                    content=blocked_response(
                                        f"Destructive action '{action_label}' was denied by human reviewer. "
                                        "Choose a non-destructive alternative."
                                    )
                                )
                            ]
                            local_state["messages"] = [*(local_state.get("messages") or []), *result_messages]
                            attempted_actions.append(
                                {
                                    "step": step_count,
                                    "label": action_label,
                                    "status": "denied",
                                    "thinking": thinking[:120] if thinking else "",
                                }
                            )
                            continue
                    except PermissionError:
                        result_messages = [
                            AIMessage(
                                content=blocked_response(
                                    f"Destructive action '{action_label}' requires human approval which was denied."
                                )
                            )
                        ]
                        local_state["messages"] = [*(local_state.get("messages") or []), *result_messages]
                        attempted_actions.append(
                            {
                                "step": step_count,
                                "label": action_label,
                                "status": "denied",
                                "thinking": thinking[:120] if thinking else "",
                            }
                        )
                        continue
                    except Exception as hitl_exc:
                        logger.debug("HITL gate check failed (non-fatal): %s", hitl_exc)
                else:
                    # No explicit HITL but gate is enabled: emit strong warning
                    local_state["messages"] = [
                        *(local_state.get("messages") or []),
                        SystemMessage(
                            content=(
                                f"WARNING: The action '{action_label}' is destructive and potentially irreversible. "
                                "Proceeding, but prefer non-destructive alternatives when possible."
                            )
                        ),
                    ]

        # Emit step progress event for UI
        publish_runtime_event(
            "agent.step.progress",
            {
                "mode": "autonomy",
                "step": step_count,
                "maxSteps": max_steps,
                "action": action_label,
                "planStep": plan_step_index if active_plan else None,
                "planTotal": len(active_plan) if active_plan else None,
            },
        )

        publish_runtime_event(
            "agent.step.tool_start",
            {"mode": "autonomy", "step": step_count, "action": action_label},
        )

        raw_result = execute_autonomous_action_with_retries(
            action_label,
            lambda: _cached_execute(decision, local_state),
        )

        publish_runtime_event(
            "agent.step.tool_complete",
            {
                "mode": "autonomy",
                "step": step_count,
                "action": action_label,
                "status": autonomous_result_status(raw_result) if isinstance(raw_result, dict) else "unknown",
            },
        )

        normalized_result = normalize_autonomous_action_result(action_label, raw_result)
        result = enrich_autonomous_action_result(action_label, local_state, normalized_result)

        # Track attempted action
        action_status = autonomous_result_status(result)
        attempted_actions.append(
            {
                "step": step_count,
                "label": action_label,
                "status": action_status,
                "thinking": thinking[:120] if thinking else "",
            }
        )

        # Track file modifications for change summary
        if action_status in ("completed", "continue"):
            consecutive_failures = 0  # Reset on success
            if decision["action"] == "edit_file":
                edited_path = str(decision.get("path") or "").strip()
                if edited_path:
                    files_modified.append(edited_path)
                # Track edit record for undo support
                _edit_record = result.get("_edit_record")
                if _edit_record and isinstance(_edit_record, dict):
                    edit_history.append(_edit_record)
                    # Cap history to prevent unbounded growth
                    if len(edit_history) > 50:
                        edit_history = edit_history[-50:]
                    local_state["edit_history"] = edit_history
            elif decision["action"] == "edit_files":
                # Track multi-file edit records
                _edit_records = result.get("_edit_records")
                if isinstance(_edit_records, list):
                    for rec in _edit_records:
                        if isinstance(rec, dict) and rec.get("path"):
                            files_modified.append(rec["path"])
                            edit_history.append(rec)
                    if len(edit_history) > 50:
                        edit_history = edit_history[-50:]
                    local_state["edit_history"] = edit_history
            elif decision["action"] == "sandbox_tool":
                tool = str(decision.get("tool_name") or "")
                if tool in ("filesystem.write", "filesystem.delete"):
                    written_path = str((decision.get("tool_args") or {}).get("path") or "")
                    if written_path:
                        files_modified.append(written_path)

            # Advance plan step index when an action succeeds
            if active_plan and plan_step_index < len(active_plan):
                plan_step_index += 1
                local_state["plan_step_index"] = plan_step_index

            # Refresh git diff stat after file changes
            if files_modified:
                try:
                    diff_result = _cached_execute(
                        {
                            "action": "local_shell",
                            "command": "git",
                            "args": ["diff", "--stat"],
                            "tool_args": {"command": "git", "args": ["diff", "--stat"]},
                        },
                        local_state,
                    )
                    if str(diff_result.get("invoke_status") or "") in ("completed", "continue"):
                        diff_text = get_message_content((diff_result.get("messages") or [None])[-1]).strip()
                        local_state["git_diff_stat"] = truncate_text(diff_text, 1000)
                except Exception:
                    pass  # git may not be available
        else:
            consecutive_failures += 1

        # Inject self-reflection after failures
        if action_status not in ("completed", "continue") and AUTONOMY_CONTINUE_ON_ACTION_ERROR:
            failure_summary = str(result.get("error") or result.get("stop_reason") or "unknown failure")
            reflection = build_reflection_prompt(objective, action_label, failure_summary, attempted_actions)
            # Append reflection to result messages so it enters the conversation
            result_messages = list(result.get("messages") or [])
            result_messages.append(reflection)

            # Adaptive re-planning: after consecutive failures with an active plan
            if active_plan and consecutive_failures >= ADAPTIVE_REPLAN_THRESHOLD and replan_count < MAX_REPLAN_COUNT:
                replan_hint = SystemMessage(
                    content=(
                        f"REPLAN: Steps {plan_step_index}-{plan_step_index + 1} have failed "
                        f"{consecutive_failures} times consecutively. Your current plan approach "
                        "is not working.\n\n"
                        "Diagnose the failure pattern before re-planning:\n"
                        "- Are you hitting the same error each time? \u2192 The approach itself is flawed.\n"
                        "- Different errors each time? \u2192 You may be missing a prerequisite.\n"
                        "- Permissions or environment issue? \u2192 Work around it, don't retry through it.\n\n"
                        "Issue a new `plan` action with a FUNDAMENTALLY different strategy. "
                        "Explain in your thinking what went wrong and how the new approach differs."
                    )
                )
                result_messages.append(replan_hint)
                logger.info(
                    "Replan hint injected after %d consecutive failures at step %d",
                    consecutive_failures,
                    step_count,
                )

            result = {**result, "messages": result_messages}
            logger.info("Self-reflection injected after failure at step %d: %s", step_count, action_label)

        # Auto-verify + auto-lint after file edits
        if action_status in ("completed", "continue") and decision["action"] in ("edit_file", "edit_files"):
            verify_path = str(decision.get("path") or "").strip()
            if not verify_path and decision["action"] == "edit_files":
                # Use first edited path for lint/test verification
                _edits_list = decision.get("edits") or []
                if _edits_list:
                    verify_path = str(_edits_list[0].get("path") or "").strip()
            if verify_path:
                result_messages = list(result.get("messages") or [])
                # Try auto-lint if we have a lint command
                lint_cmd = _auto_lint_command(
                    verify_path,
                    local_state.get("workspace_profile"),
                )
                if lint_cmd:
                    try:
                        lint_result = _cached_execute(
                            {
                                "action": "local_shell",
                                "command": lint_cmd[0],
                                "args": lint_cmd[1],
                                "tool_args": {
                                    "command": lint_cmd[0],
                                    "args": lint_cmd[1],
                                },
                            },
                            local_state,
                        )
                        lint_status = str(lint_result.get("invoke_status") or "completed")
                        lint_output = get_message_content((lint_result.get("messages") or [None])[-1]).strip()
                        if lint_status in ("completed", "continue") and lint_output:
                            result_messages.append(SystemMessage(content=f"AUTO-LINT passed for '{verify_path}'."))
                        elif lint_output:
                            result_messages.append(
                                SystemMessage(
                                    content=(
                                        f"AUTO-LINT FAILED for '{verify_path}':\\n{lint_output[:1000]}\\n"
                                        "Fix the syntax error before proceeding."
                                    )
                                )
                            )
                    except Exception as lint_exc:
                        logger.debug("Auto-lint failed (non-fatal): %s", lint_exc)
                else:
                    result_messages.append(
                        SystemMessage(
                            content=(
                                f"VERIFY: You just edited '{verify_path}'. "
                                "Consider reading the file or running tests to confirm the change is correct."
                            )
                        )
                    )

                # Auto-test: run project test suite after edits (best-effort)
                # If tests fail and AUTO_TEST_FIX_RETRIES > 0, the failure output
                # is injected as a strong reflection message so the agent's next
                # iteration can self-correct.
                test_cmd = _auto_test_command(local_state.get("workspace_profile"))
                if test_cmd:
                    _test_fix_attempts = local_state.get("_test_fix_attempts", 0)
                    try:
                        _tool_cache.clear()  # Ensure fresh test run
                        test_result = _cached_execute(
                            {
                                "action": "local_shell",
                                "command": test_cmd[0],
                                "args": test_cmd[1],
                                "tool_args": {"command": test_cmd[0], "args": test_cmd[1]},
                            },
                            local_state,
                        )
                        test_status = str(test_result.get("invoke_status") or "completed")
                        test_output = get_message_content((test_result.get("messages") or [None])[-1]).strip()
                        truncated_output = test_output[:AUTO_TEST_MAX_OUTPUT_CHARS] if test_output else ""
                        if test_status in ("completed", "continue"):
                            result_messages.append(
                                SystemMessage(content=f"AUTO-TEST passed after editing '{verify_path}'.")
                            )
                            local_state["_test_fix_attempts"] = 0
                        elif truncated_output:
                            if _test_fix_attempts < AUTO_TEST_FIX_RETRIES:
                                local_state["_test_fix_attempts"] = _test_fix_attempts + 1
                                result_messages.append(
                                    SystemMessage(
                                        content=(
                                            f"AUTO-TEST FAILED (attempt {_test_fix_attempts + 1}/{AUTO_TEST_FIX_RETRIES}) "
                                            f"after editing '{verify_path}':\n"
                                            f"{truncated_output}\n\n"
                                            "YOU MUST fix this test failure NOW before moving on.\n"
                                            "1. Read the full error trace — which assertion failed and why?\n"
                                            "2. Is the test expectation correct, or is the implementation wrong?\n"
                                            "3. Apply a targeted fix with edit_file based on the root cause."
                                        )
                                    )
                                )
                            else:
                                result_messages.append(
                                    SystemMessage(
                                        content=(
                                            f"AUTO-TEST FAILED after editing '{verify_path}' "
                                            f"(exhausted {AUTO_TEST_FIX_RETRIES} auto-fix retries):\n"
                                            f"{truncated_output}\n\n"
                                            "Auto-fix retries are exhausted. Read the failure carefully "
                                            "and fix the root cause before proceeding — do not ignore "
                                            "failing tests."
                                        )
                                    )
                                )
                                local_state["_test_fix_attempts"] = 0
                        publish_runtime_event(
                            "agent.auto_test",
                            {
                                "path": verify_path,
                                "passed": test_status in ("completed", "continue"),
                                "attempt": _test_fix_attempts + 1,
                            },
                        )
                    except Exception as test_exc:
                        logger.debug("Auto-test failed (non-fatal): %s", test_exc)

                result = {**result, "messages": result_messages}

        local_state = merge_autonomous_state(local_state, result)

        if str(result.get("invoke_status") or "continue") != "continue":
            local_state.setdefault("stop_reason", result.get("stop_reason") or "action_stopped")
            local_state.setdefault("step_count", step_count)
            return local_state


def blocked_response(reason: str) -> str:
    return f"{BLOCKED_RESPONSE_PREFIX}: {reason}"


def is_blocked_response(text: str) -> bool:
    return text.startswith(BLOCKED_RESPONSE_PREFIX)


def build_request_guard_text(
    prompt: str,
    tool_name: str,
    tool_args: dict[str, Any],
    mcp_server: str,
    a2a_target_agent: str,
    a2a_target_namespace: str,
    subagents: list[dict[str, Any]] | None = None,
) -> str:
    sections: list[str] = []
    if prompt.strip():
        sections.append(prompt.strip())

    if tool_name.strip():
        tool_payload: dict[str, Any] = {
            "tool_name": tool_name.strip(),
            "tool_args": tool_args,
        }
        if mcp_server.strip():
            tool_payload["mcp_server"] = mcp_server.strip()
        sections.append(safe_json_dumps(tool_payload))

    if a2a_target_agent.strip() and a2a_target_namespace.strip():
        sections.append(
            safe_json_dumps(
                {
                    "a2a_target_agent": a2a_target_agent.strip(),
                    "a2a_target_namespace": a2a_target_namespace.strip(),
                }
            )
        )

    if subagents:
        sections.append(
            safe_json_dumps(
                {
                    "subagents": [
                        {
                            "name": str(item.get("name") or "").strip(),
                            "namespace": str(item.get("namespace") or "").strip(),
                            "role": str(item.get("role") or "").strip() or None,
                            "task": str(item.get("task") or "").strip() or None,
                        }
                        for item in subagents
                        if isinstance(item, dict)
                    ]
                }
            )
        )

    return "\n\n".join(section for section in sections if section)


def sanitize_public_payload(value: Any, guardrails: GuardrailsEngine) -> Any:
    if isinstance(value, str):
        return guardrails.sanitize_output(value)
    if isinstance(value, list):
        return [sanitize_public_payload(item, guardrails) for item in value]
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key, item in value.items():
            if key == "headers" and isinstance(item, dict):
                sanitized[key] = {"redacted": True, "count": len(item)}
                continue
            sanitized[key] = sanitize_public_payload(item, guardrails)
        return sanitized
    return value


def prepare_subagent_shared_files(
    file_refs: list[dict[str, Any]],
    sandbox_session: dict[str, Any] | None,
    *,
    target_agent: str,
    target_namespace: str,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None, list[str]]:
    if not file_refs:
        return [], sandbox_session, []

    if not isinstance(sandbox_session, dict):
        warning = f"Skipped shared file snapshots for {target_namespace}/{target_agent} because no sandbox_session was available."
        return [], sandbox_session, [warning]

    current_session = sandbox_session
    snapshots: list[dict[str, Any]] = []
    warnings: list[str] = []

    for file_ref in file_refs:
        path = str(file_ref.get("path") or "").strip()
        if not path:
            continue

        publish_runtime_event(
            "subagent.file",
            {
                "status": "started",
                "action": "read",
                "path": path,
                "targetAgent": target_agent,
                "targetNamespace": target_namespace,
            },
        )
        try:
            result, next_session = _run_async(
                execute_sandbox_tool(
                    "sandbox.filesystem.read",
                    {"path": path},
                    current_session,
                    publish_runtime_event,
                )
            )
            current_session = merge_sandbox_sessions(current_session, next_session)
            content = ""
            if isinstance(result, dict):
                content = truncate_text(
                    str(result.get("content") or ""),
                    int(file_ref.get("max_chars") or MAX_SUBAGENT_FILE_CHARS),
                )

            snapshot: dict[str, Any] = {
                "path": path,
                "purpose": str(file_ref.get("purpose") or "").strip() or None,
                "chars": len(content),
            }
            if bool(file_ref.get("include_content", True)) and content:
                snapshot["content"] = content
            snapshots.append(snapshot)
            publish_runtime_event(
                "subagent.file",
                {
                    "status": "prepared",
                    "action": "read",
                    "path": path,
                    "chars": len(content),
                    "targetAgent": target_agent,
                    "targetNamespace": target_namespace,
                },
            )
        except Exception as exc:
            warning = f"Unable to prepare shared file '{path}' for {target_namespace}/{target_agent}: {exc}"
            warnings.append(warning)
            publish_runtime_event(
                "subagent.file",
                {
                    "status": "failed",
                    "action": "read",
                    "path": path,
                    "targetAgent": target_agent,
                    "targetNamespace": target_namespace,
                    "error": str(exc),
                },
            )

    return snapshots, current_session, warnings


def build_subagent_team_context(
    state: State,
    subagent: dict[str, Any],
    *,
    target_thread_id: str,
    shared_files: list[dict[str, Any]],
    team_messages: list[dict[str, Any]],
    strategy: str,
    position: int,
    total_subagents: int,
) -> dict[str, Any]:
    target_agent = str(subagent.get("name") or "").strip()
    target_namespace = str(subagent.get("namespace") or "").strip()
    role = str(subagent.get("role") or "").strip()
    task = str(subagent.get("task") or "").strip()

    team_context = build_outbound_team_context(state, target_agent, target_namespace, target_thread_id)
    team_context["mode"] = "subagent-orchestration"
    team_context["orchestration"] = {
        "strategy": strategy,
        "position": position,
        "totalSubagents": total_subagents,
    }
    if role or task:
        specialization: dict[str, Any] = {}
        if role:
            specialization["role"] = role
        if task:
            specialization["task"] = task
        team_context["specialization"] = specialization

    shared_file_metadata = [
        {
            "path": item.get("path"),
            "purpose": item.get("purpose"),
            "chars": item.get("chars"),
        }
        for item in shared_files
    ]
    if shared_file_metadata:
        team_context["sharedFiles"] = shared_file_metadata

    compact_messages = [
        {
            "name": item.get("name"),
            "namespace": item.get("namespace"),
            "role": item.get("role"),
            "status": item.get("status"),
            "summary": truncate_text(str(item.get("summary") or ""), 320),
        }
        for item in team_messages[-4:]
        if str(item.get("summary") or "").strip()
    ]
    if compact_messages:
        team_context["teamMessages"] = compact_messages

    metadata = subagent.get("metadata")
    if isinstance(metadata, dict) and metadata:
        team_context["subagentMetadata"] = metadata

    if bool(subagent.get("share_sandbox_session", True)) and isinstance(state.get("sandbox_session"), dict):
        team_context["sharedSandboxSession"] = True

    try:
        return (
            normalize_json_object(
                team_context,
                field_name="team_context",
                max_chars=TEAM_CONTEXT_MAX_CHARS,
            )
            or {}
        )
    except ValueError:
        return {
            "mode": "subagent-orchestration",
            "objective": truncate_text(str(state.get("request_prompt") or ""), 1024),
            "caller": team_context.get("caller"),
            "target": {"name": target_agent, "namespace": target_namespace, "threadId": target_thread_id},
            "orchestration": {"strategy": strategy, "position": position, "totalSubagents": total_subagents},
            "specialization": team_context.get("specialization"),
            "sharedFiles": shared_file_metadata,
        }


def build_subagent_prompt(
    state: State,
    subagent: dict[str, Any],
    *,
    shared_files: list[dict[str, Any]],
    team_messages: list[dict[str, Any]],
) -> str:
    objective = str(state.get("request_prompt") or "").strip()
    role = str(subagent.get("role") or "").strip()
    task = str(subagent.get("task") or "").strip()
    result_file_path = str(subagent.get("result_file_path") or "").strip()

    lines = ["You are a specialized subagent participating in a coordinated multi-agent workflow."]
    if objective:
        lines.append(f"Coordinator objective:\n{objective}")
    if role:
        lines.append(f"Your specialization:\n{role}")
    if task:
        lines.append(f"Your delegated task:\n{task}")
    else:
        lines.append("Advance the coordinator objective from your area of expertise.")

    if team_messages:
        lines.append("Messages from teammate agents:")
        for item in team_messages[-4:]:
            summary = str(item.get("summary") or "").strip()
            if not summary:
                continue
            label = f"- {item.get('name')} ({item.get('namespace')})"
            if item.get("role"):
                label = f"{label} [{item.get('role')}]"
            lines.append(f"{label}: {truncate_text(summary, 500)}")

    if shared_files:
        lines.append("Relevant files from the shared sandbox:")
        for item in shared_files:
            entry = f"Path: {item.get('path')}"
            if item.get("purpose"):
                entry = f"{entry}\nPurpose: {item.get('purpose')}"
            if item.get("content"):
                entry = f"{entry}\nContent:\n{item.get('content')}"
            lines.append(entry)

    if result_file_path:
        lines.append(f"If you produce reusable notes or artifacts, write or summarize them at {result_file_path}.")
    lines.append("Return concrete findings, file paths you inspected or changed, and any blockers.")
    return truncate_text("\n\n".join(lines), MAX_PROMPT_CHARS)


def write_subagent_result_artifact(
    sandbox_session: dict[str, Any] | None,
    *,
    target_agent: str,
    target_namespace: str,
    role: str,
    task: str,
    status: str,
    result_file_path: str,
    response_text: str,
) -> tuple[dict[str, Any] | None, str | None, list[str]]:
    if not result_file_path:
        return sandbox_session, None, []

    if not isinstance(sandbox_session, dict):
        warning = f"Skipped writing subagent result for {target_namespace}/{target_agent} because no sandbox_session was available."
        return sandbox_session, None, [warning]

    current_session = sandbox_session
    warnings: list[str] = []
    directory = parent_directory(result_file_path)
    if directory:
        try:
            _result, next_session = _run_async(
                execute_sandbox_tool(
                    "sandbox.filesystem.mkdir",
                    {"paths": [directory]},
                    current_session,
                    publish_runtime_event,
                )
            )
            current_session = merge_sandbox_sessions(current_session, next_session)
        except Exception:
            logger.debug("Ignoring subagent artifact directory create failure for %s", directory, exc_info=True)

    artifact_lines = [
        f"Subagent: {target_agent} ({target_namespace})",
        f"Status: {status}",
    ]
    if role:
        artifact_lines.append(f"Role: {role}")
    if task:
        artifact_lines.append(f"Task: {task}")
    artifact_lines.append("")
    artifact_lines.append(response_text.strip())
    artifact_text = "\n".join(artifact_lines).rstrip() + "\n"

    publish_runtime_event(
        "subagent.file",
        {
            "status": "started",
            "action": "write",
            "path": result_file_path,
            "targetAgent": target_agent,
            "targetNamespace": target_namespace,
        },
    )
    try:
        _result, next_session = _run_async(
            execute_sandbox_tool(
                "sandbox.filesystem.write",
                {"path": result_file_path, "data": artifact_text},
                current_session,
                publish_runtime_event,
            )
        )
        current_session = merge_sandbox_sessions(current_session, next_session)
        publish_runtime_event(
            "subagent.file",
            {
                "status": "written",
                "action": "write",
                "path": result_file_path,
                "chars": len(artifact_text),
                "targetAgent": target_agent,
                "targetNamespace": target_namespace,
            },
        )
        return current_session, result_file_path, warnings
    except Exception as exc:
        warning = f"Unable to write subagent result artifact '{result_file_path}' for {target_namespace}/{target_agent}: {exc}"
        warnings.append(warning)
        publish_runtime_event(
            "subagent.file",
            {
                "status": "failed",
                "action": "write",
                "path": result_file_path,
                "targetAgent": target_agent,
                "targetNamespace": target_namespace,
                "error": str(exc),
            },
        )
        return current_session, None, warnings


def render_subagent_summary(
    objective: str,
    strategy: str,
    results: list[dict[str, Any]],
) -> str:
    lines = [f"Coordinated {len(results)} specialized subagent(s) using {strategy} execution."]
    if objective:
        lines.append(f"Objective: {objective}")

    for result in results:
        header = f"{result.get('name')} ({result.get('namespace')})"
        if result.get("role"):
            header = f"{header} [{result.get('role')}]"
        lines.append(header)
        if result.get("task"):
            lines.append(f"Task: {result.get('task')}")
        lines.append(f"Status: {result.get('status')}")
        preview = str(result.get("responsePreview") or result.get("error") or "").strip()
        if preview:
            lines.append(preview)
        if result.get("resultFilePath"):
            lines.append(f"Result file: {result.get('resultFilePath')}")
        result_warnings = [str(item).strip() for item in (result.get("warnings") or []) if str(item).strip()]
        if result_warnings:
            lines.append(f"Warnings: {'; '.join(result_warnings[:2])}")

    return truncate_text("\n\n".join(lines), MAX_PROMPT_CHARS)


def synthesize_subagent_summary(
    objective: str,
    strategy: str,
    results: list[dict[str, Any]],
    synthesizer: Callable[[str, str, list[dict[str, Any]]], str] | None,
) -> tuple[str, str | None]:
    fallback = render_subagent_summary(objective, strategy, results)
    if synthesizer is None or not results:
        return fallback, None

    try:
        synthesized = str(synthesizer(objective, strategy, results)).strip()
    except Exception as exc:
        return fallback, f"Coordinator synthesis failed after subagent execution: {exc}"

    return synthesized or fallback, None


def coordinate_specialized_subagents(
    state: State,
    *,
    synthesizer: Callable[[str, str, list[dict[str, Any]]], str] | None = None,
) -> dict[str, Any]:
    subagents = [dict(item) for item in (state.get("subagents") or []) if isinstance(item, dict)]
    if not subagents:
        return {
            "messages": [AIMessage(content=blocked_response("No subagents were provided for coordination"))],
            "invoke_status": "blocked",
            "subagent_results": None,
        }

    request_prompt = str(state.get("request_prompt") or "").strip()
    strategy = normalize_subagent_strategy(state.get("subagent_strategy"))
    allowed_targets, max_timeout_seconds, _ = parse_effective_a2a_policy_config(state.get("policy", {}))
    base_request_id = REQUEST_ID.get() or str(uuid.uuid4())
    current_session = state.get("sandbox_session") if isinstance(state.get("sandbox_session"), dict) else None
    initial_session_present = current_session is not None
    warnings: list[str] = list(state.get("warnings") or [])
    result_entries: dict[int, dict[str, Any]] = {}
    team_messages: list[dict[str, Any]] = []

    def prepare_job(
        subagent: dict[str, Any],
        index: int,
        working_session: dict[str, Any] | None,
        prior_messages: list[dict[str, Any]],
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None, dict[str, Any] | None, list[str]]:
        target_agent = str(subagent.get("name") or "").strip()
        target_namespace = str(subagent.get("namespace") or "").strip()
        role = str(subagent.get("role") or "").strip()
        task = str(subagent.get("task") or "").strip()
        target_thread_id = build_thread_id(
            "subagent",
            SERVICE_NAMESPACE,
            SERVICE_NAME,
            target_namespace,
            target_agent,
            state.get("thread_id") or "",
            index,
        )
        result_file_path = str(subagent.get("result_file_path") or "").strip() or None

        def blocked_entry(reason: str) -> dict[str, Any]:
            return {
                "index": index,
                "name": target_agent,
                "namespace": target_namespace,
                "role": role or None,
                "task": task or None,
                "status": "blocked",
                "transport": None,
                "threadId": target_thread_id,
                "responsePreview": truncate_text(reason, MAX_CONTEXT_CHARS),
                "resultFilePath": None,
                "sharedFiles": [],
                "warnings": [reason],
                "error": reason,
            }

        if target_agent == SERVICE_NAME and target_namespace == SERVICE_NAMESPACE:
            reason = "Subagent cannot target itself: self-referential call detected."
            return None, blocked_entry(reason), working_session, []

        if (target_namespace, target_agent) not in allowed_targets:
            reason = (
                f"Subagent target '{target_agent}' in namespace '{target_namespace}' is not allowed. "
                "Update AgentPolicy.spec.a2a.allowedTargets to grant access."
            )
            return None, blocked_entry(reason), working_session, []

        requested_timeout = subagent.get("timeout_seconds")
        if requested_timeout is not None and float(requested_timeout) > max_timeout_seconds:
            reason = (
                f"Requested subagent timeout {requested_timeout} exceeds policy limit of {max_timeout_seconds} seconds."
            )
            return None, blocked_entry(reason), working_session, []

        shared_files, next_session, snapshot_warnings = prepare_subagent_shared_files(
            [dict(item) for item in subagent.get("input_files") or [] if isinstance(item, dict)],
            working_session,
            target_agent=target_agent,
            target_namespace=target_namespace,
        )
        next_session = merge_sandbox_sessions(working_session, next_session)
        payload = {
            "prompt": build_subagent_prompt(
                state,
                subagent,
                shared_files=shared_files,
                team_messages=prior_messages,
            ),
            "thread_id": target_thread_id,
            "caller_agent_name": SERVICE_NAME,
            "caller_agent_namespace": SERVICE_NAMESPACE,
            "delegation_depth": int(state.get("delegation_depth") or 0) + 1,
            "parent_thread_id": str(state.get("thread_id") or "").strip() or None,
            "caller_request_id": build_thread_id("subreq", base_request_id, index, max_length=128),
            "team_context": build_subagent_team_context(
                state,
                subagent,
                target_thread_id=target_thread_id,
                shared_files=shared_files,
                team_messages=prior_messages,
                strategy=strategy,
                position=index,
                total_subagents=len(subagents),
            ),
        }
        if bool(subagent.get("share_sandbox_session", True)) and next_session is not None:
            payload["sandbox_session"] = next_session

        return (
            {
                "index": index,
                "name": target_agent,
                "namespace": target_namespace,
                "role": role or None,
                "task": task or None,
                "thread_id": target_thread_id,
                "timeout_seconds": float(requested_timeout or max_timeout_seconds),
                "payload": payload,
                "shared_files": [
                    {
                        "path": item.get("path"),
                        "purpose": item.get("purpose"),
                        "chars": item.get("chars"),
                    }
                    for item in shared_files
                ],
                "result_file_path": result_file_path,
                "metadata": subagent.get("metadata") if isinstance(subagent.get("metadata"), dict) else None,
            },
            None,
            next_session,
            snapshot_warnings,
        )

    def invoke_job(job: dict[str, Any]) -> dict[str, Any]:
        try:
            result, transport, fallback_reason = invoke_a2a_target_with_fallback(
                str(job.get("name") or ""),
                str(job.get("namespace") or ""),
                dict(job.get("payload") or {}),
                str((job.get("payload") or {}).get("caller_request_id") or base_request_id),
                float(job.get("timeout_seconds") or max_timeout_seconds),
            )
            return {
                "ok": True,
                "result": result,
                "transport": transport,
                "fallback_reason": fallback_reason,
            }
        except httpx.HTTPStatusError as exc:
            return {
                "ok": False,
                "error": f"A2A target returned HTTP {exc.response.status_code}",
                "transport": "direct",
            }
        except Exception as exc:
            return {
                "ok": False,
                "error": str(exc),
                "transport": "gateway" if gateway_fallback_available() else "direct",
            }

    def finalize_job(
        job: dict[str, Any],
        invocation: dict[str, Any],
        working_session: dict[str, Any] | None,
    ) -> tuple[dict[str, Any], dict[str, Any] | None, list[str]]:
        entry_warnings: list[str] = []
        if not invocation.get("ok"):
            error_text = str(invocation.get("error") or "Subagent invocation failed")
            response_text = error_text
            response_status = "failed"
            transport = invocation.get("transport")
            result_payload: dict[str, Any] = {}
        else:
            result_payload = invocation.get("result") if isinstance(invocation.get("result"), dict) else {}
            response_text = str(result_payload.get("response", ""))
            raw_status = str(result_payload.get("status", "completed") or "completed")
            _KNOWN_SUBAGENT_STATUSES = frozenset({"completed", "failed", "blocked", "approval_pending", "partial"})
            response_status = raw_status if raw_status in _KNOWN_SUBAGENT_STATUSES else "completed"
            transport = invocation.get("transport")
            entry_warnings.extend(str(item) for item in (result_payload.get("warnings") or []))
            fallback_reason = str(invocation.get("fallback_reason") or "").strip()
            if transport == "gateway" and fallback_reason:
                entry_warnings.append(f"{fallback_reason}. Completed via API gateway fallback.")

        working_session = merge_sandbox_sessions(
            working_session,
            result_payload.get("sandbox_session") if isinstance(result_payload.get("sandbox_session"), dict) else None,
        )

        result_file_path = str(job.get("result_file_path") or "").strip()
        written_result_path: str | None = None
        if result_file_path:
            working_session, written_result_path, artifact_warnings = write_subagent_result_artifact(
                working_session,
                target_agent=str(job.get("name") or ""),
                target_namespace=str(job.get("namespace") or ""),
                role=str(job.get("role") or ""),
                task=str(job.get("task") or ""),
                status=response_status,
                result_file_path=result_file_path,
                response_text=response_text or str(invocation.get("error") or ""),
            )
            entry_warnings.extend(artifact_warnings)

        entry_warnings = dedupe_text_items(entry_warnings)
        entry = {
            "index": job.get("index"),
            "name": job.get("name"),
            "namespace": job.get("namespace"),
            "role": job.get("role"),
            "task": job.get("task"),
            "status": response_status,
            "transport": transport,
            "threadId": result_payload.get("thread_id") or job.get("thread_id"),
            "responsePreview": truncate_text(response_text or str(invocation.get("error") or ""), MAX_CONTEXT_CHARS),
            "resultFilePath": written_result_path,
            "sharedFiles": job.get("shared_files") or [],
            "warnings": entry_warnings,
            "approvalName": result_payload.get("approval_name"),
            "retryAfterSeconds": result_payload.get("retry_after_seconds"),
        }
        if job.get("metadata"):
            entry["metadata"] = job.get("metadata")
        if not invocation.get("ok"):
            entry["error"] = str(invocation.get("error") or "Subagent invocation failed")
        return entry, working_session, entry_warnings

    publish_runtime_event(
        "subagent.plan",
        {
            "status": "started",
            "count": len(subagents),
            "strategy": strategy,
            "sharedSandboxSession": initial_session_present,
        },
    )

    if strategy == "parallel":
        jobs: list[dict[str, Any]] = []
        for index, subagent in enumerate(subagents, start=1):
            job, blocked_entry, current_session, preparation_warnings = prepare_job(
                subagent, index, current_session, []
            )
            warnings.extend(preparation_warnings)
            if blocked_entry is not None:
                result_entries[index] = blocked_entry
                warnings.extend(blocked_entry.get("warnings") or [])
                continue
            if job is None:
                continue
            jobs.append(job)
            publish_runtime_event(
                "subagent.call",
                {
                    "status": "started",
                    "targetAgent": job.get("name"),
                    "targetNamespace": job.get("namespace"),
                    "targetThreadId": job.get("thread_id"),
                    "strategy": strategy,
                    "role": job.get("role"),
                },
            )

        if jobs:
            with ThreadPoolExecutor(max_workers=min(len(jobs), MAX_SUBAGENTS)) as executor:
                future_map = {executor.submit(invoke_job, job): job for job in jobs}
                for future in as_completed(future_map):
                    job = future_map[future]
                    invocation = future.result()
                    entry, current_session, entry_warnings = finalize_job(job, invocation, current_session)
                    result_entries[int(job.get("index") or 0)] = entry
                    warnings.extend(entry_warnings)
                    publish_runtime_event(
                        "subagent.call",
                        {
                            "status": "completed" if invocation.get("ok") else "failed",
                            "targetAgent": job.get("name"),
                            "targetNamespace": job.get("namespace"),
                            "targetThreadId": entry.get("threadId"),
                            "strategy": strategy,
                            "role": job.get("role"),
                            "transport": entry.get("transport"),
                            "bytes": len(str(entry.get("responsePreview") or "")),
                            "resultFilePath": entry.get("resultFilePath"),
                            "error": entry.get("error"),
                        },
                    )
    else:
        for index, subagent in enumerate(subagents, start=1):
            job, blocked_entry, current_session, preparation_warnings = prepare_job(
                subagent,
                index,
                current_session,
                team_messages,
            )
            warnings.extend(preparation_warnings)
            if blocked_entry is not None:
                result_entries[index] = blocked_entry
                warnings.extend(blocked_entry.get("warnings") or [])
                team_messages.append(
                    {
                        "name": blocked_entry.get("name"),
                        "namespace": blocked_entry.get("namespace"),
                        "role": blocked_entry.get("role"),
                        "status": blocked_entry.get("status"),
                        "summary": blocked_entry.get("responsePreview"),
                    }
                )
                continue
            if job is None:
                continue

            publish_runtime_event(
                "subagent.call",
                {
                    "status": "started",
                    "targetAgent": job.get("name"),
                    "targetNamespace": job.get("namespace"),
                    "targetThreadId": job.get("thread_id"),
                    "strategy": strategy,
                    "role": job.get("role"),
                },
            )
            invocation = invoke_job(job)
            entry, current_session, entry_warnings = finalize_job(job, invocation, current_session)
            result_entries[index] = entry
            warnings.extend(entry_warnings)
            publish_runtime_event(
                "subagent.call",
                {
                    "status": "completed" if invocation.get("ok") else "failed",
                    "targetAgent": job.get("name"),
                    "targetNamespace": job.get("namespace"),
                    "targetThreadId": entry.get("threadId"),
                    "strategy": strategy,
                    "role": job.get("role"),
                    "transport": entry.get("transport"),
                    "bytes": len(str(entry.get("responsePreview") or "")),
                    "resultFilePath": entry.get("resultFilePath"),
                    "error": entry.get("error"),
                },
            )
            team_messages.append(
                {
                    "name": entry.get("name"),
                    "namespace": entry.get("namespace"),
                    "role": entry.get("role"),
                    "status": entry.get("status"),
                    "summary": entry.get("responsePreview"),
                }
            )

    ordered_results = [result_entries[index] for index in sorted(result_entries)]
    warnings = dedupe_text_items(warnings)
    final_status = "blocked"
    if any(str(item.get("status") or "") == "completed" for item in ordered_results):
        final_status = "completed"
    elif any(str(item.get("status") or "") == "approval_pending" for item in ordered_results):
        final_status = "approval_pending"
    elif ordered_results:
        final_status = str(ordered_results[0].get("status") or "blocked")

    response_text, synthesis_warning = synthesize_subagent_summary(
        request_prompt,
        strategy,
        ordered_results,
        synthesizer,
    )
    if synthesis_warning:
        warnings.append(synthesis_warning)
        warnings = dedupe_text_items(warnings)

    shared_files_summary: list[dict[str, Any]] = []
    seen_shared_files: set[tuple[str, str | None]] = set()
    result_files: list[str] = []
    for item in ordered_results:
        for shared_file in item.get("sharedFiles") or []:
            identity = (str(shared_file.get("path") or ""), str(shared_file.get("purpose") or "") or None)
            if identity in seen_shared_files:
                continue
            seen_shared_files.add(identity)
            shared_files_summary.append(shared_file)
        if item.get("resultFilePath"):
            result_files.append(str(item["resultFilePath"]))

    publish_runtime_event(
        "subagent.plan",
        {
            "status": "completed",
            "count": len(subagents),
            "strategy": strategy,
            "completedCount": sum(1 for item in ordered_results if item.get("status") == "completed"),
            "sharedSandboxSession": initial_session_present,
            "resultFiles": result_files,
        },
    )

    return {
        "messages": [AIMessage(content=response_text)],
        "invoke_status": final_status,
        "sandbox_session": current_session,
        "subagent_results": {
            "strategy": strategy,
            "count": len(ordered_results),
            "sharedSandboxSession": initial_session_present,
            "sharedFiles": shared_files_summary,
            "resultFiles": result_files,
            "results": ordered_results,
        },
        "warnings": warnings,
    }


def get_litellm_headers() -> dict[str, str]:
    if not LITELLM_API_KEY:
        return {}
    return {"Authorization": f"Bearer {LITELLM_API_KEY}"}


def discover_qdrant_collection(client: httpx.Client) -> str:
    global DISCOVERED_QDRANT_COLLECTION

    with DISCOVERED_QDRANT_LOCK:
        if DISCOVERED_QDRANT_COLLECTION:
            return DISCOVERED_QDRANT_COLLECTION

    try:
        response = client.get(f"{QDRANT_URL}/collections", timeout=RAG_REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
        collections = response.json().get("result", {}).get("collections", [])
        if collections:
            collection_name = str(collections[0].get("name", "")).strip()
            if collection_name:
                with DISCOVERED_QDRANT_LOCK:
                    DISCOVERED_QDRANT_COLLECTION = collection_name
                return collection_name
    except Exception as exc:
        logger.warning("Failed to discover Qdrant collections: %s", exc)
    return ""


def embed_query(query: str) -> list[float]:
    with httpx.Client(
        headers=get_litellm_headers(),
        timeout=EMBEDDING_TIMEOUT_SECONDS,
        transport=httpx.HTTPTransport(retries=2),
        trust_env=False,
    ) as client:
        response = client.post(
            f"{LITELLM_BASE}/embeddings",
            json={"model": EMBEDDING_MODEL, "input": query},
        )
        response.raise_for_status()
        data = response.json().get("data", [])
        if not data:
            raise ValueError("LiteLLM embedding response contained no vectors")
        embedding = data[0].get("embedding")
        if not isinstance(embedding, list):
            raise ValueError("LiteLLM embedding response was malformed")
        return embedding


def extract_payload_text(payload: Any) -> str:
    if not isinstance(payload, dict):
        return ""

    for key in ("text", "content", "chunk", "document", "page_content", "body"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def retrieve_context(query: str) -> str:
    if not query.strip() or not RAG_ENABLED:
        return ""

    try:
        with httpx.Client(
            timeout=RAG_REQUEST_TIMEOUT_SECONDS,
            transport=httpx.HTTPTransport(retries=2),
            trust_env=False,
        ) as client:
            collection = discover_qdrant_collection(client)
            if not collection:
                logger.info("Skipping RAG retrieval because no Qdrant collection is configured.")
                return ""

            embedding = embed_query(query)
            search_response = client.post(
                f"{QDRANT_URL}/collections/{collection}/points/search",
                json={"vector": embedding, "limit": RAG_TOP_K, "with_payload": True},
            )

            if search_response.status_code == 404:
                search_response = client.post(
                    f"{QDRANT_URL}/collections/{collection}/points/query",
                    json={"query": embedding, "limit": RAG_TOP_K, "with_payload": True},
                )

            search_response.raise_for_status()
            result = search_response.json().get("result", [])
            if isinstance(result, dict):
                result = result.get("points", [])

            snippets: list[str] = []
            seen_snippets: set[str] = set()
            total_chars = 0
            for match in result:
                payload = match.get("payload", {})
                snippet = extract_payload_text(payload)
                if not snippet or snippet in seen_snippets:
                    continue

                remaining = MAX_CONTEXT_CHARS - total_chars
                if remaining <= 0:
                    break

                clipped = snippet[:remaining]
                snippets.append(clipped)
                seen_snippets.add(snippet)
                total_chars += len(clipped) + 2

            return "\n\n".join(snippets)
    except Exception as exc:
        logger.warning("Qdrant retrieval failed, continuing without RAG context: %s", exc)
        return ""


def load_active_policy(force_refresh: bool = False) -> tuple[str | None, dict[str, Any]]:
    now = time.time()
    with POLICY_CACHE_LOCK:
        if not force_refresh and now - POLICY_CACHE["timestamp"] < POLICY_CACHE_TTL_SECONDS:
            return POLICY_CACHE["name"], POLICY_CACHE["spec"]

    if not K8S_POLICY_ACCESS:
        with POLICY_CACHE_LOCK:
            POLICY_CACHE.update({"timestamp": now, "name": None, "spec": {}})
        return None, {}

    policy_name = os.getenv("AGENT_POLICY_NAME", "").strip()
    custom_api = k8s_client.CustomObjectsApi()
    try:
        if policy_name:
            policy = custom_api.get_namespaced_custom_object(
                group="sandbox.enterprise.ai",
                version="v1alpha1",
                namespace=SERVICE_NAMESPACE,
                plural="agentpolicies",
                name=policy_name,
            )
        else:
            policies = custom_api.list_namespaced_custom_object(
                group="sandbox.enterprise.ai",
                version="v1alpha1",
                namespace=SERVICE_NAMESPACE,
                plural="agentpolicies",
            ).get("items", [])
            policies.sort(key=lambda item: item.get("metadata", {}).get("name", ""))
            policy = policies[0] if policies else None

        cached_name = None
        cached_spec: dict[str, Any] = {}
        if policy:
            cached_name = policy.get("metadata", {}).get("name")
            cached_spec = policy.get("spec", {})
            logger.info("Loaded active AgentPolicy '%s'", cached_name)

        with POLICY_CACHE_LOCK:
            POLICY_CACHE.update({"timestamp": now, "name": cached_name, "spec": cached_spec})
        return cached_name, cached_spec
    except Exception as exc:
        logger.warning("Failed to load AgentPolicy, using built-in defaults: %s", exc)
        with POLICY_CACHE_LOCK:
            POLICY_CACHE.update({"timestamp": now, "name": None, "spec": {}})
        return None, {}


def build_guardrails(policy_spec: dict[str, Any]) -> GuardrailsEngine:
    input_cfg = policy_spec.get("inputGuardrails", {})
    output_cfg = policy_spec.get("outputGuardrails", {})
    return GuardrailsEngine(
        block_prompt_injection=input_cfg.get("blockPromptInjection", True),
        mask_pii=output_cfg.get("maskPII", True),
        blocked_input_patterns=input_cfg.get("blockedPatterns", []),
        blocked_output_patterns=output_cfg.get("blockedOutputPatterns", []),
        max_input_tokens=input_cfg.get("maxInputTokens", 4096),
        max_output_tokens=output_cfg.get("maxOutputTokens", 4096),
    )


def parse_tool_policy_config(policy_spec: dict[str, Any]) -> dict[str, Any]:
    tool_policy = policy_spec.get("toolPolicy") if isinstance(policy_spec, dict) else None
    if tool_policy is None:
        return {}
    if not isinstance(tool_policy, dict):
        logger.warning("Ignoring invalid AgentPolicy.spec.toolPolicy value: expected an object")
        return {}

    parsed: dict[str, Any] = {}
    try:
        if tool_policy.get("maxDelegationDepth") is not None:
            parsed["maxDelegationDepth"] = max(int(tool_policy.get("maxDelegationDepth")), 0)
    except (TypeError, ValueError):
        logger.warning("Ignoring invalid AgentPolicy.spec.toolPolicy.maxDelegationDepth value")

    def _normalize_string_list(field_name: str) -> list[str]:
        value = tool_policy.get(field_name)
        if value is None:
            return []
        if not isinstance(value, list):
            logger.warning("Ignoring invalid AgentPolicy.spec.toolPolicy.%s value: expected a list", field_name)
            return []
        return [str(item).strip() for item in value if str(item).strip()]

    allowed_prefixes = _normalize_string_list("allowedToolPrefixes")
    blocked_names = _normalize_string_list("blockedToolNames")
    require_approval_for = _normalize_string_list("requireApprovalFor")
    if allowed_prefixes:
        parsed["allowedToolPrefixes"] = tuple(dict.fromkeys(allowed_prefixes))
    if blocked_names:
        parsed["blockedToolNames"] = frozenset(blocked_names)
    if require_approval_for:
        parsed["requireApprovalFor"] = frozenset(require_approval_for)
    return parsed


def tool_policy_violation_reason(
    *,
    tool_name: str,
    mcp_server: str,
    delegation_depth: int,
    policy_spec: dict[str, Any],
) -> str | None:
    tool_policy = parse_tool_policy_config(policy_spec)
    if not tool_policy:
        return None

    max_delegation_depth = tool_policy.get("maxDelegationDepth")
    if max_delegation_depth is not None and delegation_depth > int(max_delegation_depth):
        return (
            f"Delegation depth {delegation_depth} exceeds AgentPolicy.spec.toolPolicy.maxDelegationDepth "
            f"({max_delegation_depth})."
        )

    effective_tool_name = f"{mcp_server}/{tool_name}" if mcp_server else tool_name
    blocked_names = tool_policy.get("blockedToolNames") or frozenset()
    if effective_tool_name in blocked_names or tool_name in blocked_names:
        return f"Tool '{effective_tool_name}' is blocked by AgentPolicy.spec.toolPolicy.blockedToolNames."

    allowed_prefixes = tool_policy.get("allowedToolPrefixes") or ()
    if effective_tool_name and allowed_prefixes:
        if not any(
            effective_tool_name == prefix or effective_tool_name.startswith(prefix) for prefix in allowed_prefixes
        ):
            return f"Tool '{effective_tool_name}' is not allowed by AgentPolicy.spec.toolPolicy.allowedToolPrefixes."

    return None


def tool_requires_policy_approval(*, tool_name: str, mcp_server: str, policy_spec: dict[str, Any]) -> bool:
    tool_policy = parse_tool_policy_config(policy_spec)
    if not tool_policy:
        return False
    require_approval_for = tool_policy.get("requireApprovalFor") or frozenset()
    if not require_approval_for:
        return False
    effective_tool_name = f"{mcp_server}/{tool_name}" if mcp_server else tool_name
    return effective_tool_name in require_approval_for or tool_name in require_approval_for


def derive_memory_candidates(result: dict[str, Any], response_text: str) -> dict[str, Any]:
    artifacts = result.get("artifacts") or []
    tool_calls = result.get("tool_call_records") or []
    memory: dict[str, Any] = {
        "episodic": [],
        "procedural": [],
    }

    if artifacts:
        memory["episodic"].append(
            {
                "type": "artifacts",
                "count": len(artifacts),
                "names": [
                    str(item.get("name") or item.get("path") or item.get("type") or "artifact")
                    for item in artifacts[:5]
                    if isinstance(item, dict)
                ],
            }
        )
    if tool_calls:
        memory["episodic"].append(
            {
                "type": "tools",
                "count": len(tool_calls),
                "names": [
                    str(item.get("tool_name") or item.get("toolName") or "tool")
                    for item in tool_calls[:5]
                    if isinstance(item, dict)
                ],
            }
        )
    summary = truncate_text(response_text.strip(), 280) if response_text.strip() else ""
    if summary:
        memory["procedural"].append({"type": "response-summary", "text": summary})
    return memory


def parse_effective_a2a_policy_config(policy_spec: dict[str, Any]) -> tuple[frozenset[tuple[str, str]], float, bool]:
    allowed_targets = A2A_ALLOWED_TARGETS_SNAPSHOT
    max_timeout_seconds = A2A_MAX_TIMEOUT_SECONDS
    require_hitl = A2A_REQUIRE_HITL_DEFAULT
    a2a_config = policy_spec.get("a2a") if isinstance(policy_spec, dict) else None
    if a2a_config is None:
        return allowed_targets, max_timeout_seconds, require_hitl
    if not isinstance(a2a_config, dict):
        logger.warning("Ignoring invalid AgentPolicy.spec.a2a value: expected an object")
        return allowed_targets, max_timeout_seconds, require_hitl

    if "allowedTargets" in a2a_config:
        try:
            parsed_targets = parse_a2a_peer_refs(
                a2a_config.get("allowedTargets"),
                source="AgentPolicy.spec.a2a.allowedTargets",
            )
        except ValueError as exc:
            logger.warning("Ignoring invalid AgentPolicy A2A targets: %s", exc)
        else:
            allowed_targets = frozenset((item["namespace"], item["name"]) for item in parsed_targets)

    if "maxTimeoutSeconds" in a2a_config and a2a_config.get("maxTimeoutSeconds") is not None:
        try:
            max_timeout_seconds = max(float(a2a_config.get("maxTimeoutSeconds")), 1.0)
        except (TypeError, ValueError):
            logger.warning("Ignoring invalid AgentPolicy.spec.a2a.maxTimeoutSeconds value")

    if "requireHitl" in a2a_config:
        require_hitl = bool(a2a_config.get("requireHitl"))

    return allowed_targets, max_timeout_seconds, require_hitl


def validate_inbound_a2a_request(request: InvokeRequest) -> None:
    caller_agent_name = (request.caller_agent_name or "").strip()
    caller_agent_namespace = (request.caller_agent_namespace or "").strip()
    if not caller_agent_name and not caller_agent_namespace:
        return

    if request.delegation_depth >= MAX_DELEGATION_DEPTH:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Delegation depth {request.delegation_depth} exceeds maximum of {MAX_DELEGATION_DEPTH}. "
                "This prevents infinite agent delegation loops."
            ),
        )

    if not A2A_ALLOWED_CALLERS:
        return

    if (caller_agent_namespace, caller_agent_name) not in A2A_ALLOWED_CALLERS:
        raise HTTPException(
            status_code=403,
            detail=(
                f"Agent '{caller_agent_name}' in namespace '{caller_agent_namespace}' is not allowed "
                f"to invoke agent '{SERVICE_NAME}' in namespace '{SERVICE_NAMESPACE}'."
            ),
        )


def a2a_runtime_url(agent_name: str, namespace: str) -> str:
    return f"http://{agent_name}-sandbox.{namespace}.svc.cluster.local:8080"


def route_state(state: State) -> str:
    """Route after input_guard: blocked → END, sandbox → sandbox_tool, subagents → subagent_team, A2A → a2a_call, MCP → mcp_tool, chat → rag_retrieve."""
    status = state.get("invoke_status", "continue")
    if status == "blocked":
        return "blocked"
    if is_runtime_tool(state.get("tool_name")):
        return "sandbox_tool"
    if state.get("subagents"):
        return "subagent_team"
    if state.get("a2a_target_agent"):
        return "a2a_call"
    if state.get("mcp_server"):
        return "mcp_tool"
    return "continue"


def mcp_call(
    server_type: str,
    tool_name: str,
    tool_args: dict[str, Any],
    *,
    timeout: float = 30.0,
) -> dict[str, Any]:
    """Call a tool on an MCP server with bearer-token auth.

    Security enforcements (both layers must pass):
      1. Runtime allow-list: ``server_type`` must be in ALLOWED_MCP_SERVERS
         (set from the AgentPolicy via the ALLOWED_MCP_SERVERS env var).
         This is a defence-in-depth guard on top of the K8s NetworkPolicy.
      2. Bearer token: every outbound request carries the shared bearer token
         injected from the mcp-auth Secret by the operator.

    MCP tool calls are NOT made directly here – they always flow through
    ``preflight_request_approval()`` → ``hitl_gate()`` in ``invoke_graph()``
    before this function is reached.

    Args:
        server_type: The ``mcp.sandbox.enterprise.ai/type`` label value
            (e.g. "weather", "github", "prometheus").
        tool_name:   Name of the MCP tool to invoke.
        tool_args:   Arguments dict forwarded as JSON body.
        timeout:     HTTP request timeout in seconds.

    Returns:
        The JSON response body from the MCP server.

    Raises:
        PermissionError: If server_type is not in the allow-list.
        httpx.HTTPStatusError: On non-2xx MCP responses.
    """
    skill_allowed_servers = SKILL_RUNTIME_CONFIG.get("allowedMcpServers") or frozenset()
    if SKILL_RUNTIME_CONFIG.get("skills") and (not skill_allowed_servers or server_type not in skill_allowed_servers):
        raise PermissionError(f"MCP server '{server_type}' is not granted by the agent's skill files.")

    if ALLOWED_MCP_SERVERS and server_type not in ALLOWED_MCP_SERVERS:
        raise PermissionError(
            f"MCP server type '{server_type}' is not in the agent's allowed list "
            f"({', '.join(sorted(ALLOWED_MCP_SERVERS))}). "
            "Update AgentPolicy.spec.allowedMcpServers to grant access."
        )

    # Build URL: MCP servers are in the mcp-hub namespace using internal K8s DNS.
    # Pattern: http://<release-fullname>-mcp-<type>.<mcp-hub-ns>.svc.cluster.local:8000
    release_name = os.getenv("HELM_RELEASE_NAME", "ai-agent-sandbox")
    svc = f"{release_name}-mcp-{server_type}.{MCP_HUB_NAMESPACE}.svc.cluster.local"
    url = f"http://{svc}:8000/tools/{tool_name}"

    headers: dict[str, str] = {"Content-Type": "application/json"}
    if not MCP_BEARER_TOKEN:
        raise PermissionError(
            f"MCP_BEARER_TOKEN is not configured; refusing to call MCP server '{server_type}'. "
            "Ensure the MCP auth secret is mounted into the agent runtime."
        )
    headers["Authorization"] = f"Bearer {MCP_BEARER_TOKEN}"
    if server_type == "github":
        if not GITHUB_MCP_TOKEN:
            raise PermissionError(
                "GITHUB_MCP_TOKEN is not configured; refusing to call the shared GitHub MCP server. "
                "Create the per-agent GitHub credentials secret and reference it from github_config."
            )
        headers["X-GitHub-Token"] = GITHUB_MCP_TOKEN

    with httpx.Client(
        timeout=timeout,
        transport=httpx.HTTPTransport(retries=2),
        trust_env=False,
    ) as client:
        response = client.post(url, json=tool_args, headers=headers)
        response.raise_for_status()
        return response.json()  # type: ignore[no-any-return]


def create_agent():
    def synthesize_specialized_subagents(
        objective: str,
        strategy: str,
        results: list[dict[str, Any]],
        model_name: str,
    ) -> str:
        publish_runtime_event(
            "subagent.summary",
            {"status": "started", "strategy": strategy, "count": len(results)},
        )

        fallback = render_subagent_summary(objective, strategy, results)
        llm = get_llm_client(model_name)
        if not hasattr(llm, "invoke"):
            publish_runtime_event(
                "subagent.summary",
                {"status": "completed", "strategy": strategy, "count": len(results), "fallback": True},
            )
            return fallback

        payload = {
            "objective": objective,
            "strategy": strategy,
            "results": [
                {
                    "name": item.get("name"),
                    "namespace": item.get("namespace"),
                    "role": item.get("role"),
                    "task": item.get("task"),
                    "status": item.get("status"),
                    "responsePreview": item.get("responsePreview"),
                    "resultFilePath": item.get("resultFilePath"),
                    "warnings": item.get("warnings") or [],
                }
                for item in results
            ],
        }
        response = llm.invoke(
            [
                SystemMessage(
                    content=(
                        "You are coordinating specialist subagents. "
                        "Synthesize their outputs into one concise, actionable response. "
                        "Mention concrete file paths, blockers, and next actions when present."
                    )
                ),
                HumanMessage(content=safe_json_dumps(payload)),
            ]
        )
        synthesized = get_message_content(response).strip()
        publish_runtime_event(
            "subagent.summary",
            {
                "status": "completed",
                "strategy": strategy,
                "count": len(results),
                "chars": len(synthesized),
                "fallback": not bool(synthesized),
            },
        )
        return synthesized or fallback

    def input_guard(state: State) -> dict[str, Any]:
        def _run() -> dict[str, Any]:
            with tracer.start_as_current_span("guardrails_input_validation"):
                prompt = state.get("request_prompt", "")
                guard_input = build_request_guard_text(
                    prompt,
                    state.get("tool_name", ""),
                    state.get("tool_args") or {},
                    state.get("mcp_server", ""),
                    state.get("a2a_target_agent", ""),
                    state.get("a2a_target_namespace", ""),
                    state.get("subagents") or [],
                )
                if not guard_input.strip():
                    return {"context": "", "invoke_status": "continue"}

                guardrails = build_guardrails(state.get("policy", {}))
                is_safe, reason = guardrails.validate_input(guard_input)
                if not is_safe:
                    logger.warning("Input blocked: %s", reason)
                    return {
                        "messages": [AIMessage(content=blocked_response(f"safety policy violation: {reason}"))],
                        "context": "",
                        "invoke_status": "blocked",
                    }
                return {"context": "", "invoke_status": "continue"}

        return run_graph_node("input_guard", _run)

    def rag_retrieve(state: State) -> dict[str, Any]:
        def _run() -> dict[str, Any]:
            with tracer.start_as_current_span("rag_retrieval"):
                prompt = state.get("request_prompt", "")
                if not prompt.strip():
                    return {"context": ""}

                context = retrieve_context(prompt)
                publish_runtime_event(
                    "rag.context",
                    {"chars": len(context), "present": bool(context)},
                )
                return {"context": context}

        return run_graph_node("rag_retrieve", _run)

    def chatbot(state: State) -> dict[str, Any]:
        def _run() -> dict[str, Any]:
            selected_model = str(state.get("selected_model") or MODEL_NAME)

            def invoke_messages(
                messages: list[Any], *, stream: bool, tools: list[dict] | None = None
            ) -> AIMessage | Any:
                llm = get_llm_client(selected_model)
                active_llm = llm.bind_tools(tools) if tools else llm
                publisher = current_event_publisher()
                if not stream or publisher is None or not hasattr(active_llm, "stream"):
                    return active_llm.invoke(messages)

                text_fragments: list[str] = []
                streamed = False
                try:
                    for chunk in active_llm.stream(messages):
                        streamed = True
                        delta = get_message_content(chunk)
                        if delta:
                            text_fragments.append(delta)
                            publish_runtime_event(
                                "response.delta",
                                {"delta": delta, "source": "llm", "model": selected_model},
                            )
                except Exception:
                    if streamed:
                        raise
                    logger.warning(
                        "LLM streaming setup failed, falling back to non-streaming invoke.",
                        exc_info=True,
                    )
                    return active_llm.invoke(messages)
                return AIMessage(content="".join(text_fragments))

            def run_direct_response() -> dict[str, Any]:
                with tracer.start_as_current_span("agent_llm_invocation") as span:
                    messages: list[Any] = []
                    system_prompt = state.get("system_prompt", "").strip()
                    if system_prompt:
                        messages.append(SystemMessage(content=system_prompt))

                    skill_prompt = str(SKILL_RUNTIME_CONFIG.get("prompt") or "").strip()
                    if skill_prompt:
                        messages.append(SystemMessage(content=skill_prompt))

                    collaboration_context = format_team_context_system_message(state.get("team_context"))
                    if collaboration_context:
                        messages.append(SystemMessage(content=collaboration_context))

                    context = state.get("context", "")
                    if context:
                        messages.append(
                            SystemMessage(content=f"Use the following retrieved context when answering:\n{context}")
                        )

                    messages.extend(state.get("messages", []))
                    response = invoke_messages(messages, stream=True)
                    span.set_attribute("model", selected_model)
                    span.set_attribute("rag.context_present", bool(context))
                    span.set_attribute("teamwork.context_present", bool(collaboration_context))
                    span.set_attribute("skills.present", bool(skill_prompt))
                    span.set_attribute("llm.streaming", current_event_publisher() is not None)
                    return {
                        "messages": [response],
                        "invoke_status": "completed",
                        "stop_reason": "response",
                        "step_count": int(state.get("step_count") or 0),
                    }

            if not bool(state.get("autonomy_enabled")):
                return run_direct_response()

            def execute_action(action: dict[str, Any], loop_state: State) -> dict[str, Any]:
                action_name = action["action"]
                if action_name == "sandbox_tool":
                    return sandbox_tool(
                        {
                            **loop_state,
                            "tool_name": action["tool_name"],
                            "tool_args": action["tool_args"],
                        }
                    )

                if action_name == "local_shell":
                    return sandbox_tool(
                        {
                            **loop_state,
                            "tool_name": "local.command.run",
                            "tool_args": action["tool_args"],
                        }
                    )

                if action_name == "edit_file":

                    def _edit_sandbox_tool(t_name: str, t_args: dict) -> dict:
                        return sandbox_tool(
                            {
                                **loop_state,
                                "tool_name": t_name,
                                "tool_args": t_args,
                            }
                        )

                    return execute_edit_file(
                        action["path"],
                        action["old_text"],
                        action["new_text"],
                        _edit_sandbox_tool,
                    )

                if action_name == "batch_read":

                    def _batch_sandbox_tool(t_name: str, t_args: dict) -> dict:
                        return sandbox_tool(
                            {
                                **loop_state,
                                "tool_name": t_name,
                                "tool_args": t_args,
                            }
                        )

                    return execute_batch_read(action["reads"], _batch_sandbox_tool)

                if action_name == "mcp_tool":
                    return mcp_tool(
                        {
                            **loop_state,
                            "mcp_server": action["mcp_server"],
                            "mcp_tool_name": action["tool_name"],
                            "mcp_tool_args": action["tool_args"],
                        }
                    )

                if action_name == "a2a_call":
                    return a2a_call(
                        {
                            **loop_state,
                            "a2a_target_agent": action["a2a_target_agent"],
                            "a2a_target_namespace": action["a2a_target_namespace"],
                            "a2a_timeout_seconds": action.get("a2a_timeout_seconds"),
                            "delegated_prompt": action.get("delegated_prompt") or loop_state.get("request_prompt", ""),
                        }
                    )

                if action_name == "subagent_team":
                    return subagent_team(
                        {
                            **loop_state,
                            "subagents": action["subagents"],
                            "subagent_strategy": action["subagent_strategy"],
                        }
                    )

                if action_name == "git_commit":
                    return execute_git_commit(
                        action["message"],
                        commit_all=bool(action.get("all", True)),
                        execute_local_tool=lambda cmd, args: sandbox_tool(
                            {
                                **loop_state,
                                "tool_name": "local.command.run",
                                "tool_args": {"command": cmd, "args": args},
                            }
                        ),
                    )

                if action_name == "undo_edit":
                    edit_history: list[dict[str, str]] = loop_state.get("edit_history") or []

                    def _undo_sandbox_tool(t_name: str, t_args: dict) -> dict:
                        return sandbox_tool(
                            {
                                **loop_state,
                                "tool_name": t_name,
                                "tool_args": t_args,
                            }
                        )

                    return execute_undo_edit(edit_history, _undo_sandbox_tool)

                if action_name == "edit_files":

                    def _edit_files_sandbox_tool(t_name: str, t_args: dict) -> dict:
                        return sandbox_tool(
                            {
                                **loop_state,
                                "tool_name": t_name,
                                "tool_args": t_args,
                            }
                        )

                    return execute_edit_files(action.get("edits") or [], _edit_files_sandbox_tool)

                if action_name == "search_code":
                    return execute_search_code(
                        action,
                        lambda cmd, args: sandbox_tool(
                            {
                                **loop_state,
                                "tool_name": "local.command.run",
                                "tool_args": {"command": cmd, "args": args},
                            }
                        ),
                    )

                if action_name == "parallel_tools":
                    calls = action.get("tool_calls") or []
                    combined_messages: list[Any] = []
                    combined_status = "completed"
                    with ThreadPoolExecutor(max_workers=min(len(calls), 4)) as pool:
                        future_map = {pool.submit(execute_action, call, loop_state): i for i, call in enumerate(calls)}
                        ordered_results: dict[int, dict[str, Any]] = {}
                        for future in as_completed(future_map):
                            idx = future_map[future]
                            try:
                                ordered_results[idx] = future.result()
                            except Exception as exc:
                                ordered_results[idx] = {
                                    "messages": [AIMessage(content=f"parallel_tools[{idx}] error: {exc}")],
                                    "invoke_status": "blocked",
                                }
                    for i in sorted(ordered_results):
                        r = ordered_results[i]
                        combined_messages.extend(r.get("messages") or [])
                        if str(r.get("invoke_status") or "") == "blocked":
                            combined_status = "continue"  # partial failure
                    return {
                        "messages": combined_messages,
                        "invoke_status": combined_status,
                        "tool_result": {"parallel_count": len(calls)},
                    }

                return {
                    "messages": [AIMessage(content=blocked_response(f"unsupported autonomous action '{action_name}'"))],
                    "invoke_status": "blocked",
                    "stop_reason": "unsupported_action",
                    "error_type": "unsupported_action",
                    "error": f"unsupported autonomous action '{action_name}'",
                }

            # Build tool schemas for native function calling if enabled
            _tool_schemas: list[dict] | None = None
            if USE_TOOL_CALLING:
                _capabilities = {
                    "sandboxTools": supervisor_visible_sandbox_tools(),
                    "localRuntime": supervisor_visible_local_runtime(),
                    "mcpServers": sorted(SKILL_RUNTIME_CONFIG.get("allowedMcpServers") or ALLOWED_MCP_SERVERS),
                    "a2aTargets": sorted(SKILL_RUNTIME_CONFIG.get("allowedA2ATargets") or A2A_ALLOWED_TARGETS_SNAPSHOT),
                    "allowSubagents": bool(SKILL_RUNTIME_CONFIG.get("allowSubagents") or A2A_ALLOWED_TARGETS_SNAPSHOT),
                }
                _tool_schemas = build_tool_schemas(_capabilities)

            return run_autonomous_session(
                state,
                plan_invoke=lambda messages: invoke_messages(messages, stream=False, tools=_tool_schemas),
                execute_action=execute_action,
            )

        return run_graph_node("chatbot", _run)

    def output_guard(state: State) -> dict[str, Any]:
        def _run() -> dict[str, Any]:
            with tracer.start_as_current_span("guardrails_output_sanitization"):
                last_message = state["messages"][-1] if state.get("messages") else None
                content = get_message_content(last_message)
                guardrails = build_guardrails(state.get("policy", {}))
                sanitized = guardrails.sanitize_output(content)
                if sanitized != content:
                    logger.info("Output was sanitized by guardrails")
                    msg_id = getattr(last_message, "id", None)
                    return {"messages": [AIMessage(content=sanitized, id=msg_id)]}
                return {}

        return run_graph_node("output_guard", _run)

    def sandbox_tool(state: State) -> dict[str, Any]:
        def _run() -> dict[str, Any]:
            with tracer.start_as_current_span("sandbox_tool_invocation") as span:
                tool_nm = (state.get("tool_name") or "").strip()
                tool_arguments = state.get("tool_args") or {}
                current_session = state.get("sandbox_session")

                if is_local_runtime_tool(tool_nm):
                    return execute_local_runtime_tool(tool_nm, tool_arguments)

                if not is_sandbox_tool(tool_nm):
                    return blocked_tool_state(
                        "Unsupported sandbox tool invocation",
                        error_type="unsupported_tool",
                        stop_reason="unsupported_tool",
                    )

                publish_runtime_event("sandbox.runtime", sandbox_runtime_metadata())

                try:
                    result, next_session = _run_async(
                        execute_sandbox_tool(
                            tool_nm,
                            tool_arguments,
                            current_session,
                            publish_runtime_event,
                        )
                    )
                except SandboxToolError as exc:
                    logger.warning("Sandbox tool invocation blocked: %s", exc)
                    return blocked_tool_state(
                        str(exc),
                        error_type="sandbox_tool_error",
                        stop_reason="sandbox_tool_error",
                    )
                except Exception as exc:
                    logger.exception("Sandbox tool invocation failed for %s", tool_nm)
                    return blocked_tool_state(
                        f"Sandbox tool failed: {exc}",
                        error=str(exc),
                        error_type="sandbox_tool_runtime_error",
                        stop_reason="sandbox_tool_runtime_error",
                    )

                result_text = format_tool_payload(result)
                span.set_attribute("sandbox.tool_name", tool_nm)
                if next_session and next_session.get("sandbox_id"):
                    span.set_attribute("sandbox.id", str(next_session["sandbox_id"]))
                return {
                    "messages": [AIMessage(content=result_text)],
                    "invoke_status": "completed",
                    "tool_result": result,
                    "sandbox_session": next_session,
                    "tool_call_records": [{"tool_name": tool_nm, "tool_args": tool_arguments, "status": "completed"}],
                }

        return run_graph_node("sandbox_tool", _run)

    def mcp_tool(state: State) -> dict[str, Any]:
        """Call a tool on an MCP server and return the result as an AIMessage."""

        def _run() -> dict[str, Any]:
            with tracer.start_as_current_span("mcp_tool_invocation") as span:
                server_type = (state.get("mcp_server") or "").strip()
                tool_nm = (state.get("mcp_tool_name") or "").strip()
                tool_arguments: dict[str, Any] = state.get("mcp_tool_args") or {}

                if not server_type or not tool_nm:
                    return blocked_tool_state(
                        "mcp_server and tool_name are required for MCP calls",
                        error_type="invalid_mcp_request",
                        stop_reason="invalid_mcp_request",
                    )

                try:
                    result = mcp_call(server_type, tool_nm, tool_arguments)
                    result_text = format_tool_payload(result)
                    span.set_attribute("mcp.server_type", server_type)
                    span.set_attribute("mcp.tool_name", tool_nm)
                    logger.info(
                        "MCP tool '%s/%s' returned %d bytes",
                        server_type,
                        tool_nm,
                        len(result_text),
                    )
                    publish_runtime_event(
                        "mcp.result",
                        {"serverType": server_type, "toolName": tool_nm, "bytes": len(result_text)},
                    )
                    return {
                        "messages": [AIMessage(content=result_text)],
                        "invoke_status": "completed",
                        "tool_result": result,
                        "tool_call_records": [
                            {
                                "tool_name": f"{server_type}/{tool_nm}",
                                "tool_args": tool_arguments,
                                "status": "completed",
                            }
                        ],
                    }
                except PermissionError as exc:
                    logger.warning("MCP call blocked by policy allow-list: %s", exc)
                    return blocked_tool_state(
                        str(exc),
                        error_type="mcp_permission_denied",
                        stop_reason="mcp_permission_denied",
                    )
                except httpx.TimeoutException as exc:
                    logger.warning("MCP call timed out for %s/%s", server_type, tool_nm)
                    return blocked_tool_state(
                        f"MCP call timed out for {server_type}/{tool_nm}",
                        error=str(exc),
                        error_type="mcp_timeout",
                        retryable=True,
                        stop_reason="mcp_timeout",
                    )
                except httpx.HTTPStatusError as exc:
                    logger.error(
                        "MCP server '%s' returned HTTP %s",
                        server_type,
                        exc.response.status_code,
                    )
                    retryable = exc.response.status_code in RETRYABLE_HTTP_STATUS_CODES
                    return blocked_tool_state(
                        f"MCP server error: {exc.response.status_code}",
                        error=str(exc),
                        error_type="mcp_http_error",
                        retryable=retryable,
                        stop_reason="mcp_http_error",
                    )
                except Exception as exc:
                    logger.exception("MCP tool invocation failed for %s/%s", server_type, tool_nm)
                    return blocked_tool_state(
                        f"MCP call failed: {exc}",
                        error=str(exc),
                        error_type="mcp_call_failed",
                        stop_reason="mcp_call_failed",
                    )

        return run_graph_node("mcp_tool", _run)

    def a2a_call(state: State) -> dict[str, Any]:
        def _run() -> dict[str, Any]:
            with tracer.start_as_current_span("a2a_agent_invocation") as span:
                target_agent = (state.get("a2a_target_agent") or "").strip()
                target_namespace = (state.get("a2a_target_namespace") or "").strip()
                if not target_agent or not target_namespace:
                    return {
                        "messages": [
                            AIMessage(content=blocked_response("A2A target agent and namespace are required"))
                        ],
                        "invoke_status": "blocked",
                        "a2a": None,
                    }

                if target_agent == SERVICE_NAME and target_namespace == SERVICE_NAMESPACE:
                    return {
                        "messages": [
                            AIMessage(
                                content=blocked_response(
                                    "A2A self-referential call detected: an agent cannot invoke itself"
                                )
                            )
                        ],
                        "invoke_status": "blocked",
                        "a2a": None,
                    }

                allowed_targets, max_timeout_seconds, _ = parse_effective_a2a_policy_config(state.get("policy", {}))
                if (target_namespace, target_agent) not in allowed_targets:
                    return {
                        "messages": [
                            AIMessage(
                                content=blocked_response(
                                    (
                                        f"A2A target '{target_agent}' in namespace '{target_namespace}' is not allowed. "
                                        "Update AgentPolicy.spec.a2a.allowedTargets to grant access."
                                    )
                                )
                            )
                        ],
                        "invoke_status": "blocked",
                        "a2a": None,
                    }

                requested_timeout = state.get("a2a_timeout_seconds")
                if requested_timeout is not None and float(requested_timeout) > max_timeout_seconds:
                    return {
                        "messages": [
                            AIMessage(
                                content=blocked_response(
                                    (
                                        f"Requested A2A timeout {requested_timeout} exceeds policy limit "
                                        f"of {max_timeout_seconds} seconds."
                                    )
                                )
                            )
                        ],
                        "invoke_status": "blocked",
                        "a2a": None,
                    }

                timeout_seconds = float(requested_timeout or max_timeout_seconds)
                thread_id = str(state.get("thread_id", "")).strip()
                target_thread_id = build_thread_id(
                    "a2a",
                    SERVICE_NAMESPACE,
                    SERVICE_NAME,
                    target_namespace,
                    target_agent,
                    thread_id,
                )
                request_id = REQUEST_ID.get() or str(uuid.uuid4())
                payload = {
                    "prompt": state.get("delegated_prompt") or state.get("request_prompt", ""),
                    "thread_id": target_thread_id,
                    "caller_agent_name": SERVICE_NAME,
                    "caller_agent_namespace": SERVICE_NAMESPACE,
                    "delegation_depth": int(state.get("delegation_depth") or 0) + 1,
                    "parent_thread_id": thread_id or None,
                    "caller_request_id": request_id,
                    "team_context": build_outbound_team_context(
                        state,
                        target_agent,
                        target_namespace,
                        target_thread_id,
                    ),
                }
                if isinstance(state.get("sandbox_session"), dict):
                    payload["sandbox_session"] = state.get("sandbox_session")
                publish_runtime_event(
                    "a2a.call",
                    {
                        "status": "started",
                        "targetAgent": target_agent,
                        "targetNamespace": target_namespace,
                        "targetThreadId": target_thread_id,
                        "timeoutSeconds": timeout_seconds,
                    },
                )

                try:
                    result, transport, fallback_reason = invoke_a2a_target_with_fallback(
                        target_agent,
                        target_namespace,
                        payload,
                        request_id,
                        timeout_seconds,
                    )
                except httpx.HTTPStatusError as exc:
                    publish_runtime_event(
                        "a2a.call",
                        {
                            "status": "failed",
                            "targetAgent": target_agent,
                            "targetNamespace": target_namespace,
                            "transport": "direct",
                            "httpStatus": exc.response.status_code,
                        },
                    )
                    return {
                        "messages": [
                            AIMessage(content=blocked_response(f"A2A target returned HTTP {exc.response.status_code}"))
                        ],
                        "invoke_status": "blocked",
                        "a2a": None,
                    }
                except httpx.TimeoutException:
                    publish_runtime_event(
                        "a2a.call",
                        {
                            "status": "failed",
                            "targetAgent": target_agent,
                            "targetNamespace": target_namespace,
                            "transport": "gateway" if gateway_fallback_available() else "direct",
                            "error": "timeout",
                        },
                    )
                    return {
                        "messages": [
                            AIMessage(
                                content=blocked_response(
                                    f"A2A call to '{target_agent}' in '{target_namespace}' timed out after {timeout_seconds}s"
                                )
                            )
                        ],
                        "invoke_status": "blocked",
                        "a2a": None,
                    }
                except httpx.ConnectError as exc:
                    publish_runtime_event(
                        "a2a.call",
                        {
                            "status": "failed",
                            "targetAgent": target_agent,
                            "targetNamespace": target_namespace,
                            "transport": "gateway" if gateway_fallback_available() else "direct",
                            "error": "connect_error",
                        },
                    )
                    return {
                        "messages": [
                            AIMessage(
                                content=blocked_response(
                                    f"A2A call could not connect to '{target_agent}' in '{target_namespace}': {exc}"
                                )
                            )
                        ],
                        "invoke_status": "blocked",
                        "a2a": None,
                    }
                except Exception as exc:
                    publish_runtime_event(
                        "a2a.call",
                        {
                            "status": "failed",
                            "targetAgent": target_agent,
                            "targetNamespace": target_namespace,
                            "transport": "gateway" if gateway_fallback_available() else "direct",
                            "error": str(exc),
                        },
                    )
                    return {
                        "messages": [AIMessage(content=blocked_response(f"A2A call failed: {exc}"))],
                        "invoke_status": "blocked",
                        "a2a": None,
                    }

                if not isinstance(result, dict):
                    return {
                        "messages": [
                            AIMessage(content=blocked_response("A2A callee returned a non-object JSON payload"))
                        ],
                        "invoke_status": "blocked",
                        "a2a": None,
                    }

                response_text = str(result.get("response", ""))
                response_status = str(result.get("status", "completed") or "completed")
                warnings = [str(item) for item in (result.get("warnings") or [])]
                if transport == "gateway" and fallback_reason:
                    warnings.append(f"{fallback_reason}. Completed via API gateway fallback.")
                warnings = dedupe_text_items(warnings)
                a2a_payload = {
                    "callerAgent": SERVICE_NAME,
                    "callerNamespace": SERVICE_NAMESPACE,
                    "targetAgent": target_agent,
                    "targetNamespace": target_namespace,
                    "targetThreadId": result.get("thread_id") or target_thread_id,
                    "parentThreadId": thread_id or None,
                    "responseStatus": response_status,
                    "transport": transport,
                }
                publish_runtime_event(
                    "a2a.call",
                    {
                        **a2a_payload,
                        "status": "completed",
                        "bytes": len(response_text),
                    },
                )
                span.set_attribute("a2a.target_agent", target_agent)
                span.set_attribute("a2a.target_namespace", target_namespace)
                span.set_attribute("a2a.timeout_seconds", timeout_seconds)
                span.set_attribute("a2a.transport", transport)
                callee_artifacts = result.get("artifacts") if isinstance(result.get("artifacts"), list) else []
                return {
                    "messages": [AIMessage(content=response_text)],
                    "invoke_status": response_status,
                    "approval_name": result.get("approval_name"),
                    "retry_after_seconds": result.get("retry_after_seconds"),
                    "sandbox_session": merge_sandbox_sessions(
                        state.get("sandbox_session") if isinstance(state.get("sandbox_session"), dict) else None,
                        result.get("sandbox_session") if isinstance(result.get("sandbox_session"), dict) else None,
                    ),
                    "warnings": warnings,
                    "a2a": a2a_payload,
                    "artifacts": callee_artifacts,
                }

        return run_graph_node("a2a_call", _run)

    def subagent_team(state: State) -> dict[str, Any]:
        def _run() -> dict[str, Any]:
            with tracer.start_as_current_span("subagent_orchestration") as span:
                span.set_attribute("subagent.count", len(state.get("subagents") or []))
                span.set_attribute("subagent.strategy", normalize_subagent_strategy(state.get("subagent_strategy")))
                result = coordinate_specialized_subagents(
                    state,
                    synthesizer=lambda objective, strategy, results: synthesize_specialized_subagents(
                        objective,
                        strategy,
                        results,
                        str(state.get("selected_model") or MODEL_NAME),
                    ),
                )
                summary = result.get("subagent_results") if isinstance(result.get("subagent_results"), dict) else {}
                span.set_attribute("subagent.completed_count", len(summary.get("results") or []))
                return result

        return run_graph_node("subagent_team", _run)

    graph_builder = StateGraph(State)
    graph_builder.add_node("input_guard", input_guard)
    graph_builder.add_node("rag_retrieve", rag_retrieve)
    graph_builder.add_node("chatbot", chatbot)
    graph_builder.add_node("sandbox_tool", sandbox_tool)
    graph_builder.add_node("a2a_call", a2a_call)
    graph_builder.add_node("subagent_team", subagent_team)
    graph_builder.add_node("mcp_tool", mcp_tool)
    graph_builder.add_node("output_guard", output_guard)

    graph_builder.add_edge(START, "input_guard")
    graph_builder.add_conditional_edges(
        "input_guard",
        route_state,
        {
            "continue": "rag_retrieve",
            "blocked": END,
            "sandbox_tool": "sandbox_tool",
            "subagent_team": "subagent_team",
            "a2a_call": "a2a_call",
            "mcp_tool": "mcp_tool",
        },
    )
    graph_builder.add_edge("rag_retrieve", "chatbot")
    graph_builder.add_edge("chatbot", "output_guard")
    graph_builder.add_edge("sandbox_tool", "output_guard")
    graph_builder.add_edge("subagent_team", "output_guard")
    graph_builder.add_edge("a2a_call", "output_guard")
    graph_builder.add_edge("mcp_tool", "output_guard")
    graph_builder.add_edge("output_guard", END)
    return graph_builder


def initialize_runtime() -> None:
    if RUNTIME:
        return

    with RUNTIME_LOCK:
        if RUNTIME:
            return

        configure_kubernetes_access()
        skill_config = load_skill_runtime_config()
        written_skill_files = materialize_skill_files(skill_config.get("files") or {})
        SKILL_RUNTIME_CONFIG.clear()
        SKILL_RUNTIME_CONFIG.update({**skill_config, "skillFiles": written_skill_files})
        if SKILL_RUNTIME_CONFIG.get("warnings"):
            logger.warning("Loaded agent skill files with warnings: %s", "; ".join(SKILL_RUNTIME_CONFIG["warnings"]))
        logger.info("Initializing agent runtime for %s in namespace %s.", SERVICE_NAME, SERVICE_NAMESPACE)

        db_path = "/app/state/checkpoints.sqlite"
        os.makedirs(os.path.dirname(db_path), exist_ok=True)

        connection: sqlite3.Connection | None = None
        try:
            connection = sqlite3.connect(
                db_path,
                check_same_thread=False,
                timeout=SQLITE_TIMEOUT_SECONDS,
            )
            connection.execute("PRAGMA journal_mode=WAL;")
            connection.execute("PRAGMA synchronous=NORMAL;")
            memory = SqliteSaver(connection)
            memory.setup()
            graph = create_agent().compile(checkpointer=memory)
        except Exception:
            if connection is not None:
                connection.close()
            raise

        RUNTIME.update(
            {
                "graph": graph,
                "connection": connection,
                "memory": memory,
                "session_store": create_session_store() if SESSION_STATE_ENABLED else None,
                "llm_clients": {},
                "local_tool_inventory": discover_local_tool_inventory(refresh=True),
            }
        )
        logger.info("Agent runtime initialized successfully.")


def shutdown_runtime() -> None:
    with RUNTIME_LOCK:
        session_store = RUNTIME.get("session_store")
        if session_store is not None:
            try:
                session_store.close()
            except Exception as exc:
                logger.warning("Failed to close session store cleanly: %s", exc)
        connection = RUNTIME.get("connection")
        if connection is not None:
            try:
                connection.close()
            except sqlite3.Error as exc:
                logger.warning("Failed to close runtime checkpoint database cleanly: %s", exc)
        RUNTIME.clear()


def get_runtime() -> dict[str, Any]:
    if not RUNTIME:
        initialize_runtime()
    return RUNTIME


def preflight_request_approval(
    request: InvokeRequest,
    thread_id: str,
    model_name: str,
    policy_name: str | None,
    *,
    require_approval: bool | None = None,
) -> InvokeResponse | None:
    if request.approval_action:
        default_action = request.approval_action
    elif request.tool_name:
        default_action = f"Invoke tool {request.tool_name} on agent {SERVICE_NAME}"
    elif request.subagents:
        targets = ", ".join(f"{item.namespace}/{item.name}" for item in request.subagents[:3])
        if len(request.subagents) > 3:
            targets = f"{targets}, and {len(request.subagents) - 3} more"
        default_action = f"Coordinate {len(request.subagents)} subagents from agent {SERVICE_NAME}: {targets}"
    elif request.a2a_target_agent and request.a2a_target_namespace:
        default_action = (
            f"Invoke agent {request.a2a_target_agent} in namespace {request.a2a_target_namespace} "
            f"from agent {SERVICE_NAME}"
        )
    else:
        default_action = f"Invoke agent {SERVICE_NAME}"

    approval_required = request.require_approval if require_approval is None else require_approval
    if not approval_required:
        return None

    try:
        approval = hitl_gate(
            action_description=default_action,
            tool_name=request.tool_name,
            tool_args=request.tool_args,
            request_id=thread_id,
        )
    except PermissionError as exc:
        logger.warning("Human approval denied: %s", exc)
        publish_runtime_event(
            "approval.denied",
            {"approvalName": None, "action": default_action, "reason": str(exc)},
        )
        return InvokeResponse(
            thread_id=thread_id,
            response=blocked_response(f"human approval required: {exc}"),
            context="",
            model=model_name,
            policy_name=policy_name,
            tool_name=request.tool_name or None,
            status="blocked",
        )

    approval_name = approval.get("approval_name")
    if approval.get("decision") == "pending":
        publish_runtime_event(
            "approval.pending",
            {"approvalName": approval_name, "action": default_action},
        )
        return InvokeResponse(
            thread_id=thread_id,
            response=(
                f"Approval pending for '{default_action}'. "
                "Re-submit this request with the same thread_id after approval is granted."
            ),
            context="",
            model=MODEL_NAME,
            policy_name=policy_name,
            tool_name=request.tool_name or None,
            status="approval_pending",
            approval_name=approval_name,
            retry_after_seconds=5,
        )

    publish_runtime_event(
        "approval.approved",
        {"approvalName": approval_name, "action": default_action},
    )
    return None


def invoke_graph(
    request: InvokeRequest,
    publish_event: Callable[[str, dict[str, Any]], None] | None = None,
) -> InvokeResponse:
    if _SHUTDOWN.is_set():
        raise HTTPException(status_code=503, detail="Runtime is shutting down. Retry on another pod.")

    prompt = request.prompt.strip()
    tool_name = request.tool_name.strip()
    mcp_server = (request.mcp_server or "").strip()
    a2a_target_agent = (request.a2a_target_agent or "").strip()
    a2a_target_namespace = (request.a2a_target_namespace or "").strip()
    validate_inbound_a2a_request(request)

    if not INVOCATION_SLOTS.acquire(timeout=REQUEST_QUEUE_TIMEOUT_SECONDS):
        raise HTTPException(status_code=503, detail="Agent runtime is busy. Retry shortly.")

    final_session_snapshot: SessionStateSnapshot | None = None
    try:
        policy_name, policy_spec = load_active_policy()
        selected_model = resolve_requested_model(request.model, policy_spec)
        _, _, a2a_require_hitl = parse_effective_a2a_policy_config(policy_spec)
        thread_id = request.thread_id or str(uuid.uuid4())
        tool_policy_violation = tool_policy_violation_reason(
            tool_name=tool_name,
            mcp_server=mcp_server,
            delegation_depth=request.delegation_depth,
            policy_spec=policy_spec,
        )
        if tool_policy_violation:
            return InvokeResponse(
                thread_id=thread_id,
                response=blocked_response(tool_policy_violation),
                context="",
                model=selected_model,
                policy_name=policy_name,
                tool_name=tool_name or None,
                status="blocked",
            )
        skill_violation = skill_block_reason(
            tool_name=tool_name,
            mcp_server=mcp_server,
            a2a_target_agent=a2a_target_agent,
            a2a_target_namespace=a2a_target_namespace,
            subagents=request.subagents,
        )
        if skill_violation:
            return InvokeResponse(
                thread_id=thread_id,
                response=blocked_response(skill_violation),
                context="",
                model=selected_model,
                policy_name=policy_name,
                tool_name=tool_name or None,
                status="blocked",
                warnings=dedupe_text_items(list(SKILL_RUNTIME_CONFIG.get("warnings") or [])),
            )
        route_name = (
            "sandbox_tool"
            if is_runtime_tool(tool_name)
            else "subagent_team"
            if request.subagents
            else "a2a_call"
            if a2a_target_agent
            else "mcp_tool"
            if mcp_server
            else "chat"
        )

        with bind_event_publisher(publish_event):
            publish_runtime_event(
                "response.started",
                {
                    "thread_id": thread_id,
                    "model": selected_model,
                    "status": "running",
                    "policy_name": policy_name,
                    "route": route_name,
                    "tool_name": tool_name or None,
                },
            )
            if request.caller_agent_name and request.caller_agent_namespace:
                publish_runtime_event(
                    "a2a.received",
                    {
                        "callerAgent": request.caller_agent_name,
                        "callerNamespace": request.caller_agent_namespace,
                        "parentThreadId": request.parent_thread_id,
                    },
                )

            approval_response = preflight_request_approval(
                request,
                thread_id,
                selected_model,
                policy_name,
                require_approval=(
                    request.require_approval
                    or bool(a2a_target_agent and a2a_require_hitl)
                    or tool_requires_policy_approval(
                        tool_name=tool_name, mcp_server=mcp_server, policy_spec=policy_spec
                    )
                ),
            )
            if approval_response is not None:
                return approval_response

            local_tools = local_runtime_metadata()
            initial_state: State = {
                "thread_id": thread_id,
                "messages": [HumanMessage(content=prompt)] if prompt else [],
                "request_prompt": prompt,
                "delegated_prompt": "",
                "context": "",
                "team_context": build_inbound_team_context(request),
                "autonomy_enabled": not bool(tool_name or mcp_server or a2a_target_agent or request.subagents),
                "selected_model": selected_model,
                "max_steps": int(request.max_steps or DEFAULT_MAX_AUTONOMY_STEPS),
                "step_count": 0,
                "stop_reason": "",
                "last_action_fingerprint": "",
                "repeat_action_count": 0,
                "invoke_status": "continue",
                "policy_name": policy_name or "",
                "policy": policy_spec,
                "system_prompt": SYSTEM_PROMPT,
                "tool_name": tool_name,
                "tool_args": request.tool_args,
                "tool_result": None,
                "available_local_commands": local_tools.get("availableCommands") or [],
                "sandbox_session": request.sandbox_session,
                "approval_name": None,
                "retry_after_seconds": None,
                "warnings": [],
                "last_step_error": None,
                "recent_failures": [],
                "a2a": None,
                "subagent_results": None,
                "subagents": [item.model_dump() for item in request.subagents],
                "subagent_strategy": request.subagent_strategy,
                "a2a_target_agent": a2a_target_agent,
                "a2a_target_namespace": a2a_target_namespace,
                "a2a_timeout_seconds": request.a2a_timeout_seconds,
                "caller_agent_name": request.caller_agent_name or "",
                "caller_agent_namespace": request.caller_agent_namespace or "",
                "parent_thread_id": request.parent_thread_id or "",
                "caller_request_id": request.caller_request_id or "",
                "delegation_depth": request.delegation_depth,
                "pre_authorized_actions": list(request.pre_authorized_actions or []),
                "mcp_server": mcp_server,
                "mcp_tool_name": tool_name,
                "mcp_tool_args": request.tool_args,
                "artifacts": [],
                "tool_call_records": [],
            }

            runtime = get_runtime()
            persist_session_snapshot(initial_state, session_store=runtime.get("session_store"))
            result = runtime["graph"].invoke(
                initial_state,
                config={"configurable": {"thread_id": thread_id}},
            )
            final_session_snapshot = persist_session_snapshot(result, session_store=runtime.get("session_store"))
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Agent invocation failed")
        raise HTTPException(status_code=500, detail="Agent invocation failed due to an internal error.") from exc
    finally:
        INVOCATION_SLOTS.release()

    messages = result.get("messages", [])
    response_text = get_message_content(messages[-1] if messages else None)
    response_status = str(result.get("invoke_status", "completed") or "completed")
    guardrails = build_guardrails(policy_spec)
    sanitized_tool_result = sanitize_public_payload(result.get("tool_result"), guardrails)
    sanitized_sandbox_session = sanitize_public_payload(result.get("sandbox_session"), guardrails)
    sanitized_a2a = sanitize_public_payload(result.get("a2a"), guardrails)
    sanitized_subagents = sanitize_public_payload(result.get("subagent_results"), guardrails)
    warnings: list[str] = list(result.get("warnings") or [])
    warnings.extend(str(item).strip() for item in (SKILL_RUNTIME_CONFIG.get("warnings") or []) if str(item).strip())
    if isinstance(sanitized_sandbox_session, dict):
        expires_at_value = sanitized_sandbox_session.get("expires_at")
        if isinstance(expires_at_value, str) and expires_at_value:
            try:
                expires_at = datetime.fromisoformat(expires_at_value)
                remaining_seconds = (expires_at - datetime.now(timezone.utc)).total_seconds()
                if remaining_seconds < 300:
                    warnings.append(
                        "Sandbox expires soon. Use sandbox.session.renew in the same thread_id to extend it."
                    )
            except ValueError:
                logger.debug("Ignoring invalid sandbox expiration timestamp: %s", expires_at_value)

    if sanitized_a2a is None and request.caller_agent_name and request.caller_agent_namespace:
        sanitized_a2a = sanitize_public_payload(
            {
                "callerAgent": request.caller_agent_name,
                "callerNamespace": request.caller_agent_namespace,
                "parentThreadId": request.parent_thread_id,
                "callerRequestId": request.caller_request_id,
            },
            guardrails,
        )

    warnings = dedupe_text_items(warnings)
    response_metadata = (
        sanitize_public_payload(result.get("metadata"), guardrails) if isinstance(result.get("metadata"), dict) else {}
    )
    if final_session_snapshot is not None:
        response_metadata = dict(response_metadata or {})
        response_metadata["session"] = {
            "session_id": final_session_snapshot.session_id,
            "status": final_session_snapshot.status,
            "message_count": final_session_snapshot.message_count,
            "remaining_token_budget": final_session_snapshot.remaining_token_budget,
        }
    response_metadata = dict(response_metadata or {})
    response_metadata["memory"] = derive_memory_candidates(result, response_text)
    response_metadata["toolPolicy"] = sanitize_public_payload(parse_tool_policy_config(policy_spec), guardrails)

    return InvokeResponse(
        thread_id=thread_id,
        response=response_text,
        context=result.get("context", ""),
        model=str(result.get("selected_model") or selected_model),
        step_count=int(result.get("step_count") or 0),
        stop_reason=str(result.get("stop_reason") or "").strip() or None,
        policy_name=policy_name,
        tool_name=tool_name or None,
        tool_result=sanitized_tool_result,
        sandbox_session=sanitized_sandbox_session,
        status=response_status,
        approval_name=result.get("approval_name"),
        retry_after_seconds=result.get("retry_after_seconds"),
        a2a=sanitized_a2a,
        subagents=sanitized_subagents,
        warnings=warnings,
        artifacts=result.get("artifacts") or [],
        tool_calls=result.get("tool_call_records") or [],
        metadata=response_metadata or None,
        token_usage=result.get("token_usage"),
    )


def chunk_text(text: str, chunk_size: int = 160) -> Iterator[str]:
    if chunk_size <= 0:
        raise ValueError("chunk_size must be greater than 0")

    for index in range(0, len(text), chunk_size):
        yield text[index : index + chunk_size]


def format_sse_event(event: str, payload: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


class StreamEventPublisher:
    def __init__(self, loop: asyncio.AbstractEventLoop, queue: asyncio.Queue[str], thread_id: str):
        self._loop = loop
        self._queue = queue
        self._thread_id = thread_id
        self._closed = threading.Event()
        self.event_counts: dict[str, int] = {}

    def close(self) -> None:
        self._closed.set()

    @staticmethod
    def _sanitize_event_payload(event: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        if event == "response.delta":
            return None

        if event.endswith(SENSITIVE_STREAM_EVENT_SUFFIXES):
            text = str(payload.get("text", ""))
            summary: dict[str, Any] = {
                "timestamp": payload.get("timestamp"),
                "chars": len(text),
            }
            if "extra" in payload and isinstance(payload["extra"], dict):
                summary["extraKeys"] = sorted(str(key) for key in payload["extra"].keys())
            return summary

        if event == "sandbox.endpoint":
            sanitized = dict(payload)
            headers = sanitized.get("headers")
            if headers is not None:
                sanitized["headers"] = {
                    "redacted": True,
                    "count": len(headers) if isinstance(headers, dict) else 0,
                }
            return sanitized

        return dict(payload)

    def _enqueue(self, event: str, payload: dict[str, Any]) -> None:
        if self._closed.is_set():
            return
        try:
            self._queue.put_nowait(format_sse_event(event, payload))
        except asyncio.QueueFull:
            if event in {"response.completed", "response.error"}:
                with contextlib.suppress(asyncio.QueueEmpty):
                    self._queue.get_nowait()
                with contextlib.suppress(asyncio.QueueFull):
                    self._queue.put_nowait(format_sse_event(event, payload))

    def __call__(self, event: str, payload: dict[str, Any]) -> None:
        if self._closed.is_set():
            return

        # Track event counts before sanitization so that events which are
        # intentionally dropped (e.g. response.delta) are still counted.
        # invoke_stream relies on the count to decide whether to emit a
        # fallback full-response delta.
        self.event_counts[event] = self.event_counts.get(event, 0) + 1

        event_payload = self._sanitize_event_payload(event, payload)
        if event_payload is None:
            return

        event_payload.setdefault("thread_id", self._thread_id)
        self._loop.call_soon_threadsafe(
            self._enqueue,
            event,
            event_payload,
        )


@app.get("/health")
async def health() -> dict[str, Any]:
    ready = bool(RUNTIME.get("graph") and RUNTIME.get("connection"))
    return {
        "status": "shutting-down" if _SHUTDOWN.is_set() else "healthy" if ready else "starting",
        "ready": ready,
        "shuttingDown": _SHUTDOWN.is_set(),
        "agent": SERVICE_NAME,
        "namespace": SERVICE_NAMESPACE,
        "model": MODEL_NAME,
        "policy": POLICY_CACHE.get("name"),
        "ragEnabled": RAG_ENABLED,
        "qdrantCollection": DISCOVERED_QDRANT_COLLECTION,
        "policyAccess": K8S_POLICY_ACCESS,
        "maxConcurrentRequests": MAX_CONCURRENT_REQUESTS,
        "openSandbox": sandbox_runtime_metadata(),
        "localTools": local_runtime_metadata(),
        "skills": {
            "count": len(SKILL_RUNTIME_CONFIG.get("skills") or []),
            "files": SKILL_RUNTIME_CONFIG.get("skillFiles") or [],
            "warnings": SKILL_RUNTIME_CONFIG.get("warnings") or [],
        },
    }


@app.get("/ready")
async def ready() -> dict[str, Any]:
    if _SHUTDOWN.is_set():
        raise HTTPException(status_code=503, detail="Runtime is shutting down")

    runtime_ready = bool(RUNTIME.get("graph") and RUNTIME.get("connection"))
    if not runtime_ready:
        raise HTTPException(status_code=503, detail="Runtime is not ready")

    return {"status": "ready", "agent": SERVICE_NAME, "namespace": SERVICE_NAMESPACE}


@app.get("/discover")
async def discover() -> dict[str, Any]:
    """Return this agent's identity, capabilities, and A2A configuration for peer discovery."""
    return {
        "agent": SERVICE_NAME,
        "namespace": SERVICE_NAMESPACE,
        "model": MODEL_NAME,
        "status": "shutting-down" if _SHUTDOWN.is_set() else "ready" if RUNTIME.get("graph") else "starting",
        "ragEnabled": RAG_ENABLED,
        "allowedCallers": sorted({"namespace": ns, "name": n} for ns, n in A2A_ALLOWED_CALLERS),
        "allowedTargets": sorted({"namespace": ns, "name": n} for ns, n in A2A_ALLOWED_TARGETS_SNAPSHOT),
        "skills": {
            "count": len(SKILL_RUNTIME_CONFIG.get("skills") or []),
        },
        "endpoints": {
            "invoke": "/invoke",
            "invokeStream": "/invoke/stream",
            "health": "/health",
        },
    }


@app.post("/invoke", response_model=InvokeResponse)
async def invoke(request: InvokeRequest) -> InvokeResponse:
    if _SHUTDOWN.is_set():
        raise HTTPException(status_code=503, detail="Runtime is shutting down. Retry on another pod.")
    return await asyncio.to_thread(invoke_graph, request)


@app.post("/invoke/stream")
async def invoke_stream(request: InvokeRequest) -> StreamingResponse:
    if _SHUTDOWN.is_set():
        raise HTTPException(status_code=503, detail="Runtime is shutting down. Retry on another pod.")

    async def event_generator() -> AsyncIterator[str]:
        stream_request = request
        if not stream_request.thread_id:
            stream_request = stream_request.model_copy(update={"thread_id": str(uuid.uuid4())})

        queue: asyncio.Queue[str] = asyncio.Queue(maxsize=STREAM_EVENT_QUEUE_SIZE)
        publisher = StreamEventPublisher(
            asyncio.get_running_loop(),
            queue,
            stream_request.thread_id or "",
        )
        invocation_task = asyncio.create_task(asyncio.to_thread(invoke_graph, stream_request, publisher))

        try:
            while True:
                if invocation_task.done() and queue.empty():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=0.25)
                except asyncio.TimeoutError:
                    continue
                yield event

            response = await invocation_task
            if publisher.event_counts.get("response.delta", 0) == 0 and response.response:
                yield format_sse_event(
                    "response.delta",
                    {
                        "delta": response.response,
                        "thread_id": response.thread_id,
                        "request_id": REQUEST_ID.get(),
                    },
                )
            yield format_sse_event(
                "response.completed",
                {
                    "done": True,
                    "thread_id": response.thread_id,
                    "request_id": REQUEST_ID.get(),
                    "model": response.model,
                    "policy_name": response.policy_name,
                    "status": response.status,
                    "step_count": response.step_count,
                    "stop_reason": response.stop_reason,
                    "approval_name": response.approval_name,
                    "retry_after_seconds": response.retry_after_seconds,
                    "tool_name": response.tool_name,
                    "tool_result": response.tool_result,
                    "sandbox_session": response.sandbox_session,
                    "a2a": response.a2a,
                    "subagents": response.subagents,
                    "warnings": response.warnings,
                    "artifacts": response.artifacts,
                    "tool_calls": response.tool_calls,
                    "metadata": response.metadata,
                },
            )
        except asyncio.CancelledError:
            publisher.close()
            if not invocation_task.done():
                invocation_task.cancel()
            raise
        except HTTPException as exc:
            detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
            yield format_sse_event("response.error", {"error": detail, "request_id": REQUEST_ID.get()})
        except Exception:
            logger.exception("Streaming invocation failed")
            yield format_sse_event(
                "response.error",
                {"error": "Agent invocation failed", "request_id": REQUEST_ID.get()},
            )
        finally:
            publisher.close()

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def main() -> None:
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8080, proxy_headers=True, forwarded_allow_ips="*")


if __name__ == "__main__":
    main()
