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
- Template-based agent creation and cloning/export-import driven resource bootstrap
- Agent editing and deletion with structured editors for file-backed skills and Goose config files
- Chat invoke and SSE streaming invoke
- Explicit A2A routing, chat session persistence, and specialist-team orchestration for LangGraph agents from the chat workbench
- Goose runtime remains chat-first in the UI; approvals, gateway-routed MCP tools, and sandbox session continuity remain LangGraph-only, while a limited safe subset of Goose-native run controls is exposed for chat (`max_turns`, workspace-relative `working_directory`, and a read-only system prompt preview)
- Thread continuity per selected agent
- Approval decisions and retry from the UI
- Per-agent conversation, activity state, and saved session history
- Runtime log inspection
- Selected-agent inspector coverage for parsed skill summaries, capability grants, inbound A2A callers, and discovered peer reachability
- Workflow creation, editing, inspection, deletion, run history, and visual composer execution monitoring
- Evaluation creation, editing, inspection, deletion, and per-case result visualization
- Policy management, admin user management, audit trail review, usage dashboards, and health dashboard access
- Command palette, mobile navigation shell, onboarding tour, notifications, and redesigned provider-centric settings management

## Operator workflow

The UI is built around the same production surfaces exposed by the API gateway and operator:

- connect once with a namespace and bearer token, then browse agents, workflows, and evaluations from the same session
- create and edit agents without raw JSON for `skills.files` or Goose config bundles
- inspect runtime-facing configuration, parsed skill summaries, tool and A2A metadata, logs, and approval state side-by-side with chat
- use the chat workbench for standard prompts, explicit A2A delegation, or specialist-team requests

## Admin and operations

- The admin workspace exposes user management, audit logs, usage and cost reporting, and a system health dashboard.
- The settings workspace is provider-centric: operators search providers on the left and manage API keys and enabled models in a focused detail pane on the right.
- The workflow composer includes conditional and loop step editing, live execution state, inline approvals, and recent run history.

For release verification, run `npm run build` before publishing a new image.