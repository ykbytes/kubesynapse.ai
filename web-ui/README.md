# Agent Sandbox Console

Vite + React + TypeScript frontend for the kubeminionagents API gateway.

## Local development

1. Copy `.env.example` to `.env.local` if you need to point at a non-default gateway.
2. Install dependencies with `npm install`.
3. Start the dev server with `npm run dev`.

By default the Vite dev server proxies `/api/*` to `http://127.0.0.1:8080`.

## Build

Run `npm run build` to create a production bundle in `dist/`.

## Container image

Build the production image with `podman build -t ghcr.io/your-org/ai-agent-sandbox-web-ui:latest .`.

The image serves the Vite bundle through Nginx with SPA fallback enabled. In the Helm chart the UI is published on `/`, while the API gateway remains on `/api` for the same host.

## Current scope

- Agent discovery through the API gateway
- Empty-namespace bootstrap by creating an agent from the UI
- Agent editing and deletion with structured editors for file-backed skills and Goose config files
- Chat invoke and SSE streaming invoke
- Explicit A2A routing and specialist-team orchestration for LangGraph agents from the chat workbench
- Goose runtime remains chat-first in the UI; approvals, gateway-routed MCP tools, and sandbox session continuity remain LangGraph-only, while a limited safe subset of Goose-native run controls is exposed for chat (`max_turns`, workspace-relative `working_directory`, and a read-only system prompt preview)
- Thread continuity per selected agent
- Approval decisions and retry from the UI
- Per-agent conversation and activity state
- Runtime log inspection
- Selected-agent inspector coverage for parsed skill summaries, capability grants, inbound A2A callers, and discovered peer reachability
- Workflow creation, editing, inspection, and deletion
- Evaluation creation, editing, inspection, and deletion

## Operator workflow

The UI is built around the same production surfaces exposed by the API gateway and operator:

- connect once with a namespace and bearer token, then browse agents, workflows, and evaluations from the same session
- create and edit agents without raw JSON for `skills.files` or Goose config bundles
- inspect runtime-facing configuration, parsed skill summaries, tool and A2A metadata, logs, and approval state side-by-side with chat
- use the chat workbench for standard prompts, explicit A2A delegation, or specialist-team requests

For release verification, run `npm run build` before publishing a new image.