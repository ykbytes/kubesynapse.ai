"""Focused tests for ObservationTarget live vs demo status projection."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import controllers.observation_controller as observation_controller


def test_live_target_status_projects_connector_state(monkeypatch) -> None:
    patch = SimpleNamespace(status={})
    monkeypatch.setattr(
        observation_controller,
        "_get_connector_status_snapshot",
        lambda namespace, connector_ref: {
            "exists": True,
            "ready": "True",
            "metricsCollected": 42,
            "findingCount": 0,
            "lastHealthCheck": "2026-05-07T10:00:00+00:00",
            "lastScrapeTime": "2026-05-07T10:00:00+00:00",
            "lastScrapeError": "",
        },
    )
    monkeypatch.setattr(observation_controller, "_ensure_report_for_target", lambda **kwargs: None)
    monkeypatch.setattr(observation_controller, "_reconcile_policy_status", lambda *args, **kwargs: None)

    observation_controller.reconcile_target_status(
        spec={"connectorRef": "connector-a", "policyRef": "policy-a"},
        status={},
        meta={},
        name="target-a",
        namespace="default",
        patch=patch,
        logger=MagicMock(),
    )

    assert patch.status["phase"] == "Active"
    assert patch.status["connectorHealth"] == "Healthy"
    assert patch.status["metricsCollected"] == 42
    assert patch.status["lastScrapeTime"] == "2026-05-07T10:00:00+00:00"


def test_live_target_without_demo_annotation_does_not_use_synthetic_metrics(monkeypatch) -> None:
    patch = SimpleNamespace(status={})
    monkeypatch.setattr(
        observation_controller,
        "_get_connector_status_snapshot",
        lambda namespace, connector_ref: {
            "exists": True,
            "ready": "Unknown",
            "metricsCollected": 0,
            "findingCount": 0,
            "lastHealthCheck": None,
            "lastScrapeTime": None,
            "lastScrapeError": "",
        },
    )
    monkeypatch.setattr(observation_controller, "_ensure_report_for_target", lambda **kwargs: None)
    monkeypatch.setattr(observation_controller, "_reconcile_policy_status", lambda *args, **kwargs: None)

    observation_controller.reconcile_target_status(
        spec={"connectorRef": "connector-a"},
        status={"metricsCollected": 0},
        meta={},
        name="target-a",
        namespace="default",
        patch=patch,
        logger=MagicMock(),
    )

    assert patch.status["phase"] == "Pending"
    assert patch.status["metricsCollected"] == 0


def test_explicit_demo_target_keeps_demo_projection(monkeypatch) -> None:
    patch = SimpleNamespace(status={})
    monkeypatch.setattr(observation_controller, "_ensure_report_for_target", lambda **kwargs: None)
    monkeypatch.setattr(observation_controller, "_reconcile_policy_status", lambda *args, **kwargs: None)

    observation_controller.reconcile_target_status(
        spec={"connectorRef": "connector-a"},
        status={},
        meta={"annotations": {"observability.kubesynapse.ai/demo-mode": "firing"}},
        name="target-a",
        namespace="default",
        patch=patch,
        logger=MagicMock(),
    )

    assert patch.status["phase"] == "Degraded"
    assert patch.status["metricsCollected"] > 0
    assert patch.status["connectorHealth"] == "Healthy"


def test_live_report_status_has_no_synthetic_findings() -> None:
    report_status = observation_controller._build_report_status(
        target_name="target-a",
        target_spec={},
        target_status={
            "phase": "Failed",
            "connectorHealth": "Unhealthy",
            "metricsCollected": 0,
            "lastScrapeError": "Connector missing",
        },
        policy_spec={},
        demo_mode=None,
    )

    assert report_status["findingsCount"] == 0
    assert report_status["findings"] == []
    assert "Synthetic" not in report_status["summary"]


def test_create_connector_plugin_initializes_live_status_fields() -> None:
    patch = SimpleNamespace(status={})

    observation_controller.create_connector_plugin(
        spec={"image": "kubesynapse/connector-kubernetes:v1.0"},
        name="connector-a",
        namespace="default",
        patch=patch,
        logger=MagicMock(),
    )

    assert patch.status["ready"] == "Unknown"
    assert patch.status["version"] == "v1.0"
    assert patch.status["metricsCollected"] == 0
    assert patch.status["findingCount"] == 0
