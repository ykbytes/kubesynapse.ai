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
    OPENCODE_BIN,
    OPENCODE_CONFIG_DIR,
    OPENCODE_SERVER_HOST,
    OPENCODE_SERVER_PORT,
    OPENCODE_WORKDIR,
    SERVER_POLL_INTERVAL_SECONDS,
    SERVER_STARTUP_TIMEOUT_SECONDS,
    XDG_CONFIG_HOME,
    XDG_DATA_HOME,
    server_base_url,
)

logger = logging.getLogger("opencode-runtime")

# ---------------------------------------------------------------------------
# Shared mutable state for process lifecycle
# ---------------------------------------------------------------------------
_shutting_down = False
_shutdown_event = threading.Event()
_runtime_process: subprocess.Popen[str] | None = None
_runtime_ready = False
_runtime_lock = threading.Lock()

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
    return env


# ---------------------------------------------------------------------------
# Process start / readiness
# ---------------------------------------------------------------------------

def _start_opencode_process(env: dict[str, str]) -> subprocess.Popen[str]:
    """Start the OpenCode serve subprocess."""
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
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def wait_for_server_ready(process: subprocess.Popen[str]) -> None:
    """Block until the OpenCode server responds healthy or timeout/exit."""
    deadline = time.time() + SERVER_STARTUP_TIMEOUT_SECONDS
    health_url = f"{server_base_url()}/global/health"
    while time.time() < deadline:
        if process.poll() is not None:
            stdout_out = process.stdout.read() if process.stdout else ""
            stderr_out = process.stderr.read() if process.stderr else ""
            logger.error("OpenCode server exited with code %s.\nSTDOUT: %s\nSTDERR: %s", process.returncode, stdout_out[:4000], stderr_out[:4000])
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
            logger.warning(
                "OpenCode subprocess exited unexpectedly (code=%s, restarts=%d/%d).",
                exit_code, _supervisor_restart_count, SUPERVISOR_MAX_RESTARTS,
            )
            with _runtime_lock:
                _runtime_ready = False

            if _supervisor_restart_count >= SUPERVISOR_MAX_RESTARTS:
                logger.error(
                    "Max supervisor restarts (%d) reached; not restarting OpenCode subprocess.",
                    SUPERVISOR_MAX_RESTARTS,
                )
                continue

            _supervisor_restart_count += 1
            try:
                new_process = _start_opencode_process(env)
                wait_for_server_ready(new_process)
                with _runtime_lock:
                    _runtime_process = new_process
                    _runtime_ready = True
                logger.info(
                    "OpenCode subprocess restarted successfully (attempt %d/%d).",
                    _supervisor_restart_count, SUPERVISOR_MAX_RESTARTS,
                )
            except Exception as exc:
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
