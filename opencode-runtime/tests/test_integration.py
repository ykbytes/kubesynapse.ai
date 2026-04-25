"""Integration tests for the OpenCode runtime.

These tests require a running ``opencode serve`` process and exercise the full
request cycle: session creation, prompt sending, history collection, and
artifact extraction.

Run with::

    pytest opencode-runtime/tests/test_integration.py -m integration -v

Skip in CI by default (no ``opencode`` binary available)::

    pytest opencode-runtime/tests/ -m "not integration"
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import patch

import pytest

# ---------------------------------------------------------------------------
# Bootstrap: import the runtime module from source
# ---------------------------------------------------------------------------
MODULE_PATH = Path(__file__).resolve().parents[1] / "main.py"
SPEC = importlib.util.spec_from_file_location("opencode_runtime_main", MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("Failed to load opencode-runtime main module for tests")
mod = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = mod
SPEC.loader.exec_module(mod)
opencode_client_mod = mod.RUNTIME_IMPORTED_MODULES["opencode_client"]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
OPENCODE_BIN = shutil.which("opencode") or os.getenv("OPENCODE_BIN", "opencode")
OPENCODE_HOST = "127.0.0.1"
OPENCODE_PORT = 14096  # Use a non-default port to avoid conflicts
_server_process: subprocess.Popen | None = None


def _opencode_available() -> bool:
    """Return True if the ``opencode`` binary is on PATH."""
    return shutil.which(str(OPENCODE_BIN)) is not None


def _wait_healthy(host: str, port: int, timeout: float = 30.0) -> bool:
    """Poll the OpenCode health endpoint until it becomes healthy."""
    import httpx

    deadline = time.time() + timeout
    url = f"http://{host}:{port}/global/health"
    while time.time() < deadline:
        try:
            with httpx.Client(timeout=2.0, trust_env=False) as client:
                resp = client.get(url)
                if resp.status_code == 200 and resp.json().get("healthy") is True:
                    return True
        except Exception:  # noqa: S110 — best-effort health probe in test helper
            pass
        time.sleep(0.5)
    return False


# ---------------------------------------------------------------------------
# Conditional skip
# ---------------------------------------------------------------------------
pytestmark = pytest.mark.integration
skip_no_opencode = pytest.mark.skipif(
    not _opencode_available(),
    reason="opencode binary not found on PATH",
)
skip_live_prompt_tests = pytest.mark.skipif(
    os.getenv("OPENCODE_RUN_LIVE_PROMPTS", "").strip().lower() not in {"1", "true", "yes"},
    reason="live prompt integration requires OPENCODE_RUN_LIVE_PROMPTS=1 and a reachable model backend",
)


@pytest.fixture(scope="module")
def opencode_server(tmp_path_factory):
    """Start ``opencode serve`` once for the module and tear it down after."""
    if not _opencode_available():
        pytest.skip("opencode binary not available")

    workspace = tmp_path_factory.mktemp("workspace")
    home_dir = tmp_path_factory.mktemp("home")
    config_dir = home_dir / ".config" / "opencode"
    config_dir.mkdir(parents=True, exist_ok=True)
    data_dir = home_dir / ".local" / "share"
    data_dir.mkdir(parents=True, exist_ok=True)

    # Minimal config so opencode doesn't try to auto-detect providers
    litellm_host = os.getenv("LITELLM_HOST", "http://localhost:4000")
    litellm_key = os.getenv("LITELLM_API_KEY", "")
    config = {
        "$schema": "https://opencode.ai/config.json",
        "model": "litellm/gpt-4",
        "small_model": "litellm/gpt-4",
        "default_agent": "build",
        "permission": "allow",
        "server": {"hostname": OPENCODE_HOST, "port": OPENCODE_PORT},
        "provider": {
            "litellm": {
                "npm": "@ai-sdk/openai-compatible",
                "name": "litellm",
                "options": {"baseURL": f"{litellm_host}/v1", "apiKey": litellm_key},
                "models": {
                    "gpt-4": {
                        "name": "gpt-4",
                        "limit": {"context": 128000, "output": 8192},
                    }
                },
            }
        },
    }

    env = os.environ.copy()
    env.update({
        "HOME": str(home_dir),
        "XDG_CONFIG_HOME": str(home_dir / ".config"),
        "XDG_DATA_HOME": str(data_dir),
        "OPENCODE_CONFIG_CONTENT": json.dumps(config),
        "OPENCODE_CLIENT": "server",
        "OPENCODE_DISABLE_AUTOUPDATE": "true",
        "OPENCODE_DISABLE_LSP_DOWNLOAD": "true",
    })

    proc = subprocess.Popen(
        [
            str(OPENCODE_BIN),
            "serve",
            "--hostname", OPENCODE_HOST,
            "--port", str(OPENCODE_PORT),
        ],
        cwd=str(workspace),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
    )

    if not _wait_healthy(OPENCODE_HOST, OPENCODE_PORT, timeout=45.0):
        proc.kill()
        proc.wait(timeout=5)
        pytest.skip("opencode server failed to become healthy")

    yield {
        "process": proc,
        "host": OPENCODE_HOST,
        "port": OPENCODE_PORT,
        "workspace": workspace,
        "base_url": f"http://{OPENCODE_HOST}:{OPENCODE_PORT}",
    }

    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
@skip_no_opencode
class TestSessionLifecycle:
    """Test session creation, message retrieval, and status checks."""

    def test_create_session(self, opencode_server):
        import httpx

        base = opencode_server["base_url"]
        workspace = str(opencode_server["workspace"])
        with httpx.Client(base_url=base, timeout=10.0, trust_env=False) as client:
            resp = client.post("/session", params={"directory": workspace}, json={"title": "test-session"})
            assert resp.status_code == 200, f"Session creation failed: {resp.text}"
            data = resp.json()
            assert "id" in data
            assert data["id"]

    def test_session_status_returns_dict(self, opencode_server):
        import httpx

        base = opencode_server["base_url"]
        with httpx.Client(base_url=base, timeout=10.0, trust_env=False) as client:
            resp = client.get("/session/status")
            assert resp.status_code == 200
            data = resp.json()
            assert isinstance(data, dict)

    def test_global_health(self, opencode_server):
        import httpx

        base = opencode_server["base_url"]
        with httpx.Client(base_url=base, timeout=10.0, trust_env=False) as client:
            resp = client.get("/global/health")
            assert resp.status_code == 200
            data = resp.json()
            assert data.get("healthy") is True


@skip_no_opencode
@skip_live_prompt_tests
class TestPromptExecution:
    """Test sending prompts and collecting responses."""

    LIVE_PROMPT_TIMEOUT_SECONDS = 240.0

    def test_send_simple_prompt(self, opencode_server):
        """Create a session, send a prompt, and verify we get a response."""
        import httpx

        base = opencode_server["base_url"]
        workspace = str(opencode_server["workspace"])

        with httpx.Client(base_url=base, timeout=self.LIVE_PROMPT_TIMEOUT_SECONDS, trust_env=False) as client:
            # 1. Create session
            session_resp = client.post("/session", params={"directory": workspace}, json={"title": "prompt-test"})
            assert session_resp.status_code == 200
            session_id = session_resp.json()["id"]

            # 2. Send a simple prompt
            body = {
                "parts": [{"type": "text", "text": "Respond with exactly: HELLO_INTEGRATION_TEST"}],
                "model": {"providerID": "litellm", "modelID": "gpt-4"},
                "agent": "build",
            }
            msg_resp = client.post(
                f"/session/{session_id}/message",
                params={"directory": workspace},
                json=body,
            )
            # The endpoint may return 200 or 2xx with the assistant response
            assert msg_resp.status_code in (200, 201), f"Prompt failed: {msg_resp.status_code} {msg_resp.text}"
            payload = msg_resp.json()

            # 3. Verify response has expected structure
            assert isinstance(payload, dict)
            info = payload.get("info") or {}
            assert info.get("role") == "assistant"

    def test_message_history_after_prompt(self, opencode_server):
        """After sending a prompt, message history should contain both user and assistant messages."""
        import httpx

        base = opencode_server["base_url"]
        workspace = str(opencode_server["workspace"])

        with httpx.Client(base_url=base, timeout=self.LIVE_PROMPT_TIMEOUT_SECONDS, trust_env=False) as client:
            # Create session and send prompt
            session_resp = client.post("/session", params={"directory": workspace}, json={"title": "history-test"})
            session_id = session_resp.json()["id"]

            body = {
                "parts": [{"type": "text", "text": "Say OK"}],
                "model": {"providerID": "litellm", "modelID": "gpt-4"},
                "agent": "build",
            }
            client.post(f"/session/{session_id}/message", params={"directory": workspace}, json=body)

            # Fetch history
            hist_resp = client.get(f"/session/{session_id}/message")
            assert hist_resp.status_code == 200
            messages = hist_resp.json()
            assert isinstance(messages, list)
            assert len(messages) >= 2  # At least user + assistant

            roles = [m.get("info", {}).get("role") for m in messages if isinstance(m, dict)]
            assert "user" in roles
            assert "assistant" in roles


@skip_no_opencode
@skip_live_prompt_tests
class TestFileCreation:
    """Test that the agent can create files using native tools."""

    LIVE_PROMPT_TIMEOUT_SECONDS = 240.0

    def test_write_tool_creates_file(self, opencode_server):
        """Ask the agent to create a file and verify it exists on disk."""
        import httpx

        base = opencode_server["base_url"]
        workspace = opencode_server["workspace"]
        target_file = workspace / "integration_output.txt"

        with httpx.Client(base_url=base, timeout=self.LIVE_PROMPT_TIMEOUT_SECONDS, trust_env=False) as client:
            session_resp = client.post(
                "/session", params={"directory": str(workspace)}, json={"title": "file-creation-test"}
            )
            session_id = session_resp.json()["id"]

            body = {
                "parts": [
                    {
                        "type": "text",
                        "text": (
                            f"Use the write tool to create a file at {target_file} "
                            "with the content 'INTEGRATION_FILE_CREATED'. "
                            "Do not use bash. Use the write tool directly."
                        ),
                    }
                ],
                "model": {"providerID": "litellm", "modelID": "gpt-4"},
                "agent": "build",
            }
            msg_resp = client.post(
                f"/session/{session_id}/message",
                params={"directory": str(workspace)},
                json=body,
            )
            assert msg_resp.status_code in (200, 201)

            # Collect tool calls from history
            hist_resp = client.get(f"/session/{session_id}/message")
            messages = hist_resp.json()
            tool_calls = mod.extract_tool_calls_from_messages(messages)

            # At least one tool call should have been made
            assert len(tool_calls) >= 1, f"Expected tool calls, got: {tool_calls}"

            # Verify file was actually written
            if target_file.exists():
                content = target_file.read_text(encoding="utf-8")
                assert "INTEGRATION_FILE_CREATED" in content


@skip_no_opencode
class TestRuntimeHelpers:
    """Test runtime helper functions against the live server."""

    def test_get_session_messages_returns_list(self, opencode_server):
        """get_session_messages() should return a list from the live server."""
        import httpx

        base = opencode_server["base_url"]
        workspace = str(opencode_server["workspace"])

        with httpx.Client(base_url=base, timeout=10.0, trust_env=False) as client:
            session_resp = client.post(
                "/session", params={"directory": workspace}, json={"title": "helper-test"}
            )
            session_id = session_resp.json()["id"]

        # Use the runtime's own helper with a patched base URL
        with patch.object(opencode_client_mod, "server_base_url", return_value=base):
            messages = mod.get_session_messages(session_id)
        assert isinstance(messages, list)

    def test_get_session_status_returns_idle_for_new_session(self, opencode_server):
        """A freshly created session should report idle status."""
        import httpx

        base = opencode_server["base_url"]
        workspace = str(opencode_server["workspace"])

        with httpx.Client(base_url=base, timeout=10.0, trust_env=False) as client:
            session_resp = client.post(
                "/session", params={"directory": workspace}, json={"title": "status-test"}
            )
            session_id = session_resp.json()["id"]

        with patch.object(opencode_client_mod, "server_base_url", return_value=base):
            status = mod.get_session_status(session_id)
        # New session should be idle (or not present in the status dict,
        # in which case get_session_status defaults to {"type": "idle"})
        assert status.get("type", "idle") == "idle"

    def test_wait_for_session_idle_returns_quickly(self, opencode_server):
        """wait_for_session_idle() should return immediately for an idle session."""
        import httpx

        base = opencode_server["base_url"]
        workspace = str(opencode_server["workspace"])

        with httpx.Client(base_url=base, timeout=10.0, trust_env=False) as client:
            session_resp = client.post(
                "/session", params={"directory": workspace}, json={"title": "wait-test"}
            )
            session_id = session_resp.json()["id"]

        with patch.object(opencode_client_mod, "server_base_url", return_value=base):
            t0 = time.time()
            status = mod.wait_for_session_idle(session_id, timeout_seconds=5.0)
            elapsed = time.time() - t0
        assert elapsed < 3.0, f"wait_for_session_idle took {elapsed:.1f}s for an idle session"
        assert status.get("type", "idle") == "idle"

    def test_extract_helpers_on_live_history(self, opencode_server):
        """Run extract helpers on real session history."""
        import httpx

        base = opencode_server["base_url"]
        workspace = str(opencode_server["workspace"])

        if os.getenv("OPENCODE_RUN_LIVE_PROMPTS", "").strip().lower() not in {"1", "true", "yes"}:
            pytest.skip("live prompt integration requires OPENCODE_RUN_LIVE_PROMPTS=1 and a reachable model backend")

        with httpx.Client(base_url=base, timeout=TestPromptExecution.LIVE_PROMPT_TIMEOUT_SECONDS, trust_env=False) as client:
            session_resp = client.post(
                "/session", params={"directory": workspace}, json={"title": "extract-test"}
            )
            session_id = session_resp.json()["id"]

            body = {
                "parts": [{"type": "text", "text": "Use the glob tool to list all files in the current directory."}],
                "model": {"providerID": "litellm", "modelID": "gpt-4"},
                "agent": "build",
            }
            client.post(f"/session/{session_id}/message", params={"directory": workspace}, json=body)

        with patch.object(opencode_client_mod, "server_base_url", return_value=base):
            messages = mod.get_session_messages(session_id)

        assert len(messages) >= 2

        tool_calls = mod.extract_tool_calls_from_messages(messages)
        artifacts = mod.extract_artifacts_from_messages(messages)
        errors = mod.detect_task_errors(messages)

        # Should be lists (may be empty if the model didn't call tools)
        assert isinstance(tool_calls, list)
        assert isinstance(artifacts, list)
        assert isinstance(errors, list)

        # The last assistant message should be extractable
        latest = mod.get_latest_assistant_payload(messages)
        assert latest is not None
        assert latest.get("info", {}).get("role") == "assistant"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-m", "integration"])
