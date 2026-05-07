"""Shared pytest fixtures and helpers for KubeSynth Runtime API conformance tests.

Usage
-----
This module is registered via ``tests/conftest.py`` (``pytest_plugins``) so all
fixtures are auto-discovered. Helper functions and schemas must be imported
explicitly in test modules when needed.

Environment Variables
---------------------
- ``OPENCODE_RUNTIME_URL`` — Base URL for opencode-runtime
- ``PI_RUNTIME_URL`` — Base URL for pi-runtime
- ``VIBE_RUNTIME_URL`` — Base URL for vibe-runtime
- ``RUNTIME_BEARER_TOKEN`` — Optional Bearer token for runtime auth

Example
-------
.. code-block:: python

    from runtime_conftest import (
        assert_has_fields,
        create_thread,
        parse_sse_events,
        validate_json_schema,
    )
"""

from __future__ import annotations

import json
import os
from typing import Any

import httpx
import pytest

RUNTIME_TIMEOUT = 30.0

#: Mapping of runtime names to the environment variables that hold their URLs.
RUNTIME_ENVS: dict[str, str] = {
    "opencode": "OPENCODE_RUNTIME_URL",
    "pi": "PI_RUNTIME_URL",
    "vibe": "VIBE_RUNTIME_URL",
}

#: Canonical SSE event names per KubeSynth Runtime API v1.
CANONICAL_SSE_EVENTS: set[str] = {
    "response.started",
    "response.delta",
    "response.tool_call",
    "response.tool_result",
    "todo.updated",
    "question.asked",
    "todo.cleared",
    "response.completed",
    "response.error",
}

# ---------------------------------------------------------------------------
# JSON Schema definitions (subset of OpenAPI spec)
# ---------------------------------------------------------------------------

HEALTH_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["status", "runtime"],
    "properties": {
        "status": {"type": "string", "enum": ["healthy", "unhealthy"]},
        "runtime": {"type": "string"},
        "service": {"type": "string"},
        "namespace": {"type": "string"},
        "provider": {"type": "string"},
        "agent": {"type": "string"},
        "sessions": {"type": "object"},
        "uptime_seconds": {"type": "number"},
        "timestamp": {"type": "string"},
    },
}

READY_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["status"],
    "properties": {
        "status": {"type": "string", "enum": ["ready", "not_ready"]},
        "runtime": {"type": "string"},
        "checks": {"type": "object"},
    },
}

INFO_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["runtime", "contract_version"],
    "properties": {
        "runtime": {"type": "string"},
        "contract_version": {"type": "string"},
        "service": {"type": "string"},
        "namespace": {"type": "string"},
        "provider": {"type": "string"},
        "model": {"type": "string"},
        "agent": {"type": "string"},
        "version": {"type": "string"},
    },
}

CAPABILITIES_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["runtime", "capabilities"],
    "properties": {
        "runtime": {"type": "string"},
        "service": {"type": "string"},
        "capabilities": {
            "type": "object",
            "required": ["tiers"],
            "properties": {
                "native_tools": {"type": "array", "items": {"type": "string"}},
                "output_formats": {"type": "array", "items": {"type": "string"}},
                "structured_output": {"type": "object"},
                "autonomous_execution": {"type": "object"},
                "session_management": {"type": "object"},
                "mcp_usage": {"type": "object"},
                "a2a": {"type": "object"},
                "tiers": {
                    "type": "array",
                    "items": {"type": "string", "enum": ["core", "session", "artifacts", "streaming"]},
                },
            },
        },
    },
}

INVOKE_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["status", "response"],
    "properties": {
        "thread_id": {"type": "string"},
        "response": {"type": "string"},
        "model": {"type": "string"},
        "status": {
            "type": "string",
            "enum": ["completed", "error", "cancelled", "incomplete", "context_overflow"],
        },
        "approval_name": {"type": "string"},
        "retry_after_seconds": {"type": "number"},
        "warnings": {"type": "array", "items": {"type": "string"}},
        "artifacts": {"type": "array"},
        "tool_calls": {"type": "array"},
        "continuity": {
            "type": "object",
            "properties": {
                "created_new_session": {"type": "boolean"},
                "session_recovered": {"type": "boolean"},
                "has_prior_memory": {"type": "boolean"},
            },
        },
        "metadata": {"type": "object"},
    },
}

ERROR_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["error"],
    "properties": {
        "error": {
            "type": "object",
            "required": ["code", "message"],
            "properties": {
                "code": {"type": "string"},
                "message": {"type": "string"},
                "details": {"type": "object"},
                "trace_id": {"type": "string"},
            },
        },
    },
}

TODO_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "thread_id": {"type": "string"},
        "session_id": {"type": "string"},
        "todos": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "content": {"type": "string"},
                    "status": {"type": "string", "enum": ["pending", "in_progress", "completed", "cancelled"]},
                },
            },
        },
    },
}

DIFF_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "thread_id": {"type": "string"},
        "session_id": {"type": "string"},
        "diff": {"type": "string"},
    },
}

CONTEXT_BUDGET_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "model_context_limit": {"type": "integer"},
        "tokens_used": {"type": "integer"},
        "tokens_remaining": {"type": "integer"},
        "usage_percent": {"type": "number"},
        "status": {"type": "string", "enum": ["ok", "warning", "critical", "overflow"]},
        "compaction_available": {"type": "boolean"},
    },
}

ARTIFACTS_LIST_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "files": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "size": {"type": "integer"},
                    "modified": {"type": "string"},
                },
            },
        },
        "truncated": {"type": "boolean"},
    },
}

CANCEL_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "status": {"type": "string", "enum": ["cancelled", "cancel_failed"]},
        "session_id": {"type": "string"},
        "thread_id": {"type": "string"},
    },
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _runtime_params() -> list[Any]:
    """Build pytest parameters for each runtime from environment variables."""
    params: list[Any] = []
    for name, env_var in RUNTIME_ENVS.items():
        url = os.environ.get(env_var)
        params.append(pytest.param((name, url), id=name))
    return params


def _env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


@pytest.fixture(params=_runtime_params())
def runtime_url(request: pytest.FixtureRequest) -> str:
    """Parametrized fixture that yields the base URL for each configured runtime.

    If a runtime URL is not set in the environment, the test is skipped.
    """
    name, url = request.param
    if not url:
        pytest.skip(f"{name} runtime URL not set ({RUNTIME_ENVS[name]})")
    return str(url)


@pytest.fixture
def runtime_name(request: pytest.FixtureRequest) -> str:
    """Return the human-readable name of the runtime currently under test."""
    if hasattr(request.node, "callspec") and "runtime_url" in request.node.callspec.params:
        return request.node.callspec.params["runtime_url"][0]
    return "unknown"


@pytest.fixture
def runtime_env() -> dict[str, str | None]:
    """Return a mapping of runtime names to their URLs from environment variables."""
    return {name: os.environ.get(env) for name, env in RUNTIME_ENVS.items()}


@pytest.fixture
def runtime_auth_headers() -> dict[str, str]:
    """Return authorization headers with the bearer token from RUNTIME_BEARER_TOKEN."""
    token = os.environ.get("RUNTIME_BEARER_TOKEN", "")
    if token:
        return {"Authorization": f"Bearer {token}"}
    return {}


@pytest.fixture
def runtime_client(runtime_url: str, runtime_auth_headers: dict[str, str]) -> httpx.Client:
    """Return an :class:`httpx.Client` configured for the current runtime."""
    client = httpx.Client(
        base_url=runtime_url,
        headers={**runtime_auth_headers, "Accept": "application/json"},
        timeout=RUNTIME_TIMEOUT,
    )
    yield client
    client.close()


@pytest.fixture
def unauthenticated_runtime_client(runtime_url: str) -> httpx.Client:
    client = httpx.Client(
        base_url=runtime_url,
        headers={"Accept": "application/json"},
        timeout=RUNTIME_TIMEOUT,
    )
    yield client
    client.close()


@pytest.fixture
def runtime_auth_enforced() -> bool:
    return _env_flag("RUNTIME_EXPECT_AUTH")


@pytest.fixture
def runtime_timeout_probe() -> dict[str, Any] | None:
    prompt = os.environ.get("RUNTIME_TIMEOUT_PROMPT", "").strip()
    if not prompt:
        return None
    raw_timeout = os.environ.get("RUNTIME_TIMEOUT_SECONDS", "1").strip()
    try:
        timeout_seconds = max(float(raw_timeout), 1.0)
    except ValueError:
        timeout_seconds = 1.0
    return {"prompt": prompt, "timeout_seconds": timeout_seconds}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def assert_has_fields(data: dict[str, Any], required: list[str], path: str = "response") -> None:
    """Assert that *data* contains all keys listed in *required*.

    On failure, pytest fails with a descriptive message.
    """
    missing = [field for field in required if field not in data]
    if missing:
        pytest.fail(f"{path} missing required fields: {missing}")


def validate_json_schema(data: Any, schema: dict[str, Any], path: str = "root") -> None:
    """Lightweight JSON Schema validator for conformance testing.

    Validates a subset of JSON Schema useful for API response checking:

    - ``type`` — ``object``, ``array``, ``string``, ``integer``, ``number``,
      ``boolean``, ``null``
    - ``required`` — list of required property names
    - ``properties`` — recursive sub-schemas
    - ``enum`` — allowed values
    - ``items`` — schema for array elements
    """
    if "type" in schema:
        expected = schema["type"]
        type_map: dict[str, type | tuple[type, ...]] = {
            "object": dict,
            "array": list,
            "string": str,
            "integer": int,
            "number": (int, float),
            "boolean": bool,
            "null": type(None),
        }
        if expected in type_map:
            if expected == "integer" and isinstance(data, bool):
                pytest.fail(f"{path}: expected integer, got boolean")
            if not isinstance(data, type_map[expected]):
                pytest.fail(f"{path}: expected {expected}, got {type(data).__name__}")

    if "enum" in schema and data not in schema["enum"]:
        pytest.fail(f"{path}: expected one of {schema['enum']}, got {data!r}")

    if isinstance(data, dict):
        if "required" in schema:
            for key in schema["required"]:
                if key not in data:
                    pytest.fail(f"{path}: missing required property '{key}'")
        if "properties" in schema:
            for key, sub_schema in schema["properties"].items():
                if key in data:
                    validate_json_schema(data[key], sub_schema, path=f"{path}.{key}")

    if isinstance(data, list) and "items" in schema:
        for idx, item in enumerate(data):
            validate_json_schema(item, schema["items"], path=f"{path}[{idx}]")


def parse_sse_events(text: str) -> list[dict[str, Any]]:
    """Parse an SSE ``text/event-stream`` body into a list of event dictionaries.

    Each returned dict contains:

    - ``event`` (``str``) — the event name
    - ``data`` (``Any``) — the parsed JSON payload, or the raw string if JSON
      decoding fails, or an empty dict if no data lines were present
    """
    events: list[dict[str, Any]] = []
    current_event: dict[str, Any] = {}
    current_data_lines: list[str] = []

    def _flush() -> None:
        nonlocal current_event, current_data_lines
        if current_event or current_data_lines:
            if current_data_lines:
                raw = "\n".join(current_data_lines)
                try:
                    current_event["data"] = json.loads(raw)
                except json.JSONDecodeError:
                    current_event["data"] = raw
            else:
                current_event.setdefault("data", {})
            events.append(current_event)
            current_event = {}
            current_data_lines = []

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line.startswith("event:"):
            _flush()
            current_event["event"] = line[len("event:") :].strip()
        elif line.startswith("data:"):
            current_data_lines.append(line[len("data:") :].strip())
        elif line == "":
            _flush()

    _flush()
    return events


def skip_if_tier_not_supported(runtime_client: httpx.Client, tier: str) -> None:
    """Skip the current test if the runtime does not advertise *tier* in capabilities."""
    try:
        resp = runtime_client.get("/capabilities")
    except httpx.RequestError as exc:
        pytest.skip(f"Could not reach runtime capabilities endpoint: {exc}")

    if resp.status_code == 404:
        pytest.skip("Runtime does not implement /capabilities")

    if resp.status_code != 200:
        pytest.skip(f"Capabilities endpoint returned HTTP {resp.status_code}")

    data = resp.json()
    tiers = data.get("capabilities", {}).get("tiers", [])
    if tier not in tiers:
        pytest.skip(f"Runtime does not support '{tier}' tier (supports: {tiers})")


def create_thread(
    client: httpx.Client,
    prompt: str = "Say hello",
    timeout_seconds: float = 15.0,
) -> str:
    """Invoke the runtime with *prompt* and return the resulting ``thread_id``.

    If the invoke fails or does not return a ``thread_id``, the test is skipped.
    """
    payload = {"prompt": prompt, "timeout_seconds": timeout_seconds}
    resp = client.post("/invoke", json=payload)
    if resp.status_code != 200:
        pytest.skip(f"Invoke failed with HTTP {resp.status_code}: {resp.text[:200]}")
    data = resp.json()
    thread_id = data.get("thread_id")
    if not thread_id:
        pytest.skip("Invoke response did not include thread_id")
    return str(thread_id)
