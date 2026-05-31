"""Tests for agentctl workflow commands."""

from __future__ import annotations

from contextlib import nullcontext
from typing import Any

import typer
from typer.testing import CliRunner

from agentctl.commands import register_all
from agentctl.commands import workflows
from agentctl.config import ResolvedSettings


class _DummyConsole:
    def __init__(self) -> None:
        self.print_calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    def status(self, *_args: Any, **_kwargs: Any):
        return nullcontext()

    def print(self, *args: Any, **kwargs: Any) -> None:
        self.print_calls.append((args, kwargs))


class _FakeClient:
    def __init__(self, response: Any) -> None:
        self._response = response
        self.calls: list[tuple[str, dict[str, Any] | None]] = []

    def __enter__(self) -> _FakeClient:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        self.calls.append((path, params))
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


def test_workflows_status_supports_camel_case_gateway_fields(monkeypatch) -> None:
    fake_client = _FakeClient(
        {
            "name": "demo-workflow",
            "phase": "completed",
            "currentStep": "finalize-pack",
            "runId": "wf-run-123",
            "pendingApproval": {"name": "review"},
            "stepStates": {
                "collect-research": {"status": "completed", "agentRef": "implementation-pack-writer"},
                "draft-pack": {"status": "running", "agentRef": "implementation-pack-writer"},
            },
        }
    )
    dummy_console = _DummyConsole()

    monkeypatch.setattr(workflows, "get_settings", _settings)
    monkeypatch.setattr(workflows, "_api", lambda: fake_client)
    monkeypatch.setattr(workflows, "console", dummy_console)

    result = CliRunner().invoke(_build_app(), ["workflows", "status", "demo-workflow"])

    assert result.exit_code == 0
    assert fake_client.calls == [("/api/workflows/demo-workflow", {"namespace": "test-ns"})]
    assert len(dummy_console.print_calls) == 2

    summary_table = dummy_console.print_calls[0][0][0]
    step_table = dummy_console.print_calls[1][0][0]

    assert summary_table.columns[0]._cells == ["Name", "Phase", "Current Step", "Run ID", "Pending Approval"]
    assert summary_table.columns[1]._cells == ["demo-workflow", "completed", "finalize-pack", "wf-run-123", "review"]
    assert step_table.columns[0]._cells == ["collect-research", "draft-pack"]
    assert [cell.plain for cell in step_table.columns[1]._cells] == ["completed", "running"]
    assert step_table.columns[2]._cells == ["implementation-pack-writer", "implementation-pack-writer"]


def test_workflows_list_derives_step_count_from_steps_array(monkeypatch) -> None:
    fake_client = _FakeClient(
        [
            {
                "name": "demo-workflow",
                "phase": "running",
                "currentStep": "draft-pack",
                "steps": [{"name": "one"}, {"name": "two"}, {"name": "three"}],
            }
        ]
    )
    rendered: dict[str, Any] = {}

    monkeypatch.setattr(workflows, "get_settings", _settings)
    monkeypatch.setattr(workflows, "_api", lambda: fake_client)
    monkeypatch.setattr(workflows, "console", _DummyConsole())
    monkeypatch.setattr(
        workflows,
        "print_table",
        lambda items, columns, **kwargs: rendered.update({"items": items, "columns": columns, "kwargs": kwargs}),
    )

    result = CliRunner().invoke(_build_app(), ["workflows", "list"])

    assert result.exit_code == 0
    assert fake_client.calls == [("/api/workflows", {"namespace": "test-ns"})]
    assert rendered["items"] == [
        {
            "name": "demo-workflow",
            "phase": "running",
            "currentStep": "draft-pack",
            "steps": [{"name": "one"}, {"name": "two"}, {"name": "three"}],
            "current_step": "draft-pack",
            "step_count": 3,
        }
    ]
