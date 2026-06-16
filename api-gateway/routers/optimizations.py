"""Workflow optimization ROI lab API."""

from __future__ import annotations

import copy
import json
import re
from typing import Any

import optimization_store
import trace_store
from _core import RESOURCE_GROUP, RESOURCE_KIND_BY_PLURAL, RESOURCE_VERSION, read_custom_resource
from auth_middleware import ensure_namespace_access, verify_token
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, model_validator

router = APIRouter(prefix="/optimizations", tags=["optimizations"])

_ALLOWED_CANDIDATE_KINDS = {"AIAgent", "AgentWorkflow"}
_PASSING_QUALITY_STATES = {"passed", "machine_passed", "human_passed", "approved"}
_SENSITIVE_KEY_RE = re.compile(r"(api[_-]?key|token|secret|password|credential|authorization)", re.IGNORECASE)
_SECRET_VALUE_RE = re.compile(r"\b(sk-[A-Za-z0-9_\-]{8,}|Bearer\s+[A-Za-z0-9._\-]{12,})\b")


class CreateStudyRequest(BaseModel):
    namespace: str = Field(default="default", min_length=1, max_length=128)
    workflow_name: str = Field(min_length=1, max_length=256)
    optimizer_agent_name: str | None = Field(default=None, max_length=256)
    baseline_execution_ids: list[str] = Field(default_factory=list, min_length=1, max_length=50)
    objective: str | None = Field(default=None, max_length=2048)
    source_manifests: dict[str, Any] | None = None

    @model_validator(mode="after")
    def normalize(self) -> "CreateStudyRequest":
        self.namespace = self.namespace.strip() or "default"
        self.workflow_name = self.workflow_name.strip()
        if self.optimizer_agent_name is not None:
            self.optimizer_agent_name = self.optimizer_agent_name.strip() or None
        self.baseline_execution_ids = [item.strip() for item in self.baseline_execution_ids if item.strip()]
        if not self.baseline_execution_ids:
            raise ValueError("baseline_execution_ids must contain at least one execution id")
        return self


class CreateCandidateRequest(BaseModel):
    name: str | None = Field(default=None, max_length=256)
    optimizer_output: str | None = None
    manifest_bundle: list[dict[str, Any]] = Field(default_factory=list, min_length=1, max_length=20)
    expected_savings: dict[str, Any] = Field(default_factory=dict)


class GenerateCandidateRequest(BaseModel):
    optimizer_output: str | None = None
    suffix: str | None = Field(default=None, max_length=32)
    expected_savings: dict[str, Any] = Field(default_factory=dict)


class ApprovalRequest(BaseModel):
    decision: str = Field(pattern="^(approved|denied)$")
    reason: str | None = Field(default=None, max_length=1024)


class ApplyCandidateRequest(BaseModel):
    dry_run: bool = True


class CreateTrialRequest(BaseModel):
    baseline_execution_id: str = Field(min_length=1, max_length=128)
    result_execution_id: str | None = Field(default=None, max_length=128)
    quality_status: str = Field(default="needs_review", max_length=64)
    notes: str | None = Field(default=None, max_length=2048)

    @model_validator(mode="after")
    def normalize(self) -> "CreateTrialRequest":
        self.quality_status = self.quality_status.strip().lower() or "needs_review"
        if self.result_execution_id is not None:
            self.result_execution_id = self.result_execution_id.strip() or None
        return self


def _principal(user: dict[str, Any]) -> str:
    return str(user.get("sub") or user.get("username") or user.get("id") or "unknown")


def _clone(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))


def _round(value: float | int | None, digits: int = 3) -> float:
    if value is None:
        return 0.0
    return round(float(value), digits)


def _get_trace(execution_id: str) -> dict[str, Any]:
    trace = trace_store.get_execution(execution_id)
    if trace is None:
        raise HTTPException(status_code=404, detail=f"Execution '{execution_id}' not found")
    return trace


def _aggregate_metrics(traces: list[dict[str, Any]]) -> dict[str, Any]:
    count = len(traces)
    if count == 0:
        return {
            "sample_count": 0,
            "successful_count": 0,
            "success_rate": 0.0,
            "avg_duration_ms": 0.0,
            "avg_tokens": 0.0,
            "avg_cost_usd": 0.0,
            "avg_llm_calls": 0.0,
            "avg_tool_calls": 0.0,
            "avg_cache_read_tokens": 0.0,
            "avg_cache_write_tokens": 0.0,
            "cost_per_successful_run": 0.0,
            "tokens_per_successful_run": 0.0,
            "duration_per_successful_run_ms": 0.0,
        }

    successful = [trace for trace in traces if str(trace.get("status") or "").lower() == "completed"]
    success_count = len(successful)
    cost_values = [float(trace.get("estimated_cost_usd") or trace.get("total_cost_usd") or 0) for trace in traces]
    token_values = [float(trace.get("total_tokens") or 0) for trace in traces]
    duration_values = [float(trace.get("duration_ms") or 0) for trace in traces]

    def avg(values: list[float]) -> float:
        return sum(values) / len(values) if values else 0.0

    return {
        "sample_count": count,
        "successful_count": success_count,
        "success_rate": _round(success_count / count if count else 0.0, 4),
        "avg_duration_ms": _round(avg(duration_values), 3),
        "avg_tokens": _round(avg(token_values), 3),
        "avg_cost_usd": _round(avg(cost_values), 6),
        "avg_llm_calls": _round(avg([float(trace.get("total_llm_calls") or 0) for trace in traces]), 3),
        "avg_tool_calls": _round(avg([float(trace.get("total_tool_calls") or 0) for trace in traces]), 3),
        "avg_cache_read_tokens": _round(avg([float(trace.get("cache_read_tokens") or 0) for trace in traces]), 3),
        "avg_cache_write_tokens": _round(avg([float(trace.get("cache_write_tokens") or 0) for trace in traces]), 3),
        "cost_per_successful_run": _round(sum(cost_values) / success_count if success_count else 0.0, 6),
        "tokens_per_successful_run": _round(sum(token_values) / success_count if success_count else 0.0, 3),
        "duration_per_successful_run_ms": _round(sum(duration_values) / success_count if success_count else 0.0, 3),
    }


def _opportunities_for_traces(traces: list[dict[str, Any]]) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = []
    tools: dict[str, int] = {}
    models: dict[str, int] = {}
    for trace in traces:
        steps.extend([step for step in trace.get("steps", []) if isinstance(step, dict)])
        for call in trace.get("tool_calls", []):
            if isinstance(call, dict):
                name = str(call.get("tool_name") or "unknown")
                tools[name] = tools.get(name, 0) + 1
        for call in trace.get("llm_calls", []):
            if isinstance(call, dict):
                model = str(call.get("model") or "unknown")
                models[model] = models.get(model, 0) + 1

    slowest = max(steps, key=lambda item: float(item.get("duration_ms") or 0), default={})
    heaviest = max(steps, key=lambda item: float(item.get("tokens_used") or 0), default={})
    top_tool = max(tools.items(), key=lambda item: item[1], default=("unknown", 0))
    top_model = max(models.items(), key=lambda item: item[1], default=("unknown", 0))
    metrics = _aggregate_metrics(traces)
    return [
        {
            "kind": "latency",
            "severity": "high" if float(slowest.get("duration_ms") or 0) > 60_000 else "medium",
            "title": "Slowest step",
            "evidence": {
                "step": slowest.get("step_name") or slowest.get("name"),
                "duration_ms": slowest.get("duration_ms"),
                "avg_duration_ms": metrics["avg_duration_ms"],
            },
            "recommendation": "Trim context, batch deterministic tool reads, and route this step to the cheapest model that preserves quality.",
        },
        {
            "kind": "tokens",
            "severity": "high" if metrics["avg_tokens"] > 4_000 else "medium",
            "title": "Token pressure",
            "evidence": {
                "step": heaviest.get("step_name") or heaviest.get("name"),
                "tokens": heaviest.get("tokens_used"),
                "avg_tokens": metrics["avg_tokens"],
                "top_model": top_model[0],
            },
            "recommendation": "Convert repeated context into step-specific instructions and reusable artifacts before the next LLM call.",
        },
        {
            "kind": "tool_churn",
            "severity": "high" if top_tool[1] > 4 else "medium",
            "title": "Tool churn",
            "evidence": {"tool": top_tool[0], "count": top_tool[1], "avg_tool_calls": metrics["avg_tool_calls"]},
            "recommendation": "Batch related reads/writes and ask the agent to plan tool use before calling tools.",
        },
        {
            "kind": "reliability",
            "severity": "high" if metrics["success_rate"] < 1 else "low",
            "title": "Hybrid proof gate",
            "evidence": {"success_rate": metrics["success_rate"], "sample_count": metrics["sample_count"]},
            "recommendation": "Require machine checks plus human review before promoting any cheaper candidate.",
        },
    ]


def _extract_agent_refs(workflow_manifest: dict[str, Any]) -> list[str]:
    spec = workflow_manifest.get("spec") if isinstance(workflow_manifest.get("spec"), dict) else {}
    refs: list[str] = []
    for step in spec.get("steps") or []:
        if not isinstance(step, dict):
            continue
        ref = str(step.get("agentRef") or "").strip()
        if ref and ref not in refs:
            refs.append(ref)
    return refs


def _load_source_manifests(namespace: str, workflow_name: str, provided: dict[str, Any] | None = None) -> dict[str, Any]:
    if provided:
        return _clone(provided)

    workflow = read_custom_resource("agentworkflows", workflow_name, namespace, "Workflow")
    agent_refs = _extract_agent_refs(workflow)
    agents: dict[str, Any] = {}
    for agent_ref in agent_refs:
        agents[agent_ref] = read_custom_resource("aiagents", agent_ref, namespace, "Agent")
    return {"workflow": workflow, "agent_refs": agent_refs, "agents": agents}


def _workflow_from_bundle(bundle: list[dict[str, Any]]) -> dict[str, Any] | None:
    for manifest in bundle:
        if str(manifest.get("kind") or "") == "AgentWorkflow":
            return manifest
    return None


def _manifest_namespace(manifest: dict[str, Any]) -> str:
    metadata = manifest.get("metadata") if isinstance(manifest.get("metadata"), dict) else {}
    return str(metadata.get("namespace") or "default")


def _manifest_name(manifest: dict[str, Any]) -> str:
    metadata = manifest.get("metadata") if isinstance(manifest.get("metadata"), dict) else {}
    return str(metadata.get("name") or "")


def _step_signature(workflow: dict[str, Any] | None) -> list[tuple[str, str]]:
    if workflow is None:
        return []
    spec = workflow.get("spec") if isinstance(workflow.get("spec"), dict) else {}
    result: list[tuple[str, str]] = []
    for step in spec.get("steps") or []:
        if not isinstance(step, dict):
            continue
        result.append((str(step.get("name") or ""), str(step.get("type") or step.get("stepType") or "agent")))
    return result


def _collect_sensitive_markers(value: Any, *, path: str = "") -> set[str]:
    markers: set[str] = set()
    if isinstance(value, dict):
        for key, nested in value.items():
            key_text = str(key)
            normalized_path = f"{path}.{key_text}" if path else key_text
            if key_text in {"env", "envFrom", "valueFrom", "secretKeyRef", "secretRef"} or _SENSITIVE_KEY_RE.search(key_text):
                markers.add(normalized_path)
            markers.update(_collect_sensitive_markers(nested, path=normalized_path))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            markers.update(_collect_sensitive_markers(item, path=f"{path}[]"))
    elif isinstance(value, str) and _SECRET_VALUE_RE.search(value):
        markers.add(f"{path}=secret-value")
    return markers


def _source_bundle_from_study(study: dict[str, Any]) -> list[dict[str, Any]]:
    source = study.get("source_manifests") if isinstance(study.get("source_manifests"), dict) else {}
    bundle = []
    if isinstance(source.get("workflow"), dict):
        bundle.append(source["workflow"])
    agents = source.get("agents")
    if isinstance(agents, dict):
        bundle.extend([agent for agent in agents.values() if isinstance(agent, dict)])
    return bundle


def _validate_candidate_bundle(study: dict[str, Any], bundle: list[dict[str, Any]]) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    namespace = str(study.get("namespace") or "default")
    source = study.get("source_manifests") if isinstance(study.get("source_manifests"), dict) else {}
    source_workflow = source.get("workflow") if isinstance(source.get("workflow"), dict) else None
    candidate_workflow = _workflow_from_bundle(bundle)

    if candidate_workflow is None:
        errors.append("candidate bundle must include an AgentWorkflow manifest")

    for manifest in bundle:
        kind = str(manifest.get("kind") or "")
        if kind not in _ALLOWED_CANDIDATE_KINDS:
            errors.append(f"kind {kind or '<missing>'} is not allowed in optimization candidates")
        if _manifest_namespace(manifest) != namespace:
            errors.append("candidate manifests must stay in the study namespace")

    if source_workflow and candidate_workflow and _step_signature(source_workflow) != _step_signature(candidate_workflow):
        errors.append("workflow topology must preserve step names/order and step types")

    source_names = {_manifest_name(manifest) for manifest in _source_bundle_from_study(study)}
    candidate_names = {_manifest_name(manifest) for manifest in bundle}
    if source_names & candidate_names:
        errors.append("candidate resources must be copied resources with new names, not source resources")

    source_sensitive = set()
    for manifest in _source_bundle_from_study(study):
        source_sensitive.update(_collect_sensitive_markers(manifest))
    candidate_sensitive = set()
    for manifest in bundle:
        candidate_sensitive.update(_collect_sensitive_markers(manifest))
    if candidate_sensitive - source_sensitive:
        errors.append("secret/env expansion is not allowed in v1 candidates")

    return {
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "scope": "prompt_model_tool_v1",
        "topology_preserved": not any("workflow topology" in error for error in errors),
        "hybrid_gate": "candidate requires approval, safe trials, and contract-preserving outputs before promotion",
    }


def _manifest_diff(study: dict[str, Any], bundle: list[dict[str, Any]]) -> dict[str, Any]:
    source = study.get("source_manifests") if isinstance(study.get("source_manifests"), dict) else {}
    source_workflow = source.get("workflow") if isinstance(source.get("workflow"), dict) else {}
    candidate_workflow = _workflow_from_bundle(bundle) or {}
    return {
        "workflow": {"from": _manifest_name(source_workflow), "to": _manifest_name(candidate_workflow)},
        "resource_count": {"from": len(_source_bundle_from_study(study)), "to": len(bundle)},
        "topology": {
            "from": _step_signature(source_workflow),
            "to": _step_signature(candidate_workflow),
            "preserved": _step_signature(source_workflow) == _step_signature(candidate_workflow),
        },
        "change_scope": ["prompt", "model", "tool-use", "context", "timeout"],
    }


def _copy_metadata(manifest: dict[str, Any], name: str, namespace: str, study: dict[str, Any]) -> dict[str, Any]:
    metadata = _clone(manifest.get("metadata") if isinstance(manifest.get("metadata"), dict) else {})
    metadata["name"] = name
    metadata["namespace"] = namespace
    metadata.pop("uid", None)
    metadata.pop("resourceVersion", None)
    metadata.pop("generation", None)
    labels = metadata.get("labels") if isinstance(metadata.get("labels"), dict) else {}
    labels.update(
        {
            "kubesynapse.ai/optimization-study": str(study["id"]),
            "kubesynapse.ai/source-workflow": str(study["workflow_name"]),
            "kubesynapse.ai/candidate": "true",
        }
    )
    metadata["labels"] = labels
    annotations = metadata.get("annotations") if isinstance(metadata.get("annotations"), dict) else {}
    annotations["kubesynapse.ai/optimization-mode"] = "roi-lab-v1"
    metadata["annotations"] = annotations
    return metadata


def _candidate_bundle_from_source(study: dict[str, Any], suffix: str, optimizer_output: str | None) -> list[dict[str, Any]]:
    namespace = str(study.get("namespace") or "default")
    source = study.get("source_manifests") if isinstance(study.get("source_manifests"), dict) else {}
    source_workflow = source.get("workflow") if isinstance(source.get("workflow"), dict) else None
    if source_workflow is None:
        raise HTTPException(status_code=409, detail="Study has no source workflow manifest")

    suffix = re.sub(r"[^a-z0-9-]+", "-", suffix.lower()).strip("-") or "opt"
    workflow_name = f"{study['workflow_name']}-{suffix}"
    source_agents = source.get("agents") if isinstance(source.get("agents"), dict) else {}
    agent_name_map = {name: f"{name}-{suffix}" for name in source_agents}

    bundle: list[dict[str, Any]] = []
    for source_name, source_agent in source_agents.items():
        if not isinstance(source_agent, dict):
            continue
        candidate_agent = _clone(source_agent)
        candidate_agent["metadata"] = _copy_metadata(candidate_agent, agent_name_map[source_name], namespace, study)
        annotations = candidate_agent["metadata"].setdefault("annotations", {})
        if optimizer_output:
            annotations["kubesynapse.ai/optimizer-output-preview"] = optimizer_output[:512]
        bundle.append(candidate_agent)

    candidate_workflow = _clone(source_workflow)
    candidate_workflow["metadata"] = _copy_metadata(candidate_workflow, workflow_name, namespace, study)
    spec = candidate_workflow.get("spec") if isinstance(candidate_workflow.get("spec"), dict) else {}
    steps = []
    for step in spec.get("steps") or []:
        step_copy = _clone(step)
        ref = str(step_copy.get("agentRef") or "")
        if ref in agent_name_map:
            step_copy["agentRef"] = agent_name_map[ref]
        steps.append(step_copy)
    spec["steps"] = steps
    candidate_workflow["spec"] = spec
    bundle.append(candidate_workflow)
    return bundle


def _candidate_workflow_name(bundle: list[dict[str, Any]]) -> str:
    workflow = _workflow_from_bundle(bundle)
    if workflow is None:
        return ""
    return _manifest_name(workflow)


def _saved_percent(baseline: float | int | None, candidate: float | int | None) -> float:
    baseline_value = float(baseline or 0)
    candidate_value = float(candidate or 0)
    if baseline_value <= 0:
        return 0.0
    return round(((baseline_value - candidate_value) / baseline_value) * 100, 1)


def _metrics_delta(baseline: dict[str, Any] | None, candidate: dict[str, Any] | None) -> dict[str, Any]:
    if not baseline or not candidate:
        return {}
    return {
        "duration_saved_percent": _saved_percent(baseline.get("duration_ms"), candidate.get("duration_ms")),
        "tokens_saved_percent": _saved_percent(baseline.get("total_tokens"), candidate.get("total_tokens")),
        "cost_saved_percent": _saved_percent(
            baseline.get("estimated_cost_usd") or baseline.get("total_cost_usd"),
            candidate.get("estimated_cost_usd") or candidate.get("total_cost_usd"),
        ),
        "tool_calls_saved_percent": _saved_percent(baseline.get("total_tool_calls"), candidate.get("total_tool_calls")),
    }


def _compute_roi(study: dict[str, Any], candidate_id: str | None = None) -> dict[str, Any]:
    trials = optimization_store.list_trials(study["id"], candidate_id=candidate_id)
    passing_trials = [
        trial for trial in trials
        if trial.get("result_execution_id") and str(trial.get("quality_status") or "").lower() in _PASSING_QUALITY_STATES
    ]
    candidate_traces = [_get_trace(str(trial["result_execution_id"])) for trial in passing_trials]
    candidate_metrics = _aggregate_metrics(candidate_traces)
    baseline_metrics = study.get("baseline_metrics") or {}
    deltas = {
        "duration_saved_percent": _saved_percent(baseline_metrics.get("avg_duration_ms"), candidate_metrics.get("avg_duration_ms")),
        "tokens_saved_percent": _saved_percent(baseline_metrics.get("avg_tokens"), candidate_metrics.get("avg_tokens")),
        "cost_saved_percent": _saved_percent(baseline_metrics.get("avg_cost_usd"), candidate_metrics.get("avg_cost_usd")),
        "tool_calls_saved_percent": _saved_percent(baseline_metrics.get("avg_tool_calls"), candidate_metrics.get("avg_tool_calls")),
    }
    verified = bool(
        candidate_metrics["sample_count"] > 0
        and candidate_metrics["success_rate"] >= float(baseline_metrics.get("success_rate") or 0)
        and (deltas["tokens_saved_percent"] > 0 or deltas["duration_saved_percent"] > 0 or deltas["cost_saved_percent"] > 0)
    )
    monthly_runs = max(int(baseline_metrics.get("sample_count") or 0) * 20, 1)
    projected = {
        "monthly_runs_assumption": monthly_runs,
        "monthly_cost_saved_usd": round(
            max(float(baseline_metrics.get("avg_cost_usd") or 0) - float(candidate_metrics.get("avg_cost_usd") or 0), 0)
            * monthly_runs,
            4,
        ),
        "monthly_hours_saved": round(
            max(float(baseline_metrics.get("avg_duration_ms") or 0) - float(candidate_metrics.get("avg_duration_ms") or 0), 0)
            * monthly_runs
            / 3_600_000,
            3,
        ),
    }
    projected["yearly_cost_saved_usd"] = round(projected["monthly_cost_saved_usd"] * 12, 4)
    projected["yearly_hours_saved"] = round(projected["monthly_hours_saved"] * 12, 3)
    return {
        "study_id": study["id"],
        "candidate_id": candidate_id,
        "proof_status": "verified" if verified else ("pending_trials" if candidate_metrics["sample_count"] == 0 else "needs_review"),
        "verified": verified,
        "proof_gate": study.get("proof_gate") or {},
        "baseline_metrics": baseline_metrics,
        "candidate_metrics": candidate_metrics,
        "deltas": deltas,
        "trial_count": len(trials),
        "passing_trial_count": len(passing_trials),
        "projected_savings": projected,
    }


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, nested in value.items():
            if _SENSITIVE_KEY_RE.search(str(key)):
                redacted[key] = "[REDACTED]"
            else:
                redacted[key] = _redact(nested)
        return redacted
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, str):
        return _SECRET_VALUE_RE.sub("[REDACTED]", value)
    return value


def _apply_manifest_bundle(bundle: list[dict[str, Any]], namespace: str) -> list[dict[str, str]]:
    from kubernetes import client

    api = client.CustomObjectsApi()
    results: list[dict[str, str]] = []
    plural_by_kind = {"AIAgent": "aiagents", "AgentWorkflow": "agentworkflows"}
    for manifest in bundle:
        kind = str(manifest.get("kind") or "")
        plural = plural_by_kind.get(kind)
        if not plural:
            raise HTTPException(status_code=422, detail=f"Unsupported manifest kind {kind}")
        name = _manifest_name(manifest)
        body = _clone(manifest)
        body.setdefault("apiVersion", f"{RESOURCE_GROUP}/{RESOURCE_VERSION}")
        body.setdefault("kind", RESOURCE_KIND_BY_PLURAL[plural])
        body.setdefault("metadata", {})["namespace"] = namespace
        try:
            api.create_namespaced_custom_object(
                group=RESOURCE_GROUP,
                version=RESOURCE_VERSION,
                namespace=namespace,
                plural=plural,
                body=body,
            )
            results.append({"kind": kind, "name": name, "status": "created"})
        except Exception as exc:
            if getattr(exc, "status", None) != 409:
                raise HTTPException(status_code=502, detail=f"Failed to apply {kind}/{name}") from exc
            api.replace_namespaced_custom_object(
                group=RESOURCE_GROUP,
                version=RESOURCE_VERSION,
                namespace=namespace,
                plural=plural,
                name=name,
                body=body,
            )
            results.append({"kind": kind, "name": name, "status": "updated"})
    return results


@router.post("/studies", status_code=201)
def create_study(body: CreateStudyRequest, user: dict[str, Any] = Depends(verify_token)) -> dict[str, Any]:
    ensure_namespace_access(user, body.namespace, "operator")
    traces = [_get_trace(execution_id) for execution_id in body.baseline_execution_ids]
    for trace in traces:
        ensure_namespace_access(user, str(trace.get("namespace") or body.namespace), "operator")
    source_manifests = _load_source_manifests(body.namespace, body.workflow_name, body.source_manifests)
    baseline_metrics = _aggregate_metrics(traces)
    opportunities = _opportunities_for_traces(traces)
    return optimization_store.create_study(
        namespace=body.namespace,
        workflow_name=body.workflow_name,
        optimizer_agent_name=body.optimizer_agent_name,
        objective=body.objective,
        baseline_execution_ids=body.baseline_execution_ids,
        baseline_metrics=baseline_metrics,
        opportunities=opportunities,
        source_manifests=source_manifests,
        created_by=_principal(user),
    )


@router.get("/studies/{study_id}")
def get_study(study_id: str, user: dict[str, Any] = Depends(verify_token)) -> dict[str, Any]:
    study = optimization_store.get_study(study_id)
    if study is None:
        raise HTTPException(status_code=404, detail="Optimization study not found")
    ensure_namespace_access(user, str(study["namespace"]))
    study["candidates"] = optimization_store.list_candidates(study_id)
    study["trials"] = optimization_store.list_trials(study_id)
    return study


@router.post("/studies/{study_id}/candidates", status_code=201)
def create_candidate(study_id: str, body: CreateCandidateRequest, user: dict[str, Any] = Depends(verify_token)) -> dict[str, Any]:
    study = optimization_store.get_study(study_id)
    if study is None:
        raise HTTPException(status_code=404, detail="Optimization study not found")
    ensure_namespace_access(user, str(study["namespace"]), "admin")
    validation = _validate_candidate_bundle(study, body.manifest_bundle)
    if not validation["valid"]:
        raise HTTPException(status_code=422, detail="; ".join(validation["errors"]))
    return optimization_store.create_candidate(
        study_id=study_id,
        namespace=str(study["namespace"]),
        name=body.name or _candidate_workflow_name(body.manifest_bundle),
        candidate_workflow_name=_candidate_workflow_name(body.manifest_bundle),
        manifest_bundle=_clone(body.manifest_bundle),
        manifest_diff=_manifest_diff(study, body.manifest_bundle),
        optimizer_output=body.optimizer_output,
        validation_results=validation,
        expected_savings=body.expected_savings,
        created_by=_principal(user),
    )


@router.post("/studies/{study_id}/candidates/generate", status_code=201)
def generate_candidate(study_id: str, body: GenerateCandidateRequest, user: dict[str, Any] = Depends(verify_token)) -> dict[str, Any]:
    study = optimization_store.get_study(study_id)
    if study is None:
        raise HTTPException(status_code=404, detail="Optimization study not found")
    ensure_namespace_access(user, str(study["namespace"]), "admin")
    suffix = body.suffix or f"opt-{study_id[-5:]}"
    bundle = _candidate_bundle_from_source(study, suffix, body.optimizer_output)
    validation = _validate_candidate_bundle(study, bundle)
    if not validation["valid"]:
        raise HTTPException(status_code=422, detail="; ".join(validation["errors"]))
    return optimization_store.create_candidate(
        study_id=study_id,
        namespace=str(study["namespace"]),
        name=_candidate_workflow_name(bundle),
        candidate_workflow_name=_candidate_workflow_name(bundle),
        manifest_bundle=bundle,
        manifest_diff=_manifest_diff(study, bundle),
        optimizer_output=body.optimizer_output,
        validation_results=validation,
        expected_savings=body.expected_savings,
        created_by=_principal(user),
    )


@router.post("/candidates/{candidate_id}/approval")
def approve_candidate(candidate_id: str, body: ApprovalRequest, user: dict[str, Any] = Depends(verify_token)) -> dict[str, Any]:
    candidate = optimization_store.get_candidate(candidate_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail="Optimization candidate not found")
    ensure_namespace_access(user, str(candidate["namespace"]), "admin")
    decision = optimization_store.decide_candidate(
        candidate_id=candidate_id,
        decision=body.decision,
        reason=body.reason,
        approved_by=_principal(user),
    )
    if decision is None:
        raise HTTPException(status_code=404, detail="Optimization candidate not found")
    return decision


@router.post("/candidates/{candidate_id}/apply")
def apply_candidate(
    candidate_id: str,
    body: ApplyCandidateRequest,
    request: Request,
    user: dict[str, Any] = Depends(verify_token),
) -> dict[str, Any]:
    del request
    candidate = optimization_store.get_candidate(candidate_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail="Optimization candidate not found")
    ensure_namespace_access(user, str(candidate["namespace"]), "admin")
    if candidate.get("approval_status") != "approved":
        raise HTTPException(status_code=409, detail="Candidate must be approved before apply or trial execution")
    if body.dry_run:
        return {"candidate_id": candidate_id, "dry_run": True, "applied": False, "resources": candidate["manifest_bundle"]}
    results = _apply_manifest_bundle(candidate["manifest_bundle"], str(candidate["namespace"]))
    updated = optimization_store.mark_candidate_applied(candidate_id)
    return {"candidate_id": candidate_id, "dry_run": False, "applied": True, "results": results, "candidate": updated}


@router.post("/candidates/{candidate_id}/trials", status_code=201)
def create_trial(candidate_id: str, body: CreateTrialRequest, user: dict[str, Any] = Depends(verify_token)) -> dict[str, Any]:
    candidate = optimization_store.get_candidate(candidate_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail="Optimization candidate not found")
    ensure_namespace_access(user, str(candidate["namespace"]), "admin")
    if candidate.get("approval_status") != "approved":
        raise HTTPException(status_code=409, detail="Candidate must be approved before trial proof can be recorded")
    study = optimization_store.get_study(str(candidate["study_id"]))
    if study is None:
        raise HTTPException(status_code=404, detail="Optimization study not found")
    baseline = _get_trace(body.baseline_execution_id)
    result = _get_trace(body.result_execution_id) if body.result_execution_id else None
    trial = optimization_store.create_trial(
        study_id=str(candidate["study_id"]),
        candidate_id=candidate_id,
        baseline_execution_id=body.baseline_execution_id,
        result_execution_id=body.result_execution_id,
        quality_status=body.quality_status,
        metrics_delta=_metrics_delta(baseline, result),
        notes=body.notes,
        created_by=_principal(user),
    )
    return trial


@router.get("/studies/{study_id}/roi")
def get_study_roi(
    study_id: str,
    candidate_id: str | None = None,
    user: dict[str, Any] = Depends(verify_token),
) -> dict[str, Any]:
    study = optimization_store.get_study(study_id)
    if study is None:
        raise HTTPException(status_code=404, detail="Optimization study not found")
    ensure_namespace_access(user, str(study["namespace"]))
    return _compute_roi(study, candidate_id=candidate_id)


@router.get("/studies/{study_id}/dataset")
def export_study_dataset(
    study_id: str,
    redacted: bool = True,
    user: dict[str, Any] = Depends(verify_token),
) -> dict[str, Any]:
    study = optimization_store.get_study(study_id)
    if study is None:
        raise HTTPException(status_code=404, detail="Optimization study not found")
    ensure_namespace_access(user, str(study["namespace"]), "operator")
    baseline_traces = [_get_trace(execution_id) for execution_id in study.get("baseline_execution_ids", [])]
    candidates = optimization_store.list_candidates(study_id)
    trials = optimization_store.list_trials(study_id)
    payload = {
        "study_id": study_id,
        "labels": {
            "namespace": study["namespace"],
            "workflow_name": study["workflow_name"],
            "optimizer_agent_name": study.get("optimizer_agent_name"),
            "training_strategy": "dataset_first",
        },
        "source_manifests": study.get("source_manifests") or {},
        "baseline_metrics": study.get("baseline_metrics") or {},
        "opportunities": study.get("opportunities") or [],
        "baseline_traces": baseline_traces,
        "candidates": candidates,
        "trials": trials,
    }
    return _redact(payload) if redacted else payload
