"""Pydantic request and response models for the OpenCode runtime API."""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field, model_validator

from config import (
    MAX_MODEL_CHARS,
    MAX_PROMPT_CHARS,
    MAX_SYSTEM_PROMPT_CHARS,
    MAX_TEAM_CONTEXT_CHARS,
    MAX_THREAD_ID_CHARS,
)
from prompts import FORMAT_INSTRUCTIONS
from utils import normalize_identifier


class InvokeRequest(BaseModel):
    prompt: str = Field(default="", max_length=MAX_PROMPT_CHARS)
    thread_id: str | None = Field(default=None, max_length=MAX_THREAD_ID_CHARS)
    model: str | None = Field(default=None, max_length=MAX_MODEL_CHARS)
    system: str | None = Field(default=None, max_length=MAX_SYSTEM_PROMPT_CHARS)
    require_approval: bool = False
    approval_action: str | None = Field(default=None, max_length=512)
    tool_name: str = Field(default="", max_length=128)
    tool_args: dict[str, Any] = Field(default_factory=dict)
    sandbox_session: dict[str, Any] | None = None
    mcp_server: str | None = Field(default=None, max_length=128)
    a2a_target_agent: str | None = Field(default=None, max_length=63)
    a2a_target_namespace: str | None = Field(default=None, max_length=63)
    a2a_timeout_seconds: float | None = Field(default=None, ge=1.0)
    caller_agent_name: str | None = Field(default=None, max_length=63)
    caller_agent_namespace: str | None = Field(default=None, max_length=63)
    parent_thread_id: str | None = Field(default=None, max_length=MAX_THREAD_ID_CHARS)
    caller_request_id: str | None = Field(default=None, max_length=128)
    team_context: dict[str, Any] | None = None
    debug: bool = False
    no_session: bool = False
    max_turns: int | None = Field(default=None, ge=1, le=1000)
    working_directory: str | None = Field(default=None, max_length=512)
    output_format: str | None = Field(default=None, max_length=32)
    output_schema: dict[str, Any] | None = None
    structured_output_retry_count: int | None = Field(default=None)
    max_retries: int | None = Field(default=None)
    autonomous: bool = True
    pre_authorized_actions: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_request(self) -> "InvokeRequest":
        self.prompt = self.prompt.strip()
        self.thread_id = self.thread_id.strip() or None if self.thread_id is not None else None
        self.model = self.model.strip() or None if self.model is not None else None
        self.system = self.system.strip() or None if self.system is not None else None
        self.approval_action = self.approval_action.strip() or None if self.approval_action is not None else None
        self.tool_name = self.tool_name.strip()
        self.mcp_server = self.mcp_server.strip() or None if self.mcp_server is not None else None
        self.a2a_target_agent = self.a2a_target_agent.strip() or None if self.a2a_target_agent is not None else None
        self.a2a_target_namespace = (
            self.a2a_target_namespace.strip() or None if self.a2a_target_namespace is not None else None
        )
        self.caller_agent_name = self.caller_agent_name.strip() or None if self.caller_agent_name is not None else None
        self.caller_agent_namespace = (
            self.caller_agent_namespace.strip() or None if self.caller_agent_namespace is not None else None
        )
        self.parent_thread_id = self.parent_thread_id.strip() or None if self.parent_thread_id is not None else None
        self.caller_request_id = self.caller_request_id.strip() or None if self.caller_request_id is not None else None
        self.output_format = self.output_format.strip().lower() or None if self.output_format is not None else None
        if self.output_schema is not None and not isinstance(self.output_schema, dict):
            raise ValueError("output_schema must be a JSON object when provided")
        if self.output_schema is not None and self.output_format is None:
            self.output_format = "json"

        if not self.prompt:
            raise ValueError("prompt must not be blank")
        if self.tool_name:
            raise ValueError("opencode runtime does not support direct tool_name execution")
        if self.mcp_server:
            raise ValueError("opencode runtime does not support gateway-routed mcp_server execution")
        if self.sandbox_session is not None:
            raise ValueError("opencode runtime does not support sandbox_session continuity")
        if self.a2a_target_agent or self.a2a_target_namespace:
            if not self.a2a_target_agent or not self.a2a_target_namespace:
                raise ValueError("a2a_target_agent and a2a_target_namespace must be provided together")
            normalize_identifier(self.a2a_target_agent, source="a2a_target_agent")
            normalize_identifier(self.a2a_target_namespace, source="a2a_target_namespace")
        elif self.a2a_timeout_seconds is not None:
            raise ValueError("a2a_timeout_seconds requires both a2a_target_agent and a2a_target_namespace")
        if self.caller_agent_name or self.caller_agent_namespace:
            if not self.caller_agent_name or not self.caller_agent_namespace:
                raise ValueError("caller_agent_name and caller_agent_namespace must be provided together")
            normalize_identifier(self.caller_agent_name, source="caller_agent_name")
            normalize_identifier(self.caller_agent_namespace, source="caller_agent_namespace")
        if self.no_session and self.thread_id:
            raise ValueError("thread_id cannot be used when no_session is enabled")
        if self.team_context is not None:
            encoded = json.dumps(self.team_context, ensure_ascii=False, sort_keys=True)
            if len(encoded) > MAX_TEAM_CONTEXT_CHARS:
                raise ValueError(f"team_context exceeds {MAX_TEAM_CONTEXT_CHARS} characters")
        if self.output_format and self.output_format not in FORMAT_INSTRUCTIONS:
            raise ValueError(f"output_format must be one of: {', '.join(sorted(FORMAT_INSTRUCTIONS))}")
        return self


class InvokeResponse(BaseModel):
    thread_id: str
    response: str
    model: str
    status: str = "completed"
    approval_name: str | None = None
    retry_after_seconds: int | None = None
    a2a: dict[str, Any] | None = None
    warnings: list[str] = Field(default_factory=list)
    artifacts: list[dict[str, Any]] = Field(default_factory=list)
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    continuity: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None
