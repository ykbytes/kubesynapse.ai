"""Smoke tests for api-gateway.

These tests verify the most critical endpoints and auth flow without
requiring a real Kubernetes cluster or database.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from auth_store import db_session

import trace_store
import traces_router


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

    def test_legacy_trace_list_alias_returns_deprecation_headers(
        self, client: TestClient, auth_headers: dict
    ) -> None:
        """The legacy trace list alias should keep working while advertising the canonical route."""
        with patch.object(trace_store, "list_executions", return_value=[]):
            response = client.get("/api/v1/traces?limit=1", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        assert response.headers.get("Deprecation") == "true"
        assert response.headers.get("Sunset")
        assert "/api/v1/traces/executions?limit=1" in response.headers.get("Link", "")

    def test_get_trace_detail_without_auth_returns_401(self, client: TestClient) -> None:
        """Requests without auth to trace detail should be rejected."""
        response = client.get("/api/traces/executions/exec-nonexistent")
        assert response.status_code == 401

    def test_get_trace_detail_with_auth(self, client: TestClient, auth_headers: dict) -> None:
        """Authenticated requests to trace detail should not return 401."""
        response = client.get("/api/traces/executions/exec-nonexistent", headers=auth_headers)
        assert response.status_code in {200, 404, 500}

    def test_legacy_trace_detail_alias_returns_execution_payload(
        self, client: TestClient, auth_headers: dict
    ) -> None:
        """The legacy trace detail alias should serve the canonical execution payload."""
        execution_id = f"exec-{uuid.uuid4().hex[:12]}"
        execution = {
            "id": execution_id,
            "namespace": "default",
            "workflow_name": "observatory-demo",
            "agent_name": "observatory-demo",
            "run_id": "wf-run-alias-detail",
            "status": "completed",
            "started_at": None,
            "completed_at": None,
            "duration_ms": None,
            "input_summary": None,
            "output_summary": None,
            "total_steps": 0,
            "completed_steps": 0,
            "failed_steps": 0,
            "total_llm_calls": 0,
            "total_tool_calls": 0,
            "total_tokens": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "estimated_cost_usd": None,
            "triggered_by": None,
            "error_message": None,
            "trace_file_path": None,
            "steps": [],
            "llm_calls": [],
            "tool_calls": [],
            "events": [],
        }

        with patch.object(trace_store, "get_execution", return_value=execution):
            response = client.get(f"/api/v1/traces/{execution_id}", headers=auth_headers)
            assert response.status_code == 200
            data = response.json()
            assert data["id"] == execution_id
            assert response.headers.get("Deprecation") == "true"
            assert f"/api/v1/traces/executions/{execution_id}" in response.headers.get("Link", "")

    def test_batch_ingest_without_auth_returns_401(self, client: TestClient) -> None:
        """Requests without auth to batch ingest should be rejected."""
        response = client.post("/api/traces/batch", json={"events": []})
        assert response.status_code == 401

    def test_batch_ingest_persists_step_timing_and_order(self, client: TestClient, auth_headers: dict) -> None:
        """Batch ingest helpers should preserve step order and derive duration from event timestamps."""
        trace_store.init_trace_database()
        execution_id = f"exec-{uuid.uuid4().hex[:12]}"
        step_id = f"step-{uuid.uuid4().hex[:12]}"

        events = [
            {
                "event_type": "execution_started",
                "execution_id": execution_id,
                "timestamp": 1000,
                "payload": {
                    "namespace": "default",
                    "workflow_name": "observatory-demo",
                    "agent_name": "observatory-demo",
                    "run_id": "wf-run-test",
                    "inputs": {"input": "hello"},
                    "triggered_by": "test",
                },
            },
            {
                "event_type": "step_started",
                "execution_id": execution_id,
                "step_id": step_id,
                "timestamp": 1001,
                "payload": {
                    "step_name": "verify",
                    "step_type": "agent",
                    "step_index": 3,
                    "inputs": {"step": "verify"},
                },
            },
            {
                "event_type": "step_completed",
                "execution_id": execution_id,
                "step_id": step_id,
                "timestamp": 1004,
                "payload": {
                    "status": "completed",
                    "outputs": {"ok": True},
                },
            },
        ]

        with db_session() as session:
            for event in events:
                traces_router._upsert_from_event(session, event)

        payload = trace_store.get_execution(execution_id)
        assert payload is not None
        assert payload["total_steps"] == 1
        assert len(payload["steps"]) == 1
        assert payload["steps"][0]["step_index"] == 3
        assert payload["steps"][0]["started_at"] is not None
        assert payload["steps"][0]["duration_ms"] is not None
        assert payload["steps"][0]["duration_ms"] == 3000.0

        with db_session() as session:
            step = session.query(trace_store.StepExecution).filter_by(id=step_id).one()
            session.delete(step)
            execution = session.query(trace_store.WorkflowExecution).filter_by(id=execution_id).one()
            session.delete(execution)

    def test_execution_events_survive_missing_jsonl_file(self, client: TestClient, auth_headers: dict) -> None:
        """Raw execution events should still be readable after pod-local trace files are gone."""
        trace_store.init_trace_database()
        execution_id = f"exec-{uuid.uuid4().hex[:12]}"

        events = [
            {
                "event_type": "execution_started",
                "execution_id": execution_id,
                "timestamp": 2000,
                "payload": {
                    "namespace": "default",
                    "workflow_name": "observatory-demo",
                    "agent_name": "observatory-demo",
                    "run_id": "wf-run-durable-events",
                },
            },
            {
                "event_type": "execution_completed",
                "execution_id": execution_id,
                "timestamp": 2002,
                "payload": {
                    "status": "completed",
                    "outputs": {"ok": True},
                },
            },
        ]

        for event in events:
            trace_store.TRACER._get_writer(execution_id).emit(
                trace_store.TraceEvent(
                    event_type=trace_store.EventType(event["event_type"]),
                    execution_id=execution_id,
                    step_id=event.get("step_id"),
                    timestamp=event["timestamp"],
                    payload=event["payload"],
                )
            )

        with db_session() as session:
            for event in events:
                traces_router._upsert_from_event(session, event)

        trace_path = Path(trace_store.TRACE_STORAGE_DIR) / execution_id / "trace.jsonl"
        if trace_path.exists():
            trace_path.unlink()

        summary = trace_store.get_execution_summary(execution_id)
        assert summary is not None

        payload = trace_store.read_trace_events(execution_id) or trace_store.TRACER.read_trace(execution_id)
        assert len(payload) == 2
        assert payload[0]["event_type"] == "execution_started"
        assert payload[1]["event_type"] == "execution_completed"

        with db_session() as session:
            (
                session.query(trace_store.ExecutionTraceEventRecord)
                .filter_by(execution_id=execution_id)
                .delete(synchronize_session=False)
            )
            execution = session.query(trace_store.WorkflowExecution).filter_by(id=execution_id).one()
            session.delete(execution)
