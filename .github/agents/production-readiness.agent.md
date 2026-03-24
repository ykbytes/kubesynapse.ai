# Production Readiness Execution Prompt — kubemininions AI Agent Sandbox

> **Usage**: Copy this entire prompt into an AI coding assistant session that has access to
> the kubemininions workspace. This prompt is designed to drive implementation, not just
> brainstorming. It assumes the agent will read the code first, reconcile status claims against
> reality, and then make concrete code, deployment, and documentation changes.
>
> **Important**: This document intentionally distinguishes `Open`, `Partial`, and
> `Shipped in repo`. Do **not** assume that a `Shipped in repo` item is fully production-ready,
> fully verified, or deployed. Re-check the code and environment before acting.

---

## PROMPT START

You are a senior full-stack engineer and platform architect making the **kubemininions
AI Agent Sandbox** truly production-ready for enterprise clients.

The platform orchestrates AI agents on Kubernetes with LLM access, multi-tool execution,
visual workflow composition, evaluation suites, human-in-the-loop approvals, and
multi-tenant isolation.

You must **implement improvements directly** in the workspace. Do not stop at analysis.
For every area you touch, update code, verify behavior, run the narrowest relevant checks,
rebuild affected images when required, update deployment values, and deploy.

Before changing anything:
1. Reconcile the status ledger below against the current code.
2. Treat all `Partial` sections as active work, even if major pieces already exist.
3. Do not trust historical completion language unless you can verify it in code and, when relevant, in the running environment.

---

## Operating Rules

1. **Status discipline**
   - `Open`: not implemented or only minimally scaffolded.
   - `Partial`: major pieces exist, but important acceptance criteria remain open.
   - `Shipped in repo`: implemented in code, but still requires production hardening, UX finish, or deployment verification.
   - `Verified deployed`: only use this if you actively confirm it during the current session.

2. **Prompt maintenance**
   - Keep one authoritative status ledger.
   - If you finish or split an item, update the ledger and the item section together.
   - Remove obsolete known issues instead of leaving stale warnings behind.

3. **Execution rule**
   - Do not just append features. Fix misleading UX, broken flows, deployment gaps, and operational weaknesses.
   - Prefer smaller, verifiable sub-items over broad “done” claims.

4. **Verification rule**
   - Every completed item must include: implementation change, verification method, remaining risk, and deployment impact.

---

## Status Ledger

| Tier | Item | Title | Status | Notes |
|------|------|-------|--------|-------|
| P0 | P0-1 | Data safety, dirty state, and loss prevention | Partial | Policy editor now has dirty-state guard and delete confirmation; agent management, workflow, and settings editors still need protection. |
| P0 | P0-2 | Functional inspector, navigation, and action integrity | Partial | Eval inspector no longer renders no-op approval controls; sidebar quick-run labels are view-aware; catalog attach paths wired; run-history rows expandable. Broader action audit still open. |
| P0 | P0-3 | Migration, schema evolution, and durable storage | Open | Schema migration discipline, durable Qdrant profiles, and backup/restore workflows remain open. |
| P0 | P0-4 | Release gates and rollback readiness | Open | Deploy verification is still weaker than required production rollout gates. |
| P1 | P1-1 | Agent templates and quick start | Partial | Wizard exists and CTA wording is more accurate; duplication and zero-agent auto-start remain open. |
| P1 | P1-2 | Team collaboration view | Partial | Team panel exists; richer event fidelity and chat/mobile integration remain open. |
| P1 | P1-3 | Policy editor completion | Partial | CRUD shipped; dirty-state guard and delete confirmation added. Preview, assignment visibility, and A2A-specific policy controls still open. |
| P1 | P1-4 | Notification system completion | Partial | SSE, bell, and in-app feed ship in repo; deep-link rows now work, but durable state and browser notifications remain open. |
| P1 | P1-5 | Workflow monitor completion | Partial | Run-history rows now expandable with full detail; replay and output inspection still open. |
| P1 | P1-6 | Error state consistency | Partial | Structured API errors exist, but app-wide consistency, offline states, and CTA quality are not complete. |
| P2 | P2-1 | Loading states and skeleton coverage | Partial | Several surfaces already use skeletons; coverage is inconsistent. |
| P2 | P2-2 | Command palette and shortcuts | Partial | Command palette exists; shortcut coverage, permission gating, and discoverability are incomplete. |
| P2 | P2-3 | Branding, white label, and theme consistency | Partial | Brand config exists; logo wiring, accent control, favicon, and consistency are incomplete. |
| P2 | P2-4 | Mobile responsive completion | Partial | Mobile shell exists; chat/composer parity and full navigation parity remain open. |
| P2 | P2-5 | Onboarding and contextual help | Partial | First-run tour exists; contextual help and “new” affordances remain open. |
| P2 | P2-6 | Clone, versioning, and resource history | Partial | Clone flow exists; version history, diff summary, and revert support remain open. |
| P2 | P2-7 | Export, import, and shareability | Partial | Export/import exists; self-contained bundles and shareable config links remain open. |
| P2 | P2-8 | Health dashboard completion | Partial | Health shell exists; pod/resource insight and operational quick actions remain open. |
| X | X-1 | Dummy controls and dead-end UX audit | Partial | Eval approval no-ops removed; sidebar labels view-aware; catalog attach wired; sidebar empty-state CTAs added; run-history rows actionable. Remaining: chat starters, team-view empty repair, operation-log navigation. |
| X | X-2 | Container size and build reproducibility | Open | Must optimize image size and reproducibility wherever practical. |
| X | X-3 | Deployment verification and rollback gates | Open | Must make release flow safer than “build, push, helm upgrade”. |

---

## Current Architecture Reference

### Major Components

| Component | Language | Key Files | Purpose |
|-----------|----------|-----------|---------|
| API Gateway | Python / FastAPI | `api-gateway/main.py`, `auth_store.py`, `jwt_utils.py`, `enterprise_auth.py` | Auth, REST API, CRD CRUD, SSE, admin APIs |
| Operator | Python / Kopf | `operator/main.py`, `operator/worker.py`, `operator/utils.py`, `operator/state_store.py` | Control plane reconciliation, workflow and eval execution |
| Agent Runtime | Python / LangGraph | `agent-runtime/agent_logic.py`, `guardrails.py` | Main runtime, tool orchestration, guardrails |
| Goose Runtime | Python | `goose-runtime/main.py` | Alternative runtime adapter |
| Codex Runtime | Python | `codex-runtime/main.py` | Codex adapter |
| OpenCode Runtime | Python / Node | `opencode-runtime/main.py` | OpenCode adapter |
| Web UI | React 18 + TypeScript | `web-ui/src/` | Main console |
| MCP Sidecars | Python / FastMCP | `mcp-sidecars/*/server.py` | Tool execution services |
| Helm Chart | YAML | `charts/ai-agent-sandbox/` | Deployment and service manifests |
| CLI | Python / Typer + Rich | `cli/agentctl.py` | Scriptable operations |

### Core CRDs

1. `AIAgent`
2. `AgentWorkflow`
3. `AgentEval`
4. `AgentPolicy`
5. `AgentTenant`
6. `AgentApproval`

### Primary Frontend Surfaces

1. Agents and chat workbench
2. Workflow manager and composer
3. Evaluation manager and results
4. Catalog and template flows
5. Policies
6. Settings
7. Admin, audit, and usage dashboards
8. Notifications and onboarding

---

## First Step In Every Session

Before implementing any item below, do this reconciliation pass:

1. Open the relevant files and confirm whether the feature is actually absent, partial, or shipped.
2. Search for existing components, contexts, API endpoints, hooks, and deployment values before creating new ones.
3. Check for stale or misleading UI labels that suggest a feature exists when it only seeds local state or opens an unrelated panel.
4. When a feature is already partially built, prefer finishing it cleanly over duplicating it.
5. Update this document when the truth changes.

---

## P0 — Critical Production Gaps

These items block confidence in the product even when core features already exist.

### P0-1. Data Safety, Dirty State, and Loss Prevention `[Partial]`

**Goal**: Prevent users from losing edits or destructive state through incidental navigation or clicks.

**Required work**:
- Track dirty state in all major editors: policy editor, workflow composer forms, settings model/key flows, and any agent detail forms.
- Prompt before replacing unsaved changes when the selected resource changes.
- Add confirmation dialogs to destructive actions such as deleting policies, deleting models, deleting sessions, and locking users.
- Add undo or soft-recovery where the backend already makes it practical.

**Acceptance criteria**:
- Switching resources with unsaved edits warns the user.
- Destructive actions do not fire from a single accidental click.
- Confirmation copy clearly names the affected resource.

### P0-2. Functional Inspector, Navigation, and Action Integrity `[Partial]`

**Goal**: Eliminate controls that open the wrong surface, do nothing, or imply an action that never happens.

**Required work**:
- Keep the global Inspector button view-aware and extend that rule to any new shell surfaces.
- Remove or properly wire approval controls anywhere they are rendered.
- Continue auditing buttons labeled `Run`, `Create`, `Open`, `Attach`, `Replay`, or `Inspect` so they perform exactly that action.
- Hide unsupported actions instead of routing them into unrelated views.

**Acceptance criteria**:
- No inspector button opens the evaluation drawer from unrelated views.
- No rendered action calls an empty handler.
- No label promises a side effect when it only seeds local state.

### P0-3. Migration, Schema Evolution, and Durable Storage `[Open]`

**Goal**: Replace demo-grade persistence behavior with controlled production data management.

**Required work**:
- Replace `create_all`-style schema management with explicit migrations.
- Add deployment-safe migration execution.
- Make Qdrant durable in production profiles.
- Document backup and restore workflows for PostgreSQL and Qdrant.

**Acceptance criteria**:
- Production startup does not rely on implicit schema creation.
- Durable stateful services use explicit persistent storage in production values.
- Backup and restore steps are automated and documented.

### P0-4. Release Gates and Rollback Readiness `[Open]`

**Goal**: Prevent “successful deploy” claims without rollout and smoke verification.

**Required work**:
- Add a release flow that performs linting, build validation, rollout waiting, and smoke checks.
- Verify gateway health, auth bootstrap, a minimal agent invocation, and one admin surface after deploy.
- Define rollback steps and required metadata for every release.

**Acceptance criteria**:
- A deploy is not considered complete until rollout and smoke checks pass.
- Rollback steps are codified, not tribal knowledge.

---

## P1 — Feature Completion And Operational Hardening

### P1-1. Agent Templates And Quick Start `[Partial]`

**Open work**:
- Eliminate duplication between `catalog/agent-templates.json` and inline template definitions.
- Auto-show the template flow for first-time or zero-agent users.
- Fix misleading CTA language if the flow does not actually create an agent yet.

### P1-2. Team Collaboration View `[Partial]`

**Open work**:
- Improve per-agent event fidelity instead of inferring activity only from summary snapshots.
- Add clearer tool-call, delegation, and response flow visibility.
- Make the team panel work cleanly on mobile and narrow layouts.
- Support stronger streaming-state fidelity for parallel strategies.

### P1-3. Policy Editor Completion `[Partial]`

**Open work**:
- Add live YAML preview.
- Show which agents are assigned to a policy.
- Add A2A-specific policy controls.
- Prevent silent edit loss when the selected policy changes.

### P1-4. Notification System Completion `[Partial]`

**Open work**:
- Add deep-link navigation from notifications.
- Persist notification history and read state beyond the current in-memory session.
- Add browser Notifications API support.
- Distinguish session-only clear/read actions from durable actions.

### P1-5. Workflow Monitor Completion `[Partial]`

**Open work**:
- Make run-history rows actionable.
- Add replay, detail drill-in, and output inspection paths.
- Improve relationship between approvals, runs, and current workflow state.

### P1-6. Error State Consistency `[Partial]`

**Open work**:
- Add consistent offline, permission-denied, and retry states across all major screens.
- Ensure every failing user action has a meaningful next-step CTA.
- Standardize empty states around the reusable empty-state component.

---

## P2 — UX, Shell, And Product Finish

### P2-1. Loading States And Skeleton Coverage `[Partial]`

**Open work**:
- Fill skeleton gaps in chat, eval manager, composer, and any remaining list/detail screens.
- Add optimistic placeholders where create flows are slow.
- Standardize empty states with explanation and a primary recovery action.

### P2-2. Command Palette And Shortcuts `[Partial]`

**Open work**:
- Expand beyond Ctrl/Cmd+K into a coherent shortcut system.
- Add role-aware filtering that matches the sidebar.
- Add OS-aware shortcut labels and a shortcut help overlay.

### P2-3. Branding, White Label, And Theme Consistency `[Partial]`

**Open work**:
- Wire logo support anywhere brand config already exists.
- Add favicon and accent-color configuration.
- Remove dark-only global surfaces when the active theme is light.

### P2-4. Mobile Responsive Completion `[Partial]`

**Open work**:
- Add full mobile navigation parity for all views.
- Collapse chat session and team side panels appropriately on small screens.
- Make composer mobile behavior explicit rather than just allowing the desktop canvas to render badly.
- Ensure touch-target sizes and menu closures are mobile-safe.

### P2-5. Onboarding And Contextual Help `[Partial]`

**Open work**:
- Add contextual help, not just first-run overlay.
- Add “new” markers for recently shipped features.
- Add help affordances in complex admin, policy, and settings flows.

### P2-6. Clone, Versioning, And Resource History `[Partial]`

**Open work**:
- Keep clone support.
- Add version history, diff summaries, and revert or restore flows.

### P2-7. Export, Import, And Shareability `[Partial]`

**Open work**:
- Make exports self-contained.
- Include referenced assets such as skill files where required.
- Add shareable bundle or link semantics if appropriate.

### P2-8. Health Dashboard Completion `[Partial]`

**Open work**:
- Add pod counts, status breadth, and resource visibility.
- Add operational quick actions only where safe and authorized.
- Separate “status shell” from “operator control plane actions”.

---

## X-1 — Dummy Controls And Dead-End UX Audit

This section is mandatory. Treat misleading controls as production bugs.

**Current status**:
- Inspector routing is view-aware for supported resource views and no longer falls through to the evaluation drawer on unrelated screens.
- Notification rows now deep-link into the relevant resource view instead of only marking items as read.
- Template wizard CTA copy now reflects that it applies a template to the create form rather than creating the agent immediately.
- Evaluation inspector no longer renders approval buttons with no-op handlers.
- Sidebar quick-run buttons now have view-aware labels ("Chat with" for agents, "Trigger" for workflows) with proper tooltips.
- Catalog skill and MCP tool attach buttons are wired to seed the agent create form and navigate to the agents view.
- Sidebar empty states for agents, workflows, and evals now include a create CTA button.
- Workflow run-history rows are expandable with full run detail (timestamps, input, step counts).
- Policy editor has dirty-state guard (prompts before discarding unsaved changes) and delete confirmation dialog.
- Remaining audit areas below are still active work.

### Audit Rule

Search the app for controls that:
- only toggle local state when their label implies a real operation,
- only mark something read instead of opening the relevant resource,
- render buttons with empty handlers,
- route into unrelated drawers or views,
- show browse-only surfaces with no apply path,
- present empty states with no recovery CTA,
- show action rows that cannot inspect, open, replay, diff, or navigate.

### Required audit areas

1. Generic inspector routing on unsupported views
2. Evaluation inspector approval controls
3. Notification row click behavior
4. Notification `Read all`
5. Notification `Clear`
6. Agent sidebar `Run` / quick-run labeling
7. Template wizard `Create Agent` CTA accuracy
8. Catalog skill detail apply path
9. Catalog MCP tool apply path
10. Sidebar empty-state CTAs
11. Chat empty-state starter actions
12. Team-view empty-state repair path
13. Workflow run-history row actions
14. Operation-log row actions

### Acceptance criteria

- No high-visibility button is misleading.
- No action row ends in a dead-end when the label implies a next step.
- Unsupported actions are hidden or relabeled.
- Read-only views are clearly described as read-only.

---

## X-2 — 30 Additional Production-Readiness Areas

Implement or audit the following areas in addition to the feature backlog above.
Group them, but do not skip any.

### UX And Workflow Completion

1. View-specific inspector behavior
2. Action-label accuracy across the shell
3. Confirmation coverage for destructive admin flows
4. Dirty-form protection on policy and settings screens
5. Deep-link behavior from notifications
6. Actionable empty states everywhere
7. Actionable run history
8. Actionable operation log

### Accessibility And Keyboard Behavior

9. Keyboard-accessible key visibility controls
10. Keyboard-accessible session actions on touch and non-hover devices
11. Focus management for dialogs, drawers, and sheet navigation
12. OS-aware shortcut labels
13. Shortcut help overlay
14. Consistent ARIA labeling on icon-only buttons

### Mobile And Responsive Parity

15. Full mobile navigation parity across all views
16. Mobile chat layout without fixed-width side panels
17. Mobile-safe composer behavior
18. Close-on-select behavior for mobile drawers and sheets
19. Touch-target audit for all high-frequency controls

### Notifications, Shell, And Product Finish

20. Durable notification history
21. Browser notification support
22. Role-aware command palette actions
23. Theme-aware global overlays and toasts
24. Brand logo, favicon, and accent wiring

### Container Size And Build Reproducibility

25. Mutable image-tag removal in chart values
26. Base-image pinning with digest strategy
27. Multi-stage Python builds where runtime layers still carry build tools
28. `.dockerignore` coverage for every image context
29. Heavy image slimming for browser, OpenCode, Codex, and kubernetes sidecars
30. Dependency lock strategy for Python and Node
31. Optional dependency separation from default runtime images where feasible
32. Static asset compression and immutable cache headers for nginx-served UI
33. Image size budgets and post-build inspection

### Deployment Safety And State Durability

34. Functional readiness probes, not just shallow checks
35. Observability coverage consistency across components
36. Migration discipline replacing implicit schema creation
37. Backup and restore for PostgreSQL and Qdrant
38. Qdrant persistence in production profiles
39. Multi-replica production profile for critical stateless services
40. Post-deploy smoke verification
41. Rollback playbook and release metadata
42. Cost and concurrency controls for tenants and workloads

For each numbered area above, if it is already partially implemented, finish it rather than re-creating it.

---

## X-3 — Container Size And Runtime Efficiency

Treat image size and reproducibility as production concerns, not optional cleanup.

### Objectives

1. Reduce pull time and cold-start latency.
2. Shrink runtime CVE surface.
3. Make builds reproducible.
4. Remove unneeded compilers, package managers, caches, and broad dependency drift from final images.

### Required work

- Replace mutable tags such as `latest` or `main-latest` in production-facing values.
- Convert remaining single-stage Python images to multi-stage builds where practical.
- Use narrow build contexts and add `.dockerignore` files where missing.
- Pin downloaded binaries and external install sources.
- Audit heavyweight runtime images and define target budgets.
- Keep the web UI’s existing multi-stage pattern and improve surrounding images to match that standard.
- Where enterprise auth or other optional features inflate the default image, consider extras or profile-based installs if that can be done safely.

### Acceptance criteria

- Every production image has a reproducible build story.
- Final runtime images do not contain unnecessary build toolchains where avoidable.
- Build context and dependency drift are measurably reduced.

---

## Cross-Cutting Checklists

### UX State Matrix

For every major screen, verify:
- loading
- empty
- success
- validation error
- server error
- offline or degraded gateway
- permission denied

### Accessibility Checklist

Verify:
- keyboard access to every major action
- visible focus states
- no hover-only critical actions
- correct dialog focus trap behavior
- sufficient contrast in dark and light themes
- screen-reader labels for icon-only controls

### Browser And Device Matrix

Verify at minimum:
- Chrome / Edge
- Firefox
- Safari if applicable
- phone-sized layout
- tablet-sized layout
- narrow desktop layout

### API And Data Checklist

For backend changes, verify:
- auth via `Depends(verify_token)` where required
- namespace access enforcement
- indexes for new tables
- backward-compatible response handling where possible
- pagination for list endpoints
- migration impact

### Observability Checklist

Verify:
- logs are structured enough for debugging
- metrics exposure is consistent across services
- traces or OTLP propagation are coherent where already supported
- health/readiness reflect real dependency state

### Deployment Checklist

Before calling an area complete:
- build affected images
- push them
- update `deploy/values.dockerhub.local.yaml`
- `helm upgrade` the release
- wait for rollout
- validate the UI and key APIs

---

## Known Issues To Keep Current

### `[ISSUE-1]` Status Board Drift

The prompt must not mark an item fully done while its own subsection still lists open requirements.

### `[ISSUE-2]` Template Catalog Duplication

Templates exist both in the catalog file and in inline frontend definitions. Remove duplication or establish one authoritative source.

### `[ISSUE-3]` Policy Editor Incompleteness

Policy preview, assignment visibility, and A2A-specific controls remain open.

### `[ISSUE-4]` Template Wizard Auto-Show

Zero-agent onboarding still needs automatic template guidance.

### `[ISSUE-5]` Notification Completion Gap

Notifications exist in-app, but durable state, browser notifications, and deep-link behavior are incomplete.

### `[ISSUE-6]` Mobile Composer And Chat Parity

Mobile shell exists, but full parity for chat side panels and composer behavior is incomplete.

### `[ISSUE-7]` Export And Import Completeness

Export/import exists, but self-contained bundle semantics and shareability are incomplete.

### `[ISSUE-8]` Branding Wiring Gap

Brand config exists, but logo, favicon, and richer white-label support are not fully wired.

---

## Build And Deploy Pattern

For each change set:
1. Modify source files.
2. Run narrow relevant checks first, then broader checks if needed.
3. Build affected images: `podman build -t docker.io/yakdhane/<image>:<tag>`
4. Push images.
5. Update `deploy/values.dockerhub.local.yaml`.
6. Deploy with Helm.
7. Wait for rollout.
8. Perform smoke verification.

**Images in scope**: `api-gateway`, `operator`, `web-ui`, `agent-runtime`, `goose-runtime`, `codex-runtime`, `opencode-runtime`, and MCP sidecars.

---

## Definition Of Done For Any Item

Do not mark an item complete unless all of the following are true:

1. The implementation exists in code.
2. The primary UX path works end-to-end.
3. Loading, empty, error, and permission-denied states are acceptable.
4. The action is not misleading or dead-ended.
5. Relevant tests or validation checks pass.
6. Deployment impact is understood and, if required, exercised.
7. The status ledger and known-issues section are updated.

## PROMPT END
