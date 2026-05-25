"""Cross-session memory — persistent context that survives session loss and compaction.

This module provides backward-compatible access to the new multi-tier memory
system (memory/*.py). The SessionMemory class delegates to MemoryManager under
the hood while preserving the original API.
"""

from __future__ import annotations

import contextlib
import logging
import time
from pathlib import Path
from typing import Any

from config import (
    MEMORY_CONTEXT_FENCING_ENABLED,
    MEMORY_CONTEXT_MAX_TOKENS,
    MEMORY_DEFAULT_RETENTION,
    MEMORY_DIR,
    MEMORY_ENABLED,
    MEMORY_MAX_THREAD_ENTRIES,
    MEMORY_MAX_WORKSPACE_ENTRIES,
    MEMORY_QDRANT_COLLECTION,
    MEMORY_QDRANT_DIMENSION,
    MEMORY_QDRANT_TIMEOUT,
    MEMORY_QDRANT_URL,
    MEMORY_SEMANTIC_ENABLED,
)
from memory import (
    BuiltinMemoryProvider,
    MemoryManager,
    SemanticMemoryProvider,
)
from memory.types import MemoryEntry, MemoryPriority, MemoryRetention, MemoryType

logger = logging.getLogger("opencode-runtime")

# Valid memory entry types (backward compatibility)
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

# Mapping from legacy entry types to MemoryType enum
_TYPE_MAP: dict[str, MemoryType] = {
    "task_summary": MemoryType.TASK_SUMMARY,
    "decision": MemoryType.DECISION,
    "error_pattern": MemoryType.ERROR_PATTERN,
    "codebase_insight": MemoryType.CODEBASE_INSIGHT,
    "file_map": MemoryType.FILE_MAP,
    "handoff": MemoryType.HANDOFF,
}


def _legacy_to_entry(thread_id: str, entry: dict[str, Any]) -> MemoryEntry:
    """Convert a legacy memory entry dict to a MemoryEntry object."""
    entry_type = entry.get("type", "task_summary")
    memory_type = _TYPE_MAP.get(entry_type, MemoryType.TASK_SUMMARY)

    # Determine retention from default config
    retention_str = MEMORY_DEFAULT_RETENTION
    retention = MemoryRetention.SESSION
    with contextlib.suppress(ValueError):
        retention = MemoryRetention(retention_str)

    return MemoryEntry(
        content={
            **entry.get("content", {}),
            "thread_id": thread_id,
            "legacy_type": entry_type,
        },
        memory_type=memory_type,
        retention=retention,
        priority=MemoryPriority.MEDIUM,
        tags=["legacy", entry_type],
        timestamp=entry.get("timestamp", time.time()),
    )


def _entry_to_legacy(entry: MemoryEntry) -> dict[str, Any]:
    """Convert a MemoryEntry back to legacy dict format."""
    legacy = entry.to_dict()
    # Flatten content back to legacy structure
    content = legacy.get("content", {})
    legacy_type = content.get("legacy_type", "task_summary")
    result = {
        "type": legacy_type,
        "timestamp": legacy.get("timestamp", time.time()),
        "content": {k: v for k, v in content.items() if k not in ("thread_id", "legacy_type")},
    }
    # Copy any top-level keys that were in the original entry
    for key in ("warnings", "context_budget", "original_prompt", "summary", "todos", "artifacts"):
        if key in content:
            result[key] = content[key]
    return result


class SessionMemory:
    """File-backed JSONL memory store for cross-session context persistence.

    **Backward-compatible wrapper** around the new MemoryManager.
    Provides the same API as the original SessionMemory while delegating
    to the multi-tier memory system underneath.
    """

    def __init__(self, base_dir: Path, *, max_thread: int = 100, max_workspace: int = 50):
        self._base_dir = base_dir
        self._max_thread = max_thread
        self._max_workspace = max_workspace

        # Initialize the new memory manager
        self._manager = MemoryManager(
            max_entries_per_provider=max_thread,
            context_fencing=MEMORY_CONTEXT_FENCING_ENABLED,
            max_context_tokens=MEMORY_CONTEXT_MAX_TOKENS,
        )

        # Add builtin provider (always)
        builtin = BuiltinMemoryProvider(
            base_dir=base_dir,
            max_entries=max_thread,
            max_workspace_entries=max_workspace,
        )
        self._manager.add_provider(builtin)

        # Add semantic provider if enabled
        if MEMORY_SEMANTIC_ENABLED:
            semantic = SemanticMemoryProvider(
                qdrant_url=MEMORY_QDRANT_URL,
                collection_name=MEMORY_QDRANT_COLLECTION,
                embedding_dimension=MEMORY_QDRANT_DIMENSION,
                timeout=MEMORY_QDRANT_TIMEOUT,
            )
            self._manager.add_provider(semantic)
            logger.info("Semantic memory enabled via Qdrant at %s", MEMORY_QDRANT_URL)

        self._initialized = False

    def _ensure_initialized(self, thread_id: str) -> None:
        if not self._initialized:
            self._manager.initialize(session_id=thread_id)
            self._initialized = True

    # ------------------------------------------------------------------
    # Path helpers (backward compatibility — no longer used internally)
    # ------------------------------------------------------------------

    def _thread_path(self, thread_id: str) -> Path:
        safe_id = "".join(c if c.isalnum() or c in "-_" else "_" for c in thread_id)[:64]
        return self._base_dir / "threads" / f"{safe_id}.jsonl"

    def _workspace_path(self) -> Path:
        return self._base_dir / "workspace.jsonl"

    # ------------------------------------------------------------------
    # Core operations (backward-compatible API)
    # ------------------------------------------------------------------

    def save_memory(self, thread_id: str, entry: dict[str, Any]) -> bool:
        """Append a memory entry to the thread memory file.

        The entry should have at least ``type`` and ``content`` keys.
        A ``timestamp`` is added automatically if missing.
        Unknown entry types are logged as warnings but still saved.
        """
        if not MEMORY_ENABLED:
            return False
        self._ensure_initialized(thread_id)
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
        memory_entry = _legacy_to_entry(thread_id, entry)
        return self._manager.store(memory_entry)

    def save_workspace_memory(self, entry: dict[str, Any]) -> bool:
        """Append a memory entry to the shared workspace memory file.

        Unknown entry types are logged as warnings but still saved.
        """
        if not MEMORY_ENABLED:
            return False
        self._ensure_initialized("workspace")
        entry.setdefault("timestamp", time.time())
        entry.setdefault("type", "codebase_insight")
        entry_type = entry.get("type")
        if entry_type not in MEMORY_ENTRY_TYPES:
            logger.warning(
                "Unknown workspace memory entry type %r (expected one of %s)",
                entry_type,
                sorted(MEMORY_ENTRY_TYPES),
            )
        # Use a special thread_id for workspace entries
        memory_entry = _legacy_to_entry("workspace", entry)
        memory_entry.memory_type = MemoryType.CODEBASE_INSIGHT
        return self._manager.store(memory_entry)

    def recall_memory(self, thread_id: str, limit: int = 10) -> list[dict[str, Any]]:
        """Retrieve the most recent thread memory entries."""
        if not MEMORY_ENABLED:
            return []
        self._ensure_initialized(thread_id)
        # Also include other types that were originally stored for this thread
        all_entries: list[MemoryEntry] = []
        for mtype in MemoryType:
            all_entries.extend(self._manager.recall_by_type(mtype.value, limit=limit))
        # Filter by thread_id and deduplicate
        seen: set[str] = set()
        filtered: list[dict[str, Any]] = []
        for entry in sorted(all_entries, key=lambda e: e.timestamp or 0, reverse=True):
            if entry.content.get("thread_id") == thread_id:
                entry_id = entry.content.get("task_id") or str(id(entry))
                if entry_id not in seen:
                    seen.add(entry_id)
                    filtered.append(_entry_to_legacy(entry))
                    if len(filtered) >= limit:
                        break
        return filtered

    def recall_workspace_memory(self, limit: int = 5) -> list[dict[str, Any]]:
        """Retrieve the most recent workspace memory entries."""
        if not MEMORY_ENABLED:
            return []
        self._ensure_initialized("workspace")
        entries = self._manager.recall_by_type(MemoryType.CODEBASE_INSIGHT.value, limit=limit)
        return [_entry_to_legacy(e) for e in entries]

    def build_memory_context(self, thread_id: str) -> list[dict[str, Any]]:
        """Compose memory entries from both tiers for injection into a session.

        Returns a combined list with workspace entries first, then thread entries,
        sorted by timestamp (oldest first within each tier).
        """
        if not MEMORY_ENABLED:
            return []
        self._ensure_initialized(thread_id)
        workspace = self.recall_workspace_memory(limit=5)
        thread = self.recall_memory(thread_id, limit=10)
        combined = workspace + thread
        return combined

    def has_memory(self, thread_id: str) -> bool:
        """Return True if there is any persisted memory for the thread."""
        if not MEMORY_ENABLED:
            return False
        self._ensure_initialized(thread_id)
        entries = self._manager.recall("", limit=1)
        return len(entries) > 0

    def get_handoff_memory(self, thread_id: str) -> dict[str, Any] | None:
        """Return the most recent handoff entry for a thread, if any."""
        self._ensure_initialized(thread_id)
        entries = self._manager.recall_by_type(MemoryType.HANDOFF.value, limit=10)
        for entry in sorted(entries, key=lambda e: e.timestamp or 0, reverse=True):
            if entry.content.get("thread_id") == thread_id:
                return _entry_to_legacy(entry)
        return None

    def clear_thread(self, thread_id: str) -> bool:
        """Remove all memory entries for a thread."""
        self._ensure_initialized(thread_id)
        return self._manager.clear(thread_id=thread_id)

    def shutdown(self) -> None:
        """Gracefully shut down the memory manager."""
        self._manager.shutdown()


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
    artifact_paths = [a.get("path", "?") for a in (artifacts or [])[:20]]
    tool_names = list({t.get("tool", "?") for t in (tool_calls or [])[:50]})

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
        "context_budget": context_budget,
    }
