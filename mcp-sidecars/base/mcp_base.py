"""Shared MCP sidecar server base.

Every MCP tool sidecar imports this module to get a pre-configured FastMCP
application with bearer-token authentication and a health endpoint.
"""

import os
import hmac
from functools import wraps
from typing import Any

from fastmcp import FastMCP

MCP_BEARER_TOKEN = os.getenv("MCP_BEARER_TOKEN", "").strip()
MCP_SERVER_TYPE = os.getenv("MCP_SERVER_TYPE", "unknown")
MCP_LISTEN_PORT = int(os.getenv("MCP_LISTEN_PORT", "8080"))


def create_mcp_server(name: str, description: str) -> FastMCP:
    """Create a FastMCP server instance with standard configuration."""
    server = FastMCP(
        name=name,
        instructions=description,
    )
    return server


def verify_bearer_token(token: str | None) -> bool:
    """Verify that the provided bearer token matches the expected one."""
    if not MCP_BEARER_TOKEN:
        return True  # No auth configured
    if not token:
        return False
    return hmac.compare_digest(token, MCP_BEARER_TOKEN)


def run_server(server: FastMCP) -> None:
    """Run the MCP server with streamable HTTP transport."""
    server.run(
        transport="streamable-http",
        host="0.0.0.0",
        port=MCP_LISTEN_PORT,
    )
