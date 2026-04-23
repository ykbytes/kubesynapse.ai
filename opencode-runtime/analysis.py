"""Response analysis, context budget, error classification, and artifact extraction."""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from config import (
    A2A_ALLOWED_TARGETS,
    A2A_MAX_TIMEOUT_SECONDS,
    A2A_REQUIRE_HITL,
    API_GATEWAY_INTERNAL_URL,
    API_GATEWAY_SHARED_TOKEN,
    AGENT_SELECTION_MODE,
    ARTIFACT_COLLECTION_MAX_FILES,
    ARTIFACT_PATH_PATTERN,
    COMPACTION_AGGRESSIVE_THRESHOLD,
    COMPACTION_PRUNE_THRESHOLD,
    COMPACTION_TOKEN_THRESHOLD,
    DEFAULT_AGENT,
    DOWNLOADABLE_ARTIFACT_EXTENSIONS,
    MEMORY_ENABLED,
    MODEL_CONTEXT_LIMIT,
    NATIVE_TOOL_NAMES,
    PLAN_AGENT_PROMPT_THRESHOLD,
    SESSION_INIT_ON_CREATE,
    STRUCTURED_OUTPUT_RETRY_COUNT,
    TASK_TYPE_AGENT_MAP,
    _safe_int,
)
from prompts import FORMAT_INSTRUCTIONS
from sanitize_secrets import redact_secrets
from skills import SKILL_RUNTIME_CONFIG
from utils import truncate_text

if TYPE_CHECKING:
    from models import InvokeRequest

logger = logging.getLogger("opencode-runtime")


# ---------------------------------------------------------------------------
# Text extraction
# ---------------------------------------------------------------------------


def extract_text_from_parts(parts: list[dict[str, Any]]) -> str:
    """Extract concatenated text from message parts."""
    fragments: list[str] = []
    for item in parts:
        if not isinstance(item, dict):
            continue
        if item.get("type") == "text":
            text = item.get("text")
            if isinstance(text, str) and text:
                fragments.append(text)
    return "".join(fragments).strip()


def extract_reasoning_from_parts(parts: list[dict[str, Any]]) -> str:
    """Extract concatenated reasoning/thinking text from message parts."""
    fragments: list[str] = []
    for item in parts:
        if not isinstance(item, dict):
            continue
        if item.get("type") == "reasoning":
            text = item.get("text")
            if isinstance(text, str) and text:
                fragments.append(text)
    return "\n".join(fragments).strip()


def extract_response_text(payload: dict[str, Any]) -> str:
    """Extract the authoritative response text from an OpenCode payload."""
    info = payload.get("info")
    if isinstance(info, dict):
        structured_output = info.get("structured")
        if structured_output is None:
            structured_output = info.get("structured_output")
        if structured_output is not None:
            return json.dumps(structured_output, ensure_ascii=False)
        error = info.get("error")
        if isinstance(error, dict) and error.get("message"):
            return str(error.get("message"))
    parts = payload.get("parts")
    if isinstance(parts, list):
        text = extract_text_from_parts([item for item in parts if isinstance(item, dict)])
        if text:
            return text
    return ""


def assistant_payload_has_signal(payload: dict[str, Any]) -> bool:
    """Return True when an assistant payload carries meaningful response content."""
    if extract_response_text(payload).strip():
        return True

    parts = payload.get("parts")
    if not isinstance(parts, list):
        return False

    for item in parts:
        if not isinstance(item, dict):
            continue
        part_type = str(item.get("type") or "").strip().lower()
        if part_type == "reasoning" and str(item.get("text") or "").strip():
            return True
        if part_type in {"tool", "patch"}:
            return True
    return False


# ---------------------------------------------------------------------------
# Structured output
# ---------------------------------------------------------------------------


def build_json_output_schema(output_schema: dict[str, Any] | None) -> dict[str, Any]:
    """Build a JSON schema for structured output, defaulting to a permissive schema."""
    if output_schema:
        return dict(output_schema)
    return {
        "type": "object",
        "description": "Return the final answer as a JSON object.",
        "additionalProperties": True,
    }


def build_prompt_format(request: "InvokeRequest") -> dict[str, Any] | None:
    """Build the prompt format descriptor for structured output requests."""
    if request.output_format == "json":
        return {
            "type": "json_schema",
            "schema": build_json_output_schema(request.output_schema),
            "retryCount": request.structured_output_retry_count
            if request.structured_output_retry_count is not None
            else STRUCTURED_OUTPUT_RETRY_COUNT,
        }
    return None


def _extract_structured_output(payload: dict[str, Any]) -> Any | None:
    """Return the structured output object from an OpenCode response, or *None*."""
    info = payload.get("info")
    if not isinstance(info, dict):
        return None
    structured = info.get("structured")
    if structured is not None:
        return structured
    return info.get("structured_output")


def _build_response_metadata(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Extract metadata (tokens, cost, timing, structured_output) from the OpenCode response."""
    info = payload.get("info")
    if not isinstance(info, dict):
        return None
    metadata: dict[str, Any] = {}
    tokens = info.get("tokens")
    if isinstance(tokens, dict):
        metadata["tokens"] = tokens
    cost = info.get("cost")
    if isinstance(cost, (int, float)):
        metadata["cost"] = cost
    time_info = info.get("time")
    if isinstance(time_info, dict):
        metadata["time"] = time_info
    finish = info.get("finish")
    if finish:
        metadata["finish_reason"] = str(finish)
    structured = _extract_structured_output(payload)
    if structured is not None:
        metadata["structured_output"] = structured
    return metadata or None


# ---------------------------------------------------------------------------
# Completion / error classification
# ---------------------------------------------------------------------------


def detect_completion_status(payload: dict[str, Any]) -> str:
    """Determine whether the agent response indicates task completion."""
    info = payload.get("info") or {}
    if not isinstance(info, dict):
        return "unknown"
    error = info.get("error")
    if error:
        if isinstance(error, dict):
            name = str(error.get("name", "")).strip()
            if name == "ContextOverflowError":
                return "context_overflow"
        return "error"
    finish = str(info.get("finish", "")).strip().lower()
    if finish == "error":
        return "error"
    if finish in ("tool-calls", "unknown", ""):
        return "incomplete"
    return "completed"


def classify_error_type(payload: dict[str, Any]) -> str | None:
    """Classify the error type from an OpenCode response for targeted recovery."""
    info = payload.get("info") or {}
    if not isinstance(info, dict):
        return None
    error = info.get("error")
    if not isinstance(error, dict):
        return None
    name = str(error.get("name", "")).strip()
    error_map = {
        "ContextOverflowError": "context_overflow",
        "StructuredOutputError": "structured_output",
        "ProviderAuthError": "auth",
        "APIError": "api",
        "MessageAbortedError": "aborted",
        "MessageOutputLengthError": "output_length",
    }
    return error_map.get(name)


def extract_error_message(payload: dict[str, Any]) -> str:
    """Extract the most useful human-readable error message from an OpenCode payload."""
    info = payload.get("info") or {}
    if not isinstance(info, dict):
        return ""
    error = info.get("error")
    if not isinstance(error, dict):
        return ""
    data = error.get("data")
    if isinstance(data, dict):
        detailed = str(data.get("message") or "").strip()
        if detailed:
            return detailed
    message = str(error.get("message") or "").strip()
    if message:
        return message
    return str(error.get("name") or "").strip()


def is_error_retryable(payload: dict[str, Any]) -> bool | None:
    """Return whether an OpenCode error is explicitly marked retryable."""
    info = payload.get("info") or {}
    if not isinstance(info, dict):
        return None
    error = info.get("error")
    if not isinstance(error, dict):
        return None
    data = error.get("data")
    if not isinstance(data, dict) or "isRetryable" not in data:
        return None
    raw_value = data.get("isRetryable")
    if isinstance(raw_value, bool):
        return raw_value
    if isinstance(raw_value, str):
        normalized = raw_value.strip().lower()
        if normalized in ("true", "1", "yes"):
            return True
        if normalized in ("false", "0", "no"):
            return False
    return None


def check_context_overflow(payload: dict[str, Any]) -> bool:
    """Check if the response indicates context window is nearing capacity."""
    info = payload.get("info") or {}
    if not isinstance(info, dict):
        return False
    error = info.get("error")
    if isinstance(error, dict) and error.get("name") == "ContextOverflowError":
        return True
    tokens = info.get("tokens")
    if isinstance(tokens, dict):
        total = tokens.get("total") or 0
        if not total:
            cache = tokens.get("cache") or {}
            total = (
                (tokens.get("input") or 0)
                + (tokens.get("output") or 0)
                + (cache.get("read") or 0)
                + (cache.get("write") or 0)
            )
        if total > 0 and total >= MODEL_CONTEXT_LIMIT * COMPACTION_TOKEN_THRESHOLD:
            return True
    return False


def compute_context_budget(payload: dict[str, Any]) -> dict[str, Any]:
    """Compute context budget information from an OpenCode response payload."""
    info = payload.get("info") or {}
    if not isinstance(info, dict):
        return {"status": "unknown", "model_context_limit": MODEL_CONTEXT_LIMIT}
    tokens = info.get("tokens")
    if not isinstance(tokens, dict):
        return {"status": "unknown", "model_context_limit": MODEL_CONTEXT_LIMIT}
    total = tokens.get("total") or 0
    if not total:
        cache = tokens.get("cache") or {}
        total = (
            (tokens.get("input") or 0)
            + (tokens.get("output") or 0)
            + (cache.get("read") or 0)
            + (cache.get("write") or 0)
        )
    if total <= 0:
        return {"status": "unknown", "model_context_limit": MODEL_CONTEXT_LIMIT}
    remaining = max(MODEL_CONTEXT_LIMIT - total, 0)
    usage_pct = round((total / MODEL_CONTEXT_LIMIT) * 100, 1)
    remaining_pct = 100.0 - usage_pct
    if remaining_pct > 35:
        status = "ok"
    elif remaining_pct >= 25:
        status = "warning"
    else:
        status = "critical"
    return {
        "model_context_limit": MODEL_CONTEXT_LIMIT,
        "tokens_used": total,
        "tokens_remaining": remaining,
        "usage_percent": usage_pct,
        "status": status,
    }


# ---------------------------------------------------------------------------
# Anti-pattern detection
# ---------------------------------------------------------------------------

_ANTI_PATTERN_REGEXES: list[tuple[str, re.Pattern[str]]] = [
    ("TODO marker", re.compile(r"\bTODO\b", re.IGNORECASE)),
    ("FIXME marker", re.compile(r"\bFIXME\b", re.IGNORECASE)),
    ("HACK marker", re.compile(r"\bHACK\b", re.IGNORECASE)),
    ("placeholder implementation", re.compile(r"\bplaceholder\b", re.IGNORECASE)),
    ("stub implementation", re.compile(r"\bstub\b", re.IGNORECASE)),
    ("not implemented", re.compile(r"\bnot\s+implemented\b", re.IGNORECASE)),
    ("empty return", re.compile(r"return\s*\n|return\s*$", re.MULTILINE)),
    ("pass statement", re.compile(r"^\s*pass\s*$", re.MULTILINE)),
    ("console-only implementation", re.compile(r"console\.log\(|print\(['\"]", re.IGNORECASE)),
]


def detect_anti_patterns(text: str) -> list[str]:
    """Scan response text for common anti-patterns."""
    if not text:
        return []
    found: list[str] = []
    for label, pattern in _ANTI_PATTERN_REGEXES:
        if pattern.search(text):
            found.append(label)
    return found


def derive_task_status(
    status: str,
    warnings: list[str],
    context_budget: dict[str, Any],
    anti_patterns: list[str] | None = None,
) -> str:
    """Derive a high-level task status (DONE, DONE_WITH_CONCERNS, NEEDS_CONTEXT, BLOCKED)."""
    if status in ("error",):
        return "BLOCKED"
    if context_budget.get("status") == "critical":
        return "NEEDS_CONTEXT"
    concerns = bool(warnings) or bool(anti_patterns)
    if status == "completed" and not concerns:
        return "DONE"
    if status == "completed" and concerns:
        return "DONE_WITH_CONCERNS"
    if context_budget.get("status") == "warning":
        return "NEEDS_CONTEXT"
    return "DONE_WITH_CONCERNS"


# ---------------------------------------------------------------------------
# Graduated compaction strategy
# ---------------------------------------------------------------------------


def estimate_message_tokens(message: dict[str, Any]) -> int:
    """Estimate the token count for a single message using a char-count heuristic.

    Roughly 4 characters ≈ 1 token for English text and code.
    """
    total_chars = 0
    parts = message.get("parts")
    if isinstance(parts, list):
        for part in parts:
            if not isinstance(part, dict):
                continue
            if part.get("type") == "text":
                total_chars += len(str(part.get("text", "")))
            elif part.get("type") == "tool":
                state = part.get("state") or {}
                if isinstance(state, dict):
                    total_chars += len(str(state.get("input", "")))
                    total_chars += len(str(state.get("output", "")))
    info = message.get("info")
    if isinstance(info, dict):
        system = info.get("system")
        if isinstance(system, str):
            total_chars += len(system)
    return max(total_chars // 4, 1)


def compute_context_priority(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Score each message by priority for context retention.

    Returns a list of dicts with ``index``, ``priority`` (0-10), ``tokens_est``,
    and ``category``.  Higher priority = should be retained longer.
    """
    scored: list[dict[str, Any]] = []
    total = len(messages)
    for idx, msg in enumerate(messages):
        recency = idx / max(total - 1, 1)  # 0.0 = oldest, 1.0 = newest
        info = msg.get("info") or {}
        role = str(info.get("role", "")).lower() if isinstance(info, dict) else ""
        parts = msg.get("parts") if isinstance(msg.get("parts"), list) else []

        # Base priority from role
        if role == "system":
            base = 10  # always retain system prompts
        elif role == "user":
            base = 7
        elif role == "assistant":
            base = 5
        else:
            base = 3

        # Boost for todowrite tool calls (plan state)
        has_todowrite = any(
            isinstance(p, dict) and p.get("type") == "tool" and p.get("tool") == "todowrite" for p in parts
        )
        if has_todowrite:
            base = max(base, 9)

        # Boost for error messages (important for debugging context)
        has_error = False
        for p in parts:
            if isinstance(p, dict) and p.get("type") == "tool":
                state = p.get("state") or {}
                if isinstance(state, dict) and state.get("status") == "error":
                    has_error = True
                    break
        if has_error:
            base = min(base + 2, 10)

        # Penalize large tool outputs (safe to prune)
        tokens_est = estimate_message_tokens(msg)
        if tokens_est > 2000 and role == "assistant":
            has_large_output = any(
                isinstance(p, dict)
                and p.get("type") == "tool"
                and isinstance(p.get("state"), dict)
                and len(str((p.get("state") or {}).get("output", ""))) > 8000
                for p in parts
            )
            if has_large_output:
                base = max(base - 2, 1)

        # Recency boost: recent messages get +2
        priority = base + (2.0 * recency)
        priority = min(priority, 10.0)

        # Categorize
        if role == "system":
            category = "system"
        elif has_todowrite:
            category = "plan"
        elif has_error:
            category = "error_context"
        elif tokens_est > 2000:
            category = "large_output"
        elif role == "user":
            category = "user_prompt"
        else:
            category = "reasoning"

        scored.append(
            {
                "index": idx,
                "priority": round(priority, 1),
                "tokens_est": tokens_est,
                "category": category,
            }
        )
    return scored


def recommend_compaction_strategy(budget: dict[str, Any]) -> str:
    """Return a graduated compaction strategy based on context budget.

    Returns one of: ``"none"``, ``"prune_outputs"``, ``"summarize"``, ``"aggressive"``.
    """
    usage_pct = budget.get("usage_percent", 0)
    if usage_pct <= 0:
        return "none"
    remaining_pct = 100.0 - usage_pct
    if remaining_pct > (100.0 * (1.0 - COMPACTION_PRUNE_THRESHOLD)):
        return "none"
    if remaining_pct > (100.0 * (1.0 - COMPACTION_TOKEN_THRESHOLD)):
        return "prune_outputs"
    if remaining_pct > (100.0 * (1.0 - (1.0 - COMPACTION_AGGRESSIVE_THRESHOLD))):
        return "summarize"
    return "aggressive"


def build_compaction_hints(messages: list[dict[str, Any]], strategy: str) -> str:
    """Build a hint string for the compaction/summarization prompt.

    This tells the compaction process what to preserve vs. discard.
    """
    if strategy == "none":
        return ""
    priorities = compute_context_priority(messages)
    high_priority = [p for p in priorities if p["priority"] >= 8]
    low_priority = [p for p in priorities if p["priority"] <= 4]

    hints = []
    if strategy in ("prune_outputs", "summarize", "aggressive"):
        if high_priority:
            categories = set(p["category"] for p in high_priority)
            hints.append(f"PRESERVE: {', '.join(sorted(categories))} messages (high priority)")
        if low_priority:
            total_low_tokens = sum(p["tokens_est"] for p in low_priority)
            hints.append(
                f"PRUNE CANDIDATES: {len(low_priority)} messages (~{total_low_tokens} tokens) with low priority"
            )
    if strategy == "aggressive":
        hints.append(
            "AGGRESSIVE: Condense all reasoning into brief summaries. Retain only plan state and key decisions."
        )
    return "\n".join(hints) if hints else ""


# ---------------------------------------------------------------------------
# Task type classification
# ---------------------------------------------------------------------------


def _compile_keyword_patterns(keywords: frozenset[str]) -> list[re.Pattern[str]]:
    """Compile keyword strings into word-boundary-aware regex patterns.

    Single-word keywords get ``\\b`` word boundaries to avoid substring false
    positives (e.g. "find" no longer matches inside "findings").  Multi-word
    phrases already have natural word boundaries at spaces and are matched
    literally with ``\\b`` anchors on each end.
    """
    patterns: list[re.Pattern[str]] = []
    for kw in keywords:
        # Escape any regex-special characters (e.g. "ci/cd" -> "ci\\/cd")
        escaped = re.escape(kw)
        patterns.append(re.compile(r"\b" + escaped + r"\b", re.IGNORECASE))
    return patterns


_EXPLORATION_KEYWORDS = frozenset(
    {
        "explain",
        "understand",
        "explore",
        "investigate",
        "research",
        "find",
        "search",
        "how does",
        "what is",
        "where is",
        "show me",
        "list",
        "describe",
        "analyze",
        "document",
        "map out",
        "overview",
    }
)
_DEBUGGING_KEYWORDS = frozenset(
    {
        "debug",
        "fix",
        "bug",
        "error",
        "crash",
        "fail",
        "broken",
        "issue",
        "wrong",
        "doesn't work",
        "not working",
        "traceback",
        "exception",
        "stack trace",
        "regression",
        "investigate error",
    }
)
_FEATURE_KEYWORDS = frozenset(
    {
        "implement",
        "create",
        "build",
        "add",
        "develop",
        "feature",
        "new",
        "integrate",
        "set up",
        "scaffold",
        "bootstrap",
        "design",
    }
)
_REVIEW_KEYWORDS = frozenset(
    {
        "review",
        "audit",
        "check",
        "inspect",
        "assess",
        "evaluate",
        "critique",
        "code review",
        "security review",
    }
)
_REFACTOR_KEYWORDS = frozenset(
    {
        "refactor",
        "restructure",
        "reorganize",
        "clean up",
        "simplify",
        "extract",
        "rename",
        "move",
        "decouple",
        "optimize",
    }
)
_DEPLOYMENT_KEYWORDS = frozenset(
    {
        "deploy",
        "deployment",
        "infrastructure",
        "ci/cd",
        "pipeline",
        "docker",
        "kubernetes",
        "helm",
        "terraform",
        "bicep",
        "release",
    }
)

# Pre-compiled word-boundary patterns for each category
_KEYWORD_PATTERNS: dict[str, tuple[list[re.Pattern[str]], float]] = {
    "exploration": (_compile_keyword_patterns(_EXPLORATION_KEYWORDS), 1.0),
    "debugging": (_compile_keyword_patterns(_DEBUGGING_KEYWORDS), 1.5),
    "feature": (_compile_keyword_patterns(_FEATURE_KEYWORDS), 1.0),
    "review": (_compile_keyword_patterns(_REVIEW_KEYWORDS), 1.2),
    "refactor": (_compile_keyword_patterns(_REFACTOR_KEYWORDS), 1.2),
    "deployment": (_compile_keyword_patterns(_DEPLOYMENT_KEYWORDS), 1.0),
}


def classify_task_type(prompt: str) -> str:
    """Classify the task type from a prompt string.

    Returns one of: ``exploration``, ``debugging``, ``feature``, ``edit``,
    ``review``, ``refactor``, ``deployment``, ``unknown``.

    Uses word-boundary regex matching to avoid false positives from
    substring matches (e.g. "find" no longer triggers on "findings").
    """
    # Score each category using word-boundary-aware patterns
    scores: dict[str, float] = {cat: 0.0 for cat in _KEYWORD_PATTERNS}
    for category, (patterns, weight) in _KEYWORD_PATTERNS.items():
        for pat in patterns:
            if pat.search(prompt):
                scores[category] += weight

    # Short prompts with file paths are likely edits
    has_file_paths = bool(re.search(r"[\w/]+\.\w{1,5}", prompt))
    if has_file_paths and len(prompt) < 300:
        scores["edit"] = 2.0
    else:
        scores["edit"] = 0.0

    best = max(scores, key=lambda k: scores[k])
    if scores[best] < 1.0:
        return "unknown"
    return best


# ---------------------------------------------------------------------------
# Agent selection
# ---------------------------------------------------------------------------


def select_agent_for_prompt(
    prompt: str,
    *,
    is_first_turn: bool,
    context_budget_status: str = "ok",
    has_prior_memory: bool = False,
) -> str:
    """Select the appropriate OpenCode agent based on prompt characteristics.

    When ``AGENT_SELECTION_MODE`` is ``"smart"``, uses multi-signal scoring
    including task type classification, context budget awareness, and history.
    Falls back to the simple length+markers heuristic when mode is ``"simple"``.
    """
    if not is_first_turn:
        return DEFAULT_AGENT

    if AGENT_SELECTION_MODE == "simple":
        return _select_agent_simple(prompt)

    # --- Smart selection ---
    task_type = classify_task_type(prompt)

    # Context budget awareness: avoid plan agent when budget is tight
    if context_budget_status in ("warning", "critical"):
        if task_type in ("feature", "deployment"):
            # Even complex tasks should skip planning when low on context
            return DEFAULT_AGENT
        return TASK_TYPE_AGENT_MAP.get(task_type, DEFAULT_AGENT)

    # History awareness: if resuming with memory, skip planning
    if has_prior_memory and task_type in ("feature",):
        return DEFAULT_AGENT

    # Use task type mapping
    mapped = TASK_TYPE_AGENT_MAP.get(task_type, DEFAULT_AGENT)

    # For feature tasks, also check complexity (short feature requests don't need plan)
    if mapped == "plan" and len(prompt) < PLAN_AGENT_PROMPT_THRESHOLD:
        return DEFAULT_AGENT

    return mapped


def _select_agent_simple(prompt: str) -> str:
    """Original simple agent selection: length + complexity markers."""
    if len(prompt) >= PLAN_AGENT_PROMPT_THRESHOLD and DEFAULT_AGENT == "build":
        complexity_markers = 0
        if prompt.count("\n") >= 2:
            complexity_markers += 1
        if any(marker in prompt.lower() for marker in ("step 1", "first,", "then ", "finally ", "1.", "2.", "- ")):
            complexity_markers += 1
        if len(prompt) >= 1000:
            complexity_markers += 1
        if complexity_markers >= 2:
            return "plan"
    return DEFAULT_AGENT


# ---------------------------------------------------------------------------
# Message history extraction
# ---------------------------------------------------------------------------


def get_latest_assistant_payload(
    messages: list[dict[str, Any]],
    parent_message_id: str | None = None,
) -> dict[str, Any] | None:
    """Return the latest meaningful assistant payload, optionally filtered by parent id."""
    latest_payload: dict[str, Any] | None = None
    for message in reversed(messages):
        info = message.get("info")
        if not isinstance(info, dict) or info.get("role") != "assistant":
            continue
        if parent_message_id is not None and str(info.get("parentID") or "").strip() != parent_message_id:
            continue
        payload = {
            "info": info,
            "parts": message.get("parts") if isinstance(message.get("parts"), list) else [],
        }
        if latest_payload is None:
            latest_payload = payload
        if assistant_payload_has_signal(payload):
            return payload
    return latest_payload


def extract_tool_calls_from_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Extract a summary of all tool calls from the session message history."""
    tool_calls: list[dict[str, Any]] = []
    for msg in messages:
        parts = msg.get("parts")
        if not isinstance(parts, list):
            continue
        for part in parts:
            if not isinstance(part, dict) or part.get("type") != "tool":
                continue
            state = part.get("state") or {}
            if not isinstance(state, dict):
                continue
            raw_input = state.get("input")
            raw_output = truncate_text(str(state.get("output", "")), 2000)
            # Redact secrets from both input and output before exposing to the frontend
            sanitized_input = redact_secrets(str(raw_input)) if isinstance(raw_input, str) else raw_input
            sanitized_output = redact_secrets(raw_output)
            tool_calls.append(
                {
                    "tool": str(part.get("tool", "")),
                    "status": str(state.get("status", "unknown")),
                    "input": sanitized_input,
                    "output": sanitized_output,
                }
            )
    return tool_calls



def _extract_named_items(value: list[Any], *, max_items: int = 3) -> str:
    """Return a short preview of named items from a structured tool output list."""
    names: list[str] = []
    for item in value:
        candidate = ""
        if isinstance(item, dict):
            metadata = item.get("metadata")
            if isinstance(metadata, dict):
                candidate = str(metadata.get("name") or "").strip()
            if not candidate:
                candidate = str(item.get("name") or item.get("id") or "").strip()
        elif item not in (None, ""):
            candidate = str(item).strip()
        if candidate:
            names.append(candidate)
        if len(names) >= max_items:
            break
    if not names:
        return ""
    suffix = "" if len(value) <= len(names) else ", ..."
    return ", ".join(names) + suffix


def _summarize_tool_output(value: Any, *, max_chars: int = 240) -> str:
    """Return a compact, human-readable preview for a tool output payload."""
    text = str(value or "").strip()
    if not text:
        return ""

    if text.startswith(("{", "[")):
        try:
            parsed = json.loads(text)
        except Exception:
            parsed = None
        if isinstance(parsed, list):
            preview = _extract_named_items(parsed)
            summary = f"returned {len(parsed)} item{'s' if len(parsed) != 1 else ''}"
            if preview:
                summary = f"{summary}: {preview}"
            return truncate_text(summary, max_chars)
        if isinstance(parsed, dict):
            items = parsed.get("items")
            if isinstance(items, list):
                preview = _extract_named_items(items)
                summary = f"returned {len(items)} item{'s' if len(items) != 1 else ''}"
                if preview:
                    summary = f"{summary}: {preview}"
                return truncate_text(summary, max_chars)
            keys = [str(key) for key in parsed.keys()][:5]
            if keys:
                return truncate_text(f"returned an object with keys: {', '.join(keys)}", max_chars)

    compact = re.sub(r"\s+", " ", text).strip()
    return truncate_text(compact, max_chars)


def build_tool_only_response(tool_calls: list[dict[str, Any]], *, max_tools: int = 5) -> str:
    """Build a readable fallback response when a run has tool calls but no assistant text."""
    visible_tool_calls = [call for call in tool_calls if isinstance(call, dict)]
    if not visible_tool_calls:
        return ""

    lines = [
        "The run completed tool execution but did not return a final written summary.",
        "",
        "Tool results:",
    ]

    for call in visible_tool_calls[-max_tools:]:
        tool_name = str(call.get("tool") or "tool").strip() or "tool"
        status = str(call.get("status") or "unknown").strip().lower() or "unknown"
        output_preview = _summarize_tool_output(call.get("output"))
        input_preview = _summarize_tool_output(call.get("input"), max_chars=120)

        if status == "completed":
            if output_preview:
                detail = output_preview
            elif input_preview:
                detail = f"completed with no textual output. Input: {input_preview}"
            else:
                detail = "completed with no textual output"
        else:
            detail = output_preview or input_preview or status
            if detail != status:
                detail = f"{status} - {detail}"

        lines.append(f"- {tool_name}: {detail}")

    omitted = len(visible_tool_calls) - min(len(visible_tool_calls), max_tools)
    if omitted > 0:
        lines.append(f"- ... {omitted} earlier tool call{'s' if omitted != 1 else ''} omitted.")

    return "\n".join(lines)


def detect_task_errors(messages: list[dict[str, Any]]) -> list[str]:
    """Detect tool-call errors in the session message history."""
    errors: list[str] = []
    for msg in messages:
        info = msg.get("info")
        if isinstance(info, dict):
            err = info.get("error")
            if err:
                if isinstance(err, dict):
                    payload = {"info": {"error": err}}
                    message = extract_error_message(payload)
                    errors.append(message or str(err.get("name", str(err))))
                else:
                    errors.append(str(err))
        parts = msg.get("parts")
        if not isinstance(parts, list):
            continue
        for part in parts:
            if not isinstance(part, dict) or part.get("type") != "tool":
                continue
            state = part.get("state") or {}
            if isinstance(state, dict) and state.get("status") == "error":
                tool = str(part.get("tool", "unknown"))
                reason = str(state.get("error", "unknown error"))
                errors.append(f"Tool '{tool}' failed: {reason}")
    return errors


# ---------------------------------------------------------------------------
# Artifact extraction
# ---------------------------------------------------------------------------


_ITER_ARTIFACT_MAX_DEPTH = 20


def _iter_artifact_paths(value: Any, *, _depth: int = 0) -> list[str]:
    """Recursively extract file paths from a value using the artifact pattern.

    Enforces a maximum recursion depth of ``_ITER_ARTIFACT_MAX_DEPTH`` to
    protect against pathologically nested data structures.
    """
    if _depth > _ITER_ARTIFACT_MAX_DEPTH:
        return []
    found: list[str] = []
    if isinstance(value, str):
        for match in ARTIFACT_PATH_PATTERN.finditer(value):
            candidate = str(match.group("path") or "").strip().rstrip(".,:;)")
            if candidate:
                found.append(candidate)
        return found
    if isinstance(value, dict):
        for nested in value.values():
            found.extend(_iter_artifact_paths(nested, _depth=_depth + 1))
        return found
    if isinstance(value, list):
        for nested in value:
            found.extend(_iter_artifact_paths(nested, _depth=_depth + 1))
    return found


def extract_artifacts_from_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Extract file artifacts from tool parts and patch parts."""
    artifacts: dict[str, dict[str, Any]] = {}
    for msg in messages:
        parts = msg.get("parts")
        if not isinstance(parts, list):
            continue
        for part in parts:
            if not isinstance(part, dict):
                continue
            part_type = part.get("type")
            if part_type == "tool":
                tool_name = str(part.get("tool", ""))
                state = part.get("state") or {}
                if not isinstance(state, dict):
                    continue
                if tool_name in ("write", "edit") and state.get("status") == "completed":
                    input_data = state.get("input") or {}
                    if isinstance(input_data, dict):
                        file_path = str(input_data.get("filePath", "")).strip()
                        if file_path:
                            artifacts[file_path] = {
                                "path": file_path,
                                "tool": tool_name,
                                "status": "completed",
                            }
                if state.get("status") == "completed":
                    for file_path in _iter_artifact_paths(state.get("output")) + _iter_artifact_paths(
                        state.get("input")
                    ):
                        suffix = Path(file_path).suffix.lower()
                        if suffix not in DOWNLOADABLE_ARTIFACT_EXTENSIONS:
                            continue
                        artifacts[file_path] = {
                            "path": file_path,
                            "tool": tool_name or "tool",
                            "status": "completed",
                        }
            elif part_type == "patch":
                for file_name in part.get("files") or []:
                    file_name = str(file_name).strip()
                    if file_name:
                        artifacts[file_name] = {
                            "path": file_name,
                            "tool": "patch",
                            "status": "completed",
                        }
    result = sorted(artifacts.values(), key=lambda a: a.get("path", ""))
    return result[:ARTIFACT_COLLECTION_MAX_FILES]


# ---------------------------------------------------------------------------
# Runtime capabilities
# ---------------------------------------------------------------------------


def runtime_capabilities() -> dict[str, Any]:
    """Return a capabilities descriptor for the runtime."""
    return {
        "native_tools": sorted(NATIVE_TOOL_NAMES),
        "native_tool_count": len(NATIVE_TOOL_NAMES),
        "output_formats": sorted(FORMAT_INSTRUCTIONS.keys()),
        "structured_output": {
            "supported": True,
            "json_schema": True,
            "default_retry_count": STRUCTURED_OUTPUT_RETRY_COUNT,
        },
        "autonomous_execution": {
            "supported": True,
            "default_enabled": True,
            "default_max_retries": _safe_int("OPENCODE_AUTONOMOUS_MAX_RETRIES", 3),
            "default_max_turns": _safe_int("OPENCODE_AUTONOMOUS_MAX_TURNS", 10),
        },
        "agents": {
            "available": ["build", "plan", "general", "explore"],
            "default": DEFAULT_AGENT,
            "plan_threshold_chars": PLAN_AGENT_PROMPT_THRESHOLD,
        },
        "session_management": {
            "abort": True,
            "summarize": True,
            "init": True,
            "init_on_create": SESSION_INIT_ON_CREATE,
            "todos": True,
            "compaction_threshold": COMPACTION_TOKEN_THRESHOLD,
            "durable_memory": MEMORY_ENABLED,
            "session_recovery": True,
            "handoff_resume": MEMORY_ENABLED,
        },
        "mcp_usage": {
            "available": bool(
                SKILL_RUNTIME_CONFIG.get("mcpSidecars")
                or os.getenv("OPENCODE_MCP_CONNECTIONS_JSON", "").strip()
                or os.getenv("MCP_SERVERS", "").strip()
            ),
            "preferred_mode": "native-tools-first",
        },
        "a2a": {
            "outbound_supported": True,
            "transport": "a2a-jsonrpc",
            "gateway_configured": bool(API_GATEWAY_INTERNAL_URL and API_GATEWAY_SHARED_TOKEN),
            "allowed_target_count": len(A2A_ALLOWED_TARGETS),
            "allowed_targets": [
                {"namespace": namespace, "name": name}
                for namespace, name in sorted(A2A_ALLOWED_TARGETS)
            ],
            "max_timeout_seconds": A2A_MAX_TIMEOUT_SECONDS,
            "requires_hitl": A2A_REQUIRE_HITL,
        },
    }
