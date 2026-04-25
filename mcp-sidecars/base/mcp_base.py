"""Shared MCP sidecar server base.

Every MCP tool sidecar imports this module to get a pre-configured FastMCP
application with bearer-token authentication, capability enforcement,
request/response logging, health endpoints, and egress filtering.
"""

from __future__ import annotations

import functools
import hmac
import ipaddress
import json
import logging
import os
import socket
import threading
import time
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any
from urllib.parse import urlparse

from fastmcp import FastMCP

log = logging.getLogger("mcp-base")

MCP_BEARER_TOKEN = os.getenv("MCP_BEARER_TOKEN", "").strip()
MCP_SERVER_TYPE = os.getenv("MCP_SERVER_TYPE", "unknown")
MCP_LISTEN_PORT = int(os.getenv("MCP_LISTEN_PORT", "8080"))
MCP_HEALTH_PORT = int(os.getenv("MCP_HEALTH_PORT", "8090"))
MCP_CAPABILITY_MANIFEST_PATH = os.getenv("MCP_CAPABILITY_MANIFEST_PATH", "/app/capabilities.json")

# ---------------------------------------------------------------------------
# Capability manifest loading
# ---------------------------------------------------------------------------

_CAPABILITIES: dict[str, Any] = {}


def _load_capabilities() -> dict[str, Any]:
    """Load capability manifest from disk."""
    global _CAPABILITIES
    if _CAPABILITIES:
        return _CAPABILITIES
    if os.path.exists(MCP_CAPABILITY_MANIFEST_PATH):
        try:
            with open(MCP_CAPABILITY_MANIFEST_PATH, encoding="utf-8") as f:
                _CAPABILITIES = json.load(f)
        except Exception as exc:
            log.warning("Failed to load capabilities from %s: %s", MCP_CAPABILITY_MANIFEST_PATH, exc)
            _CAPABILITIES = {}
    else:
        log.info("No capability manifest found at %s", MCP_CAPABILITY_MANIFEST_PATH)
        _CAPABILITIES = {}
    return _CAPABILITIES


def get_capabilities() -> dict[str, Any]:
    """Return the loaded capability manifest."""
    return _CAPABILITIES if _CAPABILITIES else _load_capabilities()


def allowed_tools() -> frozenset[str]:
    """Return the set of allowed tool names from the manifest."""
    caps = get_capabilities()
    tools = caps.get("allowedTools") or caps.get("tools")
    if isinstance(tools, list):
        return frozenset(str(t).strip() for t in tools if str(t).strip())
    return frozenset()


# ---------------------------------------------------------------------------
# Egress filtering helpers
# ---------------------------------------------------------------------------

def _parse_egress_allowlists() -> tuple[frozenset[str], frozenset[str]]:
    """Parse domain and CIDR allowlists from capabilities or env vars."""
    caps = get_capabilities()
    network = caps.get("networkEgress") or {}
    domains = set()
    cidrs = set()

    # From manifest
    raw_domains = network.get("domains") or []
    if isinstance(raw_domains, list):
        domains.update(str(d).strip().lower() for d in raw_domains if str(d).strip())
    raw_cidrs = network.get("ips") or []
    if isinstance(raw_cidrs, list):
        cidrs.update(str(c).strip() for c in raw_cidrs if str(c).strip())

    # From env (allows runtime override without rebuilding image)
    env_domains = os.getenv("MCP_EGRESS_DOMAINS", "").strip()
    if env_domains:
        domains.update(d.strip().lower() for d in env_domains.split(",") if d.strip())
    env_cidrs = os.getenv("MCP_EGRESS_CIDRS", "").strip()
    if env_cidrs:
        cidrs.update(c.strip() for c in env_cidrs.split(",") if c.strip())

    return frozenset(domains), frozenset(cidrs)


def check_egress_url(url: str) -> str | None:
    """Return an error message if *url* violates egress policy, else None."""
    try:
        parsed = urlparse(url)
    except Exception:
        return "Invalid URL"

    scheme = (parsed.scheme or "").lower()
    if scheme not in ("http", "https"):
        return f"Scheme '{scheme}' is not allowed"

    hostname = (parsed.hostname or "").lower()
    if not hostname:
        return "URL has no hostname"

    allowed_domains, allowed_cidrs = _parse_egress_allowlists()

    # If no allowlists configured, permit all (backward compatible)
    if not allowed_domains and not allowed_cidrs:
        return None

    # Domain allowlist check
    if allowed_domains:
        if "*" in allowed_domains:
            return None
        matched = False
        for domain in allowed_domains:
            if domain.startswith("*."):
                suffix = domain[1:]  # e.g. *.github.com -> .github.com
                if hostname.endswith(suffix):
                    matched = True
                    break
            elif hostname == domain or hostname.endswith(f".{domain}"):
                matched = True
                break
        if not matched:
            return f"Hostname '{hostname}' is not in the egress domain allowlist"

    # CIDR allowlist check (resolve hostname and verify IP)
    if allowed_cidrs:
        try:
            addr_infos = socket.getaddrinfo(hostname, parsed.port or 443, proto=socket.IPPROTO_TCP)
        except socket.gaierror:
            return f"Could not resolve hostname '{hostname}'"

        networks = []
        for cidr in allowed_cidrs:
            try:
                networks.append(ipaddress.ip_network(cidr, strict=False))
            except ValueError:
                log.warning("Invalid CIDR in egress allowlist: %s", cidr)

        for _family, _, _, _, sockaddr in addr_infos:
            ip = ipaddress.ip_address(sockaddr[0])
            if any(ip in net for net in networks):
                return None
        return "URL resolves to an IP not in the egress CIDR allowlist"

    return None


# ---------------------------------------------------------------------------
# Bearer token verification
# ---------------------------------------------------------------------------

def verify_bearer_token(token: str | None) -> bool:
    """Verify that the provided bearer token matches the expected one."""
    if not MCP_BEARER_TOKEN:
        log.warning("MCP_BEARER_TOKEN not configured — denying request (fail-secure)")
        return False  # Fail-secure: deny when no token is configured
    if not token:
        return False
    return hmac.compare_digest(token, MCP_BEARER_TOKEN)


# ---------------------------------------------------------------------------
# Request / response logging
# ---------------------------------------------------------------------------

def _sanitize_payload(payload: Any) -> Any:
    """Remove likely secrets from logged payloads."""
    if isinstance(payload, dict):
        sanitized: dict[str, Any] = {}
        for key, value in payload.items():
            lower_key = str(key).lower()
            if any(s in lower_key for s in ("token", "secret", "password", "key", "credential", "auth")):
                sanitized[key] = "[REDACTED]"
            else:
                sanitized[key] = _sanitize_payload(value)
        return sanitized
    if isinstance(payload, list):
        return [_sanitize_payload(item) for item in payload]
    return payload


def _log_tool_call(tool_name: str, args: Any, result: Any, duration_ms: float) -> None:
    """Emit a structured log line for a tool invocation."""
    log.info(
        "mcp_tool_call server=%s tool=%s duration_ms=%.2f args=%s result_preview=%s",
        MCP_SERVER_TYPE,
        tool_name,
        duration_ms,
        json.dumps(_sanitize_payload(args)),
        json.dumps(str(result)[:200]),
    )


# ---------------------------------------------------------------------------
# Capability-aware tool decorator wrapper
# ---------------------------------------------------------------------------

def _wrap_tool_decorator(server: FastMCP) -> None:
    """Monkey-patch server.tool() to enforce capabilities and logging."""
    original_tool = server.tool

    def _patched_tool(*tool_args: Any, **tool_kwargs: Any) -> Callable[..., Any]:
        def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
            tool_name = tool_kwargs.get("name") or getattr(func, "__name__", "<anonymous>")
            allowed = allowed_tools()

            @functools.wraps(func)
            def wrapper(*args: Any, **kwargs: Any) -> Any:
                if allowed and tool_name not in allowed:
                    log.warning("Tool '%s' blocked by capability manifest", tool_name)
                    return f"BLOCKED: Tool '{tool_name}' is not in the capability allowlist"
                start = time.perf_counter()
                try:
                    result = func(*args, **kwargs)
                except Exception as exc:
                    duration_ms = (time.perf_counter() - start) * 1000
                    _log_tool_call(tool_name, kwargs if kwargs else args, f"ERROR: {exc}", duration_ms)
                    raise
                duration_ms = (time.perf_counter() - start) * 1000
                _log_tool_call(tool_name, kwargs if kwargs else args, result, duration_ms)
                return result

            return original_tool(*tool_args, **tool_kwargs)(wrapper)

        return decorator

    server.tool = _patched_tool


# ---------------------------------------------------------------------------
# Health endpoint server
# ---------------------------------------------------------------------------

class _HealthHandler(BaseHTTPRequestHandler):
    """Minimal HTTP handler for /healthz and /readyz."""

    def log_message(self, format: str, *args: Any) -> None:
        log.debug("Health server: %s", format % args)

    def do_GET(self) -> None:
        if self.path in ("/healthz", "/readyz"):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            payload = json.dumps({"status": "ok", "server": MCP_SERVER_TYPE})
            self.wfile.write(payload.encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()


def _start_health_server() -> None:
    """Start a background thread serving health checks."""
    def serve() -> None:
        try:
            server = HTTPServer(("0.0.0.0", MCP_HEALTH_PORT), _HealthHandler)
            log.info("Health server listening on port %d", MCP_HEALTH_PORT)
            server.serve_forever()
        except Exception as exc:
            log.warning("Health server failed to start: %s", exc)

    thread = threading.Thread(target=serve, daemon=True, name="mcp-health-server")
    thread.start()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def create_mcp_server(name: str, description: str) -> FastMCP:
    """Create a FastMCP server instance with standard configuration."""
    server = FastMCP(
        name=name,
        instructions=description,
    )
    _load_capabilities()
    _wrap_tool_decorator(server)
    return server


def run_server(server: FastMCP) -> None:
    """Run the MCP server with streamable HTTP transport and health checks."""
    _start_health_server()
    server.run(
        transport="streamable-http",
        host="0.0.0.0",
        port=MCP_LISTEN_PORT,
    )
