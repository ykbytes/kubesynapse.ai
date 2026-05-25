"""Thread-safe session registry for thread_id → session_id mapping."""
from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path
from typing import Any

from config import SESSION_MAP_PATH, SESSION_MAX_AGE_SECONDS, SESSION_MAX_ENTRIES

logger = logging.getLogger("opencode-runtime")


class SessionRegistry:
    """Thread-safe ``thread_id → session_id`` mapping with lazy pruning."""

    def __init__(self, path: Path, *, max_age_seconds: int = 86400, max_entries: int = 1000):
        self.path = path
        self._lock = threading.Lock()
        self._cache: dict[str, dict[str, Any]] | None = None
        self.max_age_seconds = max_age_seconds
        self.max_entries = max_entries
        self._last_prune_time: float = 0.0

    def _load(self) -> dict[str, dict[str, Any]]:
        if self._cache is not None:
            return dict(self._cache)
        if not self.path.exists():
            self._cache = {}
            return {}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as _exc:
            logger.warning("Failed to load session registry from %s: %s — treating as empty.", self.path, _exc)
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        # Migrate legacy entries (plain string values) to timestamped dicts
        migrated: dict[str, dict[str, Any]] = {}
        for key, value in payload.items():
            if isinstance(value, dict) and "session_id" in value:
                migrated[str(key)] = value
            else:
                migrated[str(key)] = {"session_id": str(value), "last_accessed": time.time()}
        self._cache = migrated
        return dict(self._cache)

    def _save(self, data: dict[str, dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8")
        self._cache = data

    def _maybe_prune(self, data: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
        """Prune stale/excess entries; debounced to once per 60s."""
        now = time.time()
        if now - self._last_prune_time < 60.0:
            return data
        self._last_prune_time = now
        cutoff = now - self.max_age_seconds
        pruned = {k: v for k, v in data.items() if v.get("last_accessed", 0) >= cutoff}
        if len(pruned) > self.max_entries:
            sorted_entries = sorted(pruned.items(), key=lambda kv: kv[1].get("last_accessed", 0), reverse=True)
            pruned = dict(sorted_entries[: self.max_entries])
        return pruned

    def get(self, thread_id: str) -> str | None:
        with self._lock:
            data = self._load()
            entry = data.get(thread_id)
            if entry is None:
                return None
            entry["last_accessed"] = time.time()
            return entry["session_id"]

    def set(self, thread_id: str, session_id: str) -> None:
        with self._lock:
            data = self._load()
            data[thread_id] = {"session_id": session_id, "last_accessed": time.time()}
            data = self._maybe_prune(data)
            self._save(data)

    def get_or_set(self, thread_id: str, session_id: str) -> str:
        """Atomically return an existing session or register *session_id*."""
        with self._lock:
            data = self._load()
            existing = data.get(thread_id)
            if existing:
                existing["last_accessed"] = time.time()
                return existing["session_id"]
            data[thread_id] = {"session_id": session_id, "last_accessed": time.time()}
            data = self._maybe_prune(data)
            self._save(data)
            return session_id

    @property
    def size(self) -> int:
        """Current number of entries (for health metrics)."""
        with self._lock:
            return len(self._load())

    def stale_count(self, stale_seconds: float = 3600.0) -> int:
        """Count entries older than *stale_seconds* (for health metrics)."""
        cutoff = time.time() - stale_seconds
        with self._lock:
            data = self._load()
            return sum(1 for v in data.values() if v.get("last_accessed", 0) < cutoff)


SESSION_REGISTRY = SessionRegistry(
    SESSION_MAP_PATH,
    max_age_seconds=SESSION_MAX_AGE_SECONDS,
    max_entries=SESSION_MAX_ENTRIES,
)
