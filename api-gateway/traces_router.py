"""Execution Observatory — FastAPI router for workflow trace inspection."""

from __future__ import annotations

import functools
import html
import json
import logging
import shutil
import time
import uuid
from collections.abc import AsyncGenerator, Callable
from datetime import UTC, datetime
from typing import Any

import trace_store
from auth_middleware import (
    ensure_namespace_access,
    request_client_ip,
    safe_record_audit,
    verify_token,
)
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger("api-gateway.traces-router")

router = APIRouter(prefix="/traces", tags=["traces"])
TRACE_ALIAS_SUNSET = "Wed, 01 Oct 2026 00:00:00 GMT"


# ---------------------------------------------------------------------------
# Pydantic response models
# ---------------------------------------------------------------------------


class ExecutionListResponse(BaseModel):
    """Paginated list of workflow executions."""

    model_config = ConfigDict(from_attributes=True)

    items: list[dict[str, Any]] = Field(default_factory=list)
    limit: int = 50
    offset: int = 0


class ExecutionDetailResponse(BaseModel):
    """Full execution detail with steps, LLM/tool calls, and events."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    namespace: str
    workflow_name: str
    agent_name: str
    run_id: str
    status: str
    started_at: str | None = None
    completed_at: str | None = None
    duration_ms: float | None = None
    input_summary: dict[str, Any] | str | None = None
    output_summary: dict[str, Any] | str | None = None
    total_steps: int = 0
    completed_steps: int = 0
    failed_steps: int = 0
    total_llm_calls: int = 0
    total_tool_calls: int = 0
    total_tokens: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    reasoning_tokens: int = 0
    estimated_cost_usd: float | None = None
    triggered_by: str | None = None
    error_message: str | None = None
    trace_file_path: str | None = None

    steps: list[dict[str, Any]] = Field(default_factory=list)
    llm_calls: list[dict[str, Any]] = Field(default_factory=list)
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    events: list[dict[str, Any]] = Field(default_factory=list)


class StepDetailResponse(BaseModel):
    """Step detail with associated LLM and tool calls."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    execution_id: str
    step_name: str
    step_type: str | None = None
    step_index: int
    parent_step_id: str | None = None
    status: str
    started_at: str | None = None
    completed_at: str | None = None
    duration_ms: float | None = None
    input_summary: dict[str, Any] | str | None = None
    output_summary: dict[str, Any] | str | None = None
    error_message: str | None = None
    llm_calls_count: int = 0
    tool_calls_count: int = 0
    tokens_used: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    reasoning_tokens: int = 0
    cost_usd: float | None = None

    llm_calls: list[dict[str, Any]] = Field(default_factory=list)
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)


class BatchIngestRequest(BaseModel):
    """Batch trace event ingestion from workers."""

    events: list[dict[str, Any]] = Field(default_factory=list)


class RuntimeEventBatchRequest(BaseModel):
    """Batch runtime event ingestion for Run Intelligence Layer."""

    events: list[dict[str, Any]] = Field(default_factory=list, min_length=1, max_length=500)


class RunTimelineResponse(BaseModel):
    """Ordered semantic timeline for a run."""

    execution_id: str
    events: list[dict[str, Any]] = Field(default_factory=list)
    count: int = 0


class RunSummaryResponse(BaseModel):
    """Aggregate summary for a run from indexed events."""

    execution_id: str
    event_count: int = 0
    tool_call_count: int = 0
    tool_failure_count: int = 0
    error_count: int = 0
    total_tokens: int = 0
    estimated_cost_usd: float = 0.0
    total_duration_ms: int = 0
    runtime_kinds: list[str] = Field(default_factory=list)
    first_event: str | None = None
    last_event: str | None = None


class EventQueryResponse(BaseModel):
    """Filtered runtime events."""

    items: list[dict[str, Any]] = Field(default_factory=list)
    total: int = 0
    limit: int = 200
    offset: int = 0


class AgentGraphResponse(BaseModel):
    """Agent-to-agent dependency graph."""

    nodes: list[str] = Field(default_factory=list)
    edges: list[dict[str, Any]] = Field(default_factory=list)
    window_hours: int = 24


class SpendBreakdownResponse(BaseModel):
    """Token/cost spend breakdown."""

    items: list[dict[str, Any]] = Field(default_factory=list)
    window_hours: int = 24


# ---------------------------------------------------------------------------
# Error handling decorator
# ---------------------------------------------------------------------------


def _catch_errors(func: Callable[..., Any]) -> Callable[..., Any]:
    """Catch unexpected errors and return a sanitized 500 response."""

    @functools.wraps(func)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return await func(*args, **kwargs)
        except HTTPException:
            raise
        except Exception:
            logger.exception("Unhandled error in %s", func.__qualname__)
            return JSONResponse(status_code=500, content={"detail": "Internal server error"})

    return wrapper


def _set_trace_alias_headers(response: Response, request: Request, canonical_path: str) -> None:
    """Mark compatibility trace aliases as deprecated and point to the canonical URL."""

    canonical_url = str(request.url.replace(path=canonical_path))
    response.headers["Deprecation"] = "true"
    response.headers["Sunset"] = TRACE_ALIAS_SUNSET
    response.headers["Link"] = f'<{canonical_url}>; rel="successor-version"'
    response.headers["Warning"] = f'299 - "Deprecated API; use {canonical_path}"'


# ---------------------------------------------------------------------------
# HTML report builder
# ---------------------------------------------------------------------------


def _build_html_report(execution_id: str, execution: dict[str, Any]) -> str:
    """Build a self-contained HTML report for an execution."""

    def esc(value: Any) -> str:
        return html.escape(str(value)) if value is not None else ""

    def fmt_json(value: Any) -> str:
        try:
            return json.dumps(value, indent=2, ensure_ascii=False)
        except (TypeError, ValueError):
            return str(value)

    status = execution.get("status", "unknown")
    status_class = ""
    if status == "completed":
        status_class = "status-completed"
    elif status == "failed":
        status_class = "status-failed"
    elif status == "running":
        status_class = "status-running"

    meta_rows = [
        f"<tr><th>ID</th><td>{esc(execution_id)}</td></tr>",
        f"<tr><th>Namespace</th><td>{esc(execution.get('namespace'))}</td></tr>",
        f"<tr><th>Workflow</th><td>{esc(execution.get('workflow_name'))}</td></tr>",
        f"<tr><th>Agent</th><td>{esc(execution.get('agent_name'))}</td></tr>",
        f"<tr><th>Run ID</th><td>{esc(execution.get('run_id'))}</td></tr>",
        f"<tr><th>Status</th><td class='{status_class}'>{esc(status)}</td></tr>",
        f"<tr><th>Started</th><td>{esc(execution.get('started_at'))}</td></tr>",
        f"<tr><th>Completed</th><td>{esc(execution.get('completed_at'))}</td></tr>",
        f"<tr><th>Duration (ms)</th><td>{esc(execution.get('duration_ms'))}</td></tr>",
        f"<tr><th>Total Steps</th><td>{esc(execution.get('total_steps'))}</td></tr>",
        f"<tr><th>Completed Steps</th><td>{esc(execution.get('completed_steps'))}</td></tr>",
        f"<tr><th>Failed Steps</th><td>{esc(execution.get('failed_steps'))}</td></tr>",
        f"<tr><th>LLM Calls</th><td>{esc(execution.get('total_llm_calls'))}</td></tr>",
        f"<tr><th>Tool Calls</th><td>{esc(execution.get('total_tool_calls'))}</td></tr>",
        f"<tr><th>Tokens</th><td>{esc(execution.get('total_tokens'))}</td></tr>",
        f"<tr><th>Cost (USD)</th><td>{esc(execution.get('estimated_cost_usd'))}</td></tr>",
        f"<tr><th>Triggered By</th><td>{esc(execution.get('triggered_by'))}</td></tr>",
    ]
    if execution.get("error_message"):
        meta_rows.append(
            f"<tr><th>Error</th><td class='status-failed'>{esc(execution.get('error_message'))}</td></tr>"
        )

    steps_html = ""
    for step in execution.get("steps", []):
        step_status = step.get("status", "unknown")
        step_status_class = ""
        if step_status == "completed":
            step_status_class = "status-completed"
        elif step_status == "failed":
            step_status_class = "status-failed"
        steps_html += (
            f"<tr>"
            f"<td>{esc(step.get('step_name'))}</td>"
            f"<td>{esc(step.get('step_type'))}</td>"
            f"<td class='{step_status_class}'>{esc(step_status)}</td>"
            f"<td>{esc(step.get('duration_ms'))}</td>"
            f"<td>{esc(step.get('llm_calls_count'))}</td>"
            f"<td>{esc(step.get('tool_calls_count'))}</td>"
            f"</tr>"
        )

    llm_html = ""
    for llm in execution.get("llm_calls", []):
        llm_html += (
            f"<tr>"
            f"<td>{esc(llm.get('model'))}</td>"
            f"<td>{esc(llm.get('provider'))}</td>"
            f"<td>{esc(llm.get('total_tokens'))}</td>"
            f"<td>{esc(llm.get('latency_ms'))}</td>"
            f"<td>{esc(llm.get('cost_usd'))}</td>"
            f"</tr>"
        )

    tool_html = ""
    for tool in execution.get("tool_calls", []):
        tool_html += (
            f"<tr>"
            f"<td>{esc(tool.get('tool_name'))}</td>"
            f"<td>{esc(tool.get('duration_ms'))}</td>"
            f"<td>{esc(tool.get('error_message'))}</td>"
            f"</tr>"
        )

    events_html = ""
    for event in execution.get("events", []):
        payload = event.get("payload", {})
        events_html += (
            f"<div class='event'>"
            f"<div class='event-type'>{esc(event.get('event_type'))} "
            f"(step: {esc(event.get('step_id'))})</div>"
            f"<pre>{esc(fmt_json(payload))}</pre>"
            f"</div>"
        )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Execution Report - {esc(execution_id)}</title>
<style>
body {{
  font-family: system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial, sans-serif;
  margin: 2rem;
  background: #f8fafc;
  color: #1e293b;
}}
.container {{
  max-width: 1200px;
  margin: 0 auto;
  background: #fff;
  padding: 2rem;
  border-radius: 8px;
  box-shadow: 0 1px 3px rgba(0,0,0,0.1);
}}
h1 {{
  font-size: 1.5rem;
  margin-bottom: 1rem;
}}
h2 {{
  font-size: 1.25rem;
  margin-top: 2rem;
  border-bottom: 1px solid #e2e8f0;
  padding-bottom: 0.5rem;
}}
table {{
  width: 100%;
  border-collapse: collapse;
  margin-top: 1rem;
}}
th, td {{
  text-align: left;
  padding: 0.5rem;
  border-bottom: 1px solid #e2e8f0;
}}
th {{
  background: #f1f5f9;
  font-weight: 600;
}}
.status-completed {{
  color: #16a34a;
}}
.status-failed {{
  color: #dc2626;
}}
.status-running {{
  color: #2563eb;
}}
.event {{
  padding: 0.75rem;
  border-left: 4px solid #cbd5e1;
  margin-bottom: 0.75rem;
  background: #f8fafc;
  border-radius: 4px;
}}
.event-type {{
  font-weight: 600;
  color: #475569;
  margin-bottom: 0.25rem;
}}
pre {{
  background: #f1f5f9;
  padding: 0.5rem;
  border-radius: 4px;
  overflow-x: auto;
  font-size: 0.875rem;
}}
</style>
</head>
<body>
<div class="container">
<h1>Execution Report: {esc(execution_id)}</h1>
<h2>Metadata</h2>
<table>
{''.join(meta_rows)}
</table>

<h2>Steps</h2>
<table>
<tr><th>Name</th><th>Type</th><th>Status</th><th>Duration (ms)</th>
<th>LLM Calls</th><th>Tool Calls</th></tr>
{steps_html}
</table>

<h2>LLM Calls</h2>
<table>
<tr><th>Model</th><th>Provider</th><th>Tokens</th>
<th>Latency (ms)</th><th>Cost (USD)</th></tr>
{llm_html}
</table>

<h2>Tool Calls</h2>
<table>
<tr><th>Tool</th><th>Duration (ms)</th><th>Error</th></tr>
{tool_html}
</table>

<h2>Events</h2>
{events_html}
</div>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Batch ingestion helpers
# ---------------------------------------------------------------------------


def _get_or_create_execution(session: Any, execution_id: str, payload: dict[str, Any]) -> Any:
    """Fetch or create a WorkflowExecution record."""
    execution = (
        session.query(trace_store.WorkflowExecution)
        .filter_by(id=execution_id)
        .one_or_none()
    )
    if execution:
        return execution
    execution = trace_store.WorkflowExecution(
        id=execution_id,
        namespace=payload.get("namespace", "default"),
        workflow_name=payload.get("workflow_name", ""),
        agent_name=payload.get("agent_name", ""),
        run_id=payload.get("run_id", ""),
        status=trace_store.ExecutionStatus.PENDING.value,
        started_at=_event_timestamp_to_utc(event_timestamp=payload.get("_event_timestamp")) or trace_store.utc_now(),
        input_summary=payload.get("inputs"),
        triggered_by=payload.get("triggered_by"),
        trace_file_path=str(trace_store.TRACE_STORAGE_DIR / execution_id / "trace.jsonl"),
    )
    session.add(execution)
    session.flush()
    return execution


def _get_or_create_step(session: Any, execution_id: str, step_id: str, payload: dict[str, Any]) -> Any:
    """Fetch or create a StepExecution record."""
    step = (
        session.query(trace_store.StepExecution)
        .filter_by(id=step_id)
        .one_or_none()
    )
    if step:
        return step
    step = trace_store.StepExecution(
        id=step_id,
        execution_id=execution_id,
        step_name=payload.get("step_name", ""),
        step_type=payload.get("step_type"),
        step_index=payload.get("step_index", 0),
        parent_step_id=payload.get("parent_step_id"),
        status=trace_store.StepStatus.PENDING.value,
        started_at=_event_timestamp_to_utc(event_timestamp=payload.get("_event_timestamp")),
        input_summary=payload.get("inputs"),
    )
    session.add(step)
    session.flush()
    return step


def _event_timestamp_to_utc(event_timestamp: Any) -> datetime | None:
    if event_timestamp is None:
        return None
    try:
        return datetime.fromtimestamp(float(event_timestamp), tz=UTC)
    except (TypeError, ValueError, OSError, OverflowError):
        return None


def _coerce_int(value: Any) -> int:
    """Best-effort int coercion that treats None / non-numeric as 0."""
    if value is None:
        return 0
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value)
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _upsert_from_event(session: Any, event_data: dict[str, Any]) -> None:
    """Update DB records from a single trace event."""
    event_type = event_data.get("event_type", "custom")
    execution_id = event_data.get("execution_id")
    step_id = event_data.get("step_id")
    payload = event_data.get("payload") or {}
    payload = {**payload, "_event_timestamp": event_data.get("timestamp")}

    if event_type == "execution_started":
        execution = _get_or_create_execution(session, execution_id, payload)
        if execution.started_at is None:
            execution.started_at = _event_timestamp_to_utc(event_data.get("timestamp")) or trace_store.utc_now()
        return

    if event_type in ("execution_completed", "execution_failed", "execution_cancelled"):
        execution = (
            session.query(trace_store.WorkflowExecution)
            .filter_by(id=execution_id)
            .one_or_none()
        )
        if execution:
            execution.status = {
                "execution_completed": trace_store.ExecutionStatus.COMPLETED.value,
                "execution_failed": trace_store.ExecutionStatus.FAILED.value,
                "execution_cancelled": trace_store.ExecutionStatus.CANCELLED.value,
            }.get(event_type, trace_store.ExecutionStatus.FAILED.value)
            execution.completed_at = _event_timestamp_to_utc(event_data.get("timestamp")) or trace_store.utc_now()
            execution.output_summary = payload.get("outputs")
            execution.error_message = payload.get("error")
            metrics = payload.get("metrics") or {}
            execution.total_tokens = metrics.get("total_tokens", execution.total_tokens)
            execution.prompt_tokens = metrics.get("prompt_tokens", execution.prompt_tokens)
            execution.completion_tokens = metrics.get("completion_tokens", execution.completion_tokens)
            execution.estimated_cost_usd = metrics.get("cost_usd", execution.estimated_cost_usd)
            execution.total_steps = metrics.get("total_steps", execution.total_steps)
            execution.completed_steps = metrics.get("completed_steps", execution.completed_steps)
            execution.failed_steps = metrics.get("failed_steps", execution.failed_steps)
            execution.total_llm_calls = metrics.get("total_llm_calls", execution.total_llm_calls)
            execution.total_tool_calls = metrics.get("total_tool_calls", execution.total_tool_calls)
            execution.duration_ms = trace_store.duration_ms_between(execution.started_at, execution.completed_at)
            trace_store.refresh_execution_aggregates(session, execution)
        return

    if event_type == "step_started" and step_id:
        step = _get_or_create_step(session, execution_id, step_id, payload)
        if payload.get("step_index") is not None:
            step.step_index = payload.get("step_index", step.step_index)
        if step.started_at is None:
            step.started_at = _event_timestamp_to_utc(event_data.get("timestamp"))
        if payload.get("inputs") is not None:
            step.input_summary = payload.get("inputs")
        return

    if event_type in ("step_completed", "step_failed", "step_skipped") and step_id:
        step = (
            session.query(trace_store.StepExecution)
            .filter_by(id=step_id)
            .one_or_none()
        )
        if step:
            step.status = {
                "step_completed": trace_store.StepStatus.COMPLETED.value,
                "step_failed": trace_store.StepStatus.FAILED.value,
                "step_skipped": trace_store.StepStatus.SKIPPED.value,
            }.get(event_type, trace_store.StepStatus.FAILED.value)
            step.completed_at = _event_timestamp_to_utc(event_data.get("timestamp")) or trace_store.utc_now()
            step.output_summary = payload.get("outputs")
            step.error_message = payload.get("error")
            step.duration_ms = trace_store.duration_ms_between(step.started_at, step.completed_at)
        return

    if event_type == "llm_call_completed" and step_id:
        prompt_tokens = _coerce_int(payload.get("prompt_tokens"))
        completion_tokens = _coerce_int(payload.get("completion_tokens"))
        cache_read_tokens = _coerce_int(payload.get("cache_read_tokens"))
        cache_write_tokens = _coerce_int(payload.get("cache_write_tokens"))
        reasoning_tokens = _coerce_int(payload.get("reasoning_tokens"))
        record = trace_store.LLMCallRecord(
            id=f"llm-{uuid.uuid4().hex[:12]}",
            execution_id=execution_id,
            step_id=step_id,
            model=payload.get("model", ""),
            provider=payload.get("provider"),
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cache_read_tokens=cache_read_tokens,
            cache_write_tokens=cache_write_tokens,
            reasoning_tokens=reasoning_tokens,
            total_tokens=(
                prompt_tokens
                + completion_tokens
                + cache_read_tokens
                + cache_write_tokens
                + reasoning_tokens
            ),
            cost_usd=payload.get("cost_usd"),
            latency_ms=payload.get("latency_ms"),
            started_at=_event_timestamp_to_utc(event_data.get("timestamp")) or trace_store.utc_now(),
            prompt_preview=payload.get("prompt_preview", "")[:1024],
            response_preview=payload.get("response_preview", "")[:2048],
        )
        session.add(record)
        step = (
            session.query(trace_store.StepExecution)
            .filter_by(id=step_id)
            .one_or_none()
        )
        if step:
            step.llm_calls_count += 1
            step.tokens_used += record.total_tokens
            step.cache_read_tokens = (step.cache_read_tokens or 0) + cache_read_tokens
            step.cache_write_tokens = (step.cache_write_tokens or 0) + cache_write_tokens
            step.reasoning_tokens = (step.reasoning_tokens or 0) + reasoning_tokens
            if record.cost_usd:
                step.cost_usd = (step.cost_usd or 0.0) + record.cost_usd
        return

    # Handle runtime-emitted llm.call events (no step_id required)
    if event_type == "llm.call":
        prompt_tokens = _coerce_int(event_data.get("prompt_tokens"))
        completion_tokens = _coerce_int(event_data.get("completion_tokens"))
        cache_read_tokens = _coerce_int(event_data.get("cache_read_tokens"))
        cache_write_tokens = _coerce_int(event_data.get("cache_write_tokens"))
        reasoning_tokens = _coerce_int(event_data.get("reasoning_tokens"))
        total_tokens = _coerce_int(event_data.get("total_tokens"))
        if total_tokens == 0:
            total_tokens = prompt_tokens + completion_tokens + cache_read_tokens + cache_write_tokens + reasoning_tokens
        if total_tokens == 0:
            return  # Skip zero-token LLM call events (nothing to record)
        effective_step_id = step_id or f"step-runtime-{execution_id[:16]}"
        # Ensure the step exists (create a synthetic one if needed)
        if not step_id:
            existing_step = (
                session.query(trace_store.StepExecution)
                .filter_by(id=effective_step_id)
                .one_or_none()
            )
            if not existing_step:
                _get_or_create_step(session, execution_id, effective_step_id, {
                    "step_name": "runtime-invoke",
                    "step_type": "llm",
                })
        record = trace_store.LLMCallRecord(
            id=f"llm-{uuid.uuid4().hex[:12]}",
            execution_id=execution_id,
            step_id=effective_step_id,
            model=payload.get("model", ""),
            provider=payload.get("provider"),
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cache_read_tokens=cache_read_tokens,
            cache_write_tokens=cache_write_tokens,
            reasoning_tokens=reasoning_tokens,
            total_tokens=total_tokens,
            cost_usd=event_data.get("cost_usd"),
            latency_ms=event_data.get("duration_ms"),
            started_at=_event_timestamp_to_utc(event_data.get("timestamp")) or trace_store.utc_now(),
        )
        session.add(record)
        # Update step aggregates
        step_obj = (
            session.query(trace_store.StepExecution)
            .filter_by(id=effective_step_id)
            .one_or_none()
        )
        if step_obj:
            step_obj.llm_calls_count += 1
            step_obj.tokens_used = (step_obj.tokens_used or 0) + total_tokens
            step_obj.cache_read_tokens = (step_obj.cache_read_tokens or 0) + cache_read_tokens
            step_obj.cache_write_tokens = (step_obj.cache_write_tokens or 0) + cache_write_tokens
            step_obj.reasoning_tokens = (step_obj.reasoning_tokens or 0) + reasoning_tokens
            if record.cost_usd:
                step_obj.cost_usd = (step_obj.cost_usd or 0.0) + record.cost_usd
        # Refresh execution-level aggregates so cache/reasoning totals propagate
        execution = (
            session.query(trace_store.WorkflowExecution)
            .filter_by(id=execution_id)
            .one_or_none()
        )
        if execution:
            trace_store.refresh_execution_aggregates(session, execution)
        return

    if event_type in ("tool_call_completed", "tool_call_failed") and step_id:
        record = trace_store.ToolCallRecord(
            id=f"tool-{uuid.uuid4().hex[:12]}",
            execution_id=execution_id,
            step_id=step_id,
            tool_name=payload.get("tool_name", ""),
            tool_args=payload.get("tool_args"),
            tool_result=payload.get("tool_result"),
            error_message=payload.get("error"),
            duration_ms=payload.get("duration_ms"),
            started_at=_event_timestamp_to_utc(event_data.get("timestamp")) or trace_store.utc_now(),
        )
        session.add(record)
        step = (
            session.query(trace_store.StepExecution)
            .filter_by(id=step_id)
            .one_or_none()
        )
        if step:
            step.tool_calls_count += 1
        return


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post("/batch", status_code=202)
@_catch_errors
async def ingest_batch(
    body: BatchIngestRequest,
    user: dict[str, Any] = Depends(verify_token),
) -> JSONResponse:
    """Ingest a batch of trace events from workers.

    Accepts raw trace events, persists them to JSONL, and updates
    corresponding DB records (executions, steps, LLM/tool calls).
    """
    for event_data in body.events:
        execution_id = event_data.get("execution_id")
        if not execution_id:
            continue

        # Persist to JSONL
        try:
            event_type = trace_store.EventType(event_data.get("event_type", "custom"))
        except ValueError:
            event_type = trace_store.EventType.CUSTOM
        writer = trace_store.TRACER._get_writer(execution_id)
        writer.emit(
            trace_store.TraceEvent(
                event_type=event_type,
                execution_id=execution_id,
                step_id=event_data.get("step_id"),
                timestamp=event_data.get("timestamp", time.time()),
                payload=event_data.get("payload", {}),
            )
        )

        # Upsert DB records
        try:
            with trace_store.db_session() as session:
                _upsert_from_event(session, event_data)
        except Exception:
            logger.debug("Failed to upsert DB record for event", exc_info=True)

    return JSONResponse(status_code=202, content={"detail": "Batch accepted"})


@router.get("/executions", response_model=ExecutionListResponse)
@_catch_errors
async def list_executions(
    namespace: str | None = None,
    workflow_name: str | None = None,
    agent_name: str | None = None,
    run_id: str | None = None,
    status: str | None = None,
    execution_kind: str | None = None,
    limit: int = 50,
    offset: int = 0,
    user: dict[str, Any] = Depends(verify_token),
) -> ExecutionListResponse:
    """List workflow executions with optional filters."""
    if namespace:
        ensure_namespace_access(user, namespace)

    limit = min(max(limit, 0), 200)
    offset = max(offset, 0)

    items = trace_store.list_executions(
        namespace=namespace,
        workflow_name=workflow_name,
        agent_name=agent_name,
        run_id=run_id,
        status=status,
        execution_kind=execution_kind,
        limit=limit,
        offset=offset,
    )

    allowed_namespaces = user.get("allowed_namespaces", ["*"])
    if "*" not in allowed_namespaces:
        items = [item for item in items if item.get("namespace") in allowed_namespaces]

    return ExecutionListResponse(items=items, limit=limit, offset=offset)


@router.get("", response_model=ExecutionListResponse, include_in_schema=False)
@_catch_errors
async def list_traces_alias(
    request: Request,
    response: Response,
    namespace: str | None = None,
    workflow_name: str | None = None,
    agent_name: str | None = None,
    run_id: str | None = None,
    status: str | None = None,
    execution_kind: str | None = None,
    limit: int = 50,
    offset: int = 0,
    user: dict[str, Any] = Depends(verify_token),
) -> ExecutionListResponse:
    """Compatibility alias for older clients still calling GET /traces."""

    _set_trace_alias_headers(response, request, "/api/v1/traces/executions")
    return await list_executions(
        namespace=namespace,
        workflow_name=workflow_name,
        agent_name=agent_name,
        run_id=run_id,
        status=status,
        execution_kind=execution_kind,
        limit=limit,
        offset=offset,
        user=user,
    )


@router.get("/executions/{execution_id}", response_model=ExecutionDetailResponse)
@_catch_errors
async def get_execution_detail(
    execution_id: str,
    user: dict[str, Any] = Depends(verify_token),
) -> ExecutionDetailResponse:
    """Get full execution detail including steps and trace events."""
    execution = trace_store.get_execution(execution_id)
    if not execution:
        raise HTTPException(status_code=404, detail="Execution not found")
    ensure_namespace_access(user, execution["namespace"])
    return ExecutionDetailResponse.model_validate(execution)


@router.get("/executions/{execution_id}/summary")
@_catch_errors
async def get_execution_summary(
    execution_id: str,
    user: dict[str, Any] = Depends(verify_token),
) -> dict[str, Any]:
    """Get high-level execution summary."""
    summary = trace_store.get_execution_summary(execution_id)
    if not summary:
        raise HTTPException(status_code=404, detail="Execution not found")
    ensure_namespace_access(user, summary["namespace"])
    return summary


@router.get("/executions/{execution_id}/events")
@_catch_errors
async def get_execution_events(
    execution_id: str,
    user: dict[str, Any] = Depends(verify_token),
) -> list[dict[str, Any]]:
    """Get raw trace events from durable storage with JSONL fallback."""
    summary = trace_store.get_execution_summary(execution_id)
    if not summary:
        raise HTTPException(status_code=404, detail="Execution not found")
    ensure_namespace_access(user, summary["namespace"])
    return trace_store.read_trace_events(execution_id) or trace_store.TRACER.read_trace(execution_id)


@router.get("/steps/{step_id}", response_model=StepDetailResponse)
@_catch_errors
async def get_step_detail(
    step_id: str,
    user: dict[str, Any] = Depends(verify_token),
) -> StepDetailResponse:
    """Get step detail with LLM and tool call records."""
    step = trace_store.get_step_detail(step_id)
    if not step:
        raise HTTPException(status_code=404, detail="Step not found")
    execution = trace_store.get_execution_summary(step["execution_id"])
    if not execution:
        raise HTTPException(status_code=404, detail="Execution not found")
    ensure_namespace_access(user, execution["namespace"])
    return StepDetailResponse.model_validate(step)


@router.delete("/executions/{execution_id}")
@_catch_errors
async def delete_execution(
    execution_id: str,
    request: Request,
    user: dict[str, Any] = Depends(verify_token),
) -> JSONResponse:
    """Delete an execution and its trace directory."""
    with trace_store.db_session() as session:
        execution = (
            session.query(trace_store.WorkflowExecution)
            .filter_by(id=execution_id)
            .one_or_none()
        )
        if not execution:
            raise HTTPException(status_code=404, detail="Execution not found")

        if user.get("role") != "admin":
            ensure_namespace_access(user, execution.namespace)

        namespace = execution.namespace
        session.delete(execution)

    trace_dir = trace_store.TRACE_STORAGE_DIR / execution_id
    if trace_dir.exists():
        shutil.rmtree(trace_dir)

    trace_store.delete_trace_events(execution_id)

    safe_record_audit(
        action="execution_deleted",
        principal=user,
        resource_kind="WorkflowExecution",
        resource_name=execution_id,
        resource_namespace=namespace,
        ip_address=request_client_ip(request),
    )

    return JSONResponse(status_code=200, content={"detail": "Execution deleted"})


@router.get("/export")
@_catch_errors
async def bulk_export_executions(
    namespace: str | None = None,
    agent_name: str | None = None,
    since: str | None = None,
    until: str | None = None,
    limit: int = 200,
    fmt: str = "json",
    user: dict[str, Any] = Depends(verify_token),
):
    """Bulk export all matching executions as JSON or CSV (summary mode)."""
    if namespace:
        ensure_namespace_access(user, namespace)

    limit = min(max(limit, 0), 500)
    items = trace_store.list_executions(
        namespace=namespace,
        agent_name=agent_name,
        limit=limit,
        offset=0,
    )

    # Apply date filters client-side
    if since:
        try:
            since_dt = datetime.fromisoformat(since.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            raise HTTPException(status_code=400, detail="Invalid 'since' date format") from None
        items = [e for e in items if e.get("started_at") and since_dt <= datetime.fromisoformat(str(e["started_at"]).replace("Z", "+00:00"))]

    if until:
        try:
            until_dt = datetime.fromisoformat(until.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            raise HTTPException(status_code=400, detail="Invalid 'until' date format") from None
        items = [e for e in items if e.get("started_at") and until_dt >= datetime.fromisoformat(str(e["started_at"]).replace("Z", "+00:00"))]

    return items


@router.post("/executions/{execution_id}/export/json")
@_catch_errors
async def export_execution_json(
    execution_id: str,
    user: dict[str, Any] = Depends(verify_token),
) -> StreamingResponse:
    """Export execution metadata, steps, and events as a streamed JSON file."""
    execution = trace_store.get_execution(execution_id)
    if not execution:
        raise HTTPException(status_code=404, detail="Execution not found")
    ensure_namespace_access(user, execution["namespace"])

    async def _stream() -> AsyncGenerator[str, None]:
        yield json.dumps(execution, indent=2, default=str)

    return StreamingResponse(
        _stream(),
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="execution-{execution_id}.json"',
        },
    )


@router.get("/executions/{execution_id}/export/html")
@_catch_errors
async def export_execution_html(
    execution_id: str,
    user: dict[str, Any] = Depends(verify_token),
) -> Response:
    """Export execution as a self-contained HTML report."""
    execution = trace_store.get_execution(execution_id)
    if not execution:
        raise HTTPException(status_code=404, detail="Execution not found")
    ensure_namespace_access(user, execution["namespace"])
    html_content = _build_html_report(execution_id, execution)
    return Response(
        content=html_content,
        media_type="text/html",
        headers={
            "Content-Disposition": f'attachment; filename="execution-{execution_id}.html"',
        },
    )


# ---------------------------------------------------------------------------
# Run Intelligence Layer — Runtime Event APIs
# ---------------------------------------------------------------------------


@router.post("/runtime-events", status_code=201)
@_catch_errors
async def ingest_runtime_events(
    body: RuntimeEventBatchRequest,
    user: dict[str, Any] = Depends(verify_token),
) -> JSONResponse:
    """Batch ingest runtime events from runtimes and workers.

    Events are upserted by `event_id` for idempotency.
    Requires valid API token; namespace scoping enforced per event.
    """
    if not body.events:
        raise HTTPException(status_code=400, detail="No events provided")

    if len(body.events) > 500:
        raise HTTPException(status_code=400, detail="Too many events (max 500 per batch)")

    for evt in body.events:
        evt_ns = evt.get("namespace", "")
        if evt_ns:
            ensure_namespace_access(user, evt_ns)

    inserted = trace_store.ingest_runtime_events(body.events)

    # Also upsert execution/step/LLM DB records for trace-relevant events
    _TRACE_RELEVANT_EVENT_TYPES = {"llm.call", "run.completed", "run.error", "run.started"}
    for evt in body.events:
        if evt.get("event_type") in _TRACE_RELEVANT_EVENT_TYPES and evt.get("execution_id"):
            try:
                with trace_store.db_session() as session:
                    _upsert_from_event(session, evt)
            except Exception:
                logger.debug("Failed to upsert from runtime event %s", evt.get("event_id"), exc_info=True)

    return JSONResponse(
        status_code=201,
        content={"inserted": inserted, "total_submitted": len(body.events)},
    )


@router.get("/{execution_id}/timeline")
@_catch_errors
async def get_run_timeline(
    execution_id: str,
    event_type: str | None = None,
    from_seq: int | None = None,
    limit: int = 500,
    user: dict[str, Any] = Depends(verify_token),
) -> RunTimelineResponse:
    """Get ordered semantic timeline for a run."""
    summary = trace_store.get_execution_summary(execution_id)
    if not summary:
        raise HTTPException(status_code=404, detail="Execution not found")
    ensure_namespace_access(user, summary["namespace"])

    events = trace_store.get_run_timeline(
        execution_id=execution_id,
        event_type=event_type,
        from_seq=from_seq,
        limit=min(limit, 1000),
    )
    return RunTimelineResponse(
        execution_id=execution_id,
        events=events,
        count=len(events),
    )


@router.get("/{execution_id}/runtime-summary")
@_catch_errors
async def get_run_summary(
    execution_id: str,
    user: dict[str, Any] = Depends(verify_token),
) -> JSONResponse:
    """Get aggregate summary for a run from indexed events."""
    summary = trace_store.get_execution_summary(execution_id)
    if not summary:
        raise HTTPException(status_code=404, detail="Execution not found")
    ensure_namespace_access(user, summary["namespace"])

    run_summary = trace_store.get_run_summary(execution_id)
    if not run_summary:
        return JSONResponse(content={"execution_id": execution_id, "event_count": 0})

    return JSONResponse(content=run_summary)


@router.get("/runtime-events")
@_catch_errors
async def query_runtime_events(
    namespace: str | None = None,
    runtime_kind: str | None = None,
    event_type: str | None = None,
    agent_name: str | None = None,
    session_id: str | None = None,
    severity: str | None = None,
    from_ts: str | None = None,
    to_ts: str | None = None,
    limit: int = 200,
    offset: int = 0,
    user: dict[str, Any] = Depends(verify_token),
) -> EventQueryResponse:
    """Filter runtime events across runs."""
    if namespace:
        ensure_namespace_access(user, namespace)

    result = trace_store.query_runtime_events(
        namespace=namespace,
        runtime_kind=runtime_kind,
        event_type=event_type,
        agent_name=agent_name,
        session_id=session_id,
        severity=severity,
        from_ts=from_ts,
        to_ts=to_ts,
        limit=limit,
        offset=offset,
    )
    return EventQueryResponse(**result)


@router.get("/{execution_id}", response_model=ExecutionDetailResponse, include_in_schema=False)
@_catch_errors
async def get_trace_detail_alias(
    execution_id: str,
    request: Request,
    response: Response,
    user: dict[str, Any] = Depends(verify_token),
) -> ExecutionDetailResponse:
    """Compatibility alias for older clients still calling GET /traces/{execution_id}."""

    _set_trace_alias_headers(response, request, f"/api/v1/traces/executions/{execution_id}")
    return await get_execution_detail(execution_id=execution_id, user=user)
