"""Tests for agentctl observatory commands."""

from __future__ import annotations

from contextlib import nullcontext
from typing import Any

import typer
from typer.testing import CliRunner

from agentctl.client import ApiError
from agentctl.commands import register_all
from agentctl.commands import observatory
from agentctl.config import ResolvedSettings


class _DummyConsole:
    def status(self, *_args: Any, **_kwargs: Any):
        return nullcontext()


class _FakeClient:
    def __init__(self, response: Any = None, error: ApiError | None = None) -> None:
        self._response = response
        self._error = error
        self.calls: list[tuple[str, dict[str, Any] | None]] = []

    def __enter__(self) -> _FakeClient:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        self.calls.append((path, params))
        if self._error is not None:
            raise self._error
        return self._response


def _settings() -> ResolvedSettings:
    return ResolvedSettings(
        gateway_url="http://test-gateway:8080",
        token="test-token",
        namespace="test-ns",
        timeout=10.0,
        output_format="table",
    )


def _build_app() -> typer.Typer:
    app = typer.Typer()
    register_all(app)
    return app


def test_observatory_traces_uses_live_execution_endpoint(monkeypatch) -> None:
    fake_client = _FakeClient(
        {
            "items": [
                {
                    "id": "exec-1",
                    "workflow_name": "demo-workflow",
                    "agent_name": "demo-agent",
                    "status": "failed",
                    "duration_ms": 321.0,
                    "started_at": "2026-05-22T10:00:00+00:00",
                    "run_id": "run-1",
                    "total_tokens": 42,
                    "triggered_by": "workflow-worker",
                }
            ]
        }
    )
    rendered: dict[str, Any] = {}

    monkeypatch.setattr(observatory, "get_settings", _settings)
    monkeypatch.setattr(observatory, "_api", lambda: fake_client)
    monkeypatch.setattr(observatory, "console", _DummyConsole())
    monkeypatch.setattr(
        observatory,
        "print_table",
        lambda items, columns, **kwargs: rendered.update(
            {"items": items, "columns": columns, "kwargs": kwargs}
        ),
    )

    result = CliRunner().invoke(
        _build_app(),
        ["observatory", "traces", "--agent", "demo-agent", "--limit", "5", "--status", "failed"],
    )

    assert result.exit_code == 0
    assert fake_client.calls == [
        (
            "/api/v1/traces/executions",
            {
                "namespace": "test-ns",
                "limit": 5,
                "agent_name": "demo-agent",
                "status": "failed",
            },
        )
    ]
    assert rendered["items"] == [
        {
            "id": "exec-1",
            "workflow_name": "demo-workflow",
            "agent_name": "demo-agent",
            "status": "failed",
            "duration_ms": 321.0,
            "started_at": "2026-05-22T10:00:00+00:00",
            "run_id": "run-1",
            "total_tokens": 42,
            "triggered_by": "workflow-worker",
            "trace_id": "exec-1",
            "timestamp": "2026-05-22T10:00:00+00:00",
        }
    ]
    assert rendered["columns"][0] == ("TRACE ID", "trace_id")
    assert rendered["columns"][1] == ("WORKFLOW", "workflow_name")


def test_observatory_trace_uses_live_execution_detail_endpoint(monkeypatch) -> None:
    fake_client = _FakeClient({"id": "exec-2", "status": "completed"})
    rendered: dict[str, Any] = {}

    monkeypatch.setattr(observatory, "get_settings", _settings)
    monkeypatch.setattr(observatory, "_api", lambda: fake_client)
    monkeypatch.setattr(observatory, "console", _DummyConsole())
    monkeypatch.setattr(
        observatory,
        "print_detail",
        lambda data, **kwargs: rendered.update({"data": data, "kwargs": kwargs}),
    )

    result = CliRunner().invoke(_build_app(), ["observatory", "trace", "exec-2"])

    assert result.exit_code == 0
    assert fake_client.calls == [("/api/v1/traces/executions/exec-2", None)]
    assert rendered["data"] == {"id": "exec-2", "status": "completed"}
    assert rendered["kwargs"]["title"] == "Trace: exec-2..."


def test_observatory_traces_reports_api_errors(monkeypatch) -> None:
    fake_client = _FakeClient(error=ApiError("Not Found", status_code=404))
    captured: dict[str, Any] = {}

    monkeypatch.setattr(observatory, "get_settings", _settings)
    monkeypatch.setattr(observatory, "_api", lambda: fake_client)
    monkeypatch.setattr(observatory, "console", _DummyConsole())

    def _fatal(message: str, exit_code: int = 1) -> None:
        captured["message"] = message
        raise SystemExit(exit_code)

    monkeypatch.setattr(observatory, "fatal", _fatal)

    result = CliRunner().invoke(_build_app(), ["observatory", "traces"])

    assert result.exit_code == 1
    assert captured["message"] == "Not Found"


def test_observatory_metrics_uses_usage_endpoints(monkeypatch) -> None:
    fake_client = _FakeClient()
    fake_client._response = None
    responses = [
        {
            "items": [
                {
                    "group": "demo-agent",
                    "prompt_tokens": 10,
                    "completion_tokens": 20,
                    "total_tokens": 30,
                    "estimated_cost_usd": 0.12,
                    "invocations": 2,
                }
            ]
        },
        {
            "items": [
                {
                    "timestamp": "2026-05-22T10:00:00+00:00",
                    "agent_name": "demo-agent",
                    "model": "github-copilot/gpt-5-mini",
                    "total_tokens": 30,
                    "estimated_cost_usd": 0.12,
                    "request_id": "req-1",
                }
            ],
            "total": 1,
        },
    ]
    tables: list[dict[str, Any]] = []
    details: list[dict[str, Any]] = []

    def _get(path: str, params: dict[str, Any] | None = None) -> Any:
        fake_client.calls.append((path, params))
        return responses.pop(0)

    fake_client.get = _get  # type: ignore[method-assign]

    monkeypatch.setattr(observatory, "get_settings", _settings)
    monkeypatch.setattr(observatory, "_api", lambda: fake_client)
    monkeypatch.setattr(observatory, "console", _DummyConsole())
    monkeypatch.setattr(
        observatory,
        "print_detail",
        lambda data, **kwargs: details.append({"data": data, "kwargs": kwargs}),
    )
    monkeypatch.setattr(
        observatory,
        "print_table",
        lambda items, columns, **kwargs: tables.append({"items": items, "columns": columns, "kwargs": kwargs}),
    )

    result = CliRunner().invoke(_build_app(), ["observatory", "metrics", "--agent", "demo-agent", "--window", "24h"])

    assert result.exit_code == 0
    assert fake_client.calls == [
        (
            "/api/v1/usage/summary",
            {
                "namespace": "test-ns",
                "group_by": "agent",
                "from_date": details[0]["data"]["_from_date"] if False else fake_client.calls[0][1]["from_date"],
            },
        ),
        (
            "/api/v1/usage/detail",
            {
                "namespace": "test-ns",
                "agent_name": "demo-agent",
                "from_date": fake_client.calls[0][1]["from_date"],
                "limit": 20,
                "offset": 0,
            },
        ),
    ]
    assert details[0]["data"] == {
        "groups": 1,
        "invocations": 2,
        "prompt_tokens": 10,
        "completion_tokens": 20,
        "total_tokens": 30,
        "estimated_cost_usd": 0.12,
    }
    assert tables[0]["items"][0]["group"] == "demo-agent"
    assert tables[1]["items"][0]["request_id"] == "req-1"


def test_observatory_alerts_uses_overview_reports(monkeypatch) -> None:
    fake_client = _FakeClient(
        {
            "reports": [
                {
                    "name": "signal-high-failure",
                    "targetRef": "cli-e2e-workflow",
                    "reportType": "anomaly",
                    "phase": "Complete",
                    "healthScore": 38,
                    "findingsCount": 1,
                    "lastEvaluated": "2026-05-22T10:00:00+00:00",
                    "summary": "Failure rate exceeded threshold.",
                    "createdAt": "2026-05-22T09:59:00+00:00",
                    "findings": [{"severity": "critical", "metric": "failure_rate"}],
                },
                {
                    "name": "healthy-report",
                    "targetRef": "demo-target",
                    "reportType": "health-check",
                    "phase": "Complete",
                    "healthScore": 96,
                    "findingsCount": 0,
                    "lastEvaluated": "2026-05-22T11:00:00+00:00",
                    "summary": "Healthy.",
                    "createdAt": "2026-05-22T10:59:00+00:00",
                    "findings": [],
                },
            ]
        }
    )
    rendered: dict[str, Any] = {}

    monkeypatch.setattr(observatory, "get_settings", _settings)
    monkeypatch.setattr(observatory, "_api", lambda: fake_client)
    monkeypatch.setattr(observatory, "console", _DummyConsole())
    monkeypatch.setattr(
        observatory,
        "print_table",
        lambda items, columns, **kwargs: rendered.update({"items": items, "columns": columns, "kwargs": kwargs}),
    )

    result = CliRunner().invoke(_build_app(), ["observatory", "alerts"])

    assert result.exit_code == 0
    assert fake_client.calls == [("/api/v1/observability/overview", {"namespace": "test-ns"})]
    assert rendered["items"] == [
        {
            "name": "signal-high-failure",
            "targetRef": "cli-e2e-workflow",
            "reportType": "anomaly",
            "phase": "Complete",
            "healthScore": 38,
            "findingsCount": 1,
            "lastEvaluated": "2026-05-22T10:00:00+00:00",
            "summary": "Failure rate exceeded threshold.",
            "createdAt": "2026-05-22T09:59:00+00:00",
            "findings": [{"severity": "critical", "metric": "failure_rate"}],
            "severity": "critical",
            "target": "cli-e2e-workflow",
            "message": "Failure rate exceeded threshold.",
            "timestamp": "2026-05-22T10:00:00+00:00",
            "status": "active",
        }
    ]


def test_observatory_signals_uses_runtime_events(monkeypatch) -> None:
    fake_client = _FakeClient(
        {
            "items": [
                {
                    "id": "evt-1",
                    "execution_id": "exec-1",
                    "agent_name": "demo-agent",
                    "runtime_kind": "operator-worker",
                    "event_type": "step.failed",
                    "severity": "error",
                    "payload": {"step_name": "draft", "error": "boom"},
                    "created_at": "2026-05-22T10:00:00+00:00",
                }
            ],
            "total": 1,
        }
    )
    rendered: dict[str, Any] = {}

    monkeypatch.setattr(observatory, "get_settings", _settings)
    monkeypatch.setattr(observatory, "_api", lambda: fake_client)
    monkeypatch.setattr(observatory, "console", _DummyConsole())
    monkeypatch.setattr(
        observatory,
        "print_table",
        lambda items, columns, **kwargs: rendered.update({"items": items, "columns": columns, "kwargs": kwargs}),
    )

    result = CliRunner().invoke(_build_app(), ["observatory", "signals", "--agent", "demo-agent", "--limit", "5"])

    assert result.exit_code == 0
    assert fake_client.calls == [
        (
            "/api/v1/traces/runtime-events",
            {"namespace": "test-ns", "limit": 5, "agent_name": "demo-agent"},
        )
    ]
    assert rendered["items"] == [
        {
            "id": "evt-1",
            "execution_id": "exec-1",
            "agent_name": "demo-agent",
            "runtime_kind": "operator-worker",
            "event_type": "step.failed",
            "severity": "error",
            "payload": {"step_name": "draft", "error": "boom"},
            "created_at": "2026-05-22T10:00:00+00:00",
            "signal_type": "step.failed",
            "timestamp": "2026-05-22T10:00:00+00:00",
            "message": "boom",
        }
    ]
