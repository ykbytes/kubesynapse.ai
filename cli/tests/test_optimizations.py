"""Tests for agentctl optimization ROI commands."""

from __future__ import annotations

from contextlib import nullcontext
from typing import Any

import typer
from typer.testing import CliRunner

from agentctl.commands import optimizations, register_all
from agentctl.config import ResolvedSettings


class _DummyConsole:
    def __init__(self) -> None:
        self.print_calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    def status(self, *_args: Any, **_kwargs: Any):
        return nullcontext()

    def print(self, *args: Any, **kwargs: Any) -> None:
        self.print_calls.append((args, kwargs))


class _FakeClient:
    def __init__(self, responses: dict[tuple[str, str], Any]) -> None:
        self._responses = responses
        self.calls: list[tuple[str, str, dict[str, Any] | None]] = []

    def __enter__(self) -> _FakeClient:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        self.calls.append(("GET", path, params))
        return self._responses[("GET", path)]


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


def test_optimizations_studies_lists_counts_and_status(monkeypatch) -> None:
    fake_client = _FakeClient(
        {
            ("GET", "/api/optimizations/studies"): {
                "items": [
                    {
                        "id": "study-1",
                        "workflow_name": "daily-standup",
                        "namespace": "test-ns",
                        "created_at": "2026-06-29T10:00:00Z",
                        "proof_gate": {"status": "candidate_needed"},
                        "candidates": [{"id": "cand-1"}, {"id": "cand-2"}],
                        "trials": [{"id": "trial-1"}],
                    }
                ],
                "limit": 20,
                "offset": 0,
            }
        }
    )
    rendered: dict[str, Any] = {}

    monkeypatch.setattr(optimizations, "get_settings", _settings)
    monkeypatch.setattr(optimizations, "_api", lambda: fake_client)
    monkeypatch.setattr(
        optimizations,
        "print_table",
        lambda items, columns, **kwargs: rendered.update({"items": items, "columns": columns, "kwargs": kwargs}),
    )

    result = CliRunner().invoke(_build_app(), ["optimizations", "studies"])

    assert result.exit_code == 0
    assert fake_client.calls == [
        (
            "GET",
            "/api/optimizations/studies",
            {"namespace": "test-ns", "limit": 20, "offset": 0},
        )
    ]
    assert rendered["items"] == [
        {
            "id": "study-1",
            "workflow_name": "daily-standup",
            "namespace": "test-ns",
            "created_at": "2026-06-29T10:00:00Z",
            "proof_gate": {"status": "candidate_needed"},
            "candidates": [{"id": "cand-1"}, {"id": "cand-2"}],
            "trials": [{"id": "trial-1"}],
            "proof_status": "candidate_needed",
            "candidate_count": 2,
            "trial_count": 1,
        }
    ]


def test_optimizations_trace_extracts_selected_candidate_trace(monkeypatch) -> None:
    fake_client = _FakeClient(
        {
            ("GET", "/api/optimizations/studies/study-1"): {
                "id": "study-1",
                "workflow_name": "daily-standup",
                "candidates": [
                    {
                        "id": "cand-a",
                        "name": "daily-standup-opt-a",
                        "optimizer_trace": {"status": "completed", "events": [{"kind": "tool", "title": "read"}]},
                    },
                    {
                        "id": "cand-b",
                        "name": "daily-standup-opt-b",
                        "optimizer_trace": {"status": "completed", "events": [{"kind": "decision", "title": "route"}]},
                    },
                ],
            }
        }
    )
    captured: dict[str, Any] = {}

    monkeypatch.setattr(optimizations, "get_settings", _settings)
    monkeypatch.setattr(optimizations, "_api", lambda: fake_client)
    monkeypatch.setattr(
        optimizations,
        "print_detail",
        lambda data, **kwargs: captured.update({"data": data, "kwargs": kwargs}),
    )

    result = CliRunner().invoke(
        _build_app(),
        ["optimizations", "trace", "study-1", "--candidate-id", "cand-b"],
    )

    assert result.exit_code == 0
    assert fake_client.calls == [
        ("GET", "/api/optimizations/studies/study-1", {"namespace": "test-ns"})
    ]
    assert captured["data"] == {
        "study_id": "study-1",
        "candidate_id": "cand-b",
        "candidate_name": "daily-standup-opt-b",
        "optimizer_trace": {"status": "completed", "events": [{"kind": "decision", "title": "route"}]},
    }
    assert captured["kwargs"]["title"] == "Optimizer Trace: daily-standup-opt-b"
