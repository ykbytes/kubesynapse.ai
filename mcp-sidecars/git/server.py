"""MCP Git & GitHub sidecar — clone repos, diff, commit, and call GitHub API."""

import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "base"))
from mcp_base import create_mcp_server, run_server

server = create_mcp_server(
    "mcp-git",
    "Git operations (clone, diff, commit, log) and GitHub REST API access.",
)

WORK_DIR = os.environ.get("MCP_WORK_DIR", tempfile.gettempdir())
MAX_OUTPUT_CHARS = 12000


@server.tool()
def git_clone(repo_url: str, branch: str = "") -> str:
    """Clone a Git repository. Returns the local path."""
    try:
        repo_name = repo_url.rstrip("/").split("/")[-1].replace(".git", "")
        dest = os.path.join(WORK_DIR, repo_name)
        cmd = ["git", "clone", "--depth", "1"]
        if branch:
            cmd += ["-b", branch]
        cmd += [repo_url, dest]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if result.returncode != 0:
            return f"ERROR: {result.stderr.strip()}"
        return f"Cloned to {dest}"
    except subprocess.TimeoutExpired:
        return "ERROR: Clone timed out after 60s"
    except Exception as e:
        return f"ERROR: Clone failed: {e}"


@server.tool()
def git_diff(repo_path: str, ref: str = "HEAD") -> str:
    """Show git diff for a repository."""
    try:
        result = subprocess.run(
            ["git", "diff", ref],
            capture_output=True, text=True, timeout=15, cwd=repo_path,
        )
        output = result.stdout or "(no changes)"
        return output[:MAX_OUTPUT_CHARS]
    except Exception as e:
        return f"ERROR: git diff failed: {e}"


@server.tool()
def git_log(repo_path: str, max_count: int = 10) -> str:
    """Show recent git log entries."""
    try:
        result = subprocess.run(
            ["git", "log", f"--max-count={min(max_count, 50)}",
             "--oneline", "--no-decorate"],
            capture_output=True, text=True, timeout=15, cwd=repo_path,
        )
        return result.stdout.strip() or "(no commits)"
    except Exception as e:
        return f"ERROR: git log failed: {e}"


@server.tool()
def git_commit(repo_path: str, message: str, add_all: bool = True) -> str:
    """Stage and commit changes in a repository."""
    try:
        if add_all:
            subprocess.run(["git", "add", "-A"], cwd=repo_path, timeout=10)
        result = subprocess.run(
            ["git", "commit", "-m", message],
            capture_output=True, text=True, timeout=15, cwd=repo_path,
        )
        if result.returncode != 0:
            return f"ERROR: {result.stderr.strip()}" if result.stderr else "Nothing to commit"
        return result.stdout.strip()
    except Exception as e:
        return f"ERROR: git commit failed: {e}"


@server.tool()
def github_api(endpoint: str, method: str = "GET") -> str:
    """Call the GitHub REST API. Requires GITHUB_TOKEN env var.

    endpoint: API path, e.g. '/repos/owner/repo/issues'
    method: HTTP method (GET only for safety).
    """
    import requests
    token = os.environ.get("GITHUB_TOKEN", "")
    if not token:
        return "ERROR: GITHUB_TOKEN not set"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
    url = f"https://api.github.com{endpoint}" if endpoint.startswith("/") else endpoint
    try:
        resp = requests.request(method, url, headers=headers, timeout=15)
        resp.raise_for_status()
        return str(resp.json())[:MAX_OUTPUT_CHARS]
    except Exception as e:
        return f"ERROR: GitHub API call failed: {e}"


if __name__ == "__main__":
    run_server(server)
