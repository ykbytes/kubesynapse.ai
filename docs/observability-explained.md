# Execution Observatory — Explained

This document covers the **Execution Observatory** and **Run Intelligence Layer**: the real-time trace pipeline that captures workflow execution steps, LLM calls, tool calls, events, and worker logs for every run, plus the semantic event indexing system that enables anomaly detection, cost analysis, and agent topology mapping.

## Table of Contents

- [Architecture](#architecture)
- [How It Works](#how-it-works)
- [Trace Pipeline](#trace-pipeline)
- [Run Intelligence Layer](#run-intelligence-layer)
  - [Semantic Event Index](#semantic-event-index)
  - [Runtime Event Emission](#runtime-event-emission)
  - [Query & Timeline APIs](#query--timeline-apis)
  - [System Agents](#system-agents)
  - [Signal Watch Controller](#signal-watch-controller)
  - [Analytics APIs](#analytics-apis)
- [Data Model](#data-model)
- [Demo Workflow](#demo-workflow)
- [Troubleshooting](#troubleshooting)
- [Runtime Compatibility](#runtime-compatibility)

## Architecture

```
Workflow Trigger → Operator → Worker Job → Agent Runtime → Trace Events → API Gateway → PostgreSQL (execution_traces)
                                                      ↘ Worker Logs ↗
```

1. **Operator** enqueues a workflow run as a Kubernetes Job
2. **Worker** (running in the Job) executes each step by calling the agent runtime's `/invoke/stream` endpoint
3. **Trace Client** (embedded in the worker) accumulates step/LLM/tool/event records in memory and flushes them in batches to the API gateway's `/api/traces/batch` endpoint (HTTP 202)
4. **API Gateway** processes trace events, upserts them into the `execution_traces` PostgreSQL table, and enriches step records with per-step LLM/tool call counts and latencies
5. **Web UI** fetches execution detail via `/api/traces/executions/{id}` and renders the Observatory workspace

## How It Works

### Event Flow

Every workflow step produces a stream of events:

| Event Type | When | What It Stores |
|---|---|---|
| `execution_started` | Worker begins the run | workflow name, namespace, agent, run_id |
| `step_started` | Each step begins | step name, type, index (auto-incremented) |
| `step_completed` / `step_failed` | Each step ends | status, latency (computed from started_at → completed_at), output preview |
| `llm_call_completed` | After each LLM interaction | model, provider, tokens (prompt/completion), cost, latency, preview |
| `tool_call_completed` / `tool_call_failed` | After each tool use | tool name, args, result, error, duration |
| `execution_completed` / `execution_failed` / `execution_cancelled` | Run ends | final status, metrics, error message |

### Batch Delivery

- Worker accumulates events in a thread-safe buffer
- Flushes every 5 seconds or when the batch reaches 50 events
- Posts to `{gateway_url}/api/traces/batch` with Bearer token auth
- Gateway processes events grouped by `execution_id`
- On failure, events are dropped with a warning (tracing is fire-and-forget)

### Per-Step Enrichment

The API gateway's `_execution_trace_to_dict` function enriches each step record with its associated LLM calls, tool calls, and per-step metrics before returning to the UI:

- `llm_calls`: LLM call records with matching `step_id`
- `tool_calls`: Tool call records with matching `step_id`
- `latency_ms`: Computed from `started_at` → `completed_at`
- `tokens_used`: Sum of prompt + completion tokens across all LLM calls for that step
- `step_index`: The order of the step in the workflow (1-based in UI)

## Run Intelligence Layer

The Run Intelligence Layer extends the Execution Observatory with **semantic event indexing**, **system agents**, and **analytics APIs**. It transforms raw trace data into actionable operational intelligence.

### Architecture

```
Runtime (opencode/pi/vibe) ──→ runtime_events.py ──→ POST /api/v1/traces/runtime-events
Operator Worker ──────────────→ runtime_events.py ──→      │
                                                        ▼
                                              runtime_run_events table
                                                        │
                    ┌───────────────────────────────────┼───────────────────────────────────┐
                    ▼                                   ▼                                   ▼
          GET /traces/{id}/timeline          Signal Watch Controller          GET /observability/*
          GET /traces/runtime-events         (every 60s SQL checks)           - /agent-graph
          GET /traces/{id}/runtime-summary   Creates ObservationReport CRs    - /spend
                                                                                - system agents
```

### Semantic Event Index

The `runtime_run_events` table stores structured events from all runtimes and workers:

| Column | Type | Description |
|---|---|---|
| `id` | `VARCHAR(64)` | Primary key (`rre-{uuid}`) |
| `event_id` | `VARCHAR(128)` | Unique per event (`{execution_id}-{seq}`), idempotent upsert |
| `execution_id` | `VARCHAR(64)` | Parent execution/run ID |
| `session_id` | `VARCHAR(128)` | Runtime session ID |
| `thread_id` | `VARCHAR(128)` | Logical thread ID |
| `namespace` | `VARCHAR(128)` | Kubernetes namespace |
| `agent_name` | `VARCHAR(128)` | Agent that generated the event |
| `runtime_kind` | `VARCHAR(50)` | `opencode`, `pi`, `vibe`, `operator-worker` |
| `event_type` | `VARCHAR(64)` | Canonical event type (see taxonomy below) |
| `seq` | `INTEGER` | Per-execution sequence number |
| `severity` | `VARCHAR(16)` | `info`, `warning`, `error` |
| `payload` | `JSONB` | Flexible event data |
| `duration_ms` | `INTEGER` | Operation duration |
| `prompt_tokens` | `INTEGER` | LLM prompt tokens |
| `completion_tokens` | `INTEGER` | LLM completion tokens |
| `total_tokens` | `INTEGER` | Total tokens |
| `cost_usd` | `FLOAT` | Estimated cost |
| `created_at` | `TIMESTAMPTZ` | Event timestamp |

### Event Taxonomy

All runtimes emit events using this canonical taxonomy:

| Event Type | Emitted By | Description |
|---|---|---|
| `run.started` | All runtimes | Session/invoke started |
| `run.completed` | All runtimes | Session/invoke completed |
| `run.error` | All runtimes | Session/invoke failed |
| `tool.started` | All runtimes | Tool call initiated |
| `tool.completed` | All runtimes | Tool call succeeded |
| `tool.failed` | All runtimes | Tool call failed |
| `llm.call` | All runtimes | LLM interaction completed |
| `agent.call.started` | Operator worker | A2A agent call initiated |
| `agent.call.completed` | Operator worker | A2A agent call succeeded |
| `agent.call.failed` | Operator worker | A2A agent call failed |
| `step.started` | Operator worker | Workflow step started |
| `step.completed` | Operator worker | Workflow step completed |
| `step.failed` | Operator worker | Workflow step failed |
| `human.question` | opencode-runtime | HITL question asked |
| `todo.updated` | opencode-runtime | Todo list changed |

### Runtime Event Emission

Each runtime has a `runtime_events` module that:

1. **Queues events** in a bounded async/sync queue (max 500 events)
2. **Batch flushes** every 2 seconds or when 50 events accumulate
3. **Sanitizes payloads** — secrets redacted, large strings truncated
4. **Generates idempotent event IDs** — `{execution_id}-{seq}` format
5. **Graceful shutdown** — drains queue before exit

**Configuration (env vars):**

| Variable | Default | Description |
|---|---|---|
| `RUNTIME_EVENTS_QUEUE_SIZE` | `500` | Max events in queue |
| `RUNTIME_EVENTS_BATCH_SIZE` | `50` | Events per batch |
| `RUNTIME_EVENTS_FLUSH_INTERVAL` | `2.0` | Flush interval (seconds) |
| `RUNTIME_EVENTS_HTTP_TIMEOUT` | `10.0` | HTTP timeout (seconds) |

### Query & Timeline APIs

| Endpoint | Description |
|---|---|
| `POST /api/v1/traces/runtime-events` | Batch ingest events (max 500 per request) |
| `GET /api/v1/traces/{execution_id}/timeline` | Ordered semantic timeline for a run |
| `GET /api/v1/traces/{execution_id}/runtime-summary` | Aggregate stats (tokens, cost, duration, errors) |
| `GET /api/v1/traces/runtime-events` | Cross-run filtering with pagination |

**Timeline query parameters:**
- `event_type` — filter by event type
- `from_seq` — start from sequence number
- `limit` — max events (default 500)

**Cross-run query parameters:**
- `namespace`, `runtime_kind`, `event_type`, `agent_name`, `session_id`, `severity`
- `from_ts`, `to_ts` — ISO 8601 timestamps
- `limit`, `offset` — pagination

### System Agents

Three predefined AIAgent CRs provide AI-powered analysis on top of deterministic detection:

| Agent | Trigger | Purpose |
|---|---|---|
| `ks-run-inspector` | Workflow step failures, high error rates | Investigates failed runs, produces root-cause summaries |
| `ks-signal-summarizer` | Anomaly signals from signal watch | Converts raw signals to human-readable incident briefs |
| `ks-spend-reviewer` | Cost/token spend anomalies | Reviews spend outliers, recommends optimizations |

**Configuration (Helm values):**

```yaml
systemAgents:
  enabled: true
  namespace: "kubesynapse-system"
  defaultModel: "gpt-4"
  defaultRuntime: "opencode"
  runInspector:
    enabled: true
    triggers:
      minFailureRate: 0.3
      minErrorCount: 3
  signalSummarizer:
    enabled: true
    triggers:
      maxSignalAgeMinutes: 30
  spendReviewer:
    enabled: true
    triggers:
      costThresholdUsd: 10.0
      tokenSpikeMultiplier: 3.0
```

### Signal Watch Controller

The operator runs a periodic anomaly detection controller (`signal_watch.py`) that executes deterministic SQL checks every 60 seconds:

| Check | Threshold | Severity Mapping |
|---|---|---|
| High failure rate | >30% steps failed in window | 30%=medium, 50%=high, 70%=critical |
| Error spikes | >=3 errors in 15m window | 1x=medium, 2x=high, 5x=critical |
| Cost outliers | >3x namespace average | 3x=medium, 5x=high, 10x=critical |
| Token spikes | >3x agent rolling average | 3x=medium, 5x=high, 10x=critical |
| Stuck runs | >2x median duration | 2x=medium, 3x=high, 5x=critical |

When a check fires, an `ObservationReport` CR is created with severity classification. System agents can be invoked to provide AI-powered explanations.

**Configuration (env vars):**

| Variable | Default | Description |
|---|---|---|
| `SIGNAL_WATCH_INTERVAL_SEC` | `60` | Check interval |
| `SIGNAL_WATCH_WINDOW_MINUTES` | `15` | Anomaly detection window |
| `SIGNAL_WATCH_FAILURE_RATE` | `0.3` | Failure rate threshold |
| `SIGNAL_WATCH_ERROR_COUNT` | `3` | Error count threshold |
| `SIGNAL_WATCH_COST_MULTIPLIER` | `3.0` | Cost outlier multiplier |
| `SIGNAL_WATCH_TOKEN_MULTIPLIER` | `3.0` | Token spike multiplier |
| `SIGNAL_WATCH_STUCK_MULTIPLIER` | `2.0` | Stuck run multiplier |

### Analytics APIs

| Endpoint | Description |
|---|---|
| `GET /api/v1/observability/agent-graph` | Agent-to-agent dependency graph from A2A events |
| `GET /api/v1/observability/spend` | Token/cost breakdown by agent, model, runtime, namespace |

**Agent Graph Response:**
```json
{
  "nodes": ["agent-a", "agent-b", "agent-c"],
  "edges": [
    {
      "source": "agent-a",
      "target": "agent-b",
      "call_count": 42,
      "error_count": 2,
      "avg_latency_ms": 1250,
      "last_seen": "2026-05-04T12:00:00Z"
    }
  ],
  "window_hours": 24
}
```

**Spend Response:**
```json
{
  "items": [
    {
      "namespace": "default",
      "agent_name": "build-agent",
      "runtime_kind": "opencode",
      "model": "gpt-4",
      "total_tokens": 125000,
      "prompt_tokens": 80000,
      "completion_tokens": 45000,
      "estimated_cost_usd": 3.75,
      "run_count": 12,
      "error_count": 1
    }
  ],
  "window_hours": 24
}
```

## Data Model

### Execution Observatory Tables

### execution_traces Table

| Column | Type | Description |
|---|---|---|
| `id` | `VARCHAR` | Unique execution ID (`exec-{uuid}`) |
| `run_id` | `VARCHAR` | Workflow run identifier |
| `workflow_name` | `VARCHAR` | Name of the workflow |
| `namespace` | `VARCHAR` | Target namespace |
| `agent_name` | `VARCHAR` | Agent that executed (nullable) |
| `status` | `VARCHAR` | `running`, `completed`, `failed`, `cancelled` |
| `started_at` | `TIMESTAMPTZ` | Execution start time |
| `completed_at` | `TIMESTAMPTZ` | Execution end time |
| `duration_ms` | `INTEGER` | Total duration in milliseconds |
| `step_count` | `INTEGER` | Number of steps |
| `llm_call_count` | `INTEGER` | Total LLM calls |
| `tool_call_count` | `INTEGER` | Total tool calls |
| `total_tokens` | `INTEGER` | Token usage (pi-runtime does not report this) |
| `total_cost_usd` | `FLOAT` | Estimated cost |
| `steps_json` | `JSONB` | Step records with per-step LLM/tool arrays |
| `llm_calls_json` | `JSONB` | All LLM call records |
| `tool_calls_json` | `JSONB` | All tool call records |
| `events_json` | `JSONB` | All trace events (timeline) |

### Step Record

```json
{
  "id": "step-{uuid}",
  "execution_id": "exec-{uuid}",
  "step_index": 0,
  "name": "research-architecture",
  "type": "agent",
  "status": "completed",
  "started_at": "2026-05-03T11:04:47.010037+00:00",
  "completed_at": "2026-05-03T11:05:17.042915+00:00",
  "latency_ms": 30030,
  "llm_calls": [...],
  "tool_calls": [...],
  "tokens_used": 0
}
```

## Demo Workflow

Use `examples/observability-demo-fire.yaml`. It defines a 4-step workflow that researches Kubernetes scheduling from two angles, synthesizes findings, and does a quality review.

```bash
kubectl apply -f examples/observability-demo-fire.yaml -n default
# Wait for the workflow to appear in the UI, then trigger it
```

Open the **Execution Observatory** workspace in the UI. Select the completed execution to inspect:
- **Steps tab**: Per-step drilldown with LLM/tool counts and latency per step
- **Logs tab**: Worker logs (live or archived fallback)
- **Insights tab**: All LLM calls and tool calls with previews
- **Compare tab**: Side-by-side execution diff

## Troubleshooting

### Observatory shows "No steps recorded" for an execution

**Cause:** The trace pipeline was broken during that run. The most common issues:

1. **Missing shared token**: `DEFAULT_API_GATEWAY_SHARED_TOKEN` env var is empty in the operator deployment. Workers cannot authenticate to `/api/traces/batch`.

   **Fix:** Set the token on the operator deployment:
   ```bash
   kubectl set env deployment/kubesynapse-operator -n kubesynapse \
     DEFAULT_API_GATEWAY_SHARED_TOKEN='<your-shared-token>'
   ```

2. **Worker can't reach gateway**: Network policy or DNS issue. Verify:
   ```bash
   # Check operator has the correct gateway URL
   kubectl get deployment kubesynapse-operator -n kubesynapse -o jsonpath='{.spec.template.spec.containers[0].env[?(@.name=="API_GATEWAY_INTERNAL_URL")].value}'
   ```

3. **Old run before fix**: Pre-existing runs won't retroactively get trace data. Re-run the workflow to populate the Observatory.

### Execution shows "0 LLM calls" despite LLM interactions

**Cause:** The pi-runtime does not emit separate LLM call events in the `response.completed` stream event. The metadata field may be `null` instead of a dict.

**Fix:** The worker now records LLM calls whenever a `response` field is present (not just when `model` is explicitly set). This is fixed in operator `trace-fix-v13+`.

### Execution shows "—" for step duration

**Cause:** `latency_ms` was not computed server-side for older trace records.

**Fix:** The API gateway now computes `latency_ms` from `started_at` → `completed_at` when processing `step_completed` events and during response serialization.

### All steps show "#1" instead of "#1, #2, #3, #4"

**Cause:** The worker hardcoded `step_index=0` for every step.

**Fix:** Worker no longer sends `step_index` explicitly. The backend auto-increments from `len(steps)`.

### Worker logs show "No worker pod found"

**Cause:** The API gateway's log endpoint was looking up worker pods in the workflow's namespace (e.g., `default`) instead of the operator's namespace (`kubesynapse`).

**Fix:** The log endpoint now uses `kubesynapse` namespace for pod lookups. Falls back to archived logs if live logs are unavailable.

### Helm upgrade breaks trace pipeline

**Cause:** The helm chart template used `valueFrom: secretKeyRef` with `optional: true` for `DEFAULT_API_GATEWAY_SHARED_TOKEN`, which sometimes resolves to empty.

**Fix:** The chart template now uses a direct `value:` with the token from `platformSecrets`. After each helm upgrade, verify:
```bash
kubectl get deployment kubesynapse-operator -n kubesynapse -o jsonpath='{.spec.template.spec.containers[0].env[?(@.name=="DEFAULT_API_GATEWAY_SHARED_TOKEN")].value}'
```

## Runtime Compatibility

| Runtime | Agent Example | LLM Calls | Tool Calls | Logs | Runtime Events | Status |
|---|---|---|---|---|---|---|
| **pi-runtime** | `minimax` (mistral/devstral-small) | ✅ | ✅ | ✅ | ✅ | Full support |
| **opencode** | `opencode-test` (gpt-4o-mini) | Requires image build | — | — | ✅ | Image must be built locally for kind |

### Runtime Event Emission

All runtimes now emit structured events to the Run Intelligence Layer via their `runtime_events` module:

- **opencode-runtime**: `runtime_events.py` — sync + async emitter, integrated into `/invoke`, `/invoke/stream`, lifespan
- **pi-runtime**: `runtime_events.js` — Node.js emitter, integrated into `/invoke`, `/invoke/stream`, shutdown
- **operator worker**: `runtime_events.py` — emits workflow/step/agent/tool events alongside existing TraceClient

Events are batched, idempotent, and sanitized before being sent to `POST /api/v1/traces/runtime-events`.

### Pi-Runtime Specific Notes
- LLM calls are recorded when the runtime returns a `response` field (model is inferred from the agent spec or marked as "unknown")
- Token counts are **not reported** by the pi-runtime — this is a known limitation
- Tool calls are fully captured with args, results, and error messages

### Configuration

API keys are managed through the `kubesynapse-llm-api-keys` secret and LiteLLM model routing:

```bash
# Update API keys
kubectl patch secret kubesynapse-llm-api-keys -n kubesynapse -p '{"data":{"OPENAI_API_KEY":"<base64-key>","MISTRAL_API_KEY":"<base64-key>"}}'

# Restart LiteLLM to pick up new keys
kubectl rollout restart deployment/kubesynapse-litellm -n kubesynapse
```
