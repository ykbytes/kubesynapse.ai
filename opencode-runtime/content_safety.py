"""Prompt-content sanitization helpers for OpenCode runtime inputs."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

logger = logging.getLogger("opencode-runtime.safety")

_MAX_FRAGMENT_CHARS = 32_000
_INJECTION_ENVELOPE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"</?\s*system[\s_-]?reminder\s*>", re.IGNORECASE),
    re.compile(r"</?\s*system\s*>", re.IGNORECASE),
    re.compile(r"</?\s*/?\s*description\s*>", re.IGNORECASE),
    re.compile(r"</?\s*tool_?description\s*>", re.IGNORECASE),
    re.compile(r"</?\s*instructions?\s*>", re.IGNORECASE),
    re.compile(r"</?\s*system_?prompt\s*>", re.IGNORECASE),
    re.compile(r"</?\s*tool_?result\s*>", re.IGNORECASE),
    re.compile(r"</?\s*function_calls?\s*>", re.IGNORECASE),
    re.compile(r"</?\s*invoke\s*>", re.IGNORECASE),
    re.compile(r"</?\s*human\s*>", re.IGNORECASE),
    re.compile(r"</?\s*assistant\s*>", re.IGNORECASE),
    re.compile(r"</?\s*tool_use\s*>", re.IGNORECASE),
    re.compile(r"</?\s*ip_reminder\s*>", re.IGNORECASE),
    re.compile(r"</?\s*file\s*>", re.IGNORECASE),
    re.compile(r"</?\s*result\s*>", re.IGNORECASE),
)
_IGNORE_PATTERN = re.compile(
    r"\b(ignore|disregard|forget|override|bypass|skip)\s+"
    r"(?:all|any|the|every|previous|prior|above|earlier|system|developer|safety)"
    r"[^.\n]{0,80}?(?:instruction|prompt|directive|rule|policy|context|message)",
    re.IGNORECASE,
)


def sanitize_text(value: Any, *, source: str = "<unknown>", max_chars: int = _MAX_FRAGMENT_CHARS) -> str:
    """Return a bounded text fragment with known prompt-injection envelopes removed."""
    if value is None:
        return ""
    if not isinstance(value, str):
        try:
            value = str(value)
        except Exception:
            return ""
    text = value
    for pattern in _INJECTION_ENVELOPE_PATTERNS:
        text = pattern.sub("", text)
    text = "".join(ch for ch in text if ch in "\n\r\t" or ord(ch) >= 0x20)
    text = re.sub(r"[ \t]{4,}", "    ", text)
    if len(text) > max_chars:
        text = text[: max_chars - 3] + "..."
    if _IGNORE_PATTERN.search(text):
        logger.warning("Potential prompt-injection wording detected in %s", source)
    return text


def sanitize_a2a_text_part(value: Any, *, source: str = "a2a-text") -> str:
    return sanitize_text(value, source=source, max_chars=16_000)


def sanitize_a2a_data_part(value: Any, *, source: str = "a2a-data") -> str:
    try:
        rendered = json.dumps(value, ensure_ascii=False, default=str, sort_keys=True)
    except (TypeError, ValueError):
        rendered = str(value)
    return sanitize_text(rendered, source=source, max_chars=16_000)


def sanitize_skill_body(value: Any, *, source: str = "skill-body") -> str:
    return sanitize_text(value, source=source, max_chars=64_000)
