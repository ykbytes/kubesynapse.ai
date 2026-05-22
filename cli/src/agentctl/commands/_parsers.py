"""Shared payload parsers and normalization logic (migrated from monolith)."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml

from agentctl.output import fatal

K8S_NAME_RE = re.compile(r"^[a-z0-9]([-a-z0-9]*[a-z0-9])?$")


def read_structured_file(file_path: Path) -> dict[str, Any]:
    """Read a JSON or YAML file and return as dict."""
    try:
        raw_text = file_path.read_text(encoding="utf-8")
    except OSError as exc:
        fatal(f"Failed to read {file_path}: {exc}")
        raise  # unreachable but type checker

    try:
        loaded = json.loads(raw_text)
    except json.JSONDecodeError:
        try:
            documents = [doc for doc in yaml.safe_load_all(raw_text) if doc is not None]
        except yaml.YAMLError as exc:
            fatal(f"Failed to parse {file_path} as JSON or YAML: {exc}")
            raise
        if not documents:
            fatal(f"{file_path} did not contain any JSON or YAML document.")
        if len(documents) > 1:
            fatal(f"{file_path} contains multiple YAML documents; provide exactly one.")
        loaded = documents[0]

    if not isinstance(loaded, dict):
        fatal(f"{file_path} must contain a JSON or YAML object at the top level.")
    return loaded


def snake_or_camel(payload: dict[str, Any], snake_key: str, camel_key: str, default: Any = None) -> Any:
    if snake_key in payload:
        return payload[snake_key]
    if camel_key in payload:
        return payload[camel_key]
    return default


def normalize_list_of_strings(values: Any, field_name: str) -> list[str]:
    if not values:
        return []
    if not isinstance(values, list):
        fatal(f"{field_name} must be a list.")
    return [str(item) for item in values if str(item).strip()]


def normalize_sidecars(sidecars: Any) -> list[dict[str, Any]]:
    if not sidecars:
        return []
    if not isinstance(sidecars, list):
        fatal("mcpSidecars/mcp_sidecars must be a list.")
    normalized: list[dict[str, Any]] = []
    for item in sidecars:
        if not isinstance(item, dict):
            fatal("Each sidecar entry must be an object.")
        normalized.append(item)
    return normalized


def require_supported_runtime_kind(value: Any, field_name: str) -> str:
    runtime_kind = str(value or "").strip().lower()
    if not runtime_kind:
        fatal(f"{field_name} is required and must be 'opencode', 'pi', or 'mistral-vibe'.")
    if runtime_kind not in {"opencode", "pi", "mistral-vibe"}:
        fatal(f"{field_name} must be 'opencode', 'pi', or 'mistral-vibe'. '{runtime_kind}' is not supported.")
    return runtime_kind


def normalize_a2a_config_value(value: Any, field_name: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        fatal(f"{field_name} must be an object.")
    allowed_callers = snake_or_camel(value, "allowed_callers", "allowedCallers", [])
    if allowed_callers is None:
        allowed_callers = []
    if not isinstance(allowed_callers, list):
        fatal(f"{field_name}.allowed_callers must be a list.")
    normalized: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for item in allowed_callers:
        if not isinstance(item, dict):
            fatal(f"{field_name}.allowed_callers entries must be objects.")
        name = str(item.get("name", "")).strip()
        namespace = str(item.get("namespace", "")).strip()
        if not name or not namespace:
            fatal(f"{field_name}.allowed_callers entries need name and namespace.")
        identity = (namespace, name)
        if identity not in seen:
            seen.add(identity)
            normalized.append({"name": name, "namespace": namespace})
    return {"allowed_callers": normalized}


def normalize_opencode_config_files_value(value: Any, field_name: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        fatal(f"{field_name} must be an object.")
    return dict(value)


def normalize_agent_skills_value(value: Any, field_name: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        fatal(f"{field_name} must be an object.")
    raw_files = snake_or_camel(value, "files", "files", {})
    if not raw_files:
        return {}
    if not isinstance(raw_files, dict):
        fatal(f"{field_name}.files must be an object.")
    normalized_files: dict[str, str] = {}
    for raw_path, raw_content in sorted(raw_files.items(), key=lambda item: str(item[0])):
        path = str(raw_path or "").replace("\\", "/").strip()
        if not path:
            fatal(f"{field_name}.files keys must not be blank.")
        if not path.lower().endswith(".md"):
            fatal(f"{field_name}.files.{path} must be a Markdown file.")
        if not isinstance(raw_content, str) or not raw_content.strip():
            fatal(f"{field_name}.files.{path} must be a non-empty Markdown string.")
        normalized_files[path] = raw_content.replace("\r\n", "\n")
    return {"files": normalized_files} if normalized_files else {}


def normalize_workflow_steps(steps: Any) -> list[dict[str, Any]]:
    if not steps:
        return []
    if not isinstance(steps, list):
        fatal("steps must be a list.")
    normalized: list[dict[str, Any]] = []
    for item in steps:
        if not isinstance(item, dict):
            fatal("Each workflow step must be an object.")
        execution = snake_or_camel(item, "execution", "execution", None)
        normalized.append(
            {
                "name": str(snake_or_camel(item, "name", "name", "")),
                "agent_ref": str(snake_or_camel(item, "agent_ref", "agentRef", "")),
                "prompt": str(snake_or_camel(item, "prompt", "prompt", "")),
                "depends_on": normalize_list_of_strings(
                    snake_or_camel(item, "depends_on", "dependsOn", []), "depends_on"
                ),
                "require_approval": bool(snake_or_camel(item, "require_approval", "requireApproval", False)),
                "execution": execution if isinstance(execution, dict) else None,
            }
        )
    return normalized


def coerce_agent_payload(document: dict[str, Any], *, for_update: bool) -> tuple[dict[str, Any], str | None]:
    """Parse an agent document (CRD-style or flat) into a gateway API payload."""
    metadata = document.get("metadata") if isinstance(document.get("metadata"), dict) else {}

    if document.get("kind") == "AIAgent" and isinstance(document.get("spec"), dict):
        spec = document["spec"]
        storage = spec.get("storage") if isinstance(spec.get("storage"), dict) else {}
        runtime = spec.get("runtime") if isinstance(spec.get("runtime"), dict) else {}
        opencode_runtime = runtime.get("opencode") if isinstance(runtime.get("opencode"), dict) else {}
        payload: dict[str, Any] = {
            "model": str(spec.get("model", "")),
            "system_prompt": str(spec.get("systemPrompt", "")),
            "policy_ref": spec.get("policyRef"),
            "storage_size": storage.get("size", "1Gi"),
            "runtime_kind": require_supported_runtime_kind(runtime.get("kind"), "spec.runtime.kind"),
            "enable_gvisor": bool(spec.get("enableGVisor", False)),
            "mcp_servers": normalize_list_of_strings(spec.get("mcpServers"), "mcpServers"),
            "mcp_sidecars": normalize_sidecars(spec.get("mcpSidecars")),
            "a2a_config": normalize_a2a_config_value(spec.get("a2a"), "spec.a2a"),
            "skills": normalize_agent_skills_value(spec.get("skills"), "spec.skills"),
            "opencode_config_files": normalize_opencode_config_files_value(
                opencode_runtime.get("configFiles"), "runtime.opencode.configFiles"
            ),
        }
        if not for_update:
            payload["name"] = str(metadata.get("name", ""))
        return payload, str(metadata.get("name", "") or "")

    # Flat format
    payload = {
        "model": str(snake_or_camel(document, "model", "model", "")),
        "system_prompt": str(snake_or_camel(document, "system_prompt", "systemPrompt", "")),
        "policy_ref": snake_or_camel(document, "policy_ref", "policyRef"),
        "storage_size": snake_or_camel(document, "storage_size", "storageSize", "1Gi"),
        "runtime_kind": require_supported_runtime_kind(
            snake_or_camel(document, "runtime_kind", "runtimeKind"), "runtime_kind"
        ),
        "enable_gvisor": bool(snake_or_camel(document, "enable_gvisor", "enableGVisor", False)),
        "mcp_servers": normalize_list_of_strings(
            snake_or_camel(document, "mcp_servers", "mcpServers", []), "mcp_servers"
        ),
        "mcp_sidecars": normalize_sidecars(snake_or_camel(document, "mcp_sidecars", "mcpSidecars", [])),
        "a2a_config": normalize_a2a_config_value(snake_or_camel(document, "a2a_config", "a2aConfig", {}), "a2a_config"),
        "skills": normalize_agent_skills_value(snake_or_camel(document, "skills", "skills", {}), "skills"),
        "opencode_config_files": normalize_opencode_config_files_value(
            snake_or_camel(document, "opencode_config_files", "opencodeConfigFiles", {}), "opencode_config_files"
        ),
    }
    resource_name = str(snake_or_camel(document, "name", "name", metadata.get("name", "")) or "")
    if not for_update:
        payload["name"] = resource_name
    return payload, resource_name


def coerce_workflow_payload(document: dict[str, Any], *, for_update: bool) -> tuple[dict[str, Any], str | None]:
    """Parse a workflow document into a gateway API payload."""
    metadata = document.get("metadata") if isinstance(document.get("metadata"), dict) else {}

    if document.get("kind") == "AgentWorkflow" and isinstance(document.get("spec"), dict):
        spec = document["spec"]
        payload: dict[str, Any] = {
            "description": str(spec.get("description", "")),
            "input": str(spec.get("input", "")),
            "message_bus": str(spec.get("messageBus", "in-memory")),
            "steps": normalize_workflow_steps(spec.get("steps", [])),
        }
        if not for_update:
            payload["name"] = str(metadata.get("name", ""))
        return payload, str(metadata.get("name", "") or "")

    payload = {
        "description": str(snake_or_camel(document, "description", "description", "")),
        "input": str(snake_or_camel(document, "input", "input", "")),
        "message_bus": str(snake_or_camel(document, "message_bus", "messageBus", "in-memory")),
        "steps": normalize_workflow_steps(snake_or_camel(document, "steps", "steps", [])),
    }
    resource_name = str(snake_or_camel(document, "name", "name", metadata.get("name", "")) or "")
    if not for_update:
        payload["name"] = resource_name
    return payload, resource_name


def resolve_namespace(default_namespace: str, document: dict[str, Any]) -> str:
    """Extract namespace from document metadata, or use default."""
    metadata = document.get("metadata")
    if isinstance(metadata, dict):
        ns = metadata.get("namespace")
        if isinstance(ns, str) and ns.strip():
            return ns.strip()
    return default_namespace


def resolve_resource_name(
    name: str | None,
    file_path: Path | None,
    inferred_name: str | None,
    resource_label: str,
) -> str:
    """Determine final resource name from explicit, inferred, or file."""
    candidate = (name or inferred_name or "").strip()
    if candidate:
        return candidate
    if file_path is not None:
        fatal(f"Could not determine the {resource_label} name from {file_path}. Pass it explicitly.")
    fatal(f"{resource_label.capitalize()} name is required.")
    raise SystemExit(1)  # unreachable
