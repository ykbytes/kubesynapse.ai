"""Response analysis, context budget, error classification, and artifact extraction."""
from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from config import (
    ARTIFACT_COLLECTION_MAX_FILES,
    ARTIFACT_PATH_PATTERN,
    COMPACTION_TOKEN_THRESHOLD,
    DEFAULT_AGENT,
    DOWNLOADABLE_ARTIFACT_EXTENSIONS,
    MODEL_CONTEXT_LIMIT,
    NATIVE_TOOL_NAMES,
    PLAN_AGENT_PROMPT_THRESHOLD,
    SESSION_INIT_ON_CREATE,
    STRUCTURED_OUTPUT_RETRY_COUNT,
)
from prompts import FORMAT_INSTRUCTIONS
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
            "retryCount": request.structured_output_retry_count if request.structured_output_retry_count is not None else STRUCTURED_OUTPUT_RETRY_COUNT,
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
# Agent selection
# ---------------------------------------------------------------------------

def select_agent_for_prompt(prompt: str, *, is_first_turn: bool) -> str:
    """Select the appropriate OpenCode agent based on prompt characteristics."""
    if not is_first_turn:
        return DEFAULT_AGENT
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

def get_latest_assistant_payload(messages: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Return the most recent assistant message payload from a message list."""
    for message in reversed(messages):
        info = message.get("info")
        if isinstance(info, dict) and info.get("role") == "assistant":
            return {
                "info": info,
                "parts": message.get("parts") if isinstance(message.get("parts"), list) else [],
            }
    return None


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
            tool_calls.append({
                "tool": str(part.get("tool", "")),
                "status": str(state.get("status", "unknown")),
                "input": state.get("input"),
                "output": truncate_text(str(state.get("output", "")), 2000),
            })
    return tool_calls


def detect_task_errors(messages: list[dict[str, Any]]) -> list[str]:
    """Detect tool-call errors in the session message history."""
    errors: list[str] = []
    for msg in messages:
        info = msg.get("info")
        if isinstance(info, dict):
            err = info.get("error")
            if err:
                if isinstance(err, dict):
                    errors.append(str(err.get("message", err.get("name", str(err)))))
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

def _iter_artifact_paths(value: Any) -> list[str]:
    """Recursively extract file paths from a value using the artifact pattern."""
    found: list[str] = []
    if isinstance(value, str):
        for match in ARTIFACT_PATH_PATTERN.finditer(value):
            candidate = str(match.group("path") or "").strip().rstrip(".,:;)")
            if candidate:
                found.append(candidate)
        return found
    if isinstance(value, dict):
        for nested in value.values():
            found.extend(_iter_artifact_paths(nested))
        return found
    if isinstance(value, list):
        for nested in value:
            found.extend(_iter_artifact_paths(nested))
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
                    for file_path in _iter_artifact_paths(state.get("output")) + _iter_artifact_paths(state.get("input")):
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
    from skills import SKILL_RUNTIME_CONFIG

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
            "default_max_retries": int(os.getenv("OPENCODE_AUTONOMOUS_MAX_RETRIES", "3")),
            "default_max_turns": int(os.getenv("OPENCODE_AUTONOMOUS_MAX_TURNS", "10")),
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
        },
        "mcp_usage": {
            "available": bool(SKILL_RUNTIME_CONFIG.get("mcpSidecars") or os.getenv("MCP_SERVERS", "").strip()),
            "preferred_mode": "native-tools-first",
        },
    }
