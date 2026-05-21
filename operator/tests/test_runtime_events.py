from __future__ import annotations

import importlib
import os
import sys
import time
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _fresh_runtime_events_module():
    sys.modules.pop("runtime_events", None)
    return importlib.import_module("runtime_events")


def test_runtime_events_flush_on_idle_timeout() -> None:
    os.environ["API_GATEWAY_URL"] = "http://gateway.example"
    os.environ["WORKER_TRACE_TOKEN"] = "test-token"
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
        runtime_events.start_emitter()
        runtime_events.emit_workflow_started("exec-idle-flush", workflow_name="wf", namespace="default", run_id="run-1")

        deadline = time.time() + 1.0
        while time.time() < deadline and not posts:
            time.sleep(0.02)

        runtime_events.stop_emitter()

    assert posts, "expected idle flush to send runtime events without waiting for shutdown"
    assert posts[0]["url"] == "http://gateway.example/api/v1/traces/runtime-events"
    events = posts[0]["json"]["events"]
    assert len(events) == 1
    assert events[0]["execution_id"] == "exec-idle-flush"
    assert events[0]["event_type"] == "run.started"


def test_runtime_events_use_internal_gateway_url_fallback() -> None:
    os.environ.pop("API_GATEWAY_URL", None)
    os.environ.pop("GATEWAY_URL", None)
    os.environ["API_GATEWAY_INTERNAL_URL"] = "http://gateway.internal"
    os.environ["WORKER_TRACE_TOKEN"] = "test-token"
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
        runtime_events.start_emitter()
        runtime_events.emit_workflow_started("exec-internal-url", workflow_name="wf", namespace="default", run_id="run-1")

        deadline = time.time() + 1.0
        while time.time() < deadline and not posts:
            time.sleep(0.02)

        runtime_events.stop_emitter()

    assert posts, "expected internal gateway URL fallback to enable runtime event emission"
    assert posts[0]["url"] == "http://gateway.internal/api/v1/traces/runtime-events"
    events = posts[0]["json"]["events"]
    assert len(events) == 1
    assert events[0]["execution_id"] == "exec-internal-url"


def test_runtime_events_stop_drains_pending_batch() -> None:
    os.environ["API_GATEWAY_URL"] = "http://gateway.example"
    os.environ["WORKER_TRACE_TOKEN"] = "test-token"
    os.environ["RUNTIME_EVENTS_FLUSH_INTERVAL"] = "60"
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
        runtime_events.start_emitter()
        runtime_events.emit_workflow_started("exec-stop-flush", workflow_name="wf", namespace="default", run_id="run-1")

        # Let the background thread pull the event into its local batch without
        # waiting for the idle timeout flush.
        time.sleep(0.05)
        runtime_events._running = False
        runtime_events.stop_emitter()

    assert posts, "expected stop_emitter to flush pending runtime events"
    assert posts[0]["url"] == "http://gateway.example/api/v1/traces/runtime-events"
    events = posts[0]["json"]["events"]
    assert len(events) == 1
    assert events[0]["execution_id"] == "exec-stop-flush"
    assert events[0]["event_type"] == "run.started"
