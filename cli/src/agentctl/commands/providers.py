"""Provider and LLM model management commands."""

from __future__ import annotations

from typing import Any

import typer

from agentctl.app import get_settings
from agentctl.client import ApiClient, ApiError
from agentctl.output import (
    console,
    fatal,
    print_detail,
    print_json_output,
    print_table,
)

providers_app = typer.Typer(
    no_args_is_help=True,
    rich_markup_mode="rich",
    epilog=(
        "[bold]Examples:[/bold]\n"
        "  agentctl providers list\n"
        "  agentctl providers show github-copilot\n"
        "  agentctl providers models github-copilot\n"
        "  agentctl providers health github-copilot"
    ),
)


def _api() -> ApiClient:
    return ApiClient(get_settings())


def _fetch_provider_registry() -> list[dict[str, Any]]:
    with _api() as client:
        data = client.get("/api/v1/providers")
    return data.get("providers") or [] if isinstance(data, dict) else []


def _provider_row(provider: dict[str, Any]) -> dict[str, Any]:
    models = provider.get("models") or []
    return {
        "id": str(provider.get("id", "")),
        "name": str(provider.get("label") or provider.get("id") or "-"),
        "type": str(provider.get("kind") or "-"),
        "status": "connected" if provider.get("connected") else "disconnected",
        "model_count": len(models) if isinstance(models, list) else 0,
        "endpoint": str(provider.get("base_url") or "-"),
        "auth_type": str(provider.get("auth_type") or "-"),
        "docs_url": str(provider.get("docs_url") or "-"),
        "editable": bool(provider.get("editable", False)),
        "description": str(provider.get("description") or ""),
    }


@providers_app.command("list")
def providers_list() -> None:
    """List all configured LLM providers."""
    settings = get_settings()
    try:
        with console.status("[bold cyan]Loading providers...[/bold cyan]", spinner="dots2"):
            items = [_provider_row(item) for item in _fetch_provider_registry()]
    except ApiError as exc:
        fatal(str(exc))

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
        with console.status(f"[bold cyan]Loading provider {name}...[/bold cyan]", spinner="dots2"):
            registry = _fetch_provider_registry()
    except ApiError as exc:
        fatal(str(exc))

    for provider in registry:
        if str(provider.get("id") or "") == name:
            row = _provider_row(provider)
            row["models"] = [m.get("id") for m in (provider.get("models") or []) if isinstance(m, dict)]
            print_detail(
                row,
                title=f"Provider: {name}",
                output_format=settings.output_format,
                fields=[
                    ("Name", "name"),
                    ("ID", "id"),
                    ("Type", "type"),
                    ("Status", "status"),
                    ("Auth Type", "auth_type"),
                    ("Editable", "editable"),
                    ("Endpoint", "endpoint"),
                    ("Docs", "docs_url"),
                    ("Description", "description"),
                    ("Models", "models"),
                ],
            )
            return

    fatal(f"Provider '{name}' not found.")


@providers_app.command("models")
def providers_models(
    name: str = typer.Argument(..., help="Provider name."),
) -> None:
    """List models available from a provider."""
    settings = get_settings()
    try:
        with console.status(f"[bold cyan]Loading models for {name}...[/bold cyan]", spinner="dots2"):
            with _api() as client:
                data = client.get(f"/api/v1/providers/{name}/models")
    except ApiError as exc:
        fatal(str(exc))

    raw_items = data.get("models") or [] if isinstance(data, dict) else []
    items = [
        {
            "id": str(item.get("id") or ""),
            "name": str(item.get("name") or item.get("id") or ""),
            "description": str(item.get("description") or "-"),
        }
        for item in raw_items
        if isinstance(item, dict)
    ]
    print_table(
        items,
        columns=[
            ("MODEL ID", "id"),
            ("NAME", "name"),
            ("DESCRIPTION", "description"),
        ],
        title=f"Models: {name}",
        output_format=settings.output_format,
    )


@providers_app.command("health")
def providers_health(
    name: str = typer.Argument(..., help="Provider name."),
) -> None:
    """Check provider connectivity based on the provider registry."""
    settings = get_settings()
    try:
        with console.status(f"[bold cyan]Checking {name} health...[/bold cyan]", spinner="dots2"):
            registry = _fetch_provider_registry()
    except ApiError as exc:
        fatal(str(exc))

    for provider in registry:
        if str(provider.get("id") or "") == name:
            data = {
                "status": "healthy" if provider.get("connected") else "disconnected",
                "provider": name,
                "auth_type": provider.get("auth_type"),
                "editable": provider.get("editable"),
                "models": len(provider.get("models") or []),
                "endpoint": provider.get("base_url"),
            }
            if settings.output_format == "json":
                print_json_output(data)
                return
            print_detail(
                data,
                title=f"Provider Health: {name}",
                output_format=settings.output_format,
                fields=[
                    ("Status", "status"),
                    ("Provider", "provider"),
                    ("Auth Type", "auth_type"),
                    ("Editable", "editable"),
                    ("Models", "models"),
                    ("Endpoint", "endpoint"),
                ],
            )
            return

    fatal(f"Provider '{name}' not found.")
