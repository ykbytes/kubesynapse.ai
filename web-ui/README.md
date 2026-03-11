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
- Agent editing and deletion
- Chat invoke and SSE streaming invoke
- Thread continuity per selected agent
- Approval decisions and retry from the UI
- Per-agent conversation and activity state
- Runtime log inspection
- Workflow creation, editing, inspection, and deletion
- Evaluation creation, editing, inspection, and deletion