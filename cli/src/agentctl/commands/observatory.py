"""Observatory commands — metrics, traces, alerts, signals."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
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
    print_table,
    success,
)

observatory_app = typer.Typer(
    no_args_is_help=True,
    rich_markup_mode="rich",
    epilog=(
        "[bold]Examples:[/bold]\n"
        "  agentctl observatory metrics --window 24h\n"
        "  agentctl observatory traces --agent my-agent --limit 20\n"
        "  agentctl observatory alerts --all\n"
        "  agentctl observatory signals --agent my-agent\n"
        "  agentctl observatory health"
    ),
)


def _api() -> ApiClient:
    return ApiClient(get_settings())


def _ns_params() -> dict[str, Any]:
    return {"namespace": get_settings().namespace}


def _normalize_trace_item(item: dict[str, Any]) -> dict[str, Any]:
    """Normalize legacy and current trace payloads for table rendering."""
    normalized = dict(item)
    normalized.setdefault("trace_id", item.get("trace_id") or item.get("id"))
    normalized.setdefault("timestamp", item.get("timestamp") or item.get("started_at") or item.get("completed_at"))
    normalized.setdefault("run_id", item.get("run_id") or item.get("thread_id"))
    return normalized


def _window_to_from_date(window: str) -> str:
    """Convert a CLI time window to an ISO8601 from_date."""
    normalized = window.strip()
    match = re.fullmatch(r"(?i)(\d+)([smhd])", normalized)
    if match:
        amount = int(match.group(1))
        unit = match.group(2).lower()
        delta = {
            "s": timedelta(seconds=amount),
            "m": timedelta(minutes=amount),
            "h": timedelta(hours=amount),
            "d": timedelta(days=amount),
        }[unit]
        return (datetime.now(UTC) - delta).isoformat()

    try:
        parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    except ValueError as exc:
        raise typer.BadParameter("Window must look like 30m, 2h, 7d, or an ISO timestamp/date.") from exc

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).isoformat()


def _summarize_usage_items(items: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate usage rows into a CLI-friendly summary block."""
    return {
        "groups": len(items),
        "invocations": sum(int(item.get("invocations") or 0) for item in items),
        "prompt_tokens": sum(int(item.get("prompt_tokens") or 0) for item in items),
        "completion_tokens": sum(int(item.get("completion_tokens") or 0) for item in items),
        "total_tokens": sum(int(item.get("total_tokens") or 0) for item in items),
        "estimated_cost_usd": round(sum(float(item.get("estimated_cost_usd") or 0.0) for item in items), 6),
    }


def _report_severity(item: dict[str, Any]) -> str:
    """Infer a single severity label from an ObservationReport summary."""
    findings = item.get("findings") if isinstance(item.get("findings"), list) else []
    rank = {"info": 0, "low": 1, "warning": 2, "medium": 2, "high": 3, "critical": 4}
    severity = "info"
    for finding in findings:
        if not isinstance(finding, dict):
            continue
        candidate = str(finding.get("severity") or "info").lower()
        if rank.get(candidate, 0) > rank.get(severity, 0):
            severity = candidate
    if severity != "info":
        return severity
    if int(item.get("findingsCount") or 0) > 0:
        return "warning"
    return "info"


def _normalize_alert_item(item: dict[str, Any]) -> dict[str, Any]:
    """Normalize ObservationReport rows into alert-like CLI records."""
    normalized = dict(item)
    normalized.setdefault("severity", _report_severity(item))
    normalized.setdefault("target", item.get("targetRef") or item.get("name"))
    normalized.setdefault("message", item.get("summary") or item.get("reportType") or item.get("name"))
    normalized.setdefault("timestamp", item.get("lastEvaluated") or item.get("createdAt"))
    normalized.setdefault("status", "active" if int(item.get("findingsCount") or 0) > 0 else "clear")
    return normalized


def _runtime_event_message(item: dict[str, Any]) -> str:
    """Extract a compact human-readable message from a runtime event."""
    payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
    error = payload.get("error")
    if error:
        return str(error)

    caller = payload.get("caller_agent")
    target = payload.get("target_agent")
    if caller and target:
        return f"{caller} -> {target}"

    step_name = payload.get("step_name")
    status = payload.get("status")
    if step_name and status:
        return f"{step_name} [{status}]"
    if step_name:
        return str(step_name)

    tool_name = payload.get("tool_name")
    if tool_name:
        return str(tool_name)

    model = payload.get("model")
    if model:
        return str(model)

    workflow_name = payload.get("workflow_name")
    if workflow_name:
        return str(workflow_name)

    return str(item.get("event_type") or item.get("id") or "event")


def _normalize_signal_item(item: dict[str, Any]) -> dict[str, Any]:
    """Normalize runtime events into signal-style CLI rows."""
    normalized = dict(item)
    normalized.setdefault("signal_type", item.get("signal_type") or item.get("event_type"))
    normalized.setdefault("timestamp", item.get("timestamp") or item.get("created_at"))
    normalized.setdefault("message", item.get("message") or _runtime_event_message(item))
    return normalized


# ─── Metrics ───


@observatory_app.command("metrics")
def observatory_metrics(
    agent_name: str | None = typer.Option(None, "--agent", "-a", help="Filter by agent."),
    window: str = typer.Option("1h", "--window", "-w", help="Time window (e.g. 1h, 24h, 7d)."),
) -> None:
    """View agent and system metrics."""
    settings = get_settings()
    from_date = _window_to_from_date(window)
    summary_params: dict[str, Any] = {**_ns_params(), "group_by": "agent", "from_date": from_date}
    detail_params: dict[str, Any] | None = None
    if agent_name:
        detail_params = {**_ns_params(), "agent_name": agent_name, "from_date": from_date, "limit": 20, "offset": 0}

    try:
        with console.status("[bold cyan]Loading metrics...[/bold cyan]", spinner="dots2"):
            with _api() as client:
                summary_data = client.get("/api/v1/usage/summary", params=summary_params)
                detail_data = client.get("/api/v1/usage/detail", params=detail_params) if detail_params else None
    except ApiError as exc:
        fatal(str(exc))

    items = summary_data if isinstance(summary_data, list) else (summary_data.get("items") or [])
    items = [item for item in items if isinstance(item, dict)]
    if agent_name:
        items = [item for item in items if item.get("group") == agent_name]
    summary = _summarize_usage_items(items)
    detail_items = []
    if isinstance(detail_data, dict):
        detail_items = [item for item in (detail_data.get("items") or []) if isinstance(item, dict)]

    if settings.output_format == "json":
        payload: dict[str, Any] = {"summary": summary, "items": items}
        if detail_items:
            payload["recent"] = detail_items
        print_json_output(payload)
        return

    print_detail(
        summary,
        title="Usage Metrics",
        output_format="table",
        fields=[
            ("Invocations", "invocations"),
            ("Prompt Tokens", "prompt_tokens"),
            ("Completion Tokens", "completion_tokens"),
            ("Total Tokens", "total_tokens"),
            ("Estimated Cost (USD)", "estimated_cost_usd"),
            ("Groups", "groups"),
        ],
    )
    print_table(
        items,
        columns=[
            ("AGENT", "group"),
            ("INVOCATIONS", "invocations"),
            ("TOKENS", "total_tokens"),
            ("COST USD", "estimated_cost_usd"),
        ],
        wide_columns=[
            ("PROMPT", "prompt_tokens"),
            ("COMPLETION", "completion_tokens"),
        ],
        title="Usage Summary",
        output_format=settings.output_format,
    )
    if detail_items:
        print_table(
            detail_items,
            columns=[
                ("TIMESTAMP", "timestamp"),
                ("AGENT", "agent_name"),
                ("MODEL", "model"),
                ("TOKENS", "total_tokens"),
                ("COST USD", "estimated_cost_usd"),
            ],
            wide_columns=[("REQUEST ID", "request_id")],
            title=f"Recent Invocations For {agent_name}",
            output_format=settings.output_format,
        )


# ─── Traces ───


@observatory_app.command("traces")
def observatory_traces(
    agent_name: str | None = typer.Option(None, "--agent", "-a", help="Filter by agent."),
    limit: int = typer.Option(20, "--limit", "-l", min=1, max=200),
    status_filter: str | None = typer.Option(None, "--status", help="Filter by status (completed, failed, etc.)"),
) -> None:
    """List recent execution traces."""
    settings = get_settings()
    params: dict[str, Any] = {**_ns_params(), "limit": limit}
    if agent_name:
        params["agent_name"] = agent_name
    if status_filter:
        params["status"] = status_filter

    try:
        with console.status("[bold cyan]Loading traces...[/bold cyan]", spinner="dots2"):
            with _api() as client:
                data = client.get("/api/v1/traces/executions", params=params)
    except ApiError as exc:
        fatal(str(exc))

    raw_items = data if isinstance(data, list) else (data.get("traces") or data.get("items") or [])
    items = [_normalize_trace_item(item) for item in raw_items if isinstance(item, dict)]
    print_table(
        items,
        columns=[
            ("TRACE ID", "trace_id"),
            ("WORKFLOW", "workflow_name"),
            ("AGENT", "agent_name"),
            ("STATUS", "status"),
            ("DURATION", "duration_ms"),
            ("TIMESTAMP", "timestamp"),
        ],
        wide_columns=[
            ("RUN ID", "run_id"),
            ("TOKENS", "total_tokens"),
            ("TRIGGERED BY", "triggered_by"),
        ],
        title="Execution Traces",
        output_format=settings.output_format,
    )


@observatory_app.command("trace")
def observatory_trace_detail(
    trace_id: str = typer.Argument(..., help="Trace ID to inspect."),
) -> None:
    """Show detailed trace information."""
    settings = get_settings()
    try:
        with console.status(f"[bold cyan]Loading trace {trace_id[:12]}...[/bold cyan]", spinner="dots2"):
            with _api() as client:
                data = client.get(f"/api/v1/traces/executions/{trace_id}")
    except ApiError as exc:
        fatal(str(exc))

    print_detail(
        data,
        title=f"Trace: {trace_id[:12]}...",
        output_format=settings.output_format,
    )


# ─── Alerts ───


@observatory_app.command("alerts")
def observatory_alerts(
    active_only: bool = typer.Option(True, "--active/--all", help="Show only active alerts."),
) -> None:
    """List alerts and anomalies."""
    settings = get_settings()

    try:
        with console.status("[bold cyan]Loading alerts...[/bold cyan]", spinner="dots2"):
            with _api() as client:
                data = client.get("/api/v1/observability/overview", params=_ns_params())
    except ApiError as exc:
        fatal(str(exc))

    raw_items = data if isinstance(data, list) else (data.get("reports") or [])
    items = [_normalize_alert_item(item) for item in raw_items if isinstance(item, dict)]
    if active_only:
        items = [item for item in items if item.get("status") == "active"]
    print_table(
        items,
        columns=[
            ("SEVERITY", "severity"),
            ("TARGET", "target"),
            ("MESSAGE", "message"),
            ("SINCE", "timestamp"),
            ("STATUS", "status"),
        ],
        wide_columns=[
            ("REPORT", "name"),
            ("FINDINGS", "findingsCount"),
            ("HEALTH", "healthScore"),
        ],
        title="Alerts",
        output_format=settings.output_format,
    )


# ─── Signals / Watch ───


@observatory_app.command("signals")
def observatory_signals(
    agent_name: str | None = typer.Option(None, "--agent", "-a"),
    limit: int = typer.Option(20, "--limit", "-l", min=1, max=200),
) -> None:
    """List runtime signal events."""
    settings = get_settings()
    params: dict[str, Any] = {**_ns_params(), "limit": limit}
    if agent_name:
        params["agent_name"] = agent_name

    try:
        with console.status("[bold cyan]Loading signals...[/bold cyan]", spinner="dots2"):
            with _api() as client:
                data = client.get("/api/v1/traces/runtime-events", params=params)
    except ApiError as exc:
        fatal(str(exc))

    raw_items = data if isinstance(data, list) else (data.get("items") or data.get("signals") or [])
    items = [_normalize_signal_item(item) for item in raw_items if isinstance(item, dict)]
    print_table(
        items,
        columns=[
            ("TYPE", "signal_type"),
            ("AGENT", "agent_name"),
            ("SEVERITY", "severity"),
            ("MESSAGE", "message"),
            ("TIMESTAMP", "timestamp"),
        ],
        wide_columns=[
            ("RUNTIME", "runtime_kind"),
            ("EXECUTION", "execution_id"),
        ],
        title="Runtime Signals",
        output_format=settings.output_format,
    )


# ─── Health ───


@observatory_app.command("health")
def observatory_health() -> None:
    """Check overall platform health and component status."""
    settings = get_settings()
    try:
        with console.status("[bold cyan]Checking health...[/bold cyan]", spinner="dots2"):
            with _api() as client:
                data = client.get("/api/health")
    except ApiError as exc:
        fatal(str(exc))

    if settings.output_format == "json":
        print_json_output(data)
        return

    print_detail(
        data,
        title="Platform Health",
        output_format="table",
        fields=[
            ("Status", "status"),
            ("Gateway", "gateway"),
            ("Auth Mode", "auth_mode"),
            ("NATS", "nats_url"),
            ("Qdrant", "qdrant_url"),
        ],
    )


# ─── Export ───


@observatory_app.command("export")
def observatory_export(
    output_path: Path | None = typer.Option(None, "--output", "-o", help="Output file path."),
    fmt: str = typer.Option("json", "--format", "-f", help="Export format: json or csv."),
    since: str = typer.Option("24h", "--since", help="Time range (e.g. 24h, 7d, 2025-01-01)."),
    until: str | None = typer.Option(None, "--until", help="End time."),
    agent_name: str | None = typer.Option(None, "--agent", "-a", help="Filter by agent."),
) -> None:
    """Export traces to a file."""
    params: dict[str, Any] = {"format": fmt, "since": since}
    if until:
        params["until"] = until
    if agent_name:
        params["agent"] = agent_name

    try:
        with console.status(f"[bold cyan]Exporting traces as {fmt}...[/bold cyan]", spinner="dots2"):
            with _api() as client:
                data = client.get("/api/v1/traces/export", params=params)
    except ApiError as exc:
        fatal(str(exc))

    if not output_path:
        ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
        output_path = Path(f"traces-{ts}.{fmt}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    content = data if isinstance(data, str) else __import__("json").dumps(data, indent=2, default=str)
    output_path.write_text(content, encoding="utf-8")

    count = len(data) if isinstance(data, list) else 1
    success(f"Exported [bold]{count}[/bold] trace(s) to [bold]{output_path}[/bold]")
