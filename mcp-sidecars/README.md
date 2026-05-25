# KubeSynapse MCP Sidecars

Inventory of bundled MCP (Model Context Protocol) tool sidecars that extend
agent capabilities.

## Purpose

Sidecars attach additional tools to agents without bloating the runtime image.
Each sidecar runs as a standalone container and exposes a well-defined tool
surface via MCP.

## Bundled Sidecars

| Sidecar | Capability |
|---------|------------|
| `code-exec` | Sandboxed code execution (Python, Node.js, Bash) |
| `web-search` | Search queries with result summarization |
| `browser` | Headless browser navigation, screenshots, and forms |
| `database` | SQL and NoSQL query execution against registered connections |
| `git` | Repository clone, diff, commit, and branch operations |
| `github-adapter` | PRs, issues, releases, and repo management via GitHub API |
| `kubernetes` | In-cluster resource queries and constrained mutations |
| `messaging` | Slack, Discord, and email send/receive |
| `rag` | Retrieval-augmented generation over uploaded documents |
| `documents` | PDF, DOCX, and Markdown parsing and extraction |
| `collector` | Intelligence collector for observability data |

## Architecture

Each sidecar is a standalone container. The runtime connects to it via:

- **localhost** — When co-located in the same pod (default for most sidecars).
- **Shared MCP Hub** — A central MCP router that sidecars register with,
  allowing dynamic discovery and load balancing.

## Security

- **Capability Model** — Each sidecar declares its capabilities at startup.
  The runtime only binds tools that the agent explicitly requested.
- **Network Egress Filtering** — Sidecars run under NetworkPolicy rules that
  restrict outbound traffic to known endpoints.
- **Resource Quotas** — CPU/memory limits prevent a runaway tool from starving
  the agent runtime.
- **Bearer Token Auth** — Sidecars validate a per-session token passed by the
  runtime on every MCP request.

## Adding a New Sidecar

1. Create a new directory under `mcp-sidecars/<name>/`.
2. Implement the MCP server handshake and at least one tool handler.
3. Add a `Dockerfile` that builds to a small image (Alpine or distroless).
4. Update the Helm chart `values.yaml` under `mcpSidecars.<name>` with default
   resource limits and image coordinates.
5. Document the tool schema in this README.
6. Open a PR with a smoke test that exercises the health endpoint.

For questions, open an issue with the `sidecar` label.
