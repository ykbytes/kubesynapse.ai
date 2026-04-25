"""Entity extraction for user profiles and project context.

Inspired by Hermes Agent's entity extraction — extracts lasting facts
from conversations (preferences, projects, tools, routines) for
PERMANENT memory storage.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from memory.types import MemoryEntry, MemoryPriority, MemoryRetention, MemoryType

logger = logging.getLogger(__name__)

# Patterns for extracting entities from text
_ENTITY_PATTERNS = {
    "preference": re.compile(
        r"(?:i (?:prefer|like|want|need|use)|my (?:favorite|preferred)|"
        r"(?:preference|setting)\s*[:=]\s*)",
        re.IGNORECASE,
    ),
    "project": re.compile(
        r"(?:project|repo|repository|codebase|app|service)\s*[:=]?\s*([\w\-/]+)",
        re.IGNORECASE,
    ),
    "tool": re.compile(
        r"(?:using|with|via|tool)\s+([\w\-]+(?:\s+\w+){0,3})",
        re.IGNORECASE,
    ),
    "tech_stack": re.compile(
        r"(?:python|javascript|typescript|go|rust|java|kotlin|"
        r"react|vue|angular|svelte|next\.js|django|fastapi|flask|"
        r"kubernetes|docker|terraform|ansible|aws|gcp|azure)",
        re.IGNORECASE,
    ),
}


class EntityExtractor:
    """Extract entities from conversation text for permanent memory."""

    def extract_from_message(self, role: str, content: str) -> list[dict[str, Any]]:
        """Extract entities from a single message.

        Returns list of entity dicts with type, value, and confidence.
        """
        entities: list[dict[str, Any]] = []

        if role != "user":
            # Only extract from user messages (assistant shouldn't be the source)
            return entities

        # Preference extraction
        if _ENTITY_PATTERNS["preference"].search(content):
            entities.append({
                "type": "preference",
                "value": self._extract_preference(content),
                "confidence": 0.7,
                "source": "pattern_match",
            })

        # Project extraction
        for match in _ENTITY_PATTERNS["project"].finditer(content):
            entities.append({
                "type": "project",
                "value": match.group(1).strip(),
                "confidence": 0.8,
                "source": "regex",
            })

        # Tool extraction
        for match in _ENTITY_PATTERNS["tool"].finditer(content):
            tool = match.group(1).strip()
            if len(tool) > 2:  # Filter out very short matches
                entities.append({
                    "type": "tool",
                    "value": tool,
                    "confidence": 0.6,
                    "source": "regex",
                })

        # Tech stack extraction
        for match in _ENTITY_PATTERNS["tech_stack"].finditer(content):
            entities.append({
                "type": "tech_stack",
                "value": match.group(0).lower(),
                "confidence": 0.9,
                "source": "keyword",
            })

        return entities

    def extract_from_conversation(
        self, messages: list[dict[str, Any]]
    ) -> list[MemoryEntry]:
        """Extract all entities from a conversation and return as memory entries.

        This is called at session end to populate PERMANENT memory.
        """
        entries: list[MemoryEntry] = []
        seen: set[str] = set()

        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content", "")

            if not content or role != "user":
                continue

            entities = self.extract_from_message(role, content)
            for entity in entities:
                key = f"{entity['type']}:{entity['value']}"
                if key in seen:
                    continue
                seen.add(key)

                entries.append(
                    MemoryEntry(
                        content={
                            "entity_type": entity["type"],
                            "value": entity["value"],
                            "confidence": entity["confidence"],
                            "source": entity["source"],
                        },
                        memory_type=MemoryType.ENTITY,
                        retention=MemoryRetention.PERMANENT,
                        priority=MemoryPriority.HIGH,
                        tags=["auto_extracted", entity["type"]],
                    )
                )

        return entries

    def build_user_profile(self, entries: list[MemoryEntry]) -> dict[str, Any]:
        """Build a structured user profile from entity entries."""
        profile: dict[str, list[str]] = {
            "preferences": [],
            "projects": [],
            "tools": [],
            "tech_stack": [],
        }

        for entry in entries:
            entity_type = entry.content.get("entity_type", "")
            value = entry.content.get("value", "")
            if entity_type in profile and value:
                profile[entity_type].append(value)

        # Deduplicate while preserving order
        for key in profile:
            seen = set()
            profile[key] = [x for x in profile[key] if not (x in seen or seen.add(x))]

        return profile

    def _extract_preference(self, text: str) -> str:
        """Extract preference value from text."""
        # Simple extraction: take the sentence containing the preference
        sentences = re.split(r'[.!?]+', text)
        for sentence in sentences:
            if _ENTITY_PATTERNS["preference"].search(sentence):
                return sentence.strip()
        return text[:200]  # Fallback


# Singleton instance
ENTITY_EXTRACTOR = EntityExtractor()
