"""Pure utility functions with no domain dependencies."""
from __future__ import annotations

import json
from pathlib import Path, PurePosixPath
from typing import Any


def dedupe_items(values: list[str]) -> list[str]:
    """Return a deduplicated list preserving insertion order."""
    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = str(value).strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        deduped.append(cleaned)
    return deduped


def truncate_text(text: str, limit: int = 4000) -> str:
    """Truncate *text* to *limit* characters with an ellipsis suffix."""
    if len(text) <= limit:
        return text
    if limit <= 3:
        return text[:limit]
    return f"{text[: limit - 3]}..."


def normalize_identifier(value: str, *, source: str) -> str:
    """Validate and return a trimmed Kubernetes-style identifier."""
    cleaned = value.strip()
    if not cleaned:
        raise ValueError(f"{source} must not be blank")
    if len(cleaned) > 63:
        raise ValueError(f"{source} must be 63 characters or fewer")
    return cleaned


def normalize_relative_path(raw_path: str, *, source: str) -> str:
    """Validate and normalise a relative POSIX path."""
    candidate = str(raw_path or "").strip().replace("\\", "/")
    if not candidate:
        raise RuntimeError(f"{source} path must not be blank")
    if candidate.startswith("/"):
        raise RuntimeError(f"{source} path '{candidate}' must be relative")
    if len(candidate) > 512:
        raise RuntimeError(f"{source} path '{candidate}' is too long")
    normalized = PurePosixPath(candidate)
    if normalized.is_absolute() or any(part in {"", ".", ".."} for part in normalized.parts):
        raise RuntimeError(f"{source} path '{candidate}' must stay within the runtime config root")
    return normalized.as_posix()


def serialize_file_content(content: Any) -> str:
    """Serialize arbitrary content to a string for file writing."""
    if isinstance(content, str):
        return content
    return json.dumps(content, ensure_ascii=False, indent=2, sort_keys=True)


def sse_event(event: str, data: dict[str, Any]) -> str:
    """Format a Server-Sent Events message."""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def path_is_within(path: Path, root: Path) -> bool:
    """Return True if *path* is a descendant of *root*."""
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False
