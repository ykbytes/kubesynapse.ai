"""Skills catalog and MCP tools commands."""

from __future__ import annotations

from typing import Any, Optional

import typer
from rich.markdown import Markdown
from rich.syntax import Syntax
from rich.table import Table
from rich import box

from agentctl.app import get_settings
from agentctl.client import ApiClient, ApiError
from agentctl.output import (
    console,
    print_table,
    print_detail,
    print_json_output,
    fatal,
)

skills_app = typer.Typer(no_args_is_help=True, rich_markup_mode="rich")


def _api() -> ApiClient:
    return ApiClient(get_settings())


# ─── Skills Catalog ───


@skills_app.command("list")
def skills_list(
    category: str = typer.Option("", "--category", "-c", help="Filter by category."),
    search: str = typer.Option("", "--search", "-s", help="Search by name or description."),
) -> None:
    """List skills from the catalog."""
    settings = get_settings()
    params: dict[str, Any] = {}
    if category:
        params["category"] = category
    if search:
        params["search"] = search

    try:
        with console.status("[bold cyan]Loading skills catalog...[/bold cyan]"):
            with _api() as client:
                data = client.get("/api/skills/catalog", params=params)
    except ApiError as exc:
        fatal(str(exc))

    if settings.output_format == "json":
        print_json_output(data)
        return

    items = data.get("skills", []) if isinstance(data, dict) else data
    if not items:
        console.print("[dim]No skills found.[/dim]")
        return

    table = Table(title="Skills Catalog", border_style="bright_black")
    table.add_column("ID", style="bold")
    table.add_column("NAME")
    table.add_column("CATEGORY", style="cyan")
    table.add_column("FILES", justify="right")
    table.add_column("DESCRIPTION")
    for skill in items:
        table.add_row(
            skill.get("id", ""),
            skill.get("name", ""),
            skill.get("category", ""),
            str(len(skill.get("files", []))),
            (skill.get("description", "") or "")[:60],
        )
    console.print(table)
    console.print(f"[dim]{len(items)} skill(s) found[/dim]")


@skills_app.command("show")
def skills_show(
    skill_id: str = typer.Argument(..., help="The skill ID to inspect."),
) -> None:
    """Show details for a specific skill."""
    settings = get_settings()
    try:
        with console.status(f"[bold cyan]Loading skill {skill_id}...[/bold cyan]"):
            with _api() as client:
                data = client.get(f"/api/skills/catalog/{skill_id}")
    except ApiError as exc:
        fatal(str(exc))

    if settings.output_format == "json":
        print_json_output(data)
        return

    print_detail(
        data,
        title=f"Skill: {data.get('name', skill_id)}",
        output_format="table",
        fields=[
            ("ID", "id"),
            ("Category", "category"),
            ("Tags", "tags"),
            ("Description", "description"),
            ("Files", "files"),
            ("Total Size", "total_size_bytes"),
        ],
    )

    assets = data.get("assets", {})
    for path, content in assets.items():
        console.print(f"\n[bold cyan]-- {path} --[/bold cyan]")
        if path.endswith(".md"):
            console.print(Markdown(content[:2000]))
        else:
            console.print(Syntax(content[:2000], "text", theme="monokai"))


# ─── MCP Tools ───


@skills_app.command("tools")
def tools_list() -> None:
    """List available MCP tool sidecar categories."""
    settings = get_settings()
    try:
        with console.status("[bold cyan]Loading tools...[/bold cyan]"):
            with _api() as client:
                data = client.get("/api/skills/tools")
    except ApiError as exc:
        fatal(str(exc))

    if settings.output_format == "json":
        print_json_output(data)
        return

    categories = data.get("categories", []) if isinstance(data, dict) else data
    if not categories:
        console.print("[dim]No tool categories available.[/dim]")
        return

    table = Table(title="MCP Tool Sidecars", border_style="bright_black")
    table.add_column("ID", style="bold")
    table.add_column("NAME")
    table.add_column("PORT", justify="right", style="cyan")
    table.add_column("DESCRIPTION")
    for cat in categories:
        table.add_row(
            cat.get("id", ""),
            cat.get("name", ""),
            str(cat.get("default_port", "")),
            (cat.get("description", "") or "")[:60],
        )
    console.print(table)


@skills_app.command("hub")
def tools_hub() -> None:
    """List shared MCP hub servers available for agents."""
    settings = get_settings()
    try:
        with console.status("[bold cyan]Loading MCP hub...[/bold cyan]"):
            with _api() as client:
                data = client.get("/api/mcp-hub/servers")
    except ApiError as exc:
        fatal(str(exc))

    if settings.output_format == "json":
        print_json_output(data)
        return

    items = data if isinstance(data, list) else []
    if not items:
        console.print("[dim]No shared MCP hub servers configured.[/dim]")
        return

    table = Table(title="MCP Hub Servers", border_style="bright_black")
    table.add_column("NAME", style="bold")
    table.add_column("TRANSPORT", style="cyan")
    table.add_column("URL / COMMAND")
    table.add_column("DESCRIPTION")
    for srv in items:
        table.add_row(
            str(srv.get("name") or srv.get("id", "")),
            str(srv.get("transport", "stdio")),
            str(srv.get("url") or srv.get("command", "-")),
            str(srv.get("description", ""))[:60],
        )
    console.print(table)
