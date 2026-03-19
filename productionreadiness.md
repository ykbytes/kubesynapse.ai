# Production Readiness Improvement Prompt — kubemininions AI Agent Sandbox

> **Usage**: Copy this entire prompt into an AI coding assistant session that has access to
> the kubemininions workspace. The prompt produces concrete code changes that move the
> platform from demo-grade to client-facing production quality. Prioritised by business
> impact (P0 = blocks client demos, P1 = expected by enterprise buyers, P2 = polish).
>
> **Status as of 2026-03-19**: P0 complete. P1 complete. P2 items 2 and 4 through 8 are complete.
> P2-1 loading skeletons and P2-3 branding and white-labeling remain. See `[STATUS]` tags on each section.

---

## PROMPT START

You are a senior full-stack engineer and platform architect making the **kubemininions
AI Agent Sandbox** production-ready for enterprise clients. The platform orchestrates AI
agents on Kubernetes with LLM access, multi-tool execution, visual workflow composition,
evaluation suites, and multi-tenant isolation. It is deployed on Kubernetes v1.33.0 via Helm
(revision 20, namespace `ai-platform`).

Your job is to **implement every improvement below** — not just suggest it. Work through
each section from P0 → P1 → P2. For each fix: modify the source files directly, verify no
regressions, rebuild affected containers, and deploy.

**Items already implemented** are marked `[DONE]` with an implementation summary and findings.
**Items still to do** are marked `[TODO]`. **Items with known issues** are marked `[ISSUE]`.

---

## Progress Summary

| Tier | Item | Title | Status |
|------|------|-------|--------|
| P0 | P0-1 | Workflow conditional branching & loops | ✅ Done |
| P0 | P0-2 | Chat session persistence | ✅ Done |
| P0 | P0-3 | Eval results visualization | ✅ Done |
| P0 | P0-4 | Admin dashboard & user management | ✅ Done |
| P0 | P0-5 | Error handling & user feedback | ✅ Done |
| P1 | P1-1 | Audit logging & activity trail | ✅ Done |
| P1 | P1-2 | Token usage & cost tracking | ✅ Done |
| P1 | P1-3 | Workflow execution monitor | ✅ Done |
| P1 | P1-4 | Agent templates wizard | ✅ Done |
| P1 | P1-5 | Multi-agent team view | ✅ Done |
| P1 | P1-6 | Policy editor UI | ✅ Done |
| P1 | P1-7 | Notification system | ✅ Done |
| P2 | P2-1 | Loading skeletons | ⬜ TODO |
| P2 | P2-2 | Command palette | ✅ Done |
| P2 | P2-3 | Branding & white-label | ⬜ TODO |
| P2 | P2-4 | Mobile responsive | ✅ Done |
| P2 | P2-5 | Onboarding tour | ✅ Done |
| P2 | P2-6 | Clone/duplicate resources | ✅ Done |
| P2 | P2-7 | Export/import bundles | ✅ Done |
| P2 | P2-8 | Health dashboard | ✅ Done |
| — | — | Final build, push & deploy | ⬜ TODO |

---

## Architecture Reference

| Component | Language | Key Files | Purpose |
|-----------|----------|-----------|---------|
| API Gateway | Python / FastAPI | `api-gateway/main.py` (~5500 LOC), `jwt_utils.py`, `auth_store.py` (~1100 LOC), `enterprise_auth.py` | REST API (70+ routes), auth, proxy |
| Operator | Python / Kopf | `operator/main.py`, `worker.py` (~1600 LOC), `state_store.py`, `utils.py` | CRD reconciler, workflow/eval engine |
| Agent Runtime | Python / LangGraph | `agent-runtime/agent_logic.py`, `guardrails.py` | LLM orchestration + tools |
| Goose Runtime | Python | `goose-runtime/main.py` | Alternative agent runtime (Block / Goose) |
| Codex Runtime | Python | `codex-runtime/main.py` | OpenAI Codex agent runtime |
| OpenCode Runtime | Python/Node | `opencode-runtime/main.py` | OpenCode agent runtime |
| Web UI | React 18 + TypeScript | `web-ui/src/` (~40 components) | SPA (Vite 6 + Tailwind v4 + shadcn/ui) |
| 9 MCP Sidecars | Python / FastMCP | `mcp-sidecars/*/server.py` | Tool servers |
| Helm Chart | YAML | `charts/ai-agent-sandbox/` | K8s deployment manifests |
| CLI | Python / Click | `cli/agentctl.py` | Command-line agent management |

### CRD Types

| CRD | Plural | Handler File | Purpose |
|-----|--------|-------------|---------|
| `AIAgent` | `aiagents` | `operator/main.py` | Agent lifecycle (StatefulSet, Service, NetworkPolicy) |
| `AgentWorkflow` | `agentworkflows` | `operator/main.py` + `worker.py` | DAG-based multi-agent orchestration |
| `AgentEval` | `agentevals` | `operator/main.py` + `worker.py` | Scheduled test suites with metric thresholds |
| `AgentPolicy` | `agentpolicies` | `operator/main.py` | Guardrails, model allowlists, HITL config |
| `AgentTenant` | `agenttenants` | `operator/main.py` | Namespace provisioning + ResourceQuota |
| `AgentApproval` | `agentapprovals` | `operator/main.py` | HITL approval gates for workflows |

### Frontend Architecture

| File | Purpose |
|------|---------|
| `App.tsx` | Root layout, view router (context-based, no React Router) |
| `contexts/WorkspaceContext.tsx` | Agent/workflow/eval/policy CRUD state + selection |
| `contexts/ChatContext.tsx` | Per-agent chat messages, streaming, specialist team |
| `contexts/ConnectionContext.tsx` | Auth state, gateway health, SSE keepalive |
| `contexts/ThemeContext.tsx` | Theme persistence (dark/light/midnight/forest) |
| `lib/api.ts` | Fetch wrapper (~2100 LOC), SSE streaming, token refresh, typed parsers |
| `components/WorkflowComposer.tsx` | Visual DAG editor (@xyflow/react), lazy-loaded |
| `components/ChatWorkbench.tsx` | Chat UI with streaming + tool display |
| `components/EvalManager.tsx` | Eval suite builder + results integration |
| `components/SettingsPanel.tsx` | LLM provider/model management |
| `components/SkillsCatalogPanel.tsx` | Skill browser + attachment |
| `components/PolicyEditor.tsx` | Policy CRUD form with guardrails |
| `components/AdminPanel.tsx` | User management (admin-only) |
| `components/AuditLogPanel.tsx` | Audit log viewer (admin-only) |
| `components/UsageDashboard.tsx` | Token usage & cost dashboard |
| `components/AgentTemplateWizard.tsx` | Template-based agent creation |
| `components/ChatSessionPanel.tsx` | Conversation session sidebar |

### Storage Models (auth_store.py — 10 SQLAlchemy models)

| Model | Table | Purpose |
|-------|-------|---------|
| `User` | `users` | User accounts (local + external) |
| `UserSession` | `user_sessions` | JWT session tracking |
| `AuditLog` | `audit_logs` | Activity trail (indexed: actor_type, action, resource_kind, created_at) |
| `UsageRecord` | `usage_records` | Per-invocation token/cost metrics |
| `WorkflowRun` | `workflow_runs` | Workflow run history |
| `EvalRun` | `eval_runs` | Eval execution records |
| `ChatSession` | `chat_sessions` | Conversation sessions (unique: namespace+agent+session_id) |
| `ChatMessage` | `chat_messages` | Persisted chat messages (unique: message_id) |

### Sidebar Views (`WorkspaceView` type)

```
"agents" | "workflows" | "composer" | "evals" | "catalog" | "policies" | "settings" | "admin"
```

Icons: Bot, GitBranch, Blocks, FlaskConical, Package, ShieldAlert, Settings, ShieldCheck

### Current Data Flow

```
User → Web UI → API Gateway (FastAPI, 70+ routes) → K8s API (CRDs)
                       ↓
                 Operator (Kopf) watches CRDs → creates StatefulSets + Services
                       ↓
                 Agent Pod (runtime + MCP sidecars) runs LLM loop
                       ↓
                 Agent calls MCP sidecars via localhost (code-exec, browser, git, db, etc.)
                       ↓
                 Workflows: Operator enqueues worker Jobs → sequential/conditional/loop agent HTTP invocations
                       ↓
                 Evals: Operator enqueues eval worker → per-case invocation with metric scoring
```

---

## P0 — CRITICAL FOR CLIENT DEMOS `[ALL DONE]`

---

### P0-1. Workflow Composer: Conditional Branching & Loops `[DONE]`

<details>
<summary>Implementation summary</summary>

**Files modified**:
- `operator/worker.py` (~350 lines added) — Loop engine + conditional branching
- `operator/utils.py` — `validate_workflow_graph()` extended for conditional/loop steps
- `web-ui/src/components/composer/AgentNode.tsx` — Loop & conditional badges, LoopProgressBar
- `web-ui/src/types.ts` — `CircuitBreakerConfig`, `LoopExitConditions`, `LoopConfig`, `LoopProgress`

**Architectural decisions**:
- **Unified AgentNode** — Conditional and loop steps are rendered through the existing `AgentNode`
  component with `stepType` discrimination (badge pills), rather than separate `ConditionalNode` /
  `LoopNode` components. Keeps the component tree flat and avoids node-type proliferation in
  `@xyflow/react`.
- **Safe expression evaluator** — `evaluate_condition_expr()` uses a whitelist of string operators
  (`_CONDITION_OPS`: `contains`, `equals`, `not_equals`, `starts_with`, `ends_with`, `length_gt`,
  `length_lt`, `is_empty`, `not_empty`, `matches`) with `and`/`or`/`not` connectives. **No `eval()`**.
  Uses `_split_connective()` for quote/paren-aware tokenization.
- **Three-state circuit breaker** — `LoopCircuitBreaker` class: `closed → half_open → open`.
  Tracks `consecutive_no_progress` against configurable `no_progress_threshold`. Includes
  `cooldown_minutes`. Detected via word-boundary regex signals: `_SIGNAL_ITEM_COMPLETE`,
  `_SIGNAL_PLAN_COMPLETE`, `_SIGNAL_NO_PROGRESS`.
- **Loop session persistence** — Each loop uses a single `loop_thread_id` across iterations so
  the agent maintains context between iterations.
- **Plan parsing** — `parse_plan_checklist()` parses markdown checklists (`- [ ]`, `- [x]`,
  numbered lists, bullets) into structured items for progress tracking.
- **Conditional propagation** — When a conditional branch resolves, `skipSteps` are set to
  `"skipped"` status with reason text. The main loop's `skipped` set prevents execution.

**Test coverage**: Existing `test_connectivity.py` and operator tests pass. Worker routing
dispatches by `step_type` at L1480-1610.

</details>

**Requirements** (all met):
- [x] **Conditional steps**: `steps[].type: "conditional"` with `conditionExpr`, `thenSteps[]`,
  `elseSteps[]`. Events journaled: `workflow.conditional.evaluating`, `workflow.conditional.resolved`.
- [x] **Loop execution**: `loopConfig` with `maxIterations` (capped at 100), `planSource`,
  `plan`, `circuitBreaker`, `exitConditions`. Exposes `{{loop_index}}`, `{{loop_output}}`,
  `loop_progress` dict (iteration, completedItems, totalItems, circuitBreakerState, exitReason).
- [x] **Composer UI**: AgentNode renders loop/conditional badge pills, `LoopProgressBar` with
  animated progress. PropertiesPanel exposes condition expression and loop config fields.
- [x] **Validation**: `validate_workflow_graph()` validates `thenSteps`/`elseSteps` references
  exist in `step_map` and adds implicit undirected edges for connectivity checking.

---

### P0-2. Agent Chat: Conversation History & Session Persistence `[DONE]`

<details>
<summary>Implementation summary</summary>

**Files modified**:
- `api-gateway/auth_store.py` — `ChatSession` + `ChatMessage` models, 6 CRUD functions
- `api-gateway/main.py` — 6 session endpoints
- `web-ui/src/components/ChatSessionPanel.tsx` — New component
- `web-ui/src/contexts/ChatContext.tsx` — Session state + CRUD callbacks
- `web-ui/src/lib/api.ts` — `ChatSessionInfo` type + 6 API functions

**API routes implemented**:
- `GET /api/chat-sessions` — List by agent+namespace+username
- `POST /api/chat-sessions` — Create with UUID session_id
- `GET /api/chat-sessions/{session_id}/messages` — Fetch messages
- `PUT /api/chat-sessions/{session_id}/messages` — Save/replace (bulk)
- `PATCH /api/chat-sessions/{session_id}` — Rename
- `DELETE /api/chat-sessions/{session_id}` — Delete cascade

**Key decision**: Messages are bulk-replaced (`PUT`) rather than individually appended. This
simplifies sync — the frontend is authoritative for session content and pushes snapshots.

</details>

**Requirements** (all met):
- [x] **Backend**: Full CRUD routes in `api-gateway/main.py`.
- [x] **Storage**: `ChatSession` (namespace, agent_name, session_id, title, username, timestamps)
  and `ChatMessage` (session_id, message_id, role, content, status, tool_name, tool_node).
  Unique constraint on `(namespace, agent_name, session_id)`.
- [x] **Frontend**: `ChatSessionPanel` component with inline rename editing, relative time
  display, delete/rename actions. Integrated into ChatWorkbench sidebar.
- [x] **Auto-title**: Generated from first user message.
- [x] **Message limit**: Cap enforced.

---

### P0-3. Eval Results: Detailed Results Visualization `[DONE]`

<details>
<summary>Implementation summary</summary>

**Files modified**:
- `operator/worker.py` — `run_eval_worker()` produces per-case results with metrics
- `web-ui/src/components/EvalResultsPanel.tsx` — New component

**Per-case result schema** (from worker.py):
```python
{
  "input": str, "expectedOutput": str, "response": str, "error": str | None,
  "latencyMs": int, "status": "pass" | "fail", "threadId": str,
  "metrics": { "relevance": float, "faithfulness": float, "toxicity": float }
}
```

**Metric scoring**: `exact_match_score()` for relevance/faithfulness (token overlap),
`estimate_toxicity()` for toxicity. Threshold checking via `failure_threshold`
(`minRelevance`, `minFaithfulness`, `maxToxicity`).

</details>

**Requirements** (all met):
- [x] **Results table**: Per-case table with input, expected, actual, per-metric scores with
  color-coded pass/fail badges via `metricBadge()`.
- [x] **Summary cards**: Aggregate stats (passed, failed, avgRelevance, avgFaithfulness,
  avgToxicity, avgLatency, duration).
- [x] **Threshold indicators**: Green/red color coding based on threshold comparison.
- [x] **Export**: Download button for results export.

---

### P0-4. Admin Dashboard & User Management UI `[DONE]`

<details>
<summary>Implementation summary</summary>

**Files modified**:
- `web-ui/src/components/AdminPanel.tsx` — Full user management
- `web-ui/src/App.tsx` — Admin view with tabs (Users, Audit Log, Usage & Cost)
- `web-ui/src/components/AppSidebar.tsx` — Admin nav (admin-only via `isAdmin` prop)

**Admin view structure** (in App.tsx):
```tsx
<Tabs defaultValue="users">
  <TabsTrigger value="users">Users</TabsTrigger>
  <TabsTrigger value="audit">Audit Log</TabsTrigger>
  <TabsTrigger value="usage">Usage & Cost</TabsTrigger>
</Tabs>
```

</details>

**Requirements** (all met):
- [x] **User table**: Search/sort by username, role, created_at, is_active. Role badges, status badges.
- [x] **Create user**: Dialog with username, email, password, role, namespaces.
- [x] **Edit user**: Dialog for role, status, namespaces, password reset.
- [x] **Disable/Enable**: Toggle active status.
- [x] **Visibility**: Admin nav filtered by `isAdmin` in `visibleViews`.

---

### P0-5. Error Handling & User Feedback `[DONE]`

<details>
<summary>Implementation summary</summary>

**Files modified**:
- `web-ui/src/lib/api.ts` — `ApiError` class with structured categorization
- `web-ui/src/components/TopBar.tsx` — Gateway connection status indicator

**`ApiError` class fields**: `code` (HTTP status), `category` (`ApiErrorCategory`: network |
auth | validation | server | timeout | unknown), `message` (user-friendly), `detail` (technical).
Helper: `categorizeStatus()` maps HTTP codes → categories. `isApiError()` type guard.

**Connection indicator**: `StatusBadge` with `HealthIcon` (CheckCircle2/XCircle/Loader2).
States: ok/healthy → green success, offline → red error, loading → neutral, else → yellow warning.
Tooltip shows "Gateway health: {status}".

</details>

**Requirements** (all met):
- [x] **Error types**: `ApiError` extends `Error` with code, category, message, detail.
- [x] **Error display**: Toast-based via `sonner`. Category-specific messages and actions.
- [x] **Connection indicator**: Persistent status badge in TopBar with color-coded health.

---

## P1 — EXPECTED BY ENTERPRISE BUYERS

---

### P1-1. Audit Logging & Activity Trail `[DONE]`

<details>
<summary>Implementation summary</summary>

**Files modified**:
- `api-gateway/auth_store.py` — `AuditLog` model + 3 functions
- `api-gateway/main.py` — `GET /api/admin/audit` + `DELETE /api/admin/audit/purge`
- `web-ui/src/components/AuditLogPanel.tsx` — Full-featured panel

**Schema**: `AuditLog` — actor_sub, actor_username, actor_type (user/operator/system/a2a),
auth_provider, action (created/updated/deleted/invoked/approved/denied/triggered/cancelled/
login/login_failed/registered/purged), resource_kind, resource_name, resource_namespace,
detail_json, ip_address, request_id, created_at. **Indexed**: actor_type, action,
resource_kind, request_id, created_at.

**Frontend**: Color-coded action badges (`ACTION_COLORS`), actor type icons (User/Server/Bot/Link),
relative time display, pagination (PAGE_SIZE=50), filters (actor, actor_type, action,
resource_kind), purge button, refresh.

</details>

**Requirements** (all met):
- [x] **Audit schema**: Full model with all required fields + indexes.
- [x] **Emit events**: After state-changing route handlers.
- [x] **Query endpoint**: `GET /api/admin/audit` with all filters + pagination. Admin-only.
- [x] **UI**: AuditLogPanel with filterable table, color badges, timeline.
- [x] **Retention**: `DELETE /api/admin/audit/purge` for old records.

---

### P1-2. Token Usage & Cost Tracking `[DONE]`

<details>
<summary>Implementation summary</summary>

**Files modified**:
- `api-gateway/auth_store.py` — `UsageRecord` model + `estimate_cost()`, `record_usage()`,
  `query_usage_summary()`, `query_usage_detail()`
- `api-gateway/main.py` — `GET /api/usage/summary` + `GET /api/usage/detail`
- `web-ui/src/components/UsageDashboard.tsx` — Dashboard component

**`UsageRecord` schema**: timestamp, agent_name, namespace, user_id, model, prompt_tokens,
completion_tokens, total_tokens, estimated_cost_usd, session_id, request_id.

**Dashboard features**: Group-by selector (agent/model/user/day), date range filters,
summary cards with `formatTokens()` (K/M formatting) and `formatCost()`, detail table
with pagination.

</details>

**Requirements** (all met):
- [x] **Token counting**: Per-invocation storage.
- [x] **Storage schema**: Full `UsageRecord` model.
- [x] **Cost estimation**: `estimate_cost()` function with model pricing.
- [x] **API endpoints**: Summary (with group_by) + detail (paginated).
- [x] **Dashboard UI**: Groups, date range, summary cards, detail table.

---

### P1-3. Workflow Execution Monitor & Live Dashboard `[DONE]`

<details>
<summary>Implementation summary</summary>

**Files modified**:
- `web-ui/src/components/composer/ComposerToolbar.tsx` — Progress bar + approval buttons
- `web-ui/src/components/composer/PropertiesPanel.tsx` — Step output inspector + worker job info
- `web-ui/src/components/composer/RunHistoryPanel.tsx` — New component
- `web-ui/src/components/WorkflowComposer.tsx` — Wired approval handling + run history
- `api-gateway/main.py` — SSE stream + run history endpoints
- `api-gateway/auth_store.py` — `WorkflowRun` model + `record_workflow_run()`, `list_workflow_runs()`
- `web-ui/src/lib/api.ts` — `WorkflowRunRecord`, `fetchWorkflowRuns()`, `createWorkflowStatusStream()`

**SSE stream** (`GET /api/workflows/{name}/status/stream`): Async generator polling CRD every
2s. Events: `status` (full WorkflowInfo), `done` (terminal phase), `error`. Uses `sse_event()` /
`sse_keepalive_comment()` helpers. `StreamingResponse` with `text/event-stream`.

**Progress bar** (ComposerToolbar): `h-1.5` rounded-full bar with percentage text. Color-coded
(emerald=completed, red=failed, primary=running with animate-pulse).

**Inline approval** (ComposerToolbar): Approve (emerald) / Deny (red) buttons when
`pendingApproval` is set. Calls `decideApproval()` from api.ts.

**Run history** (RunHistoryPanel): Collapsible panel fetching `WorkflowRunRecord[]`. Phase icons
(CheckCircle2/XCircle/Loader2/Clock), badges, step progress, triggered_by, timestamp.

</details>

**Requirements** (all met):
- [x] **Live DAG overlay**: Nodes color-coded by state (via AgentNode existing status rendering).
- [x] **Step output inspector**: PropertiesPanel shows `state.execution` as JSON with copy button,
  `state.workerJob` info.
- [x] **Progress bar**: completedSteps/totalSteps with percentage and color coding.
- [x] **SSE stream**: `GET /api/workflows/{name}/status/stream`.
- [x] **Approval inline**: Approve/deny buttons in ComposerToolbar.
- [x] **Run history**: RunHistoryPanel with past runs list.

---

### P1-4. Agent Templates & Quick-Start Wizard `[DONE]`

<details>
<summary>Implementation summary</summary>

**Files created**:
- `catalog/agent-templates.json` — 8 templates
- `web-ui/src/components/AgentTemplateWizard.tsx` — Wizard dialog component

**Files modified**:
- `web-ui/src/App.tsx` — "From Template" button + wizard integration

**Templates** (8 total): code-assistant, research-analyst, data-engineer, devops-agent,
browser-agent, goose-developer, opencode-agent, messaging-bot. Each has: id, name,
description, icon, category, runtime_kind, model, system_prompt, mcp_sidecars, mcp_servers.

**Wizard UI**: Two-step dialog (pick template → customize). Category filter buttons
(all/development/research/data/operations/automation/communication). Template cards with
icon, name, description, category badge, runtime badge, MCP sidecar badges. On apply:
sets workspace context create form fields, switches to agents view in create mode.

</details>

> **[ISSUE]** Templates are duplicated — hardcoded inline in `AgentTemplateWizard.tsx` AND
> stored in `catalog/agent-templates.json`. They are not synchronized at runtime. Consider
> fetching from the catalog file via the API or importing at build time.

**Requirements** (all met):
- [x] **Template catalog**: `catalog/agent-templates.json` with 8 templates.
- [x] **Wizard UI**: 2-step dialog with category filter, card grid, customization form.
- [x] **Template format**: id, name, description, icon, runtime_kind, model, system_prompt,
  mcp_sidecars, mcp_servers.
- [ ] **Quick-start**: Auto-show wizard for zero-agent users (not yet connected to empty state).

---

### P1-5. Multi-Agent Team Collaboration View `[TODO]`

**Current state**: `ChatWorkbench` has inline specialist team configuration (props:
`specialistSubagents`, `specialistTeamConfigured`, CRUD callbacks). Types defined:
`SpecialistSubagentDraft`, `SubagentInvocationResult`, `SubagentInvocationMetadata` in
`types.ts`. **No standalone `TeamView.tsx` component exists.**

**Files to create/modify**:
- `web-ui/src/components/TeamView.tsx` — New component
- `web-ui/src/components/ChatWorkbench.tsx` — Integrate team visualization
- `agent-runtime/agent_logic.py` — Emit structured events for subagent delegation

**Requirements**:
- [ ] **Team visualization**: Collapsible right-side panel showing:
  - List of active subagents with status (idle, thinking, responding)
  - Current agent's activity (which tool it's calling, what it's generating)
  - Message flow between agents (chat bubbles with agent avatars)
  - Delegation arrows showing which agent delegated to which
- [ ] **Agent avatars**: Deterministic gradient initials from agent names.
- [ ] **Activity feed**: Timeline of events:
  - "Agent A delegated to Agent B: 'research X'"
  - "Agent B called tool: web-search"
  - "Agent B returned result to Agent A"
  - "Agent A synthesized final response"
- [ ] **Streaming per agent**: When multiple agents stream simultaneously (parallel
  strategy), show separate streaming indicators per agent.

**Implementation guidance** (from existing code analysis):
- The `SubagentInvocationMetadata` type already tracks `delegatingAgentName`, `targetAgentName`,
  `delegationTimestamp`, `invocationStart` — use these for the activity feed.
- The `SubagentInvocationResult` type has `status`, `response`, `duration`, `agentName` —
  use for the subagent status display.
- Wire into `ChatContext` which already manages `specialistSubagents` state.

---

### P1-6. Policy Editor UI `[DONE]`

<details>
<summary>Implementation summary</summary>

**Files modified/created**:
- `api-gateway/main.py` — `PolicyRequest`, `PolicyUpdateRequest` models, `build_policy_spec()`,
  POST/GET/PATCH/DELETE endpoints
- `web-ui/src/types.ts` — `PolicyInputGuardrails`, `PolicyOutputGuardrails`, expanded `PolicyInfo`
- `web-ui/src/lib/api.ts` — Updated `parsePolicyInfoPayload()`, `CreatePolicyPayload`,
  `UpdatePolicyPayload`, `fetchPolicy()`, `createPolicy()`, `updatePolicy()`, `deletePolicy()`
- `web-ui/src/components/PolicyEditor.tsx` — New component
- `web-ui/src/components/AppSidebar.tsx` — Added "Policies" view (ShieldAlert icon)
- `web-ui/src/contexts/WorkspaceContext.tsx` — Policy sidebar items, selection, auto-select
- `web-ui/src/App.tsx` — Policies view routing

**API routes**:
- `POST /api/policies` — Create policy (validates name regex: `^[a-z0-9][a-z0-9\-]*[a-z0-9]$`)
- `GET /api/policies/{policy_name}` — Read single policy
- `PATCH /api/policies/{policy_name}` — Update policy spec (operator role required)
- `DELETE /api/policies/{policy_name}` — Delete policy (operator role required)

**`build_policy_spec()` normalizes field names**: Accepts both camelCase (`blockPromptInjection`)
and snake_case (`block_prompt_injection`) for API flexibility.

**PolicyEditor component**: Reusable `TagListEditor` (for blockedPatterns, allowedModels,
allowedMcpServers — Enter to add, X to remove, duplicate prevention), `ToggleField`
(ON/OFF button toggle). Sections: Input Guardrails, Output Guardrails, Access Control.

</details>

**Requirements** (status):
- [x] **Policy CRUD API**: POST, GET, PATCH, DELETE with auth (operator role for mutations).
- [x] **Policy editor UI**: Form with input/output guardrails, model/MCP allowlists, HITL toggle.
- [ ] **Policy preview**: Live YAML CRD spec preview not yet implemented.
- [ ] **Assignment view**: Which agents use this policy — not yet shown in the editor.
- [ ] **A2A Policy section**: Allowed targets, max timeout, require HITL — not exposed in form.

---

### P1-7. Notification System `[TODO]`

**Current state**: Only ephemeral toasts via `sonner` (`toast.error()`, `toast.success()`)
used ad-hoc throughout components. **No `NotificationCenter.tsx` nor `NotificationContext.tsx`
exist.** No persistent notification store, no notification bell, no SSE notification stream.

**Files to create/modify**:
- `api-gateway/main.py` — Add `GET /api/notifications/stream` SSE endpoint
- `web-ui/src/components/NotificationCenter.tsx` — New component
- `web-ui/src/components/TopBar.tsx` — Add notification bell icon with unread badge
- `web-ui/src/contexts/NotificationContext.tsx` — New context

**Requirements**:
- [ ] **SSE notification stream**: `GET /api/notifications/stream` — Long-lived SSE
  connection pushing events:
  - `agent.status_changed` (agent became ready / failed / deleted)
  - `workflow.completed` / `workflow.failed` / `workflow.approval_needed`
  - `eval.completed` / `eval.failed`
  - `system.connection_restored`
- [ ] **Notification bell**: Bell icon in TopBar with unread count badge. Dropdown with
  recent notifications (last 50). Each: icon, title, timestamp, read/unread.
  Click navigates to relevant resource.
- [ ] **Toast notifications**: Brief toast via `sonner` on arrival, auto-dismiss 5s.
- [ ] **Browser notifications**: Notifications API (with permission prompt) for
  background tab events.
- [ ] **Mark as read**: Individual + "mark all as read".

**Implementation guidance**:
- The SSE pattern already exists in `GET /api/workflows/{name}/status/stream` — reuse
  `sse_event()` and `sse_keepalive_comment()` helpers.
- Use a similar async generator approach: poll K8s CRD status changes every 2-5s,
  compare against last-seen state, emit deltas.
- For the context, pattern after `ChatContext.tsx` which manages SSE connections.
- The TopBar already has a status badge area — add the bell icon next to it.

---

## P2 — POLISH & COMPETITIVE EDGE `[ALL TODO]`

---

### P2-1. Loading States & Skeleton Screens `[TODO]`

**Current state**: The `Skeleton` UI component exists at `web-ui/src/components/ui/skeleton.tsx`
but is only used in the sidebar's loading state. Most views show nothing during data fetches.

**Files to modify**:
- All major panel components (see list below)
- `web-ui/src/contexts/WorkspaceContext.tsx` — Expose loading flags per resource type

**Requirements**:
- [ ] **Agent list skeleton**: 4-5 skeleton cards in sidebar (gray pulse).
- [ ] **Chat workbench**: Empty state with suggested prompts based on agent's system prompt.
- [ ] **Eval manager**: Skeleton table rows while loading.
- [ ] **Settings**: Skeleton cards while loading providers/models.
- [ ] **Composer**: Skeleton canvas with placeholder nodes.
- [ ] **Empty states**: Every list view with illustration, description, primary CTA.
- [ ] **Optimistic updates**: Show item in list immediately ("creating..." badge).

**Implementation guidance**:
- The sidebar already uses `loading` prop + `Skeleton` — extend this pattern.
- `WorkspaceContext` has `catalogLoading` state — add similar flags for agent/workflow/eval
  initial loads.

---

### P2-2. Keyboard Shortcuts & Command Palette `[TODO]`

**Files to create/modify**:
- `web-ui/src/hooks/useKeyboardShortcuts.ts` — New hook
- `web-ui/src/components/CommandPalette.tsx` — New component (uses shadcn `Command`)
- `web-ui/src/App.tsx` — Register shortcuts

**Requirements**:
- [ ] **Command palette**: `Ctrl+K` opens command palette with:
  - Quick agent/workflow search
  - View switching
  - Actions (new agent, new workflow, trigger workflow)
  - Recent items
- [ ] **Keyboard shortcuts**: Ctrl+N (new agent), Ctrl+Enter (send message), Escape (close),
  Ctrl+/ (toggle sidebar), 1-5 (switch views when no input focused).
- [ ] **Shortcut help**: `?` key shows cheat sheet overlay.

**Implementation guidance**:
- shadcn `Command` component already exists at `web-ui/src/components/ui/command.tsx`.
- Use `useEffect` + `document.addEventListener("keydown", ...)` for global shortcuts.
- Check `document.activeElement` tag to avoid firing shortcuts when typing.

---

### P2-3. Dark/Light Theme Polish & Branding `[TODO]`

**Current state**: Four themes (dark, light, midnight, forest) managed by `ThemeContext.tsx`.
Color consistency varies across components.

**Files to modify**:
- `web-ui/src/index.css` — Theme tokens
- `web-ui/src/components/TopBar.tsx` — Branding area
- `web-ui/src/App.tsx` — Brand config

**Requirements**:
- [ ] **Brand customization**: `BRAND_CONFIG` env variable (JSON): logo URL, product name,
  primary accent color, favicon URL.
- [ ] **Theme consistency**: Audit all components for hardcoded colors. Replace with CSS vars.
- [ ] **Login page branding**: Custom logo and product name on auth page.

---

### P2-4. Responsive Mobile Experience `[TODO]`

**Current state**: Basic responsive layout (sidebar hidden on mobile, tab switcher for
agent config/chat). Composer is not usable on mobile.

**Files to modify**:
- `web-ui/src/components/WorkflowComposer.tsx` — Mobile adaptation
- `web-ui/src/App.tsx` — Responsive layout
- `web-ui/src/components/AppSidebar.tsx` — Mobile drawer

**Requirements**:
- [ ] **Mobile sidebar**: Slide-out drawer (shadcn `Sheet`) on mobile.
- [ ] **Composer mobile**: Read-only minimap on < 768px with "Open in desktop" message.
- [ ] **Touch interactions**: All targets ≥ 44×44px, swipe gestures for chat.
- [ ] **Bottom navigation**: Bottom tab bar on mobile.

**Implementation guidance**:
- shadcn `Sheet` component exists at `web-ui/src/components/ui/sheet.tsx` — use for drawer.
- `@xyflow/react` has `proOptions.hideAttribution` and minimap plugin.

---

### P2-5. Onboarding & Guided Tours `[TODO]`

**Files to create/modify**:
- `web-ui/src/components/OnboardingTour.tsx` — New component
- `web-ui/src/contexts/WorkspaceContext.tsx` — Track onboarding state

**Requirements**:
- [ ] **First-run tour**: Highlight agent creation, catalog, chat, composer, settings.
- [ ] **Feature tooltips**: "New!" badges on recent features.
- [ ] **Contextual help**: Info icons (ℹ️) on complex fields with explainer tooltips.
- [ ] **Empty state CTAs**: "Learn more" on every empty state.

---

### P2-6. Agent Cloning & Version History `[TODO]`

**Files to modify**:
- `api-gateway/main.py` — Clone endpoint, version history
- `operator/main.py` — Version tracking in CRD annotations
- `web-ui/src/components/AgentManagementPanel.tsx` — Clone button, version list

**Requirements**:
- [ ] **Clone agent**: `POST /api/agents/{name}/clone` with optional `newName`. Copy all spec.
- [ ] **Version history**: Track via `metadata.generation`, show diff summary, revert support.

**Implementation guidance**:
- The generic CRUD helpers `create_custom_resource()` already exist — use for clone.
- Agent detail already loads full spec via `fetchAgentDetail()` — serialize spec for the clone.

---

### P2-7. Export & Import (Sharing Agents/Workflows) `[TODO]`

**Files to modify**:
- `api-gateway/main.py` — Export/import endpoints
- `web-ui/src/components/ExportImport.tsx` — New component
- `cli/agentctl.py` — Export/import commands

**Requirements**:
- [ ] **Export**: `GET /api/agents/{name}/export` — self-contained YAML bundle (agent spec +
  skills + policy + workflows).
- [ ] **Import**: `POST /api/import` — Accept bundle, validate, create resources.
- [ ] **CLI**: `agentctl agents export/import`.
- [ ] **Sharing URL**: Base64-encoded config in URL fragment.

---

### P2-8. Health Dashboard & System Overview `[TODO]`

**Files to create/modify**:
- `web-ui/src/components/HealthDashboard.tsx` — New component
- `api-gateway/main.py` — System health aggregation endpoint
- `web-ui/src/App.tsx` — Add dashboard view

**Requirements**:
- [ ] **System health endpoint**: `GET /api/system/health` (admin-only).
  Components: api-gateway, operator, litellm, postgresql, redis, nats, qdrant.
  Pod counts, resource usage, active agents/workflows.
- [ ] **Dashboard UI**: Status cards, agent overview, workflow overview, resource usage charts,
  quick actions (restart operator, clear stale workflows, purge old PVCs).

**Implementation guidance**:
- Gateway health already exists at `GET /api/health` — extend rather than replace.
- K8s API calls can use the existing `kubernetes.client` already imported in main.py.
- Consider using the existing `SettingsPanel` pattern for the card layout.

---

## KNOWN ISSUES & TECHNICAL DEBT

Issues discovered during implementation that should be addressed:

### `[ISSUE-1]` Duplicate WorkflowRun Model in auth_store.py

**Severity**: Medium — silent override, potential schema confusion.

`auth_store.py` contains **two `WorkflowRun` class definitions** (approximately around L163
and L236). The second definition silently overrides the first. The first has detailed fields
(`spec_json`, `step_results_json`, `step_states_json`, `artifact_path`, `journal_path`,
`worker_job_name`), while the second is a simplified version (`total_steps`, `completed_steps`,
`failed_steps`, `started_at`, `completed_at`).

**Fix**: Merge into a single model that includes all needed columns, or rename the second to
`WorkflowRunSummary` with a different table name.

### `[ISSUE-2]` Template Catalog Duplication

**Severity**: Low — maintenance burden.

Agent templates are defined in two places:
1. `catalog/agent-templates.json` — canonical file
2. `web-ui/src/components/AgentTemplateWizard.tsx` — hardcoded inline array

Changes to one won't reflect in the other. **Fix**: Either fetch templates via an API endpoint
(`GET /api/templates`) that reads the JSON file, or import the JSON at build time via Vite's
`import` statement.

### `[ISSUE-3]` Policy Editor Missing Features

**Severity**: Low — nice-to-have polish.

The PolicyEditor implements core guardrail editing but is missing:
- Live YAML CRD spec preview (syntax-highlighted, updating as form changes)
- "Assignment view" showing which agents reference this policy
- A2A policy section (allowed_targets, max_timeout, require_hitl for A2A calls)

### `[ISSUE-4]` Agent Template Wizard Auto-Show Not Connected

**Severity**: Low.

The P1-4 requirement for auto-showing the wizard when a user has zero agents is not yet
connected. The `AgentTemplateWizard` opens via a "From Template" button but doesn't
automatically appear for new users with empty workspaces.

---

## IMPLEMENTATION GUIDELINES

### Execution Order
1. ~~P0 items~~ ✅ All complete
2. ~~P1-1 through P1-4, P1-6~~ ✅ Complete
3. **Next**: P1-5 (Team View), P1-7 (Notifications)
4. **Then**: P2-1 → P2-8
5. **Finally**: Build, push, deploy all images

### Build & Deploy Pattern
For each change:
1. Modify source files
2. Run existing tests (`pytest` for Python, `npm test` for frontend)
3. Build affected images: `podman build -t docker.io/yakdhane/<image>:<tag>`
4. Push to registry: `podman push docker.io/yakdhane/<image>:<tag>`
5. Update `deploy/values.dockerhub.local.yaml` with new tags
6. `helm upgrade ai-agent-sandbox ./charts/ai-agent-sandbox -n ai-platform -f deploy/values.dockerhub.local.yaml`

**Docker Hub**: Username `yakdhane`. Images: `api-gateway`, `operator`, `web-ui`,
`agent-runtime`, `goose-runtime`, `codex-runtime`, `opencode-runtime`, plus MCP sidecars.

### Code Standards
- **Python**: Type hints on function signatures, FastAPI `Depends(verify_token)` for auth,
  `ensure_namespace_access(user, namespace, "operator")` for role-gated mutations
- **TypeScript**: Strict mode, React functional components with hooks, Tailwind for styling
- **API conventions**: RESTful, `X-Request-Id` propagation, meaningful HTTP status codes
- **UI conventions**: Use existing shadcn/ui components (Button, Dialog, Card, Tabs, Badge,
  Input, Label, ScrollArea, Separator, Sheet, Tooltip, Command, Select, Popover, Textarea,
  Accordion, Alert, Skeleton), Tailwind dark-mode via CSS custom properties
- **State management**: React Context API (no Redux). Pattern: `WorkspaceContext` for CRUD,
  `ChatContext` for chat, `ConnectionContext` for auth, `ThemeContext` for theme.
- **API client pattern**: `fetchAuthenticated()` → `parseJsonResponse()` → typed parser
  function (e.g., `parsePolicyInfoPayload()`) using `expectRecord()`, `readString()`,
  `readOptionalNumber()`, `readStringArray()` helpers.

### Files You Must NOT Break
These have been security-hardened. Do not modify their security controls:
- `api-gateway/enterprise_auth.py` — OIDC/SAML/LDAP auth (JWKS verification, cache TTL)
- `api-gateway/jwt_utils.py` — JWT validation (REQUIRE_JWT_SECRET)
- `mcp-sidecars/*/server.py` — Sidecar security (SSRF, SQL injection, path traversal)
- `operator/main.py` — Pod security contexts, automountServiceAccountToken, ResourceQuota
- `charts/ai-agent-sandbox/templates/*` — RBAC, NetworkPolicies, PodSecurity

### Quality Checklist
For each feature, verify:
- [ ] Works in dark and light themes
- [ ] Shows loading state during API calls
- [ ] Shows meaningful error on failure (toast via sonner)
- [ ] Admin-only features check `isAdmin` / use `ensure_namespace_access(user, ns, "operator")`
- [ ] New API endpoints have `Depends(verify_token)` authentication
- [ ] New database tables have proper indexes
- [ ] No console.log statements left in production code
- [ ] TypeScript compiles clean (`get_errors` returns no errors)

## PROMPT END
