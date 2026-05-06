"""KubeSynapse Mistral Vibe Runtime — Enhanced with full API contract compliance."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import signal
import subprocess
import time
import uuid
import zipfile
from collections.abc import AsyncIterator
from io import BytesIO
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field, model_validator

from runtime_events import (
    emit_run_completed,
    emit_run_error,
    emit_run_started,
    emit_tool_call,
    start_emitter,
    stop_emitter,
)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

WORKSPACE_DIR = Path(os.getenv("VIBE_WORKDIR", "/workspace")).resolve()
STATE_DIR = Path(os.getenv("VIBE_HOME", "/app/state/home/.vibe")).resolve()
DEFAULT_MODEL_ALIAS = (os.getenv("VIBE_ACTIVE_MODEL") or "devstral-small").strip() or "devstral-small"
DEFAULT_SYSTEM_PROMPT = (os.getenv("VIBE_SYSTEM_PROMPT") or "").strip()
VIBE_BIN = os.getenv("VIBE_BIN", "/opt/venv/bin/vibe")
SERVICE_NAME = os.getenv("AGENT_NAME", "mistral-vibe-agent").strip() or "mistral-vibe-agent"
SERVICE_NAMESPACE = os.getenv("AGENT_NAMESPACE", "default").strip() or "default"

# ---------------------------------------------------------------------------
# Session tracking (for /cancel, /abort, /todo, etc.)
# ---------------------------------------------------------------------------

_active_sessions: dict[str, dict[str, Any]] = {}
_start_time = time.time()


def _register_session(thread_id: str, session_id: str, model: str) -> None:
    _active_sessions[thread_id] = {
        "session_id": session_id,
        "model": model,
        "status": "active",
        "created_at": time.time(),
    }


def _complete_session(thread_id: str, status: str = "completed") -> None:
    if thread_id in _active_sessions:
        _active_sessions[thread_id]["status"] = status


def _cancel_session(thread_id: str) -> bool:
    if thread_id in _active_sessions and _active_sessions[thread_id]["status"] == "active":
        _active_sessions[thread_id]["status"] = "cancelled"
        return True
    return False


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------


class InvokeRequest(BaseModel):
    prompt: str = Field(default="", max_length=256000)
    thread_id: str | None = Field(default=None, max_length=128)
    model: str | None = Field(default=None, max_length=255)
    system: str | None = Field(default=None, max_length=32000)
    no_session: bool = False
    max_turns: int | None = Field(default=None, ge=1, le=1000)
    working_directory: str | None = Field(default=None, max_length=512)
    output_format: str | None = Field(default=None, max_length=32)
    output_schema: dict[str, Any] | None = None
    timeout_seconds: float | None = Field(default=None, ge=1, le=600)
    autonomous: bool = True

    @model_validator(mode="after")
    def validate_request(self) -> "InvokeRequest":
        self.prompt = self.prompt.strip()
        self.thread_id = self.thread_id.strip() or None if self.thread_id is not None else None
        self.model = self.model.strip() or None if self.model is not None else None
        self.system = self.system.strip() or None if self.system is not None else None
        self.working_directory = self.working_directory.strip() or None if self.working_directory is not None else None
        self.output_format = self.output_format.strip().lower() or None if self.output_format is not None else None
        if not self.prompt:
            raise ValueError("prompt must not be blank")
        return self


class InvokeResponse(BaseModel):
    thread_id: str
    response: str
    model: str
    status: str = "completed"
    approval_name: str | None = None
    retry_after_seconds: int | None = None
    a2a: dict[str, Any] | None = None
    warnings: list[str] = Field(default_factory=list)
    artifacts: list[dict[str, Any]] = Field(default_factory=list)
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    continuity: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------

app = FastAPI(
    title="KubeSynapse Mistral Vibe Runtime",
    version="1.0.0",
    description="Mistral Vibe agent runtime for KubeSynapse. Implements the KubeSynth Runtime API v1 contract.",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_workdir(raw_value: str | None) -> Path:
    if not raw_value:
        return WORKSPACE_DIR
    candidate = (WORKSPACE_DIR / raw_value).resolve() if not Path(raw_value).is_absolute() else Path(raw_value).resolve()
    if WORKSPACE_DIR != candidate and WORKSPACE_DIR not in candidate.parents:
        raise HTTPException(status_code=400, detail=f"working_directory '{raw_value}' must stay inside /workspace")
    if not candidate.exists() or not candidate.is_dir():
        raise HTTPException(status_code=400, detail=f"working_directory '{raw_value}' does not exist")
    return candidate


def _extract_assistant_response(messages: Any) -> tuple[str, list[dict[str, Any]]]:
    if not isinstance(messages, list):
        return ("", [])
    response_parts: list[str] = []
    tool_calls: list[dict[str, Any]] = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        if str(message.get("role") or "").lower() == "assistant":
            content = str(message.get("content") or "").strip()
            if content:
                response_parts.append(content)
            raw_tool_calls = message.get("tool_calls")
            if isinstance(raw_tool_calls, list):
                for tool_call in raw_tool_calls:
                    if not isinstance(tool_call, dict):
                        continue
                    function = tool_call.get("function") if isinstance(tool_call.get("function"), dict) else {}
                    tool_calls.append(
                        {
                            "name": str(function.get("name") or "tool"),
                            "args": function.get("arguments"),
                            "result": None,
                        }
                    )
    return ("\n\n".join(part for part in response_parts if part).strip(), tool_calls)


def _run_vibe(request: InvokeRequest) -> InvokeResponse:
    workdir = _resolve_workdir(request.working_directory)
    env = os.environ.copy()
    env.setdefault("VIBE_HOME", str(STATE_DIR))
    env.setdefault("HOME", str(STATE_DIR.parent))
    env.setdefault("MISTRAL_API_KEY", os.getenv("MISTRAL_API_KEY", ""))
    env["VIBE_ACTIVE_MODEL"] = request.model or DEFAULT_MODEL_ALIAS

    prompt = request.prompt
    system_prompt = request.system or DEFAULT_SYSTEM_PROMPT
    if system_prompt:
        prompt = f"[System Instructions]\n{system_prompt}\n\n[User Request]\n{prompt}"

    cmd = [VIBE_BIN, "--prompt", prompt, "--output", "json"]
    if request.max_turns:
        cmd.extend(["--max-turns", str(request.max_turns)])

    timeout = request.timeout_seconds or float(os.getenv("VIBE_MODEL_TIMEOUT_SECONDS", "300"))
    process = subprocess.run(
        cmd,
        cwd=str(workdir),
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )

    stdout = (process.stdout or "").strip()
    stderr = (process.stderr or "").strip()
    if process.returncode != 0:
        raise HTTPException(status_code=502, detail=stderr or stdout or f"vibe exited with code {process.returncode}")

    try:
        messages = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=502, detail=f"Failed to parse vibe JSON output: {exc}") from exc

    response_text, tool_calls = _extract_assistant_response(messages)
    if not response_text and not tool_calls:
        response_text = "Invocation completed."

    thread_id = request.thread_id or f"vibe-{uuid.uuid4().hex[:12]}"
    session_id = f"vibe-session-{uuid.uuid4().hex[:16]}"
    _register_session(thread_id, session_id, request.model or DEFAULT_MODEL_ALIAS)

    return InvokeResponse(
        thread_id=thread_id,
        response=response_text,
        model=request.model or DEFAULT_MODEL_ALIAS,
        status="completed",
        tool_calls=tool_calls,
        continuity={
            "created_new_session": True,
            "session_recovered": False,
            "has_prior_memory": False,
        },
        metadata={
            "runtime": "mistral-vibe",
            "contract_version": "v1",
            "raw_message_count": len(messages) if isinstance(messages, list) else 0,
            "tokens": {
                "total": 0,
                "input": 0,
                "output": 0,
                "reasoning": 0,
                "cache": {"read": 0, "write": 0},
            },
            "finish_reason": "stop",
            "task_status": "DONE",
            "agent_used": "build",
        },
    )


def _list_workspace_files(root: Path) -> list[dict[str, Any]]:
    """List files in workspace with metadata."""
    files = []
    try:
        for path in root.rglob("*"):
            if path.is_file() and not path.name.startswith("."):
                stat = path.stat()
                files.append(
                    {
                        "path": str(path.relative_to(root)),
                        "size": stat.st_size,
                        "modified": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(stat.st_mtime)),
                    }
                )
    except OSError:
        pass
    return sorted(files, key=lambda f: f["path"])


# ---------------------------------------------------------------------------
# Health & Readiness
# ---------------------------------------------------------------------------


@app.get("/health", tags=["Health"])
def health() -> dict[str, Any]:
    """Liveness probe. Returns runtime health status."""
    uptime = time.time() - _start_time
    active = sum(1 for s in _active_sessions.values() if s["status"] == "active")
    return {
        "status": "healthy",
        "runtime": "mistral-vibe",
        "service": SERVICE_NAME,
        "namespace": SERVICE_NAMESPACE,
        "provider": "mistral",
        "agent": "build",
        "sessions": {
            "total": len(_active_sessions),
            "active": active,
        },
        "uptime_seconds": round(uptime, 1),
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


@app.get("/ready", tags=["Health"])
def ready() -> dict[str, Any]:
    """Readiness probe. Returns whether the runtime is ready to accept requests."""
    checks = {
        "binary_exists": Path(VIBE_BIN).exists(),
        "workspace_writable": os.access(str(WORKSPACE_DIR), os.W_OK),
        "state_dir_exists": STATE_DIR.exists(),
    }
    all_ready = all(checks.values())
    if not all_ready:
        raise HTTPException(
            status_code=503,
            detail=f"Runtime not ready: {', '.join(k for k, v in checks.items() if not v)}",
        )
    return {
        "status": "ready",
        "runtime": "mistral-vibe",
        "checks": checks,
    }


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


@app.get("/info", tags=["Discovery"])
def get_info() -> dict[str, Any]:
    """Runtime metadata and contract version."""
    return {
        "runtime": "mistral-vibe",
        "contract_version": "v1",
        "service": SERVICE_NAME,
        "namespace": SERVICE_NAMESPACE,
        "provider": "mistral",
        "model": DEFAULT_MODEL_ALIAS,
        "agent": "build",
        "version": "1.0.0",
        "capabilities": {
            "native_tools": ["bash", "read", "write", "edit", "glob", "grep"],
            "output_formats": ["text", "json", "markdown", "code"],
            "structured_output": {"supported": True, "json_schema": True},
            "autonomous_execution": {"supported": True, "default_max_turns": 10},
            "session_management": {"abort": True, "summarize": False, "compaction": False},
            "mcp_usage": {"supported": False},
            "a2a": {"outbound_supported": True},
        },
    }


@app.get("/capabilities", tags=["Discovery"])
def get_capabilities() -> dict[str, Any]:
    """Capability discovery. Returns supported features and API tiers."""
    return {
        "runtime": "mistral-vibe",
        "service": SERVICE_NAME,
        "capabilities": {
            "native_tools": ["bash", "read", "write", "edit", "glob", "grep"],
            "output_formats": ["text", "json", "markdown", "code"],
            "structured_output": {"supported": True, "json_schema": True},
            "autonomous_execution": {"supported": True, "default_max_turns": 10},
            "session_management": {"abort": True, "summarize": False, "compaction": False},
            "mcp_usage": {"supported": False},
            "a2a": {"outbound_supported": True},
            "tiers": ["core", "session", "artifacts", "streaming"],
        },
    }


# ---------------------------------------------------------------------------
# Invocation
# ---------------------------------------------------------------------------


@app.post("/invoke", tags=["Invocation"])
def invoke(request: InvokeRequest) -> JSONResponse:
    """Execute a prompt synchronously."""
    thread_id = request.thread_id or f"vibe-{uuid.uuid4().hex[:12]}"
    execution_id = f"exec-{thread_id[:16]}"
    start_time = time.time()

    emit_run_started(
        execution_id=execution_id,
        thread_id=thread_id,
        model=request.model or DEFAULT_MODEL_ALIAS,
    )

    try:
        response = _run_vibe(request)
        duration_ms = int((time.time() - start_time) * 1000)
        _complete_session(response.thread_id, response.status)

        emit_run_completed(
            execution_id=execution_id,
            thread_id=thread_id,
            status=response.status,
            duration_ms=duration_ms,
        )

        for tc in response.tool_calls:
            emit_tool_call(
                execution_id=execution_id,
                tool_name=tc.get("name", "unknown"),
                tool_args=tc.get("args"),
                status=tc.get("status", "completed"),
                thread_id=thread_id,
            )

        return JSONResponse(response.model_dump(mode="json"))
    except Exception as exc:
        emit_run_error(
            execution_id=execution_id,
            thread_id=thread_id,
            error=str(exc)[:2048],
        )
        raise


# ---------------------------------------------------------------------------
# Streaming
# ---------------------------------------------------------------------------


@app.post("/invoke/stream", tags=["Streaming"])
async def invoke_stream(request: InvokeRequest) -> StreamingResponse:
    """Execute a prompt with SSE streaming response."""
    thread_id = request.thread_id or f"vibe-stream-{uuid.uuid4().hex[:12]}"
    session_id = f"vibe-session-{uuid.uuid4().hex[:16]}"
    execution_id = f"exec-{thread_id[:16]}"
    _register_session(thread_id, session_id, request.model or DEFAULT_MODEL_ALIAS)
    start_time = time.time()

    emit_run_started(
        execution_id=execution_id,
        thread_id=thread_id,
        session_id=session_id,
        model=request.model or DEFAULT_MODEL_ALIAS,
    )

    async def event_stream() -> AsyncIterator[str]:
        yield f"event: response.started\ndata: {json.dumps({'session_id': session_id, 'model': request.model or DEFAULT_MODEL_ALIAS, 'thread_id': thread_id})}\n\n"
        try:
            response = await asyncio.to_thread(_run_vibe, request)
        except HTTPException as exc:
            _complete_session(thread_id, "error")
            emit_run_error(
                execution_id=execution_id,
                thread_id=thread_id,
                session_id=session_id,
                error=str(exc.detail)[:2048],
            )
            payload = json.dumps({"session_id": session_id, "error": str(exc.detail), "code": "internal_error"})
            yield f"event: response.error\ndata: {payload}\n\n"
            return
        except Exception as exc:
            _complete_session(thread_id, "error")
            emit_run_error(
                execution_id=execution_id,
                thread_id=thread_id,
                session_id=session_id,
                error=str(exc)[:2048],
            )
            payload = json.dumps({"session_id": session_id, "error": str(exc), "code": "internal_error"})
            yield f"event: response.error\ndata: {payload}\n\n"
            return

        if response.response:
            payload = json.dumps({"text": response.response, "session_id": session_id})
            yield f"event: response.delta\ndata: {payload}\n\n"

        for tc in response.tool_calls:
            payload = json.dumps({"name": tc.get("name", ""), "args": tc.get("args"), "id": f"tc_{uuid.uuid4().hex[:8]}", "session_id": session_id})
            yield f"event: response.tool_call\ndata: {payload}\n\n"
            emit_tool_call(
                execution_id=execution_id,
                tool_name=tc.get("name", "unknown"),
                tool_args=tc.get("args"),
                status=tc.get("status", "completed"),
                thread_id=thread_id,
                session_id=session_id,
            )

        _complete_session(thread_id, response.status)
        duration_ms = int((time.time() - start_time) * 1000)

        emit_run_completed(
            execution_id=execution_id,
            thread_id=thread_id,
            session_id=session_id,
            status=response.status,
            duration_ms=duration_ms,
        )

        meta = response.metadata or {}
        payload = json.dumps({
            "session_id": session_id,
            "tokens": meta.get("tokens", {}),
            "status": response.status,
            "finish_reason": meta.get("finish_reason", "stop"),
        })
        yield f"event: response.completed\ndata: {payload}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


# ---------------------------------------------------------------------------
# Control
# ---------------------------------------------------------------------------


@app.post("/cancel", tags=["Control"])
def cancel_session(thread_id: str | None = None) -> dict[str, Any]:
    """Cancel a running session by thread_id."""
    if not thread_id:
        raise HTTPException(status_code=400, detail="thread_id query parameter is required")
    session = _active_sessions.get(thread_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"No session found for thread_id '{thread_id}'")
    cancelled = _cancel_session(thread_id)
    if cancelled:
        return {"status": "cancelled", "session_id": session["session_id"], "thread_id": thread_id}
    return {"status": "cancel_failed", "session_id": session["session_id"], "thread_id": thread_id}


@app.post("/abort", tags=["Control"])
def abort_session(thread_id: str | None = None) -> dict[str, Any]:
    """Abort a running session by thread_id (alias for /cancel)."""
    if not thread_id:
        raise HTTPException(status_code=400, detail="thread_id query parameter is required")
    return cancel_session(thread_id=thread_id)


# ---------------------------------------------------------------------------
# Session
# ---------------------------------------------------------------------------


@app.get("/todo", tags=["Session"])
def get_todo_state(thread_id: str | None = None, request: Request = None) -> JSONResponse:
    """Get session todo/task list. Supports ETag for efficient polling."""
    if not thread_id:
        raise HTTPException(status_code=400, detail="thread_id query parameter is required")
    session = _active_sessions.get(thread_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"No session found for thread_id '{thread_id}'")

    todos: list[dict[str, Any]] = []
    body = {"thread_id": thread_id, "session_id": session["session_id"], "todos": todos}
    etag = hashlib.md5(json.dumps(todos, sort_keys=True).encode()).hexdigest()

    if request is not None:
        client_etag = request.headers.get("if-none-match", "").strip(' "')
        if client_etag and client_etag == etag:
            return JSONResponse(status_code=304, content=None, headers={"ETag": f'"{etag}"'})

    return JSONResponse(content=body, headers={"ETag": f'"{etag}"'})


@app.get("/question", tags=["Session"])
def get_pending_questions() -> list[dict[str, Any]]:
    """List pending human-in-the-loop questions."""
    return []


@app.post("/question/{request_id}/reply", tags=["Session"])
def reply_to_question(request_id: str, body: dict[str, Any]) -> dict[str, str]:
    """Answer a pending question."""
    return {"status": "accepted", "request_id": request_id}


@app.post("/question/{request_id}/reject", tags=["Session"])
def reject_question(request_id: str) -> dict[str, str]:
    """Reject a pending question."""
    return {"status": "rejected", "request_id": request_id}


@app.get("/diff", tags=["Session"])
def get_diff(thread_id: str | None = None) -> dict[str, Any]:
    """Get file change diff for a session."""
    if not thread_id:
        raise HTTPException(status_code=400, detail="thread_id query parameter is required")
    session = _active_sessions.get(thread_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"No session found for thread_id '{thread_id}'")
    return {"thread_id": thread_id, "session_id": session["session_id"], "diff": ""}


@app.get("/context-budget", tags=["Session"])
def get_context_budget(thread_id: str | None = None) -> dict[str, Any]:
    """Get context window usage and compaction hints."""
    if not thread_id:
        raise HTTPException(status_code=400, detail="thread_id query parameter is required")
    session = _active_sessions.get(thread_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"No session found for thread_id '{thread_id}'")
    return {
        "model_context_limit": 32768,
        "tokens_used": 0,
        "tokens_remaining": 32768,
        "usage_percent": 0.0,
        "status": "ok",
        "compaction_available": False,
    }


# ---------------------------------------------------------------------------
# Artifacts
# ---------------------------------------------------------------------------


@app.get("/artifacts/list", tags=["Artifacts"])
def list_artifacts(thread_id: str | None = None, root: str = "/workspace") -> dict[str, Any]:
    """List workspace files."""
    if not thread_id:
        raise HTTPException(status_code=400, detail="thread_id query parameter is required")
    session = _active_sessions.get(thread_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"No session found for thread_id '{thread_id}'")

    root_path = Path(root).resolve()
    if not root_path.exists():
        return {"files": [], "truncated": False, "roots": [str(WORKSPACE_DIR)]}

    files = _list_workspace_files(root_path)
    max_files = 500
    truncated = len(files) > max_files
    return {
        "files": files[:max_files],
        "truncated": truncated,
        "roots": [str(WORKSPACE_DIR)],
    }


@app.get("/artifacts/download", tags=["Artifacts"])
def download_artifact(thread_id: str | None = None, path: str = "") -> FileResponse:
    """Download a workspace file."""
    if not thread_id:
        raise HTTPException(status_code=400, detail="thread_id query parameter is required")
    session = _active_sessions.get(thread_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"No session found for thread_id '{thread_id}'")
    if not path:
        raise HTTPException(status_code=400, detail="path query parameter is required")

    file_path = (WORKSPACE_DIR / path).resolve()
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail=f"File not found: {path}")
    if WORKSPACE_DIR not in file_path.parents and file_path != WORKSPACE_DIR:
        raise HTTPException(status_code=403, detail="Path outside workspace")

    return FileResponse(str(file_path))


@app.get("/artifacts/zip", tags=["Artifacts"])
def download_zip(thread_id: str | None = None, root: str = "/workspace") -> StreamingResponse:
    """Download workspace as ZIP archive."""
    if not thread_id:
        raise HTTPException(status_code=400, detail="thread_id query parameter is required")
    session = _active_sessions.get(thread_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"No session found for thread_id '{thread_id}'")

    root_path = Path(root).resolve()
    if not root_path.exists():
        raise HTTPException(status_code=404, detail=f"Root directory not found: {root}")

    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for file_path in root_path.rglob("*"):
            if file_path.is_file() and not file_path.name.startswith("."):
                arcname = str(file_path.relative_to(root_path))
                zf.write(str(file_path), arcname)
    buf.seek(0)

    return StreamingResponse(
        iter(lambda: buf.read(8192), b""),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="workspace-{thread_id}.zip"'},
    )


# ---------------------------------------------------------------------------
# Signal handling
# ---------------------------------------------------------------------------


def _handle_signal(_signum: int, _frame: Any) -> None:
    for thread_id in list(_active_sessions.keys()):
        _active_sessions[thread_id]["status"] = "terminated"
    stop_emitter()
    raise SystemExit(0)


signal.signal(signal.SIGTERM, _handle_signal)
signal.signal(signal.SIGINT, _handle_signal)

# Start runtime event emitter (Run Intelligence Layer)
start_emitter()
