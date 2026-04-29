"""Pydantic models for the pi RPC protocol.

All command, event, and response types used in pi's JSON-over-stdin/stdout
RPC mode. See packages/coding-agent/docs/rpc.md for the protocol spec.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# RPC Commands (stdin → pi)
# ---------------------------------------------------------------------------


class PiPromptCommand(BaseModel):
    """Send a user prompt to the agent."""

    type: Literal["prompt"] = "prompt"
    message: str = Field(..., description="The prompt text")
    images: list[dict[str, Any]] | None = Field(
        None, description="Optional image attachments"
    )
    streaming_behavior: Literal["steer", "follow_up"] | None = Field(
        None, alias="streamingBehavior", description="Queue mode when agent is streaming"
    )
    id: str | None = Field(None, description="Optional correlation ID")


class PiSteerCommand(BaseModel):
    """Queue a steering message during agent execution."""

    type: Literal["steer"] = "steer"
    message: str = Field(..., description="The steering message")
    images: list[dict[str, Any]] | None = None
    id: str | None = None


class PiFollowUpCommand(BaseModel):
    """Queue a follow-up message after agent finishes."""

    type: Literal["follow_up"] = "follow_up"
    message: str = Field(..., description="The follow-up message")
    images: list[dict[str, Any]] | None = None
    id: str | None = None


class PiAbortCommand(BaseModel):
    """Abort the current agent operation."""

    type: Literal["abort"] = "abort"
    id: str | None = None


class PiSetModelCommand(BaseModel):
    """Switch to a specific model."""

    type: Literal["set_model"] = "set_model"
    provider: str = Field(..., description="Provider name (anthropic, openai, etc.)")
    model_id: str = Field(..., alias="modelId", description="Model ID")
    id: str | None = None


class PiSetThinkingLevelCommand(BaseModel):
    """Set the reasoning level."""

    type: Literal["set_thinking_level"] = "set_thinking_level"
    level: Literal["off", "minimal", "low", "medium", "high", "xhigh"] = Field(
        ..., alias="level"
    )
    id: str | None = None


class PiGetStateCommand(BaseModel):
    """Get current session state."""

    type: Literal["get_state"] = "get_state"
    id: str | None = None


class PiGetMessagesCommand(BaseModel):
    """Get all messages in the conversation."""

    type: Literal["get_messages"] = "get_messages"
    id: str | None = None


class PiBashCommand(BaseModel):
    """Execute a shell command and add output to context."""

    type: Literal["bash"] = "bash"
    command: str = Field(..., description="Shell command to execute")
    id: str | None = None


class PiCompactCommand(BaseModel):
    """Manually compact conversation context."""

    type: Literal["compact"] = "compact"
    custom_instructions: str | None = Field(
        None, alias="customInstructions", description="Custom compaction instructions"
    )
    id: str | None = None


class PiNewSessionCommand(BaseModel):
    """Start a fresh session."""

    type: Literal["new_session"] = "new_session"
    parent_session: str | None = Field(
        None, alias="parentSession", description="Parent session file path"
    )
    id: str | None = None


class PiSwitchSessionCommand(BaseModel):
    """Load a different session file."""

    type: Literal["switch_session"] = "switch_session"
    session_path: str = Field(
        ..., alias="sessionPath", description="Path to session JSONL file"
    )
    id: str | None = None


class PiForkCommand(BaseModel):
    """Create a new fork from a previous user message."""

    type: Literal["fork"] = "fork"
    entry_id: str = Field(
        ..., alias="entryId", description="Entry ID to fork from"
    )
    id: str | None = None


class PiGetCommandsCommand(BaseModel):
    """List available skills/templates/commands."""

    type: Literal["get_commands"] = "get_commands"
    id: str | None = None


class PiSetSessionNameCommand(BaseModel):
    """Set a display name for the session."""

    type: Literal["set_session_name"] = "set_session_name"
    name: str = Field(..., alias="name", description="Session display name")
    id: str | None = None


class PiAbortRetryCommand(BaseModel):
    """Abort an in-progress retry."""

    type: Literal["abort_retry"] = "abort_retry"
    id: str | None = None


# Union of all commands
PiRpcCommand = (
    PiPromptCommand
    | PiSteerCommand
    | PiFollowUpCommand
    | PiAbortCommand
    | PiSetModelCommand
    | PiSetThinkingLevelCommand
    | PiGetStateCommand
    | PiGetMessagesCommand
    | PiBashCommand
    | PiCompactCommand
    | PiNewSessionCommand
    | PiSwitchSessionCommand
    | PiForkCommand
    | PiGetCommandsCommand
    | PiSetSessionNameCommand
    | PiAbortRetryCommand
)


# ---------------------------------------------------------------------------
# RPC Response (stdout ← pi)
# ---------------------------------------------------------------------------


class PiResponse(BaseModel):
    """Response to a command."""

    type: Literal["response"] = "response"
    command: str = Field(..., description="Command that was executed")
    success: bool = Field(..., description="Whether the command succeeded")
    error: str | None = Field(None, description="Error message if failed")
    data: dict[str, Any] | None = Field(None, description="Response data")
    id: str | None = Field(None, description="Correlation ID from the command")


# ---------------------------------------------------------------------------
# RPC Events (stdout ← pi)
# ---------------------------------------------------------------------------


class PiAgentStartEvent(BaseModel):
    type: Literal["agent_start"] = "agent_start"


class PiAgentEndEvent(BaseModel):
    type: Literal["agent_end"] = "agent_end"
    messages: list[dict[str, Any]] = Field(default_factory=list)


class PiTurnStartEvent(BaseModel):
    type: Literal["turn_start"] = "turn_start"
    turnIndex: int | None = None


class PiTurnEndEvent(BaseModel):
    type: Literal["turn_end"] = "turn_end"
    message: dict[str, Any] | None = None
    toolResults: list[dict[str, Any]] | None = None


class PiMessageStartEvent(BaseModel):
    type: Literal["message_start"] = "message_start"
    message: dict[str, Any] = Field(...)


class PiMessageUpdateEvent(BaseModel):
    type: Literal["message_update"] = "message_update"
    message: dict[str, Any] = Field(...)
    assistantMessageEvent: dict[str, Any] = Field(...)


class PiMessageEndEvent(BaseModel):
    type: Literal["message_end"] = "message_end"
    message: dict[str, Any] = Field(...)


class PiToolExecStartEvent(BaseModel):
    type: Literal["tool_execution_start"] = "tool_execution_start"
    toolCallId: str = Field(...)
    toolName: str = Field(...)
    args: dict[str, Any] = Field(default_factory=dict)


class PiToolExecUpdateEvent(BaseModel):
    type: Literal["tool_execution_update"] = "tool_execution_update"
    toolCallId: str = Field(...)
    toolName: str = Field(...)
    args: dict[str, Any] = Field(default_factory=dict)
    partialResult: dict[str, Any] | None = None


class PiToolExecEndEvent(BaseModel):
    type: Literal["tool_execution_end"] = "tool_execution_end"
    toolCallId: str = Field(...)
    toolName: str = Field(...)
    result: dict[str, Any] | None = None
    isError: bool = False


class PiQueueUpdateEvent(BaseModel):
    type: Literal["queue_update"] = "queue_update"
    steering: list[str] = Field(default_factory=list)
    followUp: list[str] = Field(default_factory=list)


class PiCompactionStartEvent(BaseModel):
    type: Literal["compaction_start"] = "compaction_start"
    reason: str = "manual"


class PiCompactionEndEvent(BaseModel):
    type: Literal["compaction_end"] = "compaction_end"
    reason: str = "manual"
    result: dict[str, Any] | None = None
    aborted: bool = False
    willRetry: bool = False


class PiAutoRetryStartEvent(BaseModel):
    type: Literal["auto_retry_start"] = "auto_retry_start"
    attempt: int = 1
    maxAttempts: int = 3
    delayMs: int = 0
    errorMessage: str = ""


class PiAutoRetryEndEvent(BaseModel):
    type: Literal["auto_retry_end"] = "auto_retry_end"
    success: bool = False
    attempt: int = 0


class PiExtensionErrorEvent(BaseModel):
    type: Literal["extension_error"] = "extension_error"
    extensionPath: str = ""
    event: str = ""
    error: str = ""


# Union of all events
PiRpcEvent = (
    PiAgentStartEvent
    | PiAgentEndEvent
    | PiTurnStartEvent
    | PiTurnEndEvent
    | PiMessageStartEvent
    | PiMessageUpdateEvent
    | PiMessageEndEvent
    | PiToolExecStartEvent
    | PiToolExecUpdateEvent
    | PiToolExecEndEvent
    | PiQueueUpdateEvent
    | PiCompactionStartEvent
    | PiCompactionEndEvent
    | PiAutoRetryStartEvent
    | PiAutoRetryEndEvent
    | PiExtensionErrorEvent
)


# Event type to model mapping for fast dispatch
EVENT_TYPE_MAP: dict[str, type[PiRpcEvent]] = {
    "agent_start": PiAgentStartEvent,
    "agent_end": PiAgentEndEvent,
    "turn_start": PiTurnStartEvent,
    "turn_end": PiTurnEndEvent,
    "message_start": PiMessageStartEvent,
    "message_update": PiMessageUpdateEvent,
    "message_end": PiMessageEndEvent,
    "tool_execution_start": PiToolExecStartEvent,
    "tool_execution_update": PiToolExecUpdateEvent,
    "tool_execution_end": PiToolExecEndEvent,
    "queue_update": PiQueueUpdateEvent,
    "compaction_start": PiCompactionStartEvent,
    "compaction_end": PiCompactionEndEvent,
    "auto_retry_start": PiAutoRetryStartEvent,
    "auto_retry_end": PiAutoRetryEndEvent,
    "extension_error": PiExtensionErrorEvent,
}
