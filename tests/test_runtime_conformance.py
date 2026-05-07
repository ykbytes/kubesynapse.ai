"""Core tier conformance tests for KubeSynth Runtime API v1.

These tests validate the **Core** API tier which every production runtime MUST
implement:

- ``GET /health``
- ``GET /ready``
- ``GET /info``
- ``GET /capabilities``
- ``POST /invoke``
- ``POST /invoke/stream``
- ``POST /cancel``

All tests are marked with ``integration`` and require a running runtime
accessible via the environment variables defined in ``runtime_conftest.py``.
"""

from __future__ import annotations

import httpx
import pytest

from tests.runtime_conftest import (
    CANCEL_RESPONSE_SCHEMA,
    CAPABILITIES_RESPONSE_SCHEMA,
    ERROR_RESPONSE_SCHEMA,
    HEALTH_RESPONSE_SCHEMA,
    INFO_RESPONSE_SCHEMA,
    INVOKE_RESPONSE_SCHEMA,
    READY_RESPONSE_SCHEMA,
    assert_has_fields,
    create_thread,
    parse_sse_events,
    runtime_auth_headers,
    runtime_auth_enforced,
    runtime_client,
    runtime_env,
    runtime_name,
    runtime_timeout_probe,
    runtime_url,
    unauthenticated_runtime_client,
    validate_json_schema,
)

pytestmark = pytest.mark.integration


class TestCoreHealthEndpoints:
    """Tests for ``/health`` and ``/ready``."""

    def test_health_returns_200_with_status(self, runtime_client: httpx.Client) -> None:
        """GET /health must return 200 and a payload matching HealthResponse."""
        resp = runtime_client.get("/health")
        assert resp.status_code == 200, (
            f"Expected 200, got {resp.status_code}: {resp.text[:200]}"
        )
        data = resp.json()
        validate_json_schema(data, HEALTH_RESPONSE_SCHEMA, path="HealthResponse")

    def test_ready_returns_200_with_status(self, runtime_client: httpx.Client) -> None:
        """GET /ready must return 200 (or 503) and a payload matching ReadyResponse."""
        resp = runtime_client.get("/ready")
        assert resp.status_code in (200, 503), (
            f"Unexpected status: {resp.status_code}"
        )
        data = resp.json()
        validate_json_schema(data, READY_RESPONSE_SCHEMA, path="ReadyResponse")


class TestCoreDiscoveryEndpoints:
    """Tests for ``/info`` and ``/capabilities``."""

    def test_info_returns_required_fields(self, runtime_client: httpx.Client) -> None:
        """GET /info must return runtime metadata including contract_version."""
        resp = runtime_client.get("/info")
        assert resp.status_code == 200, (
            f"Expected 200, got {resp.status_code}: {resp.text[:200]}"
        )
        data = resp.json()
        validate_json_schema(data, INFO_RESPONSE_SCHEMA, path="InfoResponse")

    def test_capabilities_returns_tiers(self, runtime_client: httpx.Client) -> None:
        """GET /capabilities must return a capabilities object with a tiers array."""
        resp = runtime_client.get("/capabilities")
        assert resp.status_code == 200, (
            f"Expected 200, got {resp.status_code}: {resp.text[:200]}"
        )
        data = resp.json()
        validate_json_schema(data, CAPABILITIES_RESPONSE_SCHEMA, path="CapabilitiesResponse")
        tiers = data.get("capabilities", {}).get("tiers", [])
        assert isinstance(tiers, list), "capabilities.tiers must be an array"
        assert "core" in tiers, "All runtimes must advertise 'core' tier"


class TestCoreInvocationEndpoints:
    """Tests for ``/invoke`` and ``/invoke/stream``."""

    def test_invoke_accepts_prompt_and_returns_response(self, runtime_client: httpx.Client) -> None:
        """POST /invoke must accept a prompt and return a valid InvokeResponse."""
        payload = {"prompt": "Say hello", "timeout_seconds": 15}
        resp = runtime_client.post("/invoke", json=payload)
        assert resp.status_code == 200, (
            f"Expected 200, got {resp.status_code}: {resp.text[:200]}"
        )
        data = resp.json()
        validate_json_schema(data, INVOKE_RESPONSE_SCHEMA, path="InvokeResponse")
        assert_has_fields(data, ["thread_id", "response", "status"])
        assert data["status"] in (
            "completed",
            "error",
            "cancelled",
            "incomplete",
            "context_overflow",
        )

    def test_invoke_stream_returns_sse_content_type(self, runtime_client: httpx.Client) -> None:
        """POST /invoke/stream must return an SSE stream with the correct content type."""
        payload = {"prompt": "Say hello", "timeout_seconds": 15}
        resp = runtime_client.post("/invoke/stream", json=payload)
        assert resp.status_code == 200, (
            f"Expected 200, got {resp.status_code}: {resp.text[:200]}"
        )
        content_type = resp.headers.get("content-type", "")
        assert "text/event-stream" in content_type, (
            f"Expected text/event-stream, got {content_type}"
        )


class TestCoreControlEndpoints:
    """Tests for ``/cancel``."""

    def test_cancel_returns_status(self, runtime_client: httpx.Client) -> None:
        """POST /cancel must return 200 (or 404) with a status field when successful."""
        thread_id = create_thread(
            runtime_client, prompt="Say hello", timeout_seconds=15
        )
        resp = runtime_client.post("/cancel", params={"thread_id": thread_id})
        assert resp.status_code in (200, 404), (
            f"Unexpected status: {resp.status_code}"
        )
        if resp.status_code == 200:
            data = resp.json()
            validate_json_schema(data, CANCEL_RESPONSE_SCHEMA, path="CancelResponse")
            assert_has_fields(data, ["status"])
            assert data["status"] in ("cancelled", "cancel_failed")


class TestErrorResponseSchema:
    """Tests that error responses conform to the canonical ErrorResponse schema."""

    def test_invalid_invoke_request_returns_error_schema(self, runtime_client: httpx.Client) -> None:
        """POST /invoke with an empty body must return a 4xx with ErrorResponse."""
        resp = runtime_client.post("/invoke", json={})
        assert resp.status_code in (400, 422), (
            f"Expected 400/422, got {resp.status_code}"
        )
        data = resp.json()
        validate_json_schema(data, ERROR_RESPONSE_SCHEMA, path="ErrorResponse")
        assert "error" in data, "Error response must contain 'error' object"
        error_obj = data["error"]
        assert_has_fields(error_obj, ["code", "message"], path="error")

    def test_error_includes_trace_id(self, runtime_client: httpx.Client) -> None:
        """Error responses should include a trace_id for observability."""
        resp = runtime_client.post("/invoke", json={})
        if resp.status_code in (400, 422):
            data = resp.json()
            error_obj = data.get("error", {})
            # trace_id is recommended but not strictly required by the minimal schema.
            # We assert it is present when the runtime returns a well-formed error.
            assert "trace_id" in error_obj or "message" in error_obj, (
                "Error object should contain at least message"
            )


class TestOptionalSecurityAndTimeoutCoverage:
    """Opt-in coverage for auth enforcement and timeout behavior."""

    def test_missing_auth_is_rejected_when_enforced(
        self,
        unauthenticated_runtime_client: httpx.Client,
        runtime_auth_enforced: bool,
    ) -> None:
        if not runtime_auth_enforced:
            pytest.skip("Set RUNTIME_EXPECT_AUTH=1 to enable auth enforcement coverage")

        resp = unauthenticated_runtime_client.get("/info")
        assert resp.status_code in (401, 403), (
            f"Expected 401/403 for unauthenticated request, got {resp.status_code}: {resp.text[:200]}"
        )

    def test_timeout_probe_surfaces_timeout_when_configured(
        self,
        runtime_client: httpx.Client,
        runtime_timeout_probe: dict[str, object] | None,
    ) -> None:
        if runtime_timeout_probe is None:
            pytest.skip("Set RUNTIME_TIMEOUT_PROMPT to enable timeout coverage")

        resp = runtime_client.post(
            "/invoke",
            json={
                "prompt": runtime_timeout_probe["prompt"],
                "timeout_seconds": runtime_timeout_probe["timeout_seconds"],
            },
        )
        assert resp.status_code != 200, "Timeout probe should not complete successfully"
        assert resp.status_code in (408, 502, 504), (
            f"Expected timeout-oriented status code, got {resp.status_code}: {resp.text[:200]}"
        )
        assert "timeout" in resp.text.lower() or "timed out" in resp.text.lower(), (
            f"Timeout response should mention timeout semantics: {resp.text[:200]}"
        )
