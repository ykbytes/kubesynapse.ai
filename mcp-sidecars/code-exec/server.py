"""MCP Code Execution sidecar — run Python, Bash, and Node.js safely."""

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
            )
            output = result.stdout + result.stderr
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
        )
        output = result.stdout + result.stderr
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
            )
            output = result.stdout + result.stderr
            return output[:MAX_OUTPUT_CHARS] if output else "(no output)"
        except subprocess.TimeoutExpired:
            return f"ERROR: Execution timed out after {timeout}s"
        except FileNotFoundError:
            return "ERROR: node not found on this system"
        finally:
            os.unlink(f.name)


if __name__ == "__main__":
    run_server(server)
