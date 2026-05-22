"""Artifact management commands — list, show, download."""

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
    print_table,
    success,
)

artifacts_app = typer.Typer(
    no_args_is_help=True,
    rich_markup_mode="rich",
    epilog=(
        "[bold]Examples:[/bold]\n"
        "  agentctl artifacts list my-workflow\n"
        "  agentctl artifacts show my-workflow output.json\n"
        "  agentctl artifacts download my-workflow output.json"
    ),
)


def _api() -> ApiClient:
    return ApiClient(get_settings())


def _ns_params() -> dict[str, Any]:
    return {"namespace": get_settings().namespace}


@artifacts_app.command("list")
def artifacts_list(
    agent_name: str | None = typer.Option(None, "--agent", "-a", help="Filter by agent."),
    workflow: str | None = typer.Option(None, "--workflow", "-w", help="Filter by workflow."),
    run_id: str | None = typer.Option(None, "--run-id", help="Filter by run."),
) -> None:
    """List artifacts for agents and workflows."""
    settings = get_settings()
    params: dict[str, Any] = dict(_ns_params())
    if agent_name:
        params["agent"] = agent_name
    if workflow:
        params["workflow"] = workflow
    if run_id:
        params["run_id"] = run_id

    try:
        with console.status("[bold cyan]Loading artifacts...[/bold cyan]"):
            with _api() as client:
                data = client.get("/api/artifacts", params=params)
    except ApiError as exc:
        fatal(str(exc))

    items = data if isinstance(data, list) else (data.get("artifacts") or data.get("items") or [])
    print_table(
        items,
        columns=[
            ("ID", "id"),
            ("NAME", "name"),
            ("TYPE", "type"),
            ("SIZE", "size"),
            ("AGENT", "agent_name"),
            ("CREATED", "created_at"),
        ],
        wide_columns=[
            ("WORKFLOW", "workflow_ref"),
            ("RUN ID", "run_id"),
        ],
        title="Artifacts",
        output_format=settings.output_format,
    )


@artifacts_app.command("show")
def artifacts_show(
    artifact_id: str = typer.Argument(..., help="Artifact ID."),
) -> None:
    """Show artifact metadata."""
    settings = get_settings()
    try:
        with console.status(f"[bold cyan]Loading artifact {artifact_id[:16]}...[/bold cyan]"):
            with _api() as client:
                data = client.get(f"/api/artifacts/{artifact_id}")
    except ApiError as exc:
        fatal(str(exc))
    print_detail(data, title=f"Artifact: {artifact_id[:16]}", output_format=settings.output_format)


@artifacts_app.command("download")
def artifacts_download(
    artifact_id: str = typer.Argument(..., help="Artifact ID."),
    output_path: Path | None = typer.Option(None, "--output", "-o", help="Output file path."),
) -> None:
    """Download an artifact to a file."""
    settings = get_settings()
    try:
        with console.status(f"[bold cyan]Downloading artifact {artifact_id[:16]}...[/bold cyan]"):
            with _api() as client:
                # Get metadata first to determine filename
                meta = client.get(f"/api/artifacts/{artifact_id}")
                name = ""
                if isinstance(meta, dict):
                    name = str(meta.get("name", meta.get("filename", "")))

                # Download binary content
                response = client._client.get(
                    f"{settings.gateway_url}/api/artifacts/{artifact_id}/download",
                    params=_ns_params(),
                )
                ApiClient._raise_for_status(response)
                content = response.content
    except ApiError as exc:
        fatal(str(exc))

    out = output_path or Path(name or artifact_id)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(content)
    success(f"Downloaded [bold]{out}[/bold] ({len(content)} bytes)")
