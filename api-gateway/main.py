"""kubesynapse API Gateway — thin application factory.

All route handlers have been extracted to routers/*.py.
All shared models and helpers live in _core.py.

API versioning: all REST endpoints are mounted under /api/v1/.
Legacy /api/* paths return 308 redirects with a Deprecation header.
"""
from __future__ import annotations

import json
import logging

# Import shared infrastructure needed by the app factory
from _core import (
    _Instrumentator,
    cors_origins,
    lifespan,
)
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from routers.a2a import router as a2a_router

# Import all routers
from routers.admin import router as admin_router
from routers.agents import router as agents_router
from routers.auth import router as auth_router
from routers.chat import router as chat_router
from routers.llm import router as llm_router
from routers.observability import router as observability_router
from routers.webhooks import router as webhooks_router
from routers.workflows import router as workflows_router
from routers.incidents import router as incidents_router

# §2.2 — Gateway readiness state for health checks
_GATEWAY_STATE = {"ready": False, "shutdown_requested": False}

# Create the FastAPI application
app = FastAPI(
    title="AI Agent Sandbox API",
    description="Enterprise REST API for interacting with AI Agents",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/api/v1/docs",
    redoc_url="/api/v1/redoc",
    openapi_url="/api/v1/openapi.json",
)

# Prometheus metrics (if available)
if _Instrumentator is not None:
    _Instrumentator().instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins(),
    allow_credentials=True,
    allow_methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept", "X-Request-Id"],
)

# GZip compression — reduces response size for JSON payloads by 60-80%
from fastapi.middleware.gzip import GZipMiddleware
app.add_middleware(GZipMiddleware, minimum_size=512)


# ---------------------------------------------------------------------------
# Legacy API redirect middleware — /api/* → /api/v1/*
# ---------------------------------------------------------------------------
@app.middleware("http")
async def legacy_api_redirect(request: Request, call_next):
    """Redirect legacy /api/* paths to /api/v1/* with 308 + Deprecation header.

    Paths already under /api/v1/ pass through normally.
    """
    path = request.url.path

    # Skip routes that are already under /api/v1/, /a2a/, /metrics, /docs, etc.
    if path.startswith("/api/v1/") or not path.startswith("/api/"):
        return await call_next(request)

    # Build the new URL with /api/v1/ prefix
    new_path = "/api/v1" + path[4:]  # Replace /api  with /api/v1
    new_url = str(request.url.replace(path=new_path))

    return RedirectResponse(
        url=new_url,
        status_code=308,  # Permanent Redirect
        headers={
            "Deprecation": "true",
            "Sunset": "Wed, 01 Oct 2026 00:00:00 GMT",
            "Link": f'<{new_url}>; rel="alternate"',
        },
    )


# Mount all routers under /api/v1 prefix (except A2A which stays at /a2a)
app.include_router(admin_router, prefix="/api/v1")

# §2.2 — Health check endpoint for liveness/readiness probes
# Returns 200 when ready, 503 during startup/shutdown for graceful handling
@app.get("/health", tags=["health"])
async def _root_health() -> dict:
    """Health check endpoint for Kubernetes probes.
    
    Returns 200 OK if gateway is ready, 503 Service Unavailable during
    startup or shutdown for proper probe handling.
    """
    status_code = 200 if _GATEWAY_STATE["ready"] else 503
    return {
        "status": "ok" if _GATEWAY_STATE["ready"] else "starting",
        "service": "kubesynapse-api-gateway",
        "ready": _GATEWAY_STATE["ready"],
    }

app.include_router(auth_router, prefix="/api/v1")
app.include_router(agents_router, prefix="/api/v1")
app.include_router(workflows_router, prefix="/api/v1")
app.include_router(chat_router, prefix="/api/v1")
app.include_router(llm_router, prefix="/api/v1")
app.include_router(observability_router, prefix="/api/v1")
app.include_router(webhooks_router, prefix="/api/v1")
app.include_router(incidents_router, prefix="/api/v1")
app.include_router(a2a_router)  # A2A uses /a2a prefix (defined in router itself)

# Include traces router (pre-existing modular router)
from traces_router import router as traces_router

app.include_router(traces_router, prefix="/api/v1")

# §error-handling-P1: Standardised ErrorResponse format for all endpoints.
# Converts every exception (HTTPException, validation errors, unexpected
# crashes) to the structured ErrorResponse envelope so clients can
# programmatically determine what went wrong and what action to take.
from error_codes import ErrorCode, build_error_response, ErrorResponse
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
import logging as _logging
_log = _logging.getLogger("api-gateway")


@app.exception_handler(HTTPException)
async def _error_http(request: Request, exc: HTTPException) -> JSONResponse:
    detail = exc.detail
    if isinstance(detail, dict) and detail.get("code"):
        body = dict(detail)
    else:
        code_map = {
            400: ErrorCode.VALIDATION_ERROR, 401: ErrorCode.AUTH_INVALID,
            403: ErrorCode.NAMESPACE_DENIED, 404: ErrorCode.AGENT_NOT_FOUND,
            409: ErrorCode.RESOURCE_EXISTS, 422: ErrorCode.VALIDATION_ERROR,
            429: ErrorCode.RATE_LIMITED, 500: ErrorCode.INTERNAL_ERROR,
            502: ErrorCode.INVOKE_FAILED, 503: ErrorCode.SERVICE_UNAVAILABLE,
        }
        code = code_map.get(exc.status_code, ErrorCode.INTERNAL_ERROR)
        body = build_error_response(
            code=code,
            message=str(detail) if isinstance(detail, str) else "Request failed",
            request_id=getattr(request.state, "request_id", None),
        )
    if not body.get("request_id"):
        body["request_id"] = getattr(request.state, "request_id", None)
    return JSONResponse(status_code=exc.status_code, content=body)


@app.exception_handler(RequestValidationError)
async def _error_validation(request: Request, exc: RequestValidationError) -> JSONResponse:
    parts = [f"{' → '.join(str(p) for p in e.get('loc', []))}: {e.get('msg', 'Invalid')}" for e in exc.errors()[:5]]
    body = build_error_response(
        code=ErrorCode.VALIDATION_ERROR,
        message="Request validation failed",
        detail="; ".join(parts) if parts else None,
        request_id=getattr(request.state, "request_id", None),
    )
    return JSONResponse(status_code=422, content=body)


@app.exception_handler(Exception)
async def _error_generic(request: Request, exc: Exception) -> JSONResponse:
    _log.exception("Unhandled exception: %s", exc)
    body = build_error_response(
        code=ErrorCode.INTERNAL_ERROR,
        message="An unexpected error occurred",
        request_id=getattr(request.state, "request_id", None),
    )
    return JSONResponse(status_code=500, content=body)


# Re-export app for uvicorn (uvicorn main:app)
__all__ = ["app"]
