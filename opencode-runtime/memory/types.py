"""Memory type definitions and constants for the KubeSynth memory system."""

from __future__ import annotations

from enum import Enum, auto
from typing import Any


class MemoryRetention(Enum):
    """Memory retention tiers — determines how long and where memory persists."""

    EPHEMERAL = auto()  # Single turn only, never persisted
    SESSION = auto()  # Current thread/session, file-backed
    WORKSPACE = auto()  # Shared across threads in workspace
    LONG_TERM = auto()  # Vector DB, semantic search, survives forever
    PERMANENT = auto()  # User profile, explicitly curated, never deleted


class MemoryType(Enum):
    """Semantic memory entry types."""

    TASK_SUMMARY = "task_summary"
    DECISION = "decision"
    ERROR_PATTERN = "error_pattern"
    CODEBASE_INSIGHT = "codebase_insight"
    FILE_MAP = "file_map"
    HANDOFF = "handoff"
    USER_PREFERENCE = "user_preference"
    PROJECT_CONTEXT = "project_context"
    TOOL_USAGE = "tool_usage"
    CONVERSATION_EXCERPT = "conversation_excerpt"
    ENTITY = "entity"
    LEARNING = "learning"


class MemoryPriority(Enum):
    """Priority levels for memory retrieval ranking."""

    CRITICAL = 1.0  # Always recalled (user preferences, critical errors)
    HIGH = 0.8  # Strongly preferred (project context, recent decisions)
    NORMAL = 0.5  # Standard recall (task summaries, tool usage)
    LOW = 0.3  # Weak preference (old conversations, tangential info)
    ARCHIVE = 0.1  # Only recalled if highly relevant


# Default retention mapping per memory type
DEFAULT_RETENTION: dict[MemoryType, MemoryRetention] = {
    MemoryType.TASK_SUMMARY: MemoryRetention.SESSION,
    MemoryType.DECISION: MemoryRetention.LONG_TERM,
    MemoryType.ERROR_PATTERN: MemoryRetention.LONG_TERM,
    MemoryType.CODEBASE_INSIGHT: MemoryRetention.WORKSPACE,
    MemoryType.FILE_MAP: MemoryRetention.WORKSPACE,
    MemoryType.HANDOFF: MemoryRetention.SESSION,
    MemoryType.USER_PREFERENCE: MemoryRetention.PERMANENT,
    MemoryType.PROJECT_CONTEXT: MemoryRetention.WORKSPACE,
    MemoryType.TOOL_USAGE: MemoryRetention.SESSION,
    MemoryType.CONVERSATION_EXCERPT: MemoryRetention.EPHEMERAL,
    MemoryType.ENTITY: MemoryRetention.LONG_TERM,
    MemoryType.LEARNING: MemoryRetention.LONG_TERM,
}

# Default priority mapping per memory type
DEFAULT_PRIORITY: dict[MemoryType, MemoryPriority] = {
    MemoryType.TASK_SUMMARY: MemoryPriority.NORMAL,
    MemoryType.DECISION: MemoryPriority.HIGH,
    MemoryType.ERROR_PATTERN: MemoryPriority.HIGH,
    MemoryType.CODEBASE_INSIGHT: MemoryPriority.NORMAL,
    MemoryType.FILE_MAP: MemoryPriority.NORMAL,
    MemoryType.HANDOFF: MemoryPriority.CRITICAL,
    MemoryType.USER_PREFERENCE: MemoryPriority.CRITICAL,
    MemoryType.PROJECT_CONTEXT: MemoryPriority.HIGH,
    MemoryType.TOOL_USAGE: MemoryPriority.LOW,
    MemoryType.CONVERSATION_EXCERPT: MemoryPriority.LOW,
    MemoryType.ENTITY: MemoryPriority.NORMAL,
    MemoryType.LEARNING: MemoryPriority.HIGH,
}


class MemoryEntry:
    """A single memory entry with full metadata."""

    def __init__(
        self,
        content: dict[str, Any],
        memory_type: MemoryType,
        retention: MemoryRetention | None = None,
        priority: MemoryPriority | None = None,
        tags: list[str] | None = None,
        embedding: list[float] | None = None,
        source: str = "",
        timestamp: float | None = None,
        ttl_seconds: float | None = None,
    ):
        self.content = content
        self.memory_type = memory_type
        self.retention = retention or DEFAULT_RETENTION.get(memory_type, MemoryRetention.SESSION)
        self.priority = priority or DEFAULT_PRIORITY.get(memory_type, MemoryPriority.NORMAL)
        self.tags = tags or []
        self.embedding = embedding
        self.source = source
        self.timestamp = timestamp or __import__("time").time()
        self.ttl_seconds = ttl_seconds

    def to_dict(self) -> dict[str, Any]:
        return {
            "content": self.content,
            "type": self.memory_type.value,
            "retention": self.retention.name,
            "priority": self.priority.name,
            "tags": self.tags,
            "embedding": self.embedding,
            "source": self.source,
            "timestamp": self.timestamp,
            "ttl_seconds": self.ttl_seconds,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MemoryEntry:
        return cls(
            content=data["content"],
            memory_type=MemoryType(data.get("type", "task_summary")),
            retention=MemoryRetention[data.get("retention", "SESSION")],
            priority=MemoryPriority[data.get("priority", "NORMAL")],
            tags=data.get("tags", []),
            embedding=data.get("embedding"),
            source=data.get("source", ""),
            timestamp=data.get("timestamp"),
            ttl_seconds=data.get("ttl_seconds"),
        )

    def is_expired(self) -> bool:
        if self.ttl_seconds is None:
            return False
        return (__import__("time").time() - self.timestamp) > self.ttl_seconds
