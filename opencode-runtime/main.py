from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import mimetypes
import os
import re
import shutil
import subprocess
import threading
import time
import uuid
from collections.abc import AsyncIterator
from pathlib import Path, PurePosixPath
from typing import Any

import httpx
import yaml
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field, model_validator

from hitl import hitl_gate


logger = logging.getLogger("opencode-runtime")

MAX_PROMPT_CHARS = max(int(os.getenv("OPENCODE_MAX_PROMPT_CHARS", "64000")), 1024)
MAX_THREAD_ID_CHARS = max(int(os.getenv("OPENCODE_MAX_THREAD_ID_CHARS", "128")), 16)
MAX_MODEL_CHARS = max(int(os.getenv("OPENCODE_MAX_MODEL_CHARS", "256")), 32)
MAX_SYSTEM_PROMPT_CHARS = max(int(os.getenv("OPENCODE_MAX_SYSTEM_PROMPT_CHARS", "32000")), 512)
MAX_TEAM_CONTEXT_CHARS = max(int(os.getenv("OPENCODE_MAX_TEAM_CONTEXT_CHARS", "16000")), 512)
HTTP_TIMEOUT_SECONDS = max(float(os.getenv("OPENCODE_HTTP_TIMEOUT_SECONDS", "300")), 1.0)
SERVER_STARTUP_TIMEOUT_SECONDS = max(float(os.getenv("OPENCODE_STARTUP_TIMEOUT_SECONDS", "60")), 5.0)
SERVER_POLL_INTERVAL_SECONDS = max(float(os.getenv("OPENCODE_STARTUP_POLL_SECONDS", "0.5")), 0.1)
DEFAULT_AGENT_STEPS = max(int(os.getenv("OPENCODE_AGENT_STEPS", "16")), 1)
MODEL_CONTEXT_LIMIT = max(int(os.getenv("OPENCODE_MODEL_CONTEXT_LIMIT", "128000")), 2048)
MODEL_OUTPUT_LIMIT = max(int(os.getenv("OPENCODE_MODEL_OUTPUT_LIMIT", "8192")), 256)

SERVICE_NAME = os.getenv("AGENT_NAME", "opencode-agent").strip() or "opencode-agent"
SERVICE_NAMESPACE = os.getenv("AGENT_NAMESPACE", "default").strip() or "default"
HOME_DIR = os.getenv("HOME", "/app/state/home").strip() or "/app/state/home"
XDG_CONFIG_HOME = os.getenv("XDG_CONFIG_HOME", f"{HOME_DIR}/.config").strip() or f"{HOME_DIR}/.config"
XDG_DATA_HOME = os.getenv("XDG_DATA_HOME", f"{HOME_DIR}/.local/share").strip() or f"{HOME_DIR}/.local/share"
OPENCODE_CONFIG_DIR = os.getenv("OPENCODE_CONFIG_DIR", f"{XDG_CONFIG_HOME}/opencode-profile").strip() or f"{XDG_CONFIG_HOME}/opencode-profile"
OPENCODE_BIN = os.getenv("OPENCODE_BIN", "opencode").strip() or "opencode"
OPENCODE_WORKDIR = os.getenv("OPENCODE_WORKDIR", "/workspace").strip() or "/workspace"
OPENCODE_SERVER_HOST = os.getenv("OPENCODE_SERVER_HOST", "127.0.0.1").strip() or "127.0.0.1"
OPENCODE_SERVER_PORT = max(int(os.getenv("OPENCODE_SERVER_PORT", "4096")), 1024)
DEFAULT_PROVIDER = os.getenv("OPENCODE_PROVIDER", "litellm").strip() or "litellm"
DEFAULT_MODEL = (os.getenv("OPENCODE_MODEL") or os.getenv("AGENT_MODEL") or "gpt-4").strip() or "gpt-4"
DEFAULT_SYSTEM_PROMPT = (os.getenv("OPENCODE_SYSTEM_PROMPT") or os.getenv("AGENT_SYSTEM_PROMPT") or "").strip()
DEFAULT_AGENT = os.getenv("OPENCODE_DEFAULT_AGENT", "build").strip() or "build"
LITELLM_HOST = os.getenv("LITELLM_HOST", "http://localhost:4000").strip() or "http://localhost:4000"
LITELLM_BASE_PATH = os.getenv("LITELLM_BASE_PATH", "v1/chat/completions").strip() or "v1/chat/completions"
LITELLM_API_KEY = os.getenv("LITELLM_API_KEY", "").strip()
MCP_HUB_NAMESPACE = os.getenv("MCP_HUB_NAMESPACE", "mcp-hub").strip() or "mcp-hub"
MCP_BEARER_TOKEN = os.getenv("MCP_BEARER_TOKEN", "").strip()
GITHUB_MCP_TOKEN = os.getenv("GITHUB_MCP_TOKEN", "").strip()
HELM_RELEASE_NAME = os.getenv("HELM_RELEASE_NAME", "ai-agent-sandbox").strip() or "ai-agent-sandbox"

AUTONOMOUS_MAX_RETRIES = max(int(os.getenv("OPENCODE_AUTONOMOUS_MAX_RETRIES", "3")), 0)
AUTONOMOUS_MAX_TURNS = max(int(os.getenv("OPENCODE_AUTONOMOUS_MAX_TURNS", "10")), 1)
ARTIFACT_COLLECTION_MAX_FILES = max(int(os.getenv("OPENCODE_ARTIFACT_MAX_FILES", "200")), 1)
SESSION_IDLE_TIMEOUT_SECONDS = max(float(os.getenv("OPENCODE_SESSION_IDLE_TIMEOUT_SECONDS", "15")), 1.0)
SESSION_IDLE_POLL_SECONDS = max(float(os.getenv("OPENCODE_SESSION_IDLE_POLL_SECONDS", "0.5")), 0.1)
STRUCTURED_OUTPUT_RETRY_COUNT = max(int(os.getenv("OPENCODE_STRUCTURED_OUTPUT_RETRY_COUNT", "2")), 0)
AUTONOMY_CONTINUATION_PROMPT = (
    "Continue working on the task. Before proceeding:\n"
    "1. REVIEW: Summarize what you have completed so far and what remains.\n"
    "2. CHECK: Verify your completed work actually functions — read files back, "
    "run tests, or execute the code. Fix any issues you find.\n"
    "3. CONTINUE: Proceed with the next incomplete step in your plan.\n"
    "4. VERIFY BEFORE FINISHING: Before your final response, confirm every "
    "requirement from the original task is met — do not claim completion "
    "without fresh evidence."
)
COMPACTION_TOKEN_THRESHOLD = float(os.getenv("OPENCODE_COMPACTION_TOKEN_THRESHOLD", "0.75"))
SESSION_ABORT_TIMEOUT_SECONDS = max(float(os.getenv("OPENCODE_ABORT_TIMEOUT_SECONDS", "30")), 5.0)
PLAN_AGENT_PROMPT_THRESHOLD = max(int(os.getenv("OPENCODE_PLAN_THRESHOLD_CHARS", "500")), 100)
SESSION_MAX_AGE_SECONDS = max(int(os.getenv("OPENCODE_SESSION_MAX_AGE_SECONDS", "86400")), 60)
SESSION_MAX_ENTRIES = max(int(os.getenv("OPENCODE_SESSION_MAX_ENTRIES", "1000")), 10)
MAX_COMPACTION_ATTEMPTS = max(int(os.getenv("OPENCODE_MAX_COMPACTION_ATTEMPTS", "2")), 1)
COMPACTION_MIN_TURN_SPACING = max(int(os.getenv("OPENCODE_COMPACTION_MIN_TURN_SPACING", "3")), 1)
SESSION_INIT_ON_CREATE = os.getenv("OPENCODE_SESSION_INIT_ON_CREATE", "true").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
DOWNLOADABLE_ARTIFACT_EXTENSIONS: frozenset[str] = frozenset({
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
})
ARTIFACT_PATH_PATTERN = re.compile(
    r"(?:^|[\s\"'`(])(?P<path>(?:/[A-Za-z0-9._\-/]+|[A-Za-z0-9._-]+(?:/[A-Za-z0-9._-]+)+)"
    r"(?:\.pdf|\.md|\.txt|\.json|\.yaml|\.yml|\.csv|\.html|\.svg|\.png|\.jpg|\.jpeg|\.gif|\.doc|\.docx))(?=$|[\s\"'`),])",
    re.IGNORECASE,
)

NATIVE_TOOL_NAMES: frozenset[str] = frozenset({
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
})

FORMAT_INSTRUCTIONS: dict[str, str] = {
    "json": (
        "IMPORTANT: Your final response MUST be valid JSON only. "
        "No markdown fencing, no explanation text before or after the JSON. "
        "The output must be directly parseable by json.loads(). "
        "Ensure all required fields are present, values have correct types, "
        "no trailing commas appear, and no comments are included in the JSON."
    ),
    "code": (
        "IMPORTANT: Respond with the requested code only. No markdown code fences "
        "wrapping it. Include code comments where helpful but no explanatory prose "
        "outside the code. Provide complete, working implementations — never "
        "truncate with placeholders like '...' or 'rest of code here'."
    ),
    "markdown": "Respond in well-formatted Markdown.",
    "text": "Respond in plain text without any special formatting.",
}

AUTONOMY_SYSTEM_PROMPT = (
    "You are an autonomous coding agent. Follow these rules:\n"
    "1. PLAN FIRST: For complex tasks (3+ steps), use todowrite to create a structured plan "
    "before writing any code. Order steps by dependency — prerequisites first. Each step "
    "must be a single, verifiable unit of work. Track progress by updating todo status as you work.\n"
    "2. USE NATIVE TOOLS: Use your built-in tools (write, edit, bash, read, glob, grep, "
    "webfetch, websearch, codesearch) for all file and code operations — do NOT rely on "
    "external MCP servers for tasks you can do natively.\n"
    "3. ATOMIC TASK COMMITMENT: Complete each task fully before starting the next. "
    "Do not leave tasks partially done or switch to another task mid-way. "
    "One task at a time, done right.\n"
    "4. DIAGNOSE BEFORE FIXING: When you encounter an error, STOP. Read the full error message "
    "and stack trace. Identify the root cause before attempting any fix — never apply "
    "speculative patches. Address causes, not symptoms.\n"
    "5. NO USER INPUT: Do not ask for user input or clarification — make reasonable decisions "
    "and proceed autonomously.\n"
    "6. FILE OPERATIONS: Use write to create files, edit to modify existing files, "
    "bash to run commands and install dependencies.\n"
    "7. VERIFY BEFORE CLAIMING DONE: Task completion is not goal achievement. After each change, "
    "verify it works: read files back, run the code, execute tests. Work backwards from the goal — "
    "what must be TRUE for this to work? What must EXIST? What must be CONNECTED? Confirm each "
    "before marking complete.\n"
    "8. DELEGATE SUBTASKS: For complex multi-part work, use the task tool to delegate "
    "independent subtasks to parallel sub-agents.\n"
    "9. SEARCH BEFORE WRITING: Use glob, grep, and codesearch to understand existing code "
    "before making changes. Understand the codebase structure first.\n"
    "10. NO REPEATED FAILURES: If the same approach fails twice, step back and try a "
    "fundamentally different strategy. Do not retry identical commands expecting different results.\n"
    "11. CONTEXT AWARENESS: Keep your responses and plans focused. Avoid generating unnecessary "
    "output that wastes context window space. Prefer targeted edits over full-file rewrites.\n"
    "12. GIT OPERATIONS: For git operations (clone, commit, push, pull, branch), prefer using "
    "the git MCP sidecar tools (git_clone, git_commit, git_push, git_pull, git_branch) when "
    "available — they have authentication pre-configured. Only fall back to bash git commands "
    "if no git MCP tools are available. The shared repository URL is available in the "
    "GIT_REPO_URL environment variable — read it with `echo $GIT_REPO_URL` and use it as "
    "the repo_url parameter for git_clone. When cloning into the workspace, use "
    "target_dir='/workspace' and full_clone=true for push support.\n"
    "13. SUMMARIZE: Summarize what you accomplished in your final response, including "
    "files created/modified and verification results."
)

A2A_ALLOWED_CALLERS_ENV = "A2A_ALLOWED_CALLERS_JSON"
AGENT_SKILL_FILES_ENV = "AGENT_SKILL_FILES_JSON"
OPENCODE_RUNTIME_CONFIG_FILES_ENV = "OPENCODE_RUNTIME_CONFIG_FILES_JSON"
OPENCODE_MCP_SIDECARS_ENV = "OPENCODE_MCP_SIDECARS_JSON"
SKILL_NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")

SESSION_MAP_PATH = Path(HOME_DIR) / ".local" / "share" / "opencode-runtime" / "session-map.json"

_runtime_process: subprocess.Popen[str] | None = None
_runtime_ready = False
_runtime_lock = threading.Lock()


def _parse_json_env(name: str) -> Any:
    raw_value = os.getenv(name, "").strip()
    if not raw_value:
        return None
    try:
        return json.loads(raw_value)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{name} is not valid JSON") from exc


def _parse_allowed_callers() -> set[tuple[str, str]]:
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


def dedupe_items(values: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = str(value).strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        deduped.append(cleaned)
    return deduped


def truncate_text(text: str, limit: int = 4000) -> str:
    if len(text) <= limit:
        return text
    if limit <= 3:
        return text[:limit]
    return f"{text[: limit - 3]}..."


def normalize_identifier(value: str, *, source: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise ValueError(f"{source} must not be blank")
    if len(cleaned) > 63:
        raise ValueError(f"{source} must be 63 characters or fewer")
    return cleaned


def normalize_relative_path(raw_path: str, *, source: str) -> str:
    candidate = str(raw_path or "").strip().replace("\\", "/")
    if not candidate:
        raise RuntimeError(f"{source} path must not be blank")
    if candidate.startswith("/"):
        raise RuntimeError(f"{source} path '{candidate}' must be relative")
    if len(candidate) > 512:
        raise RuntimeError(f"{source} path '{candidate}' is too long")
    normalized = PurePosixPath(candidate)
    if normalized.is_absolute() or any(part in {"", ".", ".."} for part in normalized.parts):
        raise RuntimeError(f"{source} path '{candidate}' must stay within the runtime config root")
    return normalized.as_posix()


def build_litellm_base_url() -> str:
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


def parse_skill_frontmatter(path: str, content: str) -> tuple[str, list[str]]:
    def _normalize_skill_name(candidate: str) -> str:
        lowered = candidate.strip().lower()
        # Keep names compliant with OpenCode skill-name constraints:
        # lowercase alnum with single dashes.
        cleaned = re.sub(r"[^a-z0-9-]", "-", lowered)
        cleaned = re.sub(r"-+", "-", cleaned).strip("-")
        return cleaned or "skill"

    default_name = _normalize_skill_name(Path(path).parent.name or Path(path).stem or "skill")
    warnings: list[str] = []
    if not content.startswith("---"):
        return default_name, warnings
    parts = content.split("---", 2)
    if len(parts) < 3:
        return default_name, warnings
    try:
        frontmatter = yaml.safe_load(parts[1]) or {}
    except yaml.YAMLError as exc:
        warnings.append(f"Unable to parse skill frontmatter for '{path}': {exc}")
        return default_name, warnings
    name = _normalize_skill_name(str(frontmatter.get("name") or default_name))
    if not SKILL_NAME_RE.fullmatch(name) or len(name) > 64:
        warnings.append(
            f"Skill '{path}' has invalid frontmatter name '{frontmatter.get('name')}'. Falling back to '{default_name}'."
        )
        name = default_name
    if name != default_name:
        warnings.append(f"Materialized skill '{path}' as '{name}' for OpenCode discovery.")
    return name or default_name, warnings


def ensure_runtime_directories() -> None:
    for path in [
        Path(HOME_DIR),
        Path(XDG_CONFIG_HOME),
        Path(XDG_DATA_HOME),
        Path(OPENCODE_CONFIG_DIR),
        Path(OPENCODE_WORKDIR),
        SESSION_MAP_PATH.parent,
    ]:
        path.mkdir(parents=True, exist_ok=True)


def serialize_file_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    return json.dumps(content, ensure_ascii=False, indent=2, sort_keys=True)


def materialize_opencode_config_files() -> list[str]:
    payload = _parse_json_env(OPENCODE_RUNTIME_CONFIG_FILES_ENV)
    if payload is None:
        return []
    if not isinstance(payload, dict):
        raise RuntimeError(f"{OPENCODE_RUNTIME_CONFIG_FILES_ENV} must be a JSON object")

    written_files: list[str] = []
    root = Path(OPENCODE_CONFIG_DIR)
    for raw_path, raw_content in payload.items():
        relative_path = normalize_relative_path(str(raw_path), source=OPENCODE_RUNTIME_CONFIG_FILES_ENV)
        target = root / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(f"{serialize_file_content(raw_content).rstrip()}\n", encoding="utf-8")
        written_files.append(relative_path)
    return sorted(written_files)


def materialize_skill_files() -> tuple[list[str], list[str]]:
    payload = _parse_json_env(AGENT_SKILL_FILES_ENV)
    if payload is None:
        return [], []
    if not isinstance(payload, dict):
        raise RuntimeError(f"{AGENT_SKILL_FILES_ENV} must be a JSON object")

    written_files: list[str] = []
    warnings: list[str] = []
    seen_names: set[str] = set()
    skills_root = Path(OPENCODE_CONFIG_DIR) / "skills"

    for raw_path, raw_content in payload.items():
        content = str(raw_content)
        skill_name, skill_warnings = parse_skill_frontmatter(str(raw_path), content)
        warnings.extend(skill_warnings)
        if skill_name in seen_names:
            warnings.append(f"Skipping duplicate skill '{skill_name}' while materializing OpenCode skills.")
            continue
        seen_names.add(skill_name)
        target = skills_root / skill_name / "SKILL.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(f"{content.rstrip()}\n", encoding="utf-8")
        written_files.append(target.relative_to(Path(OPENCODE_CONFIG_DIR)).as_posix())

    return sorted(written_files), dedupe_items(warnings)


def load_opencode_sidecars() -> list[dict[str, Any]]:
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


def build_shared_mcp_config() -> tuple[dict[str, Any], list[str]]:
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
            warnings.append(
                f"Skipping shared MCP server '{server_type}' because MCP_BEARER_TOKEN is not configured."
            )
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


def build_generated_config(sidecars: list[dict[str, Any]]) -> tuple[dict[str, Any], list[str]]:
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
            }
        },
    }
    if mcp_config:
        config["mcp"] = mcp_config
    return config, warnings


class SessionRegistry:
    """Thread-safe ``thread_id → session_id`` mapping with lazy pruning."""

    def __init__(self, path: Path, *, max_age_seconds: int = 86400, max_entries: int = 1000):
        self.path = path
        self._lock = threading.Lock()
        self._cache: dict[str, dict[str, Any]] | None = None
        self.max_age_seconds = max_age_seconds
        self.max_entries = max_entries
        self._last_prune_time: float = 0.0

    def _load(self) -> dict[str, dict[str, Any]]:
        if self._cache is not None:
            return dict(self._cache)
        if not self.path.exists():
            self._cache = {}
            return {}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as _exc:
            logger.warning("Failed to load session registry from %s: %s — treating as empty.", self.path, _exc)
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        # Migrate legacy entries (plain string values) to timestamped dicts
        migrated: dict[str, dict[str, Any]] = {}
        for key, value in payload.items():
            if isinstance(value, dict) and "session_id" in value:
                migrated[str(key)] = value
            else:
                migrated[str(key)] = {"session_id": str(value), "last_accessed": time.time()}
        self._cache = migrated
        return dict(self._cache)

    def _save(self, data: dict[str, dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8")
        self._cache = data

    def _maybe_prune(self, data: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
        """Prune stale/excess entries; debounced to once per 60s."""
        now = time.time()
        if now - self._last_prune_time < 60.0:
            return data
        self._last_prune_time = now
        cutoff = now - self.max_age_seconds
        pruned = {k: v for k, v in data.items() if v.get("last_accessed", 0) >= cutoff}
        if len(pruned) > self.max_entries:
            sorted_entries = sorted(pruned.items(), key=lambda kv: kv[1].get("last_accessed", 0), reverse=True)
            pruned = dict(sorted_entries[: self.max_entries])
        return pruned

    def get(self, thread_id: str) -> str | None:
        with self._lock:
            data = self._load()
            entry = data.get(thread_id)
            if entry is None:
                return None
            entry["last_accessed"] = time.time()
            return entry["session_id"]

    def set(self, thread_id: str, session_id: str) -> None:
        with self._lock:
            data = self._load()
            data[thread_id] = {"session_id": session_id, "last_accessed": time.time()}
            data = self._maybe_prune(data)
            self._save(data)

    def get_or_set(self, thread_id: str, session_id: str) -> str:
        """Atomically return an existing session or register *session_id*.

        If another thread registered a session between the caller's
        ``get()`` and ``set()`` calls, the already-registered session
        wins and the caller's *session_id* is discarded.
        """
        with self._lock:
            data = self._load()
            existing = data.get(thread_id)
            if existing:
                existing["last_accessed"] = time.time()
                return existing["session_id"]
            data[thread_id] = {"session_id": session_id, "last_accessed": time.time()}
            data = self._maybe_prune(data)
            self._save(data)
            return session_id

    @property
    def size(self) -> int:
        """Current number of entries (for health metrics)."""
        with self._lock:
            return len(self._load())

    def stale_count(self, stale_seconds: float = 3600.0) -> int:
        """Count entries older than *stale_seconds* (for health metrics)."""
        cutoff = time.time() - stale_seconds
        with self._lock:
            data = self._load()
            return sum(1 for v in data.values() if v.get("last_accessed", 0) < cutoff)


SESSION_REGISTRY = SessionRegistry(SESSION_MAP_PATH, max_age_seconds=SESSION_MAX_AGE_SECONDS, max_entries=SESSION_MAX_ENTRIES)


def resolve_working_directory(raw_value: str | None) -> str:
    root = Path(OPENCODE_WORKDIR).resolve()
    if raw_value is None or not raw_value.strip():
        return str(root)
    candidate = raw_value.strip()
    target = (root / candidate).resolve() if not Path(candidate).is_absolute() else Path(candidate).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"working_directory '{raw_value}' must stay inside the OpenCode workspace") from exc
    if not target.exists() or not target.is_dir():
        raise HTTPException(status_code=400, detail=f"working_directory '{raw_value}' does not exist inside the OpenCode workspace")
    return str(target)


def _path_is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def resolve_download_path(raw_value: str) -> Path:
    candidate = str(raw_value or "").strip()
    if not candidate:
        raise HTTPException(status_code=400, detail="artifact download path must not be blank")
    target = Path(candidate).expanduser().resolve()
    allowed_roots = [Path(OPENCODE_WORKDIR).resolve(), Path(HOME_DIR).resolve(), Path("/tmp").resolve()]
    if not any(_path_is_within(target, root) for root in allowed_roots):
        raise HTTPException(status_code=400, detail=f"artifact path '{raw_value}' is outside the allowed runtime roots")
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail=f"artifact path '{raw_value}' does not exist")
    return target


def _iter_artifact_paths(value: Any) -> list[str]:
    found: list[str] = []
    if isinstance(value, str):
        for match in ARTIFACT_PATH_PATTERN.finditer(value):
            candidate = str(match.group("path") or "").strip().rstrip(".,:;)")
            if candidate:
                found.append(candidate)
        return found
    if isinstance(value, dict):
        for nested in value.values():
            found.extend(_iter_artifact_paths(nested))
        return found
    if isinstance(value, list):
        for nested in value:
            found.extend(_iter_artifact_paths(nested))
    return found


def sse_event(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def combine_system_prompt(*parts: str | None) -> str | None:
    rendered = [str(item).strip() for item in parts if str(item or "").strip()]
    if not rendered:
        return None
    combined = "\n\n".join(rendered)
    # Warn if the combined system prompt is very large relative to the
    # model's context window — it can crowd out working context.
    if len(combined) > MAX_SYSTEM_PROMPT_CHARS:
        logger.warning(
            "Combined system prompt (%d chars) exceeds MAX_SYSTEM_PROMPT_CHARS (%d); "
            "truncating to fit. Consider shortening your system prompt.",
            len(combined),
            MAX_SYSTEM_PROMPT_CHARS,
        )
        combined = combined[:MAX_SYSTEM_PROMPT_CHARS]
    return combined


def format_team_context_system_prompt(team_context: dict[str, Any] | None) -> str | None:
    if not team_context:
        return None
    serialized = json.dumps(team_context, ensure_ascii=False, sort_keys=True)
    return f"Team context:\n{serialized}"


def extract_text_from_parts(parts: list[dict[str, Any]]) -> str:
    fragments: list[str] = []
    for item in parts:
        if not isinstance(item, dict):
            continue
        if item.get("type") == "text":
            text = item.get("text")
            if isinstance(text, str) and text:
                fragments.append(text)
    return "".join(fragments).strip()


def extract_response_text(payload: dict[str, Any]) -> str:
    # Prioritize structured output (from OpenCode's StructuredOutput tool)
    # over plain text parts, since structured output is the authoritative
    # response when the caller requested JSON schema output.
    info = payload.get("info")
    if isinstance(info, dict):
        structured_output = info.get("structured")
        if structured_output is None:
            structured_output = info.get("structured_output")
        if structured_output is not None:
            return json.dumps(structured_output, ensure_ascii=False)
        error = info.get("error")
        if isinstance(error, dict) and error.get("message"):
            return str(error.get("message"))
    parts = payload.get("parts")
    if isinstance(parts, list):
        text = extract_text_from_parts([item for item in parts if isinstance(item, dict)])
        if text:
            return text
    return ""


def build_json_output_schema(output_schema: dict[str, Any] | None) -> dict[str, Any]:
    if output_schema:
        return dict(output_schema)
    return {
        "type": "object",
        "description": "Return the final answer as a JSON object.",
        "additionalProperties": True,
    }


def build_prompt_format(request: "InvokeRequest") -> dict[str, Any] | None:
    if request.output_format == "json":
        return {
            "type": "json_schema",
            "schema": build_json_output_schema(request.output_schema),
            "retryCount": request.structured_output_retry_count if request.structured_output_retry_count is not None else STRUCTURED_OUTPUT_RETRY_COUNT,
        }
    return None


def get_session_messages(session_id: str) -> list[dict[str, Any]]:
    """Fetch the complete message history for a session from the OpenCode server."""
    with runtime_http_client() as hclient:
        response = hclient.get(f"/session/{session_id}/message")
        if response.status_code == 404:
            return []
        response.raise_for_status()
        payload = response.json()
    if not isinstance(payload, list):
        return []
    return [item for item in payload if isinstance(item, dict)]


def get_session_status(session_id: str) -> dict[str, Any]:
    """Check the current status (idle/busy/retry) of a session."""
    try:
        with runtime_http_client() as hclient:
            response = hclient.get("/session/status")
            response.raise_for_status()
            statuses = response.json()
        if not isinstance(statuses, dict):
            return {"type": "idle"}
        return statuses.get(session_id, {"type": "idle"})
    except (httpx.HTTPError, ValueError):
        logger.warning("Failed to get session status for %s; assuming idle.", session_id)
        return {"type": "idle"}


def wait_for_session_idle(session_id: str, timeout_seconds: float = SESSION_IDLE_TIMEOUT_SECONDS) -> dict[str, Any]:
    deadline = time.time() + timeout_seconds
    last_status = {"type": "idle"}
    while time.time() < deadline:
        last_status = get_session_status(session_id)
        if str(last_status.get("type", "idle")) == "idle":
            return last_status
        time.sleep(SESSION_IDLE_POLL_SECONDS)
    return last_status


def abort_session(session_id: str) -> bool:
    """Abort an active session to stop any ongoing AI processing."""
    try:
        with runtime_http_client() as hclient:
            response = hclient.post(f"/session/{session_id}/abort")
            return response.status_code == 200
    except httpx.HTTPError:
        logger.warning("Failed to abort session %s", session_id)
        return False


def summarize_session(session_id: str, model_ref: str | None = None) -> bool:
    """Trigger compaction/summarization of a session to free context space."""
    try:
        model_payload = build_model_payload(model_ref or DEFAULT_MODEL)
        with runtime_http_client() as hclient:
            response = hclient.post(
                f"/session/{session_id}/summarize",
                json={
                    "providerID": model_payload["providerID"],
                    "modelID": model_payload["modelID"],
                    "auto": True,
                },
            )
            return response.status_code == 200
    except httpx.HTTPError:
        logger.warning("Failed to summarize session %s", session_id)
        return False


def init_session(session_id: str, model_ref: str | None = None) -> bool:
    """Initialize a session by analyzing the project for better tool use."""
    try:
        model_payload = build_model_payload(model_ref or DEFAULT_MODEL)
        with runtime_http_client() as hclient:
            response = hclient.post(
                f"/session/{session_id}/init",
                json={
                    "providerID": model_payload["providerID"],
                    "modelID": model_payload["modelID"],
                    "messageID": str(uuid.uuid4()),
                },
            )
            return response.status_code == 200
    except httpx.HTTPError:
        logger.warning("Failed to initialize session %s", session_id)
        return False


def get_session_todos(session_id: str) -> list[dict[str, Any]]:
    """Fetch the current todo list for a session."""
    try:
        with runtime_http_client() as hclient:
            response = hclient.get(f"/session/{session_id}/todo")
            if response.status_code != 200:
                return []
            payload = response.json()
            if isinstance(payload, list):
                return [item for item in payload if isinstance(item, dict)]
    except (httpx.HTTPError, ValueError):
        pass
    return []


def check_context_overflow(payload: dict[str, Any]) -> bool:
    """Check if the response indicates context window is nearing capacity."""
    info = payload.get("info") or {}
    if not isinstance(info, dict):
        return False
    # Check for ContextOverflowError
    error = info.get("error")
    if isinstance(error, dict) and error.get("name") == "ContextOverflowError":
        return True
    # Check token usage against model context limit
    tokens = info.get("tokens")
    if isinstance(tokens, dict):
        total = tokens.get("total") or 0
        if not total:
            cache = tokens.get("cache") or {}
            total = (
                (tokens.get("input") or 0)
                + (tokens.get("output") or 0)
                + (cache.get("read") or 0)
                + (cache.get("write") or 0)
            )
        if total > 0 and total >= MODEL_CONTEXT_LIMIT * COMPACTION_TOKEN_THRESHOLD:
            return True
    return False


def classify_error_type(payload: dict[str, Any]) -> str | None:
    """Classify the error type from an OpenCode response for targeted recovery.

    Returns one of: ``"context_overflow"``, ``"structured_output"``,
    ``"auth"``, ``"api"``, ``"aborted"``, ``"output_length"``, or ``None``.
    """
    info = payload.get("info") or {}
    if not isinstance(info, dict):
        return None
    error = info.get("error")
    if not isinstance(error, dict):
        return None
    name = str(error.get("name", "")).strip()
    error_map = {
        "ContextOverflowError": "context_overflow",
        "StructuredOutputError": "structured_output",
        "ProviderAuthError": "auth",
        "APIError": "api",
        "MessageAbortedError": "aborted",
        "MessageOutputLengthError": "output_length",
    }
    return error_map.get(name)


def compute_context_budget(payload: dict[str, Any]) -> dict[str, Any]:
    """Compute context budget information from an OpenCode response payload.

    Returns a dict with token usage, remaining capacity, percentage used,
    and a status tier: ``"ok"`` (>35% remaining), ``"warning"`` (25-35%),
    or ``"critical"`` (<25%).
    """
    info = payload.get("info") or {}
    if not isinstance(info, dict):
        return {"status": "unknown", "model_context_limit": MODEL_CONTEXT_LIMIT}
    tokens = info.get("tokens")
    if not isinstance(tokens, dict):
        return {"status": "unknown", "model_context_limit": MODEL_CONTEXT_LIMIT}
    total = tokens.get("total") or 0
    if not total:
        cache = tokens.get("cache") or {}
        total = (
            (tokens.get("input") or 0)
            + (tokens.get("output") or 0)
            + (cache.get("read") or 0)
            + (cache.get("write") or 0)
        )
    if total <= 0:
        return {"status": "unknown", "model_context_limit": MODEL_CONTEXT_LIMIT}
    remaining = max(MODEL_CONTEXT_LIMIT - total, 0)
    usage_pct = round((total / MODEL_CONTEXT_LIMIT) * 100, 1)
    remaining_pct = 100.0 - usage_pct
    if remaining_pct > 35:
        status = "ok"
    elif remaining_pct >= 25:
        status = "warning"
    else:
        status = "critical"
    return {
        "model_context_limit": MODEL_CONTEXT_LIMIT,
        "tokens_used": total,
        "tokens_remaining": remaining,
        "usage_percent": usage_pct,
        "status": status,
    }


_ANTI_PATTERN_REGEXES: list[tuple[str, re.Pattern[str]]] = [
    ("TODO marker", re.compile(r"\bTODO\b", re.IGNORECASE)),
    ("FIXME marker", re.compile(r"\bFIXME\b", re.IGNORECASE)),
    ("HACK marker", re.compile(r"\bHACK\b", re.IGNORECASE)),
    ("placeholder implementation", re.compile(r"\bplaceholder\b", re.IGNORECASE)),
    ("stub implementation", re.compile(r"\bstub\b", re.IGNORECASE)),
    ("not implemented", re.compile(r"\bnot\s+implemented\b", re.IGNORECASE)),
    ("empty return", re.compile(r"return\s*\n|return\s*$", re.MULTILINE)),
    ("pass statement", re.compile(r"^\s*pass\s*$", re.MULTILINE)),
    ("console-only implementation", re.compile(r"console\.log\(|print\(['\"]", re.IGNORECASE)),
]


def detect_anti_patterns(text: str) -> list[str]:
    """Scan response text for common anti-patterns.

    Returns a deduplicated list of anti-pattern labels found.
    """
    if not text:
        return []
    found: list[str] = []
    for label, pattern in _ANTI_PATTERN_REGEXES:
        if pattern.search(text):
            found.append(label)
    return found


def derive_task_status(
    status: str,
    warnings: list[str],
    context_budget: dict[str, Any],
    anti_patterns: list[str] | None = None,
) -> str:
    """Derive a high-level task status using the Superpowers 4-status model.

    Returns one of: ``DONE``, ``DONE_WITH_CONCERNS``, ``NEEDS_CONTEXT``,
    ``BLOCKED``.
    """
    if status in ("error",):
        return "BLOCKED"
    if context_budget.get("status") == "critical":
        return "NEEDS_CONTEXT"
    concerns = bool(warnings) or bool(anti_patterns)
    if status == "completed" and not concerns:
        return "DONE"
    if status == "completed" and concerns:
        return "DONE_WITH_CONCERNS"
    # incomplete or unknown statuses with context pressure
    if context_budget.get("status") == "warning":
        return "NEEDS_CONTEXT"
    return "DONE_WITH_CONCERNS"


def select_agent_for_prompt(prompt: str, *, is_first_turn: bool) -> str:
    """Select the appropriate OpenCode agent based on prompt characteristics.

    Uses the ``plan`` agent for complex first-turn prompts to get a structured
    plan before execution, then ``build`` for subsequent turns.
    """
    if not is_first_turn:
        return DEFAULT_AGENT
    # Use plan agent for complex prompts that benefit from structured planning
    if len(prompt) >= PLAN_AGENT_PROMPT_THRESHOLD and DEFAULT_AGENT == "build":
        # Heuristic: prompts with multiple sentences, bullet points, or
        # explicit multi-step indicators benefit from planning first
        complexity_markers = 0
        if prompt.count("\n") >= 2:
            complexity_markers += 1
        if any(marker in prompt.lower() for marker in ("step 1", "first,", "then ", "finally ", "1.", "2.", "- ")):
            complexity_markers += 1
        if len(prompt) >= 1000:
            complexity_markers += 1
        if complexity_markers >= 2:
            return "plan"
    return DEFAULT_AGENT


def get_latest_assistant_payload(messages: list[dict[str, Any]]) -> dict[str, Any] | None:
    for message in reversed(messages):
        info = message.get("info")
        if isinstance(info, dict) and info.get("role") == "assistant":
            return {
                "info": info,
                "parts": message.get("parts") if isinstance(message.get("parts"), list) else [],
            }
    return None


def extract_tool_calls_from_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Extract a summary of all tool calls from the session message history."""
    tool_calls: list[dict[str, Any]] = []
    for msg in messages:
        parts = msg.get("parts")
        if not isinstance(parts, list):
            continue
        for part in parts:
            if not isinstance(part, dict) or part.get("type") != "tool":
                continue
            state = part.get("state") or {}
            if not isinstance(state, dict):
                continue
            tool_calls.append({
                "tool": str(part.get("tool", "")),
                "status": str(state.get("status", "unknown")),
                "input": state.get("input"),
                "output": truncate_text(str(state.get("output", "")), 2000),
            })
    return tool_calls


def extract_artifacts_from_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Extract file artifacts from tool parts and patch parts."""
    artifacts: dict[str, dict[str, Any]] = {}
    for msg in messages:
        parts = msg.get("parts")
        if not isinstance(parts, list):
            continue
        for part in parts:
            if not isinstance(part, dict):
                continue
            part_type = part.get("type")
            if part_type == "tool":
                tool_name = str(part.get("tool", ""))
                state = part.get("state") or {}
                if not isinstance(state, dict):
                    continue
                if tool_name in ("write", "edit") and state.get("status") == "completed":
                    input_data = state.get("input") or {}
                    if isinstance(input_data, dict):
                        file_path = str(input_data.get("filePath", "")).strip()
                        if file_path:
                            artifacts[file_path] = {
                                "path": file_path,
                                "tool": tool_name,
                                "status": "completed",
                            }
                if state.get("status") == "completed":
                    for file_path in _iter_artifact_paths(state.get("output")) + _iter_artifact_paths(state.get("input")):
                        suffix = Path(file_path).suffix.lower()
                        if suffix not in DOWNLOADABLE_ARTIFACT_EXTENSIONS:
                            continue
                        artifacts[file_path] = {
                            "path": file_path,
                            "tool": tool_name or "tool",
                            "status": "completed",
                        }
            elif part_type == "patch":
                for file_name in part.get("files") or []:
                    file_name = str(file_name).strip()
                    if file_name:
                        artifacts[file_name] = {
                            "path": file_name,
                            "tool": "patch",
                            "status": "completed",
                        }
    result = sorted(artifacts.values(), key=lambda a: a.get("path", ""))
    return result[:ARTIFACT_COLLECTION_MAX_FILES]


def detect_task_errors(messages: list[dict[str, Any]]) -> list[str]:
    """Detect tool-call errors in the session message history."""
    errors: list[str] = []
    for msg in messages:
        info = msg.get("info")
        if isinstance(info, dict):
            err = info.get("error")
            if err:
                if isinstance(err, dict):
                    errors.append(str(err.get("message", err.get("name", str(err)))))
                else:
                    errors.append(str(err))
        parts = msg.get("parts")
        if not isinstance(parts, list):
            continue
        for part in parts:
            if not isinstance(part, dict) or part.get("type") != "tool":
                continue
            state = part.get("state") or {}
            if isinstance(state, dict) and state.get("status") == "error":
                tool = str(part.get("tool", "unknown"))
                reason = str(state.get("error", "unknown error"))
                errors.append(f"Tool '{tool}' failed: {reason}")
    return errors


def detect_completion_status(payload: dict[str, Any]) -> str:
    """Determine whether the agent response indicates task completion.

    Returns one of ``"completed"``, ``"error"``, ``"context_overflow"``,
    ``"incomplete"``, or ``"unknown"``.
    """
    info = payload.get("info") or {}
    if not isinstance(info, dict):
        return "unknown"
    error = info.get("error")
    if error:
        if isinstance(error, dict):
            name = str(error.get("name", "")).strip()
            if name == "ContextOverflowError":
                return "context_overflow"
        return "error"
    finish = str(info.get("finish", "")).strip().lower()
    if finish == "error":
        return "error"
    # Incomplete markers — the agent still has pending tool calls or
    # hasn't produced a finish reason yet.
    if finish in ("tool-calls", "unknown", ""):
        return "incomplete"
    # Everything else (stop, end_turn, length, content-filter, …)
    # indicates the model stopped generating and the response is final.
    return "completed"


def runtime_capabilities() -> dict[str, Any]:
    return {
        "native_tools": sorted(NATIVE_TOOL_NAMES),
        "native_tool_count": len(NATIVE_TOOL_NAMES),
        "output_formats": sorted(FORMAT_INSTRUCTIONS.keys()),
        "structured_output": {
            "supported": True,
            "json_schema": True,
            "default_retry_count": STRUCTURED_OUTPUT_RETRY_COUNT,
        },
        "autonomous_execution": {
            "supported": True,
            "default_enabled": True,
            "default_max_retries": AUTONOMOUS_MAX_RETRIES,
            "default_max_turns": AUTONOMOUS_MAX_TURNS,
        },
        "agents": {
            "available": ["build", "plan", "general", "explore"],
            "default": DEFAULT_AGENT,
            "plan_threshold_chars": PLAN_AGENT_PROMPT_THRESHOLD,
        },
        "session_management": {
            "abort": True,
            "summarize": True,
            "init": True,
            "init_on_create": SESSION_INIT_ON_CREATE,
            "todos": True,
            "compaction_threshold": COMPACTION_TOKEN_THRESHOLD,
        },
        "mcp_usage": {
            "available": bool(SKILL_RUNTIME_CONFIG.get("mcpSidecars") or os.getenv("MCP_SERVERS", "").strip()),
            "preferred_mode": "native-tools-first",
        },
    }


def build_format_system_prompt(output_format: str | None) -> str | None:
    """Return a system-prompt fragment that guides the model to produce the requested format."""
    if not output_format:
        return None
    return FORMAT_INSTRUCTIONS.get(output_format.strip().lower())


def build_model_payload(model_ref: str) -> dict[str, str]:
    cleaned = model_ref.strip()
    if "/" in cleaned:
        provider_id, model_id = cleaned.split("/", 1)
        provider_id = provider_id.strip() or DEFAULT_PROVIDER
        model_id = model_id.strip() or DEFAULT_MODEL
        return {"providerID": provider_id, "modelID": model_id}
    return {"providerID": DEFAULT_PROVIDER, "modelID": cleaned or DEFAULT_MODEL}


def validate_inbound_a2a_request(request: "InvokeRequest") -> None:
    caller_agent_name = (request.caller_agent_name or "").strip()
    caller_agent_namespace = (request.caller_agent_namespace or "").strip()
    if not caller_agent_name and not caller_agent_namespace:
        return
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


def a2a_response_metadata(request: "InvokeRequest") -> dict[str, Any] | None:
    if not request.caller_agent_name or not request.caller_agent_namespace:
        return None
    return {
        "callerAgent": request.caller_agent_name,
        "callerNamespace": request.caller_agent_namespace,
        "parentThreadId": request.parent_thread_id,
        "callerRequestId": request.caller_request_id,
    }


def build_invoke_warnings(request: "InvokeRequest") -> list[str]:
    warnings: list[str] = []
    if request.no_session:
        warnings.append("Session persistence is disabled for this invocation; the returned thread_id cannot be resumed.")
    warnings.extend(str(item).strip() for item in (SKILL_RUNTIME_CONFIG.get("warnings") or []) if str(item).strip())
    return dedupe_items(warnings)


class InvokeRequest(BaseModel):
    prompt: str = Field(default="", max_length=MAX_PROMPT_CHARS)
    thread_id: str | None = Field(default=None, max_length=MAX_THREAD_ID_CHARS)
    model: str | None = Field(default=None, max_length=MAX_MODEL_CHARS)
    system: str | None = Field(default=None, max_length=MAX_SYSTEM_PROMPT_CHARS)
    require_approval: bool = False
    approval_action: str | None = Field(default=None, max_length=512)
    tool_name: str = Field(default="", max_length=128)
    tool_args: dict[str, Any] = Field(default_factory=dict)
    sandbox_session: dict[str, Any] | None = None
    mcp_server: str | None = Field(default=None, max_length=128)
    a2a_target_agent: str | None = Field(default=None, max_length=63)
    a2a_target_namespace: str | None = Field(default=None, max_length=63)
    a2a_timeout_seconds: float | None = Field(default=None, ge=1.0)
    caller_agent_name: str | None = Field(default=None, max_length=63)
    caller_agent_namespace: str | None = Field(default=None, max_length=63)
    parent_thread_id: str | None = Field(default=None, max_length=MAX_THREAD_ID_CHARS)
    caller_request_id: str | None = Field(default=None, max_length=128)
    team_context: dict[str, Any] | None = None
    debug: bool = False
    no_session: bool = False
    max_turns: int | None = Field(default=None, ge=1, le=1000)
    working_directory: str | None = Field(default=None, max_length=512)
    output_format: str | None = Field(default=None, max_length=32)
    output_schema: dict[str, Any] | None = None
    structured_output_retry_count: int | None = Field(default=None)
    max_retries: int | None = Field(default=None)
    autonomous: bool = True
    pre_authorized_actions: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_request(self) -> "InvokeRequest":
        self.prompt = self.prompt.strip()
        self.thread_id = self.thread_id.strip() or None if self.thread_id is not None else None
        self.model = self.model.strip() or None if self.model is not None else None
        self.system = self.system.strip() or None if self.system is not None else None
        self.approval_action = self.approval_action.strip() or None if self.approval_action is not None else None
        self.tool_name = self.tool_name.strip()
        self.mcp_server = self.mcp_server.strip() or None if self.mcp_server is not None else None
        self.a2a_target_agent = self.a2a_target_agent.strip() or None if self.a2a_target_agent is not None else None
        self.a2a_target_namespace = self.a2a_target_namespace.strip() or None if self.a2a_target_namespace is not None else None
        self.caller_agent_name = self.caller_agent_name.strip() or None if self.caller_agent_name is not None else None
        self.caller_agent_namespace = self.caller_agent_namespace.strip() or None if self.caller_agent_namespace is not None else None
        self.parent_thread_id = self.parent_thread_id.strip() or None if self.parent_thread_id is not None else None
        self.caller_request_id = self.caller_request_id.strip() or None if self.caller_request_id is not None else None
        self.output_format = self.output_format.strip().lower() or None if self.output_format is not None else None
        if self.output_schema is not None and not isinstance(self.output_schema, dict):
            raise ValueError("output_schema must be a JSON object when provided")
        if self.output_schema is not None and self.output_format is None:
            self.output_format = "json"

        if not self.prompt:
            raise ValueError("prompt must not be blank")
        if self.tool_name:
            raise ValueError("opencode runtime does not support direct tool_name execution")
        if self.mcp_server:
            raise ValueError("opencode runtime does not support gateway-routed mcp_server execution")
        if self.a2a_target_agent or self.a2a_target_namespace or self.a2a_timeout_seconds is not None:
            raise ValueError("opencode runtime does not support outbound A2A invocation")
        if self.sandbox_session is not None:
            raise ValueError("opencode runtime does not support sandbox_session continuity")
        if self.caller_agent_name or self.caller_agent_namespace:
            if not self.caller_agent_name or not self.caller_agent_namespace:
                raise ValueError("caller_agent_name and caller_agent_namespace must be provided together")
            normalize_identifier(self.caller_agent_name, source="caller_agent_name")
            normalize_identifier(self.caller_agent_namespace, source="caller_agent_namespace")
        if self.no_session and self.thread_id:
            raise ValueError("thread_id cannot be used when no_session is enabled")
        if self.team_context is not None:
            encoded = json.dumps(self.team_context, ensure_ascii=False, sort_keys=True)
            if len(encoded) > MAX_TEAM_CONTEXT_CHARS:
                raise ValueError(f"team_context exceeds {MAX_TEAM_CONTEXT_CHARS} characters")
        if self.output_format and self.output_format not in FORMAT_INSTRUCTIONS:
            raise ValueError(f"output_format must be one of: {', '.join(sorted(FORMAT_INSTRUCTIONS))}")
        return self


class InvokeResponse(BaseModel):
    thread_id: str
    response: str
    model: str
    status: str = "completed"
    approval_name: str | None = None
    retry_after_seconds: int | None = None
    a2a: dict[str, Any] | None = None
    warnings: list[str] = Field(default_factory=list)
    artifacts: list[dict[str, Any]] = Field(default_factory=list)
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] | None = None


SKILL_RUNTIME_CONFIG: dict[str, Any] = {
    "skillFiles": [],
    "warnings": [],
    "configFiles": [],
    "mcpSidecars": [],
}


def configure_git_credentials() -> None:
    """Bootstrap git credentials from env vars so bash git operations have auth.

    Reads GIT_AUTH_METHOD, GIT_TOKEN, GIT_USERNAME, GIT_PASSWORD, and
    GIT_REPO_URL — the same env vars injected by the operator when
    gitConfig is set.
    """
    auth_method = os.getenv("GIT_AUTH_METHOD", "").strip()
    if not auth_method:
        return

    subprocess.run(
        ["git", "config", "--global", "user.name", "AI Agent"],
        capture_output=True, timeout=5,
    )
    subprocess.run(
        ["git", "config", "--global", "user.email", "agent@kubemininions.local"],
        capture_output=True, timeout=5,
    )

    repo_url = os.getenv("GIT_REPO_URL", "").strip()

    if auth_method == "token":
        token = os.getenv("GIT_TOKEN", "").strip()
        if not token:
            logger.warning("GIT_AUTH_METHOD=token but GIT_TOKEN is empty")
            return
        subprocess.run(
            ["git", "config", "--global", "credential.helper", "store"],
            capture_output=True, timeout=5,
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
            capture_output=True, timeout=5,
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
                ["git", "config", "--global", "core.sshCommand",
                 f"ssh -i {ssh_key} -o StrictHostKeyChecking=accept-new"],
                capture_output=True, timeout=5,
            )
            logger.info("Configured git SSH key for bash git operations")


def validate_runtime_startup() -> None:
    binary_path = Path(OPENCODE_BIN)
    if binary_path.is_absolute():
        if not binary_path.exists() or not os.access(binary_path, os.X_OK):
            raise RuntimeError(f"OpenCode binary '{OPENCODE_BIN}' is not executable")
        return
    if shutil.which(OPENCODE_BIN) is None:
        raise RuntimeError(f"OpenCode binary '{OPENCODE_BIN}' was not found on PATH")


def build_server_env(config_content: dict[str, Any]) -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "HOME": HOME_DIR,
            "XDG_CONFIG_HOME": XDG_CONFIG_HOME,
            "XDG_DATA_HOME": XDG_DATA_HOME,
            "OPENCODE_CONFIG_DIR": OPENCODE_CONFIG_DIR,
            "OPENCODE_CONFIG_CONTENT": json.dumps(config_content, ensure_ascii=False),
            "OPENCODE_CLIENT": "server",
            "OPENCODE_DISABLE_AUTOUPDATE": "true",
            "OPENCODE_DISABLE_LSP_DOWNLOAD": "true",
            "OPENCODE_DISABLE_DEFAULT_PLUGINS": env.get("OPENCODE_DISABLE_DEFAULT_PLUGINS", "false") or "false",
            "OPENCODE_SERVER_PASSWORD": env.get("OPENCODE_SERVER_PASSWORD", ""),
        }
    )
    return env


def server_base_url() -> str:
    return f"http://{OPENCODE_SERVER_HOST}:{OPENCODE_SERVER_PORT}"


def wait_for_server_ready(process: subprocess.Popen[str]) -> None:
    deadline = time.time() + SERVER_STARTUP_TIMEOUT_SECONDS
    health_url = f"{server_base_url()}/global/health"
    while time.time() < deadline:
        if process.poll() is not None:
            stdout_out = process.stdout.read() if process.stdout else ""
            stderr_out = process.stderr.read() if process.stderr else ""
            logger.error("OpenCode server exited with code %s.\nSTDOUT: %s\nSTDERR: %s", process.returncode, stdout_out[:4000], stderr_out[:4000])
            raise RuntimeError("OpenCode server exited before becoming ready")
        try:
            with httpx.Client(timeout=2.0, trust_env=False) as client:
                response = client.get(health_url)
                if response.status_code == 200 and response.json().get("healthy") is True:
                    return
        except httpx.HTTPError:
            pass
        time.sleep(SERVER_POLL_INTERVAL_SECONDS)
    raise RuntimeError("Timed out while waiting for the OpenCode server to become ready")


def ensure_server_running() -> None:
    with _runtime_lock:
        proc = _runtime_process
    if proc is None or proc.poll() is not None:
        raise HTTPException(status_code=503, detail="OpenCode server is not running")


def runtime_http_client() -> httpx.Client:
    return httpx.Client(base_url=server_base_url(), timeout=HTTP_TIMEOUT_SECONDS, trust_env=False)


def create_remote_session(working_directory: str) -> str:
    with runtime_http_client() as client:
        response = client.post("/session", params={"directory": working_directory}, json={"title": SERVICE_NAME})
        response.raise_for_status()
        payload = response.json()
    session_id = str(payload.get("id") or "").strip()
    if not session_id:
        raise HTTPException(status_code=502, detail="OpenCode session creation did not return a session id")
    return session_id


def ensure_remote_session(thread_id: str, working_directory: str) -> str:
    session_id = SESSION_REGISTRY.get(thread_id)
    if session_id:
        return session_id
    session_id = create_remote_session(working_directory)
    SESSION_REGISTRY.set(thread_id, session_id)
    return session_id


def send_prompt(
    *,
    session_id: str,
    prompt: str,
    model: str,
    system_prompt: str | None,
    prompt_format: dict[str, Any] | None,
    working_directory: str,
    agent: str,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "parts": [{"type": "text", "text": prompt}],
        "model": build_model_payload(model),
        "agent": agent,
    }
    if system_prompt:
        body["system"] = system_prompt
    if prompt_format:
        body["format"] = prompt_format

    with runtime_http_client() as client:
        response = client.post(
            f"/session/{session_id}/message",
            params={"directory": working_directory},
            json=body,
        )
        if response.status_code == 404:
            raise HTTPException(status_code=404, detail="OpenCode session not found")
        response.raise_for_status()
        return response.json()


def _send_prompt_with_session_recovery(
    *,
    session_id: str,
    prompt: str,
    model: str,
    system_prompt: str | None,
    prompt_format: dict[str, Any] | None,
    working_directory: str,
    agent: str,
    logical_thread_id: str,
    allow_session_recovery: bool,
) -> tuple[str, dict[str, Any]]:
    """Send a prompt to the OpenCode server, recovering the session on 404."""
    try:
        payload = send_prompt(
            session_id=session_id,
            prompt=prompt,
            model=model,
            system_prompt=system_prompt,
            prompt_format=prompt_format,
            working_directory=working_directory,
            agent=agent,
        )
        return session_id, payload
    except HTTPException as exc:
        if exc.status_code == 404 and allow_session_recovery:
            session_id = create_remote_session(working_directory)
            SESSION_REGISTRY.set(logical_thread_id, session_id)
            payload = send_prompt(
                session_id=session_id,
                prompt=prompt,
                model=model,
                system_prompt=system_prompt,
                prompt_format=prompt_format,
                working_directory=working_directory,
                agent=agent,
            )
            return session_id, payload
        raise


def _extract_structured_output(payload: dict[str, Any]) -> Any | None:
    """Return the structured output object from an OpenCode response, or *None*."""
    info = payload.get("info")
    if not isinstance(info, dict):
        return None
    structured = info.get("structured")
    if structured is not None:
        return structured
    return info.get("structured_output")


def _build_response_metadata(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Extract metadata (tokens, cost, timing, structured_output) from the OpenCode response."""
    info = payload.get("info")
    if not isinstance(info, dict):
        return None
    metadata: dict[str, Any] = {}
    tokens = info.get("tokens")
    if isinstance(tokens, dict):
        metadata["tokens"] = tokens
    cost = info.get("cost")
    if isinstance(cost, (int, float)):
        metadata["cost"] = cost
    time_info = info.get("time")
    if isinstance(time_info, dict):
        metadata["time"] = time_info
    finish = info.get("finish")
    if finish:
        metadata["finish_reason"] = str(finish)
    structured = _extract_structured_output(payload)
    if structured is not None:
        metadata["structured_output"] = structured
    return metadata or None


StreamCallback = Any  # Callable[[str, dict[str, Any]], None] | None


def invoke_opencode(request: InvokeRequest, stream_callback: StreamCallback = None) -> InvokeResponse:
    ensure_server_running()
    validate_inbound_a2a_request(request)

    if request.require_approval:
        try:
            approval = hitl_gate(
                action_description=request.approval_action or f"Invoke OpenCode agent '{SERVICE_NAME}'",
                request_id=request.thread_id or str(uuid.uuid4()),
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        if approval.get("decision") == "pending":
            return InvokeResponse(
                thread_id=request.thread_id or str(uuid.uuid4()),
                response="",
                model=request.model or DEFAULT_MODEL,
                status="approval_pending",
                approval_name=approval.get("approval_name"),
                a2a=a2a_response_metadata(request),
                warnings=build_invoke_warnings(request),
            )

    working_directory = resolve_working_directory(request.working_directory)
    selected_model = request.model or DEFAULT_MODEL
    logical_thread_id = request.thread_id or str(uuid.uuid4())
    created_new_session = False
    if request.no_session:
        session_id = create_remote_session(working_directory)
        created_new_session = True
    else:
        existing_session = SESSION_REGISTRY.get(logical_thread_id)
        if existing_session:
            session_id = existing_session
        else:
            session_id = create_remote_session(working_directory)
            # Atomic register: if another thread raced us, use the winner's
            # session and discard ours (avoids orphaned sessions).
            session_id = SESSION_REGISTRY.get_or_set(logical_thread_id, session_id)
            created_new_session = True

    # New sessions benefit from init analysis to improve planning quality and
    # AGENTS.md context for complex multi-step tasks.
    if created_new_session and request.autonomous and SESSION_INIT_ON_CREATE:
        if not init_session(session_id, selected_model):
            logger.warning("Session init failed for %s", session_id)

    # Build system prompt stack: autonomy instructions + native-tool preference
    # + user system prompt + output format + team context
    pre_auth_prompt: str | None = None
    if request.pre_authorized_actions:
        allowed = ", ".join(request.pre_authorized_actions)
        pre_auth_prompt = (
            f"PRE-AUTHORIZED ACTIONS: The following actions have been pre-approved "
            f"by the workflow owner and may be executed without hesitation: {allowed}. "
            f"You do NOT need confirmation to perform these actions."
        )
    system_prompt = combine_system_prompt(
        AUTONOMY_SYSTEM_PROMPT if request.autonomous else None,
        DEFAULT_SYSTEM_PROMPT,
        request.system,
        pre_auth_prompt,
        build_format_system_prompt(request.output_format),
        format_team_context_system_prompt(request.team_context),
    )
    prompt_format = build_prompt_format(request)
    max_retries = request.max_retries if request.max_retries is not None else AUTONOMOUS_MAX_RETRIES
    effective_max_turns = request.max_turns if request.max_turns is not None else AUTONOMOUS_MAX_TURNS

    # --- Autonomous multi-turn loop ---
    all_warnings: list[str] = list(build_invoke_warnings(request))
    retries_used = 0
    last_payload: dict[str, Any] = {}
    current_prompt = request.prompt
    compaction_attempts = 0
    last_compaction_turn = -COMPACTION_MIN_TURN_SPACING  # allow first compaction immediately
    handoff_summary: dict[str, Any] | None = None
    _resend_format = False  # set True when retrying structured output errors

    # Select agent: use plan for complex first prompts, then build
    current_agent = select_agent_for_prompt(request.prompt, is_first_turn=True) if request.autonomous else DEFAULT_AGENT
    if current_agent == "plan" and current_agent != DEFAULT_AGENT:
        all_warnings.append("Using plan agent for initial analysis before execution.")

    def _emit(event_type: str, data: dict[str, Any]) -> None:
        if stream_callback is not None:
            try:
                stream_callback(event_type, data)
            except Exception:
                pass

    for turn in range(effective_max_turns):
        _emit("response.turn_started", {"turn": turn + 1, "max_turns": effective_max_turns, "agent": current_agent})
        use_system = system_prompt if turn == 0 else None
        try:
            session_id, payload = _send_prompt_with_session_recovery(
                session_id=session_id,
                prompt=current_prompt,
                model=selected_model,
                system_prompt=use_system,
                prompt_format=prompt_format if (turn == 0 or _resend_format) else None,
                working_directory=working_directory,
                agent=current_agent,
                logical_thread_id=logical_thread_id,
                allow_session_recovery=(not request.no_session),
            )
        except httpx.HTTPError as exc:
            # Permanent client errors (4xx) should not be retried.
            is_permanent = (
                isinstance(exc, httpx.HTTPStatusError)
                and exc.response.status_code < 500
                and exc.response.status_code not in (408, 429)
            )
            if is_permanent or retries_used >= max_retries:
                raise HTTPException(
                    status_code=502,
                    detail=f"OpenCode invocation failed after {retries_used} retries: {exc}",
                ) from exc
            retries_used += 1
            _emit("response.error_recovery", {"turn": turn + 1, "error_type": "http", "retry": retries_used, "max_retries": max_retries})
            all_warnings.append(
                f"Turn {turn + 1}: HTTP error '{exc}', retrying ({retries_used}/{max_retries})"
            )
            # Preserve the original prompt so the retry does not lose
            # context; only prepend a short recovery note.
            recovery_note = (
                f"[Note: the previous request encountered a transient error ({type(exc).__name__}). "
                f"Check whether the previous operation partially completed before retrying. "
                f"If files were partially written or commands partially executed, verify their "
                f"state before continuing.]\n\n"
            )
            current_prompt = truncate_text(
                f"{recovery_note}{current_prompt}", MAX_PROMPT_CHARS
            )
            continue

        last_payload = payload
        completion = detect_completion_status(payload)
        _resend_format = False  # reset after each successful send

        # Emit per-turn progress
        turn_text = extract_response_text(payload).strip()
        _emit("response.turn_completed", {
            "turn": turn + 1,
            "status": completion,
            "response_length": len(turn_text),
        })
        if turn_text:
            _emit("response.delta", {"turn": turn + 1, "delta": turn_text, "source": "opencode"})

        # After plan agent completes, switch to build agent for execution
        if current_agent == "plan" and completion in ("completed", "incomplete"):
            current_agent = DEFAULT_AGENT
            if completion == "completed":
                all_warnings.append("Plan phase completed, switching to build agent for execution.")
                current_prompt = (
                    "Now execute the plan you just created. For each step:\n"
                    "1. Implement the step completely — do not skip ahead.\n"
                    "2. Verify it works (read files back, run code, check output).\n"
                    "3. Fix any issues before moving to the next step.\n"
                    "4. Update the todo list to mark the step complete.\n"
                    "After all steps: run the full test suite or verify the overall "
                    "result meets the original objective."
                )
                continue

        # Handle context overflow — trigger compaction and retry
        _can_compact = (
            compaction_attempts < MAX_COMPACTION_ATTEMPTS
            and (turn - last_compaction_turn) >= COMPACTION_MIN_TURN_SPACING
        )
        if completion == "context_overflow" and _can_compact:
            compaction_attempts += 1
            last_compaction_turn = turn
            _emit("response.compaction", {"turn": turn + 1, "reason": "context_overflow", "attempt": compaction_attempts, "max": MAX_COMPACTION_ATTEMPTS})
            if summarize_session(session_id, model_ref=selected_model):
                all_warnings.append(f"Turn {turn + 1}: context overflow detected, triggered compaction ({compaction_attempts}/{MAX_COMPACTION_ATTEMPTS}).")
                wait_for_session_idle(session_id, timeout_seconds=SESSION_ABORT_TIMEOUT_SECONDS)
                current_prompt = (
                    "The context was compacted due to overflow. Before continuing:\n"
                    "1. ORIENT: Read your todowrite plan to recall progress. Run `glob **/*` "
                    "to see all files currently in the workspace.\n"
                    "2. LOCATE: Identify exactly which step you were on when context was compacted.\n"
                    "3. VERIFY: Check the last completed item actually works (read it, run it).\n"
                    "4. CONTINUE: Proceed from the next incomplete step. Do not redo completed work "
                    "or recreate files that already exist."
                )
                continue
            all_warnings.append(f"Turn {turn + 1}: context overflow, compaction failed.")

        if completion == "completed":
            break

        # Proactive compaction — if token usage is high, compact before overflow.
        # Must run AFTER the "completed" check to avoid unnecessary continuation
        # when the task finished successfully but token usage happens to be high.
        if _can_compact and check_context_overflow(payload):
            compaction_attempts += 1
            last_compaction_turn = turn
            _emit("response.compaction", {"turn": turn + 1, "reason": "proactive", "attempt": compaction_attempts, "max": MAX_COMPACTION_ATTEMPTS})
            if summarize_session(session_id, model_ref=selected_model):
                all_warnings.append(f"Turn {turn + 1}: proactively triggered compaction (token usage high, {compaction_attempts}/{MAX_COMPACTION_ATTEMPTS}).")
                wait_for_session_idle(session_id, timeout_seconds=SESSION_ABORT_TIMEOUT_SECONDS)
                current_prompt = (
                    "Context was proactively compacted to free space. Before continuing:\n"
                    "1. Check your todowrite plan to see which steps are done vs. remaining.\n"
                    "2. Run `glob **/*` to see existing files — do not recreate them.\n"
                    "3. Verify the last completed step is correct.\n"
                    "4. Continue from the next incomplete step — do not restart from the beginning."
                )
                continue

        if completion == "error":
            error_type = classify_error_type(payload)
            if error_type == "context_overflow" and _can_compact:
                compaction_attempts += 1
                last_compaction_turn = turn
                _emit("response.compaction", {"turn": turn + 1, "reason": "error_overflow", "attempt": compaction_attempts, "max": MAX_COMPACTION_ATTEMPTS})
                if summarize_session(session_id, model_ref=selected_model):
                    all_warnings.append(f"Turn {turn + 1}: context overflow error, compacting ({compaction_attempts}/{MAX_COMPACTION_ATTEMPTS}).")
                    wait_for_session_idle(session_id, timeout_seconds=SESSION_ABORT_TIMEOUT_SECONDS)
                    current_prompt = (
                        "Context was compacted after an error. Before continuing:\n"
                        "1. Review your plan to identify where you stopped.\n"
                        "2. Run `glob **/*` to see existing files in the workspace.\n"
                        "3. Check the last action's result — did it succeed or fail?\n"
                        "4. Continue from the next actionable step. Do not recreate existing files."
                    )
                    continue
            if error_type == "structured_output" and retries_used < max_retries:
                retries_used += 1
                _resend_format = True  # re-send json_schema format on retry
                _emit("response.error_recovery", {"turn": turn + 1, "error_type": "structured_output", "retry": retries_used, "max_retries": max_retries})
                all_warnings.append(
                    f"Turn {turn + 1}: structured output validation failed, retrying ({retries_used}/{max_retries})"
                )
                current_prompt = (
                    "Your previous response did not satisfy the required JSON schema. Fix it now:\n"
                    "1. Re-read the schema requirements — check all required fields and their types.\n"
                    "2. Ensure every required field is present with the correct type.\n"
                    "3. Output ONLY the valid JSON — no markdown fencing, no explanation text.\n"
                    "4. Validate mentally: would json.loads() parse this without error?"
                )
                continue
            if error_type == "auth":
                all_warnings.append(f"Turn {turn + 1}: authentication error, cannot retry.")
                break
            if retries_used < max_retries:
                retries_used += 1
                _emit("response.error_recovery", {"turn": turn + 1, "error_type": error_type or "unknown", "retry": retries_used, "max_retries": max_retries})
                all_warnings.append(f"Turn {turn + 1}: agent error ({error_type or 'unknown'}), retrying ({retries_used}/{max_retries})")
                current_prompt = (
                    "The previous step encountered an error. Before retrying:\n"
                    "1. Read the error message carefully — what specifically failed?\n"
                    "2. Identify the root cause — not just the symptom.\n"
                    "3. Fix the underlying issue, then retry.\n"
                    "If the same approach has already failed, try a fundamentally "
                    "different strategy instead of repeating the same steps."
                )
                continue
            break

        if completion == "incomplete" and turn + 1 < effective_max_turns:
            all_warnings.append(f"Turn {turn + 1}: task incomplete, sending continuation prompt")
            current_prompt = AUTONOMY_CONTINUATION_PROMPT
            continue

        # Exhausted retries or turns
        break

    # Generate handoff summary if context is still critical after exhausting compaction
    if compaction_attempts >= MAX_COMPACTION_ATTEMPTS and last_payload:
        budget = compute_context_budget(last_payload)
        if budget.get("status") == "critical":
            handoff_summary = {
                "reason": "context_exhausted",
                "compaction_attempts": compaction_attempts,
                "context_budget": budget,
                "turns_completed": min(turn + 1, effective_max_turns),
                "original_prompt": truncate_text(request.prompt, 500),
                "recommendation": "Start a new session. The context window is exhausted.",
            }
            all_warnings.append("Context exhausted after max compaction attempts; handoff summary generated.")

    # --- Collect full session history for artifacts and tool calls ---
    collected_tool_calls: list[dict[str, Any]] = []
    collected_artifacts: list[dict[str, Any]] = []
    collected_todos: list[dict[str, Any]] = []
    authoritative_payload = dict(last_payload)
    try:
        if detect_completion_status(last_payload) not in ("completed",):
            final_status = wait_for_session_idle(session_id)
            if str(final_status.get("type", "idle")) != "idle":
                # Abort the session if it's stuck busy
                abort_session(session_id)
                all_warnings.append(
                    f"Session {session_id} remained {final_status.get('type', 'busy')}, aborted."
                )
                wait_for_session_idle(session_id, timeout_seconds=5.0)

        messages = get_session_messages(session_id)
        collected_tool_calls = extract_tool_calls_from_messages(messages)
        collected_artifacts = extract_artifacts_from_messages(messages)
        collected_todos = get_session_todos(session_id)
        if len(collected_artifacts) >= ARTIFACT_COLLECTION_MAX_FILES:
            all_warnings.append(
                f"Artifact collection limited to {ARTIFACT_COLLECTION_MAX_FILES} files; some may have been omitted."
            )
        latest_assistant = get_latest_assistant_payload(messages)
        if latest_assistant is not None:
            authoritative_payload = latest_assistant

        # Check for residual errors and surface them as warnings
        residual_errors = detect_task_errors(messages)
        for err in residual_errors[:5]:
            all_warnings.append(f"Tool error: {truncate_text(err, 200)}")
    except Exception as exc:
        logger.warning("Failed to collect session history for %s: %s", session_id, exc)

    response_text = extract_response_text(authoritative_payload).strip() or "(no output)"
    final_status = detect_completion_status(authoritative_payload)
    response_metadata = _build_response_metadata(authoritative_payload)
    if response_metadata is None:
        response_metadata = {}
    if collected_todos:
        response_metadata["todos"] = collected_todos

    response_status = final_status
    if final_status == "context_overflow":
        response_status = "error"
    elif final_status == "unknown":
        response_status = "incomplete"
    if response_status != final_status:
        response_metadata["raw_status"] = final_status

    # --- Response enrichment (context intelligence) ---
    ctx_budget = compute_context_budget(authoritative_payload)
    response_metadata["context_budget"] = ctx_budget

    anti_patterns = detect_anti_patterns(response_text)
    if anti_patterns:
        response_metadata["anti_patterns"] = anti_patterns

    task_status = derive_task_status(
        response_status, all_warnings, ctx_budget, anti_patterns
    )
    response_metadata["task_status"] = task_status

    if handoff_summary:
        response_metadata["handoff_summary"] = handoff_summary

    return InvokeResponse(
        thread_id=logical_thread_id,
        response=response_text,
        model=selected_model,
        status=response_status,
        a2a=a2a_response_metadata(request),
        warnings=dedupe_items(all_warnings),
        artifacts=collected_artifacts,
        tool_calls=collected_tool_calls,
        metadata=response_metadata or None,
    )


@contextlib.asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    global _runtime_process, _runtime_ready, SKILL_RUNTIME_CONFIG

    ensure_runtime_directories()
    configure_git_credentials()
    validate_runtime_startup()
    config_files = materialize_opencode_config_files()
    skill_files, skill_warnings = materialize_skill_files()
    sidecars = load_opencode_sidecars()
    generated_config, generated_warnings = build_generated_config(sidecars)

    env = build_server_env(generated_config)
    process = subprocess.Popen(
        [
            OPENCODE_BIN,
            "serve",
            "--hostname",
            OPENCODE_SERVER_HOST,
            "--port",
            str(OPENCODE_SERVER_PORT),
        ],
        cwd=OPENCODE_WORKDIR,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    wait_for_server_ready(process)
    with _runtime_lock:
        _runtime_process = process
        _runtime_ready = True
        SKILL_RUNTIME_CONFIG = {
            "skillFiles": skill_files,
            "warnings": dedupe_items(skill_warnings + generated_warnings),
            "configFiles": config_files,
            "mcpSidecars": sidecars,
        }

    try:
        yield
    finally:
        with _runtime_lock:
            _runtime_ready = False
            _runtime_process = None
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


app = FastAPI(title="OpenCode Runtime", version="1.0.0", lifespan=lifespan)


@app.middleware("http")
async def add_request_id(request: Request, call_next):
    request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
    response = await call_next(request)
    response.headers["x-request-id"] = request_id
    return response


@app.get("/health")
def health() -> dict[str, Any]:
    total_sessions = SESSION_REGISTRY.size
    stale_sessions = SESSION_REGISTRY.stale_count(3600)  # stale = >1h idle
    return {
        "status": "healthy" if _runtime_ready else "starting",
        "runtime": "opencode",
        "service": SERVICE_NAME,
        "namespace": SERVICE_NAMESPACE,
        "provider": DEFAULT_PROVIDER,
        "agent": DEFAULT_AGENT,
        "sessions": {
            "total": total_sessions,
            "active": total_sessions - stale_sessions,
            "stale": stale_sessions,
            "at_capacity": total_sessions >= SESSION_MAX_ENTRIES,
        },
        "skills": {
            "count": len(SKILL_RUNTIME_CONFIG.get("skillFiles") or []),
            "files": SKILL_RUNTIME_CONFIG.get("skillFiles") or [],
            "warnings": SKILL_RUNTIME_CONFIG.get("warnings") or [],
        },
        "capabilities": runtime_capabilities(),
    }


@app.get("/ready")
def ready() -> dict[str, Any]:
    ensure_runtime_directories()
    if Path(OPENCODE_BIN).is_absolute():
        resolved_binary = OPENCODE_BIN if Path(OPENCODE_BIN).exists() else None
    else:
        resolved_binary = shutil.which(OPENCODE_BIN)
    if not resolved_binary:
        raise HTTPException(status_code=503, detail=f"opencode binary '{OPENCODE_BIN}' is not available on PATH")
    ensure_server_running()
    # Check if opencode subprocess is reachable
    opencode_server_healthy = False
    try:
        with httpx.Client(timeout=5.0) as probe:
            resp = probe.get(f"http://{OPENCODE_SERVER_HOST}:{OPENCODE_SERVER_PORT}/session")
            opencode_server_healthy = resp.status_code < 500
    except Exception:
        pass
    # Check if session registry file is writable
    session_registry_writable = False
    try:
        registry_path = SESSION_REGISTRY._path
        session_registry_writable = os.access(registry_path.parent, os.W_OK)
    except Exception:
        pass
    return {
        "status": "ready",
        "runtime": "opencode",
        "opencode_binary": OPENCODE_BIN,
        "opencode_binary_path": resolved_binary,
        "opencode_server_healthy": opencode_server_healthy,
        "session_registry_writable": session_registry_writable,
        "config_root": OPENCODE_CONFIG_DIR,
        "workspace_root": OPENCODE_WORKDIR,
        "config_files": SKILL_RUNTIME_CONFIG.get("configFiles") or [],
        "skill_files": SKILL_RUNTIME_CONFIG.get("skillFiles") or [],
        "mcp_sidecars": SKILL_RUNTIME_CONFIG.get("mcpSidecars") or [],
        "capabilities": runtime_capabilities(),
    }


@app.get("/capabilities")
def capabilities() -> dict[str, Any]:
    return {
        "runtime": "opencode",
        "service": SERVICE_NAME,
        "capabilities": runtime_capabilities(),
    }


@app.post("/invoke", response_model=InvokeResponse)
def invoke(request: InvokeRequest) -> InvokeResponse:
    return invoke_opencode(request)


@app.post("/cancel")
def cancel_session(thread_id: str | None = None) -> dict[str, Any]:
    """Cancel/abort a running session by thread_id.

    Called by the operator when a workflow step times out, to prevent
    orphaned sessions from continuing to run in the background.
    """
    if not thread_id:
        raise HTTPException(status_code=400, detail="thread_id query parameter is required")
    session_id = SESSION_REGISTRY.get(thread_id)
    if session_id is None:
        raise HTTPException(status_code=404, detail=f"No session found for thread_id '{thread_id}'")
    aborted = abort_session(session_id)
    if aborted:
        return {"status": "cancelled", "session_id": session_id, "thread_id": thread_id}
    return {"status": "cancel_failed", "session_id": session_id, "thread_id": thread_id}


@app.get("/context-budget")
def context_budget(thread_id: str | None = None) -> dict[str, Any]:
    """Return context budget telemetry for the given thread."""
    if not thread_id:
        raise HTTPException(status_code=400, detail="thread_id query parameter is required")
    session_id = SESSION_REGISTRY.get(thread_id)
    if session_id is None:
        raise HTTPException(status_code=404, detail=f"No session found for thread_id '{thread_id}'")
    try:
        messages = get_session_messages(session_id)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Failed to fetch session messages: {exc}") from exc
    latest = get_latest_assistant_payload(messages) if messages else None
    budget = compute_context_budget(latest or {})
    budget["session_id"] = session_id
    budget["thread_id"] = thread_id
    budget["compaction_available"] = budget.get("status") in ("warning", "critical")
    return budget


@app.post("/invoke/stream")
async def invoke_stream(request: InvokeRequest) -> StreamingResponse:
    async def event_generator() -> AsyncIterator[str]:
        thread_id = request.thread_id or str(uuid.uuid4())
        streamed_delta_count = 0
        yield sse_event("response.started", {"thread_id": thread_id, "source": "opencode"})

        # Use a thread-safe queue so invoke_opencode_streaming can push
        # per-turn events from its synchronous thread.
        event_queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
        loop = asyncio.get_event_loop()

        def _stream_callback(event_type: str, data: dict[str, Any]) -> None:
            loop.call_soon_threadsafe(event_queue.put_nowait, {"event": event_type, "data": data})

        def _run_invoke() -> InvokeResponse:
            try:
                return invoke_opencode(request, stream_callback=_stream_callback)
            finally:
                loop.call_soon_threadsafe(event_queue.put_nowait, None)

        task = asyncio.get_event_loop().run_in_executor(None, _run_invoke)

        # Drain per-turn events while invoke is running
        while True:
            item = await event_queue.get()
            if item is None:
                break
            if item.get("event") == "response.delta":
                streamed_delta_count += 1
            yield sse_event(item["event"], item["data"])

        try:
            response = await task
        except HTTPException as exc:
            yield sse_event("response.error", {"thread_id": thread_id, "error": str(exc.detail)})
            return
        except Exception as exc:
            yield sse_event("response.error", {"thread_id": thread_id, "error": str(exc)})
            return

        if response.response and streamed_delta_count == 0:
            yield sse_event("response.delta", {"thread_id": response.thread_id, "delta": response.response, "source": "opencode"})
        yield sse_event(
            "response.completed",
            {
                "thread_id": response.thread_id,
                "response": response.response,
                "model": response.model,
                "status": response.status,
                "approval_name": response.approval_name,
                "a2a": response.a2a,
                "warnings": response.warnings,
                "artifacts": response.artifacts,
                "tool_calls": response.tool_calls,
                "metadata": response.metadata,
            },
        )

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.get("/artifacts/download")
def download_artifact(path: str) -> FileResponse:
    artifact_path = resolve_download_path(path)
    media_type, _encoding = mimetypes.guess_type(artifact_path.name)
    return FileResponse(
        artifact_path,
        media_type=media_type or "application/octet-stream",
        filename=artifact_path.name,
    )


@app.get("/artifacts/list")
def list_artifacts(root: str = "") -> dict[str, Any]:
    """Walk allowed directories and return a flat list of files."""
    allowed_roots = [Path(OPENCODE_WORKDIR).resolve(), Path(HOME_DIR).resolve(), Path("/tmp").resolve()]
    if root:
        target = Path(root).expanduser().resolve()
        if not any(_path_is_within(target, r) for r in allowed_roots):
            raise HTTPException(status_code=400, detail=f"root '{root}' is outside the allowed runtime roots")
        if not target.is_dir():
            raise HTTPException(status_code=404, detail=f"root '{root}' is not a directory")
        walk_roots = [target]
    else:
        walk_roots = [r for r in allowed_roots if r.is_dir()]

    files: list[dict[str, Any]] = []
    seen: set[str] = set()
    for walk_root in walk_roots:
        for dirpath, _dirnames, filenames in os.walk(walk_root):
            dp = Path(dirpath)
            # Skip hidden dirs and common noise
            if any(part.startswith(".") for part in dp.parts[len(walk_root.parts):]):
                continue
            for fname in filenames:
                if fname.startswith("."):
                    continue
                fpath = dp / fname
                posix_path = str(PurePosixPath(fpath))
                if posix_path in seen:
                    continue
                seen.add(posix_path)
                try:
                    stat = fpath.stat()
                except OSError:
                    continue
                files.append({
                    "path": posix_path,
                    "name": fname,
                    "size": stat.st_size,
                    "modified": stat.st_mtime,
                    "directory": str(PurePosixPath(dp)),
                })
                if len(files) >= ARTIFACT_COLLECTION_MAX_FILES:
                    return {"files": files, "truncated": True, "roots": [str(PurePosixPath(r)) for r in walk_roots]}
    return {"files": files, "truncated": False, "roots": [str(PurePosixPath(r)) for r in walk_roots]}


@app.get("/artifacts/zip")
def download_artifacts_zip(root: str = "") -> StreamingResponse:
    """Create a ZIP archive of the workspace and stream it to the client."""
    import io
    import zipfile

    workdir = Path(OPENCODE_WORKDIR).resolve()
    if root:
        target = Path(root).expanduser().resolve()
        if not _path_is_within(target, workdir):
            raise HTTPException(status_code=400, detail=f"root '{root}' is outside the workspace")
        if not target.is_dir():
            raise HTTPException(status_code=404, detail=f"root '{root}' is not a directory")
        walk_root = target
    else:
        walk_root = workdir

    if not walk_root.is_dir():
        raise HTTPException(status_code=404, detail="workspace directory does not exist")

    SKIP_DIRS = {".git", "node_modules", "__pycache__", ".next", ".venv", "venv", "dist", ".cache"}

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        file_count = 0
        for dirpath, dirnames, filenames in os.walk(walk_root):
            # Prune skipped directories in-place
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
            dp = Path(dirpath)
            for fname in filenames:
                if fname.startswith("."):
                    continue
                fpath = dp / fname
                try:
                    stat = fpath.stat()
                except OSError:
                    continue
                # Skip files larger than 50MB
                if stat.st_size > 50 * 1024 * 1024:
                    continue
                arcname = str(fpath.relative_to(walk_root))
                zf.write(fpath, arcname)
                file_count += 1
                if file_count >= 10000:
                    break
            if file_count >= 10000:
                break

    buf.seek(0)
    zip_name = walk_root.name or "workspace"
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{zip_name}.zip"'},
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8080)