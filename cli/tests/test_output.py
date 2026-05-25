"""Tests for cp1252-safe CLI output helpers and streaming commands."""

from __future__ import annotations

import io
import json
from contextlib import nullcontext
from typing import Any

import typer
from rich import box
from rich.console import Console

from agentctl.commands import register_all
from agentctl import output
from agentctl.client import ApiClient
from agentctl.commands import agents, chat
from agentctl.config import ResolvedSettings
from typer.testing import CliRunner


class _StreamClient:
    def __init__(self, events: list[dict[str, str]]) -> None:
        self._events = events
        self.calls: list[tuple[str, str, dict[str, Any] | None, dict[str, Any] | None]] = []

    def __enter__(self) -> _StreamClient:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def stream(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        payload: dict[str, Any] | None = None,
    ):
        self.calls.append((method, path, params, payload))
        response = type("_Response", (), {"is_success": True, "status_code": 200, "reason_phrase": "OK"})()
        return nullcontext(response)

    def iter_sse(self, _response: object):
        yield from self._events


def _settings() -> ResolvedSettings:
    return ResolvedSettings(
        gateway_url="http://test-gateway:8080",
        token="test-token",
        namespace="test-ns",
        timeout=10.0,
        output_format="table",
    )


def _cp1252_console() -> tuple[Console, io.TextIOWrapper, io.BytesIO]:
    buffer = io.BytesIO()
    stream = io.TextIOWrapper(buffer, encoding="cp1252", errors="strict", newline="")
    console = Console(file=stream, force_terminal=False, color_system=None, width=120)
    return console, stream, buffer


def test_ascii_fallback_helpers(monkeypatch) -> None:
    monkeypatch.setattr(output, "supports_unicode_output", lambda stream=None: False)

    assert output.inline_separator() == "|"
    assert output.prompt_prefix("you") == "| you>"
    assert output.stop_marker() == "`"
    assert output.error_marker() == "x"
    assert output.preferred_box() == box.ASCII


def test_print_stream_text_backslash_escapes_cp1252_unsafe_characters(monkeypatch) -> None:
    cp_console, stream, buffer = _cp1252_console()
    monkeypatch.setattr(output, "console", cp_console)

    output.print_stream_text("emoji 😀", end="")
    stream.flush()

    assert buffer.getvalue().decode("cp1252") == r"emoji \U0001f600"


def test_success_preserves_markup_and_sanitizes_cp1252(monkeypatch) -> None:
    cp_console, stream, buffer = _cp1252_console()
    monkeypatch.setattr(output, "console", cp_console)

    output.success("Logged in as [bold]admin[/bold] 😀")
    stream.flush()

    rendered = buffer.getvalue().decode("cp1252")
    assert "[bold]" not in rendered
    assert "Logged in as admin" in rendered
    assert r"\U0001f600" in rendered


def test_agents_invoke_stream_uses_ascii_boxes_and_safe_text(monkeypatch) -> None:
    cp_console, stream, buffer = _cp1252_console()
    fake_client = _StreamClient(
        [
            {"event": "response.delta", "data": json.dumps({"delta": "hello 😀"})},
            {
                "event": "response.completed",
                "data": json.dumps(
                    {
                        "agent_name": "demo-agent",
                        "status": "completed",
                        "model": "gpt-5-mini",
                        "thread_id": "thread-1",
                        "response": "done",
                    }
                ),
            },
        ]
    )

    monkeypatch.setattr(output, "console", cp_console)
    monkeypatch.setattr(agents, "console", cp_console)
    monkeypatch.setattr(agents, "get_settings", _settings)
    monkeypatch.setattr(agents, "_api", lambda: fake_client)
    monkeypatch.setattr(ApiClient, "_raise_for_status", staticmethod(lambda _response: None))

    agents.agents_invoke(
        agent_name="demo-agent",
        prompt_parts=["hello"],
        stream=True,
        prompt_file=None,
        thread_id=None,
        system=None,
        require_approval=False,
        no_session=False,
        max_turns=None,
        debug=False,
    )
    stream.flush()

    rendered = buffer.getvalue().decode("cp1252")
    assert fake_client.calls == [
        (
            "POST",
            "/api/agents/demo-agent/invoke/stream",
            {"namespace": "test-ns"},
            {"prompt": "hello"},
        )
    ]
    assert "demo-agent | test-ns" in rendered
    assert r"hello \U0001f600" in rendered
    assert "│" not in rendered


def test_chat_send_stream_uses_ascii_boxes_and_safe_text(monkeypatch) -> None:
    cp_console, stream, buffer = _cp1252_console()
    fake_client = _StreamClient(
        [
            {"event": "chat.delta", "data": json.dumps({"delta": "reply 😀"})},
            {"event": "chat.completed", "data": json.dumps({"thread_id": "thread-1"})},
        ]
    )

    monkeypatch.setattr(output, "console", cp_console)
    monkeypatch.setattr(chat, "console", cp_console)
    monkeypatch.setattr(chat, "get_settings", _settings)
    monkeypatch.setattr(chat, "_api", lambda: fake_client)
    monkeypatch.setattr(ApiClient, "_raise_for_status", staticmethod(lambda _response: None))

    chat.chat_send(agent_name="demo-agent", message=["hello"], thread_id=None, stream=True)
    stream.flush()

    rendered = buffer.getvalue().decode("cp1252")
    assert fake_client.calls == [
        (
            "POST",
            "/api/agents/demo-agent/invoke/stream",
            {"namespace": "test-ns"},
            {"prompt": "hello"},
        )
    ]
    assert "demo-agent" in rendered
    assert r"reply \U0001f600" in rendered
    assert "│" not in rendered


def test_top_level_invoke_passes_plain_defaults(monkeypatch) -> None:
    captured: dict[str, Any] = {}

    def _invoke(**kwargs: Any) -> None:
        captured.update(kwargs)

    monkeypatch.setattr("agentctl.commands.agents.agents_invoke", _invoke)

    app = typer.Typer()
    register_all(app)
    result = CliRunner().invoke(app, ["invoke", "demo-agent", "hello", "world"])

    assert result.exit_code == 0
    assert captured == {
        "agent_name": "demo-agent",
        "prompt_parts": ["hello", "world"],
        "stream": False,
        "prompt_file": None,
        "thread_id": None,
        "system": None,
        "require_approval": False,
        "no_session": False,
        "max_turns": None,
        "debug": False,
    }


def test_agents_live_events_uses_notifications_stream_and_filters_agent(monkeypatch) -> None:
    cp_console, stream, buffer = _cp1252_console()
    fake_client = _StreamClient(
        [
            {
                "event": "agent.status_changed",
                "data": json.dumps({"name": "demo-agent", "phase": "running", "previousPhase": "pending"}),
            },
            {
                "event": "workflow.completed",
                "data": json.dumps({"name": "demo-workflow", "phase": "succeeded", "agent_name": "demo-agent"}),
            },
            {
                "event": "agent.status_changed",
                "data": json.dumps({"name": "other-agent", "phase": "failed"}),
            },
            {
                "event": "system.error",
                "data": json.dumps({"message": "boom 😀"}),
            },
        ]
    )

    monkeypatch.setattr(output, "console", cp_console)
    monkeypatch.setattr(agents, "console", cp_console)
    monkeypatch.setattr(agents, "get_settings", _settings)
    monkeypatch.setattr(agents, "_api", lambda: fake_client)
    monkeypatch.setattr(ApiClient, "_raise_for_status", staticmethod(lambda _response: None))

    agents.agents_live_events(agent_name="demo-agent")
    stream.flush()

    rendered = buffer.getvalue().decode("cp1252")
    assert fake_client.calls == [
        (
            "GET",
            "/api/v1/notifications/stream",
            {"namespace": "test-ns"},
            None,
        )
    ]
    assert "agent.status_changed" in rendered
    assert "workflow.completed" in rendered
    assert "other-agent" not in rendered
    assert r"boom \U0001f600" in rendered
