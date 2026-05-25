"""Webhook and workflow-trigger management commands."""

from __future__ import annotations

from typing import Any

import typer

from agentctl.app import get_settings
from agentctl.client import ApiClient, ApiError
from agentctl.output import console, fatal, print_detail, print_json_output, print_table, success

webhooks_app = typer.Typer(
    no_args_is_help=True,
    rich_markup_mode="rich",
    epilog=(
        "[bold]Examples:[/bold]\n"
        "  agentctl webhooks list\n"
        "  agentctl webhooks create my-hook --workflow my-workflow --event custom\n"
        "  agentctl webhooks show my-hook\n"
        "  agentctl webhooks dispatch my-hook --payload '{\"event\":\"custom\"}'"
    ),
)


def _api() -> ApiClient:
    return ApiClient(get_settings())


def _ns_params() -> dict[str, Any]:
    return {"namespace": get_settings().namespace}


def _trigger_payload(name: str, workflow: str, event_type: str) -> dict[str, Any]:
    return {
        "name": name,
        "source_kind": "WebhookReceiver",
        "source_name": name,
        "source_ref": name,
        "event_filter": {"event": event_type},
        "target_workflow_name": workflow,
        "target_workflow_namespace": get_settings().namespace,
        "workflow_ref": {"name": workflow, "namespace": get_settings().namespace},
        "enabled": True,
    }


@webhooks_app.command("list")
def webhooks_list() -> None:
    """List webhook receivers in the current namespace."""
    settings = get_settings()
    try:
        with console.status("[bold cyan]Loading webhooks...[/bold cyan]", spinner="dots2"):
            with _api() as client:
                data = client.get("/api/v1/webhooks", params=_ns_params())
    except ApiError as exc:
        fatal(str(exc))

    items = data if isinstance(data, list) else (data.get("webhooks") or [])
    normalized = [
        {
            "name": item.get("name"),
            "secret_ref": item.get("secret_ref"),
            "enabled": "enabled" if item.get("enabled", True) else "disabled",
            "rate_limit": item.get("rate_limit"),
            "created_at": item.get("created_at"),
        }
        for item in items
        if isinstance(item, dict)
    ]
    print_table(
        normalized,
        columns=[
            ("NAME", "name"),
            ("SECRET REF", "secret_ref"),
            ("STATUS", "enabled"),
            ("RATE", "rate_limit"),
            ("CREATED", "created_at"),
        ],
        title="Webhooks",
        output_format=settings.output_format,
    )


@webhooks_app.command("show")
def webhooks_show(name: str = typer.Argument(..., help="Webhook name.")) -> None:
    """Show webhook receiver details."""
    settings = get_settings()
    try:
        with console.status(f"[bold cyan]Loading webhook {name}...[/bold cyan]", spinner="dots2"):
            with _api() as client:
                data = client.get(f"/api/v1/webhooks/{name}", params=_ns_params())
    except ApiError as exc:
        fatal(str(exc))
    print_detail(data, title=f"Webhook: {name}", output_format=settings.output_format)


@webhooks_app.command("create")
def webhooks_create(
    name: str = typer.Argument(..., help="Webhook name."),
    workflow: str = typer.Option(..., "--workflow", "-w", help="Target workflow."),
    event_type: str = typer.Option("custom", "--event", "-e", help="Payload event value to match."),
    secret: str | None = typer.Option("cli-e2e-secret", "--secret", "-s", help="Webhook secret_ref value."),
) -> None:
    """Create a webhook receiver and a matching workflow trigger with the same name."""
    webhook_payload: dict[str, Any] = {
        "name": name,
        "secret_ref": secret or "cli-e2e-secret",
        "enabled": True,
    }

    try:
        with console.status(f"[bold cyan]Creating webhook {name}...[/bold cyan]", spinner="dots2"):
            with _api() as client:
                client.post("/api/v1/webhooks", params=_ns_params(), payload=webhook_payload)
                try:
                    client.post(
                        "/api/v1/workflow-triggers",
                        params=_ns_params(),
                        payload=_trigger_payload(name=name, workflow=workflow, event_type=event_type),
                    )
                except ApiError as exc:
                    client.delete(f"/api/v1/webhooks/{name}", params=_ns_params())
                    raise exc
    except ApiError as exc:
        fatal(str(exc))
    success(f"Webhook [bold]{name}[/bold] created and linked to workflow [bold]{workflow}[/bold]")


@webhooks_app.command("delete")
def webhooks_delete(
    name: str = typer.Argument(..., help="Webhook name."),
    assume_yes: bool = typer.Option(False, "--yes", "-y"),
) -> None:
    """Delete a webhook receiver and its same-named workflow trigger."""
    if not assume_yes:
        if not typer.confirm(f"Delete webhook '{name}'?", default=False):
            raise typer.Exit(0)

    try:
        with console.status(f"[bold cyan]Deleting webhook {name}...[/bold cyan]", spinner="dots2"):
            with _api() as client:
                try:
                    client.delete(f"/api/v1/workflow-triggers/{name}", params=_ns_params())
                except ApiError as exc:
                    if exc.status_code != 404:
                        raise
                client.delete(f"/api/v1/webhooks/{name}", params=_ns_params())
    except ApiError as exc:
        fatal(str(exc))
    success(f"Webhook [bold]{name}[/bold] deleted")


@webhooks_app.command("triggers")
def triggers_list() -> None:
    """List workflow triggers."""
    settings = get_settings()
    try:
        with console.status("[bold cyan]Loading triggers...[/bold cyan]", spinner="dots2"):
            with _api() as client:
                data = client.get("/api/v1/workflow-triggers", params=_ns_params())
    except ApiError as exc:
        fatal(str(exc))

    items = data if isinstance(data, list) else (data.get("triggers") or [])
    normalized = [
        {
            "name": item.get("name"),
            "source_ref": item.get("source_ref") or item.get("source_name"),
            "workflow": (item.get("workflow_ref") or {}).get("name") or item.get("target_workflow_name"),
            "status": "enabled" if item.get("enabled", True) else "disabled",
            "last_triggered": item.get("last_triggered"),
        }
        for item in items
        if isinstance(item, dict)
    ]
    print_table(
        normalized,
        columns=[
            ("NAME", "name"),
            ("SOURCE", "source_ref"),
            ("WORKFLOW", "workflow"),
            ("STATUS", "status"),
            ("LAST TRIGGERED", "last_triggered"),
        ],
        title="Workflow Triggers",
        output_format=settings.output_format,
    )


@webhooks_app.command("trigger-show")
def trigger_show(trigger_name: str = typer.Argument(..., help="Workflow trigger name.")) -> None:
    """Show workflow trigger details."""
    settings = get_settings()
    try:
        with console.status(f"[bold cyan]Loading trigger {trigger_name}...[/bold cyan]", spinner="dots2"):
            with _api() as client:
                data = client.get(f"/api/v1/workflow-triggers/{trigger_name}", params=_ns_params())
    except ApiError as exc:
        fatal(str(exc))
    print_detail(data, title=f"Trigger: {trigger_name}", output_format=settings.output_format)


@webhooks_app.command("dispatch")
def webhooks_dispatch(
    webhook_name: str = typer.Argument(..., help="Webhook name to invoke."),
    payload_str: str | None = typer.Option(None, "--payload", "-p", help="JSON payload body."),
) -> None:
    """Invoke a webhook receiver with a synthetic JSON payload."""
    import json as json_module

    settings = get_settings()
    payload: dict[str, Any] = {}
    if payload_str:
        try:
            payload = json_module.loads(payload_str)
        except json_module.JSONDecodeError as e:
            fatal(f"Invalid JSON payload: {e}")

    try:
        with console.status(f"[bold cyan]Dispatching webhook {webhook_name}...[/bold cyan]", spinner="dots2"):
            with _api() as client:
                data = client.post(
                    f"/api/v1/webhooks/{webhook_name}/invoke",
                    params=_ns_params(),
                    payload=payload,
                )
    except ApiError as exc:
        fatal(str(exc))

    if settings.output_format == "json":
        print_json_output(data)
        return
    success(f"Webhook [bold]{webhook_name}[/bold] dispatched")
    if isinstance(data, dict):
        if data.get("invocation_id"):
            console.print(f"  [dim]Invocation ID:[/dim] {data['invocation_id']}")
        if data.get("matched_triggers") is not None:
            console.print(f"  [dim]Matched triggers:[/dim] {data['matched_triggers']}")
