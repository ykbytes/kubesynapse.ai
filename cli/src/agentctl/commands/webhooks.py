"""Webhook and Trigger management commands."""

from __future__ import annotations

from typing import Any, Optional

import typer
from rich.panel import Panel

from agentctl.app import get_settings
from agentctl.client import ApiClient, ApiError
from agentctl.output import (
    console,
    print_table,
    print_detail,
    print_json_output,
    success,
    fatal,
)

webhooks_app = typer.Typer(no_args_is_help=True, rich_markup_mode="rich")


def _api() -> ApiClient:
    return ApiClient(get_settings())


def _ns_params() -> dict[str, Any]:
    return {"namespace": get_settings().namespace}


# ─── Webhooks ───


@webhooks_app.command("list")
def webhooks_list() -> None:
    """List webhooks in the current namespace."""
    settings = get_settings()
    try:
        with console.status("[bold cyan]Loading webhooks...[/bold cyan]"):
            with _api() as client:
                data = client.get("/api/webhooks", params=_ns_params())
    except ApiError as exc:
        fatal(str(exc))

    items = data if isinstance(data, list) else (data.get("webhooks") or [])
    print_table(
        items,
        columns=[
            ("NAME", "name"),
            ("WORKFLOW", "workflow_ref"),
            ("EVENT", "event_type"),
            ("STATUS", "status"),
            ("CREATED", "created_at"),
        ],
        wide_columns=[
            ("SECRET", "has_secret"),
            ("URL", "url"),
        ],
        title="Webhooks",
        output_format=settings.output_format,
    )


@webhooks_app.command("show")
def webhooks_show(name: str = typer.Argument(..., help="Webhook name.")) -> None:
    """Show webhook details."""
    settings = get_settings()
    try:
        with console.status(f"[bold cyan]Loading webhook {name}...[/bold cyan]"):
            with _api() as client:
                data = client.get(f"/api/webhooks/{name}", params=_ns_params())
    except ApiError as exc:
        fatal(str(exc))
    print_detail(data, title=f"Webhook: {name}", output_format=settings.output_format)


@webhooks_app.command("create")
def webhooks_create(
    name: str = typer.Argument(..., help="Webhook name."),
    workflow: str = typer.Option(..., "--workflow", "-w", help="Target workflow."),
    event_type: str = typer.Option("push", "--event", "-e", help="Event type (e.g. push, pr, custom)."),
    secret: Optional[str] = typer.Option(None, "--secret", "-s", help="Webhook secret for validation."),
) -> None:
    """Create a new webhook."""
    settings = get_settings()
    payload: dict[str, Any] = {
        "name": name,
        "workflow_ref": workflow,
        "event_type": event_type,
    }
    if secret:
        payload["secret"] = secret

    try:
        with console.status(f"[bold cyan]Creating webhook {name}...[/bold cyan]"):
            with _api() as client:
                data = client.post("/api/webhooks", params=_ns_params(), payload=payload)
    except ApiError as exc:
        fatal(str(exc))
    success(f"Webhook [bold]{name}[/bold] created")


@webhooks_app.command("delete")
def webhooks_delete(
    name: str = typer.Argument(..., help="Webhook name."),
    assume_yes: bool = typer.Option(False, "--yes", "-y"),
) -> None:
    """Delete a webhook."""
    if not assume_yes:
        if not typer.confirm(f"Delete webhook '{name}'?", default=False):
            raise typer.Exit(0)

    try:
        with console.status(f"[bold cyan]Deleting webhook {name}...[/bold cyan]"):
            with _api() as client:
                client.delete(f"/api/webhooks/{name}", params=_ns_params())
    except ApiError as exc:
        fatal(str(exc))
    success(f"Webhook [bold]{name}[/bold] deleted")


# ─── Triggers ───


@webhooks_app.command("triggers")
def triggers_list() -> None:
    """List triggers (webhook-dispatched workflow executions)."""
    settings = get_settings()
    try:
        with console.status("[bold cyan]Loading triggers...[/bold cyan]"):
            with _api() as client:
                data = client.get("/api/triggers", params=_ns_params())
    except ApiError as exc:
        fatal(str(exc))

    items = data if isinstance(data, list) else (data.get("triggers") or [])
    print_table(
        items,
        columns=[
            ("ID", "id"),
            ("WEBHOOK", "webhook_name"),
            ("WORKFLOW", "workflow_ref"),
            ("STATUS", "status"),
            ("TRIGGERED AT", "triggered_at"),
        ],
        wide_columns=[
            ("EVENT", "event_type"),
            ("RUN ID", "run_id"),
        ],
        title="Triggers",
        output_format=settings.output_format,
    )


@webhooks_app.command("trigger-show")
def trigger_show(trigger_id: str = typer.Argument(..., help="Trigger ID.")) -> None:
    """Show trigger details."""
    settings = get_settings()
    try:
        with console.status(f"[bold cyan]Loading trigger {trigger_id}...[/bold cyan]"):
            with _api() as client:
                data = client.get(f"/api/triggers/{trigger_id}", params=_ns_params())
    except ApiError as exc:
        fatal(str(exc))
    print_detail(data, title=f"Trigger: {trigger_id}", output_format=settings.output_format)


@webhooks_app.command("dispatch")
def webhooks_dispatch(
    webhook_name: str = typer.Argument(..., help="Webhook name to dispatch."),
    payload_str: Optional[str] = typer.Option(None, "--payload", "-p", help="JSON payload body."),
) -> None:
    """Manually dispatch a webhook (simulate an incoming event)."""
    import json as json_module

    settings = get_settings()
    payload: dict[str, Any] = {}
    if payload_str:
        try:
            payload = json_module.loads(payload_str)
        except json_module.JSONDecodeError as e:
            fatal(f"Invalid JSON payload: {e}")

    try:
        with console.status(f"[bold cyan]Dispatching webhook {webhook_name}...[/bold cyan]"):
            with _api() as client:
                data = client.post(
                    f"/api/webhooks/{webhook_name}/dispatch",
                    params=_ns_params(),
                    payload=payload,
                )
    except ApiError as exc:
        fatal(str(exc))

    if settings.output_format == "json":
        print_json_output(data)
        return
    success(f"Webhook [bold]{webhook_name}[/bold] dispatched")
    if isinstance(data, dict) and data.get("trigger_id"):
        console.print(f"  [dim]Trigger ID:[/dim] {data['trigger_id']}")
