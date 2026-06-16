from __future__ import annotations

from datetime import UTC, datetime, timedelta
from contextlib import contextmanager
from unittest.mock import patch

_TRACE_FIXTURES: dict[str, dict] = {}


def _seed_execution(
    *,
    execution_id: str,
    workflow_name: str = "daily-standup",
    run_id: str | None = None,
    duration_ms: float = 60_000,
    tokens: int = 1_000,
    cost_usd: float | None = 0.02,
    tool_calls: int = 2,
    status: str = "completed",
    input_summary: dict | None = None,
    output_summary: dict | None = None,
) -> str:
    started_at = datetime(2026, 5, 26, 18, 0, tzinfo=UTC)
    completed_at = started_at + timedelta(milliseconds=duration_ms)
    run_id = run_id or f"run-{execution_id}"
    step_id = f"step-{execution_id}"
    tool_records = [
        {
            "id": f"tool-{execution_id}-{index}",
            "execution_id": execution_id,
            "step_id": step_id,
            "tool_name": "read" if index % 2 == 0 else "write",
            "tool_args": {"path": "/workspace/standup.md"},
            "tool_result": {"ok": True},
            "duration_ms": 100 + index,
            "started_at": started_at.isoformat(),
        }
        for index in range(tool_calls)
    ]
    llm_record = {
        "id": f"llm-{execution_id}",
        "execution_id": execution_id,
        "step_id": step_id,
        "model": "opencode-go/deepseek-v4-flash",
        "provider": "opencode",
        "prompt_tokens": int(tokens * 0.7),
        "completion_tokens": int(tokens * 0.3),
        "total_tokens": tokens,
        "cost_usd": cost_usd,
        "latency_ms": duration_ms * 0.7,
        "started_at": started_at.isoformat(),
        "prompt_preview": "Read git and Jira context, then write a concise standup.",
        "response_preview": "Wrote standup.md.",
    }
    _TRACE_FIXTURES[execution_id] = {
        "id": execution_id,
        "namespace": "default",
        "workflow_name": workflow_name,
        "agent_name": "daily-standup",
        "run_id": run_id,
        "status": status,
        "started_at": started_at.isoformat(),
        "completed_at": completed_at.isoformat(),
        "duration_ms": duration_ms,
        "input_summary": input_summary or {"request": "summarise yesterday", "api_key": "sk-test-secret"},
        "output_summary": output_summary or {"markdown": "Standup summary"},
        "total_steps": 1,
        "completed_steps": 1 if status == "completed" else 0,
        "failed_steps": 0 if status == "completed" else 1,
        "total_llm_calls": 1,
        "total_tool_calls": tool_calls,
        "total_tokens": tokens,
        "prompt_tokens": int(tokens * 0.7),
        "completion_tokens": int(tokens * 0.3),
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
        "reasoning_tokens": 0,
        "estimated_cost_usd": cost_usd,
        "steps": [
            {
                "id": step_id,
                "execution_id": execution_id,
                "step_name": "summarise",
                "step_type": "agent",
                "step_index": 0,
                "status": status,
                "started_at": started_at.isoformat(),
                "completed_at": completed_at.isoformat(),
                "duration_ms": duration_ms,
                "input_summary": {"step": "summarise"},
                "output_summary": {"artifact": "standup.md"},
                "llm_calls_count": 1,
                "tool_calls_count": tool_calls,
                "tokens_used": tokens,
                "cost_usd": cost_usd,
            }
        ],
        "llm_calls": [llm_record],
        "tool_calls": tool_records,
        "events": [],
    }
    return execution_id


def _workflow_manifest(name: str = "daily-standup") -> dict:
    return {
        "apiVersion": "kubesynapse.ai/v1alpha1",
        "kind": "AgentWorkflow",
        "metadata": {"name": name, "namespace": "default", "labels": {"app": "demo"}},
        "spec": {
            "input": "Generate a daily standup.",
            "steps": [
                {
                    "name": "summarise",
                    "type": "agent",
                    "agentRef": "daily-standup",
                    "prompt": "Read git and Jira context, then write standup.md.",
                }
            ],
        },
    }


def _agent_manifest(name: str = "daily-standup") -> dict:
    return {
        "apiVersion": "kubesynapse.ai/v1alpha1",
        "kind": "AIAgent",
        "metadata": {"name": name, "namespace": "default"},
        "spec": {
            "model": "opencode-go/deepseek-v4-flash",
            "systemPrompt": "You write daily standup reports.",
            "runtime": {"kind": "opencode"},
            "mcpConnections": [{"name": "filesystem", "server_id": "filesystem-sidecar"}],
        },
    }


def _fake_read_custom_resource(plural: str, name: str, namespace: str, _label: str) -> dict:
    if namespace != "default":
        raise AssertionError("unexpected namespace")
    if plural == "agentworkflows":
        return _workflow_manifest(name)
    if plural == "aiagents":
        return _agent_manifest(name)
    raise AssertionError(f"unexpected plural {plural}")


def _allow_namespace_access(*args, **_kwargs):
    return args[0] if args else None


def _fake_get_execution(execution_id: str):
    return _TRACE_FIXTURES.get(execution_id)


@contextmanager
def _optimization_api_context(*, manifests: bool = False):
    with patch("routers.optimizations.ensure_namespace_access", side_effect=_allow_namespace_access), patch(
        "routers.optimizations.trace_store.get_execution", side_effect=_fake_get_execution
    ):
        if manifests:
            with patch("routers.optimizations.read_custom_resource", side_effect=_fake_read_custom_resource):
                yield
        else:
            yield


def test_create_study_computes_baseline_metrics_and_opportunities(client, auth_headers) -> None:
    first = _seed_execution(execution_id="exec-opt-base-1", duration_ms=60_000, tokens=1_200, cost_usd=0.036, tool_calls=3)
    second = _seed_execution(execution_id="exec-opt-base-2", duration_ms=120_000, tokens=1_800, cost_usd=0.054, tool_calls=5)

    with _optimization_api_context(manifests=True):
        response = client.post(
            "/api/v1/optimizations/studies",
            headers=auth_headers,
            json={
                "namespace": "default",
                "workflow_name": "daily-standup",
                "optimizer_agent_name": "workflow-optimizer",
                "baseline_execution_ids": [first, second],
                "objective": "Reduce token and latency cost while preserving artifacts.",
            },
        )

    assert response.status_code == 201
    data = response.json()
    assert data["status"] == "baseline_ready"
    assert data["baseline_metrics"]["sample_count"] == 2
    assert data["baseline_metrics"]["success_rate"] == 1.0
    assert data["baseline_metrics"]["avg_duration_ms"] == 90_000
    assert data["baseline_metrics"]["avg_tokens"] == 1_500
    assert data["baseline_metrics"]["avg_cost_usd"] == 0.045
    assert data["source_manifests"]["workflow"]["metadata"]["name"] == "daily-standup"
    assert data["source_manifests"]["agent_refs"] == ["daily-standup"]
    assert {item["kind"] for item in data["opportunities"]} >= {"latency", "tokens", "tool_churn"}


def test_candidate_validation_rejects_topology_changes_and_secret_expansion(client, auth_headers) -> None:
    base_id = _seed_execution(execution_id="exec-opt-validate-1")
    with _optimization_api_context(manifests=True):
        study = client.post(
            "/api/v1/optimizations/studies",
            headers=auth_headers,
            json={"namespace": "default", "workflow_name": "daily-standup", "baseline_execution_ids": [base_id]},
        ).json()

    bad_workflow = _workflow_manifest("daily-standup-opt-bad")
    bad_workflow["spec"]["steps"].append({"name": "new-step", "type": "agent", "agentRef": "daily-standup-opt-bad"})
    bad_agent = _agent_manifest("daily-standup-opt-bad")
    bad_agent["spec"]["env"] = [{"name": "OPENAI_API_KEY", "value": "sk-leaked"}]

    with _optimization_api_context():
        response = client.post(
            f"/api/v1/optimizations/studies/{study['id']}/candidates",
            headers=auth_headers,
            json={
                "name": "unsafe candidate",
                "optimizer_output": "try a topology rewrite",
                "manifest_bundle": [bad_agent, bad_workflow],
            },
    )

    assert response.status_code == 422
    payload = response.json()
    detail = payload.get("detail") or payload.get("message") or str(payload)
    assert "workflow topology" in detail
    assert "secret" in detail.lower()


def test_candidate_lifecycle_approval_trials_and_verified_roi(client, auth_headers) -> None:
    baseline_id = _seed_execution(execution_id="exec-opt-roi-base", duration_ms=100_000, tokens=2_000, cost_usd=0.08, tool_calls=8)
    candidate_execution_id = _seed_execution(
        execution_id="exec-opt-roi-candidate",
        workflow_name="daily-standup-opt-roi1",
        duration_ms=60_000,
        tokens=1_100,
        cost_usd=0.044,
        tool_calls=4,
    )

    with _optimization_api_context(manifests=True):
        study = client.post(
            "/api/v1/optimizations/studies",
            headers=auth_headers,
            json={"namespace": "default", "workflow_name": "daily-standup", "baseline_execution_ids": [baseline_id]},
        ).json()

    with _optimization_api_context():
        valid_candidate = client.post(
            f"/api/v1/optimizations/studies/{study['id']}/candidates/generate",
            headers=auth_headers,
            json={"optimizer_output": "trim repeated context and batch file reads", "suffix": "opt-roi1"},
        ).json()

        blocked_apply = client.post(
            f"/api/v1/optimizations/candidates/{valid_candidate['id']}/apply",
            headers=auth_headers,
            json={"dry_run": True},
        )
        assert blocked_apply.status_code == 409

        blocked_trial = client.post(
            f"/api/v1/optimizations/candidates/{valid_candidate['id']}/trials",
            headers=auth_headers,
            json={
                "baseline_execution_id": baseline_id,
                "result_execution_id": candidate_execution_id,
                "quality_status": "passed",
            },
        )
        assert blocked_trial.status_code == 409

        approval = client.post(
            f"/api/v1/optimizations/candidates/{valid_candidate['id']}/approval",
            headers=auth_headers,
            json={"decision": "approved", "reason": "Run as isolated candidate copy."},
        )
        assert approval.status_code == 200
        assert approval.json()["approval_status"] == "approved"

        trial = client.post(
            f"/api/v1/optimizations/candidates/{valid_candidate['id']}/trials",
            headers=auth_headers,
            json={
                "baseline_execution_id": baseline_id,
                "result_execution_id": candidate_execution_id,
                "quality_status": "passed",
                "notes": "Artifact matched reviewer expectations.",
            },
        )
        assert trial.status_code == 201

        roi = client.get(f"/api/v1/optimizations/studies/{study['id']}/roi", headers=auth_headers)
    assert roi.status_code == 200
    data = roi.json()
    assert data["proof_status"] == "verified"
    assert data["verified"] is True
    assert data["deltas"]["tokens_saved_percent"] == 45.0
    assert data["deltas"]["duration_saved_percent"] == 40.0
    assert data["deltas"]["cost_saved_percent"] == 45.0
    assert data["candidate_metrics"]["success_rate"] == 1.0


def test_dataset_export_redacts_secrets_and_keeps_trace_labels(client, auth_headers) -> None:
    baseline_id = _seed_execution(
        execution_id="exec-opt-dataset-base",
        input_summary={"prompt": "Summarise data", "api_key": "sk-test-secret", "nested": {"token": "abc123"}},
    )

    with _optimization_api_context(manifests=True):
        study = client.post(
            "/api/v1/optimizations/studies",
            headers=auth_headers,
            json={"namespace": "default", "workflow_name": "daily-standup", "baseline_execution_ids": [baseline_id]},
        ).json()

    with _optimization_api_context():
        response = client.get(f"/api/v1/optimizations/studies/{study['id']}/dataset?redacted=true", headers=auth_headers)

    assert response.status_code == 200
    dataset = response.json()
    serialized = str(dataset)
    assert "sk-test-secret" not in serialized
    assert "abc123" not in serialized
    assert "[REDACTED]" in serialized
    assert dataset["labels"]["workflow_name"] == "daily-standup"
    assert dataset["baseline_traces"][0]["id"] == baseline_id
