"""KubeSynth API Gateway — thin application factory.

All route handlers have been extracted to routers/*.py.
All shared models and helpers live in _core.py.

API versioning: all REST endpoints are mounted under /api/v1/.
Legacy /api/* paths return 308 redirects with a Deprecation header.
"""
from __future__ import annotations

# Import shared infrastructure needed by the app factory
from _core import (
    _Instrumentator,
    cors_origins,
    lifespan,
)
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from routers.a2a import router as a2a_router

# Import all routers
from routers.admin import router as admin_router
from routers.agents import router as agents_router
from routers.auth import router as auth_router
from routers.chat import router as chat_router
from routers.evals import router as evals_router
from routers.llm import router as llm_router
from routers.observability import router as observability_router
from routers.webhooks import router as webhooks_router
from routers.workflows import router as workflows_router

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
app.include_router(auth_router, prefix="/api/v1")
app.include_router(agents_router, prefix="/api/v1")
app.include_router(workflows_router, prefix="/api/v1")
app.include_router(evals_router, prefix="/api/v1")
app.include_router(chat_router, prefix="/api/v1")
app.include_router(llm_router, prefix="/api/v1")
app.include_router(observability_router, prefix="/api/v1")
app.include_router(webhooks_router, prefix="/api/v1")
app.include_router(a2a_router)  # A2A uses /a2a prefix (defined in router itself)

# Include traces router (pre-existing modular router)
from traces_router import router as traces_router

app.include_router(traces_router, prefix="/api/v1")

# Re-export app for uvicorn (uvicorn main:app)
__all__ = ["app"]
