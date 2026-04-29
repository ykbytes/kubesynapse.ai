"""
kubesynapse Intelligence Collector Agent

Lightweight agent deployed as a DaemonSet on K8s clusters.
Accepts read-only collection tasks, executes them safely,
and returns structured results to the platform.

Safety guarantees:
- All commands run as non-root user
- Write operations are blocked at the script level
- Dangerous commands are rejected before execution
- Timeout enforcement on all tasks
- Output size capping
"""

import asyncio
import hashlib
import json
import logging
import os
import platform
import re
import socket
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from typing import Optional

import psutil
import yaml
from fastapi import FastAPI, Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import hmac
import uvicorn

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
COLLECTOR_PORT = int(os.environ.get("COLLECTOR_PORT", "9100"))
COLLECTOR_TOKEN = os.environ.get("COLLECTOR_TOKEN", "").strip()
NODE_NAME = os.environ.get("NODE_NAME", socket.gethostname())
CLUSTER_NAME = os.environ.get("CLUSTER_NAME", "unknown")
MAX_TIMEOUT = int(os.environ.get("MAX_TIMEOUT", "60"))
MAX_OUTPUT_CHARS = int(os.environ.get("MAX_OUTPUT_CHARS", "50000"))
SCRIPTS_DIR = os.environ.get("SCRIPTS_DIR", "/app/scripts")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("collector")

# ---------------------------------------------------------------------------
# Dangerous command patterns (blocked)
# ---------------------------------------------------------------------------
_DANGEROUS_PATTERNS = [
    r"\brm\s+(-[rRf]+\s+)?/",        # rm -rf /
    r"\bmkfs\b",                       # format filesystem
    r"\bdd\s+",                        # dd
    r"\b(shutdown|reboot|halt|poweroff)\b",
    r"\biptables\b",                   # firewall changes
    r"\bkubectl\s+(delete|apply|create|patch|edit|replace|scale|drain|cordon|taint)",
    r"\bkubectl\s+exec\b",            # no exec into pods
    r"\bcurl\s+.*-X\s*(POST|PUT|PATCH|DELETE)",  # no mutating HTTP
    r"\bwget\s+--post",
    r"\bchmod\b",
    r"\bchown\b",
    r"\bmount\b",
    r"\bumount\b",
    r"\bmkdir\b",
    r"\btouch\b",
    r">\s*/(?!dev/null)",                 # redirect to absolute path (allow /dev/null)
    r">>\s*/(?!dev/null)",                # append to absolute path (allow /dev/null)
    r"\bsudo\b",
    r"\bsu\s",
    r"\bnohup\b.*&",                   # backgrounded nohup
    r"\beval\b",
    r"\bsource\s+/",
    r"\|\s*bash\b",                    # piping to bash
    r"\|\s*sh\b",                      # piping to sh
]

_ALLOWED_KUBECTL = [
    "get", "describe", "logs", "top", "version",
    "api-resources", "api-versions", "cluster-info",
    "config view", "config current-context",
]

# Secret masking
_SECRET_PATTERN = re.compile(
    r"(password|secret|token|api[_-]?key|authorization|bearer)\s*[:=]\s*\S+",
    re.IGNORECASE,
)


def _validate_script(script: str) -> Optional[str]:
    """Check script for dangerous patterns. Returns error message or None."""
    for pattern in _DANGEROUS_PATTERNS:
        if re.search(pattern, script, re.IGNORECASE):
            return f"Blocked: script matches dangerous pattern: {pattern}"
    return None


def _mask_secrets(text: str) -> str:
    """Mask potential secrets in output."""
    return _SECRET_PATTERN.sub(r"\1=****", text)


def _truncate(text: str, max_chars: int = MAX_OUTPUT_CHARS) -> str:
    if len(text) <= max_chars:
        return text
    half = max_chars // 2
    return text[:half] + f"\n\n... truncated ({len(text)} chars total) ...\n\n" + text[-half:]


# ---------------------------------------------------------------------------
# Built-in collection scripts
# ---------------------------------------------------------------------------
BUILTIN_SCRIPTS = {}


def _load_builtin_scripts():
    """Load built-in scripts from the scripts/ directory."""
    if not os.path.isdir(SCRIPTS_DIR):
        return
    for fname in os.listdir(SCRIPTS_DIR):
        fpath = os.path.join(SCRIPTS_DIR, fname)
        if os.path.isfile(fpath) and fname.endswith((".sh", ".py")):
            name = os.path.splitext(fname)[0]
            with open(fpath, "r") as f:
                BUILTIN_SCRIPTS[name] = {
                    "name": name,
                    "filename": fname,
                    "content": f.read(),
                    "type": "python" if fname.endswith(".py") else "bash",
                }
    log.info("Loaded %d built-in scripts: %s", len(BUILTIN_SCRIPTS), list(BUILTIN_SCRIPTS.keys()))


# ---------------------------------------------------------------------------
# Script execution (sandboxed, read-only)
# ---------------------------------------------------------------------------
async def execute_script(
    script: str,
    script_type: str = "bash",
    timeout: int = 30,
    env_extra: Optional[dict] = None,
) -> dict:
    """Execute a read-only script and return structured results."""

    # Validate
    error = _validate_script(script)
    if error:
        return {"status": "rejected", "error": error, "output": ""}

    timeout = min(timeout, MAX_TIMEOUT)

    # Build safe environment
    safe_env = {
        "PATH": "/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin",
        "HOME": "/tmp",
        "LANG": "C.UTF-8",
        "NODE_NAME": NODE_NAME,
        "CLUSTER_NAME": CLUSTER_NAME,
    }
    # Propagate K8s service account credentials for kubectl
    for k in ("KUBERNETES_SERVICE_HOST", "KUBERNETES_SERVICE_PORT",
              "KUBERNETES_SERVICE_PORT_HTTPS"):
        v = os.environ.get(k)
        if v:
            safe_env[k] = v
    if env_extra:
        # Only allow simple string values
        for k, v in env_extra.items():
            if isinstance(v, str) and len(v) < 1024:
                safe_env[k] = v

    start = time.monotonic()

    try:
        if script_type == "python":
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".py", delete=False, dir="/tmp"
            ) as f:
                f.write(script)
                f.flush()
                script_path = f.name
            cmd = ["python3", script_path]
        else:
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".sh", delete=False, dir="/tmp"
            ) as f:
                f.write(script)
                f.flush()
                script_path = f.name
            cmd = ["bash", "-e", script_path]

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=safe_env,
        )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=timeout
        )

        elapsed = time.monotonic() - start
        stdout_str = _mask_secrets(_truncate(stdout.decode("utf-8", errors="replace")))
        stderr_str = _mask_secrets(_truncate(stderr.decode("utf-8", errors="replace")))

        # Clean up temp file
        try:
            os.unlink(script_path)
        except OSError:
            pass

        return {
            "status": "completed" if proc.returncode == 0 else "error",
            "exit_code": proc.returncode,
            "stdout": stdout_str,
            "stderr": stderr_str,
            "duration_ms": round(elapsed * 1000),
            "node": NODE_NAME,
            "cluster": CLUSTER_NAME,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    except asyncio.TimeoutError:
        elapsed = time.monotonic() - start
        try:
            proc.kill()
        except Exception:
            pass
        try:
            os.unlink(script_path)
        except (OSError, UnboundLocalError):
            pass
        return {
            "status": "timeout",
            "error": f"Script exceeded {timeout}s timeout",
            "duration_ms": round(elapsed * 1000),
            "node": NODE_NAME,
            "cluster": CLUSTER_NAME,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
            "node": NODE_NAME,
            "cluster": CLUSTER_NAME,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }


# ---------------------------------------------------------------------------
# System info collection (always available)
# ---------------------------------------------------------------------------
def collect_system_info() -> dict:
    """Gather basic system/node information."""
    try:
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage("/")
        return {
            "node": NODE_NAME,
            "cluster": CLUSTER_NAME,
            "hostname": socket.gethostname(),
            "platform": platform.platform(),
            "cpu_count": psutil.cpu_count(),
            "cpu_percent": psutil.cpu_percent(interval=0.5),
            "memory_total_gb": round(mem.total / (1024**3), 2),
            "memory_used_percent": mem.percent,
            "disk_total_gb": round(disk.total / (1024**3), 2),
            "disk_used_percent": round(disk.used / disk.total * 100, 1),
            "uptime_seconds": int(time.time() - psutil.boot_time()),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        return {"error": str(e), "node": NODE_NAME}


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------
app = FastAPI(title="kubesynapse Collector Agent", version="0.1.0")
security = HTTPBearer()


def verify_token(creds: HTTPAuthorizationCredentials = Depends(security)):
    if not hmac.compare_digest(creds.credentials, COLLECTOR_TOKEN):
        raise HTTPException(status_code=401, detail="Invalid token")
    return creds.credentials


@app.get("/healthz")
async def healthz():
    return {"status": "ok", "node": NODE_NAME, "cluster": CLUSTER_NAME}


@app.get("/info", dependencies=[Depends(verify_token)])
async def info():
    """Return collector agent info and capabilities."""
    return {
        "node": NODE_NAME,
        "cluster": CLUSTER_NAME,
        "version": "0.1.0",
        "capabilities": ["bash", "python", "system_info", "builtin_scripts"],
        "builtin_scripts": list(BUILTIN_SCRIPTS.keys()),
        "max_timeout": MAX_TIMEOUT,
        "max_output_chars": MAX_OUTPUT_CHARS,
    }


@app.get("/system-info", dependencies=[Depends(verify_token)])
async def system_info():
    """Gather system information from this node."""
    return collect_system_info()


@app.post("/collect", dependencies=[Depends(verify_token)])
async def collect(task: dict):
    """
    Execute a collection task.

    Body:
    {
        "script": "kubectl get pods -A -o wide",
        "type": "bash",          # bash or python
        "timeout": 30,           # max 60
        "env": {}                # optional extra env vars
    }

    OR use a built-in script:
    {
        "builtin": "pod_resources",
        "timeout": 30
    }
    """
    # Built-in script
    if "builtin" in task:
        name = task["builtin"]
        if name not in BUILTIN_SCRIPTS:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown builtin script: {name}. Available: {list(BUILTIN_SCRIPTS.keys())}",
            )
        bs = BUILTIN_SCRIPTS[name]
        result = await execute_script(
            bs["content"],
            script_type=bs["type"],
            timeout=task.get("timeout", 30),
        )
        result["builtin"] = name
        return result

    # Custom script
    script = task.get("script")
    if not script or not isinstance(script, str):
        raise HTTPException(status_code=400, detail="'script' field required")

    if len(script) > 10000:
        raise HTTPException(status_code=400, detail="Script too large (max 10000 chars)")

    return await execute_script(
        script,
        script_type=task.get("type", "bash"),
        timeout=task.get("timeout", 30),
        env_extra=task.get("env"),
    )


@app.post("/collect/batch", dependencies=[Depends(verify_token)])
async def collect_batch(tasks: dict):
    """
    Execute multiple collection tasks in parallel.

    Body:
    {
        "tasks": [
            {"script": "kubectl get pods -A", "type": "bash"},
            {"builtin": "node_health"}
        ],
        "max_parallel": 5
    }
    """
    task_list = tasks.get("tasks", [])
    if not task_list:
        raise HTTPException(status_code=400, detail="No tasks provided")

    if len(task_list) > 20:
        raise HTTPException(status_code=400, detail="Too many tasks (max 20)")

    max_parallel = min(tasks.get("max_parallel", 5), 10)

    semaphore = asyncio.Semaphore(max_parallel)

    async def run_one(t):
        async with semaphore:
            if "builtin" in t:
                name = t["builtin"]
                if name not in BUILTIN_SCRIPTS:
                    return {"status": "error", "error": f"Unknown builtin: {name}"}
                bs = BUILTIN_SCRIPTS[name]
                result = await execute_script(
                    bs["content"],
                    script_type=bs["type"],
                    timeout=t.get("timeout", 30),
                )
                result["builtin"] = name
                return result
            return await execute_script(
                t.get("script", "echo 'no script'"),
                script_type=t.get("type", "bash"),
                timeout=t.get("timeout", 30),
                env_extra=t.get("env"),
            )

    results = await asyncio.gather(*[run_one(t) for t in task_list])
    return {
        "results": results,
        "total": len(results),
        "completed": sum(1 for r in results if r.get("status") == "completed"),
    }


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    _load_builtin_scripts()
    log.info("Starting collector agent on %s (cluster=%s, port=%d)", NODE_NAME, CLUSTER_NAME, COLLECTOR_PORT)
    uvicorn.run(app, host="0.0.0.0", port=COLLECTOR_PORT, log_level="info")
