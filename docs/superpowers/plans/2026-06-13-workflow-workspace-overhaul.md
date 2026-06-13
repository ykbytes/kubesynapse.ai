# Workflow Workspace Overhaul Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a cleaner workflow SaaS workspace for operating workflows, browsing runs/files, and editing definitions.

**Architecture:** Keep `WorkflowManagerProps` unchanged. Move duplicated chrome into one top-level shell and split runs/files/definition into clearer subviews.

**Tech Stack:** React, TypeScript, Vite, Tailwind utility classes, lucide-react, existing UI primitives.

---

### Task 1: Add Smoke Verification

**Files:**
- Create: `web-ui/scripts/verify-workflow-workspace.mjs`
- Modify: `web-ui/package.json`

- [ ] Add a Node script that asserts `WorkflowManager.tsx` exposes the new `Overview`, `Runs`, `Files`, and `Definition` workspace tabs and does not keep the old `Workflow workspace` duplicate banner.
- [ ] Add `verify:workflow` to `web-ui/package.json`.
- [ ] Run `npm run verify:workflow` and confirm it fails before production code changes.

### Task 2: Rebuild Workflow Shell

**Files:**
- Modify: `web-ui/src/components/workflows/WorkflowManager.tsx`

- [ ] Replace the stacked header/status/brief/banner with a single workspace shell.
- [ ] Add tabs for `overview`, `runs`, `files`, and `definition`.
- [ ] Preserve create, update, delete, run, cancel, retry, approval, factory mode, and composer handlers.
- [ ] Keep selected workflow form state and step editing behavior unchanged.

### Task 3: Split Runs And Files

**Files:**
- Modify: `web-ui/src/components/workflow/WorkflowHistoryView.tsx`
- Create if needed: `web-ui/src/components/workflow/WorkflowFilesView.tsx`

- [ ] Make the run history view focus only on run list and run details.
- [ ] Move file browsing into a dedicated files view that reuses `FileExplorer`.
- [ ] Preserve observatory links, run selection, artifact ZIP download, preview, and live refresh.

### Task 4: Verify

**Files:**
- Build/test only.

- [ ] Run `npm run verify:workflow`.
- [ ] Run `npm run build`.
- [ ] Open the local page and visually verify the workflow workspace no longer has repeated UI and the runs/files/definition flows are usable.
