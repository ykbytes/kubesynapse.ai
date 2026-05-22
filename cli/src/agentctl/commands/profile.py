"""CLI profile management commands."""

from __future__ import annotations

import typer

from agentctl.config import (
    CONFIG_FILE,
    Profile,
    clear_token,
    load_config,
    load_token,
    save_config,
    save_token,
)
from agentctl.output import fatal, info, print_table, success

profile_app = typer.Typer(
    no_args_is_help=True,
    rich_markup_mode="rich",
    epilog=(
        "[bold]Examples:[/bold]\n"
        "  agentctl profile list\n"
        "  agentctl profile create demo --gateway http://localhost:8080\n"
        "  agentctl profile use demo\n"
        "  agentctl profile login --token my-token"
    ),
)


@profile_app.command("list")
def profile_list() -> None:
    """List all configured profiles."""
    config = load_config()
    items = []
    for name, p in config.profiles.items():
        items.append(
            {
                "name": name,
                "gateway_url": p.gateway_url,
                "namespace": p.namespace,
                "active": "*" if name == config.active_profile else "",
                "token": "yes" if load_token(name) else "no",
            }
        )
    print_table(
        items,
        columns=[
            ("", "active"),
            ("PROFILE", "name"),
            ("GATEWAY", "gateway_url"),
            ("NAMESPACE", "namespace"),
            ("TOKEN", "token"),
        ],
        title="Profiles",
        output_format="table",
    )
    info(f"Config: {CONFIG_FILE}")


@profile_app.command("use")
def profile_use(name: str = typer.Argument(..., help="Profile name to activate.")) -> None:
    """Switch to a different profile."""
    config = load_config()
    if name not in config.profiles:
        fatal(f"Profile '{name}' does not exist. Use 'profile create' first.")
    config.active_profile = name
    save_config(config)
    success(f"Switched to profile [bold]{name}[/bold]")


@profile_app.command("create")
def profile_create(
    name: str = typer.Argument(..., help="Profile name."),
    gateway_url: str = typer.Option("http://localhost:8080", "--gateway", "-g"),
    namespace: str = typer.Option("default", "--namespace", "-n"),
    timeout: float = typer.Option(60.0, "--timeout"),
    token: str | None = typer.Option(None, "--token", "-t", help="Save a token for this profile."),
) -> None:
    """Create a new connection profile."""
    config = load_config()
    if name in config.profiles:
        fatal(f"Profile '{name}' already exists. Use 'profile update' to modify.")

    config.profiles[name] = Profile(
        name=name,
        gateway_url=gateway_url,
        namespace=namespace,
        timeout=timeout,
    )
    save_config(config)

    if token:
        save_token(token, name)

    success(f"Profile [bold]{name}[/bold] created")


@profile_app.command("update")
def profile_update(
    name: str = typer.Argument(..., help="Profile name."),
    gateway_url: str | None = typer.Option(None, "--gateway", "-g"),
    namespace: str | None = typer.Option(None, "--namespace", "-n"),
    timeout: float | None = typer.Option(None, "--timeout"),
    token: str | None = typer.Option(None, "--token", "-t"),
) -> None:
    """Update an existing profile."""
    config = load_config()
    if name not in config.profiles:
        fatal(f"Profile '{name}' not found.")

    p = config.profiles[name]
    if gateway_url is not None:
        p.gateway_url = gateway_url
    if namespace is not None:
        p.namespace = namespace
    if timeout is not None:
        p.timeout = timeout
    save_config(config)

    if token is not None:
        save_token(token, name)

    success(f"Profile [bold]{name}[/bold] updated")


@profile_app.command("delete")
def profile_delete(
    name: str = typer.Argument(..., help="Profile name."),
    assume_yes: bool = typer.Option(False, "--yes", "-y"),
) -> None:
    """Delete a profile."""
    config = load_config()
    if name not in config.profiles:
        fatal(f"Profile '{name}' not found.")
    if name == config.active_profile and len(config.profiles) == 1:
        fatal("Cannot delete the only remaining profile.")

    if not assume_yes:
        if not typer.confirm(f"Delete profile '{name}'?", default=False):
            raise typer.Exit(0)

    del config.profiles[name]
    if config.active_profile == name:
        config.active_profile = next(iter(config.profiles))
    save_config(config)
    clear_token(name)
    success(f"Profile [bold]{name}[/bold] deleted")


@profile_app.command("login")
def profile_login(
    token: str = typer.Option(..., "--token", "-t", prompt=True, hide_input=True, help="Bearer token."),
    name: str | None = typer.Option(None, "--profile", "-p", help="Profile to save token to."),
) -> None:
    """Save a token for the active (or specified) profile."""
    config = load_config()
    target = name or config.active_profile
    if target not in config.profiles:
        fatal(f"Profile '{target}' not found.")
    save_token(token, target)
    success(f"Token saved for profile [bold]{target}[/bold]")


@profile_app.command("logout")
def profile_logout(
    name: str | None = typer.Option(None, "--profile", "-p"),
) -> None:
    """Clear saved token for a profile."""
    config = load_config()
    target = name or config.active_profile
    clear_token(target)
    success(f"Token cleared for profile [bold]{target}[/bold]")
