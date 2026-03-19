"""MCP Code Execution sidecar — run Python, Bash, and Node.js safely."""

import re
import subprocess
import sys
import tempfile
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "base"))
from mcp_base import create_mcp_server, run_server

server = create_mcp_server(
    "mcp-code-exec",
    "Execute code snippets in Python, Bash, or Node.js with resource limits.",
)

MAX_OUTPUT_CHARS = 8000
TIMEOUT_SECONDS = 30

# Environment variables safe to pass to executed code.
# Everything else (MCP_BEARER_TOKEN, DATABASE_URL, secrets) is stripped.
_SAFE_ENV_KEYS = frozenset({
    "PATH", "HOME", "LANG", "LC_ALL", "TERM", "TMPDIR", "TEMP", "TMP",
    "USER", "LOGNAME", "SHELL", "PWD", "HOSTNAME",
    "PYTHONDONTWRITEBYTECODE", "PYTHONUNBUFFERED",
    "NODE_PATH", "NODE_ENV",
})


def _sanitized_env() -> dict[str, str]:
    """Return a copy of os.environ with only safe keys."""
    return {k: v for k, v in os.environ.items() if k in _SAFE_ENV_KEYS}

# Pattern to detect API keys, tokens, passwords, and other secrets in output
_SECRET_PATTERN = re.compile(
    r"""(?x)
    (?:                                          # Known prefixes
        (?:sk|pk|ak|api|token|key|secret|password|passwd|pwd|auth|bearer|dckr_pat|ghp|gho|ghs|ghu|glpat|pypi|npm|AKIA)
        [-_]?[A-Za-z0-9]{16,}
    )
    |(?:[A-Za-z0-9+/]{40,}={0,2})              # Base64-ish long strings (potential encoded secrets)
    """,
    re.IGNORECASE,
)


def _mask_secrets(text: str) -> str:
    """Replace likely secret values in output with [REDACTED]."""
    return _SECRET_PATTERN.sub("[REDACTED]", text)


@server.tool()
def run_python(code: str, timeout: int = TIMEOUT_SECONDS) -> str:
    """Execute Python code and return stdout/stderr."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write(code)
        f.flush()
        try:
            result = subprocess.run(
                [sys.executable, f.name],
                capture_output=True,
                text=True,
                timeout=min(timeout, 60),
                cwd=tempfile.gettempdir(),
                env=_sanitized_env(),
            )
            output = _mask_secrets(result.stdout + result.stderr)
            return output[:MAX_OUTPUT_CHARS] if output else "(no output)"
        except subprocess.TimeoutExpired:
            return f"ERROR: Execution timed out after {timeout}s"
        finally:
            os.unlink(f.name)


@server.tool()
def run_bash(command: str, timeout: int = TIMEOUT_SECONDS) -> str:
    """Execute a Bash command and return stdout/stderr."""
    try:
        result = subprocess.run(
            ["bash", "-c", command],
            capture_output=True,
            text=True,
            timeout=min(timeout, 60),
            cwd=tempfile.gettempdir(),
            env=_sanitized_env(),
        )
        output = _mask_secrets(result.stdout + result.stderr)
        return output[:MAX_OUTPUT_CHARS] if output else "(no output)"
    except subprocess.TimeoutExpired:
        return f"ERROR: Command timed out after {timeout}s"
    except FileNotFoundError:
        return "ERROR: bash not found on this system"


@server.tool()
def run_node(code: str, timeout: int = TIMEOUT_SECONDS) -> str:
    """Execute Node.js code and return stdout/stderr."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".js", delete=False) as f:
        f.write(code)
        f.flush()
        try:
            result = subprocess.run(
                ["node", f.name],
                capture_output=True,
                text=True,
                timeout=min(timeout, 60),
                cwd=tempfile.gettempdir(),
                env=_sanitized_env(),
            )
            output = _mask_secrets(result.stdout + result.stderr)
            return output[:MAX_OUTPUT_CHARS] if output else "(no output)"
        except subprocess.TimeoutExpired:
            return f"ERROR: Execution timed out after {timeout}s"
        except FileNotFoundError:
            return "ERROR: node not found on this system"
        finally:
            os.unlink(f.name)


if __name__ == "__main__":
    run_server(server)
