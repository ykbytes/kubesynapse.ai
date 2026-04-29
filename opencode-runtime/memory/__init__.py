"""kubesynapse Memory System — Production-grade agent memory.

A multi-tier, pluggable memory architecture inspired by Hermes Agent.

Usage:
    from memory import MemoryManager, BuiltinMemoryProvider, SemanticMemoryProvider
    from memory.types import MemoryEntry, MemoryType, MemoryRetention

    # Initialize
    manager = MemoryManager()
    manager.add_provider(BuiltinMemoryProvider(base_dir=Path("./memory")))
    manager.add_provider(SemanticMemoryProvider(qdrant_url="http://localhost:6333"))
    manager.initialize(session_id="sess-123")

    # Store
    entry = MemoryEntry(
        content={"task": "refactor auth"},
        memory_type=MemoryType.TASK_SUMMARY,
        retention=MemoryRetention.SESSION,
    )
    manager.store(entry)

    # Recall
    results = manager.recall("authentication refactoring", limit=5)
    context = manager.build_context("authentication refactoring")
"""

from memory.builtin import BuiltinMemoryProvider
from memory.compat import (
    MEMORY_ENTRY_TYPES,
    SESSION_MEMORY,
    SessionMemory,
    build_handoff_entry,
    build_task_summary_entry,
)
from memory.entity import ENTITY_EXTRACTOR, EntityExtractor
from memory.manager import MemoryManager, build_memory_context_block, sanitize_context
from memory.provider import MemoryProvider
from memory.semantic import SemanticMemoryProvider
from memory.types import (
    DEFAULT_PRIORITY,
    DEFAULT_RETENTION,
    MemoryEntry,
    MemoryPriority,
    MemoryRetention,
    MemoryType,
)

__all__ = [
    "DEFAULT_PRIORITY",
    "DEFAULT_RETENTION",
    "ENTITY_EXTRACTOR",
    "MEMORY_ENTRY_TYPES",
    "SESSION_MEMORY",
    "BuiltinMemoryProvider",
    "EntityExtractor",
    "MemoryEntry",
    "MemoryManager",
    "MemoryPriority",
    "MemoryProvider",
    "MemoryRetention",
    "MemoryType",
    "SemanticMemoryProvider",
    "SessionMemory",
    "build_handoff_entry",
    "build_memory_context_block",
    "build_task_summary_entry",
    "sanitize_context",
]
