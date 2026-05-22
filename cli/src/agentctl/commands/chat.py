"""Chat commands — interactive agent sessions."""

from __future__ import annotations

import json
import sys
from typing import Any

import typer
from rich import box
from rich.markdown import Markdown
from rich.panel import Panel
from rich.text import Text

from agentctl.app import get_settings
from agentctl.client import ApiClient, ApiError
from agentctl.output import (
    console,
    fatal,
    print_json_output,
    print_table,
)

chat_app = typer.Typer(
    no_args_is_help=True,
    rich_markup_mode="rich",
    epilog=(
        "[bold]Examples:[/bold]\n"
        "  agentctl chat send my-agent \"Hello!\"\n"
        "  agentctl chat interactive my-agent\n"
        "  agentctl chat threads\n"
        "  agentctl chat history thread-abc"
    ),
)


def _api() -> ApiClient:
    return ApiClient(get_settings())


def _ns_params() -> dict[str, Any]:
    return {"namespace": get_settings().namespace}


@chat_app.command("send")
def chat_send(
    agent_name: str = typer.Argument(..., help="Agent name."),
    message: list[str] | None = typer.Argument(None, help="Message text."),
    thread_id: str | None = typer.Option(None, "--thread", "-t", help="Thread ID for conversation continuity."),
    stream: bool = typer.Option(True, "--stream/--no-stream", help="Stream response."),
) -> None:
    """Send a message to an agent chat session."""
    settings = get_settings()

    # Resolve message
    if message:
        text = " ".join(message).strip()
    elif not sys.stdin.isatty():
        text = sys.stdin.read().strip()
    else:
        text = typer.prompt("Message").strip()

    if not text:
        fatal("Message must not be empty.")

    payload: dict[str, Any] = {"message": text}
    if thread_id:
        payload["thread_id"] = thread_id

    if stream:
        try:
            with _api() as client:
                with client.stream(
                    "POST",
                    f"/api/chat/{agent_name}/send",
                    params=_ns_params(),
                    payload=payload,
                ) as response:
                    from agentctl.client import ApiClient as _AC

                    _AC._raise_for_status(response)

                    console.print(
                        Panel(
                            f"[bold]{agent_name}[/bold]",
                            title="[header]Chat[/header]",
                            border_style="bright_cyan",
                            box=box.ROUNDED,
                            expand=False,
                        )
                    )

                    collected = ""
                    for sse in client.iter_sse(response):
                        event = sse["event"]
                        data_str = sse["data"]
                        if event in ("chat.delta", "response.delta"):
                            event_data = json.loads(data_str) if data_str else {}
                            delta = str(event_data.get("delta", ""))
                            if delta:
                                console.print(delta, end="")
                                collected += delta
                        elif event in ("chat.completed", "response.completed"):
                            break
                        elif event in ("chat.error", "response.error"):
                            event_data = json.loads(data_str) if data_str else {}
                            fatal(str(event_data.get("error", "Chat error")))
                    if collected:
                        console.print()
        except ApiError as exc:
            fatal(str(exc))
        except KeyboardInterrupt:
            console.print("\n[dim]\u2514 Chat interrupted[/dim]")
        return

    # Non-streaming
    try:
        with console.status(f"[bold cyan]Sending to {agent_name}...[/bold cyan]"):
            with _api() as client:
                data = client.post(f"/api/chat/{agent_name}/send", params=_ns_params(), payload=payload)
    except ApiError as exc:
        fatal(str(exc))

    if settings.output_format == "json":
        print_json_output(data)
        return

    response_text = ""
    if isinstance(data, dict):
        response_text = str(data.get("response", data.get("message", "")))
        tid = data.get("thread_id")
        if tid:
            console.print(f"[dim]Thread: {tid}[/dim]")

    if response_text.strip():
        console.print(Panel(Markdown(response_text), border_style="bright_cyan", box=box.ROUNDED))
    else:
        console.print("[dim](empty response)[/dim]")


@chat_app.command("threads")
def chat_threads(
    agent_name: str | None = typer.Option(None, "--agent", "-a", help="Filter by agent."),
    limit: int = typer.Option(20, "--limit", "-l", min=1, max=100),
) -> None:
    """List chat threads / conversations."""
    settings = get_settings()
    params: dict[str, Any] = {**_ns_params(), "limit": limit}
    if agent_name:
        params["agent"] = agent_name

    try:
        with console.status("[bold cyan]Loading threads...[/bold cyan]"):
            with _api() as client:
                data = client.get("/api/chat/threads", params=params)
    except ApiError as exc:
        fatal(str(exc))

    items = data if isinstance(data, list) else (data.get("threads") or [])
    print_table(
        items,
        columns=[
            ("THREAD ID", "thread_id"),
            ("AGENT", "agent_name"),
            ("MESSAGES", "message_count"),
            ("LAST ACTIVE", "last_active"),
            ("STATUS", "status"),
        ],
        title="Chat Threads",
        output_format=settings.output_format,
    )


@chat_app.command("history")
def chat_history(
    thread_id: str = typer.Argument(..., help="Thread ID."),
    limit: int = typer.Option(50, "--limit", "-l", min=1, max=500),
) -> None:
    """Show message history for a thread."""
    settings = get_settings()
    params: dict[str, Any] = {"limit": limit}

    try:
        with console.status("[bold cyan]Loading history...[/bold cyan]"):
            with _api() as client:
                data = client.get(f"/api/chat/threads/{thread_id}", params=params)
    except ApiError as exc:
        fatal(str(exc))

    if settings.output_format == "json":
        print_json_output(data)
        return

    messages = data.get("messages") or [] if isinstance(data, dict) else data
    if not messages:
        console.print("[dim]No messages in this thread.[/dim]")
        return

    for msg in messages:
        role = str(msg.get("role", "unknown"))
        content = str(msg.get("content", ""))
        timestamp = str(msg.get("timestamp", ""))
        style = "bold green" if role == "assistant" else "bold blue"
        console.print(f"[{style}]{role}[/{style}] [dim]{timestamp}[/dim]")
        console.print(Markdown(content) if role == "assistant" else Text(content))
        console.print()


@chat_app.command("interactive")
def chat_interactive(
    agent_name: str = typer.Argument(..., help="Agent name."),
    thread_id: str | None = typer.Option(None, "--thread", "-t", help="Resume a thread."),
) -> None:
    """Start an interactive chat session (REPL-style)."""
    current_thread = thread_id

    console.print(
        Panel(
            f"Chatting with [bold]{agent_name}[/bold]\n"
            "[dim]Type your message and press Enter. Type /exit, /quit, or press Ctrl+C to end.[/dim]",
            title="[header]Chat Session[/header]",
            border_style="bright_cyan",
            box=box.ROUNDED,
        )
    )

    if current_thread:
        console.print(f"[dim]Resuming thread: {current_thread}[/dim]\n")

    try:
        while True:
            try:
                user_input = console.input("[bold bright_cyan]\u2502 you>[/bold bright_cyan] ").strip()
            except EOFError:
                console.print()
                break

            if not user_input or user_input.lower() in ("exit", "quit", "/exit", "/quit"):
                break

            payload: dict[str, Any] = {"message": user_input}
            if current_thread:
                payload["thread_id"] = current_thread

            try:
                with _api() as client:
                    with client.stream(
                        "POST",
                        f"/api/chat/{agent_name}/send",
                        params=_ns_params(),
                        payload=payload,
                    ) as response:
                        from agentctl.client import ApiClient as _AC

                        _AC._raise_for_status(response)

                        console.print("[bold green]\u2502 agent>[/bold green] ", end="")
                        collected = ""
                        for sse in client.iter_sse(response):
                            event = sse["event"]
                            data_str = sse["data"]
                            if event in ("chat.delta", "response.delta"):
                                event_data = json.loads(data_str) if data_str else {}
                                delta = str(event_data.get("delta", ""))
                                if delta:
                                    console.print(delta, end="")
                                    collected += delta
                            elif event in ("chat.completed", "response.completed"):
                                event_data = json.loads(data_str) if data_str else {}
                                if not current_thread:
                                    current_thread = event_data.get("thread_id")
                                break
                            elif event in ("chat.error", "response.error"):
                                event_data = json.loads(data_str) if data_str else {}
                                console.print(f"\n[red]\u2716 Error: {event_data.get('error', 'Unknown')}[/red]")
                                break
                        console.print()
            except ApiError as exc:
                console.print(f"\n[red]\u2716 {exc}[/red]")

    except KeyboardInterrupt:
        pass

    console.print()
    divider = Panel("Session ended", border_style="dim", box=box.SIMPLE)
    console.print(divider)
    if current_thread:
        console.print(f"[dim]Thread: {current_thread}[/dim]")
