"""§3.5 Process supervisor and §7.2 graceful shutdown coordination."""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

import httpx
from config import (
    HOME_DIR,
    LITELLM_API_KEY,
    OPENCODE_BIN,
    OPENCODE_CONFIG_DIR,
    OPENCODE_SERVER_HOST,
    OPENCODE_SERVER_PORT,
    OPENCODE_WORKDIR,
    SERVER_POLL_INTERVAL_SECONDS,
    SERVER_STARTUP_TIMEOUT_SECONDS,
    XDG_CONFIG_HOME,
    XDG_DATA_HOME,
    build_litellm_base_url,
    server_base_url,
)
from providers import OPENCODE_GO_PROVIDER, LITELLM_PROVIDER, get_provider

logger = logging.getLogger("opencode-runtime")

# ---------------------------------------------------------------------------
# Shared mutable state for process lifecycle
# ---------------------------------------------------------------------------
_shutting_down = False
_shutdown_event = threading.Event()
_runtime_process: subprocess.Popen[str] | None = None
_runtime_ready = False
_runtime_lock = threading.Lock()

# Log file paths for subprocess output (prevents pipe deadlock)
_LOG_DIR = Path(HOME_DIR) / ".local" / "share" / "opencode-runtime" / "logs"
_STDOUT_LOG = _LOG_DIR / "opencode-stdout.log"
_STDERR_LOG = _LOG_DIR / "opencode-stderr.log"

SUPERVISOR_POLL_SECONDS = max(float(os.getenv("OPENCODE_SUPERVISOR_POLL_SECONDS", "5")), 1.0)
SUPERVISOR_MAX_RESTARTS = max(int(os.getenv("OPENCODE_SUPERVISOR_MAX_RESTARTS", "5")), 0)
_supervisor_restart_count = 0


def is_shutting_down() -> bool:
    """Return True if a graceful shutdown is in progress."""
    return _shutting_down


# ---------------------------------------------------------------------------
# Runtime validation
# ---------------------------------------------------------------------------


def validate_runtime_startup() -> None:
    """Verify the OpenCode binary is available and executable."""
    binary_path = Path(OPENCODE_BIN)
    if binary_path.is_absolute():
        if not binary_path.exists() or not os.access(binary_path, os.X_OK):
            raise RuntimeError(f"OpenCode binary '{OPENCODE_BIN}' is not executable")
        return
    if shutil.which(OPENCODE_BIN) is None:
        raise RuntimeError(f"OpenCode binary '{OPENCODE_BIN}' was not found on PATH")


def _resolve_provider_id() -> str:
    """Determine which opencode provider to use."""
    return os.getenv("OPENCODE_PROVIDER", "litellm").strip().lower() or "litellm"


def build_server_env(config_content: dict[str, Any]) -> dict[str, str]:
    """Build the environment dict for the OpenCode subprocess."""
    env = os.environ.copy()
    env.update(
        {
            "HOME": HOME_DIR,
            "XDG_CONFIG_HOME": XDG_CONFIG_HOME,
            "XDG_DATA_HOME": XDG_DATA_HOME,
            "OPENCODE_CONFIG_DIR": OPENCODE_CONFIG_DIR,
            "OPENCODE_CONFIG_CONTENT": json.dumps(config_content, ensure_ascii=False),
            "OPENCODE_CLIENT": "server",
            "OPENCODE_DISABLE_AUTOUPDATE": "true",
            "OPENCODE_DISABLE_LSP_DOWNLOAD": "true",
            "OPENCODE_DISABLE_DEFAULT_PLUGINS": env.get("OPENCODE_DISABLE_DEFAULT_PLUGINS", "false") or "false",
            "OPENCODE_SERVER_PASSWORD": env.get("OPENCODE_SERVER_PASSWORD", ""),
        }
    )

    provider_id = _resolve_provider_id()
    provider = get_provider(provider_id)

    # Resolve provider-specific env vars from the provider mapping
    resolved = provider.resolve_env()
    for key, value in resolved.items():
        env[key] = value

    # Extract API key from OPENCODE_AUTH_CONTENT for opencode/openai-compatible providers
    # The Vercel AI SDK reads OPENAI_API_KEY for @ai-sdk/openai-compatible
    _inject_auth_key_from_content(env, provider_id)

    # Special case: litellm constructs BASE_URL from LITELLM_HOST+LITELLM_BASE_PATH
    if provider.id == "litellm":
        base_url = build_litellm_base_url()
        if base_url:
            env["OPENAI_BASE_URL"] = base_url
        if LITELLM_API_KEY and "OPENAI_API_KEY" not in env:
            env["OPENAI_API_KEY"] = LITELLM_API_KEY

    return env


def _inject_auth_key_from_content(env: dict[str, str], provider_id: str) -> None:
    """Read OPENCODE_AUTH_CONTENT and inject OPENAI_API_KEY for the AI SDK."""
    auth_content = os.getenv("OPENCODE_AUTH_CONTENT", "").strip()
    if not auth_content:
        return
    try:
        auth_data = json.loads(auth_content)
    except (json.JSONDecodeError, TypeError):
        return
    if not isinstance(auth_data, dict):
        return
    # Try exact provider ID first, then try without dash suffix
    for key in (provider_id, provider_id.replace("-go", ""), provider_id.replace("-", "")):
        entry = auth_data.get(key)
        if isinstance(entry, dict) and entry.get("type") == "api":
            api_key = str(entry.get("key", "")).strip()
            if api_key:
                env.setdefault("OPENAI_API_KEY", api_key)
                env.setdefault("OPENCODE_API_KEY", api_key)
                logger.info("Injected API key from OPENCODE_AUTH_CONTENT for provider '%s' (matched key '%s')", provider_id, key)
                return


# ---------------------------------------------------------------------------
# Process start / readiness
# ---------------------------------------------------------------------------


def _start_opencode_process(env: dict[str, str]) -> subprocess.Popen[str]:
    """Start the OpenCode serve subprocess.

    Redirects stdout/stderr to log files to prevent pipe buffer deadlocks.
    The log files are rotated on each restart (previous content is overwritten).
    """
    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    stdout_fh = open(_STDOUT_LOG, "w", encoding="utf-8", buffering=1)  # noqa: SIM115 — file handle managed elsewhere
    stderr_fh = open(_STDERR_LOG, "w", encoding="utf-8", buffering=1)  # noqa: SIM115 — file handle managed elsewhere
    return subprocess.Popen(
        [
            OPENCODE_BIN,
            "serve",
            "--hostname",
            OPENCODE_SERVER_HOST,
            "--port",
            str(OPENCODE_SERVER_PORT),
        ],
        cwd=OPENCODE_WORKDIR,
        env=env,
        stdout=stdout_fh,
        stderr=stderr_fh,
        text=True,
    )


def wait_for_server_ready(process: subprocess.Popen[str]) -> None:
    """Block until the OpenCode server responds healthy or timeout/exit."""
    deadline = time.time() + SERVER_STARTUP_TIMEOUT_SECONDS
    health_url = f"{server_base_url()}/global/health"
    while time.time() < deadline:
        if process.poll() is not None:
            # Read from log files since we no longer use PIPE
            stdout_out = ""
            stderr_out = ""
            try:
                if _STDOUT_LOG.exists():
                    stdout_out = _STDOUT_LOG.read_text(encoding="utf-8", errors="replace")[:4000]
            except OSError:
                pass
            try:
                if _STDERR_LOG.exists():
                    stderr_out = _STDERR_LOG.read_text(encoding="utf-8", errors="replace")[:4000]
            except OSError:
                pass
            logger.error(
                "OpenCode server exited with code %s.\nSTDOUT: %s\nSTDERR: %s",
                process.returncode,
                stdout_out,
                stderr_out,
            )
            raise RuntimeError("OpenCode server exited before becoming ready")
        try:
            with httpx.Client(timeout=2.0, trust_env=False) as client:
                response = client.get(health_url)
                if response.status_code == 200 and response.json().get("healthy") is True:
                    return
        except httpx.HTTPError:
            pass
        time.sleep(SERVER_POLL_INTERVAL_SECONDS)
    raise RuntimeError("Timed out while waiting for the OpenCode server to become ready")


# ---------------------------------------------------------------------------
# Background process supervisor
# ---------------------------------------------------------------------------


def _run_process_supervisor(env: dict[str, str]) -> None:
    """Background thread that monitors and restarts the OpenCode subprocess."""
    global _runtime_process, _runtime_ready, _supervisor_restart_count

    while not _shutdown_event.is_set():
        _shutdown_event.wait(timeout=SUPERVISOR_POLL_SECONDS)
        if _shutdown_event.is_set():
            break

        with _runtime_lock:
            proc = _runtime_process

        if proc is None:
            continue

        if proc.poll() is not None:
            exit_code = proc.returncode
            with _runtime_lock:
                _runtime_ready = False
                current_restart_count = _supervisor_restart_count

            logger.warning(
                "OpenCode subprocess exited unexpectedly (code=%s, restarts=%d/%d).",
                exit_code,
                current_restart_count,
                SUPERVISOR_MAX_RESTARTS,
            )

            if current_restart_count >= SUPERVISOR_MAX_RESTARTS:
                logger.error(
                    "Max supervisor restarts (%d) reached; not restarting OpenCode subprocess.",
                    SUPERVISOR_MAX_RESTARTS,
                )
                continue

            try:
                new_process = _start_opencode_process(env)
                wait_for_server_ready(new_process)
                with _runtime_lock:
                    _supervisor_restart_count += 1
                    _runtime_process = new_process
                    _runtime_ready = True
                logger.info(
                    "OpenCode subprocess restarted successfully (attempt %d/%d).",
                    _supervisor_restart_count,
                    SUPERVISOR_MAX_RESTARTS,
                )
            except Exception as exc:
                with _runtime_lock:
                    _supervisor_restart_count += 1
                logger.error("Failed to restart OpenCode subprocess: %s", exc)


# ---------------------------------------------------------------------------
# §7.2 — Graceful shutdown
# ---------------------------------------------------------------------------


def _sigterm_handler(signum: int, frame: Any) -> None:
    """Handle SIGTERM for graceful shutdown."""
    global _shutting_down
    _shutting_down = True
    _shutdown_event.set()
    logger.info("Received signal %d, initiating graceful shutdown.", signum)
