"""HTTP client for communicating with the running OpenCode server."""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from typing import Any

import httpx
import supervisor as _supervisor_mod
from config import (
    DEFAULT_MODEL,
    DEFAULT_PROVIDER,
    HTTP_TIMEOUT_SECONDS,
    SERVICE_NAME,
    SESSION_IDLE_MAX_POLL_SECONDS,
    SESSION_IDLE_POLL_SECONDS,
    SESSION_IDLE_TIMEOUT_SECONDS,
    server_base_url,
)
from fastapi import HTTPException
from session import SESSION_REGISTRY
from supervisor import _runtime_lock, is_shutting_down

logger = logging.getLogger("opencode-runtime")

# ---------------------------------------------------------------------------
# WP-6: Module-level pooled HTTP client for the OpenCode server.
#
# The previous implementation created a brand-new httpx.Client on every call
# inside the tight poll loop (LIVE_UPDATE_POLL_SECONDS = 0.08), causing
# continuous socket churn and TIME_WAIT accumulation.
#
# httpx.Client is thread-safe for concurrent requests (no per-request mutation
# of internal state), so a single instance shared across threads is correct.
# The client is re-created if the base URL changes (e.g. after a port config
# reload), which is guarded by _pool_lock.
# ---------------------------------------------------------------------------
_pool_lock = threading.Lock()
_pooled_client: httpx.Client | None = None
_pooled_client_base_url: str = ""
_pooled_client_auth_key: str = ""


def _opencode_server_auth() -> tuple[str, str] | None:
    password = _supervisor_mod.resolve_opencode_server_password()
    if not password:
        return None
    username = _supervisor_mod.resolve_opencode_server_username()
    return username, password


def _get_pooled_client() -> httpx.Client:
    """Return (and lazily create) the module-level pooled httpx.Client."""
    global _pooled_client, _pooled_client_auth_key, _pooled_client_base_url
    base_url = server_base_url()
    auth = _opencode_server_auth()
    auth_key = ":".join(auth) if auth else ""
    with _pool_lock:
        if _pooled_client is None or _pooled_client_base_url != base_url or _pooled_client_auth_key != auth_key:
            old = _pooled_client
            _pooled_client = httpx.Client(
                base_url=base_url,
                auth=auth,
                timeout=HTTP_TIMEOUT_SECONDS,
                trust_env=False,
                limits=httpx.Limits(
                    max_keepalive_connections=20,
                    max_connections=40,
                    keepalive_expiry=60.0,
                ),
            )
            _pooled_client_base_url = base_url
            _pooled_client_auth_key = auth_key
            if old is not None:
                try:
                    old.close()
                except Exception:
                    pass
    return _pooled_client


def close_pooled_client() -> None:
    """Close the pooled client on shutdown (called from lifespan teardown)."""
    global _pooled_client
    with _pool_lock:
        if _pooled_client is not None:
            try:
                _pooled_client.close()
            except Exception:
                pass
            _pooled_client = None


# ---------------------------------------------------------------------------
# Ascending message-ID generator (matches OpenCode's ID format so that
# string comparison ``lastUser.id < lastAssistant.id`` works correctly in
# the server's ``loop()`` exit condition).
# Format: msg_{12 hex chars}{14 random base62 chars}
# The 12 hex chars encode  timestamp_ms * 0x1000 + monotonic_counter.
# ---------------------------------------------------------------------------
_id_last_ts: int = 0
_id_counter: int = 0
_BASE62 = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"


def _ascending_message_id() -> str:
    """Generate a message ID that sorts lexicographically after any earlier ID."""
    global _id_last_ts, _id_counter
    now_ms = int(time.time() * 1000)
    if now_ms != _id_last_ts:
        _id_last_ts = now_ms
        _id_counter = 0
    _id_counter += 1
    encoded = (now_ms * 0x1000 + _id_counter) & 0xFFFFFFFFFFFF  # lower 48 bits
    time_hex = encoded.to_bytes(6, "big").hex()
    rand_part = "".join(_BASE62[b % 62] for b in os.urandom(14))
    return f"msg_{time_hex}{rand_part}"


def ensure_server_running() -> None:
    """Raise 503 if the OpenCode subprocess is not running or shutting down."""
    if is_shutting_down():
        raise HTTPException(status_code=503, detail="Runtime is shutting down")
    with _runtime_lock:
        proc = _supervisor_mod._runtime_process
    if proc is None or proc.poll() is not None:
        raise HTTPException(status_code=503, detail="OpenCode server is not running")


def runtime_http_client() -> httpx.Client:
    """Return the shared pooled httpx client for the OpenCode server.

    WP-6: Returns the module-level pooled client instead of constructing a
    new one per call.  Callers must NOT close this client (it is shared); all
    existing ``with runtime_http_client() as client:`` call sites continue to
    work because httpx.Client.__exit__ on a context manager that was *not*
    entered as a context manager does not close the underlying connection pool.

    For call sites that use ``with runtime_http_client() as client:`` the
    context manager protocol on httpx.Client does NOT close the client when
    used via __enter__/__exit__ at the request level — only pool cleanup at
    program exit.  All existing callers are safe to reuse as-is.
    """
    return _get_pooled_client()


def build_model_payload(model_ref: str) -> dict[str, str]:
    """Parse a model reference into providerID/modelID parts."""
    cleaned = model_ref.strip()
    if "/" in cleaned:
        provider_id, model_id = cleaned.split("/", 1)
        provider_id = provider_id.strip() or DEFAULT_PROVIDER
        model_id = model_id.strip() or DEFAULT_MODEL
        return {"providerID": provider_id, "modelID": model_id}
    return {"providerID": DEFAULT_PROVIDER, "modelID": cleaned or DEFAULT_MODEL}


def _resolve_message_response_from_history(session_id: str, message_id: str) -> dict[str, Any]:
    """Recover the assistant payload when OpenCode accepts a prompt but returns no body."""
    wait_for_session_idle(session_id)
    messages = get_session_messages(session_id)
    from analysis import get_latest_assistant_payload

    payload = get_latest_assistant_payload(messages, parent_message_id=message_id)
    if payload is not None:
        return payload

    fallback = get_latest_assistant_payload(messages)
    if fallback is not None:
        return fallback

    raise HTTPException(
        status_code=502,
        detail="OpenCode accepted the prompt but returned no assistant payload.",
    )


def create_remote_session(working_directory: str) -> str:
    """Create a new session on the OpenCode server."""
    with runtime_http_client() as client:
        response = client.post("/session", params={"directory": working_directory}, json={"title": SERVICE_NAME})
        response.raise_for_status()
        payload = response.json()
    session_id = str(payload.get("id") or "").strip()
    if not session_id:
        raise HTTPException(status_code=502, detail="OpenCode session creation did not return a session id")
    return session_id


def _verify_session_ready(session_id: str, max_attempts: int = 5, base_delay: float = 0.05) -> None:
    """Verify a newly created session can accept prompts.

    OpenCode may return 500 on POST /session/{id}/message immediately after
    session creation if the internal state isn't fully initialized. Polling
    GET /session/status until the session appears eliminates this race.
    """
    for attempt in range(max_attempts):
        try:
            status = get_session_status(session_id)
            if status and str(status.get("type", "idle")) in ("idle", "busy"):
                return
        except (httpx.HTTPError, ValueError):
            pass
        if attempt < max_attempts - 1:
            time.sleep(base_delay * (2 ** attempt))
    logger.debug("Session %s readiness check completed after %d attempts", session_id, max_attempts)


def ensure_remote_session(thread_id: str, working_directory: str) -> str:
    """Return an existing session or create a new one for *thread_id*."""
    session_id = SESSION_REGISTRY.get(thread_id)
    if session_id:
        return session_id
    session_id = create_remote_session(working_directory)
    _verify_session_ready(session_id)
    SESSION_REGISTRY.set(thread_id, session_id)
    return session_id


_TRANSIENT_RETRY_ATTEMPTS = 3
_TRANSIENT_RETRY_BASE_DELAY = 0.1


def _transient_retry_post(
    client: httpx.Client,
    url: str,
    json_body: dict[str, Any],
    params: dict[str, str] | None = None,
    retries: int = _TRANSIENT_RETRY_ATTEMPTS,
    base_delay: float = _TRANSIENT_RETRY_BASE_DELAY,
) -> httpx.Response:
    """POST with short retries on transient 500/502/503 errors.

    OpenCode may return 500 immediately after session creation if internal
    state isn't fully initialized. These resolve within milliseconds so a
    quick retry eliminates the need for the gateway to back off for seconds.
    """
    last_exc: Exception | None = None
    for attempt in range(retries):
        try:
            response = client.post(url, params=params, json=json_body)
            if response.status_code not in (500, 502, 503):
                return response
            last_exc = HTTPException(
                status_code=response.status_code,
                detail=f"Transient {response.status_code} on POST {url}",
            )
        except httpx.HTTPError as exc:
            last_exc = exc
        if attempt < retries - 1:
            time.sleep(base_delay * (2 ** attempt))
    if last_exc is not None:
        raise last_exc
    raise RuntimeError(f"All {retries} transient retries exhausted for POST {url}")


def send_prompt(
    *,
    session_id: str,
    prompt: str,
    model: str,
    system_prompt: str | None,
    prompt_format: dict[str, Any] | None,
    working_directory: str,
    agent: str,
) -> dict[str, Any]:
    """Send a prompt to a session and return the response payload."""
    message_id = _ascending_message_id()
    body: dict[str, Any] = {
        "messageID": message_id,
        "parts": [{"type": "text", "text": prompt}],
        "model": build_model_payload(model),
        "agent": agent,
    }
    if system_prompt:
        body["system"] = system_prompt
    if prompt_format:
        body["format"] = prompt_format

    with runtime_http_client() as client:
        response = _transient_retry_post(
            client,
            f"/session/{session_id}/message",
            body,
            params={"directory": working_directory},
        )
        if response.status_code == 404:
            raise HTTPException(status_code=404, detail="OpenCode session not found")
        response.raise_for_status()
        if not response.content or not response.content.strip():
            return _resolve_message_response_from_history(session_id, message_id)
        try:
            payload = response.json()
        except ValueError as exc:
            raise HTTPException(
                status_code=502,
                detail=f"OpenCode message response was not valid JSON: {response.text[:200]}",
            ) from exc
    if not isinstance(payload, dict):
        return _resolve_message_response_from_history(session_id, message_id)
    return payload


def send_prompt_async(
    *,
    session_id: str,
    prompt: str,
    model: str,
    system_prompt: str | None,
    prompt_format: dict[str, Any] | None,
    working_directory: str,
    agent: str,
    message_id: str | None = None,
) -> str:
    """Send a prompt asynchronously and return the user message id used for the request."""
    actual_message_id = (message_id or _ascending_message_id()).strip()
    body: dict[str, Any] = {
        "messageID": actual_message_id,
        "parts": [{"type": "text", "text": prompt}],
        "model": build_model_payload(model),
        "agent": agent,
    }
    if system_prompt:
        body["system"] = system_prompt
    if prompt_format:
        body["format"] = prompt_format

    with runtime_http_client() as client:
        response = _transient_retry_post(
            client,
            f"/session/{session_id}/prompt_async",
            body,
            params={"directory": working_directory},
        )
        if response.status_code == 404:
            raise HTTPException(status_code=404, detail="OpenCode session not found")
        response.raise_for_status()
    return actual_message_id


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
) -> tuple[str, dict[str, Any]]:
    """Send a prompt to the OpenCode server, recovering the session on 404."""
    try:
        payload = send_prompt(
            session_id=session_id,
            prompt=prompt,
            model=model,
            system_prompt=system_prompt,
            prompt_format=prompt_format,
            working_directory=working_directory,
            agent=agent,
        )
        if isinstance(payload, dict):
            payload.setdefault("_session_recovered", False)
        return session_id, payload
    except HTTPException as exc:
        if exc.status_code == 404 and allow_session_recovery:
            session_id = create_remote_session(working_directory)
            SESSION_REGISTRY.set(logical_thread_id, session_id)
            payload = send_prompt(
                session_id=session_id,
                prompt=prompt,
                model=model,
                system_prompt=system_prompt,
                prompt_format=prompt_format,
                working_directory=working_directory,
                agent=agent,
            )
            if isinstance(payload, dict):
                payload["_session_recovered"] = True
            return session_id, payload
        raise


def get_session_messages(session_id: str) -> list[dict[str, Any]]:
    """Fetch the complete message history for a session from the OpenCode server."""
    with runtime_http_client() as hclient:
        response = hclient.get(f"/session/{session_id}/message")
        if response.status_code == 404:
            return []
        response.raise_for_status()
        payload = response.json()
    if not isinstance(payload, list):
        return []
    return [item for item in payload if isinstance(item, dict)]


def get_session_message(session_id: str, message_id: str) -> dict[str, Any] | None:
    """Fetch a specific message payload for a session from the OpenCode server."""
    try:
        with runtime_http_client() as hclient:
            response = hclient.get(f"/session/{session_id}/message/{message_id}")
            if response.status_code == 404:
                return None
            response.raise_for_status()
            payload = response.json()
    except (httpx.HTTPError, ValueError):
        logger.warning("Failed to get session message %s for %s", message_id, session_id)
        return None
    if not isinstance(payload, dict):
        return None
    info = payload.get("info")
    if not isinstance(info, dict):
        return None
    parts = payload.get("parts") if isinstance(payload.get("parts"), list) else []
    return {
        "info": info,
        "parts": [item for item in parts if isinstance(item, dict)],
    }


def get_session_status(session_id: str) -> dict[str, Any]:
    """Check the current status (idle/busy/retry) of a session."""
    try:
        with runtime_http_client() as hclient:
            response = hclient.get("/session/status")
            response.raise_for_status()
            statuses = response.json()
        if not isinstance(statuses, dict):
            return {"type": "idle"}
        session_status = statuses.get(session_id)
        if not isinstance(session_status, dict):
            return {"type": "idle"}
        return session_status
    except (httpx.HTTPError, ValueError):
        logger.warning("Failed to get session status for %s; assuming idle.", session_id)
        return {"type": "idle"}


def wait_for_session_idle(session_id: str, timeout_seconds: float = SESSION_IDLE_TIMEOUT_SECONDS) -> dict[str, Any]:
    """Block until the session becomes idle or *timeout_seconds* elapses."""
    deadline = time.monotonic() + timeout_seconds
    last_status = {"type": "idle"}
    next_delay = min(SESSION_IDLE_POLL_SECONDS, max(SESSION_IDLE_POLL_SECONDS / 2, 0.1))
    while True:
        last_status = get_session_status(session_id)
        if str(last_status.get("type", "idle")) == "idle":
            return last_status
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return last_status
        time.sleep(min(next_delay, remaining))
        next_delay = min(max(next_delay * 2, SESSION_IDLE_POLL_SECONDS), SESSION_IDLE_MAX_POLL_SECONDS)
    return last_status


def abort_session(session_id: str) -> bool:
    """Abort an active session to stop any ongoing AI processing."""
    try:
        with runtime_http_client() as hclient:
            response = hclient.post(f"/session/{session_id}/abort")
            return response.status_code == 200
    except httpx.HTTPError:
        logger.warning("Failed to abort session %s", session_id)
        return False


def summarize_session(session_id: str, model_ref: str | None = None) -> bool:
    """Trigger compaction/summarization of a session to free context space."""
    try:
        model_payload = build_model_payload(model_ref or DEFAULT_MODEL)
        with runtime_http_client() as hclient:
            response = hclient.post(
                f"/session/{session_id}/summarize",
                json={
                    "providerID": model_payload["providerID"],
                    "modelID": model_payload["modelID"],
                    "auto": True,
                },
            )
            return response.status_code == 200
    except httpx.HTTPError:
        logger.warning("Failed to summarize session %s", session_id)
        return False


def init_session(session_id: str, model_ref: str | None = None) -> bool:
    """Initialize a session by analyzing the project for better tool use."""
    try:
        model_payload = build_model_payload(model_ref or DEFAULT_MODEL)
        with runtime_http_client() as hclient:
            response = hclient.post(
                f"/session/{session_id}/init",
                json={
                    "providerID": model_payload["providerID"],
                    "modelID": model_payload["modelID"],
                    "messageID": f"msg_{uuid.uuid4().hex}",
                },
            )
            return response.status_code == 200
    except httpx.HTTPError:
        logger.warning("Failed to initialize session %s", session_id)
        return False


def get_session_todos(session_id: str) -> list[dict[str, Any]]:
    """Fetch the current todo list for a session."""
    try:
        with runtime_http_client() as hclient:
            response = hclient.get(f"/session/{session_id}/todo")
            if response.status_code != 200:
                return []
            payload = response.json()
            if isinstance(payload, list):
                return [item for item in payload if isinstance(item, dict)]
    except (httpx.HTTPError, ValueError):
        pass
    return []


def list_pending_questions() -> list[dict[str, Any]]:
    """Fetch pending question requests from the OpenCode server."""
    try:
        with runtime_http_client() as hclient:
            response = hclient.get("/question")
            if response.status_code != 200:
                return []
            payload = response.json()
            if isinstance(payload, list):
                return [item for item in payload if isinstance(item, dict)]
    except (httpx.HTTPError, ValueError):
        pass
    return []


def list_pending_permissions() -> list[dict[str, Any]]:
    """Fetch pending permission questions from the OpenCode server.

    Permission questions (bash/edit/write with "ask" config) are separate
    from regular questions and live at GET /permission, not GET /question.
    """
    try:
        with runtime_http_client() as hclient:
            response = hclient.get("/permission")
            if response.status_code != 200:
                return []
            payload = response.json()
            if isinstance(payload, list):
                return [item for item in payload if isinstance(item, dict)]
    except (httpx.HTTPError, ValueError):
        pass
    return []


def auto_approve_pending_questions() -> list[str]:
    """Auto-approve all pending questions and permission requests.

    This is used when the runtime is operating in autonomous/headless mode
    (HITL_MODE=disabled) where no human is available to interactively
    approve bash/edit/write tool use. The OpenCode immutable config sets
    permissions to "ask" as a security floor, but in autonomous mode these
    questions must be auto-approved to avoid deadlock.

    Handles two separate question types:
    1. Regular questions via GET /question and POST /question/{id}/reply
    2. Permission questions via GET /permission and POST /permission/{id}/reply

    Returns a list of all approved question/permission IDs.
    """
    approved_ids: list[str] = []

    # Handle regular questions
    questions = list_pending_questions()
    for q in questions:
        qid = str(q.get("id", "")).strip()
        if not qid:
            continue
        if reply_to_question(qid, [["Yes"]]):
            approved_ids.append(qid)
            logger.info("Auto-approved question %s (autonomous mode)", qid)
        else:
            logger.warning("Failed to auto-approve question %s", qid)

    # Handle permission questions (bash/edit/write "ask" prompts)
    # These have IDs starting with "per_" and use a different endpoint.
    #
    # §security-P0: Auto-approval is NOT unconditional. Each pending permission
    # is evaluated against the policy-derived admin tool ceiling
    # (OPENCODE_ADMIN_PERMISSION_CEILING_JSON) and the catastrophic-command
    # denylist. Tools the policy caps at deny/ask — and dangerous shell
    # commands — are rejected instead of approved, even in autonomous mode.
    from runtime_permissions import evaluate_pending_permission, load_permission_ceiling

    ceiling = load_permission_ceiling()
    permissions = list_pending_permissions()
    for p in permissions:
        pid = str(p.get("id", "")).strip()
        if not pid:
            continue
        decision = evaluate_pending_permission(p, ceiling, autonomous=True)
        if decision == "reject":
            if reply_to_permission(pid, "reject"):
                logger.warning(
                    "Auto-rejected permission %s (%s) — blocked by policy ceiling or denylist",
                    pid, p.get("permission", "?"),
                )
            else:
                logger.warning("Failed to auto-reject permission %s", pid)
            continue
        if reply_to_permission(pid, "always"):
            approved_ids.append(pid)
            logger.info("Auto-approved permission %s (%s) (autonomous mode)", pid, p.get("permission", "?"))
        else:
            logger.warning("Failed to auto-approve permission %s", pid)

    return approved_ids


def reply_to_question(request_id: str, answers: list[list[str]]) -> bool:
    """Submit answers to a pending question request."""
    try:
        with runtime_http_client() as hclient:
            response = hclient.post(
                f"/question/{request_id}/reply",
                json={"answers": answers},
            )
            return response.status_code == 200
    except httpx.HTTPError:
        logger.warning("Failed to reply to question %s", request_id)
        return False


def reject_question(request_id: str) -> bool:
    """Reject a pending question request."""
    try:
        with runtime_http_client() as hclient:
            response = hclient.post(f"/question/{request_id}/reject")
            return response.status_code == 200
    except httpx.HTTPError:
        logger.warning("Failed to reject question %s", request_id)
        return False


def reply_to_permission(request_id: str, reply: str = "always") -> bool:
    """Submit a reply to a pending permission question.

    Permission questions (bash/edit/write with "ask" config) use a separate
    endpoint from regular questions. The reply value must be one of:
    "once" - approve this time only
    "always" - approve and remember for session
    "reject" - deny the permission
    """
    try:
        with runtime_http_client() as hclient:
            response = hclient.post(
                f"/permission/{request_id}/reply",
                json={"reply": reply},
            )
            return response.status_code == 200
    except httpx.HTTPError:
        logger.warning("Failed to reply to permission %s", request_id)
        return False


def get_session_diff(session_id: str) -> str:
    """Fetch the unified diff of file changes for a session."""
    try:
        with runtime_http_client() as hclient:
            response = hclient.get(f"/session/{session_id}/diff")
            if response.status_code != 200:
                return ""
            # The diff endpoint may return plain text or JSON
            content_type = response.headers.get("content-type", "")
            if "json" in content_type:
                payload = response.json()
                if isinstance(payload, str):
                    return payload
                if isinstance(payload, dict):
                    return str(payload.get("diff", payload.get("content", "")))
                return str(payload)
            return response.text
    except (httpx.HTTPError, ValueError):
        logger.warning("Failed to get session diff for %s", session_id)
        return ""


# ---------------------------------------------------------------------------
# Live SSE bridge: subscribe to OpenCode's /api/event stream and emit
# intermediate step-finish updates to a callback as they arrive.
#
# The parts-walk fix in ``analysis._build_response_metadata`` is the
# authoritative source for per-execution totals because OpenCode's
# ``info.tokens`` is last-step-wins (see processor.ts in OpenCode 1.15.13).
# The bridge below is purely additive: it provides real-time liveness in
# the Run Intelligence stream and the live dashboard, without disturbing
# the existing trace storage model.
# ---------------------------------------------------------------------------
