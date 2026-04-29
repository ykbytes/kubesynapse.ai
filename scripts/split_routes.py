#!/usr/bin/env python3
"""Extract route handlers from api-gateway/main.py into modular router files.

This is a one-shot migration script. After the split is verified it can be deleted.
"""

import re
import os
from pathlib import Path

WORKSPACE = Path(r"C:\Users\ahmed\OneDrive\Desktop\repos\kubesynapse\kubemininions")
MAIN_PY = WORKSPACE / "api-gateway" / "main.py"
ROUTERS_DIR = WORKSPACE / "api-gateway" / "routers"

# Route prefix → router file mapping
PREFIX_MAP = [
    # (URL prefix pattern, router_file_name, router_tag)
    ("/api/auth", "auth.py", "auth"),
    ("/api/admin", "admin.py", "admin"),
    ("/api/usage", "admin.py", "admin"),
    ("/api/agents", "agents.py", "agents"),
    ("/api/namespaces", "agents.py", "agents"),
    ("/api/workflows", "workflows.py", "workflows"),
    ("/api/evals", "evals.py", "evals"),
    ("/a2a/", "a2a.py", "a2a"),
    ("/.well-known/agent-card.json", "a2a.py", "a2a"),
    ("/api/chat-sessions", "chat.py", "chat"),
    ("/api/memory", "chat.py", "chat"),
    ("/api/notifications", "chat.py", "chat"),
    ("/api/providers", "llm.py", "llm"),
    ("/api/llm", "llm.py", "llm"),
    ("/api/copilot", "llm.py", "llm"),
    ("/api/observability", "observability.py", "observability"),
    ("/api/skills", "observability.py", "observability"),
    ("/api/mcp", "observability.py", "observability"),
    ("/api/mcp-hub", "observability.py", "observability"),
    ("/api/system", "admin.py", "admin"),
    ("/api/health", "admin.py", "admin"),
    ("/api/ready", "admin.py", "admin"),
    ("/api/policies", "admin.py", "admin"),
    ("/api/approvals", "admin.py", "admin"),
    ("/api/export", "admin.py", "admin"),
    ("/api/import", "admin.py", "admin"),
    ("/api/intelligence", "admin.py", "admin"),
]

# Read the entire file
content = MAIN_PY.read_text(encoding="utf-8")
lines = content.split("\n")

# Find all @app.route decorators with their line numbers
route_pattern = re.compile(r'^\s*@app\.(get|post|put|patch|delete|options)\s*\(')
route_entries = []  # (line_number, decorator_line, method, url)

for i, line in enumerate(lines):
    m = route_pattern.match(line)
    if m:
        method = m.group(1)
        # Extract URL from the decorator
        url_match = re.search(r'\(\s*["\']([^"\']+)["\']', line)
        if url_match:
            url = url_match.group(1)
            route_entries.append((i + 1, line.strip(), method, url))

print(f"Found {len(route_entries)} route decorators")

# Group routes by file
file_routes = {}
for entry in route_entries:
    line_no, decorator, method, url = entry
    target_file = None
    for prefix, filename, tag in PREFIX_MAP:
        if url.startswith(prefix):
            target_file = filename
            break
    if target_file is None:
        # Find best match
        for prefix, filename, tag in PREFIX_MAP:
            if prefix in url or url in prefix:
                target_file = filename
                break
    if target_file is None:
        print(f"WARNING: No file match for route: {method.upper()} {url} at line {line_no} — assigning to admin.py")
        target_file = "admin.py"
    if target_file not in file_routes:
        file_routes[target_file] = []
    file_routes[target_file].append((line_no, decorator, method, url))

# Print summary
for filename, routes in sorted(file_routes.items()):
    print(f"\n{filename}: {len(routes)} routes")
    for r in routes:
        print(f"  L{r[0]:5d}  {r[2].upper():7s} {r[3]}")

# Now let's figure out the function boundaries for each route
# Each route decorator is followed by its handler function
# We need to find the end of each function
# Approach: find the next route decorator OR the next top-level def/class/comment marker

# Build a set of lines that are "top-level" starts
top_level_pattern = re.compile(r'^(?:@app\.|# -{10,}|async def |def |class |if __name__)')
top_level_starts = set()
for i, line in enumerate(lines):
    if top_level_pattern.match(line):
        top_level_starts.add(i)

# For each route entry, find its function end (next top-level start minus 1)
route_blocks = []
for entry in route_entries:
    line_no, decorator, method, url = entry
    start_idx = line_no - 1  # 0-indexed
    # Find the next non-empty line after this route
    end_idx = start_idx + 30  # safe default
    for j in range(start_idx + 1, min(len(lines), start_idx + 400)):
        if j in top_level_starts:
            end_idx = j - 1
            break
        # Also look for blank line + next route pattern as a heuristic
        if j + 1 < len(lines) and route_pattern.match(lines[j + 1]) and lines[j].strip() == "":
            end_idx = j
            break
    else:
        end_idx = min(start_idx + 400, len(lines) - 1)
    route_blocks.append((line_no, end_idx + 1, method, url))

# For each file, generate the router code
IMPORTS_HEADER = '''"""Auto-generated router module — extracted from api-gateway main.py."""
from __future__ import annotations

from typing import Any, cast
from fastapi import APIRouter, Body, Cookie, Depends, Header, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse, RedirectResponse, StreamingResponse

# Re-import all shared dependencies from the gateway's dependencies module
from dependencies import *  # noqa: F403  — provides models, constants, helpers, and auth

router = APIRouter()

'''

for filename, routes in sorted(file_routes.items()):
    # Determine router tag and prefix
    tag = "misc"
    prefix = ""
    for p, f, t in PREFIX_MAP:
        if f == filename:
            tag = t
            prefix = p.split("/")[1] if p.startswith("/") else p
            break

    # Get the tag from the first matching prefix
    for p, f, t in PREFIX_MAP:
        if f == filename:
            tag = t
            break

    output_path = ROUTERS_DIR / filename

    # Merge overlapping route blocks (consecutive ones belong together)
    # Actually, just extract the code for each route
    route_code_blocks = []
    for entry in route_entries:
        ln, decorator, method, url = entry
        # Find which file this belongs to
        target_file = None
        for p, f, t in PREFIX_MAP:
            if url.startswith(p):
                target_file = f
                break

        if target_file != filename:
            continue

        # Find the route block for this entry
        for block in route_blocks:
            if block[0] == ln:
                start_ln, end_ln, bm, bu = block
                # Extract the code
                code_lines = lines[ln - 1 : end_ln]
                # Replace @app with @router
                code_text = "\n".join(code_lines)
                code_text = code_text.replace("@app.", "@router.")
                route_code_blocks.append(code_text)
                break

    if not route_code_blocks:
        print(f"WARNING: No route code blocks for {filename}")
        continue

    # Write the router file
    router_code = IMPORTS_HEADER + "\n\n".join(route_code_blocks) + "\n"
    output_path.write_text(router_code, encoding="utf-8")
    print(f"Wrote {output_path} ({len(route_code_blocks)} routes)")

print("\nDone! Router files created.")
