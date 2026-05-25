"""Auto-generated router — extracted from api-gateway main.py."""
from __future__ import annotations

from typing import Any

# Re-import all shared symbols from the gateway core
from _core import *
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import JSONResponse

router = APIRouter(tags=["a2a"])

@router.get("/.well-known/agent-card.json")
async def get_well_known_agent_card(
    request: Request,
    assistant_id: str,
    namespace: str | None = None,
    authorization: str | None = Header(default=None),
):
    if authorization is not None and authorization.strip():
        await verify_token(authorization)

    try:
        agent_name, resolved_namespace = resolve_a2a_agent_reference(assistant_id, namespace)
    except A2AJSONRPCError as exc:
        raise a2a_card_http_exception(exc) from exc

    return JSONResponse(build_agent_card(agent_name, resolved_namespace, request))


@router.post("/a2a/{assistant_id}")
async def a2a_jsonrpc(
    assistant_id: str,
    raw_request: Request,
    namespace: str | None = None,
    user=Depends(verify_token),
):
    request_id: Any = None
    try:
        validate_a2a_version(raw_request)
        try:
            payload = await raw_request.json()
        except json.JSONDecodeError:
            return JSONResponse(
                jsonrpc_error_response(request_id, JSONRPC_PARSE_ERROR, "Invalid JSON payload"),
                status_code=200,
            )

        request_id, method, params = parse_jsonrpc_payload(payload)
        agent_name, resolved_namespace = resolve_a2a_agent_reference(assistant_id, namespace)
        ensure_namespace_access(user, resolved_namespace, "operator")  # P1-7: A2A send is a mutating operation
        gateway_request_id = raw_request.headers.get("x-request-id") or str(uuid.uuid4())

        if method == "message/send":
            return JSONResponse(
                await handle_a2a_send_message(
                    agent_name,
                    resolved_namespace,
                    params,
                    request_id,
                    gateway_request_id,
                ),
                status_code=200,
            )

        if method == "message/stream":
            return await handle_a2a_stream_message(
                agent_name,
                resolved_namespace,
                params,
                request_id,
                gateway_request_id,
            )

        if method == "tasks/get":
            return JSONResponse(
                handle_a2a_get_task(agent_name, resolved_namespace, params, request_id),
                status_code=200,
            )

        return JSONResponse(
            jsonrpc_error_response(
                request_id,
                JSONRPC_METHOD_NOT_FOUND,
                "Method not found",
                {"method": method},
            ),
            status_code=200,
        )
    except A2AJSONRPCError as exc:
        return JSONResponse(
            jsonrpc_error_response(request_id, exc.code, exc.message, exc.data),
            status_code=200,
        )
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
        error_code = JSONRPC_INVALID_PARAMS if exc.status_code == 404 else JSONRPC_INTERNAL_ERROR
        return JSONResponse(jsonrpc_error_response(request_id, error_code, detail), status_code=200)
    except Exception as exc:
        logger.exception("Unhandled A2A JSON-RPC error")
        return JSONResponse(
            jsonrpc_error_response(
                request_id,
                JSONRPC_INTERNAL_ERROR,
                "Internal error",
                {"detail": str(exc)},
            ),
            status_code=200,
        )
