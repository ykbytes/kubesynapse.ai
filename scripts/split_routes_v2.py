#!/usr/bin/env python3
"""Extract route handlers from api-gateway/main.py into modular router files — v2.

Fixed: now properly extracts function bodies, not just decorators.
"""

import re
from pathlib import Path

WORKSPACE = Path(r"C:\Users\ahmed\OneDrive\Desktop\repos\kubesynapse\kubemininions")
MAIN_PY = WORKSPACE / "api-gateway" / "main.py"
ROUTERS_DIR = WORKSPACE / "api-gateway" / "routers"

# Route prefix → (router_file_name, tag, router_prefix)
PREFIX_MAP = [
    ("/api/auth", "auth.py", "auth", "/api/auth"),
    ("/api/admin", "admin.py", "admin", ""),
    ("/api/usage", "admin.py", "admin", ""),
    ("/api/agents", "agents.py", "agents", ""),
    ("/api/namespaces", "agents.py", "agents", ""),
    ("/api/workflows", "workflows.py", "workflows", ""),
    ("/api/evals", "evals.py", "evals", ""),
    ("/a2a/", "a2a.py", "a2a", "/a2a"),
    ("/.well-known/agent-card.json", "a2a.py", "a2a", ""),
    ("/api/chat-sessions", "chat.py", "chat", ""),
    ("/api/memory", "chat.py", "chat", ""),
    ("/api/notifications", "chat.py", "chat", ""),
    ("/api/providers", "llm.py", "llm", ""),
    ("/api/llm", "llm.py", "llm", ""),
    ("/api/copilot", "llm.py", "llm", ""),
    ("/api/observability", "observability.py", "observability", ""),
    ("/api/skills", "observability.py", "observability", ""),
    ("/api/mcp", "observability.py", "observability", ""),
    ("/api/mcp-hub", "observability.py", "observability", ""),
    ("/api/system", "admin.py", "admin", ""),
    ("/api/health", "admin.py", "admin", ""),
    ("/api/ready", "admin.py", "admin", ""),
    ("/api/policies", "admin.py", "admin", ""),
    ("/api/approvals", "admin.py", "admin", ""),
    ("/api/export", "admin.py", "admin", ""),
    ("/api/import", "admin.py", "admin", ""),
    ("/api/intelligence", "admin.py", "admin", ""),
]

content = MAIN_PY.read_text(encoding="utf-8")
lines = content.split("\n")
total_lines = len(lines)

# Find all @app. route decorator lines (0-indexed)
route_pattern = re.compile(r'^\s*@app\.(get|post|put|patch|delete|options)\s*\(')
route_indices = []  # list of (0-indexed line, method, url)

for i, line in enumerate(lines):
    m = route_pattern.match(line)
    if m:
        method = m.group(1)
        url_match = re.search(r'\(\s*["\']([^"\']+)["\']', line)
        if url_match:
            url = url_match.group(1)
            route_indices.append((i, method, url))

print(f"Found {len(route_indices)} route decorators")

# Identify "next decorator" boundaries
# For each route at index `start`, find where the next route starts
# The function body goes from start to (next_route_start - 1)
route_boundaries = []  # (start_idx, end_idx, method, url)
for idx, (start, method, url) in enumerate(route_indices):
    if idx + 1 < len(route_indices):
        next_start = route_indices[idx + 1][0]
    else:
        next_start = total_lines  # end of file
    route_boundaries.append((start, next_start, method, url))

# Also find section separator lines (used for dedup between routes)
section_pattern = re.compile(r'^# -{10,}')
section_lines = {i for i, line in enumerate(lines) if section_pattern.match(line)}

# Group routes by target file
file_routes = {}  # filename -> list of (start, end, method, url)
for start, end, method, url in route_boundaries:
    target_file = None
    for prefix, filename, tag, rprefix in PREFIX_MAP:
        if url.startswith(prefix):
            target_file = filename
            break
    if target_file is None:
        print(f"WARNING: No file match for {method.upper()} {url} — assigning to admin.py")
        target_file = "admin.py"
    if target_file not in file_routes:
        file_routes[target_file] = []
    file_routes[target_file].append((start, end, method, url))

# Generate router files
ROUTER_HEADER = '''"""kubesynapse API Gateway — auto-generated router module.

Extracted from the original api-gateway/main.py monolith.
"""
from __future__ import annotations

from typing import Any, cast
from fastapi import APIRouter, Body, Cookie, Depends, Header, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse, RedirectResponse, StreamingResponse

# Re-import all shared dependencies from the gateway's dependencies module
import dependencies as _d  # noqa: F401

router = APIRouter()

'''

for filename in sorted(file_routes.keys()):
    routes = file_routes[filename]
    # Merge overlapping/adjacent blocks
    # Sort by start line
    routes.sort(key=lambda r: r[0])
    
    # Determine primary tag
    tag = "misc"
    for prefix, fname, ftag, rprefix in PREFIX_MAP:
        if fname == filename:
            if routes[0][3].startswith(prefix):
                tag = ftag
                break
    
    # Add tag to router
    header = ROUTER_HEADER.replace("router = APIRouter()", f'router = APIRouter(tags=["{tag}"])')
    
    # Build the code: extract raw lines for each route, change @app. to @router.
    code_blocks = []
    seen_lines = set()
    
    for start, end, method, url in routes:
        # Don't overlap: skip lines already included from previous block
        block_lines = []
        for i in range(start, end):
            if i in seen_lines:
                continue
            line = lines[i]
            # Replace @app. with @router.
            if route_pattern.match(line):
                line = line.replace("@app.", "@router.", 1)
            block_lines.append(line)
            seen_lines.add(i)
        
        # Remove trailing blank lines but keep one
        while block_lines and block_lines[-1].strip() == "":
            block_lines.pop()
        if block_lines:
            code_blocks.append("\n".join(block_lines))
    
    if not code_blocks:
        print(f"WARNING: No code extracted for {filename}")
        continue
    
    router_code = header + "\n\n\n".join(code_blocks) + "\n"
    output_path = ROUTERS_DIR / filename
    output_path.write_text(router_code, encoding="utf-8")
    print(f"Wrote {filename}: {len(code_blocks)} route handlers ({len(''.join(code_blocks))} chars)")

print("\nDone!")
