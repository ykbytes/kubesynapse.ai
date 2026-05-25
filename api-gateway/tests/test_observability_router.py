"""Focused tests for the observability router split."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch


def test_observability_overview_uses_shared_observation_constants(client, auth_headers) -> None:
    """The overview route should keep working after the admin/observability split."""

    class _FakeCustomObjectsApi:
        def list_namespaced_custom_object(self, *, plural: str, **_kwargs):
            if plural == "observationreports":
                return {
                    "items": [
                        {
                            "metadata": {
                                "name": "signal-high-failure",
                                "namespace": "default",
                                "creationTimestamp": "2026-05-22T10:00:00+00:00",
                            },
                            "spec": {
                                "targetRef": "cli-e2e-workflow",
                                "reportType": "anomaly",
                            },
                            "status": {
                                "phase": "Complete",
                                "healthScore": 38,
                                "findingsCount": 1,
                                "lastEvaluated": "2026-05-22T10:01:00+00:00",
                                "findings": [{"severity": "critical", "metric": "failure_rate"}],
                                "summary": "Failure rate exceeded threshold.",
                            },
                        }
                    ]
                }
            return {"items": []}

    class _FakeCoreV1Api:
        def list_namespaced_pod(self, **_kwargs):
            return SimpleNamespace(items=[])

    with patch("routers.observability.k8s_client.CustomObjectsApi", _FakeCustomObjectsApi), patch(
        "routers.observability.k8s_client.CoreV1Api", _FakeCoreV1Api
    ):
        response = client.get("/api/v1/observability/overview?namespace=default", headers=auth_headers)

    assert response.status_code == 200
    data = response.json()
    assert data["summary"]["reports"]["total"] == 1
    assert data["reports"][0]["name"] == "signal-high-failure"
    assert data["reports"][0]["findingsCount"] == 1
