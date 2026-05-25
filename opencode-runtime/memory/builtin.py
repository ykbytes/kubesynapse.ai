"""Enhanced built-in memory provider — file-backed with JSONL storage.

Replaces the old SessionMemory with a proper MemoryProvider implementation
that supports all retention tiers via separate files per tier.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

from memory.provider import MemoryProvider
from memory.types import MemoryEntry, MemoryRetention

logger = logging.getLogger(__name__)


class BuiltinMemoryProvider(MemoryProvider):
    """File-backed memory provider for SESSION and WORKSPACE retention.

    Stores memories as JSONL files:
      - threads/{thread_id}.jsonl  → SESSION memory
      - workspace.jsonl            → WORKSPACE memory
    """

    def __init__(
        self,
        base_dir: Path,
        max_session_entries: int = 200,
        max_workspace_entries: int = 100,
    ):
        self._base_dir = base_dir
        self._max_session = max_session_entries
        self._max_workspace = max_workspace_entries
        self._lock = threading.Lock()
        self._session_id: str | None = None

    @property
    def name(self) -> str:
        return "builtin"

    @property
    def supported_retention(self) -> set[MemoryRetention]:
        return {MemoryRetention.SESSION, MemoryRetention.WORKSPACE}

    def is_available(self) -> bool:
        return True  # Always available (file-based)

    def initialize(self, session_id: str, **kwargs: Any) -> None:
        self._session_id = session_id
        self._base_dir.mkdir(parents=True, exist_ok=True)

    def _session_path(self, thread_id: str) -> Path:
        safe_id = "".join(c if c.isalnum() or c in "-_" else "_" for c in thread_id)[:64]
        return self._base_dir / "threads" / f"{safe_id}.jsonl"

    def _workspace_path(self) -> Path:
        return self._base_dir / "workspace.jsonl"

    def _path_for_retention(self, entry: MemoryEntry) -> Path:
        if entry.retention == MemoryRetention.WORKSPACE:
            return self._workspace_path()
        # Default to session
        thread_id = entry.content.get("thread_id", self._session_id or "default")
        return self._session_path(str(thread_id))

    def store(self, entry: MemoryEntry) -> bool:
        """Store a memory entry to the appropriate file."""
        path = self._path_for_retention(entry)
        max_entries = (
            self._max_workspace
            if entry.retention == MemoryRetention.WORKSPACE
            else self._max_session
        )
        return self._append(path, entry, max_entries)

    def recall(
        self,
        query: str,
        retention: MemoryRetention | None = None,
        limit: int = 10,
        min_relevance: float = 0.0,
    ) -> list[tuple[MemoryEntry, float]]:
        """Recall memories using simple text matching.

        For the builtin provider, relevance is based on:
        1. Timestamp (more recent = more relevant)
        2. Content match with query (simple substring/keyword matching)
        """
        results: list[tuple[MemoryEntry, float]] = []

        # Collect entries from all relevant files
        entries: list[MemoryEntry] = []

        if (retention is None or retention == MemoryRetention.SESSION) and self._session_id:
            entries.extend(self._read_all(self._session_path(self._session_id)))

        if retention is None or retention == MemoryRetention.WORKSPACE:
            entries.extend(self._read_all(self._workspace_path()))

        # Score and filter
        query_lower = query.lower()
        now = time.time()

        for entry in entries:
            if entry.is_expired():
                continue

            # Simple relevance scoring
            score = 0.0

            # Time decay (more recent = higher score)
            age_hours = (now - entry.timestamp) / 3600
            time_score = max(0.0, 1.0 - (age_hours / 168))  # Decay over 1 week
            score += time_score * 0.3

            # Priority boost
            score += entry.priority.value * 0.3

            # Content match
            content_str = json.dumps(entry.content, default=str).lower()
            query_words = [w for w in query_lower.split() if len(w) > 2]
            if query_words:
                matches = sum(1 for w in query_words if w in content_str)
                score += (matches / len(query_words)) * 0.4

            if score >= min_relevance:
                results.append((entry, round(score, 3)))

        # Sort by score descending
        results.sort(key=lambda x: x[1], reverse=True)
        return results[:limit]

    def recall_by_type(self, memory_type: str, limit: int = 10) -> list[MemoryEntry]:
        """Recall memories of a specific type."""
        entries: list[MemoryEntry] = []

        # Read all sources
        if self._session_id:
            entries.extend(self._read_all(self._session_path(self._session_id)))
        entries.extend(self._read_all(self._workspace_path()))

        # Filter by type
        filtered = [e for e in entries if e.memory_type.value == memory_type]
        return filtered[:limit]

    def delete(self, entry_id: str) -> bool:
        """Delete by finding entry with matching content.id."""
        # Best-effort: scan all files and remove matching entries
        deleted = False
        for path in self._all_memory_files():
            entries = self._read_all(path)
            filtered = [e for e in entries if e.content.get("id") != entry_id]
            if len(filtered) < len(entries):
                self._write_all(path, filtered)
                deleted = True
        return deleted

    def clear(self, thread_id: str | None = None) -> bool:
        """Clear memories."""
        try:
            if thread_id:
                path = self._session_path(thread_id)
                if path.exists():
                    path.unlink()
            else:
                # Clear session + workspace
                if self._session_id:
                    session_path = self._session_path(self._session_id)
                    if session_path.exists():
                        session_path.unlink()
                workspace_path = self._workspace_path()
                if workspace_path.exists():
                    workspace_path.unlink()
            return True
        except OSError as exc:
            logger.warning("Failed to clear memory: %s", exc)
            return False

    def compact(self, thread_id: str | None = None) -> bool:
        """Compact by removing expired entries and pruning to limits."""
        try:
            for path in self._all_memory_files():
                if thread_id and thread_id not in str(path):
                    continue
                entries = self._read_all(path)
                # Remove expired
                entries = [e for e in entries if not e.is_expired()]
                # Prune to limit
                limit = self._max_workspace if "workspace" in str(path) else self._max_session
                if len(entries) > limit:
                    entries = entries[-limit:]
                self._write_all(path, entries)
            return True
        except OSError as exc:
            logger.warning("Compaction failed: %s", exc)
            return False

    def shutdown(self) -> None:
        """No-op for file-based provider."""
        pass

    def get_stats(self) -> dict[str, Any]:
        """Return file statistics."""
        stats = {"type": "builtin", "files": {}}
        for path in self._all_memory_files():
            entries = self._read_all(path)
            stats["files"][path.name] = {
                "entries": len(entries),
                "size_bytes": path.stat().st_size if path.exists() else 0,
            }
        return stats

    # Internal helpers

    def _all_memory_files(self) -> list[Path]:
        files: list[Path] = []
        threads_dir = self._base_dir / "threads"
        if threads_dir.exists():
            files.extend(threads_dir.glob("*.jsonl"))
        workspace = self._workspace_path()
        if workspace.exists():
            files.append(workspace)
        return files

    def _append(self, path: Path, entry: MemoryEntry, max_entries: int) -> bool:
        with self._lock:
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                line = json.dumps(entry.to_dict(), ensure_ascii=False, sort_keys=True) + "\n"
                with open(path, "a", encoding="utf-8") as f:
                    f.write(line)
                self._maybe_prune(path, max_entries)
                return True
            except OSError as exc:
                logger.warning("Failed to save memory to %s: %s", path, exc)
                return False

    def _read_all(self, path: Path) -> list[MemoryEntry]:
        if not path.exists():
            return []
        entries: list[MemoryEntry] = []
        try:
            with open(path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                        entries.append(MemoryEntry.from_dict(data))
                    except (json.JSONDecodeError, KeyError):
                        continue
        except OSError as exc:
            logger.warning("Failed to read memory from %s: %s", path, exc)
        return entries

    def _write_all(self, path: Path, entries: list[MemoryEntry]) -> None:
        with self._lock:
            try:
                fd, tmp_path = tempfile.mkstemp(
                    dir=str(path.parent), suffix=".tmp", prefix=path.stem
                )
                try:
                    with os.fdopen(fd, "w", encoding="utf-8") as tmp_f:
                        for entry in entries:
                            tmp_f.write(
                                json.dumps(entry.to_dict(), ensure_ascii=False, sort_keys=True)
                                + "\n"
                            )
                    os.replace(tmp_path, str(path))
                except BaseException:
                    # Clean up the temp file on any failure
                    with contextlib.suppress(OSError):
                        os.unlink(tmp_path)
                    raise
            except OSError as exc:
                logger.warning("Failed to write memory to %s: %s", path, exc)

    def _maybe_prune(self, path: Path, max_entries: int) -> None:
        try:
            entries = self._read_all(path)
            if len(entries) <= max_entries:
                return
            self._write_all(path, entries[-max_entries:])
        except OSError:
            pass  # Pruning is best-effort
