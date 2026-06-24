"""Workflow optimization ROI lab API."""

from __future__ import annotations

import difflib
import json
import logging
import re
import time
from collections import Counter
from contextlib import suppress
from typing import Any

import optimization_store
import trace_store
import yaml
from _core import RESOURCE_GROUP, RESOURCE_KIND_BY_PLURAL, RESOURCE_VERSION, read_custom_resource
from auth_middleware import ensure_namespace_access, verify_token
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, model_validator

router = APIRouter(prefix="/optimizations", tags=["optimizations"])
logger = logging.getLogger(__name__)

_ALLOWED_CANDIDATE_KINDS = {"AIAgent", "AgentWorkflow"}
_PASSING_QUALITY_STATES = {"passed", "machine_passed", "human_passed", "approved"}
_SENSITIVE_KEY_RE = re.compile(r"(api[_-]?key|token|secret|password|credential|authorization)", re.IGNORECASE)
_SECRET_VALUE_RE = re.compile(r"\b(sk-[A-Za-z0-9_\-]{8,}|Bearer\s+[A-Za-z0-9._\-]{12,})\b")
_FENCED_BLOCK_RE = re.compile(r"```[^\n\r]*\r?\n(?P<body>.*?)```", re.DOTALL)
_OPTIMIZER_META_PROMPT_RE = re.compile(
    r"(\[ROI Candidate Guidance\]|\bROI Lab\b|\boptimization stud(?:y|ies)\b|\bcandidate trial\b|"
    r"\bexpected_metric_delta\b|\bbaseline-vs-candidate\b)",
    re.IGNORECASE,
)


class CreateStudyRequest(BaseModel):
    namespace: str = Field(default="default", min_length=1, max_length=128)
    workflow_name: str = Field(min_length=1, max_length=256)
    optimizer_agent_name: str | None = Field(default=None, max_length=256)
    baseline_execution_ids: list[str] = Field(default_factory=list, min_length=1, max_length=50)
    objective: str | None = Field(default=None, max_length=2048)
    source_manifests: dict[str, Any] | None = None

    @model_validator(mode="after")
    def normalize(self) -> CreateStudyRequest:
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
    allow_topology_rewrite: bool = False


class GenerateCandidateRequest(BaseModel):
    optimizer_output: str | None = None
    suffix: str | None = Field(default=None, max_length=32)
    expected_savings: dict[str, Any] = Field(default_factory=dict)
    allow_topology_rewrite: bool = False


class ApprovalRequest(BaseModel):
    decision: str = Field(pattern="^(approved|denied)$")
    reason: str | None = Field(default=None, max_length=1024)


class ApplyCandidateRequest(BaseModel):
    dry_run: bool = True


class RunCandidateRequest(BaseModel):
    baseline_execution_id: str | None = Field(default=None, max_length=128)
    input: str | None = Field(default=None, max_length=4000)
    notes: str | None = Field(default=None, max_length=2048)

    @model_validator(mode="after")
    def normalize(self) -> RunCandidateRequest:
        if self.baseline_execution_id is not None:
            self.baseline_execution_id = self.baseline_execution_id.strip() or None
        if self.input is not None:
            self.input = self.input.strip() or None
        return self


class PromoteCandidateRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=1024)


class CreateTrialRequest(BaseModel):
    baseline_execution_id: str = Field(min_length=1, max_length=128)
    result_execution_id: str | None = Field(default=None, max_length=128)
    quality_status: str = Field(default="needs_review", max_length=64)
    notes: str | None = Field(default=None, max_length=2048)

    @model_validator(mode="after")
    def normalize(self) -> CreateTrialRequest:
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


def _get_traces(execution_ids: list[str]) -> list[dict[str, Any]]:
    traces_by_id = trace_store.get_executions_by_ids(execution_ids)
    missing = [execution_id for execution_id in execution_ids if execution_id not in traces_by_id]
    if missing:
        raise HTTPException(status_code=404, detail=f"Execution '{missing[0]}' not found")
    return [traces_by_id[execution_id] for execution_id in execution_ids]


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


def _avg(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _as_float(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _total_tokens(call: dict[str, Any]) -> float:
    if call.get("total_tokens") is not None:
        return _as_float(call.get("total_tokens"))
    return _as_float(call.get("prompt_tokens")) + _as_float(call.get("completion_tokens"))


def _stable_json(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    except (TypeError, ValueError):
        return str(value)


def _trace_step_maps(trace: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    steps_by_id: dict[str, dict[str, Any]] = {}
    step_name_by_id: dict[str, str] = {}
    for index, step in enumerate(trace.get("steps") or []):
        if not isinstance(step, dict):
            continue
        step_id = str(step.get("id") or step.get("step_id") or f"step-{index}")
        step_name = str(step.get("step_name") or step.get("name") or f"step-{index + 1}")
        steps_by_id[step_id] = step
        step_name_by_id[step_id] = step_name
    return steps_by_id, step_name_by_id


def _step_name_for_call(call: dict[str, Any], step_name_by_id: dict[str, str]) -> str:
    step_id = str(call.get("step_id") or "")
    return step_name_by_id.get(step_id) or str(call.get("step_name") or "workflow")


def _step_rollups(traces: list[dict[str, Any]]) -> list[dict[str, Any]]:
    buckets: dict[str, dict[str, Any]] = {}
    for trace in traces:
        _, step_name_by_id = _trace_step_maps(trace)
        trace_agent = str(trace.get("agent_name") or trace.get("workflow_name") or "workflow")
        for index, step in enumerate(trace.get("steps") or []):
            if not isinstance(step, dict):
                continue
            name = str(step.get("step_name") or step.get("name") or f"step-{index + 1}")
            bucket = buckets.setdefault(
                name,
                {
                    "step_name": name,
                    "step_type": str(step.get("step_type") or step.get("type") or "agent"),
                    "agent_name": trace_agent,
                    "run_count": 0,
                    "_durations": [],
                    "_tokens": [],
                    "_costs": [],
                    "_llm_calls": [],
                    "_tool_calls": [],
                    "_models": Counter(),
                    "_tools": Counter(),
                    "_tool_args": Counter(),
                },
            )
            bucket["run_count"] += 1
            bucket["_durations"].append(_as_float(step.get("duration_ms")))
            bucket["_tokens"].append(_as_float(step.get("tokens_used")))
            bucket["_costs"].append(_as_float(step.get("cost_usd")))
            bucket["_llm_calls"].append(_as_float(step.get("llm_calls_count")))
            bucket["_tool_calls"].append(_as_float(step.get("tool_calls_count")))

        for call in trace.get("llm_calls") or []:
            if not isinstance(call, dict):
                continue
            name = _step_name_for_call(call, step_name_by_id)
            bucket = buckets.setdefault(
                name,
                {
                    "step_name": name,
                    "step_type": "agent",
                    "agent_name": trace_agent,
                    "run_count": 0,
                    "_durations": [],
                    "_tokens": [],
                    "_costs": [],
                    "_llm_calls": [],
                    "_tool_calls": [],
                    "_models": Counter(),
                    "_tools": Counter(),
                    "_tool_args": Counter(),
                },
            )
            model = str(call.get("model") or "unknown")
            bucket["_models"][model] += 1

        for call in trace.get("tool_calls") or []:
            if not isinstance(call, dict):
                continue
            name = _step_name_for_call(call, step_name_by_id)
            bucket = buckets.setdefault(
                name,
                {
                    "step_name": name,
                    "step_type": "agent",
                    "agent_name": trace_agent,
                    "run_count": 0,
                    "_durations": [],
                    "_tokens": [],
                    "_costs": [],
                    "_llm_calls": [],
                    "_tool_calls": [],
                    "_models": Counter(),
                    "_tools": Counter(),
                    "_tool_args": Counter(),
                },
            )
            tool = str(call.get("tool_name") or "unknown")
            bucket["_tools"][tool] += 1
            args_key = _stable_json(call.get("tool_args") or call.get("args") or {})
            bucket["_tool_args"][f"{tool}:{args_key}"] += 1

    rollups: list[dict[str, Any]] = []
    for bucket in buckets.values():
        repeated_groups = [key for key, count in bucket["_tool_args"].items() if count > 1]
        dominant_model = bucket["_models"].most_common(1)[0][0] if bucket["_models"] else None
        top_tool = bucket["_tools"].most_common(1)[0][0] if bucket["_tools"] else None
        rollups.append(
            {
                "step_name": bucket["step_name"],
                "step_type": bucket["step_type"],
                "agent_name": bucket["agent_name"],
                "run_count": bucket["run_count"],
                "avg_duration_ms": _round(_avg(bucket["_durations"]), 3),
                "avg_tokens": _round(_avg(bucket["_tokens"]), 3),
                "avg_cost_usd": _round(_avg(bucket["_costs"]), 6),
                "avg_llm_calls": _round(_avg(bucket["_llm_calls"]), 3),
                "avg_tool_calls": _round(_avg(bucket["_tool_calls"]), 3),
                "dominant_model": dominant_model,
                "top_tool": top_tool,
                "tool_names": [name for name, _count in bucket["_tools"].most_common(6)],
                "repeated_tool_arg_groups": len(repeated_groups),
            }
        )
    return sorted(rollups, key=lambda item: float(item.get("avg_duration_ms") or 0), reverse=True)


def _model_rollups(traces: list[dict[str, Any]]) -> list[dict[str, Any]]:
    buckets: dict[str, dict[str, Any]] = {}
    for trace in traces:
        _, step_name_by_id = _trace_step_maps(trace)
        for call in trace.get("llm_calls") or []:
            if not isinstance(call, dict):
                continue
            model = str(call.get("model") or "unknown")
            bucket = buckets.setdefault(
                model,
                {
                    "model": model,
                    "provider": str(call.get("provider") or ""),
                    "calls": 0,
                    "tokens": 0.0,
                    "cost_usd": 0.0,
                    "latency_ms": 0.0,
                    "_steps": Counter(),
                },
            )
            bucket["calls"] += 1
            bucket["tokens"] += _total_tokens(call)
            bucket["cost_usd"] += _as_float(call.get("cost_usd"))
            bucket["latency_ms"] += _as_float(call.get("latency_ms") or call.get("duration_ms"))
            bucket["_steps"][_step_name_for_call(call, step_name_by_id)] += 1

    result = []
    for bucket in buckets.values():
        calls = max(int(bucket["calls"]), 1)
        result.append(
            {
                "model": bucket["model"],
                "provider": bucket["provider"],
                "calls": bucket["calls"],
                "tokens": _round(bucket["tokens"], 3),
                "cost_usd": _round(bucket["cost_usd"], 6),
                "avg_latency_ms": _round(bucket["latency_ms"] / calls, 3),
                "affected_steps": [name for name, _count in bucket["_steps"].most_common(8)],
            }
        )
    return sorted(result, key=lambda item: float(item.get("tokens") or 0), reverse=True)


def _tool_rollups(traces: list[dict[str, Any]]) -> list[dict[str, Any]]:
    buckets: dict[str, dict[str, Any]] = {}
    for trace in traces:
        _, step_name_by_id = _trace_step_maps(trace)
        for call in trace.get("tool_calls") or []:
            if not isinstance(call, dict):
                continue
            tool = str(call.get("tool_name") or "unknown")
            args_key = _stable_json(call.get("tool_args") or call.get("args") or {})
            bucket = buckets.setdefault(
                tool,
                {
                    "tool_name": tool,
                    "calls": 0,
                    "duration_ms": 0.0,
                    "_steps": Counter(),
                    "_args": Counter(),
                },
            )
            bucket["calls"] += 1
            bucket["duration_ms"] += _as_float(call.get("duration_ms"))
            bucket["_steps"][_step_name_for_call(call, step_name_by_id)] += 1
            bucket["_args"][args_key] += 1

    result = []
    for bucket in buckets.values():
        calls = max(int(bucket["calls"]), 1)
        result.append(
            {
                "tool_name": bucket["tool_name"],
                "calls": bucket["calls"],
                "avg_duration_ms": _round(bucket["duration_ms"] / calls, 3),
                "repeated_arg_groups": sum(1 for count in bucket["_args"].values() if count > 1),
                "affected_steps": [name for name, _count in bucket["_steps"].most_common(8)],
            }
        )
    return sorted(result, key=lambda item: int(item.get("calls") or 0), reverse=True)


def _opportunities_for_traces(traces: list[dict[str, Any]]) -> list[dict[str, Any]]:
    metrics = _aggregate_metrics(traces)
    steps = _step_rollups(traces)
    tools = _tool_rollups(traces)
    models = _model_rollups(traces)
    slowest = steps[0] if steps else {}
    heaviest = max(steps, key=lambda item: float(item.get("avg_tokens") or 0), default={})
    top_tool = tools[0] if tools else {"tool_name": "unknown", "calls": 0, "affected_steps": []}
    top_model = models[0] if models else {"model": "unknown", "calls": 0, "affected_steps": []}
    opportunities = [
        {
            "kind": "latency",
            "lever": "context_trim",
            "severity": "high" if float(slowest.get("avg_duration_ms") or 0) > 60_000 else "medium",
            "title": "Trim slow-step context",
            "impact_score": min(95, 45 + int(float(slowest.get("avg_duration_ms") or 0) / 3_000)),
            "confidence": "medium" if metrics["sample_count"] >= 5 else "low",
            "metric": "avg_duration_ms",
            "baseline_value": slowest.get("avg_duration_ms"),
            "affected_steps": [slowest.get("step_name")] if slowest.get("step_name") else [],
            "estimated_savings": {"duration_percent": 10 if metrics["sample_count"] < 5 else 18},
            "evidence": {
                "step": slowest.get("step_name"),
                "avg_step_duration_ms": slowest.get("avg_duration_ms"),
                "avg_duration_ms": metrics["avg_duration_ms"],
            },
            "recommendation": "Trim context, batch deterministic tool reads, and route this step to the cheapest model that preserves quality.",
            "dataset_use": "Create replay cases that compare step output after context trimming.",
            "safe_scope": "prompt_context_only",
        },
        {
            "kind": "tokens",
            "lever": "model_route",
            "severity": "high" if metrics["avg_tokens"] > 4_000 else "medium",
            "title": "Route expensive LLM calls",
            "impact_score": min(90, 40 + int(float(metrics["avg_tokens"]) / 120)),
            "confidence": "medium" if metrics["sample_count"] >= 5 else "low",
            "metric": "avg_tokens",
            "baseline_value": metrics["avg_tokens"],
            "affected_steps": top_model.get("affected_steps") or ([heaviest.get("step_name")] if heaviest.get("step_name") else []),
            "estimated_savings": {"tokens_percent": 12 if metrics["sample_count"] < 5 else 25},
            "evidence": {
                "step": heaviest.get("step_name"),
                "avg_step_tokens": heaviest.get("avg_tokens"),
                "avg_tokens": metrics["avg_tokens"],
                "top_model": top_model.get("model"),
            },
            "recommendation": "Convert repeated context into step-specific instructions and reusable artifacts before the next LLM call.",
            "dataset_use": "Use successful traces as routing labels for cheaper models and local distillation candidates.",
            "safe_scope": "model_prompt_routing",
        },
        {
            "kind": "tool_churn",
            "lever": "tool_batching",
            "severity": "high" if int(top_tool.get("calls") or 0) > 4 else "medium",
            "title": "Batch repeated tool calls",
            "impact_score": min(88, 35 + int(top_tool.get("calls") or 0) * 6),
            "confidence": "medium" if int(top_tool.get("repeated_arg_groups") or 0) > 0 else "low",
            "metric": "avg_tool_calls",
            "baseline_value": metrics["avg_tool_calls"],
            "affected_steps": top_tool.get("affected_steps") or [],
            "estimated_savings": {"tool_calls_percent": 15 if int(top_tool.get("repeated_arg_groups") or 0) else 8},
            "evidence": {"tool": top_tool.get("tool_name"), "count": top_tool.get("calls"), "avg_tool_calls": metrics["avg_tool_calls"], "repeated_arg_groups": top_tool.get("repeated_arg_groups")},
            "recommendation": "Batch related reads/writes and ask the agent to plan tool use before calling tools.",
            "dataset_use": "Mine repeated tool arguments into reusable workflow prefetch and batching examples.",
            "safe_scope": "tool_instruction_only",
        },
        {
            "kind": "cache",
            "lever": "cache_hints",
            "severity": "medium" if metrics["avg_cache_read_tokens"] <= 0 and metrics["avg_tokens"] > 0 else "low",
            "title": "Add cacheable context boundaries",
            "impact_score": 52 if metrics["avg_cache_read_tokens"] <= 0 and metrics["avg_tokens"] > 0 else 25,
            "confidence": "low",
            "metric": "avg_cache_read_tokens",
            "baseline_value": metrics["avg_cache_read_tokens"],
            "affected_steps": [step.get("step_name") for step in steps[:3] if step.get("step_name")],
            "estimated_savings": {"tokens_percent": 5},
            "evidence": {"avg_cache_read_tokens": metrics["avg_cache_read_tokens"], "avg_tokens": metrics["avg_tokens"]},
            "recommendation": "Separate stable instructions, schemas, and examples from volatile run data so providers can reuse cached prefixes.",
            "dataset_use": "Mark stable versus volatile prompt sections for later prompt-cache policy learning.",
            "safe_scope": "prompt_layout_only",
        },
        {
            "kind": "reliability",
            "lever": "proof_gate",
            "severity": "high" if metrics["success_rate"] < 1 else "low",
            "title": "Hybrid proof gate",
            "impact_score": 40 if metrics["success_rate"] >= 1 else 70,
            "confidence": "high" if metrics["sample_count"] >= 10 else "medium" if metrics["sample_count"] >= 5 else "low",
            "metric": "success_rate",
            "baseline_value": metrics["success_rate"],
            "affected_steps": [step.get("step_name") for step in steps if step.get("step_name")],
            "estimated_savings": {"failure_retry_percent": 0 if metrics["success_rate"] >= 1 else 20},
            "evidence": {"success_rate": metrics["success_rate"], "sample_count": metrics["sample_count"]},
            "recommendation": "Require machine checks plus human review before promoting any cheaper candidate.",
            "dataset_use": "Keep failed and approved trials as evaluator labels, not only training examples.",
            "safe_scope": "evaluation_only",
        },
    ]
    return sorted(opportunities, key=lambda item: int(item.get("impact_score") or 0), reverse=True)


def _trajectory_diagnostics(traces: list[dict[str, Any]]) -> list[dict[str, Any]]:
    metrics = _aggregate_metrics(traces)
    steps = _step_rollups(traces)
    tools = _tool_rollups(traces)
    models = _model_rollups(traces)
    diagnostics: list[dict[str, Any]] = []
    repeated_tools = [tool for tool in tools if int(tool.get("repeated_arg_groups") or 0) > 0]
    if repeated_tools:
        top = repeated_tools[0]
        diagnostics.append(
            {
                "id": "repeated_tool_arguments",
                "severity": "high" if int(top.get("repeated_arg_groups") or 0) > 2 else "medium",
                "title": "Repeated tool arguments",
                "evidence": {"tool": top.get("tool_name"), "calls": top.get("calls"), "repeated_arg_groups": top.get("repeated_arg_groups")},
                "affected_steps": top.get("affected_steps") or [],
                "optimizer_hint": "Batch identical reads and convert repeated writes into a single structured artifact update.",
            }
        )
    if steps:
        slow = steps[0]
        diagnostics.append(
            {
                "id": "expensive_step",
                "severity": "high" if float(slow.get("avg_duration_ms") or 0) > metrics["avg_duration_ms"] else "medium",
                "title": "Dominant wall-clock step",
                "evidence": {"step": slow.get("step_name"), "avg_duration_ms": slow.get("avg_duration_ms"), "avg_tokens": slow.get("avg_tokens")},
                "affected_steps": [slow.get("step_name")],
                "optimizer_hint": "Start candidate work here; do not optimize cheap steps before the dominant bottleneck.",
            }
        )
    if models and len(models) == 1 and metrics["avg_llm_calls"] > 0:
        diagnostics.append(
            {
                "id": "single_model_route",
                "severity": "medium",
                "title": "No model routing observed",
                "evidence": {"model": models[0].get("model"), "calls": models[0].get("calls"), "tokens": models[0].get("tokens")},
                "affected_steps": models[0].get("affected_steps") or [],
                "optimizer_hint": "Evaluate deterministic or summarization-heavy steps on cheaper routed models before touching workflow topology.",
            }
        )
    if metrics["avg_cache_read_tokens"] <= 0 and metrics["avg_tokens"] > 0:
        diagnostics.append(
            {
                "id": "no_cache_reuse",
                "severity": "medium",
                "title": "No prompt-cache reuse",
                "evidence": {"avg_cache_read_tokens": metrics["avg_cache_read_tokens"], "avg_tokens": metrics["avg_tokens"]},
                "affected_steps": [step.get("step_name") for step in steps[:3] if step.get("step_name")],
                "optimizer_hint": "Move stable policies, schemas, and examples ahead of volatile run data to improve prefix-cache hit potential.",
            }
        )
    return diagnostics


def _dataset_readiness(traces: list[dict[str, Any]], source_manifests: dict[str, Any]) -> dict[str, Any]:
    metrics = _aggregate_metrics(traces)
    llm_examples = sum(len([call for call in trace.get("llm_calls") or [] if isinstance(call, dict)]) for trace in traces)
    tool_examples = sum(len([call for call in trace.get("tool_calls") or [] if isinstance(call, dict)]) for trace in traces)
    step_examples = sum(len([step for step in trace.get("steps") or [] if isinstance(step, dict)]) for trace in traces)
    if metrics["sample_count"] < 5:
        state = "needs_more_samples"
    elif metrics["successful_count"] < metrics["sample_count"]:
        state = "needs_more_review"
    elif llm_examples >= 20 and step_examples >= 20:
        state = "candidate"
    else:
        state = "ready_for_replay"
    workflow = source_manifests.get("workflow") if isinstance(source_manifests.get("workflow"), dict) else {}
    steps = workflow.get("spec", {}).get("steps", []) if isinstance(workflow.get("spec"), dict) else []
    return {
        "state": state,
        "baseline_examples": metrics["sample_count"],
        "successful_examples": metrics["successful_count"],
        "llm_examples": llm_examples,
        "tool_examples": tool_examples,
        "step_examples": step_examples,
        "manifest_snapshots": 1 + len(source_manifests.get("agents", {}) if isinstance(source_manifests.get("agents"), dict) else {}),
        "workflow_steps": len(steps) if isinstance(steps, list) else 0,
        "redaction_required": True,
        "labels": ["workflow", "step", "agent", "model", "tool", "quality", "contract", "cost", "latency"],
        "splits": {
            "replay_cases": metrics["sample_count"],
            "evaluator_cases": metrics["successful_count"],
            "distillation_examples": llm_examples,
            "routing_examples": llm_examples,
            "regression_cases": max(1, int(metrics["sample_count"] * 0.2)) if metrics["sample_count"] else 0,
        },
        "local_model_path": {
            "suitability": "candidate" if state == "candidate" else "needs_more_review" if state == "ready_for_replay" else "needs_more_examples",
            "next_step": "collect at least 20 reviewed LLM examples per high-value workflow before tenant-local tuning",
            "target": "tenant-local evaluator or routing model before optimizer fine-tuning",
        },
    }


def _build_optimizer_intelligence(traces: list[dict[str, Any]], source_manifests: dict[str, Any]) -> dict[str, Any]:
    metrics = _aggregate_metrics(traces)
    opportunities = _opportunities_for_traces(traces)
    sample_count = int(metrics.get("sample_count") or 0)
    confidence_level = "high" if sample_count >= 10 else "medium" if sample_count >= 5 else "low"
    return {
        "scorecard": {
            "sample_count": sample_count,
            "confidence_level": confidence_level,
            "confidence_reason": "Use at least 5 safe trials for directional ROI and 10+ for enterprise promotion confidence.",
            "optimization_scope": "prompt_model_tool_v1",
            "primary_objective": "reduce cost, tokens, wall-clock time, and retries while preserving workflow output contracts",
        },
        "ranked_levers": opportunities,
        "step_rollups": _step_rollups(traces),
        "model_rollups": _model_rollups(traces),
        "tool_rollups": _tool_rollups(traces),
        "trajectory_diagnostics": _trajectory_diagnostics(traces),
        "dataset_readiness": _dataset_readiness(traces, source_manifests),
    }


def _proof_gate_for_study(baseline_metrics: dict[str, Any], intelligence: dict[str, Any]) -> dict[str, Any]:
    confidence = intelligence.get("scorecard") if isinstance(intelligence.get("scorecard"), dict) else {}
    return {
        "mode": "hybrid",
        "requires_approval": True,
        "minimum_safe_trials": 5,
        "minimum_success_rate": baseline_metrics.get("success_rate", 0),
        "minimum_quality_status": "passed",
        "max_metric_regression_percent": 5,
        "hard_checks": [
            "same_namespace",
            "allowed_kinds",
            "same_topology",
            "preserve_step_names",
            "preserve_output_contracts",
            "no_secret_or_env_expansion",
            "no_optimizer_meta_in_candidate_prompts",
            "admin_approval_for_apply",
        ],
        "human_review_triggers": [
            "external_side_effects",
            "unverifiable_output_quality",
            "model_family_change",
            "approval_policy_change",
        ],
        "promotion_requirements": [
            "positive_cost_or_time_delta",
            "no_metric_regression_beyond_noise_budget",
            "no_contract_regression",
            "passing_quality_trials",
            "dataset_redaction_complete",
        ],
        "confidence": {
            "level": confidence.get("confidence_level", "low"),
            "sample_count": confidence.get("sample_count", 0),
            "basis": confidence.get("confidence_reason"),
        },
        "optimizer_intelligence": intelligence,
    }


def _expose_optimizer_intelligence(study: dict[str, Any]) -> dict[str, Any]:
    proof_gate = study.get("proof_gate") if isinstance(study.get("proof_gate"), dict) else {}
    intelligence = proof_gate.get("optimizer_intelligence") if isinstance(proof_gate.get("optimizer_intelligence"), dict) else None
    if intelligence is not None:
        study["optimizer_intelligence"] = intelligence
    return study



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
        workflow = provided.get("workflow")
        if not isinstance(workflow, dict):
            raise HTTPException(status_code=422, detail="source workflow manifest is required for optimization studies")
        if str(workflow.get("kind") or "") != "AgentWorkflow":
            raise HTTPException(status_code=422, detail="source workflow manifest must be an AgentWorkflow")

        workflow_namespace = _manifest_namespace(workflow)
        if workflow_namespace != namespace:
            raise HTTPException(status_code=422, detail="source workflow manifest must stay in the study namespace")
        workflow_manifest_name = _manifest_name(workflow)
        if workflow_manifest_name and workflow_manifest_name != workflow_name:
            raise HTTPException(status_code=422, detail="source workflow manifest name must match the study workflow")

        provided_agents = provided.get("agents") if isinstance(provided.get("agents"), dict) else {}
        agent_refs = [
            str(item).strip()
            for item in (provided.get("agent_refs") if isinstance(provided.get("agent_refs"), list) else _extract_agent_refs(workflow))
            if str(item).strip()
        ]
        if not agent_refs:
            agent_refs = _extract_agent_refs(workflow)

        agents: dict[str, Any] = {}
        for agent_ref in agent_refs:
            manifest = provided_agents.get(agent_ref)
            if not isinstance(manifest, dict):
                try:
                    manifest = read_custom_resource("aiagents", agent_ref, namespace, "Agent")
                except Exception as exc:
                    raise HTTPException(
                        status_code=422,
                        detail=f"source agent manifest is unavailable for workflow agentRef '{agent_ref}'",
                    ) from exc
            if str(manifest.get("kind") or "") != "AIAgent":
                raise HTTPException(status_code=422, detail=f"source agent manifest for '{agent_ref}' must be an AIAgent")
            if _manifest_namespace(manifest) != namespace:
                raise HTTPException(status_code=422, detail=f"source agent manifest for '{agent_ref}' must stay in the study namespace")
            agents[agent_ref] = _clone(manifest)

        return {"workflow": _clone(workflow), "agent_refs": agent_refs, "agents": agents}

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


def _workflow_steps(workflow: dict[str, Any] | None) -> list[dict[str, Any]]:
    if workflow is None:
        return []
    spec = workflow.get("spec") if isinstance(workflow.get("spec"), dict) else {}
    return [step for step in spec.get("steps") or [] if isinstance(step, dict)]


def _spec_model(manifest: dict[str, Any] | None) -> str | None:
    spec = manifest.get("spec") if isinstance(manifest, dict) and isinstance(manifest.get("spec"), dict) else {}
    model = spec.get("model")
    return str(model).strip() if model is not None and str(model).strip() else None


def _candidate_agent_ref_map(source_workflow: dict[str, Any] | None, candidate_workflow: dict[str, Any] | None) -> dict[str, str]:
    source_steps = _workflow_steps(source_workflow)
    candidate_steps = _workflow_steps(candidate_workflow)
    refs: dict[str, str] = {}
    for source_step, candidate_step in zip(source_steps, candidate_steps, strict=False):
        source_ref = str(source_step.get("agentRef") or "").strip()
        candidate_ref = str(candidate_step.get("agentRef") or "").strip()
        if source_ref and candidate_ref:
            refs[source_ref] = candidate_ref
    return refs


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
        for item in value:
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


def _workflow_semantic_spec(manifest: dict[str, Any] | None) -> dict[str, Any]:
    spec = _clone(manifest.get("spec") if isinstance(manifest, dict) and isinstance(manifest.get("spec"), dict) else {})
    steps = []
    for step in spec.get("steps") or []:
        if not isinstance(step, dict):
            continue
        step_copy = _clone(step)
        step_copy.pop("agentRef", None)
        steps.append(step_copy)
    if steps:
        spec["steps"] = steps
    return spec


def _agent_semantic_spec(manifest: dict[str, Any] | None) -> dict[str, Any]:
    spec = _clone(manifest.get("spec") if isinstance(manifest, dict) and isinstance(manifest.get("spec"), dict) else {})
    # Status, metadata, generated resource names, and candidate agentRefs are copy mechanics.
    # Agent spec changes are product changes and should be visible as effective candidate work.
    return spec


def _candidate_effective_changes(study: dict[str, Any], bundle: list[dict[str, Any]]) -> list[str]:
    source = study.get("source_manifests") if isinstance(study.get("source_manifests"), dict) else {}
    source_workflow = source.get("workflow") if isinstance(source.get("workflow"), dict) else None
    candidate_workflow = _workflow_from_bundle(bundle)
    changes: list[str] = []

    workflow_paths = _diff_paths(
        _workflow_semantic_spec(source_workflow),
        _workflow_semantic_spec(candidate_workflow),
        "AgentWorkflow.spec",
    )
    changes.extend(workflow_paths)
    if source_workflow and candidate_workflow and _step_signature(source_workflow) != _step_signature(candidate_workflow):
        changes.append("AgentWorkflow.topology")

    source_agents = source.get("agents") if isinstance(source.get("agents"), dict) else {}
    candidate_agents = {
        _manifest_name(manifest): manifest
        for manifest in bundle
        if isinstance(manifest, dict) and str(manifest.get("kind") or "") == "AIAgent"
    }
    mapped_candidate_names = set()
    for source_agent_name, candidate_agent_name in _candidate_agent_ref_map(source_workflow, candidate_workflow).items():
        source_agent = source_agents.get(source_agent_name) if isinstance(source_agents, dict) else None
        candidate_agent = candidate_agents.get(candidate_agent_name)
        if candidate_agent:
            mapped_candidate_names.add(candidate_agent_name)
        agent_paths = _diff_paths(
            _agent_semantic_spec(source_agent),
            _agent_semantic_spec(candidate_agent),
            f"AIAgent.{source_agent_name}.spec",
        )
        changes.extend(agent_paths)

    if source_workflow and candidate_workflow and _step_signature(source_workflow) != _step_signature(candidate_workflow):
        for candidate_agent_name in sorted(set(candidate_agents) - mapped_candidate_names):
            changes.append(f"AIAgent.{candidate_agent_name}.topology_agent")

    deduped: list[str] = []
    seen: set[str] = set()
    for change in changes:
        if not change or change in seen:
            continue
        seen.add(change)
        deduped.append(change)
    return deduped


def _candidate_optimizer_meta_noise(bundle: list[dict[str, Any]]) -> list[dict[str, str]]:
    noise: list[dict[str, str]] = []
    for manifest in bundle:
        if not isinstance(manifest, dict):
            continue
        kind = str(manifest.get("kind") or "")
        resource = f"{kind}/{_manifest_name(manifest)}"
        spec = manifest.get("spec") if isinstance(manifest.get("spec"), dict) else {}
        if kind == "AgentWorkflow":
            for index, step in enumerate(spec.get("steps") or []):
                if not isinstance(step, dict):
                    continue
                prompt = str(step.get("prompt") or "")
                if _OPTIMIZER_META_PROMPT_RE.search(prompt):
                    noise.append({"resource": resource, "path": f"spec.steps[{index}].prompt"})
        elif kind == "AIAgent":
            system_prompt = str(spec.get("systemPrompt") or "")
            if _OPTIMIZER_META_PROMPT_RE.search(system_prompt):
                noise.append({"resource": resource, "path": "spec.systemPrompt"})
    return noise


def _validate_candidate_bundle(
    study: dict[str, Any],
    bundle: list[dict[str, Any]],
    *,
    allow_topology_rewrite: bool = False,
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    errors: list[str] = []
    validation_warnings: list[str] = list(warnings or [])
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

    topology_preserved = (
        _step_signature(source_workflow) == _step_signature(candidate_workflow)
        if source_workflow and candidate_workflow
        else False
    )
    if source_workflow and candidate_workflow and not topology_preserved and not allow_topology_rewrite:
        errors.append("workflow topology must preserve step names/order and step types")

    source_agents = source.get("agents") if isinstance(source.get("agents"), dict) else {}
    candidate_agents = {
        _manifest_name(manifest): manifest
        for manifest in bundle
        if isinstance(manifest, dict) and str(manifest.get("kind") or "") == "AIAgent"
    }
    source_models = {
        model
        for model in (_spec_model(agent) for agent in source_agents.values())
        if model
    } if isinstance(source_agents, dict) else set()
    for source_agent_name, candidate_agent_name in _candidate_agent_ref_map(source_workflow, candidate_workflow).items():
        source_agent = source_agents.get(source_agent_name) if isinstance(source_agents, dict) else None
        candidate_agent = candidate_agents.get(candidate_agent_name)
        source_model = _spec_model(source_agent)
        candidate_model = _spec_model(candidate_agent)
        if source_model and candidate_model and source_model != candidate_model:
            errors.append(
                f"candidate agent '{candidate_agent_name}' must preserve source model '{source_model}' in v1"
            )
    if allow_topology_rewrite and source_models:
        for candidate_agent_name, candidate_agent in candidate_agents.items():
            candidate_model = _spec_model(candidate_agent)
            if candidate_model and candidate_model not in source_models:
                errors.append(
                    f"candidate agent '{candidate_agent_name}' must use one of the source models in topology rewrite mode"
                )

    workflow_agent_refs = {
        str(step.get("agentRef") or "")
        for step in _workflow_steps(candidate_workflow or {})
        if str(step.get("agentRef") or "")
    }
    missing_refs = sorted(ref for ref in workflow_agent_refs if ref not in candidate_agents)
    if missing_refs:
        errors.append(f"candidate workflow references missing candidate agent(s): {', '.join(missing_refs)}")

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

    optimizer_meta_noise = _candidate_optimizer_meta_noise(bundle)
    if optimizer_meta_noise:
        locations = ", ".join(f"{item['resource']}:{item['path']}" for item in optimizer_meta_noise[:6])
        errors.append(f"candidate prompts must not include optimizer/ROI Lab meta instructions ({locations})")

    effective_changes = _candidate_effective_changes(study, bundle)
    if not effective_changes:
        validation_warnings.append(
            "Candidate has no effective workflow, prompt, runtime, or topology changes beyond copied resource names; treat it as a no-change control."
        )

    return {
        "valid": not errors,
        "errors": errors,
        "warnings": validation_warnings,
        "scope": "prompt_model_tool_topology_v1" if allow_topology_rewrite else "prompt_model_tool_v1",
        "topology_preserved": topology_preserved,
        "topology_rewrite_allowed": allow_topology_rewrite,
        "effective_change_count": len(effective_changes),
        "effective_changes": effective_changes[:80],
        "no_effective_changes": not bool(effective_changes),
        "optimizer_meta_noise": optimizer_meta_noise,
        "hybrid_gate": (
            "candidate requires approval, safe trials, human contract review, and output-equivalence checks before promotion"
            if allow_topology_rewrite
            else "candidate requires approval, safe trials, and contract-preserving outputs before promotion"
        ),
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


def _copy_metadata(
    manifest: dict[str, Any],
    name: str,
    namespace: str,
    study: dict[str, Any],
    *,
    allow_topology_rewrite: bool = False,
) -> dict[str, Any]:
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
            "kubesynapse.ai/topology-rewrite": "allowed" if allow_topology_rewrite else "preserved",
        }
    )
    metadata["labels"] = labels
    annotations = metadata.get("annotations") if isinstance(metadata.get("annotations"), dict) else {}
    annotations["kubesynapse.ai/optimization-mode"] = "roi-lab-v1"
    metadata["annotations"] = annotations
    return metadata


def _label_candidate_bundle(
    study: dict[str, Any],
    bundle: list[dict[str, Any]],
    *,
    allow_topology_rewrite: bool = False,
) -> list[dict[str, Any]]:
    labelled = _clone(bundle)
    namespace = str(study.get("namespace") or "default")
    for manifest in labelled:
        if not isinstance(manifest, dict):
            continue
        if str(manifest.get("kind") or "") in _ALLOWED_CANDIDATE_KINDS:
            manifest["apiVersion"] = f"{RESOURCE_GROUP}/{RESOURCE_VERSION}"
        metadata = manifest.get("metadata") if isinstance(manifest.get("metadata"), dict) else {}
        metadata = _clone(metadata)
        metadata["namespace"] = metadata.get("namespace") or namespace
        labels = metadata.get("labels") if isinstance(metadata.get("labels"), dict) else {}
        labels.update(
            {
                "kubesynapse.ai/optimization-study": str(study["id"]),
                "kubesynapse.ai/source-workflow": str(study["workflow_name"]),
                "kubesynapse.ai/candidate": "true",
                "kubesynapse.ai/topology-rewrite": "allowed" if allow_topology_rewrite else "preserved",
            }
        )
        metadata["labels"] = labels
        manifest["metadata"] = metadata
    return labelled


def _normalise_candidate_suffix(suffix: str) -> str:
    return re.sub(r"[^a-z0-9-]+", "-", suffix.lower()).strip("-") or "opt"


def _manifest_like_documents(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        documents: list[dict[str, Any]] = []
        for item in value:
            documents.extend(_manifest_like_documents(item))
        return documents

    if not isinstance(value, dict):
        return []

    if "kind" in value and ("apiVersion" in value or "metadata" in value or "spec" in value):
        return [value]

    documents: list[dict[str, Any]] = []
    for key in ("candidate_manifest_bundle", "manifest_bundle", "manifests", "resources", "items"):
        if key in value:
            documents.extend(_manifest_like_documents(value[key]))
    return documents


def _parse_manifest_text(text: str) -> list[dict[str, Any]]:
    documents: list[dict[str, Any]] = []
    stripped = text.strip()
    if not stripped:
        return documents

    with suppress(Exception):
        documents.extend(_manifest_like_documents(json.loads(stripped)))

    with suppress(Exception):
        for document in yaml.safe_load_all(stripped):
            documents.extend(_manifest_like_documents(document))

    return documents


def _extract_optimizer_manifest_documents(optimizer_output: str | None) -> list[dict[str, Any]]:
    if not optimizer_output or not optimizer_output.strip():
        return []

    documents: list[dict[str, Any]] = []
    for match in _FENCED_BLOCK_RE.finditer(optimizer_output):
        body = match.group("body")
        if "kind:" not in body and '"kind"' not in body and "manifest_bundle" not in body:
            continue
        documents.extend(_parse_manifest_text(body))

    if documents:
        return documents

    stripped = optimizer_output.strip()
    if stripped.startswith(("{", "[")) or "kind:" in stripped[:512] or "manifest_bundle" in stripped[:512]:
        documents.extend(_parse_manifest_text(stripped))
    return documents


def _find_optimizer_document(
    documents: list[dict[str, Any]],
    *,
    kind: str,
    source_name: str,
    suffixed_name: str,
) -> dict[str, Any] | None:
    for document in documents:
        if str(document.get("kind") or "") != kind:
            continue
        name = _manifest_name(document)
        if name in {source_name, suffixed_name}:
            return document
    return None


def _documents_of_kind(documents: list[dict[str, Any]], kind: str) -> list[dict[str, Any]]:
    return [document for document in documents if str(document.get("kind") or "") == kind]


def _candidate_bundle_from_source(
    study: dict[str, Any],
    suffix: str,
    optimizer_output: str | None,
    *,
    allow_topology_rewrite: bool = False,
) -> list[dict[str, Any]]:
    namespace = str(study.get("namespace") or "default")
    source = study.get("source_manifests") if isinstance(study.get("source_manifests"), dict) else {}
    source_workflow = source.get("workflow") if isinstance(source.get("workflow"), dict) else None
    if source_workflow is None:
        raise HTTPException(status_code=409, detail="Study has no source workflow manifest")

    suffix = _normalise_candidate_suffix(suffix)
    workflow_name = f"{study['workflow_name']}-{suffix}"
    source_agents = source.get("agents") if isinstance(source.get("agents"), dict) else {}
    agent_name_map = {name: f"{name}-{suffix}" for name in source_agents}

    bundle: list[dict[str, Any]] = []
    for source_name, source_agent in source_agents.items():
        if not isinstance(source_agent, dict):
            continue
        candidate_agent = _clone(source_agent)
        candidate_agent["metadata"] = _copy_metadata(
            candidate_agent,
            agent_name_map[source_name],
            namespace,
            study,
            allow_topology_rewrite=allow_topology_rewrite,
        )
        bundle.append(candidate_agent)

    candidate_workflow = _clone(source_workflow)
    candidate_workflow["metadata"] = _copy_metadata(
        candidate_workflow,
        workflow_name,
        namespace,
        study,
        allow_topology_rewrite=allow_topology_rewrite,
    )
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


def _candidate_step_execution_overrides(source_step: dict[str, Any], candidate_step: dict[str, Any]) -> dict[str, Any] | None:
    source_execution = source_step.get("execution") if isinstance(source_step.get("execution"), dict) else {}
    candidate_execution = candidate_step.get("execution") if isinstance(candidate_step.get("execution"), dict) else {}
    if not candidate_execution:
        return _clone(source_execution) if source_execution else None

    execution = _clone(source_execution)
    timeout_seconds = candidate_execution.get("timeoutSeconds")
    if isinstance(timeout_seconds, int) and timeout_seconds > 0:
        execution["timeoutSeconds"] = timeout_seconds
    return execution or None


def _normalise_candidate_workflow_contract(
    source_workflow: dict[str, Any],
    candidate_workflow: dict[str, Any],
    *,
    agent_name_map: dict[str, str],
) -> list[str]:
    source_spec = source_workflow.get("spec") if isinstance(source_workflow.get("spec"), dict) else {}
    candidate_steps = _workflow_steps(candidate_workflow)
    candidate_by_signature: dict[tuple[str, str], dict[str, Any]] = {}
    for candidate_step in candidate_steps:
        signature = (
            str(candidate_step.get("name") or ""),
            str(candidate_step.get("type") or candidate_step.get("stepType") or "agent"),
        )
        candidate_by_signature.setdefault(signature, candidate_step)

    warnings: list[str] = []
    source_signature = _step_signature(source_workflow)
    candidate_signature = _step_signature(candidate_workflow)
    if source_signature != candidate_signature:
        warnings.append(
            "Optimizer workflow topology was repaired from the source manifest; step names, order, and types were preserved."
        )

    repaired_spec = _clone(source_spec)
    repaired_steps: list[dict[str, Any]] = []
    for source_step in _workflow_steps(source_workflow):
        repaired_step = _clone(source_step)
        signature = (
            str(source_step.get("name") or ""),
            str(source_step.get("type") or source_step.get("stepType") or "agent"),
        )
        candidate_step = candidate_by_signature.get(signature)
        if candidate_step:
            candidate_prompt = str(candidate_step.get("prompt") or "").strip()
            if candidate_prompt:
                repaired_step["prompt"] = candidate_step["prompt"]
            execution = _candidate_step_execution_overrides(source_step, candidate_step)
            if execution is not None:
                repaired_step["execution"] = execution

        ref = str(repaired_step.get("agentRef") or "")
        if ref in agent_name_map:
            repaired_step["agentRef"] = agent_name_map[ref]
        repaired_steps.append(repaired_step)

    repaired_spec["steps"] = repaired_steps
    candidate_workflow["spec"] = repaired_spec
    return warnings


def _candidate_bundle_from_optimizer_output(
    study: dict[str, Any],
    suffix: str,
    optimizer_output: str | None,
    *,
    allow_topology_rewrite: bool = False,
) -> tuple[list[dict[str, Any]], list[str]] | None:
    documents = _extract_optimizer_manifest_documents(optimizer_output)
    if not documents:
        return None

    warnings: list[str] = []
    unsupported = sorted(
        {
            str(document.get("kind") or "<missing>")
            for document in documents
            if str(document.get("kind") or "") not in _ALLOWED_CANDIDATE_KINDS
        }
    )
    if unsupported:
        warnings.append(
            f"Optimizer output included unsupported kind(s) ignored during generated candidate creation: {', '.join(unsupported)}."
        )
    documents = [document for document in documents if str(document.get("kind") or "") in _ALLOWED_CANDIDATE_KINDS]

    namespace = str(study.get("namespace") or "default")
    source = study.get("source_manifests") if isinstance(study.get("source_manifests"), dict) else {}
    source_workflow = source.get("workflow") if isinstance(source.get("workflow"), dict) else None
    if source_workflow is None:
        raise HTTPException(status_code=409, detail="Study has no source workflow manifest")

    safe_suffix = _normalise_candidate_suffix(suffix)
    workflow_name = str(study.get("workflow_name") or _manifest_name(source_workflow))
    candidate_workflow_name = f"{workflow_name}-{safe_suffix}"

    bundle = _candidate_bundle_from_source(
        study,
        safe_suffix,
        optimizer_output=None,
        allow_topology_rewrite=allow_topology_rewrite,
    )
    candidate_workflow = _workflow_from_bundle(bundle)
    if candidate_workflow is None:
        raise HTTPException(status_code=409, detail="Study has no source workflow manifest")

    workflow_document = _find_optimizer_document(
        documents,
        kind="AgentWorkflow",
        source_name=workflow_name,
        suffixed_name=candidate_workflow_name,
    )
    workflow_documents = _documents_of_kind(documents, "AgentWorkflow")
    if workflow_document is None and len(workflow_documents) == 1:
        workflow_document = workflow_documents[0]
        warnings.append("Optimizer workflow manifest name was normalized to the copied candidate resource name.")
    elif workflow_document is None and workflow_documents:
        warnings.append("Optimizer output included workflow manifests, but none matched the source workflow; generated workflow from source.")
    elif workflow_document is None:
        warnings.append("Optimizer output omitted workflow manifest; generated copied workflow from source.")

    source_agents = source.get("agents") if isinstance(source.get("agents"), dict) else {}
    agent_name_map = {name: f"{name}-{safe_suffix}" for name in source_agents}
    agent_documents = _documents_of_kind(documents, "AIAgent")
    used_agent_document_names: set[str] = set()

    for source_agent_name, candidate_agent_name in agent_name_map.items():
        agent_document = _find_optimizer_document(
            documents,
            kind="AIAgent",
            source_name=source_agent_name,
            suffixed_name=candidate_agent_name,
        )
        if agent_document is None and not allow_topology_rewrite and len(source_agents) == 1 and len(agent_documents) == 1:
            agent_document = agent_documents[0]
            warnings.append("Optimizer agent manifest name was normalized to the copied candidate agent name.")
        if agent_document is None:
            continue
        used_agent_document_names.add(_manifest_name(agent_document))
        if _manifest_namespace(agent_document) != namespace:
            warnings.append(f"Optimizer agent manifest for '{source_agent_name}' was ignored because it left the study namespace.")
            continue
        agent_spec = agent_document.get("spec") if isinstance(agent_document.get("spec"), dict) else None
        if agent_spec is None:
            warnings.append(f"Optimizer agent manifest for '{source_agent_name}' was ignored because it omitted spec.")
            continue
        source_agent = source_agents.get(source_agent_name) if isinstance(source_agents, dict) else None
        source_spec = source_agent.get("spec") if isinstance(source_agent, dict) and isinstance(source_agent.get("spec"), dict) else {}
        merged_spec = _clone(source_spec)
        system_prompt = str(agent_spec.get("systemPrompt") or "").strip()
        if system_prompt:
            merged_spec["systemPrompt"] = agent_spec["systemPrompt"]
        source_model = _spec_model(source_agent)
        if source_model:
            merged_spec["model"] = source_model
        for manifest in bundle:
            if str(manifest.get("kind") or "") == "AIAgent" and _manifest_name(manifest) == candidate_agent_name:
                manifest["spec"] = merged_spec
                break

    if allow_topology_rewrite:
        source_models = {
            model
            for model in (_spec_model(agent) for agent in source_agents.values())
            if model
        } if isinstance(source_agents, dict) else set()
        default_model = next(iter(source_models)) if len(source_models) == 1 else None
        existing_agent_names = {_manifest_name(manifest) for manifest in bundle if str(manifest.get("kind") or "") == "AIAgent"}
        for agent_document in agent_documents:
            source_doc_name = _manifest_name(agent_document)
            if not source_doc_name or source_doc_name in used_agent_document_names:
                continue
            if _manifest_namespace(agent_document) != namespace:
                warnings.append(f"Optimizer topology agent manifest '{source_doc_name}' was ignored because it left the study namespace.")
                continue
            agent_spec = agent_document.get("spec") if isinstance(agent_document.get("spec"), dict) else None
            if agent_spec is None:
                warnings.append(f"Optimizer topology agent manifest '{source_doc_name}' was ignored because it omitted spec.")
                continue
            candidate_agent_name = source_doc_name if source_doc_name.endswith(f"-{safe_suffix}") else f"{source_doc_name}-{safe_suffix}"
            if candidate_agent_name in existing_agent_names:
                continue
            candidate_agent = _clone(agent_document)
            candidate_agent["metadata"] = _copy_metadata(
                candidate_agent,
                candidate_agent_name,
                namespace,
                study,
                allow_topology_rewrite=True,
            )
            candidate_spec = _clone(agent_spec)
            if default_model and not candidate_spec.get("model"):
                candidate_spec["model"] = default_model
            candidate_agent["spec"] = candidate_spec
            bundle.append(candidate_agent)
            existing_agent_names.add(candidate_agent_name)
            agent_name_map[source_doc_name] = candidate_agent_name

    if workflow_document is not None:
        if _manifest_namespace(workflow_document) != namespace:
            warnings.append("Optimizer workflow manifest was ignored because it left the study namespace.")
        else:
            workflow_spec = workflow_document.get("spec") if isinstance(workflow_document.get("spec"), dict) else None
            if workflow_spec is None:
                warnings.append("Optimizer workflow manifest was ignored because it omitted spec.")
            else:
                candidate_workflow["spec"] = _clone(workflow_spec)
                if allow_topology_rewrite:
                    for step in _workflow_steps(candidate_workflow):
                        ref = str(step.get("agentRef") or "")
                        if ref in agent_name_map:
                            step["agentRef"] = agent_name_map[ref]
                else:
                    warnings.extend(
                        _normalise_candidate_workflow_contract(
                            source_workflow,
                            candidate_workflow,
                            agent_name_map=agent_name_map,
                        )
                    )
    return bundle, warnings


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


def _trace_or_none(execution_id: str | None) -> dict[str, Any] | None:
    if not execution_id:
        return None
    try:
        return _get_trace(execution_id)
    except HTTPException:
        return None


def _trace_metric_snapshot(trace: dict[str, Any] | None) -> dict[str, Any] | None:
    if trace is None:
        return None
    return {
        "execution_id": trace.get("id"),
        "workflow_name": trace.get("workflow_name"),
        "run_id": trace.get("run_id"),
        "status": trace.get("status"),
        "duration_ms": _round(_as_float(trace.get("duration_ms")), 3),
        "tokens": _round(_as_float(trace.get("total_tokens")), 3),
        "cost_usd": _round(_as_float(trace.get("estimated_cost_usd") or trace.get("total_cost_usd")), 6),
        "llm_calls": _round(_as_float(trace.get("total_llm_calls")), 3),
        "tool_calls": _round(_as_float(trace.get("total_tool_calls")), 3),
        "started_at": trace.get("started_at"),
        "completed_at": trace.get("completed_at"),
    }


def _average_trial_deltas(trial_rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    keys = ("duration_saved_percent", "tokens_saved_percent", "tool_calls_saved_percent", "cost_saved_percent")
    usable = [
        row.get("deltas")
        for row in trial_rows
        if isinstance(row.get("deltas"), dict) and row.get("baseline") and row.get("candidate")
    ]
    if not usable:
        return None
    return {key: _round(sum(_as_float(row.get(key)) for row in usable) / len(usable), 1) for key in keys}


def _average_trial_snapshot_value(trial_rows: list[dict[str, Any]], side: str, key: str) -> float | None:
    values = [
        _as_float((row.get(side) or {}).get(key))
        for row in trial_rows
        if isinstance(row.get(side), dict) and (row.get(side) or {}).get(key) is not None
    ]
    if not values:
        return None
    return _round(sum(values) / len(values), 6 if key == "cost_usd" else 3)


def _estimated_delta(candidate: dict[str, Any] | None, key: str) -> float | None:
    expected = candidate.get("expected_savings") if isinstance(candidate, dict) else None
    if not isinstance(expected, dict):
        return None
    if expected.get(key) is None:
        return None
    return _round(_as_float(expected.get(key)), 1)


def _normalise_expected_savings(expected: dict[str, Any] | None, validation: dict[str, Any]) -> dict[str, Any]:
    candidate_expected = _clone(expected) if isinstance(expected, dict) else {}
    if validation.get("no_effective_changes"):
        return {
            "duration_saved_percent": 0,
            "tokens_saved_percent": 0,
            "tool_calls_saved_percent": 0,
            "cost_saved_percent": 0,
            "confidence": "control",
            "reason": "No effective manifest changes were detected; this candidate is a control copy until the optimizer produces a real diff.",
        }
    return candidate_expected


def _comparison_scorecard(
    *,
    roi: dict[str, Any],
    trial_rows: list[dict[str, Any]],
    candidate: dict[str, Any] | None,
    headline: dict[str, Any],
) -> dict[str, Any]:
    trial_deltas = _average_trial_deltas(trial_rows)
    actual_deltas = trial_deltas or (roi.get("deltas") if isinstance(roi.get("deltas"), dict) else {})
    metric_source = "paired_trials" if trial_deltas is not None else "study_rollup"
    baseline_metrics = roi.get("baseline_metrics") if isinstance(roi.get("baseline_metrics"), dict) else {}
    candidate_metrics = roi.get("candidate_metrics") if isinstance(roi.get("candidate_metrics"), dict) else {}

    def value(side: str, snapshot_key: str, rollup_key: str, fallback_rollup_key: str | None = None) -> float:
        from_trials = _average_trial_snapshot_value(trial_rows, side, snapshot_key)
        if from_trials is not None:
            return from_trials
        rollup = baseline_metrics if side == "baseline" else candidate_metrics
        return _round(_as_float(rollup.get(rollup_key) if rollup.get(rollup_key) is not None else rollup.get(fallback_rollup_key or rollup_key)), 6 if snapshot_key == "cost_usd" else 3)

    metric_specs = [
        ("duration_saved_percent", "Wall-clock", "duration_ms", "duration_per_successful_run_ms", "avg_duration_ms", "ms per successful run"),
        ("tokens_saved_percent", "Tokens", "tokens", "tokens_per_successful_run", "avg_tokens", "tokens per successful run"),
        ("tool_calls_saved_percent", "Tool calls", "tool_calls", "avg_tool_calls", "avg_tool_calls", "calls per run"),
        ("cost_saved_percent", "Cost", "cost_usd", "cost_per_successful_run", "avg_cost_usd", "USD per successful run"),
    ]
    metrics = [
        {
            "key": key,
            "label": label,
            "unit": unit,
            "baseline_value": value("baseline", snapshot_key, rollup_key, fallback_key),
            "candidate_value": value("candidate", snapshot_key, rollup_key, fallback_key),
            "actual_delta_percent": _round(_as_float(actual_deltas.get(key)), 1),
            "estimated_delta_percent": _estimated_delta(candidate, key),
            "value_kind": snapshot_key,
            "source": metric_source,
        }
        for key, label, snapshot_key, rollup_key, fallback_key, unit in metric_specs
    ]

    regression_metrics = [metric for metric in metrics if _as_float(metric.get("actual_delta_percent")) < 0]
    safe_trials_remaining = int(headline.get("safe_trials_remaining") or 0)
    if roi.get("verified") is True:
        next_action = "promote"
    elif regression_metrics:
        next_action = "review_regressions"
    elif candidate is None:
        next_action = "generate_candidate"
    elif int(roi.get("passing_trial_count") or 0) == 0:
        next_action = "run_candidate"
    elif safe_trials_remaining > 0:
        next_action = "run_more_trials"
    else:
        next_action = "review_for_promotion"

    return {
        "summary": headline.get("summary") or "Run a candidate trial to measure ROI",
        "metric_source": metric_source,
        "proof_status": roi.get("proof_status") or "pending_trials",
        "verified": roi.get("verified") is True,
        "trial_count": int(roi.get("trial_count") or 0),
        "safe_trial_count": int(roi.get("passing_trial_count") or 0),
        "safe_trials_remaining": safe_trials_remaining,
        "next_action": next_action,
        "metrics": metrics,
    }


def _roi_headline(roi: dict[str, Any], trial_rows: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    trial_deltas = _average_trial_deltas(trial_rows or [])
    deltas = trial_deltas or (roi.get("deltas") if isinstance(roi.get("deltas"), dict) else {})
    labels = [
        ("duration_saved_percent", "time"),
        ("tokens_saved_percent", "tokens"),
        ("tool_calls_saved_percent", "tool calls"),
        ("cost_saved_percent", "cost"),
    ]
    values = {key: _as_float(deltas.get(key)) for key, _label in labels}
    positive = [(key, label, values[key]) for key, label in labels if values[key] > 0]
    regressions = [(key, label, values[key]) for key, label in labels if values[key] < 0]
    primary = positive[0] if positive else max(
        [(key, label, values[key]) for key, label in labels],
        key=lambda item: item[2],
        default=("duration_saved_percent", "time", 0.0),
    )
    summary_parts = [f"{value:.1f}% {label}" for _key, label, value in positive[:3]]
    if summary_parts:
        summary = f"Saved {' / '.join(summary_parts)}"
    elif regressions:
        summary = "Candidate has regressions; review before more trials"
    else:
        summary = "Run a candidate trial to measure ROI"
    passing_trials = int(roi.get("passing_trial_count") or 0)
    trial_count = int(roi.get("trial_count") or 0)
    proof_gate = roi.get("proof_gate") if isinstance(roi.get("proof_gate"), dict) else {}
    minimum_safe_trials = int(proof_gate.get("minimum_safe_trials") or 1)
    if trial_count:
        summary = f"{summary} across {passing_trials} safe trial{'s' if passing_trials != 1 else ''}"
    return {
        "summary": summary,
        "primary_saving_key": primary[0],
        "primary_saving_label": primary[1],
        "primary_saving_percent": _round(primary[2], 1),
        "regression_count": len(regressions),
        "safe_trials_remaining": max(minimum_safe_trials - passing_trials, 0),
        "metric_source": "paired_trials" if trial_deltas is not None else "study_rollup",
    }


def _comparison_delta(
    baseline: dict[str, Any] | None,
    candidate: dict[str, Any] | None,
    *,
    duration_key: str = "avg_duration_ms",
    tokens_key: str = "avg_tokens",
    cost_key: str = "avg_cost_usd",
    tool_key: str = "avg_tool_calls",
) -> dict[str, Any]:
    if not baseline or not candidate:
        return {
            "duration_saved_percent": 0.0,
            "tokens_saved_percent": 0.0,
            "cost_saved_percent": 0.0,
            "tool_calls_saved_percent": 0.0,
        }
    return {
        "duration_saved_percent": _saved_percent(baseline.get(duration_key), candidate.get(duration_key)),
        "tokens_saved_percent": _saved_percent(baseline.get(tokens_key), candidate.get(tokens_key)),
        "cost_saved_percent": _saved_percent(baseline.get(cost_key), candidate.get(cost_key)),
        "tool_calls_saved_percent": _saved_percent(baseline.get(tool_key), candidate.get(tool_key)),
    }


def _rollup_by_name(rows: list[dict[str, Any]], key: str) -> dict[str, dict[str, Any]]:
    return {str(row.get(key) or ""): row for row in rows if str(row.get(key) or "")}


def _step_comparison_rows(
    baseline_traces: list[dict[str, Any]],
    candidate_traces: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    baseline_by_step = _rollup_by_name(_step_rollups(baseline_traces), "step_name")
    candidate_by_step = _rollup_by_name(_step_rollups(candidate_traces), "step_name")
    rows: list[dict[str, Any]] = []
    for step_name in sorted(set(baseline_by_step) | set(candidate_by_step)):
        baseline = baseline_by_step.get(step_name)
        candidate = candidate_by_step.get(step_name)
        rows.append(
            {
                "step_name": step_name,
                "baseline": baseline,
                "candidate": candidate,
                "deltas": _comparison_delta(baseline, candidate),
            }
        )
    return sorted(
        rows,
        key=lambda item: max(
            _as_float((item.get("baseline") or {}).get("avg_duration_ms")),
            _as_float((item.get("candidate") or {}).get("avg_duration_ms")),
        ),
        reverse=True,
    )


def _tool_comparison_rows(
    baseline_traces: list[dict[str, Any]],
    candidate_traces: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    baseline_by_tool = _rollup_by_name(_tool_rollups(baseline_traces), "tool_name")
    candidate_by_tool = _rollup_by_name(_tool_rollups(candidate_traces), "tool_name")
    baseline_count = max(len(baseline_traces), 1)
    candidate_count = max(len(candidate_traces), 1)
    rows: list[dict[str, Any]] = []
    for tool_name in sorted(set(baseline_by_tool) | set(candidate_by_tool)):
        baseline = _clone(baseline_by_tool.get(tool_name) or {"tool_name": tool_name, "calls": 0, "avg_duration_ms": 0.0, "repeated_arg_groups": 0, "affected_steps": []})
        candidate = _clone(candidate_by_tool.get(tool_name) or {"tool_name": tool_name, "calls": 0, "avg_duration_ms": 0.0, "repeated_arg_groups": 0, "affected_steps": []})
        baseline["calls_per_run"] = _round(_as_float(baseline.get("calls")) / baseline_count, 3)
        candidate["calls_per_run"] = _round(_as_float(candidate.get("calls")) / candidate_count, 3)
        rows.append(
            {
                "tool_name": tool_name,
                "baseline": baseline,
                "candidate": candidate,
                "deltas": {
                    "calls_saved_percent": _saved_percent(baseline.get("calls_per_run"), candidate.get("calls_per_run")),
                    "duration_saved_percent": _saved_percent(baseline.get("avg_duration_ms"), candidate.get("avg_duration_ms")),
                    "repeated_arg_groups_saved_percent": _saved_percent(baseline.get("repeated_arg_groups"), candidate.get("repeated_arg_groups")),
                },
            }
        )
    return sorted(rows, key=lambda item: _as_float((item.get("baseline") or {}).get("calls_per_run")), reverse=True)


def _trial_comparison_rows(
    trials: list[dict[str, Any]],
    trace_by_id: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for trial in trials:
        baseline_id = str(trial.get("baseline_execution_id") or "")
        candidate_id = str(trial.get("result_execution_id") or "")
        baseline = trace_by_id.get(baseline_id) if trace_by_id is not None else _trace_or_none(baseline_id)
        candidate = trace_by_id.get(candidate_id) if trace_by_id is not None else _trace_or_none(candidate_id)
        metrics_delta = trial.get("metrics_delta") if isinstance(trial.get("metrics_delta"), dict) else {}
        candidate_run = metrics_delta.get("candidate_run") if isinstance(metrics_delta.get("candidate_run"), dict) else {}
        rows.append(
            {
                "id": trial.get("id"),
                "status": trial.get("status"),
                "quality_status": trial.get("quality_status"),
                "notes": trial.get("notes"),
                "created_at": trial.get("created_at"),
                "baseline": _trace_metric_snapshot(baseline),
                "candidate": _trace_metric_snapshot(candidate),
                "candidate_run": candidate_run,
                "deltas": _metrics_delta(baseline, candidate),
            }
        )
    return rows


def _comparison_manifest(manifest: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(manifest, dict):
        return {}
    prepared = _clone(manifest)
    prepared.pop("status", None)
    metadata = prepared.get("metadata") if isinstance(prepared.get("metadata"), dict) else {}
    for key in ("creationTimestamp", "finalizers", "generation", "managedFields", "resourceVersion", "uid"):
        metadata.pop(key, None)
    annotations = metadata.get("annotations") if isinstance(metadata.get("annotations"), dict) else {}
    for key in (
        "kubectl.kubernetes.io/last-applied-configuration",
        "kopf.zalando.org/last-handled-configuration",
    ):
        annotations.pop(key, None)
    if annotations:
        metadata["annotations"] = annotations
    else:
        metadata.pop("annotations", None)
    prepared["metadata"] = metadata
    return _redact(prepared)


def _manifest_yaml(manifest: dict[str, Any]) -> str:
    if not manifest:
        return ""
    return yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True).strip()


def _manifest_diff_rows(source_yaml: str, candidate_yaml: str, limit: int = 600) -> list[dict[str, Any]]:
    source_lines = source_yaml.splitlines()
    candidate_lines = candidate_yaml.splitlines()
    rows: list[dict[str, Any]] = []
    matcher = difflib.SequenceMatcher(a=source_lines, b=candidate_lines, autojunk=False)
    for tag, source_start, source_end, candidate_start, candidate_end in matcher.get_opcodes():
        span = max(source_end - source_start, candidate_end - candidate_start)
        for offset in range(span):
            source_index = source_start + offset
            candidate_index = candidate_start + offset
            rows.append(
                {
                    "type": tag,
                    "source_line_no": source_index + 1 if source_index < source_end else None,
                    "candidate_line_no": candidate_index + 1 if candidate_index < candidate_end else None,
                    "source": source_lines[source_index] if source_index < source_end else "",
                    "candidate": candidate_lines[candidate_index] if candidate_index < candidate_end else "",
                }
            )
            if len(rows) >= limit:
                rows.append(
                    {
                        "type": "truncated",
                        "source_line_no": None,
                        "candidate_line_no": None,
                        "source": f"Diff truncated after {limit} rows.",
                        "candidate": f"Diff truncated after {limit} rows.",
                    }
                )
                return rows
    return rows


def _diff_paths(left: Any, right: Any, path: str = "") -> list[str]:
    if left == right:
        return []
    if isinstance(left, dict) and isinstance(right, dict):
        paths: list[str] = []
        for key in sorted(set(left) | set(right)):
            child_path = f"{path}.{key}" if path else str(key)
            paths.extend(_diff_paths(left.get(key), right.get(key), child_path))
        return paths
    if isinstance(left, list) and isinstance(right, list):
        paths = []
        for index in range(max(len(left), len(right))):
            child_path = f"{path}[{index}]" if path else f"[{index}]"
            left_item = left[index] if index < len(left) else None
            right_item = right[index] if index < len(right) else None
            paths.extend(_diff_paths(left_item, right_item, child_path))
        return paths
    return [path or "$"]


def _manifest_highlights(
    *,
    kind: str,
    source: dict[str, Any],
    candidate: dict[str, Any],
    changed_paths: list[str],
) -> list[str]:
    highlights: list[str] = []
    if kind == "AgentWorkflow":
        source_steps = ((source.get("spec") or {}).get("steps") or []) if isinstance(source.get("spec"), dict) else []
        candidate_steps = ((candidate.get("spec") or {}).get("steps") or []) if isinstance(candidate.get("spec"), dict) else []
        for index, step in enumerate(source_steps):
            if not isinstance(step, dict) or index >= len(candidate_steps) or not isinstance(candidate_steps[index], dict):
                continue
            step_name = str(step.get("name") or f"step-{index + 1}")
            candidate_step = candidate_steps[index]
            if step.get("prompt") != candidate_step.get("prompt"):
                highlights.append(f"Step prompt changed: {step_name}")
            if step.get("agentRef") != candidate_step.get("agentRef"):
                highlights.append(f"Step agent reference rewired: {step_name}")
        if _step_signature(source) == _step_signature(candidate):
            highlights.append("Step order and output topology preserved")
    elif kind == "AIAgent":
        source_spec = source.get("spec") if isinstance(source.get("spec"), dict) else {}
        candidate_spec = candidate.get("spec") if isinstance(candidate.get("spec"), dict) else {}
        if source_spec.get("systemPrompt") != candidate_spec.get("systemPrompt"):
            highlights.append("Agent system prompt changed")
        if _spec_model(source) == _spec_model(candidate) and _spec_model(source):
            highlights.append(f"Model preserved: {_spec_model(source)}")
    if not highlights and changed_paths:
        highlights.append(f"{len(changed_paths)} manifest field changes")
    return highlights[:8]


def _manifest_diff_section(
    *,
    section_id: str,
    title: str,
    source: dict[str, Any] | None,
    candidate: dict[str, Any] | None,
) -> dict[str, Any]:
    source_prepared = _comparison_manifest(source)
    candidate_prepared = _comparison_manifest(candidate)
    changed_paths = _diff_paths(source_prepared, candidate_prepared)[:120]
    kind = str((candidate_prepared or source_prepared).get("kind") or "Resource")
    return {
        "id": section_id,
        "title": title,
        "kind": kind,
        "source_name": _manifest_name(source or {}),
        "candidate_name": _manifest_name(candidate or {}),
        "changed": bool(changed_paths),
        "change_count": len(changed_paths),
        "changed_paths": changed_paths,
        "highlights": _manifest_highlights(
            kind=kind,
            source=source_prepared,
            candidate=candidate_prepared,
            changed_paths=changed_paths,
        ),
        "source_yaml": _manifest_yaml(source_prepared),
        "candidate_yaml": _manifest_yaml(candidate_prepared),
        "diff_rows": _manifest_diff_rows(_manifest_yaml(source_prepared), _manifest_yaml(candidate_prepared)),
    }


def _manifest_comparison(study: dict[str, Any], candidate: dict[str, Any] | None) -> dict[str, Any]:
    source = study.get("source_manifests") if isinstance(study.get("source_manifests"), dict) else {}
    source_workflow = source.get("workflow") if isinstance(source.get("workflow"), dict) else {}
    bundle = candidate.get("manifest_bundle") if isinstance(candidate, dict) and isinstance(candidate.get("manifest_bundle"), list) else []
    candidate_workflow = _workflow_from_bundle(bundle) or {}
    sections: list[dict[str, Any]] = []
    sections.append(
        _manifest_diff_section(
            section_id="workflow",
            title="Workflow definition",
            source=source_workflow,
            candidate=candidate_workflow,
        )
    )

    source_agents = source.get("agents") if isinstance(source.get("agents"), dict) else {}
    candidate_agents = {
        _manifest_name(manifest): manifest
        for manifest in bundle
        if isinstance(manifest, dict) and str(manifest.get("kind") or "") == "AIAgent"
    }
    for source_agent_name, candidate_agent_name in _candidate_agent_ref_map(source_workflow, candidate_workflow).items():
        source_agent = source_agents.get(source_agent_name) if isinstance(source_agents, dict) else None
        candidate_agent = candidate_agents.get(candidate_agent_name)
        sections.append(
            _manifest_diff_section(
                section_id=f"agent:{source_agent_name}",
                title=f"Agent: {source_agent_name}",
                source=source_agent,
                candidate=candidate_agent,
            )
        )

    return {
        "topology_preserved": _step_signature(source_workflow) == _step_signature(candidate_workflow),
        "resource_count": {"baseline": len(_source_bundle_from_study(study)), "candidate": len(bundle)},
        "sections": sections,
    }


def _select_comparison_candidate(study_id: str, candidate_id: str | None) -> dict[str, Any] | None:
    if candidate_id:
        candidate = optimization_store.get_candidate(candidate_id)
        if candidate is None or str(candidate.get("study_id")) != study_id:
            raise HTTPException(status_code=404, detail="Optimization candidate not found")
        return candidate
    candidates = optimization_store.list_candidates(study_id)
    if not candidates:
        return None
    return candidates[-1]


def _comparison_payload(
    study: dict[str, Any],
    candidate: dict[str, Any] | None,
    roi: dict[str, Any],
) -> dict[str, Any]:
    candidate_id = str(candidate.get("id")) if isinstance(candidate, dict) else None
    trials = optimization_store.list_trials(study["id"], candidate_id=candidate_id)
    trace_ids = {
        str(execution_id)
        for execution_id in study.get("baseline_execution_ids", [])
        if str(execution_id or "")
    }
    for trial in trials:
        if trial.get("baseline_execution_id"):
            trace_ids.add(str(trial.get("baseline_execution_id")))
        if trial.get("result_execution_id"):
            trace_ids.add(str(trial.get("result_execution_id")))
    trace_by_id = {
        execution_id: trace
        for execution_id in trace_ids
        if (trace := _trace_or_none(execution_id)) is not None
    }
    baseline_traces = [
        trace_by_id[str(execution_id)]
        for execution_id in study.get("baseline_execution_ids", [])
        if str(execution_id) in trace_by_id
    ]
    passing_trials = [
        trial for trial in trials
        if trial.get("result_execution_id") and str(trial.get("quality_status") or "").lower() in _PASSING_QUALITY_STATES
    ]
    candidate_traces = [
        trace_by_id[str(trial.get("result_execution_id"))]
        for trial in passing_trials
        if str(trial.get("result_execution_id")) in trace_by_id
    ]
    trial_rows = _trial_comparison_rows(trials, trace_by_id)
    headline = _roi_headline(roi, trial_rows)
    return {
        "headline": headline,
        "scorecard": _comparison_scorecard(roi=roi, trial_rows=trial_rows, candidate=candidate, headline=headline),
        "trials": trial_rows,
        "steps": _step_comparison_rows(baseline_traces, candidate_traces),
        "tools": _tool_comparison_rows(baseline_traces, candidate_traces),
        "manifest_diff": _manifest_comparison(study, candidate),
    }


def _compute_roi(study: dict[str, Any], candidate_id: str | None = None, *, sync_trials: bool = True) -> dict[str, Any]:
    if sync_trials:
        _sync_candidate_trial_results(study, candidate_id=candidate_id)
    trials = optimization_store.list_trials(study["id"], candidate_id=candidate_id)
    passing_trials = [
        trial for trial in trials
        if trial.get("result_execution_id") and str(trial.get("quality_status") or "").lower() in _PASSING_QUALITY_STATES
    ]
    candidate_traces = [_get_trace(str(trial["result_execution_id"])) for trial in passing_trials]
    candidate_metrics = _aggregate_metrics(candidate_traces)
    baseline_metrics = study.get("baseline_metrics") or {}
    proof_gate = study.get("proof_gate") if isinstance(study.get("proof_gate"), dict) else {}
    minimum_safe_trials = int(proof_gate.get("minimum_safe_trials") or 1)
    rollup_deltas = {
        "duration_saved_percent": _saved_percent(baseline_metrics.get("avg_duration_ms"), candidate_metrics.get("avg_duration_ms")),
        "tokens_saved_percent": _saved_percent(baseline_metrics.get("avg_tokens"), candidate_metrics.get("avg_tokens")),
        "cost_saved_percent": _saved_percent(baseline_metrics.get("avg_cost_usd"), candidate_metrics.get("avg_cost_usd")),
        "tool_calls_saved_percent": _saved_percent(baseline_metrics.get("avg_tool_calls"), candidate_metrics.get("avg_tool_calls")),
    }
    trial_rows = _trial_comparison_rows(trials)
    paired_trial_deltas = _average_trial_deltas(trial_rows)
    deltas = paired_trial_deltas or rollup_deltas
    max_regression = abs(float(proof_gate.get("max_metric_regression_percent") or 5))
    regression_deltas = {
        key: value
        for key, value in deltas.items()
        if _as_float(value) < -max_regression
    }
    verified = bool(
        len(passing_trials) >= minimum_safe_trials
        and candidate_metrics["sample_count"] > 0
        and candidate_metrics["success_rate"] >= float(baseline_metrics.get("success_rate") or 0)
        and not regression_deltas
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
    if verified:
        proof_status = "verified"
    elif candidate_metrics["sample_count"] == 0:
        proof_status = "pending_trials"
    elif regression_deltas:
        proof_status = "regression"
    elif len(passing_trials) < minimum_safe_trials:
        proof_status = "needs_more_trials"
    else:
        proof_status = "needs_review"
    return {
        "study_id": study["id"],
        "candidate_id": candidate_id,
        "proof_status": proof_status,
        "verified": verified,
        "proof_gate": proof_gate,
        "baseline_metrics": baseline_metrics,
        "candidate_metrics": candidate_metrics,
        "deltas": deltas,
        "rollup_deltas": rollup_deltas,
        "metric_source": "paired_trials" if paired_trial_deltas is not None else "study_rollup",
        "regression_deltas": regression_deltas,
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


def _apply_manifest_bundle(
    bundle: list[dict[str, Any]],
    namespace: str,
    *,
    include_workflows: bool = True,
) -> list[dict[str, str]]:
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
        if kind == "AgentWorkflow" and not include_workflows:
            results.append({"kind": kind, "name": name, "status": "deferred_until_trial"})
            continue
        body = _clone(manifest)
        body["apiVersion"] = f"{RESOURCE_GROUP}/{RESOURCE_VERSION}"
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


def _candidate_workflow_manifest(bundle: list[dict[str, Any]], workflow_name: str) -> dict[str, Any]:
    for manifest in bundle:
        if str(manifest.get("kind") or "") != "AgentWorkflow":
            continue
        if _manifest_name(manifest) == workflow_name:
            return _clone(manifest)
    raise HTTPException(status_code=409, detail=f"Candidate workflow manifest '{workflow_name}' is not available")


def _candidate_agent_names(bundle: list[dict[str, Any]]) -> list[str]:
    names: list[str] = []
    for manifest in bundle:
        if str(manifest.get("kind") or "") != "AIAgent":
            continue
        name = _manifest_name(manifest)
        if name:
            names.append(name)
    return names


def _condition_true(resource: dict[str, Any], *condition_types: str) -> bool:
    status = resource.get("status") if isinstance(resource.get("status"), dict) else {}
    wanted = {condition_type.lower() for condition_type in condition_types}
    for condition in status.get("conditions") or []:
        if not isinstance(condition, dict):
            continue
        if str(condition.get("type") or "").lower() in wanted and str(condition.get("status") or "").lower() == "true":
            return True
    return False


def _sandbox_pod_ready(core_api: Any, namespace: str, agent_name: str) -> bool | None:
    try:
        pod = core_api.read_namespaced_pod(name=f"{agent_name}-sandbox-0", namespace=namespace)
    except Exception as exc:
        if getattr(exc, "status", None) == 404:
            return None
        raise
    statuses = getattr(getattr(pod, "status", None), "container_statuses", None) or []
    if not statuses:
        return False
    return all(bool(getattr(item, "ready", False)) for item in statuses)


def _wait_for_candidate_agents_ready(
    bundle: list[dict[str, Any]],
    namespace: str,
    *,
    timeout_seconds: float = 90.0,
    poll_seconds: float = 2.0,
) -> list[dict[str, str]]:
    names = _candidate_agent_names(bundle)
    if not names:
        return []

    from kubernetes import client

    custom_api = client.CustomObjectsApi()
    core_api = client.CoreV1Api()
    pending = set(names)
    readiness: dict[str, str] = dict.fromkeys(names, "pending")
    deadline = time.monotonic() + timeout_seconds

    while pending and time.monotonic() < deadline:
        for name in list(pending):
            try:
                resource = custom_api.get_namespaced_custom_object(
                    group=RESOURCE_GROUP,
                    version=RESOURCE_VERSION,
                    namespace=namespace,
                    plural="aiagents",
                    name=name,
                )
            except Exception as exc:
                if getattr(exc, "status", None) == 404:
                    readiness[name] = "waiting_for_resource"
                    continue
                raise HTTPException(status_code=502, detail=f"Failed to read candidate agent '{name}'") from exc

            resource = resource if isinstance(resource, dict) else {}
            status = resource.get("status") if isinstance(resource.get("status"), dict) else {}
            phase = str(status.get("phase") or "").lower()
            cr_ready = phase == "running" or _condition_true(resource, "Ready", "RuntimeHealthy")
            try:
                pod_ready = _sandbox_pod_ready(core_api, namespace, name)
            except Exception as exc:
                raise HTTPException(status_code=502, detail=f"Failed to inspect candidate agent pod '{name}'") from exc

            if cr_ready and pod_ready is not False:
                readiness[name] = "ready"
                pending.remove(name)
            elif pod_ready is False:
                readiness[name] = "waiting_for_pod"
            else:
                readiness[name] = phase or "waiting_for_runtime"

        if pending:
            time.sleep(poll_seconds)

    if pending:
        pending_list = ", ".join(sorted(pending))
        raise HTTPException(
            status_code=409,
            detail=f"Candidate agent runtime did not become ready before trial launch: {pending_list}",
        )

    return [{"name": name, "status": readiness[name]} for name in names]


def _wait_for_workflow_run(
    api: Any,
    *,
    workflow_name: str,
    namespace: str,
    generation: int | None,
    previous_run_id: str | None = None,
    timeout_seconds: float = 45.0,
    poll_seconds: float = 1.0,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    last_resource: dict[str, Any] = {}
    while time.monotonic() < deadline:
        resource = api.get_namespaced_custom_object(
            group=RESOURCE_GROUP,
            version=RESOURCE_VERSION,
            namespace=namespace,
            plural="agentworkflows",
            name=workflow_name,
        )
        last_resource = resource if isinstance(resource, dict) else {}
        status = last_resource.get("status") if isinstance(last_resource.get("status"), dict) else {}
        metadata = last_resource.get("metadata") if isinstance(last_resource.get("metadata"), dict) else {}
        observed = int(status.get("observedGeneration", 0) or 0)
        current_generation = int(metadata.get("generation", 0) or 0)
        run_id = str(status.get("runId") or "").strip()
        phase = str(status.get("phase") or "").strip()
        generation_ready = generation is None or observed == int(generation)
        run_ready = bool(run_id) and run_id != (previous_run_id or "")
        if generation_ready and run_ready and phase in {"queued", "running", "waiting-approval", "completed", "failed", "cancelled"}:
            return last_resource
        if generation is None and run_ready:
            return last_resource
        if current_generation and generation is not None and current_generation > int(generation):
            generation = current_generation
        time.sleep(poll_seconds)
    return last_resource


def _trigger_candidate_workflow(
    bundle: list[dict[str, Any]],
    workflow_name: str,
    namespace: str,
    input_text: str | None,
) -> dict[str, Any]:
    from kubernetes import client

    api = client.CustomObjectsApi()
    manifest = _candidate_workflow_manifest(bundle, workflow_name)
    manifest["apiVersion"] = f"{RESOURCE_GROUP}/{RESOURCE_VERSION}"
    manifest.setdefault("kind", RESOURCE_KIND_BY_PLURAL["agentworkflows"])
    metadata = manifest.setdefault("metadata", {})
    metadata["name"] = workflow_name
    metadata["namespace"] = namespace
    spec = manifest.get("spec") if isinstance(manifest.get("spec"), dict) else {}
    new_input = input_text if input_text is not None else str(spec.get("input") or "")
    manifest["spec"] = {**spec, "input": new_input}

    previous_run_id: str | None = None
    try:
        current = api.get_namespaced_custom_object(
            group=RESOURCE_GROUP,
            version=RESOURCE_VERSION,
            namespace=namespace,
            plural="agentworkflows",
            name=workflow_name,
        )
    except Exception as exc:
        status = getattr(exc, "status", None)
        if status == 404:
            try:
                created = api.create_namespaced_custom_object(
                    group=RESOURCE_GROUP,
                    version=RESOURCE_VERSION,
                    namespace=namespace,
                    plural="agentworkflows",
                    body=manifest,
                )
                created = created if isinstance(created, dict) else {}
                created_generation = (created.get("metadata") or {}).get("generation")
                refreshed = _wait_for_workflow_run(
                    api,
                    workflow_name=workflow_name,
                    namespace=namespace,
                    generation=int(created_generation) if created_generation is not None else None,
                    previous_run_id=None,
                )
            except Exception as create_exc:
                raise HTTPException(status_code=502, detail=f"Failed to create candidate workflow '{workflow_name}'") from create_exc
        else:
            raise HTTPException(status_code=502, detail=f"Failed to read candidate workflow '{workflow_name}'") from exc
    else:
        current = current if isinstance(current, dict) else {}
        current_status = current.get("status") if isinstance(current.get("status"), dict) else {}
        previous_run_id = str(current_status.get("runId") or "").strip() or None
        current_metadata = current.get("metadata") if isinstance(current.get("metadata"), dict) else {}
        metadata["resourceVersion"] = current_metadata.get("resourceVersion")
        try:
            updated = api.replace_namespaced_custom_object(
                group=RESOURCE_GROUP,
                version=RESOURCE_VERSION,
                namespace=namespace,
                plural="agentworkflows",
                name=workflow_name,
                body=manifest,
            )
            updated = updated if isinstance(updated, dict) else {}
            updated_generation = (updated.get("metadata") or {}).get("generation")
            refreshed = _wait_for_workflow_run(
                api,
                workflow_name=workflow_name,
                namespace=namespace,
                generation=int(updated_generation) if updated_generation is not None else None,
                previous_run_id=previous_run_id,
            )
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Failed to trigger candidate workflow '{workflow_name}'") from exc

    refreshed = refreshed if isinstance(refreshed, dict) else {}
    status = refreshed.get("status") if isinstance(refreshed.get("status"), dict) else {}
    metadata = refreshed.get("metadata") if isinstance(refreshed.get("metadata"), dict) else {}
    return {
        "workflow_name": workflow_name,
        "namespace": namespace,
        "run_id": str(status.get("runId") or "").strip() or None,
        "phase": str(status.get("phase") or "pending"),
        "generation": metadata.get("generation"),
        "input": new_input,
    }


def _sync_candidate_trial_results(study: dict[str, Any], candidate_id: str | None = None) -> list[dict[str, Any]]:
    synced: list[dict[str, Any]] = []
    candidates = optimization_store.list_candidates(str(study["id"]))
    for candidate in candidates:
        if candidate_id and str(candidate.get("id")) != str(candidate_id):
            continue
        trials = optimization_store.list_trials(str(study["id"]), candidate_id=str(candidate["id"]))
        for trial in trials:
            if trial.get("result_execution_id"):
                continue
            metrics_delta = trial.get("metrics_delta") if isinstance(trial.get("metrics_delta"), dict) else {}
            candidate_run = metrics_delta.get("candidate_run") if isinstance(metrics_delta.get("candidate_run"), dict) else {}
            workflow_name = str(candidate_run.get("workflow_name") or candidate.get("candidate_workflow_name") or "")
            if not workflow_name:
                continue
            run_id = str(candidate_run.get("run_id") or "").strip() or None
            try:
                summaries = trace_store.list_executions(
                    namespace=str(candidate["namespace"]),
                    workflow_name=workflow_name,
                    run_id=run_id,
                    limit=1,
                )
            except Exception:
                logger.debug(
                    "Skipping candidate trial sync lookup for workflow %s",
                    workflow_name,
                    exc_info=True,
                )
                continue
            if not summaries:
                continue
            summary = summaries[0] if isinstance(summaries[0], dict) else {}
            execution_id = str(summary.get("id") or "").strip()
            status = str(summary.get("status") or "").lower()
            if not execution_id or status not in {"completed", "failed", "cancelled"}:
                continue
            baseline = _get_trace(str(trial["baseline_execution_id"]))
            result = _get_trace(execution_id)
            quality_status = "machine_passed" if status == "completed" else "failed"
            merged_delta = {
                **metrics_delta,
                **_metrics_delta(baseline, result),
                "candidate_result": {
                    "execution_id": execution_id,
                    "run_id": result.get("run_id") or run_id,
                    "workflow_name": result.get("workflow_name") or workflow_name,
                    "status": status,
                },
            }
            updated = optimization_store.update_trial_result(
                trial_id=str(trial["id"]),
                result_execution_id=execution_id,
                quality_status=quality_status,
                metrics_delta=merged_delta,
                notes=trial.get("notes"),
            )
            if updated:
                synced.append(updated)
    return synced


def _dataset_plan(
    study: dict[str, Any],
    traces: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
    trials: list[dict[str, Any]],
) -> dict[str, Any]:
    source = study.get("source_manifests") if isinstance(study.get("source_manifests"), dict) else {}
    readiness = _dataset_readiness(traces, source)
    trial_labels = Counter(str(trial.get("quality_status") or "needs_review") for trial in trials)
    return {
        "strategy": "dataset_first",
        "scope": "workflow_local_optimization",
        "redaction": "required_before_export_or_training",
        "splits": readiness["splits"],
        "labels": readiness["labels"],
        "readiness_state": readiness["state"],
        "local_model_path": readiness["local_model_path"],
        "uses": [
            "offline replay regression cases",
            "few-shot optimizer examples",
            "tenant-local evaluator labels",
            "model routing and cascade rules",
            "future local distillation candidates",
        ],
        "candidate_count": len(candidates),
        "trial_count": len(trials),
        "trial_quality_labels": dict(trial_labels),
        "guardrails": [
            "tenant isolation",
            "secret redaction",
            "human approval labels",
            "contract-preserving manifest snapshots",
        ],
    }


def _training_records(traces: list[dict[str, Any]]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for trace in traces:
        _, step_name_by_id = _trace_step_maps(trace)
        base = {
            "execution_id": trace.get("id"),
            "workflow_name": trace.get("workflow_name"),
            "agent_name": trace.get("agent_name"),
            "status": trace.get("status"),
        }
        for step in trace.get("steps") or []:
            if not isinstance(step, dict):
                continue
            records.append(
                {
                    **base,
                    "record_type": "step_execution",
                    "step_name": step.get("step_name") or step.get("name"),
                    "step_type": step.get("step_type") or step.get("type"),
                    "input": step.get("input_summary"),
                    "output": step.get("output_summary"),
                    "metrics": {
                        "duration_ms": step.get("duration_ms"),
                        "tokens": step.get("tokens_used"),
                        "cost_usd": step.get("cost_usd"),
                        "llm_calls": step.get("llm_calls_count"),
                        "tool_calls": step.get("tool_calls_count"),
                    },
                    "label": "successful_step" if str(step.get("status") or "").lower() == "completed" else "needs_review",
                }
            )
        for call in trace.get("llm_calls") or []:
            if not isinstance(call, dict):
                continue
            records.append(
                {
                    **base,
                    "record_type": "llm_call",
                    "step_name": _step_name_for_call(call, step_name_by_id),
                    "model": call.get("model"),
                    "provider": call.get("provider"),
                    "prompt_preview": call.get("prompt_preview"),
                    "response_preview": call.get("response_preview"),
                    "metrics": {
                        "prompt_tokens": call.get("prompt_tokens"),
                        "completion_tokens": call.get("completion_tokens"),
                        "total_tokens": call.get("total_tokens"),
                        "cost_usd": call.get("cost_usd"),
                        "latency_ms": call.get("latency_ms"),
                    },
                    "label": "routing_candidate",
                }
            )
        for call in trace.get("tool_calls") or []:
            if not isinstance(call, dict):
                continue
            records.append(
                {
                    **base,
                    "record_type": "tool_call",
                    "step_name": _step_name_for_call(call, step_name_by_id),
                    "tool_name": call.get("tool_name"),
                    "tool_args": call.get("tool_args"),
                    "tool_result": call.get("tool_result"),
                    "metrics": {"duration_ms": call.get("duration_ms")},
                    "label": "tool_policy_example",
                }
            )
    return records


def _evaluation_records(traces: list[dict[str, Any]], trials: list[dict[str, Any]]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for trace in traces:
        completed = str(trace.get("status") or "").lower() == "completed"
        records.append(
            {
                "record_type": "baseline_execution",
                "execution_id": trace.get("id"),
                "workflow_name": trace.get("workflow_name"),
                "quality_label": "baseline_success" if completed else "baseline_failure",
                "checks": {
                    "completed": completed,
                    "has_output_summary": bool(trace.get("output_summary")),
                    "step_count": trace.get("total_steps"),
                    "failed_steps": trace.get("failed_steps"),
                },
                "metrics": {
                    "duration_ms": trace.get("duration_ms"),
                    "tokens": trace.get("total_tokens"),
                    "cost_usd": trace.get("estimated_cost_usd") or trace.get("total_cost_usd"),
                    "tool_calls": trace.get("total_tool_calls"),
                    "llm_calls": trace.get("total_llm_calls"),
                },
            }
        )
    for trial in trials:
        records.append(
            {
                "record_type": "candidate_trial",
                "trial_id": trial.get("id"),
                "candidate_id": trial.get("candidate_id"),
                "baseline_execution_id": trial.get("baseline_execution_id"),
                "result_execution_id": trial.get("result_execution_id"),
                "quality_label": trial.get("quality_status"),
                "metrics_delta": trial.get("metrics_delta") or {},
                "notes": trial.get("notes"),
            }
        )
    return records


@router.post("/studies", status_code=201)
def create_study(body: CreateStudyRequest, user: dict[str, Any] = Depends(verify_token)) -> dict[str, Any]:
    ensure_namespace_access(user, body.namespace, "operator")
    traces = _get_traces(body.baseline_execution_ids)
    for trace in traces:
        ensure_namespace_access(user, str(trace.get("namespace") or body.namespace), "operator")
    source_manifests = _load_source_manifests(body.namespace, body.workflow_name, body.source_manifests)
    baseline_metrics = _aggregate_metrics(traces)
    intelligence = _build_optimizer_intelligence(traces, source_manifests)
    opportunities = intelligence["ranked_levers"]
    proof_gate = _proof_gate_for_study(baseline_metrics, intelligence)
    study = optimization_store.create_study(
        namespace=body.namespace,
        workflow_name=body.workflow_name,
        optimizer_agent_name=body.optimizer_agent_name,
        objective=body.objective,
        baseline_execution_ids=body.baseline_execution_ids,
        baseline_metrics=baseline_metrics,
        opportunities=opportunities,
        source_manifests=source_manifests,
        proof_gate=proof_gate,
        created_by=_principal(user),
    )
    return _expose_optimizer_intelligence(study)


@router.get("/studies")
def list_studies(
    namespace: str | None = None,
    workflow_name: str | None = None,
    limit: int = 20,
    offset: int = 0,
    user: dict[str, Any] = Depends(verify_token),
) -> dict[str, Any]:
    safe_limit = max(1, min(limit, 100))
    safe_offset = max(0, offset)
    if namespace:
        ensure_namespace_access(user, namespace)
    studies = optimization_store.list_studies(
        namespace=namespace.strip() if namespace else None,
        workflow_name=workflow_name.strip() if workflow_name else None,
        limit=safe_limit,
        offset=safe_offset,
    )
    visible: list[dict[str, Any]] = []
    for study in studies:
        ensure_namespace_access(user, str(study["namespace"]))
        _sync_candidate_trial_results(study)
        study["candidates"] = optimization_store.list_candidates(str(study["id"]))
        study["trials"] = optimization_store.list_trials(str(study["id"]))
        visible.append(_expose_optimizer_intelligence(study))
    return {"items": visible, "limit": safe_limit, "offset": safe_offset}


@router.get("/studies/{study_id}")
def get_study(study_id: str, user: dict[str, Any] = Depends(verify_token)) -> dict[str, Any]:
    study = optimization_store.get_study(study_id)
    if study is None:
        raise HTTPException(status_code=404, detail="Optimization study not found")
    ensure_namespace_access(user, str(study["namespace"]))
    _sync_candidate_trial_results(study)
    study["candidates"] = optimization_store.list_candidates(study_id)
    study["trials"] = optimization_store.list_trials(study_id)
    return _expose_optimizer_intelligence(study)


@router.post("/studies/{study_id}/candidates", status_code=201)
def create_candidate(study_id: str, body: CreateCandidateRequest, user: dict[str, Any] = Depends(verify_token)) -> dict[str, Any]:
    study = optimization_store.get_study(study_id)
    if study is None:
        raise HTTPException(status_code=404, detail="Optimization study not found")
    ensure_namespace_access(user, str(study["namespace"]), "admin")
    manifest_bundle = _label_candidate_bundle(
        study,
        body.manifest_bundle,
        allow_topology_rewrite=body.allow_topology_rewrite,
    )
    validation = _validate_candidate_bundle(
        study,
        manifest_bundle,
        allow_topology_rewrite=body.allow_topology_rewrite,
    )
    if not validation["valid"]:
        raise HTTPException(status_code=422, detail="; ".join(validation["errors"]))
    return optimization_store.create_candidate(
        study_id=study_id,
        namespace=str(study["namespace"]),
        name=body.name or _candidate_workflow_name(manifest_bundle),
        candidate_workflow_name=_candidate_workflow_name(manifest_bundle),
        manifest_bundle=manifest_bundle,
        manifest_diff=_manifest_diff(study, manifest_bundle),
        optimizer_output=body.optimizer_output,
        validation_results=validation,
        expected_savings=_normalise_expected_savings(body.expected_savings, validation),
        created_by=_principal(user),
    )


@router.post("/studies/{study_id}/candidates/generate", status_code=201)
def generate_candidate(study_id: str, body: GenerateCandidateRequest, user: dict[str, Any] = Depends(verify_token)) -> dict[str, Any]:
    study = optimization_store.get_study(study_id)
    if study is None:
        raise HTTPException(status_code=404, detail="Optimization study not found")
    ensure_namespace_access(user, str(study["namespace"]), "admin")
    suffix = body.suffix or f"opt-{study_id[-5:]}"
    generated = _candidate_bundle_from_optimizer_output(
        study,
        suffix,
        body.optimizer_output,
        allow_topology_rewrite=body.allow_topology_rewrite,
    )
    validation_warnings: list[str] = []
    if generated is None:
        bundle = _candidate_bundle_from_source(
            study,
            suffix,
            body.optimizer_output,
            allow_topology_rewrite=body.allow_topology_rewrite,
        )
        validation_warnings.append(
            "Optimizer output did not include a parseable candidate_manifest_bundle; generated a no-change control candidate."
        )
    else:
        bundle, validation_warnings = generated
    bundle = _label_candidate_bundle(
        study,
        bundle,
        allow_topology_rewrite=body.allow_topology_rewrite,
    )
    validation = _validate_candidate_bundle(
        study,
        bundle,
        allow_topology_rewrite=body.allow_topology_rewrite,
        warnings=validation_warnings,
    )
    if not validation["valid"]:
        fallback_warnings = [
            *validation_warnings,
            (
                "Optimizer-generated manifest failed validation "
                f"({'; '.join(validation['errors'])}); generated a safe copied candidate instead."
            ),
        ]
        bundle = _candidate_bundle_from_source(
            study,
            suffix,
            body.optimizer_output,
            allow_topology_rewrite=body.allow_topology_rewrite,
        )
        bundle = _label_candidate_bundle(
            study,
            bundle,
            allow_topology_rewrite=body.allow_topology_rewrite,
        )
        validation = _validate_candidate_bundle(
            study,
            bundle,
            allow_topology_rewrite=body.allow_topology_rewrite,
            warnings=fallback_warnings,
        )
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
        expected_savings=_normalise_expected_savings(body.expected_savings, validation),
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
    results = _apply_manifest_bundle(candidate["manifest_bundle"], str(candidate["namespace"]), include_workflows=False)
    updated = optimization_store.mark_candidate_applied(candidate_id)
    return {"candidate_id": candidate_id, "dry_run": False, "applied": True, "results": results, "candidate": updated}


@router.post("/candidates/{candidate_id}/run", status_code=201)
def run_candidate(
    candidate_id: str,
    body: RunCandidateRequest,
    user: dict[str, Any] = Depends(verify_token),
) -> dict[str, Any]:
    candidate = optimization_store.get_candidate(candidate_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail="Optimization candidate not found")
    ensure_namespace_access(user, str(candidate["namespace"]), "admin")
    if candidate.get("approval_status") != "approved":
        raise HTTPException(status_code=409, detail="Candidate must be approved before apply or trial execution")
    study = optimization_store.get_study(str(candidate["study_id"]))
    if study is None:
        raise HTTPException(status_code=404, detail="Optimization study not found")
    baseline_execution_id = body.baseline_execution_id or str((study.get("baseline_execution_ids") or [""])[0])
    if not baseline_execution_id:
        raise HTTPException(status_code=409, detail="Study has no baseline execution to compare against")
    baseline = _get_trace(baseline_execution_id)
    apply_results = _apply_manifest_bundle(candidate["manifest_bundle"], str(candidate["namespace"]), include_workflows=False)
    updated = optimization_store.mark_candidate_applied(candidate_id)
    agent_readiness = _wait_for_candidate_agents_ready(candidate["manifest_bundle"], str(candidate["namespace"]))
    candidate_run = _trigger_candidate_workflow(
        candidate["manifest_bundle"],
        str(candidate["candidate_workflow_name"]),
        str(candidate["namespace"]),
        body.input,
    )
    trial = optimization_store.create_trial(
        study_id=str(candidate["study_id"]),
        candidate_id=candidate_id,
        baseline_execution_id=baseline_execution_id,
        result_execution_id=None,
        quality_status="needs_review",
        metrics_delta={
            "candidate_run": candidate_run,
            "apply_results": apply_results,
            "agent_readiness": agent_readiness,
            "estimated_savings": candidate.get("expected_savings") or {},
            "baseline_snapshot": {
                "execution_id": baseline.get("id"),
                "workflow_name": baseline.get("workflow_name"),
                "run_id": baseline.get("run_id"),
                "duration_ms": baseline.get("duration_ms"),
                "total_tokens": baseline.get("total_tokens"),
                "total_tool_calls": baseline.get("total_tool_calls"),
                "estimated_cost_usd": baseline.get("estimated_cost_usd") or baseline.get("total_cost_usd"),
            },
        },
        notes=body.notes or f"Launched copied candidate workflow {candidate_run.get('workflow_name')} for ROI trial.",
        created_by=_principal(user),
    )
    return {
        "candidate_id": candidate_id,
        "candidate": updated,
        "candidate_run": candidate_run,
        "apply_results": apply_results,
        "agent_readiness": agent_readiness,
        "trial": trial,
    }


@router.post("/candidates/{candidate_id}/promotion")
def promote_candidate(
    candidate_id: str,
    body: PromoteCandidateRequest,
    user: dict[str, Any] = Depends(verify_token),
) -> dict[str, Any]:
    candidate = optimization_store.get_candidate(candidate_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail="Optimization candidate not found")
    ensure_namespace_access(user, str(candidate["namespace"]), "admin")
    if candidate.get("approval_status") != "approved":
        raise HTTPException(status_code=409, detail="Candidate must be approved before promotion")
    study = optimization_store.get_study(str(candidate["study_id"]))
    if study is None:
        raise HTTPException(status_code=404, detail="Optimization study not found")
    roi = _compute_roi(study, candidate_id=candidate_id)
    if not roi.get("verified"):
        proof_gate = roi.get("proof_gate") if isinstance(roi.get("proof_gate"), dict) else {}
        target = int(proof_gate.get("minimum_safe_trials") or 1)
        raise HTTPException(
            status_code=409,
            detail=(
                f"Candidate is not promotion-ready: {roi.get('proof_status')}; "
                f"{roi.get('passing_trial_count', 0)}/{target} safe trials passed"
            ),
        )
    promoted = optimization_store.promote_candidate(
        candidate_id=candidate_id,
        promoted_by=_principal(user),
        reason=body.reason,
        roi=roi,
    )
    if promoted is None:
        raise HTTPException(status_code=404, detail="Optimization candidate not found")
    return {**promoted, "roi": roi}


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


@router.get("/studies/{study_id}/comparison")
def get_study_comparison(
    study_id: str,
    candidate_id: str | None = None,
    user: dict[str, Any] = Depends(verify_token),
) -> dict[str, Any]:
    study = optimization_store.get_study(study_id)
    if study is None:
        raise HTTPException(status_code=404, detail="Optimization study not found")
    ensure_namespace_access(user, str(study["namespace"]))
    candidate = _select_comparison_candidate(study_id, candidate_id)
    selected_candidate_id = str(candidate.get("id")) if isinstance(candidate, dict) else None
    roi = _compute_roi(study, candidate_id=selected_candidate_id, sync_trials=False)
    return {
        "study_id": study_id,
        "candidate_id": selected_candidate_id,
        "roi": roi,
        "comparison": _comparison_payload(study, candidate, roi),
    }


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
    proof_gate = study.get("proof_gate") if isinstance(study.get("proof_gate"), dict) else {}
    intelligence = proof_gate.get("optimizer_intelligence") if isinstance(proof_gate.get("optimizer_intelligence"), dict) else _build_optimizer_intelligence(
        baseline_traces,
        study.get("source_manifests") if isinstance(study.get("source_manifests"), dict) else {},
    )
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
        "optimizer_intelligence": intelligence,
        "dataset_plan": _dataset_plan(study, baseline_traces, candidates, trials),
        "redaction_report": {
            "state": "redacted" if redacted else "raw",
            "secret_key_policy": "keys matching api key, token, secret, password, credential, or authorization are redacted",
            "secret_value_policy": "provider token-looking values are replaced with [REDACTED]",
        },
        "training_records": _training_records(baseline_traces),
        "evaluation_records": _evaluation_records(baseline_traces, trials),
        "baseline_traces": baseline_traces,
        "candidates": candidates,
        "trials": trials,
    }
    return _redact(payload) if redacted else payload
