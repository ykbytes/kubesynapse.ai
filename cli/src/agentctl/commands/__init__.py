"""Command group registration."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import typer


def register_all(app: typer.Typer) -> None:
    """Register all command groups and top-level commands on the main app."""
    import typer as _typer

    from agentctl.commands.admin import admin_app
    from agentctl.commands.agents import agents_app
    from agentctl.commands.artifacts import artifacts_app
    from agentctl.commands.auth import auth_app
    from agentctl.commands.chat import chat_app
    from agentctl.commands.credentials import credentials_app
    from agentctl.commands.observatory import observatory_app
    from agentctl.commands.profile import profile_app
    from agentctl.commands.providers import providers_app
    from agentctl.commands.runs import runs_app
    from agentctl.commands.skills import skills_app
    from agentctl.commands.webhooks import webhooks_app
    from agentctl.commands.workflows import workflows_app

    # Core command groups
    app.add_typer(agents_app, name="agents", help="Manage AI agents.")
    app.add_typer(workflows_app, name="workflows", help="Manage workflows and DAGs.")
    app.add_typer(runs_app, name="runs", help="Approvals, policies, and apply.")
    app.add_typer(observatory_app, name="observatory", help="Observability -- metrics, traces, alerts.")
    app.add_typer(chat_app, name="chat", help="Interactive agent chat sessions.")
    app.add_typer(webhooks_app, name="webhooks", help="Manage webhooks and triggers.")

    # Management groups
    app.add_typer(auth_app, name="auth", help="Authentication and sessions.")
    app.add_typer(admin_app, name="admin", help="Admin operations (requires admin role).")
    app.add_typer(credentials_app, name="credentials", help="Manage agent git/GitHub credentials.")
    app.add_typer(skills_app, name="skills", help="Skills catalog and MCP tools.")
    app.add_typer(profile_app, name="profile", help="CLI configuration profiles.")

    # Asset groups
    app.add_typer(artifacts_app, name="artifacts", help="Manage workflow and agent artifacts.")
    app.add_typer(providers_app, name="providers", help="LLM provider and model management.")

    # ─── Top-level commands ───

    @app.command("health")
    def health() -> None:
        """Check API gateway health."""
        from agentctl.app import get_settings
        from agentctl.client import ApiClient, ApiError
        from agentctl.output import console, fatal, print_detail

        settings = get_settings()
        try:
            with console.status("[bold cyan]Checking gateway health...[/bold cyan]"):
                with ApiClient(settings) as client:
                    data = client.get("/api/health")
        except ApiError as exc:
            fatal(str(exc))

        print_detail(
            data,
            title="Gateway Health",
            output_format=settings.output_format,
            fields=[
                ("Status", "status"),
                ("Gateway", "gateway"),
                ("Auth Mode", "auth_mode"),
                ("NATS", "nats_url"),
                ("Qdrant", "qdrant_url"),
            ],
        )

    @app.command("apply")
    def apply_cmd(
        file_path: Path = _typer.Argument(..., exists=True, file_okay=True, dir_okay=False, help="Resource file."),
    ) -> None:
        """Create or update a resource from a file (auto-detects kind)."""
        from agentctl.commands.runs import apply

        apply(file_path)

    @app.command("invoke")
    def invoke_cmd(
        agent_name: str = _typer.Argument(..., help="Agent name."),
        prompt_parts: list[str] | None = _typer.Argument(None, help="Prompt text."),
        stream: bool = _typer.Option(False, "--stream", "-s", help="Use SSE streaming."),
        prompt_file: Path | None = _typer.Option(None, "--file", exists=True, file_okay=True, dir_okay=False),
        thread_id: str | None = _typer.Option(None, "--thread-id"),
    ) -> None:
        """Invoke an agent with a prompt (shortcut for agents invoke)."""
        import json

        # Call the real implementation with keyword args
        import sys

        from agentctl.app import get_settings
        from agentctl.client import ApiClient, ApiError
        from agentctl.output import console, fatal

        settings = get_settings()

        # Resolve prompt
        if prompt_file is not None:
            prompt = prompt_file.read_text(encoding="utf-8").strip()
        elif prompt_parts:
            prompt = " ".join(prompt_parts).strip()
        elif not sys.stdin.isatty():
            prompt = sys.stdin.read().strip()
        else:
            prompt = _typer.prompt("Prompt").strip()

        if not prompt:
            fatal("Prompt must not be empty.")

        payload: dict[str, Any] = {"prompt": prompt}
        if thread_id:
            payload["thread_id"] = thread_id

        def _ns_params() -> dict[str, Any]:
            return {"namespace": settings.namespace}

        if stream:
            try:
                with ApiClient(settings) as client:
                    with client.stream(
                        "POST", f"/api/agents/{agent_name}/invoke/stream", params=_ns_params(), payload=payload
                    ) as response:
                        ApiClient._raise_for_status(response)
                        from rich.panel import Panel

                        console.print(
                            Panel(
                                f"Streaming from [bold]{agent_name}[/bold]",
                                title="Live Invoke",
                                border_style="bright_cyan",
                            )
                        )
                        for sse in client.iter_sse(response):
                            event = sse["event"]
                            data_str = sse["data"]
                            if event == "response.delta":
                                event_data = json.loads(data_str) if data_str else {}
                                delta = str(event_data.get("delta", ""))
                                if delta:
                                    console.print(delta, end="")
                            elif event == "response.completed":
                                break
                            elif event == "response.error":
                                event_data = json.loads(data_str) if data_str else {}
                                fatal(str(event_data.get("error", "Error")))
                        console.print()
            except ApiError as exc:
                fatal(str(exc))
            return

        try:
            with console.status(f"[bold cyan]Invoking {agent_name}...[/bold cyan]"):
                with ApiClient(settings) as client:
                    data = client.post(f"/api/agents/{agent_name}/invoke", params=_ns_params(), payload=payload)
        except ApiError as exc:
            fatal(str(exc))

        if settings.output_format == "json":
            from agentctl.output import print_json_output
            print_json_output(data)
        else:
            from agentctl.commands.agents import _render_invoke_result

            _render_invoke_result(data)

    @app.command("logs")
    def logs_cmd(
        agent_name: str = _typer.Argument(..., help="Agent name."),
        tail: int = _typer.Option(200, "--tail", "-t", min=1, max=5000),
        follow: bool = _typer.Option(False, "--follow", "-f", help="Stream logs."),
    ) -> None:
        """Fetch agent logs (shortcut for agents logs)."""
        from agentctl.commands.agents import agents_logs

        agents_logs(agent_name=agent_name, tail=tail, follow=follow)
