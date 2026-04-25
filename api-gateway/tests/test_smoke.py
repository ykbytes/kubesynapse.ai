"""Smoke tests for api-gateway.

These tests verify the most critical endpoints and auth flow without
requiring a real Kubernetes cluster or database.
"""

from __future__ import annotations

from fastapi.testclient import TestClient


class TestHealthEndpoints:
    """Tests for /api/health and /api/ready."""

    def test_health_returns_200(self, client: TestClient) -> None:
        """The health endpoint should always return 200."""
        response = client.get("/api/health")
        assert response.status_code == 200
        data = response.json()
        assert data.get("status") == "healthy"

    def test_ready_returns_200_or_503(self, client: TestClient) -> None:
        """The ready endpoint should return 200 when ready, 503 otherwise."""
        response = client.get("/api/ready")
        assert response.status_code in {200, 503}
        data = response.json()
        assert "status" in data


class TestAuthMiddleware:
    """Tests for authentication and authorization."""

    def test_missing_token_returns_401(self, client: TestClient) -> None:
        """Requests without a valid token should be rejected."""
        response = client.get("/api/agents")
        assert response.status_code == 401
        data = response.json()
        assert "detail" in data or "error" in data

    def test_invalid_token_returns_401(self, client: TestClient) -> None:
        """Requests with an invalid token should be rejected."""
        response = client.get(
            "/api/agents",
            headers={"Authorization": "Bearer invalid-token"},
        )
        assert response.status_code == 401

    def test_valid_token_returns_200(self, client: TestClient, auth_headers: dict) -> None:
        """Requests with the valid shared token should succeed."""
        response = client.get("/api/agents", headers=auth_headers)
        # May return 200 or 404 depending on mock state, but should not be 401
        assert response.status_code != 401


class TestAgentCRUD:
    """Smoke tests for agent list and retrieval endpoints."""

    def test_list_agents_with_auth(self, client: TestClient, auth_headers: dict) -> None:
        """Authenticated requests to list agents should not return 401."""
        response = client.get("/api/agents", headers=auth_headers)
        assert response.status_code in {200, 404, 500}
        if response.status_code == 200:
            data = response.json()
            assert isinstance(data, list)

    def test_get_agent_by_name_with_auth(self, client: TestClient, auth_headers: dict) -> None:
        """Authenticated requests to get an agent should not return 401."""
        response = client.get("/api/agents/nonexistent-agent", headers=auth_headers)
        assert response.status_code in {200, 404, 500}


class TestPrometheusMetrics:
    """Smoke test for Prometheus metrics endpoint."""

    def test_metrics_endpoint_returns_200(self, client: TestClient) -> None:
        """The /metrics endpoint should be accessible without auth and return Prometheus text."""
        response = client.get("/metrics")
        assert response.status_code == 200
        content_type = response.headers.get("content-type", "")
        assert "text/plain" in content_type or "application/openmetrics" in content_type


class TestTraceEndpoints:
    """Smoke tests for Execution Observatory trace endpoints."""

    def test_list_traces_without_auth_returns_401(self, client: TestClient) -> None:
        """Requests without auth to trace endpoints should be rejected."""
        response = client.get("/api/traces/executions")
        assert response.status_code == 401

    def test_list_traces_with_auth(self, client: TestClient, auth_headers: dict) -> None:
        """Authenticated requests to list traces should not return 401."""
        response = client.get("/api/traces/executions", headers=auth_headers)
        assert response.status_code in {200, 404, 500}

    def test_get_trace_detail_without_auth_returns_401(self, client: TestClient) -> None:
        """Requests without auth to trace detail should be rejected."""
        response = client.get("/api/traces/executions/exec-nonexistent")
        assert response.status_code == 401

    def test_get_trace_detail_with_auth(self, client: TestClient, auth_headers: dict) -> None:
        """Authenticated requests to trace detail should not return 401."""
        response = client.get("/api/traces/executions/exec-nonexistent", headers=auth_headers)
        assert response.status_code in {200, 404, 500}

    def test_batch_ingest_without_auth_returns_401(self, client: TestClient) -> None:
        """Requests without auth to batch ingest should be rejected."""
        response = client.post("/api/traces/batch", json={"events": []})
        assert response.status_code == 401
