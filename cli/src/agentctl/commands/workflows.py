"""Workflow management commands."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import typer
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text

from agentctl.app import get_settings
from agentctl.client import ApiClient, ApiError
from agentctl.output import (
    console,
    fatal,
    preferred_box,
    print_detail,
    print_json_output,
    print_table,
    safe_text,
    status_style,
    success,
)

workflows_app = typer.Typer(
    no_args_is_help=True,
    rich_markup_mode="rich",
    epilog=(
        "[bold]Examples:[/bold]\n"
        "  agentctl workflows list\n"
        "  agentctl workflows trigger my-workflow --param key=val\n"
        "  agentctl workflows logs my-workflow --run 5\n"
        "  agentctl workflows cancel my-workflow -y"
    ),
)


def _ns_params() -> dict[str, Any]:
    return {"namespace": get_settings().namespace}


def _api() -> ApiClient:
    return ApiClient(get_settings())


@workflows_app.command("list")
def workflows_list() -> None:
    """List workflows in the current namespace."""
    settings = get_settings()
    try:
        with console.status("[bold cyan]Loading workflows...[/bold cyan]", spinner="dots2"):
            with _api() as client:
                data = client.get("/api/workflows", params=_ns_params())
    except ApiError as exc:
        fatal(str(exc))

    items = data if isinstance(data, list) else []
    print_table(
        items,
        columns=[
            ("NAME", "name"),
            ("PHASE", "phase"),
            ("CURRENT STEP", "current_step"),
            ("STEPS", "step_count"),
        ],
        title=f"Workflows in {settings.namespace}",
        wide_columns=[
            ("INPUT", "input"),
            ("MESSAGE BUS", "message_bus"),
        ],
        output_format=settings.output_format,
    )


@workflows_app.command("show")
def workflows_show(workflow_name: str = typer.Argument(..., help="Workflow name.")) -> None:
    """Show workflow details."""
    settings = get_settings()
    try:
        with console.status(f"[bold cyan]Loading workflow {workflow_name}...[/bold cyan]", spinner="dots2"):
            with _api() as client:
                data = client.get(f"/api/workflows/{workflow_name}", params=_ns_params())
    except ApiError as exc:
        fatal(str(exc))
    print_detail(data, title=f"Workflow: {workflow_name}", output_format=settings.output_format)


@workflows_app.command("create")
def workflows_create(
    file_path: Path = typer.Option(..., "--file", "-f", exists=True, file_okay=True, dir_okay=False),
) -> None:
    """Create a workflow from a JSON or YAML file."""
    from agentctl.commands._parsers import (
        coerce_workflow_payload,
        read_structured_file,
        resolve_namespace,
        resolve_resource_name,
    )

    settings = get_settings()
    document = read_structured_file(file_path)
    payload, inferred_name = coerce_workflow_payload(document, for_update=False)
    namespace = resolve_namespace(settings.namespace, document)
    name = resolve_resource_name(None, file_path, inferred_name, "workflow")
    payload["name"] = name

    try:
        with console.status(f"[bold cyan]Creating workflow {name}...[/bold cyan]", spinner="dots2"):
            with _api() as client:
                client.post("/api/workflows", params={"namespace": namespace}, payload=payload)
    except ApiError as exc:
        fatal(str(exc))
    success(f"Workflow [bold]{name}[/bold] created in {namespace}")


@workflows_app.command("update")
def workflows_update(
    workflow_name: str | None = typer.Argument(None, help="Workflow name."),
    file_path: Path = typer.Option(..., "--file", "-f", exists=True, file_okay=True, dir_okay=False),
) -> None:
    """Update a workflow from a file."""
    from agentctl.commands._parsers import (
        coerce_workflow_payload,
        read_structured_file,
        resolve_namespace,
        resolve_resource_name,
    )

    settings = get_settings()
    document = read_structured_file(file_path)
    payload, inferred_name = coerce_workflow_payload(document, for_update=True)
    namespace = resolve_namespace(settings.namespace, document)
    resolved_name = resolve_resource_name(workflow_name, file_path, inferred_name, "workflow")

    try:
        with console.status(f"[bold cyan]Updating workflow {resolved_name}...[/bold cyan]", spinner="dots2"):
            with _api() as client:
                client.patch(f"/api/workflows/{resolved_name}", params={"namespace": namespace}, payload=payload)
    except ApiError as exc:
        fatal(str(exc))
    success(f"Workflow [bold]{resolved_name}[/bold] updated")


@workflows_app.command("delete")
def workflows_delete(
    workflow_name: str | None = typer.Argument(None, help="Workflow name."),
    file_path: Path | None = typer.Option(None, "--file", "-f", exists=True, file_okay=True, dir_okay=False),
    assume_yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation."),
) -> None:
    """Delete a workflow."""
    from agentctl.commands._parsers import (
        coerce_workflow_payload,
        read_structured_file,
        resolve_namespace,
        resolve_resource_name,
    )

    settings = get_settings()
    namespace = settings.namespace
    inferred_name = ""
    if file_path is not None:
        document = read_structured_file(file_path)
        _, inferred_name = coerce_workflow_payload(document, for_update=True)
        namespace = resolve_namespace(settings.namespace, document)

    resolved_name = resolve_resource_name(workflow_name, file_path, inferred_name, "workflow")

    if not assume_yes:
        if not typer.confirm(f"Delete workflow '{resolved_name}' in '{namespace}'?", default=False):
            raise typer.Exit(0)

    try:
        with console.status(f"[bold cyan]Deleting workflow {resolved_name}...[/bold cyan]", spinner="dots2"):
            with _api() as client:
                client.delete(f"/api/workflows/{resolved_name}", params={"namespace": namespace})
    except ApiError as exc:
        fatal(str(exc))
    success(f"Workflow [bold]{resolved_name}[/bold] deleted from {namespace}")


@workflows_app.command("trigger")
def workflows_trigger(
    workflow_name: str = typer.Argument(..., help="Workflow name."),
    input_parts: list[str] | None = typer.Argument(None, help="Optional input text."),
    input_file: Path | None = typer.Option(None, "--file", "-f", exists=True, file_okay=True, dir_okay=False),
) -> None:
    """Trigger (re-)execution of a workflow."""
    settings = get_settings()
    input_text = ""
    if input_file:
        input_text = input_file.read_text(encoding="utf-8").strip()
    elif input_parts:
        input_text = " ".join(input_parts).strip()

    payload: dict[str, Any] | None = {"input": input_text} if input_text else None

    try:
        with console.status(f"[bold cyan]Triggering workflow {workflow_name}...[/bold cyan]", spinner="dots2"):
            with _api() as client:
                data = client.post(f"/api/workflows/{workflow_name}/trigger", params=_ns_params(), payload=payload)
    except ApiError as exc:
        fatal(str(exc))

    if settings.output_format == "json":
        print_json_output(data)
        return
    success(f"Workflow [bold]{workflow_name}[/bold] triggered in {settings.namespace}")
    if isinstance(data, dict):
        console.print(
            f"  [dim]Phase:[/dim] {data.get('phase', 'pending')}  [dim]Step:[/dim] {data.get('current_step', '-')}"
        )


@workflows_app.command("cancel")
def workflows_cancel(
    workflow_name: str = typer.Argument(..., help="Workflow name."),
    assume_yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation."),
) -> None:
    """Cancel a running workflow."""
    if not assume_yes:
        if not typer.confirm(f"Cancel workflow '{workflow_name}'?", default=False):
            raise typer.Exit(0)

    try:
        with console.status(f"[bold cyan]Cancelling {workflow_name}...[/bold cyan]", spinner="dots2"):
            with _api() as client:
                client.post(f"/api/workflows/{workflow_name}/cancel", params=_ns_params())
    except ApiError as exc:
        fatal(str(exc))
    success(f"Workflow [bold]{workflow_name}[/bold] cancelled")


@workflows_app.command("status")
def workflows_status(workflow_name: str = typer.Argument(..., help="Workflow name.")) -> None:
    """Show focused run status of a workflow."""
    settings = get_settings()
    try:
        with console.status(f"[bold cyan]Loading status for {workflow_name}...[/bold cyan]", spinner="dots2"):
            with _api() as client:
                data = client.get(f"/api/workflows/{workflow_name}", params=_ns_params())
    except ApiError as exc:
        fatal(str(exc))

    if settings.output_format == "json":
        print_json_output(data)
        return
    if not isinstance(data, dict):
        fatal("Unexpected response.")

    # Summary
    table = Table(show_header=False, box=preferred_box(heavy=True), border_style="bright_cyan")
    table.add_column("", style="bold magenta")
    table.add_column("")
    table.add_row("Name", str(data.get("name", workflow_name)))
    table.add_row("Phase", str(data.get("phase", "pending")))
    table.add_row("Current Step", str(data.get("current_step", "") or "-"))
    table.add_row("Run ID", str(data.get("run_id", "") or "-"))
    pending = data.get("pending_approval")
    if isinstance(pending, dict) and pending.get("name"):
        table.add_row("Pending Approval", str(pending["name"]))
    console.print(table)

    # Step states
    step_states = data.get("step_states")
    if isinstance(step_states, dict) and step_states:
        st = Table(title="Step States", border_style="bright_black", box=preferred_box())
        st.add_column("STEP", style="bold")
        st.add_column("PHASE")
        st.add_column("AGENT", style="cyan")
        for step_name, state_data in step_states.items():
            phase = str(state_data.get("phase", "pending")) if isinstance(state_data, dict) else str(state_data)
            agent = str(state_data.get("agent_ref", "-")) if isinstance(state_data, dict) else "-"
            st.add_row(str(step_name), Text(phase, style=status_style(phase)), agent)
        console.print(st)


@workflows_app.command("logs")
def workflows_logs(
    workflow_name: str = typer.Argument(..., help="Workflow name."),
    run_id: str | None = typer.Option(None, "--run-id", help="Specific run ID."),
    step: str | None = typer.Option(None, "--step", help="Filter to a specific step."),
    tail: int = typer.Option(200, "--tail", "-t", min=1, max=5000),
) -> None:
    """Fetch workflow runtime logs."""
    settings = get_settings()

    path = f"/api/workflows/{workflow_name}/logs"
    params: dict[str, Any] = {**_ns_params(), "tail": tail}
    if run_id:
        path = f"/api/workflows/{workflow_name}/runs/{run_id}/logs"
    if step:
        params["step"] = step

    try:
        with console.status(f"[bold cyan]Fetching logs for {workflow_name}...[/bold cyan]", spinner="dots2"):
            with _api() as client:
                data = client.get(path, params=params)
    except ApiError as exc:
        fatal(str(exc))

    if settings.output_format == "json":
        print_json_output(data)
        return

    logs_text = ""
    if isinstance(data, dict):
        logs_text = str(data.get("logs", ""))
    elif isinstance(data, str):
        logs_text = data
    else:
        logs_text = str(data or "")

    if not logs_text.strip():
        console.print("[dim]No logs available for this workflow.[/dim]")
        return

    title = f"Logs: {workflow_name}"
    if run_id:
        title += f" (run {run_id[:12]})"
    if step:
        title += f" [step {step}]"

    console.print(
        Panel(
            Syntax(safe_text(logs_text), "text", line_numbers=False, word_wrap=True),
            title=title,
            border_style="bright_cyan",
            box=preferred_box(),
        )
    )
