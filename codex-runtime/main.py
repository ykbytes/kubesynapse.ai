"""Codex Runtime Adapter – HTTP adapter that exposes Codex as an agent runtime
behind the Kubemininions sandbox gateway.

Provides the same ``/invoke``, ``/invoke/stream``, ``/health``, and ``/ready``
contract expected by the operator worker so AgentWorkflow steps can invoke Codex
agents identically to LangGraph and Goose agents.

Communication with Codex CLI is done through the Python SDK's
``CodexClient`` which speaks JSON-RPC over stdio to
``codex app-server``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import threading
import tomllib
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, model_validator

try:
    from codex_app_server_sdk.client import CodexClient, ThreadConfig, TurnOverrides  # type: ignore[import-not-found]
    from codex_app_server_sdk.errors import (  # type: ignore[import-not-found]
        CodexProtocolError,
        CodexTimeoutError,
        CodexTransportError,
        CodexTurnInactiveError,
    )
except ModuleNotFoundError as exc:  # pragma: no cover
    CodexClient = None  # type: ignore[assignment]
    ThreadConfig = None  # type: ignore[assignment]
    TurnOverrides = None  # type: ignore[assignment]
    CodexProtocolError = Exception  # type: ignore[assignment]
    CodexTimeoutError = Exception  # type: ignore[assignment]
    CodexTransportError = Exception  # type: ignore[assignment]
    CodexTurnInactiveError = Exception  # type: ignore[assignment]
    CODEX_SDK_IMPORT_ERROR: ModuleNotFoundError | None = exc
else:  # pragma: no cover
    CODEX_SDK_IMPORT_ERROR = None

try:
    import yaml
except ModuleNotFoundError:  # pragma: no cover
    yaml = None

try:
    from pythonjsonlogger import jsonlogger as _jsonlogger  # type: ignore[import-untyped]
except ModuleNotFoundError:  # pragma: no cover
    _jsonlogger = None

try:
    from prometheus_fastapi_instrumentator import Instrumentator as _Instrumentator  # type: ignore[import-untyped]
except ModuleNotFoundError:  # pragma: no cover
    _Instrumentator = None

try:
    import tomli_w
except ModuleNotFoundError:  # pragma: no cover
    tomli_w = None


# ---------------------------------------------------------------------------
# Environment helpers
# ---------------------------------------------------------------------------

def get_int_env(name: str, default: int, *, minimum: int = 1) -> int:
    raw_value = os.getenv(name, "").strip()
    if not raw_value:
        return max(default, minimum)
    try:
        return max(int(raw_value), minimum)
    except ValueError:
        return max(default, minimum)


def get_float_env(name: str, default: float, *, minimum: float = 0.1) -> float:
    raw_value = os.getenv(name, "").strip()
    if not raw_value:
        return max(default, minimum)
    try:
        return max(float(raw_value), minimum)
    except ValueError:
        return max(default, minimum)


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------


def _configure_logging() -> None:
    log_level = os.getenv("CODEX_RUNTIME_LOG_LEVEL", "INFO").upper()
    handler = logging.StreamHandler()
    if os.getenv("JSON_LOGS", "true").lower() in {"1", "true"} and _jsonlogger is not None:
        handler.setFormatter(_jsonlogger.JsonFormatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    else:
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    logging.basicConfig(level=log_level, handlers=[handler], force=True)


_configure_logging()
logger = logging.getLogger("codex-runtime")
_SHUTDOWN = threading.Event()

# ---------------------------------------------------------------------------
# A2A helpers (shared with goose-runtime pattern)
# ---------------------------------------------------------------------------

K8S_NAME_RE = re.compile(r"^[a-z0-9]([-a-z0-9]*[a-z0-9])?$")


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


def parse_a2a_peer_refs(value: Any, *, source: str) -> list[dict[str, str]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"{source} must be a list of peer reference objects")

    normalized: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for index, item in enumerate(value):
        peer_ref = parse_a2a_peer_ref(item, source=f"{source}[{index}]")
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


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

SERVICE_NAME = os.getenv("AGENT_NAME", "codex-runtime")
SERVICE_NAMESPACE = os.getenv("AGENT_NAMESPACE", "default")
DEFAULT_MODEL = os.getenv("CODEX_MODEL", os.getenv("AGENT_MODEL", "gpt-4"))
DEFAULT_PROVIDER = os.getenv("CODEX_PROVIDER", "litellm").strip() or "litellm"
DEFAULT_SYSTEM_PROMPT = os.getenv("CODEX_SYSTEM_PROMPT", os.getenv("AGENT_SYSTEM_PROMPT", "")).strip()
CODEX_BINARY = os.getenv("CODEX_BIN", "codex").strip() or "codex"
CODEX_WORKDIR = os.getenv("CODEX_WORKDIR", "/workspace").strip() or "/workspace"
HOME_DIR = os.getenv("HOME", "/app/state/home").strip() or "/app/state/home"
CODEX_HOME = os.getenv("CODEX_HOME", f"{HOME_DIR}/.codex").strip() or f"{HOME_DIR}/.codex"
XDG_CONFIG_HOME = os.getenv("XDG_CONFIG_HOME", f"{HOME_DIR}/.config").strip() or f"{HOME_DIR}/.config"
XDG_DATA_HOME = os.getenv("XDG_DATA_HOME", f"{HOME_DIR}/.local/share").strip() or f"{HOME_DIR}/.local/share"

MAX_PROMPT_CHARS = get_int_env("CODEX_MAX_PROMPT_CHARS", 12000)
MAX_THREAD_ID_CHARS = get_int_env("CODEX_MAX_THREAD_ID_CHARS", 128)
MAX_MODEL_CHARS = get_int_env("CODEX_MAX_MODEL_CHARS", 128)
MAX_SYSTEM_PROMPT_CHARS = get_int_env("CODEX_MAX_SYSTEM_PROMPT_CHARS", 4000)
COMMAND_TIMEOUT_SECONDS = get_float_env("CODEX_COMMAND_TIMEOUT_SECONDS", 600.0)

# LiteLLM proxy URL assembled from operator-injected env
LITELLM_HOST = os.getenv("LITELLM_HOST", "").strip()
LITELLM_API_KEY = os.getenv("LITELLM_API_KEY", "").strip()

# A2A
A2A_ALLOWED_CALLERS = parse_a2a_peer_refs_env("A2A_ALLOWED_CALLERS_JSON")

# Skill files
SKILL_FILES_ENV = "AGENT_SKILL_FILES_JSON"
SKILLS_ROOT = os.getenv("AGENT_SKILLS_ROOT", "/app/state/skills").strip() or "/app/state/skills"
MAX_AGENT_SKILL_FILES = get_int_env("AGENT_MAX_SKILL_FILES", 24, minimum=1)
MAX_AGENT_SKILL_FILE_PATH_CHARS = get_int_env("AGENT_MAX_SKILL_FILE_PATH_CHARS", 256, minimum=32)
MAX_AGENT_SKILL_FILE_CONTENT_CHARS = get_int_env("AGENT_MAX_SKILL_FILE_CONTENT_CHARS", 16000, minimum=512)
MAX_AGENT_SKILL_TOTAL_CHARS = get_int_env("AGENT_MAX_SKILL_TOTAL_CHARS", 64000, minimum=4096)
MAX_AGENT_SKILL_PROMPT_CHARS = get_int_env("AGENT_MAX_SKILL_PROMPT_CHARS", 16000, minimum=512)

# Codex-specific config files
CODEX_RUNTIME_CONFIG_FILES_ENV = "CODEX_RUNTIME_CONFIG_FILES_JSON"
CODEX_MCP_SIDECARS_ENV = "CODEX_MCP_SIDECARS_JSON"
CODEX_AUTH_JSON_ENV = "CODEX_AUTH_JSON"

# Runtime state
_runtime_ready = False


# ---------------------------------------------------------------------------
# Skill file handling
# ---------------------------------------------------------------------------

def dedupe_items(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def normalize_skill_file_path(raw_path: object) -> str:
    normalized_path = str(raw_path).replace("\\", "/").strip()
    if not normalized_path:
        raise RuntimeError("Skill file paths must not be blank")
    if len(normalized_path) > MAX_AGENT_SKILL_FILE_PATH_CHARS:
        raise RuntimeError(f"Skill file paths must be {MAX_AGENT_SKILL_FILE_PATH_CHARS} characters or fewer")
    if normalized_path.startswith("/"):
        raise RuntimeError("Skill file paths must be relative")

    parts = [part for part in normalized_path.split("/") if part]
    if not parts or any(part in {".", ".."} for part in parts):
        raise RuntimeError(f"Skill file path '{raw_path}' is invalid")

    candidate = "/".join(parts)
    if not candidate.lower().endswith(".md"):
        raise RuntimeError(f"Skill file path '{candidate}' must end in .md")
    return candidate


def split_skill_frontmatter(content: str) -> tuple[str | None, str, str | None]:
    normalized = str(content or "").replace("\r\n", "\n")
    if not normalized.startswith("---\n"):
        return None, normalized, None
    lines = normalized.split("\n")
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            return "\n".join(lines[1:index]), "\n".join(lines[index + 1:]), None
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
        return {}, [f"Skill frontmatter is invalid: {exc}"]
    if parsed is None:
        return {}, warnings
    if not isinstance(parsed, dict):
        return {}, ["Skill frontmatter must be a YAML or JSON object"]
    return parsed, warnings


def truncate_text(value: str, limit: int = 1200) -> str:
    value = value.strip()
    if len(value) <= limit:
        return value
    return f"{value[:limit].rstrip()}..."


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

    return {
        "path": path,
        "name": str(raw_name or infer_skill_name(path)).strip() or infer_skill_name(path),
        "description": str(raw_description or "").strip() or None,
        "body": str(body or "").strip(),
        "warnings": dedupe_items(warnings),
    }


def render_skill_prompt(skills: list[dict[str, Any]]) -> str:
    if not skills:
        return ""
    sections = [
        "The following file-backed skills are available. Use their guidance when relevant.",
    ]
    for skill in skills:
        lines = [f"Skill: {skill.get('name')}"]
        if skill.get("description"):
            lines.append(f"Description: {skill.get('description')}")
        if skill.get("body"):
            lines.append("Instructions:")
            lines.append(str(skill.get("body") or ""))
        sections.append("\n".join(lines).strip())
    return truncate_text("\n\n".join(section for section in sections if section.strip()), MAX_AGENT_SKILL_PROMPT_CHARS)


def load_skill_files() -> tuple[list[dict[str, Any]], list[str]]:
    raw_value = os.getenv(SKILL_FILES_ENV, "").strip()
    if not raw_value:
        return [], []

    try:
        parsed = json.loads(raw_value)
    except ValueError as exc:
        warning = f"Ignoring invalid {SKILL_FILES_ENV} value: {exc}"
        logger.warning(warning)
        return [], [warning]

    if not isinstance(parsed, dict):
        warning = f"Ignoring invalid {SKILL_FILES_ENV} value: expected a JSON object"
        logger.warning(warning)
        return [], [warning]

    skills: list[dict[str, Any]] = []
    warnings: list[str] = []
    total_chars = 0
    for raw_path, raw_content in sorted(parsed.items(), key=lambda item: str(item[0])):
        try:
            path = normalize_skill_file_path(raw_path)
        except RuntimeError as exc:
            warnings.append(str(exc))
            continue
        content = str(raw_content or "").strip()
        if not content:
            continue
        if len(content) > MAX_AGENT_SKILL_FILE_CONTENT_CHARS:
            warnings.append(f"Skill file '{path}' exceeds {MAX_AGENT_SKILL_FILE_CONTENT_CHARS} characters")
            continue
        total_chars += len(content)
        if total_chars > MAX_AGENT_SKILL_TOTAL_CHARS:
            warnings.append(f"Total skill content exceeds {MAX_AGENT_SKILL_TOTAL_CHARS} characters; skipping remaining files")
            break
        if len(skills) >= MAX_AGENT_SKILL_FILES:
            warnings.append(f"Maximum of {MAX_AGENT_SKILL_FILES} skill files reached; skipping remaining files")
            break
        skills.append(parse_skill_definition(path, content))
        warnings.extend(skills[-1].get("warnings", []))

    return skills, warnings


def materialize_skill_files(skills: list[dict[str, Any]]) -> list[str]:
    root = Path(SKILLS_ROOT)
    root.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    for skill in skills:
        path = skill.get("path", "")
        body = skill.get("body", "")
        if path and body:
            target = root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(body.rstrip("\n") + "\n", encoding="utf-8")
            written.append(path)
    return written


# ---------------------------------------------------------------------------
# Codex config files
# ---------------------------------------------------------------------------

def parse_json_object_env(name: str) -> dict[str, Any]:
    raw_value = os.getenv(name, "").strip()
    if not raw_value:
        return {}
    try:
        parsed = json.loads(raw_value)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{name} must contain valid JSON") from exc
    if not isinstance(parsed, dict):
        raise RuntimeError(f"{name} must decode to a JSON object")
    return parsed


def materialize_codex_config_files() -> list[str]:
    config_root = Path(CODEX_HOME)
    config_root.mkdir(parents=True, exist_ok=True)
    config_root = config_root.resolve()

    raw_files = parse_json_object_env(CODEX_RUNTIME_CONFIG_FILES_ENV)
    written_files: list[str] = []
    for raw_relative_path, raw_content in sorted(raw_files.items(), key=lambda item: str(item[0])):
        normalized_path = str(raw_relative_path).replace("\\", "/").strip()
        if not normalized_path or normalized_path.startswith("/"):
            continue
        parts = [part for part in normalized_path.split("/") if part]
        if not parts or any(part in {".", ".."} for part in parts):
            continue
        resolved = (config_root / Path(*parts)).resolve()
        try:
            resolved.relative_to(config_root)
        except ValueError:
            continue
        resolved.parent.mkdir(parents=True, exist_ok=True)
        content = raw_content if isinstance(raw_content, str) else json.dumps(raw_content, ensure_ascii=False, indent=2)
        resolved.write_text(content.rstrip("\n") + "\n", encoding="utf-8")
        written_files.append(resolved.relative_to(config_root).as_posix())

    return written_files


def materialize_codex_auth_file() -> str | None:
    raw_value = os.getenv(CODEX_AUTH_JSON_ENV, "").strip()
    if not raw_value:
        return None

    try:
        parsed = json.loads(raw_value)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{CODEX_AUTH_JSON_ENV} must contain valid JSON") from exc
    if not isinstance(parsed, dict):
        raise RuntimeError(f"{CODEX_AUTH_JSON_ENV} must decode to a JSON object")

    codex_home = Path(CODEX_HOME)
    codex_home.mkdir(parents=True, exist_ok=True)
    auth_path = codex_home / "auth.json"
    auth_path.write_text(json.dumps(parsed, ensure_ascii=False, indent=2).rstrip("\n") + "\n", encoding="utf-8")
    return auth_path.relative_to(codex_home).as_posix()


def load_codex_sidecars() -> list[dict[str, Any]]:
    raw_value = os.getenv(CODEX_MCP_SIDECARS_ENV, "").strip()
    if not raw_value:
        return []
    try:
        parsed = json.loads(raw_value)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{CODEX_MCP_SIDECARS_ENV} must contain valid JSON") from exc
    if not isinstance(parsed, list):
        raise RuntimeError(f"{CODEX_MCP_SIDECARS_ENV} must decode to a JSON array")

    sidecars: list[dict[str, Any]] = []
    seen_names: set[str] = set()
    for index, item in enumerate(parsed):
        if not isinstance(item, dict):
            raise RuntimeError(f"{CODEX_MCP_SIDECARS_ENV}[{index}] must be an object")

        name = str(item.get("name", "")).strip()
        if not name:
            raise RuntimeError(f"{CODEX_MCP_SIDECARS_ENV}[{index}].name must not be blank")
        if not K8S_NAME_RE.fullmatch(name):
            raise RuntimeError(f"{CODEX_MCP_SIDECARS_ENV}[{index}].name must be a valid lowercase identifier")

        raw_port = item.get("port", 8080)
        try:
            port = int(raw_port)
        except (TypeError, ValueError) as exc:
            raise RuntimeError(f"{CODEX_MCP_SIDECARS_ENV}[{index}].port must be an integer") from exc
        if port < 1 or port > 65535:
            raise RuntimeError(f"{CODEX_MCP_SIDECARS_ENV}[{index}].port must be between 1 and 65535")
        if name in seen_names:
            continue

        seen_names.add(name)
        sidecars.append({"name": name, "port": port})

    return sidecars


def materialize_codex_mcp_config(sidecars: list[dict[str, Any]]) -> str | None:
    if not sidecars:
        return None
    if tomli_w is None:
        raise RuntimeError("tomli-w is required to write Codex MCP config")

    config_root = Path(CODEX_HOME)
    config_root.mkdir(parents=True, exist_ok=True)
    config_root = config_root.resolve()
    config_path = config_root / "config.toml"

    config_data: dict[str, Any] = {}
    if config_path.exists():
        try:
            parsed = tomllib.loads(config_path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise RuntimeError(f"Failed to parse Codex config.toml: {exc}") from exc
        if not isinstance(parsed, dict):
            raise RuntimeError("Codex config.toml must contain a TOML table at the top level")
        config_data = dict(parsed)

    raw_servers = config_data.get("mcp_servers")
    if raw_servers is None:
        mcp_servers: dict[str, Any] = {}
    elif isinstance(raw_servers, dict):
        mcp_servers = dict(raw_servers)
    else:
        raise RuntimeError("Codex config.toml mcp_servers must be a table")

    for sidecar in sidecars:
        mcp_servers[sidecar["name"]] = {
            "url": f"http://127.0.0.1:{sidecar['port']}/mcp",
        }

    config_data["mcp_servers"] = mcp_servers
    config_path.write_text(tomli_w.dumps(config_data), encoding="utf-8")
    return config_path.relative_to(config_root).as_posix()


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

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

    @model_validator(mode="after")
    def validate_request(self) -> "InvokeRequest":
        self.prompt = self.prompt.strip()
        self.thread_id = self.thread_id.strip() or None if self.thread_id is not None else None
        self.model = self.model.strip() or None if self.model is not None else None
        self.system = self.system.strip() or None if self.system is not None else None
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

        if not self.prompt:
            raise ValueError("prompt must not be blank")
        if self.require_approval:
            raise ValueError("codex runtime does not support require_approval; use workflow-level approval gates")
        if self.tool_name:
            raise ValueError("codex runtime does not support direct tool_name execution")
        if self.mcp_server:
            raise ValueError("codex runtime does not support gateway-routed mcp_server execution")
        if self.a2a_target_agent or self.a2a_target_namespace or self.a2a_timeout_seconds is not None:
            raise ValueError("codex runtime does not support outbound A2A invocation")
        if self.sandbox_session is not None:
            raise ValueError("codex runtime does not support sandbox_session continuity")
        if self.caller_agent_name or self.caller_agent_namespace:
            if not self.caller_agent_name or not self.caller_agent_namespace:
                raise ValueError("caller_agent_name and caller_agent_namespace must be provided together")
            normalize_a2a_identifier(self.caller_agent_name, source="caller_agent_name")
            normalize_a2a_identifier(self.caller_agent_namespace, source="caller_agent_namespace")
            if A2A_ALLOWED_CALLERS and (
                self.caller_agent_namespace,
                self.caller_agent_name,
            ) not in A2A_ALLOWED_CALLERS:
                raise ValueError("caller agent is not permitted to invoke this codex runtime")
        if self.no_session and self.thread_id:
            raise ValueError("thread_id cannot be used when no_session is enabled")
        return self


class InvokeResponse(BaseModel):
    thread_id: str
    response: str
    model: str
    status: str = "completed"
    a2a: dict[str, Any] | None = None
    warnings: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Codex SDK integration
# ---------------------------------------------------------------------------

def build_system_prompt(request: InvokeRequest, skill_prompt: str) -> str:
    parts: list[str] = []
    base = request.system or DEFAULT_SYSTEM_PROMPT
    if base:
        parts.append(base)
    if skill_prompt:
        parts.append(skill_prompt)
    return "\n\n".join(parts)


def validate_runtime_startup() -> None:
    if CODEX_SDK_IMPORT_ERROR is not None:
        raise RuntimeError(
            "codex_app_server SDK is not installed in the runtime image"
        ) from CODEX_SDK_IMPORT_ERROR

    binary_path = Path(CODEX_BINARY)
    if binary_path.is_absolute():
        if not binary_path.exists() or not os.access(binary_path, os.X_OK):
            raise RuntimeError(f"Codex binary '{CODEX_BINARY}' is not executable")
        return

    if shutil.which(CODEX_BINARY) is None:
        raise RuntimeError(f"Codex binary '{CODEX_BINARY}' was not found on PATH")


def run_codex_turn(
    prompt: str,
    *,
    thread_id: str | None,
    model: str,
    system_prompt: str,
    working_directory: str,
    timeout_seconds: float,
) -> dict[str, Any]:
    """Execute a single Codex turn using the installed Codex SDK."""

    async def _run_turn() -> dict[str, Any]:
        if CodexClient is None or ThreadConfig is None or TurnOverrides is None:
            raise RuntimeError("codex_app_server SDK is unavailable")

        env_overrides: dict[str, str] = {"CODEX_HOME": CODEX_HOME}
        if DEFAULT_PROVIDER.lower() == "litellm" and LITELLM_HOST:
            env_overrides["OPENAI_BASE_URL"] = LITELLM_HOST
        if DEFAULT_PROVIDER.lower() == "litellm" and LITELLM_API_KEY:
            env_overrides["OPENAI_API_KEY"] = LITELLM_API_KEY

        thread_config_kwargs: dict[str, Any] = {"cwd": working_directory}
        if model:
            thread_config_kwargs["model"] = model
        if DEFAULT_PROVIDER:
            thread_config_kwargs["model_provider"] = DEFAULT_PROVIDER
        if system_prompt:
            thread_config_kwargs["base_instructions"] = system_prompt
        thread_config = ThreadConfig(**thread_config_kwargs)

        turn_override_kwargs: dict[str, Any] = {"cwd": working_directory}
        if model:
            turn_override_kwargs["model"] = model
        turn_overrides = TurnOverrides(**turn_override_kwargs)

        client = CodexClient.connect_stdio(
            command=[CODEX_BINARY, "app-server"],
            cwd=working_directory,
            env=env_overrides or None,
            request_timeout=max(timeout_seconds, 1.0),
            inactivity_timeout=timeout_seconds,
        )

        try:
            client.start()
            if thread_id:
                thread_handle = await client.resume_thread(thread_id, overrides=thread_config)
            else:
                thread_handle = await client.start_thread(thread_config)
            chat_result = await thread_handle.chat_once(
                prompt,
                turn_overrides=turn_overrides,
                inactivity_timeout=timeout_seconds,
            )
        finally:
            client.close()

        return {
            "thread_id": chat_result.thread_id,
            "response": chat_result.final_text.strip() or "(no output)",
            "model": model,
            "status": "completed",
            "warnings": [],
        }

    try:
        return asyncio.run(asyncio.wait_for(_run_turn(), timeout_seconds))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=f"Codex binary not found: {exc}") from exc
    except (TimeoutError, CodexTimeoutError, CodexTurnInactiveError) as exc:
        raise HTTPException(status_code=504, detail="Codex turn exceeded the configured timeout") from exc
    except CodexTransportError as exc:
        logger.error("Codex transport failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=502, detail="Codex transport closed unexpectedly") from exc
    except CodexProtocolError as exc:
        logger.error("Codex app-server request failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=502, detail=f"Codex app-server error: {exc}") from exc
    except Exception as exc:
        logger.error("Codex turn failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Codex execution error: {exc}") from exc


# ---------------------------------------------------------------------------
# Application lifecycle
# ---------------------------------------------------------------------------

SKILL_RUNTIME_CONFIG: dict[str, Any] = {
    "skills": [],
    "prompt": "",
    "warnings": [],
    "skillFiles": [],
    "codexConfigFiles": [],
    "codexAuthFile": None,
}


def ensure_runtime_directories() -> None:
    for path in (CODEX_WORKDIR, HOME_DIR, CODEX_HOME, XDG_CONFIG_HOME, XDG_DATA_HOME, SKILLS_ROOT, "/app/state"):
        os.makedirs(path, exist_ok=True)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    global _runtime_ready

    ensure_runtime_directories()
    validate_runtime_startup()

    skills, skill_warnings = load_skill_files()
    SKILL_RUNTIME_CONFIG["skills"] = skills
    SKILL_RUNTIME_CONFIG["prompt"] = render_skill_prompt(skills)
    SKILL_RUNTIME_CONFIG["warnings"] = skill_warnings
    SKILL_RUNTIME_CONFIG["skillFiles"] = materialize_skill_files(skills)
    codex_config_files = materialize_codex_config_files()
    auth_file = materialize_codex_auth_file()
    sidecars = load_codex_sidecars()
    mcp_config_path = materialize_codex_mcp_config(sidecars)
    if mcp_config_path:
        codex_config_files.append(mcp_config_path)
    SKILL_RUNTIME_CONFIG["codexConfigFiles"] = dedupe_items(codex_config_files)
    SKILL_RUNTIME_CONFIG["codexAuthFile"] = auth_file
    if skill_warnings:
        logger.warning("Loaded skill files with warnings: %s", "; ".join(skill_warnings))
    if auth_file and DEFAULT_PROVIDER.lower() == "litellm":
        logger.warning(
            "%s is configured, but CODEX_PROVIDER=%s. auth.json is only used when Codex authenticates directly; set CODEX_PROVIDER=openai to use auth.json-backed OpenAI or ChatGPT auth.",
            CODEX_AUTH_JSON_ENV,
            DEFAULT_PROVIDER,
        )

    _runtime_ready = True
    try:
        yield
    finally:
        _SHUTDOWN.set()
        _runtime_ready = False
        logger.info("Codex runtime shutting down.")


app = FastAPI(
    title="Codex Runtime Adapter",
    description="HTTP adapter that exposes Codex as an agent runtime behind the sandbox gateway",
    version="0.1.0",
    lifespan=lifespan,
)

if _Instrumentator is not None:
    _Instrumentator().instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "shutting-down" if _SHUTDOWN.is_set() else "ok"}


@app.get("/ready")
async def ready() -> dict[str, str]:
    if _SHUTDOWN.is_set():
        raise HTTPException(status_code=503, detail="Runtime is shutting down")
    if not _runtime_ready:
        raise HTTPException(status_code=503, detail="Runtime not yet initialized")
    return {"status": "ready"}


@app.post("/invoke", response_model=InvokeResponse)
async def invoke(request: InvokeRequest) -> InvokeResponse:
    if _SHUTDOWN.is_set():
        raise HTTPException(status_code=503, detail="Runtime is shutting down. Retry on another pod.")
    model = request.model or DEFAULT_MODEL
    system_prompt = build_system_prompt(request, SKILL_RUNTIME_CONFIG.get("prompt", ""))
    working_directory = request.working_directory or CODEX_WORKDIR

    result = await asyncio.to_thread(
        run_codex_turn,
        request.prompt,
        thread_id=request.thread_id,
        model=model,
        system_prompt=system_prompt,
        working_directory=working_directory,
        timeout_seconds=COMMAND_TIMEOUT_SECONDS,
    )

    return InvokeResponse(
        thread_id=result["thread_id"],
        response=result["response"],
        model=result["model"],
        status=result["status"],
        warnings=result.get("warnings", []),
    )


@app.post("/invoke/stream")
async def invoke_stream(request: InvokeRequest) -> StreamingResponse:
    if _SHUTDOWN.is_set():
        raise HTTPException(status_code=503, detail="Runtime is shutting down. Retry on another pod.")
    model = request.model or DEFAULT_MODEL
    system_prompt = build_system_prompt(request, SKILL_RUNTIME_CONFIG.get("prompt", ""))
    working_directory = request.working_directory or CODEX_WORKDIR

    async def event_generator() -> AsyncIterator[str]:
        def _sse_event(event: str, payload: dict[str, Any]) -> str:
            return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False, default=str)}\n\n"

        try:
            result = await asyncio.to_thread(
                run_codex_turn,
                request.prompt,
                thread_id=request.thread_id,
                model=model,
                system_prompt=system_prompt,
                working_directory=working_directory,
                timeout_seconds=COMMAND_TIMEOUT_SECONDS,
            )
            yield _sse_event("message", {"text": result["response"]})
            yield _sse_event("done", {
                "thread_id": result["thread_id"],
                "model": result["model"],
                "status": result["status"],
            })
        except HTTPException as exc:
            yield _sse_event("error", {"detail": exc.detail})
        except Exception as exc:
            yield _sse_event("error", {"detail": str(exc)})

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.get("/info")
async def info() -> dict[str, Any]:
    return {
        "runtime": "codex",
        "service_name": SERVICE_NAME,
        "service_namespace": SERVICE_NAMESPACE,
        "model": DEFAULT_MODEL,
        "provider": DEFAULT_PROVIDER,
        "codex_binary": CODEX_BINARY,
        "working_directory": CODEX_WORKDIR,
        "skills_loaded": len(SKILL_RUNTIME_CONFIG.get("skills", [])),
    }
