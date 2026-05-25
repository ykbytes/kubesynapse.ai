"""Runs / Approvals / Policies commands."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import typer

from agentctl.app import get_settings
from agentctl.client import ApiClient, ApiError
from agentctl.output import (
    console,
    fatal,
    print_json_output,
    print_table,
    success,
)

runs_app = typer.Typer(
    no_args_is_help=True,
    rich_markup_mode="rich",
    epilog=(
        "[bold]Examples:[/bold]\n"
        "  agentctl runs approvals\n"
        "  agentctl runs approve run-abc-123 --comment LGTM\n"
        "  agentctl runs deny run-abc-123\n"
        "  agentctl runs policies\n"
        "  agentctl runs apply policy.yaml"
    ),
)


def _ns_params() -> dict[str, Any]:
    return {"namespace": get_settings().namespace}


def _api() -> ApiClient:
    return ApiClient(get_settings())


# ─── Approvals ───


@runs_app.command("approvals")
def approvals_list() -> None:
    """List pending approvals across workflows."""
    settings = get_settings()
    try:
        with console.status("[bold cyan]Loading approvals...[/bold cyan]", spinner="dots2"):
            with _api() as client:
                workflows = client.get("/api/workflows", params=_ns_params())
    except ApiError as exc:
        fatal(str(exc))

    pending = []
    for wf in workflows or []:
        approval = wf.get("pending_approval")
        if isinstance(approval, dict) and approval.get("name"):
            pending.append(
                {
                    "approval_name": approval["name"],
                    "workflow": wf.get("name", ""),
                    "step": approval.get("step", "-"),
                    "phase": wf.get("phase", "waiting-approval"),
                }
            )

    if settings.output_format == "json":
        print_json_output(pending)
        return

    if not pending:
        console.print("[dim]No pending approvals.[/dim]")
        return

    print_table(
        pending,
        columns=[
            ("APPROVAL", "approval_name"),
            ("WORKFLOW", "workflow"),
            ("STEP", "step"),
            ("PHASE", "phase"),
        ],
        title="Pending Approvals",
        output_format=settings.output_format,
    )


@runs_app.command("approve")
def approval_approve(
    approval_name: str = typer.Argument(..., help="Approval name."),
    reason: str | None = typer.Option(None, "--reason", help="Review reason."),
) -> None:
    """Approve a pending request."""
    _decide_approval(approval_name, "approved", reason)


@runs_app.command("deny")
def approval_deny(
    approval_name: str = typer.Argument(..., help="Approval name."),
    reason: str | None = typer.Option(None, "--reason", help="Review reason."),
) -> None:
    """Deny a pending request."""
    _decide_approval(approval_name, "denied", reason)


def _decide_approval(approval_name: str, decision: str, reason: str | None) -> None:
    settings = get_settings()
    try:
        with console.status(f"[bold cyan]{decision.title()} {approval_name}...[/bold cyan]", spinner="dots2"):
            with _api() as client:
                data = client.patch(
                    f"/api/approvals/{approval_name}",
                    params=_ns_params(),
                    payload={"decision": decision, "reason": reason},
                )
    except ApiError as exc:
        fatal(str(exc))

    if settings.output_format == "json":
        print_json_output(data)
        return
    style = "bold green" if decision == "approved" else "bold yellow"
    console.print(f"[{style}]Approval {approval_name} -> {decision}[/{style}]")


# ─── Policies ───


@runs_app.command("policies")
def policies_list() -> None:
    """List policies in the current namespace."""
    settings = get_settings()
    try:
        with console.status("[bold cyan]Loading policies...[/bold cyan]", spinner="dots2"):
            with _api() as client:
                data = client.get("/api/policies", params=_ns_params())
    except ApiError as exc:
        fatal(str(exc))

    items = data if isinstance(data, list) else []
    print_table(
        items,
        columns=[
            ("NAME", "name"),
            ("NAMESPACE", "namespace"),
        ],
        title=f"Policies in {settings.namespace}",
        output_format=settings.output_format,
    )


@runs_app.command("policy-show")
def policy_show(name: str = typer.Argument(..., help="Policy name.")) -> None:
    """Show policy details."""
    settings = get_settings()
    try:
        with console.status(f"[bold cyan]Loading policy {name}...[/bold cyan]", spinner="dots2"):
            with _api() as client:
                data = client.get(f"/api/policies/{name}", params=_ns_params())
    except ApiError as exc:
        fatal(str(exc))

    if settings.output_format == "json":
        print_json_output(data)
        return

    from agentctl.output import print_detail

    print_detail(data, title=f"Policy: {name}", output_format=settings.output_format)


@runs_app.command("policy-delete")
def policy_delete(
    name: str = typer.Argument(..., help="Policy name."),
    assume_yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation."),
) -> None:
    """Delete a policy."""
    if not assume_yes:
        if not typer.confirm(f"Delete policy '{name}'?", default=False):
            raise typer.Exit(0)

    try:
        with console.status(f"[bold cyan]Deleting policy {name}...[/bold cyan]", spinner="dots2"):
            with _api() as client:
                client.delete(f"/api/policies/{name}", params=_ns_params())
    except ApiError as exc:
        fatal(str(exc))
    success(f"Policy [bold]{name}[/bold] deleted")


# ─── Apply (generic) ───


@runs_app.command("apply")
def apply(
    file_path: Path = typer.Argument(..., exists=True, file_okay=True, dir_okay=False, help="Resource file."),
) -> None:
    """Create or update a resource from a file (auto-detects kind)."""
    from agentctl.commands._parsers import (
        coerce_agent_payload,
        coerce_policy_payload,
        coerce_workflow_payload,
        read_structured_file,
        resolve_namespace,
        resolve_resource_name,
    )

    settings = get_settings()
    document = read_structured_file(file_path)
    kind = str(document.get("kind", "")).strip()
    namespace = resolve_namespace(settings.namespace, document)

    if kind == "AIAgent" or (not kind and "model" in document):
        payload, inferred_name = coerce_agent_payload(document, for_update=False)
        name = resolve_resource_name(None, file_path, inferred_name, "agent")
        payload["name"] = name
        try:
            with console.status(f"[bold cyan]Applying agent {name}...[/bold cyan]", spinner="dots2"):
                with _api() as client:
                    try:
                        client.post("/api/agents", params={"namespace": namespace}, payload=payload)
                        action = "created"
                    except ApiError as e:
                        if e.status_code == 409:
                            update_payload, _ = coerce_agent_payload(document, for_update=True)
                            client.patch(f"/api/agents/{name}", params={"namespace": namespace}, payload=update_payload)
                            action = "updated"
                        else:
                            raise
        except ApiError as exc:
            fatal(str(exc))
        success(f"Agent [bold]{name}[/bold] {action}")

    elif kind == "AgentWorkflow" or (not kind and "steps" in document):
        payload, inferred_name = coerce_workflow_payload(document, for_update=False)
        name = resolve_resource_name(None, file_path, inferred_name, "workflow")
        payload["name"] = name
        try:
            with console.status(f"[bold cyan]Applying workflow {name}...[/bold cyan]", spinner="dots2"):
                with _api() as client:
                    try:
                        client.post("/api/workflows", params={"namespace": namespace}, payload=payload)
                        action = "created"
                    except ApiError as e:
                        if e.status_code == 409:
                            update_payload, _ = coerce_workflow_payload(document, for_update=True)
                            client.patch(
                                f"/api/workflows/{name}", params={"namespace": namespace}, payload=update_payload
                            )
                            action = "updated"
                        else:
                            raise
        except ApiError as exc:
            fatal(str(exc))
        success(f"Workflow [bold]{name}[/bold] {action}")

    elif kind == "AgentPolicy" or (not kind and ("allowedModels" in document or "allowed_models" in document)):
        payload, inferred_name = coerce_policy_payload(document, for_update=False)
        name = resolve_resource_name(None, file_path, inferred_name, "policy")
        payload["name"] = name
        try:
            with console.status(f"[bold cyan]Applying policy {name}...[/bold cyan]", spinner="dots2"):
                with _api() as client:
                    try:
                        client.post("/api/policies", params={"namespace": namespace}, payload=payload)
                        action = "created"
                    except ApiError as e:
                        if e.status_code == 409:
                            update_payload, _ = coerce_policy_payload(document, for_update=True)
                            client.patch(
                                f"/api/policies/{name}",
                                params={"namespace": namespace},
                                payload=update_payload,
                            )
                            action = "updated"
                        else:
                            raise
        except ApiError as exc:
            fatal(str(exc))
        success(f"Policy [bold]{name}[/bold] {action}")

    else:
        fatal(f"Unsupported resource kind '{kind or '(none)'}'. Supported: AIAgent, AgentWorkflow, AgentPolicy.")
