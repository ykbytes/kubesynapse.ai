"""Workflow execution trace storage and retrieval.

Provides comprehensive traceability for every workflow execution:
- Execution metadata (start/end, status, inputs/outputs)
- Step-by-step trace with timing, state, and decisions
- LLM call inspection (prompt, response, tokens, cost, latency)
- Tool call tracing (arguments, results, errors)
- Artifact collection
- Replay support

Storage:
  - PostgreSQL/SQLite for trace metadata, indexed events, and raw trace events
  - JSONL files for raw trace event fallback and artifact payloads
  - Artifact files in trace-specific directories
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from datetime import UTC
from enum import Enum
from pathlib import Path
from typing import Any

from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    inspect,
    String,
    text,
)
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.orm import declarative_base

from auth_store import ENGINE as _AUTH_ENGINE
from auth_store import db_session, ensure_utc, utc_now

logger = logging.getLogger("api-gateway.trace-store")

_TRACE_SCHEMA_ERRORS = (OperationalError, ProgrammingError)
_TRACE_TABLES = (
    "workflow_executions",
    "step_executions",
    "llm_call_records",
    "tool_call_records",
    "execution_trace_events",
    "runtime_run_events",
)
_WORKFLOW_EXECUTION_RUN_ID_LENGTH = 128

Base = declarative_base()

# ---------------------------------------------------------------------------
# Trace storage paths
# ---------------------------------------------------------------------------

TRACE_STORAGE_DIR = Path(os.getenv("TRACE_STORAGE_DIR", "/tmp/kubesynapse-traces"))


def _ensure_trace_dir(execution_id: str) -> Path:
    path = TRACE_STORAGE_DIR / execution_id
    path.mkdir(parents=True, exist_ok=True)
    return path


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class ExecutionStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"


class StepStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"


class EventType(str, Enum):
    # Lifecycle
    EXECUTION_STARTED = "execution_started"
    EXECUTION_COMPLETED = "execution_completed"
    EXECUTION_FAILED = "execution_failed"
    EXECUTION_CANCELLED = "execution_cancelled"
    STEP_STARTED = "step_started"
    STEP_COMPLETED = "step_completed"
    STEP_FAILED = "step_failed"
    STEP_SKIPPED = "step_skipped"

    # LLM
    LLM_CALL_STARTED = "llm_call_started"
    LLM_CALL_COMPLETED = "llm_call_completed"
    LLM_CALL_FAILED = "llm_call_failed"
    LLM_STREAM_CHUNK = "llm_stream_chunk"

    # Tool
    TOOL_CALL_STARTED = "tool_call_started"
    TOOL_CALL_COMPLETED = "tool_call_completed"
    TOOL_CALL_FAILED = "tool_call_failed"

    # Decision / branching
    DECISION = "decision"
    BRANCH_TAKEN = "branch_taken"

    # State
    STATE_SNAPSHOT = "state_snapshot"
    VARIABLE_SET = "variable_set"

    # Error / warning
    ERROR = "error"
    WARNING = "warning"

    # Progress
    PROGRESS = "progress"
    TODO_CREATED = "todo_created"
    TODO_COMPLETED = "todo_completed"

    # Artifact
    ARTIFACT_CREATED = "artifact_created"

    # Custom
    CUSTOM = "custom"


# ---------------------------------------------------------------------------
# Color coding for event types (used in UI rendering)
# ---------------------------------------------------------------------------

EVENT_COLORS: dict[EventType, dict[str, str]] = {
    EventType.EXECUTION_STARTED: {"bg": "bg-emerald-50", "text": "text-emerald-700", "border": "border-emerald-200", "dot": "bg-emerald-500"},
    EventType.EXECUTION_COMPLETED: {"bg": "bg-emerald-50", "text": "text-emerald-700", "border": "border-emerald-200", "dot": "bg-emerald-500"},
    EventType.EXECUTION_FAILED: {"bg": "bg-red-50", "text": "text-red-700", "border": "border-red-200", "dot": "bg-red-500"},
    EventType.EXECUTION_CANCELLED: {"bg": "bg-amber-50", "text": "text-amber-700", "border": "border-amber-200", "dot": "bg-amber-500"},
    EventType.STEP_STARTED: {"bg": "bg-blue-50", "text": "text-blue-700", "border": "border-blue-200", "dot": "bg-blue-500"},
    EventType.STEP_COMPLETED: {"bg": "bg-blue-50", "text": "text-blue-700", "border": "border-blue-200", "dot": "bg-blue-500"},
    EventType.STEP_FAILED: {"bg": "bg-red-50", "text": "text-red-700", "border": "border-red-200", "dot": "bg-red-500"},
    EventType.STEP_SKIPPED: {"bg": "bg-gray-50", "text": "text-gray-600", "border": "border-gray-200", "dot": "bg-gray-400"},
    EventType.LLM_CALL_STARTED: {"bg": "bg-violet-50", "text": "text-violet-700", "border": "border-violet-200", "dot": "bg-violet-500"},
    EventType.LLM_CALL_COMPLETED: {"bg": "bg-violet-50", "text": "text-violet-700", "border": "border-violet-200", "dot": "bg-violet-500"},
    EventType.LLM_CALL_FAILED: {"bg": "bg-red-50", "text": "text-red-700", "border": "border-red-200", "dot": "bg-red-500"},
    EventType.TOOL_CALL_STARTED: {"bg": "bg-cyan-50", "text": "text-cyan-700", "border": "border-cyan-200", "dot": "bg-cyan-500"},
    EventType.TOOL_CALL_COMPLETED: {"bg": "bg-cyan-50", "text": "text-cyan-700", "border": "border-cyan-200", "dot": "bg-cyan-500"},
    EventType.TOOL_CALL_FAILED: {"bg": "bg-red-50", "text": "text-red-700", "border": "border-red-200", "dot": "bg-red-500"},
    EventType.DECISION: {"bg": "bg-amber-50", "text": "text-amber-700", "border": "border-amber-200", "dot": "bg-amber-500"},
    EventType.BRANCH_TAKEN: {"bg": "bg-amber-50", "text": "text-amber-700", "border": "border-amber-200", "dot": "bg-amber-500"},
    EventType.STATE_SNAPSHOT: {"bg": "bg-slate-50", "text": "text-slate-700", "border": "border-slate-200", "dot": "bg-slate-400"},
    EventType.ERROR: {"bg": "bg-red-50", "text": "text-red-700", "border": "border-red-200", "dot": "bg-red-500"},
    EventType.WARNING: {"bg": "bg-orange-50", "text": "text-orange-700", "border": "border-orange-200", "dot": "bg-orange-500"},
    EventType.PROGRESS: {"bg": "bg-sky-50", "text": "text-sky-700", "border": "border-sky-200", "dot": "bg-sky-500"},
    EventType.ARTIFACT_CREATED: {"bg": "bg-pink-50", "text": "text-pink-700", "border": "border-pink-200", "dot": "bg-pink-500"},
    EventType.CUSTOM: {"bg": "bg-gray-50", "text": "text-gray-700", "border": "border-gray-200", "dot": "bg-gray-500"},
}


def get_event_color(event_type: EventType) -> dict[str, str]:
    return EVENT_COLORS.get(event_type, EVENT_COLORS[EventType.CUSTOM])


# ---------------------------------------------------------------------------
# SQLAlchemy Models
# ---------------------------------------------------------------------------

class WorkflowExecution(Base):
    __tablename__ = "workflow_executions"

    id = Column(String(64), primary_key=True)
    namespace = Column(String(128), nullable=False, index=True)
    workflow_name = Column(String(128), nullable=False, index=True)
    agent_name = Column(String(128), nullable=False, index=True)
    run_id = Column(String(_WORKFLOW_EXECUTION_RUN_ID_LENGTH), nullable=False, index=True)
    status = Column(String(32), nullable=False, default=ExecutionStatus.PENDING.value)
    started_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    duration_ms = Column(Float, nullable=True)
    input_summary = Column(JSON, nullable=True)
    output_summary = Column(JSON, nullable=True)
    total_steps = Column(Integer, nullable=False, default=0)
    completed_steps = Column(Integer, nullable=False, default=0)
    failed_steps = Column(Integer, nullable=False, default=0)
    total_llm_calls = Column(Integer, nullable=False, default=0)
    total_tool_calls = Column(Integer, nullable=False, default=0)
    total_tokens = Column(Integer, nullable=False, default=0)
    prompt_tokens = Column(Integer, nullable=False, default=0)
    completion_tokens = Column(Integer, nullable=False, default=0)
    estimated_cost_usd = Column(Float, nullable=True)
    triggered_by = Column(String(128), nullable=True)
    error_message = Column(String(4096), nullable=True)
    trace_file_path = Column(String(512), nullable=True)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "namespace": self.namespace,
            "workflow_name": self.workflow_name,
            "agent_name": self.agent_name,
            "run_id": self.run_id,
            "status": self.status,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "duration_ms": self.duration_ms,
            "input_summary": self.input_summary,
            "output_summary": self.output_summary,
            "total_steps": self.total_steps,
            "completed_steps": self.completed_steps,
            "failed_steps": self.failed_steps,
            "total_llm_calls": self.total_llm_calls,
            "total_tool_calls": self.total_tool_calls,
            "total_tokens": self.total_tokens,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "estimated_cost_usd": self.estimated_cost_usd,
            "triggered_by": self.triggered_by,
            "error_message": self.error_message,
            "trace_file_path": self.trace_file_path,
        }


class StepExecution(Base):
    __tablename__ = "step_executions"

    id = Column(String(64), primary_key=True)
    execution_id = Column(String(64), ForeignKey("workflow_executions.id", ondelete="CASCADE"), nullable=False, index=True)
    step_name = Column(String(128), nullable=False)
    step_type = Column(String(64), nullable=True)
    step_index = Column(Integer, nullable=False)
    parent_step_id = Column(String(64), nullable=True, index=True)
    status = Column(String(32), nullable=False, default=StepStatus.PENDING.value)
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    duration_ms = Column(Float, nullable=True)
    input_summary = Column(JSON, nullable=True)
    output_summary = Column(JSON, nullable=True)
    error_message = Column(String(4096), nullable=True)
    llm_calls_count = Column(Integer, nullable=False, default=0)
    tool_calls_count = Column(Integer, nullable=False, default=0)
    tokens_used = Column(Integer, nullable=False, default=0)
    cost_usd = Column(Float, nullable=True)
    checkpoint_ref = Column(String(256), nullable=True)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "execution_id": self.execution_id,
            "step_name": self.step_name,
            "step_type": self.step_type,
            "step_index": self.step_index,
            "parent_step_id": self.parent_step_id,
            "status": self.status,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "duration_ms": self.duration_ms,
            "input_summary": self.input_summary,
            "output_summary": self.output_summary,
            "error_message": self.error_message,
            "llm_calls_count": self.llm_calls_count,
            "tool_calls_count": self.tool_calls_count,
            "tokens_used": self.tokens_used,
            "cost_usd": self.cost_usd,
        }


class LLMCallRecord(Base):
    __tablename__ = "llm_call_records"

    id = Column(String(64), primary_key=True)
    execution_id = Column(String(64), ForeignKey("workflow_executions.id", ondelete="CASCADE"), nullable=False, index=True)
    step_id = Column(String(64), nullable=False, index=True)
    model = Column(String(128), nullable=False)
    provider = Column(String(64), nullable=True)
    prompt_chars = Column(Integer, nullable=False, default=0)
    response_chars = Column(Integer, nullable=False, default=0)
    prompt_tokens = Column(Integer, nullable=False, default=0)
    completion_tokens = Column(Integer, nullable=False, default=0)
    total_tokens = Column(Integer, nullable=False, default=0)
    cost_usd = Column(Float, nullable=True)
    latency_ms = Column(Float, nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    prompt_preview = Column(String(1024), nullable=True)
    response_preview = Column(String(2048), nullable=True)
    trace_event_index = Column(Integer, nullable=True)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "execution_id": self.execution_id,
            "step_id": self.step_id,
            "model": self.model,
            "provider": self.provider,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "cost_usd": self.cost_usd,
            "latency_ms": self.latency_ms,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "prompt_preview": self.prompt_preview,
            "response_preview": self.response_preview,
        }


class ToolCallRecord(Base):
    __tablename__ = "tool_call_records"

    id = Column(String(64), primary_key=True)
    execution_id = Column(String(64), ForeignKey("workflow_executions.id", ondelete="CASCADE"), nullable=False, index=True)
    step_id = Column(String(64), nullable=False, index=True)
    tool_name = Column(String(128), nullable=False)
    tool_args = Column(JSON, nullable=True)
    tool_result = Column(JSON, nullable=True)
    error_message = Column(String(4096), nullable=True)
    duration_ms = Column(Float, nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    trace_event_index = Column(Integer, nullable=True)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "execution_id": self.execution_id,
            "step_id": self.step_id,
            "tool_name": self.tool_name,
            "tool_args": self.tool_args,
            "tool_result": self.tool_result,
            "error_message": self.error_message,
            "duration_ms": self.duration_ms,
            "started_at": self.started_at.isoformat() if self.started_at else None,
        }


# ---------------------------------------------------------------------------
# Runtime Run Event — Semantic Event Index (Run Intelligence Layer)
# ---------------------------------------------------------------------------

class RuntimeRunEvent(Base):
    """Queryable semantic event index for runtime sessions.

    Stores structured events from all runtimes (opencode, pi, vibe) and
    workers. JSONB payload provides flexibility; indexed columns enable
    fast filtering and aggregation.

    This is the core of the Run Intelligence Layer — AI-ready operational
    context stored alongside raw JSONL trace archives.
    """
    __tablename__ = "runtime_run_events"

    id = Column(String(64), primary_key=True)
    event_id = Column(String(128), nullable=False, unique=True, index=True)
    execution_id = Column(String(64), nullable=False, index=True)
    session_id = Column(String(128), nullable=True, index=True)
    thread_id = Column(String(128), nullable=True, index=True)
    namespace = Column(String(128), nullable=False, index=True)
    agent_name = Column(String(128), nullable=True, index=True)
    runtime_kind = Column(String(50), nullable=False, index=True)
    event_type = Column(String(64), nullable=False, index=True)
    seq = Column(Integer, nullable=False)
    severity = Column(String(16), nullable=True, default="info")
    payload = Column(JSON, nullable=False, server_default="{}")
    duration_ms = Column(Integer, nullable=True)
    prompt_tokens = Column(Integer, nullable=True)
    completion_tokens = Column(Integer, nullable=True)
    total_tokens = Column(Integer, nullable=True)
    cost_usd = Column(Float, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, index=True)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "event_id": self.event_id,
            "execution_id": self.execution_id,
            "session_id": self.session_id,
            "thread_id": self.thread_id,
            "namespace": self.namespace,
            "agent_name": self.agent_name,
            "runtime_kind": self.runtime_kind,
            "event_type": self.event_type,
            "seq": self.seq,
            "severity": self.severity,
            "payload": self.payload,
            "duration_ms": self.duration_ms,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "cost_usd": self.cost_usd,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class ExecutionTraceEventRecord(Base):
    """Durable raw trace event archive for observatory detail views."""

    __tablename__ = "execution_trace_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    execution_id = Column(String(64), nullable=False, index=True)
    step_id = Column(String(64), nullable=True, index=True)
    event_type = Column(String(64), nullable=False, index=True)
    timestamp = Column(Float, nullable=False, index=True)
    payload = Column(JSON, nullable=False, server_default="{}")
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, index=True)

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_type": self.event_type,
            "execution_id": self.execution_id,
            "step_id": self.step_id,
            "timestamp": self.timestamp,
            "payload": self.payload or {},
        }


# ---------------------------------------------------------------------------
# Trace Event (stored in JSONL, not DB)
# ---------------------------------------------------------------------------

class TraceEvent:
    """A single event in the execution trace. Stored as JSONL for performance."""

    def __init__(
        self,
        event_type: EventType,
        execution_id: str,
        step_id: str | None = None,
        timestamp: float | None = None,
        payload: dict[str, Any] | None = None,
    ):
        self.event_type = event_type
        self.execution_id = execution_id
        self.step_id = step_id
        self.timestamp = timestamp or time.time()
        self.payload = payload or {}

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_type": self.event_type.value,
            "execution_id": self.execution_id,
            "step_id": self.step_id,
            "timestamp": self.timestamp,
            "payload": self.payload,
        }

    def to_jsonl(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, default=str) + "\n"


# ---------------------------------------------------------------------------
# Trace File Writer
# ---------------------------------------------------------------------------

class TraceWriter:
    """Thread-safe writer for trace JSONL files."""

    def __init__(self, execution_id: str):
        self.execution_id = execution_id
        self._dir = _ensure_trace_dir(execution_id)
        self._path = self._dir / "trace.jsonl"
        self._lock = threading.Lock()
        self._event_count = 0

    def emit(self, event: TraceEvent) -> None:
        with self._lock:
            with open(self._path, "a", encoding="utf-8") as f:
                f.write(event.to_jsonl())
            self._event_count += 1

        try:
            with db_session() as session:
                session.add(
                    ExecutionTraceEventRecord(
                        execution_id=event.execution_id,
                        step_id=event.step_id,
                        event_type=event.event_type.value,
                        timestamp=event.timestamp,
                        payload=event.payload,
                    )
                )
        except Exception:
            logger.warning(
                "Failed to persist raw trace event for execution %s",
                event.execution_id,
                exc_info=True,
            )

    def write_artifact(self, name: str, content: str | bytes) -> Path:
        path = self._dir / "artifacts" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        mode = "wb" if isinstance(content, bytes) else "w"
        with open(path, mode, encoding="utf-8" if mode == "w" else None) as f:
            f.write(content)
        return path

    def read_events(self) -> list[dict[str, Any]]:
        events = read_trace_events(self.execution_id)
        if events:
            return events

        if not self._path.exists():
            return []
        events: list[dict[str, Any]] = []
        with open(self._path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        events.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        return events


# ---------------------------------------------------------------------------
# High-level Trace API
# ---------------------------------------------------------------------------

class ExecutionTracer:
    """High-level tracer for workflow executions."""

    def __init__(self) -> None:
        self._writers: dict[str, TraceWriter] = {}
        self._lock = threading.Lock()

    def _get_writer(self, execution_id: str) -> TraceWriter:
        with self._lock:
            if execution_id not in self._writers:
                self._writers[execution_id] = TraceWriter(execution_id)
            return self._writers[execution_id]

    def start_execution(
        self,
        namespace: str,
        workflow_name: str,
        agent_name: str,
        run_id: str,
        inputs: dict[str, Any] | None = None,
        triggered_by: str | None = None,
    ) -> str:
        execution_id = f"exec-{uuid.uuid4().hex[:16]}"
        writer = self._get_writer(execution_id)

        writer.emit(TraceEvent(
            event_type=EventType.EXECUTION_STARTED,
            execution_id=execution_id,
            payload={"inputs": inputs, "triggered_by": triggered_by},
        ))

        with db_session() as session:
            execution = WorkflowExecution(
                id=execution_id,
                namespace=namespace,
                workflow_name=workflow_name,
                agent_name=agent_name,
                run_id=run_id,
                status=ExecutionStatus.RUNNING.value,
                input_summary=inputs,
                triggered_by=triggered_by,
                trace_file_path=str(writer._path),
            )
            session.add(execution)

        logger.info("Started execution trace %s for %s/%s", execution_id, namespace, workflow_name)
        return execution_id

    def end_execution(
        self,
        execution_id: str,
        status: ExecutionStatus,
        outputs: dict[str, Any] | None = None,
        error_message: str | None = None,
        metrics: dict[str, Any] | None = None,
    ) -> None:
        event_type = {
            ExecutionStatus.COMPLETED: EventType.EXECUTION_COMPLETED,
            ExecutionStatus.FAILED: EventType.EXECUTION_FAILED,
            ExecutionStatus.CANCELLED: EventType.EXECUTION_CANCELLED,
            ExecutionStatus.TIMED_OUT: EventType.EXECUTION_FAILED,
        }.get(status, EventType.EXECUTION_COMPLETED)

        writer = self._get_writer(execution_id)
        writer.emit(TraceEvent(
            event_type=event_type,
            execution_id=execution_id,
            payload={"outputs": outputs, "error": error_message, "metrics": metrics},
        ))

        with db_session() as session:
            execution = session.query(WorkflowExecution).filter_by(id=execution_id).one_or_none()
            if execution:
                execution.status = status.value
                execution.completed_at = utc_now()
                execution.output_summary = outputs
                execution.error_message = error_message
                execution.duration_ms = duration_ms_between(execution.started_at, execution.completed_at)
                if metrics:
                    execution.total_tokens = metrics.get("total_tokens", execution.total_tokens)
                    execution.prompt_tokens = metrics.get("prompt_tokens", execution.prompt_tokens)
                    execution.completion_tokens = metrics.get("completion_tokens", execution.completion_tokens)
                    execution.estimated_cost_usd = metrics.get("cost_usd", execution.estimated_cost_usd)
                    execution.total_steps = metrics.get("total_steps", execution.total_steps)
                    execution.completed_steps = metrics.get("completed_steps", execution.completed_steps)
                    execution.failed_steps = metrics.get("failed_steps", execution.failed_steps)
                    execution.total_llm_calls = metrics.get("total_llm_calls", execution.total_llm_calls)
                    execution.total_tool_calls = metrics.get("total_tool_calls", execution.total_tool_calls)

        logger.info("Ended execution trace %s with status %s", execution_id, status.value)

    def start_step(
        self,
        execution_id: str,
        step_name: str,
        step_type: str | None = None,
        step_index: int = 0,
        parent_step_id: str | None = None,
        inputs: dict[str, Any] | None = None,
    ) -> str:
        step_id = f"step-{uuid.uuid4().hex[:12]}"
        writer = self._get_writer(execution_id)
        writer.emit(TraceEvent(
            event_type=EventType.STEP_STARTED,
            execution_id=execution_id,
            step_id=step_id,
            payload={"step_name": step_name, "step_type": step_type, "step_index": step_index, "inputs": inputs},
        ))

        with db_session() as session:
            step = StepExecution(
                id=step_id,
                execution_id=execution_id,
                step_name=step_name,
                step_type=step_type,
                step_index=step_index,
                parent_step_id=parent_step_id,
                status=StepStatus.RUNNING.value,
                started_at=utc_now(),
                input_summary=inputs,
            )
            session.add(step)

        return step_id

    def end_step(
        self,
        execution_id: str,
        step_id: str,
        status: StepStatus,
        outputs: dict[str, Any] | None = None,
        error_message: str | None = None,
    ) -> None:
        event_type = {
            StepStatus.COMPLETED: EventType.STEP_COMPLETED,
            StepStatus.FAILED: EventType.STEP_FAILED,
            StepStatus.SKIPPED: EventType.STEP_SKIPPED,
            StepStatus.CANCELLED: EventType.EXECUTION_CANCELLED,
        }.get(status, EventType.STEP_COMPLETED)

        writer = self._get_writer(execution_id)
        writer.emit(TraceEvent(
            event_type=event_type,
            execution_id=execution_id,
            step_id=step_id,
            payload={"outputs": outputs, "error": error_message},
        ))

        with db_session() as session:
            step = session.query(StepExecution).filter_by(id=step_id).one_or_none()
            if step:
                step.status = status.value
                step.completed_at = utc_now()
                step.output_summary = outputs
                step.error_message = error_message
                step.duration_ms = duration_ms_between(step.started_at, step.completed_at)

    def record_llm_call(
        self,
        execution_id: str,
        step_id: str,
        model: str,
        prompt: str,
        response: str,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        cost_usd: float | None = None,
        latency_ms: float | None = None,
        provider: str | None = None,
    ) -> None:
        writer = self._get_writer(execution_id)
        writer.emit(TraceEvent(
            event_type=EventType.LLM_CALL_COMPLETED,
            execution_id=execution_id,
            step_id=step_id,
            payload={
                "model": model,
                "provider": provider,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "cost_usd": cost_usd,
                "latency_ms": latency_ms,
            },
        ))

        with db_session() as session:
            record = LLMCallRecord(
                id=f"llm-{uuid.uuid4().hex[:12]}",
                execution_id=execution_id,
                step_id=step_id,
                model=model,
                provider=provider,
                prompt_chars=len(prompt),
                response_chars=len(response),
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=prompt_tokens + completion_tokens,
                cost_usd=cost_usd,
                latency_ms=latency_ms,
                prompt_preview=prompt[:1024],
                response_preview=response[:2048],
            )
            session.add(record)

            step = session.query(StepExecution).filter_by(id=step_id).one_or_none()
            if step:
                step.llm_calls_count += 1
                step.tokens_used += prompt_tokens + completion_tokens
                if cost_usd:
                    step.cost_usd = (step.cost_usd or 0.0) + cost_usd

    def record_tool_call(
        self,
        execution_id: str,
        step_id: str,
        tool_name: str,
        tool_args: dict[str, Any],
        tool_result: dict[str, Any] | None = None,
        error_message: str | None = None,
        duration_ms: float | None = None,
    ) -> None:
        writer = self._get_writer(execution_id)
        writer.emit(TraceEvent(
            event_type=EventType.TOOL_CALL_COMPLETED if not error_message else EventType.TOOL_CALL_FAILED,
            execution_id=execution_id,
            step_id=step_id,
            payload={"tool_name": tool_name, "tool_args": tool_args, "tool_result": tool_result, "error": error_message},
        ))

        with db_session() as session:
            record = ToolCallRecord(
                id=f"tool-{uuid.uuid4().hex[:12]}",
                execution_id=execution_id,
                step_id=step_id,
                tool_name=tool_name,
                tool_args=tool_args,
                tool_result=tool_result,
                error_message=error_message,
                duration_ms=duration_ms,
            )
            session.add(record)

            step = session.query(StepExecution).filter_by(id=step_id).one_or_none()
            if step:
                step.tool_calls_count += 1

    def record_event(
        self,
        execution_id: str,
        event_type: EventType,
        step_id: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        writer = self._get_writer(execution_id)
        writer.emit(TraceEvent(
            event_type=event_type,
            execution_id=execution_id,
            step_id=step_id,
            payload=payload,
        ))

    def read_trace(self, execution_id: str) -> list[dict[str, Any]]:
        writer = self._get_writer(execution_id)
        return writer.read_events()


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

TRACER = ExecutionTracer()


def _compile_type_sql(column_type: Any, dialect: Any) -> str:
    return str(column_type.compile(dialect=dialect))


def _ensure_workflow_execution_run_id_capacity() -> None:
    with _AUTH_ENGINE.begin() as connection:
        inspector = inspect(connection)
        if "workflow_executions" not in inspector.get_table_names():
            return

        columns = {
            str(column.get("name") or ""): column
            for column in inspector.get_columns("workflow_executions")
        }
        run_id_column = columns.get("run_id")
        if not run_id_column:
            return

        current_length = getattr(run_id_column.get("type"), "length", None)
        if current_length is None or current_length >= _WORKFLOW_EXECUTION_RUN_ID_LENGTH:
            return

        # PostgreSQL enforces VARCHAR widths, so widen the existing column in place.
        if connection.dialect.name != "postgresql":
            return

        target_type = _compile_type_sql(String(_WORKFLOW_EXECUTION_RUN_ID_LENGTH), connection.dialect)
        connection.execute(text(f"ALTER TABLE workflow_executions ALTER COLUMN run_id TYPE {target_type}"))
        logger.info("Widened workflow_executions.run_id column to %s", target_type)


def init_trace_database() -> None:
    """Create trace tables if they don't exist."""
    Base.metadata.create_all(bind=_AUTH_ENGINE)
    _ensure_workflow_execution_run_id_capacity()
    logger.info("Trace database initialized")


def ensure_trace_database() -> None:
    """Create trace tables on demand when startup ordering leaves them absent."""
    try:
        with _AUTH_ENGINE.connect() as connection:
            existing_tables = set(inspect(connection).get_table_names())
    except _TRACE_SCHEMA_ERRORS:
        logger.exception("Failed to inspect trace database state")
        raise

    if set(_TRACE_TABLES).issubset(existing_tables):
        _ensure_workflow_execution_run_id_capacity()
        return

    logger.warning("Trace tables missing; reinitializing trace database")
    init_trace_database()


# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------

def _serialize_execution(session: Any, execution: WorkflowExecution, include_related: bool = False) -> dict[str, Any]:
    result = execution.to_dict()

    step_rows = (
        session.query(StepExecution)
        .filter_by(execution_id=execution.id)
        .order_by(StepExecution.step_index)
        .all()
    )
    llm_rows = (
        session.query(LLMCallRecord)
        .filter_by(execution_id=execution.id)
        .order_by(LLMCallRecord.started_at)
        .all()
    )
    tool_rows = (
        session.query(ToolCallRecord)
        .filter_by(execution_id=execution.id)
        .order_by(ToolCallRecord.started_at)
        .all()
    )

    result["total_steps"] = len(step_rows)
    result["completed_steps"] = sum(1 for step in step_rows if step.status == StepStatus.COMPLETED.value)
    result["failed_steps"] = sum(1 for step in step_rows if step.status == StepStatus.FAILED.value)
    result["total_llm_calls"] = len(llm_rows)
    result["total_tool_calls"] = len(tool_rows)
    result["prompt_tokens"] = sum((row.prompt_tokens or 0) for row in llm_rows)
    result["completion_tokens"] = sum((row.completion_tokens or 0) for row in llm_rows)
    result["total_tokens"] = sum((row.total_tokens or 0) for row in llm_rows)

    known_costs = [row.cost_usd for row in llm_rows if row.cost_usd is not None]
    if known_costs:
        result["estimated_cost_usd"] = sum(known_costs)

    if not include_related:
        return result

    steps = [row.to_dict() for row in step_rows]
    llm_calls = [row.to_dict() for row in llm_rows]
    tool_calls = [row.to_dict() for row in tool_rows]

    llm_calls_by_step: dict[str, list[dict[str, Any]]] = {}
    for call in llm_calls:
        step_id = call.get("step_id")
        if step_id:
            llm_calls_by_step.setdefault(step_id, []).append(call)

    tool_calls_by_step: dict[str, list[dict[str, Any]]] = {}
    for call in tool_calls:
        step_id = call.get("step_id")
        if step_id:
            tool_calls_by_step.setdefault(step_id, []).append(call)

    for step in steps:
        step_id = step.get("id")
        step["llm_calls"] = llm_calls_by_step.get(step_id, [])
        step["tool_calls"] = tool_calls_by_step.get(step_id, [])

    result["steps"] = steps
    result["llm_calls"] = llm_calls
    result["tool_calls"] = tool_calls
    result["events"] = TRACER.read_trace(execution.id)
    return result


def duration_ms_between(started_at: Any, completed_at: Any) -> float | None:
    start = ensure_utc(started_at)
    end = ensure_utc(completed_at)
    if start is None or end is None:
        return None
    return (end - start).total_seconds() * 1000


def list_executions(
    namespace: str | None = None,
    workflow_name: str | None = None,
    agent_name: str | None = None,
    run_id: str | None = None,
    status: str | None = None,
    execution_kind: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    ensure_trace_database()
    with db_session() as session:
        query = session.query(WorkflowExecution)
        if namespace:
            query = query.filter_by(namespace=namespace)
        if workflow_name:
            query = query.filter_by(workflow_name=workflow_name)
        if agent_name:
            query = query.filter_by(agent_name=agent_name)
        if run_id:
            query = query.filter_by(run_id=run_id)
        if status:
            query = query.filter_by(status=status)
        normalized_kind = (execution_kind or "").strip().lower()
        if normalized_kind == "workflow":
            query = query.filter(WorkflowExecution.triggered_by != "direct-invoke")
        elif normalized_kind == "invoke":
            query = query.filter(WorkflowExecution.triggered_by == "direct-invoke")
        query = query.order_by(WorkflowExecution.started_at.desc())
        executions = query.limit(limit).offset(offset).all()
        return [_serialize_execution(session, execution) for execution in executions]


def get_execution(execution_id: str) -> dict[str, Any] | None:
    ensure_trace_database()
    with db_session() as session:
        execution = session.query(WorkflowExecution).filter_by(id=execution_id).one_or_none()
        if not execution:
            return None
        return _serialize_execution(session, execution, include_related=True)


def get_execution_summary(execution_id: str) -> dict[str, Any] | None:
    ensure_trace_database()
    with db_session() as session:
        execution = session.query(WorkflowExecution).filter_by(id=execution_id).one_or_none()
        if not execution:
            return None
        return _serialize_execution(session, execution)


def get_step_detail(step_id: str) -> dict[str, Any] | None:
    ensure_trace_database()
    with db_session() as session:
        step = session.query(StepExecution).filter_by(id=step_id).one_or_none()
        if not step:
            return None
        result = step.to_dict()
        result["llm_calls"] = [llm.to_dict() for llm in session.query(LLMCallRecord).filter_by(step_id=step_id).order_by(LLMCallRecord.started_at).all()]
        result["tool_calls"] = [t.to_dict() for t in session.query(ToolCallRecord).filter_by(step_id=step_id).order_by(ToolCallRecord.started_at).all()]
        return result


def read_trace_events(execution_id: str) -> list[dict[str, Any]]:
    ensure_trace_database()
    with db_session() as session:
        rows = (
            session.query(ExecutionTraceEventRecord)
            .filter_by(execution_id=execution_id)
            .order_by(ExecutionTraceEventRecord.id.asc())
            .all()
        )
        return [row.to_dict() for row in rows]


def delete_trace_events(execution_id: str) -> None:
    ensure_trace_database()
    with db_session() as session:
        (
            session.query(ExecutionTraceEventRecord)
            .filter_by(execution_id=execution_id)
            .delete(synchronize_session=False)
        )


# ---------------------------------------------------------------------------
# Runtime Run Event Ingestion (Run Intelligence Layer)
# ---------------------------------------------------------------------------

def ingest_runtime_events(events: list[dict[str, Any]]) -> int:
    """Batch ingest runtime events with idempotent upsert on event_id.

    Returns the number of events successfully inserted.
    Duplicate event_ids are silently ignored (upsert semantics).
    """
    if not events:
        return 0

    inserted = 0
    with db_session() as session:
        for evt in events:
            event_id = evt.get("event_id")
            if not event_id:
                continue

            existing = session.query(RuntimeRunEvent).filter_by(event_id=event_id).one_or_none()
            if existing:
                continue

            record = RuntimeRunEvent(
                id=evt.get("id", f"rre-{uuid.uuid4().hex[:16]}"),
                event_id=event_id,
                execution_id=evt.get("execution_id", ""),
                session_id=evt.get("session_id"),
                thread_id=evt.get("thread_id"),
                namespace=evt.get("namespace", "default"),
                agent_name=evt.get("agent_name"),
                runtime_kind=evt.get("runtime_kind", "unknown"),
                event_type=evt.get("event_type", "custom"),
                seq=evt.get("seq", 0),
                severity=evt.get("severity", "info"),
                payload=evt.get("payload", {}),
                duration_ms=evt.get("duration_ms"),
                prompt_tokens=evt.get("prompt_tokens"),
                completion_tokens=evt.get("completion_tokens"),
                total_tokens=evt.get("total_tokens"),
                cost_usd=evt.get("cost_usd"),
            )
            session.add(record)
            inserted += 1

    return inserted


# ---------------------------------------------------------------------------
# Runtime Run Event Query Helpers
# ---------------------------------------------------------------------------

def get_run_timeline(
    execution_id: str,
    event_type: str | None = None,
    from_seq: int | None = None,
    limit: int = 500,
) -> list[dict[str, Any]]:
    """Get ordered semantic timeline for a run."""
    with db_session() as session:
        query = session.query(RuntimeRunEvent).filter_by(execution_id=execution_id)
        if event_type:
            query = query.filter_by(event_type=event_type)
        if from_seq is not None:
            query = query.filter(RuntimeRunEvent.seq >= from_seq)
        query = query.order_by(RuntimeRunEvent.seq.asc())
        query = query.limit(limit)
        return [e.to_dict() for e in query.all()]


def query_runtime_events(
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
) -> dict[str, Any]:
    """Filter runtime events across runs."""
    from datetime import datetime

    with db_session() as session:
        query = session.query(RuntimeRunEvent)
        if namespace:
            query = query.filter_by(namespace=namespace)
        if runtime_kind:
            query = query.filter_by(runtime_kind=runtime_kind)
        if event_type:
            query = query.filter_by(event_type=event_type)
        if agent_name:
            query = query.filter_by(agent_name=agent_name)
        if session_id:
            query = query.filter_by(session_id=session_id)
        if severity:
            query = query.filter_by(severity=severity)
        if from_ts:
            try:
                dt = datetime.fromisoformat(from_ts.replace("Z", "+00:00"))
                query = query.filter(RuntimeRunEvent.created_at >= dt)
            except ValueError:
                pass
        if to_ts:
            try:
                dt = datetime.fromisoformat(to_ts.replace("Z", "+00:00"))
                query = query.filter(RuntimeRunEvent.created_at <= dt)
            except ValueError:
                pass

        total = query.count()
        query = query.order_by(RuntimeRunEvent.created_at.desc())
        query = query.limit(min(limit, 1000)).offset(max(offset, 0))
        items = [e.to_dict() for e in query.all()]

    return {"items": items, "total": total, "limit": limit, "offset": offset}


def get_run_summary(execution_id: str) -> dict[str, Any] | None:
    """Aggregate summary for a run from indexed events."""
    with db_session() as session:
        events = session.query(RuntimeRunEvent).filter_by(execution_id=execution_id).all()
        if not events:
            return None

        tool_calls = [e for e in events if e.event_type.startswith("tool.")]
        tool_failures = [e for e in tool_calls if e.payload.get("status") == "failed"]
        errors = [e for e in events if e.severity == "error"]

        total_tokens = sum(e.total_tokens or 0 for e in events)
        total_cost = sum(e.cost_usd or 0.0 for e in events)
        total_duration = sum(e.duration_ms or 0 for e in events)

        return {
            "execution_id": execution_id,
            "event_count": len(events),
            "tool_call_count": len(tool_calls),
            "tool_failure_count": len(tool_failures),
            "error_count": len(errors),
            "total_tokens": total_tokens,
            "estimated_cost_usd": round(total_cost, 6),
            "total_duration_ms": total_duration,
            "runtime_kinds": list(set(e.runtime_kind for e in events)),
            "first_event": events[0].created_at.isoformat() if events else None,
            "last_event": events[-1].created_at.isoformat() if events else None,
        }


def get_agent_interaction_graph(
    namespace: str | None = None,
    hours: int = 24,
) -> dict[str, Any]:
    """Build agent-to-agent dependency graph from A2A events."""
    from datetime import datetime, timedelta

    cutoff = datetime.now(UTC) - timedelta(hours=hours)

    with db_session() as session:
        query = session.query(RuntimeRunEvent).filter(
            RuntimeRunEvent.event_type.like("agent.call.%"),
            RuntimeRunEvent.created_at >= cutoff,
        )
        if namespace:
            query = query.filter_by(namespace=namespace)

        events = query.all()

    edges: dict[str, dict[str, Any]] = {}
    nodes: set[str] = set()

    for evt in events:
        caller = evt.payload.get("caller_agent", evt.agent_name)
        target = evt.payload.get("target_agent", "")
        if not caller or not target:
            continue

        nodes.add(caller)
        nodes.add(target)

        key = f"{caller}→{target}"
        if key not in edges:
            edges[key] = {
                "source": caller,
                "target": target,
                "call_count": 0,
                "error_count": 0,
                "total_duration_ms": 0,
                "last_seen": None,
            }

        edge = edges[key]
        edge["call_count"] += 1
        if evt.severity == "error" or evt.payload.get("status") == "failed":
            edge["error_count"] += 1
        if evt.duration_ms:
            edge["total_duration_ms"] += evt.duration_ms
        evt_ts = evt.created_at.isoformat()
        if not edge["last_seen"] or evt_ts > edge["last_seen"]:
            edge["last_seen"] = evt_ts

    for edge in edges.values():
        if edge["call_count"] > 0 and edge["total_duration_ms"] > 0:
            edge["avg_latency_ms"] = round(edge["total_duration_ms"] / edge["call_count"], 1)

    return {
        "nodes": sorted(nodes),
        "edges": list(edges.values()),
        "window_hours": hours,
    }


def get_spend_breakdown(
    namespace: str | None = None,
    hours: int = 24,
) -> list[dict[str, Any]]:
    """Aggregate token/cost spend by agent, model, runtime, namespace."""
    from datetime import datetime, timedelta

    cutoff = datetime.now(UTC) - timedelta(hours=hours)

    with db_session() as session:
        query = session.query(RuntimeRunEvent).filter(
            RuntimeRunEvent.created_at >= cutoff,
            RuntimeRunEvent.total_tokens.isnot(None),
        )
        if namespace:
            query = query.filter_by(namespace=namespace)

        events = query.all()

    buckets: dict[str, dict[str, Any]] = {}
    for evt in events:
        key = f"{evt.namespace}/{evt.agent_name or 'unknown'}/{evt.runtime_kind}"
        if key not in buckets:
            buckets[key] = {
                "namespace": evt.namespace,
                "agent_name": evt.agent_name or "unknown",
                "runtime_kind": evt.runtime_kind,
                "model": evt.payload.get("model", "unknown"),
                "total_tokens": 0,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "estimated_cost_usd": 0.0,
                "run_count": 0,
                "error_count": 0,
            }

        bucket = buckets[key]
        bucket["total_tokens"] += evt.total_tokens or 0
        bucket["prompt_tokens"] += evt.prompt_tokens or 0
        bucket["completion_tokens"] += evt.completion_tokens or 0
        bucket["estimated_cost_usd"] += evt.cost_usd or 0.0
        if evt.event_type == "run.completed" or evt.event_type == "run.started":
            bucket["run_count"] += 1
        if evt.severity == "error":
            bucket["error_count"] += 1

    result = list(buckets.values())
    for r in result:
        r["estimated_cost_usd"] = round(r["estimated_cost_usd"], 6)

    return sorted(result, key=lambda x: x["total_tokens"], reverse=True)
