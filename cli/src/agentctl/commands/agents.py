"""Agent management commands."""

from __future__ import annotations

import json
import sys
import textwrap
from pathlib import Path
from typing import Any

import typer
from rich.markdown import Markdown
from rich.panel import Panel
from rich.pretty import Pretty
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text

from agentctl.app import get_settings
from agentctl.client import ApiClient, ApiError
from agentctl.output import (
    console,
    fatal,
    inline_separator,
    preferred_box,
    print_detail,
    print_json_output,
    print_stream_text,
    print_table,
    safe_text,
    stop_marker,
    supports_unicode_output,
    success,
)

agents_app = typer.Typer(
    no_args_is_help=True,
    rich_markup_mode="rich",
    epilog=(
        "[bold]Examples:[/bold]\n"
        "  agentctl agents list -o wide\n"
        "  agentctl agents create ./agent.yaml\n"
        "  agentctl agents invoke my-agent --stream\n"
        "  agentctl agents logs my-agent --tail 100 -f"
    ),
)


# ─── Helpers ───


def _ns_params() -> dict[str, Any]:
    return {"namespace": get_settings().namespace}


def _api() -> ApiClient:
    return ApiClient(get_settings())


def _render_invoke_result(data: dict[str, Any]) -> None:
    """Pretty-print an invoke response."""
    settings = get_settings()
    if settings.output_format == "json":
        print_json_output(data)
        return

    # Header info
    info_rows = [
        ("Agent", str(data.get("agent_name", ""))),
        ("Status", str(data.get("status", "unknown"))),
        ("Model", str(data.get("model", ""))),
        ("Thread", str(data.get("thread_id", ""))),
        ("Policy", str(data.get("policy_name") or "-")),
        ("Approval", str(data.get("approval_name") or "-")),
    ]
    table = Table(show_header=False, box=preferred_box(heavy=True), border_style="bright_cyan")
    table.add_column("Field", style="bold magenta", no_wrap=True)
    table.add_column("Value")
    for k, v in info_rows:
        table.add_row(k, Text(safe_text(v)))
    console.print(table)

    # Response body
    response_text = str(data.get("response", "")).strip() or "(empty response)"
    response_renderable = Markdown(response_text) if supports_unicode_output() else Text(safe_text(response_text))
    console.print(
        Panel(
            response_renderable,
            title="[header]Response[/header]",
            border_style="bright_cyan",
            box=preferred_box(),
        )
    )

    # Tool result
    tool_result = data.get("tool_result")
    if tool_result is not None:
        console.print(
            Panel(
                Pretty(tool_result),
                title="[header]Tool Result[/header]",
                border_style="bright_cyan",
                box=preferred_box(),
            )
        )

    # Sandbox
    sandbox = data.get("sandbox_session")
    if sandbox:
        console.print(
            Panel(
                Pretty(sandbox),
                title="[header]Sandbox Session[/header]",
                border_style="bright_cyan",
                box=preferred_box(),
            )
        )

    # A2A metadata
    a2a = data.get("a2a")
    if isinstance(a2a, dict) and a2a:
        a2a_rows = []
        if a2a.get("targetAgent"):
            a2a_rows.append(("Target", f"{a2a.get('targetNamespace', '')}/{a2a.get('targetAgent', '')}"))
        if a2a.get("callerAgent"):
            a2a_rows.append(("Caller", f"{a2a.get('callerNamespace', '')}/{a2a.get('callerAgent', '')}"))
        if a2a_rows:
            t = Table(show_header=False, box=preferred_box(simple=True), border_style="grey58")
            t.add_column("", style="bold magenta")
            t.add_column("")
            for k, v in a2a_rows:
                t.add_row(k, Text(safe_text(v)))
            console.print(Panel(t, title="[dim]A2A[/dim]", border_style="grey58", box=preferred_box()))

    # Artifacts
    artifacts = data.get("artifacts")
    if artifacts:
        console.print(Panel(Pretty(artifacts), title="Artifacts", border_style="bright_cyan", box=preferred_box()))

    # Warnings
    warnings = data.get("warnings") or []
    if warnings:
        content = "\n".join(f"- {w}" for w in warnings)
        console.print(Panel(Text(safe_text(content)), title="Warnings", border_style="yellow", box=preferred_box()))


def _event_summary(event_name: str, payload: dict[str, Any]) -> str:
    if event_name == "response.completed":
        return f"status={payload.get('status', 'completed')} thread={payload.get('thread_id', '-')}"
    if event_name == "response.error":
        return str(payload.get("error", "Unknown streaming error"))
    parts: list[str] = []
    for key in ("tool_name", "status", "approval_name", "request_id", "role", "name", "namespace"):
        value = payload.get(key)
        if value:
            parts.append(f"{key}={value}")
    if not parts:
        text = json.dumps(payload, ensure_ascii=False)
        return textwrap.shorten(text, width=100, placeholder="...")
    return " ".join(parts)


def _notification_matches_agent(agent_name: str, event_name: str, payload: dict[str, Any]) -> bool:
    """Return True when a namespace notification is relevant to the requested agent."""

    if event_name == "system.error":
        return True

    payload_agent = str(payload.get("agent_name") or "").strip()
    payload_name = str(payload.get("name") or "").strip()
    target_agent = agent_name.strip()

    if payload_agent and payload_agent == target_agent:
        return True
    if event_name.startswith("agent.") and payload_name == target_agent:
        return True
    return False


def _notification_summary(event_name: str, payload: dict[str, Any]) -> str:
    """Build a concise CLI summary for notification SSE frames."""

    if event_name == "system.error":
        return str(payload.get("message") or payload.get("summary") or "notification stream error")

    parts: list[str] = []
    phase = str(payload.get("phase") or payload.get("status") or "").strip()
    previous_phase = str(payload.get("previousPhase") or payload.get("previous_phase") or "").strip()
    message = str(payload.get("message") or payload.get("summary") or payload.get("detail") or "").strip()

    if phase:
        parts.append(f"phase={phase}")
    if previous_phase:
        parts.append(f"previous={previous_phase}")
    if message:
        parts.append(message)

    if not parts:
        text = json.dumps(payload, ensure_ascii=False)
        return textwrap.shorten(text, width=120, placeholder="...")
    return " ".join(parts)


# ─── Commands ───


@agents_app.command("list")
def agents_list() -> None:
    """List agents in the current namespace."""
    settings = get_settings()
    try:
        with console.status("[bold cyan]Loading agents...[/bold cyan]", spinner="dots2"):
            with _api() as client:
                data = client.get("/api/agents", params=_ns_params())
    except ApiError as exc:
        fatal(str(exc))

    if settings.output_format in ("json", "yaml"):
        print_table(data, [], output_format=settings.output_format)
        return

    items = data if isinstance(data, list) else []
    print_table(
        items,
        columns=[
            ("NAME", "name"),
            ("MODEL", "model"),
            ("STATUS", "status"),
            ("NAMESPACE", "namespace"),
        ],
        title=f"Agents in {settings.namespace}",
        wide_columns=[
            ("RUNTIME", "runtime_kind"),
            ("POLICY", "policy_ref"),
        ],
        output_format=settings.output_format,
    )


@agents_app.command("show")
def agents_show(agent_name: str = typer.Argument(..., help="Agent name.")) -> None:
    """Show agent details."""
    settings = get_settings()
    try:
        with console.status(f"[bold cyan]Loading {agent_name}...[/bold cyan]", spinner="dots2"):
            with _api() as client:
                data = client.get(f"/api/agents/{agent_name}", params=_ns_params())
    except ApiError as exc:
        fatal(str(exc))

    print_detail(
        data,
        title=f"Agent: {agent_name}",
        output_format=settings.output_format,
    )


@agents_app.command("create")
def agents_create(
    file_path: Path = typer.Option(..., "--file", "-f", exists=True, file_okay=True, dir_okay=False),
) -> None:
    """Create an agent from a JSON or YAML file."""
    from agentctl.commands._parsers import (
        coerce_agent_payload,
        read_structured_file,
        resolve_namespace,
        resolve_resource_name,
    )

    settings = get_settings()
    document = read_structured_file(file_path)
    payload, inferred_name = coerce_agent_payload(document, for_update=False)
    namespace = resolve_namespace(settings.namespace, document)
    agent_name = resolve_resource_name(None, file_path, inferred_name, "agent")
    payload["name"] = agent_name

    try:
        with console.status(f"[bold cyan]Creating agent {agent_name}...[/bold cyan]", spinner="dots2"):
            with _api() as client:
                client.post("/api/agents", params={"namespace": namespace}, payload=payload)
    except ApiError as exc:
        fatal(str(exc))
    success(f"Agent [bold]{agent_name}[/bold] created in {namespace}")


@agents_app.command("update")
def agents_update(
    agent_name: str | None = typer.Argument(None, help="Agent name."),
    file_path: Path | None = typer.Option(None, "--file", "-f", exists=True, file_okay=True, dir_okay=False),
) -> None:
    """Update an agent from a file."""
    from agentctl.commands._parsers import (
        coerce_agent_payload,
        read_structured_file,
        resolve_namespace,
        resolve_resource_name,
    )

    settings = get_settings()
    if file_path is None and agent_name is None:
        fatal("Pass --file or provide an agent name.")

    if file_path is not None:
        document = read_structured_file(file_path)
        payload, inferred_name = coerce_agent_payload(document, for_update=True)
        namespace = resolve_namespace(settings.namespace, document)
    else:
        inferred_name = agent_name
        namespace = settings.namespace
        # Fetch current and pass back
        try:
            with _api() as client:
                current = client.get(f"/api/agents/{agent_name}", params={"namespace": namespace})
        except ApiError as exc:
            fatal(str(exc))
        payload = current
        inferred_name = agent_name

    resolved_name = resolve_resource_name(agent_name, file_path, inferred_name, "agent")

    try:
        with console.status(f"[bold cyan]Updating agent {resolved_name}...[/bold cyan]", spinner="dots2"):
            with _api() as client:
                client.patch(f"/api/agents/{resolved_name}", params={"namespace": namespace}, payload=payload)
    except ApiError as exc:
        fatal(str(exc))
    success(f"Agent [bold]{resolved_name}[/bold] updated")


@agents_app.command("delete")
def agents_delete(
    agent_name: str | None = typer.Argument(None, help="Agent name."),
    file_path: Path | None = typer.Option(None, "--file", "-f", exists=True, file_okay=True, dir_okay=False),
    assume_yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation."),
) -> None:
    """Delete an agent."""
    from agentctl.commands._parsers import (
        coerce_agent_payload,
        read_structured_file,
        resolve_namespace,
        resolve_resource_name,
    )

    settings = get_settings()
    namespace = settings.namespace
    inferred_name = ""
    if file_path is not None:
        document = read_structured_file(file_path)
        _, inferred_name = coerce_agent_payload(document, for_update=True)
        namespace = resolve_namespace(settings.namespace, document)

    resolved_name = resolve_resource_name(agent_name, file_path, inferred_name, "agent")

    if not assume_yes:
        if not typer.confirm(f"Delete agent '{resolved_name}' in namespace '{namespace}'?", default=False):
            raise typer.Exit(0)

    try:
        with console.status(f"[bold cyan]Deleting agent {resolved_name}...[/bold cyan]", spinner="dots2"):
            with _api() as client:
                client.delete(f"/api/agents/{resolved_name}", params={"namespace": namespace})
    except ApiError as exc:
        fatal(str(exc))
    success(f"Agent [bold]{resolved_name}[/bold] deleted from {namespace}")


@agents_app.command("discover")
def agents_discover(
    agent_name: str = typer.Argument(..., help="Agent name."),
    include_unreachable: bool = typer.Option(False, "--include-unreachable", help="Show unreachable peers too."),
) -> None:
    """Show A2A discovery for an agent."""
    settings = get_settings()
    try:
        with console.status(f"[bold cyan]Discovering peers for {agent_name}...[/bold cyan]", spinner="dots2"):
            with _api() as client:
                data = client.get(f"/api/agents/{agent_name}/discover", params=_ns_params())
    except ApiError as exc:
        fatal(str(exc))

    if settings.output_format in ("json", "yaml"):
        print_detail(data, output_format=settings.output_format)
        return

    peers = data.get("peers") or []
    visible = peers if include_unreachable else [p for p in peers if p.get("reachable")]

    console.print(
        Text.assemble(
            ("Agent:", "dim"),
            f" {safe_text(data.get('agent_name', ''))}  ",
            ("Namespace:", "dim"),
            f" {safe_text(data.get('namespace', ''))}",
        )
    )
    if not visible:
        console.print("[dim]No discoverable peers.[/dim]")
        return

    print_table(
        visible,
        columns=[
            ("NAME", "name"),
            ("NAMESPACE", "namespace"),
            ("REACHABLE", "reachable"),
            ("STATUS", "status"),
            ("RUNTIME", "runtime_kind"),
            ("MODEL", "model"),
        ],
        title="A2A Peers",
        output_format=settings.output_format,
    )


@agents_app.command("invoke")
def agents_invoke(
    agent_name: str = typer.Argument(..., help="Agent name."),
    prompt_parts: list[str] | None = typer.Argument(None, help="Prompt text."),
    stream: bool = typer.Option(False, "--stream", "-s", help="Use SSE streaming."),
    prompt_file: Path | None = typer.Option(None, "--file", exists=True, file_okay=True, dir_okay=False),
    thread_id: str | None = typer.Option(None, "--thread-id", help="Reuse thread."),
    system: str | None = typer.Option(None, "--system", help="System instructions."),
    require_approval: bool = typer.Option(False, "--require-approval", help="Request HITL approval."),
    no_session: bool = typer.Option(False, "--no-session", help="Disable session persistence."),
    max_turns: int | None = typer.Option(None, "--max-turns", min=1),
    debug: bool = typer.Option(False, "--debug"),
) -> None:
    """Invoke an agent with a prompt."""
    settings = get_settings()

    # Resolve prompt
    if prompt_file is not None:
        prompt = prompt_file.read_text(encoding="utf-8").strip()
    elif prompt_parts:
        prompt = " ".join(prompt_parts).strip()
    elif not sys.stdin.isatty():
        prompt = sys.stdin.read().strip()
    else:
        prompt = typer.prompt("Prompt").strip()

    if not prompt:
        fatal("Prompt must not be empty.")

    payload: dict[str, Any] = {"prompt": prompt}
    if thread_id:
        payload["thread_id"] = thread_id
    if system:
        payload["system"] = system
    if require_approval:
        payload["require_approval"] = True
    if no_session:
        payload["no_session"] = True
    if max_turns is not None:
        payload["max_turns"] = max_turns
    if debug:
        payload["debug"] = True

    if stream:
        try:
            with _api() as client:
                with client.stream(
                    "POST", f"/api/agents/{agent_name}/invoke/stream", params=_ns_params(), payload=payload
                ) as response:
                    from agentctl.client import ApiClient as _AC

                    _AC._raise_for_status(response)
                    console.print(
                        Panel(
                            Text.assemble(
                                (safe_text(agent_name), "bold"),
                                f" {inline_separator()} ",
                                (safe_text(settings.namespace), "dim"),
                            ),
                            title="[header]Invoke[/header]",
                            border_style="bright_cyan",
                            box=preferred_box(),
                            expand=False,
                        )
                    )
                    completed_payload: dict[str, Any] | None = None
                    emitted_delta = False
                    for sse in client.iter_sse(response):
                        event_name = sse["event"]
                        data_str = sse["data"]
                        event_data = json.loads(data_str) if data_str else {}
                        if event_name == "response.delta":
                            delta = str(event_data.get("delta", ""))
                            if delta:
                                print_stream_text(delta, end="")
                                emitted_delta = True
                            continue
                        if emitted_delta:
                            console.print()
                            emitted_delta = False
                        if event_name == "response.completed":
                            completed_payload = event_data
                            continue
                        if event_name == "response.error":
                            fatal(str(event_data.get("error", "Streaming error.")))
                        console.print(
                            Panel(
                                Text(safe_text(_event_summary(event_name, event_data))),
                                title=Text(safe_text(event_name), style="dim"),
                                border_style="grey58",
                                box=preferred_box(simple=True),
                                expand=False,
                            )
                        )
        except ApiError as exc:
            fatal(str(exc))
        if completed_payload:
            _render_invoke_result(completed_payload)
        return

    # Synchronous invoke
    try:
        with console.status(f"[bold cyan]Invoking {agent_name}...[/bold cyan]", spinner="dots2"):
            with _api() as client:
                data = client.post(f"/api/agents/{agent_name}/invoke", params=_ns_params(), payload=payload)
    except ApiError as exc:
        fatal(str(exc))
    _render_invoke_result(data)


@agents_app.command("logs")
def agents_logs(
    agent_name: str = typer.Argument(..., help="Agent name."),
    tail: int = typer.Option(200, "--tail", "-t", min=1, max=5000),
    follow: bool = typer.Option(False, "--follow", "-f", help="Stream logs in real-time."),
) -> None:
    """Fetch logs for an agent runtime."""
    settings = get_settings()

    if follow:
        try:
            with _api() as client:
                with client.stream(
                    "GET", f"/api/agents/{agent_name}/logs/stream", params={**_ns_params(), "tail": tail}
                ) as response:
                    from agentctl.client import ApiClient as _AC

                    _AC._raise_for_status(response)
                    console.print(
                        Panel(
                            Text.assemble(
                                (safe_text(agent_name), "bold"),
                                f" {inline_separator()} ",
                                ("Ctrl+C to stop", "dim"),
                            ),
                            title="[header]Logs[/header]",
                            border_style="bright_cyan",
                            box=preferred_box(),
                        )
                    )
                    for sse in client.iter_sse(response):
                        if sse["event"] == "log.line":
                            try:
                                payload = json.loads(sse["data"])
                                line = str(payload.get("line", sse["data"]))
                            except (json.JSONDecodeError, ValueError):
                                line = sse["data"]
                            print_stream_text(line)
                        elif sse["event"] == "log.ended":
                            break
        except KeyboardInterrupt:
            console.print(f"\n[dim]{stop_marker()} Log stream stopped[/dim]")
        except ApiError as exc:
            fatal(str(exc))
        return

    try:
        with console.status(f"[bold cyan]Fetching logs for {agent_name}...[/bold cyan]", spinner="dots2"):
            with _api() as client:
                data = client.get(f"/api/agents/{agent_name}/logs", params={**_ns_params(), "tail": tail})
    except ApiError as exc:
        fatal(str(exc))

    if settings.output_format == "json":
        print_json_output(data)
        return

    logs = str(data.get("logs", ""))
    if not logs.strip():
        console.print("[dim]No logs available.[/dim]")
        return
    console.print(
        Panel(
            Syntax(safe_text(logs), "text", line_numbers=False, word_wrap=True),
            title=f"Logs: {agent_name}",
            border_style="bright_cyan",
            box=preferred_box(),
        )
    )


@agents_app.command("live-events")
def agents_live_events(
    agent_name: str = typer.Argument(..., help="Agent name."),
) -> None:
    """Stream namespace notification events relevant to an agent."""
    from datetime import datetime

    try:
        with _api() as client:
            with client.stream("GET", "/api/v1/notifications/stream", params=_ns_params()) as response:
                import json as _json

                from agentctl.client import ApiClient as _AC

                _AC._raise_for_status(response)
                console.print(
                    Panel(
                        Text.assemble(
                            (safe_text(agent_name), "bold"),
                            f" {inline_separator()} ",
                            ("Ctrl+C to stop", "dim"),
                        ),
                        title="[header]Live Events[/header]",
                        border_style="bright_cyan",
                        box=preferred_box(),
                    )
                )
                for sse in client.iter_sse(response):
                    ts = datetime.now().strftime("%H:%M:%S")
                    event_type = sse["event"] or "notification"
                    data_str = sse["data"]
                    try:
                        payload = _json.loads(data_str) if data_str else {}
                    except (_json.JSONDecodeError, ValueError):
                        payload = {"message": data_str}
                    if not _notification_matches_agent(agent_name, event_type, payload):
                        continue
                    summary = _notification_summary(event_type, payload)
                    style_map = {
                        "agent.status_changed": "cyan",
                        "workflow.completed": "green",
                        "workflow.failed": "red",
                        "workflow.approval_needed": "yellow",
                        "workflow.status_changed": "magenta",
                        "system.error": "red",
                    }
                    color = style_map.get(event_type, "dim")
                    line = Text()
                    line.append(ts, style="dim")
                    line.append(" [")
                    line.append(event_type, style=color)
                    line.append("] ")
                    line.append(" ".join(safe_text(summary).splitlines())[:120])
                    console.print(line)
    except KeyboardInterrupt:
        console.print(f"\n[dim]{stop_marker()} Event stream stopped[/dim]")
    except ApiError as exc:
        fatal(str(exc))
