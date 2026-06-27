# Optimizer Candidate Trace Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist and present a clear, complete observable execution trace for every optimizer-produced candidate.

**Architecture:** Normalize optimizer SSE activity in the web client, submit it with candidate generation, sanitize and persist it as an optional JSON candidate field in the gateway, and render it in a focused timeline/inspector component. Existing candidate and optimizer contracts remain backward compatible.

**Tech Stack:** FastAPI, Pydantic, SQLAlchemy, React, TypeScript, Tailwind CSS, Lucide icons, Node contract verifiers, pytest.

---

### Task 1: Define And Persist The Trace Contract

**Files:**
- Modify: `api-gateway/tests/test_optimizations.py`
- Modify: `api-gateway/routers/optimizations.py`
- Modify: `api-gateway/optimization_store.py`

- [ ] **Step 1: Write the failing API persistence test**

Add a candidate-generation test that submits an `optimizer_trace` containing status, reasoning-summary, tool, and completion events plus a fake API token in a payload. Assert the response preserves chronology and metadata, redacts the token, and reports bounded summary counts.

- [ ] **Step 2: Run the focused test and confirm RED**

Run: `python -m pytest api-gateway/tests/test_optimizations.py -k optimizer_trace -q`

Expected: FAIL because `GenerateCandidateRequest` and `OptimizationCandidateRow` do not expose `optimizer_trace`.

- [ ] **Step 3: Implement the minimal persisted contract**

Add `optimizer_trace` to both candidate request models, the store model, `to_dict`, and `create_candidate`. Extend `_ensure_optimization_schema` with an additive JSON column migration for existing databases.

- [ ] **Step 4: Add server-side normalization**

Create `_normalise_optimizer_trace` in `routers/optimizations.py`. Reuse `_redact`, permit only known top-level fields, cap events at 250, tool calls at 100, artifacts at 50, nested depth, and string size, then derive summary counts server-side.

- [ ] **Step 5: Run focused and full optimization tests**

Run:

```powershell
python -m pytest api-gateway/tests/test_optimizations.py -k optimizer_trace -q
python -m pytest api-gateway/tests/test_optimizations.py -q
```

Expected: PASS.

### Task 2: Capture The Observable Optimizer Stream

**Files:**
- Modify: `web-ui/scripts/verify-optimise-roi-contract.mjs`
- Modify: `web-ui/src/types.ts`
- Modify: `web-ui/src/lib/api.ts`
- Modify: `web-ui/src/components/intelligence/ExecutionObservatory.tsx`

- [ ] **Step 1: Extend the UI contract verifier and confirm RED**

Require `OptimizerTrace`, `optimizer_trace`, runtime event capture for reasoning/tool/completion/error events, and submission through `generateOptimizationCandidate`.

Run: `npm --prefix web-ui run verify:optimise-roi`

Expected: FAIL on the missing trace contract.

- [ ] **Step 2: Add typed API support**

Define `OptimizerTraceEvent`, `OptimizerTraceSummary`, and `OptimizerTrace` in `types.ts`. Parse optional traces in `parseOptimizationCandidate` and accept them in `GenerateOptimizationCandidatePayload`.

- [ ] **Step 3: Normalize stream events**

Update `invokeOptimizerAgentForRoi` to collect a bounded event list with stable sequence ids and timestamps. Capture public runtime reasoning summaries, tool calls, config/model selection, response progress, completion, warnings, and errors. Return the normalized trace with `InvokeResponse`.

- [ ] **Step 4: Persist success and fallback traces**

Build a fallback trace when streaming fails and pass `optimizer_trace` in the candidate generation payload in both normal and fallback flows.

- [ ] **Step 5: Run the verifier and TypeScript build**

Run:

```powershell
npm --prefix web-ui run verify:optimise-roi
npm --prefix web-ui run build
```

Expected: PASS.

### Task 3: Build The Ergonomic Candidate Trace Workspace

**Files:**
- Create: `web-ui/src/components/intelligence/OptimizerTracePanel.tsx`
- Modify: `web-ui/scripts/verify-optimise-roi-contract.mjs`
- Modify: `web-ui/src/components/intelligence/ExecutionObservatory.tsx`

- [ ] **Step 1: Add failing UI contract checks**

Require the `Optimizer trace` tab, summary strip, activity filters, chronology, selected-event inspector, skills/resources context, visible final response, and legacy empty state. Reject the old `Optimizer decision audit` title.

- [ ] **Step 2: Run the verifier and confirm RED**

Run: `npm --prefix web-ui run verify:optimise-roi`

Expected: FAIL because the focused trace workspace does not exist.

- [ ] **Step 3: Implement `OptimizerTracePanel`**

Create a focused component that derives summary values, filters events, maintains selected event state, and renders a 40/60 chronology-inspector layout. Keep raw payload and final response in expandable sections.

- [ ] **Step 4: Replace the old Agent audit stack**

Rename the workspace tab to `Optimizer trace`, render `OptimizerTracePanel`, and remove the repeated topology/generation/audit cards. Feed legacy candidates through a derived trace assembled from their existing audit and optimizer output.

- [ ] **Step 5: Verify responsive behavior and production build**

Run:

```powershell
npm --prefix web-ui run verify:optimise-roi
npm --prefix web-ui run build
```

Expected: PASS with no TypeScript errors.

### Task 4: Integrated Regression Verification

**Files:**
- Modify only if verification reveals a regression.

- [ ] **Step 1: Run backend optimization coverage**

Run: `python -m pytest api-gateway/tests/test_optimizations.py -q`

Expected: PASS.

- [ ] **Step 2: Run relevant UI contract suites**

Run:

```powershell
npm --prefix web-ui run verify:optimise-roi
npm --prefix web-ui run verify:intelligence
npm --prefix web-ui run build
```

Expected: PASS.

- [ ] **Step 3: Inspect the working-tree patch**

Run:

```powershell
git diff --check
git status --short
```

Expected: no whitespace errors and only intended optimizer trace files changed.

- [ ] **Step 4: Commit the feature**

```powershell
git add api-gateway web-ui docs/superpowers
git commit -m "Add persisted optimizer candidate traces"
```

