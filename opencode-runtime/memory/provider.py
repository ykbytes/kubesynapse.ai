"""Abstract base class for pluggable memory providers.

Inspired by Hermes Agent's MemoryProvider architecture — provides a clean
interface for multiple memory backends (file, Qdrant, PostgreSQL, Redis).
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any

from memory.types import MemoryEntry, MemoryRetention

logger = logging.getLogger(__name__)


class MemoryProvider(ABC):
    """Abstract base class for memory providers.

    Each provider handles a specific retention tier:
      - BuiltinMemoryProvider: file-backed SESSION + WORKSPACE memory
      - SemanticMemoryProvider: Qdrant-backed LONG_TERM vector memory
      - PermanentMemoryProvider: PostgreSQL-backed PERMANENT user profile
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Short identifier (e.g. 'builtin', 'semantic', 'permanent')."""

    @property
    @abstractmethod
    def supported_retention(self) -> set[MemoryRetention]:
        """Which retention tiers this provider handles."""

    @abstractmethod
    def is_available(self) -> bool:
        """Return True if provider is configured and ready (no network calls)."""

    @abstractmethod
    def initialize(self, session_id: str, **kwargs: Any) -> None:
        """Initialize for a session. Called once at agent startup."""

    @abstractmethod
    def store(self, entry: MemoryEntry) -> bool:
        """Store a memory entry. Returns True on success."""

    @abstractmethod
    def recall(
        self,
        query: str,
        retention: MemoryRetention | None = None,
        limit: int = 10,
        min_relevance: float = 0.0,
    ) -> list[tuple[MemoryEntry, float]]:
        """Recall memories matching query. Returns list of (entry, relevance_score)."""

    @abstractmethod
    def recall_by_type(
        self,
        memory_type: str,
        limit: int = 10,
    ) -> list[MemoryEntry]:
        """Recall memories by specific type (e.g. 'user_preference')."""

    @abstractmethod
    def delete(self, entry_id: str) -> bool:
        """Delete a specific memory entry by ID."""

    @abstractmethod
    def clear(self, thread_id: str | None = None) -> bool:
        """Clear memories. If thread_id provided, clears only that thread."""

    @abstractmethod
    def compact(self, thread_id: str | None = None) -> bool:
        """Compact old memories into summaries. Best-effort operation."""

    @abstractmethod
    def shutdown(self) -> None:
        """Clean exit — flush buffers, close connections."""

    # Optional hooks (override to opt in)

    def on_turn_start(self, turn_number: int, user_message: str) -> None:
        """Called at the start of each turn. Override for prefetching."""
        return None

    def on_session_end(self, messages: list[dict[str, Any]]) -> None:
        """Called at session end for bulk ingestion. Override to extract entities."""
        return None

    def get_stats(self) -> dict[str, Any]:
        """Return provider statistics (entry count, storage size, etc.)."""
        return {}
