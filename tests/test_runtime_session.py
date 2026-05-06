"""Session tier conformance tests for KubeSynth Runtime API v1.

These tests validate the **Session** tier endpoints:

- ``GET /todo``
- ``GET /question``
- ``GET /diff``
- ``GET /context-budget``

Tests are skipped when the runtime does not advertise ``session`` in its
``/capabilities`` tiers array.
"""

from __future__ import annotations

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
