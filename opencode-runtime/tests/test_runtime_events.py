from __future__ import annotations

import importlib
import os
import sys
import sysconfig
import time
from pathlib import Path
from unittest.mock import patch

import importlib_metadata
from importlib_metadata.compat import py39 as importlib_metadata_py39

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

_stdlib_operator_path = Path(sysconfig.get_paths()["stdlib"]) / "operator.py"
_operator_spec = importlib.util.spec_from_file_location("python_stdlib_operator", _stdlib_operator_path)
if _operator_spec is None or _operator_spec.loader is None:
    raise RuntimeError("Failed to load stdlib operator module for runtime event tests")
_stdlib_operator = importlib.util.module_from_spec(_operator_spec)
_operator_spec.loader.exec_module(_stdlib_operator)
sys.modules["operator"] = _stdlib_operator
importlib_metadata.operator = _stdlib_operator
importlib_metadata_py39.operator = _stdlib_operator


def _fresh_runtime_events_module():
    sys.modules.pop("runtime_events", None)
    return importlib.import_module("runtime_events")


def test_sync_runtime_events_flush_on_idle_timeout() -> None:
    os.environ["API_GATEWAY_INTERNAL_URL"] = "http://gateway.example"
    os.environ["API_GATEWAY_SHARED_TOKEN"] = "test-token"
    os.environ["RUNTIME_EVENTS_FLUSH_INTERVAL"] = "0.01"
    os.environ["RUNTIME_EVENTS_BATCH_SIZE"] = "50"

    runtime_events = _fresh_runtime_events_module()
    posts: list[dict] = []

    class _Response:
        status_code = 201

    def _fake_post(url, json, headers, timeout):
        posts.append({
            "url": url,
            "json": {"events": list(json.get("events", []))},
            "headers": headers,
            "timeout": timeout,
        })
        return _Response()

    with patch.object(runtime_events.httpx, "post", side_effect=_fake_post):
        runtime_events.start_sync_emitter()
        runtime_events.emit_run_started("exec-idle-flush", thread_id="thread-1", model="gpt-4")

        deadline = time.time() + 1.0
        while time.time() < deadline and not posts:
            time.sleep(0.02)

        runtime_events.stop_sync_emitter()

    assert posts, "expected idle flush to send runtime events without waiting for explicit flush"
    assert posts[0]["url"] == "http://gateway.example/api/v1/traces/runtime-events"
    events = posts[0]["json"]["events"]
    assert len(events) == 1
    assert events[0]["execution_id"] == "exec-idle-flush"
    assert events[0]["event_type"] == "run.started"


def test_runtime_events_send_identity_header_when_secret_configured() -> None:
    """§security-R5: When RUNTIME_IDENTITY_HMAC_SECRET is configured, the
    runtime includes the X-Runtime-Identity header on api-gateway calls.
    This binds the shared token to a specific agent + namespace so a
    leaked shared token cannot be reused against other agents."""
    os.environ["API_GATEWAY_INTERNAL_URL"] = "http://gateway.example"
    os.environ["API_GATEWAY_SHARED_TOKEN"] = "test-token"
    os.environ["RUNTIME_IDENTITY_HMAC_SECRET"] = "test-identity-secret"
    os.environ["AGENT_NAME"] = "agent-1"
    os.environ["AGENT_NAMESPACE"] = "tenant-a"
    os.environ["RUNTIME_EVENTS_FLUSH_INTERVAL"] = "0.01"

    runtime_events = _fresh_runtime_events_module()
    posts: list[dict] = []

    class _Response:
        status_code = 201

    def _fake_post(url, json, headers, timeout):
        posts.append({"url": url, "headers": headers})
        return _Response()

    with patch.object(runtime_events.httpx, "post", side_effect=_fake_post):
        runtime_events.start_sync_emitter()
        runtime_events.emit_run_started("exec-identity", thread_id="thread-1", model="gpt-4")
        deadline = time.time() + 1.0
        while time.time() < deadline and not posts:
            time.time() and time.sleep(0.02)
        runtime_events.stop_sync_emitter()

    assert posts
    identity = posts[0]["headers"].get("X-Runtime-Identity")
    assert identity is not None
    parts = identity.split(":")
    assert len(parts) == 3
    assert parts[0] == "agent-1"
    assert parts[1] == "tenant-a"
    assert len(parts[2]) == 64  # sha256 hex digest


def test_runtime_events_omit_identity_header_when_secret_unset() -> None:
    """When RUNTIME_IDENTITY_HMAC_SECRET is empty, no identity header is
    sent and the api-gateway falls back to the unscoped principal."""
    os.environ["API_GATEWAY_INTERNAL_URL"] = "http://gateway.example"
    os.environ["API_GATEWAY_SHARED_TOKEN"] = "test-token"
    os.environ.pop("RUNTIME_IDENTITY_HMAC_SECRET", None)
    os.environ["AGENT_NAME"] = "agent-1"
    os.environ["AGENT_NAMESPACE"] = "tenant-a"
    os.environ["RUNTIME_EVENTS_FLUSH_INTERVAL"] = "0.01"

    runtime_events = _fresh_runtime_events_module()
    posts: list[dict] = []

    class _Response:
        status_code = 201

    def _fake_post(url, json, headers, timeout):
        posts.append({"url": url, "headers": headers})
        return _Response()

    with patch.object(runtime_events.httpx, "post", side_effect=_fake_post):
        runtime_events.start_sync_emitter()
        runtime_events.emit_run_started("exec-no-identity", thread_id="thread-1", model="gpt-4")
        deadline = time.time() + 1.0
        while time.time() < deadline and not posts:
            time.sleep(0.02)
        runtime_events.stop_sync_emitter()

    assert posts
    assert "X-Runtime-Identity" not in posts[0]["headers"]
