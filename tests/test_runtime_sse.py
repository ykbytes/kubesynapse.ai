"""SSE event taxonomy conformance tests for KubeSynapse Runtime API v1.

These tests validate that ``POST /invoke/stream`` produces Server-Sent Events
following the canonical taxonomy defined in the Runtime API contract:

- ``response.started``
- ``response.delta``
- ``response.tool_call``
- ``response.tool_result``
- ``todo.updated``
- ``question.asked``
- ``todo.cleared``
- ``response.completed``
- ``response.error``

Key rules enforced:

1. Every stream MUST end with ``response.completed`` or ``response.error``.
2. ``response.started`` MUST be the first event.
3. ``response.delta`` events MUST concatenate in order to form the full text.
"""

from __future__ import annotations

import httpx
import pytest

from tests.runtime_conftest import (
    CANONICAL_SSE_EVENTS,
    assert_has_fields,
    parse_sse_events,
    runtime_client,
)

pytestmark = pytest.mark.integration


class TestSSEEventTaxonomy:
    """Tests that SSE streams follow the canonical event taxonomy."""

    def test_stream_uses_canonical_event_names(self, runtime_client: httpx.Client) -> None:
        """All events in the stream must belong to the canonical taxonomy."""
        payload = {"prompt": "Say hello", "timeout_seconds": 15}
        resp = runtime_client.post("/invoke/stream", json=payload)
        assert resp.status_code == 200, (
            f"Expected 200, got {resp.status_code}: {resp.text[:200]}"
        )
        events = parse_sse_events(resp.text)
        non_canonical = [
            e["event"] for e in events if e.get("event") not in CANONICAL_SSE_EVENTS
        ]
        assert not non_canonical, (
            f"Non-canonical SSE events found: {non_canonical}"
        )

    def test_stream_starts_with_response_started(self, runtime_client: httpx.Client) -> None:
        """The first event in every stream MUST be ``response.started``."""
        payload = {"prompt": "Say hello", "timeout_seconds": 15}
        resp = runtime_client.post("/invoke/stream", json=payload)
        assert resp.status_code == 200, (
            f"Expected 200, got {resp.status_code}: {resp.text[:200]}"
        )
        events = parse_sse_events(resp.text)
        assert events, "Stream must contain at least one event"
        first_event = events[0]
        assert first_event.get("event") == "response.started", (
            f"First event must be response.started, got {first_event.get('event')}"
        )
        data = first_event.get("data", {})
        assert_has_fields(
            data, ["session_id", "model", "thread_id"], path="response.started payload"
        )

    def test_stream_ends_with_completed_or_error(self, runtime_client: httpx.Client) -> None:
        """The last event in every stream MUST be ``response.completed`` or ``response.error``."""
        payload = {"prompt": "Say hello", "timeout_seconds": 15}
        resp = runtime_client.post("/invoke/stream", json=payload)
        assert resp.status_code == 200, (
            f"Expected 200, got {resp.status_code}: {resp.text[:200]}"
        )
        events = parse_sse_events(resp.text)
        assert events, "Stream must contain at least one event"
        last_event = events[-1]
        assert last_event.get("event") in ("response.completed", "response.error"), (
            f"Last event must be response.completed or response.error, got {last_event.get('event')}"
        )

    def test_delta_events_concatenate_to_response_text(self, runtime_client: httpx.Client) -> None:
        """``response.delta`` events must carry ``text`` and ``session_id`` and concatenate to non-empty text."""
        payload = {"prompt": "Say hello", "timeout_seconds": 15}
        resp = runtime_client.post("/invoke/stream", json=payload)
        assert resp.status_code == 200, (
            f"Expected 200, got {resp.status_code}: {resp.text[:200]}"
        )
        events = parse_sse_events(resp.text)
        delta_events = [e for e in events if e.get("event") == "response.delta"]
        for evt in delta_events:
            data = evt.get("data", {})
            assert "text" in data, "response.delta payload must include 'text'"
            assert isinstance(data["text"], str), "response.delta text must be a string"
            assert "session_id" in data, "response.delta payload must include 'session_id'"

        if delta_events:
            full_text = "".join(e["data"]["text"] for e in delta_events)
            assert full_text, "Concatenated delta text should not be empty"

    def test_completed_event_has_required_payload(self, runtime_client: httpx.Client) -> None:
        """If ``response.completed`` is emitted, it must include the required payload fields."""
        payload = {"prompt": "Say hello", "timeout_seconds": 15}
        resp = runtime_client.post("/invoke/stream", json=payload)
        assert resp.status_code == 200, (
            f"Expected 200, got {resp.status_code}: {resp.text[:200]}"
        )
        events = parse_sse_events(resp.text)
        completed_events = [
            e for e in events if e.get("event") == "response.completed"
        ]
        if completed_events:
            data = completed_events[-1].get("data", {})
            assert_has_fields(
                data, ["session_id", "tokens", "status"], path="response.completed payload"
            )

    def test_error_event_has_required_payload(self, runtime_client: httpx.Client) -> None:
        """If ``response.error`` is emitted, it must include the required payload fields."""
        payload = {"prompt": "Say hello", "timeout_seconds": 15}
        resp = runtime_client.post("/invoke/stream", json=payload)
        assert resp.status_code == 200, (
            f"Expected 200, got {resp.status_code}: {resp.text[:200]}"
        )
        events = parse_sse_events(resp.text)
        error_events = [e for e in events if e.get("event") == "response.error"]
        if error_events:
            data = error_events[-1].get("data", {})
            assert_has_fields(
                data, ["session_id", "error", "code"], path="response.error payload"
            )

    def test_tool_events_have_required_payloads_when_present(self, runtime_client: httpx.Client) -> None:
        """Tool-call and tool-result events must carry the required fields when emitted."""
        payload = {"prompt": "Say hello", "timeout_seconds": 15}
        resp = runtime_client.post("/invoke/stream", json=payload)
        assert resp.status_code == 200, (
            f"Expected 200, got {resp.status_code}: {resp.text[:200]}"
        )

        events = parse_sse_events(resp.text)
        tool_call_events = [e for e in events if e.get("event") == "response.tool_call"]
        tool_result_events = [e for e in events if e.get("event") == "response.tool_result"]

        for evt in tool_call_events:
            data = evt.get("data", {})
            assert_has_fields(data, ["name", "id", "session_id"], path="response.tool_call payload")
            assert isinstance(data["name"], str) and data["name"], "response.tool_call name must be a non-empty string"

        for evt in tool_result_events:
            data = evt.get("data", {})
            assert_has_fields(data, ["id", "result", "status", "session_id"], path="response.tool_result payload")
            assert data["status"] in ("completed", "error", "cancelled"), (
                f"response.tool_result status must be completed/error/cancelled, got {data['status']}"
            )
