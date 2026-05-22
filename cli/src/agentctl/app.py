"""Main Typer application with global options and command registration."""

from __future__ import annotations

import typer
from rich.console import Console

from agentctl import __version__
from agentctl.config import ResolvedSettings, resolve_settings

# ─── Global state shared across commands ───

_resolved: ResolvedSettings | None = None


def get_settings() -> ResolvedSettings:
    """Retrieve resolved settings for the current invocation."""
    if _resolved is None:
        return resolve_settings()
    return _resolved


# ─── App definition ───

app = typer.Typer(
    name="agentctl",
    help="KubeSynapse CLI — manage AI agents, workflows, and observability on Kubernetes.",
    no_args_is_help=True,
    rich_markup_mode="rich",
    pretty_exceptions_enable=True,
    pretty_exceptions_show_locals=False,
    epilog=(
        "[bold]Quick start:[/bold]\n"
        "  agentctl profile create demo --gateway http://localhost:8080\n"
        "  agentctl profile use demo\n"
        "  agentctl agents list\n"
        "  agentctl invoke my-agent \"Deploy nginx\"\n"
        "See [underline]docs/cli-architecture.md[/underline] for full documentation."
    ),
)


def version_callback(value: bool) -> None:
    if value:
        Console().print(f"agentctl [bold cyan]{__version__}[/bold cyan]")
        raise typer.Exit()


@app.callback()
def main_callback(
    ctx: typer.Context,
    gateway_url: str | None = typer.Option(
        None,
        "--gateway",
        "-g",
        envvar="AGENT_GATEWAY_URL",
        help="Gateway API base URL.",
    ),
    token: str | None = typer.Option(
        None,
        "--token",
        "-t",
        envvar="AGENT_GATEWAY_TOKEN",
        help="Bearer token for authentication.",
    ),
    namespace: str | None = typer.Option(
        None,
        "--namespace",
        "-n",
        envvar="AGENT_NAMESPACE",
        help="Target namespace.",
    ),
    profile: str | None = typer.Option(
        None,
        "--profile",
        "-p",
        help="Configuration profile to use.",
    ),
    output: str = typer.Option(
        "table",
        "--output",
        "-o",
        help="Output format: table, json, yaml, wide, name.",
    ),
    timeout: float | None = typer.Option(
        None,
        "--timeout",
        help="Request timeout in seconds.",
    ),
    _version: bool | None = typer.Option(
        None,
        "--version",
        "-V",
        callback=version_callback,
        is_eager=True,
        help="Show version and exit.",
    ),
) -> None:
    """KubeSynapse CLI — Kubernetes-native AI agent operations."""
    global _resolved
    _resolved = resolve_settings(
        gateway_url=gateway_url,
        token=token,
        namespace=namespace,
        timeout=timeout,
        output_format=output,
        profile=profile,
    )
