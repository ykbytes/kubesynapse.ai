# KubeSynapse Console

Vite + React + TypeScript frontend for the KubeSynapse API gateway.

## Supported runtimes

The console creates and manages agents for the three supported runtime kinds:

- `opencode` is the default runtime and gets the richer config-file editing flows.
- `pi` is the supported alternative runtime and uses the same create, edit, inspect, and invoke surfaces.
- `mistral-vibe` is the supported Mistral-backed runtime bridge and uses the same create, edit, inspect, and invoke surfaces.

## Local development

1. Copy `.env.example` to `.env.local` if you need to point at a non-default gateway.
2. Install dependencies with `npm install`.
3. Start the dev server with `npm run dev`.

Default local dev shape:

- Vite serves the app on `http://127.0.0.1:5173` and proxies `/api/*` to `http://127.0.0.1:8080`.
- `npm run preview` serves the production bundle on `http://127.0.0.1:4173`.
- The gateway's default browser CORS allowlist already matches the dev server port `5173`, so local browser QA is cleanest when the UI runs there.
- For a self-contained browser QA session, run the gateway with local auth enabled and a file-backed SQLite path under `api-gateway/.local/` so the first account bootstrap and refresh session flow survive restarts.

By default the Vite dev server proxies `/api/*` to `http://127.0.0.1:8080`.

The desktop workspace shell now sizes the left sidebar from the app shell instead of forcing a fixed internal width. On narrower desktop panes the sidebar clamps down before content gets squeezed, while the mobile sheet still renders the sidebar full-width.

## Build

Run `npm run build` to create a production bundle in `dist/`.

## Container image

Build the production image with `podman build -t docker.io/kubesynapse/kubesynapse-web-ui:<tag> .`.

The image serves the Vite bundle through Nginx with SPA fallback enabled. In the Helm chart the UI is published on `/`, while the API gateway remains on `/api` for the same host.

Current deployed image: `docker.io/kubesynapse/kubesynapse-web-ui:v1.2.0`.

## Live Activity Stream

Real-time step-level status transitions with a pulse indicator and a
**Ctrl+L** keyboard toggle. The stream surfaces agent starts, completions,
approvals, and errors as they happen without polling.

## ExecutionObservatory

Post-execution trace analysis suite:

- **TracePlayer** — Replay a workflow run step-by-step.
- **StepInspector** — Deep-dive into inputs, outputs, and timing for any step.
- **LLMCallViewer** — Inspect raw prompt/response pairs sent to the model.
- **ExecutionTimeline** — Gantt-style view of parallel and sequential steps.
- **ExecutionDiffView** — Compare two runs side-by-side to spot regressions.

## WorkflowComposer

Visual DAG builder that supports conditional and loop step editing, live
execution state overlays, inline approval gates, and a recent run history
sidebar. Changes are validated against the workflow CRD schema before saving.

## FileExplorer + Artifact Browser

Tree view of generated files across all agent workspaces. Includes a built-in
file preview for Markdown, JSON, images, and code, plus a one-click ZIP
download of the entire workspace.

## Agent Live Reasoning Log (planned)

Terminal-style SSE stream that surfaces raw Pi agent events in real time.
Useful for debugging model reasoning loops and tool-use decisions.

## Current scope

- Agent discovery through the API gateway
- Empty-namespace bootstrap by creating an agent from the UI
- Template-based agent creation and cloning/export-import driven resource bootstrap
- Agent editing and deletion with structured editors for file-backed skills and OpenCode config files
- Chat invoke and SSE streaming invoke
- Explicit A2A routing, chat session persistence, and OpenCode-focused chat workbench flows
- OpenCode chat controls for safe runtime tuning, including `system`, `max_turns`, and workspace-relative `working_directory`
- Thread continuity per selected agent
- Approval decisions and retry from the UI
- Per-agent conversation, activity state, and saved session history
- Runtime log inspection
- Selected-agent inspector coverage for parsed skill summaries, capability grants, inbound A2A callers, and discovered peer reachability
- Workflow creation, editing, inspection, deletion, run history, and visual composer execution monitoring
- Evaluation creation, editing, inspection, deletion, and per-case result visualization
- Policy management, admin user management, audit trail review, usage dashboards, and health dashboard access
- Command palette, mobile navigation shell, onboarding tour, notifications, and redesigned provider-centric settings management
- Live Activity Stream with real-time step-level status transitions, pulse indicator, and Ctrl+L toggle
- ExecutionObservatory for post-execution trace analysis (TracePlayer, StepInspector, LLMCallViewer, Timeline, DiffView)
- WorkflowComposer DAG builder with conditional/loop editing, live execution state, inline approvals, and run history
- FileExplorer and Artifact Browser with tree view, file preview, and ZIP download of the entire workspace
- Agent Live Reasoning Log (planned) — terminal-style SSE stream of Pi agent events

## Operator workflow

The UI is built around the same production surfaces exposed by the API gateway and operator:

- connect once with a namespace and bearer token, then browse agents, workflows, and evaluations from the same session
- create and edit agents without raw JSON for `skills.files` or OpenCode config bundles
- inspect runtime-facing configuration, parsed skill summaries, tool and A2A metadata, logs, and approval state side-by-side with chat
- use the chat workbench for standard prompts or explicit A2A delegation

## Admin and operations

- The admin workspace exposes user management, audit logs, usage and cost reporting, and a system health dashboard.
- The settings workspace is provider-centric: operators search providers on the left and manage API keys and enabled models in a focused detail pane on the right.
- The workflow composer includes conditional and loop step editing, live execution state, inline approvals, and recent run history.

For release verification, run `npm run build` before publishing a new image.
