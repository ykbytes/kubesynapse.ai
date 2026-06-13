# Workflow Workspace Overhaul Design

## Goal

Replace the duplicated workflow page chrome with one SaaS-style workspace that lets users operate workflows, inspect runs, browse files, and edit definitions without losing context.

## Direction

The page will keep the existing `WorkflowManagerProps` contract and reuse existing API handlers from `App.tsx`. The redesign is presentation-only unless a security or runtime contract bug appears during implementation.

## Layout

The workspace becomes a single shell:

- A compact header with workflow identity, phase, primary actions, and summary metrics.
- A tab rail for `Overview`, `Runs`, `Files`, and `Definition`.
- `Overview` shows current run health, progress, next action, and step signals.
- `Runs` shows a clean run list beside selected run details, without the nested half-width run panel.
- `Files` reuses the existing file explorer for workflow agents and preserves download/preview behavior.
- `Definition` keeps create/edit fields, execution settings, and step editing in one builder view.

## Component Strategy

`WorkflowManager` will own top-level workspace state and tabs. `WorkflowHistoryView` will become a run-focused view instead of embedding files. A new file-focused subview may be added if it keeps `WorkflowHistoryView` smaller and clearer.

## Testing

Because `web-ui` does not currently include a React test runner, add a small source-level smoke verification script for the expected workspace structure, then run `npm run build`. After implementation, verify the page in the browser at `localhost:3000`.
