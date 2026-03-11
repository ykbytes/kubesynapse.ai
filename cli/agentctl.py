#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import typer
import yaml
from rich import box
from rich.console import Console
from rich.json import JSON
from rich.markdown import Markdown
from rich.panel import Panel
from rich.pretty import Pretty
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text
from rich.theme import Theme

APP_NAME = "agentctl"
APP_VERSION = "0.1.0"
DEFAULT_GATEWAY_URL = "http://localhost:8080"
DEFAULT_NAMESPACE = "default"

THEME = Theme(
    {
        "accent": "bold cyan",
        "ok": "bold green",
        "warn": "bold yellow",
        "error": "bold red",
        "muted": "bright_black",
        "title": "bold white",
    }
)

console = Console(theme=THEME)
error_console = Console(stderr=True, theme=THEME)

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    rich_markup_mode="rich",
    help="Modern CLI for the AI Agent Sandbox API gateway.",
)
agents_app = typer.Typer(no_args_is_help=True, help="Manage and inspect agents.")
workflows_app = typer.Typer(no_args_is_help=True, help="Manage and inspect workflows.")
evals_app = typer.Typer(no_args_is_help=True, help="Manage and inspect eval suites.")
approvals_app = typer.Typer(no_args_is_help=True, help="Review and decide approvals.")
policies_app = typer.Typer(no_args_is_help=True, help="List policies.")
get_app = typer.Typer(no_args_is_help=True, hidden=True)

app.add_typer(agents_app, name="agents")
app.add_typer(workflows_app, name="workflows")
app.add_typer(evals_app, name="evals")
app.add_typer(approvals_app, name="approvals")
app.add_typer(policies_app, name="policies")
app.add_typer(get_app, name="get")


@dataclass(frozen=True)
class Settings:
    gateway_url: str
    token: str
    namespace: str
    timeout: float
    json_output: bool


class ApiError(RuntimeError):
    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class ApiClient:
    def __init__(self, settings: Settings) -> None:
        headers = {"Accept": "application/json"}
        if settings.token:
            headers["Authorization"] = f"Bearer {settings.token}"
        self._client = httpx.Client(
            base_url=settings.gateway_url.rstrip("/"),
            headers=headers,
            timeout=settings.timeout,
            follow_redirects=True,
            trust_env=False,
        )

    def __enter__(self) -> ApiClient:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self._client.close()

    def json(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        payload: dict[str, Any] | None = None,
    ) -> Any:
        try:
            response = self._client.request(method, path, params=params, json=payload)
        except httpx.HTTPError as exc:
            raise ApiError(f"Request failed: {exc}") from exc
        self._raise_for_status(response)
        if not response.content:
            return None
        return response.json()

    def stream(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        payload: dict[str, Any] | None = None,
    ) -> httpx.Response:
        return self._client.stream(method, path, params=params, json=payload)

    @staticmethod
    def _raise_for_status(response: httpx.Response) -> None:
        if response.is_success:
            return

        message = response.text.strip() or response.reason_phrase
        try:
            payload = response.json()
        except ValueError:
            payload = None
        if isinstance(payload, dict):
            detail = payload.get("detail")
            if isinstance(detail, str) and detail.strip():
                message = detail.strip()
            else:
                message = json.dumps(payload, indent=2)
        raise ApiError(message, status_code=response.status_code)


def status_style(status: str | None) -> str:
    value = (status or "unknown").strip().lower()
    if value in {"completed", "healthy", "ready", "approved", "passed", "running"}:
        return "ok"
    if value in {"pending", "queued", "blocked"}:
        return "warn"
    if value in {"failed", "denied", "error", "unhealthy"}:
        return "error"
    return "accent"


def styled_status(status: str | None) -> Text:
    return Text((status or "unknown").upper(), style=status_style(status))


def fatal(message: str, *, status_code: int | None = None) -> None:
    title = f"HTTP {status_code}" if status_code else "Command failed"
    error_console.print(Panel(message, title=title, border_style="error"))
    raise typer.Exit(1)


def ctx_settings(ctx: typer.Context) -> Settings:
    settings = ctx.obj
    if not isinstance(settings, Settings):
        fatal("CLI context was not initialized.")
    return settings


def namespace_params(settings: Settings) -> dict[str, Any]:
    return {"namespace": settings.namespace}


def print_json(data: Any) -> None:
    console.print(JSON.from_data(data))


def render_info_table(title: str, rows: list[tuple[str, str]]) -> None:
    table = Table(title=title, box=box.SIMPLE_HEAVY, show_header=False)
    table.add_column("Field", style="accent", no_wrap=True)
    table.add_column("Value", style="title")
    for key, value in rows:
        table.add_row(key, value)
    console.print(table)


def render_generic_detail(title: str, data: dict[str, Any], json_output: bool) -> None:
    if json_output:
        print_json(data)
        return
    console.print(Panel(Pretty(data, expand_all=False), title=title, border_style="accent"))


def render_agents(items: list[dict[str, Any]], json_output: bool, namespace: str) -> None:
    if json_output:
        print_json(items)
        return
    table = Table(title=f"Agents in {namespace}", box=box.ROUNDED)
    table.add_column("Name", style="title")
    table.add_column("Model", style="accent")
    table.add_column("Status")
    table.add_column("Namespace", style="muted")
    for item in items:
        table.add_row(
            str(item.get("name", "")),
            str(item.get("model", "")),
            styled_status(str(item.get("status", "unknown"))),
            str(item.get("namespace", "")),
        )
    if not items:
        console.print(Panel("No agents found.", title="Agents", border_style="warn"))
        return
    console.print(table)


def render_workflows(items: list[dict[str, Any]], json_output: bool, namespace: str) -> None:
    if json_output:
        print_json(items)
        return
    table = Table(title=f"Workflows in {namespace}", box=box.ROUNDED)
    table.add_column("Name", style="title")
    table.add_column("Phase")
    table.add_column("Current Step", style="accent")
    table.add_column("Steps", justify="right")
    table.add_column("Pending Approval", style="warn")
    for item in items:
        pending = item.get("pending_approval") or {}
        table.add_row(
            str(item.get("name", "")),
            styled_status(str(item.get("phase", "pending"))),
            str(item.get("current_step", "") or "-"),
            str(len(item.get("steps") or [])),
            str(pending.get("name") or "-"),
        )
    if not items:
        console.print(Panel("No workflows found.", title="Workflows", border_style="warn"))
        return
    console.print(table)


def render_evals(items: list[dict[str, Any]], json_output: bool, namespace: str) -> None:
    if json_output:
        print_json(items)
        return
    table = Table(title=f"Evaluations in {namespace}", box=box.ROUNDED)
    table.add_column("Name", style="title")
    table.add_column("Agent", style="accent")
    table.add_column("Phase")
    table.add_column("Passed")
    table.add_column("Schedule", style="muted")
    for item in items:
        passed = item.get("passed")
        if passed is True:
            passed_text = Text("YES", style="ok")
        elif passed is False:
            passed_text = Text("NO", style="error")
        else:
            passed_text = Text("-", style="muted")
        table.add_row(
            str(item.get("name", "")),
            str(item.get("agent_ref", "")),
            styled_status(str(item.get("phase", "pending"))),
            passed_text,
            str(item.get("schedule") or "manual"),
        )
    if not items:
        console.print(Panel("No evals found.", title="Evaluations", border_style="warn"))
        return
    console.print(table)


def render_policies(items: list[dict[str, Any]], json_output: bool, namespace: str) -> None:
    if json_output:
        print_json(items)
        return
    table = Table(title=f"Policies in {namespace}", box=box.ROUNDED)
    table.add_column("Name", style="title")
    table.add_column("Namespace", style="muted")
    for item in items:
        table.add_row(str(item.get("name", "")), str(item.get("namespace", "")))
    if not items:
        console.print(Panel("No policies found.", title="Policies", border_style="warn"))
        return
    console.print(table)


def render_markdown_response(title: str, response_text: str) -> None:
    body = response_text.strip() or "(empty response)"
    console.print(Panel(Markdown(body), title=title, border_style="accent"))


def render_warnings(warnings: list[str]) -> None:
    if not warnings:
        return
    content = "\n".join(f"- {item}" for item in warnings)
    console.print(Panel(content, title="Warnings", border_style="warn"))


def render_invoke_result(data: dict[str, Any], json_output: bool) -> None:
    if json_output:
        print_json(data)
        return
    render_info_table(
        "Invocation",
        [
            ("Agent", str(data.get("agent_name", ""))),
            ("Status", str(data.get("status", "unknown"))),
            ("Model", str(data.get("model", ""))),
            ("Thread", str(data.get("thread_id", ""))),
            ("Policy", str(data.get("policy_name") or "-")),
            ("Approval", str(data.get("approval_name") or "-")),
        ],
    )
    render_markdown_response("Response", str(data.get("response", "")))
    tool_result = data.get("tool_result")
    if tool_result:
        console.print(Panel(Pretty(tool_result), title="Tool Result", border_style="accent"))
    sandbox_session = data.get("sandbox_session")
    if sandbox_session:
        console.print(Panel(Pretty(sandbox_session), title="Sandbox Session", border_style="accent"))
    render_warnings(list(data.get("warnings") or []))


def render_logs(data: dict[str, Any], json_output: bool) -> None:
    if json_output:
        print_json(data)
        return
    logs = str(data.get("logs", ""))
    if not logs.strip():
        console.print(Panel("No logs available.", title="Logs", border_style="warn"))
        return
    console.print(
        Panel(
            Syntax(logs, "text", line_numbers=False, word_wrap=True),
            title=f"Logs for {data.get('agent_name', 'agent')}",
            border_style="accent",
        )
    )


def render_delete_result(data: dict[str, Any], json_output: bool) -> None:
    if json_output:
        print_json(data)
        return
    kind = str(data.get("kind", "resource"))
    name = str(data.get("name", ""))
    namespace = str(data.get("namespace", ""))
    console.print(
        Panel(
            f"Deleted [bold]{kind}[/bold] [bold]{name}[/bold] in namespace [bold]{namespace}[/bold].",
            title="Deleted",
            border_style="ok",
        )
    )


def read_structured_file(file_path: Path) -> dict[str, Any]:
    try:
        raw_text = file_path.read_text(encoding="utf-8")
    except OSError as exc:
        fatal(f"Failed to read {file_path}: {exc}")

    try:
        loaded = json.loads(raw_text)
    except json.JSONDecodeError:
        try:
            documents = [doc for doc in yaml.safe_load_all(raw_text) if doc is not None]
        except yaml.YAMLError as exc:
            fatal(f"Failed to parse {file_path} as JSON or YAML: {exc}")
        if not documents:
            fatal(f"{file_path} did not contain any JSON or YAML document.")
        if len(documents) > 1:
            fatal(f"{file_path} contains multiple YAML documents; provide exactly one resource per file.")
        loaded = documents[0]

    if not isinstance(loaded, dict):
        fatal(f"{file_path} must contain a JSON or YAML object at the top level.")
    return loaded


def resolve_namespace(settings: Settings, document: dict[str, Any]) -> str:
    metadata = document.get("metadata")
    if isinstance(metadata, dict):
        namespace = metadata.get("namespace")
        if isinstance(namespace, str) and namespace.strip():
            return namespace.strip()
    return settings.namespace


def normalize_sidecars(sidecars: Any) -> list[dict[str, Any]]:
    if not sidecars:
        return []
    if not isinstance(sidecars, list):
        fatal("mcpSidecars/mcp_sidecars must be a list.")
    normalized: list[dict[str, Any]] = []
    for item in sidecars:
        if not isinstance(item, dict):
            fatal("Each sidecar entry must be an object.")
        normalized.append(item)
    return normalized


def normalize_list_of_strings(values: Any, field_name: str) -> list[str]:
    if not values:
        return []
    if not isinstance(values, list):
        fatal(f"{field_name} must be a list.")
    return [str(item) for item in values if str(item).strip()]


def snake_or_camel(payload: dict[str, Any], snake_key: str, camel_key: str, default: Any = None) -> Any:
    if snake_key in payload:
        return payload[snake_key]
    if camel_key in payload:
        return payload[camel_key]
    return default


def coerce_agent_payload(document: dict[str, Any], *, for_update: bool) -> tuple[dict[str, Any], str | None]:
    metadata = document.get("metadata") if isinstance(document.get("metadata"), dict) else {}
    if document.get("kind") == "AIAgent" and isinstance(document.get("spec"), dict):
        spec = document["spec"]
        storage = spec.get("storage") if isinstance(spec.get("storage"), dict) else {}
        payload: dict[str, Any] = {
            "model": str(spec.get("model", "")),
            "system_prompt": str(spec.get("systemPrompt", "")),
            "policy_ref": spec.get("policyRef"),
            "storage_size": storage.get("size", "1Gi"),
            "enable_gvisor": bool(spec.get("enableGVisor", False)),
            "mcp_servers": normalize_list_of_strings(spec.get("mcpServers"), "mcpServers"),
            "mcp_sidecars": normalize_sidecars(spec.get("mcpSidecars")),
        }
        if not for_update:
            payload["name"] = str(metadata.get("name", ""))
        return payload, str(metadata.get("name", "") or "")

    payload = dict(document)
    normalized = {
        "model": str(snake_or_camel(payload, "model", "model", "")),
        "system_prompt": str(snake_or_camel(payload, "system_prompt", "systemPrompt", "")),
        "policy_ref": snake_or_camel(payload, "policy_ref", "policyRef"),
        "storage_size": snake_or_camel(payload, "storage_size", "storageSize", "1Gi"),
        "enable_gvisor": bool(snake_or_camel(payload, "enable_gvisor", "enableGVisor", False)),
        "mcp_servers": normalize_list_of_strings(
            snake_or_camel(payload, "mcp_servers", "mcpServers", []),
            "mcp_servers",
        ),
        "mcp_sidecars": normalize_sidecars(snake_or_camel(payload, "mcp_sidecars", "mcpSidecars", [])),
    }
    resource_name = str(snake_or_camel(payload, "name", "name", metadata.get("name", "")) or "")
    if not for_update:
        normalized["name"] = resource_name
    return normalized, resource_name


def normalize_workflow_steps(steps: Any) -> list[dict[str, Any]]:
    if not steps:
        return []
    if not isinstance(steps, list):
        fatal("steps must be a list.")
    normalized: list[dict[str, Any]] = []
    for item in steps:
        if not isinstance(item, dict):
            fatal("Each workflow step must be an object.")
        execution = snake_or_camel(item, "execution", "execution", None)
        normalized.append(
            {
                "name": str(snake_or_camel(item, "name", "name", "")),
                "agent_ref": str(snake_or_camel(item, "agent_ref", "agentRef", "")),
                "prompt": str(snake_or_camel(item, "prompt", "prompt", "")),
                "depends_on": normalize_list_of_strings(
                    snake_or_camel(item, "depends_on", "dependsOn", []),
                    "depends_on",
                ),
                "require_approval": bool(
                    snake_or_camel(item, "require_approval", "requireApproval", False)
                ),
                "execution": execution if isinstance(execution, dict) else None,
            }
        )
    return normalized


def coerce_workflow_payload(document: dict[str, Any], *, for_update: bool) -> tuple[dict[str, Any], str | None]:
    metadata = document.get("metadata") if isinstance(document.get("metadata"), dict) else {}
    if document.get("kind") == "AgentWorkflow" and isinstance(document.get("spec"), dict):
        spec = document["spec"]
        payload: dict[str, Any] = {
            "description": str(spec.get("description", "")),
            "input": str(spec.get("input", "")),
            "message_bus": str(spec.get("messageBus", "in-memory")),
            "steps": normalize_workflow_steps(spec.get("steps", [])),
        }
        if not for_update:
            payload["name"] = str(metadata.get("name", ""))
        return payload, str(metadata.get("name", "") or "")

    payload = dict(document)
    normalized = {
        "description": str(snake_or_camel(payload, "description", "description", "")),
        "input": str(snake_or_camel(payload, "input", "input", "")),
        "message_bus": str(snake_or_camel(payload, "message_bus", "messageBus", "in-memory")),
        "steps": normalize_workflow_steps(snake_or_camel(payload, "steps", "steps", [])),
    }
    resource_name = str(snake_or_camel(payload, "name", "name", metadata.get("name", "")) or "")
    if not for_update:
        normalized["name"] = resource_name
    return normalized, resource_name


def normalize_eval_test_suite(test_suite: Any) -> list[dict[str, Any]]:
    if not test_suite:
        return []
    if not isinstance(test_suite, list):
        fatal("test_suite/testSuite must be a list.")
    normalized: list[dict[str, Any]] = []
    for item in test_suite:
        if not isinstance(item, dict):
            fatal("Each eval test case must be an object.")
        normalized.append(
            {
                "input": str(snake_or_camel(item, "input", "input", "")),
                "expected_output": str(
                    snake_or_camel(item, "expected_output", "expectedOutput", "")
                ),
                "metrics": normalize_list_of_strings(
                    snake_or_camel(item, "metrics", "metrics", []),
                    "metrics",
                ),
            }
        )
    return normalized


def coerce_eval_payload(document: dict[str, Any], *, for_update: bool) -> tuple[dict[str, Any], str | None]:
    metadata = document.get("metadata") if isinstance(document.get("metadata"), dict) else {}
    if document.get("kind") == "AgentEval" and isinstance(document.get("spec"), dict):
        spec = document["spec"]
        payload: dict[str, Any] = {
            "agent_ref": str(spec.get("agentRef", "")),
            "schedule": spec.get("schedule"),
            "test_suite": normalize_eval_test_suite(spec.get("testSuite", [])),
            "failure_threshold": dict(spec.get("failureThreshold") or {}),
        }
        if not for_update:
            payload["name"] = str(metadata.get("name", ""))
        return payload, str(metadata.get("name", "") or "")

    payload = dict(document)
    normalized = {
        "agent_ref": str(snake_or_camel(payload, "agent_ref", "agentRef", "")),
        "schedule": snake_or_camel(payload, "schedule", "schedule"),
        "test_suite": normalize_eval_test_suite(
            snake_or_camel(payload, "test_suite", "testSuite", []),
        ),
        "failure_threshold": dict(
            snake_or_camel(payload, "failure_threshold", "failureThreshold", {}) or {}
        ),
    }
    resource_name = str(snake_or_camel(payload, "name", "name", metadata.get("name", "")) or "")
    if not for_update:
        normalized["name"] = resource_name
    return normalized, resource_name


def resolve_resource_name(
    name: str | None,
    file_path: Path | None,
    inferred_name: str | None,
    resource_label: str,
) -> str:
    candidate = (name or inferred_name or "").strip()
    if candidate:
        return candidate
    if file_path is not None:
        fatal(f"Could not determine the {resource_label} name from {file_path}. Pass it explicitly.")
    fatal(f"{resource_label.capitalize()} name is required.")


def confirm_delete(resource_label: str, name: str, namespace: str, assume_yes: bool) -> None:
    if assume_yes:
        return
    confirmed = typer.confirm(
        f"Delete {resource_label} '{name}' in namespace '{namespace}'?",
        default=False,
    )
    if not confirmed:
        raise typer.Exit(0)


def load_prompt(prompt_parts: list[str], file_path: Path | None) -> str:
    if file_path is not None:
        return file_path.read_text(encoding="utf-8").strip()
    if prompt_parts:
        return " ".join(prompt_parts).strip()
    if not sys.stdin.isatty():
        return sys.stdin.read().strip()
    return typer.prompt("Prompt").strip()


def event_summary(event_name: str, payload: dict[str, Any]) -> str:
    if event_name == "response.completed":
        return (
            f"status={payload.get('status', 'completed')} "
            f"thread={payload.get('thread_id', '-')}"
        )
    if event_name == "response.error":
        return str(payload.get("error", "Unknown streaming error"))
    parts: list[str] = []
    for key in ("tool_name", "status", "approval_name", "request_id"):
        value = payload.get(key)
        if value:
            parts.append(f"{key}={value}")
    if not parts:
        text = json.dumps(payload, ensure_ascii=False)
        return textwrap.shorten(text, width=100, placeholder="...")
    return " ".join(parts)


def iter_sse(response: httpx.Response):
    event_name = "message"
    data_lines: list[str] = []
    for line in response.iter_lines():
        if line is None:
            continue
        if line == "":
            if data_lines:
                yield event_name, "\n".join(data_lines)
            event_name = "message"
            data_lines = []
            continue
        if line.startswith(":"):
            continue
        if line.startswith("event:"):
            event_name = line.partition(":")[2].strip()
            continue
        if line.startswith("data:"):
            data_lines.append(line.partition(":")[2].lstrip())
    if data_lines:
        yield event_name, "\n".join(data_lines)


@app.callback()
def main_callback(
    ctx: typer.Context,
    gateway_url: str = typer.Option(
        DEFAULT_GATEWAY_URL,
        "--gateway-url",
        envvar="AGENT_GATEWAY_URL",
        help="API gateway base URL.",
    ),
    token: str = typer.Option(
        "",
        "--token",
        envvar="AGENT_GATEWAY_TOKEN",
        help="Bearer token for the API gateway.",
    ),
    namespace: str = typer.Option(
        DEFAULT_NAMESPACE,
        "--namespace",
        "-n",
        envvar="AGENT_NAMESPACE",
        help="Default Kubernetes namespace to query.",
    ),
    timeout: float = typer.Option(60.0, "--timeout", min=1.0, help="HTTP timeout in seconds."),
    json_output: bool = typer.Option(False, "--json", help="Emit raw JSON instead of rich output."),
) -> None:
    ctx.obj = Settings(
        gateway_url=gateway_url.rstrip("/"),
        token=token.strip(),
        namespace=namespace.strip() or DEFAULT_NAMESPACE,
        timeout=max(timeout, 1.0),
        json_output=json_output,
    )


@app.command("health")
def health(ctx: typer.Context) -> None:
    """Check API gateway health."""
    settings = ctx_settings(ctx)
    try:
        with console.status("[accent]Checking gateway health...[/accent]"):
            with ApiClient(settings) as client:
                data = client.json("GET", "/api/health")
    except ApiError as exc:
        fatal(str(exc), status_code=exc.status_code)

    if settings.json_output:
        print_json(data)
        return
    render_info_table(
        "Gateway Health",
        [
            ("Status", str(data.get("status", "unknown"))),
            ("Gateway", str(data.get("gateway", ""))),
            ("Auth Mode", str(data.get("auth_mode", ""))),
            ("NATS", str(data.get("nats_url", ""))),
            ("Qdrant", str(data.get("qdrant_url", ""))),
        ],
    )


@app.command("config")
def config(ctx: typer.Context) -> None:
    """Show the effective CLI configuration."""
    settings = ctx_settings(ctx)
    data = {
        "gateway_url": settings.gateway_url,
        "namespace": settings.namespace,
        "timeout": settings.timeout,
        "token_configured": bool(settings.token),
        "output": "json" if settings.json_output else "rich",
    }
    if settings.json_output:
        print_json(data)
        return
    render_info_table(
        "CLI Configuration",
        [
            ("Gateway URL", settings.gateway_url),
            ("Namespace", settings.namespace),
            ("Timeout", f"{settings.timeout:.1f}s"),
            ("Token", "configured" if settings.token else "missing"),
            ("Output", "json" if settings.json_output else "rich"),
        ],
    )


@app.command("invoke")
def invoke(
    ctx: typer.Context,
    agent_name: str = typer.Argument(..., help="Agent name."),
    prompt_parts: list[str] = typer.Argument(None, help="Prompt text."),
    stream: bool = typer.Option(False, "--stream", "-s", help="Use SSE streaming output."),
    prompt_file: Path | None = typer.Option(None, "--file", exists=True, file_okay=True, dir_okay=False),
    thread_id: str | None = typer.Option(None, "--thread-id", help="Reuse an existing thread id."),
    require_approval: bool = typer.Option(False, "--require-approval", help="Request HITL approval."),
    approval_action: str | None = typer.Option(None, "--approval-action", help="Approval action label."),
) -> None:
    """Invoke an agent with a prompt."""
    settings = ctx_settings(ctx)
    try:
        prompt = load_prompt(prompt_parts or [], prompt_file)
    except OSError as exc:
        fatal(f"Failed to read prompt file: {exc}")
    if not prompt:
        fatal("Prompt must not be empty.")

    payload: dict[str, Any] = {"prompt": prompt}
    if thread_id:
        payload["thread_id"] = thread_id
    if require_approval:
        payload["require_approval"] = True
    if approval_action:
        payload["approval_action"] = approval_action

    if stream:
        try:
            with ApiClient(settings) as client:
                with client.stream(
                    "POST",
                    f"/api/agents/{agent_name}/invoke/stream",
                    params=namespace_params(settings),
                    payload=payload,
                ) as response:
                    ApiClient._raise_for_status(response)
                    console.print(
                        Panel(
                            (
                                f"Streaming response from [bold]{agent_name}[/bold] "
                                f"in namespace [bold]{settings.namespace}[/bold]"
                            ),
                            title="Live Invoke",
                            border_style="accent",
                        )
                    )
                    completed_payload: dict[str, Any] | None = None
                    emitted_delta = False
                    for event_name, data in iter_sse(response):
                        payload_data = json.loads(data) if data else {}
                        if event_name == "response.delta":
                            delta = str(payload_data.get("delta", ""))
                            if delta:
                                console.print(delta, end="")
                                emitted_delta = True
                            continue
                        if emitted_delta:
                            console.print()
                            emitted_delta = False
                        if event_name == "response.completed":
                            completed_payload = payload_data
                            continue
                        if event_name == "response.error":
                            fatal(str(payload_data.get("error", "Streaming request failed.")))
                        console.print(
                            Panel(
                                event_summary(event_name, payload_data),
                                title=event_name,
                                border_style="muted",
                            )
                        )
        except ApiError as exc:
            fatal(str(exc), status_code=exc.status_code)

        if completed_payload:
            if settings.json_output:
                print_json(completed_payload)
            else:
                render_info_table(
                    "Stream Complete",
                    [
                        ("Status", str(completed_payload.get("status", "completed"))),
                        ("Thread", str(completed_payload.get("thread_id", ""))),
                        ("Policy", str(completed_payload.get("policy_name") or "-")),
                        ("Approval", str(completed_payload.get("approval_name") or "-")),
                    ],
                )
                render_warnings(list(completed_payload.get("warnings") or []))
        return

    try:
        with console.status(f"[accent]Invoking {agent_name}...[/accent]"):
            with ApiClient(settings) as client:
                data = client.json(
                    "POST",
                    f"/api/agents/{agent_name}/invoke",
                    params=namespace_params(settings),
                    payload=payload,
                )
    except ApiError as exc:
        fatal(str(exc), status_code=exc.status_code)

    render_invoke_result(data, settings.json_output)


@app.command("logs")
def logs(ctx: typer.Context, agent_name: str = typer.Argument(..., help="Agent name.")) -> None:
    """Fetch the last 100 log lines for an agent runtime."""
    settings = ctx_settings(ctx)
    try:
        with console.status(f"[accent]Fetching logs for {agent_name}...[/accent]"):
            with ApiClient(settings) as client:
                data = client.json(
                    "GET",
                    f"/api/agents/{agent_name}/logs",
                    params=namespace_params(settings),
                )
    except ApiError as exc:
        fatal(str(exc), status_code=exc.status_code)

    render_logs(data, settings.json_output)


@agents_app.command("list")
def agents_list(ctx: typer.Context) -> None:
    """List agents in the current namespace."""
    settings = ctx_settings(ctx)
    try:
        with console.status("[accent]Loading agents...[/accent]"):
            with ApiClient(settings) as client:
                data = client.json("GET", "/api/agents", params=namespace_params(settings))
    except ApiError as exc:
        fatal(str(exc), status_code=exc.status_code)
    render_agents(data, settings.json_output, settings.namespace)


@agents_app.command("create")
def agents_create(
    ctx: typer.Context,
    file_path: Path = typer.Option(..., "--file", "-f", exists=True, file_okay=True, dir_okay=False),
) -> None:
    """Create an agent from a JSON or YAML file."""
    settings = ctx_settings(ctx)
    document = read_structured_file(file_path)
    payload, inferred_name = coerce_agent_payload(document, for_update=False)
    namespace = resolve_namespace(settings, document)
    agent_name = resolve_resource_name(None, file_path, inferred_name, "agent")
    payload["name"] = agent_name

    try:
        with console.status(f"[accent]Creating agent {agent_name}...[/accent]"):
            with ApiClient(settings) as client:
                data = client.json("POST", "/api/agents", params={"namespace": namespace}, payload=payload)
    except ApiError as exc:
        fatal(str(exc), status_code=exc.status_code)
    render_generic_detail(f"Agent Created: {agent_name}", data, settings.json_output)


@agents_app.command("show")
def agents_show(ctx: typer.Context, agent_name: str = typer.Argument(..., help="Agent name.")) -> None:
    """Show agent details."""
    settings = ctx_settings(ctx)
    try:
        with console.status(f"[accent]Loading {agent_name}...[/accent]"):
            with ApiClient(settings) as client:
                data = client.json(
                    "GET",
                    f"/api/agents/{agent_name}",
                    params=namespace_params(settings),
                )
    except ApiError as exc:
        fatal(str(exc), status_code=exc.status_code)
    render_generic_detail(f"Agent: {agent_name}", data, settings.json_output)


@agents_app.command("update")
def agents_update(
    ctx: typer.Context,
    agent_name: str | None = typer.Argument(None, help="Agent name. Optional when the file contains metadata.name."),
    file_path: Path = typer.Option(..., "--file", "-f", exists=True, file_okay=True, dir_okay=False),
) -> None:
    """Update an agent from a JSON or YAML file."""
    settings = ctx_settings(ctx)
    document = read_structured_file(file_path)
    payload, inferred_name = coerce_agent_payload(document, for_update=True)
    namespace = resolve_namespace(settings, document)
    resolved_name = resolve_resource_name(agent_name, file_path, inferred_name, "agent")

    try:
        with console.status(f"[accent]Updating agent {resolved_name}...[/accent]"):
            with ApiClient(settings) as client:
                data = client.json(
                    "PATCH",
                    f"/api/agents/{resolved_name}",
                    params={"namespace": namespace},
                    payload=payload,
                )
    except ApiError as exc:
        fatal(str(exc), status_code=exc.status_code)
    render_generic_detail(f"Agent Updated: {resolved_name}", data, settings.json_output)


@agents_app.command("delete")
def agents_delete(
    ctx: typer.Context,
    agent_name: str | None = typer.Argument(None, help="Agent name. Optional when using --file."),
    file_path: Path | None = typer.Option(None, "--file", "-f", exists=True, file_okay=True, dir_okay=False),
    assume_yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation."),
) -> None:
    """Delete an agent by name or from a file."""
    settings = ctx_settings(ctx)
    document: dict[str, Any] = {}
    inferred_name = ""
    namespace = settings.namespace
    if file_path is not None:
        document = read_structured_file(file_path)
        _, inferred_name = coerce_agent_payload(document, for_update=True)
        namespace = resolve_namespace(settings, document)
    resolved_name = resolve_resource_name(agent_name, file_path, inferred_name, "agent")
    confirm_delete("agent", resolved_name, namespace, assume_yes)

    try:
        with console.status(f"[accent]Deleting agent {resolved_name}...[/accent]"):
            with ApiClient(settings) as client:
                data = client.json(
                    "DELETE",
                    f"/api/agents/{resolved_name}",
                    params={"namespace": namespace},
                )
    except ApiError as exc:
        fatal(str(exc), status_code=exc.status_code)
    render_delete_result(data, settings.json_output)


@workflows_app.command("list")
def workflows_list(ctx: typer.Context) -> None:
    """List workflows."""
    settings = ctx_settings(ctx)
    try:
        with console.status("[accent]Loading workflows...[/accent]"):
            with ApiClient(settings) as client:
                data = client.json("GET", "/api/workflows", params=namespace_params(settings))
    except ApiError as exc:
        fatal(str(exc), status_code=exc.status_code)
    render_workflows(data, settings.json_output, settings.namespace)


@workflows_app.command("create")
def workflows_create(
    ctx: typer.Context,
    file_path: Path = typer.Option(..., "--file", "-f", exists=True, file_okay=True, dir_okay=False),
) -> None:
    """Create a workflow from a JSON or YAML file."""
    settings = ctx_settings(ctx)
    document = read_structured_file(file_path)
    payload, inferred_name = coerce_workflow_payload(document, for_update=False)
    namespace = resolve_namespace(settings, document)
    workflow_name = resolve_resource_name(None, file_path, inferred_name, "workflow")
    payload["name"] = workflow_name

    try:
        with console.status(f"[accent]Creating workflow {workflow_name}...[/accent]"):
            with ApiClient(settings) as client:
                data = client.json(
                    "POST",
                    "/api/workflows",
                    params={"namespace": namespace},
                    payload=payload,
                )
    except ApiError as exc:
        fatal(str(exc), status_code=exc.status_code)
    render_generic_detail(f"Workflow Created: {workflow_name}", data, settings.json_output)


@workflows_app.command("show")
def workflows_show(ctx: typer.Context, workflow_name: str = typer.Argument(..., help="Workflow name.")) -> None:
    """Show workflow details."""
    settings = ctx_settings(ctx)
    try:
        with console.status(f"[accent]Loading workflow {workflow_name}...[/accent]"):
            with ApiClient(settings) as client:
                data = client.json(
                    "GET",
                    f"/api/workflows/{workflow_name}",
                    params=namespace_params(settings),
                )
    except ApiError as exc:
        fatal(str(exc), status_code=exc.status_code)
    render_generic_detail(f"Workflow: {workflow_name}", data, settings.json_output)


@workflows_app.command("update")
def workflows_update(
    ctx: typer.Context,
    workflow_name: str | None = typer.Argument(
        None,
        help="Workflow name. Optional when the file contains metadata.name.",
    ),
    file_path: Path = typer.Option(..., "--file", "-f", exists=True, file_okay=True, dir_okay=False),
) -> None:
    """Update a workflow from a JSON or YAML file."""
    settings = ctx_settings(ctx)
    document = read_structured_file(file_path)
    payload, inferred_name = coerce_workflow_payload(document, for_update=True)
    namespace = resolve_namespace(settings, document)
    resolved_name = resolve_resource_name(workflow_name, file_path, inferred_name, "workflow")

    try:
        with console.status(f"[accent]Updating workflow {resolved_name}...[/accent]"):
            with ApiClient(settings) as client:
                data = client.json(
                    "PATCH",
                    f"/api/workflows/{resolved_name}",
                    params={"namespace": namespace},
                    payload=payload,
                )
    except ApiError as exc:
        fatal(str(exc), status_code=exc.status_code)
    render_generic_detail(f"Workflow Updated: {resolved_name}", data, settings.json_output)


@workflows_app.command("delete")
def workflows_delete(
    ctx: typer.Context,
    workflow_name: str | None = typer.Argument(None, help="Workflow name. Optional when using --file."),
    file_path: Path | None = typer.Option(None, "--file", "-f", exists=True, file_okay=True, dir_okay=False),
    assume_yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation."),
) -> None:
    """Delete a workflow by name or from a file."""
    settings = ctx_settings(ctx)
    document: dict[str, Any] = {}
    inferred_name = ""
    namespace = settings.namespace
    if file_path is not None:
        document = read_structured_file(file_path)
        _, inferred_name = coerce_workflow_payload(document, for_update=True)
        namespace = resolve_namespace(settings, document)
    resolved_name = resolve_resource_name(workflow_name, file_path, inferred_name, "workflow")
    confirm_delete("workflow", resolved_name, namespace, assume_yes)

    try:
        with console.status(f"[accent]Deleting workflow {resolved_name}...[/accent]"):
            with ApiClient(settings) as client:
                data = client.json(
                    "DELETE",
                    f"/api/workflows/{resolved_name}",
                    params={"namespace": namespace},
                )
    except ApiError as exc:
        fatal(str(exc), status_code=exc.status_code)
    render_delete_result(data, settings.json_output)


@evals_app.command("list")
def evals_list(ctx: typer.Context) -> None:
    """List eval suites."""
    settings = ctx_settings(ctx)
    try:
        with console.status("[accent]Loading evals...[/accent]"):
            with ApiClient(settings) as client:
                data = client.json("GET", "/api/evals", params=namespace_params(settings))
    except ApiError as exc:
        fatal(str(exc), status_code=exc.status_code)
    render_evals(data, settings.json_output, settings.namespace)


@evals_app.command("create")
def evals_create(
    ctx: typer.Context,
    file_path: Path = typer.Option(..., "--file", "-f", exists=True, file_okay=True, dir_okay=False),
) -> None:
    """Create an eval suite from a JSON or YAML file."""
    settings = ctx_settings(ctx)
    document = read_structured_file(file_path)
    payload, inferred_name = coerce_eval_payload(document, for_update=False)
    namespace = resolve_namespace(settings, document)
    eval_name = resolve_resource_name(None, file_path, inferred_name, "eval")
    payload["name"] = eval_name

    try:
        with console.status(f"[accent]Creating eval {eval_name}...[/accent]"):
            with ApiClient(settings) as client:
                data = client.json(
                    "POST",
                    "/api/evals",
                    params={"namespace": namespace},
                    payload=payload,
                )
    except ApiError as exc:
        fatal(str(exc), status_code=exc.status_code)
    render_generic_detail(f"Eval Created: {eval_name}", data, settings.json_output)


@evals_app.command("show")
def evals_show(ctx: typer.Context, eval_name: str = typer.Argument(..., help="Eval name.")) -> None:
    """Show eval details."""
    settings = ctx_settings(ctx)
    try:
        with console.status(f"[accent]Loading eval {eval_name}...[/accent]"):
            with ApiClient(settings) as client:
                data = client.json(
                    "GET",
                    f"/api/evals/{eval_name}",
                    params=namespace_params(settings),
                )
    except ApiError as exc:
        fatal(str(exc), status_code=exc.status_code)
    render_generic_detail(f"Eval: {eval_name}", data, settings.json_output)


@evals_app.command("update")
def evals_update(
    ctx: typer.Context,
    eval_name: str | None = typer.Argument(None, help="Eval name. Optional when the file contains metadata.name."),
    file_path: Path = typer.Option(..., "--file", "-f", exists=True, file_okay=True, dir_okay=False),
) -> None:
    """Update an eval suite from a JSON or YAML file."""
    settings = ctx_settings(ctx)
    document = read_structured_file(file_path)
    payload, inferred_name = coerce_eval_payload(document, for_update=True)
    namespace = resolve_namespace(settings, document)
    resolved_name = resolve_resource_name(eval_name, file_path, inferred_name, "eval")

    try:
        with console.status(f"[accent]Updating eval {resolved_name}...[/accent]"):
            with ApiClient(settings) as client:
                data = client.json(
                    "PATCH",
                    f"/api/evals/{resolved_name}",
                    params={"namespace": namespace},
                    payload=payload,
                )
    except ApiError as exc:
        fatal(str(exc), status_code=exc.status_code)
    render_generic_detail(f"Eval Updated: {resolved_name}", data, settings.json_output)


@evals_app.command("delete")
def evals_delete(
    ctx: typer.Context,
    eval_name: str | None = typer.Argument(None, help="Eval name. Optional when using --file."),
    file_path: Path | None = typer.Option(None, "--file", "-f", exists=True, file_okay=True, dir_okay=False),
    assume_yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation."),
) -> None:
    """Delete an eval suite by name or from a file."""
    settings = ctx_settings(ctx)
    document: dict[str, Any] = {}
    inferred_name = ""
    namespace = settings.namespace
    if file_path is not None:
        document = read_structured_file(file_path)
        _, inferred_name = coerce_eval_payload(document, for_update=True)
        namespace = resolve_namespace(settings, document)
    resolved_name = resolve_resource_name(eval_name, file_path, inferred_name, "eval")
    confirm_delete("eval", resolved_name, namespace, assume_yes)

    try:
        with console.status(f"[accent]Deleting eval {resolved_name}...[/accent]"):
            with ApiClient(settings) as client:
                data = client.json(
                    "DELETE",
                    f"/api/evals/{resolved_name}",
                    params={"namespace": namespace},
                )
    except ApiError as exc:
        fatal(str(exc), status_code=exc.status_code)
    render_delete_result(data, settings.json_output)


@policies_app.command("list")
def policies_list(ctx: typer.Context) -> None:
    """List policies."""
    settings = ctx_settings(ctx)
    try:
        with console.status("[accent]Loading policies...[/accent]"):
            with ApiClient(settings) as client:
                data = client.json("GET", "/api/policies", params=namespace_params(settings))
    except ApiError as exc:
        fatal(str(exc), status_code=exc.status_code)
    render_policies(data, settings.json_output, settings.namespace)


@approvals_app.command("show")
def approvals_show(ctx: typer.Context, approval_name: str = typer.Argument(..., help="Approval name.")) -> None:
    """Show approval details."""
    settings = ctx_settings(ctx)
    try:
        with console.status(f"[accent]Loading approval {approval_name}...[/accent]"):
            with ApiClient(settings) as client:
                data = client.json(
                    "GET",
                    f"/api/approvals/{approval_name}",
                    params=namespace_params(settings),
                )
    except ApiError as exc:
        fatal(str(exc), status_code=exc.status_code)
    render_generic_detail(f"Approval: {approval_name}", data, settings.json_output)


def decide_approval(ctx: typer.Context, approval_name: str, decision: str, reason: str | None) -> None:
    settings = ctx_settings(ctx)
    try:
        with console.status(f"[accent]{decision.title()} approval {approval_name}...[/accent]"):
            with ApiClient(settings) as client:
                data = client.json(
                    "PATCH",
                    f"/api/approvals/{approval_name}",
                    params=namespace_params(settings),
                    payload={"decision": decision, "reason": reason},
                )
    except ApiError as exc:
        fatal(str(exc), status_code=exc.status_code)

    if settings.json_output:
        print_json(data)
        return
    console.print(
        Panel(
            f"Approval [bold]{approval_name}[/bold] marked as [bold]{decision}[/bold].",
            title="Approval Updated",
            border_style="ok" if decision == "approved" else "warn",
        )
    )
    render_generic_detail(f"Approval: {approval_name}", data, False)


@approvals_app.command("approve")
def approvals_approve(
    ctx: typer.Context,
    approval_name: str = typer.Argument(..., help="Approval name."),
    reason: str | None = typer.Option(None, "--reason", help="Optional review reason."),
) -> None:
    """Approve a pending request."""
    decide_approval(ctx, approval_name, "approved", reason)


@approvals_app.command("deny")
def approvals_deny(
    ctx: typer.Context,
    approval_name: str = typer.Argument(..., help="Approval name."),
    reason: str | None = typer.Option(None, "--reason", help="Optional review reason."),
) -> None:
    """Deny a pending request."""
    decide_approval(ctx, approval_name, "denied", reason)


@get_app.command("agents")
def get_agents(ctx: typer.Context) -> None:
    """Compatibility alias for `agentctl agents list`."""
    agents_list(ctx)


@get_app.command("workflows")
def get_workflows(ctx: typer.Context) -> None:
    """Compatibility alias for `agentctl workflows list`."""
    workflows_list(ctx)


@get_app.command("evals")
def get_evals(ctx: typer.Context) -> None:
    """Compatibility alias for `agentctl evals list`."""
    evals_list(ctx)


@get_app.command("policies")
def get_policies(ctx: typer.Context) -> None:
    """Compatibility alias for `agentctl policies list`."""
    policies_list(ctx)


@app.command("version")
def version() -> None:
    """Show the CLI version."""
    console.print(Panel(f"{APP_NAME} {APP_VERSION}", title="Version", border_style="accent"))


def main() -> None:
    app()


if __name__ == "__main__":
    main()
