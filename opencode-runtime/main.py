from __future__ import annotations

import asyncio
import contextlib
import json
import logging
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
from fastapi.responses import StreamingResponse
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
    "Continue working on the task. Review your progress, fix any errors, "
    "and complete all remaining steps. Verify your work before finishing."
)
COMPACTION_TOKEN_THRESHOLD = float(os.getenv("OPENCODE_COMPACTION_TOKEN_THRESHOLD", "0.75"))
SESSION_ABORT_TIMEOUT_SECONDS = max(float(os.getenv("OPENCODE_ABORT_TIMEOUT_SECONDS", "30")), 5.0)
PLAN_AGENT_PROMPT_THRESHOLD = max(int(os.getenv("OPENCODE_PLAN_THRESHOLD_CHARS", "500")), 100)
SESSION_INIT_ON_CREATE = os.getenv("OPENCODE_SESSION_INIT_ON_CREATE", "true").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}

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
        "The output must be directly parseable by json.loads()."
    ),
    "code": (
        "IMPORTANT: Respond with the requested code only. No markdown code fences "
        "wrapping it. Include code comments where helpful but no explanatory prose "
        "outside the code."
    ),
    "markdown": "Respond in well-formatted Markdown.",
    "text": "Respond in plain text without any special formatting.",
}

AUTONOMY_SYSTEM_PROMPT = (
    "You are an autonomous coding agent. Follow these rules:\n"
    "1. PLAN FIRST: For complex tasks (3+ steps), use todowrite to create a structured plan "
    "before writing any code. Track progress by updating todo status as you work.\n"
    "2. USE NATIVE TOOLS: Use your built-in tools (write, edit, bash, read, glob, grep, "
    "webfetch, websearch, codesearch) for all file and code operations — do NOT rely on "
    "external MCP servers for tasks you can do natively.\n"
    "3. COMPLETE FULLY: Create all necessary files, write all code, install dependencies, "
    "and verify your work. Do not leave tasks partially done.\n"
    "4. HANDLE ERRORS: If you encounter an error, diagnose it, fix it, and retry automatically. "
    "Read error messages carefully and address root causes, not symptoms.\n"
    "5. NO USER INPUT: Do not ask for user input or clarification — make reasonable decisions "
    "and proceed autonomously.\n"
    "6. FILE OPERATIONS: Use write to create files, edit to modify existing files, "
    "bash to run commands and install dependencies.\n"
    "7. VERIFY WORK: After creating or modifying files, verify by reading them back, "
    "running the code, or executing tests. Fix issues before marking tasks complete.\n"
    "8. DELEGATE SUBTASKS: For complex multi-part work, use the task tool to delegate "
    "independent subtasks to parallel sub-agents.\n"
    "9. SEARCH BEFORE WRITING: Use glob, grep, and codesearch to understand existing code "
    "before making changes. Understand the codebase structure first.\n"
    "10. SUMMARIZE: Summarize what you accomplished in your final response, including "
    "files created/modified and any remaining issues."
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
    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.Lock()
        self._cache: dict[str, str] | None = None

    def _load(self) -> dict[str, str]:
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
        self._cache = {str(key): str(value) for key, value in payload.items()}
        return dict(self._cache)

    def get(self, thread_id: str) -> str | None:
        with self._lock:
            return self._load().get(thread_id)

    def set(self, thread_id: str, session_id: str) -> None:
        with self._lock:
            payload = self._load()
            payload[thread_id] = session_id
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8")
            self._cache = payload

    def get_or_set(self, thread_id: str, session_id: str) -> str:
        """Atomically return an existing session or register *session_id*.

        If another thread registered a session between the caller's
        ``get()`` and ``set()`` calls, the already-registered session
        wins and the caller's *session_id* is discarded.
        """
        with self._lock:
            payload = self._load()
            existing = payload.get(thread_id)
            if existing:
                return existing
            payload[thread_id] = session_id
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8")
            self._cache = payload
            return session_id


SESSION_REGISTRY = SessionRegistry(SESSION_MAP_PATH)


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


def sse_event(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def combine_system_prompt(*parts: str | None) -> str | None:
    rendered = [str(item).strip() for item in parts if str(item or "").strip()]
    if not rendered:
        return None
    return "\n\n".join(rendered)


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
            "retryCount": request.structured_output_retry_count,
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


def summarize_session(session_id: str) -> bool:
    """Trigger compaction/summarization of a session to free context space."""
    try:
        with runtime_http_client() as hclient:
            response = hclient.post(f"/session/{session_id}/summarize")
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
            total = (tokens.get("input") or 0) + (tokens.get("output") or 0) + (tokens.get("cache", {}).get("read") or 0)
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
    """Extract file artifacts from tool parts (write, edit) and patch parts."""
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
    structured_output_retry_count: int = Field(default=STRUCTURED_OUTPUT_RETRY_COUNT, ge=0, le=10)
    max_retries: int | None = Field(default=None, ge=0, le=10)
    autonomous: bool = True

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
            SESSION_REGISTRY.get_or_set(logical_thread_id, session_id)
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


def _build_response_metadata(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Extract metadata (tokens, cost, timing) from the OpenCode response."""
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
    return metadata or None


def invoke_opencode(request: InvokeRequest) -> InvokeResponse:
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
    system_prompt = combine_system_prompt(
        AUTONOMY_SYSTEM_PROMPT if request.autonomous else None,
        DEFAULT_SYSTEM_PROMPT,
        request.system,
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
    compaction_triggered = False

    # Select agent: use plan for complex first prompts, then build
    current_agent = select_agent_for_prompt(request.prompt, is_first_turn=True) if request.autonomous else DEFAULT_AGENT
    if current_agent == "plan" and current_agent != DEFAULT_AGENT:
        all_warnings.append("Using plan agent for initial analysis before execution.")

    for turn in range(effective_max_turns):
        use_system = system_prompt if turn == 0 else None
        try:
            session_id, payload = _send_prompt_with_session_recovery(
                session_id=session_id,
                prompt=current_prompt,
                model=selected_model,
                system_prompt=use_system,
                prompt_format=prompt_format if turn == 0 else None,
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
            all_warnings.append(
                f"Turn {turn + 1}: HTTP error '{exc}', retrying ({retries_used}/{max_retries})"
            )
            # Preserve the original prompt so the retry does not lose
            # context; only prepend a short recovery note.
            recovery_note = (
                f"[Note: the previous request encountered a transient error ({type(exc).__name__}). "
                f"Continue from where you left off.]\n\n"
            )
            current_prompt = truncate_text(
                f"{recovery_note}{current_prompt}", MAX_PROMPT_CHARS
            )
            continue

        last_payload = payload
        completion = detect_completion_status(payload)

        # After plan agent completes, switch to build agent for execution
        if current_agent == "plan" and completion in ("completed", "incomplete"):
            current_agent = DEFAULT_AGENT
            if completion == "completed":
                all_warnings.append("Plan phase completed, switching to build agent for execution.")
                current_prompt = (
                    "Now execute the plan you just created. Follow the steps "
                    "exactly, creating all files and running all commands. "
                    "Update the todo list as you complete each step."
                )
                continue

        # Handle context overflow — trigger compaction and retry
        if completion == "context_overflow" and not compaction_triggered:
            compaction_triggered = True
            if summarize_session(session_id):
                all_warnings.append(f"Turn {turn + 1}: context overflow detected, triggered compaction.")
                wait_for_session_idle(session_id, timeout_seconds=SESSION_ABORT_TIMEOUT_SECONDS)
                current_prompt = (
                    "The context was compacted due to overflow. Continue working on the "
                    "task from where you left off. Check what has been done and complete "
                    "any remaining steps."
                )
                continue
            all_warnings.append(f"Turn {turn + 1}: context overflow, compaction failed.")

        # Proactive compaction — if token usage is high, compact before overflow
        if not compaction_triggered and check_context_overflow(payload):
            compaction_triggered = True
            if summarize_session(session_id):
                all_warnings.append(f"Turn {turn + 1}: proactively triggered compaction (token usage high).")
                wait_for_session_idle(session_id, timeout_seconds=SESSION_ABORT_TIMEOUT_SECONDS)
                current_prompt = (
                    "Context was proactively compacted to free space. "
                    "Continue working on your task from where you left off."
                )
                continue

        if completion == "completed":
            break

        if completion == "error":
            error_type = classify_error_type(payload)
            if error_type == "context_overflow" and not compaction_triggered:
                compaction_triggered = True
                if summarize_session(session_id):
                    all_warnings.append(f"Turn {turn + 1}: context overflow error, compacting.")
                    wait_for_session_idle(session_id, timeout_seconds=SESSION_ABORT_TIMEOUT_SECONDS)
                    current_prompt = (
                        "Context was compacted. Continue the task from where you left off."
                    )
                    continue
            if error_type == "structured_output" and retries_used < max_retries:
                retries_used += 1
                all_warnings.append(
                    f"Turn {turn + 1}: structured output validation failed, retrying ({retries_used}/{max_retries})"
                )
                current_prompt = (
                    "Your previous response did not satisfy the required JSON schema. "
                    "Produce ONLY valid structured output that matches the schema exactly."
                )
                continue
            if error_type == "auth":
                all_warnings.append(f"Turn {turn + 1}: authentication error, cannot retry.")
                break
            if retries_used < max_retries:
                retries_used += 1
                all_warnings.append(f"Turn {turn + 1}: agent error ({error_type or 'unknown'}), retrying ({retries_used}/{max_retries})")
                current_prompt = (
                    "The previous step encountered an error. Review what went wrong, "
                    "fix the issues, and complete the task."
                )
                continue
            break

        if completion == "incomplete" and turn + 1 < effective_max_turns:
            all_warnings.append(f"Turn {turn + 1}: task incomplete, sending continuation prompt")
            current_prompt = AUTONOMY_CONTINUATION_PROMPT
            continue

        # Exhausted retries or turns
        break

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
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
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
    return {
        "status": "healthy" if _runtime_ready else "starting",
        "runtime": "opencode",
        "service": SERVICE_NAME,
        "namespace": SERVICE_NAMESPACE,
        "provider": DEFAULT_PROVIDER,
        "agent": DEFAULT_AGENT,
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
    return {
        "status": "ready",
        "runtime": "opencode",
        "opencode_binary": OPENCODE_BIN,
        "opencode_binary_path": resolved_binary,
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


@app.post("/invoke/stream")
async def invoke_stream(request: InvokeRequest) -> StreamingResponse:
    async def event_generator() -> AsyncIterator[str]:
        thread_id = request.thread_id or str(uuid.uuid4())
        yield sse_event("response.started", {"thread_id": thread_id, "source": "opencode"})
        try:
            response = await asyncio.to_thread(invoke_opencode, request)
        except HTTPException as exc:
            yield sse_event("response.error", {"thread_id": thread_id, "error": str(exc.detail)})
            return
        if response.response:
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


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8080)