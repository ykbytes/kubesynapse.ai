"""GitHub MCP adapter.

This adapter preserves the runtime's existing /tools/<name> bridge while
proxying calls to the upstream GitHub MCP server over streamable HTTP.
"""

from __future__ import annotations

import asyncio
import hmac
import json
import logging
import os
from typing import Any

from fastapi import FastAPI, Header, HTTPException, status
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
import uvicorn

logger = logging.getLogger("mcp-github-adapter")

MCP_BEARER_TOKEN = os.getenv("MCP_BEARER_TOKEN", "").strip()
GITHUB_UPSTREAM_URL = os.getenv("GITHUB_UPSTREAM_URL", "http://127.0.0.1:8082").strip().rstrip("/")
GITHUB_TOKEN_HEADER = os.getenv("GITHUB_TOKEN_HEADER", "X-GitHub-Token").strip() or "X-GitHub-Token"
REQUEST_TIMEOUT_SECONDS = max(float(os.getenv("GITHUB_ADAPTER_TIMEOUT_SECONDS", "30")), 1.0)


def _listen_host_port() -> tuple[str, int]:
    raw_value = os.getenv("MCP_LISTEN_ADDR", "0.0.0.0:8000").strip() or "0.0.0.0:8000"
    if ":" not in raw_value:
        return raw_value, 8000
    host, raw_port = raw_value.rsplit(":", 1)
    try:
        port = int(raw_port)
    except ValueError:
        port = 8000
    return host or "0.0.0.0", port


def _verify_platform_token(authorization: str | None) -> None:
    if not MCP_BEARER_TOKEN:
        return
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing MCP bearer token")
    token = authorization.split(" ", 1)[1].strip()
    if not token or not hmac.compare_digest(token, MCP_BEARER_TOKEN):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid MCP bearer token")


def _serialize_content_item(item: Any) -> dict[str, Any]:
    if hasattr(item, "model_dump"):
        payload = item.model_dump(exclude_none=True)
        if isinstance(payload, dict):
            return payload
    if isinstance(item, dict):
        return item

    payload: dict[str, Any] = {}
    item_type = getattr(item, "type", None)
    if item_type:
        payload["type"] = str(item_type)
    text = getattr(item, "text", None)
    if text is not None:
        payload["text"] = str(text)
    data = getattr(item, "data", None)
    if data is not None:
        payload["data"] = data
    annotations = getattr(item, "annotations", None)
    if annotations is not None:
        payload["annotations"] = annotations
    if payload:
        return payload
    return {"type": item.__class__.__name__.lower(), "value": str(item)}


def _coerce_tool_result(result: Any) -> Any:
    structured = getattr(result, "structuredContent", None)
    if structured is None:
        structured = getattr(result, "structured_content", None)
    if structured is not None:
        return structured

    content = [_serialize_content_item(item) for item in (getattr(result, "content", None) or [])]
    if len(content) == 1 and content[0].get("type") == "text":
        text_value = content[0].get("text")
        if isinstance(text_value, str):
            try:
                return json.loads(text_value)
            except json.JSONDecodeError:
                pass

    if not content:
        return {"content": [], "is_error": bool(getattr(result, "isError", False))}

    return {
        "content": content,
        "is_error": bool(getattr(result, "isError", False)),
    }


async def call_upstream_tool(tool_name: str, tool_args: dict[str, Any], github_token: str) -> Any:
    headers = {"Authorization": f"Bearer {github_token}"}
    async with asyncio.timeout(REQUEST_TIMEOUT_SECONDS):
        async with streamablehttp_client(GITHUB_UPSTREAM_URL, headers=headers) as transport:
            if len(transport) == 2:
                read_stream, write_stream = transport
            elif len(transport) == 3:
                read_stream, write_stream, _ = transport
            else:
                raise RuntimeError(f"Unexpected streamable HTTP transport tuple: {transport!r}")

            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                result = await session.call_tool(tool_name, arguments=tool_args)
                return _coerce_tool_result(result)


app = FastAPI(title="GitHub MCP Adapter", version="1.0.0")


@app.get("/healthz")
async def healthz() -> dict[str, Any]:
    return {
        "status": "ok",
        "upstream_url": GITHUB_UPSTREAM_URL,
    }


@app.post("/tools/{tool_name}")
async def call_tool(
    tool_name: str,
    tool_args: dict[str, Any] | None = None,
    authorization: str | None = Header(default=None, alias="Authorization"),
    github_token: str | None = Header(default=None, alias=GITHUB_TOKEN_HEADER),
) -> Any:
    _verify_platform_token(authorization)
    if not github_token or not github_token.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing forwarded GitHub token",
        )

    try:
        result = await call_upstream_tool(tool_name, tool_args or {}, github_token.strip())
        logger.info("GitHub MCP tool '%s' completed", tool_name)
        return result
    except HTTPException:
        raise
    except Exception as exc:  # pragma: no cover - exercised via route behavior tests
        logger.exception("GitHub MCP tool '%s' failed", tool_name)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"GitHub MCP adapter failed: {exc}",
        ) from exc


if __name__ == "__main__":
    listen_host, listen_port = _listen_host_port()
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO").upper())
    uvicorn.run(app, host=listen_host, port=listen_port)