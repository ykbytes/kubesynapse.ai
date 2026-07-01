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

    def post(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        payload: dict[str, Any] | None = None,
    ) -> Any:
        self.calls.append(("POST", path, payload))
        return self._responses.get(("POST", path), {})

    def patch(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        payload: dict[str, Any] | None = None,
    ) -> Any:
        self.calls.append(("PATCH", path, payload))
        return self._responses.get(("PATCH", path), {})

    def delete(self, path: str, params: dict[str, Any] | None = None) -> Any:
        self.calls.append(("DELETE", path, params))
        return self._responses.get(("DELETE", path), {})

    def get_text(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        accept: str = "text/plain",
    ) -> str:
        self.calls.append(("GET_TEXT", path, {"params": params, "accept": accept}))
        return str(self._responses[("GET_TEXT", path)])


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


def test_optimizations_candidates_lists_cross_study_registry(monkeypatch) -> None:
    fake_client = _FakeClient(
        {
            ("GET", "/api/optimizations/candidates"): {
                "items": [
                    {
                        "id": "cand-1",
                        "candidate_workflow_name": "daily-standup-opt-a",
                        "workflow_name": "daily-standup",
                        "approval_status": "approved",
                        "lifecycle_state": "active",
                        "trial_count": 2,
                        "expected_savings": {
                            "duration_saved_percent": 31.2,
                            "tokens_saved_percent": 18.8,
                        },
                        "tags": ["winner"],
                        "created_at": "2026-06-30T10:00:00Z",
                    }
                ]
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

    result = CliRunner().invoke(
        _build_app(),
        [
            "optimizations",
            "candidates",
            "--workflow",
            "daily-standup",
            "--tag",
            "winner",
            "--include-archived",
        ],
    )

    assert result.exit_code == 0
    assert fake_client.calls == [
        (
            "GET",
            "/api/optimizations/candidates",
            {
                "namespace": "test-ns",
                "workflow_name": "daily-standup",
                "tag": "winner",
                "include_archived": True,
                "limit": 100,
                "offset": 0,
            },
        )
    ]
    assert rendered["items"][0]["expected_gain"] == "31% time · 19% tokens"
    assert rendered["items"][0]["state"] == "approved"


def test_optimizations_candidate_shows_detail(monkeypatch) -> None:
    fake_client = _FakeClient(
        {
            ("GET", "/api/optimizations/candidates/cand-1"): {
                "candidate": {
                    "id": "cand-1",
                    "candidate_workflow_name": "daily-standup-opt-a",
                    "workflow_name": "daily-standup",
                    "study_id": "study-1",
                    "status": "draft",
                    "approval_status": "pending",
                    "lifecycle_state": "active",
                    "manifest_bundle": [{}, {}, {}],
                    "tags": ["review"],
                },
                "study": {"id": "study-1"},
                "trials": [{"id": "trial-1"}],
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

    result = CliRunner().invoke(_build_app(), ["optimizations", "candidate", "cand-1"])

    assert result.exit_code == 0
    assert captured["data"]["candidate"]["manifest_resource_count"] == 3
    assert captured["data"]["candidate"]["trial_count"] == 1


def test_optimizations_manifest_writes_exact_yaml(monkeypatch, tmp_path) -> None:
    fake_client = _FakeClient(
        {
            ("GET_TEXT", "/api/optimizations/candidates/cand-1/manifest"): (
                "---\napiVersion: kubesynapse.ai/v1alpha1\nkind: AgentWorkflow\n"
            )
        }
    )
    output_path = tmp_path / "candidate.yaml"
    monkeypatch.setattr(optimizations, "get_settings", _settings)
    monkeypatch.setattr(optimizations, "_api", lambda: fake_client)

    result = CliRunner().invoke(
        _build_app(),
        ["optimizations", "manifest", "cand-1", "--output", str(output_path)],
    )

    assert result.exit_code == 0
    assert output_path.read_text(encoding="utf-8").startswith("---\napiVersion:")
    assert fake_client.calls == [
        (
            "GET_TEXT",
            "/api/optimizations/candidates/cand-1/manifest",
            {"params": None, "accept": "application/yaml"},
        )
    ]


def test_optimizations_tags_merges_additions_and_removals(monkeypatch) -> None:
    fake_client = _FakeClient(
        {
            ("GET", "/api/optimizations/candidates/cand-1"): {
                "candidate": {"id": "cand-1", "tags": ["review", "slow"]},
                "study": {},
                "trials": [],
            },
            ("PATCH", "/api/optimizations/candidates/cand-1"): {
                "id": "cand-1",
                "tags": ["review", "winner"],
            },
        }
    )
    monkeypatch.setattr(optimizations, "get_settings", _settings)
    monkeypatch.setattr(optimizations, "_api", lambda: fake_client)
    monkeypatch.setattr(optimizations, "print_detail", lambda *_args, **_kwargs: None)

    result = CliRunner().invoke(
        _build_app(),
        ["optimizations", "tags", "cand-1", "--add", "winner", "--remove", "slow"],
    )

    assert result.exit_code == 0
    assert fake_client.calls[-1] == (
        "PATCH",
        "/api/optimizations/candidates/cand-1",
        {"tags": ["review", "winner"]},
    )


def test_optimizations_archive_requires_explicit_yes_and_calls_delete(monkeypatch) -> None:
    fake_client = _FakeClient(
        {
            ("DELETE", "/api/optimizations/candidates/cand-1"): {
                "id": "cand-1",
                "lifecycle_state": "archived",
            }
        }
    )
    monkeypatch.setattr(optimizations, "get_settings", _settings)
    monkeypatch.setattr(optimizations, "_api", lambda: fake_client)
    monkeypatch.setattr(optimizations, "print_detail", lambda *_args, **_kwargs: None)

    result = CliRunner().invoke(_build_app(), ["optimizations", "archive", "cand-1", "--yes"])

    assert result.exit_code == 0
    assert fake_client.calls == [
        ("DELETE", "/api/optimizations/candidates/cand-1", {"namespace": "test-ns"})
    ]


def test_optimizations_approve_and_dry_run_apply_use_safe_payloads(monkeypatch) -> None:
    fake_client = _FakeClient(
        {
            ("POST", "/api/optimizations/candidates/cand-1/approval"): {"id": "cand-1"},
            ("POST", "/api/optimizations/candidates/cand-1/apply"): {"dry_run": True},
        }
    )
    monkeypatch.setattr(optimizations, "get_settings", _settings)
    monkeypatch.setattr(optimizations, "_api", lambda: fake_client)
    monkeypatch.setattr(optimizations, "print_detail", lambda *_args, **_kwargs: None)

    approve_result = CliRunner().invoke(
        _build_app(),
        ["optimizations", "approve", "cand-1", "--reason", "reviewed"],
    )
    apply_result = CliRunner().invoke(_build_app(), ["optimizations", "apply", "cand-1"])

    assert approve_result.exit_code == 0
    assert apply_result.exit_code == 0
    assert fake_client.calls == [
        (
            "POST",
            "/api/optimizations/candidates/cand-1/approval",
            {"decision": "approved", "reason": "reviewed"},
        ),
        (
            "POST",
            "/api/optimizations/candidates/cand-1/apply",
            {"dry_run": True},
        ),
    ]


def test_optimizations_run_and_promote_require_yes(monkeypatch) -> None:
    fake_client = _FakeClient(
        {
            ("POST", "/api/optimizations/candidates/cand-1/run"): {"candidate_id": "cand-1"},
            ("POST", "/api/optimizations/candidates/cand-1/promotion"): {"id": "cand-1"},
        }
    )
    monkeypatch.setattr(optimizations, "get_settings", _settings)
    monkeypatch.setattr(optimizations, "_api", lambda: fake_client)
    monkeypatch.setattr(optimizations, "print_detail", lambda *_args, **_kwargs: None)

    run_result = CliRunner().invoke(
        _build_app(),
        ["optimizations", "run", "cand-1", "--input", "smoke", "--yes"],
    )
    promote_result = CliRunner().invoke(
        _build_app(),
        ["optimizations", "promote", "cand-1", "--reason", "verified ROI", "--yes"],
    )

    assert run_result.exit_code == 0
    assert promote_result.exit_code == 0
    assert fake_client.calls == [
        (
            "POST",
            "/api/optimizations/candidates/cand-1/run",
            {"input": "smoke", "baseline_execution_id": None, "notes": None},
        ),
        (
            "POST",
            "/api/optimizations/candidates/cand-1/promotion",
            {"reason": "verified ROI"},
        ),
    ]
