"""Provider and LLM model management commands."""

from __future__ import annotations

from typing import Any, Optional

import typer

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

providers_app = typer.Typer(no_args_is_help=True, rich_markup_mode="rich")


def _api() -> ApiClient:
    return ApiClient(get_settings())


@providers_app.command("list")
def providers_list() -> None:
    """List all configured LLM providers."""
    settings = get_settings()
    try:
        with console.status("[bold cyan]Loading providers...[/bold cyan]"):
            with _api() as client:
                data = client.get("/api/providers")
    except ApiError as exc:
        fatal(str(exc))

    items = data if isinstance(data, list) else (data.get("providers") or [])
    print_table(
        items,
        columns=[
            ("NAME", "name"),
            ("TYPE", "type"),
            ("STATUS", "status"),
            ("MODELS", "model_count"),
            ("ENDPOINT", "endpoint"),
        ],
        title="LLM Providers",
        output_format=settings.output_format,
    )


@providers_app.command("show")
def providers_show(
    name: str = typer.Argument(..., help="Provider name."),
) -> None:
    """Show provider details and configuration."""
    settings = get_settings()
    try:
        with console.status(f"[bold cyan]Loading provider {name}...[/bold cyan]"):
            with _api() as client:
                data = client.get(f"/api/providers/{name}")
    except ApiError as exc:
        fatal(str(exc))
    print_detail(data, title=f"Provider: {name}", output_format=settings.output_format)


@providers_app.command("models")
def providers_models(
    name: str = typer.Argument(..., help="Provider name."),
) -> None:
    """List models available from a provider."""
    settings = get_settings()
    try:
        with console.status(f"[bold cyan]Loading models for {name}...[/bold cyan]"):
            with _api() as client:
                data = client.get(f"/api/providers/{name}/models")
    except ApiError as exc:
        fatal(str(exc))

    items = data if isinstance(data, list) else (data.get("models") or [])
    print_table(
        items,
        columns=[
            ("MODEL ID", "id"),
            ("CONTEXT", "context_window"),
            ("MAX TOKENS", "max_tokens"),
            ("STATUS", "status"),
        ],
        wide_columns=[
            ("PRICING", "pricing"),
            ("SUPPORTED", "features"),
        ],
        title=f"Models: {name}",
        output_format=settings.output_format,
    )


@providers_app.command("health")
def providers_health(
    name: str = typer.Argument(..., help="Provider name."),
) -> None:
    """Check provider connectivity and health."""
    settings = get_settings()
    try:
        with console.status(f"[bold cyan]Checking {name} health...[/bold cyan]"):
            with _api() as client:
                data = client.get(f"/api/providers/{name}/health")
    except ApiError as exc:
        fatal(str(exc))

    if settings.output_format == "json":
        print_json_output(data)
        return

    status = data.get("status", "unknown")
    style = "bold green" if status == "healthy" else "bold red"
    console.print(f"[{style}]Provider {name}: {status}[/{style}]")
    for k, v in (data.get("details") or {}).items():
        console.print(f"  [dim]{k}:[/dim] {v}")
