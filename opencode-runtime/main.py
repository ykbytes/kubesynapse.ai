"""OpenCode Runtime — FastAPI application, routes, and lifespan."""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import mimetypes
import os
import shutil
import signal
import subprocess
import threading
import uuid
from collections.abc import AsyncIterator
from pathlib import Path, PurePosixPath
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Re-exports for backward compatibility (tests import from main.py)
# ---------------------------------------------------------------------------
from config import (  # noqa: F401 — re-exported
    A2A_ALLOWED_CALLERS,
    A2A_ALLOWED_CALLERS_ENV,
    AGENT_SELECTION_MODE,
    AGENT_SKILL_FILES_ENV,
    ARTIFACT_COLLECTION_MAX_FILES,
    AUTONOMOUS_MAX_RETRIES,
    AUTONOMOUS_MAX_TURNS,
    COMPACTION_AGGRESSIVE_THRESHOLD,
    COMPACTION_PRUNE_THRESHOLD,
    COMPACTION_TOKEN_THRESHOLD,
    DEFAULT_AGENT,
    DEFAULT_MODEL,
    DEFAULT_PROVIDER,
    HOME_DIR,
    MAX_PROMPT_CHARS,
    MEMORY_DIR,
    MEMORY_ENABLED,
    MODEL_CONTEXT_LIMIT,
    NATIVE_TOOL_NAMES,
    OPENCODE_BIN,
    OPENCODE_CONFIG_DIR,
    OPENCODE_RUNTIME_CONFIG_FILES_ENV,
    OPENCODE_SERVER_HOST,
    OPENCODE_SERVER_PORT,
    OPENCODE_WORKDIR,
    SERVICE_NAME,
    SERVICE_NAMESPACE,
    SESSION_MAX_ENTRIES,
    STRUCTURED_OUTPUT_RETRY_COUNT,
    TASK_TYPE_AGENT_MAP,
    WORKSPACE_SNAPSHOT_DIR,
    WORKSPACE_SNAPSHOT_ENABLED,
    _parse_json_env,
    _safe_float,
    _safe_int,
    logger,
    server_base_url,
)
from tracing import (  # noqa: F401 — re-exported
    StatusCode,
    _OTEL_AVAILABLE,
    get_tracer,
    init_tracing,
)
from utils import (  # noqa: F401 — re-exported
    dedupe_items,
    normalize_identifier,
    normalize_relative_path,
    path_is_within,
    serialize_file_content,
    sse_event,
    truncate_text,
)
from prompts import (  # noqa: F401 — re-exported
    AUTONOMY_CONTINUATION_PROMPT,
    AUTONOMY_SYSTEM_PROMPT,
    CONTEXT_AWARE_CONTINUATION_PROMPTS,
    FORMAT_INSTRUCTIONS,
    TASK_TYPE_PROMPTS,
    build_format_system_prompt,
    build_handoff_resumption_prompt,
    build_recovery_prompt,
    combine_system_prompt,
    format_memory_context,
    format_team_context_system_prompt,
    format_workspace_system_prompt,
    get_continuation_prompt,
    get_task_type_prompt,
)
from models import InvokeRequest, InvokeResponse  # noqa: F401 — re-exported
from session import SESSION_REGISTRY, SessionRegistry  # noqa: F401 — re-exported
from skills import (  # noqa: F401 — re-exported
    SKILL_RUNTIME_CONFIG,
    build_generated_config,
    build_mcp_config,
    build_shared_mcp_config,
    configure_git_credentials,
    ensure_runtime_directories,
    load_opencode_sidecars,
    materialize_opencode_config_files,
    materialize_skill_files,
    parse_skill_frontmatter,
)
from opencode_client import (  # noqa: F401 — re-exported
    _send_prompt_with_session_recovery,
    abort_session,
    build_model_payload,
    create_remote_session,
    ensure_remote_session,
    ensure_server_running,
    get_session_diff,
    get_session_messages,
    get_session_status,
    get_session_todos,
    init_session,
    list_pending_questions,
    reject_question,
    reply_to_question,
    runtime_http_client,
    send_prompt,
    summarize_session,
    wait_for_session_idle,
)
from analysis import (  # noqa: F401 — re-exported
    _ITER_ARTIFACT_MAX_DEPTH,
    _KEYWORD_PATTERNS,
    _build_response_metadata,
    _compile_keyword_patterns,
    _extract_structured_output,
    _iter_artifact_paths,
    _select_agent_simple,
    build_compaction_hints,
    build_json_output_schema,
    build_prompt_format,
    check_context_overflow,
    classify_error_type,
    classify_task_type,
    compute_context_budget,
    compute_context_priority,
    derive_task_status,
    detect_anti_patterns,
    detect_completion_status,
    detect_task_errors,
    estimate_message_tokens,
    extract_artifacts_from_messages,
    extract_response_text,
    extract_text_from_parts,
    extract_tool_calls_from_messages,
    get_latest_assistant_payload,
    recommend_compaction_strategy,
    runtime_capabilities,
    select_agent_for_prompt,
)
from invoke import (  # noqa: F401 — re-exported
    StreamCallback,
    a2a_response_metadata,
    build_invoke_warnings,
    invoke_opencode,
    resolve_working_directory,
    validate_inbound_a2a_request,
)
from memory import (  # noqa: F401 — re-exported
    MEMORY_ENTRY_TYPES,
    SESSION_MEMORY,
    SessionMemory,
    build_handoff_entry,
    build_task_summary_entry,
)
from workspace import (  # noqa: F401 — re-exported
    capture_workspace_snapshot,
    get_or_refresh_snapshot,
)
from supervisor import (
    SUPERVISOR_MAX_RESTARTS,
    _runtime_lock,
    _runtime_process,
    _runtime_ready,
    _run_process_supervisor,
    _shutdown_event,
    _sigterm_handler,
    _start_opencode_process,
    _supervisor_restart_count,
    build_server_env,
    is_shutting_down,
    validate_runtime_startup,
    wait_for_server_ready,
)

# Backward compat: tests and old code may reference _path_is_within
_path_is_within = path_is_within

# Backward compat: mutable globals need to be visible from this module
import supervisor as _supervisor_mod  # noqa: E402


def resolve_download_path(raw_value: str) -> Path:
    """Validate and resolve an artifact download path."""
    candidate = str(raw_value or "").strip()
    if not candidate:
        raise HTTPException(status_code=400, detail="artifact download path must not be blank")
    target = Path(candidate).expanduser().resolve()
    allowed_roots = [Path(OPENCODE_WORKDIR).resolve(), Path(HOME_DIR).resolve(), Path("/tmp").resolve()]
    if not any(path_is_within(target, root) for root in allowed_roots):
        raise HTTPException(status_code=400, detail=f"artifact path '{raw_value}' is outside the allowed runtime roots")
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail=f"artifact path '{raw_value}' does not exist")
    return target


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------


@contextlib.asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    signal.signal(signal.SIGTERM, _sigterm_handler)
    signal.signal(signal.SIGINT, _sigterm_handler)

    init_tracing()

    ensure_runtime_directories()
    configure_git_credentials()
    validate_runtime_startup()
    config_files = materialize_opencode_config_files()
    skill_files, skill_warnings = materialize_skill_files()
    sidecars = load_opencode_sidecars()
    generated_config, generated_warnings = build_generated_config(sidecars)

    env = build_server_env(generated_config)
    process = _start_opencode_process(env)

    wait_for_server_ready(process)
    with _runtime_lock:
        _supervisor_mod._runtime_process = process
        _supervisor_mod._runtime_ready = True
        SKILL_RUNTIME_CONFIG.update(
            {
                "skillFiles": skill_files,
                "warnings": dedupe_items(skill_warnings + generated_warnings),
                "configFiles": config_files,
                "mcpSidecars": sidecars,
            }
        )

    supervisor_thread = threading.Thread(
        target=_run_process_supervisor,
        args=(env,),
        daemon=True,
        name="opencode-supervisor",
    )
    supervisor_thread.start()

    try:
        yield
    finally:
        _shutdown_event.set()
        supervisor_thread.join(timeout=5)

        with _runtime_lock:
            _supervisor_mod._runtime_ready = False
            _supervisor_mod._runtime_process = None
        if process.poll() is None:
            logger.info("Terminating OpenCode subprocess (PID %d).", process.pid)
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                logger.warning("OpenCode subprocess did not exit; killing.")
                process.kill()
                process.wait(timeout=5)
        logger.info("OpenCode runtime shutdown complete.")


# ---------------------------------------------------------------------------
# FastAPI app + routes
# ---------------------------------------------------------------------------

app = FastAPI(title="OpenCode Runtime", version="1.0.0", lifespan=lifespan)


@app.middleware("http")
async def add_request_id(request: Request, call_next):  # type: ignore[no-untyped-def]
    request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
    response = await call_next(request)
    response.headers["x-request-id"] = request_id
    return response


@app.get("/health")
def health() -> dict[str, Any]:
    total_sessions = SESSION_REGISTRY.size
    stale_sessions = SESSION_REGISTRY.stale_count(3600)
    status = "shutting_down" if is_shutting_down() else ("healthy" if _supervisor_mod._runtime_ready else "starting")
    return {
        "status": status,
        "runtime": "opencode",
        "service": SERVICE_NAME,
        "namespace": SERVICE_NAMESPACE,
        "provider": DEFAULT_PROVIDER,
        "agent": DEFAULT_AGENT,
        "sessions": {
            "total": total_sessions,
            "active": total_sessions - stale_sessions,
            "stale": stale_sessions,
            "at_capacity": total_sessions >= SESSION_MAX_ENTRIES,
        },
        "skills": {
            "count": len(SKILL_RUNTIME_CONFIG.get("skillFiles") or []),
            "files": SKILL_RUNTIME_CONFIG.get("skillFiles") or [],
            "warnings": SKILL_RUNTIME_CONFIG.get("warnings") or [],
        },
        "supervisor": {
            "restart_count": _supervisor_mod._supervisor_restart_count,
            "max_restarts": SUPERVISOR_MAX_RESTARTS,
        },
        "capabilities": runtime_capabilities(),
    }


@app.get("/ready")
def ready() -> dict[str, Any]:
    ensure_runtime_directories()
    if Path(OPENCODE_BIN).is_absolute():
        resolved_binary = OPENCODE_BIN if Path(OPENCODE_BIN).exists() else None
    else:
        resolved_binary = shutil.which(OPENCODE_BIN)
    if not resolved_binary:
        raise HTTPException(status_code=503, detail=f"opencode binary '{OPENCODE_BIN}' is not available on PATH")
    ensure_server_running()
    opencode_server_healthy = False
    try:
        with httpx.Client(timeout=5.0) as probe:
            resp = probe.get(f"http://{OPENCODE_SERVER_HOST}:{OPENCODE_SERVER_PORT}/session")
            opencode_server_healthy = resp.status_code < 500
    except Exception:
        pass
    session_registry_writable = False
    try:
        session_registry_writable = os.access(SESSION_REGISTRY.path.parent, os.W_OK)
    except Exception:
        pass
    subprocess_alive = False
    with _runtime_lock:
        proc = _supervisor_mod._runtime_process
    if proc is not None and proc.poll() is None:
        subprocess_alive = True
    return {
        "status": "ready",
        "runtime": "opencode",
        "opencode_binary": OPENCODE_BIN,
        "opencode_binary_path": resolved_binary,
        "opencode_server_healthy": opencode_server_healthy,
        "subprocess_alive": subprocess_alive,
        "session_registry_writable": session_registry_writable,
        "config_root": OPENCODE_CONFIG_DIR,
        "workspace_root": OPENCODE_WORKDIR,
        "config_files": SKILL_RUNTIME_CONFIG.get("configFiles") or [],
        "skill_files": SKILL_RUNTIME_CONFIG.get("skillFiles") or [],
        "mcp_sidecars": SKILL_RUNTIME_CONFIG.get("mcpSidecars") or [],
        "capabilities": runtime_capabilities(),
    }


@app.get("/capabilities")
def capabilities() -> dict[str, Any]:
    return {
        "runtime": "opencode",
        "service": SERVICE_NAME,
        "capabilities": runtime_capabilities(),
    }


# ---------------------------------------------------------------------------
# §3.6 — Runtime contract /info endpoint
# ---------------------------------------------------------------------------
RUNTIME_CONTRACT_VERSION = "v1alpha1"


@app.get("/info")
def info() -> dict[str, Any]:
    """Declare runtime contract version and metadata for operator compatibility checks."""
    return {
        "runtime": "opencode",
        "contract_version": RUNTIME_CONTRACT_VERSION,
        "service": SERVICE_NAME,
        "namespace": SERVICE_NAMESPACE,
        "provider": DEFAULT_PROVIDER,
        "model": DEFAULT_MODEL,
        "agent": DEFAULT_AGENT,
        "capabilities": runtime_capabilities(),
        "supervisor": {
            "restart_count": _supervisor_mod._supervisor_restart_count,
            "max_restarts": SUPERVISOR_MAX_RESTARTS,
        },
        "tracing": {
            "enabled": get_tracer() is not None,
            "otel_available": _OTEL_AVAILABLE,
        },
    }


@app.post("/invoke", response_model=InvokeResponse)
def invoke(request: InvokeRequest) -> InvokeResponse:
    """Invoke the OpenCode agent with optional OTEL tracing."""
    tracer = get_tracer()
    if tracer is not None:
        with tracer.start_as_current_span(
            "opencode.invoke",
            attributes={
                "agent.name": SERVICE_NAME,
                "agent.namespace": SERVICE_NAMESPACE,
                "agent.model": request.model or DEFAULT_MODEL,
                "agent.autonomous": request.autonomous,
                "agent.output_format": request.output_format or "",
            },
        ) as span:
            try:
                result = invoke_opencode(request)
                span.set_attribute("agent.status", result.status)
                return result
            except Exception as exc:
                if _OTEL_AVAILABLE and StatusCode is not None:
                    span.set_status(StatusCode.ERROR, str(exc))
                raise
    return invoke_opencode(request)


@app.post("/cancel")
def cancel_session(thread_id: str | None = None) -> dict[str, Any]:
    """Cancel/abort a running session by thread_id."""
    if not thread_id:
        raise HTTPException(status_code=400, detail="thread_id query parameter is required")
    session_id = SESSION_REGISTRY.get(thread_id)
    if session_id is None:
        raise HTTPException(status_code=404, detail=f"No session found for thread_id '{thread_id}'")
    aborted = abort_session(session_id)
    if aborted:
        return {"status": "cancelled", "session_id": session_id, "thread_id": thread_id}
    return {"status": "cancel_failed", "session_id": session_id, "thread_id": thread_id}


@app.get("/todo")
def get_todo_state(thread_id: str | None = None, request: Request = None) -> JSONResponse:  # type: ignore[assignment]
    """Return the current OpenCode todo list for a logical thread.

    Supports conditional requests via ETag / If-None-Match so UI polling
    is cheap when the todo list hasn't changed.
    """
    if not thread_id:
        raise HTTPException(status_code=400, detail="thread_id query parameter is required")
    session_id = SESSION_REGISTRY.get(thread_id)
    if session_id is None:
        raise HTTPException(status_code=404, detail=f"No session found for thread_id '{thread_id}'")
    try:
        todos = get_session_todos(session_id)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Failed to fetch session todos: {exc}") from exc

    body = {"thread_id": thread_id, "session_id": session_id, "sessionID": session_id, "todos": todos}
    etag = hashlib.md5(json.dumps(todos, sort_keys=True).encode()).hexdigest()  # noqa: S324
    if request is not None:
        client_etag = request.headers.get("if-none-match", "").strip(' "')
        if client_etag and client_etag == etag:
            return JSONResponse(status_code=304, content=None, headers={"ETag": f'"{etag}"'})
    return JSONResponse(content=body, headers={"ETag": f'"{etag}"'})


@app.get("/question")
def get_pending_questions() -> list[dict[str, Any]]:
    """Return all pending question requests from the OpenCode server."""
    ensure_server_running()
    return list_pending_questions()


class QuestionReplyBody(BaseModel):
    answers: list[list[str]]


@app.post("/question/{request_id}/reply")
def post_question_reply(request_id: str, body: QuestionReplyBody) -> dict[str, Any]:
    """Reply to a pending question request."""
    ensure_server_running()
    ok = reply_to_question(request_id, body.answers)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Question '{request_id}' not found or reply failed")
    return {"status": "replied", "request_id": request_id}


@app.post("/question/{request_id}/reject")
def post_question_reject(request_id: str) -> dict[str, Any]:
    """Reject a pending question request."""
    ensure_server_running()
    ok = reject_question(request_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Question '{request_id}' not found or reject failed")
    return {"status": "rejected", "request_id": request_id}


@app.get("/diff")
def get_diff(thread_id: str | None = None) -> dict[str, Any]:
    """Return the unified diff of file changes for the given thread."""
    if not thread_id:
        raise HTTPException(status_code=400, detail="thread_id query parameter is required")
    session_id = SESSION_REGISTRY.get(thread_id)
    if session_id is None:
        raise HTTPException(status_code=404, detail=f"No session found for thread_id '{thread_id}'")
    try:
        diff_text = get_session_diff(session_id)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Failed to fetch session diff: {exc}") from exc
    return {"thread_id": thread_id, "session_id": session_id, "diff": diff_text}


@app.get("/context-budget")
def context_budget(thread_id: str | None = None) -> dict[str, Any]:
    """Return context budget telemetry for the given thread."""
    if not thread_id:
        raise HTTPException(status_code=400, detail="thread_id query parameter is required")
    session_id = SESSION_REGISTRY.get(thread_id)
    if session_id is None:
        raise HTTPException(status_code=404, detail=f"No session found for thread_id '{thread_id}'")
    try:
        messages = get_session_messages(session_id)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Failed to fetch session messages: {exc}") from exc
    latest = get_latest_assistant_payload(messages) if messages else None
    budget = compute_context_budget(latest or {})
    budget["session_id"] = session_id
    budget["thread_id"] = thread_id
    budget["compaction_available"] = budget.get("status") in ("warning", "critical")
    return budget


@app.post("/invoke/stream")
async def invoke_stream(request: InvokeRequest) -> StreamingResponse:
    async def event_generator() -> AsyncIterator[str]:
        thread_id = request.thread_id or str(uuid.uuid4())
        request_with_thread = request.model_copy(update={"thread_id": thread_id})
        streamed_delta_count = 0
        yield sse_event("response.started", {"thread_id": thread_id, "source": "opencode"})

        event_queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
        loop = asyncio.get_event_loop()
        stop_todo_poller = asyncio.Event()

        def _stream_callback(event_type: str, data: dict[str, Any]) -> None:
            loop.call_soon_threadsafe(event_queue.put_nowait, {"event": event_type, "data": data})

        def _run_invoke() -> InvokeResponse:
            try:
                return invoke_opencode(request_with_thread, stream_callback=_stream_callback)
            finally:
                loop.call_soon_threadsafe(event_queue.put_nowait, None)

        async def _poll_todos() -> None:
            last_signature: str | None = None
            while not stop_todo_poller.is_set():
                session_id = SESSION_REGISTRY.get(thread_id)
                if session_id:
                    try:
                        todos = await asyncio.to_thread(get_session_todos, session_id)
                        signature = json.dumps(todos, sort_keys=True)
                        if signature != last_signature:
                            last_signature = signature
                            await event_queue.put(
                                {
                                    "event": "todo.updated",
                                    "data": {
                                        "thread_id": thread_id,
                                        "session_id": session_id,
                                        "sessionID": session_id,
                                        "todos": todos,
                                        "source": "opencode",
                                    },
                                }
                            )
                    except Exception:
                        pass
                try:
                    await asyncio.wait_for(stop_todo_poller.wait(), timeout=0.5)
                except TimeoutError:
                    continue

        async def _poll_questions() -> None:
            last_ids: set[str] = set()
            while not stop_todo_poller.is_set():
                try:
                    questions = await asyncio.to_thread(list_pending_questions)
                    current_ids = {q.get("id", "") for q in questions if q.get("id")}
                    new_ids = current_ids - last_ids
                    if new_ids:
                        for q in questions:
                            if q.get("id") in new_ids:
                                await event_queue.put(
                                    {
                                        "event": "question.asked",
                                        "data": {
                                            "thread_id": thread_id,
                                            "source": "opencode",
                                            **q,
                                        },
                                    }
                                )
                    last_ids = current_ids
                except Exception:
                    pass
                try:
                    await asyncio.wait_for(stop_todo_poller.wait(), timeout=0.3)
                except TimeoutError:
                    continue

        task = asyncio.get_event_loop().run_in_executor(None, _run_invoke)
        todo_task = asyncio.create_task(_poll_todos())
        question_task = asyncio.create_task(_poll_questions())

        while True:
            try:
                item = await asyncio.wait_for(event_queue.get(), timeout=10.0)
            except TimeoutError:
                yield ": keepalive\n\n"
                continue
            if item is None:
                break
            if item.get("event") == "response.delta":
                streamed_delta_count += 1
            yield sse_event(item["event"], item["data"])

        stop_todo_poller.set()
        with contextlib.suppress(Exception):
            await todo_task
        with contextlib.suppress(Exception):
            await question_task

        # Emit todo.cleared when all todos are done/cancelled after invoke
        try:
            final_session = SESSION_REGISTRY.get(thread_id)
            if final_session:
                final_todos = await asyncio.to_thread(get_session_todos, final_session)
                if final_todos and all(
                    t.get("status") in ("completed", "cancelled") for t in final_todos
                ):
                    yield sse_event(
                        "todo.cleared",
                        {"thread_id": thread_id, "session_id": final_session, "todos": final_todos, "source": "opencode"},
                    )
        except Exception:
            pass

        try:
            response = await task
        except HTTPException as exc:
            yield sse_event("response.error", {"thread_id": thread_id, "error": str(exc.detail)})
            return
        except Exception as exc:
            yield sse_event("response.error", {"thread_id": thread_id, "error": str(exc)})
            return

        if response.response and streamed_delta_count == 0:
            yield sse_event(
                "response.delta", {"thread_id": response.thread_id, "delta": response.response, "source": "opencode"}
            )
        yield sse_event(
            "response.completed",
            {
                "thread_id": response.thread_id,
                "response": response.response,
                "model": response.model,
                "status": response.status,
                "approval_name": response.approval_name,
                "a2a": response.a2a,
                "warnings": response.warnings,
                "artifacts": response.artifacts,
                "tool_calls": response.tool_calls,
                "metadata": response.metadata,
            },
        )

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.get("/artifacts/download")
def download_artifact(path: str) -> FileResponse:
    artifact_path = resolve_download_path(path)
    media_type, _encoding = mimetypes.guess_type(artifact_path.name)
    return FileResponse(
        artifact_path,
        media_type=media_type or "application/octet-stream",
        filename=artifact_path.name,
    )


@app.get("/artifacts/list")
def list_artifacts(root: str = "") -> dict[str, Any]:
    """Walk allowed directories and return a flat list of files."""
    allowed_roots = [Path(OPENCODE_WORKDIR).resolve(), Path(HOME_DIR).resolve(), Path("/tmp").resolve()]
    if root:
        target = Path(root).expanduser().resolve()
        if not any(path_is_within(target, r) for r in allowed_roots):
            raise HTTPException(status_code=400, detail=f"root '{root}' is outside the allowed runtime roots")
        if not target.is_dir():
            raise HTTPException(status_code=404, detail=f"root '{root}' is not a directory")
        walk_roots = [target]
    else:
        walk_roots = [r for r in allowed_roots if r.is_dir()]

    files: list[dict[str, Any]] = []
    seen: set[str] = set()
    for walk_root in walk_roots:
        for dirpath, _dirnames, filenames in os.walk(walk_root):
            dp = Path(dirpath)
            if any(part.startswith(".") for part in dp.parts[len(walk_root.parts) :]):
                continue
            for fname in filenames:
                if fname.startswith("."):
                    continue
                fpath = dp / fname
                posix_path = str(PurePosixPath(fpath))
                if posix_path in seen:
                    continue
                seen.add(posix_path)
                try:
                    stat = fpath.stat()
                except OSError:
                    continue
                files.append(
                    {
                        "path": posix_path,
                        "name": fname,
                        "size": stat.st_size,
                        "modified": stat.st_mtime,
                        "directory": str(PurePosixPath(dp)),
                    }
                )
                if len(files) >= ARTIFACT_COLLECTION_MAX_FILES:
                    return {"files": files, "truncated": True, "roots": [str(PurePosixPath(r)) for r in walk_roots]}
    return {"files": files, "truncated": False, "roots": [str(PurePosixPath(r)) for r in walk_roots]}


@app.get("/artifacts/zip")
def download_artifacts_zip(root: str = "") -> StreamingResponse:
    """Create a ZIP archive of the workspace and stream it to the client."""
    import io
    import zipfile

    workdir = Path(OPENCODE_WORKDIR).resolve()
    if root:
        target = Path(root).expanduser().resolve()
        if not path_is_within(target, workdir):
            raise HTTPException(status_code=400, detail=f"root '{root}' is outside the workspace")
        if not target.is_dir():
            raise HTTPException(status_code=404, detail=f"root '{root}' is not a directory")
        walk_root = target
    else:
        walk_root = workdir

    if not walk_root.is_dir():
        raise HTTPException(status_code=404, detail="workspace directory does not exist")

    SKIP_DIRS = {".git", "node_modules", "__pycache__", ".next", ".venv", "venv", "dist", ".cache"}

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        file_count = 0
        for dirpath, dirnames, filenames in os.walk(walk_root):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
            dp = Path(dirpath)
            for fname in filenames:
                if fname.startswith("."):
                    continue
                fpath = dp / fname
                try:
                    stat = fpath.stat()
                except OSError:
                    continue
                if stat.st_size > 50 * 1024 * 1024:
                    continue
                arcname = str(fpath.relative_to(walk_root))
                zf.write(fpath, arcname)
                file_count += 1
                if file_count >= 10000:
                    break
            if file_count >= 10000:
                break

    buf.seek(0)
    zip_name = walk_root.name or "workspace"
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{zip_name}.zip"'},
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8080)
