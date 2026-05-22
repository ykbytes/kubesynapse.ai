"""Admin commands — user management (requires admin role)."""

from __future__ import annotations

from typing import Any

import typer
from rich.table import Table
from rich.text import Text

from agentctl.app import get_settings
from agentctl.client import ApiClient, ApiError
from agentctl.output import (
    console,
    fatal,
    print_json_output,
    success,
)

admin_app = typer.Typer(
    no_args_is_help=True,
    rich_markup_mode="rich",
    epilog=(
        "[bold]Examples:[/bold]\n"
        "  agentctl admin users\n"
        "  agentctl admin user-create admin2 --role admin\n"
        "  agentctl admin user-update admin2 --suspended\n"
        "  agentctl admin user-delete old-user --yes"
    ),
)


def _api() -> ApiClient:
    return ApiClient(get_settings())


@admin_app.command("users")
def admin_users_list() -> None:
    """List all local users (admin only)."""
    settings = get_settings()
    try:
        with console.status("[bold cyan]Loading users...[/bold cyan]"):
            with _api() as client:
                data = client.get("/api/admin/users")
    except ApiError as exc:
        fatal(str(exc))

    if settings.output_format == "json":
        print_json_output(data)
        return

    items = data if isinstance(data, list) else []
    if not items:
        console.print("[dim]No users found.[/dim]")
        return

    table = Table(title="Users", border_style="bright_black")
    table.add_column("ID", style="dim", justify="right")
    table.add_column("USERNAME", style="bold")
    table.add_column("ROLE", style="cyan")
    table.add_column("ACTIVE")
    table.add_column("PROVIDER", style="dim")
    table.add_column("NAMESPACES")
    for user in items:
        active = bool(user.get("is_active", True))
        ns_list = user.get("allowed_namespaces") or []
        table.add_row(
            str(user.get("id", "")),
            str(user.get("username", "")),
            str(user.get("role", "")),
            Text("YES", style="bold green") if active else Text("NO", style="bold red"),
            str(user.get("auth_provider", "local")),
            ", ".join(str(n) for n in ns_list) if ns_list else "-",
        )
    console.print(table)


@admin_app.command("user-create")
def admin_user_create(
    username: str = typer.Option(..., "--username", "-u", prompt=True, help="Username (3-128 chars)."),
    password: str = typer.Option(
        ..., "--password", "-p", prompt=True, hide_input=True, confirmation_prompt=True, help="Password (8+ chars)."
    ),
    role: str = typer.Option("viewer", "--role", help="Role: viewer, operator, or admin."),
    email: str | None = typer.Option(None, "--email", help="Email address."),
    display_name: str | None = typer.Option(None, "--display-name", help="Display name."),
    allowed_namespaces: list[str] | None = typer.Option(
        None, "--namespace", help="Allowed namespaces (repeatable)."
    ),
) -> None:
    """Create a new local user (admin only)."""
    settings = get_settings()
    if role not in {"viewer", "operator", "admin"}:
        fatal("--role must be viewer, operator, or admin.")

    payload: dict[str, Any] = {"username": username, "password": password, "role": role}
    if email:
        payload["email"] = email
    if display_name:
        payload["display_name"] = display_name
    if allowed_namespaces:
        payload["allowed_namespaces"] = allowed_namespaces

    try:
        with console.status(f"[bold cyan]Creating user {username}...[/bold cyan]"):
            with _api() as client:
                data = client.post("/api/admin/users", payload=payload)
    except ApiError as exc:
        fatal(str(exc))

    if settings.output_format == "json":
        print_json_output(data)
        return
    success(f"User [bold]{username}[/bold] created (role: {role})")


@admin_app.command("user-update")
def admin_user_update(
    user_id: int = typer.Argument(..., help="User ID to update."),
    role: str | None = typer.Option(None, "--role", help="New role: viewer, operator, or admin."),
    display_name: str | None = typer.Option(None, "--display-name", help="New display name."),
    active: bool | None = typer.Option(None, "--active/--inactive", help="Enable or disable."),
    allowed_namespaces: list[str] | None = typer.Option(
        None, "--namespace", help="Allowed namespaces (repeatable)."
    ),
) -> None:
    """Update a local user (admin only)."""
    settings = get_settings()
    if role is not None and role not in {"viewer", "operator", "admin"}:
        fatal("--role must be viewer, operator, or admin.")

    payload: dict[str, Any] = {}
    if role is not None:
        payload["role"] = role
    if display_name is not None:
        payload["display_name"] = display_name
    if active is not None:
        payload["is_active"] = active
    if allowed_namespaces is not None:
        payload["allowed_namespaces"] = allowed_namespaces
    if not payload:
        fatal("Provide at least one field to update.")

    try:
        with console.status(f"[bold cyan]Updating user {user_id}...[/bold cyan]"):
            with _api() as client:
                data = client.patch(f"/api/admin/users/{user_id}", payload=payload)
    except ApiError as exc:
        fatal(str(exc))

    if settings.output_format == "json":
        print_json_output(data)
        return
    success(f"User {user_id} updated")


@admin_app.command("user-delete")
def admin_user_delete(
    user_id: int = typer.Argument(..., help="User ID to delete."),
    assume_yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation."),
) -> None:
    """Delete a local user (admin only)."""
    if not assume_yes:
        if not typer.confirm(f"Delete user ID {user_id}?", default=False):
            raise typer.Exit(0)

    try:
        with console.status(f"[bold cyan]Deleting user {user_id}...[/bold cyan]"):
            with _api() as client:
                client.delete(f"/api/admin/users/{user_id}")
    except ApiError as exc:
        fatal(str(exc))
    success(f"User {user_id} deleted")
