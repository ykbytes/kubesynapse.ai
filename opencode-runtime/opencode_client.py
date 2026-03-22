"""HTTP client for communicating with the running OpenCode server."""
from __future__ import annotations

import json
import logging
import uuid
from typing import Any

import httpx
from fastapi import HTTPException

from config import (
    DEFAULT_MODEL,
    DEFAULT_PROVIDER,
    HTTP_TIMEOUT_SECONDS,
    OPENCODE_WORKDIR,
    SERVICE_NAME,
    SESSION_IDLE_POLL_SECONDS,
    SESSION_IDLE_TIMEOUT_SECONDS,
    server_base_url,
)
from session import SESSION_REGISTRY
from supervisor import _runtime_lock, _runtime_process, is_shutting_down

import time

logger = logging.getLogger("opencode-runtime")


def ensure_server_running() -> None:
    """Raise 503 if the OpenCode subprocess is not running or shutting down."""
    if is_shutting_down():
        raise HTTPException(status_code=503, detail="Runtime is shutting down")
    with _runtime_lock:
        proc = _runtime_process
    if proc is None or proc.poll() is not None:
        raise HTTPException(status_code=503, detail="OpenCode server is not running")


def runtime_http_client() -> httpx.Client:
    """Return a pre-configured httpx client for the OpenCode server."""
    return httpx.Client(base_url=server_base_url(), timeout=HTTP_TIMEOUT_SECONDS, trust_env=False)


def build_model_payload(model_ref: str) -> dict[str, str]:
    """Parse a model reference into providerID/modelID parts."""
    cleaned = model_ref.strip()
    if "/" in cleaned:
        provider_id, model_id = cleaned.split("/", 1)
        provider_id = provider_id.strip() or DEFAULT_PROVIDER
        model_id = model_id.strip() or DEFAULT_MODEL
        return {"providerID": provider_id, "modelID": model_id}
    return {"providerID": DEFAULT_PROVIDER, "modelID": cleaned or DEFAULT_MODEL}


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


def ensure_remote_session(thread_id: str, working_directory: str) -> str:
    """Return an existing session or create a new one for *thread_id*."""
    session_id = SESSION_REGISTRY.get(thread_id)
    if session_id:
        return session_id
    session_id = create_remote_session(working_directory)
    SESSION_REGISTRY.set(thread_id, session_id)
    return session_id


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
    body: dict[str, Any] = {
        "parts": [{"type": "text", "text": prompt}],
        "model": build_model_payload(model),
        "agent": agent,
    }
    if system_prompt:
        body["system"] = system_prompt
    if prompt_format:
        body["format"] = prompt_format

    with runtime_http_client() as client:
        response = client.post(
            f"/session/{session_id}/message",
            params={"directory": working_directory},
            json=body,
        )
        if response.status_code == 404:
            raise HTTPException(status_code=404, detail="OpenCode session not found")
        response.raise_for_status()
        return response.json()


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


def get_session_status(session_id: str) -> dict[str, Any]:
    """Check the current status (idle/busy/retry) of a session."""
    try:
        with runtime_http_client() as hclient:
            response = hclient.get("/session/status")
            response.raise_for_status()
            statuses = response.json()
        if not isinstance(statuses, dict):
            return {"type": "idle"}
        return statuses.get(session_id, {"type": "idle"})
    except (httpx.HTTPError, ValueError):
        logger.warning("Failed to get session status for %s; assuming idle.", session_id)
        return {"type": "idle"}


def wait_for_session_idle(session_id: str, timeout_seconds: float = SESSION_IDLE_TIMEOUT_SECONDS) -> dict[str, Any]:
    """Block until the session becomes idle or *timeout_seconds* elapses."""
    deadline = time.time() + timeout_seconds
    last_status = {"type": "idle"}
    while time.time() < deadline:
        last_status = get_session_status(session_id)
        if str(last_status.get("type", "idle")) == "idle":
            return last_status
        time.sleep(SESSION_IDLE_POLL_SECONDS)
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
                    "messageID": str(uuid.uuid4()),
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
