#!/usr/bin/env python3
"""Split api-gateway/main.py into:
- _core.py: all non-route code (models, helpers, constants, lifespan, app factory)
- routers/*.py: one file per route group with APIRouter
- main.py: thin wrapper that imports _core and mounts routers

Strategy:
1. Identify all route handler blocks in main.py
2. Extract route handler code into router files (replacing @app. → @router.)
3. Everything NOT in a route handler goes into _core.py
4. Create thin main.py
"""

import re
from pathlib import Path

WORKSPACE = Path(r"C:\Users\ahmed\OneDrive\Desktop\repos\kubesynapse\kubemininions")
MAIN_PY = WORKSPACE / "api-gateway" / "main.py"
ROUTERS_DIR = WORKSPACE / "api-gateway" / "routers"
CORE_PY = WORKSPACE / "api-gateway" / "_core.py"
NEW_MAIN_PY = WORKSPACE / "api-gateway" / "main_new.py"

PREFIX_MAP = [
    ("/api/auth/", "auth.py", "auth"),
    ("/api/admin/", "admin.py", "admin"),
    ("/api/usage/", "admin.py", "admin"),
    ("/api/agents/", "agents.py", "agents"),
    ("/api/namespaces", "agents.py", "agents"),
    ("/api/workflows/", "workflows.py", "workflows"),
    ("/api/evals/", "evals.py", "evals"),
    ("/a2a/", "a2a.py", "a2a"),
    ("/.well-known/agent-card.json", "a2a.py", "a2a"),
    ("/api/chat-sessions", "chat.py", "chat"),
    ("/api/memory/", "chat.py", "chat"),
    ("/api/memory\"", "chat.py", "chat"),
    ("/api/notifications/", "chat.py", "chat"),
    ("/api/providers", "llm.py", "llm"),
    ("/api/llm/", "llm.py", "llm"),
    ("/api/copilot/", "llm.py", "llm"),
    ("/api/observability/", "observability.py", "observability"),
    ("/api/skills/", "observability.py", "observability"),
    ("/api/mcp/", "observability.py", "observability"),
    ("/api/mcp-hub/", "observability.py", "observability"),
    ("/api/system/", "admin.py", "admin"),
    ("/api/health", "admin.py", "admin"),
    ("/api/ready", "admin.py", "admin"),
    ("/api/policies", "admin.py", "admin"),
    ("/api/approvals/", "admin.py", "admin"),
    ("/api/export/", "admin.py", "admin"),
    ("/api/import/", "admin.py", "admin"),
    ("/api/intelligence/", "admin.py", "admin"),
]

def classify_url(url: str) -> str:
    """Return the target router filename for a URL."""
    for prefix, filename, tag in PREFIX_MAP:
        if url.startswith(prefix) or (prefix.endswith('"') and prefix[:-1] in url):
            return filename
    print(f"WARNING: Unmatched URL: {url}")
    return "admin.py"

content = MAIN_PY.read_text(encoding="utf-8")
lines = content.split("\n")
total = len(lines)

# Step 1: Find all route blocks
route_pattern = re.compile(r'^\s*@app\.(get|post|put|patch|delete|options)\s*\(')
route_starts = []  # 0-indexed line numbers where routes start

for i, line in enumerate(lines):
    if route_pattern.match(line):
        route_starts.append(i)

print(f"Found {len(route_starts)} route decorators")

# Step 2: For each route block, find the end
# A route block = decorator line + all subsequent lines until the next decorator
# But we want to trim trailing blank lines between routes
route_blocks = []  # list of (start_0idx, end_0idx_exclusive)

for idx, start in enumerate(route_starts):
    if idx + 1 < len(route_starts):
        end = route_starts[idx + 1]  # next decorator starts here
    else:
        end = total  # end of file
    
    # Trim trailing blank lines from the route block
    while end > start and lines[end - 1].strip() == "":
        end -= 1
    
    route_blocks.append((start, end))

# Step 3: Mark which lines belong to route blocks
route_lines = set()
for start, end in route_blocks:
    for i in range(start, end):
        route_lines.add(i)

# Step 4: Build _core.py (all non-route lines)
core_lines = []
for i in range(total):
    if i not in route_lines:
        core_lines.append(lines[i])
    else:
        # Replace the line with nothing — route-specific code goes to router files
        pass

# Also, modify _core.py: create router objects for each file that were @app
# Actually, _core.py shouldn't have any @app references since those are all in route blocks
# But there might be @app references in non-route code (unlikely but check)
core_text = "\n".join(core_lines)
core_text = core_text.strip() + "\n"

# Remove the if __name__ block from _core.py if present
core_text = re.sub(r'\nif __name__\s*==\s*["\']__main__["\'].*', '', core_text, flags=re.DOTALL)

CORE_PY.write_text(core_text, encoding="utf-8")
print(f"Wrote _core.py: {len(core_lines)} lines ({len(core_text)} chars)")

# Step 5: Build router files
ROUTER_HEADER = '''"""Auto-generated router — extracted from api-gateway main.py."""
from __future__ import annotations

from typing import Any, cast
from fastapi import APIRouter, Body, Cookie, Depends, Header, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse, RedirectResponse, StreamingResponse

# Re-import all shared symbols from the gateway core
from _core import *  # noqa: F403

'''

# Group route blocks by file
file_blocks = {}
for start, end in route_blocks:
    # Get the URL from the first line
    first_line = lines[start]
    url_match = re.search(r'\(\s*["\']([^"\']+)["\']', first_line)
    if not url_match:
        continue
    url = url_match.group(1)
    filename = classify_url(url)
    
    if filename not in file_blocks:
        file_blocks[filename] = []
    file_blocks[filename].append((start, end, url))

for filename in sorted(file_blocks.keys()):
    blocks = sorted(file_blocks[filename], key=lambda b: b[0])
    
    # Find the tag
    tag = "misc"
    for prefix, fname, ftag in PREFIX_MAP:
        if fname == filename:
            tag = ftag
            break
    
    header = ROUTER_HEADER + f'router = APIRouter(tags=["{tag}"])\n\n'
    
    code_parts = []
    for start, end, url in blocks:
        block_lines = []
        for i in range(start, end):
            line = lines[i]
            # Replace @app.X with @router.X
            if route_pattern.match(line):
                line = line.replace("@app.", "@router.", 1)
            block_lines.append(line)
        
        # Trim trailing blank lines
        while block_lines and block_lines[-1].strip() == "":
            block_lines.pop()
        
        if block_lines:
            code_parts.append("\n".join(block_lines))
    
    if not code_parts:
        print(f"WARNING: No code for {filename}")
        continue
    
    router_code = header + "\n\n\n".join(code_parts) + "\n"
    output_path = ROUTERS_DIR / filename
    output_path.write_text(router_code, encoding="utf-8")
    print(f"Wrote {filename}: {len(blocks)} routes, {len(router_code)} chars")

# Step 6: Build new main.py
NEW_MAIN = '''"""kubesynapse API Gateway — thin application factory.

All route handlers have been extracted to routers/*.py.
All shared models and helpers live in _core.py.
"""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Import all shared infrastructure
from _core import (  # noqa: F401  — side-effects: logger, SHUTDOWN, _Instrumentator
    A2A_TASK_RETENTION_SECONDS,
    _Instrumentator,
    _configure_logging,
    cors_origins,
    lifespan,
    logger,
    purge_expired_a2a_tasks,
    _clean_expired_mcp_oauth_flows,
    _intelligence_scheduler_loop,
)

# Import all routers
from routers.agents import router as agents_router
from routers.workflows import router as workflows_router
from routers.evals import router as evals_router
from routers.auth import router as auth_router
from routers.a2a import router as a2a_router
from routers.chat import router as chat_router
from routers.llm import router as llm_router
from routers.observability import router as observability_router
from routers.admin import router as admin_router

# Create the FastAPI application
app = FastAPI(
    title="AI Agent Sandbox API",
    description="Enterprise REST API for interacting with AI Agents",
    version="1.0.0",
    lifespan=lifespan,
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

# Mount all routers — order matters for route resolution
app.include_router(admin_router)           # /api/health, /api/ready, /api/admin, /api/system, etc.
app.include_router(auth_router)            # /api/auth/*
app.include_router(agents_router)          # /api/agents/*, /api/namespaces
app.include_router(workflows_router)       # /api/workflows/*
app.include_router(evals_router)           # /api/evals/*
app.include_router(chat_router)            # /api/chat-sessions/*, /api/memory/*, /api/notifications/*
app.include_router(llm_router)             # /api/providers/*, /api/llm/*, /api/copilot/*
app.include_router(observability_router)   # /api/skills/*, /api/mcp/*, /api/observability/*
app.include_router(a2a_router)             # /a2a/*, /.well-known/agent-card.json

# Include traces router (pre-existing modular router)
from traces_router import router as traces_router
app.include_router(traces_router)

# Re-export app for uvicorn (uvicorn main:app)
__all__ = ["app"]
'''
NEW_MAIN_PY.write_text(NEW_MAIN, encoding="utf-8")
print(f"Wrote main_new.py: {len(NEW_MAIN)} chars")

print("\n=== SUMMARY ===")
print(f"_core.py: {len(core_text.split(chr(10)))} lines (all non-route code)")
print(f"main_new.py: {len(NEW_MAIN.split(chr(10)))} lines (thin factory)")
for f in sorted(file_blocks.keys()):
    print(f"routers/{f}: {len(file_blocks[f])} routes")
print("\nNext steps:")
print("1. Run: python -m py_compile api-gateway/_core.py api-gateway/routers/*.py api-gateway/main_new.py")
print("2. Fix any import errors")
print("3. Rename main.py → main_old.py, main_new.py → main.py")
print("4. Run: ruff check api-gateway/")
print("5. Run: pytest api-gateway/tests/")
