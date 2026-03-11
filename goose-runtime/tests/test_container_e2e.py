import json
import os
import platform
import shutil
import socket
import subprocess
import tempfile
import threading
import time
import unittest
import uuid
from contextlib import suppress
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib import error, request


TEST_MODEL = "test-model"
DEFAULT_SYSTEM_PROMPT = "Container default system prompt."
COMMAND_TIMEOUT_SECONDS = int(os.getenv("GOOSE_E2E_COMMAND_TIMEOUT", "1200"))
READY_TIMEOUT_SECONDS = int(os.getenv("GOOSE_E2E_READY_TIMEOUT", "180"))
HTTP_TIMEOUT_SECONDS = int(os.getenv("GOOSE_E2E_HTTP_TIMEOUT", "90"))
CONTAINER_CLI = os.getenv("CONTAINER_CLI", "docker")
GOOSE_RUNTIME_DIR = Path(__file__).resolve().parents[1]


def docker_available() -> bool:
    if shutil.which(CONTAINER_CLI) is None:
        return False

    with suppress(OSError, subprocess.TimeoutExpired):
        result = subprocess.run(
            [CONTAINER_CLI, "version"],
            capture_output=True,
            check=False,
            text=True,
            timeout=30,
        )
        return result.returncode == 0

    return False


def run_command(*args: str, timeout: int = COMMAND_TIMEOUT_SECONDS) -> str:
    result = subprocess.run(
        list(args),
        capture_output=True,
        check=False,
        text=True,
        timeout=timeout,
    )
    if result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip() or "command failed"
        raise AssertionError(f"{' '.join(args)} failed: {message}")
    return result.stdout.strip()


def post_json(url: str, payload: dict[str, Any], *, accept: str = "application/json") -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    req = request.Request(
        url,
        data=body,
        headers={
            "Accept": accept,
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=HTTP_TIMEOUT_SECONDS) as response:
            data = response.read().decode("utf-8")
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise AssertionError(f"{url} returned {exc.code}: {detail}") from exc

    parsed = json.loads(data)
    if not isinstance(parsed, dict):
        raise AssertionError(f"Expected JSON object from {url}, got: {parsed!r}")
    return parsed


def collect_sse_events(url: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
    body = json.dumps(payload).encode("utf-8")
    req = request.Request(
        url,
        data=body,
        headers={
            "Accept": "text/event-stream",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    events: list[dict[str, Any]] = []
    event_name = ""
    event_data: list[str] = []

    try:
        with request.urlopen(req, timeout=HTTP_TIMEOUT_SECONDS) as response:
            for raw_line in response:
                line = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")
                if not line:
                    if event_name and event_data:
                        payload_text = "\n".join(event_data)
                        events.append({"event": event_name, "payload": json.loads(payload_text)})
                    event_name = ""
                    event_data = []
                    continue
                if line.startswith("event: "):
                    event_name = line[len("event: ") :]
                    continue
                if line.startswith("data: "):
                    event_data.append(line[len("data: ") :])
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise AssertionError(f"{url} returned {exc.code}: {detail}") from exc

    return events


def wait_for_ready(url: str, timeout_seconds: int) -> dict[str, Any]:
    deadline = time.time() + timeout_seconds
    last_error = "runtime did not become ready"

    while time.time() < deadline:
        try:
            with request.urlopen(url, timeout=5) as response:
                payload = json.loads(response.read().decode("utf-8"))
            if isinstance(payload, dict) and payload.get("status") == "ready":
                return payload
            last_error = f"unexpected readiness payload: {payload!r}"
        except Exception as exc:  # pragma: no cover - exercised only while waiting on external process
            last_error = str(exc)
        time.sleep(1)

    raise AssertionError(last_error)


def extract_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts = [extract_text(item) for item in value]
        return "\n".join(part for part in parts if part).strip()
    if isinstance(value, dict):
        if value.get("type") == "text":
            return extract_text(value.get("text"))
        for key in ("text", "content"):
            text = extract_text(value.get(key))
            if text:
                return text
    return ""


def find_message(messages: list[dict[str, Any]], role: str) -> str:
    for message in messages:
        if str(message.get("role", "")).strip().lower() != role:
            continue
        text = extract_text(message.get("content"))
        if text:
            return text
    return ""


def pick_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen(1)
        return int(sock.getsockname()[1])


class FakeOpenAIHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:  # noqa: N802
        self.server.record_request(self.path, None)  # type: ignore[attr-defined]
        self._send_json(
            {
                "object": "list",
                "data": [{"id": TEST_MODEL, "object": "model", "owned_by": "tests"}],
            }
        )

    def do_POST(self) -> None:  # noqa: N802
        content_length = int(self.headers.get("Content-Length", "0"))
        raw_body = self.rfile.read(content_length) if content_length else b"{}"
        payload = json.loads(raw_body.decode("utf-8"))
        self.server.record_request(self.path, payload)  # type: ignore[attr-defined]

        messages = payload.get("messages") if isinstance(payload, dict) else []
        if not isinstance(messages, list):
            messages = []
        user_prompt = find_message([item for item in messages if isinstance(item, dict)], "user").lower()
        response_text = "stream test ok" if "stream" in user_prompt else "invoke test ok"

        if payload.get("stream"):
            self._send_stream(response_text)
            return

        self._send_json(
            {
                "id": "chatcmpl-test",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": TEST_MODEL,
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": response_text},
                        "finish_reason": "stop",
                    }
                ],
            }
        )

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
        return

    def _send_json(self, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_stream(self, response_text: str) -> None:
        midpoint = max(1, len(response_text) // 2)
        chunks = [response_text[:midpoint], response_text[midpoint:]]

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()

        for index, chunk in enumerate(chunks):
            if not chunk:
                continue
            payload = {
                "id": "chatcmpl-test",
                "object": "chat.completion.chunk",
                "created": int(time.time()),
                "model": TEST_MODEL,
                "choices": [
                    {
                        "index": 0,
                        "delta": {"role": "assistant", "content": chunk} if index == 0 else {"content": chunk},
                        "finish_reason": None,
                    }
                ],
            }
            self.wfile.write(f"data: {json.dumps(payload)}\n\n".encode("utf-8"))
            self.wfile.flush()

        final_payload = {
            "id": "chatcmpl-test",
            "object": "chat.completion.chunk",
            "created": int(time.time()),
            "model": TEST_MODEL,
            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
        }
        self.wfile.write(f"data: {json.dumps(final_payload)}\n\n".encode("utf-8"))
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()


class FakeOpenAIServer(ThreadingHTTPServer):
    def __init__(self, server_address: tuple[str, int]):
        super().__init__(server_address, FakeOpenAIHandler)
        self._requests: list[dict[str, Any]] = []
        self._lock = threading.Lock()

    def record_request(self, path: str, payload: dict[str, Any] | None) -> None:
        with self._lock:
            self._requests.append({"path": path, "payload": payload})

    def snapshot_requests(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._requests)


@unittest.skipUnless(docker_available(), "Docker is required for Goose container E2E tests")
class GooseContainerE2ETests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.image_tag = f"ai-goose-runtime-e2e:{uuid.uuid4().hex[:12]}"
        cls.container_name = f"ai-goose-runtime-e2e-{uuid.uuid4().hex[:12]}"
        cls.runtime_port = pick_free_port()
        cls.workspace_dir = tempfile.TemporaryDirectory()
        workspace_root = Path(cls.workspace_dir.name)
        (workspace_root / "project").mkdir(parents=True, exist_ok=True)
        (workspace_root / "project" / "marker.txt").write_text("container e2e workspace\n", encoding="utf-8")

        cls.fake_server = FakeOpenAIServer(("0.0.0.0", 0))
        cls.fake_server_thread = threading.Thread(target=cls.fake_server.serve_forever, daemon=True)
        cls.fake_server_thread.start()
        cls.fake_server_port = int(cls.fake_server.server_address[1])

        run_command(CONTAINER_CLI, "build", "-t", cls.image_tag, str(GOOSE_RUNTIME_DIR))

        docker_run_args = [
            CONTAINER_CLI,
            "run",
            "-d",
            "--rm",
            "--name",
            cls.container_name,
            "-p",
            f"{cls.runtime_port}:8080",
            "-v",
            f"{workspace_root}:/workspace",
            "-e",
            "GOOSE_PROVIDER=openai",
            "-e",
            f"GOOSE_MODEL={TEST_MODEL}",
            "-e",
            f"GOOSE_SYSTEM_PROMPT={DEFAULT_SYSTEM_PROMPT}",
            "-e",
            "OPENAI_API_KEY=test-openai-key",
            "-e",
            f"OPENAI_HOST=http://host.docker.internal:{cls.fake_server_port}",
            "-e",
            "OPENAI_BASE_PATH=v1/chat/completions",
            "-e",
            "GOOSE_PROVIDER__TYPE=openai",
            "-e",
            "GOOSE_PROVIDER__API_KEY=test-openai-key",
            "-e",
            f"GOOSE_PROVIDER__HOST=http://host.docker.internal:{cls.fake_server_port}",
            cls.image_tag,
        ]
        if platform.system() == "Linux":
            docker_run_args[2:2] = ["--add-host", "host.docker.internal:host-gateway"]

        run_command(*docker_run_args)
        wait_for_ready(f"http://127.0.0.1:{cls.runtime_port}/ready", READY_TIMEOUT_SECONDS)

    @classmethod
    def tearDownClass(cls) -> None:
        with suppress(Exception):
            run_command(CONTAINER_CLI, "rm", "-f", cls.container_name, timeout=60)
        with suppress(Exception):
            run_command(CONTAINER_CLI, "rmi", "-f", cls.image_tag, timeout=120)
        with suppress(Exception):
            cls.fake_server.shutdown()
        with suppress(Exception):
            cls.fake_server.server_close()
        with suppress(Exception):
            cls.fake_server_thread.join(timeout=5)
        with suppress(Exception):
            cls.workspace_dir.cleanup()

    def test_invoke_runs_inside_real_goose_container(self) -> None:
        response = post_json(
            f"http://127.0.0.1:{self.runtime_port}/invoke",
            {
                "prompt": "Reply with the invoke sentinel only.",
                "system": "Request-level read-only note.",
                "max_turns": 3,
                "working_directory": "project",
            },
        )

        self.assertEqual(response.get("status"), "completed")
        self.assertEqual(response.get("model"), TEST_MODEL)
        self.assertIn("invoke test ok", str(response.get("response", "")))
        self.assertTrue(str(response.get("thread_id", "")).strip())

        completion_request = next(
            request_entry
            for request_entry in reversed(self.fake_server.snapshot_requests())
            if isinstance(request_entry.get("payload"), dict)
            and not bool(request_entry["payload"].get("stream"))
            and str(request_entry.get("path", "")).endswith("chat/completions")
        )
        messages = completion_request["payload"].get("messages")
        self.assertIsInstance(messages, list)
        system_text = find_message([item for item in messages if isinstance(item, dict)], "system")
        user_text = find_message([item for item in messages if isinstance(item, dict)], "user")
        self.assertIn(DEFAULT_SYSTEM_PROMPT, system_text)
        self.assertIn("Request-level read-only note.", system_text)
        self.assertIn("invoke sentinel", user_text.lower())

    def test_invoke_stream_emits_delta_and_completed_events(self) -> None:
        events = collect_sse_events(
            f"http://127.0.0.1:{self.runtime_port}/invoke/stream",
            {
                "prompt": "Reply with the stream sentinel only.",
                "max_turns": 2,
                "working_directory": "project",
            },
        )

        event_names = [str(event.get("event", "")) for event in events]
        self.assertIn("response.delta", event_names)
        self.assertIn("response.completed", event_names)

        completed_event = next(event for event in events if event.get("event") == "response.completed")
        completed_payload = completed_event.get("payload")
        self.assertIsInstance(completed_payload, dict)
        self.assertEqual(completed_payload.get("status"), "completed")
        self.assertIn("stream test ok", str(completed_payload.get("response", "")))

        stream_request = next(
            request_entry
            for request_entry in reversed(self.fake_server.snapshot_requests())
            if isinstance(request_entry.get("payload"), dict)
            and bool(request_entry["payload"].get("stream"))
            and str(request_entry.get("path", "")).endswith("chat/completions")
        )
        messages = stream_request["payload"].get("messages")
        self.assertIsInstance(messages, list)
        user_text = find_message([item for item in messages if isinstance(item, dict)], "user")
        self.assertIn("stream sentinel", user_text.lower())


if __name__ == "__main__":
    unittest.main()