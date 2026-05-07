# KubeSynapse Repo Surface Map For Roadmap Handoffs

Use this reference when turning roadmap stories or remediation docs into engineer tasks. It is intentionally biased toward the repo's current platform and observability backlog.

## Source Docs

### Primary planning docs

- `docs/ROADMAP.md`
- `ROADMAP.md`
- `docs/observability-remediation-plan.md`

### Supporting docs

- `docs/observability-explained.md`
- `docs/architecture-overview.md`
- `docs/deployment-readme.md`
- `scripts/observability-smoke-test.ps1`

## Ownership By Subsystem

### Operator and CRD reconciliation

Use these when the story changes controller behavior, CRD status, report generation, periodic watchers, or worker-side trace emission.

- `operator/main.py`
- `operator/controllers/__init__.py`
- `operator/controllers/observation_controller.py`
- `operator/controllers/signal_watch.py`
- `operator/controllers/status_projection.py`
- `operator/runtime_events.py`
- `operator/trace_client.py`
- `operator/worker.py`
- `operator/tests/test_trace_client.py`

### API gateway and persistence

Use these when the story changes trace routes, response shapes, persistence, spend or runtime summaries, or observability APIs.

- `api-gateway/main.py`
- `api-gateway/traces_router.py`
- `api-gateway/trace_store.py`
- `api-gateway/routers/observability.py`
- `api-gateway/routers/workflows.py`
- `api-gateway/_core.py`

### Direct runtimes

Treat each runtime as its own implementation surface when event emission or runtime behavior changes.

- `opencode-runtime/main.py`
- `opencode-runtime/runtime_events.py`
- `pi-runtime/pi_bridge.js`
- `pi-runtime/runtime_events.js`
- `vibe-runtime/main.py`
- `vibe-runtime/runtime_events.py`

### SDKs and client contracts

Use these when public trace methods or API consumers change.

- `clients/python/kubesynapse/client.py`
- `clients/typescript/src/client.ts`
- `docs/api-reference.md`

### UI surfaces

Use these only after the backend contract is clear.

- `web-ui/src/components/ExecutionObservatory.tsx`
- `web-ui/src/components/ObservabilityDashboard.tsx`
- `web-ui/src/components/WorkflowLogPanel.tsx`
- `web-ui/src/lib/api.ts`

### Helm and CRD templates

Use these when the story changes configurable intervals, chart behavior, CRD schemas, system agents, or rollout semantics.

- `charts/kubesynapse/values.yaml`
- `charts/kubesynapse/templates/system-agents.yaml`
- `charts/kubesynapse/templates/observationtarget-crd.yaml`
- `charts/kubesynapse/templates/connectorplugin-crd.yaml`

## Observability Surface Distinctions

### Execution Observatory

Primary files:

- `api-gateway/trace_store.py`
- `api-gateway/traces_router.py`
- `web-ui/src/components/ExecutionObservatory.tsx`
- `web-ui/src/lib/api.ts`

Focus areas:

- execution list and detail
- timeline and runtime-summary
- runtime event ingestion
- spend and agent graph analytics

### CRD-based observability

Primary files:

- `operator/controllers/observation_controller.py`
- `operator/controllers/signal_watch.py`
- `api-gateway/routers/observability.py`
- `web-ui/src/components/ObservabilityDashboard.tsx`
- `charts/kubesynapse/templates/observationtarget-crd.yaml`

Focus areas:

- ObservationTarget status
- ObservationReport generation
- ConnectorPlugin status projection
- deterministic anomaly reporting

### Workflow log access

Primary files:

- `operator/controllers/status_projection.py`
- `api-gateway/_core.py`
- `api-gateway/routers/workflows.py`
- `web-ui/src/components/WorkflowLogPanel.tsx`

Focus areas:

- archived terminal logs
- live-worker fallback
- run trace loading in the UI

## Current Story Map For Phase 2.5

### Story 10.1: Connector-backed ObservationTarget status

Start here:

- `operator/controllers/observation_controller.py`
- `charts/kubesynapse/templates/observationtarget-crd.yaml`
- `charts/kubesynapse/templates/connectorplugin-crd.yaml`

Likely follow-ons:

- `api-gateway/routers/observability.py`
- `web-ui/src/components/ObservabilityDashboard.tsx`

Checklist focus:

- split demo and live reconciliation
- define connector status contract
- replace synthetic metrics and findings
- keep demo mode opt-in and clearly marked
- validate status mapping and report creation

### Story 10.2: Signal watch hardening

Start here:

- `operator/controllers/signal_watch.py`
- `operator/main.py`
- `charts/kubesynapse/values.yaml`
- `charts/kubesynapse/templates/system-agents.yaml`

Cross-check with:

- `api-gateway/trace_store.py`

Checklist focus:

- replace `kopf.text` with `sqlalchemy.text`
- use `workflow_executions.estimated_cost_usd`
- make scheduling singleton or leader-bound
- isolate detector failures
- deduplicate report creation

### Story 10.3: Trace SDK contract alignment

Start here:

- `clients/python/kubesynapse/client.py`
- `clients/typescript/src/client.ts`
- `api-gateway/traces_router.py`
- `api-gateway/main.py`
- `docs/api-reference.md`

Checklist focus:

- move clients to `/api/v1/traces/executions`
- align return types to execution list and detail envelopes
- decide whether to add temporary server aliases
- add contract tests or backward-compat checks

### Story 10.4: Direct-runtime `llm.call` parity

Start here:

- `opencode-runtime/main.py`
- `opencode-runtime/runtime_events.py`
- `pi-runtime/pi_bridge.js`
- `pi-runtime/runtime_events.js`
- `vibe-runtime/main.py`
- `vibe-runtime/runtime_events.py`

Cross-check with:

- `api-gateway/trace_store.py`
- `api-gateway/traces_router.py`

Checklist focus:

- emit `llm.call` only when final model metadata is available
- normalize provider, model, token, cost, duration, and preview payload fields
- keep one final semantic event per completed call, not per delta token
- confirm runtime-summary and spend surfaces include these events

### Story 10.5: Contract and smoke coverage

Start here:

- `operator/tests/`
- `clients/python/`
- `clients/typescript/`
- `scripts/observability-smoke-test.ps1`
- `docs/deployment-readme.md`

Checklist focus:

- add missing focused tests near the owning code
- create new test files if no nearby surface exists
- extend smoke coverage for runtime events, spend, and signal watch
- update deployment docs if the smoke path changes

## Default Validation Ladder

Prefer the narrowest useful validation for the touched slice:

1. focused unit tests near the changed package
2. package-local build or typecheck
3. documented observability smoke path
4. broader repo-level checks only when needed

Useful repo anchors:

- `operator/tests/test_trace_client.py`
- `scripts/observability-smoke-test.ps1`
- `docs/deployment-readme.md`
- `web-ui` build path documented in `docs/deployment-readme.md`

## Handoff Quality Checks

Before finalizing a roadmap handoff, verify that:

1. each subtask names the owning file or an explicitly missing test surface
2. the handoff distinguishes verified behavior from intended design
3. validations are tied to the touched slice
4. compatibility notes exist whenever SDKs, routes, CRDs, or runtime payloads change
5. sequencing is explicit if more than one subsystem is involved