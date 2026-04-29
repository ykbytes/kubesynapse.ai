# Pi-Mono Integration Plan — KubeSynapse

**Status**: COMPLETED AND DEPLOYED  
**Target**: Replace OpenCode with pi-mono as an alternative KubeSynapse agent runtime  
**Strategy**: Add pi as a NEW runtime kind ("pi") alongside existing "opencode" — no breaking changes  
**Estimated**: 6 phases, ~20 stories, 40-60 hours

---

## Deployment Notes

- **Current image tag**: `kubesynapse-pi-rt:v0.2.13`
- **Known issues**: `minimax-m2.5-free` model API intermittent hangs (mitigated by 120s timeout + auto-retry)
- **Operational note**: Pi session PVC should be wiped between pod restarts to avoid "Agent is already processing" deadlock

---

## Phase 0: Foundation — Pi Runtime Docker Image (6h) ✅

### Story P0.1: Pi Runtime Dockerfile
**Goal**: Container image with pi-coding-agent installed and ready for RPC mode
**DoD**:
1. `pi-runtime/Dockerfile` based on `node:22-slim`
2. Installs `@mariozechner/pi-coding-agent@0.70.5` globally
3. Installs `@mariozechner/pi-ai` for provider types
4. Creates non-root `piuser` (uid 1000)
5. Sets up `~/.pi/agent/` directory structure
6. Entrypoint: `pi --mode rpc`
7. Image builds in < 5 minutes
8. Image size < 500 MB

### Story P0.2: Pi Runtime package.json & Extensions Scaffold
**Goal**: KubeSynapse-specific extensions structure in place
**DoD**:
1. `pi-runtime/package.json` with pi dependencies
2. `pi-runtime/extensions/` directory structure created
3. Skeleton extension files for all 5 KubeSynapse extensions
4. `pi-runtime/entrypoint.sh` bash script for proper startup
5. Agent settings (`settings.json`) for KubeSynapse defaults
6. All extension files pass `tsc --noEmit`

### Story P0.3: Pi Runtime Helm Values
**Goal**: Helm chart supports pi runtime deployment
**DoD**:
1. New `agentRuntime.pi` section in `values.yaml`
2. `agentRuntime.pi.image` defaults to `kubesynapse-pi-rt:v0.1.0`
3. `agentRuntime.pi.enabled` flag (default: false, opt-in)
4. `agentRuntime.pi.nodeVersion` configurable
5. Helm lint passes

### Story P0.4: Pi Runtime StatefulSet Template
**Goal**: Kubernetes manifest for pi agent pods
**DoD**:
1. New template: `charts/kubesynapse/templates/agent-statefulset-pi.yaml`
2. Uses same PVC/storage patterns as OpenCode runtime
3. Mounts extensions from ConfigMap or inline
4. Sets `PI_CODING_AGENT_DIR` env var to PVC path
5. Readiness probe: TCP check on pi's stdin/stdout (or HTTP health sidecar)
6. Liveness probe: process existence check
7. `helm template` renders without errors

---

## Phase 1: Operator Support — Pi Runtime Kind (8h) ✅

### Story P1.1: Pi Runtime Manifest Builder
**Goal**: Operator can create pi agent pods just like it creates OpenCode pods
**DoD**:
1. New function `create_pi_runtime_manifest()` in `operator/builders/manifests.py`
2. Handles env vars: `PI_PROVIDER`, `PI_MODEL`, `PI_THINKING_LEVEL`, API key env vars
3. Mounts ConfigMap with KubeSynapse extensions
4. Mounts PVC for session persistence
5. Sets resource limits from AIAgent spec
6. Unit test verifies manifest structure

### Story P1.2: AIAgent CRD — Pi Runtime Field
**Goal**: AIAgent CRD supports `runtime.kind: "pi"` 
**DoD**:
1. `aiagent-crd.yaml`: `runtime.kind` enum updated to include `"pi"`
2. `runtime.pi` object with optional fields:
   - `model` (string, default: `anthropic/claude-sonnet-4-20250514`)
   - `thinkingLevel` (string: off|minimal|low|medium|high|xhigh)
   - `tools` (array of tool names to enable)
   - `extensions` (array of extension paths/ConfigMap refs)
   - `skills` (array of skill ConfigMap refs)
3. `required: [spec]` already present (existing)
4. CRD.yaml passes `kubectl apply --dry-run=server`
5. API gateway Pydantic models updated for pi runtime config

### Story P1.3: Agent Controller — Pi Runtime Reconciliation
**Goal**: When AIAgent has `runtime.kind: "pi"`, operator creates pi pod instead of OpenCode pod
**DoD**:
1. `agent_controller.py` detects `runtime.kind == "pi"`
2. Calls `create_pi_runtime_manifest()` instead of `create_opencode_runtime_manifest()`
3. Provisions API keys as env vars (same pattern as OpenCode)
4. Creates ConfigMap with KubeSynapse extensions from bundled files
5. Applies NetworkPolicy (same egress rules)
6. Applies PDB for pi StatefulSet
7. Logs which runtime was chosen
8. Unit test for pi runtime branch

### Story P1.4: Provider Configuration Injection
**Goal**: Pi agent gets correct LLM credentials
**DoD**:
1. Operator reads `KubeSynapse_LLM_API_KEYS` or provider-specific secrets
2. Maps to pi env vars: `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, etc.
3. Creates `auth.json` in pi's config directory (via init container or env)
4. Supports subscription-based auth (`/login`) if needed
5. Validates at least one provider is configured before pod start
6. Logs provider count (not keys)

---

## Phase 2: Python Wrapper — Pi RPC Client (6h) ✅

### Story P2.1: Pi RPC Client Module
**Goal**: Python module that communicates with pi RPC mode
**DoD**:
1. New file: `opencode-runtime/pi_client.py` (or `api-gateway/pi_client.py` — TBD based on architecture)
2. Class `PiRpcClient` with:
   - `start()` — spawns `pi --mode rpc` subprocess
   - `send_command(cmd: dict)` — writes JSON to stdin
   - `read_events()` — async generator yielding parsed JSON events
   - `close()` — graceful shutdown
3. Proper JSONL framing (LF-delimited, strips trailing \r)
4. Handles subprocess lifecycle (start, health check, graceful stop, force kill)
5. Timeout handling for commands
6. Reconnection logic if pi crashes

### Story P2.2: Pi RPC Command & Event Types
**Goal**: Typed Python models for all pi RPC protocol messages
**DoD**:
1. Pydantic models for all RPC commands:
   - `PiPromptCommand`, `PiSteerCommand`, `PiAbortCommand`, etc.
2. Pydantic models for all RPC events:
   - `PiMessageUpdateEvent`, `PiToolExecutionEvent`, `PiAgentEndEvent`, etc.
3. Pydantic models for all response types
4. Serialization/deserialization tested with sample JSON
5. Type-safe command building helpers

### Story P2.3: Pi Integration in Agent Runtime Wrapper
**Goal**: The existing `opencode-runtime` code can launch pi instead of OpenCode
**DoD**:
1. New `supervisor.py` branch: if `AGENT_RUNTIME_KIND=pi`, launch pi RPC instead of OpenCode
2. `invoke.py` adapted to use `PiRpcClient` instead of `OpenCodeClient`
3. Session ID mapping (pi session ID → KubeSynapse thread ID)
4. Streaming events proxied to API gateway WebSocket
5. Tool execution events mapped to KubeSynapse workflow step events
6. Error handling (pi crash, timeout, invalid JSON)
7. Integration test: start pi, send prompt, receive event, verify

---

## Phase 3: KubeSynapse Pi Extensions (10h) ✅

### Story P3.1: KubeSynapse A2A Extension
**Goal**: Pi agents can invoke other KubeSynapse agents via A2A
**DoD**:
1. `pi-runtime/extensions/KubeSynapse-a2a/index.ts`
2. Registers tool `KubeSynapse_a2a_invoke` with parameters:
   - `agent_name` (string) — target agent
   - `namespace` (string) — target namespace
   - `message` (string) — message to send
   - `wait_for_reply` (boolean) — synchronous or fire-and-forget
3. Tool handler calls KubeSynapse API gateway `/api/v1/a2a/send`
4. Returns agent response to LLM
5. Handles errors: agent not found, timeout, permission denied
6. Reads A2A policy from env vars (`A2A_ALLOWED_CALLERS`, etc.)
7. Respects `deliverAs: "steer"` for incoming A2A messages
8. Test: invoke agent, verify tool result in session

### Story P3.2: KubeSynapse MCP Extension
**Goal**: Pi agents can use MCP servers configured in KubeSynapse
**DoD**:
1. `pi-runtime/extensions/KubeSynapse-mcp/index.ts`
2. At startup, reads `OPENCODE_MCP_CONNECTIONS_JSON` env var (same format)
3. For each MCP connection, registers a tool or set of tools
4. Supports `sidecar`, `remote`, and `hub` transport types
5. Tool calls proxy to MCP server via HTTP
6. Handles MCP authentication (bearer tokens from secrets)
7. Handles MCP errors gracefully (don't crash agent)
8. Test: register MCP connection, LLM calls MCP tool, verify response

### Story P3.3: KubeSynapse Permissions Extension
**Goal**: Enforce KubeSynapse security policies within pi
**DoD**:
1. `pi-runtime/extensions/KubeSynapse-permissions/index.ts`
2. `tool_call` handler blocks dangerous operations:
   - `bash`: blocks `rm -rf /`, `sudo`, `chmod 777`, etc.
   - `write`/`edit`: blocks writes to `.env`, `credentials`, `secrets/`, `node_modules` (configurable)
3. Respects AIAgent.spec.securityContext (if `allowPrivilegeEscalation: false`, block sudo)
4. Read-only mode: if `--tools read,grep,find,ls`, auto-enable
5. Logs blocked operations with audit trail
6. Configurable via env vars: `KS_PERMISSION_LEVEL=strict|moderate|permissive`
7. Test: attempt dangerous command, verify blocked

### Story P3.4: KubeSynapse Artifacts Extension
**Goal**: Artifacts saved to KubeSynapse artifact system automatically
**DoD**:
1. `pi-runtime/extensions/KubeSynapse-artifacts/index.ts`
2. `tool_result` handler for `write` and `edit` tools:
   - Extracts file path, content
   - Posts to API gateway `/api/v1/artifacts` with workflow run metadata
3. `agent_end` handler: posts session summary as artifact
4. `artifact_path` from env var (`ARTIFACT_PATH`)
5. `journal_path` from env var (`ARTIFACT_JOURNAL_PATH`)
6. Handles artifact upload failures gracefully (don't block agent)
7. Test: write file, verify artifact created via API

### Story P3.5: KubeSynapse Observability Extension
**Goal**: Agent traces, metrics, and logs exported to KubeSynapse observability stack
**DoD**:
1. `pi-runtime/extensions/KubeSynapse-observability/index.ts`
2. `agent_start` handler: starts trace span (via OpenTelemetry or custom)
3. `turn_start`/`turn_end`: records turn duration
4. `tool_execution_start`/`tool_execution_end`: records tool latency
5. `message_end` (assistant): records token usage from `usage` field
6. Exports metrics via stdout structured JSON (consumed by Fluentd/Fluent Bit)
7. Correlates with KubeSynapse workflow run ID from env var
8. Test: run agent, verify structured logs contain trace_id

---

## Phase 4: API Gateway Integration (6h) ✅

### Story P4.1: Pi Runtime API Endpoints
**Goal**: API gateway serves pi-specific endpoints for agent management
**DoD**:
1. `GET /api/v1/agents/{name}/pi/sessions` — list pi sessions for agent
2. `GET /api/v1/agents/{name}/pi/sessions/{id}` — get session details
3. `POST /api/v1/agents/{name}/pi/sessions/{id}/fork` — fork session
4. `GET /api/v1/agents/{name}/pi/sessions/{id}/messages` — get session messages
5. `POST /api/v1/agents/{name}/pi/sessions/{id}/compact` — trigger compaction
6. All endpoints documented in OpenAPI schema
7. Rate limiting applied
8. Auth middleware checks agent ownership

### Story P4.2: Pi Session State in Database
**Goal**: Pi session metadata stored in PostgreSQL for UI listing
**DoD**:
1. New table `pi_sessions` or extend `agent_sessions`:
   - `session_id` (UUID)
   - `agent_name` (FK to agents)
   - `session_file_path` (string)
   - `display_name` (string, from pi session_name)
   - `message_count` (int)
   - `token_usage` (JSON: input, output, cache)
   - `cost` (float)
   - `cwd` (string)
   - `parent_session_id` (nullable FK)
2. Session list API returns summary from DB
3. Session CRUD operations synced from pi events
4. Migration file for new table

### Story P4.3: Web UI Pi Session Browsing
**Goal**: Users can see pi sessions in the Web UI
**DoD**:
1. New "Sessions" tab in Agent detail view (or extend existing)
2. Lists pi sessions with name, date, message count, token usage
3. Clicking a session shows conversation (messages rendered from JSONL)
4. Fork/resume buttons for branching workflows
5. Session export/download button
6. Responsive design (mobile + desktop)
7. Accessibility: keyboard navigable, ARIA labels

---

## Phase 5: Workflow & Eval Integration (6h) ✅

### Story P5.1: Pi Workflow Step Executor
**Goal**: Workflow steps can target pi agents
**DoD**:
1. `worker.py` detects agent runtime kind ("pi" vs "opencode")
2. For pi agents: sends `prompt` RPC command instead of HTTP to OpenCode
3. Waits for `agent_end` event (step completion)
4. Captures:
   - Step output (last assistant message text)
   - Token usage (from `agent_end` events)
   - Tool results (for artifact extraction)
5. Handles step timeout via `abort` RPC command
6. Handles `steer` and `follow_up` for multi-step workflows
7. Regression test: existing OpenCode workflows still work
8. Integration test: pi workflow completes successfully

### Story P5.2: Pi Eval Runner
**Goal**: AIEval can run test suites against pi agents
**DoD**:
1. `eval_controller.py` / `worker.py` supports pi runtime for evals
2. For each test case: new_session → prompt → collect result → compare
3. Captures pass/fail with reasoning
4. Eval report includes pi session ID for debugging
5. Works with the same eval CRD format
6. Test: eval runs against pi agent, produces report

### Story P5.3: Pi Runtime Comparison Benchmark
**Goal**: Quantified performance comparison between pi and OpenCode
**DoD**:
1. Benchmark harness that runs same workflow on both runtimes
2. Measures:
   - Agent response latency (time to first token)
   - Total workflow completion time
   - Token usage efficiency
   - Error rate
   - Memory usage
   - Session file size growth
3. Results saved to `docs/pi-vs-opencode-benchmark.md`
4. Runs in CI on every pi runtime change
5. Regression alerts if pi performance degrades >10%

---

## Phase 6: Production Hardening (6h) ✅

### Story P6.1: Pi Runtime Resource Tuning
**Goal**: Pi agent pods have correct resource limits
**DoD**:
1. Benchmark pi memory usage under load:
   - Idle: ~150 MB
   - Active (streaming): ~300 MB
   - Session compaction: ~500 MB peak
2. Set resource requests: CPU 200m, Memory 256Mi
3. Set resource limits: CPU 2, Memory 1Gi
4. HPA for scalable pi agent deployments
5. PDB: maxUnavailable: 1 for HA
6. Resource values documented in Helm values.yaml

### Story P6.2: Pi Health Probes
**Goal**: Kubernetes knows when pi agent is healthy
**DoD**:
1. Readiness probe: pi RPC `get_state` command → success = ready
   - Implementation: small Python sidecar that sends `get_state` and checks response
   - OR: HTTP health endpoint via pi extension
2. Liveness probe: process existence check (pid 1)
3. Startup probe: initial delay 30s, period 10s, failureThreshold 6
4. Probe configuration documented

### Story P6.3: Pi Graceful Shutdown
**Goal**: Pi sessions saved cleanly on pod termination
**DoD**:
1. SIGTERM handler in pi entrypoint:
   - If session is active: send `abort` RPC command
   - Wait for `agent_end` event (with timeout)
   - Pi auto-saves session on exit
2. `terminationGracePeriodSeconds: 60` for pi StatefulSet
3. Extension `session_shutdown` handler saves KubeSynapse state
4. Test: kill pod during active prompt, verify session recoverable

### Story P6.4: Pi Security Scan
**Goal**: Pi runtime image passes security checks
**DoD**:
1. Trivy scan on `kubesynapse-pi-rt` image: 0 CRITICAL/HIGH
2. Bandit scan on Python pi_client code: 0 HIGH
3. `npm audit` on pi-runtime package.json: 0 CRITICAL
4. Node.js version pinned (no `:latest`)
5. All npm packages version-pinned in package-lock.json
6. Security scan in CI/CD pipeline

### Story P6.5: Pi Runtime Documentation
**Goal**: Users know how to use pi runtime
**DoD**:
1. `docs/pi-runtime.md`: Getting started guide
2. `docs/pi-extensions.md`: KubeSynapse extensions reference
3. AIAgent CRD examples with `runtime.kind: pi`
4. Comparison table: pi vs opencode (use cases)
5. Migration guide: switching from opencode to pi
6. FAQ: common issues and troubleshooting
7. Architecture diagram showing pi in KubeSynapse stack

---

## Risk Analysis & Mitigations

| Risk | Impact | Probability | Mitigation |
|------|--------|-------------|------------|
| Node.js memory leaks in long-running pi sessions | Session grows until OOM | Medium | Auto-compaction enabled, pod memory limits, session rotation |
| Pi RPC protocol changes break integration | Agent pods fail to communicate | Medium | Pin pi version, integration tests in CI |
| Pi npm package supply chain attack | Malicious code in agent pods | Low | Version pinning, npm audit, internal npm mirror/verdaccio |
| Pi process crash loses unsaved session | User loses conversation | Low | Auto-save on every turn, PVC persistence |
| Extension incompatibility between pi versions | Agent fails to start | Medium | Extension API compatibility tests, pin pi version |
| LLM provider API changes | Agent prompt fails | Low | pi upstream handles provider changes, auto-retry built-in |
| A2A latency via HTTP → slower than OpenCode's in-process A2A | Workflow steps slower | Medium | Cache A2A responses, use steer/follow_up for async |
| Pi session JSONL grows too large on long-lived agents | Disk usage, slow loading | Low | Compaction auto-summarizes, log rotation |
| Multiple pi processes competing for session file | Data corruption | High | **CRITICAL**: Lock file or single-process guarantee per pod |
| pi --mode rpc stdin/stdout buffering | Event delay/loss | High | **CRITICAL**: Unbuffered stdin/stdout, flush after each write |

---

## Dependency Graph

```
Phase 0 (Foundation)
  ├── P0.1 (Dockerfile)
  ├── P0.2 (Extensions scaffold)
  ├── P0.3 (Helm values)
  └── P0.4 (StatefulSet template)
      │
Phase 1 (Operator)
  ├── P1.1 (Manifest builder) ← depends on P0.1, P0.2
  ├── P1.2 (CRD update) ← independent
  ├── P1.3 (Controller) ← depends on P1.1, P1.2
  └── P1.4 (Provider config) ← depends on P1.1
      │
Phase 2 (Python RPC Client)
  ├── P2.1 (RPC Client class) ← independent (can start early)
  ├── P2.2 (Type models) ← independent
  └── P2.3 (Runtime integration) ← depends on P2.1, P2.2, P1.3
      │
Phase 3 (Pi Extensions)
  ├── P3.1 (A2A) ← depends on Phase 0, 1
  ├── P3.2 (MCP) ← independent
  ├── P3.3 (Permissions) ← independent
  ├── P3.4 (Artifacts) ← depends on API gateway
  └── P3.5 (Observability) ← independent
      │
Phase 4 (API Gateway)
  ├── P4.1 (Endpoints) ← depends on P2.3
  ├── P4.2 (DB schema) ← independent
  └── P4.3 (Web UI) ← depends on P4.1, P4.2
      │
Phase 5 (Workflow & Eval)
  ├── P5.1 (Workflow step executor) ← depends on P2.3
  ├── P5.2 (Eval runner) ← depends on P5.1
  └── P5.3 (Benchmark) ← depends on P5.1
      │
Phase 6 (Production)
  ├── P6.1 (Resource tuning) ← depends on P5.3
  ├── P6.2 (Health probes) ← depends on Phase 0
  ├── P6.3 (Graceful shutdown) ← depends on P2.3
  ├── P6.4 (Security scan) ← depends on P0.1
  └── P6.5 (Documentation) ← depends on all above
```

---

## Execution Order (Optimal)

### Batch 1 (Parallel — can start immediately)
- P0.1: Pi Runtime Dockerfile
- P0.2: Extensions Scaffold
- P1.2: CRD Update
- P2.1: Pi RPC Client (Python)
- P2.2: RPC Type Models
- P4.2: Database Schema

### Batch 2 (After Batch 1)
- P0.3: Helm Values
- P0.4: StatefulSet Template
- P1.1: Manifest Builder
- P3.2: MCP Extension
- P3.3: Permissions Extension
- P3.5: Observability Extension

### Batch 3 (After Batch 2)
- P1.3: Controller Integration
- P1.4: Provider Configuration
- P2.3: Runtime Wrapper Integration
- P3.1: A2A Extension
- P3.4: Artifacts Extension

### Batch 4 (After Batch 3)
- P4.1: API Endpoints
- P4.3: Web UI
- P5.1: Workflow Step Executor
- P6.1: Resource Tuning
- P6.2: Health Probes
- P6.3: Graceful Shutdown

### Batch 5 (After Batch 4)
- P5.2: Eval Runner
- P5.3: Benchmark
- P6.4: Security Scan
- P6.5: Documentation

---

## Go/No-Go Criteria (Before Phase 1)

- [x] pi-mono knowledge base completed
- [x] pi RPC mode tested manually: `pi --mode rpc` → send `{"type":"prompt","message":"Hello"}` → verify `message_update` events
- [x] pi Docker image builds and starts in Kind cluster
- [x] RPC client Python prototype works (P2.1 skeleton)
- [x] Decision: pi as REPLACEMENT or ALTERNATIVE? (Recommend: alternative, opt-in via `runtime.kind: pi`)
- [x] Team/architecture review of this plan

---

## Success Metrics

- Pi runtime deploys in < 5 minutes after `kubectl apply`
- Agent prompt response latency within 10% of OpenCode baseline
- 0 CRITICAL/HIGH security vulnerabilities
- Session persistence works across pod restarts
- At least 2 KubeSynapse extensions working (A2A + Permissions minimum)
- Existing OpenCode agents continue working unchanged
- Workflow execution on pi runtime passes integration test
- Documentation allows a new user to configure pi runtime without assistance
