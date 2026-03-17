#!/usr/bin/env python3
from __future__ import annotations

import json
import re
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
K8S_NAME_RE = re.compile(r"^[a-z0-9]([-a-z0-9]*[a-z0-9])?$")

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


def render_agent_discovery(data: dict[str, Any], json_output: bool, include_unreachable: bool) -> None:
    if json_output:
        print_json(data)
        return

    peers = data.get("peers") or []
    if not isinstance(peers, list):
        fatal("A2A discovery response must include a peers list.")
    visible_peers = peers if include_unreachable else [item for item in peers if bool(item.get("reachable"))]

    render_info_table(
        "A2A Discovery",
        [
            ("Agent", str(data.get("agent_name", ""))),
            ("Namespace", str(data.get("namespace", ""))),
            ("Policy", str(data.get("policy_ref") or "-")),
            ("Configured Targets", str(len(peers))),
            ("Shown", str(len(visible_peers))),
        ],
    )

    if not visible_peers:
        message = (
            "No discoverable peers are currently reachable."
            if not include_unreachable
            else "No A2A targets are configured for this agent."
        )
        console.print(Panel(message, title="Discovery", border_style="warn"))
        return

    table = Table(title="Target Peers", box=box.ROUNDED)
    table.add_column("Name", style="title")
    table.add_column("Namespace", style="muted")
    table.add_column("Reachable")
    table.add_column("Status")
    table.add_column("Runtime", style="accent")
    table.add_column("Model", style="accent")
    table.add_column("Reason")
    for item in visible_peers:
        reachable = bool(item.get("reachable"))
        status = str(item.get("status") or "missing")
        table.add_row(
            str(item.get("name", "")),
            str(item.get("namespace", "")),
            Text("YES", style="ok") if reachable else Text("NO", style="warn"),
            styled_status(status),
            str(item.get("runtime_kind") or "-"),
            str(item.get("model") or "-"),
            str(item.get("reason") or "-"),
        )
    console.print(table)


def render_markdown_response(title: str, response_text: str) -> None:
    body = response_text.strip() or "(empty response)"
    console.print(Panel(Markdown(body), title=title, border_style="accent"))


def render_warnings(warnings: list[str]) -> None:
    if not warnings:
        return
    content = "\n".join(f"- {item}" for item in warnings)
    console.print(Panel(content, title="Warnings", border_style="warn"))


def render_a2a_metadata(payload: Any) -> None:
    if not isinstance(payload, dict) or not payload:
        return

    target_agent = str(payload.get("targetAgent") or "")
    target_namespace = str(payload.get("targetNamespace") or "")
    caller_agent = str(payload.get("callerAgent") or "")
    caller_namespace = str(payload.get("callerNamespace") or "")
    rows: list[tuple[str, str]] = []
    if target_agent or target_namespace:
        rows.append(("Target", f"{target_namespace}/{target_agent}".strip("/")))
    if payload.get("targetThreadId"):
        rows.append(("Target Thread", str(payload.get("targetThreadId"))))
    if payload.get("responseStatus"):
        rows.append(("Target Status", str(payload.get("responseStatus"))))
    if caller_agent or caller_namespace:
        rows.append(("Caller", f"{caller_namespace}/{caller_agent}".strip("/")))
    if payload.get("parentThreadId"):
        rows.append(("Parent Thread", str(payload.get("parentThreadId"))))
    if payload.get("callerRequestId"):
        rows.append(("Caller Request", str(payload.get("callerRequestId"))))

    if rows:
        render_info_table("A2A", rows)


def render_subagent_metadata(payload: Any) -> None:
    if not isinstance(payload, dict) or not payload:
        return

    results = payload.get("results") if isinstance(payload.get("results"), list) else []
    render_info_table(
        "Specialist Team",
        [
            ("Strategy", str(payload.get("strategy") or "sequential")),
            ("Members", str(payload.get("count") or len(results))),
            ("Shared Session", "yes" if bool(payload.get("sharedSandboxSession")) else "no"),
            ("Artifacts", str(len(payload.get("resultFiles") or []))),
        ],
    )

    if not results:
        return

    table = Table(title="Subagent Results", box=box.ROUNDED)
    table.add_column("Target", style="title")
    table.add_column("Role", style="accent")
    table.add_column("Status")
    table.add_column("Transport", style="accent")
    table.add_column("Thread", style="muted")
    table.add_column("Artifact", style="accent")
    for item in results:
        if not isinstance(item, dict):
            continue
        target = f"{item.get('namespace', '')}/{item.get('name', '')}".strip("/")
        table.add_row(
            target or "-",
            str(item.get("role") or "-"),
            styled_status(str(item.get("status") or "unknown")),
            str(item.get("transport") or "-"),
            str(item.get("threadId") or "-"),
            str(item.get("resultFilePath") or "-"),
        )
    console.print(table)


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
    if "tool_result" in data and tool_result is not None:
        console.print(Panel(Pretty(tool_result), title="Tool Result", border_style="accent"))
    sandbox_session = data.get("sandbox_session")
    if sandbox_session:
        console.print(Panel(Pretty(sandbox_session), title="Sandbox Session", border_style="accent"))
    render_a2a_metadata(data.get("a2a"))
    render_subagent_metadata(data.get("subagents"))
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


def read_any_structured_file(file_path: Path) -> Any:
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

    return loaded


def read_structured_file(file_path: Path) -> dict[str, Any]:
    loaded = read_any_structured_file(file_path)

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


def normalize_subagent_strategy_text(value: str | None) -> str | None:
    if value is None:
        return None
    strategy = value.strip().lower()
    if not strategy:
        return None
    if strategy not in {"sequential", "parallel"}:
        fatal("--subagent-strategy must be either 'sequential' or 'parallel'.")
    return strategy


def parse_subagent_ref_text(value: str, source: str) -> tuple[str, str]:
    raw_value = value.strip()
    namespace, separator, name = raw_value.partition("/")
    if not separator or not namespace.strip() or not name.strip():
        fatal(f"{source} must use namespace/name syntax. Invalid value: {value}")
    namespace = namespace.strip()
    name = name.strip()
    if not K8S_NAME_RE.fullmatch(namespace):
        fatal(f"{source} namespace must be a valid lowercase Kubernetes name. Invalid value: {namespace}")
    if not K8S_NAME_RE.fullmatch(name):
        fatal(f"{source} name must be a valid lowercase Kubernetes name. Invalid value: {name}")
    return namespace, name


def normalize_subagent_input_files(values: Any, source: str) -> list[dict[str, Any]]:
    if values in (None, "", []):
        return []
    if not isinstance(values, list):
        fatal(f"{source} must be a list when provided.")

    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(values):
        label = f"{source}[{index}]"
        if isinstance(item, str):
            path = item.strip()
            if not path:
                continue
            normalized.append({"path": path})
            continue
        if not isinstance(item, dict):
            fatal(f"{label} must be a string path or object.")

        path = str(snake_or_camel(item, "path", "path", "") or "").strip()
        if not path:
            fatal(f"{label}.path is required.")
        entry: dict[str, Any] = {"path": path}
        purpose = str(snake_or_camel(item, "purpose", "purpose", "") or "").strip()
        if purpose:
            entry["purpose"] = purpose
        include_content = snake_or_camel(item, "include_content", "includeContent")
        if include_content is not None:
            if not isinstance(include_content, bool):
                fatal(f"{label}.include_content must be a boolean when provided.")
            entry["include_content"] = include_content
        max_chars = snake_or_camel(item, "max_chars", "maxChars")
        if max_chars is not None:
            try:
                parsed_max_chars = int(max_chars)
            except (TypeError, ValueError):
                fatal(f"{label}.max_chars must be an integer when provided.")
            if parsed_max_chars < 1:
                fatal(f"{label}.max_chars must be greater than or equal to 1.")
            entry["max_chars"] = parsed_max_chars
        normalized.append(entry)
    return normalized


def normalize_subagent_payload_item(item: Any, source: str) -> dict[str, Any]:
    if not isinstance(item, dict):
        fatal(f"{source} must be an object.")

    name = str(snake_or_camel(item, "name", "name", "") or "").strip()
    namespace = str(snake_or_camel(item, "namespace", "namespace", "") or "").strip()
    if not name or not namespace:
        raw_ref = str(snake_or_camel(item, "ref", "agentRef", "") or "").strip()
        if raw_ref:
            namespace, name = parse_subagent_ref_text(raw_ref, f"{source}.ref")
    if not name or not namespace:
        fatal(f"{source} requires name and namespace fields, or ref/agentRef using namespace/name syntax.")
    if not K8S_NAME_RE.fullmatch(namespace):
        fatal(f"{source}.namespace must be a valid lowercase Kubernetes name.")
    if not K8S_NAME_RE.fullmatch(name):
        fatal(f"{source}.name must be a valid lowercase Kubernetes name.")

    normalized: dict[str, Any] = {
        "name": name,
        "namespace": namespace,
    }
    role = str(snake_or_camel(item, "role", "role", "") or "").strip()
    if role:
        normalized["role"] = role
    task = str(snake_or_camel(item, "task", "task", "") or "").strip()
    if task:
        normalized["task"] = task
    result_file_path = str(snake_or_camel(item, "result_file_path", "resultFilePath", "") or "").strip()
    if result_file_path:
        normalized["result_file_path"] = result_file_path
    input_files = normalize_subagent_input_files(
        snake_or_camel(item, "input_files", "inputFiles", []),
        f"{source}.input_files",
    )
    if input_files:
        normalized["input_files"] = input_files
    share_sandbox_session = snake_or_camel(item, "share_sandbox_session", "shareSandboxSession", True)
    if not isinstance(share_sandbox_session, bool):
        fatal(f"{source}.share_sandbox_session must be a boolean when provided.")
    normalized["share_sandbox_session"] = share_sandbox_session
    timeout_seconds = snake_or_camel(item, "timeout_seconds", "timeoutSeconds")
    if timeout_seconds is not None:
        try:
            parsed_timeout = float(timeout_seconds)
        except (TypeError, ValueError):
            fatal(f"{source}.timeout_seconds must be numeric when provided.")
        if parsed_timeout < 1:
            fatal(f"{source}.timeout_seconds must be greater than or equal to 1.")
        normalized["timeout_seconds"] = parsed_timeout
    metadata = snake_or_camel(item, "metadata", "metadata")
    if metadata is not None:
        if not isinstance(metadata, dict):
            fatal(f"{source}.metadata must be an object when provided.")
        normalized["metadata"] = metadata
    return normalized


def parse_subagent_shorthand(value: str, source: str) -> dict[str, Any]:
    ref_text, role_text, task_text = [part.strip() for part in (value.split("|", 2) + ["", ""])[:3]]
    namespace, name = parse_subagent_ref_text(ref_text, source)
    payload: dict[str, Any] = {
        "name": name,
        "namespace": namespace,
        "share_sandbox_session": True,
    }
    if role_text:
        payload["role"] = role_text
    if task_text:
        payload["task"] = task_text
    return payload


def load_subagents_file(file_path: Path) -> tuple[list[dict[str, Any]], str | None]:
    loaded = read_any_structured_file(file_path)
    strategy: str | None = None
    raw_subagents: Any = loaded
    if isinstance(loaded, dict):
        if "subagents" in loaded or "subagent_strategy" in loaded or "subagentStrategy" in loaded:
            raw_subagents = snake_or_camel(loaded, "subagents", "subagents", [])
            strategy = normalize_subagent_strategy_text(
                str(snake_or_camel(loaded, "subagent_strategy", "subagentStrategy", "") or "")
            )
        else:
            raw_subagents = [loaded]

    if not isinstance(raw_subagents, list):
        fatal(f"{file_path} must contain either a subagents array or a single subagent object.")

    normalized = [
        normalize_subagent_payload_item(item, f"{file_path}.subagents[{index}]")
        for index, item in enumerate(raw_subagents)
    ]
    return normalized, strategy


def snake_or_camel(payload: dict[str, Any], snake_key: str, camel_key: str, default: Any = None) -> Any:
    if snake_key in payload:
        return payload[snake_key]
    if camel_key in payload:
        return payload[camel_key]
    return default


def normalize_goose_config_files_value(value: Any, field_name: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"{field_name} must be an object keyed by relative Goose config file paths.")
    return dict(value)


def normalize_opencode_config_files_value(value: Any, field_name: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"{field_name} must be an object keyed by relative OpenCode config file paths.")
    return dict(value)


def normalize_agent_skills_value(value: Any, field_name: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        fatal(f"{field_name} must be an object.")

    raw_files = snake_or_camel(value, "files", "files", {})
    if raw_files in (None, {}):
        return {}
    if not isinstance(raw_files, dict):
        fatal(f"{field_name}.files must be an object keyed by relative Markdown file paths.")

    normalized_files: dict[str, str] = {}
    for raw_path, raw_content in sorted(raw_files.items(), key=lambda item: str(item[0])):
        path = str(raw_path or "").replace("\\", "/").strip()
        if not path:
            fatal(f"{field_name}.files keys must not be blank.")
        if not path.lower().endswith(".md"):
            fatal(f"{field_name}.files.{path} must point to a Markdown file ending in .md.")
        if not isinstance(raw_content, str):
            fatal(f"{field_name}.files.{path} must be a Markdown string.")
        if not raw_content.strip():
            fatal(f"{field_name}.files.{path} must not be blank.")
        normalized_files[path] = raw_content.replace("\r\n", "\n")
    return {"files": normalized_files} if normalized_files else {}


def normalize_a2a_peer_ref(value: Any, field_name: str) -> dict[str, str]:
    if not isinstance(value, dict):
        fatal(f"{field_name} entries must be objects with name and namespace fields.")
    name = str(value.get("name", "")).strip()
    namespace = str(value.get("namespace", "")).strip()
    if not name or not namespace:
        fatal(f"{field_name} entries must include non-empty name and namespace values.")
    if not K8S_NAME_RE.fullmatch(name):
        fatal(f"{field_name}.name must be a valid lowercase Kubernetes resource name.")
    if not K8S_NAME_RE.fullmatch(namespace):
        fatal(f"{field_name}.namespace must be a valid lowercase Kubernetes namespace name.")
    return {"name": name, "namespace": namespace}


def normalize_a2a_peer_refs(value: Any, field_name: str) -> list[dict[str, str]]:
    if value is None:
        return []
    if not isinstance(value, list):
        fatal(f"{field_name} must be a list.")
    normalized: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for index, item in enumerate(value):
        peer_ref = normalize_a2a_peer_ref(item, f"{field_name}[{index}]")
        identity = (peer_ref["namespace"], peer_ref["name"])
        if identity in seen:
            continue
        seen.add(identity)
        normalized.append(peer_ref)
    return normalized


def normalize_a2a_config_value(value: Any, field_name: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        fatal(f"{field_name} must be an object.")
    return {
        "allowed_callers": normalize_a2a_peer_refs(
            snake_or_camel(value, "allowed_callers", "allowedCallers", []),
            f"{field_name}.allowed_callers",
        )
    }


def parse_goose_config_assignment(spec: str, *, field_name: str) -> tuple[str, str]:
    relative_path, separator, raw_value = spec.partition("=")
    if not separator or not relative_path.strip() or not raw_value.strip():
        raise ValueError(f"{field_name} entries must use RELATIVE_PATH=VALUE syntax.")
    return relative_path.strip(), raw_value.strip()


def build_goose_config_files_payload(
    current: Any,
    *,
    clear_existing: bool = False,
    file_assignments: list[str] | None = None,
    text_assignments: list[str] | None = None,
) -> dict[str, Any]:
    merged = {} if clear_existing else normalize_goose_config_files_value(current, "goose_config_files")

    for assignment in file_assignments or []:
        relative_path, source_path_text = parse_goose_config_assignment(
            assignment,
            field_name="--goose-config-file",
        )
        source_path = Path(source_path_text)
        try:
            merged[relative_path] = source_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise ValueError(f"Failed to read Goose config source file {source_path}: {exc}") from exc

    for assignment in text_assignments or []:
        relative_path, inline_text = parse_goose_config_assignment(
            assignment,
            field_name="--goose-config-text",
        )
        merged[relative_path] = inline_text

    return merged


def build_opencode_config_files_payload(
    current: Any,
    *,
    clear_existing: bool = False,
    file_assignments: list[str] | None = None,
    text_assignments: list[str] | None = None,
) -> dict[str, Any]:
    merged = {} if clear_existing else normalize_opencode_config_files_value(current, "opencode_config_files")

    for assignment in file_assignments or []:
        relative_path, source_path_text = parse_goose_config_assignment(
            assignment,
            field_name="--opencode-config-file",
        )
        source_path = Path(source_path_text)
        try:
            merged[relative_path] = source_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise ValueError(f"Failed to read OpenCode config source file {source_path}: {exc}") from exc

    for assignment in text_assignments or []:
        relative_path, inline_text = parse_goose_config_assignment(
            assignment,
            field_name="--opencode-config-text",
        )
        merged[relative_path] = inline_text

    return merged


def agent_payload_from_detail(detail: dict[str, Any]) -> dict[str, Any]:
    return {
        "model": str(detail.get("model", "")),
        "system_prompt": str(detail.get("system_prompt", "")),
        "policy_ref": detail.get("policy_ref"),
        "storage_size": detail.get("storage_size") or "1Gi",
        "runtime_kind": str(detail.get("runtime_kind") or "langgraph"),
        "enable_gvisor": bool(detail.get("enable_gvisor", False)),
        "mcp_servers": normalize_list_of_strings(detail.get("mcp_servers"), "mcp_servers"),
        "mcp_sidecars": normalize_sidecars(detail.get("mcp_sidecars")),
        "a2a_config": normalize_a2a_config_value(detail.get("a2a_config"), "a2a_config"),
        "skills": normalize_agent_skills_value(detail.get("skills"), "skills"),
        "goose_config_files": normalize_goose_config_files_value(
            detail.get("goose_config_files"),
            "goose_config_files",
        ),
        "opencode_config_files": normalize_opencode_config_files_value(
            detail.get("opencode_config_files"),
            "opencode_config_files",
        ),
    }


def coerce_agent_payload(document: dict[str, Any], *, for_update: bool) -> tuple[dict[str, Any], str | None]:
    metadata = document.get("metadata") if isinstance(document.get("metadata"), dict) else {}
    if document.get("kind") == "AIAgent" and isinstance(document.get("spec"), dict):
        spec = document["spec"]
        storage = spec.get("storage") if isinstance(spec.get("storage"), dict) else {}
        runtime = spec.get("runtime") if isinstance(spec.get("runtime"), dict) else {}
        goose_runtime = runtime.get("goose") if isinstance(runtime.get("goose"), dict) else {}
        opencode_runtime = runtime.get("opencode") if isinstance(runtime.get("opencode"), dict) else {}
        payload: dict[str, Any] = {
            "model": str(spec.get("model", "")),
            "system_prompt": str(spec.get("systemPrompt", "")),
            "policy_ref": spec.get("policyRef"),
            "storage_size": storage.get("size", "1Gi"),
            "runtime_kind": str(runtime.get("kind", "langgraph") or "langgraph"),
            "enable_gvisor": bool(spec.get("enableGVisor", False)),
            "mcp_servers": normalize_list_of_strings(spec.get("mcpServers"), "mcpServers"),
            "mcp_sidecars": normalize_sidecars(spec.get("mcpSidecars")),
            "a2a_config": normalize_a2a_config_value(spec.get("a2a"), "spec.a2a"),
            "skills": normalize_agent_skills_value(spec.get("skills"), "spec.skills"),
            "goose_config_files": normalize_goose_config_files_value(
                goose_runtime.get("configFiles"),
                "runtime.goose.configFiles",
            ),
            "opencode_config_files": normalize_opencode_config_files_value(
                opencode_runtime.get("configFiles"),
                "runtime.opencode.configFiles",
            ),
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
        "runtime_kind": str(snake_or_camel(payload, "runtime_kind", "runtimeKind", "langgraph") or "langgraph"),
        "enable_gvisor": bool(snake_or_camel(payload, "enable_gvisor", "enableGVisor", False)),
        "mcp_servers": normalize_list_of_strings(
            snake_or_camel(payload, "mcp_servers", "mcpServers", []),
            "mcp_servers",
        ),
        "mcp_sidecars": normalize_sidecars(snake_or_camel(payload, "mcp_sidecars", "mcpSidecars", [])),
        "a2a_config": normalize_a2a_config_value(
            snake_or_camel(payload, "a2a_config", "a2aConfig", {}),
            "a2a_config",
        ),
        "skills": normalize_agent_skills_value(
            snake_or_camel(payload, "skills", "skills", {}),
            "skills",
        ),
        "goose_config_files": normalize_goose_config_files_value(
            snake_or_camel(payload, "goose_config_files", "gooseConfigFiles", {}),
            "goose_config_files",
        ),
        "opencode_config_files": normalize_opencode_config_files_value(
            snake_or_camel(payload, "opencode_config_files", "opencodeConfigFiles", {}),
            "opencode_config_files",
        ),
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


def load_prompt(prompt_parts: list[str], file_path: Path | None, *, allow_empty: bool = False) -> str:
    if file_path is not None:
        return file_path.read_text(encoding="utf-8").strip()
    if prompt_parts:
        return " ".join(prompt_parts).strip()
    if not sys.stdin.isatty():
        return sys.stdin.read().strip()
    if allow_empty:
        return ""
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
    for key in ("tool_name", "status", "approval_name", "request_id", "role", "name", "namespace"):
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
    system: str | None = typer.Option(None, "--system", help="Additional Goose system instructions."),
    require_approval: bool = typer.Option(False, "--require-approval", help="Request HITL approval."),
    approval_action: str | None = typer.Option(None, "--approval-action", help="Approval action label."),
    no_session: bool = typer.Option(False, "--no-session", help="Disable Goose session persistence for this invoke."),
    max_turns: int | None = typer.Option(None, "--max-turns", min=1, help="Limit Goose autonomous turns for this invoke."),
    max_retries: int | None = typer.Option(None, "--max-retries", min=0, help="Limit OpenCode autonomous retries for this invoke."),
    debug: bool = typer.Option(False, "--debug", help="Enable Goose debug output for this invoke."),
    output_format: str | None = typer.Option(
        None,
        "--output-format",
        help="Preferred final output format for runtimes that support it: json, code, markdown, or text.",
    ),
    output_schema_file: Path | None = typer.Option(
        None,
        "--output-schema-file",
        exists=True,
        file_okay=True,
        dir_okay=False,
        help="JSON or YAML schema file used for OpenCode structured JSON output.",
    ),
    no_autonomous: bool = typer.Option(
        False,
        "--no-autonomous",
        help="Disable OpenCode's autonomous completion prompt and retry flow for this invoke.",
    ),
    working_directory: str | None = typer.Option(
        None,
        "--working-directory",
        help="Run Goose from a subdirectory inside the runtime workspace.",
    ),
    builtin: list[str] | None = typer.Option(
        None,
        "--builtin",
        help="Enable a Goose builtin extension for this invoke. Can be repeated.",
    ),
    extension: list[str] | None = typer.Option(
        None,
        "--extension",
        help="Add a Goose stdio extension command for this invoke. Can be repeated.",
    ),
    http_extension: list[str] | None = typer.Option(
        None,
        "--http-extension",
        help="Add a Goose Streamable HTTP extension URL for this invoke. Can be repeated.",
    ),
    a2a_target_agent: str | None = typer.Option(
        None,
        "--a2a-target-agent",
        help="Route this request through an explicit A2A call to the named target agent.",
    ),
    a2a_target_namespace: str | None = typer.Option(
        None,
        "--a2a-target-namespace",
        help="Namespace of the explicit A2A target agent.",
    ),
    a2a_timeout_seconds: float | None = typer.Option(
        None,
        "--a2a-timeout-seconds",
        min=1.0,
        help="Maximum time the caller should wait for the callee response.",
    ),
    subagent: list[str] | None = typer.Option(
        None,
        "--subagent",
        help="Add a specialist using namespace/name|role|task. Can be repeated.",
    ),
    subagents_file: Path | None = typer.Option(
        None,
        "--subagents-file",
        exists=True,
        file_okay=True,
        dir_okay=False,
        help="Load specialist-team definitions from a JSON or YAML file.",
    ),
    subagent_strategy: str | None = typer.Option(
        None,
        "--subagent-strategy",
        help="Execution strategy for specialists: sequential or parallel.",
    ),
) -> None:
    """Invoke an agent with a prompt."""
    settings = ctx_settings(ctx)

    subagent_payloads: list[dict[str, Any]] = []
    file_strategy: str | None = None
    if subagents_file is not None:
        subagent_payloads, file_strategy = load_subagents_file(subagents_file)
    for index, item in enumerate(subagent or []):
        subagent_payloads.append(parse_subagent_shorthand(item, f"--subagent[{index}]"))
    resolved_subagent_strategy = normalize_subagent_strategy_text(subagent_strategy) or file_strategy

    try:
        prompt = load_prompt(prompt_parts or [], prompt_file, allow_empty=bool(subagent_payloads))
    except OSError as exc:
        fatal(f"Failed to read prompt file: {exc}")
    if not prompt and not subagent_payloads:
        fatal("Prompt must not be empty.")
    if not prompt and not any(item.get("task") for item in subagent_payloads):
        fatal("Provide a prompt or set at least one specialist task when using specialist teams.")
    if no_session and thread_id:
        fatal("--thread-id cannot be combined with --no-session.")
    if output_format and output_format.strip().lower() not in {"json", "code", "markdown", "text"}:
        fatal("--output-format must be one of: json, code, markdown, text.")
    if output_schema_file is not None and (output_format or "").strip().lower() not in {"", "json"}:
        fatal("--output-schema-file can only be used with --output-format json.")
    if bool(a2a_target_agent) != bool(a2a_target_namespace):
        fatal("Pass both --a2a-target-agent and --a2a-target-namespace together.")
    if subagent_payloads and a2a_target_agent:
        fatal("Specialist teams cannot be combined with explicit A2A routing in a single invoke.")
    if a2a_target_agent and not K8S_NAME_RE.fullmatch(a2a_target_agent.strip()):
        fatal("--a2a-target-agent must be a valid lowercase Kubernetes resource name.")
    if a2a_target_namespace and not K8S_NAME_RE.fullmatch(a2a_target_namespace.strip()):
        fatal("--a2a-target-namespace must be a valid lowercase Kubernetes namespace name.")
    if resolved_subagent_strategy and not subagent_payloads:
        fatal("--subagent-strategy requires at least one specialist definition.")

    payload: dict[str, Any] = {"prompt": prompt}
    if thread_id:
        payload["thread_id"] = thread_id
    if system:
        payload["system"] = system
    if require_approval:
        payload["require_approval"] = True
    if approval_action:
        payload["approval_action"] = approval_action
    if no_session:
        payload["no_session"] = True
    if max_turns is not None:
        payload["max_turns"] = max_turns
    if max_retries is not None:
        payload["max_retries"] = max_retries
    if debug:
        payload["debug"] = True
    if output_format:
        payload["output_format"] = output_format.strip().lower()
    if output_schema_file is not None:
        try:
            schema_payload = read_any_structured_file(output_schema_file)
        except OSError as exc:
            fatal(f"Failed to read output schema file: {exc}")
        if not isinstance(schema_payload, dict):
            fatal("--output-schema-file must contain a JSON or YAML object.")
        payload["output_schema"] = schema_payload
        payload.setdefault("output_format", "json")
    if no_autonomous:
        payload["autonomous"] = False
    if working_directory:
        payload["working_directory"] = working_directory
    if builtin:
        payload["builtin_extensions"] = builtin
    if extension:
        payload["stdio_extensions"] = extension
    if http_extension:
        payload["streamable_http_extensions"] = http_extension
    if a2a_target_agent and a2a_target_namespace:
        payload["a2a_target_agent"] = a2a_target_agent.strip()
        payload["a2a_target_namespace"] = a2a_target_namespace.strip()
    if a2a_timeout_seconds is not None:
        payload["a2a_timeout_seconds"] = a2a_timeout_seconds
    if subagent_payloads:
        payload["subagents"] = subagent_payloads
    if resolved_subagent_strategy:
        payload["subagent_strategy"] = resolved_subagent_strategy

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
                render_a2a_metadata(completed_payload.get("a2a"))
                render_subagent_metadata(completed_payload.get("subagents"))
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


@agents_app.command("discover")
def agents_discover(
    ctx: typer.Context,
    agent_name: str = typer.Argument(..., help="Agent name."),
    include_unreachable: bool = typer.Option(
        False,
        "--include-unreachable",
        help="Include configured targets that are currently blocked, missing, or not running.",
    ),
) -> None:
    """Show the agent's configured A2A targets and which ones are currently callable."""
    settings = ctx_settings(ctx)
    try:
        with console.status(f"[accent]Discovering A2A peers for {agent_name}...[/accent]"):
            with ApiClient(settings) as client:
                data = client.json(
                    "GET",
                    f"/api/agents/{agent_name}/discover",
                    params=namespace_params(settings),
                )
    except ApiError as exc:
        fatal(str(exc), status_code=exc.status_code)
    render_agent_discovery(data, settings.json_output, include_unreachable)


@agents_app.command("update")
def agents_update(
    ctx: typer.Context,
    agent_name: str | None = typer.Argument(None, help="Agent name. Optional when the file contains metadata.name."),
    file_path: Path | None = typer.Option(None, "--file", "-f", exists=True, file_okay=True, dir_okay=False),
    goose_config_file: list[str] | None = typer.Option(
        None,
        "--goose-config-file",
        help="Map a Goose config-root path to a local file using RELATIVE_PATH=FILE. Can be repeated.",
    ),
    goose_config_text: list[str] | None = typer.Option(
        None,
        "--goose-config-text",
        help="Set a Goose config-root file from inline text using RELATIVE_PATH=TEXT. Can be repeated.",
    ),
    clear_goose_config_files: bool = typer.Option(
        False,
        "--clear-goose-config-files",
        help="Remove all existing agent-specific Goose config files before applying overrides.",
    ),
    opencode_config_file: list[str] | None = typer.Option(
        None,
        "--opencode-config-file",
        help="Map an OpenCode config-root path to a local file using RELATIVE_PATH=FILE. Can be repeated.",
    ),
    opencode_config_text: list[str] | None = typer.Option(
        None,
        "--opencode-config-text",
        help="Set an OpenCode config-root file from inline text using RELATIVE_PATH=TEXT. Can be repeated.",
    ),
    clear_opencode_config_files: bool = typer.Option(
        False,
        "--clear-opencode-config-files",
        help="Remove all existing agent-specific OpenCode config files before applying overrides.",
    ),
) -> None:
    """Update an agent from a file or patch runtime config files directly."""
    settings = ctx_settings(ctx)
    document: dict[str, Any] = {}
    inferred_name: str | None = None
    namespace = settings.namespace
    goose_override_requested = clear_goose_config_files or bool(goose_config_file) or bool(goose_config_text)
    opencode_override_requested = clear_opencode_config_files or bool(opencode_config_file) or bool(opencode_config_text)
    override_requested = goose_override_requested or opencode_override_requested

    if goose_override_requested and opencode_override_requested:
        fatal("Choose either Goose or OpenCode config override flags in a single update command, not both.")

    if file_path is not None:
        document = read_structured_file(file_path)
        payload, inferred_name = coerce_agent_payload(document, for_update=True)
        namespace = resolve_namespace(settings, document)
    else:
        if not override_requested:
            fatal("Pass --file or at least one runtime config override flag.")
        if not agent_name or not agent_name.strip():
            fatal("Agent name is required when updating without --file.")
        resolved_name = resolve_resource_name(agent_name, None, None, "agent")
        try:
            with console.status(f"[accent]Loading agent {resolved_name}...[/accent]"):
                with ApiClient(settings) as client:
                    current_detail = client.json(
                        "GET",
                        f"/api/agents/{resolved_name}",
                        params=namespace_params(settings),
                    )
        except ApiError as exc:
            fatal(str(exc), status_code=exc.status_code)

        if not isinstance(current_detail, dict):
            fatal("Agent detail response must be a JSON object.")
        payload = agent_payload_from_detail(current_detail)

    resolved_name = resolve_resource_name(agent_name, file_path, inferred_name, "agent")

    try:
        if goose_override_requested:
            runtime_kind = str(payload.get("runtime_kind", "langgraph") or "langgraph").strip().lower() or "langgraph"
            if runtime_kind != "goose":
                fatal(
                    "Goose config overrides require a Goose agent/runtime. Switch the agent to runtime_kind=goose first or update from a file that sets it."
                )
            payload["goose_config_files"] = build_goose_config_files_payload(
                payload.get("goose_config_files"),
                clear_existing=clear_goose_config_files,
                file_assignments=goose_config_file,
                text_assignments=goose_config_text,
            )
        if opencode_override_requested:
            runtime_kind = str(payload.get("runtime_kind", "langgraph") or "langgraph").strip().lower() or "langgraph"
            if runtime_kind != "opencode":
                fatal(
                    "OpenCode config overrides require an OpenCode agent/runtime. Switch the agent to runtime_kind=opencode first or update from a file that sets it."
                )
            payload["opencode_config_files"] = build_opencode_config_files_payload(
                payload.get("opencode_config_files"),
                clear_existing=clear_opencode_config_files,
                file_assignments=opencode_config_file,
                text_assignments=opencode_config_text,
            )
    except ValueError as exc:
        fatal(str(exc))

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


# ── Skills & Tools Catalog ───────────────────────────────────────────────────

skills_app = typer.Typer(no_args_is_help=True, help="Browse the skills catalog.")
tools_app = typer.Typer(no_args_is_help=True, help="Browse MCP tool sidecars.")
app.add_typer(skills_app, name="skills")
app.add_typer(tools_app, name="tools")


@skills_app.command("list")
def skills_list(
    ctx: typer.Context,
    category: str = typer.Option("", "--category", "-c", help="Filter by category."),
    search: str = typer.Option("", "--search", "-s", help="Search by name or description."),
) -> None:
    """List skills from the catalog."""
    settings = ctx_settings(ctx)
    params: dict[str, Any] = {}
    if category:
        params["category"] = category
    if search:
        params["search"] = search
    with ApiClient(settings) as api:
        try:
            data = api.json("GET", "/api/skills/catalog", params=params)
        except ApiError as exc:
            fatal(str(exc), status_code=exc.status_code)
    if settings.json_output:
        print_json(data)
        return
    items = data.get("skills", [])
    if not items:
        console.print("[muted]No skills found.[/muted]")
        return
    table = Table(title="Skills Catalog", box=box.SIMPLE_HEAVY, border_style="accent")
    table.add_column("ID", style="title")
    table.add_column("Name")
    table.add_column("Category", style="accent")
    table.add_column("Files", justify="right")
    table.add_column("Description")
    for skill in items:
        table.add_row(
            skill.get("id", ""),
            skill.get("name", ""),
            skill.get("category", ""),
            str(len(skill.get("files", []))),
            (skill.get("description", "") or "")[:60],
        )
    console.print(table)
    console.print(f"[muted]{len(items)} skill(s) found[/muted]")


@skills_app.command("get")
def skills_get(
    ctx: typer.Context,
    skill_id: str = typer.Argument(help="The skill ID to inspect."),
) -> None:
    """Show details for a specific skill."""
    settings = ctx_settings(ctx)
    with ApiClient(settings) as api:
        try:
            data = api.json("GET", f"/api/skills/catalog/{skill_id}")
        except ApiError as exc:
            fatal(str(exc), status_code=exc.status_code)
    if settings.json_output:
        print_json(data)
        return
    render_info_table(
        f"Skill: {data.get('name', skill_id)}",
        [
            ("ID", data.get("id", "")),
            ("Category", data.get("category", "")),
            ("Tags", ", ".join(data.get("tags", []))),
            ("Description", data.get("description", "")),
            ("Files", ", ".join(data.get("files", []))),
            ("Total Size", f"{data.get('total_size_bytes', 0)} bytes"),
        ],
    )
    assets = data.get("assets", {})
    for path, content in assets.items():
        console.print(f"\n[accent]── {path} ──[/accent]")
        if path.endswith(".md"):
            console.print(Markdown(content[:2000]))
        else:
            console.print(Syntax(content[:2000], "text", theme="monokai"))


@tools_app.command("list")
def tools_list(ctx: typer.Context) -> None:
    """List available MCP tool sidecar categories."""
    settings = ctx_settings(ctx)
    with ApiClient(settings) as api:
        try:
            data = api.json("GET", "/api/skills/tools")
        except ApiError as exc:
            fatal(str(exc), status_code=exc.status_code)
    if settings.json_output:
        print_json(data)
        return
    categories = data.get("categories", [])
    if not categories:
        console.print("[muted]No tool categories available.[/muted]")
        return
    table = Table(title="MCP Tool Sidecars", box=box.SIMPLE_HEAVY, border_style="accent")
    table.add_column("ID", style="title")
    table.add_column("Name")
    table.add_column("Port", justify="right")
    table.add_column("Description")
    for cat in categories:
        table.add_row(
            cat.get("id", ""),
            cat.get("name", ""),
            str(cat.get("default_port", "")),
            (cat.get("description", "") or "")[:60],
        )
    console.print(table)


@get_app.command("skills")
def get_skills(ctx: typer.Context) -> None:
    """Compatibility alias for `agentctl skills list`."""
    skills_list(ctx)


@get_app.command("tools")
def get_tools(ctx: typer.Context) -> None:
    """Compatibility alias for `agentctl tools list`."""
    tools_list(ctx)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
