# Observability Consistency Remediation Plan

> **Updated:** 2026-05-07  
> **Status:** Proposed implementation plan for the May 2026 observability hardening sprint  
> **Scope:** Execution Observatory, CRD-based observability, signal watch, SDK parity, and runtime semantic event parity

---

## 1. Objectives

This plan addresses the four audited observability gaps that currently create misleading status, broken or duplicated anomaly detection, stale SDK behavior, and incomplete direct-runtime analytics.

### Primary goals

1. Make `ObservationTarget` status reflect real collector outcomes instead of synthetic demo state.
2. Make signal watch correct against the current trace schema and ensure it runs once per interval.
3. Bring Python and TypeScript SDK trace methods back in sync with the live gateway contract.
4. Ensure OpenCode, Pi, and Vibe direct runtime paths emit `llm.call` events with the same semantic coverage expected by the analytics APIs.
5. Add tests and smoke checks so these surfaces stay aligned.

### Non-goals

1. Replacing the existing trace store schema.
2. Redesigning the web UI observability experience.
3. Adding new analytics endpoints beyond parity and hardening work.

---

## 2. Workstream A: Replace Synthetic ObservationTarget Status

### Current problem

`operator/controllers/observation_controller.py` currently treats the live controller path as demo-friendly behavior:

- demo mode is inferred from resource metadata
- findings are rendered as synthetic text
- `connectorHealth` is forced to a healthy state
- `metricsCollected` is incremented with a fabricated value on each timer cycle

That makes the CRD dashboard look active even when no connector has actually scraped anything.

### Target behavior

Production reconciliation must derive status from real connector or collector state. Demo mode can remain for examples, but it must be explicitly isolated and impossible to confuse with live telemetry.

### Files to change

- `operator/controllers/observation_controller.py`
- `charts/kubesynapse/templates/observationtarget-crd.yaml`
- `charts/kubesynapse/templates/connectorplugin-crd.yaml` if additional status fields are required
- `api-gateway/routers/observability.py` only if the response contract needs new fields
- `web-ui/src/components/ObservabilityDashboard.tsx` only if a new status field is surfaced

### Implementation design

#### 2.1 Split demo and production code paths

Refactor `reconcile_target_status()` into two explicit branches:

1. `_reconcile_demo_target_status(...)`
2. `_reconcile_live_target_status(...)`

The outer timer should do nothing except choose the path and persist the patch. That keeps demo-only behavior from leaking into the production branch.

#### 2.2 Define the production status source

Use the connector or collector as the only source of scrape truth. The live path should read a status payload that contains at least:

- `phase`
- `connectorHealth`
- `lastScrapeTime`
- `metricsCollected`
- `findingCount`
- `lastError`

If the connector already writes these to `ConnectorPlugin.status`, read them there. If not, add a minimal connector status contract first and keep `ObservationTarget.status` as a projection of connector state.

#### 2.3 Replace synthetic report generation

`_ensure_report_for_target()` should create or refresh `ObservationReport` objects only from:

1. collector findings returned by the connector, or
2. deterministic rules that operate on real scrape output

The controller must stop generating free-form synthetic narrative for the live path.

#### 2.4 Production status mapping

Use the following mapping in the live path:

- `phase = Pending` when no scrape has completed
- `phase = Active` when the last scrape succeeded and the connector is healthy
- `phase = Degraded` when the connector is reachable but the last scrape returned partial failures or warnings
- `phase = Failed` when the connector is unhealthy or repeated scrapes fail

`metricsCollected` must come from the last successful scrape summary, not an incrementing counter.

#### 2.5 Demo-mode guardrails

Keep demo mode opt-in through an explicit annotation or values flag, but write a `status.mode = demo` marker or equivalent label so UI and API consumers can identify it immediately.

### Data and schema impact

If existing CRDs do not already declare the connector status fields above, update the CRD schemas. This is a schema-extension change, not a breaking change, because the current fields can remain optional.

### Validation

1. Unit test: live path with healthy connector status produces `Active` and real counts.
2. Unit test: live path with connector error produces `Failed` and preserves last error.
3. Unit test: demo path still works and marks the target as demo-backed.
4. Smoke test: create a target with a real connector response and verify the dashboard shows live values without fabricated increments.

---

## 3. Workstream B: Harden Signal Watch

### Current problem

`operator/controllers/signal_watch.py` has three separate correctness risks:

1. It executes SQL through `kopf.text`, which is not the right query primitive.
2. It queries `workflow_executions.cost_usd`, while the workflow execution table stores `estimated_cost_usd`.
3. It schedules the sweep as a timer on every labeled system `AIAgent`, which likely duplicates the same anomaly pass once per agent object.

The whole cycle is also inside one outer `try` block, so a failure in one detector can prevent the later detectors from running.

### Target behavior

Signal watch should execute once per interval on the active operator leader, run each detector independently, and query only columns that exist in the current schema.

### Files to change

- `operator/controllers/signal_watch.py`
- `operator/main.py`
- `charts/kubesynapse/values.yaml`
- `charts/kubesynapse/templates/system-agents.yaml` only if labels or callers are adjusted
- `operator/tests/` for signal watch coverage

### Implementation design

#### 3.1 Extract a pure cycle function

Refactor the timer body into:

- `run_signal_watch_cycle(logger: logging.Logger) -> None`

That function should:

1. run each detector
2. map rows to `ObservationReport` payloads
3. log a per-detector result summary

This makes the sweep callable from tests and from a singleton scheduler.

#### 3.2 Replace the SQL helper

Change `_query()` to use `sqlalchemy.text` and pass named parameters. Do not depend on Kopf for SQL primitives.

#### 3.3 Fix spend queries against the real schema

Replace all references to `workflow_executions.cost_usd` with `workflow_executions.estimated_cost_usd`. Keep runtime event spend queries on `runtime_run_events.cost_usd` because that column is real and already used by runtime summaries.

#### 3.4 Move scheduling to a singleton leader loop

Do not run signal watch as an object-bound timer on `AIAgent` resources.

Preferred implementation:

1. Start a background task from operator startup when `signalWatch.enabled` is true.
2. Run the loop only on the active operator leader.
3. Sleep for `WATCH_INTERVAL_SEC` between cycles.
4. Call `run_signal_watch_cycle()` inside the loop.

This preserves Helm configurability while removing duplicate per-object scheduling.

#### 3.5 Isolate detector failures

Each detector should run inside its own `try` block with its own warning log. A failed spend query must not suppress failure-rate, error-spike, token-spike, or stuck-run checks.

#### 3.6 Deduplicate reports

Use a deterministic key derived from anomaly type, execution id, and a time bucket so the same interval does not create duplicate `ObservationReport` objects if the cycle retries.

### Validation

1. Unit test: spend outlier query reads `estimated_cost_usd`.
2. Unit test: when one detector raises, later detectors still run.
3. Unit test: a single anomaly cycle does not create duplicates on retry.
4. Integration test: one operator leader produces one sweep per interval even when multiple system agents exist.

---

## 4. Workstream C: Align SDKs With The Trace Contract

### Current problem

The SDKs still call legacy trace endpoints and still type the list response as a bare array. The gateway now exposes executions under `/api/v1/traces/executions` and returns an envelope with `items`, `limit`, and `offset`.

### Target behavior

SDKs must expose the current execution contract while keeping a controlled migration path for callers already using `list_traces` and `get_trace`.

### Files to change

- `clients/python/kubesynapse/client.py`
- `clients/typescript/src/client.ts`
- `api-gateway/traces_router.py` if compatibility aliases are added
- `docs/api-reference.md`
- SDK tests in both client packages

### Implementation design

#### 4.1 Add canonical execution methods

Expose canonical names that match the gateway resource model:

- Python: `list_executions()`, `get_execution()`
- TypeScript: `listExecutions()`, `getExecution()`

These methods should call:

- `GET /api/v1/traces/executions`
- `GET /api/v1/traces/executions/{execution_id}`

#### 4.2 Preserve compatibility wrappers

Keep `list_traces` and `get_trace` as deprecated wrappers that forward to the new methods. That lets existing callers survive the transition without silently breaking.

#### 4.3 Correct the payload types

Return structured objects that mirror the gateway models:

- list response: `items`, `limit`, `offset`
- detail response: execution metadata plus steps, tool calls, LLM calls, and events

In TypeScript, add explicit interfaces instead of `Record<string, unknown>` for the main trace types touched by these methods.

#### 4.4 Optional server aliases

If backwards compatibility for external consumers is important, add temporary route aliases on the server:

- `GET /api/v1/traces`
- `GET /api/v1/traces/{execution_id}`

Those aliases should delegate to the execution handlers and emit deprecation metadata. This is optional if SDK migration is sufficient, but it is the safest path for third-party callers.

### Validation

1. Unit test: SDK list methods deserialize the execution list envelope.
2. Unit test: deprecated wrappers still return the same data shape as the canonical methods.
3. Contract test: compare SDK route constants against the live gateway router.
4. Docs update: examples in the API reference use `executions` terminology.

---

## 5. Workstream D: Emit `llm.call` Events From Direct Runtimes

### Current problem

Worker-driven workflow runs record rich LLM usage through the trace client, but the direct runtimes do not emit equivalent semantic `llm.call` events on their main invoke paths. That leaves the runtime timeline, spend lens, and model analytics incomplete for direct runtime usage.

### Target behavior

Every runtime should emit `llm.call` whenever it has enough metadata to describe a model invocation, regardless of whether the call came from a workflow worker or a direct runtime request.

### Files to change

- `opencode-runtime/main.py`
- `opencode-runtime/runtime_events.py`
- `pi-runtime/pi_bridge.js`
- `pi-runtime/runtime_events.js`
- `vibe-runtime/main.py`
- `vibe-runtime/runtime_events.py`
- `api-gateway/trace_store.py` only if new payload fields need indexing or summary support

### Shared event contract

All runtimes should emit the same normalized payload fields where available:

- `provider`
- `model`
- `prompt_tokens`
- `completion_tokens`
- `total_tokens`
- `cost_usd`
- `duration_ms`
- `prompt_preview`
- `response_preview`
- `status`
- `step_id` when applicable

Null values are acceptable for fields a provider does not expose, but the event type and basic provider or model identity should be present.

### Implementation design

#### 5.1 OpenCode runtime

OpenCode already imports `emit_llm_call`, so the work is to call it at the right time:

1. `/invoke`: emit after the final model result and usage metadata are assembled.
2. `/invoke/stream`: emit once per completed model response, not once per token delta.
3. Reuse the same execution id as the surrounding run and tool events.

#### 5.2 Pi runtime

Pi already defines `emitLlmCall` in `runtime_events.js`, but the bridge never invokes it. Add emission in two places:

1. after the bridge receives the final invoke result payload
2. after the stream completes and usage metadata is finalized

If the bridge only sees usage data at the end of a stream, emit a single summarized `llm.call` event there.

#### 5.3 Vibe runtime

Vibe defines `emit_llm_call` but does not import or use it from `main.py`. Import it and emit once the runtime has response metadata for both invoke paths.

#### 5.4 Summary and spend parity

Verify that `trace_store.get_run_summary()` and spend aggregation continue to work with these events. If the summaries already read from `runtime_run_events.cost_usd`, no schema change is needed. If not, extend the aggregation helpers rather than adding a second path.

### Validation

1. Unit test per runtime: `llm.call` is emitted on successful invoke.
2. Streaming test per runtime: one final `llm.call` event is emitted after stream completion.
3. Analytics test: `runtime-summary` and spend queries reflect direct runtime runs after the change.

---

## 6. Workstream E: Test And Rollout Strategy

### Test matrix

#### Unit tests

1. Observation controller live path and demo path.
2. Signal watch query helper, cost query, per-detector isolation, and dedupe.
3. SDK execution route and response-shape handling.
4. OpenCode, Pi, and Vibe `llm.call` emission.

#### Integration tests

1. Gateway plus trace store contract tests for `/api/v1/traces/executions`.
2. Operator leader loop test for singleton signal watch behavior.
3. End-to-end runtime event ingestion into timeline and runtime-summary endpoints.

#### Smoke tests

Extend the deploy-time smoke path to validate:

1. direct runtime invoke creates `run.started`, `llm.call`, and `run.completed`
2. workflow run creates trace events and archived logs
3. a seeded anomaly creates exactly one `ObservationReport`
4. SDK examples resolve the live trace endpoints

### Rollout order

1. Land gateway and operator fixes first: signal watch, compatibility aliases if used, and observation controller split.
2. Land SDK updates second so external callers can consume the fixed contract.
3. Land runtime `llm.call` parity third.
4. Run smoke tests in a multi-replica operator deployment to verify signal watch singleton behavior.
5. Remove any temporary compatibility aliases only after one release cycle.

### Release notes checklist

1. Call out that `ObservationTarget` status is now connector-backed.
2. Document the canonical trace SDK methods and deprecation of legacy wrappers.
3. Note that direct runtime runs now contribute to spend and model analytics via `llm.call`.
4. Mention any temporary compatibility aliases and their removal timeline.

---

## 7. Recommended Delivery Sequence

If this work is implemented in one sprint, use this order:

1. Signal watch hardening, because it has the highest risk of silent failure and duplicate reports.
2. ObservationTarget live-status correction, because it removes misleading CRD health.
3. SDK contract alignment, because it unblocks consumers immediately.
4. Runtime `llm.call` parity, because it improves analytics completeness after the contract is stable.
5. Test and smoke coverage, because it locks the fixes in place.

This order minimizes user-visible inconsistency first, then improves analytics completeness.