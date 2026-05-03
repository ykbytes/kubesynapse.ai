# Execution Observatory — Explained

This document covers the **Execution Observatory**: the real-time trace pipeline that captures workflow execution steps, LLM calls, tool calls, events, and worker logs for every run. It replaces the older ObservationTarget/ObservationReport system with a direct, deterministic event stream.

## Table of Contents

- [Architecture](#architecture)
- [How It Works](#how-it-works)
- [Trace Pipeline](#trace-pipeline)
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

## Data Model

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

Use `examples/observatory-demo.yaml` in the repo root. It defines a 4-step workflow that researches Kubernetes scheduling from two angles, synthesizes findings, and does a quality review. Each step is verified.

```bash
kubectl apply -f observatory-demo.yaml -n default
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

| Runtime | Agent Example | LLM Calls | Tool Calls | Logs | Status |
|---|---|---|---|---|---|
| **pi-runtime** | `minimax` (mistral/devstral-small) | ✅ | ✅ | ✅ | Full support |
| **mistral-vibe** | `mistral-vibe-smoke` (devstral-small) | ✅ | ✅ | ✅ | Full support |
| **opencode** | `opencode-test` (gpt-4o-mini) | Requires image build | — | — | Image must be built locally for kind |

### Pi-Runtime Specific Notes
- LLM calls are recorded when the runtime returns a `response` field (model is inferred from the agent spec or marked as "unknown")
- Token counts are **not reported** by the pi-runtime — this is a known limitation
- Tool calls are fully captured with args, results, and error messages

### Vibe-Runtime Specific Notes
- Uses the Mistral provider; API keys must be configured in `kubesynapse-llm-api-keys` secret
- Responds to prompts with text; verification criteria should accommodate the response style

### Configuration

API keys are managed through the `kubesynapse-llm-api-keys` secret and LiteLLM model routing:

```bash
# Update API keys
kubectl patch secret kubesynapse-llm-api-keys -n kubesynapse -p '{"data":{"OPENAI_API_KEY":"<base64-key>","MISTRAL_API_KEY":"<base64-key>"}}'

# Restart LiteLLM to pick up new keys
kubectl rollout restart deployment/kubesynapse-litellm -n kubesynapse
```
