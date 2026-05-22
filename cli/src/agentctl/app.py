"""Main Typer application with global options and command registration."""

from __future__ import annotations

from typing import Optional

import typer
from rich.console import Console

from agentctl import __version__
from agentctl.config import resolve_settings, ResolvedSettings

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
)


def version_callback(value: bool) -> None:
    if value:
        Console().print(f"agentctl [bold cyan]{__version__}[/bold cyan]")
        raise typer.Exit()


@app.callback()
def main_callback(
    ctx: typer.Context,
    gateway_url: Optional[str] = typer.Option(
        None,
        "--gateway", "-g",
        envvar="AGENT_GATEWAY_URL",
        help="Gateway API base URL.",
    ),
    token: Optional[str] = typer.Option(
        None,
        "--token", "-t",
        envvar="AGENT_GATEWAY_TOKEN",
        help="Bearer token for authentication.",
    ),
    namespace: Optional[str] = typer.Option(
        None,
        "--namespace", "-n",
        envvar="AGENT_NAMESPACE",
        help="Target namespace.",
    ),
    profile: Optional[str] = typer.Option(
        None,
        "--profile", "-p",
        help="Configuration profile to use.",
    ),
    output: str = typer.Option(
        "table",
        "--output", "-o",
        help="Output format: table, json, yaml, wide, name.",
    ),
    timeout: Optional[float] = typer.Option(
        None,
        "--timeout",
        help="Request timeout in seconds.",
    ),
    _version: Optional[bool] = typer.Option(
        None,
        "--version", "-V",
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
