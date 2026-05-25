"""Command group registration."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

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
            with console.status("[bold cyan]Checking gateway health...[/bold cyan]", spinner="dots2"):
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
        from agentctl.commands.agents import agents_invoke

        agents_invoke(
            agent_name=agent_name,
            prompt_parts=prompt_parts,
            stream=stream,
            prompt_file=prompt_file,
            thread_id=thread_id,
            system=None,
            require_approval=False,
            no_session=False,
            max_turns=None,
            debug=False,
        )

    @app.command("logs")
    def logs_cmd(
        agent_name: str = _typer.Argument(..., help="Agent name."),
        tail: int = _typer.Option(200, "--tail", "-t", min=1, max=5000),
        follow: bool = _typer.Option(False, "--follow", "-f", help="Stream logs."),
    ) -> None:
        """Fetch agent logs (shortcut for agents logs)."""
        from agentctl.commands.agents import agents_logs

        agents_logs(agent_name=agent_name, tail=tail, follow=follow)

    @app.command("completion")
    def completion_cmd(
        shell: str = _typer.Argument(..., help="Target shell: bash, zsh, fish, or pwsh (PowerShell)."),
    ) -> None:
        """Generate shell completion script for agentctl.

        Install in one step:

        \b
        # bash (~/.bashrc)
        eval "$(agentctl completion bash)"

        \b
        # zsh (~/.zshrc)
        eval "$(agentctl completion zsh)"

        \b
        # fish (~/.config/fish/completions/agentctl.fish)
        agentctl completion fish > ~/.config/fish/completions/agentctl.fish

        \b
        # PowerShell ($PROFILE)
        agentctl completion pwsh | Out-String | Invoke-Expression
        """
        prog = "agentctl"
        shell_normalized = shell.strip().lower()

        scripts: dict[str, str] = {
            "bash": f'''# agentctl bash completion — generated by `agentctl completion bash`
# Add to ~/.bashrc:  eval "$(agentctl completion bash)"

_agentctl_completion() {{
    local IFS=$'\n'
    local cword="$COMP_CWORD"
    local -a words
    read -ra words <<<"$COMP_WORDS"
    local response
    response=$(env COMP_WORDS="${{words[*]}}" COMP_CWORD="$cword" \
        _AGENTCTL_COMPLETE=complete_bash {prog} 2>/dev/null) || return
    mapfile -t completions <<<"$response"
    COMPREPLY=($(compgen -W "${{completions[*]}}" -- "${{words[cword]}}"))
}}
complete -o nosort -F _agentctl_completion {prog}
''',
            "zsh": f'''#compdef {prog}
# agentctl zsh completion — generated by `agentctl completion zsh`
# Add to ~/.zshrc:  eval "$(agentctl completion zsh)"

_agentctl_completion() {{
    local -a words
    read -rA words <<<"$COMP_WORDS"
    local cword="$COMP_CWORD"
    local response
    response=$(env COMP_WORDS="${{words[*]}}" COMP_CWORD="$cword" _AGENTCTL_COMPLETE=complete_zsh {prog} 2>/dev/null)
    local -a completions
    IFS=$'\n' completions=($response)
    compadd -a completions
}}

compdef _agentctl_completion {prog}
''',
            "fish": f'''# agentctl fish completion — generated by `agentctl completion fish`
# Install: agentctl completion fish > ~/.config/fish/completions/agentctl.fish

function _agentctl_completion
    set -l cli_cmd (commandline -cp)
    set -l cursor_pos (commandline -C)
    set -l response (env COMP_WORDS="$cli_cmd" COMP_CWORD="$cursor_pos" \
        _AGENTCTL_COMPLETE=complete_fish {prog} 2>/dev/null)
    for line in $response
        echo $line
    end
end

complete -f -c {prog} -a "(_agentctl_completion)"
''',
            "pwsh": rf'''# agentctl PowerShell completion — generated by `agentctl completion pwsh`
# Add to $PROFILE:  agentctl completion pwsh | Out-String | Invoke-Expression

Register-ArgumentCompleter -Native -CommandName {prog} -ScriptBlock {{
    param($wordToComplete, $commandAst, $cursorPosition)

    $cmd = $commandAst.ToString()
    if ($cmd -eq $null) {{ $cmd = "" }}

    $env:_AGENTCTL_COMPLETE = "complete_powershell"
    $env:_TYPER_COMPLETE_ARGS = $cmd
    $env:_TYPER_COMPLETE_WORD_TO_COMPLETE = $wordToComplete

    $result = & {prog} 2>$null

    $env:_AGENTCTL_COMPLETE = $null
    $env:_TYPER_COMPLETE_ARGS = $null
    $env:_TYPER_COMPLETE_WORD_TO_COMPLETE = $null

    if ($result -and $wordToComplete) {{
        $result -split "`n" | ForEach-Object {{
            $parts = $_ -split ":::", 2
            $cmdName = $parts[0]
            $helpText = if ($parts.Count -gt 1) {{ $parts[1] }} else {{ $cmdName }}
            [System.Management.Automation.CompletionResult]::new($cmdName, $cmdName, 'ParameterValue', $helpText)
        }}
    }}
}}
'''
        }

        if shell_normalized not in scripts:
            from agentctl.output import fatal
            fatal(f"Unsupported shell: '{shell}'. Supported: bash, zsh, fish, pwsh.")

        from agentctl.output import console, safe_text

        console.print(safe_text(scripts[shell_normalized]), markup=False, highlight=False)
