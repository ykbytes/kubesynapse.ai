import asyncio
import contextlib
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextvars import ContextVar
import hashlib
import json
import logging
import os
import re
import shutil
import sqlite3
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
MODEL_NAME = os.getenv("AGENT_MODEL", "gpt-4")
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
MCP_HUB_NAMESPACE = os.getenv("MCP_HUB_NAMESPACE", "mcp-hub").strip()
_raw_allowed = os.getenv("ALLOWED_MCP_SERVERS", "").strip()
ALLOWED_MCP_SERVERS: frozenset[str] = frozenset(s.strip() for s in _raw_allowed.split(",") if s.strip())
A2A_ALLOWED_CALLERS = parse_a2a_peer_refs_env("A2A_ALLOWED_CALLERS_JSON")
A2A_ALLOWED_TARGETS_SNAPSHOT = parse_a2a_peer_refs_env("A2A_ALLOWED_TARGETS_JSON")
A2A_REQUIRE_HITL_DEFAULT = get_bool_env("A2A_REQUIRE_HITL", False)
A2A_MAX_TIMEOUT_SECONDS = get_float_env("A2A_MAX_TIMEOUT_SECONDS", 60.0, minimum=1.0)
API_GATEWAY_INTERNAL_URL = os.getenv("API_GATEWAY_INTERNAL_URL", "").strip().rstrip("/")
API_GATEWAY_SHARED_TOKEN = os.getenv("API_GATEWAY_SHARED_TOKEN", "").strip()
TEAM_CONTEXT_MAX_CHARS = get_int_env("A2A_TEAM_CONTEXT_MAX_CHARS", 4096, minimum=256)
TEAMWORK_WORKING_AGREEMENT = (
    "Treat this request as one delegated step in a multi-agent workflow.",
    "Do the subtask directly and return concrete findings or next actions.",
    "Call out blockers, uncertainties, or missing inputs explicitly instead of guessing.",
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
SKILL_FILES_ENV = "AGENT_SKILL_FILES_JSON"
SKILLS_ROOT = os.getenv("AGENT_SKILLS_ROOT", "/app/state/skills").strip() or "/app/state/skills"
MAX_AGENT_SKILL_FILES = get_int_env("AGENT_MAX_SKILL_FILES", 24, minimum=1)
MAX_AGENT_SKILL_FILE_PATH_CHARS = get_int_env("AGENT_MAX_SKILL_FILE_PATH_CHARS", 256, minimum=32)
MAX_AGENT_SKILL_FILE_CONTENT_CHARS = get_int_env("AGENT_MAX_SKILL_FILE_CONTENT_CHARS", 16000, minimum=512)
MAX_AGENT_SKILL_TOTAL_CHARS = get_int_env("AGENT_MAX_SKILL_TOTAL_CHARS", 64000, minimum=4096)
MAX_AGENT_SKILL_PROMPT_CHARS = get_int_env("AGENT_MAX_SKILL_PROMPT_CHARS", 16000, minimum=512)
BLOCKED_RESPONSE_PREFIX = "Request blocked"
SENSITIVE_STREAM_EVENT_SUFFIXES = (".stdout", ".stderr", ".result")


def build_thread_id(prefix: str, *parts: object, max_length: int = MAX_THREAD_ID_CHARS) -> str:
    normalized_parts = [re.sub(r"[^a-zA-Z0-9_-]+", "-", str(part).strip()).strip("-_") for part in parts if str(part).strip()]
    normalized_parts = [part for part in normalized_parts if part]
    base = "-".join([prefix, *normalized_parts])
    if len(base) <= max_length:
        return base

    digest = hashlib.sha1(base.encode("utf-8")).hexdigest()[:10]
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


def normalize_json_object(value: Any, *, field_name: str, max_chars: int) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError(f"{field_name} must be an object when provided")

    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    if len(encoded) > max_chars:
        raise ValueError(f"{field_name} exceeds {max_chars} characters once serialized")

    normalized = json.loads(encoded)
    if not isinstance(normalized, dict):
        raise ValueError(f"{field_name} must serialize to an object")
    return normalized


def normalize_subagent_strategy(value: Any) -> str:
    strategy = str(value or "sequential").strip().lower() or "sequential"
    if strategy not in SUBAGENT_STRATEGIES:
        raise ValueError(
            f"subagent_strategy must be one of {', '.join(sorted(SUBAGENT_STRATEGIES))}"
        )
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
        raise ValueError(
            f"{source} must be {MAX_AGENT_SKILL_FILE_PATH_CHARS} characters or fewer"
        )
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
            warnings.append(
                f"{SKILL_FILES_ENV}.{path} exceeds {MAX_AGENT_SKILL_FILE_CONTENT_CHARS} characters"
            )
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
        sandbox_patterns.update(str(item).strip() for item in (skill.get("allowedSandboxTools") or []) if str(item).strip())
        allowed_mcp_servers.update(str(item).strip() for item in (skill.get("allowedMcpServers") or []) if str(item).strip())
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

    if is_sandbox_tool(tool_name):
        allowed_patterns = SKILL_RUNTIME_CONFIG.get("allowedSandboxToolPatterns") or frozenset()
        if not skill_allows_sandbox_tool(tool_name, allowed_patterns):
            return f"Sandbox tool '{tool_name}' is not granted by the agent's skill files"

    if mcp_server:
        allowed_mcp_servers = SKILL_RUNTIME_CONFIG.get("allowedMcpServers") or frozenset()
        if not allowed_mcp_servers or mcp_server not in allowed_mcp_servers:
            return f"MCP server '{mcp_server}' is not granted by the agent's skill files"

    if a2a_target_agent and a2a_target_namespace:
        allowed_targets = SKILL_RUNTIME_CONFIG.get("allowedA2ATargets") or frozenset()
        if not allowed_targets or (a2a_target_namespace, a2a_target_agent) not in allowed_targets:
            return (
                f"A2A target '{a2a_target_namespace}/{a2a_target_agent}' is not granted by the agent's skill files"
            )

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

        existing_chain = team_context.get("delegationChain") if isinstance(team_context.get("delegationChain"), list) else []
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

    existing_chain = team_context.get("delegationChain") if isinstance(team_context.get("delegationChain"), list) else []
    delegation_chain = dedupe_delegation_chain([*existing_chain, caller_entry])
    if delegation_chain:
        team_context["delegationChain"] = delegation_chain

    try:
        return normalize_json_object(
            team_context,
            field_name="team_context",
            max_chars=TEAM_CONTEXT_MAX_CHARS,
        ) or {}
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
        for item in (team_context.get("workingAgreement") if isinstance(team_context.get("workingAgreement"), list) else [])
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
        lines.append(json.dumps(extra, ensure_ascii=False, sort_keys=True, default=str))

    return truncate_text("\n".join(lines), TEAM_CONTEXT_MAX_CHARS)


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
    try:
        return invoke_direct_a2a_target(target_agent, target_namespace, payload, request_id, timeout_seconds), "direct", None
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code < 500:
            raise
        direct_failure = f"Direct A2A target returned HTTP {exc.response.status_code}"
    except Exception as exc:
        direct_failure = f"Direct A2A transport failed: {exc}"

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

resource = Resource(attributes={
    "service.name": SERVICE_NAME,
    "service.namespace": SERVICE_NAMESPACE,
})
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
    context: str
    team_context: dict[str, Any] | None
    subagents: list[dict[str, Any]]
    subagent_strategy: str
    invoke_status: str
    policy_name: str
    policy: dict[str, Any]
    system_prompt: str
    tool_name: str
    tool_args: dict[str, Any]
    tool_result: Any
    sandbox_session: dict[str, Any] | None
    approval_name: str | None
    retry_after_seconds: int | None
    warnings: list[str]
    a2a: dict[str, Any] | None
    subagent_results: dict[str, Any] | None
    a2a_target_agent: str
    a2a_target_namespace: str
    a2a_timeout_seconds: float | None
    caller_agent_name: str
    caller_agent_namespace: str
    parent_thread_id: str
    caller_request_id: str
    # MCP tool invocation fields – populated by invoke_graph when the caller
    # sets mcp_server on InvokeRequest.  The mcp_tool graph node reads these.
    mcp_server: str
    mcp_tool_name: str
    mcp_tool_args: dict[str, Any]


class InvokeRequest(BaseModel):
    prompt: str = Field(default="", max_length=MAX_PROMPT_CHARS)
    thread_id: str | None = Field(default=None, max_length=MAX_THREAD_ID_CHARS)
    model: str | None = Field(default=None, max_length=128)
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
    mcp_server: str | None = Field(
        default=None,
        max_length=128,
        description=(
            "MCP server type to call (e.g. 'github', 'prometheus'). "
            "When set, the request is routed to the mcp_tool graph node "
            "instead of the normal chat/RAG path."
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

        if mcp_server and is_sandbox_tool(tool_name):
            raise ValueError("sandbox tools cannot be invoked through mcp_server")

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
        sections.append(json.dumps(tool_payload, ensure_ascii=False, sort_keys=True, default=str))

    if a2a_target_agent.strip() and a2a_target_namespace.strip():
        sections.append(
            json.dumps(
                {
                    "a2a_target_agent": a2a_target_agent.strip(),
                    "a2a_target_namespace": a2a_target_namespace.strip(),
                },
                ensure_ascii=False,
                sort_keys=True,
                default=str,
            )
        )

    if subagents:
        sections.append(
            json.dumps(
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
                },
                ensure_ascii=False,
                sort_keys=True,
                default=str,
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
        warning = (
            f"Skipped shared file snapshots for {target_namespace}/{target_agent} because no sandbox_session was available."
        )
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
            result, next_session = asyncio.run(
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
        return normalize_json_object(
            team_context,
            field_name="team_context",
            max_chars=TEAM_CONTEXT_MAX_CHARS,
        ) or {}
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
        lines.append(
            "If you produce reusable notes or artifacts, write or summarize them at "
            f"{result_file_path}."
        )
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
        warning = (
            f"Skipped writing subagent result for {target_namespace}/{target_agent} because no sandbox_session was available."
        )
        return sandbox_session, None, [warning]

    current_session = sandbox_session
    warnings: list[str] = []
    directory = parent_directory(result_file_path)
    if directory:
        try:
            _result, next_session = asyncio.run(
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
        _result, next_session = asyncio.run(
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

        return {
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
        }, None, next_session, snapshot_warnings

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
            response_status = str(result_payload.get("status", "completed") or "completed")
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
            job, blocked_entry, current_session, preparation_warnings = prepare_job(subagent, index, current_session, [])
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
    if not force_refresh and now - POLICY_CACHE["timestamp"] < POLICY_CACHE_TTL_SECONDS:
        return POLICY_CACHE["name"], POLICY_CACHE["spec"]

    if not K8S_POLICY_ACCESS:
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

        POLICY_CACHE.update({"timestamp": now, "name": cached_name, "spec": cached_spec})
        return cached_name, cached_spec
    except Exception as exc:
        logger.warning("Failed to load AgentPolicy, using built-in defaults: %s", exc)
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
    if is_sandbox_tool(state.get("tool_name")):
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
        raise PermissionError(
            f"MCP server '{server_type}' is not granted by the agent's skill files."
        )

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

    with httpx.Client(
        timeout=timeout,
        transport=httpx.HTTPTransport(retries=2),
        trust_env=False,
    ) as client:
        response = client.post(url, json=tool_args, headers=headers)
        response.raise_for_status()
        return response.json()  # type: ignore[no-any-return]


def create_agent(llm: ChatOpenAI):
    def synthesize_specialized_subagents(
        objective: str,
        strategy: str,
        results: list[dict[str, Any]],
    ) -> str:
        publish_runtime_event(
            "subagent.summary",
            {"status": "started", "strategy": strategy, "count": len(results)},
        )

        fallback = render_subagent_summary(objective, strategy, results)
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
                HumanMessage(content=json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)),
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
                publisher = current_event_publisher()
                response: AIMessage | Any
                if publisher is None:
                    response = llm.invoke(messages)
                else:
                    text_fragments: list[str] = []
                    streamed = False
                    try:
                        for chunk in llm.stream(messages):
                            streamed = True
                            delta = get_message_content(chunk)
                            if delta:
                                text_fragments.append(delta)
                                publish_runtime_event(
                                    "response.delta",
                                    {"delta": delta, "source": "llm"},
                                )
                    except Exception:
                        if streamed:
                            raise
                        logger.warning(
                            "LLM streaming setup failed, falling back to non-streaming invoke.",
                            exc_info=True,
                        )
                        response = llm.invoke(messages)
                    else:
                        response = AIMessage(content="".join(text_fragments))

                span.set_attribute("model", MODEL_NAME)
                span.set_attribute("rag.context_present", bool(context))
                span.set_attribute("teamwork.context_present", bool(collaboration_context))
                span.set_attribute("skills.present", bool(skill_prompt))
                span.set_attribute("llm.streaming", publisher is not None)
                return {"messages": [response], "invoke_status": "completed"}

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

                if not is_sandbox_tool(tool_nm):
                    return {
                        "messages": [AIMessage(content=blocked_response("Unsupported sandbox tool invocation"))],
                        "invoke_status": "blocked",
                        "tool_result": None,
                    }

                publish_runtime_event("sandbox.runtime", sandbox_runtime_metadata())

                try:
                    result, next_session = asyncio.run(
                        execute_sandbox_tool(
                            tool_nm,
                            tool_arguments,
                            current_session,
                            publish_runtime_event,
                        )
                    )
                except SandboxToolError as exc:
                    logger.warning("Sandbox tool invocation blocked: %s", exc)
                    return {
                        "messages": [AIMessage(content=blocked_response(str(exc)))],
                        "invoke_status": "blocked",
                        "tool_result": None,
                    }
                except Exception as exc:
                    logger.exception("Sandbox tool invocation failed for %s", tool_nm)
                    return {
                        "messages": [AIMessage(content=blocked_response(f"Sandbox tool failed: {exc}"))],
                        "invoke_status": "blocked",
                        "tool_result": None,
                    }

                result_text = format_tool_payload(result)
                span.set_attribute("sandbox.tool_name", tool_nm)
                if next_session and next_session.get("sandbox_id"):
                    span.set_attribute("sandbox.id", str(next_session["sandbox_id"]))
                return {
                    "messages": [AIMessage(content=result_text)],
                    "invoke_status": "completed",
                    "tool_result": result,
                    "sandbox_session": next_session,
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
                    return {
                        "messages": [AIMessage(content=blocked_response(
                            "mcp_server and tool_name are required for MCP calls"
                        ))],
                        "invoke_status": "blocked",
                        "tool_result": None,
                    }

                try:
                    result = mcp_call(server_type, tool_nm, tool_arguments)
                    result_text = format_tool_payload(result)
                    span.set_attribute("mcp.server_type", server_type)
                    span.set_attribute("mcp.tool_name", tool_nm)
                    logger.info(
                        "MCP tool '%s/%s' returned %d bytes",
                        server_type, tool_nm, len(result_text),
                    )
                    publish_runtime_event(
                        "mcp.result",
                        {"serverType": server_type, "toolName": tool_nm, "bytes": len(result_text)},
                    )
                    return {
                        "messages": [AIMessage(content=result_text)],
                        "invoke_status": "completed",
                        "tool_result": result,
                    }
                except PermissionError as exc:
                    logger.warning("MCP call blocked by policy allow-list: %s", exc)
                    return {
                        "messages": [AIMessage(content=blocked_response(str(exc)))],
                        "invoke_status": "blocked",
                        "tool_result": None,
                    }
                except httpx.HTTPStatusError as exc:
                    logger.error(
                        "MCP server '%s' returned HTTP %s",
                        server_type, exc.response.status_code,
                    )
                    return {
                        "messages": [AIMessage(content=blocked_response(
                            f"MCP server error: {exc.response.status_code}"
                        ))],
                        "invoke_status": "blocked",
                        "tool_result": None,
                    }
                except Exception as exc:
                    logger.exception("MCP tool invocation failed for %s/%s", server_type, tool_nm)
                    return {
                        "messages": [AIMessage(content=blocked_response(f"MCP call failed: {exc}"))],
                        "invoke_status": "blocked",
                        "tool_result": None,
                    }

        return run_graph_node("mcp_tool", _run)

    def a2a_call(state: State) -> dict[str, Any]:
        def _run() -> dict[str, Any]:
            with tracer.start_as_current_span("a2a_agent_invocation") as span:
                target_agent = (state.get("a2a_target_agent") or "").strip()
                target_namespace = (state.get("a2a_target_namespace") or "").strip()
                if not target_agent or not target_namespace:
                    return {
                        "messages": [AIMessage(content=blocked_response("A2A target agent and namespace are required"))],
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
                    "prompt": state.get("request_prompt", ""),
                    "thread_id": target_thread_id,
                    "caller_agent_name": SERVICE_NAME,
                    "caller_agent_namespace": SERVICE_NAMESPACE,
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
                            AIMessage(
                                content=blocked_response(
                                    f"A2A target returned HTTP {exc.response.status_code}"
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
                        "messages": [AIMessage(content=blocked_response("A2A callee returned a non-object JSON payload"))],
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
                }

        return run_graph_node("a2a_call", _run)

    def subagent_team(state: State) -> dict[str, Any]:
        def _run() -> dict[str, Any]:
            with tracer.start_as_current_span("subagent_orchestration") as span:
                span.set_attribute("subagent.count", len(state.get("subagents") or []))
                span.set_attribute("subagent.strategy", normalize_subagent_strategy(state.get("subagent_strategy")))
                result = coordinate_specialized_subagents(
                    state,
                    synthesizer=synthesize_specialized_subagents,
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

        litellm_api_key = LITELLM_API_KEY or LITELLM_PLACEHOLDER_API_KEY
        if not LITELLM_API_KEY:
            logger.warning(
                "LITELLM_API_KEY is not set; using a placeholder client key for base URL %s.",
                LITELLM_BASE,
            )

        llm = ChatOpenAI(
            model=MODEL_NAME,
            base_url=LITELLM_BASE,
            api_key=SecretStr(litellm_api_key),
            timeout=LITELLM_TIMEOUT_SECONDS,
            max_retries=2,
        )

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
            graph = create_agent(llm).compile(checkpointer=memory)
        except Exception:
            if connection is not None:
                connection.close()
            raise

        RUNTIME.update({"llm": llm, "graph": graph, "connection": connection, "memory": memory})
        logger.info("Agent runtime initialized successfully.")


def shutdown_runtime() -> None:
    with RUNTIME_LOCK:
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
            model=MODEL_NAME,
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
    if request.model and request.model != MODEL_NAME:
        raise HTTPException(
            status_code=400,
            detail=f"Agent '{SERVICE_NAME}' is pinned to model '{MODEL_NAME}', not '{request.model}'",
        )

    if not INVOCATION_SLOTS.acquire(timeout=REQUEST_QUEUE_TIMEOUT_SECONDS):
        raise HTTPException(status_code=503, detail="Agent runtime is busy. Retry shortly.")

    try:
        policy_name, policy_spec = load_active_policy()
        _, _, a2a_require_hitl = parse_effective_a2a_policy_config(policy_spec)
        thread_id = request.thread_id or str(uuid.uuid4())
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
                model=MODEL_NAME,
                policy_name=policy_name,
                tool_name=tool_name or None,
                status="blocked",
                warnings=dedupe_text_items(list(SKILL_RUNTIME_CONFIG.get("warnings") or [])),
            )
        route_name = (
            "sandbox_tool"
            if is_sandbox_tool(tool_name)
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
                    "model": MODEL_NAME,
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
                policy_name,
                require_approval=request.require_approval or bool(a2a_target_agent and a2a_require_hitl),
            )
            if approval_response is not None:
                return approval_response

            initial_state: State = {
                "thread_id": thread_id,
                "messages": [HumanMessage(content=prompt)] if prompt else [],
                "request_prompt": prompt,
                "context": "",
                "team_context": build_inbound_team_context(request),
                "invoke_status": "continue",
                "policy_name": policy_name or "",
                "policy": policy_spec,
                "system_prompt": SYSTEM_PROMPT,
                "tool_name": tool_name,
                "tool_args": request.tool_args,
                "tool_result": None,
                "sandbox_session": request.sandbox_session,
                "approval_name": None,
                "retry_after_seconds": None,
                "warnings": [],
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
                "mcp_server": mcp_server,
                "mcp_tool_name": tool_name,
                "mcp_tool_args": request.tool_args,
            }

            result = get_runtime()["graph"].invoke(
                initial_state,
                config={"configurable": {"thread_id": thread_id}},
            )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Agent invocation failed")
        raise HTTPException(status_code=500, detail=f"Agent invocation failed: {exc}") from exc
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

    return InvokeResponse(
        thread_id=thread_id,
        response=response_text,
        context=result.get("context", ""),
        model=MODEL_NAME,
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
    )


def chunk_text(text: str, chunk_size: int = 160) -> Iterator[str]:
    if chunk_size <= 0:
        raise ValueError("chunk_size must be greater than 0")

    for index in range(0, len(text), chunk_size):
        yield text[index:index + chunk_size]


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

        event_payload = self._sanitize_event_payload(event, payload)
        if event_payload is None:
            return

        event_payload.setdefault("thread_id", self._thread_id)
        self.event_counts[event] = self.event_counts.get(event, 0) + 1
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
                    "policy_name": response.policy_name,
                    "status": response.status,
                    "approval_name": response.approval_name,
                    "retry_after_seconds": response.retry_after_seconds,
                    "tool_name": response.tool_name,
                    "tool_result": response.tool_result,
                    "sandbox_session": response.sandbox_session,
                    "a2a": response.a2a,
                    "subagents": response.subagents,
                    "warnings": response.warnings,
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
