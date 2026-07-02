from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import optimization_store
import yaml
from sqlalchemy import create_engine, inspect, text

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
        "model": "opencode/deepseek-v4-flash-free",
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
            "model": "opencode/deepseek-v4-flash-free",
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


def _fake_get_executions_by_ids(execution_ids: list[str]):
    return {
        execution_id: _TRACE_FIXTURES[execution_id] for execution_id in execution_ids if execution_id in _TRACE_FIXTURES
    }


@contextmanager
def _optimization_api_context(*, manifests: bool = False):
    with (
        patch("routers.optimizations.ensure_namespace_access", side_effect=_allow_namespace_access),
        patch("routers.optimizations.trace_store.get_execution", side_effect=_fake_get_execution),
        patch("routers.optimizations.trace_store.get_executions_by_ids", side_effect=_fake_get_executions_by_ids),
    ):
        if manifests:
            with patch("routers.optimizations.read_custom_resource", side_effect=_fake_read_custom_resource):
                yield
        else:
            yield


def test_create_study_reconstructs_missing_source_agent_contract_from_traces(client, auth_headers) -> None:
    baseline_id = _seed_execution(
        execution_id="exec-opt-missing-source-agent",
        workflow_name="daily-standup",
        duration_ms=180_000,
        tokens=4_000,
        tool_calls=8,
    )
    workflow = _workflow_manifest("daily-standup")
    workflow["spec"]["steps"] = [
        {
            "name": "summarize-git",
            "type": "agent",
            "agentRef": "standup-git",
            "prompt": "Summarize git commits and write /workspace/commits-summary.md.",
        },
        {
            "name": "track-jira",
            "type": "agent",
            "agentRef": "standup-jira",
            "prompt": "Analyze Jira sprint status and write /workspace/sprint-status.json.",
        },
    ]

    def fake_read_missing_git(plural: str, name: str, namespace: str, label: str) -> dict:
        if plural == "aiagents" and name == "standup-git":
            raise RuntimeError("missing source agent")
        return _fake_read_custom_resource(plural, name, namespace, label)

    with (
        patch("routers.optimizations.ensure_namespace_access", side_effect=_allow_namespace_access),
        patch("routers.optimizations.trace_store.get_execution", side_effect=_fake_get_execution),
        patch("routers.optimizations.trace_store.get_executions_by_ids", side_effect=_fake_get_executions_by_ids),
        patch("routers.optimizations.read_custom_resource", side_effect=fake_read_missing_git),
    ):
        response = client.post(
            "/api/v1/optimizations/studies",
            headers=auth_headers,
            json={
                "namespace": "default",
                "workflow_name": "daily-standup",
                "optimizer_agent_name": "workflow-optimizer",
                "baseline_execution_ids": [baseline_id],
                "source_manifests": {
                    "workflow": workflow,
                    "agent_refs": ["standup-git", "standup-jira"],
                    "agents": {"standup-jira": _agent_manifest("standup-jira")},
                },
            },
        )

    assert response.status_code == 201, response.json()
    source = response.json()["source_manifests"]
    reconstructed = source["agents"]["standup-git"]
    assert reconstructed["kind"] == "AIAgent"
    assert reconstructed["metadata"]["annotations"]["kubesynapse.ai/reconstructed-source"] == "true"
    assert reconstructed["spec"]["model"] == "opencode/deepseek-v4-flash-free"
    assert reconstructed["spec"]["runtime"] == {"kind": "opencode"}
    # The reconstruction preamble and step data must NOT leak into the
    # systemPrompt (it is a stable behavioral identity); step contract lives
    # in an annotation so optimizer copies do not inherit optimizer meta text.
    assert "Reconstructed source contract" not in reconstructed["spec"]["systemPrompt"]
    assert (
        "Summarize git commits"
        in reconstructed["metadata"]["annotations"]["kubesynapse.ai/reconstructed-step-contract"]
    )
    assert any("standup-git" in warning for warning in source["warnings"])


def test_create_study_computes_baseline_metrics_and_opportunities(client, auth_headers) -> None:
    first = _seed_execution(
        execution_id="exec-opt-base-1", duration_ms=60_000, tokens=1_200, cost_usd=0.036, tool_calls=3
    )
    second = _seed_execution(
        execution_id="exec-opt-base-2", duration_ms=120_000, tokens=1_800, cost_usd=0.054, tool_calls=5
    )

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

    assert response.status_code == 201, response.json()
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
    assert {item["lever"] for item in data["opportunities"]} >= {"context_trim", "model_route", "tool_batching"}
    assert data["proof_gate"]["minimum_safe_trials"] == 5
    assert "same_topology" in data["proof_gate"]["hard_checks"]
    intelligence = data["optimizer_intelligence"]
    assert intelligence["dataset_readiness"]["baseline_examples"] == 2
    assert intelligence["dataset_readiness"]["state"] == "needs_more_samples"
    assert intelligence["ranked_levers"][0]["impact_score"] >= intelligence["ranked_levers"][-1]["impact_score"]
    assert any(lever["lever"] == "tool_batching" for lever in intelligence["ranked_levers"])
    assert intelligence["step_rollups"][0]["step_name"] == "summarise"
    assert intelligence["model_rollups"][0]["model"] == "opencode/deepseek-v4-flash-free"


def test_create_study_uses_bulk_trace_loading(client, auth_headers) -> None:
    first = _seed_execution(execution_id="exec-opt-bulk-1", duration_ms=60_000, tokens=1_200, tool_calls=3)
    second = _seed_execution(execution_id="exec-opt-bulk-2", duration_ms=90_000, tokens=1_500, tool_calls=4)
    requested_ids: list[str] = []

    def fake_get_executions(execution_ids: list[str]) -> dict[str, dict]:
        requested_ids.extend(execution_ids)
        return {execution_id: _TRACE_FIXTURES[execution_id] for execution_id in execution_ids}

    with (
        patch("routers.optimizations.ensure_namespace_access", side_effect=_allow_namespace_access),
        patch(
            "routers.optimizations.trace_store.get_execution",
            side_effect=AssertionError("create_study must not load baseline traces one connection at a time"),
        ),
        patch("routers.optimizations.trace_store.get_executions_by_ids", side_effect=fake_get_executions, create=True),
        patch("routers.optimizations.read_custom_resource", side_effect=_fake_read_custom_resource),
    ):
        response = client.post(
            "/api/v1/optimizations/studies",
            headers=auth_headers,
            json={
                "namespace": "default",
                "workflow_name": "daily-standup",
                "optimizer_agent_name": "workflow-optimizer",
                "baseline_execution_ids": [first, second],
            },
        )

    assert response.status_code == 201, response.json()
    assert requested_ids == [first, second]
    assert response.json()["baseline_metrics"]["sample_count"] == 2


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


def test_candidate_validation_allows_topology_rewrite_only_when_explicit(client, auth_headers) -> None:
    base_id = _seed_execution(execution_id="exec-opt-topology-mode")
    with _optimization_api_context(manifests=True):
        study = client.post(
            "/api/v1/optimizations/studies",
            headers=auth_headers,
            json={"namespace": "default", "workflow_name": "daily-standup", "baseline_execution_ids": [base_id]},
        ).json()

    rewritten_workflow = _workflow_manifest("daily-standup-opt-single")
    rewritten_workflow["spec"]["steps"] = [
        {
            "name": "standup-e2e",
            "type": "agent",
            "agentRef": "daily-standup-opt-single",
            "prompt": "Produce the same standup.md artifact in one consolidated agent pass.",
        }
    ]
    rewritten_agent = _agent_manifest("daily-standup-opt-single")
    rewritten_agent["spec"]["systemPrompt"] = (
        "You consolidate git, Jira, and final standup writing without losing required output behavior."
    )

    with _optimization_api_context():
        blocked = client.post(
            f"/api/v1/optimizations/studies/{study['id']}/candidates",
            headers=auth_headers,
            json={
                "name": "single step candidate",
                "optimizer_output": "merge compatible steps into one agent",
                "manifest_bundle": [rewritten_agent, rewritten_workflow],
            },
        )
        allowed = client.post(
            f"/api/v1/optimizations/studies/{study['id']}/candidates",
            headers=auth_headers,
            json={
                "name": "single step candidate",
                "optimizer_output": "merge compatible steps into one agent",
                "manifest_bundle": [rewritten_agent, rewritten_workflow],
                "allow_topology_rewrite": True,
            },
        )

    assert blocked.status_code == 422
    assert allowed.status_code == 201
    candidate = allowed.json()
    assert candidate["validation_results"]["valid"] is True
    assert candidate["validation_results"]["scope"] == "prompt_model_tool_topology_v1"
    assert candidate["validation_results"]["topology_preserved"] is False
    assert candidate["validation_results"]["optimizer_audit"]["topology_decision"]["decision"] == "rewritten"
    assert candidate["validation_results"]["optimizer_audit"]["topology_decision"]["rewrite_produced"] is True
    assert "topology-rewrite" in candidate["validation_results"]["optimizer_audit"]["skills_requested"]
    assert candidate["manifest_diff"]["topology"]["preserved"] is False
    workflow = next(manifest for manifest in candidate["manifest_bundle"] if manifest["kind"] == "AgentWorkflow")
    assert workflow["metadata"]["labels"]["kubesynapse.ai/topology-rewrite"] == "allowed"


def test_candidate_validation_rejects_source_model_changes(client, auth_headers) -> None:
    base_id = _seed_execution(execution_id="exec-opt-model-guard")
    with _optimization_api_context(manifests=True):
        study = client.post(
            "/api/v1/optimizations/studies",
            headers=auth_headers,
            json={"namespace": "default", "workflow_name": "daily-standup", "baseline_execution_ids": [base_id]},
        ).json()

    workflow = _workflow_manifest("daily-standup-opt-model")
    workflow["spec"]["steps"][0]["agentRef"] = "daily-standup-opt-model"
    agent = _agent_manifest("daily-standup-opt-model")
    agent["spec"]["model"] = "opencode-go/different-model"

    with _optimization_api_context():
        response = client.post(
            f"/api/v1/optimizations/studies/{study['id']}/candidates",
            headers=auth_headers,
            json={
                "name": "unsafe model candidate",
                "optimizer_output": "try a provider switch",
                "manifest_bundle": [agent, workflow],
            },
        )

    assert response.status_code == 422
    payload = response.json()
    detail = payload.get("detail") or payload.get("message") or str(payload)
    assert "model" in detail.lower()


def test_create_study_rejects_provided_manifests_without_workflow(client, auth_headers) -> None:
    baseline_id = _seed_execution(execution_id="exec-opt-bad-source")

    with _optimization_api_context(manifests=True):
        response = client.post(
            "/api/v1/optimizations/studies",
            headers=auth_headers,
            json={
                "namespace": "default",
                "workflow_name": "daily-standup",
                "baseline_execution_ids": [baseline_id],
                "source_manifests": {"agents": {"daily-standup": _agent_manifest()}},
            },
        )

    assert response.status_code == 422
    payload = response.json()
    detail = payload.get("detail") or payload.get("message") or str(payload)
    assert "source workflow manifest" in detail


def test_generate_candidate_does_not_copy_optimizer_output_into_manifest_annotations(client, auth_headers) -> None:
    baseline_id = _seed_execution(execution_id="exec-opt-output-redaction")

    with _optimization_api_context(manifests=True):
        study = client.post(
            "/api/v1/optimizations/studies",
            headers=auth_headers,
            json={"namespace": "default", "workflow_name": "daily-standup", "baseline_execution_ids": [baseline_id]},
        ).json()

    with _optimization_api_context():
        response = client.post(
            f"/api/v1/optimizations/studies/{study['id']}/candidates/generate",
            headers=auth_headers,
            json={
                "optimizer_output": "candidate review included token-like text sk-redacted-example-1234567890",
                "suffix": "opt-safe-output",
            },
        )

    assert response.status_code == 201, response.json()
    candidate = response.json()
    serialized_bundle = str(candidate["manifest_bundle"])
    assert "optimizer-output-preview" not in serialized_bundle
    assert "sk-redacted-example" not in serialized_bundle
    assert "token-like text" in candidate["optimizer_output"]


def test_generate_candidate_persists_redacted_optimizer_trace(client, auth_headers) -> None:
    base_id = _seed_execution(execution_id="exec-opt-trace")
    with _optimization_api_context(manifests=True):
        study = client.post(
            "/api/v1/optimizations/studies",
            headers=auth_headers,
            json={"namespace": "default", "workflow_name": "daily-standup", "baseline_execution_ids": [base_id]},
        ).json()

    optimizer_trace = {
        "request_id": "optimise-exec-opt-trace",
        "thread_id": "thread-opt-trace",
        "agent_name": "workflow-optimizer",
        "model": "opencode/deepseek-v4-flash-free",
        "status": "completed",
        "started_at": "2026-06-27T10:00:00Z",
        "completed_at": "2026-06-27T10:00:03Z",
        "duration_ms": 3000,
        "events": [
            {
                "id": "evt-1",
                "sequence": 1,
                "timestamp": "2026-06-27T10:00:00Z",
                "kind": "status",
                "title": "Optimizer started",
                "summary": "Loaded baseline dossier.",
            },
            {
                "id": "evt-2",
                "sequence": 2,
                "timestamp": "2026-06-27T10:00:00.500Z",
                "kind": "skill",
                "title": "Skill loaded",
                "summary": "critical-path-roi loaded from its materialized SKILL.md file.",
                "payload": {
                    "name": "critical-path-roi",
                    "file": "/app/state/home/.config/opencode/skills/critical-path-roi/SKILL.md",
                    "delivery": "system_prompt",
                },
            },
            {
                "id": "evt-3",
                "sequence": 3,
                "timestamp": "2026-06-27T10:00:01Z",
                "kind": "reasoning",
                "title": "Reasoning summary",
                "summary": "The slow step repeats deterministic reads.",
            },
            {
                "id": "evt-4",
                "sequence": 4,
                "timestamp": "2026-06-27T10:00:02Z",
                "kind": "tool",
                "title": "read",
                "summary": "Inspected source workflow.",
                "payload": {"path": "/workspace/workflow.yaml", "api_key": "sk-should-not-survive"},
            },
            {
                "id": "evt-5",
                "sequence": 5,
                "timestamp": "2026-06-27T10:00:03Z",
                "kind": "completion",
                "title": "Candidate ready",
                "summary": "Returned a contract-preserving manifest bundle.",
            },
        ],
        "tool_calls": [{"tool": "read", "args": {"authorization": "Bearer secret-value"}}],
        "artifacts": [{"path": "/workspace/candidate.yaml"}],
        "skills": ["critical-path-roi"],
        "resources": ["skill file: /app/state/home/.config/opencode/skills/critical-path-roi/SKILL.md"],
        "summary": {"event_count": 999, "tool_count": 999, "reasoning_event_count": 999},
    }

    with _optimization_api_context():
        response = client.post(
            f"/api/v1/optimizations/studies/{study['id']}/candidates/generate",
            headers=auth_headers,
            json={
                "optimizer_output": "Trim repeated context and deterministic reads.",
                "suffix": "opt-trace",
                "optimizer_trace": optimizer_trace,
            },
        )

    assert response.status_code == 201, response.json()
    persisted = response.json()["optimizer_trace"]
    assert persisted["request_id"] == "optimise-exec-opt-trace"
    assert persisted["thread_id"] == "thread-opt-trace"
    assert [event["sequence"] for event in persisted["events"]] == [1, 2, 3, 4, 5, 6]
    assert persisted["events"][1]["kind"] == "skill"
    assert persisted["events"][-1]["title"] == "Candidate persisted"
    assert persisted["summary"] == {
        "event_count": 6,
        "tool_count": 1,
        "reasoning_event_count": 1,
        "error_count": 0,
    }
    assert "critical-path-roi" in persisted["skills"]
    assert any("SKILL.md" in resource for resource in persisted["resources"])
    serialized = str(persisted)
    assert "sk-should-not-survive" not in serialized
    assert "Bearer secret-value" not in serialized
    assert "[REDACTED]" in serialized

    with _optimization_api_context():
        reloaded_study = client.get(
            f"/api/v1/optimizations/studies/{study['id']}",
            headers=auth_headers,
        ).json()
    reloaded_candidate = next(item for item in reloaded_study["candidates"] if item["id"] == response.json()["id"])
    assert reloaded_candidate["optimizer_trace"] == persisted


def test_generate_candidate_appends_persisted_candidate_trace_event(client, auth_headers) -> None:
    baseline_id = _seed_execution(execution_id="exec-opt-trace-persisted")
    with _optimization_api_context(manifests=True):
        study = client.post(
            "/api/v1/optimizations/studies",
            headers=auth_headers,
            json={"namespace": "default", "workflow_name": "daily-standup", "baseline_execution_ids": [baseline_id]},
        ).json()

    optimizer_trace = {
        "request_id": "optimise-exec-opt-trace-persisted",
        "thread_id": "thread-opt-trace-persisted",
        "agent_name": "workflow-optimizer",
        "model": "opencode/deepseek-v4-flash-free",
        "status": "completed",
        "events": [
            {
                "id": "evt-1",
                "sequence": 1,
                "timestamp": "2026-06-27T10:00:00Z",
                "kind": "status",
                "title": "Optimizer started",
                "summary": "Loaded the baseline dossier.",
            }
        ],
    }
    optimizer_output = """
```json
{
  "optimizer_decision_record": {
    "skills_used": ["critical-path-roi", "tool-economy"],
    "resources_used": ["baseline traces", "AgentWorkflow/daily-standup"],
    "topology_decision": {"decision": "preserve", "reason": "prompt-only change"},
    "topology_equivalence_map": [],
    "candidate_strategy": "Trim repeated reads while preserving workflow structure.",
    "regression_budget": {"duration_regression_percent": 0},
    "rejected_options": ["No safe topology rewrite needed."]
  }
}
```
"""

    with _optimization_api_context():
        response = client.post(
            f"/api/v1/optimizations/studies/{study['id']}/candidates/generate",
            headers=auth_headers,
            json={
                "optimizer_output": optimizer_output,
                "suffix": "opt-trace-persisted",
                "optimizer_trace": optimizer_trace,
            },
        )

    assert response.status_code == 201, response.json()
    persisted = response.json()["optimizer_trace"]
    assert any(event["title"] == "Candidate persisted" for event in persisted["events"])
    persisted_event = next(event for event in persisted["events"] if event["title"] == "Candidate persisted")
    assert persisted_event["kind"] == "completion"
    assert "daily-standup-opt-trace-persisted" in persisted_event["summary"]
    assert "critical-path-roi" in persisted["skills"]
    assert any("candidate workflow" in resource.lower() for resource in persisted["resources"])


def test_download_candidate_manifest_returns_persisted_yaml_bundle(client, auth_headers) -> None:
    baseline_id = _seed_execution(execution_id="exec-opt-manifest-download")
    with _optimization_api_context(manifests=True):
        study = client.post(
            "/api/v1/optimizations/studies",
            headers=auth_headers,
            json={"namespace": "default", "workflow_name": "daily-standup", "baseline_execution_ids": [baseline_id]},
        ).json()

    with _optimization_api_context():
        candidate_response = client.post(
            f"/api/v1/optimizations/studies/{study['id']}/candidates/generate",
            headers=auth_headers,
            json={
                "optimizer_output": "Create a conservative copied candidate.",
                "suffix": "opt-download",
            },
        )

    assert candidate_response.status_code == 201, candidate_response.json()
    candidate = candidate_response.json()
    response = client.get(
        f"/api/v1/optimizations/candidates/{candidate['id']}/manifest",
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/yaml")
    assert "attachment;" in response.headers["content-disposition"]
    assert "daily-standup-opt-download.yaml" in response.headers["content-disposition"]
    documents = list(yaml.safe_load_all(response.text))
    assert documents == candidate["manifest_bundle"]
    assert any(document["kind"] == "AgentWorkflow" for document in documents)
    assert any(document["kind"] == "AIAgent" for document in documents)


def test_candidate_registry_lists_across_studies_with_lineage(client, auth_headers) -> None:
    baseline_id = _seed_execution(execution_id="exec-opt-registry")
    created: list[tuple[dict, dict]] = []

    with _optimization_api_context(manifests=True):
        for suffix in ("registry-a", "registry-b"):
            study = client.post(
                "/api/v1/optimizations/studies",
                headers=auth_headers,
                json={
                    "namespace": "default",
                    "workflow_name": "daily-standup",
                    "baseline_execution_ids": [baseline_id],
                },
            ).json()
            candidate = client.post(
                f"/api/v1/optimizations/studies/{study['id']}/candidates/generate",
                headers=auth_headers,
                json={"optimizer_output": f"candidate {suffix}", "suffix": suffix},
            ).json()
            created.append((study, candidate))

    with _optimization_api_context():
        response = client.get(
            "/api/v1/optimizations/candidates",
            headers=auth_headers,
            params={"namespace": "default", "workflow_name": "daily-standup", "limit": 100},
        )

    assert response.status_code == 200, response.text
    payload = response.json()
    ids = [item["id"] for item in payload["items"]]
    assert created[0][1]["id"] in ids
    assert created[1][1]["id"] in ids
    selected = next(item for item in payload["items"] if item["id"] == created[1][1]["id"])
    assert selected["workflow_name"] == "daily-standup"
    assert selected["study_id"] == created[1][0]["id"]
    assert selected["baseline_execution_count"] == 1
    assert selected["trial_count"] == 0
    assert selected["tags"] == []
    assert selected["lifecycle_state"] == "active"


def test_candidate_registry_updates_tags_and_returns_detail(client, auth_headers) -> None:
    baseline_id = _seed_execution(execution_id="exec-opt-registry-tags")
    with _optimization_api_context(manifests=True):
        study = client.post(
            "/api/v1/optimizations/studies",
            headers=auth_headers,
            json={
                "namespace": "default",
                "workflow_name": "daily-standup",
                "baseline_execution_ids": [baseline_id],
            },
        ).json()
        candidate = client.post(
            f"/api/v1/optimizations/studies/{study['id']}/candidates/generate",
            headers=auth_headers,
            json={"optimizer_output": "taggable candidate", "suffix": "registry-tags"},
        ).json()

    with _optimization_api_context():
        updated = client.patch(
            f"/api/v1/optimizations/candidates/{candidate['id']}",
            headers=auth_headers,
            json={"tags": ["challenger", "team:platform", "challenger", "  cost-focus  "]},
        )
        detail = client.get(
            f"/api/v1/optimizations/candidates/{candidate['id']}",
            headers=auth_headers,
        )

    assert updated.status_code == 200, updated.text
    assert updated.json()["tags"] == ["challenger", "team:platform", "cost-focus"]
    assert detail.status_code == 200, detail.text
    assert detail.json()["candidate"]["id"] == candidate["id"]
    assert detail.json()["candidate"]["tags"] == ["challenger", "team:platform", "cost-focus"]
    assert detail.json()["study"]["id"] == study["id"]
    assert detail.json()["trials"] == []


def test_candidate_registry_delete_archives_and_hides_candidate(client, auth_headers) -> None:
    baseline_id = _seed_execution(execution_id="exec-opt-registry-archive")
    with _optimization_api_context(manifests=True):
        study = client.post(
            "/api/v1/optimizations/studies",
            headers=auth_headers,
            json={
                "namespace": "default",
                "workflow_name": "daily-standup",
                "baseline_execution_ids": [baseline_id],
            },
        ).json()
        candidate = client.post(
            f"/api/v1/optimizations/studies/{study['id']}/candidates/generate",
            headers=auth_headers,
            json={"optimizer_output": "archive candidate", "suffix": "registry-archive"},
        ).json()

    with _optimization_api_context():
        archived = client.delete(
            f"/api/v1/optimizations/candidates/{candidate['id']}",
            headers=auth_headers,
        )
        active = client.get(
            "/api/v1/optimizations/candidates",
            headers=auth_headers,
            params={"namespace": "default", "workflow_name": "daily-standup", "limit": 100},
        )
        including_archived = client.get(
            "/api/v1/optimizations/candidates",
            headers=auth_headers,
            params={
                "namespace": "default",
                "workflow_name": "daily-standup",
                "include_archived": "true",
                "limit": 100,
            },
        )

    assert archived.status_code == 200, archived.text
    assert archived.json()["lifecycle_state"] == "archived"
    assert archived.json()["archived_at"]
    assert candidate["id"] not in {item["id"] for item in active.json()["items"]}
    restored_item = next(item for item in including_archived.json()["items"] if item["id"] == candidate["id"])
    assert restored_item["lifecycle_state"] == "archived"


def test_generate_candidate_fallback_copies_manifests_without_roi_prompt_injection(client, auth_headers) -> None:
    baseline_id = _seed_execution(execution_id="exec-opt-guided-fallback")

    with _optimization_api_context(manifests=True):
        study = client.post(
            "/api/v1/optimizations/studies",
            headers=auth_headers,
            json={"namespace": "default", "workflow_name": "daily-standup", "baseline_execution_ids": [baseline_id]},
        ).json()

    with _optimization_api_context():
        response = client.post(
            f"/api/v1/optimizations/studies/{study['id']}/candidates/generate",
            headers=auth_headers,
            json={
                "optimizer_output": "Trim repeated reads and batch tool updates, but preserve all outputs.",
                "suffix": "opt-guided",
            },
        )

    assert response.status_code == 201
    candidate = response.json()
    bundle = candidate["manifest_bundle"]
    workflow = next(manifest for manifest in bundle if manifest["kind"] == "AgentWorkflow")
    agent = next(manifest for manifest in bundle if manifest["kind"] == "AIAgent")

    assert workflow["metadata"]["name"] == "daily-standup-opt-guided"
    assert workflow["spec"]["steps"][0]["agentRef"] == "daily-standup-opt-guided"
    assert "[ROI Candidate Guidance]" not in workflow["spec"]["steps"][0]["prompt"]
    assert workflow["spec"]["steps"][0]["prompt"] == "Read git and Jira context, then write standup.md."
    assert "[ROI Candidate Guidance]" not in agent["spec"]["systemPrompt"]
    assert agent["spec"]["systemPrompt"] == "You write daily standup reports."
    assert agent["spec"]["model"] == "opencode/deepseek-v4-flash-free"
    assert candidate["validation_results"]["no_effective_changes"] is True
    assert candidate["expected_savings"]["confidence"] == "control"
    assert candidate["expected_savings"]["duration_saved_percent"] == 0

    with _optimization_api_context():
        refreshed = client.get(f"/api/v1/optimizations/studies/{study['id']}", headers=auth_headers).json()
    assert (
        refreshed["source_manifests"]["workflow"]["spec"]["steps"][0]["prompt"]
        == "Read git and Jira context, then write standup.md."
    )
    assert (
        refreshed["source_manifests"]["agents"]["daily-standup"]["spec"]["systemPrompt"]
        == "You write daily standup reports."
    )


def test_generate_candidate_rejects_optimizer_meta_inside_candidate_prompts(client, auth_headers) -> None:
    baseline_id = _seed_execution(execution_id="exec-opt-meta-noise")

    with _optimization_api_context(manifests=True):
        study = client.post(
            "/api/v1/optimizations/studies",
            headers=auth_headers,
            json={"namespace": "default", "workflow_name": "daily-standup", "baseline_execution_ids": [baseline_id]},
        ).json()

    optimizer_output = """
```yaml
apiVersion: kubesynapse.ai/v1alpha1
kind: AIAgent
metadata:
  name: daily-standup
  namespace: default
spec:
  model: opencode/deepseek-v4-flash-free
  runtime:
    kind: opencode
  systemPrompt: |
    [ROI Candidate Guidance]
    You are running inside ROI Lab. Beat the baseline-vs-candidate trial.
---
apiVersion: kubesynapse.ai/v1alpha1
kind: AgentWorkflow
metadata:
  name: daily-standup
  namespace: default
spec:
  input: Generate a daily standup.
  steps:
    - name: summarise
      type: agent
      agentRef: daily-standup
      prompt: Write standup.md.
```
"""

    with _optimization_api_context():
        response = client.post(
            f"/api/v1/optimizations/studies/{study['id']}/candidates/generate",
            headers=auth_headers,
            json={"optimizer_output": optimizer_output, "suffix": "opt-meta"},
        )

    assert response.status_code == 201, response.json()
    candidate = response.json()
    serialized_bundle = str(candidate["manifest_bundle"])
    assert "[ROI Candidate Guidance]" not in serialized_bundle
    assert "baseline-vs-candidate" not in serialized_bundle
    assert candidate["validation_results"]["no_effective_changes"] is True
    assert any("optimizer/roi lab meta" in warning.lower() for warning in candidate["validation_results"]["warnings"])


def test_validate_contract_preservation_rejects_dropped_output_path() -> None:
    """A candidate that drops a required /workspace output path is rejected."""
    from routers.optimizations import _validate_contract_preservation

    source = {
        "spec": {
            "messageBus": "in-memory",
            "steps": [
                {
                    "name": "summarize-git",
                    "type": "agent",
                    "agentRef": "git-agent",
                    "prompt": "Write the output to /workspace/commits-summary.md.",
                },
                {
                    "name": "track-jira",
                    "type": "agent",
                    "agentRef": "jira-agent",
                    "prompt": "Write the output to /workspace/sprint-status.json.",
                },
            ],
        }
    }
    candidate = {
        "spec": {
            "messageBus": "in-memory",
            "steps": [
                {
                    "name": "summarize-git",
                    "type": "agent",
                    "agentRef": "git-agent",
                    "prompt": "Produce a summary of the commits.",
                },
                {
                    "name": "track-jira",
                    "type": "agent",
                    "agentRef": "jira-agent",
                    "prompt": "Write the output to /workspace/sprint-status.json.",
                },
            ],
        }
    }
    violations = _validate_contract_preservation(source, candidate)
    codes = [v["code"] for v in violations if v["severity"] == "error"]
    assert "dropped_output_path" in codes


def test_validate_contract_preservation_rejects_broken_handoff() -> None:
    """Replacing embedded handoff with file reads on an in-memory bus is rejected."""
    from routers.optimizations import _validate_contract_preservation

    source = {
        "spec": {
            "messageBus": "in-memory",
            "steps": [
                {
                    "name": "summarize-git",
                    "type": "agent",
                    "agentRef": "git",
                    "prompt": "Write to /workspace/commits-summary.md.\n[FILE_CONTENT]\n(paste content)\n[/FILE_CONTENT]",
                },
                {
                    "name": "track-jira",
                    "type": "agent",
                    "agentRef": "jira",
                    "prompt": "Write to /workspace/sprint-status.json.\n[FILE_CONTENT]\n(paste content)\n[/FILE_CONTENT]",
                },
                {
                    "name": "compose",
                    "type": "agent",
                    "agentRef": "scribe",
                    "dependsOn": ["summarize-git", "track-jira"],
                    "prompt": "Use the embedded content from {{previous_output}}. Write to /workspace/standup.md.",
                },
            ],
        }
    }
    candidate = {
        "spec": {
            "messageBus": "in-memory",
            "steps": [
                {
                    "name": "summarize-git",
                    "type": "agent",
                    "agentRef": "git",
                    "prompt": "Write to /workspace/commits-summary.md.",
                },
                {
                    "name": "track-jira",
                    "type": "agent",
                    "agentRef": "jira",
                    "prompt": "Write to /workspace/sprint-status.json.",
                },
                {
                    "name": "compose",
                    "type": "agent",
                    "agentRef": "scribe",
                    "dependsOn": ["summarize-git", "track-jira"],
                    "prompt": "Read /workspace/commits-summary.md and /workspace/sprint-status.json. Write to /workspace/standup.md.",
                },
            ],
        }
    }
    violations = _validate_contract_preservation(source, candidate)
    codes = [v["code"] for v in violations if v["severity"] == "error"]
    # compose switched from embedded to file reads on an in-memory bus, and the
    # file reads are unsatisfiable because pods don't share /workspace.
    assert "handoff_mode_broken" in codes or "unsatisfiable_read" in codes


def test_validate_contract_preservation_rejects_stripped_inline_data() -> None:
    """Stripping inline input data from a step prompt is rejected."""
    from routers.optimizations import _validate_contract_preservation

    source = {
        "spec": {
            "messageBus": "in-memory",
            "steps": [
                {
                    "name": "summarize-git",
                    "type": "agent",
                    "agentRef": "git",
                    "prompt": "## Task: Summarize Git Activity\n\nGit log:\nabc1234 | alice | feat: add thing\n\nWrite to /workspace/commits-summary.md.",
                },
            ],
        }
    }
    candidate = {
        "spec": {
            "messageBus": "in-memory",
            "steps": [
                {
                    "name": "summarize-git",
                    "type": "agent",
                    "agentRef": "git",
                    "prompt": "## Task: Summarize Git Activity\n[Git log data follows]\nWrite to /workspace/commits-summary.md.",
                },
            ],
        }
    }
    violations = _validate_contract_preservation(source, candidate)
    codes = [v["code"] for v in violations if v["severity"] == "error"]
    assert "stripped_inline_data" in codes


def test_sanitize_candidate_prompt_strips_tool_bans() -> None:
    """Optimizer-injected tool bans and one-pass directives are stripped."""
    from routers.optimizations import _sanitize_candidate_prompt

    prompt = (
        "## Task: Summarize Git Activity\n"
        "Write to /workspace/commits-summary.md.\n\n"
        "IMPORTANT: Do NOT use todowrite. Complete the task in one pass and write the file."
    )
    sanitized = _sanitize_candidate_prompt(prompt)
    assert "Do NOT use todowrite" not in sanitized
    assert "Complete the task in one pass" not in sanitized
    assert "Summarize Git Activity" in sanitized
    assert "/workspace/commits-summary.md" in sanitized


def test_reconstructed_source_agent_does_not_leak_preamble_into_systemprompt() -> None:
    """The reconstruction preamble must live in annotations, not systemPrompt."""
    from routers.optimizations import _reconstructed_source_agent

    workflow = {
        "spec": {
            "steps": [
                {
                    "name": "summarize-git",
                    "agentRef": "standup-git",
                    "prompt": "Summarize git commits and write /workspace/commits-summary.md.",
                },
            ]
        }
    }
    agent = _reconstructed_source_agent(
        namespace="default",
        agent_ref="standup-git",
        workflow_manifest=workflow,
        traces=None,
    )
    system_prompt = agent["spec"]["systemPrompt"]
    assert "Reconstructed source contract" not in system_prompt
    assert "Summarize git commits" not in system_prompt
    annotations = agent["metadata"]["annotations"]
    assert annotations["kubesynapse.ai/reconstructed-source"] == "true"
    assert "Summarize git commits" in annotations["kubesynapse.ai/reconstructed-step-contract"]


def test_generate_candidate_rejects_broken_handoff_via_contract_gate(client, auth_headers) -> None:
    """End-to-end: a candidate that breaks the in-memory handoff falls back to a no-change control."""
    baseline_id = _seed_execution(execution_id="exec-opt-contract-break")

    source_workflow = _workflow_manifest("daily-standup")
    source_workflow["spec"]["messageBus"] = "in-memory"
    source_workflow["spec"]["steps"] = [
        {
            "name": "summarize-git",
            "type": "agent",
            "agentRef": "standup-git",
            "prompt": "Summarize the git log below.\nabc1234 | alice | feat: x\nWrite to /workspace/commits-summary.md.\n[FILE_CONTENT]\n(paste)\n[/FILE_CONTENT]",
        },
        {
            "name": "compose",
            "type": "agent",
            "agentRef": "standup-scribe",
            "dependsOn": ["summarize-git"],
            "prompt": "Use {{previous_output}} to write /workspace/standup.md.",
        },
    ]

    with _optimization_api_context():
        study = client.post(
            "/api/v1/optimizations/studies",
            headers=auth_headers,
            json={
                "namespace": "default",
                "workflow_name": "daily-standup",
                "baseline_execution_ids": [baseline_id],
                "source_manifests": {
                    "workflow": source_workflow,
                    "agent_refs": ["standup-git", "standup-scribe"],
                    "agents": {
                        "standup-git": _agent_manifest("standup-git"),
                        "standup-scribe": _agent_manifest("standup-scribe"),
                    },
                },
            },
        ).json()

    optimizer_output = """
```yaml
apiVersion: kubesynapse.ai/v1alpha1
kind: AgentWorkflow
metadata:
  name: daily-standup
  namespace: default
spec:
  messageBus: in-memory
  steps:
    - name: summarize-git
      type: agent
      agentRef: standup-git
      prompt: Produce a summary. Write to /workspace/commits-summary.md.
    - name: compose
      type: agent
      agentRef: standup-scribe
      dependsOn: ["summarize-git"]
      prompt: Read /workspace/commits-summary.md and write /workspace/standup.md.
```
"""

    with _optimization_api_context():
        response = client.post(
            f"/api/v1/optimizations/studies/{study['id']}/candidates/generate",
            headers=auth_headers,
            json={"optimizer_output": optimizer_output, "suffix": "opt-break"},
        )

    assert response.status_code == 201, response.json()
    candidate = response.json()
    # The broken candidate must fall back to a no-change control.
    assert candidate["validation_results"]["no_effective_changes"] is True
    assert any("failed validation" in w.lower() for w in candidate["validation_results"]["warnings"])
    baseline_id = _seed_execution(execution_id="exec-opt-generated-manifest")

    with _optimization_api_context(manifests=True):
        study = client.post(
            "/api/v1/optimizations/studies",
            headers=auth_headers,
            json={"namespace": "default", "workflow_name": "daily-standup", "baseline_execution_ids": [baseline_id]},
        ).json()

    optimizer_output = """
The candidate keeps the same workflow topology and trims repeated context.

```yaml
apiVersion: kubesynapse.ai/v1alpha1
kind: AIAgent
metadata:
  name: daily-standup
  namespace: default
spec:
  model: opencode-go/different-model
  runtime:
    kind: opencode
  mcpConnections:
    - name: filesystem
      server_id: filesystem-sidecar
  systemPrompt: >
    Produce the standup from already loaded Git and Jira summaries.
    Avoid rereading unchanged files; batch deterministic file reads first.
---
apiVersion: kubesynapse.ai/v1alpha1
kind: AgentWorkflow
metadata:
  name: daily-standup
  namespace: default
spec:
  input: Generate a daily standup.
  steps:
    - name: summarise
      type: agent
      agentRef: daily-standup
      prompt: >
        Use the provided Git and Jira summaries to write standup.md.
        Read only missing artifacts and avoid repeating the same workspace scan.
```
"""

    with _optimization_api_context():
        response = client.post(
            f"/api/v1/optimizations/studies/{study['id']}/candidates/generate",
            headers=auth_headers,
            json={"optimizer_output": optimizer_output, "suffix": "opt-agent"},
        )

    assert response.status_code == 201
    candidate = response.json()
    bundle = candidate["manifest_bundle"]
    workflow = next(manifest for manifest in bundle if manifest["kind"] == "AgentWorkflow")
    agent = next(manifest for manifest in bundle if manifest["kind"] == "AIAgent")

    assert workflow["metadata"]["name"] == "daily-standup-opt-agent"
    assert agent["metadata"]["name"] == "daily-standup-opt-agent"
    assert workflow["spec"]["steps"][0]["name"] == "summarise"
    assert workflow["spec"]["steps"][0]["agentRef"] == "daily-standup-opt-agent"
    assert "avoid repeating the same workspace scan" in workflow["spec"]["steps"][0]["prompt"]
    assert agent["spec"]["model"] == "opencode/deepseek-v4-flash-free"
    assert "Avoid rereading unchanged files" in agent["spec"]["systemPrompt"]
    assert candidate["validation_results"]["no_effective_changes"] is False
    assert "AIAgent.daily-standup.spec.systemPrompt" in candidate["validation_results"]["effective_changes"]

    with _optimization_api_context():
        refreshed = client.get(f"/api/v1/optimizations/studies/{study['id']}", headers=auth_headers).json()
    source_workflow = refreshed["source_manifests"]["workflow"]
    source_agent = refreshed["source_manifests"]["agents"]["daily-standup"]
    assert source_workflow["metadata"]["name"] == "daily-standup"
    assert source_workflow["spec"]["steps"][0]["prompt"] == "Read git and Jira context, then write standup.md."
    assert source_agent["spec"]["model"] == "opencode/deepseek-v4-flash-free"


def test_generate_candidate_repairs_optimizer_manifest_topology_rewrite(client, auth_headers) -> None:
    baseline_id = _seed_execution(execution_id="exec-opt-generated-unsafe")

    with _optimization_api_context(manifests=True):
        study = client.post(
            "/api/v1/optimizations/studies",
            headers=auth_headers,
            json={"namespace": "default", "workflow_name": "daily-standup", "baseline_execution_ids": [baseline_id]},
        ).json()

    optimizer_output = """
```yaml
apiVersion: kubesynapse.ai/v1alpha1
kind: AgentWorkflow
metadata:
  name: daily-standup
  namespace: default
spec:
  input: Generate a daily standup.
  steps:
    - name: summarise
      type: agent
      agentRef: daily-standup
      prompt: Keep the original behavior.
    - name: publish
      type: agent
      agentRef: daily-standup
      prompt: Push the report to chat.
```
"""

    with _optimization_api_context():
        response = client.post(
            f"/api/v1/optimizations/studies/{study['id']}/candidates/generate",
            headers=auth_headers,
            json={"optimizer_output": optimizer_output, "suffix": "opt-unsafe"},
        )

    assert response.status_code == 201
    candidate = response.json()
    workflow = next(manifest for manifest in candidate["manifest_bundle"] if manifest["kind"] == "AgentWorkflow")
    steps = workflow["spec"]["steps"]
    assert [(step["name"], step["type"]) for step in steps] == [("summarise", "agent")]
    assert steps[0]["agentRef"] == "daily-standup-opt-unsafe"
    assert "Keep the original behavior" in steps[0]["prompt"]
    assert "publish" not in str(steps)
    assert candidate["validation_results"]["valid"] is True
    assert candidate["validation_results"]["topology_preserved"] is True
    assert any("topology" in warning.lower() for warning in candidate["validation_results"]["warnings"])


def test_generate_candidate_normalizes_topology_rewrite_api_versions(client, auth_headers) -> None:
    baseline_id = _seed_execution(execution_id="exec-opt-generated-version-normalize")

    with _optimization_api_context(manifests=True):
        study = client.post(
            "/api/v1/optimizations/studies",
            headers=auth_headers,
            json={"namespace": "default", "workflow_name": "daily-standup", "baseline_execution_ids": [baseline_id]},
        ).json()

    optimizer_output = """
```yaml
apiVersion: kubesynapse.ai/v1
kind: AgentWorkflow
metadata:
  name: daily-standup-single-pass
  namespace: default
spec:
  steps:
    - name: standup-e2e
      type: agent
      agentRef: standup-single-pass
      prompt: Preserve the same standup artifact in one consolidated pass.
---
apiVersion: kubesynapse.ai/v1
kind: AIAgent
metadata:
  name: standup-single-pass
  namespace: default
spec:
  model: opencode/deepseek-v4-flash-free
  runtime:
    kind: opencode
  systemPrompt: Preserve the baseline report contract with fewer repeated tool calls.
```
"""

    with _optimization_api_context():
        response = client.post(
            f"/api/v1/optimizations/studies/{study['id']}/candidates/generate",
            headers=auth_headers,
            json={"optimizer_output": optimizer_output, "suffix": "opt-single", "allow_topology_rewrite": True},
        )

    assert response.status_code == 201, response.json()
    candidate = response.json()
    assert {manifest["apiVersion"] for manifest in candidate["manifest_bundle"]} == {"kubesynapse.ai/v1alpha1"}
    extra_agent = next(
        manifest
        for manifest in candidate["manifest_bundle"]
        if manifest["kind"] == "AIAgent" and manifest["metadata"]["name"] == "standup-single-pass-opt-single"
    )
    assert extra_agent["metadata"]["labels"]["kubesynapse.ai/topology-rewrite"] == "allowed"
    assert candidate["validation_results"]["topology_rewrite_allowed"] is True


def test_generate_candidate_records_optimizer_audit_when_topology_rewrite_preserves_graph(client, auth_headers) -> None:
    baseline_id = _seed_execution(execution_id="exec-opt-audit-preserve-topology")

    with _optimization_api_context(manifests=True):
        study = client.post(
            "/api/v1/optimizations/studies",
            headers=auth_headers,
            json={"namespace": "default", "workflow_name": "daily-standup", "baseline_execution_ids": [baseline_id]},
        ).json()

    optimizer_output = """
The optimizer evaluated a single-agent consolidation and rejected it because the source contract needs the existing handoff for review.

```json
{
  "optimizer_decision_record": {
    "skills_used": ["critical-path-roi", "context-compression", "topology-rewrite", "regression-proof-gate"],
    "resources_used": ["baseline traces", "AgentWorkflow/daily-standup", "AIAgent/daily-standup"],
    "topology_decision": {"decision": "preserve", "reason": "single-step source already has no safe topology reduction"},
    "topology_equivalence_map": [{"source_step": "summarise", "candidate_responsibility": "summarise"}],
    "candidate_strategy": "Trim context and repeated tool reads while preserving the step graph.",
    "regression_budget": {"duration_regression_percent": 0},
    "rejected_options": ["No fewer-step candidate exists for a one-step workflow."]
  }
}
```

```yaml
apiVersion: kubesynapse.ai/v1alpha1
kind: AIAgent
metadata:
  name: daily-standup
  namespace: default
spec:
  model: opencode/deepseek-v4-flash-free
  runtime:
    kind: opencode
  systemPrompt: >
    Produce the standup artifact using already loaded Git and Jira summaries.
    Read each source artifact at most once, then write standup.md once.
---
apiVersion: kubesynapse.ai/v1alpha1
kind: AgentWorkflow
metadata:
  name: daily-standup
  namespace: default
spec:
  input: Generate a daily standup.
  steps:
    - name: summarise
      type: agent
      agentRef: daily-standup
      prompt: >
        Read known Git and Jira inputs once, reuse summaries, and write standup.md.
```
"""

    with _optimization_api_context():
        response = client.post(
            f"/api/v1/optimizations/studies/{study['id']}/candidates/generate",
            headers=auth_headers,
            json={"optimizer_output": optimizer_output, "suffix": "opt-audit", "allow_topology_rewrite": True},
        )

    assert response.status_code == 201, response.json()
    candidate = response.json()
    validation = candidate["validation_results"]
    audit = validation["optimizer_audit"]
    assert validation["valid"] is True
    assert validation["topology_preserved"] is True
    assert any("topology rewrite was allowed" in warning.lower() for warning in validation["warnings"])
    assert audit["private_reasoning"] == "not_exposed"
    assert audit["topology_decision"]["mode"] == "allow_topology_rewrite"
    assert audit["topology_decision"]["decision"] == "preserved_after_review"
    assert audit["topology_decision"]["rewrite_produced"] is False
    assert "topology-rewrite" in audit["skills_requested"]
    assert "topology-rewrite" in audit["skills_used"]
    assert audit["parsed_blocks"]["optimizer_decision_record"] is True
    assert audit["parsed_blocks"]["candidate_manifest_bundle"] is True
    assert audit["resources_used"]["source_agent_refs"] == ["daily-standup"]
    assert "single-agent consolidation" in audit["visible_response_excerpt"]


def test_generate_candidate_recovers_from_incomplete_optimizer_manifest(client, auth_headers) -> None:
    baseline_id = _seed_execution(execution_id="exec-opt-incomplete-output")

    with _optimization_api_context(manifests=True):
        study = client.post(
            "/api/v1/optimizations/studies",
            headers=auth_headers,
            json={"namespace": "default", "workflow_name": "daily-standup", "baseline_execution_ids": [baseline_id]},
        ).json()

    optimizer_output = """
The candidate only needs an agent prompt trim.

```yaml
apiVersion: kubesynapse.ai/v1alpha1
kind: AIAgent
metadata:
  name: generated-agent-name
  namespace: default
spec:
  model: opencode-go/different-model
  runtime:
    kind: opencode
  systemPrompt: >
    Keep the same output contract, but avoid rereading unchanged workspace files.
```
"""

    with _optimization_api_context():
        response = client.post(
            f"/api/v1/optimizations/studies/{study['id']}/candidates/generate",
            headers=auth_headers,
            json={"optimizer_output": optimizer_output, "suffix": "opt-incomplete"},
        )

    assert response.status_code == 201
    candidate = response.json()
    bundle = candidate["manifest_bundle"]
    workflow = next(manifest for manifest in bundle if manifest["kind"] == "AgentWorkflow")
    agent = next(manifest for manifest in bundle if manifest["kind"] == "AIAgent")

    assert workflow["metadata"]["name"] == "daily-standup-opt-incomplete"
    assert workflow["spec"]["steps"][0]["agentRef"] == "daily-standup-opt-incomplete"
    assert agent["metadata"]["name"] == "daily-standup-opt-incomplete"
    assert agent["spec"]["model"] == "opencode/deepseek-v4-flash-free"
    assert agent["spec"]["runtime"] == {"kind": "opencode"}
    assert agent["spec"]["mcpConnections"] == [{"name": "filesystem", "server_id": "filesystem-sidecar"}]
    assert "avoid rereading unchanged workspace files" in agent["spec"]["systemPrompt"]
    assert candidate["validation_results"]["valid"] is True
    assert any("workflow manifest" in warning.lower() for warning in candidate["validation_results"]["warnings"])


def test_generate_candidate_normalizes_unexpected_workflow_name(client, auth_headers) -> None:
    baseline_id = _seed_execution(execution_id="exec-opt-unexpected-name")

    with _optimization_api_context(manifests=True):
        study = client.post(
            "/api/v1/optimizations/studies",
            headers=auth_headers,
            json={"namespace": "default", "workflow_name": "daily-standup", "baseline_execution_ids": [baseline_id]},
        ).json()

    optimizer_output = """
```yaml
apiVersion: kubesynapse.ai/v1alpha1
kind: AgentWorkflow
metadata:
  name: optimizer-invented-name
  namespace: default
spec:
  input: Generate a daily standup.
  steps:
    - name: summarise
      type: agent
      agentRef: optimizer-invented-agent
      prompt: >
        Reuse existing context summaries before reading files, then write standup.md.
```
"""

    with _optimization_api_context():
        response = client.post(
            f"/api/v1/optimizations/studies/{study['id']}/candidates/generate",
            headers=auth_headers,
            json={"optimizer_output": optimizer_output, "suffix": "opt-named"},
        )

    assert response.status_code == 201
    candidate = response.json()
    workflow = next(manifest for manifest in candidate["manifest_bundle"] if manifest["kind"] == "AgentWorkflow")
    assert workflow["metadata"]["name"] == "daily-standup-opt-named"
    assert workflow["spec"]["steps"][0]["name"] == "summarise"
    assert workflow["spec"]["steps"][0]["agentRef"] == "daily-standup-opt-named"
    assert "Reuse existing context summaries" in workflow["spec"]["steps"][0]["prompt"]
    assert any("name" in warning.lower() for warning in candidate["validation_results"]["warnings"])


def test_generate_candidate_falls_back_when_optimizer_manifest_fails_validation(client, auth_headers) -> None:
    baseline_id = _seed_execution(execution_id="exec-opt-unsafe-generated")

    with _optimization_api_context(manifests=True):
        study = client.post(
            "/api/v1/optimizations/studies",
            headers=auth_headers,
            json={"namespace": "default", "workflow_name": "daily-standup", "baseline_execution_ids": [baseline_id]},
        ).json()

    optimizer_output = """
The optimizer candidate accidentally references a topology agent it forgot to include.

```yaml
apiVersion: kubesynapse.ai/v1alpha1
kind: AgentWorkflow
metadata:
  name: daily-standup
  namespace: default
spec:
  steps:
    - name: standup-e2e
      type: agent
      agentRef: missing-optimizer-agent
      prompt: Preserve the same standup.md output in one pass.
```
"""

    with _optimization_api_context():
        response = client.post(
            f"/api/v1/optimizations/studies/{study['id']}/candidates/generate",
            headers=auth_headers,
            json={"optimizer_output": optimizer_output, "suffix": "opt-safe-fallback", "allow_topology_rewrite": True},
        )

    assert response.status_code == 201, response.json()
    candidate = response.json()
    serialized_bundle = str(candidate["manifest_bundle"])
    assert "missing-optimizer-agent" not in serialized_bundle
    assert candidate["candidate_workflow_name"] == "daily-standup-opt-safe-fallback"
    assert candidate["validation_results"]["valid"] is True
    assert any("safe copied candidate" in warning.lower() for warning in candidate["validation_results"]["warnings"])
    assert any("missing candidate agent" in warning.lower() for warning in candidate["validation_results"]["warnings"])


def test_list_studies_returns_recent_workflow_studies_with_candidates(client, auth_headers) -> None:
    older_baseline_id = _seed_execution(execution_id="exec-opt-list-older")
    newer_baseline_id = _seed_execution(execution_id="exec-opt-list-newer")

    with _optimization_api_context(manifests=True):
        older = client.post(
            "/api/v1/optimizations/studies",
            headers=auth_headers,
            json={
                "namespace": "default",
                "workflow_name": "daily-standup",
                "baseline_execution_ids": [older_baseline_id],
                "objective": "Older study",
            },
        ).json()
        newer = client.post(
            "/api/v1/optimizations/studies",
            headers=auth_headers,
            json={
                "namespace": "default",
                "workflow_name": "daily-standup",
                "baseline_execution_ids": [newer_baseline_id],
                "objective": "Newer study",
            },
        ).json()

    with _optimization_api_context():
        candidate_response = client.post(
            f"/api/v1/optimizations/studies/{newer['id']}/candidates/generate",
            headers=auth_headers,
            json={"optimizer_output": "trim repeated context and batch deterministic reads", "suffix": "opt-listed"},
        )
        response = client.get(
            "/api/v1/optimizations/studies?namespace=default&workflow_name=daily-standup&limit=10",
            headers=auth_headers,
        )

    assert candidate_response.status_code == 201
    assert response.status_code == 200
    studies = response.json()["items"]
    assert [study["id"] for study in studies[:2]] == [newer["id"], older["id"]]
    assert studies[0]["candidates"][0]["candidate_workflow_name"] == "daily-standup-opt-listed"
    assert studies[0]["trials"] == []


def test_candidate_lifecycle_approval_trials_and_verified_roi(client, auth_headers) -> None:
    baseline_id = _seed_execution(
        execution_id="exec-opt-roi-base", duration_ms=100_000, tokens=2_000, cost_usd=0.08, tool_calls=8
    )
    candidate_execution_ids = [
        _seed_execution(
            execution_id=f"exec-opt-roi-candidate-{index}",
            workflow_name="daily-standup-opt-roi1",
            duration_ms=60_000,
            tokens=1_100,
            cost_usd=0.044,
            tool_calls=4,
        )
        for index in range(5)
    ]

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
                "result_execution_id": candidate_execution_ids[0],
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

        for candidate_execution_id in candidate_execution_ids:
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
    assert data["proof_gate"]["minimum_safe_trials"] == 5
    assert data["deltas"]["tokens_saved_percent"] == 45.0
    assert data["deltas"]["duration_saved_percent"] == 40.0
    assert data["deltas"]["cost_saved_percent"] == 45.0
    assert data["candidate_metrics"]["success_rate"] == 1.0


def test_roi_marks_regression_when_candidate_trials_are_slower(client, auth_headers) -> None:
    baseline_id = _seed_execution(
        execution_id="exec-opt-regress-base",
        duration_ms=100_000,
        tokens=2_000,
        cost_usd=0.08,
        tool_calls=8,
    )
    candidate_execution_ids = [
        _seed_execution(
            execution_id=f"exec-opt-regress-candidate-{index}",
            workflow_name="daily-standup-opt-regress",
            duration_ms=150_000,
            tokens=1_500,
            cost_usd=0.06,
            tool_calls=6,
        )
        for index in range(5)
    ]

    with _optimization_api_context(manifests=True):
        study = client.post(
            "/api/v1/optimizations/studies",
            headers=auth_headers,
            json={"namespace": "default", "workflow_name": "daily-standup", "baseline_execution_ids": [baseline_id]},
        ).json()

    with _optimization_api_context():
        candidate = client.post(
            f"/api/v1/optimizations/studies/{study['id']}/candidates/generate",
            headers=auth_headers,
            json={"optimizer_output": "trim repeated context", "suffix": "opt-regress"},
        ).json()
        client.post(
            f"/api/v1/optimizations/candidates/{candidate['id']}/approval",
            headers=auth_headers,
            json={"decision": "approved", "reason": "Regression test candidate."},
        )
        for candidate_execution_id in candidate_execution_ids:
            client.post(
                f"/api/v1/optimizations/candidates/{candidate['id']}/trials",
                headers=auth_headers,
                json={
                    "baseline_execution_id": baseline_id,
                    "result_execution_id": candidate_execution_id,
                    "quality_status": "passed",
                },
            )
        roi = client.get(f"/api/v1/optimizations/studies/{study['id']}/roi", headers=auth_headers)

    assert roi.status_code == 200
    payload = roi.json()
    assert payload["verified"] is False
    assert payload["proof_status"] == "regression"
    assert payload["metric_source"] == "paired_trials"
    assert payload["deltas"]["duration_saved_percent"] == -50.0
    assert payload["regression_deltas"]["duration_saved_percent"] == -50.0


def test_roi_comparison_exposes_trials_steps_tools_and_manifest_diff(client, auth_headers) -> None:
    baseline_ids = [
        _seed_execution(
            execution_id="exec-opt-compare-base-1",
            duration_ms=100_000,
            tokens=2_000,
            cost_usd=0.08,
            tool_calls=8,
        ),
        _seed_execution(
            execution_id="exec-opt-compare-base-2",
            duration_ms=120_000,
            tokens=2_200,
            cost_usd=0.088,
            tool_calls=10,
        ),
    ]
    candidate_execution_id = _seed_execution(
        execution_id="exec-opt-compare-candidate-1",
        workflow_name="daily-standup-opt-compare",
        duration_ms=55_000,
        tokens=1_100,
        cost_usd=0.044,
        tool_calls=4,
    )

    with _optimization_api_context(manifests=True):
        study = client.post(
            "/api/v1/optimizations/studies",
            headers=auth_headers,
            json={
                "namespace": "default",
                "workflow_name": "daily-standup",
                "baseline_execution_ids": baseline_ids,
            },
        ).json()

    with _optimization_api_context():
        candidate = client.post(
            f"/api/v1/optimizations/studies/{study['id']}/candidates/generate",
            headers=auth_headers,
            json={
                "optimizer_output": "Trim repeated context and batch deterministic file reads.",
                "suffix": "opt-compare",
            },
        ).json()
        client.post(
            f"/api/v1/optimizations/candidates/{candidate['id']}/approval",
            headers=auth_headers,
            json={"decision": "approved", "reason": "Compare isolated candidate copy."},
        )
        client.post(
            f"/api/v1/optimizations/candidates/{candidate['id']}/trials",
            headers=auth_headers,
            json={
                "baseline_execution_id": baseline_ids[0],
                "result_execution_id": candidate_execution_id,
                "quality_status": "passed",
                "notes": "Output matched the baseline artifact contract.",
            },
        )
        response = client.get(
            f"/api/v1/optimizations/studies/{study['id']}/comparison?candidate_id={candidate['id']}",
            headers=auth_headers,
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["roi"]["candidate_id"] == candidate["id"]
    assert payload["comparison"]["headline"]["primary_saving_key"] == "duration_saved_percent"
    assert payload["comparison"]["headline"]["primary_saving_percent"] == 45.0
    assert payload["comparison"]["headline"]["metric_source"] == "paired_trials"
    assert "45.0% time" in payload["comparison"]["headline"]["summary"]
    assert "time" in payload["comparison"]["headline"]["summary"].lower()
    scorecard = payload["comparison"]["scorecard"]
    assert scorecard["metric_source"] == "paired_trials"
    assert scorecard["trial_count"] == 1
    assert scorecard["safe_trial_count"] == 1
    assert scorecard["summary"] == payload["comparison"]["headline"]["summary"]
    duration_metric = next(item for item in scorecard["metrics"] if item["key"] == "duration_saved_percent")
    assert duration_metric["baseline_value"] == 100_000.0
    assert duration_metric["candidate_value"] == 55_000.0
    assert duration_metric["actual_delta_percent"] == 45.0
    assert duration_metric["estimated_delta_percent"] == 0.0
    tool_metric = next(item for item in scorecard["metrics"] if item["key"] == "tool_calls_saved_percent")
    assert tool_metric["actual_delta_percent"] == 50.0
    assert scorecard["next_action"] == "run_more_trials"
    assert scorecard["safe_trials_remaining"] == 4

    trial = payload["comparison"]["trials"][0]
    assert trial["baseline"]["execution_id"] == baseline_ids[0]
    assert trial["candidate"]["execution_id"] == candidate_execution_id
    assert trial["deltas"]["duration_saved_percent"] == 45.0
    assert trial["deltas"]["tokens_saved_percent"] == 45.0
    assert trial["deltas"]["tool_calls_saved_percent"] == 50.0

    step = payload["comparison"]["steps"][0]
    assert step["step_name"] == "summarise"
    assert step["baseline"]["avg_tokens"] == 2100.0
    assert step["candidate"]["avg_tokens"] == 1100.0
    assert step["deltas"]["tokens_saved_percent"] == 47.6

    tool_names = {item["tool_name"] for item in payload["comparison"]["tools"]}
    assert {"read", "write"} <= tool_names

    manifest = payload["comparison"]["manifest_diff"]
    assert manifest["topology_preserved"] is True
    workflow_section = next(section for section in manifest["sections"] if section["kind"] == "AgentWorkflow")
    assert workflow_section["source_name"] == "daily-standup"
    assert workflow_section["candidate_name"] == "daily-standup-opt-compare"
    assert "Read git and Jira context" in workflow_section["source_yaml"]
    assert "[ROI Candidate Guidance]" not in workflow_section["source_yaml"]
    assert "Read git and Jira context" in workflow_section["candidate_yaml"]
    assert "[ROI Candidate Guidance]" not in workflow_section["candidate_yaml"]
    assert "spec.steps[0].agentRef" in workflow_section["changed_paths"]
    assert any(row["type"] in {"replace", "insert"} for row in workflow_section["diff_rows"])
    assert not any("[ROI Candidate Guidance]" in str(row["candidate"]) for row in workflow_section["diff_rows"])


def test_run_candidate_applies_copy_triggers_workflow_and_records_trial(client, auth_headers) -> None:
    baseline_id = _seed_execution(
        execution_id="exec-opt-run-base", duration_ms=100_000, tokens=2_000, cost_usd=0.08, tool_calls=8
    )

    with _optimization_api_context(manifests=True):
        study = client.post(
            "/api/v1/optimizations/studies",
            headers=auth_headers,
            json={"namespace": "default", "workflow_name": "daily-standup", "baseline_execution_ids": [baseline_id]},
        ).json()

    with (
        _optimization_api_context(),
        patch(
            "routers.optimizations._apply_manifest_bundle",
            return_value=[{"kind": "AIAgent", "name": "daily-standup-opt-run", "status": "created"}],
        ) as apply_bundle,
        patch(
            "routers.optimizations._wait_for_candidate_agents_ready",
            return_value=[
                {"name": "standup-git-opt-run", "status": "ready"},
                {"name": "standup-jira-opt-run", "status": "ready"},
                {"name": "standup-scribe-opt-run", "status": "ready"},
            ],
        ) as wait_ready,
        patch(
            "routers.optimizations._trigger_candidate_workflow",
            return_value={
                "workflow_name": "daily-standup-opt-run",
                "namespace": "default",
                "run_id": "wf-run-default-daily-standup-opt-run-1-abc123",
                "phase": "pending",
                "generation": 2,
            },
        ) as trigger_workflow,
    ):
        candidate = client.post(
            f"/api/v1/optimizations/studies/{study['id']}/candidates/generate",
            headers=auth_headers,
            json={"optimizer_output": "trim repeated context", "suffix": "opt-run"},
        ).json()

        blocked = client.post(
            f"/api/v1/optimizations/candidates/{candidate['id']}/run",
            headers=auth_headers,
            json={"baseline_execution_id": baseline_id},
        )
        assert blocked.status_code == 409

        client.post(
            f"/api/v1/optimizations/candidates/{candidate['id']}/approval",
            headers=auth_headers,
            json={"decision": "approved", "reason": "Run isolated copy."},
        )

        launched = client.post(
            f"/api/v1/optimizations/candidates/{candidate['id']}/run",
            headers=auth_headers,
            json={"baseline_execution_id": baseline_id, "input": "Generate a daily standup candidate trial."},
        )

    assert launched.status_code == 201
    payload = launched.json()
    assert payload["candidate"]["status"] == "applied"
    assert payload["candidate_run"]["workflow_name"] == "daily-standup-opt-run"
    assert payload["trial"]["status"] == "pending"
    assert (
        payload["trial"]["metrics_delta"]["candidate_run"]["run_id"] == "wf-run-default-daily-standup-opt-run-1-abc123"
    )
    assert payload["trial"]["metrics_delta"]["apply_results"][0]["status"] == "created"
    assert payload["trial"]["metrics_delta"]["agent_readiness"][0]["status"] == "ready"
    apply_bundle.assert_called_once()
    assert apply_bundle.call_args.kwargs["include_workflows"] is False
    wait_ready.assert_called_once()
    trigger_workflow.assert_called_once()
    assert trigger_workflow.call_args.args[1] == "daily-standup-opt-run"


def test_apply_candidate_stages_agents_and_defers_workflow_until_trial(client, auth_headers) -> None:
    baseline_id = _seed_execution(execution_id="exec-opt-stage-base")

    with _optimization_api_context(manifests=True):
        study = client.post(
            "/api/v1/optimizations/studies",
            headers=auth_headers,
            json={"namespace": "default", "workflow_name": "daily-standup", "baseline_execution_ids": [baseline_id]},
        ).json()

    with (
        _optimization_api_context(),
        patch(
            "routers.optimizations._apply_manifest_bundle",
            return_value=[
                {"kind": "AIAgent", "name": "daily-standup-opt-stage", "status": "created"},
                {"kind": "AgentWorkflow", "name": "daily-standup-opt-stage", "status": "deferred_until_trial"},
            ],
        ) as apply_bundle,
    ):
        candidate = client.post(
            f"/api/v1/optimizations/studies/{study['id']}/candidates/generate",
            headers=auth_headers,
            json={"optimizer_output": "trim repeated context", "suffix": "opt-stage"},
        ).json()
        client.post(
            f"/api/v1/optimizations/candidates/{candidate['id']}/approval",
            headers=auth_headers,
            json={"decision": "approved", "reason": "Stage isolated candidate agents."},
        )
        staged = client.post(
            f"/api/v1/optimizations/candidates/{candidate['id']}/apply",
            headers=auth_headers,
            json={"dry_run": False},
        )

    assert staged.status_code == 200
    assert staged.json()["results"][-1]["status"] == "deferred_until_trial"
    assert apply_bundle.call_args.kwargs["include_workflows"] is False


def test_roi_syncs_completed_candidate_run_into_pending_trial(client, auth_headers) -> None:
    baseline_id = _seed_execution(
        execution_id="exec-opt-sync-base", duration_ms=100_000, tokens=2_000, cost_usd=0.08, tool_calls=8
    )
    candidate_id = _seed_execution(
        execution_id="exec-opt-sync-candidate",
        workflow_name="daily-standup-opt-sync",
        run_id="wf-run-default-daily-standup-opt-sync-1-abc123",
        duration_ms=55_000,
        tokens=1_000,
        cost_usd=0.04,
        tool_calls=4,
    )

    with _optimization_api_context(manifests=True):
        study = client.post(
            "/api/v1/optimizations/studies",
            headers=auth_headers,
            json={"namespace": "default", "workflow_name": "daily-standup", "baseline_execution_ids": [baseline_id]},
        ).json()

    with (
        _optimization_api_context(),
        patch(
            "routers.optimizations._apply_manifest_bundle",
            return_value=[{"kind": "AgentWorkflow", "name": "daily-standup-opt-sync", "status": "created"}],
        ),
        patch(
            "routers.optimizations._wait_for_candidate_agents_ready",
            return_value=[{"name": "standup-git-opt-sync", "status": "ready"}],
        ),
        patch(
            "routers.optimizations._trigger_candidate_workflow",
            return_value={
                "workflow_name": "daily-standup-opt-sync",
                "namespace": "default",
                "run_id": "wf-run-default-daily-standup-opt-sync-1-abc123",
                "phase": "pending",
            },
        ),
        patch(
            "routers.optimizations.trace_store.list_executions",
            return_value=[_TRACE_FIXTURES[candidate_id]],
        ),
    ):
        candidate = client.post(
            f"/api/v1/optimizations/studies/{study['id']}/candidates/generate",
            headers=auth_headers,
            json={"optimizer_output": "trim repeated context", "suffix": "opt-sync"},
        ).json()
        client.post(
            f"/api/v1/optimizations/candidates/{candidate['id']}/approval",
            headers=auth_headers,
            json={"decision": "approved", "reason": "Run isolated copy."},
        )
        client.post(
            f"/api/v1/optimizations/candidates/{candidate['id']}/run",
            headers=auth_headers,
            json={"baseline_execution_id": baseline_id},
        )
        roi = client.get(
            f"/api/v1/optimizations/studies/{study['id']}/roi?candidate_id={candidate['id']}",
            headers=auth_headers,
        )
        refreshed = client.get(f"/api/v1/optimizations/studies/{study['id']}", headers=auth_headers).json()

    assert roi.status_code == 200
    roi_payload = roi.json()
    assert roi_payload["candidate_metrics"]["sample_count"] == 1
    assert roi_payload["deltas"]["tokens_saved_percent"] == 50.0
    synced_trial = refreshed["trials"][0]
    assert synced_trial["result_execution_id"] == candidate_id
    assert synced_trial["quality_status"] == "machine_passed"


def test_promote_candidate_requires_verified_safe_trials(client, auth_headers) -> None:
    baseline_id = _seed_execution(
        execution_id="exec-opt-promote-base", duration_ms=100_000, tokens=2_000, cost_usd=0.08, tool_calls=8
    )
    candidate_execution_ids = [
        _seed_execution(
            execution_id=f"exec-opt-promote-candidate-{index}",
            workflow_name="daily-standup-opt-promote",
            duration_ms=50_000,
            tokens=1_000,
            cost_usd=0.04,
            tool_calls=3,
        )
        for index in range(5)
    ]

    with _optimization_api_context(manifests=True):
        study = client.post(
            "/api/v1/optimizations/studies",
            headers=auth_headers,
            json={"namespace": "default", "workflow_name": "daily-standup", "baseline_execution_ids": [baseline_id]},
        ).json()

    with _optimization_api_context():
        candidate = client.post(
            f"/api/v1/optimizations/studies/{study['id']}/candidates/generate",
            headers=auth_headers,
            json={"optimizer_output": "use cheaper model route", "suffix": "opt-promote"},
        ).json()
        approval = client.post(
            f"/api/v1/optimizations/candidates/{candidate['id']}/approval",
            headers=auth_headers,
            json={"decision": "approved", "reason": "Safe isolated copy."},
        )
        assert approval.status_code == 200

        early_promote = client.post(
            f"/api/v1/optimizations/candidates/{candidate['id']}/promotion",
            headers=auth_headers,
            json={"reason": "Try to promote early."},
        )
        assert early_promote.status_code == 409

        for candidate_execution_id in candidate_execution_ids:
            trial = client.post(
                f"/api/v1/optimizations/candidates/{candidate['id']}/trials",
                headers=auth_headers,
                json={
                    "baseline_execution_id": baseline_id,
                    "result_execution_id": candidate_execution_id,
                    "quality_status": "passed",
                },
            )
            assert trial.status_code == 201

        promoted = client.post(
            f"/api/v1/optimizations/candidates/{candidate['id']}/promotion",
            headers=auth_headers,
            json={"reason": "5 safe trials beat baseline."},
        )

    assert promoted.status_code == 200
    payload = promoted.json()
    assert payload["candidate"]["status"] == "promoted"
    assert payload["study"]["status"] == "promoted"
    assert payload["roi"]["verified"] is True
    assert payload["promotion"]["promoted_by"] == "shared-token-user"


def test_optimization_schema_adds_trace_and_proof_gate_to_existing_tables(monkeypatch) -> None:
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE optimization_studies (
                    id VARCHAR(64) PRIMARY KEY,
                    namespace VARCHAR(128) NOT NULL,
                    workflow_name VARCHAR(256) NOT NULL
                )
                """
            )
        )
        connection.execute(
            text(
                "INSERT INTO optimization_studies (id, namespace, workflow_name) "
                "VALUES ('opt-existing', 'default', 'daily-standup')"
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE optimization_candidates (
                    id VARCHAR(64) PRIMARY KEY,
                    study_id VARCHAR(64) NOT NULL,
                    namespace VARCHAR(128) NOT NULL,
                    name VARCHAR(256) NOT NULL,
                    candidate_workflow_name VARCHAR(256) NOT NULL
                )
                """
            )
        )
        connection.execute(
            text(
                "INSERT INTO optimization_candidates "
                "(id, study_id, namespace, name, candidate_workflow_name) "
                "VALUES ('cand-existing', 'opt-existing', 'default', 'candidate', 'daily-standup-opt')"
            )
        )

    monkeypatch.setattr(optimization_store, "_AUTH_ENGINE", engine)

    optimization_store._ensure_optimization_schema()

    with engine.connect() as connection:
        columns = {str(column["name"]) for column in inspect(connection).get_columns("optimization_studies")}
        assert "proof_gate" in columns
        stored = connection.execute(
            text("SELECT proof_gate FROM optimization_studies WHERE id = 'opt-existing'")
        ).scalar_one()
        assert "requires_approval" in stored
        candidate_columns = {
            str(column["name"]) for column in inspect(connection).get_columns("optimization_candidates")
        }
        assert "optimizer_trace" in candidate_columns
        assert {"tags", "lifecycle_state", "archived_by", "archived_at"} <= candidate_columns
        trace = connection.execute(
            text("SELECT optimizer_trace FROM optimization_candidates WHERE id = 'cand-existing'")
        ).scalar_one()
        assert trace == "{}"
        tags, lifecycle_state = connection.execute(
            text("SELECT tags, lifecycle_state FROM optimization_candidates WHERE id = 'cand-existing'")
        ).one()
        assert tags == "[]"
        assert lifecycle_state == "active"


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
        response = client.get(
            f"/api/v1/optimizations/studies/{study['id']}/dataset?redacted=true", headers=auth_headers
        )

    assert response.status_code == 200
    dataset = response.json()
    serialized = str(dataset)
    assert "sk-test-secret" not in serialized
    assert "abc123" not in serialized
    assert "[REDACTED]" in serialized
    assert dataset["labels"]["workflow_name"] == "daily-standup"
    assert dataset["baseline_traces"][0]["id"] == baseline_id
    assert dataset["dataset_plan"]["strategy"] == "dataset_first"
    assert dataset["dataset_plan"]["splits"]["replay_cases"] == 1
    assert dataset["dataset_plan"]["local_model_path"]["suitability"] in {
        "needs_more_review",
        "needs_more_examples",
        "candidate",
    }
    assert dataset["redaction_report"]["state"] == "redacted"
    assert any(record["record_type"] == "llm_call" for record in dataset["training_records"])
    assert dataset["evaluation_records"][0]["quality_label"] == "baseline_success"


def test_optimizer_agent_manifest_declares_roi_optimization_skills() -> None:
    path = Path(__file__).resolve().parents[2] / "examples" / "daily-standup-bot" / "optimizer-agent.yaml"
    manifest = yaml.safe_load(path.read_text(encoding="utf-8"))
    skills = ((manifest.get("spec") or {}).get("skills") or {}).get("files") or {}

    assert manifest["metadata"]["name"] == "workflow-optimizer"
    assert len(skills) >= 5
    skill_text = "\n".join(str(value) for value in skills.values())
    assert "critical-path-roi" in skill_text
    assert "context-compression" in skill_text
    assert "tool-economy" in skill_text
    assert "topology-rewrite" in skill_text
    assert "regression-proof-gate" in skill_text


def test_generate_candidate_patches_a2a_allowed_callers_with_candidate_workflow_name(client, auth_headers) -> None:
    """Candidate agents must allow the candidate workflow name as an A2A caller.

    Without this, the workflow worker gets HTTP 403 forbidden when invoking
    candidate agents because the source agent's allowedCallers lists the
    source workflow name, not the suffixed candidate workflow name.
    """
    baseline_id = _seed_execution(execution_id="exec-a2a-callers")

    with _optimization_api_context(manifests=True):
        study = client.post(
            "/api/v1/optimizations/studies",
            headers=auth_headers,
            json={"namespace": "default", "workflow_name": "daily-standup", "baseline_execution_ids": [baseline_id]},
        ).json()

    with _optimization_api_context():
        response = client.post(
            f"/api/v1/optimizations/studies/{study['id']}/candidates/generate",
            headers=auth_headers,
            json={
                "optimizer_output": "Minor prompt refinement for clarity.",
                "suffix": "opt-a2a-fix",
            },
        )

    assert response.status_code == 201, response.json()
    candidate = response.json()
    bundle = candidate["manifest_bundle"]
    workflow = next(m for m in bundle if m["kind"] == "AgentWorkflow")
    candidate_wf_name = workflow["metadata"]["name"]

    for manifest in bundle:
        if manifest["kind"] != "AIAgent":
            continue
        a2a = (manifest.get("spec") or {}).get("a2a") or {}
        callers = a2a.get("allowedCallers") or []
        caller_names = [c.get("name") for c in callers if isinstance(c, dict)]
        assert candidate_wf_name in caller_names, (
            f"Candidate agent '{manifest['metadata']['name']}' does not list "
            f"candidate workflow '{candidate_wf_name}' in a2a.allowedCallers. "
            f"Found: {caller_names}"
        )
