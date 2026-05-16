"""Session tier conformance tests for KubeSynapse Runtime API v1.

These tests validate the **Session** tier endpoints:

- ``GET /todo``
- ``GET /question``
- ``GET /diff``
- ``GET /context-budget``

Tests are skipped when the runtime does not advertise ``session`` in its
``/capabilities`` tiers array.
"""

from __future__ import annotations

import uuid

import httpx
import pytest

from tests.runtime_conftest import (
    CONTEXT_BUDGET_RESPONSE_SCHEMA,
    DIFF_RESPONSE_SCHEMA,
    TODO_RESPONSE_SCHEMA,
    assert_has_fields,
    create_thread,
    runtime_client,
    skip_if_tier_not_supported,
    validate_json_schema,
)

pytestmark = pytest.mark.integration


class TestSessionTierEndpoints:
    """Tests for session management endpoints."""

    def test_todo_returns_todos_array(self, runtime_client: httpx.Client) -> None:
        """GET /todo must return a todo list with thread_id and todos array."""
        skip_if_tier_not_supported(runtime_client, "session")
        thread_id = create_thread(
            runtime_client, prompt="Say hello", timeout_seconds=15
        )
        resp = runtime_client.get("/todo", params={"thread_id": thread_id})
        assert resp.status_code in (200, 404), (
            f"Unexpected status: {resp.status_code}"
        )
        if resp.status_code == 200:
            data = resp.json()
            validate_json_schema(data, TODO_RESPONSE_SCHEMA, path="TodoResponse")
            assert_has_fields(data, ["todos", "thread_id"])
            assert isinstance(data["todos"], list)

    def test_question_returns_array(self, runtime_client: httpx.Client) -> None:
        """GET /question must return an array of pending questions."""
        skip_if_tier_not_supported(runtime_client, "session")
        resp = runtime_client.get("/question")
        assert resp.status_code in (200, 404), (
            f"Unexpected status: {resp.status_code}"
        )
        if resp.status_code == 200:
            data = resp.json()
            assert isinstance(data, list), "GET /question must return an array"

    def test_diff_returns_diff_string(self, runtime_client: httpx.Client) -> None:
        """GET /diff must return a diff string with thread_id."""
        skip_if_tier_not_supported(runtime_client, "session")
        thread_id = create_thread(
            runtime_client, prompt="Say hello", timeout_seconds=15
        )
        resp = runtime_client.get("/diff", params={"thread_id": thread_id})
        assert resp.status_code in (200, 404), (
            f"Unexpected status: {resp.status_code}"
        )
        if resp.status_code == 200:
            data = resp.json()
            validate_json_schema(data, DIFF_RESPONSE_SCHEMA, path="DiffResponse")
            assert_has_fields(data, ["diff", "thread_id"])
            assert isinstance(data["diff"], str)

    def test_context_budget_returns_budget_fields(self, runtime_client: httpx.Client) -> None:
        """GET /context-budget must return token budget telemetry."""
        skip_if_tier_not_supported(runtime_client, "session")
        thread_id = create_thread(
            runtime_client, prompt="Say hello", timeout_seconds=15
        )
        resp = runtime_client.get("/context-budget", params={"thread_id": thread_id})
        assert resp.status_code in (200, 404), (
            f"Unexpected status: {resp.status_code}"
        )
        if resp.status_code == 200:
            data = resp.json()
            validate_json_schema(
                data, CONTEXT_BUDGET_RESPONSE_SCHEMA, path="ContextBudgetResponse"
            )
            assert_has_fields(
                data,
                [
                    "model_context_limit",
                    "tokens_used",
                    "tokens_remaining",
                    "usage_percent",
                    "status",
                ],
            )
            assert data["status"] in ("ok", "warning", "critical", "overflow")

    def test_reused_thread_keeps_session_identity_when_continuity_is_supported(self, runtime_client: httpx.Client) -> None:
        """Repeated invokes with the same thread_id should keep the same logical session when the runtime exposes continuity."""
        skip_if_tier_not_supported(runtime_client, "session")
        thread_id = f"continuity-{uuid.uuid4().hex[:12]}"

        first = runtime_client.post(
            "/invoke",
            json={"prompt": "Say hello", "thread_id": thread_id, "timeout_seconds": 15},
        )
        if first.status_code != 200:
            pytest.skip(f"First invoke failed with HTTP {first.status_code}: {first.text[:200]}")

        todo_first = runtime_client.get("/todo", params={"thread_id": thread_id})
        second = runtime_client.post(
            "/invoke",
            json={"prompt": "Continue", "thread_id": thread_id, "timeout_seconds": 15},
        )
        if second.status_code != 200:
            pytest.skip(f"Second invoke failed with HTTP {second.status_code}: {second.text[:200]}")

        todo_second = runtime_client.get("/todo", params={"thread_id": thread_id})
        first_data = first.json()
        second_data = second.json()
        first_continuity = first_data.get("continuity")
        second_continuity = second_data.get("continuity")
        if not isinstance(first_continuity, dict) or not isinstance(second_continuity, dict):
            pytest.skip("Runtime does not expose continuity metadata")

        assert first_continuity.get("created_new_session") is True, first_continuity
        assert second_continuity.get("created_new_session") is False, second_continuity

        if todo_first.status_code == 200 and todo_second.status_code == 200:
            first_session_id = todo_first.json().get("session_id")
            second_session_id = todo_second.json().get("session_id")
            if first_session_id and second_session_id:
                assert first_session_id == second_session_id, (
                    f"Expected stable session_id for reused thread_id, got {first_session_id!r} and {second_session_id!r}"
                )
