from __future__ import annotations

import hashlib
import io
import json
import os
import tempfile
import threading
import time
import uuid
import zipfile
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


HOST = os.environ.get("MOCK_RUNTIME_HOST", "127.0.0.1")
PORT = int(os.environ.get("MOCK_RUNTIME_PORT", "18080"))
BEARER_TOKEN = os.environ.get("RUNTIME_BEARER_TOKEN", "test-token")
TIMEOUT_PROMPT = (os.environ.get("RUNTIME_TIMEOUT_PROMPT") or "__trigger_timeout__").strip()
WORKSPACE_DIR = Path(tempfile.mkdtemp(prefix="kubesynapse-mock-runtime-"))
WORKSPACE_DIR.joinpath("hello.txt").write_text("hello from mock runtime\n", encoding="utf-8")
WORKSPACE_DIR.joinpath("notes.md").write_text("# Mock Runtime\n", encoding="utf-8")
SESSIONS: dict[str, dict[str, object]] = {}
LOCK = threading.Lock()


def _error_payload(code: str, message: str, details: dict[str, object] | None = None) -> dict[str, object]:
    payload: dict[str, object] = {
        "error": {
            "code": code,
            "message": message,
            "trace_id": f"trace-{uuid.uuid4().hex[:12]}",
        }
    }
    if details:
        payload["error"]["details"] = details
    return payload


def _workspace_path(raw_value: str) -> Path:
    candidate = (raw_value or "").strip()
    if candidate in {"", "/workspace"}:
        return WORKSPACE_DIR
    if candidate.startswith("/workspace/"):
        resolved = (WORKSPACE_DIR / candidate.removeprefix("/workspace/")).resolve()
    elif Path(candidate).is_absolute():
        raise PermissionError(f"Path outside workspace: {candidate}")
    else:
        resolved = (WORKSPACE_DIR / candidate).resolve()
    if resolved != WORKSPACE_DIR and WORKSPACE_DIR not in resolved.parents:
        raise PermissionError(f"Path outside workspace: {candidate}")
    return resolved


def _build_continuity(created_new_session: bool) -> dict[str, bool]:
    return {
        "created_new_session": created_new_session,
        "session_recovered": False,
        "has_prior_memory": False,
    }


def _build_context_budget(tokens_total: int) -> dict[str, object]:
    limit = 32768
    remaining = max(limit - tokens_total, 0)
    usage = round((tokens_total / limit) * 100, 2) if limit else 0.0
    status = "ok"
    if usage >= 100:
        status = "overflow"
    elif usage >= 90:
        status = "critical"
    elif usage >= 75:
        status = "warning"
    return {
        "model_context_limit": limit,
        "tokens_used": tokens_total,
        "tokens_remaining": remaining,
        "usage_percent": usage,
        "status": status,
        "compaction_available": False,
    }


def _ensure_session(thread_id: str, prompt: str) -> tuple[dict[str, object], dict[str, bool]]:
    with LOCK:
        existing = SESSIONS.get(thread_id)
        if existing is not None:
            existing["prompt"] = prompt
            existing["status"] = "active"
            existing["updated_at"] = time.time()
            existing["todos"] = [{"content": prompt, "status": "in_progress"}]
            return existing, _build_continuity(created_new_session=False)

        session = {
            "thread_id": thread_id,
            "session_id": f"mock-session-{uuid.uuid4().hex[:16]}",
            "prompt": prompt,
            "status": "active",
            "created_at": time.time(),
            "updated_at": time.time(),
            "todos": [{"content": prompt, "status": "in_progress"}],
            "diff": "",
            "context_budget": _build_context_budget(0),
        }
        SESSIONS[thread_id] = session
        return session, _build_continuity(created_new_session=True)


def _complete_session(thread_id: str, prompt: str, response_text: str) -> dict[str, object]:
    with LOCK:
        session = SESSIONS[thread_id]
        file_path = WORKSPACE_DIR / f"{thread_id}.txt"
        previous = file_path.read_text(encoding="utf-8") if file_path.exists() else ""
        file_path.write_text(f"{response_text}\n", encoding="utf-8")
        session["status"] = "completed"
        session["updated_at"] = time.time()
        session["todos"] = [{"content": prompt, "status": "completed"}]
        tokens_total = 12 if response_text else 0
        session["context_budget"] = _build_context_budget(tokens_total)
        session["diff"] = (
            f"--- a/{thread_id}.txt\n"
            f"+++ b/{thread_id}.txt\n"
            f"-{previous.rstrip()}\n"
            f"+{response_text}\n"
        )
        return session


def _list_files(root: Path) -> list[dict[str, object]]:
    files: list[dict[str, object]] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.name.startswith("."):
            continue
        stat = path.stat()
        files.append(
            {
                "path": f"/workspace/{path.relative_to(WORKSPACE_DIR).as_posix()}",
                "size": stat.st_size,
                "modified": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(stat.st_mtime)),
            }
        )
    return files


class MockRuntimeHandler(BaseHTTPRequestHandler):
    server_version = "KubeSynapseMockRuntime/1.0"

    def _send_json(self, status: int, payload: dict[str, object] | list[object], headers: dict[str, str] | None = None) -> None:
        encoded = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        if headers:
            for key, value in headers.items():
                self.send_header(key, value)
        self.end_headers()
        self.wfile.write(encoded)

    def _send_error(self, status: int, code: str, message: str, details: dict[str, object] | None = None) -> None:
        self._send_json(status, _error_payload(code, message, details))

    def _send_sse(self, body: str) -> None:
        encoded = body.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _require_auth(self) -> bool:
        if not BEARER_TOKEN:
            return True
        auth = self.headers.get("Authorization", "")
        if auth == f"Bearer {BEARER_TOKEN}":
            return True
        self._send_error(HTTPStatus.UNAUTHORIZED, "unauthorized", "Missing or invalid bearer token")
        return False

    def _read_json(self) -> dict[str, object]:
        content_length = int(self.headers.get("Content-Length", "0") or "0")
        raw = self.rfile.read(content_length) if content_length else b"{}"
        if not raw:
            return {}
        return json.loads(raw.decode("utf-8"))

    def _thread_session(self, thread_id: str) -> dict[str, object] | None:
        with LOCK:
            return SESSIONS.get(thread_id)

    def do_GET(self) -> None:  # noqa: N802
        if not self._require_auth():
            return
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)

        if parsed.path == "/health":
            self._send_json(
                HTTPStatus.OK,
                {
                    "status": "healthy",
                    "runtime": "mock-runtime",
                    "service": "mock-runtime",
                    "namespace": "default",
                    "provider": "mock",
                    "agent": "build",
                    "sessions": {"total": len(SESSIONS), "active": sum(1 for session in SESSIONS.values() if session["status"] == "active")},
                    "uptime_seconds": 1.0,
                    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                },
            )
            return

        if parsed.path == "/ready":
            self._send_json(
                HTTPStatus.OK,
                {
                    "status": "ready",
                    "runtime": "mock-runtime",
                    "checks": {"mock_server": True},
                },
            )
            return

        if parsed.path == "/info":
            self._send_json(
                HTTPStatus.OK,
                {
                    "runtime": "mock-runtime",
                    "contract_version": "v1",
                    "service": "mock-runtime",
                    "namespace": "default",
                    "provider": "mock",
                    "model": "mock-model",
                    "agent": "build",
                    "version": "1.0.0",
                },
            )
            return

        if parsed.path == "/capabilities":
            self._send_json(
                HTTPStatus.OK,
                {
                    "runtime": "mock-runtime",
                    "service": "mock-runtime",
                    "capabilities": {
                        "native_tools": ["mock.tool"],
                        "output_formats": ["text", "json", "markdown"],
                        "structured_output": {"supported": True, "json_schema": True},
                        "autonomous_execution": {"supported": True, "default_max_turns": 10},
                        "session_management": {"abort": True, "summarize": False, "compaction": False},
                        "mcp_usage": {"supported": False},
                        "a2a": {"outbound_supported": False},
                        "tiers": ["core", "session", "artifacts", "streaming"],
                    },
                },
            )
            return

        if parsed.path == "/todo":
            thread_id = (query.get("thread_id") or [""])[0]
            session = self._thread_session(thread_id)
            if session is None:
                self._send_error(HTTPStatus.NOT_FOUND, "not_found", f"No session found for thread_id '{thread_id}'")
                return
            todos = session.get("todos", [])
            etag = hashlib.md5(json.dumps(todos, sort_keys=True).encode()).hexdigest()  # noqa: S324
            if self.headers.get("If-None-Match", "").strip(' "') == etag:
                self.send_response(HTTPStatus.NOT_MODIFIED)
                self.send_header("ETag", f'"{etag}"')
                self.end_headers()
                return
            self._send_json(
                HTTPStatus.OK,
                {"thread_id": thread_id, "session_id": session["session_id"], "todos": todos},
                headers={"ETag": f'"{etag}"'},
            )
            return

        if parsed.path == "/question":
            self._send_json(HTTPStatus.OK, [])
            return

        if parsed.path == "/diff":
            thread_id = (query.get("thread_id") or [""])[0]
            session = self._thread_session(thread_id)
            if session is None:
                self._send_error(HTTPStatus.NOT_FOUND, "not_found", f"No session found for thread_id '{thread_id}'")
                return
            self._send_json(HTTPStatus.OK, {"thread_id": thread_id, "session_id": session["session_id"], "diff": session["diff"]})
            return

        if parsed.path == "/context-budget":
            thread_id = (query.get("thread_id") or [""])[0]
            session = self._thread_session(thread_id)
            if session is None:
                self._send_error(HTTPStatus.NOT_FOUND, "not_found", f"No session found for thread_id '{thread_id}'")
                return
            self._send_json(
                HTTPStatus.OK,
                {"thread_id": thread_id, "session_id": session["session_id"], **session["context_budget"]},
            )
            return

        if parsed.path == "/artifacts/list":
            thread_id = (query.get("thread_id") or [""])[0]
            if self._thread_session(thread_id) is None:
                self._send_error(HTTPStatus.NOT_FOUND, "not_found", f"No session found for thread_id '{thread_id}'")
                return
            try:
                root = _workspace_path((query.get("root") or ["/workspace"])[0])
            except PermissionError as exc:
                self._send_error(HTTPStatus.FORBIDDEN, "forbidden", str(exc))
                return
            self._send_json(HTTPStatus.OK, {"files": _list_files(root), "truncated": False})
            return

        if parsed.path == "/artifacts/download":
            thread_id = (query.get("thread_id") or [""])[0]
            if self._thread_session(thread_id) is None:
                self._send_error(HTTPStatus.NOT_FOUND, "not_found", f"No session found for thread_id '{thread_id}'")
                return
            requested_path = (query.get("path") or [""])[0]
            if not requested_path:
                self._send_error(HTTPStatus.BAD_REQUEST, "invalid_request", "path query parameter is required")
                return
            try:
                file_path = _workspace_path(requested_path)
            except PermissionError as exc:
                self._send_error(HTTPStatus.FORBIDDEN, "forbidden", str(exc))
                return
            if not file_path.exists() or not file_path.is_file():
                self._send_error(HTTPStatus.NOT_FOUND, "not_found", f"File not found: {requested_path}")
                return
            encoded = file_path.read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)
            return

        if parsed.path == "/artifacts/zip":
            thread_id = (query.get("thread_id") or [""])[0]
            if self._thread_session(thread_id) is None:
                self._send_error(HTTPStatus.NOT_FOUND, "not_found", f"No session found for thread_id '{thread_id}'")
                return
            try:
                root = _workspace_path((query.get("root") or ["/workspace"])[0])
            except PermissionError as exc:
                self._send_error(HTTPStatus.FORBIDDEN, "forbidden", str(exc))
                return
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as archive:
                for file_path in root.rglob("*"):
                    if file_path.is_file() and not file_path.name.startswith("."):
                        archive.write(file_path, file_path.relative_to(root).as_posix())
            payload = buf.getvalue()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/zip")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return

        self._send_error(HTTPStatus.NOT_FOUND, "not_found", "Unknown route")

    def do_POST(self) -> None:  # noqa: N802
        if not self._require_auth():
            return
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)

        if parsed.path in {"/invoke", "/invoke/stream"}:
            try:
                payload = self._read_json()
            except json.JSONDecodeError:
                self._send_error(HTTPStatus.BAD_REQUEST, "invalid_json", "Request body must be valid JSON")
                return

            prompt = str(payload.get("prompt") or "").strip()
            if not prompt:
                self._send_error(HTTPStatus.BAD_REQUEST, "invalid_request", "prompt is required")
                return

            timeout_seconds = float(payload.get("timeout_seconds") or 15)
            if prompt == TIMEOUT_PROMPT:
                self._send_error(HTTPStatus.REQUEST_TIMEOUT, "request_timeout", f"Mock runtime timed out after {timeout_seconds} seconds")
                return

            thread_id = str(payload.get("thread_id") or f"mock-{uuid.uuid4().hex[:12]}")
            session, continuity = _ensure_session(thread_id, prompt)
            response_text = f"Hello from mock runtime for {thread_id}"
            _complete_session(thread_id, prompt, response_text)
            response_payload = {
                "thread_id": thread_id,
                "response": response_text,
                "model": "mock-model",
                "status": "completed",
                "warnings": [],
                "artifacts": [],
                "tool_calls": [{"name": "mock.tool", "args": {"prompt": prompt}, "result": "ok", "status": "completed"}],
                "continuity": continuity,
                "metadata": {
                    "runtime": "mock-runtime",
                    "tokens": {"total": 12, "input": 5, "output": 7, "reasoning": 0, "cache": {"read": 0, "write": 0}},
                    "finish_reason": "stop",
                },
            }

            if parsed.path == "/invoke":
                self._send_json(HTTPStatus.OK, response_payload)
                return

            events = [
                ("response.started", {"session_id": session["session_id"], "model": "mock-model", "thread_id": thread_id}),
                ("response.delta", {"text": response_text, "session_id": session["session_id"]}),
                ("response.tool_call", {"name": "mock.tool", "id": "tool-1", "args": {"prompt": prompt}, "session_id": session["session_id"]}),
                ("response.tool_result", {"id": "tool-1", "result": "ok", "status": "completed", "session_id": session["session_id"]}),
                ("response.completed", {"session_id": session["session_id"], "tokens": {"total": 12}, "status": "completed", "finish_reason": "stop"}),
            ]
            sse_body = "".join(f"event: {event}\ndata: {json.dumps(data)}\n\n" for event, data in events)
            self._send_sse(sse_body)
            return

        if parsed.path in {"/cancel", "/abort"}:
            thread_id = (query.get("thread_id") or [""])[0]
            if not thread_id:
                self._send_error(HTTPStatus.BAD_REQUEST, "invalid_request", "thread_id query parameter is required")
                return
            session = self._thread_session(thread_id)
            if session is None:
                self._send_error(HTTPStatus.NOT_FOUND, "not_found", f"No session found for thread_id '{thread_id}'")
                return
            session["status"] = "cancelled"
            session["todos"] = [{"content": str(session["prompt"]), "status": "cancelled"}]
            self._send_json(
                HTTPStatus.OK,
                {"status": "cancelled", "session_id": session["session_id"], "thread_id": thread_id},
            )
            return

        if parsed.path.startswith("/question/"):
            self._send_error(HTTPStatus.NOT_FOUND, "not_found", "No pending question found")
            return

        self._send_error(HTTPStatus.NOT_FOUND, "not_found", "Unknown route")

    def log_message(self, format: str, *args: object) -> None:  # noqa: A003
        return


def main() -> None:
    server = ThreadingHTTPServer((HOST, PORT), MockRuntimeHandler)
    print(f"mock runtime listening on http://{HOST}:{PORT}", flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == "__main__":
    main()