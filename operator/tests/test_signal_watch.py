"""Focused tests for signal watch hardening."""

from __future__ import annotations

from unittest.mock import MagicMock

import controllers.signal_watch as signal_watch


def test_query_uses_sqlalchemy_text(monkeypatch) -> None:
    sentinel = object()
    engine = MagicMock()
    conn = engine.connect.return_value.__enter__.return_value
    result = MagicMock()
    result.keys.return_value = ["execution_id"]
    result.__iter__.return_value = iter([("exec-1",)])
    conn.execute.return_value = result

    monkeypatch.setattr(signal_watch, "_get_db_engine", lambda: engine)
    monkeypatch.setattr(signal_watch, "sql_text", lambda sql: sentinel)

    rows = signal_watch._query("SELECT 1", {"cutoff": "now"})

    conn.execute.assert_called_once_with(sentinel, {"cutoff": "now"})
    assert rows == [{"execution_id": "exec-1"}]


def test_cost_outlier_query_uses_estimated_cost_usd(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_query(sql: str, params: dict[str, object] | None = None):
        captured["sql"] = sql
        captured["params"] = params
        return []

    monkeypatch.setattr(signal_watch, "_query", fake_query)

    signal_watch._check_cost_outliers()

    sql = str(captured["sql"])
    assert "AVG(estimated_cost_usd) AS avg_cost" in sql
    assert "we.estimated_cost_usd" in sql


def test_run_signal_watch_cycle_continues_after_detector_failure(monkeypatch) -> None:
    calls: list[str] = []

    def boom() -> int:
        calls.append("boom")
        raise RuntimeError("broken detector")

    def ok() -> int:
        calls.append("ok")
        return 2

    monkeypatch.setattr(signal_watch, "_emit_high_failure_rate_reports", boom)
    monkeypatch.setattr(signal_watch, "_emit_error_spike_reports", ok)
    monkeypatch.setattr(signal_watch, "_emit_cost_outlier_reports", lambda: 0)
    monkeypatch.setattr(signal_watch, "_emit_token_spike_reports", lambda: 0)
    monkeypatch.setattr(signal_watch, "_emit_stuck_run_reports", lambda: 0)

    total = signal_watch.run_signal_watch_cycle()

    assert calls == ["boom", "ok"]
    assert total == 2


def test_timer_runs_cycle_only_once_per_interval(monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(signal_watch, "WATCH_INTERVAL_SEC", 60)
    monkeypatch.setattr(signal_watch, "run_signal_watch_cycle", lambda: calls.append("run") or 0)

    signal_watch._last_cycle_started_at = 0.0
    signal_watch.signal_watch_timer()
    signal_watch.signal_watch_timer()

    assert calls == ["run"]


def test_report_name_is_deterministic_within_same_interval(monkeypatch) -> None:
    monkeypatch.setattr(signal_watch, "WATCH_INTERVAL_SEC", 60)
    monkeypatch.setattr(signal_watch.time, "time", lambda: 120.0)

    kwargs = {
        "namespace": "default",
        "name": "workflow-a",
        "anomaly_type": "cost_outlier",
        "details": {"execution_id": "exec-1"},
        "affected_executions": ["exec-1"],
    }

    first = signal_watch._build_report_name(**kwargs)
    second = signal_watch._build_report_name(**kwargs)

    assert first == second


def test_create_observation_report_uses_deterministic_name(monkeypatch) -> None:
    created = {}

    class FakeApi:
        def create_namespaced_custom_object(self, **kwargs):
            created.update(kwargs)

    monkeypatch.setattr(signal_watch.kubernetes.client, "CustomObjectsApi", lambda: FakeApi())
    monkeypatch.setattr(signal_watch, "_build_report_name", lambda **kwargs: "signal-cost-outlier-test")

    signal_watch._create_observation_report(
        namespace="default",
        name="workflow-a",
        anomaly_type="cost_outlier",
        severity="high",
        title="Cost outlier",
        description="expensive",
        details={"execution_id": "exec-1"},
        affected_executions=["exec-1"],
    )

    assert created["body"]["metadata"]["name"] == "signal-cost-outlier-test"
