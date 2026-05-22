"""Observatory commands — metrics, traces, alerts, signals."""

from __future__ import annotations

from datetime import UTC, datetime
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
        "  agentctl observatory metrics --since 2h\n"
        "  agentctl observatory traces my-agent --limit 20\n"
        "  agentctl observatory alerts --status firing\n"
        "  agentctl observatory signals\n"
        "  agentctl observatory export traces.json"
    ),
)


def _api() -> ApiClient:
    return ApiClient(get_settings())


def _ns_params() -> dict[str, Any]:
    return {"namespace": get_settings().namespace}


# ─── Metrics ───


@observatory_app.command("metrics")
def observatory_metrics(
    agent_name: str | None = typer.Option(None, "--agent", "-a", help="Filter by agent."),
    window: str = typer.Option("1h", "--window", "-w", help="Time window (e.g. 1h, 24h, 7d)."),
) -> None:
    """View agent and system metrics."""
    settings = get_settings()
    params: dict[str, Any] = {**_ns_params(), "window": window}
    if agent_name:
        params["agent"] = agent_name

    try:
        with console.status("[bold cyan]Loading metrics...[/bold cyan]"):
            with _api() as client:
                data = client.get("/api/observatory/metrics", params=params)
    except ApiError as exc:
        fatal(str(exc))

    if settings.output_format == "json":
        print_json_output(data)
        return

    if isinstance(data, dict):
        # Summary metrics
        summary = data.get("summary") or data
        fields = [
            ("Total Invocations", "total_invocations"),
            ("Success Rate", "success_rate"),
            ("Avg Latency", "avg_latency_ms"),
            ("P95 Latency", "p95_latency_ms"),
            ("Active Agents", "active_agents"),
            ("Error Count", "error_count"),
        ]
        print_detail(summary, title="Observatory Metrics", output_format="table", fields=fields)

        # Per-agent breakdown
        agents = data.get("agents") or []
        if agents:
            print_table(
                agents,
                columns=[
                    ("AGENT", "name"),
                    ("INVOCATIONS", "invocations"),
                    ("SUCCESS %", "success_rate"),
                    ("AVG MS", "avg_latency_ms"),
                    ("ERRORS", "errors"),
                ],
                title="Per-Agent Metrics",
                output_format=settings.output_format,
            )
    else:
        print_json_output(data)


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
        params["agent"] = agent_name
    if status_filter:
        params["status"] = status_filter

    try:
        with console.status("[bold cyan]Loading traces...[/bold cyan]"):
            with _api() as client:
                data = client.get("/api/observatory/traces", params=params)
    except ApiError as exc:
        fatal(str(exc))

    items = data if isinstance(data, list) else (data.get("traces") or data.get("items") or [])
    print_table(
        items,
        columns=[
            ("TRACE ID", "trace_id"),
            ("AGENT", "agent_name"),
            ("STATUS", "status"),
            ("DURATION", "duration_ms"),
            ("TIMESTAMP", "timestamp"),
        ],
        wide_columns=[
            ("THREAD", "thread_id"),
            ("MODEL", "model"),
            ("TOKENS", "total_tokens"),
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
        with console.status(f"[bold cyan]Loading trace {trace_id[:12]}...[/bold cyan]"):
            with _api() as client:
                data = client.get(f"/api/observatory/traces/{trace_id}")
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
    params: dict[str, Any] = {**_ns_params()}
    if active_only:
        params["active"] = "true"

    try:
        with console.status("[bold cyan]Loading alerts...[/bold cyan]"):
            with _api() as client:
                data = client.get("/api/observatory/alerts", params=params)
    except ApiError as exc:
        fatal(str(exc))

    items = data if isinstance(data, list) else (data.get("alerts") or [])
    print_table(
        items,
        columns=[
            ("SEVERITY", "severity"),
            ("AGENT", "agent_name"),
            ("MESSAGE", "message"),
            ("SINCE", "created_at"),
            ("STATUS", "status"),
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
    """List signal watch events (anomaly detections)."""
    settings = get_settings()
    params: dict[str, Any] = {**_ns_params(), "limit": limit}
    if agent_name:
        params["agent"] = agent_name

    try:
        with console.status("[bold cyan]Loading signals...[/bold cyan]"):
            with _api() as client:
                data = client.get("/api/observatory/signals", params=params)
    except ApiError as exc:
        fatal(str(exc))

    items = data if isinstance(data, list) else (data.get("signals") or [])
    print_table(
        items,
        columns=[
            ("TYPE", "signal_type"),
            ("AGENT", "agent_name"),
            ("SEVERITY", "severity"),
            ("MESSAGE", "message"),
            ("TIMESTAMP", "timestamp"),
        ],
        title="Signal Watch Events",
        output_format=settings.output_format,
    )


# ─── Health ───


@observatory_app.command("health")
def observatory_health() -> None:
    """Check overall platform health and component status."""
    settings = get_settings()
    try:
        with console.status("[bold cyan]Checking health...[/bold cyan]"):
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
        with console.status(f"[bold cyan]Exporting traces as {fmt}...[/bold cyan]"):
            with _api() as client:
                data = client.get("/api/observatory/traces/export", params=params)
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
