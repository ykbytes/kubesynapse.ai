"""Authentication commands — login, logout, register, me, change-password."""

from __future__ import annotations

from typing import Any, Optional

import typer
from rich.panel import Panel
from rich.table import Table
from rich import box

from agentctl.app import get_settings
from agentctl.client import ApiClient, ApiError
from agentctl.config import save_token, clear_token, load_config
from agentctl.output import (
    console,
    print_detail,
    print_json_output,
    success,
    info,
    fatal,
)

auth_app = typer.Typer(no_args_is_help=True, rich_markup_mode="rich")


def _api() -> ApiClient:
    return ApiClient(get_settings())


@auth_app.command("login")
def auth_login(
    username: str = typer.Option(..., "--username", "-u", prompt=True, help="Username."),
    password: str = typer.Option(..., "--password", "-p", prompt=True, hide_input=True, help="Password."),
    provider: str = typer.Option("local", "--provider", help="Auth provider: local or ldap."),
    save: bool = typer.Option(True, "--save/--no-save", help="Persist the token to the active profile."),
) -> None:
    """Login and obtain an access token."""
    settings = get_settings()
    payload: dict[str, Any] = {"username": username, "password": password, "provider": provider}

    try:
        with console.status("[bold cyan]Logging in...[/bold cyan]"):
            with _api() as client:
                data = client.post("/api/auth/login", payload=payload)
    except ApiError as exc:
        fatal(str(exc))

    if settings.output_format == "json":
        print_json_output(data)
        return

    token = data.get("access_token") or data.get("token", "")
    role = data.get("role", "-")
    display_user = data.get("username", username)

    if save and token:
        config = load_config()
        save_token(token, config.active_profile)
        success(f"Logged in as [bold]{display_user}[/bold] (role: {role}) — token saved to profile")
    else:
        success(f"Logged in as [bold]{display_user}[/bold] (role: {role})")
        if token:
            console.print(f"[dim]Token:[/dim] {token[:20]}...")
            console.print("[dim]Export: AGENT_GATEWAY_TOKEN=<token>[/dim]")


@auth_app.command("logout")
def auth_logout(
    revoke: bool = typer.Option(True, "--revoke/--local-only", help="Revoke session on server."),
) -> None:
    """Logout — revoke session and clear saved token."""
    settings = get_settings()
    config = load_config()

    if revoke:
        try:
            with console.status("[bold cyan]Logging out...[/bold cyan]"):
                with _api() as client:
                    client.post("/api/auth/logout")
        except ApiError:
            pass  # Best-effort revocation

    clear_token(config.active_profile)
    success("Logged out — token cleared")


@auth_app.command("register")
def auth_register(
    username: str = typer.Option(..., "--username", "-u", prompt=True, help="Username (3-128 chars)."),
    password: str = typer.Option(
        ..., "--password", "-p", prompt=True, hide_input=True, confirmation_prompt=True, help="Password (8+ chars)."
    ),
    email: Optional[str] = typer.Option(None, "--email", help="Email address."),
    display_name: Optional[str] = typer.Option(None, "--display-name", help="Display name."),
) -> None:
    """Register a new local user account."""
    settings = get_settings()
    payload: dict[str, Any] = {"username": username, "password": password}
    if email:
        payload["email"] = email
    if display_name:
        payload["display_name"] = display_name

    try:
        with console.status("[bold cyan]Registering...[/bold cyan]"):
            with _api() as client:
                data = client.post("/api/auth/register", payload=payload)
    except ApiError as exc:
        fatal(str(exc))

    if settings.output_format == "json":
        print_json_output(data)
        return
    success(f"Registered [bold]{data.get('username', username)}[/bold] (role: {data.get('role', '-')})")


@auth_app.command("me")
def auth_me() -> None:
    """Show the current authenticated user."""
    settings = get_settings()
    try:
        with console.status("[bold cyan]Loading user context...[/bold cyan]"):
            with _api() as client:
                data = client.get("/api/auth/me")
    except ApiError as exc:
        fatal(str(exc))

    if settings.output_format == "json":
        print_json_output(data)
        return

    user = data.get("user", data) if isinstance(data, dict) else data
    if isinstance(user, dict):
        table = Table(show_header=False, box=box.SIMPLE_HEAVY, border_style="bright_cyan")
        table.add_column("", style="bold magenta")
        table.add_column("")
        table.add_row("Username", str(user.get("username") or user.get("preferred_username", "-")))
        table.add_row("Role", str(user.get("role", "-")))
        table.add_row("Auth Provider", str(user.get("auth_provider", "-")))
        namespaces = user.get("allowed_namespaces", [])
        table.add_row("Namespaces", ", ".join(namespaces) if namespaces else "*")
        email = user.get("email")
        if email:
            table.add_row("Email", str(email))
        console.print(Panel(table, title="Current User", border_style="bright_cyan"))
    else:
        print_detail(data, title="Current User", output_format=settings.output_format)


@auth_app.command("change-password")
def auth_change_password(
    current_password: str = typer.Option(..., "--current", prompt=True, hide_input=True, help="Current password."),
    new_password: str = typer.Option(
        ..., "--new", prompt=True, hide_input=True, confirmation_prompt=True, help="New password (8+ chars)."
    ),
) -> None:
    """Change your password (local users only)."""
    settings = get_settings()
    try:
        with console.status("[bold cyan]Updating password...[/bold cyan]"):
            with _api() as client:
                client.post("/api/auth/change-password", payload={
                    "current_password": current_password,
                    "new_password": new_password,
                })
    except ApiError as exc:
        fatal(str(exc))
    success("Password updated successfully")


@auth_app.command("config")
def auth_config() -> None:
    """Show the gateway authentication configuration."""
    settings = get_settings()
    try:
        with console.status("[bold cyan]Loading auth config...[/bold cyan]"):
            with _api() as client:
                data = client.get("/api/auth/config")
    except ApiError as exc:
        fatal(str(exc))
    print_detail(data, title="Authentication Configuration", output_format=settings.output_format)
