"""MCP Git & GitHub sidecar — clone, diff, commit, push, branch, and GitHub API."""

import ipaddress
import logging
import os
import re
import socket
import subprocess
import sys
import tempfile
from urllib.parse import urlparse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "base"))
from mcp_base import create_mcp_server, run_server

log = logging.getLogger("mcp-git")

server = create_mcp_server(
    "mcp-git",
    "Git operations (clone, diff, commit, push, branch, status) and GitHub REST API access.",
)

WORK_DIR = os.environ.get("MCP_WORK_DIR", tempfile.gettempdir())
MAX_OUTPUT_CHARS = 12000

# --- Credential bootstrap at startup ---

GIT_AUTH_METHOD = os.environ.get("GIT_AUTH_METHOD", "")  # token | basic | ssh
GIT_TOKEN = os.environ.get("GIT_TOKEN", "")
GIT_USERNAME = os.environ.get("GIT_USERNAME", "")
GIT_PASSWORD = os.environ.get("GIT_PASSWORD", "")
GIT_SSH_KEY_PATH = os.environ.get("GIT_SSH_KEY_PATH", "/home/mcpuser/.ssh/id_rsa")
GIT_REPO_URL = os.environ.get("GIT_REPO_URL", "")
GIT_BRANCH = os.environ.get("GIT_BRANCH", "")


def _run(cmd: list[str], cwd: str | None = None, timeout: int = 30) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=cwd)


def configure_git_credentials() -> None:
    """Configure git credentials based on GIT_AUTH_METHOD env var at startup."""
    if not GIT_AUTH_METHOD:
        log.info("No GIT_AUTH_METHOD set, skipping credential configuration")
        return

    # Set safe defaults
    _run(["git", "config", "--global", "user.name", "AI Agent"])
    _run(["git", "config", "--global", "user.email", "agent@kubesynth.local"])

    if GIT_AUTH_METHOD == "token":
        if not GIT_TOKEN:
            log.warning("GIT_AUTH_METHOD=token but GIT_TOKEN is empty")
            return
        _run(["git", "config", "--global", "credential.helper", "store"])
        # Write token-based credential to git-credentials
        cred_path = os.path.expanduser("~/.git-credentials")
        if GIT_REPO_URL and GIT_REPO_URL.startswith("https://"):
            host = GIT_REPO_URL.split("//")[1].split("/")[0]
            cred_line = f"https://oauth2:{GIT_TOKEN}@{host}\n"
        else:
            cred_line = f"https://oauth2:{GIT_TOKEN}@github.com\n"
        with open(cred_path, "w") as f:
            f.write(cred_line)
        os.chmod(cred_path, 0o600)
        log.info("Configured git credential store (token)")

    elif GIT_AUTH_METHOD == "basic":
        if not GIT_USERNAME or not GIT_PASSWORD:
            log.warning("GIT_AUTH_METHOD=basic but GIT_USERNAME or GIT_PASSWORD is empty")
            return
        _run(["git", "config", "--global", "credential.helper", "store"])
        cred_path = os.path.expanduser("~/.git-credentials")
        if GIT_REPO_URL and GIT_REPO_URL.startswith("https://"):
            host = GIT_REPO_URL.split("//")[1].split("/")[0]
            cred_line = f"https://{GIT_USERNAME}:{GIT_PASSWORD}@{host}\n"
        else:
            cred_line = f"https://{GIT_USERNAME}:{GIT_PASSWORD}@github.com\n"
        with open(cred_path, "w") as f:
            f.write(cred_line)
        os.chmod(cred_path, 0o600)
        log.info("Configured git credential store (basic)")

    elif GIT_AUTH_METHOD == "ssh":
        ssh_dir = os.path.expanduser("~/.ssh")
        os.makedirs(ssh_dir, exist_ok=True)
        os.chmod(ssh_dir, 0o700)
        if os.path.exists(GIT_SSH_KEY_PATH):
            os.chmod(GIT_SSH_KEY_PATH, 0o600)
        # Accept new host keys on first connect but verify on subsequent connections
        ssh_config = os.path.join(ssh_dir, "config")
        if not os.path.exists(ssh_config):
            with open(ssh_config, "w") as f:
                f.write("Host *\n  StrictHostKeyChecking accept-new\n")
            os.chmod(ssh_config, 0o600)
        _run(["git", "config", "--global", "core.sshCommand",
              f"ssh -i {GIT_SSH_KEY_PATH} -o StrictHostKeyChecking=accept-new"])
        log.info("Configured git SSH key")
    else:
        log.warning(f"Unknown GIT_AUTH_METHOD: {GIT_AUTH_METHOD}")


# --- URL validation ---

_BLOCKED_CLONE_SCHEMES = frozenset({"file", "ftp", "ftps"})

_BLOCKED_IP_NETWORKS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
]


def _validate_clone_url(url: str) -> str | None:
    """Return an error message if *url* should not be cloned, else None."""
    # SSH-style URLs (git@host:path) are allowed — only validate parseable URLs
    if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", url):
        parsed = urlparse(url)
        if parsed.scheme.lower() in _BLOCKED_CLONE_SCHEMES:
            return f"Scheme '{parsed.scheme}' is not allowed for cloning"
        hostname = parsed.hostname or ""
        if not hostname:
            return "URL has no hostname"
        try:
            for info in socket.getaddrinfo(hostname, None):
                addr = ipaddress.ip_address(info[4][0])
                for net in _BLOCKED_IP_NETWORKS:
                    if addr in net:
                        return "Cloning from internal/private network addresses is blocked"
        except socket.gaierror:
            pass  # let git handle DNS failures
    return None


# --- Git tools ---


@server.tool()
def git_clone(repo_url: str, branch: str = "", full_clone: bool = False, target_dir: str = "") -> str:
    """Clone a Git repository. Returns the local path.

    full_clone: If true, perform a full (non-shallow) clone for push support.
    target_dir: Clone directly into this directory (e.g. '/workspace').
                If empty, creates a subdirectory named after the repo.
                If the directory is non-empty, initializes git and pulls
                from the remote instead of cloning.
    """
    url_err = _validate_clone_url(repo_url)
    if url_err:
        return f"BLOCKED: {url_err}"
    try:
        if target_dir:
            dest = target_dir
        else:
            repo_name = repo_url.rstrip("/").split("/")[-1].replace(".git", "")
            dest = os.path.join(WORK_DIR, repo_name)

        # If target_dir is non-empty or already a git repo, use init+fetch
        # instead of clone (git clone requires an empty directory).
        dest_non_empty = os.path.isdir(dest) and os.listdir(dest)
        dest_is_git = os.path.isdir(os.path.join(dest, ".git"))

        if dest_is_git:
            # Already a git repo — just fetch latest
            fetch_cmd = ["git", "fetch", "origin"]
            result = _run(fetch_cmd, cwd=dest, timeout=120)
            if result.returncode != 0:
                return f"ERROR: git fetch failed: {result.stderr.strip()}"
            return f"Repository at {dest} updated (already initialized)"

        if dest_non_empty:
            # Non-empty directory — init, add remote, fetch, then checkout
            os.makedirs(dest, exist_ok=True)
            init_result = _run(["git", "init"], cwd=dest, timeout=15)
            if init_result.returncode != 0:
                return f"ERROR: git init failed: {init_result.stderr.strip()}"
            _run(["git", "remote", "add", "origin", repo_url], cwd=dest, timeout=15)
            fetch_result = _run(["git", "fetch", "origin"], cwd=dest, timeout=120)
            if fetch_result.returncode != 0:
                return f"ERROR: git fetch failed: {fetch_result.stderr.strip()}"
            # Check out the target branch (or default) without overwriting
            # existing files — use reset to align HEAD with remote.
            target_branch = branch or "main"
            checkout = _run(
                ["git", "checkout", "-b", target_branch, f"origin/{target_branch}"],
                cwd=dest, timeout=30,
            )
            if checkout.returncode != 0:
                # Remote branch may not exist yet (new repo) — just set up
                # local branch so push works.
                _run(["git", "checkout", "-b", target_branch], cwd=dest, timeout=15)
            return f"Initialized git repo at {dest} with remote origin"

        # Standard clone into empty/new directory
        cmd = ["git", "clone"]
        if not full_clone:
            cmd += ["--depth", "1"]
        if branch:
            cmd += ["-b", branch]
        cmd += [repo_url, dest]
        result = _run(cmd, timeout=120)
        if result.returncode != 0:
            return f"ERROR: {result.stderr.strip()}"
        # If shallow clone, unshallow for push support
        if not full_clone:
            unshallow = _run(["git", "fetch", "--unshallow"], cwd=dest, timeout=120)
            if unshallow.returncode != 0:
                unshallow_err = unshallow.stderr.strip()
                log.warning("git fetch --unshallow failed for %s: %s", dest, unshallow_err)
                return (
                    f"Cloned to {dest} (WARNING: repo is shallow — unshallow failed: "
                    f"{unshallow_err}. Push may fail. Re-clone with full_clone=true "
                    f"for push support.)"
                )
        return f"Cloned to {dest}"
    except subprocess.TimeoutExpired:
        return "ERROR: Clone timed out"
    except Exception as e:
        return f"ERROR: Clone failed: {e}"


@server.tool()
def git_status(repo_path: str) -> str:
    """Show git status (short format) for a repository."""
    try:
        result = _run(["git", "status", "--short", "--branch"], cwd=repo_path, timeout=15)
        return result.stdout.strip() or "(clean working tree)"
    except Exception as e:
        return f"ERROR: git status failed: {e}"


@server.tool()
def git_diff(repo_path: str, ref: str = "HEAD") -> str:
    """Show git diff for a repository."""
    try:
        result = _run(["git", "diff", ref], cwd=repo_path, timeout=15)
        output = result.stdout or "(no changes)"
        return output[:MAX_OUTPUT_CHARS]
    except Exception as e:
        return f"ERROR: git diff failed: {e}"


@server.tool()
def git_log(repo_path: str, max_count: int = 10) -> str:
    """Show recent git log entries."""
    try:
        result = _run(
            ["git", "log", f"--max-count={min(max_count, 50)}", "--oneline", "--no-decorate"],
            cwd=repo_path, timeout=15,
        )
        return result.stdout.strip() or "(no commits)"
    except Exception as e:
        return f"ERROR: git log failed: {e}"


@server.tool()
def git_add(repo_path: str, paths: str = ".") -> str:
    """Stage files for commit. Use '.' for all, or space-separated paths."""
    try:
        cmd = ["git", "add"] + paths.split()
        result = _run(cmd, cwd=repo_path, timeout=15)
        if result.returncode != 0:
            return f"ERROR: {result.stderr.strip()}"
        return "Staged successfully"
    except Exception as e:
        return f"ERROR: git add failed: {e}"


@server.tool()
def git_commit(repo_path: str, message: str, add_all: bool = True) -> str:
    """Stage and commit changes in a repository."""
    try:
        if add_all:
            _run(["git", "add", "-A"], cwd=repo_path, timeout=10)
        result = _run(["git", "commit", "-m", message], cwd=repo_path, timeout=15)
        if result.returncode != 0:
            return f"ERROR: {result.stderr.strip()}" if result.stderr else "Nothing to commit"
        return result.stdout.strip()
    except Exception as e:
        return f"ERROR: git commit failed: {e}"


@server.tool()
def git_push(repo_path: str, remote: str = "origin", branch: str = "") -> str:
    """Push commits to remote. If branch is empty, pushes current branch.

    Uses --set-upstream on the first push so new repositories and branches
    get proper tracking configuration automatically.
    """
    try:
        cmd = ["git", "push", "--set-upstream", remote]
        if branch:
            cmd.append(branch)
        else:
            cmd.append("HEAD")
        result = _run(cmd, cwd=repo_path, timeout=60)
        if result.returncode != 0:
            return f"ERROR: {result.stderr.strip()}"
        output = result.stderr.strip() or result.stdout.strip()
        return output[:MAX_OUTPUT_CHARS] or "Pushed successfully"
    except subprocess.TimeoutExpired:
        return "ERROR: Push timed out after 60s"
    except Exception as e:
        return f"ERROR: git push failed: {e}"


@server.tool()
def git_branch(repo_path: str, name: str = "", create: bool = False, delete: bool = False) -> str:
    """List, create, or delete branches.

    No args: list branches. name+create: create new branch. name+delete: delete branch.
    """
    try:
        if not name:
            result = _run(["git", "branch", "-a"], cwd=repo_path, timeout=15)
            return result.stdout.strip() or "(no branches)"
        if delete:
            result = _run(["git", "branch", "-D", name], cwd=repo_path, timeout=15)
        elif create:
            result = _run(["git", "checkout", "-b", name], cwd=repo_path, timeout=15)
        else:
            result = _run(["git", "branch", name], cwd=repo_path, timeout=15)
        if result.returncode != 0:
            return f"ERROR: {result.stderr.strip()}"
        return result.stdout.strip() or f"Branch '{name}' {'created and checked out' if create else 'created' if not delete else 'deleted'}"
    except Exception as e:
        return f"ERROR: git branch failed: {e}"


@server.tool()
def git_checkout(repo_path: str, ref: str) -> str:
    """Checkout a branch, tag, or commit."""
    try:
        result = _run(["git", "checkout", ref], cwd=repo_path, timeout=15)
        if result.returncode != 0:
            return f"ERROR: {result.stderr.strip()}"
        return result.stderr.strip() or f"Checked out '{ref}'"
    except Exception as e:
        return f"ERROR: git checkout failed: {e}"


@server.tool()
def git_pull(repo_path: str, remote: str = "origin", branch: str = "") -> str:
    """Pull latest changes from remote."""
    try:
        cmd = ["git", "pull", remote]
        if branch:
            cmd.append(branch)
        result = _run(cmd, cwd=repo_path, timeout=60)
        if result.returncode != 0:
            return f"ERROR: {result.stderr.strip()}"
        return result.stdout.strip()[:MAX_OUTPUT_CHARS]
    except subprocess.TimeoutExpired:
        return "ERROR: Pull timed out"
    except Exception as e:
        return f"ERROR: git pull failed: {e}"


@server.tool()
def git_stash(repo_path: str, action: str = "push", message: str = "") -> str:
    """Manage git stash. Actions: push, pop, list, drop."""
    try:
        cmd = ["git", "stash", action]
        if action == "push" and message:
            cmd += ["-m", message]
        result = _run(cmd, cwd=repo_path, timeout=15)
        if result.returncode != 0:
            return f"ERROR: {result.stderr.strip()}"
        return result.stdout.strip() or "Stash operation completed"
    except Exception as e:
        return f"ERROR: git stash failed: {e}"


@server.tool()
def github_api(endpoint: str, method: str = "GET") -> str:
    """Call the GitHub REST API (read-only). Requires GITHUB_TOKEN or GIT_TOKEN env var.

    endpoint: API path, e.g. '/repos/owner/repo/issues'
    method: Must be GET (enforced).
    """
    if method.upper() != "GET":
        return "BLOCKED: Only GET requests are allowed through github_api"
    import requests
    token = os.environ.get("GITHUB_TOKEN", "") or GIT_TOKEN
    if not token:
        return "ERROR: GITHUB_TOKEN / GIT_TOKEN not set"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
    # Only allow api.github.com — reject arbitrary URLs
    if endpoint.startswith("/"):
        url = f"https://api.github.com{endpoint}"
    else:
        parsed = urlparse(endpoint)
        if parsed.hostname != "api.github.com":
            return "BLOCKED: Only api.github.com endpoints are allowed"
        url = endpoint
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
        return str(resp.json())[:MAX_OUTPUT_CHARS]
    except Exception as e:
        log.exception("GitHub API call failed")
        return "ERROR: GitHub API call failed"


def auto_clone_if_configured() -> None:
    """Auto-clone the repo into WORK_DIR at startup when GIT_REPO_URL is set.

    Skips if WORK_DIR already contains a .git directory (already cloned).
    Uses full_clone=true so push works immediately.
    When GIT_BRANCH is set, checks out (or creates) that branch after cloning.
    """
    if not GIT_REPO_URL:
        log.info("No GIT_REPO_URL set, skipping auto-clone")
        return
    git_dir = os.path.join(WORK_DIR, ".git")
    if os.path.isdir(git_dir):
        log.info("WORK_DIR already has .git, fetching latest")
        result = _run(["git", "fetch", "origin"], cwd=WORK_DIR, timeout=120)
        if result.returncode != 0:
            log.warning("Auto-fetch failed: %s", result.stderr.strip())
        if GIT_BRANCH:
            _checkout_branch(WORK_DIR, GIT_BRANCH)
        return
    log.info("Auto-cloning %s into %s", GIT_REPO_URL, WORK_DIR)
    result_text = git_clone(GIT_REPO_URL, full_clone=True, target_dir=WORK_DIR)
    log.info("Auto-clone result: %s", result_text)
    if GIT_BRANCH:
        _checkout_branch(WORK_DIR, GIT_BRANCH)


def _checkout_branch(repo_path: str, branch: str) -> None:
    """Checkout or create a branch, pulling from origin if it exists remotely."""
    # Try checking out an existing remote branch
    result = _run(["git", "checkout", "-b", branch, f"origin/{branch}"], cwd=repo_path, timeout=30)
    if result.returncode == 0:
        log.info("Checked out existing remote branch '%s'", branch)
        return
    # Try checking out a local branch that already exists
    result = _run(["git", "checkout", branch], cwd=repo_path, timeout=15)
    if result.returncode == 0:
        log.info("Checked out existing local branch '%s'", branch)
        return
    # Create a new branch from the current HEAD
    result = _run(["git", "checkout", "-b", branch], cwd=repo_path, timeout=15)
    if result.returncode == 0:
        log.info("Created new branch '%s'", branch)
    else:
        log.warning("Failed to create branch '%s': %s", branch, result.stderr.strip())


if __name__ == "__main__":
    configure_git_credentials()
    auto_clone_if_configured()
    run_server(server)
