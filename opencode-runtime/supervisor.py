"""§3.5 Process supervisor and §7.2 graceful shutdown coordination."""

from __future__ import annotations

import json
import logging
import os
import secrets
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
from providers import get_provider

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

# Track open log file handles so they can be closed before re-opening on restart
_active_stdout_fh: Any = None
_active_stderr_fh: Any = None
_generated_server_password: str | None = None

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


def resolve_opencode_server_password() -> str:
    """Return the Basic Auth password for the local OpenCode server."""
    global _generated_server_password
    configured = os.getenv("OPENCODE_SERVER_PASSWORD", "").strip()
    if configured:
        return configured
    if _generated_server_password is None:
        _generated_server_password = secrets.token_urlsafe(32)
        logger.info("Generated per-process OpenCode server password for local Basic Auth")
    return _generated_server_password


def resolve_opencode_server_username() -> str:
    """Return the Basic Auth username for the local OpenCode server."""
    return os.getenv("OPENCODE_SERVER_USERNAME", "opencode").strip() or "opencode"


_ENV_ALLOWLIST: frozenset[str] = frozenset({
    "HOME",
    "PATH",
    "LANG",
    "LC_ALL",
    "TERM",
    "TZ",
    "XDG_CONFIG_HOME",
    "XDG_DATA_HOME",
    "OPENCODE_CONFIG_DIR",
    "OPENCODE_WORKDIR",
    "OPENCODE_BIN",
    "OPENCODE_PROVIDER",
    "OPENCODE_MODEL",
    "OPENCODE_SYSTEM_PROMPT",
    "OPENCODE_DEFAULT_AGENT",
    "OPENCODE_MODEL_OUTPUT_LIMIT",
    "OPENCODE_AUTONOMOUS_MAX_RETRIES",
    "OPENCODE_AUTONOMOUS_MAX_TURNS",
    "OPENCODE_SESSION_IDLE_TIMEOUT_SECONDS",
    "OPENCODE_SESSION_IDLE_POLL_SECONDS",
    "OPENCODE_SESSION_IDLE_MAX_POLL_SECONDS",
    "OPENCODE_LIVE_UPDATE_TIMEOUT_SECONDS",
    "OPENCODE_LIVE_UPDATE_MAX_WALL_SECONDS",
    "OPENCODE_DISABLE_DEFAULT_PLUGINS",
    "OPENCODE_DISABLE_AUTOUPDATE",
    "OPENCODE_DISABLE_LSP_DOWNLOAD",
    "OPENCODE_ARTIFACT_MAX_FILES",
    "OPENCODE_CLIENT",
    "OPENCODE_SERVER_HOST",
    "OPENCODE_SERVER_PORT",
    "MCP_SERVERS",
    "MCP_HUB_NAMESPACE",
    "HELM_RELEASE_NAME",
    "CREDENTIAL_PROXY_ENABLED",
    "CREDENTIAL_PROXY_MCP_HUB_PORT",
    "KUBESYNAPSE_AGENT_NAME",
    "KUBESYNAPSE_NAMESPACE",
    "AGENT_NAME",
    "GIT_AUTHOR_NAME",
    "GIT_AUTHOR_EMAIL",
    "GIT_COMMITTER_NAME",
    "GIT_CONFIG_GLOBAL",
    "LITELLM_HOST",
    "LITELLM_BASE_PATH",
    "OTEL_EXPORTER_OTLP_ENDPOINT",
    "OPENCODE_SELECTED_PROVIDER_JSON",
    "OPENCODE_RUNTIME_CONFIG_FILES_JSON",
    "OPENCODE_MCP_CONNECTIONS_JSON",
    "OPENCODE_MCP_SIDECARS_JSON",
    "AGENT_SKILL_FILES_JSON",
    "AGENT_SKILL_CONFIGMAP_PATH",
    "HITL_MODE",
    "HITL_NOTIFICATION_WEBHOOK_URL",
})


def build_server_env(config_content: dict[str, Any]) -> dict[str, str]:
    """Build a minimal, secret-free environment for the OpenCode subprocess.

    Only env vars in the allowlist are passed through. Secrets (API keys,
    bearer tokens, passwords) are never included — they are held exclusively
    in the credential-proxy sidecar container.
    """
    env: dict[str, str] = {}
    for key in _ENV_ALLOWLIST:
        val = os.getenv(key)
        if val is not None:
            env[key] = val

    env["HOME"] = HOME_DIR
    env["XDG_CONFIG_HOME"] = XDG_CONFIG_HOME
    env["XDG_DATA_HOME"] = XDG_DATA_HOME
    env["OPENCODE_CONFIG_DIR"] = OPENCODE_CONFIG_DIR
    env["OPENCODE_CONFIG_CONTENT"] = json.dumps(config_content, ensure_ascii=False)
    env["OPENCODE_CLIENT"] = "server"
    env["OPENCODE_DISABLE_AUTOUPDATE"] = "true"
    env["OPENCODE_DISABLE_LSP_DOWNLOAD"] = "true"
    env["OPENCODE_DISABLE_DEFAULT_PLUGINS"] = os.getenv("OPENCODE_DISABLE_DEFAULT_PLUGINS", "true") or "true"
    env["OPENCODE_SERVER_USERNAME"] = resolve_opencode_server_username()
    env["OPENCODE_SERVER_PASSWORD"] = resolve_opencode_server_password()

    credential_proxy_enabled = os.getenv("CREDENTIAL_PROXY_ENABLED", "false").strip().lower() in ("true", "1", "yes")

    provider_id = _resolve_provider_id()
    provider = get_provider(provider_id)

    if not credential_proxy_enabled:
        resolved = provider.resolve_env()
        for key, value in resolved.items():
            env[key] = value
        _inject_auth_key_from_content(env, provider_id)

    if provider.id == "litellm":
        base_url = build_litellm_base_url()
        if base_url:
            env["OPENAI_BASE_URL"] = base_url
        if not credential_proxy_enabled and LITELLM_API_KEY and "OPENAI_API_KEY" not in env:
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
    Previous handles are closed before opening new ones to avoid FD leaks.
    """
    global _active_stdout_fh, _active_stderr_fh

    # Close stale handles from a prior (possibly crashed) process before
    # opening new ones.  Silently ignore errors — the old process is gone.
    if _active_stdout_fh is not None:
        try:
            _active_stdout_fh.close()
        except OSError:
            pass
        _active_stdout_fh = None
    if _active_stderr_fh is not None:
        try:
            _active_stderr_fh.close()
        except OSError:
            pass
        _active_stderr_fh = None

    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    stdout_fh = open(_STDOUT_LOG, "w", encoding="utf-8", buffering=1)  # noqa: SIM115
    stderr_fh = open(_STDERR_LOG, "w", encoding="utf-8", buffering=1)  # noqa: SIM115
    _active_stdout_fh = stdout_fh
    _active_stderr_fh = stderr_fh
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


def close_log_handles() -> None:
    """Close any open subprocess log file handles (called on graceful shutdown)."""
    global _active_stdout_fh, _active_stderr_fh
    for handle in (_active_stdout_fh, _active_stderr_fh):
        if handle is not None:
            try:
                handle.close()
            except OSError:
                pass
    _active_stdout_fh = None
    _active_stderr_fh = None
