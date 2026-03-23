from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

from pydantic import BaseModel, ConfigDict, Field, computed_field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _stringify_content(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts = [_stringify_content(item) for item in value]
        return " ".join(part for part in parts if part).strip()
    if isinstance(value, dict):
        if "text" in value:
            return _stringify_content(value.get("text"))
        if "content" in value:
            return _stringify_content(value.get("content"))
    return str(value).strip()


def _message_role(message: Any) -> str:
    explicit_role = getattr(message, "role", None)
    if isinstance(explicit_role, str) and explicit_role.strip():
        return explicit_role.strip().lower()
    type_name = type(message).__name__.lower()
    if "human" in type_name or "user" in type_name:
        return "user"
    if "system" in type_name:
        return "system"
    if "tool" in type_name:
        return "tool"
    return "assistant"


class TokenUsageSnapshot(BaseModel):
    model_config = ConfigDict(extra="ignore")

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | None) -> "TokenUsageSnapshot":
        if value is None:
            return cls()
        prompt_tokens = int(value.get("prompt_tokens", 0) or 0)
        completion_tokens = int(value.get("completion_tokens", 0) or 0)
        total_tokens = int(value.get("total_tokens", prompt_tokens + completion_tokens) or 0)
        return cls(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            cost_usd=float(value.get("cost_usd", 0.0) or 0.0),
        )


class SessionMessageSnapshot(BaseModel):
    model_config = ConfigDict(extra="ignore")

    role: str
    content: str = ""
    created_at: datetime = Field(default_factory=utc_now)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ToolResultSnapshot(BaseModel):
    model_config = ConfigDict(extra="ignore")

    tool_name: str
    status: str = "completed"
    summary: str = ""
    created_at: datetime = Field(default_factory=utc_now)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ScratchpadEntry(BaseModel):
    model_config = ConfigDict(extra="ignore")

    note: str
    created_at: datetime = Field(default_factory=utc_now)


class SessionStateSnapshot(BaseModel):
    model_config = ConfigDict(extra="ignore")

    session_id: str
    thread_id: str
    status: str = "active"
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    expires_at: datetime | None = None
    current_messages: list[SessionMessageSnapshot] = Field(default_factory=list)
    tool_results: list[ToolResultSnapshot] = Field(default_factory=list)
    scratchpad: list[ScratchpadEntry] = Field(default_factory=list)
    token_usage: TokenUsageSnapshot = Field(default_factory=TokenUsageSnapshot)
    max_token_budget: int = 0
    reserved_tokens: int = 0
    metadata: dict[str, Any] = Field(default_factory=dict)

    @computed_field
    @property
    def message_count(self) -> int:
        return len(self.current_messages)

    @computed_field
    @property
    def remaining_token_budget(self) -> int | None:
        if self.max_token_budget <= 0:
            return None
        return max(self.max_token_budget - self.reserved_tokens - self.token_usage.total_tokens, 0)


def _build_message_snapshots(messages: list[Any], *, max_messages: int) -> list[SessionMessageSnapshot]:
    selected = messages[-max_messages:] if max_messages > 0 else messages
    snapshots: list[SessionMessageSnapshot] = []
    for message in selected:
        snapshots.append(
            SessionMessageSnapshot(
                role=_message_role(message),
                content=_stringify_content(getattr(message, "content", message)),
            )
        )
    return snapshots


def _build_tool_result_snapshots(agent_state: Mapping[str, Any], *, max_tool_results: int) -> list[ToolResultSnapshot]:
    records = agent_state.get("tool_call_records") or []
    snapshots: list[ToolResultSnapshot] = []
    if isinstance(records, list) and records:
        for item in records[-max_tool_results:]:
            if not isinstance(item, Mapping):
                continue
            snapshots.append(
                ToolResultSnapshot(
                    tool_name=str(item.get("tool_name") or item.get("toolName") or "unknown").strip() or "unknown",
                    status=str(item.get("status") or "completed").strip() or "completed",
                    summary=_stringify_content(item.get("summary") or item.get("result") or item.get("content")),
                    metadata={
                        "tool_args": item.get("tool_args") or item.get("toolArgs"),
                        "node": item.get("tool_node") or item.get("toolNode"),
                    },
                )
            )
    elif agent_state.get("tool_name"):
        snapshots.append(
            ToolResultSnapshot(
                tool_name=str(agent_state.get("tool_name") or "unknown").strip() or "unknown",
                status=str(agent_state.get("invoke_status") or "completed").strip() or "completed",
                summary=_stringify_content(agent_state.get("tool_result")),
                metadata={"tool_args": agent_state.get("tool_args")},
            )
        )
    return snapshots


def _build_scratchpad_entries(agent_state: Mapping[str, Any]) -> list[ScratchpadEntry]:
    scratchpad = agent_state.get("scratchpad") or []
    if not isinstance(scratchpad, list):
        return []
    entries: list[ScratchpadEntry] = []
    for item in scratchpad:
        text = _stringify_content(item)
        if not text:
            continue
        entries.append(ScratchpadEntry(note=text))
    return entries


def build_session_state_snapshot(
    agent_state: Mapping[str, Any],
    *,
    session_id: str | None = None,
    ttl_seconds: int = 0,
    max_token_budget: int = 0,
    reserved_tokens: int = 0,
    max_messages: int = 24,
    max_tool_results: int = 12,
) -> SessionStateSnapshot:
    now = utc_now()
    thread_id = str(agent_state.get("thread_id") or session_id or "").strip()
    resolved_session_id = str(session_id or thread_id).strip()
    expires_at = now + timedelta(seconds=ttl_seconds) if ttl_seconds > 0 else None
    messages = agent_state.get("messages") or []
    message_list = messages if isinstance(messages, list) else []
    metadata = {
        "selected_model": agent_state.get("selected_model"),
        "policy_name": agent_state.get("policy_name"),
        "step_count": int(agent_state.get("step_count") or 0),
        "max_steps": int(agent_state.get("max_steps") or 0),
        "workspace_scanned": bool(agent_state.get("workspace_scanned", False)),
        "autonomy_enabled": bool(agent_state.get("autonomy_enabled", False)),
        "stop_reason": str(agent_state.get("stop_reason") or "").strip() or None,
    }

    return SessionStateSnapshot(
        session_id=resolved_session_id,
        thread_id=thread_id or resolved_session_id,
        status=str(agent_state.get("invoke_status") or "active").strip() or "active",
        created_at=now,
        updated_at=now,
        expires_at=expires_at,
        current_messages=_build_message_snapshots(message_list, max_messages=max_messages),
        tool_results=_build_tool_result_snapshots(agent_state, max_tool_results=max_tool_results),
        scratchpad=_build_scratchpad_entries(agent_state),
        token_usage=TokenUsageSnapshot.from_mapping(agent_state.get("token_usage") if isinstance(agent_state, Mapping) else None),
        max_token_budget=max(0, int(max_token_budget or 0)),
        reserved_tokens=max(0, int(reserved_tokens or 0)),
        metadata={key: value for key, value in metadata.items() if value is not None},
    )