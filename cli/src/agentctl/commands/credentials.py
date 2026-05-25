"""Credential management commands — git and GitHub credentials for agents."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import typer

from agentctl.app import get_settings
from agentctl.client import ApiClient, ApiError
from agentctl.output import (
    console,
    fatal,
    print_detail,
    print_json_output,
    success,
)

credentials_app = typer.Typer(
    no_args_is_help=True,
    rich_markup_mode="rich",
    epilog=(
        "[bold]Examples:[/bold]\n"
        "  agentctl credentials git-show my-agent\n"
        "  agentctl credentials git-set my-agent --url git.example.com\n"
        "  agentctl credentials git-delete my-agent -y\n"
        "  agentctl credentials github-show my-agent"
    ),
)


def _api() -> ApiClient:
    return ApiClient(get_settings())


def _ns_params() -> dict[str, Any]:
    return {"namespace": get_settings().namespace}


# ─── Git Credentials ───


@credentials_app.command("git-set")
def credentials_git_set(
    agent_name: str = typer.Argument(..., help="Agent name."),
    auth_method: str = typer.Option(..., "--method", help="Auth method: token, basic, or ssh."),
    token: str | None = typer.Option(None, "--token", help="Personal access token (method=token)."),
    username: str | None = typer.Option(None, "--username", help="Username (method=basic)."),
    password: str | None = typer.Option(None, "--password", help="Password (method=basic)."),
    ssh_key_file: Path | None = typer.Option(
        None, "--ssh-key-file", exists=True, file_okay=True, dir_okay=False, help="SSH private key file (method=ssh)."
    ),
) -> None:
    """Create or replace git credentials for an agent."""
    settings = get_settings()
    if auth_method not in {"token", "basic", "ssh"}:
        fatal("--method must be token, basic, or ssh.")

    payload: dict[str, Any] = {"auth_method": auth_method}
    if auth_method == "token":
        if not token:
            token = typer.prompt("Git token", hide_input=True)
        payload["token"] = token
    elif auth_method == "basic":
        if not username:
            username = typer.prompt("Git username")
        if not password:
            password = typer.prompt("Git password", hide_input=True)
        payload["username"] = username
        payload["password"] = password
    elif auth_method == "ssh":
        if not ssh_key_file:
            fatal("--ssh-key-file is required for ssh auth method.")
        payload["ssh_private_key"] = ssh_key_file.read_text(encoding="utf-8")

    try:
        with console.status(f"[bold cyan]Setting git credentials for {agent_name}...[/bold cyan]", spinner="dots2"):
            with _api() as client:
                data = client.post(
                    f"/api/agents/{agent_name}/git-credentials",
                    params=_ns_params(),
                    payload=payload,
                )
    except ApiError as exc:
        fatal(str(exc))

    if settings.output_format == "json":
        print_json_output(data)
        return
    success(f"Git credentials ({auth_method}) configured for [bold]{agent_name}[/bold]")


@credentials_app.command("git-show")
def credentials_git_show(
    agent_name: str = typer.Argument(..., help="Agent name."),
) -> None:
    """Show git credential metadata for an agent."""
    settings = get_settings()
    try:
        with console.status(f"[bold cyan]Loading git credentials for {agent_name}...[/bold cyan]", spinner="dots2"):
            with _api() as client:
                data = client.get(
                    f"/api/agents/{agent_name}/git-credentials",
                    params=_ns_params(),
                )
    except ApiError as exc:
        fatal(str(exc))
    print_detail(data, title=f"Git Credentials: {agent_name}", output_format=settings.output_format)


@credentials_app.command("git-delete")
def credentials_git_delete(
    agent_name: str = typer.Argument(..., help="Agent name."),
    assume_yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation."),
) -> None:
    """Delete git credentials for an agent."""
    if not assume_yes:
        if not typer.confirm(f"Delete git credentials for agent '{agent_name}'?", default=False):
            raise typer.Exit(0)

    try:
        with console.status(f"[bold cyan]Deleting git credentials for {agent_name}...[/bold cyan]", spinner="dots2"):
            with _api() as client:
                client.delete(f"/api/agents/{agent_name}/git-credentials", params=_ns_params())
    except ApiError as exc:
        fatal(str(exc))
    success(f"Git credentials removed for [bold]{agent_name}[/bold]")


# ─── GitHub Credentials ───


@credentials_app.command("github-set")
def credentials_github_set(
    agent_name: str = typer.Argument(..., help="Agent name."),
    token: str = typer.Option("", "--token", help="GitHub personal access token."),
) -> None:
    """Create or replace GitHub MCP credentials for an agent."""
    settings = get_settings()
    if not token:
        token = typer.prompt("GitHub token", hide_input=True)

    try:
        with console.status(f"[bold cyan]Setting GitHub credentials for {agent_name}...[/bold cyan]", spinner="dots2"):
            with _api() as client:
                data = client.post(
                    f"/api/agents/{agent_name}/github-credentials",
                    params=_ns_params(),
                    payload={"token": token},
                )
    except ApiError as exc:
        fatal(str(exc))

    if settings.output_format == "json":
        print_json_output(data)
        return
    success(f"GitHub credentials configured for [bold]{agent_name}[/bold]")


@credentials_app.command("github-show")
def credentials_github_show(
    agent_name: str = typer.Argument(..., help="Agent name."),
) -> None:
    """Show GitHub credential metadata for an agent."""
    settings = get_settings()
    try:
        with console.status(f"[bold cyan]Loading GitHub credentials for {agent_name}...[/bold cyan]", spinner="dots2"):
            with _api() as client:
                data = client.get(
                    f"/api/agents/{agent_name}/github-credentials",
                    params=_ns_params(),
                )
    except ApiError as exc:
        fatal(str(exc))
    print_detail(data, title=f"GitHub Credentials: {agent_name}", output_format=settings.output_format)


@credentials_app.command("github-delete")
def credentials_github_delete(
    agent_name: str = typer.Argument(..., help="Agent name."),
    assume_yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation."),
) -> None:
    """Delete GitHub MCP credentials for an agent."""
    if not assume_yes:
        if not typer.confirm(f"Delete GitHub credentials for agent '{agent_name}'?", default=False):
            raise typer.Exit(0)

    try:
        with console.status(f"[bold cyan]Deleting GitHub credentials for {agent_name}...[/bold cyan]", spinner="dots2"):
            with _api() as client:
                client.delete(f"/api/agents/{agent_name}/github-credentials", params=_ns_params())
    except ApiError as exc:
        fatal(str(exc))
    success(f"GitHub credentials removed for [bold]{agent_name}[/bold]")
