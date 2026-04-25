"""Standalone utility helpers for the API Gateway."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from constants import FACTORY_MODES, SUBAGENT_STRATEGIES


def now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string with millisecond precision."""
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def normalize_json_object(value: Any, *, field_name: str, max_chars: int) -> dict[str, Any] | None:
    """Validate and normalize a JSON object field, enforcing a serialized size limit."""
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
    """Validate and return a subagent strategy name."""
    strategy = str(value or "sequential").strip().lower() or "sequential"
    if strategy not in SUBAGENT_STRATEGIES:
        raise ValueError(f"subagent_strategy must be one of {', '.join(sorted(SUBAGENT_STRATEGIES))}")
    return strategy


def normalize_path_text(value: Any, *, source: str) -> str:
    """Validate a non-blank path / identifier string (max 512 chars)."""
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{source} must not be blank")
    if len(text) > 512:
        raise ValueError(f"{source} must not exceed 512 characters")
    return text


def normalize_factory_mode(value: Any) -> str | None:
    """Validate and return a factory mode name, or None if blank."""
    normalized = str(value or "").strip().lower()
    if not normalized:
        return None
    if normalized not in FACTORY_MODES:
        raise ValueError(f"factory_mode must be one of {', '.join(sorted(FACTORY_MODES))}")
    return normalized


def is_factory_agent_resource(agent_name: str, agent: dict[str, Any] | None = None) -> bool:
    """Return True if the agent name or its spec refers to the factory context."""
    from constants import FACTORY_AGENT_NAME, FACTORY_CONTEXT_NAME

    if agent_name == FACTORY_AGENT_NAME:
        return True
    spec = (agent or {}).get("spec") or {}
    return str(spec.get("contextRef") or "").strip() == FACTORY_CONTEXT_NAME


def is_factory_workflow_resource(workflow_name: str, workflow_spec: dict[str, Any] | None = None) -> bool:
    """Return True if the workflow name or its spec refers to the factory context."""
    from constants import FACTORY_CONTEXT_NAME, FACTORY_WORKFLOW_NAME

    if workflow_name == FACTORY_WORKFLOW_NAME:
        return True
    spec = workflow_spec or {}
    return str(spec.get("contextRef") or "").strip() == FACTORY_CONTEXT_NAME


def append_system_note(request_payload: dict[str, Any], note: str | None) -> None:
    """Append a system note to a request payload's 'system' field."""
    note_text = str(note or "").strip()
    if not note_text:
        return
    existing_system = str(request_payload.get("system") or "").strip()
    request_payload["system"] = f"{existing_system}\n\n{note_text}" if existing_system else note_text


def unwrap_factory_workflow_input(input_value: str) -> tuple[str | None, str]:
    """Parse a factory workflow input string.

    Returns a tuple of (factory_mode, unwrapped_request). If the input
    was not wrapped by build_factory_workflow_input, factory_mode is None
    and the original input is returned as the request.
    """
    input_str = str(input_value or "").strip()
    if not input_str:
        return None, ""
    try:
        parsed = json.loads(input_str)
        if isinstance(parsed, dict) and "__factory_mode" in parsed:
            return parsed["__factory_mode"], str(parsed.get("request") or "")
    except json.JSONDecodeError:
        pass
    return None, input_str


def build_factory_workflow_input(base_input: str, factory_mode: str) -> str:
    """Wrap a request input with factory mode metadata.

    The wrapped value is a JSON object that unwrap_factory_workflow_input
    can parse back into the original request and mode.
    """
    return json.dumps(
        {"__factory_mode": factory_mode, "request": base_input},
        ensure_ascii=False,
    )
