"""Rich output formatters - table, json, yaml, wide, name modes."""

from __future__ import annotations

import json
import locale
import os
import sys
from typing import Any

import yaml
from rich import box
from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.style import Style
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
        "accent": "bright_cyan",
        "muted": "grey58",
        "debug": "dim cyan",
        "critical": "bold white on red",
    }
)

console = Console(theme=THEME)
err_console = Console(stderr=True, theme=THEME)

_UNICODE_SENTINEL = "│└✖…"

_STATUS_MAP = {
    "running": "ready",
    "active": "ready",
    "healthy": "ready",
    "succeeded": "ready",
    "completed": "ready",
    "pending": "pending",
    "waiting": "pending",
    "unknown": "pending",
    "initializing": "pending",
    "failed": "failed",
    "error": "failed",
    "degraded": "failed",
    "crash": "failed",
}

_LOG_STYLES = {
    "error": "bold red",
    "warning": "bold yellow",
    "warn": "bold yellow",
    "info": "bright_cyan",
    "debug": "dim cyan",
    "critical": "bold white on red",
    "trace": "dim grey58",
}

_ALT_ROW = Style(color="grey58")


def status_style(status: str) -> str:
    return _STATUS_MAP.get(status.lower(), "dim")


def status_badge(status: str) -> Text:
    """Render status as a compact colored badge."""
    base = status_style(status)
    return Text(f" {status.upper()} ", style=f"bold {base} on {base.replace('bold ', '')}")


def log_level_style(level: str) -> str:
    return _LOG_STYLES.get(level.lower(), "dim")


def truncate(text: str, max_len: int = 50) -> str:
    if len(text) <= max_len:
        return text
    return text[: max_len - 1] + "\u2026"


def terminal_encoding(stream: Any | None = None) -> str:
    """Return the active terminal encoding or a sensible UTF-8 fallback."""

    active_stream = stream or console.file or sys.stdout
    return getattr(active_stream, "encoding", None) or locale.getpreferredencoding(False) or "utf-8"


def safe_text(value: Any, stream: Any | None = None, *, errors: str = "backslashreplace") -> str:
    """Return text that can be written safely to the active terminal encoding."""

    text = str(value)
    encoding = terminal_encoding(stream)
    try:
        text.encode(encoding)
    except Exception:
        return text.encode(encoding, errors=errors).decode(encoding)
    return text


def supports_unicode_output(stream: Any | None = None) -> bool:
    """Return True when the active terminal encoding can safely print common UI glyphs."""

    encoding = terminal_encoding(stream)
    if os.environ.get("PYTHONIOENCODING", "").lower().startswith("utf-8"):
        return True
    try:
        _UNICODE_SENTINEL.encode(encoding)
    except Exception:
        return False
    return True


def preferred_box(*, heavy: bool = False, simple: bool = False) -> box.Box:
    """Choose a Rich box style that is safe for the active terminal encoding."""

    if supports_unicode_output():
        if heavy:
            return box.SIMPLE_HEAVY
        if simple:
            return box.SIMPLE
        return box.ROUNDED
    return box.ASCII


def inline_separator() -> str:
    return "│" if supports_unicode_output() else "|"


def prompt_prefix(kind: str) -> str:
    return f"│ {kind}>" if supports_unicode_output() else f"| {kind}>"


def stop_marker() -> str:
    return "└" if supports_unicode_output() else "`"


def error_marker() -> str:
    return "✖" if supports_unicode_output() else "x"


def print_stream_text(message: Any, *, end: str = "\n", style: str | Style | None = None) -> None:
    """Print raw streamed text without Rich markup and without encoding failures."""

    console.print(safe_text(message), end=end, markup=False, highlight=False, soft_wrap=True, style=style)


# ─── Core output functions ───


def print_json_output(data: Any) -> None:
    output = json.dumps(data, indent=2, default=str)
    console.print(Syntax(safe_text(output), "json", theme="monokai", word_wrap=True))


def print_yaml_output(data: Any) -> None:
    output = yaml.dump(data, default_flow_style=False, allow_unicode=True)
    console.print(Syntax(safe_text(output), "yaml", theme="monokai", word_wrap=True))


def print_name_output(items: list[dict[str, Any]], name_key: str = "name") -> None:
    for item in items:
        name = item.get(name_key) or item.get("id") or "unknown"
        console.print(Text(safe_text(name)))


def print_table(
    items: list[dict[str, Any]],
    columns: list[tuple[str, str]],
    *,
    title: str | None = None,
    wide_columns: list[tuple[str, str]] | None = None,
    output_format: str = "table",
) -> None:
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

    cols = list(columns)
    if output_format == "wide" and wide_columns:
        cols.extend(wide_columns)

    table = Table(
        title=title,
        show_lines=False,
        expand=False,
        border_style="bright_black",
        box=preferred_box(),
        header_style="bold bright_cyan",
        row_styles=["", _ALT_ROW],
    )
    for header, _ in cols:
        table.add_column(header, style="bold")

    for item in items:
        row: list[str | Text] = []
        for _, key in cols:
            val = item.get(key)
            if val is None:
                row.append(Text("-", style="dim"))
            elif key in ("status", "state", "phase"):
                style = status_style(str(val))
                row.append(Text(safe_text(str(val)).ljust(10), style=style))
            else:
                row.append(Text(safe_text(val)))
        table.add_row(*row)

    console.print(table)


def print_detail(
    data: dict[str, Any],
    *,
    title: str | None = None,
    output_format: str = "table",
    fields: list[tuple[str, str]] | None = None,
) -> None:
    if output_format == "json":
        print_json_output(data)
        return
    if output_format == "yaml":
        print_yaml_output(data)
        return
    if output_format == "name":
        console.print(Text(safe_text(data.get("name") or data.get("id") or "unknown")))
        return

    lines: list[str] = []
    pairs = fields if fields else [(k.replace("_", " ").title(), k) for k in data]
    for label, key in pairs:
        val = data.get(key, "-")
        if isinstance(val, (dict, list)):
            val = json.dumps(val, indent=2, default=str)
        if key in ("status", "state", "phase"):
            rendered = safe_text(str(val)).ljust(10)
            lines.append(f"[key]{label}:[/key] [bold {status_style(str(val))}]{rendered}[/]")
        else:
            lines.append(f"[key]{label}:[/key] {escape(safe_text(val))}")

    content = "\n".join(lines)
    if title:
        console.print(
            Panel(
                content,
                title=f"[header]{title}[/header]",
                border_style="bright_cyan",
                box=preferred_box(),
                expand=False,
            )
        )
    else:
        console.print(content)


# ─── Message helpers ───


def success(message: str) -> None:
    """Print a success message."""
    console.print(f"[bold green]OK[/bold green] {safe_text(message)}")


def info(message: str) -> None:
    """Print an info message."""
    console.print(f"[bright_cyan]>>[/bright_cyan] {safe_text(message)}")


def warning(message: str) -> None:
    """Print a warning message to stderr."""
    err_console.print(f"[bold yellow]!![/bold yellow] {safe_text(message, err_console.file)}")


def error(message: str) -> None:
    """Print an error message to stderr."""
    err_console.print(f"[bold red]Error:[/bold red] {safe_text(message, err_console.file)}")


def fatal(message: str, exit_code: int = 1) -> None:
    """Print error and exit."""
    error(message)
    raise SystemExit(exit_code)


def print_log_line(level: str, message: str, timestamp: str = "") -> None:
    """Format a single log line with level-based coloring."""
    ts = f"[dim]{timestamp}[/dim] " if timestamp else ""
    tag = f"[{log_level_style(level)}]{level.upper():<8}[/]"
    msg_style = log_level_style(level)
    console.print(f"{ts}{tag} [{msg_style}]{escape(safe_text(message))}[/]")
