"""Main Typer application with global options and command registration."""

from __future__ import annotations

import typer
from rich.panel import Panel
from rich.text import Text

from agentctl import __version__
from agentctl.config import ResolvedSettings, resolve_settings
from agentctl.output import console, preferred_box

# ─── Global state shared across commands ───

_resolved: ResolvedSettings | None = None


def get_settings() -> ResolvedSettings:
    """Retrieve resolved settings for the current invocation."""
    if _resolved is None:
        return resolve_settings()
    return _resolved


# ─── Brand banner ───


def _show_banner() -> None:
    """Print the brand header panel."""
    name = Text("agentctl", style="bold bright_cyan")
    version = Text(f" v{__version__}", style="dim")
    tagline = Text("\nKubeSynapse CLI - Kubernetes-native AI agent operations", style="grey58")
    console.print(
        Panel(
            Text.assemble(name, version, tagline),
            box=preferred_box(),
            border_style="bright_black",
            padding=(1, 2),
        )
    )


# ─── App definition ───

app = typer.Typer(
    name="agentctl",
    help="KubeSynapse CLI - manage AI agents, workflows, and observability on Kubernetes.",
    invoke_without_command=True,
    rich_markup_mode="rich",
    pretty_exceptions_enable=True,
    pretty_exceptions_show_locals=False,
    epilog=(
        "[bold]Quick start:[/bold]\n"
        "  agentctl profile create demo --gateway http://localhost:8080\n"
        "  agentctl profile use demo\n"
        "  agentctl agents list\n"
        "  agentctl invoke my-agent \"Deploy nginx\"\n"
        "\n"
        "[bold]Shell completion:[/bold]\n"
        "  agentctl completion bash  | source  # bash/zsh\n"
        "  agentctl completion pwsh  | Invoke-Expression  # PowerShell\n"
        "  agentctl completion fish > ~/.config/fish/completions/agentctl.fish\n"
        "\n"
        "See [underline]docs/cli-architecture.md[/underline] for full documentation."
    ),
)


def version_callback(value: bool) -> None:
    if value:
        console.print(f"agentctl [bold cyan]{__version__}[/bold cyan]")
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
    """KubeSynapse CLI - Kubernetes-native AI agent operations."""
    global _resolved
    _resolved = resolve_settings(
        gateway_url=gateway_url,
        token=token,
        namespace=namespace,
        timeout=timeout,
        output_format=output,
        profile=profile,
    )

    if ctx.invoked_subcommand is None:
        _show_banner()
        console.print(ctx.get_help())
        raise typer.Exit()
