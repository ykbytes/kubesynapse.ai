"""Cross-session memory — persistent context that survives session loss and compaction."""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

from config import (
    MEMORY_DIR,
    MEMORY_ENABLED,
    MEMORY_MAX_THREAD_ENTRIES,
    MEMORY_MAX_WORKSPACE_ENTRIES,
)

logger = logging.getLogger("opencode-runtime")

# Valid memory entry types
MEMORY_ENTRY_TYPES: frozenset[str] = frozenset(
    {
        "task_summary",
        "decision",
        "error_pattern",
        "codebase_insight",
        "file_map",
        "handoff",
    }
)


class SessionMemory:
    """File-backed JSONL memory store for cross-session context persistence.

    Provides two tiers:
      - **Thread memory** (per ``thread_id``): task summaries, decisions,
        errors, and key learnings from a specific conversation thread.
      - **Workspace memory** (shared): codebase structure, recurring patterns,
        tech stack info, and common paths shared across all threads.
    """

    def __init__(self, base_dir: Path, *, max_thread: int = 100, max_workspace: int = 50):
        self._base_dir = base_dir
        self._max_thread = max_thread
        self._max_workspace = max_workspace
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Path helpers
    # ------------------------------------------------------------------

    def _thread_path(self, thread_id: str) -> Path:
        # Sanitize thread_id for filesystem safety
        safe_id = "".join(c if c.isalnum() or c in "-_" else "_" for c in thread_id)[:64]
        return self._base_dir / "threads" / f"{safe_id}.jsonl"

    def _workspace_path(self) -> Path:
        return self._base_dir / "workspace.jsonl"

    # ------------------------------------------------------------------
    # Core operations
    # ------------------------------------------------------------------

    def save_memory(self, thread_id: str, entry: dict[str, Any]) -> bool:
        """Append a memory entry to the thread memory file.

        The entry should have at least ``type`` and ``content`` keys.
        A ``timestamp`` is added automatically if missing.
        Unknown entry types are logged as warnings but still saved.
        """
        if not MEMORY_ENABLED:
            return False
        entry.setdefault("timestamp", time.time())
        entry.setdefault("type", "task_summary")
        entry_type = entry.get("type")
        if entry_type not in MEMORY_ENTRY_TYPES:
            logger.warning(
                "Unknown memory entry type %r for thread %s (expected one of %s)",
                entry_type,
                thread_id,
                sorted(MEMORY_ENTRY_TYPES),
            )
        return self._append(self._thread_path(thread_id), entry, self._max_thread)

    def save_workspace_memory(self, entry: dict[str, Any]) -> bool:
        """Append a memory entry to the shared workspace memory file.

        Unknown entry types are logged as warnings but still saved.
        """
        if not MEMORY_ENABLED:
            return False
        entry.setdefault("timestamp", time.time())
        entry.setdefault("type", "codebase_insight")
        entry_type = entry.get("type")
        if entry_type not in MEMORY_ENTRY_TYPES:
            logger.warning(
                "Unknown workspace memory entry type %r (expected one of %s)",
                entry_type,
                sorted(MEMORY_ENTRY_TYPES),
            )
        return self._append(self._workspace_path(), entry, self._max_workspace)

    def recall_memory(self, thread_id: str, limit: int = 10) -> list[dict[str, Any]]:
        """Retrieve the most recent thread memory entries."""
        if not MEMORY_ENABLED:
            return []
        return self._read_recent(self._thread_path(thread_id), limit)

    def recall_workspace_memory(self, limit: int = 5) -> list[dict[str, Any]]:
        """Retrieve the most recent workspace memory entries."""
        if not MEMORY_ENABLED:
            return []
        return self._read_recent(self._workspace_path(), limit)

    def build_memory_context(self, thread_id: str) -> list[dict[str, Any]]:
        """Compose memory entries from both tiers for injection into a session.

        Returns a combined list with workspace entries first, then thread entries,
        sorted by timestamp (oldest first within each tier).
        """
        if not MEMORY_ENABLED:
            return []
        workspace = self.recall_workspace_memory(limit=5)
        thread = self.recall_memory(thread_id, limit=10)
        # Workspace context first (general), then thread-specific (more recent)
        combined = workspace + thread
        return combined

    def has_memory(self, thread_id: str) -> bool:
        """Return True if there is any persisted memory for the thread."""
        if not MEMORY_ENABLED:
            return False
        path = self._thread_path(thread_id)
        return path.exists() and path.stat().st_size > 0

    def get_handoff_memory(self, thread_id: str) -> dict[str, Any] | None:
        """Return the most recent handoff entry for a thread, if any."""
        entries = self.recall_memory(thread_id, limit=20)
        for entry in reversed(entries):
            if entry.get("type") == "handoff":
                return entry
        return None

    def clear_thread(self, thread_id: str) -> bool:
        """Remove all memory entries for a thread."""
        path = self._thread_path(thread_id)
        try:
            if path.exists():
                path.unlink()
            return True
        except OSError as exc:
            logger.warning("Failed to clear thread memory for %s: %s", thread_id, exc)
            return False

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _append(self, path: Path, entry: dict[str, Any], max_entries: int) -> bool:
        """Append an entry to a JSONL file, pruning old entries if needed."""
        with self._lock:
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                line = json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n"
                with open(path, "a", encoding="utf-8") as f:
                    f.write(line)
                # Prune if over limit
                self._maybe_prune(path, max_entries)
                return True
            except OSError as exc:
                logger.warning("Failed to save memory to %s: %s", path, exc)
                return False

    def _read_recent(self, path: Path, limit: int) -> list[dict[str, Any]]:
        """Read the most recent entries from a JSONL file."""
        if not path.exists():
            return []
        entries: list[dict[str, Any]] = []
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        except OSError as exc:
            logger.warning("Failed to read memory from %s: %s", path, exc)
            return []
        return entries[-limit:]

    def _maybe_prune(self, path: Path, max_entries: int) -> None:
        """Prune a JSONL file to keep only the most recent entries.

        Uses atomic write (tempfile + os.replace) so a crash mid-prune
        cannot lose the entire file.
        """
        try:
            entries: list[str] = []
            with open(path, "r", encoding="utf-8") as f:
                entries = [line for line in f if line.strip()]
            if len(entries) <= max_entries:
                return
            # Keep the most recent entries — write to a temp file then atomically replace
            pruned = entries[-max_entries:]
            fd, tmp_path = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp", prefix=path.stem)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as tmp_f:
                    tmp_f.writelines(pruned)
                os.replace(tmp_path, str(path))
            except BaseException:
                # Clean up the temp file on any failure
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise
        except OSError:
            pass  # Pruning is best-effort


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

SESSION_MEMORY = SessionMemory(
    MEMORY_DIR,
    max_thread=MEMORY_MAX_THREAD_ENTRIES,
    max_workspace=MEMORY_MAX_WORKSPACE_ENTRIES,
)


# ---------------------------------------------------------------------------
# Convenience functions for building memory entries from invocation results
# ---------------------------------------------------------------------------


def build_task_summary_entry(
    *,
    prompt: str,
    response_text: str,
    status: str,
    artifacts: list[dict[str, Any]] | None = None,
    tool_calls: list[dict[str, Any]] | None = None,
    todos: list[dict[str, Any]] | None = None,
    warnings: list[str] | None = None,
    context_budget: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a task_summary memory entry from invocation results."""
    # Produce a brief summary of the work done
    artifact_paths = [a.get("path", "?") for a in (artifacts or [])[:20]]
    tool_names = list(set(t.get("tool", "?") for t in (tool_calls or [])[:50]))

    completed_todos = [t.get("content", "?") for t in (todos or []) if t.get("status") == "completed"]
    pending_todos = [t.get("content", "?") for t in (todos or []) if t.get("status") in ("pending", "in_progress")]

    return {
        "type": "task_summary",
        "content": {
            "prompt_summary": prompt[:300],
            "status": status,
            "artifacts": artifact_paths,
            "tools_used": tool_names,
            "completed": completed_todos[:15],
            "remaining": pending_todos[:15],
            "response_excerpt": response_text[:500],
        },
        "warnings": (warnings or [])[:5],
        "context_budget": context_budget,
    }


def build_handoff_entry(
    *,
    prompt: str,
    summary: str,
    todos: list[dict[str, Any]] | None = None,
    artifacts: list[dict[str, Any]] | None = None,
    context_budget: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a handoff memory entry for session continuity."""
    return {
        "type": "handoff",
        "content": {
            "original_prompt": prompt[:1000],
            "summary": summary[:2000],
            "todos": (todos or [])[:30],
            "artifacts": (artifacts or [])[:30],
            "context_budget": context_budget,
        },
        "original_prompt": prompt[:1000],
        "summary": summary[:2000],
        "todos": (todos or [])[:30],
        "artifacts": (artifacts or [])[:30],
    }
