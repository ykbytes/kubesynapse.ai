"""Smoke tests for api-gateway.

These tests verify the most critical endpoints and auth flow without
requiring a real Kubernetes cluster or database.
"""

from __future__ import annotations

import uuid
import time
from pathlib import Path
from unittest.mock import MagicMock
from unittest.mock import patch

import trace_store
import traces_router
from fastapi.testclient import TestClient

import pytest
import routers.admin as admin_router

from auth_store import db_session


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

    def test_ready_returns_503_when_litellm_is_unavailable(self, client: TestClient) -> None:
        """LiteLLM failures should degrade readiness."""

        class _FailingAsyncClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def get(self, *args, **kwargs):
                raise RuntimeError("litellm unavailable")

        with patch("routers.admin.httpx.AsyncClient", return_value=_FailingAsyncClient()):
            response = client.get("/api/ready")

        assert response.status_code == 503
        assert response.json()["checks"]["litellm"] == "error"

    def test_ready_bounds_slow_database_dependency_check(self, client: TestClient) -> None:
        """A slow database check should not make the readiness probe hang."""

        admin_router._READY_CACHE["expires_at"] = 0.0

        class _HealthyAsyncClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def get(self, *args, **kwargs):
                return MagicMock(status_code=200)

        def _slow_database_check() -> bool:
            time.sleep(0.25)
            return True

        started_at = time.monotonic()
        with (
            patch("routers.admin._READY_DEPENDENCY_TIMEOUT_SECONDS", 0.01),
            patch("routers.admin._check_database_ready_sync", side_effect=_slow_database_check),
            patch("routers.admin.httpx.AsyncClient", return_value=_HealthyAsyncClient()),
        ):
            response = client.get("/api/ready")
        elapsed = time.monotonic() - started_at

        assert elapsed < 0.2
        assert response.status_code == 503
        assert response.json()["checks"]["database"] == "timeout"

    def test_ready_reuses_recent_dependency_check_result(self, client: TestClient) -> None:
        """Readiness probes should not open DB/LiteLLM connections on every hit."""

        admin_router._READY_CACHE["expires_at"] = 0.0

        class _HealthyAsyncClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def get(self, *args, **kwargs):
                return MagicMock(status_code=200)

        with (
            patch("routers.admin._READY_CACHE_TTL_SECONDS", 30.0),
            patch("routers.admin._check_database_ready_sync", return_value=True) as db_check,
            patch("routers.admin.httpx.AsyncClient", return_value=_HealthyAsyncClient()),
        ):
            first = client.get("/api/ready")
            second = client.get("/api/ready")

        assert first.status_code == 200
        assert second.status_code == 200
        assert db_check.call_count == 1


class TestAuthMiddleware:
    """Tests for authentication and authorization."""

    def test_missing_token_returns_401(self, client: TestClient) -> None:
        """Requests without a valid token should be rejected."""
        response = client.get("/api/agents")
        assert response.status_code == 401
        data = response.json()
        assert "detail" in data or "error" in data or "code" in data

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
        with patch(
            "routers.agents.read_agent",
            return_value={
                "metadata": {"name": "nonexistent-agent", "namespace": "default"},
                "spec": {"model": "gpt-4", "runtime": {"kind": "opencode"}},
            },
        ):
            response = client.get("/api/agents/nonexistent-agent", headers=auth_headers)
        assert response.status_code == 200


class TestIncidentEndpoints:
    """Smoke tests for incident auth boundaries."""

    def test_list_incidents_without_auth_returns_401(self, client: TestClient) -> None:
        response = client.get("/api/incidents")
        assert response.status_code == 401

    def test_list_incidents_with_auth_returns_200(self, client: TestClient, auth_headers: dict) -> None:
        with patch("routers.incidents.list_incidents", return_value=[]):
            response = client.get("/api/incidents", headers=auth_headers)

        assert response.status_code == 200
        assert response.json()["incidents"] == []

    def test_alertmanager_webhook_remains_public(self, client: TestClient) -> None:
        with patch("routers.incidents.create_incident", side_effect=ValueError("skip")):
            response = client.post("/api/webhooks/alertmanager", json={"alerts": []})

        assert response.status_code == 200
        assert response.json()["total"] == 0


class TestPrometheusMetrics:
    """Smoke test for Prometheus metrics endpoint."""

    def test_metrics_endpoint_returns_200(self, client: TestClient) -> None:
        """The /metrics endpoint should be accessible without auth and return Prometheus text.

        If prometheus_fastapi_instrumentator is not installed the /metrics route
        is never mounted, so the test is skipped rather than failing.
        """
        from _core import _Instrumentator

        if _Instrumentator is None:
            pytest.skip("prometheus_fastapi_instrumentator not installed")

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

    def test_runtime_events_query_endpoint_is_not_shadowed_by_trace_alias(
        self, client: TestClient, auth_headers: dict
    ) -> None:
        """The static runtime-events route should win over the legacy trace detail alias."""

        with patch.object(
            trace_store,
            "query_runtime_events",
            return_value={"items": [], "total": 0, "limit": 1, "offset": 0},
        ):
            response = client.get(
                "/api/v1/traces/runtime-events?namespace=default&limit=1",
                headers=auth_headers,
            )

        assert response.status_code == 200
        data = response.json()
        assert data["items"] == []
        assert data["total"] == 0

    def test_batch_ingest_without_auth_returns_401(self, client: TestClient) -> None:
        """Requests without auth to batch ingest should be rejected."""
        response = client.post("/api/traces/batch", json={"events": []})
        assert response.status_code == 401

    def test_batch_ingest_persists_step_timing_and_order(self) -> None:
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

    def test_execution_completion_recomputes_tool_call_totals(self) -> None:
        """Completion ingest should backfill tool totals from persisted tool rows."""
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
                    "run_id": "wf-run-tool-count",
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
                    "step_index": 1,
                },
            },
            {
                "event_type": "tool_call_completed",
                "execution_id": execution_id,
                "step_id": step_id,
                "timestamp": 1002,
                "payload": {
                    "tool_name": "read",
                    "tool_args": {"filePath": "/tmp/demo.txt"},
                    "tool_result": {"content": "ok"},
                },
            },
            {
                "event_type": "step_completed",
                "execution_id": execution_id,
                "step_id": step_id,
                "timestamp": 1003,
                "payload": {
                    "status": "completed",
                    "outputs": {"ok": True},
                },
            },
            {
                "event_type": "execution_completed",
                "execution_id": execution_id,
                "timestamp": 1004,
                "payload": {
                    "outputs": {"ok": True},
                    "metrics": {
                        "total_steps": 1,
                        "completed_steps": 1,
                        "failed_steps": 0,
                    },
                },
            },
        ]

        with db_session() as session:
            for event in events:
                traces_router._upsert_from_event(session, event)

        payload = trace_store.get_execution(execution_id)
        assert payload is not None
        assert payload["total_tool_calls"] == 1

        with db_session() as session:
            tool = session.query(trace_store.ToolCallRecord).filter_by(execution_id=execution_id).one()
            step = session.query(trace_store.StepExecution).filter_by(id=step_id).one()
            execution = session.query(trace_store.WorkflowExecution).filter_by(id=execution_id).one()
            session.delete(tool)
            session.delete(step)
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

    def test_list_traces_recreates_missing_trace_tables(self, client: TestClient, auth_headers: dict) -> None:
        trace_store.init_trace_database()

        with db_session() as session:
            session.query(trace_store.ExecutionTraceEventRecord).delete(synchronize_session=False)
            session.query(trace_store.ToolCallRecord).delete(synchronize_session=False)
            session.query(trace_store.LLMCallRecord).delete(synchronize_session=False)
            session.query(trace_store.StepExecution).delete(synchronize_session=False)
            session.query(trace_store.RuntimeRunEvent).delete(synchronize_session=False)
            session.query(trace_store.WorkflowExecution).delete(synchronize_session=False)

        with trace_store._AUTH_ENGINE.begin() as connection:
            connection.exec_driver_sql("DROP TABLE execution_trace_events")
            connection.exec_driver_sql("DROP TABLE tool_call_records")
            connection.exec_driver_sql("DROP TABLE llm_call_records")
            connection.exec_driver_sql("DROP TABLE step_executions")
            connection.exec_driver_sql("DROP TABLE runtime_run_events")
            connection.exec_driver_sql("DROP TABLE workflow_executions")

        response = client.get("/api/v1/traces/executions?namespace=default&limit=10", headers=auth_headers)
        assert response.status_code == 200
        payload = response.json()
        assert payload["items"] == []

    def test_trace_database_widens_workflow_execution_run_id_for_postgres(self) -> None:
        from contextlib import contextmanager

        from sqlalchemy.dialects import postgresql

        executed_sql: list[str] = []

        class FakeConnection:
            def __init__(self) -> None:
                self.dialect = postgresql.dialect()

            def execute(self, statement: object) -> None:
                executed_sql.append(str(statement))

        class FakeInspector:
            def get_table_names(self) -> list[str]:
                return ["workflow_executions"]

            def get_columns(self, table_name: str) -> list[dict[str, object]]:
                assert table_name == "workflow_executions"
                return [{"name": "run_id", "type": trace_store.String(64)}]

        class FakeEngine:
            @contextmanager
            def begin(self) -> object:
                yield FakeConnection()

        with patch.object(trace_store, "_AUTH_ENGINE", FakeEngine()), patch.object(
            trace_store,
            "inspect",
            new=lambda _connection: FakeInspector(),
        ):
            trace_store._ensure_workflow_execution_run_id_capacity()

        assert any(
            "ALTER TABLE workflow_executions ALTER COLUMN run_id TYPE VARCHAR(128)" in sql
            for sql in executed_sql
        )
