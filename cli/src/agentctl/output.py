"""Rich output formatters — table, json, yaml, wide, name modes."""

from __future__ import annotations

import json
import sys
from typing import Any

import yaml
from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text
from rich.theme import Theme

THEME = Theme(
    {
        "info": "cyan",
        "success": "bold green",
        "warning": "bold yellow",
        "error": "bold red",
        "key": "bold magenta",
        "dim": "dim white",
        "header": "bold bright_cyan",
        "running": "bold blue",
        "ready": "bold green",
        "pending": "bold yellow",
        "failed": "bold red",
    }
)

console = Console(theme=THEME)
err_console = Console(stderr=True, theme=THEME)


# ─── Helpers ───


def status_style(status: str) -> str:
    """Return a Rich style based on resource status."""
    s = status.lower()
    if s in ("running", "active", "healthy", "succeeded", "completed"):
        return "ready"
    if s in ("pending", "waiting", "unknown", "initializing"):
        return "pending"
    if s in ("failed", "error", "degraded", "crash"):
        return "failed"
    return "dim"


def truncate(text: str, max_len: int = 50) -> str:
    """Truncate text with ellipsis."""
    if len(text) <= max_len:
        return text
    return text[: max_len - 1] + "\u2026"


# ─── Core output functions ───


def print_json_output(data: Any) -> None:
    """Print as indented JSON."""
    output = json.dumps(data, indent=2, default=str)
    console.print(Syntax(output, "json", theme="monokai", word_wrap=True))


def print_yaml_output(data: Any) -> None:
    """Print as YAML."""
    output = yaml.dump(data, default_flow_style=False, allow_unicode=True)
    console.print(Syntax(output, "yaml", theme="monokai", word_wrap=True))


def print_name_output(items: list[dict[str, Any]], name_key: str = "name") -> None:
    """Print just the names, one per line."""
    for item in items:
        name = item.get(name_key) or item.get("id") or "unknown"
        console.print(name)


def print_table(
    items: list[dict[str, Any]],
    columns: list[tuple[str, str]],
    *,
    title: str | None = None,
    wide_columns: list[tuple[str, str]] | None = None,
    output_format: str = "table",
) -> None:
    """
    Unified output for lists.

    columns: list of (header_label, dict_key) — shown in table mode.
    wide_columns: additional columns shown in 'wide' mode.
    """
    if not items:
        console.print("[dim]No items found.[/dim]")
        return

    if output_format == "json":
        print_json_output(items)
        return
    if output_format == "yaml":
        print_yaml_output(items)
        return
    if output_format == "name":
        name_key = columns[0][1] if columns else "name"
        print_name_output(items, name_key)
        return

    # Table or wide mode
    cols = list(columns)
    if output_format == "wide" and wide_columns:
        cols.extend(wide_columns)

    table = Table(title=title, show_lines=False, expand=False, border_style="bright_black")
    for header, _ in cols:
        table.add_column(header, style="bold")

    for item in items:
        row: list[str | Text] = []
        for _, key in cols:
            val = item.get(key)
            if val is None:
                row.append(Text("-", style="dim"))
            elif key == "status" or key == "state" or key == "phase":
                style = status_style(str(val))
                row.append(Text(str(val), style=style))
            else:
                row.append(str(val))
        table.add_row(*row)

    console.print(table)


def print_detail(
    data: dict[str, Any],
    *,
    title: str | None = None,
    output_format: str = "table",
    fields: list[tuple[str, str]] | None = None,
) -> None:
    """
    Display a single resource detail.

    fields: list of (label, dict_key). If None, prints all keys.
    """
    if output_format == "json":
        print_json_output(data)
        return
    if output_format == "yaml":
        print_yaml_output(data)
        return
    if output_format == "name":
        console.print(data.get("name") or data.get("id") or "unknown")
        return

    # Render as key-value panel
    lines: list[str] = []
    pairs = fields if fields else [(k.replace("_", " ").title(), k) for k in data]
    for label, key in pairs:
        val = data.get(key, "-")
        if isinstance(val, (dict, list)):
            val = json.dumps(val, indent=2, default=str)
        lines.append(f"[key]{label}:[/key] {escape(str(val))}")

    content = "\n".join(lines)
    if title:
        console.print(Panel(content, title=f"[header]{title}[/header]", border_style="bright_cyan", expand=False))
    else:
        console.print(content)


# ─── Message helpers ───


def success(message: str) -> None:
    """Print a success message."""
    console.print(f"[success]OK[/success] {message}")


def info(message: str) -> None:
    """Print an info message."""
    console.print(f"[info]>>[/info] {message}")


def warning(message: str) -> None:
    """Print a warning message."""
    err_console.print(f"[warning]!![/warning] {message}")


def error(message: str) -> None:
    """Print an error message to stderr."""
    err_console.print(f"[error]Error:[/error] {message}")


def fatal(message: str, exit_code: int = 1) -> None:
    """Print error and exit."""
    error(message)
    raise SystemExit(exit_code)
