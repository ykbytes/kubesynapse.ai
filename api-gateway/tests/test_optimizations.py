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
        execution_id: _TRACE_FIXTURES[execution_id]
        for execution_id in execution_ids
        if execution_id in _TRACE_FIXTURES
    }


@contextmanager
def _optimization_api_context(*, manifests: bool = False):
    with patch("routers.optimizations.ensure_namespace_access", side_effect=_allow_namespace_access), patch(
        "routers.optimizations.trace_store.get_execution", side_effect=_fake_get_execution
    ), patch(
        "routers.optimizations.trace_store.get_executions_by_ids", side_effect=_fake_get_executions_by_ids
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

    with patch("routers.optimizations.ensure_namespace_access", side_effect=_allow_namespace_access), patch(
        "routers.optimizations.trace_store.get_execution", side_effect=_fake_get_execution
    ), patch(
        "routers.optimizations.trace_store.get_executions_by_ids", side_effect=_fake_get_executions_by_ids
    ), patch("routers.optimizations.read_custom_resource", side_effect=fake_read_missing_git):
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
    assert "Summarize git commits" in reconstructed["spec"]["systemPrompt"]
    assert any("standup-git" in warning for warning in source["warnings"])


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

    with patch("routers.optimizations.ensure_namespace_access", side_effect=_allow_namespace_access), patch(
        "routers.optimizations.trace_store.get_execution",
        side_effect=AssertionError("create_study must not load baseline traces one connection at a time"),
    ), patch("routers.optimizations.trace_store.get_executions_by_ids", side_effect=fake_get_executions, create=True), patch(
        "routers.optimizations.read_custom_resource", side_effect=_fake_read_custom_resource
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
    rewritten_agent["spec"]["systemPrompt"] = "You consolidate git, Jira, and final standup writing without losing required output behavior."

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
            json={"optimizer_output": "Trim repeated reads and batch tool updates, but preserve all outputs.", "suffix": "opt-guided"},
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
    assert refreshed["source_manifests"]["workflow"]["spec"]["steps"][0]["prompt"] == "Read git and Jira context, then write standup.md."
    assert refreshed["source_manifests"]["agents"]["daily-standup"]["spec"]["systemPrompt"] == "You write daily standup reports."


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


def test_generate_candidate_uses_optimizer_manifest_copy_without_mutating_source(client, auth_headers) -> None:
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
        manifest for manifest in candidate["manifest_bundle"]
        if manifest["kind"] == "AIAgent" and manifest["metadata"]["name"] == "standup-single-pass-opt-single"
    )
    assert extra_agent["metadata"]["labels"]["kubesynapse.ai/topology-rewrite"] == "allowed"
    assert candidate["validation_results"]["topology_rewrite_allowed"] is True


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
    baseline_id = _seed_execution(execution_id="exec-opt-roi-base", duration_ms=100_000, tokens=2_000, cost_usd=0.08, tool_calls=8)
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
    baseline_id = _seed_execution(execution_id="exec-opt-run-base", duration_ms=100_000, tokens=2_000, cost_usd=0.08, tool_calls=8)

    with _optimization_api_context(manifests=True):
        study = client.post(
            "/api/v1/optimizations/studies",
            headers=auth_headers,
            json={"namespace": "default", "workflow_name": "daily-standup", "baseline_execution_ids": [baseline_id]},
        ).json()

    with _optimization_api_context(), patch(
        "routers.optimizations._apply_manifest_bundle",
        return_value=[{"kind": "AIAgent", "name": "daily-standup-opt-run", "status": "created"}],
    ) as apply_bundle, patch(
        "routers.optimizations._wait_for_candidate_agents_ready",
        return_value=[
            {"name": "standup-git-opt-run", "status": "ready"},
            {"name": "standup-jira-opt-run", "status": "ready"},
            {"name": "standup-scribe-opt-run", "status": "ready"},
        ],
    ) as wait_ready, patch(
        "routers.optimizations._trigger_candidate_workflow",
        return_value={
            "workflow_name": "daily-standup-opt-run",
            "namespace": "default",
            "run_id": "wf-run-default-daily-standup-opt-run-1-abc123",
            "phase": "pending",
            "generation": 2,
        },
    ) as trigger_workflow:
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
    assert payload["trial"]["metrics_delta"]["candidate_run"]["run_id"] == "wf-run-default-daily-standup-opt-run-1-abc123"
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

    with _optimization_api_context(), patch(
        "routers.optimizations._apply_manifest_bundle",
        return_value=[
            {"kind": "AIAgent", "name": "daily-standup-opt-stage", "status": "created"},
            {"kind": "AgentWorkflow", "name": "daily-standup-opt-stage", "status": "deferred_until_trial"},
        ],
    ) as apply_bundle:
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
    baseline_id = _seed_execution(execution_id="exec-opt-sync-base", duration_ms=100_000, tokens=2_000, cost_usd=0.08, tool_calls=8)
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

    with _optimization_api_context(), patch(
        "routers.optimizations._apply_manifest_bundle",
        return_value=[{"kind": "AgentWorkflow", "name": "daily-standup-opt-sync", "status": "created"}],
    ), patch(
        "routers.optimizations._wait_for_candidate_agents_ready",
        return_value=[{"name": "standup-git-opt-sync", "status": "ready"}],
    ), patch(
        "routers.optimizations._trigger_candidate_workflow",
        return_value={
            "workflow_name": "daily-standup-opt-sync",
            "namespace": "default",
            "run_id": "wf-run-default-daily-standup-opt-sync-1-abc123",
            "phase": "pending",
        },
    ), patch(
        "routers.optimizations.trace_store.list_executions",
        return_value=[_TRACE_FIXTURES[candidate_id]],
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
    baseline_id = _seed_execution(execution_id="exec-opt-promote-base", duration_ms=100_000, tokens=2_000, cost_usd=0.08, tool_calls=8)
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


def test_optimization_schema_adds_proof_gate_to_existing_tables(monkeypatch) -> None:
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

    monkeypatch.setattr(optimization_store, "_AUTH_ENGINE", engine)

    optimization_store._ensure_optimization_schema()

    with engine.connect() as connection:
        columns = {str(column["name"]) for column in inspect(connection).get_columns("optimization_studies")}
        assert "proof_gate" in columns
        stored = connection.execute(text("SELECT proof_gate FROM optimization_studies WHERE id = 'opt-existing'")).scalar_one()
        assert "requires_approval" in stored


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
    assert dataset["dataset_plan"]["strategy"] == "dataset_first"
    assert dataset["dataset_plan"]["splits"]["replay_cases"] == 1
    assert dataset["dataset_plan"]["local_model_path"]["suitability"] in {"needs_more_review", "needs_more_examples", "candidate"}
    assert dataset["redaction_report"]["state"] == "redacted"
    assert any(record["record_type"] == "llm_call" for record in dataset["training_records"])
    assert dataset["evaluation_records"][0]["quality_label"] == "baseline_success"


def test_optimizer_agent_manifest_declares_roi_optimization_skills() -> None:
    path = Path(__file__).resolve().parents[2] / "examples" / "daily-standup-bot" / "optimizer-agent.yaml"
    manifest = yaml.safe_load(path.read_text(encoding="utf-8"))
    skills = (((manifest.get("spec") or {}).get("skills") or {}).get("files") or {})

    assert manifest["metadata"]["name"] == "workflow-optimizer"
    assert len(skills) >= 5
    skill_text = "\n".join(str(value) for value in skills.values())
    assert "critical-path-roi" in skill_text
    assert "context-compression" in skill_text
    assert "tool-economy" in skill_text
    assert "topology-rewrite" in skill_text
    assert "regression-proof-gate" in skill_text
