from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import subprocess
import threading
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, model_validator

try:
    import yaml
except ModuleNotFoundError:  # pragma: no cover - covered by runtime packaging
    yaml = None

try:
    from pythonjsonlogger import jsonlogger as _jsonlogger  # type: ignore[import-untyped]
except ModuleNotFoundError:  # pragma: no cover
    _jsonlogger = None

try:
    from prometheus_fastapi_instrumentator import Instrumentator as _Instrumentator  # type: ignore[import-untyped]
except ModuleNotFoundError:  # pragma: no cover
    _Instrumentator = None


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


logging.basicConfig(
    level=os.getenv("GOOSE_RUNTIME_LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)


def _configure_logging() -> None:
    log_level = os.getenv("GOOSE_RUNTIME_LOG_LEVEL", "INFO").upper()
    handler = logging.StreamHandler()
    if os.getenv("JSON_LOGS", "true").lower() in {"1", "true"} and _jsonlogger is not None:
        handler.setFormatter(_jsonlogger.JsonFormatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    else:
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    logging.basicConfig(level=log_level, handlers=[handler], force=True)


_configure_logging()
logger = logging.getLogger("goose-runtime")
_SHUTDOWN = threading.Event()
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

SERVICE_NAME = os.getenv("AGENT_NAME", "goose-runtime")
SERVICE_NAMESPACE = os.getenv("AGENT_NAMESPACE", "default")
DEFAULT_MODEL = os.getenv("GOOSE_MODEL", os.getenv("AGENT_MODEL", "gpt-4"))
DEFAULT_PROVIDER = os.getenv("GOOSE_PROVIDER", "litellm").strip() or "litellm"
DEFAULT_SYSTEM_PROMPT = os.getenv("GOOSE_SYSTEM_PROMPT", os.getenv("AGENT_SYSTEM_PROMPT", "")).strip()
GOOSE_BINARY = os.getenv("GOOSE_BIN", "goose").strip() or "goose"
GOOSE_WORKDIR = os.getenv("GOOSE_WORKDIR", "/workspace").strip() or "/workspace"
HOME_DIR = os.getenv("HOME", "/app/state/home").strip() or "/app/state/home"
XDG_CONFIG_HOME = os.getenv("XDG_CONFIG_HOME", f"{HOME_DIR}/.config").strip() or f"{HOME_DIR}/.config"
XDG_DATA_HOME = os.getenv("XDG_DATA_HOME", f"{HOME_DIR}/.local/share").strip() or f"{HOME_DIR}/.local/share"
MAX_PROMPT_CHARS = get_int_env("GOOSE_MAX_PROMPT_CHARS", 12000)
MAX_THREAD_ID_CHARS = get_int_env("GOOSE_MAX_THREAD_ID_CHARS", 128)
MAX_MODEL_CHARS = get_int_env("GOOSE_MAX_MODEL_CHARS", 128)
MAX_SYSTEM_PROMPT_CHARS = get_int_env("GOOSE_MAX_SYSTEM_PROMPT_CHARS", 4000)
MAX_WORKING_DIRECTORY_CHARS = get_int_env("GOOSE_MAX_WORKING_DIRECTORY_CHARS", 512)
MAX_EXTENSION_SPEC_CHARS = get_int_env("GOOSE_MAX_EXTENSION_SPEC_CHARS", 1024)
MAX_EXTENSION_ITEMS = get_int_env("GOOSE_MAX_EXTENSION_ITEMS", 16)
MAX_TURNS_LIMIT = get_int_env("GOOSE_MAX_TURNS_LIMIT", 1000)
COMMAND_TIMEOUT_SECONDS = get_float_env("GOOSE_COMMAND_TIMEOUT_SECONDS", 600.0)
TEAM_CONTEXT_MAX_CHARS = get_int_env("A2A_TEAM_CONTEXT_MAX_CHARS", 4096, minimum=256)
SKILL_FILES_ENV = "AGENT_SKILL_FILES_JSON"
SKILLS_ROOT = os.getenv("AGENT_SKILLS_ROOT", "/app/state/skills").strip() or "/app/state/skills"
MAX_AGENT_SKILL_FILES = get_int_env("AGENT_MAX_SKILL_FILES", 24, minimum=1)
MAX_AGENT_SKILL_FILE_PATH_CHARS = get_int_env("AGENT_MAX_SKILL_FILE_PATH_CHARS", 256, minimum=32)
MAX_AGENT_SKILL_FILE_CONTENT_CHARS = get_int_env("AGENT_MAX_SKILL_FILE_CONTENT_CHARS", 16000, minimum=512)
MAX_AGENT_SKILL_TOTAL_CHARS = get_int_env("AGENT_MAX_SKILL_TOTAL_CHARS", 64000, minimum=4096)
MAX_AGENT_SKILL_PROMPT_CHARS = get_int_env("AGENT_MAX_SKILL_PROMPT_CHARS", 16000, minimum=512)


def dedupe_items(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def parse_string_list_env(name: str) -> list[str]:
    raw_value = os.getenv(name, "").strip()
    if not raw_value:
        return []

    try:
        parsed = json.loads(raw_value)
    except json.JSONDecodeError:
        splitter = "\n" if "\n" in raw_value else ","
        return dedupe_items([item.strip() for item in raw_value.split(splitter) if item.strip()])

    if isinstance(parsed, list):
        return dedupe_items([str(item).strip() for item in parsed if str(item).strip()])
    if isinstance(parsed, str) and parsed.strip():
        return [parsed.strip()]
    return []


DEFAULT_BUILTIN_EXTENSIONS = parse_string_list_env("GOOSE_RUNTIME_BUILTINS")
DEFAULT_STDIO_EXTENSIONS = parse_string_list_env("GOOSE_RUNTIME_STDIO_EXTENSIONS")
DEFAULT_STREAMABLE_HTTP_EXTENSIONS = parse_string_list_env("GOOSE_RUNTIME_STREAMABLE_HTTP_EXTENSIONS")
A2A_ALLOWED_CALLERS = parse_a2a_peer_refs_env("A2A_ALLOWED_CALLERS_JSON")
GOOSE_RUNTIME_CONFIG_FILES_ENV = "GOOSE_RUNTIME_CONFIG_FILES_JSON"
SKILL_RUNTIME_CONFIG: dict[str, Any] = {
    "files": {},
    "skills": [],
    "prompt": "",
    "warnings": [],
    "gooseBuiltinExtensions": frozenset(),
    "gooseStdioExtensions": frozenset(),
    "gooseStreamableHttpExtensions": frozenset(),
    "skillFiles": [],
}


def goose_config_root() -> Path:
    return (Path(XDG_CONFIG_HOME).expanduser() / "goose").resolve()


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


def resolve_goose_config_file_path(root: Path, raw_relative_path: str) -> Path:
    normalized_path = raw_relative_path.replace("\\", "/").strip()
    if not normalized_path:
        raise RuntimeError("Goose config file paths must not be blank")
    if normalized_path.startswith("/"):
        raise RuntimeError(f"Goose config file path '{raw_relative_path}' must be relative")

    parts = [part for part in normalized_path.split("/") if part]
    if not parts or any(part in {".", ".."} for part in parts):
        raise RuntimeError(f"Goose config file path '{raw_relative_path}' is invalid")
    if "/".join(parts) == "secrets.yaml":
        raise RuntimeError(
            "Goose secrets.yaml must not be preseeded; inject secrets through environment variables instead"
        )
    if parts[0] == "permissions":
        raise RuntimeError(
            "Goose config files under permissions/ are runtime-managed and cannot be preseeded"
        )

    resolved = (root / Path(*parts)).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise RuntimeError(f"Goose config file path '{raw_relative_path}' escapes the config root") from exc
    return resolved


def serialize_goose_config_file_content(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, indent=2)


def materialize_goose_config_files() -> list[str]:
    root = goose_config_root()
    root.mkdir(parents=True, exist_ok=True)

    raw_files = parse_json_object_env(GOOSE_RUNTIME_CONFIG_FILES_ENV)
    written_files: list[str] = []
    for raw_relative_path, raw_content in sorted(raw_files.items(), key=lambda item: str(item[0])):
        resolved_path = resolve_goose_config_file_path(root, str(raw_relative_path))
        resolved_path.parent.mkdir(parents=True, exist_ok=True)
        content = serialize_goose_config_file_content(raw_content)
        resolved_path.write_text(content.rstrip("\n") + "\n", encoding="utf-8")
        written_files.append(resolved_path.relative_to(root).as_posix())

    return written_files


def current_goose_config_files() -> list[str]:
    root = goose_config_root()
    if not root.exists():
        return []

    return sorted(
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file()
    )


def normalize_skill_file_path(raw_path: object) -> str:
    normalized_path = str(raw_path).replace("\\", "/").strip()
    if not normalized_path:
        raise RuntimeError("Skill file paths must not be blank")
    if len(normalized_path) > MAX_AGENT_SKILL_FILE_PATH_CHARS:
        raise RuntimeError(
            f"Skill file paths must be {MAX_AGENT_SKILL_FILE_PATH_CHARS} characters or fewer"
        )
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
        return {}, [f"Skill frontmatter is invalid: {exc}"]

    if parsed is None:
        return {}, warnings
    if not isinstance(parsed, dict):
        return {}, ["Skill frontmatter must be a YAML or JSON object"]
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
        if len(value) > MAX_EXTENSION_SPEC_CHARS:
            warnings.append(f"{field_name}[{index}] must be {MAX_EXTENSION_SPEC_CHARS} characters or fewer")
            continue
        if value in seen:
            continue
        seen.add(value)
        normalized.append(value)
    return normalized, warnings


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
    warnings.extend(builtin_warnings)
    warnings.extend(stdio_warnings)
    warnings.extend(http_warnings)
    warnings = dedupe_items(warnings)

    return {
        "path": path,
        "name": str(raw_name or infer_skill_name(path)).strip() or infer_skill_name(path),
        "description": str(raw_description or "").strip() or None,
        "body": str(body or "").strip(),
        "gooseBuiltinExtensions": goose_builtin_extensions,
        "gooseStdioExtensions": goose_stdio_extensions,
        "gooseStreamableHttpExtensions": goose_streamable_http_extensions,
        "warnings": warnings,
    }


def render_skill_prompt(skills: list[dict[str, Any]]) -> str:
    if not skills:
        return ""

    sections = [
        "The following file-backed skills are available. Use their guidance when relevant and stay within their declared capability grants.",
    ]
    for skill in skills:
        lines = [f"Skill: {skill.get('name')}"]
        if skill.get("description"):
            lines.append(f"Description: {skill.get('description')}")
        grants: list[str] = []
        if skill.get("gooseBuiltinExtensions"):
            grants.append("Goose builtins: " + ", ".join(skill.get("gooseBuiltinExtensions") or []))
        if skill.get("gooseStdioExtensions"):
            grants.append("Goose stdio extensions: " + ", ".join(skill.get("gooseStdioExtensions") or []))
        if skill.get("gooseStreamableHttpExtensions"):
            grants.append(
                "Goose streamable HTTP extensions: " + ", ".join(skill.get("gooseStreamableHttpExtensions") or [])
            )
        if grants:
            lines.append("Capability grants:")
            lines.extend(f"- {item}" for item in grants)
        if skill.get("body"):
            lines.append("Instructions:")
            lines.append(str(skill.get("body") or ""))
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
            "gooseBuiltinExtensions": frozenset(),
            "gooseStdioExtensions": frozenset(),
            "gooseStreamableHttpExtensions": frozenset(),
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
            "gooseBuiltinExtensions": frozenset(),
            "gooseStdioExtensions": frozenset(),
            "gooseStreamableHttpExtensions": frozenset(),
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
            "gooseBuiltinExtensions": frozenset(),
            "gooseStdioExtensions": frozenset(),
            "gooseStreamableHttpExtensions": frozenset(),
            "skillFiles": [],
        }

    files: dict[str, str] = {}
    skills: list[dict[str, Any]] = []
    warnings: list[str] = []
    builtin_extensions: set[str] = set()
    stdio_extensions: set[str] = set()
    streamable_http_extensions: set[str] = set()
    total_chars = 0

    for raw_path, raw_content in sorted(parsed.items(), key=lambda item: str(item[0])):
        try:
            path = normalize_skill_file_path(raw_path)
        except RuntimeError as exc:
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
            warnings.append(f"Ignoring {path} because total skill content exceeds {MAX_AGENT_SKILL_TOTAL_CHARS} characters")
            break

        normalized_content = raw_content.replace("\r\n", "\n")
        files[path] = normalized_content
        skill = parse_skill_definition(path, normalized_content)
        skills.append(skill)
        warnings.extend(skill.get("warnings") or [])
        builtin_extensions.update(str(item).strip() for item in (skill.get("gooseBuiltinExtensions") or []) if str(item).strip())
        stdio_extensions.update(str(item).strip() for item in (skill.get("gooseStdioExtensions") or []) if str(item).strip())
        streamable_http_extensions.update(
            str(item).strip() for item in (skill.get("gooseStreamableHttpExtensions") or []) if str(item).strip()
        )

    warnings = dedupe_items(warnings)
    return {
        "files": files,
        "skills": skills,
        "prompt": render_skill_prompt(skills),
        "warnings": warnings,
        "gooseBuiltinExtensions": frozenset(builtin_extensions),
        "gooseStdioExtensions": frozenset(stdio_extensions),
        "gooseStreamableHttpExtensions": frozenset(streamable_http_extensions),
        "skillFiles": sorted(files.keys()),
    }


def materialize_skill_files() -> list[str]:
    skill_files = SKILL_RUNTIME_CONFIG.get("files") or {}
    if os.path.isdir(SKILLS_ROOT):
        shutil.rmtree(SKILLS_ROOT, ignore_errors=True)
    os.makedirs(SKILLS_ROOT, exist_ok=True)

    written_files: list[str] = []
    for path, content in sorted(skill_files.items()):
        resolved_path = (Path(SKILLS_ROOT) / Path(*path.split("/"))).resolve()
        resolved_path.parent.mkdir(parents=True, exist_ok=True)
        resolved_path.write_text(content.rstrip("\n") + "\n", encoding="utf-8")
        written_files.append(path)
    return written_files


def validate_skill_extension_request(request: "InvokeRequest") -> None:
    if not SKILL_RUNTIME_CONFIG.get("skills"):
        return

    allowed_builtin_extensions = SKILL_RUNTIME_CONFIG.get("gooseBuiltinExtensions") or frozenset()
    if request.builtin_extensions and not allowed_builtin_extensions.issuperset(request.builtin_extensions):
        disallowed = sorted(set(request.builtin_extensions) - set(allowed_builtin_extensions))
        raise HTTPException(
            status_code=400,
            detail=f"Requested Goose builtin extensions are not granted by the agent's skill files: {', '.join(disallowed)}",
        )

    allowed_stdio_extensions = SKILL_RUNTIME_CONFIG.get("gooseStdioExtensions") or frozenset()
    if request.stdio_extensions and not allowed_stdio_extensions.issuperset(request.stdio_extensions):
        disallowed = sorted(set(request.stdio_extensions) - set(allowed_stdio_extensions))
        raise HTTPException(
            status_code=400,
            detail=f"Requested Goose stdio extensions are not granted by the agent's skill files: {', '.join(disallowed)}",
        )

    allowed_streamable_http_extensions = SKILL_RUNTIME_CONFIG.get("gooseStreamableHttpExtensions") or frozenset()
    if request.streamable_http_extensions and not allowed_streamable_http_extensions.issuperset(request.streamable_http_extensions):
        disallowed = sorted(set(request.streamable_http_extensions) - set(allowed_streamable_http_extensions))
        raise HTTPException(
            status_code=400,
            detail=(
                "Requested Goose streamable HTTP extensions are not granted by the agent's skill files: "
                + ", ".join(disallowed)
            ),
        )


def inspect_goose_configuration() -> dict[str, Any]:
    ensure_runtime_directories()
    materialize_goose_config_files()
    resolved_goose_binary = shutil.which(GOOSE_BINARY)
    if resolved_goose_binary is None:
        raise HTTPException(status_code=503, detail=f"goose binary '{GOOSE_BINARY}' is not available on PATH")

    command = [resolved_goose_binary, "info", "-v"]
    try:
        completed = subprocess.run(
            command,
            cwd=str(goose_workspace_root()),
            env=build_goose_environment(DEFAULT_MODEL),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=COMMAND_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise HTTPException(status_code=504, detail="goose info -v timed out") from exc
    except OSError as exc:
        raise HTTPException(status_code=502, detail=f"Failed to run goose info -v: {exc}") from exc

    return {
        "status": "ok" if completed.returncode == 0 else "error",
        "command": command,
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "goose_binary": GOOSE_BINARY,
        "goose_binary_path": resolved_goose_binary,
        "goose_config_root": str(goose_config_root()),
        "config_files": current_goose_config_files(),
        "workspace_root": str(goose_workspace_root()),
    }


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
    max_turns: int | None = Field(default=None, ge=1, le=MAX_TURNS_LIMIT)
    working_directory: str | None = Field(default=None, max_length=MAX_WORKING_DIRECTORY_CHARS)
    builtin_extensions: list[str] = Field(default_factory=list)
    stdio_extensions: list[str] = Field(default_factory=list)
    streamable_http_extensions: list[str] = Field(default_factory=list)

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
        self.team_context = normalize_json_object(
            self.team_context,
            field_name="team_context",
            max_chars=TEAM_CONTEXT_MAX_CHARS,
        )

        if not self.prompt:
            raise ValueError("prompt must not be blank")
        if self.no_session and self.thread_id:
            raise ValueError("thread_id cannot be used when no_session is enabled")
        if self.require_approval:
            raise ValueError("goose runtime does not support require_approval yet")
        if self.tool_name:
            raise ValueError("goose runtime does not support direct tool_name execution yet")
        if self.mcp_server:
            raise ValueError("goose runtime does not support gateway-routed mcp_server execution yet")
        if self.a2a_target_agent or self.a2a_target_namespace or self.a2a_timeout_seconds is not None:
            raise ValueError("goose runtime does not support outbound A2A invocation yet")
        if self.caller_agent_name or self.caller_agent_namespace:
            if not self.caller_agent_name or not self.caller_agent_namespace:
                raise ValueError("caller_agent_name and caller_agent_namespace must be provided together")
            normalize_a2a_identifier(self.caller_agent_name, source="caller_agent_name")
            normalize_a2a_identifier(self.caller_agent_namespace, source="caller_agent_namespace")
        if self.sandbox_session is not None:
            raise ValueError("goose runtime does not support sandbox_session continuity")

        cleaned_builtin_extensions = []
        for value in self.builtin_extensions:
            text = str(value).strip()
            if not text:
                continue
            if len(text) > 128:
                raise ValueError("builtin extension ids must be 128 characters or fewer")
            if not all(ch.isalnum() or ch in {"-", "_", "."} for ch in text):
                raise ValueError(f"builtin extension '{text}' contains invalid characters")
            cleaned_builtin_extensions.append(text)
        self.builtin_extensions = dedupe_items(cleaned_builtin_extensions)

        for field_name in ("stdio_extensions", "streamable_http_extensions"):
            cleaned_values: list[str] = []
            for value in getattr(self, field_name):
                text = str(value).strip()
                if not text:
                    continue
                if len(text) > MAX_EXTENSION_SPEC_CHARS:
                    raise ValueError(f"{field_name} entries must be {MAX_EXTENSION_SPEC_CHARS} characters or fewer")
                cleaned_values.append(text)
            setattr(self, field_name, dedupe_items(cleaned_values))

        if len(self.builtin_extensions) > MAX_EXTENSION_ITEMS:
            raise ValueError(f"builtin_extensions cannot contain more than {MAX_EXTENSION_ITEMS} entries")
        if len(self.stdio_extensions) > MAX_EXTENSION_ITEMS:
            raise ValueError(f"stdio_extensions cannot contain more than {MAX_EXTENSION_ITEMS} entries")
        if len(self.streamable_http_extensions) > MAX_EXTENSION_ITEMS:
            raise ValueError(f"streamable_http_extensions cannot contain more than {MAX_EXTENSION_ITEMS} entries")

        for value in self.streamable_http_extensions:
            parsed_url = urlparse(value)
            if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
                raise ValueError(f"streamable_http_extensions entry '{value}' must be an http or https URL")

        if self.working_directory is not None:
            trimmed_workdir = self.working_directory.strip()
            self.working_directory = trimmed_workdir or None
        return self


class InvokeResponse(BaseModel):
    thread_id: str
    response: str
    model: str
    status: str = "completed"
    a2a: dict[str, Any] | None = None
    warnings: list[str] = Field(default_factory=list)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    ensure_runtime_directories()
    SKILL_RUNTIME_CONFIG.clear()
    SKILL_RUNTIME_CONFIG.update(load_skill_runtime_config())
    SKILL_RUNTIME_CONFIG["skillFiles"] = materialize_skill_files()
    if SKILL_RUNTIME_CONFIG.get("warnings"):
        logger.warning("Loaded Goose skill files with warnings: %s", "; ".join(SKILL_RUNTIME_CONFIG["warnings"]))
    materialize_goose_config_files()
    if shutil.which(GOOSE_BINARY) is None:
        raise RuntimeError(f"goose binary '{GOOSE_BINARY}' is not available on PATH")
    try:
        yield
    finally:
        _SHUTDOWN.set()
        logger.info("Goose runtime shutting down.")


app = FastAPI(
    title="Goose Runtime Adapter",
    description="HTTP adapter that exposes Goose as an agent runtime behind the sandbox gateway",
    version="0.1.0",
    lifespan=lifespan,
)

if _Instrumentator is not None:
    _Instrumentator().instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)


def ensure_runtime_directories() -> None:
    for path in (GOOSE_WORKDIR, HOME_DIR, XDG_CONFIG_HOME, XDG_DATA_HOME, str(goose_config_root()), SKILLS_ROOT, "/app/state"):
        os.makedirs(path, exist_ok=True)


def sse_event(event: str, payload: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False, default=str)}\n\n"


def truncate_text(value: str, limit: int = 1200) -> str:
    value = value.strip()
    if len(value) <= limit:
        return value
    return f"{value[:limit].rstrip()}..."


def normalize_session_name(thread_id: str) -> str:
    normalized = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in thread_id.strip())
    normalized = normalized.strip("-")
    return normalized or str(uuid.uuid4())


def combined_error_text(stdout_text: str, stderr_text: str) -> str:
    parts = [part.strip() for part in (stderr_text, stdout_text) if part.strip()]
    return "\n".join(parts).strip()


def combine_system_prompt(*parts: str | None) -> str:
    return "\n\n".join(part.strip() for part in parts if part and part.strip())


def format_team_context_system_prompt(team_context: dict[str, Any] | None) -> str:
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

    extra = {
        key: value
        for key, value in team_context.items()
        if key not in {"caller", "target", "objective", "workingAgreement", "delegationChain", "mode"}
    }
    if extra:
        lines.append("Additional collaboration context:")
        lines.append(json.dumps(extra, ensure_ascii=False, sort_keys=True, default=str))

    return truncate_text("\n".join(lines), TEAM_CONTEXT_MAX_CHARS)


def merge_setting_lists(*value_groups: list[str]) -> list[str]:
    merged: list[str] = []
    for values in value_groups:
        merged.extend(value for value in values if value)
    return dedupe_items(merged)


def goose_workspace_root() -> Path:
    return Path(GOOSE_WORKDIR).resolve()


def resolve_working_directory(raw_value: str | None) -> str:
    root = goose_workspace_root()
    if not raw_value:
        return str(root)

    candidate = Path(raw_value)
    if not candidate.is_absolute():
        candidate = root / candidate

    resolved = candidate.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"working_directory '{raw_value}' must stay within {root}",
        ) from exc

    if not resolved.exists() or not resolved.is_dir():
        raise HTTPException(
            status_code=400,
            detail=f"working_directory '{raw_value}' does not exist inside the Goose workspace",
        )

    return str(resolved)


def build_invoke_warnings(request: InvokeRequest) -> list[str]:
    warnings: list[str] = []
    if request.no_session:
        warnings.append("Session persistence is disabled for this invocation; the returned thread_id cannot be resumed.")
    warnings.extend(str(item).strip() for item in (SKILL_RUNTIME_CONFIG.get("warnings") or []) if str(item).strip())
    return warnings


def merged_payload_warnings(payload: dict[str, Any], request: InvokeRequest) -> list[str]:
    warnings = build_invoke_warnings(request)
    raw_warnings = payload.get("warnings") if isinstance(payload, dict) else None
    if isinstance(raw_warnings, list):
        warnings.extend(str(value).strip() for value in raw_warnings if str(value).strip())
    return dedupe_items(warnings)


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


def a2a_response_metadata(request: InvokeRequest) -> dict[str, Any] | None:
    if not request.caller_agent_name or not request.caller_agent_namespace:
        return None
    return {
        "callerAgent": request.caller_agent_name,
        "callerNamespace": request.caller_agent_namespace,
        "parentThreadId": request.parent_thread_id,
        "callerRequestId": request.caller_request_id,
    }


def normalize_goose_event_name(event_type: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "_" for ch in event_type.strip().lower())
    return f"goose.{cleaned}" if cleaned else "goose.event"


def session_not_found(stdout_text: str, stderr_text: str) -> bool:
    combined = combined_error_text(stdout_text, stderr_text).lower()
    return "no session found" in combined


def build_goose_environment(model: str) -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "HOME": HOME_DIR,
            "XDG_CONFIG_HOME": XDG_CONFIG_HOME,
            "XDG_DATA_HOME": XDG_DATA_HOME,
            "GOOSE_PROVIDER": DEFAULT_PROVIDER,
            "GOOSE_MODEL": model,
        }
    )
    env.setdefault("GOOSE_DISABLE_SESSION_NAMING", "true")
    env.setdefault("GOOSE_DISABLE_KEYRING", "1")
    return env


def build_goose_run_command(
    *,
    model: str,
    session_name: str,
    output_format: str,
    resume: bool,
    system_prompt: str,
    max_turns: int | None,
    debug: bool,
    no_session: bool,
    builtin_extensions: list[str],
    stdio_extensions: list[str],
    streamable_http_extensions: list[str],
) -> list[str]:
    command = [
        GOOSE_BINARY,
        "run",
        "--instructions",
        "-",
        "--provider",
        DEFAULT_PROVIDER,
        "--model",
        model,
        "--output-format",
        output_format,
    ]
    if not no_session:
        command.extend(["--name", session_name])
    if system_prompt:
        command.extend(["--system", system_prompt])
    if max_turns is not None:
        command.extend(["--max-turns", str(max_turns)])
    if debug:
        command.append("--debug")
    if no_session:
        command.append("--no-session")
    if resume and not no_session:
        command.append("--resume")
    if builtin_extensions:
        command.extend(["--with-builtin", ",".join(builtin_extensions)])
    for extension_command in stdio_extensions:
        command.extend(["--with-extension", extension_command])
    for extension_url in streamable_http_extensions:
        command.extend(["--with-streamable-http-extension", extension_url])
    return command


async def execute_goose_json(
    *,
    prompt: str,
    model: str,
    session_name: str,
    allow_resume: bool,
    system_prompt: str,
    max_turns: int | None,
    debug: bool,
    no_session: bool,
    builtin_extensions: list[str],
    stdio_extensions: list[str],
    streamable_http_extensions: list[str],
    working_directory: str,
) -> dict[str, Any]:
    attempts = [True, False] if allow_resume else [False]

    for resume in attempts:
        command = build_goose_run_command(
            model=model,
            session_name=session_name,
            output_format="json",
            resume=resume,
            system_prompt=system_prompt,
            max_turns=max_turns,
            debug=debug,
            no_session=no_session,
            builtin_extensions=builtin_extensions,
            stdio_extensions=stdio_extensions,
            streamable_http_extensions=streamable_http_extensions,
        )
        logger.info("Running Goose command for %s in %s", SERVICE_NAME, working_directory)
        process = await asyncio.create_subprocess_exec(
            *command,
            cwd=working_directory,
            env=build_goose_environment(model),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                process.communicate(prompt.encode("utf-8")),
                timeout=COMMAND_TIMEOUT_SECONDS,
            )
        except TimeoutError as exc:
            process.kill()
            await process.communicate()
            raise HTTPException(status_code=504, detail="Goose runtime timed out") from exc

        stdout_text = stdout_bytes.decode("utf-8", errors="replace")
        stderr_text = stderr_bytes.decode("utf-8", errors="replace")

        if process.returncode == 0:
            try:
                return json.loads(stdout_text)
            except json.JSONDecodeError as exc:
                raise HTTPException(
                    status_code=502,
                    detail=f"Goose returned non-JSON output: {truncate_text(stdout_text)}",
                ) from exc

        if resume and session_not_found(stdout_text, stderr_text):
            logger.info("Goose session '%s' was not found, retrying without resume", session_name)
            continue

        raise HTTPException(
            status_code=502,
            detail=f"Goose invocation failed: {truncate_text(combined_error_text(stdout_text, stderr_text) or 'unknown error')}",
        )

    raise HTTPException(status_code=500, detail="Goose invocation failed before a session could be created")


def message_role(message: dict[str, Any]) -> str:
    role = message.get("role") or message.get("sender") or message.get("author") or ""
    return str(role).strip().lower()


def extract_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts = [extract_text(item) for item in value]
        return "\n".join(part for part in parts if part).strip()
    if isinstance(value, dict):
        for key in ("text", "content", "message", "body"):
            if key in value:
                text = extract_text(value.get(key))
                if text:
                    return text
    return ""


def extract_latest_assistant_text(messages: list[dict[str, Any]]) -> str:
    for message in reversed(messages):
        if message_role(message) != "assistant":
            continue
        content = extract_text(message.get("content"))
        if content:
            return content
    return ""


async def stream_goose_events(
    *,
    prompt: str,
    model: str,
    session_name: str,
    thread_id: str,
    allow_resume: bool,
    system_prompt: str,
    max_turns: int | None,
    debug: bool,
    no_session: bool,
    builtin_extensions: list[str],
    stdio_extensions: list[str],
    streamable_http_extensions: list[str],
    working_directory: str,
    a2a: dict[str, Any] | None,
    warnings: list[str],
) -> AsyncIterator[str]:
    attempts = [True, False] if allow_resume else [False]

    for resume in attempts:
        command = build_goose_run_command(
            model=model,
            session_name=session_name,
            output_format="stream-json",
            resume=resume,
            system_prompt=system_prompt,
            max_turns=max_turns,
            debug=debug,
            no_session=no_session,
            builtin_extensions=builtin_extensions,
            stdio_extensions=stdio_extensions,
            streamable_http_extensions=streamable_http_extensions,
        )
        process = await asyncio.create_subprocess_exec(
            *command,
            cwd=working_directory,
            env=build_goose_environment(model),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stderr_task = asyncio.create_task(process.stderr.read() if process.stderr else asyncio.sleep(0, result=b""))
        assistant_text = ""
        saw_output = False

        try:
            async with asyncio.timeout(COMMAND_TIMEOUT_SECONDS):
                if process.stdin is not None:
                    process.stdin.write(prompt.encode("utf-8"))
                    await process.stdin.drain()
                    process.stdin.close()

                while True:
                    line = await process.stdout.readline() if process.stdout else b""
                    if not line:
                        break
                    payload = line.decode("utf-8", errors="replace").strip()
                    if not payload:
                        continue
                    try:
                        event = json.loads(payload)
                    except json.JSONDecodeError:
                        logger.debug("Skipping non-JSON Goose stream line: %s", payload)
                        continue

                    saw_output = True
                    event_type = str(event.get("type", "")).strip().lower()

                    if event_type == "message":
                        message = event.get("message") or {}
                        if isinstance(message, dict) and message_role(message) == "assistant":
                            next_text = extract_text(message.get("content"))
                            if next_text:
                                delta = next_text[len(assistant_text):] if next_text.startswith(assistant_text) else next_text
                                assistant_text = next_text
                                if delta:
                                    yield sse_event(
                                        "response.delta",
                                        {
                                            "thread_id": thread_id,
                                            "delta": delta,
                                            "source": "goose",
                                        },
                                    )
                                    continue

                    if event_type == "notification":
                        yield sse_event(
                            "goose.notification",
                            {
                                "thread_id": thread_id,
                                "extension_id": event.get("extension_id"),
                                "message": event.get("message"),
                                "data": event.get("data"),
                            },
                        )
                        continue

                    if event_type == "model_change":
                        yield sse_event(
                            "goose.model_change",
                            {
                                "thread_id": thread_id,
                                "model": event.get("model") or model,
                                "mode": event.get("mode"),
                            },
                        )
                        continue

                    if event_type == "error":
                        error_text = str(event.get("error") or "Goose invocation failed")
                        yield sse_event(
                            "response.error",
                            {
                                "thread_id": thread_id,
                                "error": error_text,
                            },
                        )
                        continue

                    forwarded_event = event if isinstance(event, dict) else {"payload": event}
                    if not isinstance(forwarded_event, dict):
                        forwarded_event = {"payload": str(forwarded_event)}
                    forwarded_event.setdefault("thread_id", thread_id)
                    yield sse_event(normalize_goose_event_name(event_type), forwarded_event)
        except TimeoutError:
            process.kill()
            await process.wait()
            yield sse_event(
                "response.error",
                {
                    "thread_id": thread_id,
                    "error": "Goose runtime timed out",
                },
            )
            return
        except asyncio.CancelledError:
            process.kill()
            raise
        finally:
            await process.wait()
            stderr_bytes = await stderr_task

        stderr_text = stderr_bytes.decode("utf-8", errors="replace")
        if process.returncode == 0:
            yield sse_event(
                "response.completed",
                {
                    "thread_id": thread_id,
                    "response": assistant_text,
                    "model": model,
                    "status": "completed",
                    "a2a": a2a,
                    "warnings": warnings,
                },
            )
            return

        if resume and session_not_found("", stderr_text) and not saw_output:
            logger.info("Goose session '%s' was not found during stream startup, retrying without resume", session_name)
            continue

        yield sse_event(
            "response.error",
            {
                "thread_id": thread_id,
                "error": truncate_text(stderr_text or "Goose invocation failed"),
            },
        )
        return


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "status": "shutting-down" if _SHUTDOWN.is_set() else "healthy",
        "runtime": "goose",
        "service": SERVICE_NAME,
        "namespace": SERVICE_NAMESPACE,
        "provider": DEFAULT_PROVIDER,
        "skills": {
            "count": len(SKILL_RUNTIME_CONFIG.get("skills") or []),
            "files": SKILL_RUNTIME_CONFIG.get("skillFiles") or [],
            "warnings": SKILL_RUNTIME_CONFIG.get("warnings") or [],
        },
    }


@app.get("/ready")
def ready() -> dict[str, Any]:
    if _SHUTDOWN.is_set():
        raise HTTPException(status_code=503, detail="Runtime is shutting down")
    ensure_runtime_directories()
    resolved_goose_binary = shutil.which(GOOSE_BINARY)
    if resolved_goose_binary is None:
        raise HTTPException(status_code=503, detail=f"goose binary '{GOOSE_BINARY}' is not available on PATH")

    return {
        "status": "ready",
        "runtime": "goose",
        "goose_binary": GOOSE_BINARY,
        "goose_binary_path": resolved_goose_binary,
        "goose_config_root": str(goose_config_root()),
        "config_files": current_goose_config_files(),
        "workspace_root": str(goose_workspace_root()),
        "skill_files": SKILL_RUNTIME_CONFIG.get("skillFiles") or [],
    }


@app.get("/debug/goose-info")
def debug_goose_info() -> dict[str, Any]:
    return inspect_goose_configuration()


@app.post("/invoke", response_model=InvokeResponse)
async def invoke(request: InvokeRequest) -> InvokeResponse:
    if _SHUTDOWN.is_set():
        raise HTTPException(status_code=503, detail="Runtime is shutting down. Retry on another pod.")
    validate_inbound_a2a_request(request)
    validate_skill_extension_request(request)
    model = (request.model or DEFAULT_MODEL).strip() or DEFAULT_MODEL
    thread_id = request.thread_id or str(uuid.uuid4())
    session_name = normalize_session_name(thread_id)
    system_prompt = combine_system_prompt(
        DEFAULT_SYSTEM_PROMPT,
        request.system,
        str(SKILL_RUNTIME_CONFIG.get("prompt") or "").strip(),
        format_team_context_system_prompt(request.team_context),
    )
    builtin_extensions = merge_setting_lists(DEFAULT_BUILTIN_EXTENSIONS, request.builtin_extensions)
    stdio_extensions = merge_setting_lists(DEFAULT_STDIO_EXTENSIONS, request.stdio_extensions)
    streamable_http_extensions = merge_setting_lists(
        DEFAULT_STREAMABLE_HTTP_EXTENSIONS,
        request.streamable_http_extensions,
    )
    working_directory = resolve_working_directory(request.working_directory)
    payload = await execute_goose_json(
        prompt=request.prompt,
        model=model,
        session_name=session_name,
        allow_resume=bool(request.thread_id) and not request.no_session,
        system_prompt=system_prompt,
        max_turns=request.max_turns,
        debug=request.debug,
        no_session=request.no_session,
        builtin_extensions=builtin_extensions,
        stdio_extensions=stdio_extensions,
        streamable_http_extensions=streamable_http_extensions,
        working_directory=working_directory,
    )
    messages = payload.get("messages") if isinstance(payload, dict) else []
    if not isinstance(messages, list):
        messages = []

    response_text = extract_latest_assistant_text([item for item in messages if isinstance(item, dict)])
    metadata = payload.get("metadata") if isinstance(payload, dict) else {}
    status = "completed"
    if isinstance(metadata, dict):
        status = str(metadata.get("status") or "completed")

    return InvokeResponse(
        thread_id=thread_id,
        response=response_text,
        model=model,
        status=status,
        a2a=a2a_response_metadata(request),
        warnings=merged_payload_warnings(payload, request),
    )


@app.post("/invoke/stream")
async def invoke_stream(request: InvokeRequest) -> StreamingResponse:
    if _SHUTDOWN.is_set():
        raise HTTPException(status_code=503, detail="Runtime is shutting down. Retry on another pod.")
    validate_inbound_a2a_request(request)
    validate_skill_extension_request(request)
    model = (request.model or DEFAULT_MODEL).strip() or DEFAULT_MODEL
    allow_resume = bool(request.thread_id) and not request.no_session
    thread_id = request.thread_id or str(uuid.uuid4())
    session_name = normalize_session_name(thread_id)
    system_prompt = combine_system_prompt(
        DEFAULT_SYSTEM_PROMPT,
        request.system,
        str(SKILL_RUNTIME_CONFIG.get("prompt") or "").strip(),
        format_team_context_system_prompt(request.team_context),
    )
    builtin_extensions = merge_setting_lists(DEFAULT_BUILTIN_EXTENSIONS, request.builtin_extensions)
    stdio_extensions = merge_setting_lists(DEFAULT_STDIO_EXTENSIONS, request.stdio_extensions)
    streamable_http_extensions = merge_setting_lists(
        DEFAULT_STREAMABLE_HTTP_EXTENSIONS,
        request.streamable_http_extensions,
    )
    working_directory = resolve_working_directory(request.working_directory)
    warnings = build_invoke_warnings(request)

    async def event_generator() -> AsyncIterator[str]:
        async for event in stream_goose_events(
            prompt=request.prompt,
            model=model,
            session_name=session_name,
            thread_id=thread_id,
            allow_resume=allow_resume,
            system_prompt=system_prompt,
            max_turns=request.max_turns,
            debug=request.debug,
            no_session=request.no_session,
            builtin_extensions=builtin_extensions,
            stdio_extensions=stdio_extensions,
            streamable_http_extensions=streamable_http_extensions,
            working_directory=working_directory,
            a2a=a2a_response_metadata(request),
            warnings=warnings,
        ):
            yield event

    return StreamingResponse(event_generator(), media_type="text/event-stream")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8080)