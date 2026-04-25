"""Workspace awareness caching — pre-computed codebase context for new sessions."""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import os
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

from config import (
    WORKSPACE_SNAPSHOT_DIR,
    WORKSPACE_SNAPSHOT_ENABLED,
    WORKSPACE_SNAPSHOT_MAX_AGE_SECONDS,
)

logger = logging.getLogger("opencode-runtime")

# Lock for thread-safe cache access
_snapshot_lock = threading.Lock()

# Directories to skip when building the workspace tree
_SKIP_DIRS: frozenset[str] = frozenset(
    {
        ".git",
        "node_modules",
        "__pycache__",
        ".next",
        ".venv",
        "venv",
        "dist",
        ".cache",
        ".tox",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "vendor",
        "build",
        ".terraform",
        ".angular",
        "coverage",
        ".nyc_output",
        "target",
        ".gradle",
        ".idea",
        ".vscode",
        "eggs",
    }
)

# Directory name suffixes that should also be skipped (e.g., "mypackage.egg-info")
_SKIP_DIR_SUFFIXES: tuple[str, ...] = (".egg-info",)

# Files that signal the tech stack
_KEY_FILE_PATTERNS: frozenset[str] = frozenset(
    {
        "package.json",
        "package-lock.json",
        "yarn.lock",
        "pnpm-lock.yaml",
        "requirements.txt",
        "pyproject.toml",
        "setup.py",
        "setup.cfg",
        "Pipfile",
        "Cargo.toml",
        "go.mod",
        "go.sum",
        "Makefile",
        "Dockerfile",
        "docker-compose.yml",
        "docker-compose.yaml",
        ".env.example",
        "tsconfig.json",
        "jest.config.js",
        "jest.config.ts",
        "vite.config.ts",
        "next.config.js",
        "next.config.mjs",
        "webpack.config.js",
        "rollup.config.js",
        "tox.ini",
        "pytest.ini",
        "conftest.py",
        ".eslintrc.js",
        ".eslintrc.json",
        ".prettierrc",
        "Gemfile",
        "pom.xml",
        "build.gradle",
        "build.gradle.kts",
        "CMakeLists.txt",
        "Taskfile.yml",
        "azure.yaml",
        "bicep.parameters.json",
        "main.bicep",
        "main.tf",
    }
)

# Hidden files that should still be captured (important for tech stack / config)
_IMPORTANT_HIDDEN_FILES: frozenset[str] = frozenset(
    {
        ".env.example",
        ".env.sample",
        ".env.template",
        ".gitignore",
        ".dockerignore",
        ".eslintrc.js",
        ".eslintrc.json",
        ".eslintrc.yml",
        ".prettierrc",
        ".prettierrc.js",
        ".prettierrc.json",
        ".babelrc",
        ".editorconfig",
        ".nvmrc",
        ".python-version",
        ".ruby-version",
        ".node-version",
        ".tool-versions",
    }
)

# Extension -> language mapping for tech stack detection
_EXT_TO_LANG: dict[str, str] = {
    ".py": "Python",
    ".js": "JavaScript",
    ".ts": "TypeScript",
    ".tsx": "TypeScript/React",
    ".jsx": "JavaScript/React",
    ".go": "Go",
    ".rs": "Rust",
    ".java": "Java",
    ".kt": "Kotlin",
    ".rb": "Ruby",
    ".cs": "C#",
    ".cpp": "C++",
    ".c": "C",
    ".swift": "Swift",
    ".php": "PHP",
    ".scala": "Scala",
    ".tf": "Terraform",
    ".bicep": "Bicep",
    ".html": "HTML",
    ".css": "CSS",
    ".scss": "SCSS",
}


def _hash_path(path: str) -> str:
    """Produce a short hash for a workspace path."""
    return hashlib.sha256(path.encode()).hexdigest()[:16]


def _snapshot_path(working_directory: str) -> Path:
    """Return the file path for a cached workspace snapshot."""
    return WORKSPACE_SNAPSHOT_DIR / f"{_hash_path(working_directory)}.json"


def capture_workspace_snapshot(working_directory: str) -> dict[str, Any]:
    """Walk the workspace and capture a structural snapshot.

    Returns a dict with keys: ``directory_tree``, ``key_files``,
    ``tech_stack``, ``file_stats``, ``git_info``, ``total_files``,
    ``captured_at``.
    """
    root = Path(working_directory).resolve()
    if not root.is_dir():
        return {"error": f"Workspace directory '{working_directory}' does not exist"}

    tree_lines: list[str] = []
    key_files: list[str] = []
    file_stats: dict[str, int] = {}
    total_files = 0
    max_tree_depth = 4
    max_tree_entries = 120
    max_total_files = 10000  # Safety cap to prevent unbounded walk

    def _walk(directory: Path, prefix: str, depth: int) -> None:
        nonlocal total_files
        if depth > max_tree_depth or len(tree_lines) >= max_tree_entries or total_files >= max_total_files:
            return
        try:
            entries = sorted(directory.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower()))
        except PermissionError:
            return

        def _should_skip_dir(name: str) -> bool:
            if name in _SKIP_DIRS:
                return True
            if name.startswith("."):
                return True
            return bool(any(name.endswith(suffix) for suffix in _SKIP_DIR_SUFFIXES))

        dirs = [e for e in entries if e.is_dir() and not _should_skip_dir(e.name)]
        # Include non-hidden files AND important hidden files
        files = [
            e for e in entries if e.is_file() and (not e.name.startswith(".") or e.name in _IMPORTANT_HIDDEN_FILES)
        ]

        for f in files:
            total_files += 1
            ext = f.suffix.lower()
            if ext:
                file_stats[ext] = file_stats.get(ext, 0) + 1
            rel = str(f.relative_to(root)).replace("\\", "/")
            if f.name in _KEY_FILE_PATTERNS:
                key_files.append(rel)
            if len(tree_lines) < max_tree_entries:
                tree_lines.append(f"{prefix}{f.name}")

        for d in dirs:
            if len(tree_lines) >= max_tree_entries:
                break
            tree_lines.append(f"{prefix}{d.name}/")
            _walk(d, prefix + "  ", depth + 1)

    _walk(root, "", 0)

    # Detect tech stack
    tech_stack: list[str] = []
    for ext, lang in _EXT_TO_LANG.items():
        if file_stats.get(ext, 0) > 0 and lang not in tech_stack:
            tech_stack.append(lang)

    # Detect frameworks from key files
    key_file_names = {Path(f).name for f in key_files}
    if "package.json" in key_file_names:
        tech_stack.append("Node.js")
    if "next.config.js" in key_file_names or "next.config.mjs" in key_file_names:
        tech_stack.append("Next.js")
    if "pyproject.toml" in key_file_names or "requirements.txt" in key_file_names:
        tech_stack.append("Python")
    if "Cargo.toml" in key_file_names:
        tech_stack.append("Rust/Cargo")
    if "go.mod" in key_file_names:
        tech_stack.append("Go")
    if "Dockerfile" in key_file_names:
        tech_stack.append("Docker")
    if "azure.yaml" in key_file_names:
        tech_stack.append("Azure Developer CLI")
    if "main.tf" in key_file_names:
        tech_stack.append("Terraform")
    if "main.bicep" in key_file_names:
        tech_stack.append("Bicep")
    # Deduplicate
    seen: set[str] = set()
    unique_tech: list[str] = []
    for t in tech_stack:
        if t not in seen:
            seen.add(t)
            unique_tech.append(t)
    tech_stack = unique_tech

    # Git info
    git_info = _capture_git_info(str(root))

    # Build compact directory tree string
    directory_tree = "\n".join(tree_lines[:max_tree_entries])
    if len(tree_lines) >= max_tree_entries:
        directory_tree += f"\n... ({total_files} total files)"

    snapshot: dict[str, Any] = {
        "directory_tree": directory_tree,
        "key_files": key_files[:30],
        "tech_stack": tech_stack,
        "file_stats": dict(sorted(file_stats.items(), key=lambda x: -x[1])[:20]),
        "git_info": git_info,
        "total_files": total_files,
        "captured_at": time.time(),
        "working_directory": str(root),
    }
    return snapshot


def _capture_git_info(working_directory: str) -> dict[str, Any] | None:
    """Capture basic git information for the workspace."""
    git_dir = Path(working_directory) / ".git"
    if not git_dir.exists():
        return None
    info: dict[str, Any] = {}
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=working_directory,
        )
        if result.returncode == 0:
            info["branch"] = result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass
    try:
        result = subprocess.run(
            ["git", "log", "--oneline", "-5", "--no-decorate"],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=working_directory,
        )
        if result.returncode == 0:
            info["recent_commits"] = result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass
    return info or None


def get_or_refresh_snapshot(
    working_directory: str,
    max_age: int | None = None,
) -> dict[str, Any] | None:
    """Return a cached workspace snapshot, refreshing if stale.

    Returns ``None`` if workspace snapshots are disabled.
    Thread-safe: uses a lock to prevent concurrent cache refresh races,
    and atomic file writes to prevent partial reads.
    """
    if not WORKSPACE_SNAPSHOT_ENABLED:
        return None

    if max_age is None:
        max_age = WORKSPACE_SNAPSHOT_MAX_AGE_SECONDS

    cache_path = _snapshot_path(working_directory)

    with _snapshot_lock:
        # Try loading cached snapshot
        if cache_path.exists():
            try:
                data = json.loads(cache_path.read_text(encoding="utf-8"))
                captured_at = data.get("captured_at", 0)
                if time.time() - captured_at < max_age:
                    return data
            except (OSError, json.JSONDecodeError) as exc:
                logger.debug("Failed to load workspace snapshot from %s: %s", cache_path, exc)

        # Capture fresh snapshot
        try:
            snapshot = capture_workspace_snapshot(working_directory)
            if "error" in snapshot:
                return None
            # Atomic write: write to temp file, then rename
            WORKSPACE_SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
            content = json.dumps(snapshot, ensure_ascii=False, indent=2)
            fd, tmp_path = tempfile.mkstemp(
                dir=str(WORKSPACE_SNAPSHOT_DIR),
                suffix=".tmp",
                prefix="snapshot-",
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as tmp_f:
                    tmp_f.write(content)
                # On Windows, os.replace handles cross-device atomicity
                os.replace(tmp_path, str(cache_path))
            except Exception:
                # Clean up temp file on failure
                with contextlib.suppress(OSError):
                    os.unlink(tmp_path)
                raise
            return snapshot
        except Exception as exc:
            logger.warning("Failed to capture workspace snapshot for %s: %s", working_directory, exc)
            return None
