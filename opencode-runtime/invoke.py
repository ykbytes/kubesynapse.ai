"""Core invocation logic — the autonomous multi-turn loop."""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import os
import time
import uuid
from pathlib import Path
from typing import Any

import httpx
from analysis import (
    _build_response_metadata,
    assistant_payload_has_signal,
    build_prompt_format,
    build_tool_only_response,
    check_context_overflow,
    classify_error_type,
    classify_task_type,
    compute_context_budget,
    derive_task_status,
    detect_anti_patterns,
    detect_completion_status,
    detect_task_errors,
    extract_artifacts_from_messages,
    extract_error_message,
    extract_reasoning_from_parts,
    extract_response_text,
    extract_text_from_parts,
    extract_tool_calls_from_messages,
    get_latest_assistant_payload,
    is_error_retryable,
    recommend_compaction_strategy,
    select_agent_for_prompt,
)
from config import (
    A2A_ALLOWED_CALLERS,
    A2A_ALLOWED_TARGETS,
    A2A_MAX_TIMEOUT_SECONDS,
    A2A_REQUIRE_HITL,
    API_GATEWAY_INTERNAL_URL,
    API_GATEWAY_SHARED_TOKEN,
    ARTIFACT_COLLECTION_MAX_FILES,
    AUTONOMOUS_MAX_RETRIES,
    AUTONOMOUS_MAX_TURNS,
    COMPACTION_MIN_TURN_SPACING,
    DEFAULT_AGENT,
    DEFAULT_MODEL_REF,
    DEFAULT_SYSTEM_PROMPT,
    LIVE_UPDATE_MAX_WALL_SECONDS,
    LIVE_UPDATE_TIMEOUT_SECONDS,
    MAX_COMPACTION_ATTEMPTS,
    MAX_PROMPT_CHARS,
    MAX_THREAD_ID_CHARS,
    MEMORY_ENABLED,
    OPENCODE_WORKDIR,
    SERVICE_NAME,
    SERVICE_NAMESPACE,
    SESSION_ABORT_TIMEOUT_SECONDS,
    SESSION_INIT_ON_CREATE,
    WORKSPACE_SNAPSHOT_ENABLED,
)
from fastapi import HTTPException
from memory import (
    SESSION_MEMORY,
    build_handoff_entry,
    build_task_summary_entry,
)
from models import InvokeRequest, InvokeResponse
from opencode_client import (
    abort_session,
    create_remote_session,
    ensure_server_running,
    get_session_message,
    get_session_messages,
    get_session_status,
    get_session_todos,
    init_session,
    auto_approve_pending_questions,
    send_prompt_async,
    summarize_session,
    wait_for_session_idle,
)
from prompts import (
    AUTONOMY_SYSTEM_PROMPT,
    KUBESYNAPSE_AGENT_SYSTEM_PROMPT,
    build_format_system_prompt,
    build_handoff_resumption_prompt,
    build_recovery_prompt,
    combine_system_prompt,
    format_memory_context,
    format_skills_system_prompt,
    format_team_context_system_prompt,
    format_workspace_system_prompt,
    get_continuation_prompt,
    get_task_type_prompt,
)
from sanitize_secrets import redact_secrets
from session import SESSION_REGISTRY
from skills import SKILL_RUNTIME_CONFIG
from workspace import get_or_refresh_snapshot

from hitl import hitl_gate
from utils import dedupe_items, truncate_text

logger = logging.getLogger("opencode-runtime")

_CREDENTIAL_PROXY_ENABLED = os.getenv("CREDENTIAL_PROXY_ENABLED", "false").strip().lower() in ("true", "1", "yes")
_GATEWAY_PROXY_URL = "http://127.0.0.1:8080"

StreamCallback = Any  # Callable[[str, dict[str, Any]], None] | None
LIVE_UPDATE_POLL_SECONDS = 0.08


def validate_inbound_a2a_request(request: InvokeRequest) -> None:
    """Validate that the caller is allowed to invoke this agent."""
    caller_agent_name = (request.caller_agent_name or "").strip()
    caller_agent_namespace = (request.caller_agent_namespace or "").strip()
    if not caller_agent_name and not caller_agent_namespace:
        return
    if not A2A_ALLOWED_CALLERS:
        return
    if (caller_agent_namespace, caller_agent_name) not in A2A_ALLOWED_CALLERS:
        raise HTTPException(
            status_code=403,
            detail=(
                f"Agent '{caller_agent_name}' in namespace '{caller_agent_namespace}' is not allowed "
                f"to invoke agent '{SERVICE_NAME}' in namespace '{SERVICE_NAMESPACE}'."
            ),
        )


def a2a_response_metadata(request: InvokeRequest) -> dict[str, Any] | None:
    """Build A2A response metadata if the request is from another agent."""
    if not request.caller_agent_name or not request.caller_agent_namespace:
        return None
    return {
        "callerAgent": request.caller_agent_name,
        "callerNamespace": request.caller_agent_namespace,
        "parentThreadId": request.parent_thread_id,
        "callerRequestId": request.caller_request_id,
    }


def gateway_a2a_available() -> bool:
    """Return True when the runtime can reach the internal gateway for A2A calls."""
    if _CREDENTIAL_PROXY_ENABLED:
        return True
    return bool(API_GATEWAY_INTERNAL_URL and API_GATEWAY_SHARED_TOKEN)


def validate_outbound_a2a_request(request: InvokeRequest) -> None:
    """Validate outbound A2A targets against the injected policy configuration."""
    target_agent = (request.a2a_target_agent or "").strip()
    target_namespace = (request.a2a_target_namespace or "").strip()
    if not target_agent and not target_namespace:
        return
    if not gateway_a2a_available():
        raise HTTPException(
            status_code=503,
            detail=(
                "Outbound A2A invocation is not configured for this OpenCode runtime. "
                "Internal gateway connectivity must be configured."
            ),
        )
    if not A2A_ALLOWED_TARGETS:
        raise HTTPException(
            status_code=403,
            detail=(
                "This agent has no outbound A2A targets configured. "
                "Update AgentPolicy.spec.a2a.allowedTargets to grant access."
            ),
        )
    if (target_namespace, target_agent) not in A2A_ALLOWED_TARGETS:
        raise HTTPException(
            status_code=403,
            detail=(
                f"Agent '{SERVICE_NAME}' in namespace '{SERVICE_NAMESPACE}' is not allowed to invoke "
                f"agent '{target_agent}' in namespace '{target_namespace}'."
            ),
        )
    requested_timeout = request.a2a_timeout_seconds
    if requested_timeout is not None and float(requested_timeout) > A2A_MAX_TIMEOUT_SECONDS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Requested A2A timeout {requested_timeout} exceeds policy limit of "
                f"{A2A_MAX_TIMEOUT_SECONDS} seconds."
            ),
        )


def build_outbound_a2a_thread_id(logical_thread_id: str, target_agent: str, target_namespace: str) -> str:
    """Build a stable target thread identifier for outbound A2A calls."""
    seed = f"{SERVICE_NAMESPACE}:{SERVICE_NAME}:{target_namespace}:{target_agent}:{logical_thread_id}"
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:20]
    thread_id = f"a2a-{target_namespace}-{target_agent}-{digest}"
    return thread_id[:MAX_THREAD_ID_CHARS]


def build_outbound_a2a_team_context(
    request: InvokeRequest,
    *,
    target_agent: str,
    target_namespace: str,
    target_thread_id: str,
    logical_thread_id: str,
) -> dict[str, Any] | None:
    """Build a minimal collaboration context for a delegated peer call."""
    base_context = dict(request.team_context or {})
    base_context["delegation"] = {
        "caller": {"name": SERVICE_NAME, "namespace": SERVICE_NAMESPACE, "threadId": logical_thread_id},
        "target": {"name": target_agent, "namespace": target_namespace, "threadId": target_thread_id},
        "transport": "a2a-jsonrpc",
    }
    if request.caller_agent_name and request.caller_agent_namespace:
        base_context["upstreamCaller"] = {
            "name": request.caller_agent_name,
            "namespace": request.caller_agent_namespace,
            "threadId": request.parent_thread_id,
            "requestId": request.caller_request_id,
        }
    return base_context or None


def build_gateway_a2a_jsonrpc_payload(payload: dict[str, Any], request_id: str) -> dict[str, Any]:
    KUBESYNAPSE_invoke: dict[str, Any] = {}
    thread_id = str(payload.get("thread_id") or "").strip()
    if thread_id:
        KUBESYNAPSE_invoke["threadId"] = thread_id

    for source_key, target_key in (
        ("system", "system"),
        ("model", "model"),
        ("caller_agent_name", "callerAgentName"),
        ("caller_agent_namespace", "callerAgentNamespace"),
        ("parent_thread_id", "parentThreadId"),
        ("caller_request_id", "callerRequestId"),
    ):
        value = str(payload.get(source_key) or "").strip()
        if value:
            KUBESYNAPSE_invoke[target_key] = value

    team_context = payload.get("team_context")
    if isinstance(team_context, dict) and team_context:
        KUBESYNAPSE_invoke["teamContext"] = team_context

    params: dict[str, Any] = {
        "message": {
            "messageId": request_id,
            "role": "ROLE_USER",
            "parts": [{"text": str(payload.get("prompt") or ""), "mediaType": "text/plain"}],
        }
    }
    if KUBESYNAPSE_invoke:
        params["metadata"] = {"KubeSynapseInvoke": KUBESYNAPSE_invoke}

    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": "SendMessage",
        "params": params,
    }


def extract_text_from_a2a_parts(parts: Any) -> str:
    if not isinstance(parts, list):
        return ""

    chunks: list[str] = []
    for raw_part in parts:
        if not isinstance(raw_part, dict):
            continue
        text = raw_part.get("text")
        if isinstance(text, str) and text.strip():
            chunks.append(text)
            continue
        if "data" in raw_part:
            try:
                rendered = json.dumps(raw_part.get("data"), ensure_ascii=False, default=str)
            except TypeError:
                rendered = str(raw_part.get("data"))
            if rendered.strip():
                chunks.append(rendered)
    return "\n\n".join(chunk for chunk in chunks if chunk.strip()).strip()


def extract_response_text_from_a2a_task(task: dict[str, Any]) -> str:
    artifacts = task.get("artifacts")
    if isinstance(artifacts, list):
        for artifact in artifacts:
            if not isinstance(artifact, dict):
                continue
            text = extract_text_from_a2a_parts(artifact.get("parts"))
            if text:
                return text

    status = task.get("status")
    if isinstance(status, dict):
        message = status.get("message")
        if isinstance(message, dict):
            text = extract_text_from_a2a_parts(message.get("parts"))
            if text:
                return text

    history = task.get("history")
    if isinstance(history, list):
        for message in reversed(history):
            if not isinstance(message, dict):
                continue
            role = str(message.get("role") or "").strip().upper()
            if role not in {"ROLE_AGENT", "AGENT"}:
                continue
            text = extract_text_from_a2a_parts(message.get("parts"))
            if text:
                return text

    return ""


def invoke_status_from_a2a_task(task: dict[str, Any]) -> str:
    metadata = task.get("metadata")
    if isinstance(metadata, dict):
        explicit_status = str(metadata.get("status") or "").strip()
        if explicit_status:
            return explicit_status

    state = str(((task.get("status") if isinstance(task.get("status"), dict) else {}) or {}).get("state") or "").strip()
    return {
        "TASK_STATE_COMPLETED": "completed",
        "TASK_STATE_FAILED": "failed",
        "TASK_STATE_CANCELED": "failed",
        "TASK_STATE_REJECTED": "blocked",
        "TASK_STATE_AUTH_REQUIRED": "approval_pending",
        "TASK_STATE_INPUT_REQUIRED": "blocked",
        "TASK_STATE_WORKING": "partial",
        "TASK_STATE_SUBMITTED": "partial",
    }.get(state, "completed")


def flatten_gateway_a2a_task_response(response_payload: dict[str, Any], request_id: str) -> dict[str, Any]:
    error = response_payload.get("error")
    if isinstance(error, dict):
        message = str(error.get("message") or "A2A request failed").strip() or "A2A request failed"
        raise RuntimeError(message)

    result = response_payload.get("result")
    if not isinstance(result, dict):
        raise RuntimeError("Outbound A2A target returned an invalid JSON-RPC result")

    message = result.get("message")
    if isinstance(message, dict):
        return {
            "response": extract_text_from_a2a_parts(message.get("parts")),
            "model": "",
            "status": "completed",
            "warnings": [],
            "artifacts": [],
            "tool_calls": [],
            "metadata": {},
            "thread_id": request_id,
        }

    task = result.get("task")
    if not isinstance(task, dict):
        raise RuntimeError("Outbound A2A target did not return a task or message result")

    task_metadata = task.get("metadata")
    task_metadata = task_metadata if isinstance(task_metadata, dict) else {}
    nested_metadata = task_metadata.get("metadata")
    flattened_metadata = dict(nested_metadata) if isinstance(nested_metadata, dict) else {}
    task_id = str(task.get("id") or "").strip()
    context_id = str(task.get("contextId") or "").strip()
    if task_id:
        flattened_metadata.setdefault("a2aTaskId", task_id)
    if context_id:
        flattened_metadata.setdefault("a2aContextId", context_id)

    return {
        "response": extract_response_text_from_a2a_task(task),
        "model": str(task_metadata.get("model") or ""),
        "status": invoke_status_from_a2a_task(task),
        "approval_name": task_metadata.get("approvalName"),
        "retry_after_seconds": task_metadata.get("retryAfterSeconds"),
        "warnings": list(task_metadata.get("warnings") or []),
        "artifacts": list(task.get("artifacts") or []),
        "tool_calls": list(task_metadata.get("toolCalls") or []),
        "continuity": task_metadata.get("continuity") if isinstance(task_metadata.get("continuity"), dict) else None,
        "metadata": flattened_metadata,
        "a2a": task_metadata.get("a2a") if isinstance(task_metadata.get("a2a"), dict) else None,
        "thread_id": str(task_metadata.get("threadId") or request_id or "").strip(),
    }


def invoke_gateway_a2a_target(
    target_agent: str,
    target_namespace: str,
    payload: dict[str, Any],
    request_id: str,
    timeout_seconds: float,
) -> dict[str, Any]:
    """Invoke another agent through the internal API gateway."""
    jsonrpc_payload = build_gateway_a2a_jsonrpc_payload(payload, request_id)
    with httpx.Client(
        timeout=timeout_seconds,
        transport=httpx.HTTPTransport(retries=2),
        trust_env=False,
    ) as client:
        gateway_url = _GATEWAY_PROXY_URL if _CREDENTIAL_PROXY_ENABLED else API_GATEWAY_INTERNAL_URL
        headers = {
            "A2A-Version": "1.0",
            "Accept": "application/json",
            "x-request-id": request_id,
        }
        if not _CREDENTIAL_PROXY_ENABLED:
            headers["Authorization"] = f"Bearer {API_GATEWAY_SHARED_TOKEN}"
        response = client.post(
            f"{gateway_url}/a2a/{target_agent}",
            params={"namespace": target_namespace},
            json=jsonrpc_payload,
            headers=headers,
        )
        response.raise_for_status()
        try:
            return flatten_gateway_a2a_task_response(response.json(), request_id)
        except ValueError as exc:
            raise RuntimeError("Outbound A2A target returned invalid JSON") from exc


def invoke_outbound_a2a_request(
    request: InvokeRequest,
    *,
    logical_thread_id: str,
    selected_model: str,
) -> InvokeResponse:
    """Invoke an allowed peer agent through the internal API gateway."""
    validate_outbound_a2a_request(request)
    target_agent = str(request.a2a_target_agent or "").strip()
    target_namespace = str(request.a2a_target_namespace or "").strip()
    timeout_seconds = float(request.a2a_timeout_seconds or A2A_MAX_TIMEOUT_SECONDS)
    request_id = str(request.caller_request_id or logical_thread_id or uuid.uuid4()).strip() or str(uuid.uuid4())
    target_thread_id = build_outbound_a2a_thread_id(logical_thread_id, target_agent, target_namespace)
    warnings = build_invoke_warnings(request)
    payload: dict[str, Any] = {
        "prompt": request.prompt,
        "thread_id": target_thread_id,
        "caller_agent_name": SERVICE_NAME,
        "caller_agent_namespace": SERVICE_NAMESPACE,
        "parent_thread_id": logical_thread_id,
        "caller_request_id": request_id,
        "team_context": build_outbound_a2a_team_context(
            request,
            target_agent=target_agent,
            target_namespace=target_namespace,
            target_thread_id=target_thread_id,
            logical_thread_id=logical_thread_id,
        ),
    }
    if request.system:
        payload["system"] = request.system
    if request.model:
        payload["model"] = request.model

    try:
        data = invoke_gateway_a2a_target(target_agent, target_namespace, payload, request_id, timeout_seconds)
    except httpx.HTTPStatusError as exc:
        detail = redact_secrets(exc.response.text.strip() or f"HTTP {exc.response.status_code}")
        raise HTTPException(
            status_code=502,
            detail=(
                f"Outbound A2A invocation failed for {target_namespace}/{target_agent}: "
                f"HTTP {exc.response.status_code} {detail}"
            ),
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=redact_secrets(f"Outbound A2A invocation failed for {target_namespace}/{target_agent}: {exc}"),
        ) from exc

    metadata: dict[str, Any] = {}
    raw_metadata = data.get("metadata")
    if isinstance(raw_metadata, dict):
        metadata.update(raw_metadata)
    metadata["a2aTarget"] = {
        "agent": target_agent,
        "namespace": target_namespace,
        "threadId": target_thread_id,
        "requestId": request_id,
        "transport": "a2a-jsonrpc",
        "timeoutSeconds": timeout_seconds,
    }
    return InvokeResponse(
        thread_id=logical_thread_id,
        response=str(data.get("response") or ""),
        model=str(data.get("model") or selected_model),
        status=str(data.get("status") or "completed"),
        approval_name=data.get("approval_name"),
        retry_after_seconds=data.get("retry_after_seconds"),
        a2a=a2a_response_metadata(request),
        warnings=dedupe_items(warnings + [str(item) for item in (data.get("warnings") or []) if str(item).strip()]),
        artifacts=list(data.get("artifacts") or []),
        tool_calls=list(data.get("tool_calls") or []),
        continuity=data.get("continuity") if isinstance(data.get("continuity"), dict) else None,
        metadata=metadata or None,
    )


def build_invoke_warnings(request: InvokeRequest) -> list[str]:
    """Build the initial warnings list for an invocation."""
    warnings: list[str] = []
    if request.no_session:
        warnings.append(
            "Session persistence is disabled for this invocation; the returned thread_id cannot be resumed."
        )
    warnings.extend(str(item).strip() for item in (SKILL_RUNTIME_CONFIG.get("warnings") or []) if str(item).strip())
    return dedupe_items(warnings)


def _best_warning_response(warnings: list[str]) -> str:
    """Return the most actionable warning text to surface as a fallback response."""
    for warning in warnings:
        text = str(warning or "").strip()
        if not text:
            continue
        if text.startswith("Tool error:"):
            return text
    for warning in warnings:
        text = str(warning or "").strip()
        if not text:
            continue
        if ": " in text:
            return text.split(": ", 1)[1].strip() or text
        return text
    return ""


def resolve_working_directory(raw_value: str | None) -> str:
    """Resolve and validate the working directory for an invocation."""
    root = Path(OPENCODE_WORKDIR).resolve()
    if raw_value is None or not raw_value.strip():
        return str(root)
    candidate = raw_value.strip()
    target = (root / candidate).resolve() if not Path(candidate).is_absolute() else Path(candidate).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise HTTPException(
            status_code=400, detail=f"working_directory '{raw_value}' must stay inside the OpenCode workspace"
        ) from exc
    if not target.exists() or not target.is_dir():
        raise HTTPException(
            status_code=400, detail=f"working_directory '{raw_value}' does not exist inside the OpenCode workspace"
        )
    return str(target)


def _capture_pre_compaction_state(
    session_id: str,
    messages: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Capture structured task state before compaction for recovery prompts.

    Fetches todos, recent artifacts, and the last successful tool action.
    """
    state: dict[str, Any] = {}

    # Fetch todos
    try:
        todos = get_session_todos(session_id)
        state["todos"] = todos
    except Exception:
        state["todos"] = []

    # Extract artifacts and last action from messages
    if messages is None:
        try:
            messages = get_session_messages(session_id)
        except Exception:
            messages = []

    if messages:
        from analysis import extract_artifacts_from_messages, extract_tool_calls_from_messages

        state["artifacts"] = extract_artifacts_from_messages(messages)
        tool_calls = extract_tool_calls_from_messages(messages)
        if tool_calls:
            last_successful = None
            for tc in reversed(tool_calls):
                if tc.get("status") == "completed":
                    last_successful = tc
                    break
            if last_successful:
                state["last_action"] = (
                    f"{last_successful.get('tool', '?')}: {truncate_text(str(last_successful.get('input', '')), 200)}"
                )

    return state


def _find_assistant_payload_for_parent(
    messages: list[dict[str, Any]],
    parent_message_id: str,
) -> dict[str, Any] | None:
    """Return the latest meaningful assistant payload that replies to *parent_message_id*."""
    return get_latest_assistant_payload(messages, parent_message_id=parent_message_id)


def _emit_live_snapshot_updates(
    turn: int,
    payload: dict[str, Any],
    last_snapshots: dict[str, str],
    emit: Any,
) -> None:
    """Emit snapshot-style text and reasoning updates for the current assistant payload."""
    parts = payload.get("parts")
    if not isinstance(parts, list):
        return

    filtered_parts = [item for item in parts if isinstance(item, dict)]
    text = extract_text_from_parts(filtered_parts)
    if text and text != last_snapshots.get("text", ""):
        emit("response.delta", {"turn": turn + 1, "delta": text, "source": "opencode"})
        last_snapshots["text"] = text

    reasoning = extract_reasoning_from_parts(filtered_parts)
    if reasoning and reasoning != last_snapshots.get("reasoning", ""):
        emit("response.reasoning", {"turn": turn + 1, "reasoning": reasoning})
        last_snapshots["reasoning"] = reasoning


def _is_stuck_idle_payload(payload: dict[str, Any]) -> bool:
    """Return True when an assistant payload has no progress markers and finish='unknown'.

    Used as a safety net by the live poller to avoid infinite polling when
    upstream providers (e.g. github-copilot via the credential-proxy and
    AI-SDK v6 openai-compatible) return content-less responses with
    finish='unknown'. Detected as: no extractable text, no reasoning, no
    tool calls, no patches, and finish='unknown' on the latest assistant
    info.
    """
    info = payload.get("info") if isinstance(payload.get("info"), dict) else {}
    finish = str(info.get("finish", "")).strip().lower()
    if finish not in ("unknown", ""):
        return False
    if assistant_payload_has_signal(payload):
        return False
    return True


def _send_prompt_async_with_session_recovery(
    *,
    session_id: str,
    prompt: str,
    model: str,
    system_prompt: str | None,
    prompt_format: dict[str, Any] | None,
    working_directory: str,
    agent: str,
    logical_thread_id: str,
    allow_session_recovery: bool,
    turn: int,
    emit: Any,
) -> tuple[str, dict[str, Any]]:
    """Send a streamed prompt via OpenCode's async endpoint and poll live message snapshots."""

    recovered = False
    max_idle_retries = 3
    idle_retry_count = 0

    def _do_send(sid: str) -> str:
        return send_prompt_async(
            session_id=sid,
            prompt=prompt,
            model=model,
            system_prompt=system_prompt,
            prompt_format=prompt_format,
            working_directory=working_directory,
            agent=agent,
        )

    try:
        user_message_id = _do_send(session_id)
        logger.info(
            "prompt_async sent: session=%s user_msg=%s turn=%d",
            session_id, user_message_id, turn + 1,
        )
    except HTTPException as exc:
        if exc.status_code == 404 and allow_session_recovery:
            session_id = create_remote_session(working_directory)
            SESSION_REGISTRY.set(logical_thread_id, session_id)
            user_message_id = _do_send(session_id)
            logger.info(
                "prompt_async sent (recovered session): session=%s user_msg=%s turn=%d",
                session_id, user_message_id, turn + 1,
            )
            recovered = True
        else:
            raise

    deadline = time.monotonic() + LIVE_UPDATE_TIMEOUT_SECONDS
    # Absolute cap: even with progress, never exceed this wall-clock limit per turn.
    absolute_deadline = time.monotonic() + LIVE_UPDATE_MAX_WALL_SECONDS
    last_snapshots = {"text": "", "reasoning": ""}
    latest_payload: dict[str, Any] | None = None
    # Grace period: after sending prompt_async, wait a short time before
    # treating "idle + no assistant" as a dropped prompt.  The sidecar needs
    # a moment to transition from idle → busy → generating.
    idle_grace_until = time.monotonic() + 5.0

    # Auto-approve permission questions in autonomous mode to prevent deadlock.
    # When HITL_MODE=disabled (the default for workflow agents), OpenCode's
    # "ask" permissions would block forever without this.
    from hitl import HITL_MODE
    _should_auto_approve = HITL_MODE == "disabled"

    # Track progress to extend the deadline when OpenCode is actively working.
    # If the session is "busy" (tools executing, LLM responding), we should
    # wait — the hard deadline only applies when the session stalls.
    _last_progress_message_count: int = 0

    while True:
        # Auto-approve any pending permission questions before polling messages.
        # This ensures OpenCode is never blocked waiting for tool permission.
        if _should_auto_approve:
            auto_approve_pending_questions()

        messages = get_session_messages(session_id)

        # Detect progress: if new messages appeared, the session is making progress.
        # Extend the deadline to give OpenCode more time to finish (capped by absolute max).
        if len(messages) > _last_progress_message_count:
            _last_progress_message_count = len(messages)
            deadline = min(time.monotonic() + LIVE_UPDATE_TIMEOUT_SECONDS, absolute_deadline)

        latest_payload = _find_assistant_payload_for_parent(messages, user_message_id)
        if latest_payload is not None:
            _emit_live_snapshot_updates(turn, latest_payload, last_snapshots, emit)
            completion = detect_completion_status(latest_payload)
            completed = completion in (
                "completed",
                "context_overflow",
                "error",
            )
            session_status = get_session_status(session_id)
            session_idle = str(session_status.get("type", "idle")) == "idle"
            # Safety net: if the session is idle and the latest assistant
            # message has no progress markers (finish="unknown" with empty
            # text/reasoning/tools), upstream providers like github-copilot
            # occasionally return a stuck, content-less reply. Returning the
            # best-known payload prevents the poller from spinning forever
            # waiting for content that will never arrive.
            if session_idle and completed:
                payload = dict(latest_payload)
                payload["_session_recovered"] = recovered
                payload["_live_streamed"] = bool(last_snapshots["text"] or last_snapshots["reasoning"])
                return session_id, payload
            if session_idle and _is_stuck_idle_payload(latest_payload):
                payload = dict(latest_payload)
                payload["_session_recovered"] = recovered
                payload["_live_streamed"] = bool(last_snapshots["text"] or last_snapshots["reasoning"])
                logger.warning(
                    "Session %s idle with stuck payload (finish=unknown, no content) — "
                    "returning best-known payload to avoid infinite poll.",
                    session_id,
                )
                return session_id, payload
            # Session is busy and making progress — extend deadline (capped)
            if not session_idle:
                deadline = min(time.monotonic() + LIVE_UPDATE_TIMEOUT_SECONDS, absolute_deadline)
        else:
            # No assistant reply yet.  If the session went idle, the sidecar
            # silently dropped our prompt (e.g. after a pod restart, transient
            # LLM error, or race condition).  Re-send the prompt.
            if time.monotonic() > idle_grace_until:
                session_status = get_session_status(session_id)
                if str(session_status.get("type", "idle")) == "idle":  # noqa: SIM102 — nested if for readability
                    if idle_retry_count < max_idle_retries:
                        idle_retry_count += 1
                        logger.warning(
                            "Session %s went idle without assistant reply for msg %s — "
                            "re-sending prompt (retry %d/%d)",
                            session_id, user_message_id, idle_retry_count, max_idle_retries,
                        )
                        try:
                            user_message_id = _do_send(session_id)
                            logger.info(
                                "prompt_async re-sent: session=%s user_msg=%s retry=%d",
                                session_id, user_message_id, idle_retry_count,
                            )
                        except Exception:
                            logger.warning(
                                "Failed to re-send prompt_async to %s (retry %d)",
                                session_id, idle_retry_count, exc_info=True,
                            )
                        idle_grace_until = time.monotonic() + 5.0
                        latest_payload = None
                        last_snapshots = {"text": "", "reasoning": ""}
                else:
                    # Session is busy but no assistant reply yet — extend deadline (capped)
                    deadline = min(time.monotonic() + LIVE_UPDATE_TIMEOUT_SECONDS, absolute_deadline)

        if time.monotonic() >= deadline:
            # Abort the session to stop any in-progress generation.
            # Without this, a timed-out session remains "busy" and future
            # prompt_async calls on the same session_id are silently queued
            # behind the stale generation — causing retries to hang.
            try:
                abort_session(session_id)
                logger.info("Session %s aborted after deadline timeout.", session_id)
            except Exception:
                logger.warning("Failed to abort session %s on deadline.", session_id)
            if latest_payload is not None:
                payload = dict(latest_payload)
                payload["_session_recovered"] = recovered
                payload["_live_streamed"] = bool(last_snapshots["text"] or last_snapshots["reasoning"])
                return session_id, payload
            raise HTTPException(status_code=504, detail="Timed out waiting for OpenCode response")

        time.sleep(LIVE_UPDATE_POLL_SECONDS)


def _send_prompt_with_session_recovery(
    *,
    session_id: str,
    prompt: str,
    model: str,
    system_prompt: str | None,
    prompt_format: dict[str, Any] | None,
    working_directory: str,
    agent: str,
    logical_thread_id: str,
    allow_session_recovery: bool,
    turn: int = 0,
) -> tuple[str, dict[str, Any]]:
    """Compatibility wrapper for normal invokes using the async prompt flow."""
    return _send_prompt_async_with_session_recovery(
        session_id=session_id,
        prompt=prompt,
        model=model,
        system_prompt=system_prompt,
        prompt_format=prompt_format,
        working_directory=working_directory,
        agent=agent,
        logical_thread_id=logical_thread_id,
        allow_session_recovery=allow_session_recovery,
        turn=turn,
        emit=lambda *_args, **_kwargs: None,
    )


def _send_prompt_with_live_updates_and_recovery(
    *,
    session_id: str,
    prompt: str,
    model: str,
    system_prompt: str | None,
    prompt_format: dict[str, Any] | None,
    working_directory: str,
    agent: str,
    logical_thread_id: str,
    allow_session_recovery: bool,
    turn: int,
    emit: Any,
) -> tuple[str, dict[str, Any]]:
    """Send a streamed prompt via OpenCode's async endpoint and poll live message snapshots."""
    if system_prompt:
        session_id, payload = _send_prompt_with_session_recovery(
            session_id=session_id,
            prompt=prompt,
            model=model,
            system_prompt=system_prompt,
            prompt_format=prompt_format,
            working_directory=working_directory,
            agent=agent,
            logical_thread_id=logical_thread_id,
            allow_session_recovery=allow_session_recovery,
            turn=turn,
        )
        if isinstance(payload, dict):
            payload["_live_streamed"] = False
        return session_id, payload

    return _send_prompt_async_with_session_recovery(
        session_id=session_id,
        prompt=prompt,
        model=model,
        system_prompt=system_prompt,
        prompt_format=prompt_format,
        working_directory=working_directory,
        agent=agent,
        logical_thread_id=logical_thread_id,
        allow_session_recovery=allow_session_recovery,
        turn=turn,
        emit=emit,
    )


def invoke_opencode(request: InvokeRequest, stream_callback: StreamCallback = None) -> InvokeResponse:
    """Execute the autonomous multi-turn invocation loop."""
    validate_inbound_a2a_request(request)
    logical_thread_id = request.thread_id or str(uuid.uuid4())

    approval_required = request.require_approval or bool(
        request.a2a_target_agent and request.a2a_target_namespace and A2A_REQUIRE_HITL
    )

    if approval_required:
        approval_action = request.approval_action
        if not approval_action and request.a2a_target_agent and request.a2a_target_namespace:
            approval_action = (
                f"Invoke agent {request.a2a_target_agent} in namespace {request.a2a_target_namespace} "
                f"from OpenCode agent '{SERVICE_NAME}'"
            )
        try:
            approval = hitl_gate(
                action_description=approval_action or f"Invoke OpenCode agent '{SERVICE_NAME}'",
                request_id=logical_thread_id,
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        if approval.get("decision") == "pending":
            return InvokeResponse(
                thread_id=logical_thread_id,
                response="",
                model=request.model or DEFAULT_MODEL_REF,
                status="approval_pending",
                approval_name=approval.get("approval_name"),
                a2a=a2a_response_metadata(request),
                warnings=build_invoke_warnings(request),
            )

    if request.a2a_target_agent and request.a2a_target_namespace:
        return invoke_outbound_a2a_request(
            request,
            logical_thread_id=logical_thread_id,
            selected_model=request.model or DEFAULT_MODEL_REF,
        )

    ensure_server_running()

    working_directory = resolve_working_directory(request.working_directory)
    selected_model = request.model or DEFAULT_MODEL_REF
    created_new_session = False
    if request.no_session:
        session_id = create_remote_session(working_directory)
        created_new_session = True
    else:
        existing_session = SESSION_REGISTRY.get(logical_thread_id)
        if existing_session:
            session_id = existing_session
        else:
            session_id = create_remote_session(working_directory)
            session_id = SESSION_REGISTRY.get_or_set(logical_thread_id, session_id)
            created_new_session = True

    if created_new_session and request.autonomous and SESSION_INIT_ON_CREATE:  # noqa: SIM102 — nested if for readability
        if not init_session(session_id, selected_model):
            logger.warning("Session init failed for %s", session_id)

    # --- Build enhanced system prompt with workspace and memory context ---
    pre_auth_prompt: str | None = None
    if request.pre_authorized_actions:
        allowed = ", ".join(request.pre_authorized_actions)
        pre_auth_prompt = (
            f"PRE-AUTHORIZED ACTIONS: The following actions have been pre-approved "
            f"by the workflow owner and may be executed without hesitation: {allowed}. "
            f"You do NOT need confirmation to perform these actions."
        )

    # Workspace awareness: inject pre-computed codebase context
    workspace_prompt: str | None = None
    if WORKSPACE_SNAPSHOT_ENABLED and created_new_session:
        snapshot = get_or_refresh_snapshot(working_directory)
        workspace_prompt = format_workspace_system_prompt(snapshot)

    # Cross-session memory: inject prior context
    memory_prompt: str | None = None
    has_prior_memory = False
    memory_entry_count = 0
    handoff_memory: dict[str, Any] | None = None
    if MEMORY_ENABLED and not request.no_session:
        has_prior_memory = SESSION_MEMORY.has_memory(logical_thread_id)
        if has_prior_memory:
            # Check for handoff entry (session continuity from context exhaustion)
            handoff_memory = SESSION_MEMORY.get_handoff_memory(logical_thread_id)
            if handoff_memory:
                memory_prompt = None  # Will inject via the prompt, not system prompt
            else:
                memory_entries = SESSION_MEMORY.build_memory_context(logical_thread_id)
                memory_entry_count = len(memory_entries)
                memory_prompt = format_memory_context(memory_entries)

    # Task type classification for supplementary prompt
    task_type = classify_task_type(request.prompt) if request.autonomous else "unknown"
    task_type_prompt = get_task_type_prompt(task_type) if request.autonomous else None

    # Skills awareness: inject available skill names and descriptions
    skills_prompt = format_skills_system_prompt(SKILL_RUNTIME_CONFIG.get("skillMeta"))

    system_prompt = combine_system_prompt(
        AUTONOMY_SYSTEM_PROMPT if request.autonomous else None,
        KUBESYNAPSE_AGENT_SYSTEM_PROMPT,
        DEFAULT_SYSTEM_PROMPT,
        request.system,
        pre_auth_prompt,
        workspace_prompt,
        memory_prompt,
        skills_prompt,
        task_type_prompt,
        build_format_system_prompt(request.output_format),
        format_team_context_system_prompt(request.team_context),
    )
    prompt_format = build_prompt_format(request)
    max_retries = request.max_retries if request.max_retries is not None else AUTONOMOUS_MAX_RETRIES
    effective_max_turns = request.max_turns if request.max_turns is not None else AUTONOMOUS_MAX_TURNS

    # --- Autonomous multi-turn loop ---
    all_warnings: list[str] = list(build_invoke_warnings(request))
    retries_used = 0
    last_payload: dict[str, Any] = {}
    current_prompt = request.prompt
    compaction_attempts = 0
    last_compaction_turn = -COMPACTION_MIN_TURN_SPACING
    handoff_summary: dict[str, Any] | None = None
    _resend_format = False
    current_budget_status = "ok"
    session_recovered = False

    # If resuming from handoff, inject the resumption prompt
    if handoff_memory and created_new_session:
        resumption = build_handoff_resumption_prompt(handoff_memory)
        current_prompt = f"{resumption}\n\n---\n\nNEW INSTRUCTIONS:\n{current_prompt}"
        all_warnings.append("Resuming from prior session handoff - context from previous session injected.")

    current_agent = (
        select_agent_for_prompt(
            request.prompt,
            is_first_turn=True,
            context_budget_status=current_budget_status,
            has_prior_memory=has_prior_memory,
        )
        if request.autonomous
        else DEFAULT_AGENT
    )
    if current_agent == "plan" and current_agent != DEFAULT_AGENT:
        all_warnings.append("Using plan agent for initial analysis before execution.")
    if current_agent != DEFAULT_AGENT and current_agent != "plan":
        all_warnings.append(f"Using '{current_agent}' agent based on task type classification ({task_type}).")

    def _emit(event_type: str, data: dict[str, Any]) -> None:
        if stream_callback is not None:
            with contextlib.suppress(Exception):
                stream_callback(event_type, data)

    for turn in range(effective_max_turns):
        _emit("response.turn_started", {"turn": turn + 1, "max_turns": effective_max_turns, "agent": current_agent})
        use_system = system_prompt if turn == 0 else None
        try:
            if stream_callback is not None:
                session_id, payload = _send_prompt_with_live_updates_and_recovery(
                    session_id=session_id,
                    prompt=current_prompt,
                    model=selected_model,
                    system_prompt=use_system,
                    prompt_format=prompt_format if (turn == 0 or _resend_format) else None,
                    working_directory=working_directory,
                    agent=current_agent,
                    logical_thread_id=logical_thread_id,
                    allow_session_recovery=(not request.no_session),
                    turn=turn,
                    emit=_emit,
                )
            else:
                session_id, payload = _send_prompt_with_session_recovery(
                    session_id=session_id,
                    prompt=current_prompt,
                    model=selected_model,
                    system_prompt=use_system,
                    prompt_format=prompt_format if (turn == 0 or _resend_format) else None,
                    working_directory=working_directory,
                    agent=current_agent,
                    logical_thread_id=logical_thread_id,
                    allow_session_recovery=(not request.no_session),
                    turn=turn,
                )
            recovered = bool(payload.pop("_session_recovered", False)) if isinstance(payload, dict) else False
            live_streamed = bool(payload.pop("_live_streamed", False)) if isinstance(payload, dict) else False
            session_recovered = session_recovered or recovered
        except httpx.HTTPError as exc:
            is_permanent = (
                isinstance(exc, httpx.HTTPStatusError)
                and exc.response.status_code < 500
                and exc.response.status_code not in (408, 429)
            )
            if is_permanent or retries_used >= max_retries:
                raise HTTPException(
                    status_code=502,
                    detail=f"OpenCode invocation failed after {retries_used} retries: {exc}",
                ) from exc
            retries_used += 1
            _emit(
                "response.error_recovery",
                {"turn": turn + 1, "error_type": "http", "retry": retries_used, "max_retries": max_retries},
            )
            all_warnings.append(f"Turn {turn + 1}: HTTP error '{exc}', retrying ({retries_used}/{max_retries})")
            recovery_note = (
                f"[Note: the previous request encountered a transient error ({type(exc).__name__}). "
                f"Check whether the previous operation partially completed before retrying. "
                f"If files were partially written or commands partially executed, verify their "
                f"state before continuing.]\n\n"
            )
            current_prompt = truncate_text(f"{recovery_note}{current_prompt}", MAX_PROMPT_CHARS)
            continue

        last_payload = payload
        completion = detect_completion_status(payload)
        _resend_format = False

        # Update context budget status for prompt selection
        turn_budget = compute_context_budget(payload)
        current_budget_status = turn_budget.get("status", "ok")

        turn_text = extract_response_text(payload).strip()
        _emit(
            "response.turn_completed",
            {
                "turn": turn + 1,
                "status": completion,
                "response_length": len(turn_text),
                "context_budget_status": current_budget_status,
            },
        )
        if turn_text and not live_streamed:
            _emit("response.delta", {"turn": turn + 1, "delta": turn_text, "source": "opencode"})

        # Emit reasoning/thinking content if present
        parts = payload.get("parts")
        if isinstance(parts, list):
            if not live_streamed:
                reasoning_text = extract_reasoning_from_parts(parts)
                if reasoning_text:
                    _emit("response.reasoning", {"turn": turn + 1, "reasoning": reasoning_text})

            # Emit structured tool call and patch events
            for part in parts:
                if not isinstance(part, dict):
                    continue
                part_type = part.get("type")
                if part_type == "tool":
                    state = part.get("state") or {}
                    if isinstance(state, dict):
                        _emit("response.tool_call", {
                            "turn": turn + 1,
                            "tool": str(part.get("tool", "")),
                            "status": str(state.get("status", "unknown")),
                            "input": state.get("input"),
                            "output": truncate_text(str(state.get("output", "")), 4000),
                            "source": "opencode",
                        })
                elif part_type == "patch":
                    _emit("response.patch", {
                        "turn": turn + 1,
                        "files": part.get("files") or [],
                        "source": "opencode",
                    })

        if current_agent == "plan" and completion in ("completed", "incomplete"):
            current_agent = DEFAULT_AGENT
            if completion == "completed":
                all_warnings.append("Plan phase completed, switching to build agent for execution.")
                current_prompt = (
                    "Now execute the plan you just created. For each step:\n"
                    "1. Implement the step completely — do not skip ahead.\n"
                    "2. Verify it works (read files back, run code, check output).\n"
                    "3. Fix any issues before moving to the next step.\n"
                    "4. Update the todo list to mark the step complete.\n"
                    "After all steps: run the full test suite or verify the overall "
                    "result meets the original objective."
                )
                continue

        _can_compact = (
            compaction_attempts < MAX_COMPACTION_ATTEMPTS
            and (turn - last_compaction_turn) >= COMPACTION_MIN_TURN_SPACING
        )

        # --- Graduated compaction logic ---
        if completion == "context_overflow" and _can_compact:
            compaction_attempts += 1
            last_compaction_turn = turn
            _emit(
                "response.compaction",
                {
                    "turn": turn + 1,
                    "reason": "context_overflow",
                    "attempt": compaction_attempts,
                    "max": MAX_COMPACTION_ATTEMPTS,
                },
            )

            # Capture state before compaction for structured recovery
            pre_state = _capture_pre_compaction_state(session_id)

            if summarize_session(session_id, model_ref=selected_model):
                all_warnings.append(
                    f"Turn {turn + 1}: context overflow detected, triggered compaction ({compaction_attempts}/{MAX_COMPACTION_ATTEMPTS})."
                )
                wait_for_session_idle(session_id, timeout_seconds=SESSION_ABORT_TIMEOUT_SECONDS)
                # Use structured recovery prompt
                current_prompt = build_recovery_prompt(pre_state)
                continue
            all_warnings.append(f"Turn {turn + 1}: context overflow, compaction failed.")

        if completion == "completed":
            break

        # Proactive compaction with graduated strategy
        if _can_compact and check_context_overflow(payload):
            strategy = recommend_compaction_strategy(turn_budget)
            if strategy in ("summarize", "aggressive"):
                compaction_attempts += 1
                last_compaction_turn = turn
                _emit(
                    "response.compaction",
                    {
                        "turn": turn + 1,
                        "reason": "proactive",
                        "strategy": strategy,
                        "attempt": compaction_attempts,
                        "max": MAX_COMPACTION_ATTEMPTS,
                    },
                )

                # Capture state and hints
                pre_state = _capture_pre_compaction_state(session_id)

                if summarize_session(session_id, model_ref=selected_model):
                    all_warnings.append(
                        f"Turn {turn + 1}: proactively triggered {strategy} compaction ({compaction_attempts}/{MAX_COMPACTION_ATTEMPTS})."
                    )
                    wait_for_session_idle(session_id, timeout_seconds=SESSION_ABORT_TIMEOUT_SECONDS)
                    current_prompt = build_recovery_prompt(pre_state)
                    continue
            elif strategy == "prune_outputs":
                all_warnings.append(
                    f"Turn {turn + 1}: context usage high — prune_outputs strategy recommended but continuing."
                )

        if completion == "error":
            error_type = classify_error_type(payload)
            retryable_error = is_error_retryable(payload)
            error_message = truncate_text(extract_error_message(payload), 240)
            if error_type == "context_overflow" and _can_compact:
                compaction_attempts += 1
                last_compaction_turn = turn
                _emit(
                    "response.compaction",
                    {
                        "turn": turn + 1,
                        "reason": "error_overflow",
                        "attempt": compaction_attempts,
                        "max": MAX_COMPACTION_ATTEMPTS,
                    },
                )
                pre_state = _capture_pre_compaction_state(session_id)
                if summarize_session(session_id, model_ref=selected_model):
                    all_warnings.append(
                        f"Turn {turn + 1}: context overflow error, compacting ({compaction_attempts}/{MAX_COMPACTION_ATTEMPTS})."
                    )
                    wait_for_session_idle(session_id, timeout_seconds=SESSION_ABORT_TIMEOUT_SECONDS)
                    current_prompt = build_recovery_prompt(pre_state)
                    continue
            if error_type == "structured_output" and retries_used < max_retries:
                retries_used += 1
                _resend_format = True
                _emit(
                    "response.error_recovery",
                    {
                        "turn": turn + 1,
                        "error_type": "structured_output",
                        "retry": retries_used,
                        "max_retries": max_retries,
                    },
                )
                all_warnings.append(
                    f"Turn {turn + 1}: structured output validation failed, retrying ({retries_used}/{max_retries})"
                )
                current_prompt = (
                    "Your previous response did not satisfy the required JSON schema. Fix it now:\n"
                    "1. Re-read the schema requirements — check all required fields and their types.\n"
                    "2. Ensure every required field is present with the correct type.\n"
                    "3. Output ONLY the valid JSON — no markdown fencing, no explanation text.\n"
                    "4. Validate mentally: would json.loads() parse this without error?"
                )
                continue
            if error_type == "auth":
                all_warnings.append(f"Turn {turn + 1}: authentication error, cannot retry.")
                break
            if error_type == "vision_required":
                # The model does not support image input — surface a clear message
                # and stop retrying so the user gets actionable feedback.
                detail = (
                    "The current model does not support image input. "
                    "To use clipboard images or image uploads, switch to a vision-capable model "
                    "(e.g., gpt-4o, gpt-4-turbo, claude-3-sonnet) or paste the image as a file path instead."
                )
                if error_message:
                    detail = f"{detail} Original error: {error_message}"
                all_warnings.append(f"Turn {turn + 1}: vision required — {detail}")
                break
            if retryable_error is False:
                warning = f"Turn {turn + 1}: non-retryable {error_type or 'error'}"
                if error_message:
                    warning = f"{warning}: {error_message}"
                all_warnings.append(warning)
                break
            if retries_used < max_retries:
                retries_used += 1
                _emit(
                    "response.error_recovery",
                    {
                        "turn": turn + 1,
                        "error_type": error_type or "unknown",
                        "retry": retries_used,
                        "max_retries": max_retries,
                    },
                )
                all_warnings.append(
                    f"Turn {turn + 1}: agent error ({error_type or 'unknown'}), retrying ({retries_used}/{max_retries})"
                )
                current_prompt = (
                    "The previous step encountered an error. Before retrying:\n"
                    "1. Read the error message carefully — what specifically failed?\n"
                    "2. Identify the root cause — not just the symptom.\n"
                    "3. Fix the underlying issue, then retry.\n"
                    "If the same approach has already failed, try a fundamentally "
                    "different strategy instead of repeating the same steps."
                )
                continue
            break

        if completion == "incomplete" and turn + 1 < effective_max_turns:
            all_warnings.append(f"Turn {turn + 1}: task incomplete, sending continuation prompt")
            # Use context-budget-aware continuation prompt
            current_prompt = get_continuation_prompt(current_budget_status)
            continue

        break

    # --- Handoff summary with memory persistence ---
    if compaction_attempts >= MAX_COMPACTION_ATTEMPTS and last_payload:
        budget = compute_context_budget(last_payload)
        if budget.get("status") == "critical":
            handoff_summary = {
                "reason": "context_exhausted",
                "compaction_attempts": compaction_attempts,
                "context_budget": budget,
                "turns_completed": min(turn + 1, effective_max_turns),
                "original_prompt": truncate_text(request.prompt, 500),
                "recommendation": "Start a new session. The context window is exhausted.",
            }
            all_warnings.append("Context exhausted after max compaction attempts; handoff summary generated.")

    # --- Collect full session history for artifacts and tool calls ---
    collected_tool_calls: list[dict[str, Any]] = []
    collected_artifacts: list[dict[str, Any]] = []
    collected_todos: list[dict[str, Any]] = []
    authoritative_payload = dict(last_payload)
    current_message_id = ""
    last_payload_info = last_payload.get("info") if isinstance(last_payload.get("info"), dict) else None
    if isinstance(last_payload_info, dict):
        current_message_id = str(last_payload_info.get("id") or "").strip()
    try:
        if detect_completion_status(last_payload) not in ("completed",):
            final_status = wait_for_session_idle(session_id)
            if str(final_status.get("type", "idle")) != "idle":
                abort_session(session_id)
                all_warnings.append(f"Session {session_id} remained {final_status.get('type', 'busy')}, aborted.")
                wait_for_session_idle(session_id, timeout_seconds=5.0)

        if current_message_id:
            exact_message = get_session_message(session_id, current_message_id)
            if exact_message is not None:
                authoritative_payload = exact_message

        messages = get_session_messages(session_id)
        collected_tool_calls = extract_tool_calls_from_messages(messages)
        collected_artifacts = extract_artifacts_from_messages(messages)
        collected_todos = get_session_todos(session_id)
        if len(collected_artifacts) >= ARTIFACT_COLLECTION_MAX_FILES:
            all_warnings.append(
                f"Artifact collection limited to {ARTIFACT_COLLECTION_MAX_FILES} files; some may have been omitted."
            )
        authoritative_info = authoritative_payload.get("info") if isinstance(authoritative_payload.get("info"), dict) else None
        authoritative_parent_id = ""
        if isinstance(authoritative_info, dict):
            authoritative_parent_id = str(authoritative_info.get("parentID") or "").strip()
        if detect_completion_status(authoritative_payload) not in ("completed",) or not extract_response_text(authoritative_payload).strip():
            latest_assistant = get_latest_assistant_payload(messages, parent_message_id=authoritative_parent_id or None)
            if latest_assistant is not None:
                authoritative_payload = latest_assistant

        residual_errors = detect_task_errors(messages)
        for err in residual_errors[:5]:
            all_warnings.append(f"Tool error: {truncate_text(err, 200)}")
    except Exception as exc:
        logger.warning("Failed to collect session history for %s: %s", session_id, exc)

    final_status_str = detect_completion_status(authoritative_payload)
    response_metadata = _build_response_metadata(authoritative_payload)
    if response_metadata is None:
        response_metadata = {}
    if collected_todos:
        response_metadata["todos"] = collected_todos

    response_status = final_status_str
    if final_status_str == "context_overflow":
        response_status = "error"
    elif final_status_str == "unknown":
        response_status = "incomplete"
    if response_status != final_status_str:
        response_metadata["raw_status"] = final_status_str

    response_text = extract_response_text(authoritative_payload).strip()
    if not response_text and response_status == "error":
        # Prefer the structured error detail from the payload's info.error over
        # a generic warning when the response body is empty or truncated.
        structured_error = str(last_payload.get("info", {}).get("error", {}).get("message") or "").strip()
        if structured_error:
            response_text = f"[Runtime Error] {structured_error}"
        else:
            response_text = _best_warning_response(all_warnings)
    if not response_text and collected_tool_calls:
        response_text = build_tool_only_response(collected_tool_calls)
    if not response_text:
        response_text = "(no output)"
    
    # Defense-in-depth: redact any leaked secrets from the response text and warnings
    response_text = redact_secrets(response_text)
    all_warnings = [redact_secrets(w) for w in all_warnings]

    ctx_budget = compute_context_budget(authoritative_payload)
    response_metadata["context_budget"] = ctx_budget

    anti_patterns = detect_anti_patterns(response_text)
    if anti_patterns:
        response_metadata["anti_patterns"] = anti_patterns

    task_status = derive_task_status(response_status, all_warnings, ctx_budget, anti_patterns)
    response_metadata["task_status"] = task_status

    # Include task type and agent selection info
    if task_type != "unknown":
        response_metadata["task_type"] = task_type
    response_metadata["agent_used"] = current_agent

    if handoff_summary:
        response_metadata["handoff_summary"] = handoff_summary

    # Emit memory candidates for the gateway to persist in PostgreSQL
    if response_text and response_status in ("completed", "incomplete"):
        _mem_candidates: dict[str, list[dict[str, Any]]] = {}
        _summary_text = response_text[:280].strip()
        if _summary_text:
            _mem_candidates["procedural"] = [{"type": "assistant-summary", "text": _summary_text}]
        if collected_tool_calls:
            _tool_names = sorted({str(tc.get("tool") or tc.get("name") or "") for tc in collected_tool_calls if isinstance(tc, dict)} - {""})
            if _tool_names:
                _mem_candidates["episodic"] = [{"type": "tool-usage", "names": _tool_names}]
        if _mem_candidates:
            response_metadata["memory"] = _mem_candidates

    continuity = {
        "created_new_session": created_new_session,
        "session_recovered": session_recovered,
        "has_prior_memory": has_prior_memory,
        "memory_applied": bool(memory_prompt) or bool(handoff_memory),
        "memory_entry_count": memory_entry_count,
        "handoff_resumed": bool(handoff_memory and created_new_session),
        "remote_session_id": session_id,
    }

    # --- Persist memory after invocation ---
    if MEMORY_ENABLED and not request.no_session:
        try:
            # Save task summary
            summary_entry = build_task_summary_entry(
                prompt=request.prompt,
                response_text=response_text,
                status=response_status,
                artifacts=collected_artifacts,
                tool_calls=collected_tool_calls,
                todos=collected_todos,
                warnings=all_warnings,
                context_budget=ctx_budget,
            )
            SESSION_MEMORY.save_memory(logical_thread_id, summary_entry)

            # Save handoff entry if context was exhausted
            if handoff_summary:
                handoff_entry = build_handoff_entry(
                    prompt=request.prompt,
                    summary=response_text[:2000],
                    todos=collected_todos,
                    artifacts=collected_artifacts,
                    context_budget=ctx_budget,
                )
                SESSION_MEMORY.save_memory(logical_thread_id, handoff_entry)
        except Exception as exc:
            logger.warning("Failed to persist session memory for %s: %s", logical_thread_id, exc)

    return InvokeResponse(
        thread_id=logical_thread_id,
        response=response_text,
        model=selected_model,
        status=response_status,
        a2a=a2a_response_metadata(request),
        warnings=dedupe_items(all_warnings),
        artifacts=collected_artifacts,
        tool_calls=collected_tool_calls,
        continuity=continuity,
        metadata=response_metadata or None,
    )
